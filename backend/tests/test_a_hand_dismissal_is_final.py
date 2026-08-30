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

=============================  =============================  ====================
surface                        ``resync``                     ``user``
=============================  =============================  ====================
review answer on its link      restores the card              mints beside it
the board picker               (its own card is choosable)    refuses the id
the catch-up, unlinked mail    restores the card              mints beside it
the catch-up, a settled link   restores the card              not selected at all
=============================  =============================  ====================

THE LAST ROW IS #598 AND IT IS THE ONE ASYMMETRIC PAIR. Everywhere else a
``user`` dismissal is overruled by MINTING beside the card. There it is not
overruled at all: the catch-up's orphan test is now
``_not_filed_on_an_application_that_answers``, and a hand-dismissed card ANSWERS
for its mail, so the message is never selected. Nothing happens — the correct
outcome for a row that is settled rather than stranded, and the reason that
selection may not be written as ``dismissed_at IS NULL``, which would revive the
card on every sync.

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
* BOTH #598 TESTS RED, and they did not exist when this ledger was first
  written: #598 put that same SQL clause into the catch-up's own SELECTION, so
  the mutation now reaches a third surface.
  :func:`test_a_settled_message_on_a_machine_dismissed_card_is_caught_up` reds
  on the board — its ``resync`` row starts reading as answered-for and is no
  longer selected — and
  :func:`test_a_settled_message_on_a_hand_dismissed_card_is_not_caught_up` reds
  on the board too, from the other direction: its ``user`` row stops reading as
  answered-for, is selected, the resolver refuses its hand-dismissed link, and
  the pass MINTS a fresh card beside one the user removed on purpose. That second one is why the twin
  asserts an empty board and an unmoved link rather than only the two dismissal
  columns — those columns survive the mutation untouched.
* :func:`test_the_old_selection_leaves_the_machine_dismissed_card_off_the_board`
  stays green under it, correctly: it replaces the predicate outright, so a
  mutation inside the predicate cannot reach it.
* EVERY OTHER TEST HERE STAYS GREEN, and that is the point rather than a gap.
  The never-restore behaviour lives in ``_resolve_application_for_email`` and
  ``_chosen_application``, which read the reason in PYTHON. Those tests are
  unmoved by a mutation scoped to the SQL clause, so a green there says the
  exclusion is genuinely a second mechanism and not the same one seen twice.
  Its own mutations — deleting the ``not _user_dismissed(linked)`` guard, or
  the ``candidates`` filter, or ``_chosen_application``'s, or turning the link
  branch's REFUSAL back into a fall-through — red exactly the tests named in
  each docstring below. The last of those is the one no single-row fixture
  could catch; see "#618 — the deliberate exception" below.

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
    The catch-up cases in this table are UNLINKED and ``reviewed``, which is
    what sends them through the CASCADE — the route the resolver's exclusion
    defends.

    A LINKED settled row is an orphan too since #598: the selection reads
    :func:`_not_filed_on_an_application_that_answers` rather than
    ``application_id IS NULL``. But it reaches the catch-up's else-branch
    through the message's OWN LINK, which is a different mechanism proving a
    different claim, so it has its own fixture at the foot of this file instead
    of a row here.
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
#
# AND EVERY CASE HERE GIVES ITS EMPLOYER EXACTLY ONE ROW, which is a second
# property of this table and — unlike the first — a blind spot rather than a
# design. It is what let the two-card hijack (#618) survive: with only ever one
# row per employer, taking the hand-dismissed one out of the resolver's
# candidate set always emptied that set, so "the caller then mints" held by
# accident. Give the employer a LIVE sibling and the same skip hands the
# message to it instead. The two tests under "#618 — the deliberate exception"
# below are the exception, and they are deliberately standalone functions with
# their own fixture rather than rows here: adding a second row per employer to
# this table would reintroduce exactly the luck the rule above forbids for
# every case that reads it.
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
            "these two catch-up cases must carry NO link — unlinked is what "
            "routes them through the CASCADE, which is the path the resolver's "
            "exclusion defends. Since #598 a LINKED settled row is selected "
            "too, but it takes the link branch and proves something else; that "
            "shape has its own fixture at the foot of this file"
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
# #618 — the deliberate exception to "one employer per case"
# =============================================================================
#
# THE TWO TESTS BELOW BREAK THE RULE STATED ABOVE :data:`CARDS`, and breaking it
# is the entire point. Every case in that table gives its employer exactly ONE
# row, so neither this file nor the 2002 tests around it could observe what a
# hand-dismissed card does when the SAME EMPLOYER also holds a live one. The
# exclusion was measured against a candidate set that was always empty after the
# dismissed row came out of it, so "the caller then mints" was true by accident
# rather than by construction.
#
# It is not: with a live sibling in the set, skipping the hand-dismissed link
# and falling through to the cascade hands the message to that sibling, and the
# landing reads as a keyed one — so ``_adopt_mail_identity`` stamps the
# DISMISSED application's ``req_id`` and ``role_token`` onto the LIVE one.
# Measured on both routes before the fix, by execution: the message moved off
# the dismissed card, the live card walked to ``rejected`` and to ``gmail_user``
# and ended up wearing an identity belonging to a different application. Rule 1 routes that application's future
# mail there afterwards, and only ``POST /{id}/split`` undoes it.
#
# TWO TESTS BECAUSE THERE ARE TWO ROUTES THROUGH ``_pick_application``, and they
# are different rules reached on different evidence:
#
#   * PRIMARY — the message NAMES a requisition and a role. Rules 1 and 2 miss
#     (the live row is identity-less), and RULE 3 adopts it as the employer's
#     single ``unidentified`` row. ``blind`` is False on its FIRST conjunct
#     (``req_id is None``), so the live-row count is never consulted.
#   * BLIND — subject and snippet name nothing, so RULE 4 returns
#     ``rows[0]``, which is the live row because ``_company_rows`` sorts
#     live-first. Here ``live > 1`` IS what decides ``blind``, and with one
#     live row it is False — so the BODY-GRADE identity on the stored
#     ``identity_*`` columns is stamped even though the cascade read nothing.
#
# Both are needed. A patch that only narrowed the ``live`` count would leave the
# primary route open, and a single test on the primary route would green for it.
#
# The fixture lives beside them rather than up with :func:`seeded` on purpose:
# it is the one seed in this file that is not a :data:`CARDS` row, and putting
# it next to the rule it breaks is what stops it being read as a second general
# fixture that the table-driven tests may quietly start using.


