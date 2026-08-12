"""Re-applying to a role you were rejected for.

The board's identity is ``(employer, req_id or role_token)`` and the resolver
matches that identity against EVERY row at the employer — dismissed and terminal
ones included. So a second application to a role that was already rejected does
not mint a second row: it resolves to the rejected one. Before this change
``advance_application_status`` then early-returned ``rejected``, the fresh
confirmation was filed onto the settled row, and the application the user had
just made existed nowhere on the board.

The fix is REOPEN-IN-PLACE: one row per identity, whose status reflects the
LATEST journey segment. A rejection ends a segment; anything strictly newer than
the newest dated rejection starts the next one. Everything else — the identity,
the filing date, the deadline, the linked mail — is unchanged, and that is the
property :func:`test_a_cluster_with_no_post_rejection_application_is_byte_identical`
pins down: for every cluster the corpus already contains, the new rollup returns
exactly what the old one did.

What this deliberately gives up is a second CARD. Two applications to one
requisition are one row whose ``applied_date`` keeps the FIRST filing. Splitting
them is not available at this layer: ``partition_applications`` keys clusters
with no temporal dimension, so a full rebuild merges both applications' mail into
one cluster and no per-cluster mint-vs-match rule can be correct against it.
"""

from __future__ import annotations

import datetime
import itertools
import logging
import uuid as _uuid

import pytest
from sqlmodel import select

from jobtracker.cloud import applications as apps
from jobtracker.cloud import pipeline as p
from jobtracker.database.models import (
    Application,
    ApplicationStatus,
    Email,
    EmailCategory,
)

USER = _uuid.UUID("3f8a2c11-6d44-4a90-9c1e-0b2d5e7f4a63")

BASE = datetime.datetime(2026, 8, 11, 2, 0)
ACME = "careers@acme.com"

# One employer, one role, worded the way a real ATS words it. The confirmation
# names the role (so it keys the cluster); the rejection names none, which is the
# common shape — at an employer with a single application it joins that one.
CONF_SUBJECT = "Thanks for applying to the Data Scientist role at Acme"
CONF_SNIPPET = "Hi Ayush, we have received your application and will review it shortly."
REJ_SUBJECT = "Update on your application"
REJ_SNIPPET = "Hi Ayush, we have decided not to move forward at this time."
INTERVIEW_SUBJECT = "Interview for the Data Scientist role at Acme"
INTERVIEW_SNIPPET = "Hi Ayush, we would like to schedule an interview with you."


def at(minutes: int) -> datetime.datetime:
    return BASE + datetime.timedelta(minutes=minutes)


_UNSET = object()


def item(
    message_id: str,
    *,
    category: str = "applied",
    minutes: int = 0,
    received_at=_UNSET,
    subject: str = CONF_SUBJECT,
    snippet: str = CONF_SNIPPET,
    sender: str = ACME,
    name: str | None = "Acme",
    confidence: float = 0.95,
) -> p.PipelineItem:
    return p.PipelineItem(
        message_id=message_id,
        thread_id=f"th-{message_id}",
        subject=subject,
        sender_email=sender,
        sender_name=name,
        received_at=at(minutes) if received_at is _UNSET else received_at,
        category=category,
        confidence=confidence,
        snippet=snippet,
    )


def confirmation(message_id: str, minutes: int) -> p.PipelineItem:
    return item(message_id, category="applied", minutes=minutes)


def rejection(message_id: str, minutes: int | None, **kw) -> p.PipelineItem:
    return item(
        message_id,
        category="rejection",
        subject=REJ_SUBJECT,
        snippet=REJ_SNIPPET,
        **({"received_at": None} if minutes is None else {"minutes": minutes}),
        **kw,
    )


def interview(message_id: str, minutes: int) -> p.PipelineItem:
    return item(
        message_id,
        category="interview",
        minutes=minutes,
        subject=INTERVIEW_SUBJECT,
        snippet=INTERVIEW_SNIPPET,
    )


CONF = confirmation("k1", 0)
REJ = rejection("k2", 100)
CONF2 = confirmation("k3", 200)
CORPUS = [CONF, REJ, CONF2]


