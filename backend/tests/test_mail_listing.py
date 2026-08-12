"""``GET /applications/mail`` — every stored verdict must be reachable.

Why this file exists
--------------------

``/applications/review`` was the product's only listing of classified mail, and
it filters to ``needs_review AND application_id IS NULL AND is_reviewed = false``.
Those three predicates make a verdict unreachable the moment it is touched. In
the owner's production database:

* emails 58 and 59 sit at ``needs_review`` with ``is_reviewed = true`` (58 is
  linked to application 67). No endpoint could name them, so no screen could
  show them and no screen could change them — permanently stuck at a verdict
  the user disagreed with;
* the same query returns **0 rows** for that account overall, so the review UI
  never rendered at all;
* meanwhile the write path, :func:`classify_review_item`, selects on
  ``(user_id, message_id)`` with no such constraint — correcting any of these
  already worked. Only the *read* was missing.

So the case that matters most here is the boring-looking one: a reviewed email
appears. That single assertion is the whole point of the endpoint, and it is
the one a re-added ``is_reviewed == False`` filter would break.

Proven to fail
--------------

Every assertion below was checked by breaking the thing it covers and watching
it go red (see the report accompanying the change). The mutations and their
results are recorded next to each test.

The fixtures are guarded: :func:`test_the_fixture_set_is_what_the_tests_assume`
runs first and pins the seeded corpus against the literals the other tests use,
because a test that seeds nothing and asserts over nothing is green.
"""

from __future__ import annotations

import importlib
import re
import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event

JWT_SECRET = "mail-listing-test-jwt-secret-at-least-32-bytes-long-hs256"
OWNER = "dddddddd-dddd-dddd-dddd-dddddddddddd"
STRANGER = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"

# Nearly every row carries the SAME timestamp on purpose: that is the state a
# sync leaves behind, and the only state in which the `id` tiebreak matters.
TIED_AT = datetime(2026, 8, 11, 9, 30, 0)
# One row is genuinely newer, so "newest first" is falsifiable rather than
# vacuously true over a set of ties.
NEWEST_AT = TIED_AT + timedelta(days=1)

# Seeded into `body_text`/`body_html` on every row. Bodies are never fetched by
# the cloud sync and must never leave the backend; asserting on this string
# rather than on the absence of a field name is what makes the check able to
# fail (a response model with no `body_text` field cannot ever contain the
# literal "body_text", so that assertion would pass no matter what).
BODY_SENTINEL = "SENTINEL-BODY-MUST-NOT-LEAVE-THE-BACKEND"

CRUSOE = "Crusoe Energy"
NORTHWIND = "Northwind Systems"


# (message_id, subject, sender_name, sender_email, category, is_reviewed, link)
# `link` is a company name to file the message under, or None for unlinked.
OWNER_MAIL: tuple[tuple[str, str, str, str, str, bool, str | None], ...] = (
    # The two rows this endpoint exists for. Both already reviewed once, so
    # `/review` can never list them again; one is linked to an application
    # (email 58's shape), one is not (email 59's).
    (
        "m-58",
        "Crusoe | Application Received",
        "Crusoe Recruiting",
        "recruiting@crusoe.ai",
        "needs_review",
        True,
        CRUSOE,
    ),
    (
        "m-59",
        "Crusoe | Application Received",
        "Crusoe Recruiting",
        "recruiting@crusoe.ai",
        "needs_review",
        True,
        None,
    ),
    # Matches q="crusoe" on the SENDER only — its subject says nothing.
    (
        "m-sender",
        "Thanks for your interest",
        "Talent Team",
        "jobs@crusoe.ai",
        "applied",
        False,
        None,
    ),
    # Matches q="crusoe" on the SUBJECT only — its sender is a job board.
    (
        "m-subject",
        "Your Crusoe application",
        "Greenhouse",
        "noreply@greenhouse.io",
        "applied",
        False,
        None,
    ),
    ("n-1", "Thanks for applying", "Northwind", "careers@northwind.test", "applied", False, NORTHWIND),
    ("n-2", "Application received", "Northwind", "careers@northwind.test", "applied", False, NORTHWIND),
    ("n-3", "We got your application", "Northwind", "careers@northwind.test", "applied", False, None),
    ("n-4", "Application submitted", "Northwind", "careers@northwind.test", "applied", False, None),
    ("n-5", "Received: Backend Engineer", "Northwind", "careers@northwind.test", "applied", False, None),
    ("n-6", "Received: Data Engineer", "Northwind", "careers@northwind.test", "applied", False, None),
    ("n-7", "Received: Platform Engineer", "Northwind", "careers@northwind.test", "applied", False, None),
    # The newest row, and not an application at all.
    ("m-other", "Your weekly newsletter", "Substack", "no-reply@substack.test", "other", False, None),
)

