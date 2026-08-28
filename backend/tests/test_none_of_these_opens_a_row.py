"""THE QUEUE ASKED WHICH APPLICATION, AND ANSWERED ITSELF (#554).

``ReviewQueue.tsx`` shows a "which application is this about?" picker when an
employer holds two or more candidate cards. Its default answer was **"not one of
these"** — ``applicationId`` initialised to ``null`` and that radio was
``checked={applicationId === null}``. A user who read the subject, chose a stage
and clicked classify had answered "none of my applications at this employer"
without ever choosing it.

WHAT THAT COST, on the backend. ``application_id: None`` skipped
``_chosen_application`` and dropped into ``_resolve_application_for_email``. A
rejection names no role in the ~200 characters the snippet carries, so the
cascade reached ``_pick_application``'s rule 4 — the employer's OLDEST live row —
and ``advance_application_status`` moved it to ``rejected``. Terminal is the one
status it will not walk back, and no product surface re-points a filed message,
so the wrong card was rejected permanently and the application that really was
rejected still read "Applied".

WHERE THE NUMBER COMES FROM, because "19 destroyed records" is the sentence this
whole change rests on and it is not re-derived by anything in CI.

``tests/corpus_independent/harness.py``'s ``answer_the_queue`` replays every held
case in the independent corpus — 2,701 of them — through this very function, and
``test_independent_corpus.py`` records what that produces
(``RECORDED_ANSWERS``: 2,701 queued, 2,701 answered, 2,024 filed on an existing
card, 421 landing where several existed). The comparison below was made by
running that same replay twice, changing exactly one thing: whether ground truth
supplies ``application_id``.

    default (as the queue behaved)     19 MERGE, 58 SPLIT, 80 blank titles
    a card supplied every time          0 MERGE,  1 SPLIT, 42 blank titles

It is a one-off probe and deliberately not a gate: the two arms need two database
states and therefore two full replays, roughly +2 minutes on a gate that already
takes ten, to re-derive a number that cannot move until this issue is fixed. What
IS a gate is everything below, plus the recorded counters the corpus already
carries.

WHY "NONE OF THESE" IS ITS OWN FIELD AND NOT AN ABSENT ID. Absent means "nobody
asked" — single-candidate queue rows, the mail reclassify surface, the live scan
— and rule 4 is the right answer to silence: it is a stable tie-break over a
cluster the scan already reasoned about, and making it mint instead would open a
fresh row on every sync at any employer with two rows (the unbounded growth PR
#76 fixed). So the two answers are separated on the wire, and only a caller that
ASKED and was ANSWERED takes the mint branch.

THE ANSWER IS A MINT, NOT A REFUSAL. Leaving the row in the queue re-presents
the identical picker with the identical candidates forever — a question with no
acceptable answer. Filing with no application reproduces the Crusoe incident's
shape: user says "rejection", board shows nothing. A lifecycle message about an
application the board does not hold IS an application the board is missing, and
it is the cheap direction to be wrong in: a spurious row is one dismiss click, a
wrongly-terminal row is permanent.

EVERY ASSERTION HERE IS PAIRED WITH ITS CONTROL. A test that only says "the
oldest row was not touched" passes when the endpoint does nothing at all, and a
test that only drives the flag says nothing about the behaviour it changed. So
each case is run twice — once with the flag and once without — against the same
fixture, and the without-flag half asserts today's behaviour explicitly.

Every fixture is invented. The employer names are public companies; no real
mailbox content appears.
"""

from __future__ import annotations

import datetime
import uuid

from sqlmodel import select

from jobtracker.cloud import applications as apps
from jobtracker.database.models import (
    Application,
    ApplicationStatus,
    Email,
    EmailCategory,
    EmailSource,
)

USER = uuid.UUID("33333333-3333-3333-3333-333333333333")
BASE = datetime.datetime(2026, 8, 11, 2, 0)

SENDER = "noreply@mail.amazon.jobs"
TOKEN = "amazon"

#: The shape that reaches rule 4: an employer this subject names, and no role
#: anywhere in it. This is not contrived — it is why the picker exists.
BLIND_SUBJECT = "Update on your application to Amazon"
BLIND_BODY = "Hi Ayush, we wanted to share an update on your application status."