# --- 1. the defect ------------------------------------------------------------


def test_re_applying_after_a_rejection_reopens_the_row():
    """The application the user actually made has to exist somewhere.

    Three messages, one identity: a confirmation, the rejection that settled it,
    and the confirmation of a SECOND application to the same role. Rolling the
    third up as ``rejected`` is what made it invisible — the upsert resolved it
    onto the settled row and ``advance_application_status`` refused to move.
    """

    assert p.roll_up_applications([CONF])[0].status == "applied"
    assert p.roll_up_applications([CONF, REJ])[0].status == "rejected"

    rolled = p.roll_up_applications(CORPUS)

    assert len(rolled) == 1
    assert rolled[0].status == "applied"
    # And it carries the evidence, because the persistent half has to be able to
    # tell a genuine reopen from a rejection the scan's window simply missed.
    assert rolled[0].latest_rejection_at == at(100)
    assert rolled[0].latest_applied_signal_at == at(200)
    # One row, one identity, all three messages — never a second card.
    assert {m.message_id for m in rolled[0].messages} == {"k1", "k2", "k3"}
    # The filing date is the FIRST application's. This is the give-up: the board
    # shows one card, dated when the user first applied.
    assert rolled[0].applied_at == at(0)


def test_the_reopened_segment_rolls_up_its_own_furthest_stage():
    """A reopened row is not pinned at ``applied`` — it resumes a real journey."""

    rolled = p.roll_up_applications(CORPUS + [interview("k4", 300)])

    assert len(rolled) == 1
    assert rolled[0].status == "interviewing"


def test_only_a_rejection_starts_a_new_segment():
    """The guard against the naive chronological walk.

    Reading the LAST message as the status would downgrade an interviewing row
    the moment a duplicate confirmation arrived after it. Segments are cut by
    rejections and by nothing else, so with no rejection the rollup is still the
    order-blind furthest stage.
    """

    late_duplicate = [CONF, interview("k5", 100), confirmation("k6", 200)]

    assert p.roll_up_applications(late_duplicate)[0].status == "interviewing"


# --- 2. compatibility ---------------------------------------------------------
#
# The whole live corpus falls in here: on 2026-08-11 all 42 of the owner's rows
# were APPLIED and none was terminal. So the claim that makes this safe to ship
# is not "the reopen case is right", it is "every OTHER case is untouched" — and
# the honest way to assert that is against the old algorithm itself, copied
# verbatim below rather than described.


def _legacy_roll_up(items) -> list[tuple]:
    """``roll_up_applications`` exactly as it stood before reopen-in-place."""

    clusters, _unplaced = p.partition_applications(items)

    rolled: list[tuple] = []
    for cluster in clusters:
        token, display, msgs = cluster.company_token, cluster.company_display, cluster.items
        categories = {m.category for m in msgs}
        has_rejection = "rejection" in categories
        max_rank = max((p._STAGE_RANK.get(c, 0) for c in categories), default=1)
        status = "rejected" if has_rejection else p._rank_to_status(max_rank)

        dated = [p.to_naive_utc(m.received_at) for m in msgs if m.received_at is not None]
        applied_dates = [
            p.to_naive_utc(m.received_at)
            for m in msgs
            if m.category in ("applied", "pending_application") and m.received_at
        ]
        applied_at = min(applied_dates) if applied_dates else (min(dated) if dated else None)
        last_activity = max(dated) if dated else None

        role = cluster.role

        stated = [
            (p.to_naive_utc(m.received_at), p.extract_deadline(m.subject, m.snippet, m.received_at))
            for m in msgs
        ]
        dated = [(seen, due) for seen, due in stated if due is not None and seen is not None]
        due_at = max(dated, key=lambda pair: pair[0])[1] if dated else None

        refs = tuple(
            sorted(
                (p._message_ref(m) for m in msgs),
                key=lambda r: p._as_utc(r.received_at) if r.received_at else p._EPOCH,
                reverse=True,
            )
        )

        rolled.append(
            (
                token,
                display,
                role,
                status,
                applied_at,
                last_activity,
                refs,
                cluster.req_id,
                cluster.role_token,
                due_at,
            )
        )

    return sorted(rolled, key=lambda r: (r[0], r[7] or "", r[8] or ""))