# A second account whose mail must never appear in the first one's listing —
# including a row that would match every filter the tests apply.
STRANGER_MAIL: tuple[tuple[str, str, str, str, str, bool, str | None], ...] = (
    ("s-1", "Crusoe | Application Received", "Crusoe Recruiting", "recruiting@crusoe.ai", "needs_review", True, None),
    ("s-2", "Thanks for applying", "Someone Else", "careers@elsewhere.test", "applied", False, None),
    ("s-3", "Your weekly newsletter", "Substack", "no-reply@substack.test", "other", False, None),
)

# Hardcoded so a mistake in the table above cannot quietly redefine what the
# tests prove; `test_the_fixture_set_is_what_the_tests_assume` reconciles the
# two. (Derived-only expectations agree with any corpus, including an empty one.)
EXPECTED_TOTAL = 12
EXPECTED_COUNTS = {"applied": 9, "needs_review": 2, "other": 1}
Q_NEEDLE = "crusoe"
EXPECTED_Q_MATCHES = {"m-58", "m-59", "m-sender", "m-subject"}
EXPECTED_Q_COUNTS = {"applied": 2, "needs_review": 2}
LINKED_MESSAGES = {"m-58": CRUSOE, "n-1": NORTHWIND, "n-2": NORTHWIND}


def _token_for(user_id: str) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {"sub": user_id, "aud": "authenticated", "iat": now, "exp": now + 300},
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture
async def cloud_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """The cloud app over the in-memory SQLite test DB (see test_user_id_scoping)."""

    monkeypatch.setenv("JOBTRACKER_DEPLOYMENT", "cloud")
    monkeypatch.setenv("JOBTRACKER_ENVIRONMENT", "test")
    monkeypatch.setenv("JOBTRACKER_SUPABASE_JWT_SECRET", JWT_SECRET)

    import jobtracker.config as config_module
    import jobtracker.database.connection as connection_module

    importlib.reload(config_module)
    connection_module._engine = None

    import jobtracker.auth.supabase_jwt as auth_module

    importlib.reload(auth_module)

    import jobtracker.cloud.applications as cloud_apps_module

    importlib.reload(cloud_apps_module)

    import jobtracker.main_cloud as main_cloud_module

    importlib.reload(main_cloud_module)

    from jobtracker.database import init_db

    await init_db()

    yield main_cloud_module.app

    if connection_module._engine is not None:
        await connection_module._engine.dispose()
    connection_module._engine = None
    monkeypatch.undo()
    importlib.reload(config_module)


