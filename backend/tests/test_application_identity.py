"""One employer, several applications.

Every case here is drawn from the owner's real mailbox on 2026-08-11, where the
board showed three cards for eight genuine applications. The message shapes are
reproduced verbatim (including the HTML entities Gmail snippets arrive carrying)
because the whole design rests on what those templates actually contain, and a
fixture written from memory would prove nothing about them.

The assertions are deliberately about OUTCOMES a user would notice — how many
rows, which role, whose rejection settles what — rather than about the internals
that produce them, so a future refactor of the clustering is free to change
shape without these needing edits.
"""
from __future__ import annotations

import datetime

import pytest

from jobtracker.cloud import pipeline as p

BASE = datetime.datetime(2026, 8, 11, 2, 0)


def item(
    message_id: str,
    subject: str,
    sender: str,
    snippet: str = "",
    *,
    category: str = "applied",
    confidence: float = 0.95,
    thread_id: str | None = None,
    minutes: int = 0,
) -> p.PipelineItem:
    return p.PipelineItem(
        message_id=message_id,
        thread_id=thread_id,
        subject=subject,
        sender_email=sender,
        sender_name=None,
        received_at=BASE + datetime.timedelta(minutes=minutes),
        category=category,
        confidence=confidence,
        snippet=snippet,
    )


AMAZON_SENDER = "noreply@mail.amazon.jobs"
AMAZON_SUBJECT = "Thank you for Applying to Amazon!"


def amazon(message_id: str, role: str, req: str, minutes: int = 0) -> p.PipelineItem:
    """One real Amazon confirmation. All four share a subject AND a thread."""

    return item(
        message_id,
        AMAZON_SUBJECT,
        AMAZON_SENDER,
        f"Amazon.jobs Hi Ayush, Thanks for applying to Amazon! We&#39;ve received "
        f"your application for the {role} (ID: {req}) position. What happens next?",
        thread_id="19fee99ce7d5feb8",
        minutes=minutes,
    )


AMAZON_FOUR = [
    amazon("a1", "Software Development Engineer - 2026 (US)", "3177934", 0),
    amazon("a2", "Software Development Engineer – Embedded Systems 2026 (US)", "3183020", 2),
    amazon("a3", "Software Development Engineer, AWS Data Services - 2026 (US)", "10414316", 3),
    amazon("a4", "Software Development Engineer – Database 2026 (US)", "3130865", 4),
]


# --- the headline defect ------------------------------------------------------


def test_four_amazon_requisitions_are_four_applications():
    """The defect this whole change exists for.

    Four different roles, applied for in one evening, sharing one subject line
    and one Gmail thread. Grouping on the employer — or on the thread — makes
    them one row and hides three real applications.
    """

    rolled = p.roll_up_applications(AMAZON_FOUR)

    assert len(rolled) == 4
    assert {r.req_id for r in rolled} == {"3177934", "3183020", "10414316", "3130865"}
    assert all(r.company_display == "Amazon" for r in rolled)
    # And each names its own role, which is the only thing distinguishing the
    # four cards on the board.
    assert len({r.role for r in rolled}) == 4


def test_the_same_requisition_seen_twice_is_still_one_application():
    """Idempotence: a re-scan must not grow the board."""

    again = [amazon("a1-again", "Software Development Engineer - 2026 (US)", "3177934", 60)]
    rolled = p.roll_up_applications(AMAZON_FOUR + again)

    assert len(rolled) == 4
    by_req = {r.req_id: r for r in rolled}
    assert len(by_req["3177934"].messages) == 2


def test_amazon_follow_up_naming_only_the_requisition_joins_its_own_row():
    """"Keep track of your application" carries the id but not a clean title."""

    follow_up = item(
        "a5",
        "Keep track of your application",
        AMAZON_SENDER,
        "Amazon.jobs Hi Ayush, Thank you for your interest in Software Development "
        "Engineer – Database 2026 (US) (ID: 3130865). If you have completed the application:",
        thread_id="19fedfd7036353f4",  # a DIFFERENT Gmail thread
        minutes=90,
    )
    rolled = p.roll_up_applications(AMAZON_FOUR + [follow_up])

    assert len(rolled) == 4
    joined = next(r for r in rolled if r.req_id == "3130865")
    assert {m.message_id for m in joined.messages} == {"a4", "a5"}


# --- the case that forbids the naive "split on role" fix ----------------------


def test_roblox_verification_mail_does_not_mint_a_second_application():
    """Two messages, two senders, no shared role text, no shared thread — one job.

    A key of ``(employer, role)`` alone splits this into two rows. The rule that
    saves it is that role-less mail joins the employer's only application.
    """

    confirmation = item(
        "r1",
        "Thank you for applying to Roblox!",
        "no-reply@roblox.com",
        "Early Career Talent Hi Ayush, Thank you for applying to Roblox! We received "
        "your application for the [2027] Software Engineer, Early Career role",
    )
    verification = item(
        "r2",
        "[Action Required] Your Roblox Application",
        "assessment@email.roblox.com",
        "Email Verification Hi Ayush, Thank you for submitting your application for a "
        "position at Roblox! Please click here to verify your email address",
        minutes=1,
    )

    rolled = p.roll_up_applications([confirmation, verification])

    assert len(rolled) == 1
    assert {m.message_id for m in rolled[0].messages} == {"r1", "r2"}


def test_two_differently_worded_acknowledgements_are_one_application():
    """Supabase acknowledges twice, two hours apart, naming no role either time.

    THIS TEST HAS BEEN BOTH WAYS AND THE HISTORY IS THE POINT.

    It first asserted ONE row, on the reasoning that one row is the honest floor
    when the mail draws no distinction. The owner overruled that on 2026-08-21
    and it became TWO, because Google sends the same shape at three — three
    confirmations on 11, 13 and 21 August 2026 that folded onto one card dated
    the 11th, so a sync which classified every message correctly showed a board
    that had not moved. That was right about Google.

    It generalised from Google to EVERY anonymous confirmation, and that caught
    Supabase as collateral. The owner reported it on 2026-08-23: "it shows 2 now,
    but the other mail is just the confirmation for the first". Both of his
    instructions are satisfiable at once, because the two cases differ in shape
    even though neither message names an application:

      Supabase   TWO templates, 2h01m apart      -> one submission, acked twice
      Google     ONE template, 2 and 8 days apart -> three submissions

    So the rule is template AND window, not "every confirmation mints"
    (:func:`pipeline.group_double_acknowledgements`). The Google half of this
    decision is asserted directly below and must not be traded away for this one.

    THE ASYMMETRY THE 08-21 DECISION RESTED ON DOES NOT EXIST. It was argued as
    "a merge is invisible and destroys the record; a split is visible and a
    person can fix it". Checked on 2026-08-23: `POST /applications/{id}/split`
    exists and has a UI prompt, and there is **no merge endpoint and no merge
    control anywhere in this repository**. Over-splitting was not the
    recoverable error it was documented as. It also poisons the employer's
    future mail — with two cards, ``known_multi`` sends every later role-less
    Supabase message to the review queue to ask which of two applications it
    belongs to, and there is no right answer.
    """

    first = item(
        "s1",
        "Thanks for applying to Supabase",
        "no-reply@ashbyhq.com",
        "Hi Ayush, Thanks for applying to Supabase. We&#39;re really glad you&#39;re "
        "interested in what we&#39;re building.",
    )
    second = item(
        "s2",
        "Thank you for applying to Supabase!",
        "no-reply@ashbyhq.com",
        "Hey Ayush, Thanks for your interest in a role with Supabase; we confirm your "
        "application has been received.",
        minutes=120,
    )

    rolled = p.roll_up_applications([first, second])

    assert len(rolled) == 1
    assert {m.message_id for m in rolled[0].messages} == {"s1", "s2"}
    # "interest in a" is prose sitting between the anchors, not a job title. If
    # it were accepted it would key an application — which is a different reason
    # to reach ONE row than the one under test (both would key the same bogus
    # token), and would make this pass for the wrong reason.
    assert all(r.role is None and r.role_token is None for r in rolled)