class TwoCardCase(NamedTuple):
    """One employer holding a hand-dismissed card AND a live, anonymous one.

    ``identity_role``/``identity_req_id`` are the BODY-GRADE columns — what a
    fetched body yielded, as opposed to what the ~200-character snippet can be
    re-read for. The blind case sets them and leaves the subject and snippet
    saying nothing, which is the real production shape (24 of the 26 corpus
    cards are rejections, whose snippet ends mid-preamble) and the only way to
    reach rule 4 while still having an identity available to stamp.
    """

    company: str
    message_id: str
    role: str
    req_id: str
    subject: str
    snippet: str
    identity_role: str | None
    identity_req_id: str | None


#: The message names the job outright — rule 3.
PRIMARY_CASE = TwoCardCase(
    company="Ivenmoor",
    message_id="m-ivenmoor-two-cards",
    role="Platform Engineer",
    req_id="R-77104",
    subject="Your application for Platform Engineer (Job ID: R-77104) at Ivenmoor",
    snippet="We have completed our review of your application.",
    identity_role=None,
    identity_req_id=None,
)
#: The message names nothing readable; the identity is on the stored columns —
#: rule 4, and the route where the live-row count is load-bearing.
BLIND_CASE = TwoCardCase(
    company="Jarrowfen",
    message_id="m-jarrowfen-two-cards",
    role="Data Platform Engineer",
    req_id="R-31882",
    subject="Update on your Jarrowfen application",
    snippet="Thank you for taking the time to speak with us.",
    identity_role="Data Platform Engineer",
    identity_req_id="R-31882",
)
TWO_CARD_CASES = (PRIMARY_CASE, BLIND_CASE)

#: What the LIVE row is seeded as, in one place, so the "untouched" assertions
#: and the seed cannot drift apart. ``""`` is ``applications._NO_ROLE`` — an
#: anonymous auto row, which is what an employer's unattributed confirmation
#: leaves behind and the only shape rule 3 will adopt.
LIVE_SIBLING_POSITION = ""
#: ``SOURCE_GMAIL_AUTO``. Spelled literally for the reason :func:`seeded` gives:
#: the plausible-looking "gmail_auto" reads as user-owned to ``_is_auto_row``,
#: which would take the row out of rule 3's ``unidentified`` set and make the
#: primary test pass for the wrong reason.
LIVE_SIBLING_SOURCE = "gmail"


