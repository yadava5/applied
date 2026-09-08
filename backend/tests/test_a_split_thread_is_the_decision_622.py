"""#622 — a thread that spans a hand-dismissed card SPLITS, and that is the answer.

What this file ratifies
-----------------------

#622 reported a shape and explicitly declined to say which behaviour was right:
one employer, one card the user dismissed BY HAND, one Gmail thread whose two
messages both link to it. Reclassify one message from ``/inbox`` and it is
answered onto a freshly minted card while its sibling stays on the dismissed
one — the conversation is now split across two applications, and reclassifying
the sibling too mints a THIRD.

**Option 1 was chosen: leave it.** This file is that decision written down as
assertions, so the next reader who trips over a two-card employer finds a test
saying "this is intended" instead of re-filing the issue. Nothing here is a
The decision is recorded as DEC-012 in ``docs/DECISIONS.md``, which carries
the two alternatives that were rejected and why one of them is the mutation
``_resolve_application_for_email``'s refusal branch exists to forbid.

defect being pinned. The ``rows == 3`` assertion at the end of the ``user`` arm
is the ratification, and it carries its own note.

Why the split is correct rather than merely cheap
-------------------------------------------------

Two stated principles point in different directions on this one shape, and #622
is the collision:

* ``classify_review_item``'s own comment — *one decision settles the whole
  conversation, because the queue offers one entry per conversation*.
* #597 — *a hand dismissal yields to nothing except the human acting on that
  same card again*.

The first is a rule about the QUEUE, and the queue never offered this
conversation at all: both messages are filed on a card that ANSWERS for them
(``_not_filed_on_an_application_that_answers``), so the entry count for this
thread is zero. This test asserts that emptiness before it touches anything —
see :func:`test_the_fixture_is_one_conversation_no_queue_entry_answers_for`.
What the user actually used is ``/inbox``'s reclassify, which is a
per-MESSAGE control: it names one message id, it is reachable for mail the
queue does not offer, and ``classify_review_item`` looks the message up by id
without consulting the queue at all. So n per-message commands yielding n cards
is the per-message control behaving as a per-message control, and the "one
decision settles the conversation" rule is not being violated because no such
decision was ever offered.

The second is why the sibling may not be carried along. Option 2 ("carry the
thread to the mint") moves mail OFF a hand-dismissed card on the strength of a
decision the user made about a DIFFERENT message. That is the product arguing
with a person who removed a row on purpose, and it is not one dismiss click
away from tidy — where a spurious card is.

The structure: one probe, one variable
--------------------------------------

Every claim below is stated twice, once per :data:`ARMS`, and the two arms
differ in exactly ONE seeded column: ``Application.dismissed_reason``. Same
employer, same thread, same two messages, same ``dismissed_at``, same request.
That is what makes the outcome attributable to the reason rather than to the
timestamp, the link, or the fixture's shape:

===========================  =========================  ========================
                             ``resync`` (the CONTROL)   ``user`` (the CASE)
===========================  =========================  ========================
queue entries for the thread 1 — the card is a machine  0 — the card answers
                             opinion, its mail is an    for its mail (#597), so
                             open question              nothing is asked
answering the first message  lands ON the seeded card,  REFUSED at its own link,
                             which is restored (#595)   mints beside it
its thread sibling           settled onto the same row  unmoved: still on the
                             and marked reviewed        dismissed card, still
                                                        un-reviewed
answering the sibling too    lands on the same row      mints a THIRD row
rows at the employer         1, then 1                  2, then 3
===========================  =========================  ========================

The ``resync`` arm is the twin ``test_dismissed_card_does_not_settle_its_mail``
already owns (its ``m-thread-newer``/``m-thread-older`` pair); it is rebuilt
here rather than imported because a control that lives in another module's
fixture cannot be held to THIS fixture's one-variable rule.

Two fixture-integrity controls, without which this file proves nothing
---------------------------------------------------------------------

1. **The two messages share a review key.** ``pipeline.review_dedup_key`` keys
   a threaded message on the thread PLUS which application it names (#454), so
   siblings only settle each other when their derived identity agrees. Differing
   text gives them different keys, the ``resync`` arm's sibling is then left
   alone for a reason that has nothing to do with dismissal, and the whole
   comparison is vacuous. Asserted through :func:`applications._review_key`, the
   product's own reader for a stored row, and asserted as a VALUE
   (:data:`ROLE_TOKEN`) rather than as ``key1 == key2``: both messages naming
   nothing would satisfy an equality and pin nothing, since every nameless
   message of a thread collides with every other.

2. **The queue is empty before any answer, in the ``user`` arm.** That is the
   fact separating this fixture from the ``resync`` twin, and it is what makes
   the split a per-message outcome rather than a settle that lost half its
   conversation.

MUTATION, and its expected red set. Give the second message a different subject
(``"Your application for Data Platform Engineer"``, measured to derive the
sub-key ``"data platform engineer"`` where the seeded one derives
``"platform engineer"``):

* :func:`test_the_fixture_is_one_conversation_no_queue_entry_answers_for` reds
  on the key control, in both arms.
* THE ``resync`` ARM OF :func:`test_a_split_thread_is_the_decision` ALSO REDS,
  which is what makes the key control load-bearing rather than decorative. RUN,
  not predicted: it fails at the queue read, ``{'m-thornwick-newer',
  'm-thornwick-older'} == {'m-thornwick-newer'}`` — one conversation now
  surfaces as TWO entries, because the queue reads the same key the settle
  does. Had it got past that, the settle would have dropped the sibling and
  left it un-reviewed and ``NEEDS_REVIEW``; the queue simply says it one
  assertion earlier.
* the ``user`` arm stays GREEN under it, correctly: it is refused at the link
  branch before any key is compared, so a key mutation cannot reach it. Its
  queue is empty either way — a message answered for by a hand-dismissed card
  is out of the queue whatever it names.

A second mutation, for the claim this file exists to make, and RUN as well:
delete the ``if not _user_dismissed(linked)`` guard from
:func:`applications._resolve_application_for_email`'s link branch — a deletion,
which proves the clause is PRESENT rather than merely reachable — and the
``user`` arm reds at its first landing assertion, ``assert 1 != 1``: the answer
lands on the card the user dismissed by hand, so #622's shape stops existing
and #597 with it. The ``resync`` arm stays green under it, correctly — its
landing never consulted the guard — which is what says the two arms are
separated by that branch and not by the fixture.

Every employer, sender, requisition and role here is INVENTED and the domain is
RFC-reserved. Nothing in this file comes from a real mailbox (#593).
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

# 32+ bytes so PyJWT does not warn, spelled in the shape `.gitleaks.toml`
# allowlists BY VALUE — a string that says of itself that it is a test JWT
# secret of an HS256-legal length. A free-form variant only passes the scanner
# if its entropy happens to fall under the generic rule's threshold.
JWT_SECRET = "split-thread-622-test-jwt-secret-at-least-32-bytes-long-hs256"
OWNER = "c2c2c2c2-c2c2-4c2c-8c2c-c2c2c2c2c2c2"

DISMISSED_AT = datetime(2026, 8, 22, 5, 2, 29)
RECEIVED_AT = datetime(2026, 8, 24, 10, 0, 0)

#: One employer for the whole file. Both arms run against a fresh in-memory
#: database, so sharing the name costs nothing and keeps the two seeds
#: byte-identical apart from the one column under test.
COMPANY = "Thornwick"
#: Measured, not assumed: `pipeline.resolve_employer` returns
#: `('thornwick', 'Thornwick')` for this address, so the card the answer names
#: is the card this fixture seeded and a mint carries the same display name.
#: An `@…example.test` sender resolves to "Example" and would open a card of
#: that name instead — the failure an earlier fixture in this family shipped.
SENDER = "careers@thornwick.test"
THREAD_ID = "t-thornwick-pair"

#: The seeded card's own identity. `REQ_ID` is deliberately a value NEITHER
#: MESSAGE NAMES: it is what makes the "byte-untouched" assertions on the `user`
#: arm able to catch a wipe-to-None, which an identity the mail also carries
#: could not.
ROLE = "Platform Engineer"
REQ_ID = "R-40214"
#: `pipeline.normalize_role_token(ROLE)`, spelled out so the expectation is not
#: read from the function it is checking. Reconciled against the product's own
#: normalizer in the fixture control below.
ROLE_TOKEN = "platform engineer"

#: IDENTICAL ON BOTH MESSAGES, and that is a requirement rather than tidiness —
#: see control 1 in the module docstring. Measured: this subject derives the
#: role `Platform Engineer` and no requisition id, so both messages key on
#: `(THREAD_ID, "platform engineer")`. A subject deriving NOTHING would key both
#: on `(THREAD_ID, None)`, which is equal for any two nameless messages and
#: therefore proves nothing.
SUBJECT = f"Your application for {ROLE}"
SNIPPET = "We have received your application and will be in touch."

#: The message the user reclassifies FIRST. The newer of the two, which is the
#: one the queue puts in front of a user when it offers this conversation at all
#: — so the `resync` arm's first call is genuinely the queue's own entry being
#: answered rather than an inbox reclassify wearing its clothes.
FIRST_MESSAGE = "m-thornwick-newer"
#: Its thread sibling. #622 is about where THIS row ends up.
SECOND_MESSAGE = "m-thornwick-older"

#: What the user tells the endpoint, on both calls and in both arms. This is an
#: :class:`EmailCategory`, which is a different vocabulary from the application
#: STATUS it maps to below — the two words are close enough to be swapped by
#: eye, and a status asserted as "rejection" is a name no `ApplicationStatus`
#: holds.
ANSWER = "rejection"
#: `CATEGORY_TO_STATUS[ANSWER]`. Spelled out rather than looked up so the
#: expectation is not read from the table the code reads.
ANSWERED_STATUS = "rejected"


class Arm(NamedTuple):
    """One value of ``dismissed_reason`` and every outcome it decides.

    Hardcoded rather than derived. An expectation computed from the code under
    test agrees with any behaviour, including the one this file exists to
    forbid.
    """

    reason: str
    #: Message ids the review queue offers BEFORE anything is answered.
    queue_before: frozenset[str]
    #: Does the first answer land on the SEEDED card, or beside it?
    lands_on_the_seeded_card: bool
    restored: bool
    restored_company: str | None
    #: Is the thread sibling settled by that answer — reviewed, and carrying the
    #: answered category?
    sibling_settled: bool
    #: Message ids still queued after the first answer.
    queue_after_first: frozenset[str]
    #: Applications at this employer after the first and the second answer.
    rows_after_first: int
    rows_after_second: int
    #: How many of those the user can SEE once both messages are answered. The
    #: stored count above cannot say: a dismissed row is counted there and shown
    #: nowhere, so this is the claim about the SCREEN and it is hardcoded like
    #: the rest — deriving it from the row count minus "one if still dismissed"
    #: is algebra over a number this test just asserted, which agrees with
    #: whatever that number was.
    board_rows_after_second: int
    #: The seeded card's stored state afterwards, as ABSOLUTE values.
    seed_dismissed_at: datetime | None
    seed_dismissed_reason: str | None
    seed_status: str


#: THE CASE. A person said "this is not an application"; the thread splits.
USER_ARM = Arm(
    reason="user",
    # #597: both messages are filed on a card that answers for them, so the
    # conversation is not a question and the queue does not ask it.
    queue_before=frozenset(),
    lands_on_the_seeded_card=False,
    restored=False,
    restored_company=None,
    sibling_settled=False,
    queue_after_first=frozenset(),
    rows_after_first=2,
    # #622's ratification. See the assertion.
    rows_after_second=3,
    # The seeded card stays dismissed and invisible; both mints are on the
    # board. TWO CARDS AT ONE EMPLOYER is what the user actually sees, and it is
    # the outcome option 1 accepts.
    board_rows_after_second=2,
    seed_dismissed_at=DISMISSED_AT,
    seed_dismissed_reason="user",
    seed_status="applied",
)
#: THE CONTROL. A re-sync's opinion; answering it puts the card back (#595) and
#: the conversation stays whole.
RESYNC_ARM = Arm(
    reason="resync",
    queue_before=frozenset({FIRST_MESSAGE}),
    lands_on_the_seeded_card=True,
    restored=True,
    restored_company=COMPANY,
    sibling_settled=True,
    queue_after_first=frozenset(),
    rows_after_first=1,
    rows_after_second=1,
    # The restored card, and only it.
    board_rows_after_second=1,
    seed_dismissed_at=None,
    seed_dismissed_reason=None,
    seed_status=ANSWERED_STATUS,
)
ARMS = (USER_ARM, RESYNC_ARM)


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
    usable here: several modules reload ``jobtracker.config`` during collection,
    which mints a second settings object while ``jobtracker.auth.supabase_jwt``
    and ``jobtracker.database.connection`` keep their bindings on the first, so
    patching one instance sets the JWT secret on an object the verifier never
    reads (#582). Green alone, ``401 Invalid signature`` in a full run.
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


@pytest.fixture(params=ARMS, ids=[arm.reason for arm in ARMS])
def arm(request) -> Arm:
    """The one variable. Parametrized at the FIXTURE so both tests see both arms.

    Not on the tests individually: the fixture control below and the probe
    itself have to run against the same two seeds, or the control is asserting
    the integrity of a fixture the probe does not use.
    """

    return request.param


@pytest.fixture
async def seeded(cloud_app, arm: Arm) -> int:
    """One dismissed card holding a two-message thread, both un-reviewed.

    Written straight at the session. No endpoint offers to create this state:
    it is what a re-sync leaves behind — ``NEEDS_REVIEW`` mail still linked to a
    card the same pass dismissed — with the dismissal reason then set by hand
    for the ``user`` arm.

    ``identity_role``/``identity_req_id`` are left NULL on both messages so the
    review key derives from subject plus snippet, which is the text control 1
    is about. ``source`` is ``SOURCE_GMAIL_AUTO``, whose value is "gmail" — NOT
    the plausible-looking "gmail_auto", which ``_is_auto_row`` reads as an
    unknown/legacy tag and therefore as user-owned; the stage advance is gated
    on that function, so the wrong string makes the ``resync`` arm assert a card
    that comes back at the stage it was dismissed at.

    Returns the seeded application's id — the ``D`` of #622.
    """

    from jobtracker.database import get_session

    owner = uuid.UUID(OWNER)

    async with get_session() as session:
        row = Application(
            user_id=owner,
            company=COMPANY,
            position=ROLE,
            status=ApplicationStatus.APPLIED,
            source="gmail",
            req_id=REQ_ID,
            role_token=ROLE_TOKEN,
            dismissed_at=DISMISSED_AT,
            # THE ONLY COLUMN THAT DIFFERS BETWEEN THE TWO ARMS.
            dismissed_reason=arm.reason,
        )
        session.add(row)
        await session.flush()
        application_id = row.id

        for message_id, minutes in ((FIRST_MESSAGE, 0), (SECOND_MESSAGE, 90)):
            session.add(
                Email(
                    user_id=owner,
                    # LINKED to the dismissed card — both of them. That is the
                    # whole shape: the thread SPANS the card, so the resolver's
                    # link branch is what decides each message's fate.
                    application_id=application_id,
                    source_account=EmailSource.GMAIL,
                    message_id=message_id,
                    thread_id=THREAD_ID,
                    subject=SUBJECT,
                    sender_name="Careers",
                    sender_email=SENDER,
                    received_at=RECEIVED_AT - timedelta(minutes=minutes),
                    body_snippet=SNIPPET,
                    classified_as=EmailCategory.NEEDS_REVIEW,
                    classification_confidence=0.80,
                    is_reviewed=False,
                    user_corrected=False,
                )
            )

        await session.commit()

    return application_id


async def _queue_message_ids(client: AsyncClient, headers: dict[str, str]) -> set[str]:
    resp = await client.get("/applications/review", headers=headers)
    assert resp.status_code == 200, resp.text
    return {item["message_id"] for item in resp.json()["items"]}


async def _board(client: AsyncClient, headers: dict[str, str]) -> dict[str, dict]:
    """Company → the card on the board, for the cards the user can SEE."""

    resp = await client.get("/applications", headers=headers)
    assert resp.status_code == 200, resp.text
    return {row["company"]: row for row in resp.json()["applications"]}


async def _rows_by_id() -> dict[int, Application]:
    """Every application of the owner's, dismissed included, read at the session.

    No endpoint of the owner's lists a dismissed row beside its
    ``dismissed_reason``, and half the claims here are claims about exactly
    those columns on a row the board will not show.
    """

    from jobtracker.database import get_session

    async with get_session() as session:
        rows = (
            await session.exec(
                select(Application).where(Application.user_id == uuid.UUID(OWNER))
            )
        ).all()
    return {row.id: row for row in rows}


async def _message_rows() -> dict[str, Email]:
    """Both stored messages by id — the board never shows a message's link."""

    from jobtracker.database import get_session

    async with get_session() as session:
        rows = (
            await session.exec(
                select(Email).where(Email.user_id == uuid.UUID(OWNER))
            )
        ).all()
    return {row.message_id: row for row in rows}


