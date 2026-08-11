"""One policy for who may write ``Application.status``, enforced at every write.

The policy the product actually intends is a single sentence:

    Mail may only push an IN-FLIGHT row forward; a terminal status is settled;
    a row whose ``source`` is user-owned is not re-advanced by automation.

``pipeline.advance_application_status`` is the choke point for the first two
clauses; ``_is_auto_row`` is the choke point for the third. Only the sync upsert
used both. Three other paths wrote the column their own way, and each of them is
a distinct, user-visible way for a card to get stuck on the wrong stage:

1. ``classify_review_item`` assigned the category's status VERBATIM, so
   answering "this message is an application confirmation" about a row already
   at ``interviewing`` snapped it back to ``applied`` — and, because the same
   line flipped ``source`` to ``gmail_user``, no later sync could ever undo it.
2. ``split_application_cloud`` recomputed each SIBLING's stage from its own mail
   but left the RETAINED row holding the merged row's status — so splitting a
   row that was rejected because of a sibling requisition left the retained row
   terminally rejected with none of its own remaining mail being a rejection.
3. ``reconcile_orphaned_classifications`` advanced any row it landed on, with no
   ``_is_auto_row`` gate, so one stranded settled email could overwrite a
   standing human correction.

The assertions below are about the stage a user would see on the card, not about
which helper produced it.
"""

from __future__ import annotations

import datetime
import uuid
from contextlib import asynccontextmanager

import pytest
from sqlmodel import select

from jobtracker.cloud import applications as apps
from jobtracker.cloud import pipeline as p
from jobtracker.database.models import (
    Application,
    ApplicationStatus,
    Email,
    EmailCategory,
    EmailSource,
)

USER = uuid.UUID("11111111-1111-1111-1111-111111111111")
BASE = datetime.datetime(2026, 8, 11, 2, 0)

AMAZON_SENDER = "noreply@mail.amazon.jobs"
AMAZON_SUBJECT = "Thank you for Applying to Amazon!"

# The two requisitions used throughout. Real ids from the corpus the identity
# work was built against; what matters is only that they are different.
REQ_LIVE = "3177934"
REQ_DEAD = "3130865"
ROLE_LIVE = "Software Development Engineer - 2026 (US)"
ROLE_DEAD = "Software Development Engineer – Database 2026 (US)"


def _snippet(role: str, req: str) -> str:
    return (
        "Amazon.jobs Hi Ayush, Thanks for applying to Amazon! We've received your "
        f"application for the {role} (ID: {req}) position. What happens next?"
    )


def stored(
    *,
    status: ApplicationStatus,
    source: str = apps.SOURCE_GMAIL_AUTO,
    req_id: str | None = None,
    role: str | None = None,
) -> Application:
    return Application(
        user_id=USER,
        company="Amazon",
        position=role or "",
        status=status,
        source=source,
        req_id=req_id,
        role_token=p.normalize_role_token(role) if role else None,
    )


def mail(
    message_id: str,
    *,
    role: str,
    req: str,
    category: EmailCategory,
    minutes: int = 0,
    application_id: int | None = None,
    reviewed: bool = False,
) -> Email:
    return Email(
        user_id=USER,
        application_id=application_id,
        source_account=EmailSource.GMAIL,
        message_id=message_id,
        thread_id=None,
        subject=AMAZON_SUBJECT,
        sender_email=AMAZON_SENDER,
        body_snippet=_snippet(role, req),
        received_at=BASE + datetime.timedelta(minutes=minutes),
        classified_as=category,
        classification_confidence=0.9,
        is_reviewed=reviewed,
        user_corrected=reviewed,
    )


async def _seed(session, *rows) -> None:
    for row in rows:
        session.add(row)
    await session.commit()


async def _reload(session, app_id: int) -> Application:
    row = (
        await session.exec(select(Application).where(Application.id == app_id))
    ).first()
    await session.refresh(row)
    return row


# =============================================================================
# (1) Classifying a MESSAGE is not a statement about the row's STAGE
# =============================================================================


async def test_classifying_a_message_never_snaps_an_advanced_row_backwards(test_session):
    """The question asked is "what is this message?", not "what stage is this?".

    A stray role-less "thank you for applying" answered as ``applied`` against a
    row already at ``interviewing`` used to overwrite the stage verbatim. The
    card jumped backwards, and because the same write flipped ``source`` to
    ``gmail_user`` the sync's advance gate could never repair it — frozen wrong
    forever.
    """

    row = stored(status=ApplicationStatus.INTERVIEWING, req_id=REQ_LIVE, role=ROLE_LIVE)
    await _seed(test_session, row)
    await _seed(
        test_session,
        mail("rv-back", role=ROLE_LIVE, req=REQ_LIVE, category=EmailCategory.NEEDS_REVIEW),
    )

    result = await apps.classify_review_item(
        test_session, USER, "rv-back", EmailCategory.APPLIED
    )

    assert result["application_id"] == row.id, "must land on the existing row"
    after = await _reload(test_session, row.id)
    assert after.status == ApplicationStatus.INTERVIEWING
    # And it is still the sync's to advance, because the user asserted nothing
    # about the stage that the row did not already hold.
    assert after.source == apps.SOURCE_GMAIL_AUTO


