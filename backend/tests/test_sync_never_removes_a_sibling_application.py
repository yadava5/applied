"""An ordinary sync must not remove one of an employer's other applications.

The production incident (2026-08-12). The owner's board went from 49 rows to 27
over two days without a single click: 22 rows carried ``dismissed_reason =
'resync'`` and not one carried ``'user'``. Three of them share a write timestamp
to the microsecond, and — the tell — every one of them belongs to an employer
that is STILL on the board: Amazon kept three live applications while two
siblings were removed, Crusoe kept two, Verkada three.

That shape cannot come from the rebuild's contradiction test. ``purge_and_rebuild_gmail_pipeline``
skips any row whose employer appears in the fresh rollup before it ever consults
``_scan_contradicts``, so a live sibling protects the whole employer. It comes
from the other place that writes ``'resync'``: ``_dismiss_rows_left_without_mail``,
which runs inside the upsert and therefore on the ADDITIVE path too — the path
whose entire promise is that it removes nothing.

The chain is:

1. an employer holds two applications, told apart by role token (the identity
   model since 2026-08-11: employer + req_id-or-role);
2. a later scan re-reads one message WITHOUT the text that names its role — a
   metadata-only pass carries no snippet, and ``_persist_message_refs`` already
   documents that "a ref that carries no snippet means this pass did not fetch
   one". The cluster is now anonymous;
3. ``_pick_application`` rule 4 resolves an anonymous cluster to ``rows[0]`` —
   the employer's OLDEST live row. That is a tie-break, not evidence;
4. the message is re-pointed onto that sibling, its own row is left with no
   mail, and the emptied row is dismissed as ``'resync'``.

Nothing in that chain observed anything about the removed application. The scan
merely failed to re-derive an identity it had derived before, which is exactly
"the scan did not reach this mail" — and it must never read as "this application
is disproven".
"""

from __future__ import annotations

import datetime
import uuid as _uuid

from sqlmodel import select

from jobtracker.cloud import applications as apps
from jobtracker.cloud import pipeline as p
from jobtracker.database.models import Application, Email

USER = _uuid.UUID("6b1f0c2e-59a3-4d18-8f7c-2a4e91b6d055")

BASE = datetime.datetime(2026, 8, 10, 9, 0)

# Two real Amazon requisitions from the owner's board. The subject is the same
# ATS template for both — which is the whole reason identity has to come from
# the body — so the role, and therefore the row, lives in the snippet.
ATS_SUBJECT = "Thank you for applying to Amazon"
SDE_2026 = (
    "Thank you for applying to the Software Development Engineer - 2026 (US) "
    "position at Amazon."
)
SDE_DATABASE = (
    "Thank you for applying to the Software Development Engineer, Database - "
    "2026 (US) position at Amazon."
)


def at(minutes: int) -> datetime.datetime:
    return BASE + datetime.timedelta(minutes=minutes)


def item(
    message_id: str,
    *,
    snippet: str,
    subject: str = ATS_SUBJECT,
    sender: str = "no-reply@amazon.com",
    name: str | None = "Amazon",
    category: str = "applied",
    minutes: int = 0,
    confidence: float = 0.95,
) -> p.PipelineItem:
    return p.PipelineItem(
        message_id=message_id,
        thread_id=f"th-{message_id}",
        subject=subject,
        sender_email=sender,
        sender_name=name,
        received_at=at(minutes),
        category=category,
        confidence=confidence,
        snippet=snippet,
    )


async def _sync(session, items: list[p.PipelineItem]) -> apps.MergeResult:
    """One ordinary (additive) sync of exactly these messages.

    The same two calls ``POST /gmail/sync`` makes before it merges, so the test
    exercises the real rollup rather than a hand-built one.
    """

    return await apps.sync_gmail_pipeline_additive(
        session, USER, p.roll_up_applications(items), p.collect_review_items(items)
    )


async def _rows(session, *, dismissed: bool) -> list[Application]:
    rows = (
        await session.exec(
            select(Application)
            .where(Application.user_id == USER)
            .order_by(Application.id)
        )
    ).all()
    return [r for r in rows if (r.dismissed_at is not None) == dismissed]


async def _linked(session, application_id: int) -> set[str]:
    return set(
        (
            await session.exec(
                select(Email.message_id).where(
                    Email.user_id == USER, Email.application_id == application_id
                )
            )
        ).all()
    )


