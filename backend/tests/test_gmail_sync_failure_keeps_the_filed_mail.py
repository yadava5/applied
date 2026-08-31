"""A failed sync is not an unchanged board — the mail is already filed (#604).

``InboxWorkbench`` used to answer a failed "File these" with

    Couldn't file these (500) — nothing was changed.

That sentence is false, and this module is what establishes it as a fact about
the endpoint rather than a claim about the endpoint.

WHERE THE COMMIT IS. ``POST /gmail/sync`` persists inside the merge:
``sync_gmail_pipeline_additive`` commits, and ``upsert_applications_for_user``
commits again inside it. The cursor stamp — ``record_gmail_sync_success`` — runs
AFTER that, deliberately, so that the only way to fail is with the cursor not
advanced (one repeated scan, never a skipped message). The cost of that ordering
is a window in which the mail is durably filed and the request still ends badly,
and nothing in the product's copy acknowledged it.

THE TRIGGER USED HERE is the migrate/deploy window
``alembic/versions/a3f7d21c60be_sync_scan_ledger.py`` writes down: an additive
revision and a Vercel deploy start together and nothing orders them, so for a
few seconds the new code selects six ``sync_state`` columns the database does not
have. Every ``select()`` in ``jobtracker.cloud`` emits an explicit column list,
so that is an error, not a missing field. A RETURNING user's lease is a bare
UPDATE and matches, the run proceeds, the merge commits, and
``record_gmail_sync_success`` raises on the read. The window is reproduced by
dropping the columns the revision adds — imported from the revision's own
``_LEDGER_COLUMNS`` so this file cannot drift from the migration.

The window is only a trigger. Any failure past that first commit has the same
shape: a stamp deadlock, a dropped connection, a function killed on its 60 s
ceiling. That is why the corrected copy names the property rather than the
cause.

WHAT EACH TEST BELOW IS FOR

  * ``..._returning_user_keeps_the_mail_it_filed`` — the fact the new copy
    stands on. 500, three ``emails`` rows on disk, cursor and ``last_sync_at``
    exactly where they were seeded.
  * ``..._with_the_columns_intact`` — THE DISCRIMINATOR. Same user, same items,
    same callsite, one variable changed. Without it the test above measures
    nothing: "three rows exist" is only evidence if the same three rows are
    absent when the run cannot reach the merge.
  * ``..._first_time_user_files_nothing`` — the migration docstring's
    "harmless" claim, pinned. Worth stating plainly: this one fails EARLIER
    than the test above, in ``acquire_gmail_sync_lease``'s fallback read, which
    is outside the endpoint's ``try``. It shares a status code with the others
    and not a code path, so it is a claim about the first-time case and not a
    control for the returning one — and it carries its own control instead,
    because "no mail was filed" is otherwise true of a database nobody ever
    posted to.
  * ``..._recovery_re_files_idempotently`` — what makes the new sentence true
    in the other direction. Once the migration lands, the same POST succeeds,
    adds no duplicate row over ``UNIQUE ix_emails_user_id_message_id``, and
    finally advances the cursor.

THE FILENAME IS LOAD-BEARING; do not tidy it. ``cloud_app`` comes from
``test_gmail_oauth_cloud.py`` and reloads ``jobtracker.config`` on teardown
without re-pointing the modules holding a reference to the old ``settings``, so
any consumer sorting BEFORE it reds 15 auth assertions in a file that has
nothing to do with sync. ``test_gmail_sync_says_what_it_looked_at.py`` carries
the full account of that leak; this module sorts after the fixture's own module
for the same reason.
"""

from __future__ import annotations

import ast
import uuid as _uuid
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

