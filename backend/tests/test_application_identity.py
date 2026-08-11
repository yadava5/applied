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


def test_an_employer_that_names_no_role_keeps_exactly_one_row():
    """Supabase confirms twice, two hours apart, naming no role either time.

    Ambiguous by construction. One row is the honest floor — inventing two would
    assert a distinction the mail does not make.
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
    # "interest in a" is prose sitting between the anchors, not a job title. If
    # it were accepted it would key an application and split this employer in two.
    assert rolled[0].role is None
    assert rolled[0].role_token is None


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