def _ten_fields(r: p.RolledApplication) -> tuple:
    """The fields that existed before this change, in the legacy tuple's order."""

    return (
        r.company_token,
        r.company_display,
        r.role,
        r.status,
        r.applied_at,
        r.last_activity,
        r.messages,
        r.req_id,
        r.role_token,
        r.due_at,
    )


UNCHANGED_CORPORA = {
    "nothing at all": [],
    "one confirmation": [CONF],
    "confirmation then rejection": [CONF, REJ],
    # An interview is not an application. The segment after a rejection only
    # opens on an applied/pending_application signal, so this stays settled.
    "interview after the rejection": [CONF, REJ, interview("k7", 300)],
    # THE conservative case. An undated rejection cannot be ordered against
    # anything, so the rollup falls back to the old rule wholesale.
    "undated rejection with a later confirmation": [CONF, rejection("k8", None), CONF2],
    # Equal timestamps stay rejected: a false stay is one visible bug a human can
    # fix, a false reopen compounds on every rebuild.
    "rejection and confirmation at the same instant": [CONF, REJ, confirmation("k9", 100)],
    # Several applications at one employer, one of them settled — the shape the
    # per-application identity work exists for.
    "two roles, one rejected": [
        CONF,
        REJ,
        item(
            "k10",
            subject="Thanks for applying to the Platform Engineer role at Acme",
            snippet="Hi Ayush, we have received your application.",
            minutes=50,
        ),
    ],
    "a rejection at a different employer": [
        CONF,
        item(
            "k11",
            category="rejection",
            subject=REJ_SUBJECT,
            snippet=REJ_SNIPPET,
            sender="careers@initech.com",
            name="Initech",
            minutes=100,
        ),
    ],
}


@pytest.mark.parametrize("corpus", list(UNCHANGED_CORPORA.values()), ids=list(UNCHANGED_CORPORA))
def test_a_cluster_with_no_post_rejection_application_is_byte_identical(corpus):
    """No post-rejection applied signal → the old rollup, field for field."""

    assert [_ten_fields(r) for r in p.roll_up_applications(corpus)] == _legacy_roll_up(corpus)


def test_the_compatibility_comparison_is_live():
    """Positive control: the two implementations DO disagree where they should.

    Without this the parametrized test above would keep passing if
    ``_legacy_roll_up`` silently became a copy of the new behaviour.
    """

    assert [_ten_fields(r) for r in p.roll_up_applications(CORPUS)] != _legacy_roll_up(CORPUS)


# --- 3. determinism -----------------------------------------------------------


def test_the_rollup_does_not_depend_on_the_order_mail_arrives_in():
    """A rebuild reads the mailbox in whatever order Gmail returns it.

    Nothing here is decided by position: the segment is a set filter on "strictly
    newer than the newest dated rejection", and the status over it is an
    order-blind maximum. So every permutation is the same row.
    """

    expected = [_ten_fields(r) for r in p.roll_up_applications(CORPUS)]

    for permutation in itertools.permutations(CORPUS):
        assert [_ten_fields(r) for r in p.roll_up_applications(list(permutation))] == expected


def test_a_confirmation_at_the_rejections_own_instant_stays_rejected():
    """Ties resolve toward stay-rejected, in every order."""

    tied = [CONF, REJ, confirmation("k12", 100)]

    for permutation in itertools.permutations(tied):
        rolled = p.roll_up_applications(list(permutation))
        assert len(rolled) == 1
        assert rolled[0].status == "rejected"
        assert rolled[0].latest_rejection_at == rolled[0].latest_applied_signal_at == at(100)


# --- the persistent half ------------------------------------------------------


def _rolled(items):
    return p.roll_up_applications(list(items))


async def _live_rows(session) -> list[Application]:
    rows = await apps._company_rows(session, USER, "acme")
    return [r for r in rows if r.dismissed_at is None]


