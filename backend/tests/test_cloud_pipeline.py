"""Unit tests for the pure cloud pipeline analytics (issue C7).

These cover the Gmail-free logic that runs over an accumulated set of
classified verdicts: company grouping (seeing through shared ATS relays),
category summarization, and the "no response — follow up" ghosting flag.
No network, no Gmail, no DB — just pure functions over plain data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from jobtracker.cloud import pipeline as p

# --- company_key ------------------------------------------------------------


def test_company_key_uses_registrable_brand_for_direct_sender() -> None:
    assert p.company_key("careers@stripe.com", "Thanks for applying", "Stripe") == "stripe"
    # Subdomains collapse to the brand.
    assert p.company_key("no-reply@jobs.stripe.com", "", None) == "stripe"


def test_company_key_handles_country_second_level_domain() -> None:
    assert p.company_key("hr@acme.co.uk", "", None) == "acme"


def test_company_key_sees_through_relay_to_subject_company() -> None:
    # Lever/Greenhouse front many employers; the domain brand is useless, so we
    # take the company named in the subject.
    assert (
        p.company_key("no-reply@lever.co", "Your application to Acme", "Acme via Lever")
        == "acme"
    )
    # Multi-word employers collapse to the stable leading brand token, so
    # "Globex Corp" / "Globex Inc" / "Globex" all group together.
    assert (
        p.company_key(
            "notifications@greenhouse.io", "Interview with Globex Corp", "Globex"
        )
        == "globex"
    )


def test_company_key_falls_back_to_cleaned_sender_name() -> None:
    # No company in the subject → strip recruiting noise from the display name.
    assert (
        p.company_key("no-reply@lever.co", "We received your submission", "Initech Recruiting")
        == "initech"
    )


def test_company_key_last_resort_is_stable_nonempty() -> None:
    # Consumer webmail with nothing to go on still yields a stable token.
    assert p.company_key("someone@gmail.com", "", None) == "gmail"
    assert p.company_key("garbage", "", None) == "unknown"


# --- summarize --------------------------------------------------------------


def _item(category: str, mid: str = "m") -> p.PipelineItem:
    return p.PipelineItem(message_id=mid, category=category, sender_email="a@b.com", subject="s")


def test_summarize_reports_every_bucket_zero_filled() -> None:
    summary = p.summarize([_item("applied", "1"), _item("applied", "2"), _item("offer", "3")])
    assert summary["applied"] == 2
    assert summary["offer"] == 1
    # Every canonical bucket is present, even at zero — the UI never has to guard.
    for cat in p.CANONICAL_CATEGORIES:
        assert cat in summary
    assert summary["rejection"] == 0


def test_summarize_tallies_unknown_category_honestly() -> None:
    summary = p.summarize([_item("weird_new_label", "1")])
    assert summary["weird_new_label"] == 1


# --- flag_follow_ups --------------------------------------------------------

NOW = datetime(2026, 7, 23, tzinfo=UTC)


def _msg(
    mid: str,
    category: str,
    company_email: str,
    days_ago: int | None,
    subject: str = "",
    name: str | None = None,
    conf: float = 0.9,
    thread_id: str | None = None,
) -> p.PipelineItem:
    received = None if days_ago is None else NOW - timedelta(days=days_ago)
    return p.PipelineItem(
        message_id=mid,
        category=category,
        sender_email=company_email,
        subject=subject,
        sender_name=name,
        received_at=received,
        confidence=conf,
        thread_id=thread_id,
    )


def test_follow_up_flags_old_unanswered_application() -> None:
    items = [_msg("a1", "applied", "careers@acme.com", 40)]
    flags = p.flag_follow_ups(items, now=NOW, stale_days=21)
    assert [f.company for f in flags] == ["acme"]
    assert flags[0].days_since == 40


def test_follow_up_cleared_by_later_response_from_same_company() -> None:
    items = [
        _msg("a1", "applied", "careers@globex.com", 40),
        _msg("i1", "interview", "careers@globex.com", 30),  # later than the application
    ]
    assert p.flag_follow_ups(items, now=NOW, stale_days=21) == []


def test_follow_up_ignores_earlier_unrelated_signal() -> None:
    # A response dated BEFORE the application does not clear it.
    items = [
        _msg("i0", "interview", "careers@globex.com", 60),
        _msg("a1", "applied", "careers@globex.com", 40),
    ]
    flags = p.flag_follow_ups(items, now=NOW, stale_days=21)
    assert [f.company for f in flags] == ["globex"]


def test_follow_up_respects_stale_threshold() -> None:
    items = [_msg("a1", "applied", "careers@initech.com", 5)]
    assert p.flag_follow_ups(items, now=NOW, stale_days=21) == []


def test_follow_up_skips_application_without_a_date() -> None:
    items = [_msg("a1", "applied", "careers@acme.com", None)]
    assert p.flag_follow_ups(items, now=NOW, stale_days=21) == []


def test_follow_up_dedupes_to_oldest_per_company() -> None:
    items = [
        _msg("a1", "applied", "careers@acme.com", 40),
        _msg("a2", "applied", "careers@acme.com", 25),
    ]
    flags = p.flag_follow_ups(items, now=NOW, stale_days=21)
    assert len(flags) == 1
    # The oldest (most overdue) application represents the company.
    assert flags[0].message_id == "a1"
    assert flags[0].days_since == 40


def test_follow_up_sorted_most_overdue_first() -> None:
    items = [
        _msg("a1", "applied", "careers@acme.com", 30),
        _msg("a2", "applied", "careers@globex.com", 90),
        _msg("a3", "applied", "careers@initech.com", 45),
    ]
    flags = p.flag_follow_ups(items, now=NOW, stale_days=21)
    assert [f.days_since for f in flags] == [90, 45, 30]


def test_follow_up_handles_naive_datetimes() -> None:
    # Gmail's Date header can parse to a naive datetime; comparison must not blow up.
    naive = datetime(2026, 6, 1, 12, 0, 0)  # ~52 days before NOW, no tzinfo
    items = [
        p.PipelineItem(
            message_id="a1",
            category="applied",
            sender_email="careers@acme.com",
            subject="Application received",
            received_at=naive,
        )
    ]
    flags = p.flag_follow_ups(items, now=NOW, stale_days=21)
    assert len(flags) == 1
    assert flags[0].company == "acme"


# --- roll_up_applications ---------------------------------------------------


def test_rollup_one_row_per_company_furthest_stage() -> None:
    items = [
        _msg("a1", "applied", "no-reply@lever.co", 40, "Application to Acme", "Acme via Lever"),
        _msg("i1", "interview", "no-reply@lever.co", 20, "Interview with Acme", "Acme"),
    ]
    rolled = p.roll_up_applications(items)
    assert len(rolled) == 1
    r = rolled[0]
    assert r.company_token == "acme"
    assert r.company_display == "Acme"
    # Furthest stage reached wins (applied < interview → interviewing).
    assert r.status == "interviewing"
    # applied_at is the earliest application date, not the interview date.
    assert r.applied_at is not None and r.applied_at.day == (NOW - timedelta(days=40)).day


def test_rollup_rejection_is_terminal_override() -> None:
    items = [
        _msg("a1", "applied", "careers@globex.com", 30, "Applied", "Globex"),
        _msg("o1", "offer", "careers@globex.com", 10, "Offer", "Globex"),
        _msg("r1", "rejection", "careers@globex.com", 5, "Update", "Globex"),
    ]
    rolled = p.roll_up_applications(items)
    assert len(rolled) == 1
    assert rolled[0].status == "rejected"


def test_rollup_skips_noise_and_weak_followup_only() -> None:
    items = [
        _msg("n1", "other", "news@digest.com", 1, "Weekly digest"),
        _msg("f1", "follow_up", "recruit@ghost.io", 5, "just checking in", "Ghost"),
        _msg("nr", "needs_review", "x@y.com", 2, "hmm"),
    ]
    # Nothing is a real lifecycle signal → no phantom application rows.
    assert p.roll_up_applications(items) == []


def test_rollup_extracts_role_from_subject() -> None:
    items = [
        _msg(
            "a1",
            "applied",
            "careers@acme.com",
            10,
            "Your application for the Senior Backend Engineer role",
            "Acme",
        )
    ]
    rolled = p.roll_up_applications(items)
    assert rolled[0].role == "Senior Backend Engineer"


def test_rollup_is_deterministic_and_sorted() -> None:
    items = [
        _msg("a2", "applied", "careers@zeta.com", 5, "Applied", "Zeta"),
        _msg("a1", "applied", "careers@alpha.com", 5, "Applied", "Alpha"),
    ]
    tokens = [r.company_token for r in p.roll_up_applications(items)]
    assert tokens == ["alpha", "zeta"]


# --- advance_application_status ---------------------------------------------


def test_advance_moves_forward_only() -> None:
    assert p.advance_application_status("applied", "offered") == "offered"
    assert p.advance_application_status("offered", "applied") == "offered"
    assert p.advance_application_status("applied", "interviewing") == "interviewing"


def test_advance_rejection_is_terminal_override_of_in_flight() -> None:
    assert p.advance_application_status("interviewing", "rejected") == "rejected"


def test_advance_never_overrides_a_settled_status() -> None:
    # A mail signal must not un-reject, un-accept, or un-withdraw a row.
    assert p.advance_application_status("rejected", "offered") == "rejected"
    assert p.advance_application_status("accepted", "rejected") == "accepted"
    assert p.advance_application_status("withdrawn", "interviewing") == "withdrawn"


# --- resolve_employer (precision: never fabricate a company) -----------------


def test_resolve_employer_uses_own_corporate_domain() -> None:
    assert p.resolve_employer("careers@stripe.com", "Thanks for applying", "Stripe") == (
        "stripe",
        "Stripe",
    )


def test_resolve_employer_sees_through_relay_to_subject() -> None:
    # Lever relays many employers; the domain is useless, the subject names Acme.
    assert p.resolve_employer(
        "no-reply@lever.co", "Your application to Acme was received", "Acme via Lever"
    ) == ("acme", "Acme")


def test_resolve_employer_returns_none_for_ats_job_alert() -> None:
    # Handshake / Greenhouse / Workday / PageUp relays with no named employer:
    # skipping is better than a garbage "Joinhandshake" / "Pageuppeople" row.
    assert p.resolve_employer("alerts@mail.joinhandshake.com", "New jobs for you", "Handshake") is None
    assert p.resolve_employer("no-reply@pageuppeople.com", "Application update", None) is None
    assert p.resolve_employer("no-reply@myworkday.com", "Workday Services", None) is None
    assert p.resolve_employer("no-reply@greenhouse-mail.io", "An update", None) is None


def test_resolve_employer_ignores_edu_and_person_and_fragments() -> None:
    # A student's university is not an employer here.
    assert p.resolve_employer("noreply@miamioh.edu", "Online Onboarding", "Miami OH") is None
    # A person on consumer webmail is never a company (no "Julee Johnson" rows).
    assert p.resolve_employer("julee.johnson@gmail.com", "Re: our chat", None) is None
    # A bare subject fragment never becomes a company ("The", "Software") when
    # the sender is a relay with no nameable employer.
    assert p.resolve_employer("news@mail.joinhandshake.com", "The Software you wanted", "The") is None


# --- roll_up precision gate --------------------------------------------------


def test_rollup_requires_confidence_at_or_above_gate() -> None:
    # Same employer, one gated verdict, one below-gate guess: status must not be
    # bumped by the low-confidence signal, and no row for the guess alone.
    items = [
        _msg("a1", "applied", "careers@acme.com", 10, "Application to Acme", "Acme", conf=0.90),
        _msg("i1", "interview", "careers@acme.com", 5, "Interview with Acme", "Acme", conf=0.75),
    ]
    rolled = p.roll_up_applications(items)
    assert len(rolled) == 1
    # The 0.75 interview is below the 0.85 gate → status stays applied.
    assert rolled[0].status == "applied"


def test_rollup_drops_low_confidence_lifecycle_entirely() -> None:
    items = [_msg("a1", "applied", "careers@acme.com", 10, "Application to Acme", "Acme", conf=0.60)]
    # Below the review floor → not a row and not even a review item.
    assert p.roll_up_applications(items) == []
    assert p.collect_review_items(items) == []


def test_rollup_skips_when_employer_unnameable_even_if_confident() -> None:
    # A confident "offer" from a person on webmail cannot name an employer:
    # skipping is required (this is the observed "Julee Johnson → OFFERED" bug).
    items = [_msg("o1", "offer", "julee.johnson@gmail.com", 2, "You have an offer", "Julee Johnson", conf=0.95)]
    assert p.roll_up_applications(items) == []
    # It still surfaces for human review rather than vanishing silently.
    review = p.collect_review_items(items)
    assert len(review) == 1 and review[0].company_display is None


def test_rollup_ignores_ats_job_alert_noise() -> None:
    # A Handshake job alert (marketing/noise) never becomes an application.
    items = [
        _msg("h1", "other", "alerts@mail.joinhandshake.com", 1, "New jobs for you", "Handshake", conf=0.96),
        _msg("h2", "applied", "alerts@mail.joinhandshake.com", 1, "New jobs for you", "Handshake", conf=0.90),
    ]
    # Even the (mis)labelled "applied" has no nameable employer → no hard row.
    assert p.roll_up_applications(items) == []


def test_rollup_carries_message_refs_and_dates() -> None:
    applied_day = NOW - timedelta(days=30)
    interview_day = NOW - timedelta(days=10)
    items = [
        _msg("a1", "applied", "careers@stripe.com", 30, "Thanks for applying to the Data Scientist role", "Stripe", conf=0.9, thread_id="t-a1"),
        _msg("i1", "interview", "careers@stripe.com", 10, "Interview with Stripe", "Stripe", conf=0.9, thread_id="t-i1"),
    ]
    rolled = p.roll_up_applications(items)
    assert len(rolled) == 1
    r = rolled[0]
    assert r.company_display == "Stripe"
    assert r.role == "Data Scientist"
    assert r.status == "interviewing"
    # Applied date is the earliest application mail, from the email — not now().
    assert r.applied_at is not None and r.applied_at.date() == applied_day.date()
    assert r.last_activity is not None and r.last_activity.date() == interview_day.date()
    # Message refs are attached newest-first for the click-through detail view.
    assert [m.message_id for m in r.messages] == ["i1", "a1"]
    assert r.messages[0].thread_id == "t-i1"


# --- collect_review_items (the "needs classification" queue) ------------------


def test_review_items_include_uncertain_band_and_needs_review() -> None:
    items = [
        # 0.70-0.85 band lifecycle → review.
        _msg("r1", "interview", "no-reply@lever.co", 3, "Interview with Globex", "Globex", conf=0.78),
        # explicit needs_review → review regardless of confidence.
        _msg("r2", "needs_review", "hr@initech.com", 2, "Quick question", "Initech", conf=0.4),
        # confident + nameable → a hard row, NOT review.
        _msg("r3", "applied", "careers@acme.com", 1, "Application to Acme", "Acme", conf=0.92),
        # plain noise → neither.
        _msg("r4", "other", "news@digest.example", 1, "Weekly digest"),
    ]
    review_ids = {r.message_id for r in p.collect_review_items(items)}
    assert review_ids == {"r1", "r2"}
    assert [r.company_token for r in p.roll_up_applications(items)] == ["acme"]


# --- gmail_deeplink ----------------------------------------------------------


def test_gmail_deeplink_prefers_thread_then_message() -> None:
    assert p.gmail_deeplink(thread_id="t1", message_id="m1").endswith("#all/t1")
    assert p.gmail_deeplink(message_id="m1").endswith("#all/m1")
    assert p.gmail_deeplink() is None