def test_the_same_acknowledgement_twice_is_two_applications():
    """The Google half, and the control that stops the rule above collapsing everything.

    Three "Thanks for applying to Google", byte-identical, no role and no
    requisition in any of them, on 11, 13 and 21 August 2026. Three real
    applications. Under a template-only rule they would still be three; under a
    window-only rule the first two are 2 days apart and would already be safe,
    but this asserts the shape that matters — SAME template means the submission
    event happened again, however close together the mail arrives.
    """

    google = [
        item(
            f"g{k}",
            "Thanks for applying to Google",
            "noreply@google.com",
            "Hi Ayush Yadav, Thanks for applying to Google! There are a ton of great "
            "companies out there, so we appreciate your interest in joining our team.",
            minutes=minutes,
        )
        for k, minutes in enumerate((0, 2 * 24 * 60, 10 * 24 * 60))
    ]

    rolled = p.roll_up_applications(google)

    assert len(rolled) == 3
    assert [{m.message_id for m in r.messages} for r in rolled] == [
        {"g0"},
        {"g1"},
        {"g2"},
    ]


def test_the_same_acknowledgement_twice_within_the_window_is_still_two():
    """The window must not rescue an identical template.

    Two byte-identical acknowledgements twenty minutes apart are two
    submissions, not one submission acked twice — the ATS emitted its template
    once per event. Without this, "close together" alone would merge every
    same-day pair of applications to an employer that names no role, which is
    exactly what the ``repeat-anonymous`` corpus family is built to catch.
    """

    pair = [
        item(
            f"t{k}",
            "Thank you for applying to Torc Robotics!",
            "no-reply@torc.ai",
            "Hi Ayush, Thank you for beginning your application process with Torc "
            "Robotics! We are excited to learn more about your interests.",
            minutes=k * 20,
        )
        for k in range(2)
    ]

    rolled = p.roll_up_applications(pair)

    assert len(rolled) == 2


def test_two_templates_far_apart_are_two_applications():
    """The template must not rescue a wide gap.

    Two differently-worded acknowledgements a month apart are two applications:
    an employer that reworded its template between them would otherwise lose
    one silently, and a silent loss is the failure this whole area exists to
    avoid. Only template-differs AND inside the window merges.
    """

    early = item(
        "w1",
        "Thanks for applying to Northwind Analytics",
        "no-reply@ashbyhq.com",
        "Hi Ayush, Thanks for applying to Northwind Analytics. We review every "
        "application carefully.",
    )
    late = item(
        "w2",
        "Thank you for applying to Northwind Analytics!",
        "no-reply@ashbyhq.com",
        "Hey Ayush, Thanks for your interest in a role with Northwind Analytics; we "
        "confirm your application has been received.",
        minutes=30 * 24 * 60,
    )

    rolled = p.roll_up_applications([early, late])

    assert len(rolled) == 2


def test_an_outstanding_step_is_not_a_second_application():
    """"Complete your application" reports on one; it does not assert a new one.

    ``pending_application`` used to sit in ``APPLIED_SIGNAL_CATEGORIES`` while
    the comment above that set enumerated only the confirmation. So a nudge to
    finish an application counted as an ANCHOR: two anonymous "assertions" at
    one employer, two cards, and the second is a card for an application that
    does not exist.

    This is not the same message as the one #459 was reported for. That one is
    an email verification and now scores 0.80, under the auto-file gate, so it
    is held for a person and cannot mint anything. These wordings clear the gate
    — measured 0.90 for "complete your application", 0.95 for "finish your
    application" and for "your application is incomplete" — so for them the
    anchor set is the only thing standing between the user and a rival card,
    and the corpus does not contain the shape.
    """

    confirmation = item(
        "n1",
        "Thank you for applying to Northwind",
        "no-reply@us.greenhouse-mail.io",
        "Hi Ayush, thank you for applying to Northwind. Our team will review "
        "your application.",
    )
    unfinished = item(
        "n2",
        "Complete your application to Northwind",
        "no-reply@us.greenhouse-mail.io",
        "Hi Ayush, you started an application with Northwind. Please complete "
        "your application to be considered.",
        category="pending_application",
        confidence=0.90,
        minutes=60,
    )

    rolled = p.roll_up_applications([confirmation, unfinished])

    assert len(rolled) == 1, [
        {m.message_id for m in r.messages} for r in rolled
    ]
    assert {m.message_id for m in rolled[0].messages} == {"n1", "n2"}
    # It still counts as an application signal for the STATUS — the card reads
    # `applied`, which is what `EmailCategory.PENDING_APPLICATION` maps to. The
    # change is narrower than "pending mail stops mattering".
    assert rolled[0].status == "applied"


def test_an_outstanding_step_alone_still_gets_its_own_card():
    """The control, and the failure this change must not cause.

    An employer whose only mail is "complete your application" has no other
    cluster to join, so it mints one through the "no other cluster" branch. If
    this ever goes to zero rows, the fix above has stopped mail reaching the
    board instead of stopping it minting a DUPLICATE.
    """

    unfinished = item(
        "u1",
        "Complete your application to Cedar Labs",
        "no-reply@us.greenhouse-mail.io",
        "Hi Ayush, you started an application with Cedar Labs. Please complete "
        "your application to be considered.",
        category="pending_application",
        confidence=0.90,
    )

    rolled = p.roll_up_applications([unfinished])

    assert len(rolled) == 1
    assert {m.message_id for m in rolled[0].messages} == {"u1"}


def test_one_role_less_confirmation_still_keeps_exactly_one_row():
    """The control on the split above, and the rule Roblox depends on.

    A single role-less confirmation is the ordinary case — mail that names no
    role — not evidence of a second application. Only two or more of them at one
    employer make the claim that there are two applications, so this employer
    keeps the one row it has always had and its later mail keeps landing on it.
    Without this pairing the split would be free to fire on every anonymous
    confirmation in the mailbox and nothing here would notice.
    """

    confirmation = item(
        "t1",
        "Thank you for applying to Together AI",
        "no-reply@us.greenhouse-mail.io",
        "Hi Ayush, thank you for applying to Together AI. Our team will review "
        "your application.",
    )
    rejection = item(
        "t2",
        "Important information about your application to Together AI",
        "no-reply@us.greenhouse-mail.io",
        "Thank you again for your interest in Together AI. Unfortunately we are "
        "not moving forward.",
        category="rejection",
        minutes=2880,
    )

    rolled = p.roll_up_applications([confirmation, rejection])

    assert len(rolled) == 1
    assert {m.message_id for m in rolled[0].messages} == {"t1", "t2"}
    assert rolled[0].status == "rejected"


# --- what a rejection may and may not settle ----------------------------------


def test_one_requisitions_rejection_does_not_settle_the_other_three():
    """The reason this is a correctness bug and not a display bug.

    ``advance_application_status`` treats ``rejected`` as terminal, so a merged
    row settled by one rejection silently discards every later interview and
    offer for the other three requisitions.
    """

    rejection = amazon("a6", "Software Development Engineer – Database 2026 (US)", "3130865", 200)
    rejection = p.PipelineItem(**{**rejection.__dict__, "category": "rejection"})

    rolled = p.roll_up_applications(AMAZON_FOUR + [rejection])
    by_req = {r.req_id: r.status for r in rolled}

    assert by_req["3130865"] == "rejected"
    assert by_req["3177934"] == "applied"
    assert by_req["3183020"] == "applied"
    assert by_req["10414316"] == "applied"


def test_a_rejection_naming_no_role_is_asked_about_not_guessed():
    """"Update on your application" names the company and nothing else.

    With four live Amazon applications there is no way to know which one it
    settles, and settling the wrong one freezes a live application permanently.
    So it settles none of them and goes to the review queue for the user.
    """

    rejection = item(
        "a7",
        "Update on your Amazon application",
        AMAZON_SENDER,
        "Hi Ayush, Thank you for your interest in Amazon. After careful consideration "
        "we will not be moving forward at this time.",
        category="rejection",
        minutes=300,
    )
    everything = AMAZON_FOUR + [rejection]

    rolled = p.roll_up_applications(everything)
    assert len(rolled) == 4
    assert {r.status for r in rolled} == {"applied"}
    assert all("a7" not in {m.message_id for m in r.messages} for r in rolled)

    queued = {r.message_id for r in p.collect_review_items(everything)}
    assert "a7" in queued