def _row(
    *,
    req_id: str | None = None,
    position: str = "",
    status: ApplicationStatus = ApplicationStatus.APPLIED,
    source: str = apps.SOURCE_GMAIL_AUTO,
) -> Application:
    return Application(
        user_id=USER,
        company="Amazon",
        position=position,
        status=status,
        source=source,
        req_id=req_id,
    )


def _mail(message_id: str, *, minutes: int = 0) -> Email:
    return Email(
        user_id=USER,
        application_id=None,
        source_account=EmailSource.GMAIL,
        message_id=message_id,
        thread_id=None,
        subject=BLIND_SUBJECT,
        sender_email=SENDER,
        body_snippet=BLIND_BODY,
        received_at=BASE + datetime.timedelta(minutes=minutes),
        classified_as=EmailCategory.NEEDS_REVIEW,
        classification_confidence=0.62,
        is_reviewed=False,
        user_corrected=False,
    )


async def _seed(session, *rows) -> None:
    for row in rows:
        session.add(row)
    await session.commit()


async def _reload(session, app_id: int) -> Application:
    row = (await session.exec(select(Application).where(Application.id == app_id))).first()
    await session.refresh(row)
    return row


async def _amazon_rows(session) -> list[Application]:
    return list(
        (
            await session.exec(
                select(Application)
                .where(Application.user_id == USER)
                .order_by(Application.id)
            )
        ).all()
    )


# ── the premise ──────────────────────────────────────────────────────────────


async def test_the_fixture_really_does_reach_the_blind_tie_break(test_session):
    """Asserted before anything depends on it.

    If this message named a role, the resolver would key on it and never reach
    rule 4 — and every assertion below would pass against a path that was never
    in question. A guard that the fixture cannot reach proves nothing about the
    guard.
    """

    from jobtracker.cloud import pipeline as p

    assert p.role_from_message(BLIND_SUBJECT, BLIND_BODY) is None
    assert p.extract_req_id(BLIND_SUBJECT, BLIND_BODY) is None
    resolved = p.resolve_employer(SENDER, BLIND_SUBJECT)
    assert resolved is not None and resolved[0] == TOKEN


# ── the defect, and its control ──────────────────────────────────────────────


async def test_none_of_these_opens_a_row_instead_of_rejecting_the_oldest(test_session):
    await _seed(
        test_session,
        _row(req_id="3177934"),
        _row(req_id="3130865"),
        _row(req_id="3183020"),
    )
    before = await _amazon_rows(test_session)
    assert len(before) == 3
    oldest = before[0]
    await _seed(test_session, _mail("rv-none"))

    result = await apps.classify_review_item(
        test_session,
        USER,
        "rv-none",
        EmailCategory.REJECTION,
        none_of_these=True,
    )

    after = await _amazon_rows(test_session)
    assert len(after) == 4, "the user said none of these; that is a row the board lacks"
    assert result["application_id"] not in {r.id for r in before}

    # The whole point: not one of the three the user disclaimed was touched.
    for row in before:
        reloaded = await _reload(test_session, row.id)
        assert reloaded.status == ApplicationStatus.APPLIED, (
            f"application {row.id} was moved to {reloaded.status} by a message "
            "the user said was not about it"
        )
    assert (await _reload(test_session, oldest.id)).source == apps.SOURCE_GMAIL_AUTO

    minted = await _reload(test_session, int(result["application_id"]))
    assert minted.status == ApplicationStatus.REJECTED
    assert minted.company == "Amazon"
    # Sticky, because a human said it: the sync must not re-advance or purge it.
    assert minted.source == apps.SOURCE_GMAIL_USER