@pytest.fixture
async def two_card_seeds(cloud_app) -> dict[str, dict[str, int]]:
    """Both cases at once: per employer, one hand-dismissed row and one live one.

    Two employers in one database rather than two fixtures, because the tests
    below are about what happens WITHIN one employer's row set and a second,
    differently-named employer proves the scoping is real. ``_company_rows``
    matches on the exact lowered name plus a prefix scan of the first word, and
    the two names share no leading character.
    """

    from jobtracker.database import get_session

    owner = uuid.UUID(OWNER)
    seeds: dict[str, dict[str, int]] = {}

    async with get_session() as session:
        for index, case in enumerate(TWO_CARD_CASES):
            dismissed = Application(
                user_id=owner,
                company=case.company,
                position=case.role,
                status=ApplicationStatus.APPLIED,
                source="gmail",
                req_id=case.req_id,
                # THE SEED AND THE ASSERTION READ ONE ACCESSOR. Through the
                # product's own normalizer rather than a hand ``.lower()``: the
                # two agree for these titles, and that is the point — the seed
                # has to be a row the sync could actually have written, or the
                # assertions below are about a shape production never makes.
                role_token=_role_token(case.role),
                dismissed_at=DISMISSED_AT,
                dismissed_reason="user",
            )
            session.add(dismissed)
            await session.flush()

            live = Application(
                user_id=owner,
                company=case.company,
                position=LIVE_SIBLING_POSITION,
                status=ApplicationStatus.APPLIED,
                source=LIVE_SIBLING_SOURCE,
                req_id=None,
                role_token=None,
                dismissed_at=None,
                dismissed_reason=None,
            )
            session.add(live)
            await session.flush()

            seeds[case.company] = {"dismissed": dismissed.id, "live": live.id}

            session.add(
                Email(
                    user_id=owner,
                    # LINKED to the dismissed card, which is what makes this the
                    # resolver's link branch rather than the cascade's.
                    application_id=dismissed.id,
                    source_account=EmailSource.GMAIL,
                    message_id=case.message_id,
                    thread_id=f"t-{case.company.lower()}",
                    subject=case.subject,
                    sender_name="Careers",
                    sender_email=_sender_for(case.company),
                    received_at=RECEIVED_AT - timedelta(minutes=index),
                    body_snippet=case.snippet,
                    identity_role=case.identity_role,
                    identity_req_id=case.identity_req_id,
                    classified_as=EmailCategory.NEEDS_REVIEW,
                    classification_confidence=0.78,
                    is_reviewed=False,
                    user_corrected=False,
                )
            )

        await session.commit()

    return seeds


def _role_token(role: str) -> str:
    """The comparison key the product derives from a title. One spelling."""

    from jobtracker.cloud import pipeline

    return pipeline.normalize_role_token(role)


async def _message_row(message_id: str) -> Email:
    """One stored message, read at the session — the board never shows its link."""

    from jobtracker.database import get_session

    async with get_session() as session:
        return (
            await session.exec(
                select(Email).where(
                    Email.user_id == uuid.UUID(OWNER), Email.message_id == message_id
                )
            )
        ).first()