def test_a_role_less_rejection_at_a_single_application_employer_still_settles_it():
    """The same message must NOT be punted when there is nothing to confuse it with.

    Sending every role-less rejection to the queue would make the product worse
    for the overwhelmingly common case of one application per employer.
    """

    # A corporate sender, so the employer is nameable from the domain alone —
    # a role-less rejection relayed by a shared ATS names no employer at all and
    # is refused a step earlier, by `resolve_employer`.
    confirmation = item(
        "c1",
        "Thank you for applying to DoorDash",
        "no-reply@doordash.com",
        "Hi Ayush, Thank you for applying to DoorDash&#39;s Software Engineer I, "
        "Entry-Level position! We&#39;ve received your application",
    )
    rejection = item(
        "c2",
        "Update on your application",
        "no-reply@doordash.com",
        "Hi Ayush, we have decided not to move forward.",
        category="rejection",
        minutes=500,
    )

    rolled = p.roll_up_applications([confirmation, rejection])

    assert len(rolled) == 1
    assert rolled[0].status == "rejected"
    assert {m.message_id for m in rolled[0].messages} == {"c1", "c2"}


# --- role extraction ----------------------------------------------------------


@pytest.mark.parametrize(
    ("subject", "snippet", "expected"),
    [
        (
            "Crusoe | Application Received",
            "Hi Ayush, Thank you for applying to our role: Software Engineer I, Storage. "
            "We appreciate your interest in joining the team!",
            "Software Engineer I, Storage",
        ),
        (
            "Thank you for applying to DoorDash",
            "Hi Ayush, Thank you for applying to DoorDash&#39;s Software Engineer I, "
            "Entry-Level (Graduation Date: Fall 2025-Summer 2026) position!",
            "Software Engineer I, Entry-Level (Graduation Date: Fall 2025-Summer 2026)",
        ),
        (
            "Thank you for applying to Anthropic",
            "Hi Ayush, We appreciate you taking the time to submit an application for the "
            "TPU Kernel Engineer position, and are delighted",
            "TPU Kernel Engineer",
        ),
        (
            "Thank you for applying with MotherDuck!",
            "Hi Ayush, Thank you for your interest in joining the flock here at MotherDuck. "
            "We appreciate your interest in the Software Engineer - Database position.",
            "Software Engineer - Database",
        ),
        (
            "Thanks for applying to Cursor!",
            "Hi Ayush, Thank you for applying for the Software Engineer, Model Routing "
            "&amp; Inference role at Cursor!",
            "Software Engineer, Model Routing & Inference",
        ),
        # Two preposition+article pairs in one sentence. A regex matches
        # leftmost-first, so this shipped to the live board as the role
        # "interest in the Software Engineer, C#".
        (
            "Path Robotics update",
            "Dear Ayush, Thank you for your interest in the Software Engineer, C# "
            "position at Path Robotics. We have successfully received your online application.",
            "Software Engineer, C#",
        ),
        # Names no role anywhere. Must stay None rather than become a guess.
        (
            "Thank you for applying to Twitch",
            "Ayush, Thanks for applying to Twitch. Your application has been received "
            "and we will review it right away.",
            None,
        ),
    ],
)
def test_role_is_read_from_the_body_when_the_subject_does_not_carry_it(subject, snippet, expected):
    assert p.role_from_message(subject, snippet) == expected


def test_role_token_ignores_punctuation_drift():
    """One employer wording its own title two ways is still one application."""

    assert p.normalize_role_token("Software Engineer I, Storage") == p.normalize_role_token(
        "Software Engineer I - Storage"
    )
    assert p.normalize_role_token("TPU Kernel Engineer") != p.normalize_role_token(
        "Performance Engineer, Inference Systems"
    )


@pytest.mark.parametrize(
    ("subject", "snippet", "expected"),
    [
        ("Thank you for Applying to Amazon!", "your application for the SDE (ID: 3177934) position", "3177934"),
        ("Requisition ID: R-4821", "", "R-4821"),
        ("Your application JR0093214", "", "JR0093214"),
        # A bare year is not an id. Accepting one would merge every 2026 role at
        # an employer into a single application.
        ("Software Development Engineer - 2026 (US)", "", None),
        ("Thanks for applying to Supabase", "We review every application carefully.", None),
    ],
)
def test_requisition_ids_are_only_read_from_explicit_labels(subject, snippet, expected):
    assert p.extract_req_id(subject, snippet) == expected


# --- employer display names ---------------------------------------------------


@pytest.mark.parametrize(
    ("sender", "subject", "expected"),
    [
        # The careers subdomain is the right thing to trust and the wrong thing
        # to print: this rendered "Twitchjobs" on the live board.
        ("no-reply@twitchjobs.tv", "Thank you for applying to Twitch", "Twitch"),
        # Title-casing a lowercase domain label cannot know where the intercap
        # goes; the employer's own subject line can.
        ("no-reply@doordash.com", "Thank you for applying to DoorDash", "DoorDash"),
        ("jobs@ixl.com", "Thank you for applying to IXL Learning!", "IXL Learning"),
    ],
)
def test_the_subject_spelling_of_an_employer_beats_its_domain(sender, subject, expected):
    resolved = p.resolve_employer(sender, subject)
    assert resolved is not None
    assert resolved[1] == expected


def test_a_company_merely_mentioned_in_a_subject_does_not_rename_the_relay():
    """The agreement test is what keeps the subject from hijacking the name.

    An ATS relay's subject can mention an employer the domain knows nothing
    about; only a subject that AGREES with the domain may override its spelling.
    """

    resolved = p.resolve_employer("no-reply@us.greenhouse-mail.io", "Thank you for applying to Anthropic")
    assert resolved is not None
    assert resolved[1] == "Anthropic"


# --- resolving a cluster onto a stored row ------------------------------------
#
# The rules above are pure; these are the persistent half. Both cases below were
# found by predicting what a real sync would do to the owner's live rows, and
# both would have been visible damage.

import uuid as _uuid  # noqa: E402

from jobtracker.cloud import applications as apps  # noqa: E402
from jobtracker.database.models import (  # noqa: E402
    Application,
    ApplicationStatus,
    Email,
    EmailCategory,
    EmailSource,
)

USER = _uuid.UUID("7d8676d9-6f45-4466-a1b1-fa63575b2ff5")


def stored(
    company: str,
    *,
    req_id: str | None = None,
    role_token: str | None = None,
    source: str | None = "gmail",
    app_id: int | None = None,
) -> Application:
    return Application(
        id=app_id,
        user_id=USER,
        company=company,
        position="",
        status=ApplicationStatus.APPLIED,
        source=source,
        req_id=req_id,
        role_token=role_token,
    )


def test_a_cluster_that_names_no_role_never_mints_beside_existing_rows():
    """Idempotence at an employer that already has two rows.

    Returning None here would mint a fresh row on every single sync — the same
    unbounded growth PR #76 fixed by a different route. The owner's live board
    carries exactly this shape: two "Together AI" rows, and Together AI's mail
    names no role anywhere.
    """

    rows = [stored("Together AI", app_id=64), stored("Together AI", app_id=65)]

    picked = apps._pick_application(rows, None, None)

    assert picked is not None
    assert picked.id == 64  # live-first, then oldest — stable across syncs


def test_an_identified_cluster_adopts_the_syncs_own_row_not_the_users():
    """A manual row is a human's entry and must not be rewritten.

    Live shape: Amazon holds one auto row from the sync and one filed by hand.
    Exactly one of them is the sync's to claim.
    """

    auto = stored("Amazon", source="gmail", app_id=69)
    manual = stored("Amazon", source="manual", app_id=75)

    picked = apps._pick_application(
        [auto, manual], "3177934", "software development engineer 2026 us"
    )

    assert picked is auto


def test_a_second_requisition_mints_rather_than_stealing_the_adopted_row():
    """Once a row carries an identity, a different requisition is a new row."""

    adopted = stored("Amazon", req_id="3177934", source="gmail", app_id=69)

    assert (
        apps._pick_application(
            [adopted], "3183020", "software development engineer embedded systems"
        )
        is None
    )
    assert (
        apps._pick_application([adopted], "3177934", "software development engineer 2026 us")
        is adopted
    )