async def _all_rows(session) -> list[Application]:
    return list(
        (await session.exec(select(Application).where(Application.user_id == USER))).all()
    )


async def _linked(session, application_id: int) -> set[str]:
    rows = (
        await session.exec(
            select(Email).where(
                Email.user_id == USER, Email.application_id == application_id
            )
        )
    ).all()
    return {e.message_id for e in rows}


# --- 4. the narrow incremental window -----------------------------------------


async def test_an_incremental_scan_that_never_saw_the_rejection_still_reopens(
    test_session, caplog
):
    """The delta sync's window is small and the rejection is often outside it.

    The second scan carries ONE message — the new confirmation — so the cluster
    knows of no rejection at all. The evidence then has to come off the row: its
    own linked rejection mail is older than the applied signal, which is the same
    fact stated from the other side.
    """

    await apps.sync_gmail_pipeline_additive(test_session, USER, _rolled([CONF, REJ]), [])
    seeded = await _live_rows(test_session)
    assert [r.status for r in seeded] == [ApplicationStatus.REJECTED]
    row_id = seeded[0].id

    with caplog.at_level(logging.INFO, logger="jobtracker.cloud.applications"):
        await apps.sync_gmail_pipeline_additive(test_session, USER, _rolled([CONF2]), [])

    rows = await _live_rows(test_session)
    assert len(rows) == 1
    assert rows[0].id == row_id  # reopened in place, not minted beside
    assert rows[0].status == ApplicationStatus.APPLIED
    assert await _linked(test_session, row_id) == {"k1", "k2", "k3"}

    # The log line is the entire monitoring story for this transition, so it has
    # to name the row and both instants that licensed it.
    reopened = [rec for rec in caplog.records if "Reopened" in rec.getMessage()]
    assert len(reopened) == 1
    message = reopened[0].getMessage()
    assert str(row_id) in message and "Acme" in message
    assert str(at(100)) in message and str(at(200)) in message


# --- 5. the PR #90 guard ------------------------------------------------------


async def test_two_full_rebuilds_of_the_whole_corpus_leave_one_row(test_session):
    """The failure mode a mint-then-dismiss fix would have re-created.

    ``partition_applications`` has no temporal dimension, so a rebuild merges
    both applications' mail into ONE cluster. A fix that minted a second row for
    the newer application would have it re-pointed away by
    ``_persist_message_refs`` and then dismissed by
    ``_dismiss_rows_left_without_mail`` as an auto row with no mail — every
    rebuild, forever. Reopening in place has nothing to churn.
    """

    coverage = apps.ScanCoverage.from_items(CORPUS)

    first = await apps.purge_and_rebuild_gmail_pipeline(
        test_session, USER, _rolled(CORPUS), p.collect_review_items(CORPUS), coverage
    )
    assert (first.created, first.purged, first.removed) == (1, 0, ())
    rows = await _live_rows(test_session)
    assert len(rows) == 1
    assert rows[0].status == ApplicationStatus.APPLIED
    row_id = rows[0].id

    second = await apps.purge_and_rebuild_gmail_pipeline(
        test_session, USER, _rolled(CORPUS), p.collect_review_items(CORPUS), coverage
    )
    assert (second.created, second.purged, second.removed) == (0, 0, ())
    rows = await _live_rows(test_session)
    assert [r.id for r in rows] == [row_id]
    assert rows[0].status == ApplicationStatus.APPLIED
    assert rows[0].dismissed_at is None
    # Nothing was minted and quietly hidden, either.
    assert len(await _all_rows(test_session)) == 1


