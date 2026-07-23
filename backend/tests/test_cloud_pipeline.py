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
) -> p.PipelineItem:
    received = None if days_ago is None else NOW - timedelta(days=days_ago)
    return p.PipelineItem(
        message_id=mid,
        category=category,
        sender_email=company_email,
        subject=subject,
        sender_name=name,
        received_at=received,
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