# The cloud app, its client and a Gmail connection, from the suite that owns
# them — the same idiom as ``test_gmail_sync_says_what_it_looked_at.py``.
from tests.test_gmail_oauth_cloud import (  # noqa: F401 — fixtures by name
    GMAIL_ADDRESS,
    USER_A,
    _connect_gmail,
    _token_for,
    client,
    cloud_app,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent
LEDGER_REVISION = "a3f7d21c60be"

HEADERS = {"Authorization": f"Bearer {_token_for(USER_A)}"}

# The owner id AS THE RAW SQL BELOW HAS TO SPELL IT. ``_user_id_field`` declares
# ``sa.Uuid(as_uuid=True)``, which renders native ``UUID`` on Postgres and
# ``CHAR(32)`` on SQLite — dashless hex. A ``text()`` statement gets no type
# coercion, so binding the dashed form matches zero rows and the setup fails
# silently as "no row to seed" rather than as a wrong literal.
USER_A_KEY = _uuid.UUID(USER_A).hex

# What the seeded cursor says before the failing run touches anything. Both are
# arbitrary and both must come back unchanged: ``last_sync_at`` is what the UI
# renders as "last synced N minutes ago", and ``gmail_history_id`` is what makes
# the next sync incremental.
SEEDED_SYNC_AT = datetime(2026, 8, 1, 9, 30, 0)
# The same instant in the form SQLAlchemy's SQLite ``DATETIME`` stores, since
# the seed and the read-back both go through raw SQL and never see the type.
SEEDED_SYNC_AT_SQL = SEEDED_SYNC_AT.strftime("%Y-%m-%d %H:%M:%S.%f")
SEEDED_HISTORY_ID = "770001"


def _ledger_columns() -> tuple[str, ...]:
    """The six columns the ledger revision adds, read from the revision itself.

    Parsed rather than imported, following ``_revision_parent`` in
    ``test_agreement_is_not_a_correction.py``: an Alembic revision module is not
    on the import path, ``from alembic import op`` resolves to ``backend/alembic``
    when pytest runs from ``backend/``, and importing it would want a migration
    context that does not exist here.

    Read from the migration rather than restated so the reproduction cannot
    drift from what is actually deployed — a hand-copied list would keep passing
    against a seventh column nobody added it to.
    """

    matches = sorted((BACKEND_DIR / "alembic" / "versions").glob(f"{LEDGER_REVISION}_*.py"))
    assert len(matches) == 1, f"expected one module for {LEDGER_REVISION}, found {matches}"
    for node in ast.parse(matches[0].read_text()).body:
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", "") == "_LEDGER_COLUMNS" for target in node.targets
        ):
            columns = ast.literal_eval(node.value)
            assert isinstance(columns, tuple) and columns, f"bad _LEDGER_COLUMNS: {columns!r}"
            return columns
    raise AssertionError(f"{LEDGER_REVISION} declares no _LEDGER_COLUMNS")


LEDGER_COLUMNS = _ledger_columns()


@pytest.fixture
async def client_500(cloud_app) -> AsyncIterator[AsyncClient]:
    """The workbench's client: an uncaught exception is a 500 ON THE WIRE.

    The shared ``client`` fixture uses ``ASGITransport``'s default
    ``raise_app_exceptions=True``, which re-raises the app's exception into the
    test. That is the right default for a suite asserting on handled responses,
    and it is the wrong one here: what #604 is about is the STATUS the browser
    receives and the sentence rendered beside it, and an exception that never
    becomes a response cannot show either. Starlette's ``ServerErrorMiddleware``
    writes the 500 and then re-raises; this transport keeps the 500.
    """

    transport = ASGITransport(app=cloud_app, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport, base_url="http://cloud-test", follow_redirects=False
    ) as c:
        yield c


def _seed_items() -> list[dict]:
    """One earlier sync's worth of mail — what makes the user a RETURNING one.

    Its only job is to create the ``sync_state`` row, because that row is the
    entire difference between the two failure shapes: with it the lease UPDATE
    matches and the run reaches the merge, without it the lease falls through to
    a read and dies before any mail is touched.
    """

    return [
        {
            "message_id": "seed-1",
            "category": "applied",
            "sender_email": "no-reply@greenhouse.test",
            "subject": "Your application to Northwind",
            "sender_name": "Northwind",
            "received_at": "2026-07-01T12:00:00+00:00",
            "confidence": 0.92,
            "thread_id": "th-northwind",
        }
    ]


