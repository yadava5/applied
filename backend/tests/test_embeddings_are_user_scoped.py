"""Classifier layer 2 (embeddings) must never read another user's examples.

``email_embeddings`` carries a ``user_id`` column and is one of the eight
tables under RLS (see ``alembic/versions/a8d4ec5fba26``), so the row store is
per-tenant by construction. The *reader* was not: ``load_known_embeddings``
issued a bare ``select(EmailEmbedding)`` and every stored example — whoever
owned it — became a candidate neighbour for whoever happened to be asking.

Two independent leaks live in that one layer, and only one of them is
something RLS could have caught:

1. **The query.** On Postgres a policy would have clipped the unscoped
   ``SELECT`` back to the caller. On SQLite (desktop, and every test in this
   repo) there is no RLS at all, so the ``WHERE`` is the only defence. Same
   reasoning as ``test_training_is_single_user.py``, which says it outright:
   "RLS is additive security, not the primary check."

2. **The cache.** ``EmbeddingsClassifier`` is a process-global singleton
   (``get_embeddings_classifier``) holding ``_known_embeddings`` behind a
   boolean ``_loaded`` flag. The first request to touch it populated that
   list; every later request in the same process short-circuited on
   ``_loaded`` and reused it. No query runs on the second request, so **no
   policy is ever evaluated** — RLS cannot see this one, on any backend. The
   cache must therefore be keyed by owner, not by "have we loaded yet".

The writes matter as much as the reads: ``add_example`` built an
``EmailEmbedding`` with no ``user_id``, so every cloud correction landed on
the ``LOCAL_USER_ID`` sentinel. Scoping reads without stamping writes would
turn a leak into silent data loss (real users would match nothing), so both
directions are pinned here.

The e5-small-v2 model is stubbed throughout — these tests are about ownership,
and must not download 80 MB to say so.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from jobtracker.classifier.embeddings import (
    EmbeddingModel,
    EmbeddingsClassifier,
    embedding_to_bytes,
)
from jobtracker.database.connection import user_id_scope
from jobtracker.database.models import LOCAL_USER_ID, EmailCategory, EmailEmbedding

USER_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


# =============================================================================
# Deterministic stand-in vectors
# =============================================================================
#
# A's example and B's example are orthogonal unit vectors, so a query equal to
# one of them scores cosine 1.0 against it and 0.0 against the other — well
# either side of the 0.85 acceptance threshold. A match reported for the wrong
# vector is unambiguously the wrong user's row, never a near miss.

_DIM = EmbeddingModel.EMBEDDING_DIM


def _unit(axis: int) -> np.ndarray:
    vector = np.zeros(_DIM, dtype=np.float32)
    vector[axis] = 1.0
    return vector


VEC_A = _unit(0)
VEC_B = _unit(1)
VEC_UNRELATED = _unit(2)

# Markers the stub encoder recognises inside "<subject>\n\n<body>".
TEXT_LIKE_A = "MATCHES-A"
TEXT_LIKE_B = "MATCHES-B"


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
async def embeddings_db(monkeypatch: pytest.MonkeyPatch):
    """In-memory DB wired in as ``jobtracker.database.get_session``.

    ``embeddings.py`` imports ``get_session`` *inside* each method body, so
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

    async def _seed(
        user_id: uuid.UUID,
        category: EmailCategory,
        vector: np.ndarray,
        *,
        email_id: int,
    ) -> None:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add(
                EmailEmbedding(
                    user_id=user_id,
                    email_id=email_id,
                    label=category.value,
                    embedding=embedding_to_bytes(vector),
                )
            )
            await session.commit()

    async def _rows() -> list[EmailEmbedding]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            result = await session.exec(select(EmailEmbedding))
            return list(result.all())

    yield SimpleNamespace(seed=_seed, rows=_rows)

    await engine.dispose()


