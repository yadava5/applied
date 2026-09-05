"""A review row with no stored snippet, settled by its sibling's decision.

ISSUE #462, the residual #454 left and named. Every site in the review path
keys on ``review_dedup_key(thread_id, <which application this names>)``, and a
row whose identity columns are both NULL and whose ``body_snippet`` is empty
names nothing — so a decision on a sibling that DOES name a role did not reach
it. The user answered the one entry the queue offered and the same
conversation came back to be answered again.

MEASURED THROUGH THE SHIPPED PATH before anything was changed, two rows in one
thread on SQLite, classifying the first:

    CONTROL  sibling has snippet + identity       -> settled=1  is_reviewed=True
    CONTROL  sibling has snippet, identity NULL   -> settled=1  is_reviewed=True
    #462     sibling snippet NULL + identity NULL -> settled=0  is_reviewed=False
    #462     sibling snippet ''   + identity NULL -> settled=0  is_reviewed=False

The two controls settling are what make the two failures mean something: the
row is not skipped because the settle is inert, it is skipped because its key
is ``('t', None)`` and the decided key is ``('t', 'backend engineer alarms')``.

WHY THE FIX IS NOT A BACKFILL. The population has two sources and only one of
them is historical. ``d5e91c4a7f28`` added the identity columns and backfilled
nothing, deliberately; and ``_record_scanned_email`` writes both columns NULL
on EVERY client-relayed scan on purpose, because ``PipelineItemIn``
"deliberately does not accept" an identity from a client "and must not learn
to" — accepting one would let a client reshape dedup keys. That second source
is permanent by security design, so a migration cannot close this issue. The
rule has to be about what the thread says, and it is: an unknown row is
settled only when the whole conversation names exactly ONE application, which
is then the only application the row could be about.

WHAT THIS MODULE IS REALLY GUARDING is the other direction. #454's defect was
settling every message of a four-role ATS thread onto whichever of the four
the user happened to answer — a 1-in-4 guess that files mail on the wrong card
and, because rejection is terminal, can settle a live application. Three tests
below exist to keep that closed, and each names the same-typed mutation that
reds it: deleting the one-name guard, narrowing the census to the rows the
settle can still touch, and spelling the NULL test as ``not role`` so a
derived "names nothing" collapses into "nothing was derived".
"""

from __future__ import annotations

import datetime
import uuid

from sqlmodel import select

from jobtracker.cloud import applications as apps
from jobtracker.cloud import pipeline as p
from jobtracker.cloud.applications import (
    Application,
    ApplicationStatus,
    Email,
    EmailCategory,
    EmailSource,
)

OWNER = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
STRANGER = uuid.UUID("c2c2c2c2-c2c2-4c2c-8c2c-c2c2c2c2c2c2")

THREAD = "t-halberd-ack"
SUBJECT = "Thank you for applying to Halberd Robotics"
COMPANY = "Halberd Robotics"

#: Two roles at one employer, in one Gmail thread — the shape that threads on a
#: byte-identical subject and sender and is nonetheless two applications.
ROLE_A = "Backend Engineer, Alarms"
ROLE_B = "Firmware Engineer, Sensors"

SNIPPET_A = (
    "Hi there, Thank you so much for applying to the Backend Engineer, Alarms "
    "role at Halberd Robotics! Our team will review your application."
)
SNIPPET_B = (
    "Hi there, Thank you so much for applying to the Firmware Engineer, "
    "Sensors role at Halberd Robotics! Our team will review your application."
)

RECEIVED_AT = datetime.datetime(2026, 8, 22, 9, 0)