async def test_classifying_a_message_never_reopens_a_settled_row(test_session):
    """A terminal status is settled — automation-adjacent writes do not leave it."""

    row = stored(status=ApplicationStatus.REJECTED, req_id=REQ_LIVE, role=ROLE_LIVE)
    await _seed(test_session, row)
    await _seed(
        test_session,
        mail("rv-term", role=ROLE_LIVE, req=REQ_LIVE, category=EmailCategory.NEEDS_REVIEW),
    )

    await apps.classify_review_item(test_session, USER, "rv-term", EmailCategory.APPLIED)

    after = await _reload(test_session, row.id)
    assert after.status == ApplicationStatus.REJECTED


async def test_classifying_a_message_still_advances_and_settles_the_row(test_session):
    """The advance the endpoint exists for still happens — and becomes sticky."""

    row = stored(status=ApplicationStatus.APPLIED, req_id=REQ_LIVE, role=ROLE_LIVE)
    await _seed(test_session, row)
    await _seed(
        test_session,
        mail("rv-fwd", role=ROLE_LIVE, req=REQ_LIVE, category=EmailCategory.NEEDS_REVIEW),
    )

    await apps.classify_review_item(test_session, USER, "rv-fwd", EmailCategory.INTERVIEW)

    after = await _reload(test_session, row.id)
    assert after.status == ApplicationStatus.INTERVIEWING
    # A stage the user did move IS a decision, so the row becomes user-owned.
    assert after.source == apps.SOURCE_GMAIL_USER


# =============================================================================
# (2) A split leaves nobody holding a stage derived from mail that moved out
# =============================================================================


@pytest.fixture
def split_session(test_session, monkeypatch: pytest.MonkeyPatch):
    """Run the split handler against the fixture session, not the app engine."""

    @asynccontextmanager
    async def _session():
        yield test_session

    monkeypatch.setattr(apps, "get_session", _session)

    async def _no_account(_user_id):
        return None

    monkeypatch.setattr(apps, "_connected_account_email", _no_account)
    return test_session


async def test_the_retained_row_stops_holding_a_sibling_s_rejection(split_session):
    """The exact damage the split exists to undo, left behind on the retained row.

    One merged Amazon row: requisition A is alive, requisition B was rejected. A
    merged row's status is "rejected if any linked mail is a rejection", so the
    row reads ``rejected``. The split gives B its own row and recomputes it —
    but the retained row (A) kept the merged ``rejected``, with none of its own
    remaining mail being a rejection. ``rejected`` is terminal, so no later sync
    could move it: a live application, permanently dead on the board.
    """

    row = stored(status=ApplicationStatus.REJECTED)
    await _seed(split_session, row)
    await _seed(
        split_session,
        mail("m1", role=ROLE_LIVE, req=REQ_LIVE, category=EmailCategory.APPLIED,
             minutes=0, application_id=row.id),
        mail("m2", role=ROLE_DEAD, req=REQ_DEAD, category=EmailCategory.APPLIED,
             minutes=5, application_id=row.id),
        mail("m3", role=ROLE_DEAD, req=REQ_DEAD, category=EmailCategory.REJECTION,
             minutes=400, application_id=row.id),
    )

    result = await apps.split_application_cloud(row.id, user_id=USER)

    assert len(result) == 2
    retained, sibling = result[0], result[1]
    assert retained.id == row.id, "the earliest cluster keeps the row id"

    persisted = {r.id: r for r in (await split_session.exec(select(Application))).all()}
    assert persisted[retained.id].req_id == REQ_LIVE
    assert persisted[sibling.id].req_id == REQ_DEAD
    # The rejection went with the requisition it was actually about...
    assert sibling.status == ApplicationStatus.REJECTED
    # ...and the retained row is back to what its OWN mail says.
    assert retained.status == ApplicationStatus.APPLIED


async def test_a_split_never_rewrites_a_stage_the_user_owns(split_session):
    """A human-set stage survives the split, exactly as it survives a sync."""

    row = stored(status=ApplicationStatus.REJECTED, source=apps.SOURCE_GMAIL_USER)
    await _seed(split_session, row)
    await _seed(
        split_session,
        mail("u1", role=ROLE_LIVE, req=REQ_LIVE, category=EmailCategory.APPLIED,
             minutes=0, application_id=row.id),
        mail("u2", role=ROLE_DEAD, req=REQ_DEAD, category=EmailCategory.APPLIED,
             minutes=5, application_id=row.id),
    )

    result = await apps.split_application_cloud(row.id, user_id=USER)

    assert result[0].id == row.id
    assert result[0].status == ApplicationStatus.REJECTED


# =============================================================================
# (3) The orphan catch-up obeys the same stickiness the sync does
# =============================================================================


