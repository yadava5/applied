"""The SYNC's settled-test — a dismissed link must not swallow arriving mail.

Why this file exists
--------------------

One idea, "this question is already answered", was spelled twice. #587 moved
the READ path (``GET /applications/review`` and the ``needs_review`` tile on
``GET /applications/summary``) to ``_not_filed_on_an_application_that_answers``. The
WRITE path — :func:`applications._persist_review_items_additive`, the settled
filter every routine sync runs — kept the predicate that replaced:

    ``Email.application_id IS NOT NULL OR Email.is_reviewed``

A row linked to a DISMISSED card satisfies ``application_id IS NOT NULL``, so
the sync called it settled. It does not merely skip such a row: it collects
their ``pipeline.review_dedup_key``s into ``settled_applications`` and filters
EVERY arriving ref against that set. So a stranded row the queue is currently
showing suppressed the NEW mail arriving on its thread with the same identity.
That message was never stored, never queued, never counted — the corpus's
``LOST`` mode (#596).

DO NOT ASSERT THIS AT THE QUEUE. READ THIS BEFORE ADDING A TEST HERE
--------------------------------------------------------------------

A queue-level assertion CANNOT see this bug, and adding one here would be a
check that cannot fail. The stranded row is already in the queue (that is what
#587 fixed), and the suppressed sibling shares its ``review_dedup_key`` **by
construction** — the key match is precisely why it was suppressed. Both
``GET /applications/review`` and the ``needs_review`` tile collapse a thread's
siblings to ONE entry, so the queue reads identically before and after the fix.
The issue's own reproduction shows it: ``QUEUE after the sync: ['m-stranded']``
in both worlds.

The observable difference is at the STORAGE BOUNDARY only, so that is what is
asserted here, two ways for every case:

* the row exists in ``GET /applications/mail`` — the audit surface, one entry
  per stored message whatever its linkage (#445/#576), and
* the persist's own return count, which is how many dated refs survived the
  filter.

The case matrix, and what the mutation is expected to do to it
--------------------------------------------------------------

A sibling ARRIVES on the thread of a stored row that is:

================================  ==============  ================================
stored row                        arriving ref    why
================================  ==============  ================================
unlinked, un-reviewed             STORED          unchanged behaviour
linked to a RESYNC-dismissed card STORED          **the #596 fix**
linked to a USER-dismissed card   suppressed      **#597, and it FLIPPED**
linked to a LIVE card             suppressed      **the regression guard**
``is_reviewed`` + resync-dismissed suppressed     the arm a careless rewrite drops
linked to a STRANGER's card       STORED          the write-path-only scoping case
================================  ==============  ================================

THE THIRD ROW USED TO READ "STORED", AND SAYING SO IS THE POINT. When this
module shipped, the settled-test read ``dismissed_at`` alone: every dismissal
un-settled its mail, so the sibling arriving behind a hand-dismissed card was
stored and queued exactly like the resync one. #597 decided that a hand
dismissal is FINAL — the user said "this is not an application" and fresh mail
on that card does not reopen the question — so the row flips to suppressed.
The table is rewritten rather than appended to because "dismissed → stored" is
no longer a true row of it, and a table carrying both the old claim and its
replacement would document a product that does not exist.

The two dismissal cases are now DIRECTIONAL: same ``dismissed_at``, opposite
``dismissed_reason``, opposite answer. One "dismissed" case could never have
told them apart.

The last one has no read-path twin and cannot get one: a cross-user link is a
stale link, and no endpoint will ever create the row, so only the write path
can be asked about it.

TWO MUTATIONS, because there are now two clauses to prove.

#596's. Swap the write path's ``_filed_on_an_application_that_answers(user_id)``
back to ``Email.application_id.is_not(None)`` — a same-typed swap, SQL boolean
for SQL boolean, and exactly the pre-fix state. Then and only then:

* ``…resync_dismissed_card…`` REDS,
* ``…another_users_card…`` REDS,
* ``…all_six_cases…`` REDS,
* the LIVE arm, the ``is_reviewed`` arm, the unlinked arm and the
  USER-dismissed arm stay GREEN. The first three are settled (or unsettled)
  identically under both spellings; the fourth is settled under both — by the
  ``dismissed_reason`` clause here, by the bare link test there — which is
  precisely why it needs the OTHER mutation to be worth anything.

#597's. Swap ``DISMISSED_BY_USER`` for ``DISMISSED_BY_RESYNC`` inside
:func:`_filed_on_an_application_that_answers` — one reason constant for the
other, same type, same column. Then:

* ``…user_dismissed_card…`` REDS (the sibling is stored again),
* ``…resync_dismissed_card…`` REDS (it is suppressed instead),
* ``…all_six_cases…`` REDS,
* the LIVE, ``is_reviewed``, unlinked and stranger arms stay GREEN — none of
  them names a dismissal reason at all.

If an arm predicted GREEN reds, the FIXTURE is wrong, not the product. If an
arm predicted RED stays green the test is vacuous.

The fixture positive control
----------------------------

:func:`test_the_fixture_set_is_what_the_tests_assume` exists because an
arriving ref can no-op BEFORE the settled-test is ever consulted, in two
directions, each of which would make a different half of the matrix pass for
the wrong reason:

* an UNDATED ref is skipped outright by ``_persist_message_refs`` (the Email
  row requires a receive time and none is ever fabricated), which would make
  the two "suppressed" arms pass with the predicate never reached;
* an arriving ``message_id`` colliding with a seeded one is an UPSERT of the
  existing row, not a new one, which would make the three "stored" arms pass
  against a row the fixture wrote itself.

So the control pins that the arriving ids are disjoint from the seeded ones and
that a ref of exactly this shape, on a thread holding no stored row, is
surfaced and stored.

The fixture form is the #582-safe one
-------------------------------------

``monkeypatch.setattr(settings, ...)`` on every settings instance the request
path holds, and NOT the env-var-plus-``importlib.reload(jobtracker.config)``
shape. Eight modules reload ``jobtracker.config`` during collection, which
mints a second settings object while ``jobtracker.auth.supabase_jwt`` and
``jobtracker.database.connection`` keep their bindings on the first; patching
one instance then sets the JWT secret on an object the verifier never reads and
every request comes back ``401 Invalid signature`` — green alone, red in a full
run. See ``test_dismissed_card_does_not_settle_its_mail.py``'s fixture for the
measurement.

Every employer, sender, requisition and role below is INVENTED and every
address is under ``example.test``. Nothing in this file, its fixtures or its
prose comes from a real mailbox (#593).
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any, NamedTuple

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
JWT_SECRET = "arriving-sibling-write-path-secret-at-least-32-bytes"
OWNER = "c4c4c4c4-c4c4-4c4c-8c4c-c4c4c4c4c4c4"
# Holds a LIVE card the owner's mail is stale-linked to. Never authenticates.
STRANGER = "d5d5d5d5-d5d5-4d5d-8d5d-d5d5d5d5d5d5"

SEEDED_AT = datetime(2026, 8, 20, 11, 30, 0)
# Strictly later, and dated — an undated ref never reaches the settled-test.
ARRIVED_AT = datetime(2026, 8, 26, 9, 15, 0)

# Invented employers. No real mailbox material anywhere in this module.
LIVE_COMPANY = "Halberd Dynamics"
RESYNC_DISMISSED_COMPANY = "Ironvale Freight"
# Its own employer, not a second card at ``RESYNC_DISMISSED_COMPANY``: one
# employer holding both reasons would make each assertion depend on which row
# ``_company_rows`` returned first, which is luck rather than a property.
USER_DISMISSED_COMPANY = "Cindervale Robotics"
STRANGER_COMPANY = "Marrowgate Analytics"


class Case(NamedTuple):
    """One stored row, and the sibling that arrives on its thread later.

    ``link`` names the application the stored row is filed against (``None``
    for an unlinked row); ``owner`` says whose card that is. ``arriving_stored``
    is the assertion: does the sibling survive the sync's settled filter?
    """

    key: str
    subject: str
    snippet: str
    link: str | None
    link_owner: str | None
    is_reviewed: bool
    arriving_stored: bool


# The snippet is short on purpose. ``pipeline.review_dedup_key`` truncates the
# STORED side to ``STORED_SNIPPET_CHARS`` (500) before deriving identity while
# the arriving ref passes its own snippet whole; a snippet long enough to be cut
# could give the two sides different identities and stop them colliding, which
# would make every "suppressed" arm pass for no reason at all.
CASES: tuple[Case, ...] = (
    # Always worked: nothing about an unlinked, un-reviewed row is settled.
    Case(
        key="unlinked",
        subject="Following up on your interest",
        snippet="We would like to learn more about your background.",
        link=None,
        link_owner=None,
        is_reviewed=False,
        arriving_stored=True,
    ),
    # THE FIX. The link outlived the verdict that justified it: a re-sync
    # dismissed the card and re-parked the message in the same pass.
    Case(
        key="resync-dismissed-card",
        subject="Your application to Ironvale Freight",
        snippet="Requisition IVF-40188, Backend Engineer.",
        link=RESYNC_DISMISSED_COMPANY,
        link_owner=OWNER,
        is_reviewed=False,
        arriving_stored=True,
    ),
    # #597, AND THE ROW THAT FLIPPED. Byte-identical to the case above but for
    # the employer and the reason on its card. The user removed this one by
    # hand, so their "no" answers for the whole thread and the sibling arriving
    # behind it is suppressed rather than queued.
    Case(
        key="user-dismissed-card",
        subject="Your application to Cindervale Robotics",
        snippet="Requisition CVR-40188, Backend Engineer.",
        link=USER_DISMISSED_COMPANY,
        link_owner=OWNER,
        is_reviewed=False,
        arriving_stored=False,
    ),
    # THE REGRESSION GUARD. A card the user can see answers for its own thread,
    # and the fix must not become "is_reviewed alone".
    Case(
        key="live-card",
        subject="Your application to Halberd Dynamics",
        snippet="Requisition HBD-20514, Platform Engineer.",
        link=LIVE_COMPANY,
        link_owner=OWNER,
        is_reviewed=False,
        arriving_stored=False,
    ),
    # The arm a careless rewrite drops. ``is_reviewed`` records that a human
    # answered; removing the card does not un-answer it.
    Case(
        key="reviewed-on-a-dismissed-card",
        subject="Update on your Ironvale Freight application",
        snippet="Requisition IVF-77301, Data Engineer.",
        link=RESYNC_DISMISSED_COMPANY,
        link_owner=OWNER,
        is_reviewed=True,
        arriving_stored=False,
    ),
    # The write path's own scoping case. A stale link at a LIVE card that is
    # NOT the owner's answers nothing the owner can see.
    Case(
        key="another-users-card",
        subject="Your application to Marrowgate Analytics",
        snippet="Requisition MGA-51120, Analytics Engineer.",
        link=STRANGER_COMPANY,
        link_owner=STRANGER,
        is_reviewed=False,
        arriving_stored=True,
    ),
)

BY_KEY = {case.key: case for case in CASES}

# Hardcoded, so a mistake in the table above cannot quietly redefine what is
# proved; the fixture control reconciles the two. A derived-only expectation
# agrees with any corpus, including an empty one.
SEEDED_IDS = frozenset(f"s-{case.key}" for case in CASES)
EXPECTED_STORED_AFTER_FULL_SYNC = SEEDED_IDS | {
    "a-unlinked",
    "a-resync-dismissed-card",
    "a-another-users-card",
}
EXPECTED_SURFACED_BY_FULL_SYNC = 3

# A thread this database has never seen — the control's own arriving ref.
UNSEEN = Case(
    key="never-seen",
    subject="Your application to Halberd Dynamics",
    snippet="Requisition HBD-99002, Reliability Engineer.",
    link=None,
    link_owner=None,
    is_reviewed=False,
    arriving_stored=True,
)


def _sender_for(case: Case) -> str:
    return f"careers+{case.key}@ats.example.test"


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

    Patched on EVERY settings instance the request path reads — see the module
    docstring for #582 and why the single-instance form is green alone and red
    in a full run. De-duplicated by identity, so the extra writes are a no-op in
    the ordinary case where all three names are the same object.
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
    """Four cards and the six stored rows of :data:`CASES`.

    Written straight at the session rather than through the API: two of these
    states are ones only a re-sync produces (a NEEDS_REVIEW message still linked
    to a card the same pass dismissed, and a link left pointing at a row that is
    not the owner's), and no endpoint offers to create either.

    ``identity_role``/``identity_req_id`` are left NULL deliberately. Both sides
    of :func:`pipeline.review_dedup_key` then derive identity from subject plus
    snippet, which is what makes the arriving sibling collide with its stored
    row — and colliding is the whole mechanism under test.
    """

    from jobtracker.database import get_session

    application_ids: dict[str, int] = {}

    async with get_session() as session:
        for company, owner, dismissed_at, dismissed_reason in (
            (LIVE_COMPANY, OWNER, None, None),
            # `resync` and not `user`: the state #481 found was produced by a
            # re-sync, and the reason column is what says who removed the row.
            (
                RESYNC_DISMISSED_COMPANY,
                OWNER,
                datetime(2026, 8, 22, 5, 2, 29),
                "resync",
            ),
            # THE SAME `dismissed_at`, the opposite reason (#597). Sharing the
            # timestamp is deliberate: it leaves the reason column as the only
            # variable between this card and the one above it.
            (
                USER_DISMISSED_COMPANY,
                OWNER,
                datetime(2026, 8, 22, 5, 2, 29),
                "user",
            ),
            # LIVE, and not the owner's. Dismissing it would collapse this case
            # into the one above and it would discriminate nothing.
            (STRANGER_COMPANY, STRANGER, None, None),
        ):
            row = Application(
                user_id=uuid.UUID(owner),
                company=company,
                position="Backend Engineer",
                status=ApplicationStatus.APPLIED,
                source="gmail_auto",
                dismissed_at=dismissed_at,
                dismissed_reason=dismissed_reason,
            )
            session.add(row)
            await session.flush()
            application_ids[company] = row.id

        for index, case in enumerate(CASES):
            session.add(
                Email(
                    # The MAIL row is always the owner's, including the
                    # stale-linked one; the asymmetry of the last case lives
                    # entirely in who owns the application.
                    user_id=uuid.UUID(OWNER),
                    application_id=(
                        application_ids[case.link] if case.link is not None else None
                    ),
                    source_account=EmailSource.GMAIL,
                    message_id=f"s-{case.key}",
                    thread_id=f"t-{case.key}",
                    subject=case.subject,
                    sender_name="Careers",
                    sender_email=_sender_for(case),
                    received_at=SEEDED_AT - timedelta(minutes=index),
                    body_snippet=case.snippet,
                    classified_as=EmailCategory.NEEDS_REVIEW,
                    classification_confidence=0.78,
                    is_reviewed=case.is_reviewed,
                )
            )

        await session.commit()

    return application_ids


def _arriving(case: Case):
    """The sibling a LATER sync hands the additive persist.

    Same thread, same subject, same snippet as the stored row — which is what
    makes the two share a ``review_dedup_key``, and so what makes the settled
    filter able to suppress it. A NEW ``message_id``, so nothing here is an
    upsert of the seeded row.
    """

    from jobtracker.cloud import pipeline

    return pipeline.ReviewItem(
        message_id=f"a-{case.key}",
        thread_id=f"t-{case.key}",
        subject=case.subject,
        sender_email=_sender_for(case),
        sender_name="Careers",
        received_at=ARRIVED_AT,
        category="applied",
        confidence=0.61,
        company_display=None,
        snippet=case.snippet,
    )


async def _sync(*cases: Case) -> int:
    """Run the write path for real and return how many refs it surfaced.

    Called directly rather than over HTTP: the thing under test is the settled
    filter inside :func:`_persist_review_items_additive`, and reaching it
    through ``POST /gmail/sync`` would mean standing up the whole scan.
    """

    from jobtracker.cloud.applications import _persist_review_items_additive
    from jobtracker.database import get_session

    async with get_session() as session:
        surfaced = await _persist_review_items_additive(
            session, uuid.UUID(OWNER), [_arriving(case) for case in cases]
        )
        await session.commit()
    return surfaced


async def _stored_message_ids(client: AsyncClient, headers: dict[str, str]) -> set[str]:
    """Every message id in ``GET /applications/mail`` — the audit surface.

    NOT the review queue. The queue collapses a thread's siblings into one
    entry and reads identically either side of this fix; see the module
    docstring.
    """

    resp = await client.get("/applications/mail", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == len(body["messages"]), (
        "the mail listing paged, so the set below is not the whole corpus"
    )
    return {message["message_id"] for message in body["messages"]}


# =============================================================================
# The positive control — an arriving ref that no-ops never reaches the predicate
# =============================================================================


async def test_the_fixture_set_is_what_the_tests_assume(client, headers, seeded):
    """Runs first. Pins the seed, and proves an arriving ref REACHES the test.

    Three claims, and each closes a way this module could be green while
    proving nothing:

    1. the six rows exist, stored at ``needs_review``, linked as the table
       says — including the cross-user link, which is the case no endpoint can
       create;
    2. the arriving ids are DISJOINT from the seeded ones, so a "stored" arm is
       never an upsert of a row the fixture itself wrote;
    3. a ref of exactly the arriving shape, on a thread holding no stored row,
       is surfaced and stored. That is what says the refs are dated — an
       undated one is dropped by ``_persist_message_refs`` before any settled
       filter is consulted, and both "suppressed" arms would pass vacuously.
    """

    resp = await client.get("/applications/mail", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["total"] == len(CASES)
    assert body["category_counts"] == {"needs_review": len(CASES)}

    linked = {m["message_id"]: m["application_id"] for m in body["messages"]}
    assert set(linked) == set(SEEDED_IDS)
    assert linked["s-unlinked"] is None
    assert linked["s-resync-dismissed-card"] == seeded[RESYNC_DISMISSED_COMPANY]
    assert linked["s-user-dismissed-card"] == seeded[USER_DISMISSED_COMPANY]
    assert (
        linked["s-reviewed-on-a-dismissed-card"] == seeded[RESYNC_DISMISSED_COMPANY]
    )
    assert linked["s-live-card"] == seeded[LIVE_COMPANY]
    assert linked["s-another-users-card"] == seeded[STRANGER_COMPANY], (
        "the stale cross-user link is the premise of one whole case; without it "
        "that test is asking about an ordinary owned link"
    )

    board = await client.get("/applications", headers=headers)
    assert board.status_code == 200, board.text
    assert [row["company"] for row in board.json()["applications"]] == [LIVE_COMPANY], (
        "both dismissed cards must be off the board and the stranger's card "
        "must never have been on it"
    )

    # DIRECTIONAL CONTROL for the pair the whole #597 half rests on: the two
    # dismissed cards differ in the reason column and in nothing else. Read at
    # the session because no endpoint of the owner's shows a dismissed row's
    # reason alongside its timestamp.
    from sqlmodel import select

    from jobtracker.database import get_session

    async with get_session() as session:
        rows = {
            row.company: (row.dismissed_at, row.dismissed_reason)
            for row in (
                await session.exec(
                    select(Application).where(Application.user_id == uuid.UUID(OWNER))
                )
            ).all()
        }

    assert rows[RESYNC_DISMISSED_COMPANY][1] == "resync"
    assert rows[USER_DISMISSED_COMPANY][1] == "user"
    assert (
        rows[RESYNC_DISMISSED_COMPANY][0]
        == rows[USER_DISMISSED_COMPANY][0]
        is not None
    ), "the two dismissed rows must differ in the REASON and nothing else"

    # The hardcoded expectations, reconciled against the table they describe.
    # Hardcoding is what stops a mistake in ``CASES`` quietly redefining what is
    # proved; this is what stops the two drifting apart instead.
    stored_by_the_table = {f"a-{c.key}" for c in CASES if c.arriving_stored}
    assert len(stored_by_the_table) == EXPECTED_SURFACED_BY_FULL_SYNC
    assert SEEDED_IDS | stored_by_the_table == EXPECTED_STORED_AFTER_FULL_SYNC

    arriving_ids = {f"a-{case.key}" for case in CASES}
    assert not (arriving_ids & SEEDED_IDS), (
        "an arriving message_id that collides with a seeded one is an UPSERT, "
        "not a new row, and every 'stored' assertion below would be vacuous"
    )

    assert await _sync(UNSEEN) == 1, (
        "a ref of this exact shape, on a thread with nothing stored, was not "
        "surfaced — so the refs never reach the settled-test at all and the "
        "suppression assertions prove nothing"
    )
    assert f"a-{UNSEEN.key}" in await _stored_message_ids(client, headers)


# =============================================================================
# The six cases, one arriving sibling at a time
# =============================================================================


async def test_a_sibling_of_an_unlinked_row_is_stored(client, headers, seeded):
    """Unchanged behaviour, asserted so the fix cannot lose it.

    Nothing about an unlinked, un-reviewed row is settled under either
    spelling, so this stays green under the mutation.
    """

    case = BY_KEY["unlinked"]
    assert await _sync(case) == 1
    assert f"a-{case.key}" in await _stored_message_ids(client, headers)


async def test_a_sibling_of_a_row_on_a_resync_dismissed_card_is_stored(
    client, headers, seeded
):
    """THE #596 FIX, and the LOST mode it closes.

    The stored row is linked to a card a RE-SYNC dismissed. The queue shows it
    as an open question; the sync used to treat it as the answer and drop the
    mail arriving behind it.

    MUTATION (#596's): swap ``_filed_on_an_application_that_answers(user_id)``
    in ``_persist_review_items_additive`` back to
    ``Email.application_id.is_not(None)`` and this fails — the arriving sibling
    is not stored at all, which is production's state.

    MUTATION (#597's): swap the reason constant and this fails too, the other
    way — the resync card starts answering and the sibling is suppressed.
    """

    case = BY_KEY["resync-dismissed-card"]
    assert await _sync(case) == 1, (
        "the arriving sibling was filtered out as settled by a card that a "
        "machine removed and the user cannot see"
    )
    assert f"a-{case.key}" in await _stored_message_ids(client, headers)


async def test_a_sibling_of_a_row_on_a_user_dismissed_card_is_not_stored(
    client, headers, seeded
):
    """#597, AND IT IS THE ROW THIS MODULE USED TO ASSERT THE OTHER WAY.

    A human took this card off the board. That is a standing instruction, not a
    verdict a later message may argue with, so the whole thread is answered:
    the arriving sibling is filtered out as settled and never stored.

    The directional twin of the resync case above — same ``dismissed_at``, same
    un-reviewed stored row, same arriving shape, opposite ``dismissed_reason``,
    opposite answer.

    MUTATION (#597's): swap ``DISMISSED_BY_USER`` for ``DISMISSED_BY_RESYNC``
    in :func:`_filed_on_an_application_that_answers` and this fails — the
    sibling is stored, which is what the product did before this change.

    MUTATION (#596's): GREEN. ``application_id IS NOT NULL`` is true of this
    link too, so the old spelling suppressed it for a different reason. That is
    exactly why one dismissal case could not carry both claims.
    """

    case = BY_KEY["user-dismissed-card"]
    assert await _sync(case) == 0, (
        "mail arriving on a card the user dismissed by hand was surfaced again "
        "— the queue is asking about an application they removed on purpose"
    )
    assert f"a-{case.key}" not in await _stored_message_ids(client, headers)


async def test_a_sibling_of_a_row_on_a_live_card_is_still_suppressed(
    client, headers, seeded
):
    """THE REGRESSION GUARD, and the reason the fix is not ``is_reviewed`` alone.

    A card the user can see already answers for its thread. Without this arm a
    "fix" that deleted the link clause outright would pass every other case
    here and re-ask a question the board has already answered.

    This is also the dedup-key control: the arriving ``message_id`` is new, so
    ``settled_messages`` cannot fire and the suppression can only have come
    from ``settled_applications`` — i.e. the two really do share a key.

    MUTATION: green under the swap. Both spellings call this row settled.
    """

    case = BY_KEY["live-card"]
    assert await _sync(case) == 0
    assert f"a-{case.key}" not in await _stored_message_ids(client, headers)


async def test_a_sibling_of_a_reviewed_row_on_a_dismissed_card_is_suppressed(
    client, headers, seeded
):
    """``is_reviewed`` is a human answer and a dismissal does not un-answer it.

    The arm a careless rewrite drops. The read path's helper is explicit that
    this is NOT a widening of ``is_reviewed``: every caller keeps that clause,
    the readers as ``is_reviewed == False`` and the sync as the other arm of
    its ``or_``.

    MUTATION: green under both swaps. Settled every way, on ``is_reviewed``.
    """

    case = BY_KEY["reviewed-on-a-dismissed-card"]
    assert await _sync(case) == 0
    assert f"a-{case.key}" not in await _stored_message_ids(client, headers)


async def test_a_sibling_of_a_row_on_another_users_card_is_stored(
    client, headers, seeded
):
    """The write path's own scoping case — no read-path test can cover it.

    A stale link pointing at a LIVE application that belongs to somebody else.
    The read path's helper scopes its subquery to ``user_id`` for exactly this
    reason (#489), but no endpoint will ever create the row, so the claim can
    only be made where a sync can meet one.

    MUTATION: REDS under the swap — ``application_id IS NOT NULL`` is true of a
    link the owner cannot resolve, so the arriving sibling was dropped.
    """

    case = BY_KEY["another-users-card"]
    assert await _sync(case) == 1
    assert f"a-{case.key}" in await _stored_message_ids(client, headers)


# =============================================================================
# All six in ONE sync, which is the shape a real delta has
# =============================================================================


async def test_one_sync_carrying_all_six_cases_stores_exactly_three(
    client, headers, seeded
):
    """The matrix as one set, so a fix cannot pass five arms and add a sixth row.

    A sync does not arrive one message at a time, and the settled filter is
    built ONCE per call over every thread the batch names — a per-case run
    cannot show that one case's stored row does not settle another's arriving
    sibling.

    MUTATION: REDS under either swap — #596's at two of the three stored ids,
    #597's by storing ``a-user-dismissed-card`` and dropping
    ``a-resync-dismissed-card``.
    """

    assert await _sync(*CASES) == EXPECTED_SURFACED_BY_FULL_SYNC
    assert await _stored_message_ids(client, headers) == EXPECTED_STORED_AFTER_FULL_SYNC


# =============================================================================
# The refusal is COUNTED — the only place the drop is observable (#630)
# =============================================================================
#
# A ref this filter refuses is dropped before ``_persist_message_refs``, so it
# gets no row, no queue entry and no counter. Every test above asserts the
# refusal by its ABSENCE — a message id missing from the audit surface — which
# is the only evidence there was. Absence is not evidence a later query can
# find, so the rate of #630's class in a running mailbox was unobservable by
# construction, and the read-only count against the owner's real mail on
# 2026-09-02 could only ever measure the PRECONDITION for a drop (0 pairs
# written in a later sync than a settled row sharing their thread).
#
# The log line is therefore the ONLY production instrument. These two tests are
# directional on purpose: one proves it fires with the right numbers, the other
# proves it stays silent when nothing was refused. A counter that always logs
# and a counter that never logs both pass a one-sided test.


def _every_arriving_ref_is_dated(cases) -> None:
    """The precondition that makes ``len(batch) - surfaced`` an exact refusal count.

    Both persist functions return a count of DATED refs, so an UNDATED ref would
    survive the filter and still not be counted as surfaced — and the test above
    would then read a refusal that did not happen. Every case here is dated
    (``ARRIVED_AT`` in :func:`_arriving`), so the two coincide, but that is a
    property of the fixture and not of the code. ``_every_message_is_dated`` in
    ``test_settled_filter_drops_an_uncertain_update.py`` exists for the same
    reason; this is its local twin rather than a shared import, because the two
    modules build their arriving refs differently.
    """

    undated = [c.key for c in cases if _arriving(c).received_at is None]
    assert undated == [], f"an undated ref would be miscounted as refused: {undated}"


def _refusals(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The refusal lines this run emitted, from the sync module's logger only."""

    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "jobtracker.cloud.applications"
        and "Settled filter refused" in record.getMessage()
    ]


async def test_the_refusals_are_counted_and_the_count_is_the_real_one(
    client, headers, seeded, caplog: pytest.LogCaptureFixture
):
    """Six cases in, three surfaced, and the line must say three of six.

    Both numbers are asserted, not just the first. ``refused`` alone is
    satisfiable by a line that reports the batch size, and ``offered`` alone by
    one that reports the surfaced count; only the pair pins which is which.

    The user id is asserted because a log line naming no account cannot be
    read against a mailbox, and this repository has shipped an aggregate with
    no user predicate before.

    MUTATION (deletion, proves the line is PRESENT): drop the ``logger.info``
    block from ``_persist_review_items_additive`` and this reds.

    MUTATION (operand swap, proves the RIGHT VALUE): report ``len(refs)``
    instead of ``refused`` — same type, same scope — and this reds while
    :func:`test_a_batch_that_refuses_nothing_logs_nothing` stays green, which
    is what makes the pair worth having.

    ``UNSEEN`` IS IN THE BATCH TO BREAK A SYMMETRY, and it is load-bearing for
    EXACTLY ONE of those mutations — the ``len(refs)``-as-``refused`` swap. The
    other three red with ``CASES`` alone; this is not a claim that the whole
    table needs it. ``CASES`` alone is six refs of which three survive, so
    ``refused`` and ``len(refs)`` are BOTH 3 and that one swap is an equivalent
    mutant: it changes nothing, the test stays green, and the docstring above
    would be claiming a detection property the test does not have. Seven
    offered, four surfaced and three refused are three distinct numbers.

    THE DISTINCTNESS GUARD IS THE POINT, not the specific batch. It fails if a
    future edit makes any two of the three coincide again, which is the state
    that silently disarms the swap.
    """

    batch = (*CASES, UNSEEN)
    _every_arriving_ref_is_dated(batch)
    with caplog.at_level(logging.INFO, logger="jobtracker.cloud.applications"):
        surfaced = await _sync(*batch)

    # UNSEEN names a thread this database has never held, so it is kept and the
    # surfaced count is one above the six-case constant.
    assert surfaced == EXPECTED_SURFACED_BY_FULL_SYNC + 1
    refused = len(batch) - surfaced
    assert len({refused, surfaced, len(batch)}) == 3, (
        "the batch went symmetric, so the operand swap this test documents "
        "would no longer red it"
    )
    lines = _refusals(caplog)
    assert len(lines) == 1, f"expected exactly one refusal line, got {lines}"
    # `refused` and `offered` in one substring, `surfaced` by the assertion
    # above: two assertions for three numbers, which is what pins each of them
    # exactly once.
    assert f"refused {refused} of {len(batch)}" in lines[0], lines[0]
    # `user_id=` and not a bare substring. Without the key, a line that moved
    # the account id anywhere else — into a message id, a table name — would
    # satisfy this, and the only consumer of this line is a person grepping it.
    assert f"user_id={OWNER}" in lines[0], (
        f"the line does not name the account under `user_id=`: {lines[0]}"
    )


async def test_a_batch_that_refuses_nothing_logs_nothing(
    client, headers, seeded, caplog: pytest.LogCaptureFixture
):
    """The directional control, and it is the half that decides the other one.

    Three arriving refs the filter must KEEP — the unlinked row, the card the
    rebuild dismissed, and a stranger's link — plus a thread this database has
    never seen. Nothing is refused, so nothing may be logged: a line here would
    mean the count is reporting the batch rather than the refusals, and every
    assertion in the test above would then be satisfied by a counter that is
    always wrong in the same direction.

    Asserted as "surfaced == 4" as well, so a run where the filter refused
    everything and the logger was simply broken cannot pass it silently.
    """

    keeps = (
        BY_KEY["unlinked"],
        BY_KEY["resync-dismissed-card"],
        BY_KEY["another-users-card"],
        UNSEEN,
    )
    with caplog.at_level(logging.INFO, logger="jobtracker.cloud.applications"):
        surfaced = await _sync(*keeps)

    assert surfaced == len(keeps), "a case this test assumes is kept was refused"
    assert _refusals(caplog) == [], (
        "the settled filter refused nothing and logged a refusal anyway"
    )
