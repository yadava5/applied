"""SetFit training must never pool one user's corrections with another's.

Applied reads mail through Gmail's **restricted** ``gmail.readonly`` scope.
Google's Workspace API user-data policy allows data obtained that way to feed
"a machine learning or artificial intelligence model" only where the model is
*personalized to that one end user*, with no co-mingling across users. A batch
trainer pointed at production Postgres runs on an admin connection, which RLS
does not constrain, so an unfiltered ``select(TrainingData)`` there would build
exactly the prohibited pooled model — and restricted-scope verification (the
thing that lifts the 100-user OAuth test cap) is granted against this policy.

These tests pin two independent defences:

1. The corpus read is **scoped** — ``user_id`` is a required keyword argument
   and becomes a ``WHERE`` clause.
2. The corpus is **checked after loading**, derived from the rows themselves
   rather than from a caller's promise, so a future refactor that deletes the
   ``WHERE`` as "redundant" fails loudly instead of silently pooling.

Defence 2 is unreachable while defence 1 is intact — that is the point of belt
and braces. It is exercised here by substituting the row loader, which is what
a dropped filter looks like from ``_get_training_data``'s side.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from jobtracker.classifier.setfit_model import (
    CrossUserTrainingError,
    SetFitClassifier,
    resolve_training_user_id,
)
from jobtracker.database.models import LOCAL_USER_ID, TrainingData

USER_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
async def training_db(monkeypatch: pytest.MonkeyPatch):
    """In-memory DB wired in as ``jobtracker.database.get_session``.

    ``setfit_model`` imports ``get_session`` *inside* the method body, so
    patching the attribute on the package is picked up by late binding.
    """

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    @asynccontextmanager
    async def _fake_get_session() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    import jobtracker.database as database_pkg

    monkeypatch.setattr(database_pkg, "get_session", _fake_get_session)

    async def _seed(user_id: uuid.UUID, label: str, count: int, source: str = "user_correction"):
        async with AsyncSession(engine, expire_on_commit=False) as session:
            for i in range(count):
                session.add(
                    TrainingData(
                        user_id=user_id,
                        subject=f"{label} subject {user_id.hex[:4]}-{i}",
                        body_text=f"{label} body {user_id.hex[:4]}-{i}",
                        label=label,
                        source=source,
                    )
                )
            await session.commit()

    yield _seed

    await engine.dispose()


def _loader_returning(*rows: TrainingData):
    """A ``_load_training_rows`` stand-in — i.e. a corpus read with no filter."""

    async def _load(_self, _session, *, user_id):  # noqa: ANN001 - test double
        return list(rows)

    return _load


def _block_real_training(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make an actual SetFit fit impossible.

    Without this, a regression that removes the guard does not merely fail the
    assertion below — it downloads a sentence-transformer and starts training
    on the fixture rows. Keep the failure fast, offline, and about the guard.
    """

    def _never(*_args, **_kwargs):  # pragma: no cover - must never run
        raise AssertionError("SetFit training must not start on a cross-user corpus")

    monkeypatch.setattr(SetFitClassifier, "_train_sync", _never)


@pytest.fixture
def allowlisted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put every user this file trains on onto the training allowlist.

    Since the owner-only gate landed, a corpus of ``user_correction`` rows is
    refused unless its user is named in
    ``JOBTRACKER_TRAINING_ALLOWED_USER_IDS`` — default-deny. These tests are
    about the *scoping* guards, so they hand themselves the permission and
    leave the allowlist's own behaviour to
    ``test_training_is_owner_only.py``. Requesting this fixture in a test that
    expects a refusal would mask it, so the refusal tests below do not.
    """

    from jobtracker.config import settings

    monkeypatch.setattr(
        settings,
        "training_allowed_user_ids",
        [USER_A, USER_B, LOCAL_USER_ID],
    )


def _row(user_id: uuid.UUID, label: str, i: int = 0) -> TrainingData:
    return TrainingData(
        user_id=user_id,
        subject=f"{label} subject {i}",
        body_text=f"{label} body {i}",
        label=label,
        source="user_correction",
    )


# =============================================================================
# 1. The corpus read is scoped to one user
# =============================================================================


async def test_get_training_data_reads_only_the_requested_user(
    training_db, allowlisted
) -> None:
    """Two users in the table; a training run sees exactly one of them.

    This is the test that turns red (with ``CrossUserTrainingError``) if the
    ``WHERE user_id = ...`` is ever removed — the mutation used to prove the
    post-load assertion actually bites.
    """

    await training_db(USER_A, "applied", 6)
    await training_db(USER_B, "rejection", 6)

    classifier = SetFitClassifier()
    texts, labels = await classifier._get_training_data(user_id=USER_A)

    assert set(labels) == {"applied"}
    assert len(texts) == 6
    assert all(USER_B.hex[:4] not in text for text in texts)


async def test_desktop_single_user_corpus_is_unchanged(training_db, allowlisted) -> None:
    """Desktop is single-user (the ``LOCAL_USER_ID`` sentinel) and keeps working."""

    for label in ("applied", "rejection", "interview"):
        await training_db(LOCAL_USER_ID, label, 6)

    classifier = SetFitClassifier()
    texts, labels = await classifier._get_training_data(user_id=LOCAL_USER_ID)

    assert len(texts) == 18
    assert sorted(set(labels)) == ["applied", "interview", "rejection"]


async def test_resolve_training_user_id_defaults_to_the_desktop_sentinel() -> None:
    """With no authenticated identity bound, training scopes to the sentinel."""

    assert resolve_training_user_id() == LOCAL_USER_ID


async def test_resolve_training_user_id_follows_the_bound_identity() -> None:
    from jobtracker.database.connection import user_id_scope

    with user_id_scope(USER_B):
        assert resolve_training_user_id() == USER_B
    assert resolve_training_user_id() == LOCAL_USER_ID


async def test_should_retrain_counts_only_the_requested_user(training_db) -> None:
    """One prolific user must not push another user's model over the threshold."""

    # USER_B alone clears every gate: 45 examples across 3 categories.
    for label in ("applied", "rejection", "interview"):
        await training_db(USER_B, label, 15)
    # USER_A has nowhere near enough.
    await training_db(USER_A, "applied", 3)

    classifier = SetFitClassifier()
    assert await classifier.should_retrain(user_id=USER_A) is False
    assert await classifier.should_retrain(user_id=USER_B) is True