# --- ghost nudges are per application too -------------------------------------


def _followups(items, days: int = 40):
    return p.flag_follow_ups(items, now=BASE + datetime.timedelta(days=days), stale_days=21)


def test_a_rejection_for_one_role_does_not_silence_the_nudge_for_another():
    """Grouping the ghost check by company hides a genuinely ignored application.

    Two Amazon requisitions; one is rejected, the other never answered. The
    un-answered one is exactly what a follow-up nudge is for.
    """

    rejected = amazon("f2", "Software Development Engineer – Database 2026 (US)", "3130865", 1)
    rejection = p.PipelineItem(
        **{
            **amazon("f3", "Software Development Engineer – Database 2026 (US)", "3130865", 5).__dict__,
            "category": "rejection",
        }
    )

    flags = _followups([AMAZON_FOUR[0], rejected, rejection])

    assert len(flags) == 1
    # The flagged one is the requisition nobody answered, not the rejected one.
    assert flags[0].message_id == "a1"


def test_a_response_that_names_no_role_still_answers_the_whole_company():
    """The conservative direction, on purpose.

    "Update on your application" cannot be attributed to one of four
    requisitions. Suppressing a nudge is a small annoyance; telling someone a
    company has ignored them when it has already written back is not.
    """

    silent = item(
        "f4",
        "Update on your application",
        AMAZON_SENDER,
        "Hi Ayush, we have an update for you.",
        category="rejection",
        minutes=60,
    )

    assert _followups(AMAZON_FOUR + [silent]) == []


# --- the user's own answer to "which application is this about?" --------------


async def _seed(session, rows: list[Application]) -> None:
    for row in rows:
        session.add(row)
    await session.commit()


async def test_the_users_choice_of_application_is_honoured(test_session):
    """The review queue asks which of an employer's rows a message belongs to.

    A message that names no role — "Update on your application" — belongs to
    exactly one of four Amazon applications without saying which. The answer has
    to actually be used, or the control is decoration.
    """

    await _seed(
        test_session,
        [
            stored("Amazon", req_id="3177934", app_id=None),
            stored("Amazon", req_id="3130865", app_id=None),
        ],
    )
    rows = await apps._company_rows(test_session, USER, "amazon")
    assert len(rows) == 2
    target = rows[1]

    picked = await apps._chosen_application(test_session, USER, target.id, "amazon")

    assert picked is not None
    assert picked.id == target.id


async def test_a_choice_at_the_wrong_employer_is_ignored_not_obeyed(test_session):
    """A stale id from a board that has re-synced must not misfile the message.

    Falling back to ordinary resolution files it correctly; obeying the id would
    attach an Amazon message to a Crusoe row.
    """

    await _seed(
        test_session,
        [stored("Amazon", req_id="3177934"), stored("Crusoe", role_token="software engineer i storage")],
    )
    crusoe = (await apps._company_rows(test_session, USER, "crusoe"))[0]

    assert await apps._chosen_application(test_session, USER, crusoe.id, "amazon") is None
    assert await apps._chosen_application(test_session, USER, None, "amazon") is None
    assert await apps._chosen_application(test_session, USER, 99999, "amazon") is None


async def test_a_stored_employer_name_is_restyled_when_the_resolver_improves(test_session):
    """A fix to name resolution has to reach the rows already on the board.

    "Doordash" was live — a title-cased domain label that cannot know where the
    intercap goes. Restyling only happens when the new spelling still answers to
    the same token, so the row stays findable on the next sync.
    """

    row = stored("Doordash", source="gmail")
    await _seed(test_session, [row])

    rolled = p.RolledApplication(
        company_token="doordash",
        company_display="DoorDash",
        role=None,
        status="applied",
        applied_at=None,
        last_activity=None,
    )
    created, updated = await apps.upsert_applications_for_user(test_session, USER, [rolled])

    assert (created, updated) == (0, 1)
    rows = await apps._company_rows(test_session, USER, "doordash")
    assert [r.company for r in rows] == ["DoorDash"]


async def test_a_user_owned_row_keeps_the_name_the_user_gave_it(test_session):
    """The sync owns an auto row's company. It does not own a human's."""

    await _seed(test_session, [stored("My Own Label", source="manual")])
    rolled = p.RolledApplication(
        company_token="my",
        company_display="My Corp",
        role=None,
        status="applied",
        applied_at=None,
        last_activity=None,
    )

    await apps.upsert_applications_for_user(test_session, USER, [rolled])

    rows = await apps._company_rows(test_session, USER, "my")
    assert [r.company for r in rows] == ["My Own Label"]


def test_the_match_token_moves_with_the_display_name():
    """Otherwise a restyled row becomes unfindable and the sync duplicates it.

    `matches_company_token` compares leading words, so a row displayed as
    "Twitch" cannot be found by the token "twitchjobs". Returning one without
    the other is how a rename turns into a duplicate.
    """

    resolved = p.resolve_employer("no-reply@twitchjobs.tv", "Thank you for applying to Twitch")

    assert resolved == ("twitch", "Twitch")
    assert p.matches_company_token(resolved[1], resolved[0])


def test_a_domain_that_disagrees_with_the_subject_keeps_its_own_token():
    """The agreement test is the whole safety of taking a name from a subject."""

    resolved = p.resolve_employer(
        "careers@stripe.com", "Your application to Acme was received"
    )

    assert resolved is not None
    assert resolved[0] == "stripe"


async def test_a_stored_role_is_re_taken_when_extraction_improves(test_session):
    """The same gap as the company name, one field over.

    Filling only an EMPTY position means an extraction fix reaches new rows and
    never the ones already on the board. "Path Robotics · interest in the
    Software Engineer, C#" outlived the fix that stopped producing it.
    """

    row = stored("Path Robotics", source="gmail", role_token="software engineer c")
    row.position = "interest in the Software Engineer, C#"
    await _seed(test_session, [row])

    rolled = p.RolledApplication(
        company_token="path",
        company_display="Path Robotics",
        role="Software Engineer, C#",
        status="applied",
        applied_at=None,
        last_activity=None,
        role_token="software engineer c",
    )
    await apps.upsert_applications_for_user(test_session, USER, [rolled])

    rows = await apps._company_rows(test_session, USER, "path")
    assert [r.position for r in rows] == ["Software Engineer, C#"]


async def test_a_role_the_user_wrote_is_never_overwritten(test_session):
    """A hand-filed row's title is the human's, and the sync does not own it."""

    row = stored("Path Robotics", source="manual", role_token="software engineer c")
    row.position = "SWE (C#) — the one Dana referred me for"
    await _seed(test_session, [row])

    rolled = p.RolledApplication(
        company_token="path",
        company_display="Path Robotics",
        role="Software Engineer, C#",
        status="applied",
        applied_at=None,
        last_activity=None,
        role_token="software engineer c",
    )
    await apps.upsert_applications_for_user(test_session, USER, [rolled])

    rows = await apps._company_rows(test_session, USER, "path")
    assert [r.position for r in rows] == ["SWE (C#) — the one Dana referred me for"]


def test_an_ats_relay_subdomain_does_not_become_the_employer():
    """Observed live: a "Rippling" row the owner never applied to.

    "Thank You for Applying to Supernova Technology", sent by
    no-reply@ats.rippling.com, filed an application at Rippling — the ATS — while
    the sender display name said Supernova Technology all along. A relay's own
    brand is never the employer.
    """

    resolved = p.resolve_employer(
        "no-reply@ats.rippling.com",
        "Thank You for Applying to Supernova Technology",
        "Supernova Technology",
    )

    assert resolved is not None
    token, display = resolved
    assert token != "rippling"
    assert display.startswith("Supernova")


async def test_an_exactly_named_row_does_not_hide_its_own_siblings(test_session):
    """The bug that grew six rows for one employer on the live board.

    A row named exactly "IXL" answers the exact-match query for token `ixl`, so
    the early return meant the rows named "IXL Learning" — same employer, same
    token — were never seen. The resolver read one row where there were three,
    and every rebuild minted another.

    Renaming a row is what makes the two sets diverge, so the rename feature and
    the early return were unsafe together and only the second one revealed it.
    """

    await _seed(
        test_session,
        [
            stored("IXL", source="gmail"),
            stored("IXL Learning", source="gmail"),
            stored("IXL Learning", source="gmail"),
        ],
    )

    rows = await apps._company_rows(test_session, USER, "ixl")

    assert len(rows) == 3
    assert {r.company for r in rows} == {"IXL", "IXL Learning"}


