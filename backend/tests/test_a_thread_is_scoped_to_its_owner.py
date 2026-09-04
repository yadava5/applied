"""One account's mail must not decide another account's thread placements.

Why this file exists
--------------------

``threads_naming_one_application`` reads every filed message, groups it by
thread, and keeps the threads that name exactly one live application. The sync
then treats membership of that set as "this conversation already belongs
somewhere", which is how an identity-less arrival lands on the right card.

The tenant predicate in its first query — ``Email.user_id == user_id`` — had **no
control in a 2,921-test suite** (#718). Deleting it left the entire backend green.
Not a production defect: the line is present and correct. Coverage that reads as
present and is not, which is this repository's named recurring shape.

Why 2,921 tests could not see it
--------------------------------

**Every fixture that reaches this function is single-user.** The corpus harness
hardcodes one user id, the four direct callers each build one account, and the
modules that DO have a second user never reach this function. With one account
in the database the predicate is a no-op, so its deletion changes nothing.

That is only half the reason, and the other half is the trap this file is really
about. **A two-user fixture is not automatically enough.** Give each user their
own thread and only ONE of the two failures appears:

* a thread holding only the stranger's mail LEAKS into the owner's set;
* the owner's own placement is never lost, because nothing collides.

The second failure needs the stranger's mail on the OWNER'S thread id. Then the
thread names two applications, ``len(apps) == 1`` is false, and the thread drops
out of the owner's set entirely — the owner's correct placement destroyed by a
message they cannot see. Both cases are below, and
``test_the_predicate_is_observable_in_both_directions`` is the one that fails if
a future fixture quietly loses the collision.

Blast radius, stated precisely: this decides where an identity-less follow-up
lands. It is not an authorization boundary — RLS is, and
``test_rls_postgres.py`` owns that. This is the application-level half agreeing
with it.

Every employer, sender and domain here is INVENTED and every domain is RFC 2606
reserved. Nothing in this file comes from a real mailbox (#593).
"""

from __future__ import annotations

import datetime
import uuid

import pytest
from sqlmodel import select

from jobtracker.cloud.applications import (
    Application,
    ApplicationStatus,
    Email,
    EmailCategory,
    EmailSource,
    threads_naming_one_application,
)

#: The account under test, and the one whose mail must never be consulted for it.
OWNER = uuid.UUID("00000000-0000-0000-0000-000000000718")
STRANGER = uuid.UUID("00000000-0000-0000-0000-000000000719")

STORED_AT = datetime.datetime(2026, 8, 24, 10, 0, 0)

#: The thread the owner has a placement on, and which the stranger also touches.
#: One thread id across two accounts is not contrived: Gmail thread ids are per
#: mailbox, but nothing in the schema or this query says so, and the predicate
#: under test is the only thing that makes that assumption safe.
SHARED_THREAD = "t-shared"

#: A thread only the stranger has mail on.
STRANGER_THREAD = "t-stranger-only"

#: A thread only the owner has mail on. The positive control: if this stops
#: being named, the fixture has stopped reaching the function and every
#: assertion below would pass on an empty set.
OWNER_THREAD = "t-owner-only"


async def _card(session, user_id: uuid.UUID, company: str) -> int:
    row = Application(
        user_id=user_id,
        company=company,
        position="",
        status=ApplicationStatus.APPLIED,
        source="gmail",
    )
    session.add(row)
    await session.flush()
    return row.id


async def _mail(
    session,
    *,
    user_id: uuid.UUID,
    company: str,
    message_id: str,
    thread_id: str,
    application_id: int,
) -> None:
    session.add(
        Email(
            user_id=user_id,
            application_id=application_id,
            source_account=EmailSource.GMAIL,
            message_id=message_id,
            thread_id=thread_id,
            subject=f"Update on your {company} application",
            sender_name="Careers",
            sender_email=f"careers@{company.lower()}.test",
            received_at=STORED_AT,
            body_snippet="Thank you for taking the time to speak with us.",
            classified_as=EmailCategory.REJECTION,
            classification_confidence=0.78,
            is_reviewed=False,
            user_corrected=False,
        )
    )


@pytest.fixture
async def two_accounts(test_session) -> dict[str, int]:
    """The owner and a stranger, with the stranger's mail on a shared thread.

    The collision is the point. Without it this fixture cannot see half the
    damage, which is exactly why the existing two-user modules missed it.
    """

    owner_card = await _card(test_session, OWNER, "Halberd")
    stranger_card = await _card(test_session, STRANGER, "Ironvale")

    # The owner's own placement, on a thread the stranger also writes to.
    await _mail(
        test_session,
        user_id=OWNER,
        company="Halberd",
        message_id="m-owner-shared",
        thread_id=SHARED_THREAD,
        application_id=owner_card,
    )
    # The stranger's mail on the OWNER's thread, naming the STRANGER's card.
    await _mail(
        test_session,
        user_id=STRANGER,
        company="Ironvale",
        message_id="m-stranger-shared",
        thread_id=SHARED_THREAD,
        application_id=stranger_card,
    )
    # A thread only the stranger touches at all.
    await _mail(
        test_session,
        user_id=STRANGER,
        company="Ironvale",
        message_id="m-stranger-only",
        thread_id=STRANGER_THREAD,
        application_id=stranger_card,
    )
    # A thread only the owner touches at all — the positive control.
    await _mail(
        test_session,
        user_id=OWNER,
        company="Halberd",
        message_id="m-owner-only",
        thread_id=OWNER_THREAD,
        application_id=owner_card,
    )
    await test_session.commit()
    return {"owner": owner_card, "stranger": stranger_card}


