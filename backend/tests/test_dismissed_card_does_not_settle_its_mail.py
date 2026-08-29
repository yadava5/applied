"""A dismissed card settles nothing — its mail belongs back in the queue.

Why this file exists
--------------------

``GET /applications/review`` and the ``needs_review`` tile on
``GET /applications/summary`` both filtered on ``application_id IS NULL``. That
clause encodes "a linked message is already filed, so there is nothing to ask",
which is true of a message linked to a card the user can SEE and false of one
linked to a card that was dismissed: dismissal takes the row off the board, off
the funnel and out of every tile, so nothing about its mail is settled from the
user's side.

Issue #481 found the state on the owner's production account. Email 108
(``donotreply@email.careers.microsoft.com``, "Thank you for your application!")
sits at ``NEEDS_REVIEW`` linked to application 115, which a re-sync dismissed
minutes before the same pass re-classified the message below the auto-file gate.
The board showed zero Microsoft cards, the queue showed 7 items instead of 8,
and there was no screen from which that message could be acted on.

The predicate this asserts
--------------------------

"Not linked to an application the user can see", written as a ``NOT EXISTS``
over live applications rather than as ``application_id IS NULL``. Three cases,
and all three are needed — a fix that merely DROPS the link clause satisfies the
dismissed case and breaks the product, because every message already filed on a
live card would come back and ask its question again:

* unlinked ``needs_review``      → in the queue (unchanged),
* linked to a DISMISSED card     → in the queue (the fix),
* linked to a LIVE card          → NOT in the queue (the regression guard).

Plus the clause the fix must not widen: a message the user already REVIEWED
stays out even when its card was later dismissed. ``is_reviewed`` records that
the question was answered, and answering it is not undone by removing the row.

The three counts are allowed to differ
--------------------------------------

There are three surfaces counting review-ish things, deliberately differently
(#445, #576): the work queue, the inbox's stored-mail chip, and the per-scan
verdict chip. This change moves the WORK QUEUE only.
:func:`test_the_inbox_stored_mail_count_does_not_move` pins the inbox's count
against the fixture and asserts it is still LARGER than the queue's — a change
that made the two equal would have reconciled the surfaces instead of fixing
the predicate, which is the failure mode this file also exists to catch.

The `on your board` badge is NOT re-fixed here
----------------------------------------------

#481 names a second defect: ``/inbox`` badging this row "on your board" when the
board holds no such card. That predicate is a DIFFERENT one — the mail listing
resolves ``on_board`` from ``Application.dismissed_at`` in the same query that
resolves the employer — and it was already fixed by #491 for issue #489. So
:func:`test_the_inbox_does_not_call_a_dismissed_row_on_your_board` passes with
no product change; it is here to LOCK that, because it is one line of a set
comprehension away from regressing and #481 read the old behaviour as live.

The fixture form is the #582-safe one
-------------------------------------

``monkeypatch.setattr(settings, ...)`` and not the env-var-plus-
``importlib.reload(jobtracker.config)`` shape. This module's name sorts BETWEEN
``test_application_delete_children.py`` and ``test_status_vocabulary.py``, which
is exactly the collection window in which the reloading fixture leaks a stale
settings instance and fails six tests with ``401 Invalid signature``. It sorts
after eight modules that reload, too, so :func:`cloud_app` patches every
settings instance the request path holds rather than assuming one — measured,
not assumed: the single-instance form passed this module alone and failed all
nine of its tests in a full run. Details in the fixture's own docstring.

``on_board`` also has a module of its own,
``test_mail_says_whether_the_row_is_on_the_board.py`` (#489/#491). The
assertion here is not a replacement for it — it is the same claim made about
THIS row, in the fixture that builds the dismissed link, because #481 reports
the badge as broken and the cheapest way to answer that is on the data the
issue is about.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

from jobtracker.database.models import (
    Application,
    ApplicationStatus,
    Email,
    EmailCategory,
    EmailSource,
)

# 32+ bytes so PyJWT does not warn; the value only has to match the token helper.
JWT_SECRET = "dismissed-card-review-queue-secret-at-least-32-bytes"
OWNER = "b1b1b1b1-b1b1-4b1b-8b1b-b1b1b1b1b1b1"

RECEIVED_AT = datetime(2026, 8, 13, 14, 5, 0)

LIVE_COMPANY = "Northwind Systems"
DISMISSED_COMPANY = "Microsoft"

# The queue's four cases, seeded one row each. `link` names the application the
# message is filed against, or None for an unlinked message.
#
# (message_id, thread_id, subject, link, is_reviewed)
OWNER_MAIL: tuple[tuple[str, str, str, str | None, bool], ...] = (
    # Unlinked and un-reviewed: the shape the queue was always built for.
    ("m-unlinked", "t-unlinked", "Quick question about your background", None, False),
    # Email 108's shape: linked to a card a re-sync dismissed. Reachable from
    # nothing before this fix.
    (
        "m-dismissed",
        "t-dismissed",
        "Thank you for your application!",
        DISMISSED_COMPANY,
        False,
    ),
    # Filed on a card the user can see. Must STAY out of the queue: the board
    # already answers for it, and asking again is asking twice.
    ("m-live", "t-live", "Thanks for applying", LIVE_COMPANY, False),
    # Dismissed card, but the user already answered this one. `is_reviewed`
    # records a human decision, and removing the row does not un-make it.
    (
        "m-dismissed-reviewed",
        "t-dismissed-reviewed",
        "Your application status",
        DISMISSED_COMPANY,
        True,
    ),
)

# Hardcoded so a mistake in the table above cannot quietly redefine what the
# assertions prove; the fixture guard below reconciles the two. A derived-only
# expectation agrees with any corpus, including an empty one.
EXPECTED_STORED_NEEDS_REVIEW = 4
EXPECTED_IN_QUEUE = {"m-unlinked", "m-dismissed"}
EXPECTED_OUT_OF_QUEUE = {"m-live", "m-dismissed-reviewed"}


def _token_for(user_id: str) -> str:
    """A Supabase-shaped HS256 JWT for ``user_id``."""

    now = int(time.time())
    return pyjwt.encode(
        {"sub": user_id, "aud": "authenticated", "iat": now, "exp": now + 300},
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture
async def cloud_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """The cloud FastAPI app over the in-memory SQLite test DB, auth enabled.

    The ``monkeypatch``-on-``settings`` form — see the module docstring for why
    the ``importlib.reload`` variant is not usable at this point in collection
    order. ``database_url`` is a property derived from ``environment``, so the
    in-memory URL follows from the same patch, and clearing ``_engine`` is what
    makes the next ``get_engine()`` build against it.

    PATCHED ON EVERY INSTANCE THE REQUEST PATH READS, not just on
    ``jobtracker.config.settings``. ``settings`` is meant to be a singleton held
    by reference, and it is — right up until a module earlier in collection
    order calls ``importlib.reload(jobtracker.config)``. That mints a SECOND
    settings object and rebinds ``config_module.settings`` to it, while
    ``jobtracker.auth.supabase_jwt`` and ``jobtracker.database.connection`` keep
    their ``from jobtracker.config import settings`` bindings pointed at the
    first. Eight modules sorting before this one do exactly that (#582), so
    patching only ``config_module.settings`` sets the JWT secret on an object
    the verifier never reads and every request comes back
    ``401 Invalid signature`` — green alone, red in a full run.

    De-duplicated by identity, so this is a no-op extra write in the ordinary
    case where all three names are the same object.
    """

    import jobtracker.auth.supabase_jwt as auth_module
    import jobtracker.config as config_module
    import jobtracker.database.connection as connection_module

    holders = {
        id(module.settings): module.settings
        for module in (config_module, auth_module, connection_module)
    }
    for instance in holders.values():
        monkeypatch.setattr(instance, "environment", "test")
        monkeypatch.setattr(instance, "deployment", "cloud")
        monkeypatch.setattr(instance, "supabase_jwt_secret", JWT_SECRET)

    connection_module._engine = None

    from jobtracker.database import init_db

    await init_db()

    import jobtracker.main_cloud as main_cloud_module

    yield main_cloud_module.app

    if connection_module._engine is not None:
        await connection_module._engine.dispose()
    connection_module._engine = None


@pytest.fixture
async def client(cloud_app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=cloud_app)
    async with AsyncClient(transport=transport, base_url="http://cloud-test") as c:
        yield c


@pytest.fixture
def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token_for(OWNER)}"}


@pytest.fixture
async def seeded(cloud_app) -> dict[str, int]:
    """One live card, one dismissed card, and the four messages of OWNER_MAIL.

    Written straight at the session rather than through the API: the state under
    test is one a re-sync produces (a dismissal and a re-classification in the
    same pass), and there is no endpoint that leaves a NEEDS_REVIEW message
    linked to a dismissed row.
    """

    from jobtracker.database import get_session

    owner = uuid.UUID(OWNER)
    application_ids: dict[str, int] = {}

    async with get_session() as session:
        for company, dismissed_at, dismissed_reason in (
            (LIVE_COMPANY, None, None),
            # `resync` and not `user`: the production row was removed by the
            # 2026-08-22 re-sync, and the reason column is what says who.
            (DISMISSED_COMPANY, datetime(2026, 8, 22, 5, 2, 29), "resync"),
        ):
            row = Application(
                user_id=owner,
                company=company,
                position="Software Engineer",
                status=ApplicationStatus.APPLIED,
                source="gmail_auto",
                dismissed_at=dismissed_at,
                dismissed_reason=dismissed_reason,
            )
            session.add(row)
            await session.flush()
            application_ids[company] = row.id

        for index, (message_id, thread_id, subject, link, is_reviewed) in enumerate(
            OWNER_MAIL
        ):
            session.add(
                Email(
                    user_id=owner,
                    application_id=(
                        application_ids[link] if link is not None else None
                    ),
                    source_account=EmailSource.GMAIL,
                    message_id=message_id,
                    thread_id=thread_id,
                    subject=subject,
                    sender_name="Careers",
                    sender_email="donotreply@email.careers.example.test",
                    received_at=RECEIVED_AT - timedelta(minutes=index),
                    body_snippet="We have received your application.",
                    classified_as=EmailCategory.NEEDS_REVIEW,
                    classification_confidence=0.80,
                    is_reviewed=is_reviewed,
                )
            )

        await session.commit()

    return application_ids


async def _queue_message_ids(client: AsyncClient, headers: dict[str, str]) -> set[str]:
    resp = await client.get("/applications/review", headers=headers)
    assert resp.status_code == 200, resp.text
    return {item["message_id"] for item in resp.json()["items"]}


# =============================================================================
# The positive control — a corpus that seeded nothing would pass everything
# =============================================================================


async def test_the_fixture_set_is_what_the_tests_assume(client, headers, seeded):
    """Runs first. Pins the seeded rows against the literals below them.

    Both applications exist, exactly one is on the board, and all four messages
    are stored at ``NEEDS_REVIEW``. Without this the queue assertions would be
    green against a database in which the seed silently wrote nothing.
    """

    resp = await client.get("/applications/mail", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["total"] == len(OWNER_MAIL)
    assert body["category_counts"] == {"needs_review": EXPECTED_STORED_NEEDS_REVIEW}

    linked = {m["message_id"]: m["application_id"] for m in body["messages"]}
    assert linked["m-unlinked"] is None
    assert linked["m-dismissed"] == seeded[DISMISSED_COMPANY]
    assert linked["m-dismissed-reviewed"] == seeded[DISMISSED_COMPANY]
    assert linked["m-live"] == seeded[LIVE_COMPANY]

    board = await client.get("/applications", headers=headers)
    assert board.status_code == 200, board.text
    companies = [row["company"] for row in board.json()["applications"]]
    assert companies == [LIVE_COMPANY], (
        "the dismissed card is supposed to be off the board — if it is on it, "
        "the whole premise of this module is not being exercised"
    )


# =============================================================================
# The three cases
# =============================================================================


async def test_a_message_linked_to_a_dismissed_card_is_back_in_the_queue(
    client, headers, seeded
):
    """THE FIX. Email 108's shape, and it was reachable from nothing.

    MUTATION: restore ``Email.application_id.is_(None)`` in
    ``review_queue_cloud`` and this fails — ``m-dismissed`` is absent, which is
    production's state.
    """

    assert "m-dismissed" in await _queue_message_ids(client, headers)


async def test_a_message_linked_to_a_live_card_stays_out_of_the_queue(
    client, headers, seeded
):
    """THE REGRESSION GUARD, and the reason the fix is not "drop the clause".

    A card the user can see already answers for its mail. Dropping the link
    clause outright would put every filed message back in front of them.

    MUTATION: replace the predicate with no link condition at all and this
    fails — ``m-live`` appears.
    """

    assert "m-live" not in await _queue_message_ids(client, headers)


async def test_an_unlinked_message_is_still_in_the_queue(client, headers, seeded):
    """The case that always worked, asserted so the fix cannot lose it."""

    assert "m-unlinked" in await _queue_message_ids(client, headers)


async def test_a_message_the_user_already_reviewed_stays_out(client, headers, seeded):
    """``is_reviewed`` is a human answer, and a dismissal does not un-answer it.

    MUTATION: drop ``Email.is_reviewed == False`` and this fails —
    ``m-dismissed-reviewed`` appears.
    """

    assert "m-dismissed-reviewed" not in await _queue_message_ids(client, headers)


async def test_the_queue_holds_exactly_the_two_reachable_messages(
    client, headers, seeded
):
    """The four cases stated as one set, so a fix cannot pass three and add a
    fifth row from somewhere else."""

    in_queue = await _queue_message_ids(client, headers)
    assert in_queue == EXPECTED_IN_QUEUE
    assert not (in_queue & EXPECTED_OUT_OF_QUEUE)


# =============================================================================
# The dashboard tile reads the same predicate as the queue it links to
# =============================================================================


async def test_the_dashboard_tile_counts_what_the_queue_lists(client, headers, seeded):
    """7 → 8 on production, 1 → 2 here.

    The tile is a link to the queue, so a tile that counts a different set sends
    the user to a screen that disagrees with the number they clicked. Both read
    :func:`_not_filed_on_a_live_application`, which is why they cannot drift.

    MUTATION: revert the summary handler's predicate alone and this fails at 1
    while the queue lists 2.
    """

    resp = await client.get("/applications/summary", headers=headers)
    assert resp.status_code == 200, resp.text

    assert resp.json()["needs_review"] == len(EXPECTED_IN_QUEUE)
    assert len(await _queue_message_ids(client, headers)) == len(EXPECTED_IN_QUEUE)


# =============================================================================
# What must NOT move: the inbox's stored-mail count, and the badge that already
# tells the truth
# =============================================================================


async def test_the_inbox_stored_mail_count_does_not_move(client, headers, seeded):
    """THE ANTI-RECONCILIATION GUARD (#445, #576).

    The inbox is an audit surface: one entry per stored message, whatever its
    linkage or reviewed state. It is therefore always the LARGER number, and the
    gap is exactly the messages the queue has no question about. A change that
    made the two equal would have reconciled two counts that are allowed to
    differ instead of fixing the queue's predicate.
    """

    resp = await client.get(
        "/applications/mail", params={"category": "needs_review"}, headers=headers
    )
    assert resp.status_code == 200, resp.text

    stored = resp.json()["total"]
    assert stored == EXPECTED_STORED_NEEDS_REVIEW
    assert stored > len(EXPECTED_IN_QUEUE), (
        "the inbox's stored-mail count collapsed onto the work queue's; these "
        "two are labelled apart on purpose and must not be made equal"
    )


async def test_the_inbox_does_not_call_a_dismissed_row_on_your_board(
    client, headers, seeded
):
    """#481's second defect, and it is ALREADY FIXED — this locks it.

    The badge reads ``on_board``, which the mail listing resolves from
    ``Application.dismissed_at`` in the same query that resolves the employer
    (#489/#491). It is a DIFFERENT predicate from the queue's, so this passes
    with no product change; it is asserted here because the two defects share a
    row and the next reader should not have to re-derive which half was live.

    MUTATION: build ``on_board_applications`` from every fetched pair instead of
    the ``dismissed_at is None`` ones and this fails.
    """

    resp = await client.get("/applications/mail", headers=headers)
    assert resp.status_code == 200, resp.text
    on_board = {m["message_id"]: m["on_board"] for m in resp.json()["messages"]}

    assert on_board["m-dismissed"] is False
    assert on_board["m-dismissed-reviewed"] is False
    assert on_board["m-live"] is True
    assert on_board["m-unlinked"] is False
