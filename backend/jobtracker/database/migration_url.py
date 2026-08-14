"""Normalise a database URL to the sync driver Alembic has to use.

WHY THIS IS A MODULE AND NOT A HELPER INSIDE ``alembic/env.py``
---------------------------------------------------------------
``db-migrate.yml`` confirms the database is reachable before it runs the
migration. That step used to normalise the URL *its own way* — strip any
SQLAlchemy driver suffix, hand the rest to ``psycopg.connect`` — while
``env.py`` normalised differently. Two copies of one rule, and they drifted
in the way that matters: the guard passed on a URL the migration then died
on.

Concretely, on run 31770840632 (2026-08-14, the first run that ever had a
credential): ``DIRECT_URL`` was a bare ``postgresql://…``, which is exactly
what Supabase's dashboard hands you and exactly what this workflow's own
error message tells you to paste. The reachability check stripped nothing,
connected fine, printed ``connected: PostgreSQL 17.6``. Then SQLAlchemy
resolved bare ``postgresql://`` to its default dialect — **psycopg2** — which
``requirements-migrate.txt`` deliberately does not ship (it ships psycopg 3),
and the run ended at ``ModuleNotFoundError: No module named 'psycopg2'``.

So the rule lives here, both callers import it, and the guard now fails on
anything the migration would fail on. A check that cannot fail before it
matters is the recurring defect shape in this repo; this is one less.
"""

from __future__ import annotations

# Every spelling of "a Postgres URL" that should end up on psycopg 3:
#
#   postgresql+asyncpg  the app's own runtime driver, async — Alembic is sync
#   postgresql          the bare scheme; SQLAlchemy defaults it to psycopg2
#   postgres            the legacy scheme, still emitted by some providers
#   postgresql+psycopg2 an explicit ask for a driver we do not install
#
# The last one is rewritten rather than left to fail. The intent behind it is
# "the sync Postgres driver", and psycopg 3 is the sync Postgres driver here;
# honouring the letter of it would only produce the ModuleNotFoundError this
# module exists to prevent.
_POSTGRES_PREFIXES = (
    "postgresql+asyncpg://",
    "postgresql+psycopg2://",
    "postgresql://",
    "postgres://",
)

_SYNC_POSTGRES = "postgresql+psycopg://"


def normalise_sync_driver(url: str) -> str:
    """Return ``url`` with a driver Alembic can open synchronously.

    Alembic runs migrations synchronously, so an async driver cannot be used
    even though it is the correct one at runtime. Anything already naming a
    sync driver (including ``postgresql+psycopg``) is returned untouched.
    """

    if url.startswith("sqlite+aiosqlite"):
        return url.replace("sqlite+aiosqlite", "sqlite", 1)

    for prefix in _POSTGRES_PREFIXES:
        if url.startswith(prefix):
            return _SYNC_POSTGRES + url[len(prefix) :]

    return url


def to_libpq_url(url: str) -> str:
    """Strip the SQLAlchemy driver suffix so ``psycopg.connect`` accepts it.

    Used by the reachability probe, which talks to psycopg directly rather
    than through SQLAlchemy. Deliberately built on top of
    :func:`normalise_sync_driver` so the probe can only ever be pointed at
    the same endpoint the migration will use.
    """

    normalised = normalise_sync_driver(url)
    if normalised.startswith(_SYNC_POSTGRES):
        return "postgresql://" + normalised[len(_SYNC_POSTGRES) :]
    return normalised