# =============================================================================
# 2. The corpus is checked after loading, derived from the rows
# =============================================================================


async def test_corpus_spanning_two_users_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        SetFitClassifier,
        "_load_training_rows",
        _loader_returning(_row(USER_A, "applied"), _row(USER_B, "rejection")),
    )

    classifier = SetFitClassifier()
    with pytest.raises(CrossUserTrainingError) as excinfo:
        await classifier._get_training_data(user_id=USER_A)

    message = str(excinfo.value)
    assert str(USER_B) in message
    # The message has to explain *why*, not merely that it refused.
    assert "gmail.readonly" in message
    assert "personalized" in message


async def test_corpus_from_the_wrong_single_user_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One distinct ``user_id`` is not enough — it must be the requested one."""

    monkeypatch.setattr(
        SetFitClassifier,
        "_load_training_rows",
        _loader_returning(_row(USER_B, "applied"), _row(USER_B, "rejection")),
    )

    classifier = SetFitClassifier()
    with pytest.raises(CrossUserTrainingError):
        await classifier._get_training_data(user_id=USER_A)


async def test_foreign_rows_are_caught_even_when_every_one_is_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``needs_review`` rows are skipped for training but still count as evidence.

    Otherwise a foreign user whose rows are all ``needs_review`` walks past the
    assertion because nothing they own reaches the corpus lists.
    """

    monkeypatch.setattr(
        SetFitClassifier,
        "_load_training_rows",
        _loader_returning(_row(USER_A, "applied"), _row(USER_B, "needs_review")),
    )

    classifier = SetFitClassifier()
    with pytest.raises(CrossUserTrainingError):
        await classifier._get_training_data(user_id=USER_A)


# =============================================================================
# 3. It fails loudly — the error reaches the caller, it is not logged away
# =============================================================================


async def test_cross_user_error_propagates_out_of_train(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``train()`` swallows exceptions by design; this one must not be swallowed."""

    _block_real_training(monkeypatch)
    monkeypatch.setattr(
        SetFitClassifier,
        "_load_training_rows",
        _loader_returning(_row(USER_A, "applied"), _row(USER_B, "rejection")),
    )

    classifier = SetFitClassifier()
    with pytest.raises(CrossUserTrainingError):
        await classifier.train(user_id=USER_A)

    # The training latch must still be released.
    assert classifier.is_training() is False


async def test_cross_user_error_propagates_out_of_hybrid_retrain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public trigger (`ml_cycle.sh --retrain`, `POST /classify/retrain`)."""

    from jobtracker.classifier.hybrid import HybridClassifier

    _block_real_training(monkeypatch)
    monkeypatch.setattr(
        SetFitClassifier,
        "_load_training_rows",
        _loader_returning(_row(USER_A, "applied"), _row(USER_B, "rejection")),
    )

    hybrid = HybridClassifier()
    hybrid._setfit_instance = SetFitClassifier()

    with pytest.raises(CrossUserTrainingError):
        await hybrid.retrain_setfit(user_id=USER_A)


# =============================================================================
# 4. Omitting the scope is a call-time failure, not a full-table read
# =============================================================================


def test_training_entry_points_cannot_be_called_without_a_user_id() -> None:
    from jobtracker.classifier.hybrid import HybridClassifier

    classifier = SetFitClassifier()
    hybrid = HybridClassifier()

    with pytest.raises(TypeError):
        classifier.train()
    with pytest.raises(TypeError):
        classifier.should_retrain()
    with pytest.raises(TypeError):
        classifier._get_training_data()
    with pytest.raises(TypeError):
        hybrid.retrain_setfit()