async def _assert_two_card_post_state(
    case: TwoCardCase, ids: dict[str, int], body: dict
) -> None:
    """The full post-state both routes must produce. Shared so they cannot drift.

    Every claim is stated as an ABSOLUTE value rather than as a difference from
    the other row: the live sibling's identity columns are asserted ``is None``,
    not "not the dismissed row's", because an assertion that passes for any
    value is not a control — it would green on a row that had adopted a THIRD
    application's key.
    """

    rows = await _rows_by_id()

    # ORDERED SHARPEST FIRST, and the order is not cosmetic. pytest stops at the
    # first failing assert, so whichever claim is stated first is the one a
    # reader of the red actually sees — and this repo has already shipped a case
    # where an early guard fired and hid every later one. The landing itself is
    # the defect's own signature, so it goes first; the row COUNT, which is a
    # consequence of it, goes after the state assertions rather than before.
    minted_id = body["application_id"]
    assert minted_id not in (ids["dismissed"], ids["live"]), (
        "the answer landed on a row that ALREADY EXISTED — on the hand-dismissed "
        f"card if it is {ids['dismissed']}, on its LIVE SIBLING if it is "
        f"{ids['live']}; a fresh row was supposed to be minted beside them"
    )
    minted = rows[minted_id]
    assert minted.company == case.company
    assert minted.dismissed_at is None
    assert minted.status.value == "rejected"

    # THE LIVE SIBLING IS UNTOUCHED — every column the hijack moved.
    live = rows[ids["live"]]
    assert live.req_id is None, (
        "the live sibling adopted a requisition id it was never seeded with — "
        "two applications at one employer now answer to one key"
    )
    assert live.role_token is None, (
        "the live sibling adopted a role token it was never seeded with"
    )
    assert live.position == LIVE_SIBLING_POSITION, (
        "the live sibling was given another application's job title"
    )
    assert live.status.value == "applied", (
        "the live sibling's stage was advanced by an answer about a message "
        "that was never about it"
    )
    assert live.source == LIVE_SIBLING_SOURCE, (
        "the live sibling was flipped to user-owned, which freezes it against "
        "the sync's own advance gate"
    )
    assert live.dismissed_at is None

    # THE HAND DISMISSAL SURVIVED, and so did the card's own identity.
    dismissed = rows[ids["dismissed"]]
    assert dismissed.dismissed_at == DISMISSED_AT
    assert dismissed.dismissed_reason == "user"
    assert dismissed.req_id == case.req_id
    assert dismissed.role_token == _role_token(case.role)
    assert dismissed.position == case.role
    assert dismissed.status.value == "applied", (
        "the answer walked the dismissed card's stage even though it did not "
        "land there"
    )

    # AND THE MESSAGE ITSELF POINTS AT THE MINT, not merely what the response
    # claimed about it — the two are written in the same transaction and a
    # response that names a row the stored message does not is its own defect.
    email = await _message_row(case.message_id)
    assert email.application_id == minted_id, (
        "the response named the minted row but the stored message points "
        f"somewhere else ({email.application_id})"
    )

    # EXACTLY ONE ROW WAS ADDED. Stated last because it is the consequence of
    # everything above; stated at all because "minted beside it" is a claim
    # about the SIZE of the board too, and a mint that also duplicated the live
    # row would satisfy every assertion above this one.
    at_employer = [row for row in rows.values() if row.company == case.company]
    assert len(at_employer) == 3, (
        "expected the two seeded rows plus exactly one mint, got "
        f"{[(r.id, r.dismissed_reason) for r in at_employer]}"
    )

    # NOTHING WAS RESTORED. The row that was landed on is live, so
    # ``restore_target`` is never set — this is the correct value, not a
    # symptom, and it is asserted so a future restore-on-mint cannot slip in.
    assert body["restored"] is False
    assert body["restored_company"] is None


async def test_a_hand_dismissed_cards_mail_does_not_hijack_its_live_sibling(
    client, headers, two_card_seeds
):
    """RULE 3. The message names the job, and the live sibling must not get it.

    Before the refusal, ``_resolve_application_for_email`` skipped the
    hand-dismissed own-link and fell through to the cascade with the live row as
    the only candidate. ``_pick_application`` rules 1 and 2 miss it (it carries
    neither key), so rule 3 adopts it as the employer's single identity-less
    auto row — and ``blind`` is False because the message NAMES a requisition,
    so ``_adopt_mail_identity`` stamps ``R-77104`` and ``platform engineer``
    onto it. Measured post-state on this exact seed: ``application_id`` 1 → 2,
    the live row at ``rejected`` / ``gmail_user`` / ``R-77104``.

    Reached the way ``/inbox``'s reclassify control reaches it — no
    ``application_id`` in the body, which is what that control sends for a
    message already filed against a row, on the stated grounds that the link
    outranks every tie-break.

    MUTATION: restore ``if linked is not None and not _user_dismissed(linked):
    return linked, LANDED_LINKED`` in place of the refusal — i.e. skip instead
    of refuse — and this fails on ``minted_id not in (dismissed, live)``.
    """

    from jobtracker.cloud import pipeline

    case = PRIMARY_CASE
    ids = two_card_seeds[case.company]

    # THE ROUTE CONTROL. If extraction stopped naming the requisition this test
    # would silently become the blind one and prove the other route twice.
    assert pipeline.extract_req_id(case.subject, case.snippet) == case.req_id
    assert pipeline.role_from_message(case.subject, case.snippet) == case.role

    # THE FIXTURE CONTROL. Two rows at this employer before the answer, and the
    # message pointing at the dismissed one — without both, "it did not land on
    # the live sibling" is a claim about a shape that was never built.
    before = await _rows_by_id()
    assert len([r for r in before.values() if r.company == case.company]) == 2
    assert (await _message_row(case.message_id)).application_id == ids["dismissed"]

    answered = await client.post(
        f"/applications/review/{case.message_id}/classify",
        json={"category": "rejection"},
        headers=headers,
    )
    assert answered.status_code == 200, answered.text
    body = answered.json()
    assert body["needs_employer"] is False, answered.text

    await _assert_two_card_post_state(case, ids, body)