def _filable_items() -> list[dict]:
    """THREE messages that must each become a row. Three distinct employers.

    Every one clears the 0.85 auto-file gate and names an employer, so each
    produces an application AND an ``emails`` row — ``_persist_message_refs``
    writes one only for a message that clustered into an application or was
    flagged for review, which is exactly why "nothing was filed" was so easy to
    believe. Distinct employers so the count is three rows and not one row
    advanced three times.
    """

    return [
        {
            "message_id": "file-1",
            "category": "applied",
            "sender_email": "no-reply@lever.test",
            "subject": "Your application to Cedartech",
            "sender_name": "Cedartech",
            "received_at": "2026-07-20T12:00:00+00:00",
            "confidence": 0.93,
            "thread_id": "th-cedartech",
        },
        {
            "message_id": "file-2",
            "category": "applied",
            "sender_email": "careers@initech.test",
            "subject": "Your application to Initech",
            "sender_name": "Initech",
            "received_at": "2026-07-21T12:00:00+00:00",
            "confidence": 0.91,
            "thread_id": "th-initech",
        },
        {
            "message_id": "file-3",
            "category": "applied",
            "sender_email": "jobs@aventine.test",
            "subject": "Your application to Aventine",
            "sender_name": "Aventine",
            "received_at": "2026-07-22T12:00:00+00:00",
            "confidence": 0.9,
            "thread_id": "th-aventine",
        },
    ]


FILED_MESSAGE_IDS = tuple(item["message_id"] for item in _filable_items())


async def _filed_mail_rows() -> int:
    """How many of the three relayed messages are on disk as ``emails`` rows."""

    from sqlmodel import select as sm_select

    from jobtracker.database import get_session
    from jobtracker.database.models import Email

    async with get_session() as session:
        rows = (
            await session.exec(
                sm_select(Email).where(
                    Email.user_id == _uuid.UUID(USER_A),
                    Email.message_id.in_(FILED_MESSAGE_IDS),
                )
            )
        ).all()
    return len(rows)


async def _live_applications() -> int:
    """Board rows that are still on the board."""

    from sqlalchemy import func as sa_func
    from sqlmodel import select as sm_select

    from jobtracker.database import get_session
    from jobtracker.database.models import Application

    async with get_session() as session:
        return (
            await session.exec(
                sm_select(sa_func.count())
                .select_from(Application)
                .where(
                    Application.user_id == _uuid.UUID(USER_A),
                    Application.dismissed_at.is_(None),
                )
            )
        ).one()


async def _sync_state_rows() -> int:
    """How many ``sync_state`` rows this user owns, counted WITHOUT the ORM.

    The fact that MAKES the first-time case a different failure from the
    returning one: no row, so the lease's conditional UPDATE matches nothing and
    the fallback read runs — outside the endpoint's ``try``, before any mail is
    parsed. Without this the "zero mail rows" assertion beside it is true of a
    database where no sync has ever run for any reason at all.
    """

    from sqlalchemy import text

    from jobtracker.database import get_session

    async with get_session() as session:
        rows = (
            await session.exec(
                text(
                    "SELECT COUNT(*) FROM sync_state WHERE user_id = :uid"
                ).bindparams(uid=USER_A_KEY)
            )
        ).all()
    return rows[0][0]


async def _cursor_row() -> tuple[Any, Any]:
    """``(last_sync_at, gmail_history_id)``, read WITHOUT the ORM.

    Raw SQL because the ORM cannot read this table while the ledger columns are
    missing — that is the whole failure being reproduced, and an assertion that
    tripped over it would report the reproduction as the finding.
    """

    from sqlalchemy import text

    from jobtracker.database import get_session

    async with get_session() as session:
        row = (
            await session.exec(
                text(
                    "SELECT last_sync_at, gmail_history_id FROM sync_state "
                    "WHERE user_id = :uid AND account_email = :email"
                ).bindparams(uid=USER_A_KEY, email=GMAIL_ADDRESS)
            )
        ).all()
    assert len(row) == 1, f"expected exactly one sync_state row, found {len(row)}"
    return row[0][0], row[0][1]


async def _seed_cursor() -> None:
    """Put a KNOWN cursor on the row, so "unmoved" is a value and not a null."""

    from sqlalchemy import text

    from jobtracker.database import get_session

    async with get_session() as session:
        result = await session.exec(
            text(
                "UPDATE sync_state SET last_sync_at = :at, gmail_history_id = :hid "
                "WHERE user_id = :uid AND account_email = :email"
            ).bindparams(
                at=SEEDED_SYNC_AT_SQL,
                hid=SEEDED_HISTORY_ID,
                uid=USER_A_KEY,
                email=GMAIL_ADDRESS,
            )
        )
        assert result.rowcount == 1, "test setup: no sync_state row to seed"
        await session.commit()