async def test_a_metadata_only_re_read_does_not_remove_the_sibling_application(
    test_session,
):
    """THE REPRODUCTION: a scan that cannot re-derive a role removed the row.

    Both Amazon applications are real and both are on the board. The third sync
    is the ordinary case this fell over on — the same message, re-read by a pass
    that carried no snippet, so nothing in it names a role any more. Before the
    fix the anonymous cluster adopted the OLDEST Amazon row, took the newer
    row's only email with it, and the newer row was dismissed as ``'resync'``.
    """

    await _sync(test_session, [item("m-sde", snippet=SDE_2026, minutes=0)])
    await _sync(test_session, [item("m-db", snippet=SDE_DATABASE, minutes=30)])

    live = await _rows(test_session, dismissed=False)
    assert [r.company for r in live] == ["Amazon", "Amazon"]
    older, newer = live
    assert await _linked(test_session, newer.id) == {"m-db"}

    # A later pass re-reads the same message with metadata only.
    result = await _sync(test_session, [item("m-db", snippet="", minutes=30)])

    live_after = await _rows(test_session, dismissed=False)
    assert [r.id for r in live_after] == [older.id, newer.id], (
        "an application was taken off the board because one scan could not "
        "re-derive its role — the employer is still on the board, so nothing "
        "was disproven"
    )
    assert await _rows(test_session, dismissed=True) == []
    # And the message is still filed against its own application, not adopted
    # by the sibling that merely happens to be older.
    assert await _linked(test_session, newer.id) == {"m-db"}
    assert await _linked(test_session, older.id) == {"m-sde"}
    assert result.purged == 0 and result.removed == ()


async def test_a_row_emptied_into_a_sibling_at_the_same_employer_stays(test_session):
    """The second half: an emptied row is not evidence when the mail stayed home.

    Here the re-attribution is not blocked — the scan DOES name a role, it just
    tokenizes to something the stored row was not minted under (any change to
    role extraction does this to every row filed before it). The cluster matches
    no existing row, mints a new one, and takes the old row's mail with it.

    Company-token reasoning cannot tell that apart from "this application is
    gone", because the employer is present either way. When the mail merely
    moved to a sibling at the SAME employer the application is still there — so
    the row stays, and the ambiguity resolves toward keeping data.
    """

    await _sync(test_session, [item("m-db", snippet=SDE_DATABASE, minutes=0)])
    [row] = await _rows(test_session, dismissed=False)

    # The row as an older tokenizer would have left it: same message, a token
    # today's extraction no longer produces.
    row.role_token = "sde database"
    test_session.add(row)
    await test_session.commit()

    result = await _sync(test_session, [item("m-db", snippet=SDE_DATABASE, minutes=0)])

    assert await _rows(test_session, dismissed=True) == [], (
        "a re-tokenized role moved the mail to a fresh row and the original was "
        "removed — the application never went anywhere"
    )
    assert result.purged == 0 and result.removed == ()


async def test_a_row_emptied_by_a_move_to_another_employer_is_removed_and_named(
    test_session,
):
    """The removal that IS legitimate — and it has to be reported.

    A message re-attributed to a DIFFERENT employer means the row it left was a
    misattribution of another company's mail: nothing about that employer
    remains, so leaving an empty row on the board is the worse state (it is
    counted, and no scan can ever contradict a row with no mail to re-read).
    That one is still dismissed — but the sync now NAMES it, because the board
    changed under the user and the receipt is where the one-click undo lives.
    """

    filed = item(
        "m-moves",
        subject="We received your application to Cedartech",
        snippet="Thank you for applying to the Platform Engineer position.",
        sender="careers@cedartech.com",
        name="Cedartech",
    )
    await _sync(test_session, [filed])
    [row] = await _rows(test_session, dismissed=False)
    assert row.company == "Cedartech"

    moved = item(
        "m-moves",
        subject="We received your application to Aven",
        snippet="Thank you for applying to the Platform Engineer position.",
        sender="careers@aven.com",
        name="Aven",
    )
    result = await _sync(test_session, [moved])

    assert [r.company for r in await _rows(test_session, dismissed=False)] == ["Aven"]
    dismissed = await _rows(test_session, dismissed=True)
    assert [r.company for r in dismissed] == ["Cedartech"]
    assert dismissed[0].dismissed_reason == apps.DISMISSED_BY_RESYNC

    assert result.purged == 1
    assert [(r.id, r.company) for r in result.removed] == [(row.id, "Cedartech")], (
        "a sync that took a row off the board said nothing about it — the user "
        "cannot undo a removal they were never told about"
    )
