"""``classification_method`` must REPORT which layer answered, not assert one.

Both sync write sites in ``_persist_message_refs`` set the column to the string
literal ``"rules"``. ``jobtracker.classifier.get_classifier`` is
``get_hybrid_classifier``, whose result carries a ``method`` of ``rules`` /
``embeddings`` / ``setfit`` / ``content_filter`` / ``fallback`` — so whenever
anything but the rules layer answered, the stored row said otherwise. A column
that can only ever hold one value is not provenance; it is a constant with a
provenance-shaped name, and no query against it could ever have disagreed with
reality.

IT ALREADY COST A WRONG DIAGNOSIS. While tracing #493 the stored rows claimed
``method="rules"`` while the rules classifier, run against those exact
messages, returned something else. The contradiction read as "then some other
layer produced these labels". It had not — the checkout was stale — and the
column had nothing to say either way, because it never had anything to say.

WHY A UNIT TEST ON THE WRITE PATH AND NOT AN END-TO-END. The end-to-end needs a
live Gmail sync, which needs a connected mailbox, which is the #188 hole. The
defect is entirely in what the write does with the value it is handed, so that
is what is asserted — plus the carry through ``PipelineItem`` → ``MessageRef``,
because a faithful write of a value nobody populated would be the same bug
wearing a different hat.
"""

from __future__ import annotations

import datetime
import uuid

import pytest
from sqlmodel import select

from jobtracker.cloud import pipeline
from jobtracker.cloud.applications import Email, _persist_message_refs

USER = uuid.UUID("00000000-0000-0000-0000-0000000000c9")
RECEIVED = datetime.datetime(2026, 8, 21, 7, 45)


def ref(method: str | None, message_id: str = "m1") -> pipeline.MessageRef:
    return pipeline.MessageRef(
        message_id=message_id,
        thread_id=None,
        subject="Thanks for applying to Google",
        sender_email="noreply@google.com",
        sender_name=None,
        received_at=RECEIVED,
        category="applied",
        confidence=0.9,
        snippet="Hi Ayush Yadav, Thanks for applying to Google!",
        method=method,
    )


async def _stored(session, message_id: str = "m1") -> Email:
    return (
        await session.exec(select(Email).where(Email.message_id == message_id))
    ).one()


@pytest.mark.asyncio
async def test_a_non_rules_layer_is_recorded_as_itself(test_session):
    """The row the old literal made impossible."""

    await _persist_message_refs(test_session, USER, None, [ref("setfit")])

    stored = await _stored(test_session)
    assert stored.classification_method == "setfit", (
        "the write asserted its own idea of which layer ran instead of "
        "recording the one that did"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method",
    ["rules", "embeddings", "setfit", "content_filter", "fallback"],
)
async def test_every_layer_the_hybrid_can_emit_survives_the_write(
    test_session, method
):
    """Pinned against ``classifier/hybrid.py``'s own vocabulary.

    Parametrised rather than spot-checked so that a write which special-cases
    one value — or a mapping table that silently drops an unknown one — fails
    here rather than in production, where the only symptom is a column quietly
    reverting to a lie.
    """

    await _persist_message_refs(
        test_session, USER, None, [ref(method, message_id=f"m-{method}")]
    )

    stored = await _stored(test_session, f"m-{method}")
    assert stored.classification_method == method


@pytest.mark.asyncio
async def test_rules_still_records_as_rules(test_session):
    """CONTROL. Without it, a write that hardcodes ``"rules"`` again would
    still pass every test above that happens to pass ``"rules"`` — and deleting
    the column write entirely has to be caught by something that expects a
    value, not merely by something that expects a DIFFERENT value."""

    await _persist_message_refs(test_session, USER, None, [ref("rules", "m-r")])

    assert (await _stored(test_session, "m-r")).classification_method == "rules"


@pytest.mark.asyncio
async def test_an_unknown_method_is_null_not_a_guess(test_session):
    """The client-relay paths, where no classifier ran on this server.

    ``None`` is written through as NULL on purpose. The alternative — keeping
    the old literal as a default — is what made the column meaningless in the
    first place, and "we did not see a classifier run" is a different fact from
    "the rules layer answered". The column is ``Optional[str]`` and nullable
    rows already exist, so NULL is a state every reader already handles.
    """

    await _persist_message_refs(test_session, USER, None, [ref(None, "m-none")])

    stored = await _stored(test_session, "m-none")
    assert stored.classification_method is None, (
        "an unknown method was backfilled with a guess"
    )


@pytest.mark.asyncio
async def test_a_re_sync_updates_the_method_too(test_session):
    """The UPDATE branch is a second write site and had the same literal.

    A row first stored by one layer and re-classified by another must end up
    saying the second one, or the column goes stale in exactly the way that
    makes it untrustworthy.
    """

    await _persist_message_refs(test_session, USER, None, [ref("rules", "m-up")])
    assert (await _stored(test_session, "m-up")).classification_method == "rules"

    await _persist_message_refs(test_session, USER, None, [ref("setfit", "m-up")])
    assert (await _stored(test_session, "m-up")).classification_method == "setfit"


@pytest.mark.asyncio
async def test_the_pipeline_item_actually_carries_it(test_session):
    """The other half: a faithful write of a value nobody sets is the same bug.

    ``_message_ref`` is the only thing between the classifier result and the
    write, so if it drops ``method`` the column returns to being uniform — and
    every assertion above would still pass, because they hand a ref straight in.
    """

    item = pipeline.PipelineItem(
        message_id="m-carry",
        category="applied",
        sender_email="noreply@google.com",
        subject="Thanks for applying to Google",
        confidence=0.9,
        method="embeddings",
    )

    assert pipeline._message_ref(item).method == "embeddings", (
        "_message_ref drops the classifier's method, so the persisted column "
        "is uniform again no matter what the write does with it"
    )


@pytest.mark.asyncio
async def test_a_settled_row_keeps_its_method(test_session):
    """A human's verdict outranks the classifier's, method included.

    ``_persist_message_refs`` guards category/confidence/method together behind
    ``user_corrected or is_reviewed``. Carrying the method must not have moved
    the write outside that guard.
    """

    await _persist_message_refs(test_session, USER, None, [ref("rules", "m-set")])
    stored = await _stored(test_session, "m-set")
    stored.user_corrected = True
    stored.classification_method = "user"
    test_session.add(stored)
    await test_session.commit()

    await _persist_message_refs(test_session, USER, None, [ref("setfit", "m-set")])

    assert (await _stored(test_session, "m-set")).classification_method == "user", (
        "a re-sync overwrote a human's recorded decision"
    )