async def test_a_rebuild_reopens_a_row_the_scan_itself_sees_re_applied(
    test_session, caplog
):
    """The OTHER half of the evidence — the one a full rebuild uses.

    A rebuild re-reads the whole history, so the rejection and the second
    application arrive in the same cluster and the comparison never touches the
    database. The two branches are deliberately exclusive: when the cluster
    names a rejection, the row's own stored mail is not consulted at all, or a
    scan that has just watched an application END could be overruled by an older
    rejection still linked to the row. Without this test that rule is
    unobserved — the suite stays green with the whole branch stubbed out.
    """

    await apps.sync_gmail_pipeline_additive(test_session, USER, _rolled([CONF, REJ]), [])
    seeded = await _live_rows(test_session)
    assert [r.status for r in seeded] == [ApplicationStatus.REJECTED]
    row_id = seeded[0].id

    coverage = apps.ScanCoverage.from_items(CORPUS)
    with caplog.at_level(logging.INFO, logger="jobtracker.cloud.applications"):
        result = await apps.purge_and_rebuild_gmail_pipeline(
            test_session, USER, _rolled(CORPUS), p.collect_review_items(CORPUS), coverage
        )

    assert (result.created, result.purged, result.removed) == (0, 0, ())
    rows = await _live_rows(test_session)
    assert [r.id for r in rows] == [row_id]
    assert rows[0].status == ApplicationStatus.APPLIED
    assert await _linked(test_session, row_id) == {"k1", "k2", "k3"}
    # Both instants are the CLUSTER's, which is what says the cluster-side
    # branch ran rather than the row-side fallback.
    assert any(
        str(at(100)) in rec.getMessage() and str(at(200)) in rec.getMessage()
        for rec in caplog.records
        if "Reopened" in rec.getMessage()
    )


# --- 6. replay without a re-application ---------------------------------------


async def test_replaying_a_settled_application_leaves_it_settled(test_session):
    """The same rebuild, minus the second confirmation, must not drift."""

    settled = [CONF, REJ]
    coverage = apps.ScanCoverage.from_items(settled)

    for _ in range(2):
        await apps.purge_and_rebuild_gmail_pipeline(
            test_session, USER, _rolled(settled), p.collect_review_items(settled), coverage
        )
        rows = await _live_rows(test_session)
        assert len(rows) == 1
        assert rows[0].status == ApplicationStatus.REJECTED


# --- 7. the boundary of the sync's authority ----------------------------------


async def test_a_rejection_the_user_settled_is_never_reopened(test_session):
    """Reopen is scoped to AUTO rows, exactly like every other status write.

    ``record_status_correction`` flips ``source`` to ``gmail_user``, which puts
    the row outside the sync's status authority entirely. There is no rejection
    EMAIL here at all — the human is the whole signal — so the row-side evidence
    query has nothing to find, and must not be asked in the first place.
    """

    await apps.sync_gmail_pipeline_additive(test_session, USER, _rolled([CONF]), [])
    row_id = (await _live_rows(test_session))[0].id
    await apps.record_status_correction(
        test_session, USER, row_id, ApplicationStatus.REJECTED
    )

    await apps.sync_gmail_pipeline_additive(test_session, USER, _rolled([CONF2]), [])

    rows = await _live_rows(test_session)
    assert len(rows) == 1
    assert rows[0].id == row_id
    assert rows[0].status == ApplicationStatus.REJECTED
    assert rows[0].source == apps.SOURCE_GMAIL_USER
    # The new confirmation is still filed against the row — the sync keeps the
    # evidence even where it may not touch the verdict.
    assert await _linked(test_session, row_id) == {"k1", "k3"}


# --- 8. both messages in one delivery -----------------------------------------


async def test_a_rejection_and_the_next_application_in_one_scan(test_session):
    """One scan can carry the whole segment boundary.

    The cluster settles and reopens inside a single delivery. Rolling it up as
    ``rejected`` would settle a live application on the strength of a message
    that has already been superseded.
    """

    await apps.sync_gmail_pipeline_additive(test_session, USER, _rolled([CONF]), [])
    row_id = (await _live_rows(test_session))[0].id

    await apps.sync_gmail_pipeline_additive(test_session, USER, _rolled([REJ, CONF2]), [])

    rows = await _live_rows(test_session)
    assert len(rows) == 1
    assert rows[0].id == row_id
    assert rows[0].status == ApplicationStatus.APPLIED
    assert await _linked(test_session, row_id) == {"k1", "k2", "k3"}
    stored = (
        await test_session.exec(
            select(Email).where(Email.user_id == USER, Email.message_id == "k2")
        )
    ).first()
    assert stored is not None and stored.classified_as == EmailCategory.REJECTION