async def test_company_rows_puts_live_before_dismissed_across_both_queries(test_session):
    """The union must not let query order decide which row gets adopted."""

    dismissed = stored("IXL", source="gmail")
    dismissed.dismissed_at = datetime.datetime(2026, 8, 11, 5, 0)
    live = stored("IXL Learning", source="gmail")
    await _seed(test_session, [dismissed, live])

    rows = await apps._company_rows(test_session, USER, "ixl")

    assert [r.company for r in rows] == ["IXL Learning", "IXL"]


@pytest.mark.parametrize(
    ("sender", "subject"),
    [
        ("jobs@ixl.com", "Thank you for applying to IXL Learning!"),
        ("no-reply@twitchjobs.tv", "Thank you for applying to Twitch"),
        ("no-reply@doordash.com", "Thank you for applying to DoorDash"),
        ("careers@torc.ai", "Thank you for applying to Torc Robotics"),
    ],
)
def test_a_resolved_employer_can_always_find_its_own_stored_row(sender, subject):
    """The invariant that ties the two halves of identity together.

    `_company_rows` finds a stored row by running `matches_company_token` over
    its display name. If `resolve_employer` ever returns a token that does not
    match the display it returned alongside it, the lookup misses its own row
    and the upsert mints another — every sync, forever.

    That is not hypothetical: a multi-word name was space-stripped into
    "ixllearning", which matches the stored "IXL Learning" under no rule, and the
    owner's board grew a fresh "IXL Learning" and "Torc Robotics" row on every
    single rebuild.
    """

    resolved = p.resolve_employer(sender, subject)

    assert resolved is not None
    token, display = resolved
    assert p.matches_company_token(display, token), (
        f"resolve_employer returned token {token!r} for display {display!r}, "
        "which cannot find its own row"
    )


# --- splitting a merged row from stored mail alone -----------------------------


def mail(
    message_id: str,
    subject: str,
    snippet: str,
    *,
    application_id: int | None = None,
    category=None,
    minutes: int = 0,
) -> Email:
    return Email(
        user_id=USER,
        application_id=application_id,
        source_account=EmailSource.GMAIL,
        message_id=message_id,
        subject=subject,
        sender_email=AMAZON_SENDER,
        body_snippet=snippet,
        received_at=BASE + datetime.timedelta(minutes=minutes),
        classified_as=category or EmailCategory.APPLIED,
        classification_confidence=0.9,
    )


def amazon_mail(message_id: str, role: str, req: str, minutes: int, **kw) -> Email:
    return mail(
        message_id,
        AMAZON_SUBJECT,
        f"Amazon.jobs Hi Ayush, Thanks for applying to Amazon! We&#39;ve received your "
        f"application for the {role} (ID: {req}) position. What ha",
        minutes=minutes,
        **kw,
    )


def test_a_merged_row_offers_its_own_mail_as_a_split():
    """No Gmail call needed — the identity is already on disk.

    Every contributing message kept its subject and snippet, so the requisition
    ids that tell four Amazon applications apart can be read straight back out.
    That is what makes splitting possible without a rebuild, which is the only
    other route and reads as destructive.
    """

    clusters = apps.cluster_stored_mail(
        [
            amazon_mail("m1", "Software Development Engineer - 2026 (US)", "3177934", 0),
            amazon_mail("m2", "Software Development Engineer – Database 2026 (US)", "3130865", 5),
            amazon_mail("m3", "Software Development Engineer, AWS Data Services - 2026 (US)", "10414316", 3),
        ]
    )

    assert len(clusters) == 3
    assert {c.req_id for c in clusters} == {"3177934", "3130865", "10414316"}
    # Earliest first — that cluster is the one that keeps the row's id.
    assert clusters[0].req_id == "3177934"


def test_a_row_whose_mail_names_one_application_offers_no_split():
    """"Fewer than two" is the normal case and must not read as an error."""

    assert apps.cluster_stored_mail([]) == []
    assert (
        apps.cluster_stored_mail(
            [
                mail("s1", "Thanks for applying to Supabase", "Hi Ayush, Thanks for applying to Supabase."),
                mail("s2", "Thank you for applying to Supabase!", "Hey Ayush, we confirm your application."),
            ]
        )
        == []
    )


def test_mail_that_names_no_role_stays_with_the_retained_row():
    """Real mail for this employer, unattributable — kept, never dropped."""

    clusters = apps.cluster_stored_mail(
        [
            amazon_mail("m1", "Software Development Engineer - 2026 (US)", "3177934", 0),
            amazon_mail("m2", "Software Development Engineer – Database 2026 (US)", "3130865", 5),
            mail("m3", "Update on your Amazon application", "Hi Ayush, we have an update.", minutes=90),
        ]
    )

    assert len(clusters) == 2
    assert "m3" in {e.message_id for e in clusters[0].emails}
    assert sum(len(c.emails) for c in clusters) == 3


def test_a_siblings_status_is_recomputed_not_inherited():
    """The row being split may already be terminal.

    `advance_application_status` never leaves a terminal state, so inheriting
    would hand every sibling one requisition's rejection — the exact damage the
    identity work exists to undo.
    """

    live = [amazon_mail("m1", "SDE - 2026 (US)", "3177934", 0)]
    rejected = [
        amazon_mail("m2", "SDE – Database 2026 (US)", "3130865", 5),
        amazon_mail("m3", "SDE – Database 2026 (US)", "3130865", 400, category=EmailCategory.REJECTION),
    ]

    assert apps._status_from_mail(live) == "applied"
    assert apps._status_from_mail(rejected) == "rejected"


# --- the snippet the user actually reads --------------------------------------


def test_snippets_are_decoded_before_they_are_stored():
    """The detail sheet rendered "Please don&#39;t be" verbatim on the live board.

    Gmail returns snippets pre-escaped and they were persisted exactly as
    fetched, so every surface that shows one showed the raw entity. Decoding at
    the persistence layer fixes all of them at once, and the stored value is
    then also what role extraction compares.
    """

    raw = "Hi Ayush, Thanks for applying to Supabase. We&#39;re glad you&#39;re interested &amp; excited."

    assert p.unescape_entities(raw) == (
        "Hi Ayush, Thanks for applying to Supabase. We're glad you're interested & excited."
    )
    # Numeric and named forms beyond the handful that happened to show up.
    assert p.unescape_entities("caf&eacute; &mdash; 5&nbsp;PM &#8212; &hellip;") == (
        "café — 5 PM — …"
    )
    # No entities: returned unchanged, not re-encoded.
    assert p.unescape_entities("plain text") == "plain text"
    assert p.unescape_entities("") == ""


def test_a_role_extracted_from_a_decoded_snippet_is_unchanged():
    """Decoding at write time must not change what the extractor already found."""

    escaped = (
        "Amazon.jobs Hi Ayush, Thanks for applying to Amazon! We&#39;ve received your "
        "application for the Software Development Engineer - 2026 (US) (ID: 3177934) position."
    )
    decoded = p.unescape_entities(escaped)

    assert p.role_from_message(AMAZON_SUBJECT, escaped) == p.role_from_message(
        AMAZON_SUBJECT, decoded
    )
    assert p.extract_req_id(AMAZON_SUBJECT, decoded) == "3177934"


# --- deadlines ----------------------------------------------------------------
#
# The product's landing page opens by promising an assessment's 48-hour deadline
# will not pass unseen. These are the tests that keep that promise honest — and
# the ones that matter most are the refusals, because a fabricated deadline
# would have someone drop what they are doing for a date nobody set.