async def test_a_blind_answer_at_a_hand_dismissed_card_does_not_hijack_either(
    client, headers, two_card_seeds
):
    """RULE 4, and the route a narrower fix would have missed.

    Same two-card shape, but the subject and snippet name nothing — so the
    cascade's own ``req_id`` and ``role_token`` are both None and
    ``_pick_application`` falls to rule 4, ``rows[0]``, which is the live row
    because ``_company_rows`` sorts live-first. ``blind`` is then decided by
    ``live > 1``, and with exactly one live row it is False: the landing reads
    KEYED and the BODY-GRADE identity sitting on ``identity_role`` /
    ``identity_req_id`` is stamped onto a row the resolver read nothing about.

    THIS IS WHY THE REFUSAL SITS ABOVE THE CASCADE rather than in the ``live``
    count. Tightening ``blind`` to treat one live row as ambiguous would close
    this route and leave the rule-3 one open, because that one never consults
    the count — its ``blind`` is already False on ``req_id is None``.

    MUTATION: the same one as the test above — skip the hand-dismissed link
    instead of refusing it — and this fails on
    ``minted_id not in (dismissed, live)``.
    """

    from jobtracker.cloud import pipeline

    case = BLIND_CASE
    ids = two_card_seeds[case.company]

    # THE ROUTE CONTROL, and it is directional against the test above: this
    # message must read as anonymous to the SNIPPET-grade cascade while still
    # carrying an identity on its stored columns. If extraction ever starts
    # reading this subject, rule 3 fires instead and this stops being the
    # rule-4 test without saying so.
    assert pipeline.extract_req_id(case.subject, case.snippet) is None
    assert pipeline.role_from_message(case.subject, case.snippet) is None
    seeded_message = await _message_row(case.message_id)
    assert seeded_message.identity_req_id == case.req_id
    assert seeded_message.identity_role == case.role

    before = await _rows_by_id()
    assert len([r for r in before.values() if r.company == case.company]) == 2
    assert seeded_message.application_id == ids["dismissed"]

    answered = await client.post(
        f"/applications/review/{case.message_id}/classify",
        json={"category": "rejection"},
        headers=headers,
    )
    assert answered.status_code == 200, answered.text
    body = answered.json()
    assert body["needs_employer"] is False, answered.text

    await _assert_two_card_post_state(case, ids, body)


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


# =============================================================================
# #598 — the catch-up's SELECTION, on a settled message that carries a link
# =============================================================================
#
# EVERY CATCH-UP CASE ABOVE ARRIVES THROUGH THE CASCADE, because both orphans in
# :data:`CARDS` are unlinked. That was the only shape the old selection could
# see: it asked ``Email.application_id IS NULL``, i.e. "no application was
# produced". Dismissal made that reading false. A message linked to a card a
# RE-SYNC removed produced no application the user can SEE, and is stranded in
# precisely the way this pass exists to undo — reviewed, in a filing category,
# on no board, out of the queue — and the pass stepped straight over it (#598,
# found while auditing #587).
#
# The selection now reads ``_not_filed_on_an_application_that_answers``, the
# same predicate the review queue and the ``needs_review`` tile read. It is a
# strict WIDENING: a NULL link makes that ``EXISTS`` false, so every row the old
# clause selected is still selected, and the cases above are unaffected.
#
# TWO EMPLOYERS, ONE CARD EACH, AND THE PAIR IS THE POINT. ``dismissed_reason``
# is the only difference between them, so a selection reading ``dismissed_at``
# alone cannot separate them — and ``dismissed_at IS NULL`` is the tempting
# wrong answer here, because it would revive a hand-dismissed card on every
# catch-up pass, which is what #597 forbids.
#
# A SEPARATE FIXTURE rather than two more :data:`CARDS` rows, for the reason the
# #618 section gives for its own: ``created`` is a WHOLE-PASS number and
# :func:`test_a_catch_up_orphan_at_a_hand_dismissed_employer_mints` asserts it
# equals 1. Rows in that table would make an unrelated test's arithmetic depend
# on this one's fixture. The shape does not belong there either — see
# :class:`Card`.