def mail(
    message_id: str,
    *,
    snippet: str | None,
    role: str | None,
    req_id: str | None = None,
    is_reviewed: bool = False,
    user_id: uuid.UUID = OWNER,
) -> Email:
    """One stored message. ``snippet=None`` is the row #462 is about.

    ``role=None, req_id=None`` is "no derivation exists" — what the migration
    left and what the relay path writes. ``role=""`` is "a reader looked and
    the message names no application", which is a different fact.
    """

    return Email(
        user_id=user_id,
        source_account=EmailSource.GMAIL,
        message_id=message_id,
        thread_id=THREAD,
        subject=SUBJECT,
        sender_name="Careers",
        sender_email="careers@halberd.test",
        received_at=RECEIVED_AT,
        body_snippet=snippet,
        identity_role=role,
        identity_req_id=req_id,
        classified_as=EmailCategory.NEEDS_REVIEW,
        classification_confidence=0.80,
        is_reviewed=is_reviewed,
    )


def key(row: Email):
    return p.review_dedup_key(
        message_id=row.message_id,
        thread_id=row.thread_id,
        subject=row.subject or "",
        snippet=row.body_snippet or "",
        identity_role=row.identity_role,
        identity_req_id=row.identity_req_id,
    )


async def settle(session, decided: Email, others: list[Email]) -> int:
    """Seed a thread, answer ``decided``, and return how many rows settled.

    The answered message lands on a card the way the endpoint's own resolve
    would land it, so the id the settle writes onto a sibling is a real one and
    an assertion about the link means something.
    """

    card = Application(
        user_id=OWNER,
        company=COMPANY,
        position=ROLE_A,
        status=ApplicationStatus.APPLIED,
        source="gmail_auto",
    )
    session.add(card)
    await session.flush()

    decided.application_id = card.id
    session.add(decided)
    for row in others:
        session.add(row)
    await session.commit()

    settled = await apps._settle_thread_siblings(
        session, OWNER, decided, EmailCategory.REJECTION, card.id
    )
    await session.commit()
    return settled


async def stored(session, message_id: str) -> Email:
    return (
        await session.exec(select(Email).where(Email.message_id == message_id))
    ).one()


# --- the positive control the rest of the module rests on --------------------


def test_the_two_shapes_really_do_hold_different_keys() -> None:
    """Without this every assertion below could pass for the wrong reason.

    If the snippet-less row keyed the same as the decided one it would settle
    through plain key equality, #462 would not exist in this fixture, and the
    guard tests would be measuring nothing.
    """

    decided = key(mail("m1", snippet=SNIPPET_A, role=ROLE_A))
    unknown = key(mail("m2", snippet=None, role=None))
    second = key(mail("m3", snippet=SNIPPET_B, role=None))

    assert decided == (THREAD, "backend engineer alarms")
    assert unknown == (THREAD, None)
    assert second == (THREAD, "firmware engineer sensors")
    assert decided != unknown != second


# --- the two controls: the settle is not inert -------------------------------


async def test_a_sibling_that_names_the_same_role_settles(test_session) -> None:
    """The path that always worked — stored identity, same application."""

    settled = await settle(
        test_session,
        mail("m1", snippet=SNIPPET_A, role=ROLE_A),
        [mail("m2", snippet=SNIPPET_A, role=ROLE_A)],
    )

    sibling = await stored(test_session, "m2")
    assert settled == 1
    assert sibling.is_reviewed is True
    assert sibling.classified_as == EmailCategory.REJECTION


async def test_a_sibling_with_a_snippet_and_no_identity_re_derives(
    test_session,
) -> None:
    """NULL identity is not on its own the defect — this row settles.

    Both parts ``None`` means "no derivation exists", so ``identity_parts``
    reads the text instead and gets the same role. It is the reason the fix
    could not simply be "settle every NULL-identity sibling": most of them
    already answer for themselves.
    """

    settled = await settle(
        test_session,
        mail("m1", snippet=SNIPPET_A, role=ROLE_A),
        [mail("m2", snippet=SNIPPET_A, role=None)],
    )

    sibling = await stored(test_session, "m2")
    assert key(sibling) == (THREAD, "backend engineer alarms")
    assert settled == 1
    assert sibling.is_reviewed is True


# --- #462 itself -------------------------------------------------------------