async def _seed() -> dict[str, int]:
    """Write both accounts' applications and mail. Returns app ids by company."""

    from jobtracker.database.connection import get_session
    from jobtracker.database.models import (
        Application,
        ApplicationStatus,
        Email,
        EmailCategory,
        EmailSource,
    )

    app_ids: dict[str, int] = {}
    async with get_session() as session:
        for company in (CRUSOE, NORTHWIND):
            row = Application(
                user_id=uuid.UUID(OWNER),
                company=company,
                position="Software Engineer",
                status=ApplicationStatus.APPLIED,
            )
            session.add(row)
            await session.flush()
            app_ids[company] = row.id

        # The stranger holds an application at the same employer, so a
        # cross-user company lookup would resolve to something plausible
        # rather than to nothing.
        stranger_app = Application(
            user_id=uuid.UUID(STRANGER),
            company=CRUSOE,
            position="Software Engineer",
            status=ApplicationStatus.APPLIED,
        )
        session.add(stranger_app)
        await session.flush()

        for owner, table in ((OWNER, OWNER_MAIL), (STRANGER, STRANGER_MAIL)):
            for (
                message_id,
                subject,
                sender_name,
                sender_email,
                category,
                is_reviewed,
                link,
            ) in table:
                session.add(
                    Email(
                        user_id=uuid.UUID(owner),
                        source_account=EmailSource.GMAIL,
                        message_id=message_id,
                        thread_id=f"thread-{message_id}",
                        subject=subject,
                        sender_name=sender_name,
                        sender_email=sender_email,
                        received_at=NEWEST_AT if message_id == "m-other" else TIED_AT,
                        body_text=f"{BODY_SENTINEL} plain",
                        body_html=f"<p>{BODY_SENTINEL} html</p>",
                        body_snippet=f"snippet for {message_id}",
                        classified_as=EmailCategory(category),
                        classification_confidence=0.71,
                        classification_method="rules",
                        user_corrected=is_reviewed,
                        is_reviewed=is_reviewed,
                        application_id=app_ids[link] if link and owner == OWNER else None,
                    )
                )
        await session.commit()

    return app_ids


async def _get(cloud_app, user: str = OWNER, **params: Any) -> Any:
    async with AsyncClient(
        transport=ASGITransport(app=cloud_app), base_url="http://test"
    ) as client:
        return await client.get(
            "/applications/mail",
            params=params,
            headers={"Authorization": f"Bearer {_token_for(user)}"},
        )


# =============================================================================
# The premise guard — run this before believing anything below it
# =============================================================================


async def test_the_fixture_set_is_what_the_tests_assume(cloud_app):
    """Reconcile the seeded corpus with the literals the other tests use.

    A previous test in this repo reported "3 passed, 4 skipped" because its
    table names were wrong and every case skipped itself into green. Assertions
    over an empty or mis-shaped fixture set are worth nothing, so this pins the
    fixture set itself before anything asserts over it.
    """

    app_ids = await _seed()
    assert set(app_ids) == {CRUSOE, NORTHWIND}

    assert len(OWNER_MAIL) == EXPECTED_TOTAL, "the owner's corpus changed size"
    assert len({row[0] for row in OWNER_MAIL}) == EXPECTED_TOTAL, "duplicate message ids"

    derived: dict[str, int] = {}
    for row in OWNER_MAIL:
        derived[row[4]] = derived.get(row[4], 0) + 1
    assert derived == EXPECTED_COUNTS

    derived_q = {row[0] for row in OWNER_MAIL if Q_NEEDLE in (row[1] + row[3]).lower()}
    assert derived_q == EXPECTED_Q_MATCHES

    derived_links = {row[0]: row[6] for row in OWNER_MAIL if row[6] is not None}
    assert derived_links == LINKED_MESSAGES
    assert len(LINKED_MESSAGES) >= 2, (
        "the N+1 check needs at least two linked rows on one page, otherwise "
        "'one query' and 'one query per row' are the same number"
    )

    # And the rows really landed in the database.
    from sqlmodel import select

    from jobtracker.database.connection import get_session
    from jobtracker.database.models import Email

    async with get_session() as session:
        stored = (await session.exec(select(Email))).all()
    assert len(stored) == len(OWNER_MAIL) + len(STRANGER_MAIL)