async def _set_ledger_columns(*, present: bool) -> None:
    """Add or drop the ledger columns underneath the running app.

    SQLite has supported ``ALTER TABLE ... DROP COLUMN`` since 3.35 and the
    engine here is a ``StaticPool`` ``:memory:`` database, so the DDL and the
    ORM share one connection — the drop is visible to the very next
    ``select(SyncState)``, which is the premise this module rests on and is
    positively controlled by the columns-intact test below.
    """

    from sqlalchemy import text

    from jobtracker.database import get_session

    async with get_session() as session:
        for name in LEDGER_COLUMNS if present else reversed(LEDGER_COLUMNS):
            verb = f"ADD COLUMN {name} INTEGER" if present else f"DROP COLUMN {name}"
            await session.exec(text(f"ALTER TABLE sync_state {verb}"))
        await session.commit()


async def _make_returning_user(client: AsyncClient) -> None:
    """Connect Gmail, run ONE successful sync, then seed a known cursor.

    In this order and not another: the successful sync is what creates the
    ``sync_state`` row and the board rows, and an ORM insert after the columns
    were dropped would itself raise — the setup would fail as the reproduction.
    """

    await _connect_gmail(USER_A)
    seeded = await client.post("/gmail/sync", json={"items": _seed_items()}, headers=HEADERS)
    assert seeded.status_code == 200, seeded.text
    assert seeded.json()["created"] == 1, seeded.text
    await _seed_cursor()


# =============================================================================
# The fact the new copy stands on
# =============================================================================


async def test_returning_user_keeps_the_mail_it_filed(client_500: AsyncClient) -> None:
    """500, three messages filed, cursor exactly where it was.

    This is the state ``InboxWorkbench`` used to describe as "nothing was
    changed": the merge committed, the stamp raised on a column the database
    does not have, and the user was told their board was untouched while three
    new applications sat on it.
    """

    await _make_returning_user(client_500)
    await _set_ledger_columns(present=False)

    resp = await client_500.post(
        "/gmail/sync", json={"items": _filable_items()}, headers=HEADERS
    )

    assert resp.status_code == 500, resp.text

    # THE MAIL IS FILED. Equality, not truthiness: at three, a same-typed swap
    # for one of the other counts on this page has to red.
    assert await _filed_mail_rows() == 3
    # …and it reached the board, not just the mail table.
    assert await _live_applications() == 4  # the seed's Northwind + these three

    # THE CURSOR IS NOT. Both halves: ``last_sync_at`` is what the UI renders as
    # "last synced", and the history id is what would make the next run skip
    # this window.
    last_sync_at, history_id = await _cursor_row()
    assert history_id == SEEDED_HISTORY_ID
    assert last_sync_at == SEEDED_SYNC_AT_SQL


# =============================================================================
# The discriminator: same callsite, one variable
# =============================================================================


