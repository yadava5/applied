"""The assessment noun, on its own.

Every ASSESSMENT pattern used to require a verb pairing ("complete your
assessment") or a qualifier ("online assessment", "technical assessment"). Real
mail does not oblige. ``[Action Required] Your Roblox Assessments Invitation``
— an actual message in the owner's inbox — matched nothing at all and was
filed as ``other`` at 0.50, which on this product means the application never
moved to INTERVIEWING.

The negative half of this file is the part that earns its keep. Two groups,
kept apart on purpose:

* ``NOT_ASSESSMENT_GUARDS_NEW_PATTERNS`` — subjects that collide with the
  noun-only patterns added alongside these tests. Without the veto list they
  would be new false positives, invented by the fix.
* ``NOT_ASSESSMENT_ALREADY_BROKEN`` — subjects that classified as
  ``assessment`` at 0.90 *before* any of this, via the pre-existing
  ``complete.{0,30}(assessment|challenge|test)`` pattern. Those are the ones
  that prove a -5 negative was never enough: a strong subject match is +6, so a
  negative leaves +1 and the category still wins.
* ``NOT_ASSESSMENT_MARKETING`` — content *about* assessments. Note what this
  group does not contain: newsletter and promo vocabulary, which belongs to the
  content guard one layer up and is tested there instead.

Assertions are on the category a user would see, plus the confidence band the
hybrid layer keys off (``>= 0.90`` is accepted immediately, hybrid.py:249) —
not on which regex fired, so the patterns stay free to be rewritten.
"""
from __future__ import annotations

import pytest

from jobtracker.classifier.rules import PATTERNS, RulesClassifier
from jobtracker.database.models import EmailCategory

# Instantiated directly rather than through get_rules_classifier(): the module
# singleton would make this file's behaviour depend on what ran before it.
CLASSIFIER = RulesClassifier()

# The subject that started this, byte for byte.
ROBLOX_SUBJECT = "[Action Required] Your Roblox Assessments Invitation"


IS_ASSESSMENT = [
    # --- the noun, with no verb to lean on ---------------------------------
    ROBLOX_SUBJECT,
    "Assessment Invitation",
    "Assessments Invitation",
    "your assessments are ready",
    "Assessment link",
    "Assessment reminder",
    "Assessment instructions",
    "Assessment deadline",
    "Invitation to Assessment - Software Engineer",
    "Invitation to your online assessment",
    # --- sibling nouns of the same category --------------------------------
    # take-home had the same shape: "take.?home (assignment|project|exercise)"
    # needed the following noun, so the bare form scored nothing.
    "Take-home for Backend Engineer",
    "Your take-home is ready",
    "Take-home round for the platform team",
    # HireVue was absent from the vendor list entirely, unlike HackerRank,
    # Codility and CodeSignal.
    "HireVue invitation",
    "Complete your HireVue",
    # --- shapes that already worked; here so a rewrite cannot lose them -----
    "complete your assessment",
    "invitation to complete your assessment",
    "Complete your online assessment",
    "Take-home assignment for Backend Engineer",
    "Your coding challenge is ready",
    "Your HackerRank test",
    "Codility invitation",
    "CodeSignal invite",
    "Online test invitation",
    "Skills assessment pending",
]

NOT_ASSESSMENT_GUARDS_NEW_PATTERNS = [
    # Each of these collides with a noun-only pattern added above: the veto
    # list is the only thing keeping them out of the category.
    "Risk assessment reminder",
    "Needs assessment link",
    "Impact assessment deadline",
    "Performance assessment invitation",
    "Self assessment reminder",
    "Self-assessment reminder",
    "Assessment of damages in your claim",
    "Your take-home pay is changing",
]

NOT_ASSESSMENT_ALREADY_BROKEN = [
    # Verified against the unmodified classifier on 2026-08-12: every one of
    # these returned assessment/0.90 before the veto list existed.
    "Complete your self-assessment before your review",
    "Please complete your annual performance assessment",
    "Complete the risk assessment for vendor onboarding",
    "Complete your needs assessment survey",
]

NOT_ASSESSMENT_MARKETING = [
    # Content *about* assessments rather than an invitation to sit one. Note
    # what is NOT in this list: "Newsletter: ...", "Weekly digest: ...". Those
    # are marketing vocabulary, which belongs to the content guard that runs
    # ahead of this layer — see test_marketing_guard_owns_newsletter_vocabulary.
    "Webinar: how to ace your online assessment",
    "Complete our assessment quiz",
    "Take our free assessment quiz and get 20% off",
    "Take home a free gift - 20% off today",
    "Vulnerability assessment results for your website",
]

# A real ATS invitation, footer and all. Bodies like this are why the veto list
# names no marketing vocabulary: vetoes match the body too.
ATS_INVITATION_BODY = (
    "You have been invited to complete an online assessment for the Backend "
    "Engineer role. The link expires in 72 hours.\n\n---\n"
    "You are receiving this because you subscribed to our newsletter. "
    "Manage preferences | Unsubscribe | View all jobs"
)


def test_production_subject_is_an_assessment() -> None:
    """The mail that was misfiled in production."""
    result = CLASSIFIER.classify(ROBLOX_SUBJECT, "", None)

    assert result.category is EmailCategory.ASSESSMENT
    # 0.90 is not cosmetic: below it HybridClassifier stops trusting the rules
    # layer outright and hands the mail to the semantic cascade.
    assert result.confidence >= 0.90


@pytest.mark.parametrize("subject", IS_ASSESSMENT)
def test_assessment_subjects_classify_as_assessment(subject: str) -> None:
    result = CLASSIFIER.classify(subject, "", None)

    assert result.category is EmailCategory.ASSESSMENT, result.scores
    assert result.confidence >= 0.90, result.scores