# =============================================================================
# The gap this endpoint closes
# =============================================================================


async def test_a_reviewed_email_is_listed(cloud_app):
    """Emails 58 and 59: reviewed, and therefore invisible to ``/review``.

    THE POINT OF THE ENDPOINT. A verdict the user already touched once stays
    correctable, instead of being frozen wherever the classifier left it.

    Mutation: re-adding ``Email.is_reviewed == False`` to the page filters →
    this test fails (both ids missing).
    """

    await _seed()
    res = await _get(cloud_app)
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["messages"], "the listing returned nothing to assert over"
    by_id = {m["message_id"]: m for m in body["messages"]}

    for message_id in ("m-58", "m-59"):
        assert message_id in by_id, (
            f"{message_id} is reviewed needs-review mail and is unreachable "
            "again — this is the exact state emails 58/59 are stuck in"
        )
        assert by_id[message_id]["is_reviewed"] is True
        assert by_id[message_id]["category"] == "needs_review"

    # 59 is unlinked; the review queue would additionally have dropped 58 for
    # being filed against an application.
    assert by_id["m-59"]["application_id"] is None
    assert by_id["m-58"]["application_id"] is not None


async def test_a_linked_email_carries_its_company(cloud_app):
    """A filed message names its employer, and an unfiled one names nothing.

    Mutation: adding ``Email.application_id.is_(None)`` to the page filters →
    fails (m-58 missing). Returning ``company=None`` unconditionally → fails.
    """

    app_ids = await _seed()
    res = await _get(cloud_app)
    assert res.status_code == 200, res.text
    by_id = {m["message_id"]: m for m in res.json()["messages"]}
    assert by_id, "the listing returned nothing to assert over"

    for message_id, company in LINKED_MESSAGES.items():
        assert by_id[message_id]["application_id"] == app_ids[company]
        assert by_id[message_id]["company"] == company

    assert by_id["m-59"]["company"] is None
    assert by_id["m-other"]["company"] is None


async def test_company_resolution_is_one_query_not_one_per_row(cloud_app):
    """Three linked rows on the page must cost ONE applications SELECT.

    Reads the statements handed to the driver, so it measures the query the
    database actually receives rather than the shape of the Python.

    Mutation: resolving the company inside the per-row loop → 3 statements,
    this fails.
    """

    await _seed()

    import jobtracker.database.connection as connection_module

    engine = connection_module._engine
    assert engine is not None, "the fixture should have built an engine"

    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _capture(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        statements.append(statement)

    try:
        res = await _get(cloud_app, page_size=EXPECTED_TOTAL)
        assert res.status_code == 200, res.text
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _capture)

    linked = [m for m in res.json()["messages"] if m["application_id"] is not None]
    assert len(linked) == len(LINKED_MESSAGES), "the page did not contain the linked rows"

    against_applications = [s for s in statements if "FROM applications" in s]
    assert len(against_applications) <= 1, (
        "the company lookup is running per row: "
        f"{len(against_applications)} SELECTs against applications for "
        f"{len(linked)} linked messages"
    )


async def test_another_users_mail_is_never_listed(cloud_app):
    """Owner-scoped rows, owner-scoped counts.

    Mutation: dropping ``Email.user_id == user_id`` from the page filters →
    fails (the stranger's ids appear and the totals inflate).
    """

    await _seed()

    mine = await _get(cloud_app, page_size=EXPECTED_TOTAL)
    assert mine.status_code == 200, mine.text
    mine_body = mine.json()
    mine_ids = {m["message_id"] for m in mine_body["messages"]}
    assert mine_ids == {row[0] for row in OWNER_MAIL}
    assert mine_body["total"] == EXPECTED_TOTAL
    assert mine_body["category_counts"] == EXPECTED_COUNTS

    theirs = await _get(cloud_app, user=STRANGER, page_size=EXPECTED_TOTAL)
    assert theirs.status_code == 200, theirs.text
    theirs_body = theirs.json()
    theirs_ids = {m["message_id"] for m in theirs_body["messages"]}
    assert theirs_ids == {row[0] for row in STRANGER_MAIL}
    assert theirs_ids, "the stranger's own listing came back empty"
    assert not (theirs_ids & mine_ids)
    assert theirs_body["total"] == len(STRANGER_MAIL)

    # And the stranger's Crusoe application must not surface on their mail
    # either — s-1 is unlinked, so it names no employer.
    assert all(m["company"] is None for m in theirs_body["messages"])