@pytest.mark.parametrize(
    ("body", "expected_days"),
    [
        ("Please complete the assessment within 48 hours.", 2),
        ("Kindly finish your take-home within 3 days.", 3),
        # Weekends are not working days: Tue + 5 business days is the next Tuesday.
        ("You have 5 business days to complete your take-home.", 7),
    ],
)
def test_a_stated_window_is_anchored_to_the_message(body, expected_days):
    sent = datetime.datetime(2026, 8, 11, 14, 0)  # a Tuesday

    due = p.extract_deadline("Your assessment", body, sent)

    assert due is not None
    assert (due - sent).days == expected_days


@pytest.mark.parametrize(
    "body",
    [
        "Your challenge link expires on August 15, 2026.",
        "Please submit your exercise no later than Aug 15.",
        "Kindly complete by 08/15/2026 to move forward.",
    ],
)
def test_a_stated_calendar_date_becomes_an_end_of_day_deadline(body):
    """End of day, because a date with no time is a whole day.

    Treating it as midnight would mark the application overdue a full day early,
    which for this feature is the same class of error as inventing one.
    """

    due = p.extract_deadline("Assessment", body, datetime.datetime(2026, 8, 11, 14, 0))

    assert due == datetime.datetime(2026, 8, 15, 23, 59, 59)


@pytest.mark.parametrize(
    "body",
    [
        # THE case. This sentence appears in almost every application
        # confirmation ever sent, and reading it as a deadline would have put a
        # fabricated due date on very nearly every card on the board.
        "We will get back to you within 5 business days.",
        "Our team will review and respond within 48 hours.",
        "You will hear from us within 7 days.",
        "We will review your application within 10 days.",
        "We aim to respond by August 20, 2026.",
        # A date, but not a deadline.
        "Your interview is scheduled for August 20, 2026 at 2pm.",
        "Thanks for applying. We received it on August 11, 2026.",
        "Copyright 2026. Unsubscribe here.",
        # Cue present, but the window is nonsense or already past.
        "Please complete within 0 hours.",
        "Please complete by August 1, 2026.",
    ],
)
def test_a_deadline_is_never_invented(body):
    assert p.extract_deadline("Update on your application", body, datetime.datetime(2026, 8, 11, 14, 0)) is None


def test_no_deadline_without_an_anchor():
    """"Within 48 hours" of what? Undated mail cannot say."""

    assert p.extract_deadline("Assessment", "Please complete within 48 hours.", None) is None


def test_the_latest_stated_deadline_wins():
    """A rescheduled assessment supersedes the original."""

    first = item(
        "d1",
        "Your Roblox assessment",
        "assessment@email.roblox.com",
        "Please complete the assessment within 48 hours.",
        category="assessment",
        minutes=0,
    )
    rescheduled = item(
        "d2",
        "Your Roblox assessment — extended",
        "assessment@email.roblox.com",
        "Good news: please complete the assessment within 7 days.",
        category="assessment",
        minutes=60,
    )

    rolled = p.roll_up_applications([first, rescheduled])

    assert len(rolled) == 1
    assert rolled[0].due_at == BASE + datetime.timedelta(minutes=60, days=7)


def test_the_owners_real_mail_produces_no_deadlines():
    """22 real application confirmations, zero invented deadlines.

    Kept as a corpus test rather than prose because "it doesn't fire on real
    mail" is the only claim that matters, and it is the one a future pattern
    tweak is most likely to break.
    """

    corpus = [
        ("Crusoe | Application Received", "Thank you for applying to our role: Software Engineer I, Storage. We will review your application shortly."),
        ("Thanks for applying to Cursor!", "We appreciate your interest in joining the team. We will review your application and get back"),
        ("Thank you for applying with MotherDuck!", "Our team will review your application and will"),
        ("Thank you for applying to Together AI", "Your application has been received and we will review it right away."),
        ("Thank you for applying to Supabase!", "We respond to all candidates and will be in touch."),
        ("Thank you for Applying to Amazon!", "We've received your application for the Software Development Engineer - 2026 (US) (ID: 3177934) position. What happens next?"),
        ("Thank you for applying to IXL Learning!", "Our hiring team will review your resume soon! Please note, due to the high volume of applications we receive"),
        ("Your application has been received!", "Our team is reviewing your application and will be in touch if we think you're a potential match"),
        ("Thank You for Applying to Supernova Technology", "We have received your application and will review it promptly."),
    ]
    sent = datetime.datetime(2026, 8, 11, 5, 0)

    invented = [
        subject for subject, body in corpus if p.extract_deadline(subject, body, sent) is not None
    ]

    assert invented == []


# --- an employer name one edit from one already on the board ------------------
#
# Applications 110 and 119 on the owner's board, 2026-08-13: the same Verkada
# role twice, one reading APPLIED under "Verkada" and one reading REJECTED under
# "Verkeda". Both messages came from no-reply@us.greenhouse-mail.io, which names
# no employer, so the rejection reached the review queue and a human typed the
# company — one letter wrong. Identity is employer + (req_id or role), so the
# near miss on the employer half defeated the key before the role half was ever
# consulted, and a status change minted a fifth row instead of settling one.
#
# The rule below is a QUESTION, never a merge. Every test here is written to
# that distinction, because the failure it must not trade for is joining two
# real employers: `advance_application_status` never leaves a terminal status,
# so a wrongly-merged rejection is unreachable through the product afterwards.

# The rejection as Greenhouse actually sends it: the subject names no employer
# and no role, and the role is only in the body.
VERKADA_ROLE_TOKEN = "embedded software engineer access control"
REJECTION_SUBJECT = "Update on your application"
REJECTION_SNIPPET = (
    "Thank you for your interest in the Embedded Software Engineer, Access Control "
    "position. Although your application was not selected to move forward, we "
    "appreciate the time you invested."
)
GREENHOUSE = "no-reply@us.greenhouse-mail.io"


def review_mail(message_id: str, snippet: str = REJECTION_SNIPPET) -> Email:
    """One rejection sitting in the review queue: unlinked, un-reviewed."""

    return Email(
        user_id=USER,
        source_account=EmailSource.GMAIL,
        message_id=message_id,
        subject=REJECTION_SUBJECT,
        sender_email=GREENHOUSE,
        body_snippet=snippet,
        received_at=datetime.datetime(2026, 8, 13, 17, 30),
        classified_as=EmailCategory.NEEDS_REVIEW,
        classification_confidence=0.7,
    )


def test_the_relay_that_started_this_still_names_no_employer():
    """The premise the rest of this section rests on, asserted rather than assumed.

    If the resolver could name Verkada from this message the review queue would
    never have asked, the human would never have typed a spelling, and the whole
    path below would be unreachable. It cannot: an ATS relay's subject lead and
    display name are the only signals it has, and this rejection carries neither.

    Mutation: pointing the fixture at a sender whose own domain is the employer
    → resolves, and the near-miss tests below stop exercising what they claim.
    """

    assert p.resolve_employer(GREENHOUSE, REJECTION_SUBJECT, None) is None
    assert p.normalize_role_token(p.role_from_message(REJECTION_SUBJECT, REJECTION_SNIPPET)) == (
        VERKADA_ROLE_TOKEN
    )


def test_a_one_letter_slip_is_offered_the_spelling_already_on_the_board():
    """"Verkeda" against a board holding "Verkada" — the reported case, pure.

    Mutation: `_within_one_edit` returning False for a substitution → None, and
    the endpoint test below opens its second row again.
    """

    assert p.near_miss_employer("verkeda", ["Verkada", "Anthropic"]) == "Verkada"
    # Every shape a hand slips in, not just the substitution that was reported.
    assert p.near_miss_employer("verkada", ["Verkadaa"]) == "Verkadaa"  # doubled letter
    assert p.near_miss_employer("verkda", ["Verkada"]) == "Verkada"  # dropped letter
    assert p.near_miss_employer("verkaad", ["Verkada"]) == "Verkada"  # swapped pair
    # A stored display name is compared by its LEADING word, the same way
    # `matches_company_token` compares one — otherwise every multi-word employer
    # on the board is invisible to this check.
    assert p.near_miss_employer("verkeda", ["Verkada Security Inc"]) == "Verkada Security Inc"