def _rows_at_the_employer(rows: dict[int, Application]) -> list[Application]:
    return [row for row in rows.values() if row.company == COMPANY]


async def _assert_the_seeded_card(seeded: int, arm: Arm) -> None:
    """The seeded card's state, as ABSOLUTE VALUES rather than as a difference.

    The #618 style, and the reason for it is that "unchanged" is not a claim a
    test can make: reading the row before and comparing greens on a fixture that
    was already wrong, and asserting "not the minted row's value" greens on a
    row that adopted a THIRD application's key. Every column the two paths
    through ``classify_review_item`` could move is named with the value it is
    supposed to hold.
    """

    rows = await _rows_by_id()
    card = rows[seeded]
    assert card.dismissed_at == arm.seed_dismissed_at, (
        "the seeded card's dismissal did not survive an answer about one of "
        "its messages"
        if arm.reason == "user"
        else "answering the surfaced question did not put the card back (#595)"
    )
    assert card.dismissed_reason == arm.seed_dismissed_reason
    assert card.status.value == arm.seed_status
    # The identity columns, on both arms. A landing may advance a stage; it may
    # not rewrite the card's job title or its keys, and #618 is the measurement
    # of what happens when one application starts wearing another's identity.
    assert card.company == COMPANY
    assert card.position == ROLE
    assert card.req_id == REQ_ID
    assert card.role_token == ROLE_TOKEN