async def test_bodies_never_leave_the_backend(cloud_app):
    """The stored body is on disk; it is not in the response.

    Asserts on a SENTINEL seeded into ``body_text``/``body_html``, not on the
    absence of a field name — the response model has no body field, so
    ``"body_text" not in response`` is a check that cannot fail.

    Mutation: ``snippet=e.body_text`` → fails.
    """

    await _seed()
    res = await _get(cloud_app, page_size=EXPECTED_TOTAL)
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["messages"], "the listing returned nothing to assert over"
    assert BODY_SENTINEL not in res.text, "a stored email body reached the client"
    # The snippet is still there — this is not passing because the payload is
    # empty of content.
    assert all(m["snippet"] for m in body["messages"])
    assert body["messages"][0]["snippet"].startswith("snippet for ")


# =============================================================================
# Filtering
# =============================================================================


async def test_category_filters_the_page(cloud_app):
    """``?category=`` narrows the listing and ``total`` follows it.

    Mutation: dropping the ``category`` filter from the page filters → fails
    (12 rows come back for a filter that should return 2).
    """

    await _seed()

    res = await _get(cloud_app, category="needs_review", page_size=EXPECTED_TOTAL)
    assert res.status_code == 200, res.text
    body = res.json()
    assert {m["message_id"] for m in body["messages"]} == {"m-58", "m-59"}
    assert body["total"] == EXPECTED_COUNTS["needs_review"]

    applied = await _get(cloud_app, category="applied", page_size=EXPECTED_TOTAL)
    assert applied.status_code == 200, applied.text
    assert applied.json()["total"] == EXPECTED_COUNTS["applied"]
    assert all(m["category"] == "applied" for m in applied.json()["messages"])

    # The wire vocabulary is the enum's VALUES, lowercase — the same words
    # `POST /review/{message_id}/classify` accepts, so a category read here can
    # be sent straight back as a correction. An unknown one is a visible 422,
    # not a silently empty page.
    assert (await _get(cloud_app, category="NEEDS_REVIEW")).status_code == 422
    assert (await _get(cloud_app, category="banana")).status_code == 422


async def test_q_matches_subject_and_sender(cloud_app):
    """``?q=`` is a case-insensitive substring over subject AND sender.

    The corpus contains a row that matches on the sender only and a row that
    matches on the subject only, so dropping either half of the OR fails.

    Mutation: dropping the ``q`` filter → fails (12 rows for a 4-row query).
    """

    await _seed()

    res = await _get(cloud_app, q=Q_NEEDLE, page_size=EXPECTED_TOTAL)
    assert res.status_code == 200, res.text
    body = res.json()
    assert {m["message_id"] for m in body["messages"]} == EXPECTED_Q_MATCHES
    assert body["total"] == len(EXPECTED_Q_MATCHES)

    # Case-insensitive: the corpus spells it "Crusoe".
    upper = await _get(cloud_app, q="CRUSOE", page_size=EXPECTED_TOTAL)
    assert {m["message_id"] for m in upper.json()["messages"]} == EXPECTED_Q_MATCHES

    # A needle that matches nothing returns an honest empty page, not everything.
    empty = await _get(cloud_app, q="zzz-no-such-mail", page_size=EXPECTED_TOTAL)
    assert empty.json()["total"] == 0
    assert empty.json()["messages"] == []