class LinkedOrphanCase(NamedTuple):
    """A SETTLED message already carrying the ``application_id`` of a dismissed card.

    Only a re-sync produces this state: the pass dismisses the card and leaves
    the link on the mail, because the additive persist rewrites
    ``classified_as`` and never clears ``application_id``. No endpoint offers to
    create it, so it is written straight at the session.
    """

    company: str
    reason: str
    message_id: str


#: The rebuild's removal. Its mail is still an open question, so a human having
#: filed it is newer evidence and the card comes back.
MACHINE_LINK = LinkedOrphanCase("Marrowgate", "resync", "m-marrowgate-linked")
#: The human's removal. Its mail is SETTLED, so there is no orphan to reconcile.
HAND_LINK = LinkedOrphanCase("Nettlebourne", "user", "m-nettlebourne-linked")
LINKED_ORPHAN_CASES = (MACHINE_LINK, HAND_LINK)


@pytest.fixture
async def linked_orphan_seeds(cloud_app) -> dict[str, int]:
    """One dismissed card per case, and the settled message pointing straight at it.

    ``classified_as`` is a FILING category and ``is_reviewed`` is true, so each
    message is settled from the user's side — the half of the orphan shape the
    catch-up has always required. The half #598 changed is that these rows carry
    a LINK, which the old selection read as "already filed".

    Both cards share one ``dismissed_at``, for the reason :func:`seeded` gives:
    the reason column has to be the only variable between the pair, or a
    predicate reading the timestamp could separate them and the pair would prove
    nothing about which column is read.

    ``source="gmail"`` is ``SOURCE_GMAIL_AUTO`` — the same trap :func:`seeded`
    documents. With any other tag ``_is_auto_row`` reads the row as user-owned,
    the catch-up's stage advance is skipped, and the restored card silently
    comes back at the stage it was dismissed at.
    """

    from jobtracker.database import get_session

    owner = uuid.UUID(OWNER)
    application_ids: dict[str, int] = {}

    async with get_session() as session:
        for index, case in enumerate(LINKED_ORPHAN_CASES):
            row = Application(
                user_id=owner,
                company=case.company,
                position="Backend Engineer",
                status=ApplicationStatus.APPLIED,
                source="gmail",
                dismissed_at=DISMISSED_AT,
                dismissed_reason=case.reason,
            )
            session.add(row)
            await session.flush()
            application_ids[case.company] = row.id

            session.add(
                Email(
                    user_id=owner,
                    application_id=row.id,
                    source_account=EmailSource.GMAIL,
                    message_id=case.message_id,
                    thread_id=f"t-{case.company.lower()}",
                    subject=f"Update on your {case.company} application",
                    sender_name="Careers",
                    sender_email=_sender_for(case.company),
                    received_at=RECEIVED_AT - timedelta(minutes=index),
                    body_snippet="We have completed our review of your application.",
                    classified_as=EmailCategory.REJECTION,
                    classification_confidence=0.78,
                    is_reviewed=True,
                    user_corrected=True,
                )
            )

        await session.commit()

    return application_ids