# =============================================================================
# The fixture controls — without these the file is green and vacuous
# =============================================================================


async def test_the_fixture_is_one_conversation_no_queue_entry_answers_for(
    client, headers, arm: Arm, seeded: int
):
    """Runs first. Pins the seed, the shared review key, and what is ASKED.

    Four claims, each closing a way this module could pass while proving
    nothing:

    1. one card, dismissed at the SAME timestamp in both arms, differing only
       in the reason — without that the pair has two variables and neither arm
       proves which column is read;
    2. the board is empty, so a card appearing later appeared because an answer
       put it there;
    3. BOTH MESSAGES SHARE ONE REVIEW KEY, and it is not ``None``. This is
       control 1 of the module docstring: ``pipeline.review_dedup_key`` is what
       lets one decision settle a sibling (#454), so differing text would leave
       the ``resync`` arm's sibling alone for a reason that has nothing to do
       with dismissal. Asserted as the VALUE, because two nameless messages
       also compare equal and pin nothing;
    4. THE QUEUE. Empty in the ``user`` arm — both messages are answered for by
       a card that a person removed on purpose (#597) — and exactly the newer
       message in the ``resync`` arm, which is one conversation offered once.
       Asserted by IDENTITY rather than by count: if the queue offered the
       sibling instead, the probe's first call would be an inbox reclassify
       wearing the queue's clothes and the arms would not be comparable.
    """

    from jobtracker.cloud import pipeline
    from jobtracker.cloud.applications import _review_key

    rows = await _rows_by_id()
    assert len(rows) == 1
    card = rows[seeded]
    assert card.dismissed_at == DISMISSED_AT, (
        "both arms must share one dismissed_at; a differing timestamp leaves a "
        "second variable between the case and its control"
    )
    assert card.dismissed_reason == arm.reason
    assert pipeline.normalize_role_token(ROLE) == ROLE_TOKEN, (
        "the hardcoded role token drifted from the product's own normalizer"
    )

    assert await _board(client, headers) == {}, (
        "the board must start empty — otherwise a card 'appearing' proves "
        "nothing about the answer that was supposed to mint it"
    )

    messages = await _message_rows()
    assert set(messages) == {FIRST_MESSAGE, SECOND_MESSAGE}
    for message_id, stored in messages.items():
        assert stored.application_id == seeded, message_id
        assert stored.is_reviewed is False, message_id
        assert stored.classified_as == EmailCategory.NEEDS_REVIEW, message_id
        assert stored.thread_id == THREAD_ID, message_id

    first_key = _review_key(messages[FIRST_MESSAGE])
    second_key = _review_key(messages[SECOND_MESSAGE])
    assert first_key == second_key == (THREAD_ID, ROLE_TOKEN), (
        "the two messages do not share a review key, so nothing below is about "
        "a thread the product reads as ONE decision — and a key of "
        f"(thread, None) would be equal for any nameless pair. Got {first_key} "
        f"and {second_key}"
    )

    assert await _queue_message_ids(client, headers) == set(arm.queue_before), (
        "the queue is not asking what this arm assumes it asks"
    )