@pytest.mark.parametrize(
    ("typed", "board"),
    [
        # Different first letters. The part of a brand a reader recognises.
        ("notion", ["Motion"]),
        ("figma", ["Sigma"]),
        ("zoom", ["Loom"]),
        # Short enough that one edit is most of the word. These two share their
        # opening letters, so the length floor is the ONLY rule holding them
        # apart — pairs the prefix rule already catches would leave it untested.
        ("loom", ["Loop"]),
        ("bolt", ["Bold"]),
        # Two edits or more is not a slip, it is another company. Coinbase and
        # Codebase clear the length floor and share their opening letters, so
        # the edit budget is the only thing separating them — the far-apart
        # pairs below never reach it.
        ("coinbase", ["Codebase"]),
        ("datadog", ["Databricks"]),
        ("verkada", ["Verizon"]),
        ("anthropic", ["Verkada"]),
        # Already the same employer: the caller found no row for this token, so
        # answering "did you mean the identical name?" would loop the user.
        ("verkada", ["Verkada"]),
        ("verkada", ["Verkada Security"]),
        # Nothing on the board at all.
        ("verkeda", []),
    ],
)
def test_two_employers_that_are_not_one_typo_apart_are_never_offered(typed, board):
    """The negative half, and the one that decides whether this is safe to ship.

    Mutation: dropping the length floor → Zoom/Loom and Bolt/Volt are offered;
    dropping the shared-prefix rule → Notion/Motion and Figma/Sigma are; raising
    the edit budget to two → Datadog/Databricks is. Each was seen failing.
    """

    assert p.near_miss_employer(typed, board) is None


def test_several_near_misses_ask_rather_than_falling_silent():
    """Ambiguity is a reason to ASK, not a reason to mint the row it is about.

    The board below is the owner's own, today: one employer already spelled two
    ways. That is where a third typo is MOST likely, not least — so returning
    None on "more than one candidate", which is the natural rule for an
    auto-merge, would reproduce the entire defect in exactly the case that
    already went wrong once. The pick is deterministic instead, and stable under
    the order the rows come back in.

    Mutation: `return None` when `len(matches) > 1` → both assertions fail and
    a third spelling is minted silently.
    """

    assert p.near_miss_employer("verkida", ["Verkeda", "Verkada"]) == "Verkada"
    assert p.near_miss_employer("verkida", ["Verkada", "Verkeda"]) == "Verkada"


async def test_a_typod_employer_asks_instead_of_opening_a_second_application(test_session):
    """THE case: existing "Verkada", incoming "Verkeda", same role → one row.

    The first call is the human typing the typo. Nothing may be filed from it —
    not the new row that production got, and not a silent merge onto the existing
    one either. The second call is them accepting the offered spelling, and it
    settles the application that was already there.

    Mutation: skipping the `_misspelled_employer` check in `classify_review_item`
    → the first call returns an `application_id`, `rows` is 2, and the assertion
    on `needs_company_confirmation` fails first.
    """

    await _seed(
        test_session,
        [stored("Verkada", role_token=VERKADA_ROLE_TOKEN, source="gmail")],
    )
    test_session.add(review_mail("rejection-113"))
    await test_session.commit()

    asked = await apps.classify_review_item(
        test_session,
        USER,
        "rejection-113",
        EmailCategory.REJECTION,
        company="Verkeda",
    )

    assert asked["needs_company_confirmation"] is True
    assert asked["suggested_company"] == "Verkada"
    assert asked["application_id"] is None
    # The pair, deliberately: a client that predates the confirmation still
    # reads this as "name the company" and keeps the row in the queue, rather
    # than reading a resolved 2xx and dropping an item that filed nothing.
    assert asked["needs_employer"] is True
    assert len(await apps._company_rows(test_session, USER, "verkeda")) == 0
    # ...and the existing application was not quietly settled on the guess.
    verkada = await apps._company_rows(test_session, USER, "verkada")
    assert [r.status for r in verkada] == [ApplicationStatus.APPLIED]

    filed = await apps.classify_review_item(
        test_session,
        USER,
        "rejection-113",
        EmailCategory.REJECTION,
        company="Verkada",
    )

    verkada = await apps._company_rows(test_session, USER, "verkada")
    assert len(verkada) == 1, "the role appears twice on the board again"
    assert verkada[0].status == ApplicationStatus.REJECTED
    assert filed["application_id"] == verkada[0].id


async def test_a_role_less_near_miss_asks_before_it_could_guess_a_sibling(test_session):
    """The ask has to come first, or the employer's row count decides the answer.

    A rejection that names no role reaches `_pick_application` with (None, None),
    where rule 4 returns the employer's first row rather than minting. So at a
    one-row employer a loose match would look harmless and at a four-row one it
    would settle an arbitrary sibling — the same reason the queue asks "which
    application is this about?" at all. Neither happens: the spelling is queried
    before any of it.

    Mutation: skipping the check → this mints a "Verkeda" row beside the two
    Verkada ones and both assertions fail.
    """

    await _seed(
        test_session,
        [
            stored("Verkada", role_token=VERKADA_ROLE_TOKEN, source="gmail"),
            stored("Verkada", role_token="security engineer", source="gmail"),
        ],
    )
    test_session.add(review_mail("rejection-role-less", snippet="Although your application"))
    await test_session.commit()

    asked = await apps.classify_review_item(
        test_session,
        USER,
        "rejection-role-less",
        EmailCategory.REJECTION,
        company="Verkeda",
    )

    assert asked["needs_company_confirmation"] is True
    rows = await apps._company_rows(test_session, USER, "verkada")
    assert [r.status for r in rows] == [ApplicationStatus.APPLIED, ApplicationStatus.APPLIED]


async def test_a_genuinely_different_employer_is_filed_without_a_question(test_session):
    """The cost of the check, bounded: it must not stand between a user and a
    company they have simply never applied to before.

    Mutation: comparing on `startswith` instead of an edit budget → "Anthropic"
    is offered "Verkada" (or vice versa) and this asks a question nobody can
    answer usefully.
    """

    await _seed(test_session, [stored("Verkada", role_token=VERKADA_ROLE_TOKEN, source="gmail")])
    test_session.add(review_mail("rejection-anthropic"))
    await test_session.commit()

    filed = await apps.classify_review_item(
        test_session,
        USER,
        "rejection-anthropic",
        EmailCategory.REJECTION,
        company="Anthropic",
    )

    assert filed.get("needs_company_confirmation") is None
    assert filed["application_id"] is not None
    anthropic = await apps._company_rows(test_session, USER, "anthropic")
    assert [r.company for r in anthropic] == ["Anthropic"]
    # Verkada's row is untouched — the two employers did not merge.
    verkada = await apps._company_rows(test_session, USER, "verkada")
    assert [r.status for r in verkada] == [ApplicationStatus.APPLIED]


async def test_a_confirmed_new_company_is_two_employers_not_one(test_session):
    """Stripe and Strive are one edit apart and both real. The rule flags that
    pair by design, so the human's "no" has to be the end of it.

    This is the negative that matters more than the positive: it proves the
    resemblance is never acted on. Nothing merges here — the board ends with two
    applications at two employers, which is what the user said was true.

    Mutation: treating the near miss as a match and filing against the suggested
    row → one row named "Stripe" holding the other company's rejection, at a
    terminal status `advance_application_status` will not let it leave.
    """

    await _seed(test_session, [stored("Stripe", role_token=VERKADA_ROLE_TOKEN, source="gmail")])
    test_session.add(review_mail("rejection-strive"))
    await test_session.commit()

    asked = await apps.classify_review_item(
        test_session, USER, "rejection-strive", EmailCategory.REJECTION, company="Strive"
    )
    assert asked["needs_company_confirmation"] is True
    assert asked["suggested_company"] == "Stripe"

    filed = await apps.classify_review_item(
        test_session,
        USER,
        "rejection-strive",
        EmailCategory.REJECTION,
        company="Strive",
        confirm_new_company=True,
    )

    strive = await apps._company_rows(test_session, USER, "strive")
    assert [r.company for r in strive] == ["Strive"]
    assert filed["application_id"] == strive[0].id
    stripe = await apps._company_rows(test_session, USER, "stripe")
    assert [r.status for r in stripe] == [ApplicationStatus.APPLIED]