@pytest.mark.parametrize(
    "subject",
    NOT_ASSESSMENT_GUARDS_NEW_PATTERNS
    + NOT_ASSESSMENT_ALREADY_BROKEN
    + NOT_ASSESSMENT_MARKETING,
)
def test_non_hiring_senses_of_the_noun_are_not_assessments(subject: str) -> None:
    result = CLASSIFIER.classify(subject, "", None)

    assert result.category is not EmailCategory.ASSESSMENT, result.matched_patterns
    assert result.scores["assessment"] <= 0, result.matched_patterns


def test_veto_beats_a_strong_subject_match() -> None:
    """A -5 negative could not do this; that is why `veto` exists.

    "Complete your self-assessment" matches
    ``complete.{0,30}(assessment|challenge|test)`` in the SUBJECT, which is
    +6. Any negative pattern would leave +1 — still the winning score, still
    reported as `assessment`.
    """
    result = CLASSIFIER.classify("Complete your self-assessment", "", None)

    assert result.category is EmailCategory.OTHER
    assert result.scores["assessment"] == 0
    assert any(p.startswith("[VETO]") for p in result.matched_patterns)


def test_veto_only_lowers_a_score_it_never_raises_one() -> None:
    """The cap is ``min(score, 0)``, not ``= 0``.

    Raising an already-negative category to 0 would shrink the runner-up gap
    and quietly change the confidence of whichever category does win.
    """
    subject = "Unfortunately we regret to inform you"
    body = "Our risk assessment is complete."
    result = CLASSIFIER.classify(subject, body, None)

    assert result.scores["assessment"] < 0, result.matched_patterns


def test_veto_is_tagged_apart_from_negative() -> None:
    """hybrid.py reads the "[NEGATIVE]" tag to distrust the semantic layers.

    A veto says one category is wrong, not that the mail is non-job-related,
    so it must not be mistaken for a negative signal.
    """
    result = CLASSIFIER.classify("Risk assessment reminder", "", None)

    vetoes = [p for p in result.matched_patterns if p.startswith("[VETO]")]
    assert vetoes
    assert not any("[NEGATIVE]" in p for p in vetoes)


@pytest.mark.parametrize(
    "subject",
    [
        "Your HackerRank assessment for Backend Engineer",
        "Assessments Invitation",
        "Take-home for Backend Engineer",
    ],
)
def test_ats_footer_does_not_veto_a_real_invitation(subject: str) -> None:
    """The reverse of the bug being fixed, and the reason the veto list is short.

    Veto patterns are matched against the body as well as the subject. An
    assessment invitation from an ATS carries "unsubscribe", "manage
    preferences" and often "you subscribed to our newsletter" in its footer, so
    a veto on any of those words would suppress precisely the mail this
    category exists to catch.
    """
    result = CLASSIFIER.classify(subject, ATS_INVITATION_BODY, None)

    assert result.category is EmailCategory.ASSESSMENT, result.matched_patterns
    assert result.confidence >= 0.90


def test_marketing_guard_owns_newsletter_vocabulary() -> None:
    """Where the newsletter/marketing guard actually lives — not here.

    `hybrid.NON_APPLICATION_PATTERNS` already carries "newsletter", "weekly
    digest", "coupon", "flash sale", "limited time offer", "unsubscribe" and
    "manage preferences", and `_forced_other_reason` runs BEFORE the rules
    layer. It needs two such signals (or one plus a marketing sender), and a
    lifecycle phrase overrides it. Repeating that vocabulary in the assessment
    veto list — threshold of one, no override, body included — would be a
    second marketing guard that disagrees with the first.
    """
    from jobtracker.classifier.hybrid import HybridClassifier

    body = (
        "This week: how skills assessments are changing hiring, plus five roles "
        "we like.\nView all jobs | Unsubscribe | Manage preferences"
    )
    guard = HybridClassifier()._forced_other_reason(
        "Newsletter: 2026 skills assessment trends", body, None
    )

    assert guard == "digest_or_promotional_content"


def test_known_gap_content_guard_also_swallows_real_invitations() -> None:
    """CHARACTERISATION, not an endorsement. Measured 2026-08-12.

    The same content guard forces OTHER on a genuine assessment invitation
    whose body carries an ordinary ATS footer, because "unsubscribe" plus
    "manage preferences" is two marketing signals and
    `hybrid.LIFECYCLE_PATTERNS` rescues only `technical (assessment|challenge|
    test)` — not "online assessment", not "assessments invitation". So the noun
    fix in this file lands at the rules layer, and mail with two footer signals
    never reaches that layer.

    `mlruns/README.md` documents the same effect from the other direction.
    Deliberately NOT fixed here: the guard is shared by every category and
    widening `LIFECYCLE_PATTERNS` is a change to all of them, not to this one.
    """
    from jobtracker.classifier.hybrid import HybridClassifier

    guard = HybridClassifier()._forced_other_reason(
        "Assessments Invitation", ATS_INVITATION_BODY, None
    )

    assert guard == "digest_or_promotional_content"


def test_which_categories_declare_vetoes() -> None:
    """Blast radius, stated as an assertion.

    Every other category has an empty veto list, so its scoring is bit-for-bit
    what it was. Extending this is fine — being surprised by it is not.

    ``FOLLOW_UP`` joined on 2026-08-12: a stated hiring decision makes that
    category wrong, and a -5 negative could not out-vote a +6 subject match any
    more than it could here. See test_rules_classifier_rejection.py.
    """
    with_vetoes = {category for category, patterns in PATTERNS.items() if patterns.veto}

    assert with_vetoes == {EmailCategory.ASSESSMENT, EmailCategory.FOLLOW_UP}