# =============================================================================
# #622 — the decision: option 1, the thread splits and each answer mints
# =============================================================================


async def test_a_split_thread_is_the_decision(client, headers, arm: Arm, seeded: int):
    """RATIFIES OPTION 1 OF #622. Reclassify both messages; get two cards.

    Driven through the REAL endpoint on both calls, because the whole shape is
    only reachable through it: ``POST /applications/review/{id}/classify`` is
    what ``/inbox``'s reclassify control sends, it names ONE message id, and it
    sends no ``application_id`` for an already-filed message on the documented
    grounds that the message's own link beats every tie-break. That link is the
    hand-dismissed card, which the resolver REFUSES — so a fresh card is minted
    beside it, and the sibling, being answered for by the card it still points
    at, is not swept along.

    The ``resync`` arm is the same probe with ``dismissed_reason`` flipped and
    it comes out the other way on every axis: the answer lands on the seeded
    card, the card is restored (#595), the sibling is settled onto it, and the
    employer holds one row no matter how many messages are answered. Two
    outcomes from one column is what makes this a decision about hand dismissal
    rather than a property of threads.

    MUTATION LEDGER: the module docstring's, in full. The short version is that
    deleting the ``not _user_dismissed(linked)`` refusal reds the ``user`` arm's
    first landing assertion, and giving the sibling a different subject reds the
    ``resync`` arm's settle assertions while leaving the ``user`` arm correctly
    green.
    """

    # READ BEFORE THE ANSWER, deliberately: it makes reachability part of this
    # test rather than an assumption, so a change to the queue predicate reds
    # here instead of leaving the probe inert.
    assert await _queue_message_ids(client, headers) == set(arm.queue_before)

    first = await client.post(
        f"/applications/review/{FIRST_MESSAGE}/classify",
        json={"category": ANSWER},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    body = first.json()
    # A 2xx is not on its own a filing — see `classify_review_item`. If the
    # employer could not be named the item is left in the queue untouched and
    # everything below is measuring a request that did nothing.
    assert body["needs_employer"] is False, first.text

    # ORDERED SHARPEST FIRST. pytest stops at the first failing assert, so the
    # claim stated first is the one a reader of the red actually sees, and the
    # landing IS #622's signature. The counts, which are consequences of it,
    # come after the state assertions rather than before.
    first_landing = body["application_id"]
    if arm.lands_on_the_seeded_card:
        assert first_landing == seeded, (
            "a machine-dismissed card is still the right row to land on, and "
            f"the answer went somewhere else ({first_landing})"
        )
    else:
        assert first_landing != seeded, (
            "the answer landed on the card the user dismissed by hand — #597 "
            "is gone and #622's shape with it"
        )
    assert body["restored"] is arm.restored, first.text
    assert body["restored_company"] == arm.restored_company, first.text

    messages = await _message_rows()
    answered = messages[FIRST_MESSAGE]
    assert answered.application_id == first_landing, (
        "the response named one row and the stored message points at another "
        f"({answered.application_id}); the two are written in one transaction"
    )
    assert answered.is_reviewed is True

    # THE SIBLING. Note that its `application_id` is the seeded card's id in
    # BOTH arms and means opposite things: in the `resync` arm the settle wrote
    # back the id it already held (that is why #591's "this is a relink"
    # objection was wrong), and in the `user` arm nothing touched it at all. So
    # `is_reviewed` and the stored category are what actually separate settled
    # from unmoved, and the link alone would green either way.
    sibling = messages[SECOND_MESSAGE]
    assert sibling.application_id == seeded, (
        "the sibling moved off the card it was filed on; neither path is "
        "supposed to relink it"
    )
    if arm.sibling_settled:
        assert sibling.is_reviewed is True, (
            "one decision settles the whole conversation, and the sibling was "
            "left un-reviewed — it is queued again on the next re-sync"
        )
        assert sibling.classified_as.value == ANSWER
    else:
        assert sibling.is_reviewed is False, (
            "the sibling was settled by a decision about a different message, "
            "which is option 2 of #622 and was not the option chosen"
        )
        assert sibling.classified_as == EmailCategory.NEEDS_REVIEW, (
            "the sibling took the answered category without being answered"
        )

    await _assert_the_seeded_card(seeded, arm)

    rows = await _rows_by_id()
    at_employer = _rows_at_the_employer(rows)
    assert len(at_employer) == arm.rows_after_first, (
        f"expected {arm.rows_after_first} row(s) at {COMPANY} after one answer, "
        f"got {[(r.id, r.dismissed_reason) for r in at_employer]}"
    )
    if not arm.lands_on_the_seeded_card:
        minted = rows[first_landing]
        assert minted.company == COMPANY, (
            "the mint carries a display name the seeded card does not, so the "
            "row counts above are counting two different employers"
        )
        assert minted.dismissed_at is None
        assert minted.status.value == ANSWERED_STATUS

    # THE SPLIT MUST NOT LEAK A QUEUE ENTRY. The sibling is settled by the
    # standing instruction — its card answers for it — so it is not offered,
    # not re-asked, and the `needs_review` tile does not move. #622 names this:
    # the sibling is not lost, it is reachable in `/inbox` badged `on a removed
    # row`, and reclassifying it is exactly what the second half of this test
    # does.
    assert await _queue_message_ids(client, headers) == set(arm.queue_after_first)

    second = await client.post(
        f"/applications/review/{SECOND_MESSAGE}/classify",
        json={"category": ANSWER},
        headers=headers,
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["needs_employer"] is False, second.text
    second_landing = second_body["application_id"]
    if arm.lands_on_the_seeded_card:
        assert second_landing == seeded
    else:
        assert second_landing not in (seeded, first_landing), (
            "the second reclassify was expected to mint a THIRD row; it landed "
            f"on {second_landing}"
        )
    # Nothing is restored by either second answer, and for different reasons:
    # the `user` arm mints again, and the `resync` arm's card is already live.
    assert second_body["restored"] is False, second.text
    assert second_body["restored_company"] is None, second.text

    await _assert_the_seeded_card(seeded, arm)

    rows = await _rows_by_id()
    at_employer = _rows_at_the_employer(rows)
    # ===================================================================
    # THIS IS THE RATIFICATION, and it is the whole reason the file exists.
    #
    # Three rows at one employer is not a defect being pinned. It is OPTION 1
    # OF #622 being chosen: `/inbox`'s reclassify is a per-MESSAGE control, the
    # queue never offered this conversation at all (asserted above — it is
    # empty in this arm), and n per-message commands therefore yield n cards. A
    # four-message thread would mint four, and every one of them is one dismiss
    # click from tidy.
    #
    # The alternative was to carry the answered message's unreviewed thread
    # siblings to the mint, which moves mail OFF a hand-dismissed card on the
    # strength of a decision about a DIFFERENT message. That is not option 1,
    # and a reader who arrives here wanting it should reopen #622 rather than
    # change this number.
    # ===================================================================
    assert len(at_employer) == arm.rows_after_second, (
        f"expected {arm.rows_after_second} row(s) at {COMPANY} after both "
        f"messages were answered, got "
        f"{[(r.id, r.dismissed_reason) for r in at_employer]}"
    )

    # AND THE BOARD SAYS THE SAME THING. The count above is a session read that
    # includes a dismissed row nobody can see, so it cannot on its own say what
    # the user is looking at: two cards at one employer in the `user` arm, one
    # restored card in the `resync` arm.
    board_rows = [
        row
        for row in (await client.get("/applications", headers=headers)).json()[
            "applications"
        ]
        if row["company"] == COMPANY
    ]
    assert len(board_rows) == arm.board_rows_after_second, (
        f"the board shows {len(board_rows)} row(s) at {COMPANY} where this arm "
        f"expects {arm.board_rows_after_second}"
    )