async def test_an_employer_only_on_a_dismissed_row_is_not_offered(test_session):
    """A suggestion has to name something the user can see.

    `_company_rows` puts live rows first, so accepting a dismissed employer's
    name would file the mail against a row that is not on the board — worse than
    the extra row, and invisible either way. Minting here is the behaviour this
    path already had.

    Mutation: dropping the `dismissed_at IS NULL` filter → this asks about a row
    the board does not show.
    """

    dismissed = stored("Verkada", role_token=VERKADA_ROLE_TOKEN, source="gmail")
    dismissed.dismissed_at = datetime.datetime(2026, 8, 12, 9, 0)
    await _seed(test_session, [dismissed])
    test_session.add(review_mail("rejection-dismissed"))
    await test_session.commit()

    filed = await apps.classify_review_item(
        test_session, USER, "rejection-dismissed", EmailCategory.REJECTION, company="Verkeda"
    )

    assert filed.get("needs_company_confirmation") is None
    assert filed["application_id"] is not None


async def test_an_employer_the_mail_names_itself_is_never_second_guessed(test_session):
    """Only a HAND-TYPED name can carry a typo.

    A name the resolver read out of the mail is machine-derived and consistent
    with itself; running it past this check would mean the SYNC could be stopped
    by a question nobody is standing there to answer. The flag exists for that
    reason, and this pins it.

    Mutation: dropping the `named_by_hand` guard → this asks about a company the
    message named itself, and the user's classification files nothing.
    """

    await _seed(test_session, [stored("Verkada", source="gmail")])
    email = review_mail("rejection-named")
    email.sender_email = "careers@verkeda.com"  # a different employer's own domain
    test_session.add(email)
    await test_session.commit()

    filed = await apps.classify_review_item(
        test_session, USER, "rejection-named", EmailCategory.REJECTION, company="Verkada"
    )

    assert filed.get("needs_company_confirmation") is None
    assert filed["application_id"] is not None


# --- the leftmost-anchor misfire (SimpliSafe, #320 regression) -----------------
#
# Reported from the live board on 2026-08-15: a rejection for a job already
# tracked minted a SECOND card instead of settling the first. Row 73 held
# "SimpliSafe" / "software engineer i user systems" in APPLIED; row 124 arrived
# as "Simplisafe" / "interest in simplisafe and our software engineer i user
# systems" in REJECTED. Same job, twice.
#
# The cause is `_ROLE_BODY_PATTERNS`' preposition+article pattern. `re.search`
# returns the LEFTMOST match, so it anchored on "for your " at offset 20 and the
# lazy capture stretched to the sentence's single "position", swallowing the
# employer name and a conjunction. The correct anchor is "and our " at offset
# 52 — which was not an anchor at all, because "and" was missing from the
# alternation.
#
# A regression from #320: before the body-reading change the classifier only saw
# Gmail's ~200-char snippet, so these body patterns fired on far less text than
# they now do.

SIMPLISAFE_SUBJECT = "Important information about your application to SimpliSafe"
SIMPLISAFE_REJECTION = (
    "Hi Ayush, Thank you for your interest in SimpliSafe and our Software "
    "Engineer I- User Systems position. We have carefully reviewed your "
    "application."
)
# Exactly what row 73 already carries, so a match here is a settled card.
SIMPLISAFE_ROLE_TOKEN = "software engineer i user systems"


def test_the_role_anchors_on_the_article_nearest_the_keyword():
    """The reported body, verbatim. The employer name must not enter the role.

    Mutation: drop `and` from the anchor alternation in the second
    `_ROLE_BODY_PATTERNS` entry → the only remaining anchor is the leftmost
    "for your " and the capture becomes the reported
    "interest in SimpliSafe and our Software Engineer I- User Systems".
    Mutation: drop the tempering (the negative lookahead inside the capture) →
    "for your " matches again and the same wrong role returns.
    """

    assert p.role_from_message(SIMPLISAFE_SUBJECT, SIMPLISAFE_REJECTION) == (
        "Software Engineer I- User Systems"
    )


def test_the_rejection_settles_the_existing_card_instead_of_minting_one():
    """The damage the user actually saw, asserted at the identity layer.

    The role above is only worth extracting because of what it keys. This is the
    assertion that encodes the bug report: the rejection must resolve ONTO row
    73, not past it.

    Mutation: either mutation above → the token becomes
    "interest in simplisafe and our software engineer i user systems", which
    matches no row, and `_pick_application` returns None — the caller's signal
    to mint the duplicate card.
    """

    row_73 = stored("SimpliSafe", role_token=SIMPLISAFE_ROLE_TOKEN, app_id=73)

    role = p.role_from_message(SIMPLISAFE_SUBJECT, SIMPLISAFE_REJECTION)
    picked = apps._pick_application(
        [row_73],
        p.extract_req_id(SIMPLISAFE_SUBJECT, SIMPLISAFE_REJECTION),
        p.normalize_role_token(role),
    )

    assert picked is row_73


def test_employer_narrowing_ignores_the_case_the_employer_typed():
    """"SimpliSafe" and "Simplisafe" are one employer, not two.

    The two live rows disagree on case, which would be a SECOND independent
    cause of duplicate cards if the employer half of the key were
    case-sensitive. It is not — both sides go through `_normalize_token` — and
    that is asserted here rather than read off the source.

    Mutation: drop the `.lower()` from `_normalize_token` → every assertion here
    fails and the duplicate has two causes instead of one.
    """

    assert p.matches_company_token("SimpliSafe", "simplisafe")
    assert p.matches_company_token("Simplisafe", "simplisafe")
    assert p.matches_company_token("SIMPLISAFE", "simplisafe")
    # Both spellings normalise to the one token the lookup queries by.
    assert p.normalize_company_name("SimpliSafe") == p.normalize_company_name("Simplisafe")


@pytest.mark.parametrize(
    ("snippet", "expected"),
    [
        # The fix, on the shape that motivated it.
        (
            "Thank you for your interest in Acme and the Backend Engineer role.",
            "Backend Engineer",
        ),
        # `and` as an anchor must not invent a role out of ordinary prose. The
        # all-lowercase capture "hiring manager for this" is refused by the
        # Title-Case guard, which is the only thing standing between the wider
        # alternation and a fabricated identity.
        (
            "We received your resume and the hiring manager for this position "
            "will review it shortly.",
            None,
        ),
        (
            "Thanks for applying. We will keep your resume on file and the "
            "recruiter for the role will be in touch.",
            None,
        ),
        # `at`/`with` temper a capture but are deliberately NOT outer anchors,
        # so this refuses rather than re-anchoring on "at the". A decision, not
        # an accident: a wrong role is strictly worse than no role, because
        # `_pick_application` rule 4 files a role-less message onto the
        # employer's existing row.
        (
            "Thank you for your interest in the Software Engineer at the Edge position.",
            None,
        ),
        # The residual refusal, reached through the Ashby `role:` pattern, which
        # is deliberately untempered because Ashby prints the title verbatim
        # after the colon. Here the template does not, and the fragment must be
        # refused rather than keyed.
        #
        # The next two cases isolate the two halves of that refusal. Written
        # because the obvious single case ("... and our Storage team") trips
        # BOTH halves, so either one could be deleted with the suite still
        # green — a gate that cannot fail.
        #
        # Only the anchor+article half sees this one: "and the" is exactly the
        # gap in `_clean_role`'s existing cut, which knows `in|for|to|at|with`
        # but not `and`.
        (
            "Thank you for applying to our role: Software Engineer and the Storage team",
            None,
        ),
        # Only the bare-possessive half sees this one: "our" here follows a
        # comma, not an anchor.
        (
            "Thank you for applying to our role: Software Engineer, our Flagship team",
            None,
        ),
        # A legitimate title containing "the" is NOT collateral damage.
        (
            "Thank you for your interest in the Head of the Americas position.",
            "Head of the Americas",
        ),
    ],
)
def test_a_body_capture_that_spans_a_clause_is_refused(snippet, expected):
    """A sentence fragment is never an identity.

    Mutation: remove the `\\b(?:and|for|in|to|at|with)\\s+(?:the|our|your|a|an)\\b`
    refusal in `_clean_role` → the Ashby case yields
    "Software Engineer and our Storage team".
    """

    assert p.role_from_message("Update on your application", snippet) == expected
