"""A re-sync that omits a thread id must not unlink a message from its thread.

``_persist_message_refs`` carries this comment, and has since the snippet
version of the same bug was fixed:

    A thread id, likewise: a metadata fetch that omits it must not unlink a
    message from its conversation.

    if ref.thread_id:
        existing.thread_id = ref.thread_id

Four lines below it, ``existing.thread_id = ref.thread_id`` ran again —
unconditionally — and blanked exactly what the guard had just protected. The
guard was written, documented, and then defeated in the same block, so the
comment described behaviour the file did not have.

WHAT IT COSTS. ``thread_id`` is what ``_settle_thread_siblings`` walks to settle
the rest of a conversation when the user classifies one message of it, and what
``gmail_deeplink`` needs to open the right conversation. A blanked thread id
turns both into no-ops silently.

This is the same defect family as issue #430: a check that reads correctly at
the point it is written and is undone by a later line in the same function.
"""

from __future__ import annotations

import datetime
import uuid

import pytest
from sqlmodel import select

from jobtracker.cloud import pipeline
from jobtracker.cloud.applications import Email, _persist_message_refs

USER = uuid.UUID("00000000-0000-0000-0000-0000000000bb")
RECEIVED = datetime.datetime(2026, 8, 21, 7, 45)


def ref(thread_id: str | None) -> pipeline.MessageRef:
    return pipeline.MessageRef(
        message_id="m1",
        thread_id=thread_id,
        subject="Thanks for applying to Google",
        sender_email="noreply@google.com",
        sender_name=None,
        received_at=RECEIVED,
        category="applied",
        confidence=0.9,
        snippet="Hi Ayush Yadav, Thanks for applying to Google!",
    )


async def _stored(session) -> Email:
    return (await session.exec(select(Email).where(Email.message_id == "m1"))).one()


@pytest.mark.asyncio
async def test_a_ref_without_a_thread_id_leaves_the_stored_one_alone(test_session):
    await _persist_message_refs(test_session, USER, None, [ref("1a0234892a062ff6")])
    await test_session.commit()
    assert (await _stored(test_session)).thread_id == "1a0234892a062ff6"

    # The metadata-only pass: same message, no thread id this time.
    await _persist_message_refs(test_session, USER, None, [ref(None)])
    await test_session.commit()

    assert (await _stored(test_session)).thread_id == "1a0234892a062ff6", (
        "a re-sync that did not fetch the thread id erased the stored one. "
        "_settle_thread_siblings and gmail_deeplink both read this column."
    )


@pytest.mark.asyncio
async def test_an_empty_string_is_not_a_thread_id_either(test_session):
    """``_parse_metadata_message`` defaults ``threadId`` to ``""``, not None.

    The guard is a truthiness test, so it already covers this — but only the
    guard does, and the assignment it was fighting did not. Pinned separately
    because the two callers reach here with different absent-values and a fix
    that handled one of them would look complete.
    """

    await _persist_message_refs(test_session, USER, None, [ref("1a0234892a062ff6")])
    await test_session.commit()
    await _persist_message_refs(test_session, USER, None, [ref("")])
    await test_session.commit()

    assert (await _stored(test_session)).thread_id == "1a0234892a062ff6"


@pytest.mark.asyncio
async def test_a_ref_that_carries_one_still_updates_it(test_session):
    """The control. The guard must not freeze the column against real news.

    Without this pair the whole fix could be "never write thread_id" and both
    tests above would still pass.
    """

    await _persist_message_refs(test_session, USER, None, [ref(None)])
    await test_session.commit()
    assert (await _stored(test_session)).thread_id is None

    await _persist_message_refs(test_session, USER, None, [ref("19ff97772e932c0f")])
    await test_session.commit()
    assert (await _stored(test_session)).thread_id == "19ff97772e932c0f"