async def test_the_linked_orphan_fixture_is_the_shape_598_is_about(
    client, headers, linked_orphan_seeds
):
    """Runs first. Without it the two tests below could both be about nothing.

    Four claims, and each closes a way this section could be green while the
    fixture was never the state #598 reported:

    1. both cards are dismissed at the SAME timestamp and differ only in the
       reason — the control that makes the pair directional;
    2. the board is empty, so a card appearing below appeared because the
       catch-up put it there;
    3. each message CARRIES ITS CARD'S LINK. That is the clause #598 changed,
       and an unlinked row here would make both tests duplicates of the
       :data:`CARDS` cases;
    4. each message is reviewed and stored in a FILING category — settled from
       the user's side, which the catch-up has always required and which #598
       did not touch.

    AND THE ROUTE CONTROL, the same kind the #618 tests carry. The catch-up
    ``continue``s on an orphan whose employer :func:`pipeline.resolve_employer`
    cannot name, and "selected but unnameable" is OBSERVATIONALLY IDENTICAL to
    "never selected" — no card, no mint, the link unmoved, every dismissal
    column intact. That is precisely the twin's expected post-state, so without
    this assertion the twin would green on a fixture the pass never got past,
    which is this repo's standing defect. Called with the same three arguments
    in the same order the catch-up passes.
    """

    rows = await _rows_by_id()
    assert len(rows) == len(LINKED_ORPHAN_CASES)
    by_company = {row.company: row for row in rows.values()}
    for case in LINKED_ORPHAN_CASES:
        stored = by_company[case.company]
        assert stored.dismissed_reason == case.reason, case.company
        assert stored.dismissed_at == DISMISSED_AT, (
            "both cards must share one dismissed_at; a differing timestamp "
            "leaves a second variable between the `resync` case and its twin"
        )

    assert await _board(client, headers) == {}, (
        "the board must start empty — otherwise a card 'appearing' proves "
        "nothing about the catch-up that was supposed to put it there"
    )

    from jobtracker.cloud import pipeline

    for case in LINKED_ORPHAN_CASES:
        named = pipeline.resolve_employer(
            _sender_for(case.company),
            f"Update on your {case.company} application",
            "Careers",
        )
        assert named is not None, (
            f"{case.company} must be NAMEABLE from its message — the catch-up "
            "`continue`s on an employer it cannot name, and that outcome is "
            "indistinguishable from 'never selected', which is exactly what "
            "the hand-dismissed twin below asserts"
        )

        email = await _message_row(case.message_id)
        assert email.application_id == linked_orphan_seeds[case.company], (
            "the message must already point at the dismissed card — an unlinked "
            "row is the shape the OLD selection already reached and these tests "
            "would say nothing about #598"
        )
        assert email.is_reviewed is True
        assert email.classified_as == EmailCategory.REJECTION


async def test_a_settled_message_on_a_machine_dismissed_card_is_caught_up(
    client, headers, linked_orphan_seeds
):
    """#598's acceptance case: the catch-up reaches a row it used to step over.

    Reproduced in the issue by execution on the old selection: ``created: 0``,
    ``BOARD: []``, ``QUEUE: []``, and the message sitting on an
    ``application_id`` whose card does not exist on any screen. The row was
    reviewed, in a filing category, on no board and out of the queue — the exact
    definition of the strandedness this function exists to undo — and the
    catch-up reported nothing to do.

    ORDERED SHARPEST FIRST: the board is this test's own claim, so it is
    asserted before anything derived from it. ``created`` comes LAST because it
    is a WHOLE-PASS number over both cases of :func:`linked_orphan_seeds` — zero
    is correct for the pair (this case restores a card that already exists, and
    the twin's message must not be selected at all), but a non-zero reading
    there can be the twin's defect rather than this one's, and a claim that can
    fire for another case's reason must not be the first thing a reader sees.

    MUTATION: revert the selection to ``Email.application_id.is_(None)`` and
    this fails at the board — the linked row is not an orphan again. That
    mutation is also shipped as
    :func:`test_the_old_selection_leaves_the_machine_dismissed_card_off_the_board`,
    so the direction is proved by an executable test and not only by a comment.
    """

    case = MACHINE_LINK
    card_id = linked_orphan_seeds[case.company]

    created = await _reconcile()

    board = await _board(client, headers)
    assert case.company in board, (
        "the settled message is still stranded — on no board, out of the queue, "
        "and pointing at a card the user cannot see, which is #598's whole "
        "reproduction"
    )
    assert board[case.company]["id"] == card_id, (
        "the SAME card came back, not a duplicate minted beside the dismissed one"
    )
    assert board[case.company]["status"] == "rejected", (
        "the card came back at the stage the human's own filing named"
    )

    rows = await _rows_by_id()
    restored = rows[card_id]
    assert restored.dismissed_at is None
    assert restored.dismissed_reason is None
    assert len([row for row in rows.values() if row.company == case.company]) == 1, (
        "exactly one row at this employer — a second would mean the pass filed "
        "a duplicate beside the card it restored"
    )

    email = await _message_row(case.message_id)
    assert email.application_id == card_id, (
        "the message must still name the card it was reconciled onto"
    )

    assert created == 0, (
        "the pass over this fixture must CREATE nothing: this case restores the "
        "card its message already names, and the hand-dismissed twin's message "
        f"is settled and must never be selected. Got created={created}, which "
        "means one of the two minted"
    )


