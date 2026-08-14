"""The constant the running code carries must equal the migration chain's head.

``jobtracker.database.schema_version.EXPECTED_REVISION`` is a literal because
the deployed function does not contain ``backend/alembic/`` (``vercel.json``
ships ``includeFiles: "backend/jobtracker/**"``), so nothing can derive it at
runtime in the one place the answer matters. A literal that nobody updates is
worse than no literal at all, so this module is what keeps it true.

The single-head assertion is the more interesting of the two. Alembic tolerates
multiple heads via branch labels, and this project has never used them — so more
than one head means two pull requests each wrote a revision whose
``down_revision`` is the same parent. Both merge green, because each is a valid
chain on its own. ``alembic upgrade head`` then fails on the *deploy*, with
"Multiple head revisions are present", against a database nobody has touched.
That is precisely the class of failure this repo keeps finding: a gate that
passes because it never looked at the combination.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from jobtracker.database.schema_version import (
    EXPECTED_REVISION,
    read_applied_revision,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def script_directory() -> ScriptDirectory:
    """Alembic's own view of the revision graph — not a hand-rolled parse."""

    return ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))


def test_migration_chain_has_exactly_one_head(
    script_directory: ScriptDirectory,
) -> None:
    """Two heads deploy green and then fail on `upgrade head`. Catch it here."""

    heads = script_directory.get_heads()
    assert len(heads) == 1, (
        f"The migration chain has {len(heads)} heads: {sorted(heads)}. Two "
        f"revisions share a down_revision — rebase one onto the other so the "
        f"chain is linear, or `alembic upgrade head` will fail on deploy."
    )


def test_expected_revision_is_the_head(script_directory: ScriptDirectory) -> None:
    """The baked constant must name the revision a fresh deploy would reach."""

    head = script_directory.get_current_head()
    assert head == EXPECTED_REVISION, (
        f"EXPECTED_REVISION is {EXPECTED_REVISION!r} but the migration head is "
        f"{head!r}. A revision was added without updating "
        f"jobtracker/database/schema_version.py, so /health/schema would report "
        f"a correctly-migrated database as out of date."
    )


def test_expected_revision_is_a_revision_that_exists(
    script_directory: ScriptDirectory,
) -> None:
    """Guards the typo that the equality test cannot: both sides edited wrong."""

    assert script_directory.get_revision(EXPECTED_REVISION) is not None


@pytest.mark.asyncio
async def test_read_applied_revision_returns_none_without_the_table() -> None:
    """A database Alembic has never touched reports None, and does not raise.

    The endpoint that calls this is unauthenticated and must never 500; the
    absence of a version table is a legitimate answer ("cannot say yes"), not an
    error condition.
    """

    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with AsyncSession(engine) as session:
            assert await read_applied_revision(session) is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_read_applied_revision_returns_the_stamp() -> None:
    """A stamped database reports exactly what is in the table."""

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with AsyncSession(engine) as session:
            await session.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(32))")
            )
            await session.execute(
                text("INSERT INTO alembic_version VALUES ('deadbeef1234')")
            )
            assert await read_applied_revision(session) == "deadbeef1234"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_read_applied_revision_reports_a_forked_version_table() -> None:
    """Two rows means the graph forked. Report both rather than picking one.

    Picking one would make `ok: false` look like a simple lag, and the actual
    problem — a database carrying two heads — invisible.
    """

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with AsyncSession(engine) as session:
            await session.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(32))")
            )
            await session.execute(
                text("INSERT INTO alembic_version VALUES ('bbbb'), ('aaaa')")
            )
            assert await read_applied_revision(session) == "aaaa+bbbb"
    finally:
        await engine.dispose()