async def test_without_the_flag_the_same_message_still_lands_on_the_oldest(test_session):
    """THE CONTROL, and the reason the test above means anything.

    Identical fixture, identical call, one argument removed. This asserts the
    behaviour the flag exists to avoid — so if the endpoint ever stops reaching
    rule 4 for any other reason, the test above becomes true by construction and
    this one goes red to say so.

    It also states plainly that rule 4 is NOT being changed: silence still
    resolves exactly as it did.
    """

    await _seed(
        test_session,
        _row(req_id="3177934"),
        _row(req_id="3130865"),
        _row(req_id="3183020"),
    )
    before = await _amazon_rows(test_session)
    oldest = before[0]
    await _seed(test_session, _mail("rv-silent"))

    result = await apps.classify_review_item(
        test_session, USER, "rv-silent", EmailCategory.REJECTION
    )

    assert result["application_id"] == oldest.id, (
        "silence must still tie-break; the fix separates the ANSWER from the "
        "silence rather than changing what silence means"
    )
    assert len(await _amazon_rows(test_session)) == 3, "silence mints nothing"
    assert (await _reload(test_session, oldest.id)).status == ApplicationStatus.REJECTED


async def test_a_picked_row_is_still_the_row_that_moves(test_session):
    """The third answer, and the one the picker exists to carry.

    Also the endpoint-level gate the suite did not have: the existing
    `test_the_users_choice_of_application_is_honoured` calls
    `_chosen_application` directly, so deleting the endpoint's call to it left
    that test green while the picker became decoration.
    """

    await _seed(
        test_session,
        _row(req_id="3177934"),
        _row(req_id="3130865"),
        _row(req_id="3183020"),
    )
    rows = await _amazon_rows(test_session)
    chosen = rows[2]
    await _seed(test_session, _mail("rv-picked"))

    result = await apps.classify_review_item(
        test_session,
        USER,
        "rv-picked",
        EmailCategory.REJECTION,
        application_id=chosen.id,
    )

    assert result["application_id"] == chosen.id
    assert len(await _amazon_rows(test_session)) == 3, "a pick resolves; it does not mint"
    assert (await _reload(test_session, chosen.id)).status == ApplicationStatus.REJECTED
    assert (await _reload(test_session, rows[0].id)).status == ApplicationStatus.APPLIED


async def test_the_flag_outranks_a_stale_id_that_arrives_with_it(test_session):
    """Two answers to one question must not both be obeyed.

    The client builds both fields from one value, so this cannot happen from the
    product — which is exactly why it is asserted here: a future caller that
    builds them separately must not be able to file against a row the same
    request disclaims.
    """

    await _seed(test_session, _row(req_id="3177934"), _row(req_id="3130865"))
    rows = await _amazon_rows(test_session)
    await _seed(test_session, _mail("rv-both"))

    result = await apps.classify_review_item(
        test_session,
        USER,
        "rv-both",
        EmailCategory.REJECTION,
        application_id=rows[0].id,
        none_of_these=True,
    )

    assert result["application_id"] not in {r.id for r in rows}
    assert (await _reload(test_session, rows[0].id)).status == ApplicationStatus.APPLIED


async def test_the_flag_does_not_reach_past_the_employer_gate(test_session):
    """A message whose employer cannot be named still files nothing.

    The mint branch sits INSIDE `if status_value is not None and employer is not
    None`. A flag that jumped that gate would open a company-less row — the
    Crusoe incident with a new cause.
    """

    await _seed(test_session, _row(req_id="3177934"), _row(req_id="3130865"))
    anonymous = _mail("rv-anon")
    anonymous.subject = "Update on your application"
    anonymous.sender_email = "no-reply@notifications.example"
    await _seed(test_session, anonymous)

    result = await apps.classify_review_item(
        test_session,
        USER,
        "rv-anon",
        EmailCategory.REJECTION,
        none_of_these=True,
    )

    assert result["needs_employer"] is True
    assert result["application_id"] is None
    assert len(await _amazon_rows(test_session)) == 2, "nothing was opened"


async def test_a_non_filing_category_opens_nothing_either(test_session):
    """"Not job related" plus "none of these" is not an application."""

    await _seed(test_session, _row(req_id="3177934"), _row(req_id="3130865"))
    await _seed(test_session, _mail("rv-other"))

    result = await apps.classify_review_item(
        test_session, USER, "rv-other", EmailCategory.OTHER, none_of_these=True
    )

    assert result["application_id"] is None
    assert len(await _amazon_rows(test_session)) == 2
