"""SetFit may train on the owner's rows or on fixtures — nobody else's.

``test_training_is_single_user.py`` pins that a training run reads exactly one
user. That is necessary and not sufficient: a run that pools nothing and trains
on one stranger's mailbox satisfies it perfectly, because whoever called passed
that stranger's ``user_id``. Applied reads mail under Gmail's restricted
``gmail.readonly`` scope, whose user-data policy allows training only a model
personalized to a single end user — so *whose* mailbox a model may see has to
be a configured fact, not a caller's argument.

The gate under test, ``SetFitClassifier._assert_training_allowed``, is layered
on top of ``_assert_single_user_corpus`` and refuses unless:

* the requested ``user_id`` appears in ``JOBTRACKER_TRAINING_ALLOWED_USER_IDS``
  (``settings.training_allowed_user_ids``), or
* every row in the corpus carries a source in ``SYNTHETIC_TRAINING_SOURCES``.

Default-deny: the list is empty unless an operator sets it, nothing in the
hosted deployment does, and so the deployed app refuses everyone. These tests
exercise the refusing branch directly — deleting the gate turns them red, which
was performed and recorded rather than assumed.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from jobtracker.classifier.setfit_model import (
    SYNTHETIC_TRAINING_SOURCES,
    CrossUserTrainingError,
    SetFitClassifier,
    TrainingNotAllowedError,
    TrainingPolicyError,
)
from jobtracker.database.models import TrainingData


def _config():
    """The *live* ``jobtracker.config`` module.

    Never `from jobtracker.config import Settings`: other tests in this suite
    call ``importlib.reload`` on that module, which rebuilds ``Settings``,
    ``TrainingAllowedUserIdsError`` and the ``settings`` singleton as new
    objects while a name imported here still points at the old ones. The
    symptom is a `pytest.raises` that does not catch an exception the traceback
    plainly shows being raised, and a monkeypatched allowlist the code under
    test cannot see. Both were observed here before this helper existed.
    """

    import importlib

    return importlib.import_module("jobtracker.config")


OWNER = uuid.UUID("11111111-1111-1111-1111-111111111111")
STRANGER = uuid.UUID("22222222-2222-2222-2222-222222222222")


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def training_db(monkeypatch: pytest.MonkeyPatch):
    """In-memory DB wired in as ``jobtracker.database.get_session``.

    ``setfit_model`` imports ``get_session`` inside the method body, so
    patching the attribute on the package is picked up by late binding.
    """

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @asynccontextmanager
    async def _fake_get_session() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    import jobtracker.database as database_pkg

    monkeypatch.setattr(database_pkg, "get_session", _fake_get_session)

    async def _seed(user_id: uuid.UUID, label: str, count: int, source: str) -> None:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            for i in range(count):
                session.add(
                    TrainingData(
                        user_id=user_id,
                        subject=f"{label} subject {source}-{i}",
                        body_text=f"{label} body {source}-{i}",
                        label=label,
                        source=source,
                    )
                )
            await session.commit()

    yield _seed


@pytest.fixture
def allowlist(monkeypatch: pytest.MonkeyPatch):
    """Set ``settings.training_allowed_user_ids`` for the duration of a test.

    Defaults to empty on entry so no test inherits a permission it did not ask
    for — the state the hosted app is in.
    """

    def _set(*user_ids: uuid.UUID) -> None:
        monkeypatch.setattr(
            _config().settings, "training_allowed_user_ids", list(user_ids)
        )

    _set()
    return _set


def _block_real_training(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """Replace the actual fit with a recorder.

    Returns the list it appends to, so a test can assert training *did* start
    without downloading a sentence-transformer. Without this, a regression that
    opens the gate does not merely fail an assertion — it starts a real fit on
    the fixture rows.
    """

    calls: list[tuple] = []

    def _record(_self, texts, labels):  # noqa: ANN001 - test double
        calls.append((list(texts), list(labels)))

    monkeypatch.setattr(SetFitClassifier, "_train_sync", _record)
    return calls


def _rows(user_id: uuid.UUID, source: str, count: int = 6) -> list[TrainingData]:
    return [
        TrainingData(
            user_id=user_id,
            subject=f"applied subject {i}",
            body_text=f"applied body {i}",
            label="applied",
            source=source,
        )
        for i in range(count)
    ]


def _loader_returning(*rows: TrainingData):
    async def _load(_self, _session, *, user_id):  # noqa: ANN001 - test double
        return list(rows)

    return _load


# =============================================================================
# 1. Default-deny — an unset variable refuses everyone
# =============================================================================


async def test_unset_allowlist_refuses_the_owner(training_db, allowlist) -> None:
    """Nothing configured means nobody trains, owner included.

    This is the hosted app's state: no deployment sets the variable, so the
    deployed classifier cannot train on anybody. A misconfiguration lands
    here, not on the permissive side.
    """

    await training_db(OWNER, "applied", 6, "user_correction")

    classifier = SetFitClassifier()
    with pytest.raises(TrainingNotAllowedError) as excinfo:
        await classifier._get_training_data(user_id=OWNER)

    assert str(OWNER) in str(excinfo.value)


async def test_unset_allowlist_refuses_a_stranger(training_db, allowlist) -> None:
    await training_db(STRANGER, "applied", 6, "user_correction")

    classifier = SetFitClassifier()
    with pytest.raises(TrainingNotAllowedError):
        await classifier._get_training_data(user_id=STRANGER)


async def test_default_settings_allowlist_is_empty() -> None:
    """The field's own default, read off a fresh Settings — not the singleton.

    A default that is only empty because this process happens to have no env
    var set would be a check that cannot fail.
    """

    assert _config().Settings(_env_file=None).training_allowed_user_ids == []


# =============================================================================
# 2. Allowlisted trains; anyone else is refused
# =============================================================================


async def test_allowlisted_user_trains(training_db, allowlist) -> None:
    allowlist(OWNER)
    await training_db(OWNER, "applied", 6, "user_correction")

    classifier = SetFitClassifier()
    texts, labels = await classifier._get_training_data(user_id=OWNER)

    assert len(texts) == 6
    assert set(labels) == {"applied"}


async def test_a_user_not_on_the_list_is_refused_even_when_someone_is(
    training_db, allowlist
) -> None:
    """Listing the owner does not license a run aimed at anyone else."""

    allowlist(OWNER)
    await training_db(STRANGER, "applied", 6, "user_correction")

    classifier = SetFitClassifier()
    with pytest.raises(TrainingNotAllowedError) as excinfo:
        await classifier._get_training_data(user_id=STRANGER)

    message = str(excinfo.value)
    assert str(STRANGER) in message
    # The refusal has to say how to allow it, by name.
    assert "JOBTRACKER_TRAINING_ALLOWED_USER_IDS" in message
    # ...and why, so an assessor reading a log knows this was policy.
    assert "gmail.readonly" in message


async def test_refusal_reaches_the_caller_of_train(
    training_db, allowlist, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``train()`` swallows exceptions by design. Not this one.

    Pins the ``except TrainingPolicyError: raise`` clause. Were the refusal a
    plain ``RuntimeError`` it would land in the catch-all below that clause,
    be logged, and ``POST /classify/retrain`` would report success.
    """

    calls = _block_real_training(monkeypatch)
    await training_db(STRANGER, "applied", 6, "user_correction")

    classifier = SetFitClassifier()
    with pytest.raises(TrainingNotAllowedError):
        await classifier.train(user_id=STRANGER)

    assert calls == [], "no fit may start on a refused corpus"
    # The latch must still be released.
    assert classifier.is_training() is False