async def test_the_same_relay_succeeds_with_the_columns_intact(
    client_500: AsyncClient,
) -> None:
    """Same user, same three items, columns present: 200 and the cursor MOVES.

    Without this the test above proves nothing. "Three rows exist" is evidence
    only against a run in which they do not, and the first-time-user case below
    cannot supply that contrast because it dies at a different callsite. This
    one changes exactly one thing — whether the six columns are there.
    """

    await _make_returning_user(client_500)

    resp = await client_500.post(
        "/gmail/sync", json={"items": _filable_items()}, headers=HEADERS
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 3, resp.text
    assert await _filed_mail_rows() == 3
    assert await _live_applications() == 4

    last_sync_at, history_id = await _cursor_row()
    assert last_sync_at != SEEDED_SYNC_AT_SQL, "a successful sync did not stamp"
    assert datetime.fromisoformat(last_sync_at) > SEEDED_SYNC_AT
    # The relay path deliberately records no baseline (the client's mine may be
    # a narrower window than a server scan), so the seeded id must SURVIVE a
    # success too — this is not the thing the failure above is asserting.
    assert history_id == SEEDED_HISTORY_ID


# =============================================================================
# The first-time user, whom the migration calls harmless
# =============================================================================


async def test_first_time_user_files_nothing(client_500: AsyncClient) -> None:
    """No ``sync_state`` row: the run dies before it touches any mail.

    The lease's conditional UPDATE matches nothing, the fallback
    ``load_gmail_sync_state`` reads the missing columns, and that read happens
    OUTSIDE the endpoint's ``try`` — before the relay items are even parsed. So
    this is a 500 with genuinely nothing filed, which is what the revision's
    docstring claims and what makes "nothing was filed" a legitimate sentence
    for some failures and not for the one above.

    Every assertion about an empty database is also true of a database nobody
    ever posted to, so the same request is repeated with the columns back at
    the end: it takes the lease, writes the row and files all three.
    """

    await _connect_gmail(USER_A)
    # THE PRECONDITION, ASSERTED. It is the whole difference between this
    # failure and the one above, and "no row" is also the state every other
    # early death would leave behind — so it is checked before the request, not
    # inferred from the empty board after it.
    assert await _sync_state_rows() == 0, "this user is not a first-time syncer"
    await _set_ledger_columns(present=False)

    resp = await client_500.post(
        "/gmail/sync", json={"items": _filable_items()}, headers=HEADERS
    )

    assert resp.status_code == 500, resp.text
    assert await _filed_mail_rows() == 0
    assert await _live_applications() == 0
    # STILL no row, and that is the specific fact. ``acquire_gmail_sync_lease``
    # CREATES the row when its conditional UPDATE finds none — but only after
    # the ``load_gmail_sync_state`` that disambiguates "no row" from "someone
    # else holds it", and that read is the one that raises. So a zero here says
    # the run died inside the lease, before the insert and long before the
    # merge, rather than merely saying nothing happened.
    assert await _sync_state_rows() == 0

    # THE CONTROL, on the same user and the same callsite: with the columns
    # back, this identical request takes the lease, writes the row and files
    # the mail. Without it every assertion above is also true of a database
    # nobody ever posted to.
    await _set_ledger_columns(present=True)
    recovered = await client_500.post(
        "/gmail/sync", json={"items": _filable_items()}, headers=HEADERS
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["created"] == 3, recovered.text
    assert await _filed_mail_rows() == 3
    assert await _sync_state_rows() == 1


# =============================================================================
# The other direction: what the corrected sentence promises about recovery
# =============================================================================


async def test_recovery_re_files_idempotently_and_then_stamps(
    client_500: AsyncClient,
) -> None:
    """The migration lands; the identical POST now succeeds and adds nothing.

    "Anything filed before the failure stays that way" is only honest if the
    retry the user is being offered does not duplicate what survived. It does
    not: ``UNIQUE ix_emails_user_id_message_id`` and the application upsert make
    the re-file a no-op on row counts, and the stamp that failed the first time
    finally advances.
    """

    await _make_returning_user(client_500)
    await _set_ledger_columns(present=False)

    failed = await client_500.post(
        "/gmail/sync", json={"items": _filable_items()}, headers=HEADERS
    )
    assert failed.status_code == 500, failed.text
    mail_after_failure = await _filed_mail_rows()
    board_after_failure = await _live_applications()
    assert mail_after_failure == 3
    assert board_after_failure == 4

    # The db-migrate workflow catches up.
    await _set_ledger_columns(present=True)

    recovered = await client_500.post(
        "/gmail/sync", json={"items": _filable_items()}, headers=HEADERS
    )

    assert recovered.status_code == 200, recovered.text
    body = recovered.json()
    # Nothing NEW — every one of the three was already filed by the run that
    # failed, which is the whole point.
    assert body["created"] == 0, body
    assert body["updated"] == 3, body

    assert await _filed_mail_rows() == mail_after_failure
    assert await _live_applications() == board_after_failure

    last_sync_at, _history_id = await _cursor_row()
    assert last_sync_at != SEEDED_SYNC_AT_SQL, "the recovered sync did not stamp"
    assert datetime.fromisoformat(last_sync_at) > SEEDED_SYNC_AT
