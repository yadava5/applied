"""What a dismissal MEANS, once the two halves of the product agree (#595/#597).

Why this file exists
--------------------

Two issues, one decision, and neither is testable without the other.

#597 asked whether the review queue should surface mail from a card the user
removed BY HAND. The sync upsert had refused to un-dismiss such a row for
months (``dismissed_reason == DISMISSED_BY_USER`` → ``continue``); the queue
predicate #587 shipped did not read the column at all. So one half of the
product treated a hand dismissal as a standing instruction and the other half
treated every dismissal as a machine's opinion.

#595 asked what happens when the surfaced question is ANSWERED. Nothing did:
``_resolve_application_for_email`` returned the message's own link with no
dismissal test, ``classify_review_item`` filed the mail against it and never
cleared ``dismissed_at``. The message left the queue, ``is_reviewed`` went
true so it would never be asked again, and the board gained nothing. The
reproduction in #595 is a ``200`` naming application 1, a status walked to
``rejected``, and ``BOARD AFTER: []``.

THE DECISION, and it is one rule, not two
-----------------------------------------

**A machine's removal yields to any newer evidence. A human's removal yields to
nothing except the human acting on that same card again.**

  * ``dismissed_reason = 'resync'`` — the rebuild's opinion. Its mail is still
    an open question, it is offered in the queue, and ANSWERING IT PUTS THE
    CARD BACK. That is #595's acceptance criterion, which is the one #481
    named: *answer the surfaced question, and a card appears.*
  * ``dismissed_reason = 'user'`` — a person said "this is not an
    application". Its mail is settled, it is never offered, and no answer
    landing anywhere may revive it. A fresh card is minted beside it instead —
    visible and reversible, where a silent un-dismissal is neither.

What each module in this family proves
--------------------------------------

Three files, and the split is not arbitrary — each owns the surface it can
actually observe:

* ``test_dismissed_card_does_not_settle_its_mail.py`` — the READ path. Which
  messages the queue and the ``needs_review`` tile offer.
* ``test_a_dismissed_link_does_not_settle_arriving_mail.py`` — the WRITE path.
  Which arriving siblings a sync stores at all.
* **this file** — what an ANSWER does to the board. The two above can both be
  green while answering the question changes nothing a user can see, which is
  precisely the state #595 reported.

THE STRUCTURE IS DIRECTIONAL THROUGHOUT. Every claim about ``user`` has a
``resync`` twin on an otherwise identical fixture, because a test that only
ever sees one reason cannot tell "reads ``dismissed_reason``" from "reads
``dismissed_at``" from "reads neither". The pairs:

===========================  =============================  ==================
surface                      ``resync``                     ``user``
===========================  =============================  ==================
review answer on its link    restores the card              mints beside it
the board picker             (its own card is choosable)    refuses the id
the orphan catch-up          restores the card              mints beside it
===========================  =============================  ==================

MUTATION, and its expected red set. Swap ``DISMISSED_BY_USER`` for
``DISMISSED_BY_RESYNC`` inside
:func:`applications._filed_on_an_application_that_answers` — one reason
constant for the other, same type, same column, and it compiles. Then:

* :func:`test_the_fixture_is_reachable_the_way_these_tests_assume` REDS on
  ``in_queue == EXPECTED_IN_QUEUE``. The three LINKED ``resync`` rows become
  answered-for and leave; the linked ``user`` row stops being answered-for and
  arrives. (``m-dunmarrow`` does not move either way — it carries no link, so
  no dismissal reason reaches it.)
* :func:`test_answering_the_surfaced_question_puts_the_card_back` REDS at its
  first assertion — the row it answers is no longer in the queue.
* EVERY OTHER TEST HERE STAYS GREEN, and that is the point rather than a gap.
  The never-restore behaviour lives in ``_resolve_application_for_email`` and
  ``_chosen_application``, which read the reason in PYTHON. The mutation is
  scoped to the SQL clause, so a green here says the exclusion is genuinely a
  second mechanism and not the same one seen twice. Its own mutations —
  deleting the ``not _user_dismissed(linked)`` guard, or the ``candidates``
  filter, or ``_chosen_application``'s — red exactly the tests named in each
  docstring below.

Every employer, sender, requisition and role here is INVENTED and every domain
is RFC-reserved. Nothing in this file comes from a real mailbox (#593).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any, NamedTuple

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from jobtracker.database.models import (
    Application,
    ApplicationStatus,
    Email,
    EmailCategory,
    EmailSource,
)

# 32+ bytes so PyJWT does not warn; the value only has to match the token
# helper. Spelled in the shape `.gitleaks.toml` allowlists BY VALUE — a string
# that says of itself that it is a test JWT secret of an HS256-legal length.
# The free-form variants used by the sibling modules only pass the scanner
# because their entropy happens to fall under the generic rule's threshold;
# this one's did not, which is the failure mode that allowlist entry describes.
JWT_SECRET = "hand-dismissal-test-jwt-secret-at-least-32-bytes-long-hs256"
OWNER = "e6e6e6e6-e6e6-4e6e-8e6e-e6e6e6e6e6e6"

DISMISSED_AT = datetime(2026, 8, 22, 5, 2, 29)
RECEIVED_AT = datetime(2026, 8, 24, 10, 0, 0)


class Card(NamedTuple):
    """One dismissed application and the single message that names it.

    ``linked`` says whether the message carries this card's ``application_id``.
    The catch-up cases are UNLINKED and ``reviewed`` — that is the exact shape
    :func:`reconcile_orphaned_classifications` selects, and a linked row would
    not be an orphan at all.
    """

    company: str
    reason: str
    message_id: str
    category: EmailCategory
    linked: bool
    reviewed: bool


# One employer per case. Sharing an employer between two cases would make each
# assertion depend on which row ``_company_rows`` happened to return first,
# which is luck rather than a property.
CARDS: tuple[Card, ...] = (
    # #595's acceptance card. A re-sync removed it; its mail is an open
    # question, and answering that question has to put it back.
    Card("Brackenhill", "resync", "m-brackenhill", EmailCategory.NEEDS_REVIEW, True, False),
    # #597's never-restore card, reached through the message's OWN LINK.
    Card("Cindervale", "user", "m-cindervale", EmailCategory.NEEDS_REVIEW, True, False),
    # #597 through the BOARD PICKER: the caller names this id explicitly.
    Card("Dunmarrow", "user", "m-dunmarrow", EmailCategory.NEEDS_REVIEW, False, False),
    # The catch-up's never-restore case. Unlinked, reviewed, filing category —
    # an orphan, and the cascade would have landed it on the dismissed card.
    Card("Ellersby", "user", "m-ellersby", EmailCategory.REJECTION, False, True),
    # Its directional twin: the same orphan shape at a MACHINE-dismissed card,
    # which the catch-up has always restored and must go on restoring.
    Card("Foxglade", "resync", "m-foxglade", EmailCategory.REJECTION, False, True),
    # A non-filing answer restores nothing, because no landing occurs.
    Card("Garrowmere", "resync", "m-garrowmere", EmailCategory.NEEDS_REVIEW, True, False),
    # "None of these" mints rather than landing, so it restores nothing either.
    Card("Hallowmere", "resync", "m-hallowmere", EmailCategory.NEEDS_REVIEW, True, False),
)

BY_COMPANY = {card.company: card for card in CARDS}

# Hardcoded, so a mistake in the table above cannot quietly redefine what is
# proved; the fixture control reconciles the two. A derived-only expectation
# agrees with any corpus, including an empty one.
EXPECTED_IN_QUEUE = {
    "m-brackenhill",
    "m-garrowmere",
    "m-hallowmere",
    # UNLINKED, so it is in the queue even though its employer's only card was
    # dismissed by hand — and that is correct, not a leak. The settlement
    # predicate asks "does an application of mine answer for THIS MESSAGE?",
    # which it can only ask through a link. A message carrying none is an open
    # question whatever else is on the board, and refusing to ask would mean
    # inferring settlement from an employer name — the guess #481 exists to
    # stop. It is also what makes the picker test below realistic: the user
    # really is shown this row, and really can name a card for it.
    "m-dunmarrow",
}
# ``m-ellersby`` and ``m-foxglade`` are absent from both sets on purpose: they
# are reviewed and already classified, so they are out of the queue for a
# reason that has nothing to do with dismissal.
EXPECTED_OUT_OF_QUEUE = {"m-cindervale"}


def _sender_for(company: str) -> str:
    """An address that resolves BACK to ``company``, which the fixture needs.

    ``classify_review_item`` names the employer from the MESSAGE and then looks
    the card up by that token. A sender resolving anywhere else would mint a
    card of the wrong name and every assertion below would be about a different
    row. Measured rather than assumed — an ``@…example.test`` sender resolves
    to "Example", which is how an earlier fixture in this family opened a card
    called Example.
    """

    return f"careers@{company.lower()}.test"


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

    The ``monkeypatch``-on-``settings`` form, patched on EVERY instance the
    request path holds. The env-var-plus-``importlib.reload`` shape is not
    usable here: eight modules reload ``jobtracker.config`` during collection,
    which mints a second settings object while ``jobtracker.auth.supabase_jwt``
    and ``jobtracker.database.connection`` keep their bindings on the first, so
    patching one instance sets the JWT secret on an object the verifier never
    reads (#582). Green alone, ``401 Invalid signature`` in a full run — see
    ``test_dismissed_card_does_not_settle_its_mail.py`` for the measurement.
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
    """One dismissed card per :data:`CARDS`, and the one message that names it.

    Written straight at the session rather than through the API. Two of these
    states are ones only a re-sync produces — a ``NEEDS_REVIEW`` message still
    linked to a card the same pass dismissed, and a settled orphan carrying no
    link at all — and no endpoint offers to create either.

    EVERY CARD SHARES ONE ``dismissed_at``. That is the control: the reason
    column is then the only variable between a ``user`` case and its ``resync``
    twin, so a predicate reading the timestamp cannot separate them and one
    reading the reason must.

    ``identity_role``/``identity_req_id`` are left NULL so identity derives
    from subject plus snippet on both sides, the same as the sibling modules.
    """

    from jobtracker.database import get_session

    owner = uuid.UUID(OWNER)
    application_ids: dict[str, int] = {}

    async with get_session() as session:
        for index, card in enumerate(CARDS):
            row = Application(
                user_id=owner,
                company=card.company,
                position="Backend Engineer",
                status=ApplicationStatus.APPLIED,
                # ``SOURCE_GMAIL_AUTO``, whose value is "gmail" — NOT the
                # plausible-looking "gmail_auto", which ``_is_auto_row`` reads
                # as an unknown/legacy tag and therefore as user-owned. The
                # catch-up's stage advance is gated on that function, so with
                # the wrong string this fixture silently asserts a card that
                # comes back at the stage it was dismissed at. Measured: the
                # Foxglade arm read ``applied`` where the answer said
                # ``rejected``.
                source="gmail",
                dismissed_at=DISMISSED_AT,
                dismissed_reason=card.reason,
            )
            session.add(row)
            await session.flush()
            application_ids[card.company] = row.id

            session.add(
                Email(
                    user_id=owner,
                    application_id=row.id if card.linked else None,
                    source_account=EmailSource.GMAIL,
                    message_id=card.message_id,
                    thread_id=f"t-{card.company.lower()}",
                    subject=f"Update on your {card.company} application",
                    sender_name="Careers",
                    sender_email=_sender_for(card.company),
                    received_at=RECEIVED_AT - timedelta(minutes=index),
                    body_snippet="We have completed our review of your application.",
                    classified_as=card.category,
                    classification_confidence=0.78,
                    is_reviewed=card.reviewed,
                    user_corrected=card.reviewed,
                )
            )

        await session.commit()

    return application_ids


async def _board(client: AsyncClient, headers: dict[str, str]) -> dict[str, dict]:
    """Company → the card on the board, for the cards the user can SEE."""

    resp = await client.get("/applications", headers=headers)
    assert resp.status_code == 200, resp.text
    return {row["company"]: row for row in resp.json()["applications"]}


async def _queue_message_ids(client: AsyncClient, headers: dict[str, str]) -> set[str]:
    resp = await client.get("/applications/review", headers=headers)
    assert resp.status_code == 200, resp.text
    return {item["message_id"] for item in resp.json()["items"]}


async def _rows_by_id() -> dict[int, Application]:
    """Every application of the owner's, dismissed included, read at the session.

    No endpoint of the owner's lists a dismissed row's ``dismissed_reason``
    beside its timestamp, and the never-restore claims are claims about exactly
    those two columns on a row the board will not show.
    """

    from jobtracker.database import get_session

    async with get_session() as session:
        rows = (
            await session.exec(
                select(Application).where(Application.user_id == uuid.UUID(OWNER))
            )
        ).all()
    return {row.id: row for row in rows}


# =============================================================================
# The positive control — every claim below assumes a reachable fixture
# =============================================================================


async def test_the_fixture_is_reachable_the_way_these_tests_assume(
    client, headers, seeded
):
    """Runs first. Pins the seed, and pins WHICH rows are questions at all.

    Four claims, each closing a way this module could be green while proving
    nothing:

    1. every card is dismissed, at the SAME timestamp, differing only in the
       reason — without that the ``user``/``resync`` pairs have two variables;
    2. the board is empty, so any card appearing later appeared because an
       answer put it there;
    3. the queue offers the ``resync`` rows and NOT the message LINKED to a
       hand-dismissed card (#597) — which is also what makes the acceptance
       test below an acceptance test rather than a call to an endpoint nobody
       could have reached. The UNLINKED message at a hand-dismissed employer
       is offered, deliberately; see :data:`EXPECTED_IN_QUEUE`;
    4. the two catch-up orphans are unlinked, reviewed and in a filing
       category, which is the exact shape ``reconcile_orphaned_classifications``
       selects. A linked orphan is not an orphan and the pass would skip it.
    """

    rows = await _rows_by_id()
    assert len(rows) == len(CARDS)
    by_company = {row.company: row for row in rows.values()}
    for card in CARDS:
        stored = by_company[card.company]
        assert stored.dismissed_reason == card.reason, card.company
        assert stored.dismissed_at == DISMISSED_AT, (
            "every card must share one dismissed_at; a differing timestamp "
            "leaves a second variable between a `user` case and its twin"
        )

    assert await _board(client, headers) == {}, (
        "the board must start empty — otherwise a card 'appearing' proves "
        "nothing about the answer that was supposed to put it there"
    )

    in_queue = await _queue_message_ids(client, headers)
    assert in_queue == EXPECTED_IN_QUEUE
    assert not (in_queue & EXPECTED_OUT_OF_QUEUE), (
        "the queue is asking about mail on a card the user removed by hand"
    )

    mail = await client.get("/applications/mail", headers=headers)
    assert mail.status_code == 200, mail.text
    stored_mail = {m["message_id"]: m for m in mail.json()["messages"]}
    assert len(stored_mail) == len(CARDS)
    for key in ("m-ellersby", "m-foxglade"):
        assert stored_mail[key]["application_id"] is None, (
            "a catch-up orphan carries no link — a linked row is not selected "
            "by the catch-up at all and the test would be vacuous"
        )
        # ``category`` is what the mail listing calls the stored verdict.
        assert stored_mail[key]["category"] == "rejection"


# =============================================================================
# #595 / #481 — answer the surfaced question, and a card appears
# =============================================================================


async def test_answering_the_surfaced_question_puts_the_card_back(
    client, headers, seeded
):
    """THE ACCEPTANCE TEST #481 NAMED, and #595's whole reproduction inverted.

    #595 ran exactly this and got: ``200`` naming application 1, a status
    walked to ``rejected``, ``dismissed_at`` untouched, ``BOARD AFTER: []`` and
    ``SUMMARY AFTER: needs_review=0 total=0``. The question was asked once, the
    user answered it, and nothing they can see recorded the answer — and
    ``is_reviewed`` was now true, so it would never be asked again.

    The queue is read BEFORE the answer deliberately: it makes the row's
    reachability part of this test rather than an assumption, so the #597
    mutation reds here too instead of leaving this inert.

    MUTATION: delete the ``if app.dismissed_at is not None`` restore block in
    ``classify_review_item``'s landing branch and this fails at the board — the
    answer lands, the message leaves the queue, and the card stays off.
    """

    card = BY_COMPANY["Brackenhill"]
    assert card.message_id in await _queue_message_ids(client, headers)

    answered = await client.post(
        f"/applications/review/{card.message_id}/classify",
        json={"category": "rejection"},
        headers=headers,
    )
    assert answered.status_code == 200, answered.text
    body = answered.json()
    # A 2xx is not on its own a filing — see ``classify_review_item``. If the
    # employer could not be named the item is left in the queue untouched and
    # everything below would be measuring a request that did nothing.
    assert body["needs_employer"] is False, answered.text
    # AND IT LANDED ON THE DISMISSED CARD rather than minting a second one.
    assert body["application_id"] == seeded[card.company], answered.text

    # THE RESPONSE SAYS THE BOARD CHANGED. A sync that changes the board
    # without saying so is a defect this repo has produced twice; a card
    # appearing out of a review answer is the same defect from the other side.
    assert body["restored"] is True, answered.text
    assert body["restored_company"] == card.company, answered.text

    board = await _board(client, headers)
    assert card.company in board, (
        "the user answered the question and no card appeared — #595's exact "
        "outcome, and strictly worse than the unreachable state #481 reported"
    )
    assert board[card.company]["status"] == "rejected", (
        "the card came back at the stage the answer named"
    )
    assert board[card.company]["id"] == seeded[card.company], (
        "the SAME card, not a duplicate minted beside the dismissed one"
    )

    assert card.message_id not in await _queue_message_ids(client, headers)


async def test_a_non_filing_answer_restores_nothing(client, headers, seeded):
    """``other`` files no mail, so there is nothing for a card to come back for.

    The restore rides on a LANDING, not on the act of answering. ``other`` has
    no lifecycle status, so the filing block never runs — the card stays
    dismissed and the response says so. Asserted because "any answer restores
    the card" is the obvious over-fix, and it would revive a card on the
    strength of a human saying the mail is not job mail at all.
    """

    card = BY_COMPANY["Garrowmere"]
    answered = await client.post(
        f"/applications/review/{card.message_id}/classify",
        json={"category": "other"},
        headers=headers,
    )
    assert answered.status_code == 200, answered.text
    body = answered.json()
    assert body["application_id"] is None, answered.text
    assert body["restored"] is False, answered.text
    assert body["restored_company"] is None, answered.text

    assert card.company not in await _board(client, headers)
    rows = await _rows_by_id()
    assert rows[seeded[card.company]].dismissed_at == DISMISSED_AT
    assert rows[seeded[card.company]].dismissed_reason == "resync"


async def test_none_of_these_mints_and_restores_nothing(client, headers, seeded):
    """"None of these" is the user saying the answer is no existing row.

    So resolution is skipped entirely, a fresh card is minted, and no landing
    occurs — which means no restore, even though the dismissed card is a
    ``resync`` one that a landing WOULD have restored. The directional partner
    of the acceptance test: same card kind, same category, and the only
    difference is whether a landing happened.
    """

    card = BY_COMPANY["Hallowmere"]
    answered = await client.post(
        f"/applications/review/{card.message_id}/classify",
        json={"category": "rejection", "none_of_these": True},
        headers=headers,
    )
    assert answered.status_code == 200, answered.text
    body = answered.json()
    assert body["needs_employer"] is False, answered.text
    assert body["application_id"] != seeded[card.company], answered.text
    assert body["restored"] is False, answered.text

    rows = await _rows_by_id()
    assert rows[seeded[card.company]].dismissed_at == DISMISSED_AT, (
        "the dismissed card must be untouched — nothing landed on it"
    )
    assert rows[body["application_id"]].dismissed_at is None


# =============================================================================
# #597 — a hand dismissal is final, at all three surfaces that could break it
# =============================================================================


async def test_answering_mail_on_a_hand_dismissed_link_mints_beside_it(
    client, headers, seeded
):
    """A ``user`` dismissal survives an answer landing on its own message.

    Reachable in production through the inbox's reclassify control even though
    the queue no longer offers the row: ``classify_review_item`` looks the
    message up by id and does not consult the queue. So the exclusion has to
    live at the resolver, not at the queue predicate.

    A fresh card is minted rather than the answer being refused, and that is
    the cheap direction to be wrong in: a spurious card is one dismiss click,
    where reviving a card a person deliberately removed is the product arguing
    with them and nothing tells them it happened.

    MUTATION: delete ``and not _user_dismissed(linked)`` from
    :func:`_resolve_application_for_email`'s link branch — a deletion, which
    proves the clause is PRESENT — and this fails twice over: the answer lands
    on the dismissed row and the restore block then un-dismisses it.
    """

    card = BY_COMPANY["Cindervale"]
    answered = await client.post(
        f"/applications/review/{card.message_id}/classify",
        json={"category": "rejection"},
        headers=headers,
    )
    assert answered.status_code == 200, answered.text
    body = answered.json()
    assert body["needs_employer"] is False, answered.text
    assert body["application_id"] != seeded[card.company], (
        "the answer landed on the card the user dismissed by hand"
    )
    assert body["restored"] is False, answered.text
    assert body["restored_company"] is None, answered.text

    rows = await _rows_by_id()
    old = rows[seeded[card.company]]
    assert old.dismissed_at == DISMISSED_AT, (
        "the hand dismissal did not survive an answer about one of its messages"
    )
    assert old.dismissed_reason == "user"

    minted = rows[body["application_id"]]
    assert minted.dismissed_at is None
    assert minted.company == card.company
    # Exactly one card of this employer's is on the board: the new one. Two
    # would mean the old row came back as well as a duplicate being filed.
    board = await _board(client, headers)
    assert board[card.company]["id"] == body["application_id"]


async def test_the_picker_may_not_choose_a_hand_dismissed_card(
    client, headers, seeded
):
    """The user naming the id explicitly does not reopen the card either.

    ``_chosen_application`` accepted any id ``_company_rows`` returned, and
    that function returns dismissed rows deliberately (it sorts them last
    rather than dropping them). So the board picker was a second way in, on a
    message carrying no link at all.

    The message here is UNLINKED, which is what makes this test about the
    picker: with no link the resolver's link branch never runs, so only
    ``_chosen_application`` can be what refuses the id.

    MUTATION: drop ``and not _user_dismissed(row)`` from
    :func:`_chosen_application` and this fails — the chosen row is returned,
    the answer lands on it and the restore un-dismisses it.

    NOTED, NOT DECIDED HERE: a user who picks that card is arguably "the human
    acting on that same card again", which is the one thing #597 lets overturn
    a hand dismissal. The picker offers the BOARD, and a dismissed card is not
    on it, so today the id can only arrive stale. If a surface is ever built
    that offers dismissed cards, this is the test that has to be revisited
    first.
    """

    card = BY_COMPANY["Dunmarrow"]
    answered = await client.post(
        f"/applications/review/{card.message_id}/classify",
        json={"category": "rejection", "application_id": seeded[card.company]},
        headers=headers,
    )
    assert answered.status_code == 200, answered.text
    body = answered.json()
    assert body["needs_employer"] is False, answered.text
    assert body["application_id"] != seeded[card.company], (
        "the picker handed the answer straight to a hand-dismissed card"
    )
    assert body["restored"] is False, answered.text

    rows = await _rows_by_id()
    assert rows[seeded[card.company]].dismissed_at == DISMISSED_AT
    assert rows[seeded[card.company]].dismissed_reason == "user"
    assert rows[body["application_id"]].dismissed_at is None


# =============================================================================
# The catch-up: the branch whose comment said "either kind"
# =============================================================================


async def _reconcile() -> int:
    """Run the orphan catch-up for real and return how many rows it CREATED.

    Called directly rather than over HTTP: it is a sync-internal pass with no
    endpoint of its own, and reaching it through ``POST /gmail/sync`` would
    mean standing up the whole scan.
    """

    from jobtracker.cloud.applications import reconcile_orphaned_classifications
    from jobtracker.database import get_session

    async with get_session() as session:
        created = await reconcile_orphaned_classifications(session, uuid.UUID(OWNER))
        await session.commit()
    return created


async def test_a_catch_up_orphan_at_a_hand_dismissed_employer_mints(
    client, headers, seeded
):
    """THE LIVE VIOLATION THE OLD COMMENT DESCRIBED, closed by the resolver.

    ``reconcile_orphaned_classifications``' else-branch said it restores "a
    dismissed row (either kind)". Under this decision that is wrong for the
    ``user`` kind — and it was not merely a wrong comment. The orphan here
    carries NO link, so it reaches the branch through the CASCADE, and
    ``_company_rows`` returns dismissed rows: the cascade would pick the
    hand-dismissed card and the either-kind branch would revive it, on a
    message the user never said anything about after removing the card.

    Nothing in the catch-up guards against that now, and deliberately so — the
    exclusion lives at ``_resolve_application_for_email``, one choke point for
    all four landing surfaces, so ``app`` arrives here as ``None`` and the pass
    mints. A guard inside the branch would be code no test could red.

    MUTATION: delete the ``candidates`` filter in
    :func:`_resolve_application_for_email` and this fails — ``created`` drops
    to 0 for this employer and the hand-dismissed card is back on the board.
    """

    card = BY_COMPANY["Ellersby"]
    created = await _reconcile()
    # One per MINTING orphan. The fixture holds two orphans and this pass
    # handles both: Ellersby mints (below) and Foxglade lands on its restored
    # card (the next test), so exactly one row is created.
    assert created == 1, created

    rows = await _rows_by_id()
    old = rows[seeded[card.company]]
    assert old.dismissed_at == DISMISSED_AT, (
        "the catch-up revived a card the user removed by hand"
    )
    assert old.dismissed_reason == "user"

    board = await _board(client, headers)
    assert card.company in board, "the orphan was not filed anywhere at all"
    assert board[card.company]["id"] != seeded[card.company]
    assert board[card.company]["status"] == "rejected"


async def test_a_catch_up_orphan_at_a_machine_dismissed_employer_still_restores(
    client, headers, seeded
):
    """THE DIRECTIONAL TWIN, and the behaviour this change must NOT break.

    Identical orphan, identical dismissal timestamp, ``resync`` instead of
    ``user``. Here the catch-up's long-standing behaviour is exactly right: a
    human put this message into a filing category, which is newer evidence than
    the rebuild's removal was, so the card comes back rather than a duplicate
    being filed beside it.

    Without this arm, "exclude dismissed rows from the cascade" would pass
    every other test in this file while quietly turning every re-sync
    dismissal into a duplicate card.
    """

    card = BY_COMPANY["Foxglade"]
    await _reconcile()

    rows = await _rows_by_id()
    restored = rows[seeded[card.company]]
    assert restored.dismissed_at is None, (
        "a machine-dismissed card did not come back when a human filed its mail"
    )
    assert restored.dismissed_reason is None

    board = await _board(client, headers)
    assert board[card.company]["id"] == seeded[card.company], (
        "the SAME card, not a duplicate minted beside the dismissed one"
    )
    assert board[card.company]["status"] == "rejected"


# ---------------------------------------------------------------------------
# The conjunct nothing else defends.
#
# A full-suite mutation matrix over this change found exactly one green
# mutation: dropping ``app.dismissed_at is not None`` from
# :func:`_user_dismissed` left all 2002 tests passing. Every other arm of the
# change has a defender; this one had none.
#
# The state it guards — a LIVE row still carrying a stale ``'user'`` reason —
# is UNREACHABLE today, and that is verified rather than assumed: all five
# sites that clear ``dismissed_at`` clear ``dismissed_reason`` on the adjacent
# line with no early return between them, and there is no SQL-level clear
# anywhere in ``jobtracker/`` or ``alembic/``.
#
# So this is a unit test on the helper with a hand-built row, deliberately NOT
# an end-to-end fixture. An integration test would have to construct a state
# the product cannot produce, and a test that greens against an unreachable
# state proves nothing — the failure mode this repo has now hit twice in one
# day. What is being pinned is the helper's stated guarantee, so that the
# conjunct cannot be "simplified" away by a future reader who notices that both
# columns always move together. The moment anyone adds an un-dismiss path or a
# migration that clears one column without the other, this becomes the thing
# standing between them and a live card reading as dismissed.
# ---------------------------------------------------------------------------


def test_a_live_row_with_a_stale_reason_is_not_hand_dismissed() -> None:
    """``dismissed_at`` is load-bearing, not decoration beside the reason."""

    from jobtracker.cloud.applications import DISMISSED_BY_USER, _user_dismissed

    live_but_stale = Application(
        user_id=uuid.uuid4(),
        company="Brackenhill",
        position="Engineer",
        status=ApplicationStatus.APPLIED,
        dismissed_at=None,
        dismissed_reason=DISMISSED_BY_USER,
    )
    assert _user_dismissed(live_but_stale) is False, (
        "a row that is ON THE BOARD must never read as hand-dismissed, whatever "
        "reason string it is still carrying"
    )

    genuinely_dismissed = Application(
        user_id=uuid.uuid4(),
        company="Brackenhill",
        position="Engineer",
        status=ApplicationStatus.APPLIED,
        dismissed_at=datetime(2026, 8, 22, 5, 2, 29),
        dismissed_reason=DISMISSED_BY_USER,
    )
    assert _user_dismissed(genuinely_dismissed) is True, (
        "the directional control: without this the assertion above passes for a "
        "helper that always returns False"
    )
