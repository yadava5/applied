"""A review-queue row must keep the application its BODY named (#484).

THE RESIDUAL. Issue #484's titled defect — identity resolution running on
Gmail's ~200-character snippet while the classifier got the whole body — is
fixed on the ROLLED path: ``_classify_messages`` derives from the body,
``PipelineItem`` carries the answer, ``pipeline._message_ref`` forwards it and
``_persist_message_refs`` writes it.

The QUEUE path did not. ``ReviewItem``'s field list was::

    message_id thread_id subject sender_email sender_name received_at
    category confidence company_display snippet

and nothing else, so ``collect_review_items`` dropped the identity it had
already read off the item — two lines above ``review_dedup_key``, which reads
exactly those two fields to decide which application the queue entry is about.
Both persist sites then built their ``MessageRef`` without them, the field took
its ``None`` default, and the create branch of ``_persist_message_refs`` wrote
NULL. Measured on this module's fixture before the fix::

    ReviewItem fields: [... 'company_display', 'snippet']   # no identity
    stored identity_role   -> None
    stored identity_req_id -> None
    role the ITEM carried  -> 'Distributed Systems Engineer II'

WHY NO NUMBER OF SYNCS REPAIRED IT. The update branch's ratchet is
``if ref.identity_role is not None``, and a ref built without the kwarg is
always ``None``, so the healing branch could not fire either. Migration
``d5e91c4a7f28`` adds the columns and backfills nothing. A queue row's identity
was, for every row ever queued, permanently unwritable.

THE READERS WERE ALREADY LIVE. ``GET /applications/review`` renders
``role=e.identity_role or role_from_message(subject, snippet[:200])`` and cites
this issue for the ordering; ``_hold_reason_for`` passes ``stored_role=
email.identity_role`` and cites it too; ``summary``'s needs-review count keys
on ``review_dedup_key(identity_role=…, identity_req_id=…)`` off the same
columns. Three readers built for a column nothing wrote — so the queue grouped
by a body-derived identity while the row it stored held NULL, which is the
"queued one way, settled another" failure ``STORED_SNIPPET_CHARS`` records, one
layer down.

WHAT IS NOT ASSERTED HERE, deliberately. Nothing in this file says an identity
is NULL. That assertion passes today, passes under the bug, and passes under
several wrong fixes; the repository has already lost a mutant to exactly that
shape. Every claim below is that a specific STORED value equals a specific
string — including :func:`test_derived_and_names_nothing_stores_an_empty_string`,
where the value that matters is ``""`` and ``""`` is a value.

MUTATION-PROVEN, three arms, each run on its own (see the commit body):
deleting the two kwargs from ``collect_review_items``' ``ReviewItem(...)``, from
``_persist_review_items``' ``MessageRef(...)``, or from
``_persist_review_items_additive``' ``MessageRef(...)`` each turns a different
subset of this file red, and no arm leaves it green.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import pytest
from sqlmodel import select as sm_select

USER = uuid.UUID("77777777-7777-7777-7777-777777777777")

#: An ATS relay on a reserved domain. The queue path is reached because the
#: confidence sits between the review floor and the auto-file gate, NOT because
#: the employer is unnameable — ``resolve_employer`` does name this one
#: ("Ats Relay"), and :func:`test_the_premise` pins which gate is doing the work
#: so a later resolver change cannot silently move this file onto another path.
SENDER = "no-reply@ats-relay.test"
SUBJECT = "Update on your application"

#: What Gmail hands over as the preview, and therefore what ``body_snippet``
#: holds: the opening ~190 characters, which name no job.
SNIPPET = (
    "Hello, thanks for beginning your application with Contoso Systems. We are "
    "glad you are interested in what we build and in the team you would be "
    "joining. Someone from recruiting will be in"
)

#: The whole message. The title is at character ~380 — past the snippet, in the
#: same place Torc Robotics' was.
BODY = (
    SNIPPET
    + " touch shortly. Your application has been received and will be reviewed "
    "by our staff. If you are chosen to move forward in the interview process "
    "for the Distributed Systems Engineer II opportunity, we will contact you."
)

ROLE = "Distributed Systems Engineer II"

#: Same genre of mail, naming no job anywhere in it. This is the normal
#: permanent state for a talent-community acknowledgement, and it is what makes
#: ``""`` (derived, names nothing) a different fact from NULL (never derived).
SILENT_BODY = (
    "Hello, thank you for your interest in potential opportunities with our "
    "team. Your details have been added to our database and we will be in "
    "touch if a suitable opening appears."
)

#: Below ``AUTO_FILE_GATE`` (0.85) and at or above ``REVIEW_FLOOR`` (0.70).
QUEUE_CONFIDENCE = 0.75


@pytest.fixture
async def cloud_db(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """The cloud app's own ``get_session()`` over the in-memory SQLite test DB.

    Same construction as ``test_suggested_category.cloud_app`` and for the same
    reason: the persist helpers and ``review_queue_cloud`` both open their own
    session through ``jobtracker.database.get_session``, so the module-level
    engine has to point at the test database rather than a fixture-held one.
    """

    import jobtracker.auth.supabase_jwt as auth_module
    import jobtracker.config as config_module
    import jobtracker.database.connection as connection_module

    holders = {
        id(module.settings): module.settings
        for module in (config_module, auth_module, connection_module)
    }
    for instance in holders.values():
        monkeypatch.setattr(instance, "deployment", "cloud")
        monkeypatch.setattr(instance, "environment", "test")

    connection_module._engine = None

    from jobtracker.database import init_db

    await init_db()
    yield

    if connection_module._engine is not None:
        await connection_module._engine.dispose()
    connection_module._engine = None


def _scanned(
    message_id: str,
    *,
    body: str = BODY,
    thread_id: str = "t-contoso",
    req_id: str = "",
    day: int = 2,
) -> Any:
    """One message as a SERVER scan produces it — identity read off the body.

    Mirrors ``gmail_oauth._classify_messages`` exactly, ``or ""`` included: a
    server pass that looks and finds nothing records ``""``, never ``None``.
    """

    from jobtracker.cloud import pipeline

    return pipeline.PipelineItem(
        message_id=message_id,
        category="rejection",
        sender_email=SENDER,
        subject=SUBJECT,
        sender_name=None,
        received_at=datetime(2026, 8, day, 9, 0),
        confidence=QUEUE_CONFIDENCE,
        thread_id=thread_id,
        # The persisted snippet is Gmail's preview, not the body. This is the
        # whole asymmetry the issue is about.
        snippet=SNIPPET if body is BODY else body,
        identity_role=pipeline.role_from_message(SUBJECT, body) or "",
        identity_req_id=req_id or (pipeline.extract_req_id(SUBJECT, body) or ""),
    )


async def _stored(message_id: str) -> Any:
    from jobtracker.database import get_session
    from jobtracker.database.models import Email

    async with get_session() as session:
        return (
            await session.exec(sm_select(Email).where(Email.message_id == message_id))
        ).first()


def test_the_premise() -> None:
    """The fixture measures what it claims to. Four facts, all positive.

    If the extractor ever reads this title out of the preview, or the gates
    move, this fails HERE rather than quietly testing a different code path.
    """

    from jobtracker.cloud import pipeline

    # (i) the title is genuinely past the preview boundary...
    assert len(SNIPPET) < pipeline.STORED_SNIPPET_CHARS
    assert BODY.index(ROLE) > 200
    # (ii) ...so the body is the only text that names it,
    assert pipeline.role_from_message(SUBJECT, BODY) == ROLE
    # (iii) the message reaches the QUEUE because of the confidence gate,
    assert pipeline.REVIEW_FLOOR <= QUEUE_CONFIDENCE < pipeline.AUTO_FILE_GATE
    assert pipeline._qualifies_for_hard_row(_scanned("premise")) is None
    # (iv) and the queue is where it lands.
    assert [r.message_id for r in pipeline.collect_review_items([_scanned("premise")])] == [
        "premise"
    ]


def test_the_queue_item_carries_what_the_reader_derived() -> None:
    """``collect_review_items`` must hand the identity on, not drop it.

    The first of the four places this value was lost. ``review_dedup_key`` reads
    it off the item three lines below the construction, so the queue was already
    grouping by an answer it then refused to carry into storage.
    """

    from jobtracker.cloud import pipeline

    item = pipeline.collect_review_items([_scanned("carry-1")])[0]
    assert item.identity_role == ROLE
    assert item.identity_req_id == ""


async def test_the_rebuild_path_stores_the_title_the_body_named(cloud_db: None) -> None:
    """"Re-sync" — ``_persist_review_items`` — writes the identity.

    THE CONTROL THE ISSUE ASKS FOR: a message whose body names a role past
    character 200, driven through the review-persist path, leaves a POPULATED
    ``emails.identity_role`` equal to that role.
    """

    from jobtracker.cloud import pipeline
    from jobtracker.cloud.applications import _persist_review_items
    from jobtracker.database import get_session
    from jobtracker.database.models import EmailCategory

    review = pipeline.collect_review_items([_scanned("rebuild-1")])
    async with get_session() as session:
        surfaced = await _persist_review_items(session, USER, review)
        await session.commit()
    assert surfaced == 1

    row = await _stored("rebuild-1")
    assert row is not None
    assert row.identity_role == ROLE
    # The queue state is still the commitment — this changes nothing about it.
    assert row.classified_as == EmailCategory.NEEDS_REVIEW
    # And the stored snippet is still the ~190 characters that do NOT name it,
    # which is why the column has to exist at all.
    assert row.body_snippet == SNIPPET


async def test_the_routine_sync_path_stores_it_too(cloud_db: None) -> None:
    """The OTHER persist site. A routine sync takes this one.

    ``_persist_review_items_additive`` is an independently written copy of the
    same construction, and ``test_suggested_category`` records — measured, for
    the identical shape of change — that removing a writer from one site alone
    leaves the other site's tests green. Two sites, two tests.

    A requisition id rides along here so the second column is exercised by
    something other than the empty string.
    """

    from jobtracker.cloud import pipeline
    from jobtracker.cloud.applications import _persist_review_items_additive
    from jobtracker.database import get_session

    review = pipeline.collect_review_items(
        [_scanned("additive-1", thread_id="t-additive", req_id="REQ-4471002")]
    )
    async with get_session() as session:
        surfaced = await _persist_review_items_additive(session, USER, review)
        await session.commit()
    assert surfaced == 1

    row = await _stored("additive-1")
    assert row is not None
    assert row.identity_role == ROLE
    assert row.identity_req_id == "REQ-4471002"


async def test_an_older_queue_row_is_healed_by_the_next_scan(cloud_db: None) -> None:
    """No backfill. The ratchet repairs what shipped, on the next sync.

    The "before" row here is written by the SHIPPED persist function called the
    way the old code called it — a ``MessageRef`` built without the two kwargs —
    so this is the real pre-fix row and not a hand-made imitation of one. The
    second pass is the fixed path, and the assertion is on what the row HOLDS
    afterwards.
    """

    from jobtracker.cloud import pipeline
    from jobtracker.cloud.applications import (
        _persist_message_refs,
        _persist_review_items,
    )
    from jobtracker.database import get_session

    review = pipeline.collect_review_items([_scanned("heal-1")])
    item = review[0]

    # Exactly the construction this commit changed, minus the change.
    old_ref = pipeline.MessageRef(
        message_id=item.message_id,
        thread_id=item.thread_id,
        subject=item.subject,
        sender_email=item.sender_email,
        sender_name=item.sender_name,
        received_at=item.received_at,
        category="needs_review",
        confidence=item.confidence,
        snippet=item.snippet,
        suggested_category=item.category,
    )
    async with get_session() as session:
        await _persist_message_refs(session, USER, None, [old_ref])
        await session.commit()

    # The pre-fix row is real: it holds the snippet, and the snippet is the
    # text that does not name the job. (Stated as an equality, not as a null.)
    before = await _stored("heal-1")
    assert before.body_snippet == SNIPPET

    async with get_session() as session:
        await _persist_review_items(session, USER, review)
        await session.commit()

    after = await _stored("heal-1")
    assert after.identity_role == ROLE


async def test_derived_and_names_nothing_stores_an_empty_string(
    cloud_db: None,
) -> None:
    """``""`` is a value, and it is the one a real scan writes most often.

    A server pass that reads the whole body and finds no title records ``""``
    (``_classify_messages`` ends both derivations with ``or ""``). That must
    reach storage as the empty string: NULL would send every reader back to
    re-deriving from the snippet forever, which is the collapse
    ``test_identity_survives_the_snippet`` pins one layer up.

    Paired with the row above deliberately — the two are written by the same
    code path in the same session and hold DIFFERENT values, so this cannot
    pass by the column simply being untouched.
    """

    from jobtracker.cloud import pipeline
    from jobtracker.cloud.applications import _persist_review_items
    from jobtracker.database import get_session

    review = pipeline.collect_review_items(
        [
            _scanned("names-2", day=3),
            _scanned("silent-2", body=SILENT_BODY, thread_id="t-silent", day=4),
        ]
    )
    async with get_session() as session:
        await _persist_review_items(session, USER, review)
        await session.commit()

    assert (await _stored("names-2")).identity_role == ROLE
    assert (await _stored("silent-2")).identity_role == ""


async def test_the_queue_shows_the_title_it_stored(cloud_db: None) -> None:
    """The payoff, at the surface a person actually reads.

    ``GET /applications/review`` has rendered ``e.identity_role or
    role_from_message(subject, snippet[:200])`` since #484 shipped, and for a
    queue row the first operand was always NULL — so the reader that exists
    precisely to show a body-named title has never once shown one. This is the
    assertion that the fallback is no longer the only live branch.
    """

    from jobtracker.cloud import applications as apps
    from jobtracker.cloud import pipeline
    from jobtracker.database import get_session

    review = pipeline.collect_review_items([_scanned("surface-1")])
    async with get_session() as session:
        await apps._persist_review_items(session, USER, review)
        await session.commit()

    queue = await apps.review_queue_cloud(user_id=USER, limit=100)
    entry = next(i for i in queue.items if i.message_id == "surface-1")
    assert entry.role == ROLE
    # The snippet the row also carries is the text that does NOT name it, so the
    # role above can only have come from the stored column.
    assert entry.snippet == SNIPPET
    assert pipeline.role_from_message(SUBJECT, SNIPPET) is None