async def test_a_settled_message_on_a_hand_dismissed_card_is_not_caught_up(
    client, headers, linked_orphan_seeds
):
    """THE DIRECTIONAL TWIN, and the reason the selection is not ``dismissed_at``.

    Identical row, identical timestamp, ``user`` instead of ``resync``. Under
    #597 the human's removal answers for that card's mail: the message is
    SETTLED, not stranded, so it is not an orphan and the pass must do nothing
    at all with it. Selecting on ``dismissed_at IS NULL`` — the one-character
    shortcut that passes the test above — would revive a card the user
    deliberately removed, silently, on every sync.

    WHY THIS DIFFERS FROM ``Ellersby``, which is the same reason column and the
    opposite expectation. That case is UNLINKED, so nothing answers for it, it
    IS an orphan, and minting beside the dismissed card is right. This one
    carries the card's own link, so the card answers and the correct outcome is
    that nothing happens.

    THE BOARD AND THE LINK ARE ASSERTED, not only the two dismissal columns, and
    that is what makes this test directional rather than decorative. Under the
    ledger's mutation this row IS selected, the resolver refuses its
    hand-dismissed link, and the pass MINTS a fresh card — leaving
    ``dismissed_at`` and ``dismissed_reason`` on the old row untouched. A twin
    that read only those two columns would stay green through exactly the
    failure it exists to catch.
    """

    case = HAND_LINK
    card_id = linked_orphan_seeds[case.company]

    created = await _reconcile()

    board = await _board(client, headers)
    assert case.company not in board, (
        "the catch-up put a card on the board for an employer whose only card "
        f"the user removed by hand: {board.get(case.company)}"
    )

    rows = await _rows_by_id()
    assert len([row for row in rows.values() if row.company == case.company]) == 1, (
        "a row was minted beside the hand-dismissed card; this message is "
        "settled, so the pass should not have selected it at all"
    )
    untouched = rows[card_id]
    assert untouched.dismissed_at == DISMISSED_AT, (
        "the catch-up revived a card the user removed by hand"
    )
    assert untouched.dismissed_reason == "user"

    email = await _message_row(case.message_id)
    assert email.application_id == card_id, (
        "the message's link moved, so the pass touched a row it was never "
        f"supposed to select (now {email.application_id})"
    )

    assert created == 0, (
        "the pass over this fixture must CREATE nothing — a mint is a card "
        "appearing for mail the user already answered by removing its "
        f"application. Got created={created}"
    )


async def test_the_old_selection_leaves_the_machine_dismissed_card_off_the_board(
    client, headers, linked_orphan_seeds, monkeypatch: pytest.MonkeyPatch
):
    """THE CONTROL. Put the old clause back and the card does NOT come back.

    A test that greens both ways proves nothing, and every assertion in
    :func:`test_a_settled_message_on_a_machine_dismissed_card_is_caught_up`
    would pass on any code that happened to leave a card on the board. So the
    selection is reverted here — ``Email.application_id.is_(None)``, the literal
    clause #598 replaced — and the acceptance claim is asserted to FAIL.

    Patched at the module global rather than by editing the query, because
    ``reconcile_orphaned_classifications`` looks the helper up by name at call
    time. That is also why this test reads only the BOARD: the patch reverts the
    predicate for every caller in the process, including the review queue and
    the ``needs_review`` tile, and a queue read inside it would be measuring
    three surfaces at once.

    ``created`` is 0 both ways and is therefore not the control — with the old
    clause because no row is selected, with the new one because the row that is
    selected lands on a card that already exists. Asserted anyway, so a revert
    that started MINTING instead would not slip past as a green.
    """

    from jobtracker.cloud import applications

    case = MACHINE_LINK
    card_id = linked_orphan_seeds[case.company]

    monkeypatch.setattr(
        applications,
        "_not_filed_on_an_application_that_answers",
        lambda _user_id: Email.application_id.is_(None),
    )

    created = await _reconcile()
    assert created == 0, created

    board = await _board(client, headers)
    assert case.company not in board, (
        "the old selection reached the linked row after all — then the test "
        "above is not measuring the predicate swap and #598 was not a defect"
    )

    rows = await _rows_by_id()
    assert rows[card_id].dismissed_at == DISMISSED_AT
    assert rows[card_id].dismissed_reason == "resync"
