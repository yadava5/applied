"""Unit tests for the pure cloud pipeline analytics (issue C7).

These cover the Gmail-free logic that runs over an accumulated set of
classified verdicts: company grouping (seeing through shared ATS relays),
category summarization, and the "no response — follow up" ghosting flag.
No network, no Gmail, no DB — just pure functions over plain data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

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


# --- #325: "<Role> @ <Company>" — the at-sign outranks the preposition -------
#
# The real subject from issue #166, quoted verbatim in the public issue. Both
# "application **to** …" and "… @ Together AI" claim to name the employer, and
# only one of them is right.
AT_SIGN_SUBJECT = (
    "Important information about your application to "
    "Systems Research Engineer, GPU Programming @ Together AI"
)


def test_at_sign_beats_the_preposition_for_the_same_subject() -> None:
    # Was "Research Engineer" — "Systems" eaten by _CORP_TAIL, the rest a job
    # title filed where a company belongs.
    assert p._employer_from_subject(AT_SIGN_SUBJECT, ats_relay=True) == "Together AI"
    assert p.resolve_employer("no-reply@us.greenhouse-mail.io", AT_SIGN_SUBJECT, None) == (
        "together",
        "Together AI",
    )
    # The at-sign must be the SUBJECT'S OWN tail, not a stray one mid-line.
    assert p._employer_from_subject("Role @ Acme — next steps", ats_relay=True) is None


def test_at_sign_is_read_only_for_ats_relays() -> None:
    # Off a relay the same shape is a time or a place, not an employer, and a
    # person's mail is where those occur. Both of these resolve to nothing.
    assert p.resolve_employer("friend@gmail.com", "Coffee @ Home", None) is None
    assert p.resolve_employer("friend@gmail.com", "Interview @ Noon", None) is None
    # Same function, same subject, relay flag off: the at-sign is not consulted,
    # so a subject whose ONLY employer signal is the at-sign names nobody. The
    # default is off, which is what keeps every non-relay caller unchanged.
    assert p._employer_from_subject("Backend Engineer @ Globex", ats_relay=True) == "Globex"
    assert p._employer_from_subject("Backend Engineer @ Globex", ats_relay=False) is None
    assert p._employer_from_subject("Backend Engineer @ Globex") is None


def test_at_sign_refuses_an_email_address() -> None:
    # A dot followed by letters is a hostname, not a company.
    assert p._employer_from_subject("Update @ Careers.Acme.com", ats_relay=True) is None
    assert p.resolve_employer("no-reply@ashbyhq.com", "Reply to ayush@together.ai", None) is None
    # ...and refusing FALLS THROUGH rather than returning None outright, so the
    # anchored pattern still gets its turn.
    assert (
        p._employer_from_subject(
            "Your application to Acme, reply to jobs@Careers.Acme.com", ats_relay=True
        )
        == "Acme"
    )


def test_subjects_without_an_at_sign_are_untouched() -> None:
    # The whole corpus is this shape — 52 of 52 stored production subjects hold
    # no at-sign — so the anchored pattern still decides all of them.
    assert p._employer_from_subject("Your application to Stripe", ats_relay=True) == "Stripe"
    assert (
        p._employer_from_subject("Thank you for applying to Together AI", ats_relay=True)
        == "Together AI"
    )


def test_the_two_cases_this_rule_still_gets_wrong() -> None:
    """Characterisation, deliberately — both are argued in ``_employer_from_subject``.

    Pinned so the next person to widen this reads the reasoning instead of
    discovering the trade-off by accident. Either line going green is a real
    improvement and wants this test rewritten, not deleted.
    """
    # 1. No at-sign, so nothing separates the role from a company: the
    #    preposition's object wins and it is a job title.
    #
    #    The SPELLING of that wrong answer changed with #532 and the answer did
    #    not. It read "Research Engineer" while `_clean_company_display` ran an
    #    unanchored `_CORP_TAIL`, which deleted the leading "Systems" — so the
    #    rule was wrong AND was hiding a word. It is still a job title, which is
    #    the thing this line pins; nothing here has gone green.
    assert (
        p._employer_from_subject("Your application to Systems Research Engineer", ats_relay=True)
        == "Systems Research Engineer"
    )
    # 2. The at-sign path does not ask whether it just named the COURIER.
    assert (
        p._employer_from_subject("Your application to Acme @ Greenhouse", ats_relay=True)
        == "Greenhouse"
    )


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


# --- resolve_employer: the four REAL production sender/subject pairs ----------
#
# These are the exact senders + subjects sitting in the owner's production
# ``emails`` table. Three already resolved; the fourth ("Crusoe | Application
# Received") did not, and a user classifying it created NOTHING while the API
# reported success. Pinned here as a set so a future precision tweak cannot
# regress one while fixing another.

PRODUCTION_ATS_PAIRS = [
    (
        "no-reply@us.greenhouse-mail.io",
        "Thank you for applying to Anthropic",
        None,
        ("anthropic", "Anthropic"),
    ),
    (
        "no-reply@ashbyhq.com",
        "Thank you for applying with MotherDuck!",
        "Team Talent @ MotherDuck",
        ("motherduck", "MotherDuck"),
    ),
    (
        "no-reply@ashbyhq.com",
        "Thanks for applying to Supabase 🚀",
        "Supabase Hiring Team",
        ("supabase", "Supabase"),
    ),
    (
        "no-reply@ashbyhq.com",
        "Crusoe | Application Received",
        "Crusoe Hiring Team",
        ("crusoe", "Crusoe"),
    ),
]


@pytest.mark.parametrize(
    ("sender_email", "subject", "sender_name", "expected"), PRODUCTION_ATS_PAIRS
)
def test_resolve_employer_names_every_real_production_ats_mail(
    sender_email: str, subject: str, sender_name: str | None, expected: tuple[str, str]
) -> None:
    assert p.resolve_employer(sender_email, subject, sender_name) == expected


def test_resolve_employer_falls_back_to_ats_sender_display_name() -> None:
    # Role-ish TAIL words are stripped, one pass per word.
    assert p.resolve_employer("no-reply@ashbyhq.com", "Application update", "Crusoe Hiring Team") == (
        "crusoe",
        "Crusoe",
    )
    assert p.resolve_employer("no-reply@ashbyhq.com", "Application update", "Acme Talent Acquisition") == (
        "acme",
        "Acme",
    )
    # "<something> @ <Company>" — the company follows the at-sign.
    assert p.resolve_employer("no-reply@ashbyhq.com", "Application update", "Team Talent @ MotherDuck") == (
        "motherduck",
        "MotherDuck",
    )
    assert p.resolve_employer("no-reply@lever.co", "We received your submission", "Initech Recruiting") == (
        "initech",
        "Initech",
    )


def test_resolve_employer_falls_back_to_subject_lead_segment() -> None:
    # "<Company> | <anything>" and "<Company> - <anything>" — the ATS subject
    # shape with no at/with/to connective for the anchored pattern to use.
    assert p.resolve_employer("no-reply@ashbyhq.com", "Crusoe | Application Received", None) == (
        "crusoe",
        "Crusoe",
    )
    assert p.resolve_employer("no-reply@ashbyhq.com", "Globex — Interview scheduled", None) == (
        "globex",
        "Globex",
    )
    # A separator that is NOT the leading segment cannot invent a company.
    assert p.resolve_employer("no-reply@ashbyhq.com", "Re: your note | thanks", None) is None


def test_resolve_employer_fallbacks_never_name_a_relay_or_a_person() -> None:
    # The courier is not the company — neither by relay vocabulary...
    assert p.resolve_employer("alerts@mail.joinhandshake.com", "New jobs for you", "Handshake") is None
    # ...nor by the actual sending brand ("Ashby" for ashbyhq.com).
    assert p.resolve_employer("no-reply@ashbyhq.com", "Application update", "Ashby") is None
    # A display name that is really an address names the relay, not an employer.
    assert (
        p.resolve_employer("no-reply@ashbyhq.com", "Application Received", "no-reply@ashbyhq.com")
        is None
    )
    # Consumer webmail is excluded from the name fallback entirely: a display
    # name there is a PERSON. This is the "Julee Johnson → OFFERED" row.
    assert p.resolve_employer("julee.johnson@gmail.com", "You have an offer", "Julee Johnson") is None
    # A .edu never reaches the fallbacks (it fails the corporate test, and is
    # not an ATS relay), so a university display name still yields nothing.
    assert p.resolve_employer("noreply@miamioh.edu", "Online Onboarding", "Miami OH") is None


def test_relay_domain_sets_partition_without_drift() -> None:
    # RELAY_DOMAINS is composed from the three subsets, so a domain can never be
    # in the "never an employer" list yet missing from all of them. The third
    # subset is #687's: assessment vendors relay ONE employer's mail per message
    # the way an ATS does, but they are not an ATS and only one of the two earns
    # the display-name and subject-lead fallbacks.
    assert p.RELAY_DOMAINS == (
        p.ATS_RELAY_DOMAINS | p.ASSESSMENT_RELAY_DOMAINS | p.CONSUMER_WEBMAIL_DOMAINS
    )
    # Pairwise disjoint, all three ways. Kept as three assertions rather than a
    # length sum so a failure names WHICH pair drifted.
    assert not (p.ATS_RELAY_DOMAINS & p.CONSUMER_WEBMAIL_DOMAINS)
    assert not (p.ATS_RELAY_DOMAINS & p.ASSESSMENT_RELAY_DOMAINS)
    assert not (p.ASSESSMENT_RELAY_DOMAINS & p.CONSUMER_WEBMAIL_DOMAINS)
    assert "ashbyhq" in p.ATS_RELAY_DOMAINS and "ashbyhq" in p.RELAY_DOMAINS
    assert "gmail" in p.CONSUMER_WEBMAIL_DOMAINS and "gmail" in p.RELAY_DOMAINS
    assert "coderbyte" in p.ASSESSMENT_RELAY_DOMAINS and "coderbyte" in p.RELAY_DOMAINS
    # ...and an assessment vendor is NOT an ATS relay, which is what keeps steps
    # 3 and 4 of `resolve_employer` off it.
    assert "coderbyte" not in p.ATS_RELAY_DOMAINS


def test_employer_from_text_validates_a_user_supplied_company() -> None:
    assert p.employer_from_text("Crusoe") == ("crusoe", "Crusoe")
    assert p.employer_from_text("  Globex Inc. ") == ("globex", "Globex")
    # A blank or stopword-only string still cannot manufacture a row.
    assert p.employer_from_text("") is None
    assert p.employer_from_text(None) is None
    assert p.employer_from_text("the") is None
    assert p.employer_from_text("Careers") is None


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


# --- one ATS thread, several applications (#454) ------------------------------

#: Thread ``19ff36237eef1ef3`` of the owner's mailbox, read 2026-08-22. Five
#: Greenhouse acknowledgements for FOUR Verkada roles, all under one subject
#: from one no-reply address, which is why Gmail threaded them. Snippets are
#: Gmail's own, verbatim; only the message ids are the real ones too.
_VERKADA_THREAD = (
    ("19ff36237eef1ef3", "Backend Engineer, Alarms"),
    ("19ff39a08b3bc051", "Frontend Engineer - Access Control"),
    ("19ff39afaed0fc1d", "Backend Engineer - Connectivity"),
    ("19ff3c8bf80031ab", "Backend Engineer, Alarms"),
    ("19ff3c8c90a8650d", "Embedded Software Engineer, Access Control"),
)


def _verkada(mid: str, role: str, minute: int) -> p.PipelineItem:
    """One message of that thread, scored UNDER the auto-file gate.

    Under the gate on purpose: the queue is the path being tested, and mail that
    clears the gate never reaches it. The corpus family ``one-thread-many-roles``
    covers the confident half and cannot red on this — every one of its messages
    files a card and skips ``collect_review_items`` entirely.
    """

    return p.PipelineItem(
        message_id=mid,
        category="applied",
        sender_email="no-reply@us.greenhouse-mail.io",
        sender_name="Verkada",
        subject="Thank you for applying to Verkada",
        snippet=(
            f"Hi Ayush, Thank you so much for applying to the {role} role at "
            "Verkada! We are always looking for great talent and we are excited "
            "to receive your application. We will review it as"
        ),
        received_at=NOW - timedelta(minutes=minute),
        confidence=0.78,
        thread_id="19ff36237eef1ef3",
    )


def test_one_ats_thread_asks_about_every_application_in_it() -> None:
    """Four applications share one Gmail thread; the queue must hold four.

    An ATS sends every acknowledgement for an employer under one subject from
    one address, and Gmail threads on subject plus sender. Keyed on the thread
    alone the queue held ONE entry and the other three applications reached no
    card, no queue and no counter.

    The duplicate is the other half of the assertion: two of the five messages
    name the same role, and they must still be ONE decision. Five messages,
    four entries — not five, and not one.
    """

    items = [
        _verkada(mid, role, minute)
        for minute, (mid, role) in enumerate(_VERKADA_THREAD)
    ]
    review = p.collect_review_items(items)

    roles = sorted(
        p.application_sub_key(r.subject, r.snippet) for r in review
    )
    assert roles == [
        "backend engineer alarms",
        "backend engineer connectivity",
        "embedded software engineer access control",
        "frontend engineer access control",
    ]
    assert len(review) == 4


def test_a_thread_naming_no_application_is_still_one_decision() -> None:
    """The control, and the case the thread key was added for.

    Emails 58 and 73 of thread ``19fed7e0706ee704`` — "Crusoe | Application
    Received", twice, with no body to extract a role from. Both sub-keys are
    ``None``, so widening the key by identity must not widen this: the owner is
    asked once, exactly as before #454.
    """

    def crusoe(mid: str, minute: int) -> p.PipelineItem:
        return p.PipelineItem(
            message_id=mid,
            category="applied",
            sender_email="no-reply@ashbyhq.com",
            sender_name="Crusoe",
            subject="Crusoe | Application Received",
            received_at=NOW - timedelta(minutes=minute),
            confidence=0.78,
            thread_id="19fed7e0706ee704",
        )

    review = p.collect_review_items(
        [crusoe("19fed7e0706ee704", 0), crusoe("19fedeb77e1accb3", 1)]
    )
    assert [r.message_id for r in review] == ["19fed7e0706ee704"]


def test_unthreaded_mail_is_keyed_by_message_and_never_by_role() -> None:
    """No thread id, no widening.

    Two employers, no threads, and mail that normalizes to the same role token.
    A ``(None, sub_key)`` key would make these one entry and lose an
    application; the bare ``message_id`` fallback cannot.
    """

    def loose(mid: str, company: str) -> p.PipelineItem:
        return p.PipelineItem(
            message_id=mid,
            category="applied",
            sender_email=f"careers@{company}.com",
            sender_name=company.title(),
            subject=f"Your application to {company.title()}",
            snippet=(
                "Thank you for applying to the Software Engineer role. We have "
                "received your application and will review it shortly."
            ),
            received_at=NOW,
            confidence=0.78,
        )

    review = p.collect_review_items([loose("m1", "acme"), loose("m2", "globex")])
    assert {r.message_id for r in review} == {"m1", "m2"}


def test_the_review_key_is_computed_from_the_text_that_is_stored() -> None:
    """A decision has to settle the row it was made about.

    The pipeline keys on ``PipelineItem.snippet``, which ``POST /gmail/sync``
    accepts up to 2000 characters. The row it becomes holds
    ``Email.body_snippet``, which is 500. Every later site — the queue endpoint,
    the summary tile, the sibling settle, the additive persist — recomputes the
    key from the STORED text, so a role sitting past character 500 gave one key
    at sync and a different one at settle: the row could never be settled and
    came back on every sync.

    Both directions are asserted. The short snippet is the control: truncating
    must not be a blanket "ignore the snippet", which would pass the first
    assertion by making every key ``(thread, None)``.
    """

    subject = "Thank you for applying to Verkada"
    filler = "We appreciate the time you invested in our process. " * 10
    late = f"Hi Ayush, {filler} We received your application for the Backend Engineer, Alarms role."
    assert len(late) > p.STORED_SNIPPET_CHARS

    def key(snippet: str):
        return p.review_dedup_key(
            message_id="m", thread_id="t", subject=subject, snippet=snippet
        )

    assert key(late) == key(late[: p.STORED_SNIPPET_CHARS])

    early = (
        "Hi Ayush, Thank you so much for applying to the Backend Engineer, "
        "Alarms role at Verkada! We will review it as soon as we can."
    )
    assert len(early) < p.STORED_SNIPPET_CHARS
    assert key(early) == ("t", "backend engineer alarms")


# --- gmail_deeplink ----------------------------------------------------------


def test_gmail_deeplink_prefers_thread_then_message() -> None:
    assert p.gmail_deeplink(thread_id="t1", message_id="m1").endswith("#all/t1")
    assert p.gmail_deeplink(message_id="m1").endswith("#all/m1")
    assert p.gmail_deeplink() is None


def test_gmail_deeplink_selects_connected_account_when_known() -> None:
    # Unknown account → positional /u/0/ (browser-default) fallback.
    assert (
        p.gmail_deeplink(thread_id="t1")
        == "https://mail.google.com/mail/u/0/#all/t1"
    )
    # Known account → authuser selector so the RIGHT mailbox opens, not /u/0/;
    # the address is URL-encoded and the #all/<ref> conversation is preserved.
    link = p.gmail_deeplink(thread_id="t1", account_email="reader@harbourgate.test")
    assert link == "https://mail.google.com/mail/?authuser=reader%40harbourgate.test#all/t1"
    assert "/u/0/" not in link


def test_retarget_gmail_deeplink_heals_stored_links() -> None:
    stored = "https://mail.google.com/mail/u/0/#all/t9"
    # Retarget a legacy /u/0/ link at the connected account, keeping the ref.
    assert (
        p.retarget_gmail_deeplink(stored, "a@b.com")
        == "https://mail.google.com/mail/?authuser=a%40b.com#all/t9"
    )
    # No account or non-Gmail / fragment-less urls pass through untouched.
    assert p.retarget_gmail_deeplink(stored, None) == stored
    assert p.retarget_gmail_deeplink("https://example.com/x", "a@b.com") == "https://example.com/x"
    assert p.retarget_gmail_deeplink(None, "a@b.com") is None


# --- datetime normalization (asyncpg naive-column safety) --------------------

from datetime import timezone as _tz  # noqa: E402


def test_to_naive_utc_strips_offset_and_converts_to_utc() -> None:
    # An AWARE datetime (as parsedate_to_datetime returns) → naive UTC.
    aware = datetime(2026, 7, 8, 20, 4, 21, tzinfo=_tz(timedelta(hours=-4)))
    naive = p.to_naive_utc(aware)
    assert naive is not None
    assert naive.tzinfo is None
    assert naive == datetime(2026, 7, 9, 0, 4, 21)  # -04:00 → +00:00 rolls the day
    # A naive datetime passes through untouched; None → None.
    already = datetime(2026, 7, 8, 20, 4, 21)
    assert p.to_naive_utc(already) is already
    assert p.to_naive_utc(None) is None


def test_rollup_and_review_emit_naive_datetimes_from_aware_input() -> None:
    # The pure layer must NEVER hand an aware datetime to the persistence layer,
    # or asyncpg's naive TIMESTAMP encoder raises (the prod 500). Mixed aware/
    # naive input must not raise on the min()/max() date reduction either.
    aware = datetime(2026, 7, 8, 20, 4, 21, tzinfo=_tz(timedelta(hours=-4)))
    naive = datetime(2026, 7, 1, 12, 0, 0)
    items = [
        p.PipelineItem(
            message_id="a1", category="applied", sender_email="careers@stripe.com",
            subject="Thanks for applying at Stripe", sender_name="Stripe",
            received_at=aware, confidence=0.95, thread_id="t1",
        ),
        p.PipelineItem(
            message_id="a2", category="interview", sender_email="careers@stripe.com",
            subject="Interview with Stripe", sender_name="Stripe",
            received_at=naive, confidence=0.9,
        ),
        p.PipelineItem(
            message_id="r1", category="interview", sender_email="talent@replit.com",
            subject="About your background", sender_name="Replit",
            received_at=aware, confidence=0.78,
        ),
    ]
    rolled = p.roll_up_applications(items)
    assert len(rolled) == 1
    r = rolled[0]
    assert r.applied_at is not None and r.applied_at.tzinfo is None
    assert r.last_activity is not None and r.last_activity.tzinfo is None
    for ref in r.messages:
        assert ref.received_at is None or ref.received_at.tzinfo is None

    review = p.collect_review_items(items)
    assert len(review) == 1
    assert review[0].received_at is not None and review[0].received_at.tzinfo is None


# --- ScanCoverage: what a bounded scan can honestly claim to have seen -------


def _scanned_item(message_id: str, received_at: datetime | None) -> p.PipelineItem:
    return p.PipelineItem(
        message_id=message_id,
        category="other",
        sender_email="news@example.com",
        subject="Newsletter",
        received_at=received_at,
    )


def test_scan_coverage_spans_only_what_the_scan_returned() -> None:
    from jobtracker.cloud.applications import ScanCoverage

    naive = datetime(2026, 5, 10, 9, 0, 0)
    coverage = ScanCoverage.from_items(
        [_scanned_item("m1", naive), _scanned_item("m2", naive + timedelta(days=5))]
    )
    assert coverage.message_ids == {"m1", "m2"}
    assert coverage.covers(naive) and coverage.covers(naive + timedelta(days=5))
    # Older than the oldest message the scan reached, and newer than its newest:
    # in both directions the scan simply did not get there.
    assert not coverage.covers(naive - timedelta(seconds=1))
    assert not coverage.covers(naive + timedelta(days=5, seconds=1))
    assert not coverage.covers(None)


def test_scan_coverage_compares_aware_and_naive_without_blowing_up() -> None:
    """A relayed aware timestamp vs a naive stored column must not raise.

    ``Email.received_at`` is TIMESTAMP WITHOUT TIME ZONE while a client relays
    ISO-8601 with an offset. Mixing the two in a comparison is a TypeError, and
    it would be raised in the middle of deciding what to remove.
    """

    from jobtracker.cloud.applications import ScanCoverage

    aware = datetime(2026, 5, 10, 20, 4, 21, tzinfo=UTC)
    coverage = ScanCoverage.from_items([_scanned_item("m1", aware)])
    assert coverage.oldest is not None and coverage.oldest.tzinfo is None
    assert coverage.covers(datetime(2026, 5, 10, 20, 4, 21))  # naive, same instant
    assert coverage.covers(aware)


def test_empty_scan_covers_nothing() -> None:
    from jobtracker.cloud.applications import ScanCoverage

    coverage = ScanCoverage.from_items([])
    assert coverage.message_ids == frozenset()
    assert not coverage.covers(datetime(2026, 5, 10, 9, 0, 0))


# --- _scan_contradicts: membership, not date containment --------------------
#
# ``_scan_contradicts`` only reads ``.message_id`` and ``.received_at`` off each
# row, so these drive it with plain stand-ins and keep this module DB-free.


class _StoredEmail:
    """The two fields ``_scan_contradicts`` reads off a linked Email row."""

    def __init__(self, message_id: str, received_at: datetime | None) -> None:
        self.message_id = message_id
        self.received_at = received_at


def test_a_message_the_scan_never_read_blocks_removal_even_inside_the_span() -> None:
    """Date containment is not membership — the 2026-08-10 deletion, in one call.

    The row has two messages: one the scan re-read and no longer files, one that
    was archived and so never appeared in the scan at all. Its date falls inside
    the span the scan reached, which is exactly what made span-containment say
    "covered" about a message nobody looked at.
    """

    from jobtracker.cloud.applications import ScanCoverage, _scan_contradicts

    coverage = ScanCoverage.from_items(
        [
            _scanned_item("m-inbox", datetime(2026, 5, 10, 9, 0, 0)),
            _scanned_item("m-other", datetime(2026, 5, 1, 9, 0, 0)),
        ]
    )
    emails = [
        _StoredEmail("m-inbox", datetime(2026, 5, 10, 9, 0, 0)),
        _StoredEmail("m-archived", datetime(2026, 5, 5, 9, 0, 0)),  # never read
    ]
    assert coverage.covers(emails[1].received_at)  # the old test said "covered"
    assert _scan_contradicts(emails, coverage) is False


def test_a_scan_that_re_read_every_message_of_a_row_does_contradict_it() -> None:
    """The counterpart that keeps the rule above honest: full re-reading purges."""

    from jobtracker.cloud.applications import ScanCoverage, _scan_contradicts

    coverage = ScanCoverage.from_items(
        [
            _scanned_item("m-inbox", datetime(2026, 5, 10, 9, 0, 0)),
            _scanned_item("m-archived", datetime(2026, 5, 5, 9, 0, 0)),
        ]
    )
    emails = [
        _StoredEmail("m-inbox", datetime(2026, 5, 10, 9, 0, 0)),
        _StoredEmail("m-archived", datetime(2026, 5, 5, 9, 0, 0)),
    ]
    assert _scan_contradicts(emails, coverage) is True


def test_span_still_blocks_a_removal_when_the_scans_copy_had_no_date() -> None:
    """Why the span test survives id-membership: it is the stricter of the two.

    An undated message (an unparseable ``Date`` header) contributes its id to
    the coverage but nothing to the span, so a row whose stored date predates
    everything the scan dated is outside the span even though its id was read.
    Membership alone would remove it; the span clause keeps it, and keeping a
    row is the safe direction.
    """

    from jobtracker.cloud.applications import ScanCoverage, _scan_contradicts

    coverage = ScanCoverage.from_items(
        [
            _scanned_item("m1", None),  # re-read, but Gmail's Date was unusable
            _scanned_item("m2", datetime(2026, 5, 10, 9, 0, 0)),
        ]
    )
    assert coverage.message_ids == {"m1", "m2"}
    emails = [_StoredEmail("m1", datetime(2026, 5, 1, 9, 0, 0))]
    assert _scan_contradicts(emails, coverage) is False