@pytest.mark.asyncio
async def test_the_fixture_really_holds_two_accounts(test_session, two_accounts) -> None:
    """The control. Every assertion below is vacuous against a one-user fixture.

    2,921 tests missed this predicate because none of them had a second user's
    filed mail anywhere near it. A fixture that quietly lost its second account
    would reproduce that silence exactly, so it is asserted rather than assumed.
    """

    owners = (await test_session.exec(select(Email.user_id))).all()

    assert set(owners) == {OWNER, STRANGER}, (
        f"the fixture holds mail for {set(owners)}. Both accounts must have "
        "filed mail or the tenant predicate is a no-op and nothing below can fail."
    )
    shared = [t for t in (await test_session.exec(select(Email.thread_id))).all() if t == SHARED_THREAD]
    assert len(shared) == 2, (
        "the shared thread must carry mail from BOTH accounts. Without the "
        "collision only the leak is observable and the lost-placement half of "
        "#718 goes unmeasured."
    )


@pytest.mark.asyncio
async def test_a_thread_holding_only_a_strangers_mail_is_not_named(
    test_session, two_accounts
) -> None:
    """The leak. Nothing about the stranger's conversation is the owner's."""

    named = await threads_naming_one_application(test_session, OWNER)

    assert STRANGER_THREAD not in named, (
        f"{STRANGER_THREAD!r} holds only the stranger's filed mail and it is in "
        "the owner's set. An identity-less arrival on that conversation would "
        "now be filed against whatever card it names."
    )


@pytest.mark.asyncio
async def test_a_strangers_mail_cannot_unname_the_owners_thread(
    test_session, two_accounts
) -> None:
    """The half a separate-threads fixture cannot see.

    The owner has a placement on ``SHARED_THREAD``. The stranger's mail on the
    same thread id names a DIFFERENT application, so without the predicate the
    thread names two and is dropped for naming none — the owner's own correct
    placement destroyed by a message they cannot see.
    """

    named = await threads_naming_one_application(test_session, OWNER)

    assert SHARED_THREAD in named, (
        f"{SHARED_THREAD!r} names exactly one of the OWNER's applications and is "
        "missing from the owner's set. A stranger's mail on the same thread id "
        "has been allowed to vote on which card the owner's conversation names."
    )


@pytest.mark.asyncio
async def test_the_owners_own_thread_is_still_named(test_session, two_accounts) -> None:
    """The positive control. A function returning an empty set passes both tests above."""

    named = await threads_naming_one_application(test_session, OWNER)

    assert OWNER_THREAD in named, (
        "the owner's own single-card thread is not named, so this function is "
        "returning less than it should and the two assertions above are passing "
        "on an empty set rather than on a scoped one."
    )


@pytest.mark.asyncio
async def test_the_predicate_is_observable_in_both_directions(
    test_session, two_accounts
) -> None:
    """What the deletion actually costs, asserted as a pair.

    Deleting ``Email.user_id == user_id`` does two different things at once, and
    a fixture that shows only one of them is the reason this went unnoticed. The
    unscoped answer is computed here the way the mutated function would compute
    it, so the two sets can be compared directly rather than described.
    """

    scoped = await threads_naming_one_application(test_session, OWNER)

    rows = (
        await test_session.exec(
            select(Email.thread_id, Email.application_id).where(
                Email.thread_id.is_not(None),
                Email.application_id.is_not(None),
            )
        )
    ).all()
    by_thread: dict[str, set[int]] = {}
    for thread_id, application_id in rows:
        by_thread.setdefault(thread_id, set()).add(application_id)
    names_one = {t: next(iter(a)) for t, a in by_thread.items() if t and len(a) == 1}
    live = set(
        (
            await test_session.exec(
                select(Application.id).where(Application.id.in_(list(names_one.values())))
            )
        ).all()
    )
    unscoped = frozenset(t for t, a in names_one.items() if a in live)

    leaked = unscoped - scoped
    dropped = scoped - unscoped

    assert leaked == {STRANGER_THREAD}, (
        f"expected the stranger's own thread to be what leaks; got {sorted(leaked)}"
    )
    assert dropped == {SHARED_THREAD}, (
        f"expected the owner's shared-thread placement to be what is lost; got "
        f"{sorted(dropped)}"
    )