@pytest.fixture
def stub_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap e5-small-v2 for a lookup table so nothing is downloaded."""

    def _encode(_self: EmbeddingModel, text: str) -> np.ndarray:
        if TEXT_LIKE_A in text:
            return VEC_A
        if TEXT_LIKE_B in text:
            return VEC_B
        return VEC_UNRELATED

    monkeypatch.setattr(EmbeddingModel, "is_available", lambda _self: True)
    monkeypatch.setattr(EmbeddingModel, "encode", _encode)


async def _seed_both_users(embeddings_db) -> None:
    """One example each, orthogonal, different labels."""

    await embeddings_db.seed(USER_A, EmailCategory.OFFER, VEC_A, email_id=1)
    await embeddings_db.seed(USER_B, EmailCategory.REJECTION, VEC_B, email_id=2)


def _labels(classifier: EmbeddingsClassifier) -> list[EmailCategory]:
    return [category for _vector, category in classifier._known_embeddings]


# =============================================================================
# 1. The corpus read is scoped to the caller
# =============================================================================


async def test_load_known_embeddings_reads_only_the_bound_user(
    embeddings_db, stub_model
) -> None:
    """Two owners in the table; a load sees exactly the bound one."""

    await _seed_both_users(embeddings_db)

    classifier = EmbeddingsClassifier()
    with user_id_scope(USER_A):
        await classifier.load_known_embeddings()

    assert _labels(classifier) == [EmailCategory.OFFER], (
        "user A's embeddings layer loaded another tenant's examples: "
        f"{_labels(classifier)}"
    )


async def test_a_prediction_cannot_be_decided_by_another_users_example(
    embeddings_db, stub_model
) -> None:
    """The claim, stated as behaviour.

    User A asks about a message whose embedding is *identical* to user B's
    stored ``rejection`` example and unrelated to anything A owns. A has no
    neighbour for it, so the honest answer is "no match". Any verdict at all
    here is B's label deciding A's classification.
    """

    await _seed_both_users(embeddings_db)

    classifier = EmbeddingsClassifier()
    with user_id_scope(USER_A):
        result = await classifier.classify(TEXT_LIKE_B, "body text")

    assert result is None, (
        "user A's prediction was decided by user B's stored example: "
        f"got {result}"
    )


# =============================================================================
# 2. The per-process cache is keyed by owner, not by "already loaded"
# =============================================================================


async def test_cached_examples_do_not_survive_a_change_of_user(
    embeddings_db, stub_model
) -> None:
    """The variant RLS cannot catch.

    ``get_embeddings_classifier()`` hands the same instance to every request
    in a process, so this two-load sequence on one instance is exactly what a
    request from A followed by a request from B does. B's load must re-read,
    not short-circuit on a flag that A set.
    """

    await _seed_both_users(embeddings_db)

    classifier = EmbeddingsClassifier()
    with user_id_scope(USER_A):
        await classifier.load_known_embeddings()
    with user_id_scope(USER_B):
        await classifier.load_known_embeddings()

    assert _labels(classifier) == [EmailCategory.REJECTION], (
        "user B was served user A's cached examples: " f"{_labels(classifier)}"
    )


async def test_a_warm_process_does_not_answer_the_next_user_from_cache(
    embeddings_db, stub_model
) -> None:
    """Same shape, driven through ``classify()`` — the real request path.

    A's request warms the process. B then asks about a message identical to
    A's ``offer`` example. B owns no such example, so B must get no match.
    """

    await _seed_both_users(embeddings_db)

    classifier = EmbeddingsClassifier()
    with user_id_scope(USER_A):
        await classifier.classify(TEXT_LIKE_A, "body text")

    with user_id_scope(USER_B):
        result = await classifier.classify(TEXT_LIKE_A, "body text")

    assert result is None, (
        "a warm process answered user B out of user A's cache: " f"got {result}"
    )


# =============================================================================
# 3. Counts and writes carry the same owner
# =============================================================================


async def test_example_count_counts_only_the_bound_user(
    embeddings_db, stub_model
) -> None:
    """``GET /classify/status`` reports a per-user total, not a global one."""

    await embeddings_db.seed(USER_A, EmailCategory.OFFER, VEC_A, email_id=1)
    await embeddings_db.seed(USER_B, EmailCategory.REJECTION, VEC_B, email_id=2)
    await embeddings_db.seed(USER_B, EmailCategory.INTERVIEW, VEC_UNRELATED, email_id=3)

    classifier = EmbeddingsClassifier()
    with user_id_scope(USER_A):
        count = await classifier.get_example_count()

    assert count == 1, f"status leaked other tenants' example counts: {count}"


async def test_add_example_stamps_the_bound_user(embeddings_db, stub_model) -> None:
    """A correction must be owned by whoever made it.

    Without this, scoping the read alone would leave every cloud user reading
    an empty corpus while their corrections piled up on ``LOCAL_USER_ID``.
    """

    classifier = EmbeddingsClassifier()
    with user_id_scope(USER_B):
        await classifier.add_example(
            email_id=7,
            subject=TEXT_LIKE_B,
            body="body text",
            category=EmailCategory.REJECTION,
        )

    rows = await embeddings_db.rows()
    assert len(rows) == 1
    assert rows[0].user_id == USER_B, (
        "correction was written under the wrong owner: "
        f"{rows[0].user_id} (LOCAL_USER_ID is {LOCAL_USER_ID})"
    )


async def test_add_example_does_not_append_into_another_users_cache(
    embeddings_db, stub_model
) -> None:
    """Appending to a warm cache is a write-side version of the same leak."""

    await _seed_both_users(embeddings_db)

    classifier = EmbeddingsClassifier()
    with user_id_scope(USER_A):
        await classifier.load_known_embeddings()

    with user_id_scope(USER_B):
        await classifier.add_example(
            email_id=9,
            subject=TEXT_LIKE_B,
            body="body text",
            category=EmailCategory.INTERVIEW,
        )

    assert _labels(classifier) == [EmailCategory.OFFER], (
        "user B's new example was appended into user A's loaded cache: "
        f"{_labels(classifier)}"
    )


# =============================================================================
# 4. Belt and braces: the corpus is re-checked after loading
# =============================================================================
#
# Defence 3 (the ``WHERE``) makes this unreachable, which is the point — it
# exists so that a future refactor deleting the filter as "redundant" fails
# loudly instead of quietly pooling tenants again. Exercised by substituting
# the row loader, which is what a dropped filter looks like from the caller's
# side. Same construction as ``test_training_is_single_user.py``.


async def test_a_dropped_filter_raises_instead_of_pooling(
    embeddings_db, stub_model, monkeypatch: pytest.MonkeyPatch
) -> None:
    from jobtracker.classifier.embeddings import CrossUserEmbeddingError

    await _seed_both_users(embeddings_db)

    async def _unfiltered(_self, session, *, user_id):  # noqa: ANN001 - test double
        result = await session.exec(select(EmailEmbedding))
        return list(result.all())

    monkeypatch.setattr(EmbeddingsClassifier, "_load_rows", _unfiltered)

    classifier = EmbeddingsClassifier()
    with user_id_scope(USER_A), pytest.raises(CrossUserEmbeddingError):
        await classifier.load_known_embeddings()

    assert classifier._known_embeddings == []


# =============================================================================
# 5. Keying the cache by owner must not silently re-arm the eval harness
# =============================================================================


async def test_pinned_empty_corpus_holds_for_every_user(
    embeddings_db, stub_model
) -> None:
    """``evaluate_classifier``'s ``deterministic`` profile must stay deterministic.

    It pins layer 2 to an empty corpus so a benchmark never depends on local
    database state. An owner-keyed load cache would otherwise re-read for any
    caller whose identity differs from the pinned one — turning a reproducible
    score back into a stateful one, with every existing assertion still green.
    """

    await _seed_both_users(embeddings_db)

    classifier = EmbeddingsClassifier()
    classifier.pin_empty_corpus()

    for owner in (USER_A, USER_B):
        with user_id_scope(owner):
            await classifier.load_known_embeddings()
        assert classifier._known_embeddings == [], (
            f"pinned corpus was re-read from the database for {owner}"
        )
