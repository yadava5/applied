"""
Schema Version
==============

The Alembic revision this *code* was written against, and a reader for the
revision the *database* is actually at.

Why a baked constant
--------------------

``EXPECTED_REVISION`` is a literal, deliberately **not** derived by scanning
``backend/alembic/versions/`` at import time. ``vercel.json`` ships the function
with ``includeFiles: "backend/jobtracker/**"``, so the alembic tree is not in
the deployed bundle at all — a runtime scan would find zero revisions in the one
environment where the answer matters, and report the empty result as fact. It is
kept honest by ``tests/test_schema_version.py``, which asserts the constant
equals Alembic's single head; that test fails on any revision added without
updating it.

The failure this exists to make visible
---------------------------------------

Nothing runs ``alembic upgrade head`` on a Vercel deploy. A revision therefore
lands in the repo and sits there while the code that needs it goes live. Because
every ``select(Email)`` in ``jobtracker.cloud`` emits an explicit column list, a
missing column is an ``UndefinedColumn`` error on the *first read* — the whole
board 500s and the deployment looks broken in a way that says nothing about
schema. Comparing these two strings turns that into one legible sentence.

This module reports; it never enforces. A schema check that refuses to serve
converts a false positive into an outage, and the drift it detects is by
construction a state where *some* endpoints still work fine.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

# The head of backend/alembic/versions/ as of this commit.
# Update it in the same commit that adds a revision; the test enforces this.
EXPECTED_REVISION = "f1c47b93a2d6"


async def read_applied_revision(session) -> str | None:
    """Return the revision stamped in ``alembic_version``, or ``None``.

    ``None`` is returned for three genuinely different situations, and the
    caller must not read it as "behind":

    - the table does not exist (a database Alembic has never touched),
    - the table exists but is empty (stamped down to base),
    - the query failed (no grant, connection lost, project paused).

    They are collapsed because the endpoint's job is to answer "does the
    database agree with this code?", and every one of them means "cannot say
    yes". The distinction is recoverable from logs, which is where it belongs
    rather than in an unauthenticated response body.
    """

    try:
        result = await session.execute(text("SELECT version_num FROM alembic_version"))
        rows = result.scalars().all()
    except Exception as exc:  # noqa: BLE001 - reporting endpoint, never raises
        logger.warning("Could not read alembic_version: %s", exc)
        return None

    if not rows:
        return None
    if len(rows) > 1:
        # Multiple heads applied to one database. Alembic permits this with
        # branch labels; this project has never used them, so it means a
        # migration graph that forked. Report it verbatim rather than picking
        # one — picking one would make a real, fixable problem invisible.
        logger.warning("alembic_version holds %d rows: %s", len(rows), sorted(rows))
        return "+".join(sorted(rows))
    return rows[0]