async def test_category_counts_ignore_category_but_respect_q(cloud_app):
    """The chips must show their own totals while one of them is selected.

    This is the asymmetry in the contract: ``total`` is the current query,
    ``category_counts`` deliberately is not.

    Mutations: counting over the page filters instead of the base filters →
    fails (the counts collapse to the selected chip); dropping ``q`` from the
    counts query → fails (the counts stay at the unfiltered totals).
    """

    await _seed()

    unfiltered = await _get(cloud_app, page_size=EXPECTED_TOTAL)
    assert unfiltered.json()["category_counts"] == EXPECTED_COUNTS

    # Selecting a chip must NOT change what the other chips say.
    filtered = await _get(cloud_app, category="needs_review", page_size=EXPECTED_TOTAL)
    assert filtered.json()["category_counts"] == EXPECTED_COUNTS, (
        "the counts collapsed to the selected category — every other chip "
        "would read zero the moment one was clicked"
    )
    assert filtered.json()["total"] == EXPECTED_COUNTS["needs_review"]

    # A search DOES change them: the chips describe the searched set.
    searched = await _get(cloud_app, q=Q_NEEDLE, page_size=EXPECTED_TOTAL)
    assert searched.json()["category_counts"] == EXPECTED_Q_COUNTS
    assert searched.json()["category_counts"] != EXPECTED_COUNTS

    # Both at once: counts follow `q` only.
    both = await _get(
        cloud_app, category="applied", q=Q_NEEDLE, page_size=EXPECTED_TOTAL
    )
    assert both.json()["category_counts"] == EXPECTED_Q_COUNTS
    assert both.json()["total"] == EXPECTED_Q_COUNTS["applied"]
    assert {m["message_id"] for m in both.json()["messages"]} == {"m-sender", "m-subject"}


# =============================================================================
# Ordering and paging
# =============================================================================


async def test_newest_first(cloud_app):
    """``m-other`` is a day newer than everything else, so it leads.

    Mutation: ``.asc()`` instead of ``.desc()`` on ``received_at`` → fails.
    """

    await _seed()
    res = await _get(cloud_app, page_size=EXPECTED_TOTAL)
    body = res.json()
    assert body["messages"], "the listing returned nothing to assert over"
    assert body["messages"][0]["message_id"] == "m-other"

    stamps = [m["received_at"] for m in body["messages"]]
    assert stamps == sorted(stamps, reverse=True), "the page is not newest-first"


async def test_paging_returns_every_row_exactly_once(cloud_app):
    """Walk every page over a corpus of tied timestamps and rebuild the set.

    Proves the offset/limit arithmetic and the ``page``/``page_size`` echo.
    It does NOT prove the ordering: SQLite returns tied rows in rowid order, so
    it is stable here whether or not the tiebreak exists. That half is
    :func:`test_the_listing_asks_the_database_for_a_total_order` — see the
    module docstring of ``test_listing_order_is_deterministic.py`` for why the
    split is necessary rather than belt-and-braces.
    """

    await _seed()

    page_size = 5
    collected: list[str] = []
    page = 1
    while True:
        res = await _get(cloud_app, page=page, page_size=page_size)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["total"] == EXPECTED_TOTAL
        assert body["page"] == page
        assert body["page_size"] == page_size
        got = [m["message_id"] for m in body["messages"]]
        if not got:
            break
        assert len(got) <= page_size
        collected.extend(got)
        if len(collected) >= body["total"]:
            break
        page += 1

    assert len(collected) == EXPECTED_TOTAL, "paging dropped or duplicated rows"
    assert len(set(collected)) == EXPECTED_TOTAL, "a row appeared on two pages"
    assert set(collected) == {row[0] for row in OWNER_MAIL}

    # Past the end: an empty page, not an error and not a wrapped-around one.
    over = await _get(cloud_app, page=99, page_size=page_size)
    assert over.status_code == 200
    assert over.json()["messages"] == []
    assert over.json()["total"] == EXPECTED_TOTAL


