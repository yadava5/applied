"""
Rule-Based Email Classifier (Layer 1)
=====================================

Pattern matching with weighted scoring for job application emails.
This is the first layer of classification - works on Day 1 without training data.

Scoring system:
- Strong patterns: +3 points (highly specific phrases)
- Weak patterns: +1 point (suggestive but ambiguous)
- Negative patterns: -5 points (contradicting phrases)
- Subject patterns: 2x weight (subjects are more predictable)
- ATS sender domains: bonus confidence

The category with highest score wins. Confidence is based on margin and match strength.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from jobtracker.database.models import EmailCategory

logger = logging.getLogger(__name__)


# =============================================================================
# Pattern Definitions
# =============================================================================


@dataclass
class CategoryPatterns:
    """Pattern definitions for a single category."""

    strong: list[str] = field(default_factory=list)  # +3 points
    weak: list[str] = field(default_factory=list)  # +1 point
    negative: list[str] = field(default_factory=list)  # -5 points


# Pattern definitions for each category
PATTERNS: dict[EmailCategory, CategoryPatterns] = {
    EmailCategory.REJECTION: CategoryPatterns(
        strong=[
            r"unfortunately.{0,50}(not|won't|will not|unable)",
            r"regret to inform",
            r"decided not to proceed",
            r"not (be )?(moving|proceeding) forward",
            r"move(d)? forward with other candidates",
            r"position has been filled",
            r"(role|position).{0,20}(closed|filled)",
            r"decision on (your |my )?candidacy",
            r"not (been )?selected.{0,30}(position|role|interview)",
            r"will not be moving forward.{0,30}(application|candidacy)",
            r"not (be )?able to offer.{0,20}(position|role|interview)",
            r"decided to pursue other candidates",
            r"chosen to move forward with another candidate",
            r"after careful (consideration|review).{0,30}(not|decided|unfortunately)",
            r"we('ve| have) decided to go in (a )?different direction",
            r"wish you (the best|well|success) in your (job )?search",
            r"encourage you to apply (for )?future.{0,20}(position|role|opening)",
            r"keep your (resume|application) on file",
            r"won't be advancing.{0,20}(application|candidacy)",
            r"not a (good )?fit.{0,20}(at this time|for this role)",
            r"not.{0,20}moving forward.{0,20}(application|your candidacy)",
        ],
        weak=[
            r"competitive (applicant )?(pool|field)",
            r"many qualified (candidates|applicants)",
            r"difficult decision",
        ],
        negative=[
            r"schedule.{0,20}interview",
            r"excited to (meet|speak)",
            r"offer (you|letter|of employment)",
            r"looking forward to speaking",
            r"thank you for applying",
            r"application.{0,20}received",
            r"\b(unsubscribe|manage preferences|newsletter|digest)\b",
            r"\b(discount|promo(?:tion)?|coupon|sale|limited time offer)\b",
            r"\b(order|purchase|shipment|tracking number)\b",
            r"\b(security alert|verification code|otp|one[- ]time (passcode|password|code)|sign[- ]in|login)\b",
        ],
    ),
    EmailCategory.INTERVIEW: CategoryPatterns(
        strong=[
            r"schedule.{0,20}interview",
            r"interview invitation",
            r"interview.{0,20}(scheduling|schedule|request|invitation)",
            r"(would |)like to (schedule|set up|arrange).{0,20}(call|meeting|interview|chat).{0,30}(with you|discuss)",
            r"meet (the )?(hiring )?team",
            r"phone screen.{0,20}(schedule|availability|available|call)",
            r"video (call|interview).{0,20}(schedule|discuss|talk)",
            r"calendly.{0,20}(link|schedule|book)",
            r"zoom (meeting|link|call).{0,20}(discuss|interview)",
            r"discuss.{0,30}(your candidacy|the role|the position|next steps)",
            r"technical (interview|round|screen)",
            r"onsite (interview|visit)",
            r"panel interview",
            r"hiring manager.{0,30}(speak|meet|call|would like)",
            r"recruiter.{0,20}(call|chat|speak).{0,20}(with you|to discuss)",
            r"(your |)availability.{0,30}(for an?|to) (meeting|call|interview)",
            r"please.{0,20}(book|schedule|pick).{0,20}time.{0,20}(interview|call|meet)",
            r"invite you to.{0,20}interview",
            r"interviewing.{0,20}candidates",
        ],
        weak=[
            r"looking forward to (speaking|meeting|connecting) with you",
            r"learn more about (you|your background|your experience)",
            r"excited (about|to discuss).{0,20}(candidacy|application)",
            r"next step.{0,20}interview",
        ],
        negative=[
            r"unfortunately",
            r"regret to inform",
            r"not (be )?(moving|proceeding) forward",
            r"decided not to",
            r"position (has been )?filled",
            r"application was sent",
            r"application.{0,20}received",
            r"thank you for applying",
            r"congratulations on completing",
            r"your course",
            r"trial.{0,20}(ended|ends|started)",
            r"free trial",
            r"premium features",
            r"next steps.{0,20}hear from us",
            r"your application for\s+.+\s+at\s+[A-Z]",
            r"your application to\s+.+\s+at\s+[A-Z]",
        ],
    ),
    EmailCategory.OFFER: CategoryPatterns(
        strong=[
            r"pleased to (offer|extend).{0,30}(position|role|job)",
            r"offer (you the|letter|of employment)",
            r"extend.{0,20}(job |employment )?offer",
            r"congratulations.{0,30}(job )?offer",
            r"formal (job )?offer",
            r"compensation package.{0,50}(details?|salary|annual)",
            r"(annual|base) salary.{0,20}\$?\d+",
            r"your.{0,20}start date.{0,20}(will be|is)",
            r"accept (this|the|our) (job )?offer",
            r"sign(ing)? bonus.{0,20}\$?\d+",
            r"stock options.{0,30}(vest|grant)",
            r"employment (agreement|contract|offer)",
            r"contingent upon.{0,30}background",
            r"offer (letter |)expires",
            r"please (confirm|accept|sign).{0,30}offer",
            r"offer.{0,30}(position|role) of",
        ],
        weak=[
            r"excited to have you.{0,20}(join|team)",
            r"welcome.{0,10}(to the |)(team|company|aboard)",
            r"joining.{0,20}(our |the )team",
            r"look forward to (you |)(working|joining|starting)",
        ],
        negative=[
            r"unfortunately",
            r"regret to inform",
            r"not (at this time|selected)",
            r"interview",
            r"schedule.{0,20}call",
            r"thank you for applying",
            r"application.{0,20}received",
            r"open.{0,20}account",
            r"premium.{0,20}(free|gift)",
            r"discount|promo|sale|off\b",
            r"subscribe|unsubscribe",
            r"newsletter",
        ],
    ),
    EmailCategory.APPLIED: CategoryPatterns(
        strong=[
            r"application.{0,20}received",
            r"application complete",
            r"thank(s| you) for applying",
            r"successfully submitted",
            r"confirm(ing)? receipt",
            r"application.{0,30}has been (received|submitted)",
            r"we (have |'ve )received your application",
            r"we received your (job )?application",
            r"application (is|has been) (under|in) review",
            r"reviewing (applications|candidates)",
            r"be in touch (soon|shortly|if)",
            r"next steps.{0,30}hear from us",
            r"application.{0,20}(for|to).{0,40}(position|role|job)",
            r"applied.{0,20}(for|to).{0,40}(position|role|job)",
            r"thank you for your interest.{0,40}(position|role|career)",
            r"application was sent to",
            r"your application for\s+.+\s+at\s+[A-Z]",
            r"your application to\s+.+\s+at\s+[A-Z]",
            r"application.{0,20}is in",
        ],
        weak=[
            r"thank you for your interest",
            r"interested in.{0,30}(position|role|opportunity)",
            r"review your (application|resume|qualifications)",
            r"hearing from us",
            r"reach out.{0,20}updates",
        ],
        negative=[
            r"unfortunately",
            r"pleased to offer",
            r"schedule.{0,20}interview",
            r"regret",
            r"not (moving|proceeding)",
            r"move(d)? forward with other",
            r"congratulations on completing",
            r"your course",
            r"\b(unsubscribe|manage preferences|newsletter|digest)\b",
            r"\b(discount|promo(?:tion)?|coupon|sale|limited time offer|flash sale)\b",
            r"\b(shop|buy|cart|checkout|order|purchase|shipment|tracking number)\b",
            r"\b(security alert|verification code|otp|one[- ]time (passcode|password|code)|sign[- ]in|login)\b",
        ],
    ),
    EmailCategory.PENDING_APPLICATION: CategoryPatterns(
        strong=[
            r"complete your application",
            r"finish your application",
            r"continue your application",
            r"application.{0,20}(incomplete|not complete)",
            r"your application is incomplete",
            r"action required.{0,30}(application|submit)",
            r"complete additional steps",
            r"additional information.{0,20}(required|needed)",
            r"please complete.{0,30}(application|profile)",
            r"submit your application to be considered",
            r"before we can review your application",
        ],
        weak=[
            r"missing information",
            r"update your application",
            r"continue where you left off",
            r"application deadline.{0,20}(approaching|soon)",
        ],
        negative=[
            r"application.{0,20}received",
            r"thank(s| you) for applying",
            r"interview invitation",
            r"pleased to offer",
            r"regret to inform",
            r"not moving forward",
        ],
    ),
    EmailCategory.ASSESSMENT: CategoryPatterns(
        strong=[
            r"(technical|coding|take.?home).{0,20}(assessment|challenge|test|exercise)",
            r"complete.{0,30}(assessment|challenge|test)",
            r"hackerrank",
            r"codility",
            r"codesignal",
            r"leetcode",
            r"take.?home (assignment|project|exercise)",
            r"coding (exercise|test|challenge)",
            r"online (assessment|test)",
            r"skills (assessment|test)",
            r"deadline.{0,30}(assessment|test|challenge)",
            r"time limit.{0,20}(hour|minute)",
        ],
        weak=[
            r"next step.{0,30}(assessment|test)",
            r"assessment follow-?up",
            r"complete.{0,30}next",
            r"evaluation",
            r"demonstrate.{0,20}skills",
        ],
        negative=[
            r"unfortunately",
            r"regret",
            r"offer",
            r"not (moving|proceeding)",
        ],
    ),
    EmailCategory.FOLLOW_UP: CategoryPatterns(
        strong=[
            r"following up.{0,30}(application|interview|position|role)",
            r"follow-?up",
            r"check(ing)? in.{0,30}(application|status|interview)",
            r"any update(s)?.{0,20}(application|interview|position)",
            r"status (of|on).{0,20}(your |my )application",
            r"wanted to (follow up|check in).{0,30}(application|interview|candidacy|position|role)",
            r"reach(ing)? out.{0,30}(application |interview )?(status|update)",
            r"wondering.{0,30}(application|interview).{0,20}(status|update|progress)",
        ],
        weak=[
            r"circling back.{0,30}(application|interview|position|role)",
        ],
        negative=[
            r"unfortunately",
            r"offer",
            r"schedule.{0,20}interview",
            r"regret",
            r"application.{0,20}received",
            r"\b(unsubscribe|manage preferences|newsletter|digest)\b",
            r"\b(discount|promo(?:tion)?|coupon|sale|limited time offer|flash sale)\b",
            r"\b(order|purchase|shipment|tracking number)\b",
            r"\b(security alert|verification code|otp|one[- ]time (passcode|password|code)|sign[- ]in|login)\b",
        ],
    ),
}

# Known ATS (Applicant Tracking System) sender domains
ATS_DOMAINS = [
    "greenhouse.io",
    "lever.co",
    "myworkday.com",
    "workday.com",
    "icims.com",
    "jobvite.com",
    "smartrecruiters.com",
    "taleo.net",
    "successfactors.com",
    "breezy.hr",
    "ashbyhq.com",
    "applytojob.com",
    "hire.com",
    "recruitee.com",
]


# =============================================================================
# Rule-Based Classifier
# =============================================================================


@dataclass
class RuleClassificationResult:
    """Result from rule-based classification."""

    category: EmailCategory
    confidence: float
    matched_patterns: list[str]
    scores: dict[str, int]  # Category -> score


class RulesClassifier:
    """
    Rule-based email classifier using pattern matching.

    Uses weighted scoring:
    - Strong pattern match: +3
    - Weak pattern match: +1
    - Negative pattern match: -5
    - Subject patterns: 2x weight

    Confidence is calculated based on:
    - The winning category's score
    - The margin over the second-best category
    - Whether any strong patterns matched
    """

    def __init__(self):
        # Compile all patterns for efficiency
        self._compiled_patterns: dict[EmailCategory, dict[str, list[re.Pattern]]] = {}

        for category, patterns in PATTERNS.items():
            self._compiled_patterns[category] = {
                "strong": [re.compile(p, re.IGNORECASE) for p in patterns.strong],
                "weak": [re.compile(p, re.IGNORECASE) for p in patterns.weak],
                "negative": [re.compile(p, re.IGNORECASE) for p in patterns.negative],
            }

        logger.info(f"RulesClassifier initialized with {len(PATTERNS)} categories")

    def classify(
        self,
        subject: str,
        body: str,
        sender_email: Optional[str] = None,
    ) -> RuleClassificationResult:
        """
        Classify an email using pattern matching.

        Args:
            subject: Email subject line
            body: Email body text
            sender_email: Sender email address (for ATS detection)

        Returns:
            RuleClassificationResult with category, confidence, and details
        """
        scores: dict[str, int] = {cat.value: 0 for cat in EmailCategory}
        matched_patterns: list[str] = []

        # Check if sender is from a known ATS domain
        is_ats_email = False
        if sender_email:
            sender_domain = sender_email.lower().split("@")[-1] if "@" in sender_email else ""
            is_ats_email = any(ats in sender_domain for ats in ATS_DOMAINS)

        # Score each category
        for category, compiled in self._compiled_patterns.items():
            category_score = 0
            category_matches: list[str] = []

            # Check strong patterns (+3, 2x for subject)
            for pattern in compiled["strong"]:
                if pattern.search(subject):
                    category_score += 6  # 3 * 2 for subject
                    category_matches.append(f"[STRONG-SUBJECT] {pattern.pattern}")
                elif pattern.search(body):
                    category_score += 3
                    category_matches.append(f"[STRONG] {pattern.pattern}")

            # Check weak patterns (+1, 2x for subject)
            for pattern in compiled["weak"]:
                if pattern.search(subject):
                    category_score += 2  # 1 * 2 for subject
                    category_matches.append(f"[WEAK-SUBJECT] {pattern.pattern}")
                elif pattern.search(body):
                    category_score += 1
                    category_matches.append(f"[WEAK] {pattern.pattern}")

            # Check negative patterns (-5)
            for pattern in compiled["negative"]:
                if pattern.search(subject) or pattern.search(body):
                    category_score -= 5
                    category_matches.append(f"[NEGATIVE] {pattern.pattern}")

            scores[category.value] = category_score
            if category_matches:
                matched_patterns.extend(category_matches)

        # Find winner
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        winner_name, winner_score = sorted_scores[0]
        runner_up_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0

        # Default to 'other' if no strong signal
        if winner_score <= 0:
            return RuleClassificationResult(
                category=EmailCategory.OTHER,
                confidence=0.5,
                matched_patterns=matched_patterns,
                scores=scores,
            )

        # Calculate confidence
        margin = winner_score - runner_up_score
        has_strong_match = any("[STRONG" in p for p in matched_patterns if winner_name in str(p).lower() or True)

        # Base confidence on score and margin
        if winner_score >= 10 and margin >= 5:
            confidence = 0.95
        elif winner_score >= 6 and margin >= 3:
            confidence = 0.90
        elif winner_score >= 4 and margin >= 2:
            confidence = 0.80
        elif winner_score >= 2 and margin >= 1:
            confidence = 0.70
        else:
            confidence = 0.60

        # Boost confidence for ATS emails
        if is_ats_email and winner_name in ["applied", "rejection", "interview", "offer"]:
            confidence = min(confidence + 0.05, 0.95)

        return RuleClassificationResult(
            category=EmailCategory(winner_name),
            confidence=confidence,
            matched_patterns=matched_patterns,
            scores=scores,
        )


# =============================================================================
# Singleton Instance
# =============================================================================

_classifier: Optional[RulesClassifier] = None


def get_rules_classifier() -> RulesClassifier:
    """Get singleton rules classifier instance."""
    global _classifier
    if _classifier is None:
        _classifier = RulesClassifier()
    return _classifier