async def test_an_orphan_never_overrides_a_standing_human_correction(test_session):
    """A stranded rejection must not undo a stage the user set by hand.

    The upsert's contract is that a row the user corrected keeps its status
    untouched forever. The catch-up did not know that, so a single orphaned
    settled email could overwrite the correction — once, silently, and to a
    terminal state nothing could then move.
    """

    row = stored(
        status=ApplicationStatus.INTERVIEWING,
        source=apps.SOURCE_GMAIL_USER,
        req_id=REQ_LIVE,
        role=ROLE_LIVE,
    )
    await _seed(test_session, row)
    await _seed(
        test_session,
        mail(
            "orphan-rej",
            role=ROLE_LIVE,
            req=REQ_LIVE,
            category=EmailCategory.REJECTION,
            minutes=200,
            reviewed=True,
        ),
    )

    created = await apps.reconcile_orphaned_classifications(test_session, USER)
    await test_session.commit()

    assert created == 0, "it belongs to the existing row, not a new one"
    after = await _reload(test_session, row.id)
    assert after.status == ApplicationStatus.INTERVIEWING
    # The mail is still filed against the row — only the STAGE is protected.
    linked = (
        await test_session.exec(select(Email).where(Email.message_id == "orphan-rej"))
    ).first()
    assert linked.application_id == row.id


async def test_an_orphan_still_advances_an_auto_row(test_session):
    """The catch-up keeps working on rows nobody has corrected."""

    row = stored(status=ApplicationStatus.APPLIED, req_id=REQ_LIVE, role=ROLE_LIVE)
    await _seed(test_session, row)
    await _seed(
        test_session,
        mail(
            "orphan-adv",
            role=ROLE_LIVE,
            req=REQ_LIVE,
            category=EmailCategory.INTERVIEW,
            minutes=200,
            reviewed=True,
        ),
    )

    await apps.reconcile_orphaned_classifications(test_session, USER)
    await test_session.commit()

    after = await _reload(test_session, row.id)
    assert after.status == ApplicationStatus.INTERVIEWING


async def test_two_orphans_in_one_pass_still_roll_up_to_one_settled_row(test_session):
    """The documented "two orphans collapse into one application" case.

    The row is minted by the FIRST orphan of the pass and is tagged
    ``gmail_user`` because it came from a human decision. A literal stickiness
    gate would then refuse the second orphan of the same pass — so the user's
    own rejection would never reach the row they just caused to exist. A row
    this pass created is not a *standing* correction, and is exempt.
    """

    await _seed(
        test_session,
        mail(
            "orphan-a",
            role=ROLE_LIVE,
            req=REQ_LIVE,
            category=EmailCategory.APPLIED,
            minutes=0,
            reviewed=True,
        ),
        mail(
            "orphan-b",
            role=ROLE_LIVE,
            req=REQ_LIVE,
            category=EmailCategory.REJECTION,
            minutes=300,
            reviewed=True,
        ),
    )

    created = await apps.reconcile_orphaned_classifications(test_session, USER)
    await test_session.commit()

    assert created == 1, "one employer, one requisition → one row"
    rows = (await test_session.exec(select(Application))).all()
    assert len(rows) == 1
    assert rows[0].status == ApplicationStatus.REJECTED


# =============================================================================
# What ``_status_from_mail`` actually guarantees
# =============================================================================


def test_the_stage_a_cluster_reaches_does_not_depend_on_message_order():
    """Order-independent by construction, not by sorting.

    From a non-terminal start the fold is a commutative max-by-rank and a
    rejection absorbs whatever it meets, so no permutation of the same mail can
    produce a different stage. Worth pinning: the function used to sort
    chronologically, which reads as "latest wins" — a guarantee it never made.
    """

    emails = [
        mail("s1", role=ROLE_LIVE, req=REQ_LIVE, category=EmailCategory.APPLIED, minutes=0),
        mail("s2", role=ROLE_LIVE, req=REQ_LIVE, category=EmailCategory.INTERVIEW, minutes=10),
        mail("s3", role=ROLE_LIVE, req=REQ_LIVE, category=EmailCategory.REJECTION, minutes=20),
        mail("s4", role=ROLE_LIVE, req=REQ_LIVE, category=EmailCategory.OFFER, minutes=30),
    ]

    assert apps._status_from_mail(emails) == "rejected"
    assert apps._status_from_mail(list(reversed(emails))) == "rejected"
    assert apps._status_from_mail([emails[3], emails[0], emails[1]]) == "offered"
    assert apps._status_from_mail([emails[1], emails[0]]) == "interviewing"


def test_follow_up_asserts_no_stage_at_all():
    """``_STAGE_RANK`` has no ``follow_up`` key, and could not use one.

    ``_qualifies_for_hard_row`` drops follow-ups before any rank is consulted,
    so a follow-up can never reach the rollup's ``max`` — the entry that used to
    sit there was unreachable and read as if follow-ups asserted ``applied``.
    """

    assert "follow_up" not in p._STAGE_RANK

    nudge = p.PipelineItem(
        message_id="fu1",
        thread_id=None,
        subject="Keep track of your application",
        sender_email=AMAZON_SENDER,
        sender_name=None,
        received_at=BASE,
        category="follow_up",
        confidence=0.99,
        snippet=_snippet(ROLE_LIVE, REQ_LIVE),
    )

    assert p._qualifies_for_hard_row(nudge) is None
    assert p.roll_up_applications([nudge]) == []