async def test_a_null_snippet_sibling_settles_on_a_one_name_thread(
    test_session,
) -> None:
    """THE DEFECT. Measured at ``settled=0, is_reviewed=False`` before the fix.

    The thread names one application, so the row that names none is about that
    one — there is nothing else it could be about.
    """

    settled = await settle(
        test_session,
        mail("m1", snippet=SNIPPET_A, role=ROLE_A),
        [mail("m2", snippet=None, role=None)],
    )

    sibling = await stored(test_session, "m2")
    assert key(sibling) == (THREAD, None), "the fixture stopped being the defect"
    assert settled == 1, (
        "the row the queue keeps re-asking about was not settled by the answer "
        "its own conversation already gave"
    )
    assert sibling.is_reviewed is True
    assert sibling.classified_as == EmailCategory.REJECTION
    assert sibling.application_id == (await stored(test_session, "m1")).application_id


async def test_an_empty_snippet_sibling_settles_on_a_one_name_thread(
    test_session,
) -> None:
    """The other spelling of the same row — ``_persist_message_refs`` stores
    ``""`` where ``_record_scanned_email`` stores NULL, and the user cannot
    tell which path wrote their row."""

    settled = await settle(
        test_session,
        mail("m1", snippet=SNIPPET_A, role=ROLE_A),
        [mail("m2", snippet="", role=None)],
    )

    sibling = await stored(test_session, "m2")
    assert settled == 1
    assert sibling.is_reviewed is True
    assert sibling.classified_as == EmailCategory.REJECTION


async def test_a_relay_shaped_answer_settles_an_unknown_sibling(
    test_session,
) -> None:
    """THE ANSWERED ROW can be relay-shaped too, and usually is.

    ``_record_scanned_email`` writes both identity columns NULL on EVERY
    client-relayed row, so the message the user answers is as likely to carry
    no stored identity as its sibling — its name comes from re-deriving the
    snippet. The census has to read every row of the thread through the same
    cascade, or this fix would only reach threads whose answered message
    happens to have been read by the server. That is the permanent source the
    issue's proposed backfill could not have covered, so it is measured here
    rather than argued in a commit message.
    """

    settled = await settle(
        test_session,
        mail("m1", snippet=SNIPPET_A, role=None),
        [mail("m2", snippet=None, role=None)],
    )

    answered = await stored(test_session, "m1")
    sibling = await stored(test_session, "m2")
    assert key(answered) == (THREAD, "backend engineer alarms"), (
        "the answered row stopped being the re-derived shape"
    )
    assert settled == 1
    assert sibling.is_reviewed is True
    assert sibling.application_id == answered.application_id


# --- and the three that keep #454 closed -------------------------------------


async def test_a_thread_naming_two_applications_settles_nothing_unknown(
    test_session,
) -> None:
    """THE GUARD. Two names in the conversation, so "unknown" is a guess.

    This is #454's defect in the shape the #462 fix could reintroduce: settle
    the nameless row onto whichever application the user happened to answer.
    The user is asked again instead, which is visible and recoverable.

    MUTATION: delete the ``named == {decided_sub_key}`` test in
    ``_settle_thread_siblings`` — keep the arm, drop the condition — and this
    fails at ``assert 0 == 1``, with ``m3`` filed on the Alarms card.
    """

    settled = await settle(
        test_session,
        mail("m1", snippet=SNIPPET_A, role=ROLE_A),
        [
            mail("m2", snippet=SNIPPET_B, role=ROLE_B),
            mail("m3", snippet=None, role=None),
        ],
    )

    unknown = await stored(test_session, "m3")
    other = await stored(test_session, "m2")
    assert settled == 0, "a nameless row was filed on one of two applications"
    assert unknown.is_reviewed is False
    assert unknown.application_id is None
    assert unknown.classified_as == EmailCategory.NEEDS_REVIEW
    # The row that names the OTHER application is untouched either way.
    assert other.is_reviewed is False
    assert other.application_id is None


