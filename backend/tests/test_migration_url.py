"""The URL normalisation that stands between a pasted secret and a migration.

Every case here is a real string somebody can plausibly put in ``DIRECT_URL``.
The bare ``postgresql://`` one is not hypothetical: it is what Supabase's
dashboard hands you, what db-migrate.yml's own error message asks for, and
what killed run 31770840632 with ``ModuleNotFoundError: No module named
'psycopg2'`` — after the reachability probe had already printed a green
"connected".
"""

from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url

from jobtracker.database.migration_url import (
    normalise_sync_driver,
    to_libpq_url,
)

# (input, expected) — the driver on the right is the one this repo installs.
POSTGRES_CASES = [
    # The bare scheme. SQLAlchemy defaults it to psycopg2, which is NOT in
    # requirements-migrate.txt. This is the regression.
    ("postgresql://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
    # The legacy scheme some providers still emit.
    ("postgres://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
    # The app's runtime driver — async, unusable from a sync migration.
    ("postgresql+asyncpg://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
    # An explicit ask for a sync driver we do not ship.
    ("postgresql+psycopg2://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
    # Already correct — must be left exactly alone.
    ("postgresql+psycopg://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
]


@pytest.mark.parametrize("raw,expected", POSTGRES_CASES)
def test_every_postgres_spelling_lands_on_psycopg3(raw: str, expected: str) -> None:
    assert normalise_sync_driver(raw) == expected


@pytest.mark.parametrize("raw,_expected", POSTGRES_CASES)
def test_sqlalchemy_agrees_the_driver_is_psycopg3(raw: str, _expected: str) -> None:
    """The assertion that would have caught this.

    Comparing strings only proves the rewrite happened. What actually broke
    was SQLAlchemy's *dialect resolution*, so ask SQLAlchemy.
    """

    url = make_url(normalise_sync_driver(raw))
    assert url.get_driver_name() == "psycopg"


def test_bare_postgresql_resolves_to_psycopg2_without_the_fix() -> None:
    """Positive control: proves the case above is not vacuous.

    If SQLAlchemy ever changed its default DBAPI for the bare scheme, the
    test above would keep passing for a reason unrelated to this module.
    """

    assert make_url("postgresql://u:p@h/db").get_driver_name() == "psycopg2"


def test_async_sqlite_becomes_sync_sqlite() -> None:
    assert normalise_sync_driver("sqlite+aiosqlite:///x.db") == "sqlite:///x.db"


def test_unrecognised_urls_pass_through_untouched() -> None:
    assert normalise_sync_driver("sqlite:///x.db") == "sqlite:///x.db"
    assert normalise_sync_driver("mysql://u:p@h/db") == "mysql://u:p@h/db"


@pytest.mark.parametrize("raw,_expected", POSTGRES_CASES)
def test_libpq_form_drops_the_driver_suffix(raw: str, _expected: str) -> None:
    """psycopg.connect rejects a SQLAlchemy-style ``+driver`` scheme."""

    libpq = to_libpq_url(raw)
    assert libpq.startswith("postgresql://")
    assert "+" not in libpq.split("://", 1)[0]


def test_the_two_forms_describe_the_same_endpoint() -> None:
    """The drift that made the old probe useless.

    The reachability check and the migration must be pointed at one host, one
    port, one database, one user. Previously they normalised independently.
    """

    raw = "postgresql://someuser:secret@aws-1-us-east-2.pooler.supabase.com:5432/postgres"
    probe = make_url(to_libpq_url(raw))
    migration = make_url(normalise_sync_driver(raw))

    assert (probe.host, probe.port, probe.database, probe.username) == (
        migration.host,
        migration.port,
        migration.database,
        migration.username,
    )