async def test_the_refusal_is_a_training_policy_error() -> None:
    """The base class is what ``train()`` re-raises on; keep the hierarchy."""

    assert issubclass(TrainingNotAllowedError, TrainingPolicyError)
    assert issubclass(CrossUserTrainingError, TrainingPolicyError)


# =============================================================================
# 3. Synthetic corpora stay trainable — fixtures and the local dev loop
# =============================================================================


@pytest.mark.parametrize("source", sorted(SYNTHETIC_TRAINING_SOURCES))
async def test_a_wholly_synthetic_corpus_trains_without_the_allowlist(
    training_db, allowlist, source: str
) -> None:
    await training_db(STRANGER, "applied", 6, source)

    classifier = SetFitClassifier()
    texts, labels = await classifier._get_training_data(user_id=STRANGER)

    assert len(texts) == 6
    assert set(labels) == {"applied"}


async def test_a_synthetic_corpus_reaches_the_fit(
    training_db, allowlist, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The permissive branch is not vacuous — ``train()`` really proceeds."""

    calls = _block_real_training(monkeypatch)
    for label in ("applied", "rejection", "interview"):
        await training_db(OWNER, label, 6, "mock_seed_v3")

    classifier = SetFitClassifier()
    monkeypatch.setattr(SetFitClassifier, "_load_model", lambda _self: None)
    await classifier.train(user_id=OWNER)

    assert len(calls) == 1
    assert len(calls[0][0]) == 18


async def test_one_real_correction_poisons_a_synthetic_corpus(
    allowlist, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All, not any. A single ``user_correction`` is real mail.

    Otherwise anyone could be trained on by seeding one fixture row beside
    their corrections.
    """

    monkeypatch.setattr(
        SetFitClassifier,
        "_load_training_rows",
        _loader_returning(
            *_rows(STRANGER, "mock_seed_v3", 20),
            *_rows(STRANGER, "user_correction", 1),
        ),
    )

    classifier = SetFitClassifier()
    with pytest.raises(TrainingNotAllowedError) as excinfo:
        await classifier._get_training_data(user_id=STRANGER)

    assert "user_correction" in str(excinfo.value)


async def test_an_unknown_source_is_not_synthetic(
    allowlist, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``import_jsonl_training_data.py --source`` takes whatever was typed.

    An unrecognised value must fail closed rather than be assumed harmless.
    """

    monkeypatch.setattr(
        SetFitClassifier,
        "_load_training_rows",
        _loader_returning(*_rows(STRANGER, "whatever_the_operator_typed")),
    )

    classifier = SetFitClassifier()
    with pytest.raises(TrainingNotAllowedError):
        await classifier._get_training_data(user_id=STRANGER)


async def test_bulk_import_is_not_synthetic(
    allowlist, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It is in ``SOURCE_PRIORITY`` but nothing writes it — so it is unknown."""

    assert "bulk_import" not in SYNTHETIC_TRAINING_SOURCES

    monkeypatch.setattr(
        SetFitClassifier,
        "_load_training_rows",
        _loader_returning(*_rows(STRANGER, "bulk_import")),
    )

    classifier = SetFitClassifier()
    with pytest.raises(TrainingNotAllowedError):
        await classifier._get_training_data(user_id=STRANGER)


async def test_an_empty_corpus_is_refused(allowlist, monkeypatch: pytest.MonkeyPatch) -> None:
    """``all()`` of nothing is ``True``; a gate that opens on no evidence is not a gate."""

    monkeypatch.setattr(SetFitClassifier, "_load_training_rows", _loader_returning())

    classifier = SetFitClassifier()
    with pytest.raises(TrainingNotAllowedError):
        await classifier._get_training_data(user_id=STRANGER)


# =============================================================================
# 4. Layered on top of the single-user guard, not instead of it
# =============================================================================


async def test_a_cross_user_corpus_still_raises_the_cross_user_error(
    allowlist, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Allowlisting the requested user does not license pooling.

    ``_assert_single_user_corpus`` runs first and stays the thing that catches
    a dropped ``WHERE`` clause. The two guards are mutual defence; this pins
    that the new one did not replace the old one.
    """

    allowlist(OWNER, STRANGER)
    monkeypatch.setattr(
        SetFitClassifier,
        "_load_training_rows",
        _loader_returning(*_rows(OWNER, "user_correction", 3), *_rows(STRANGER, "user_correction", 3)),
    )

    classifier = SetFitClassifier()
    with pytest.raises(CrossUserTrainingError):
        await classifier._get_training_data(user_id=OWNER)


async def test_a_synthetic_corpus_spanning_users_is_still_refused(
    allowlist, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The synthetic exemption does not reach past the single-user guard."""

    monkeypatch.setattr(
        SetFitClassifier,
        "_load_training_rows",
        _loader_returning(*_rows(OWNER, "mock_seed_v3", 3), *_rows(STRANGER, "mock_seed_v3", 3)),
    )

    classifier = SetFitClassifier()
    with pytest.raises(CrossUserTrainingError):
        await classifier._get_training_data(user_id=OWNER)


# =============================================================================
# 5. The env var parses into real UUIDs, or the process stops
# =============================================================================


def test_the_env_var_parses_a_comma_separated_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "JOBTRACKER_TRAINING_ALLOWED_USER_IDS", f" {OWNER} , {STRANGER} "
    )

    parsed = _config().Settings(_env_file=None).training_allowed_user_ids

    assert parsed == [OWNER, STRANGER]
    # Real UUIDs, not strings — ``user_id in allowlist`` compares by identity
    # of type as well as value.
    assert all(isinstance(item, uuid.UUID) for item in parsed)


def test_a_malformed_entry_stops_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """And is not a ``ValidationError``, which would echo the whole variable."""

    monkeypatch.setenv(
        "JOBTRACKER_TRAINING_ALLOWED_USER_IDS", f"{OWNER},not-a-uuid-at-all"
    )

    with pytest.raises(_config().TrainingAllowedUserIdsError) as excinfo:
        _config().Settings(_env_file=None)

    message = str(excinfo.value)
    assert "#2 of 2" in message
    # The value must not reach the logs.
    assert "not-a-uuid-at-all" not in message
    assert not issubclass(_config().TrainingAllowedUserIdsError, ValueError)
    assert not isinstance(excinfo.value, ValidationError)