async def test_the_same_page_twice_is_the_same_page(cloud_app):
    """A second identical read must not reshuffle a page of tied timestamps."""

    await _seed()
    first = await _get(cloud_app, page=1, page_size=5)
    second = await _get(cloud_app, page=1, page_size=5)
    assert first.status_code == second.status_code == 200
    assert [m["message_id"] for m in first.json()["messages"]] == [
        m["message_id"] for m in second.json()["messages"]
    ]


async def test_the_listing_asks_the_database_for_a_total_order(cloud_app):
    """The emitted SQL must order by ``received_at`` AND ``id``.

    The assertion that catches the tiebreak being deleted. SQLite cannot show
    the bug — it returns tied rows in rowid order — so this reads the statement
    handed to the driver instead of the row order it happens to produce, which
    is what Postgres would receive in production.

    Mutation: deleting ``Email.id.desc()`` → fails here, and only here.
    """

    await _seed()

    import jobtracker.database.connection as connection_module

    engine = connection_module._engine
    assert engine is not None, "the fixture should have built an engine"

    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _capture(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        statements.append(statement)

    try:
        res = await _get(cloud_app, page=1, page_size=5)
        assert res.status_code == 200, res.text
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _capture)

    # The count and GROUP BY queries also read `emails` and carry no ORDER BY;
    # this picks out the one that pages.
    ordered = [
        s for s in statements if "FROM emails" in s and "ORDER BY" in s.upper()
    ]
    assert ordered, f"no ordered SELECT against emails was issued: {statements}"

    order_clause = re.split(r"ORDER BY", ordered[-1], flags=re.IGNORECASE)[1]
    lowered = order_clause.lower()

    assert "received_at" in lowered, f"received_at is not in the ORDER BY: {order_clause}"
    assert re.search(r"\bid\b", lowered), (
        "the mail listing no longer breaks ties on id — rows sharing a "
        "received_at are free to reorder per request on Postgres, which drops "
        f"and repeats them across pages. ORDER BY was: {order_clause}"
    )
    assert lowered.index("received_at") < lowered.rindex("id"), (
        "id must come after received_at, otherwise it is the primary sort and "
        f"the newest-first contract is broken. ORDER BY was: {order_clause}"
    )


async def test_page_size_is_bounded(cloud_app):
    """``page_size`` is capped by the router's MAX_PAGE_SIZE, and it is a 422."""

    await _seed()
    import jobtracker.cloud.applications as cloud_apps_module

    over = await _get(cloud_app, page_size=cloud_apps_module.MAX_PAGE_SIZE + 1)
    assert over.status_code == 422
    at_cap = await _get(cloud_app, page_size=cloud_apps_module.MAX_PAGE_SIZE)
    assert at_cap.status_code == 200
    assert at_cap.json()["page_size"] == cloud_apps_module.MAX_PAGE_SIZE


async def test_the_listing_requires_a_token(cloud_app):
    """No bearer token, no mail — the router-level dependency covers this route."""

    async with AsyncClient(
        transport=ASGITransport(app=cloud_app), base_url="http://test"
    ) as client:
        res = await client.get("/applications/mail")
    assert res.status_code == 401


async def test_mail_is_not_swallowed_by_the_application_id_route(cloud_app):
    """``/applications/mail`` must not be parsed as ``/applications/{id}``.

    FastAPI matches in declaration order. Declared below ``/{application_id}``
    this returns 422 ("mail" is not an int) — the same trap ``/summary``,
    ``/review`` and ``/statuses`` are each declared above it to avoid.
    """

    await _seed()
    res = await _get(cloud_app)
    assert res.status_code == 200, res.text
    assert "messages" in res.json(), (
        "the mail route was shadowed by /applications/{application_id}"
    )