async def test_a_second_name_already_answered_still_blocks(test_session) -> None:
    """The census reads the WHOLE thread, not the rows still settleable.

    A real four-role ATS thread is answered one entry at a time. By the last
    one, three of its four names sit on rows that are already reviewed — so a
    census scoped to the settle's own candidate list sees exactly one name and
    the nameless row gets filed on it. That is the same 1-in-4 guess, reached
    by a different route.

    MUTATION: have ``_thread_sub_keys`` read ``conversation`` instead of
    querying the thread — or add ``Email.is_reviewed == False`` to its where
    clause — and this fails at ``assert 0 == 1``. The test above stays GREEN
    through that mutation, which is why both exist.
    """

    settled = await settle(
        test_session,
        mail("m1", snippet=SNIPPET_A, role=ROLE_A),
        [
            mail("m2", snippet=SNIPPET_B, role=ROLE_B, is_reviewed=True),
            mail("m3", snippet=None, role=None),
        ],
    )

    unknown = await stored(test_session, "m3")
    assert settled == 0, (
        "an already-answered second application dropped out of the census and "
        "the thread read as naming only one"
    )
    assert unknown.is_reviewed is False
    assert unknown.application_id is None


async def test_a_derived_names_nothing_row_is_not_swept_in(test_session) -> None:
    """``""`` IS NOT ``None``, and this is where that is measured.

    Empty strings are a READER'S ANSWER: the body was read and it names no
    application. Such a row keys as "the same unknown" and settles with other
    nameless mail — but it is not evidence of ignorance, so the one-name thread
    rule does not reach it.

    ONE VARIABLE. This fixture is byte-for-byte the settling ``#462`` case
    above except that its identity columns hold ``""`` where that one holds
    NULL: same subject, same absent snippet, same ``(thread, None)`` key, same
    one-name thread. So the identity spelling is the only thing that can decide
    it, and an earlier draft that also gave this row a snippet proved nothing —
    the empty-text clause excluded it and the mutation below stayed GREEN.

    MUTATION: spell ``pipeline.identity_never_derived`` as ``not req_id and not
    role`` instead of ``is None`` — a same-typed swap — and this fails at
    ``assert 1 == 0``.
    """

    settled = await settle(
        test_session,
        mail("m1", snippet=SNIPPET_A, role=ROLE_A),
        [mail("m2", snippet="", role="", req_id="")],
    )

    sibling = await stored(test_session, "m2")
    assert key(sibling) == (THREAD, None), "the key is not what excludes it"
    assert settled == 0
    assert sibling.is_reviewed is False
    assert sibling.application_id is None


async def test_two_rows_that_name_nothing_still_settle_each_other(
    test_session,
) -> None:
    """The Crusoe control, unchanged by all of this.

    Two nameless messages of one thread hold equal keys and always settled each
    other through plain equality. The #462 arm must not be what carries them —
    if it were, this would start depending on the thread naming something.
    """

    settled = await settle(
        test_session,
        mail("m1", snippet=None, role=None),
        [mail("m2", snippet=None, role=None)],
    )

    sibling = await stored(test_session, "m2")
    assert settled == 1
    assert sibling.is_reviewed is True


async def test_a_strangers_copy_of_the_thread_decides_nothing(
    test_session,
) -> None:
    """A Gmail thread id says nothing about whose mailbox it came from.

    The census is scoped to the owner for the reason
    ``test_a_thread_is_scoped_to_its_owner.py`` exists. Unscoped, the
    stranger's Sensors row would count as a second name in the owner's thread
    and their answer would stop settling their own mail.

    MUTATION: drop ``Email.user_id == user_id`` from ``_thread_sub_keys`` and
    this fails at ``assert 0 == 1``.
    """

    settled = await settle(
        test_session,
        mail("m1", snippet=SNIPPET_A, role=ROLE_A),
        [
            mail("m2", snippet=None, role=None),
            mail("s1", snippet=SNIPPET_B, role=ROLE_B, user_id=STRANGER),
        ],
    )

    assert settled == 1, "another tenant's mail decided this user's thread"
    assert (await stored(test_session, "m2")).is_reviewed is True
    # And the stranger's row was never a candidate in the first place.
    assert (await stored(test_session, "s1")).is_reviewed is False
