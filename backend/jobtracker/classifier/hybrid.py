"""
Hybrid Email Classifier
=======================

Combines all 3 classification layers:
1. Rules (regex patterns) - instant, catches obvious patterns
2. Embeddings (similarity) - catches variations of labeled examples
3. SetFit (few-shot ML) - fit offline on a labelled corpus, NOT on user
   corrections; see setfit_model.py's module header for the gate

Decision flow:
- High-confidence rule match (≥0.9) → accept immediately
- Embedding similarity match (≥0.85) → accept
- SetFit prediction (≥0.7) → accept
- Otherwise → return best guess with lower confidence

Confidence thresholds:
- ≥0.85: Auto-classify (no review needed)
- 0.70-0.84: Auto-classify but flag for review queue
- <0.70: Lower-confidence fallback (often `needs_review`)
"""

import logging
import re
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from jobtracker.config import settings
from jobtracker.database.models import EmailCategory

from .rules import domain_matches, get_rules_classifier, sender_domain

if TYPE_CHECKING:  # pragma: no cover - types only, never imported at runtime
    from .embeddings import EmbeddingsClassifier
    from .setfit_model import SetFitClassifier

logger = logging.getLogger(__name__)


# =============================================================================
# Content Guards
# =============================================================================

# Signals for digest/marketing style emails that should never become
# application lifecycle events.
NON_APPLICATION_PATTERNS = [
    r"\bjob alerts?\b",
    r"\brecommended jobs?\b",
    r"\bjobs? you may be interested in\b",
    r"\bnew jobs? for you\b",
    r"\bbased on your profile\b",
    r"\bview (all )?jobs?\b",
    r"\bunsubscribe\b",
    r"\bmanage preferences\b",
    r"\bweekly digest\b",
    r"\bdaily digest\b",
    r"\bnewsletter\b",
    r"\btop picks? for you\b",
    r"\bshop now\b",
    r"\bflash sale\b",
    r"\blimited time offer\b",
    r"\bcoupon\b",
    r"\byour order\b",
    r"\btracking number\b",
    r"\bsecurity alert\b",
    r"\bverification code\b",
    r"\bconfirmation code\b",
    r"\bone[- ]time (passcode|password|code)\b",
    r"\botp\b",
    r"\bsign[- ]in\b",
    r"\blogin\b",
    r"\baccount (alert|security|verification)\b",
    r"\bbank alert\b",
    r"\bstatement available\b",
    r"\btransaction alert\b",
    r"\breferral bonus\b",
    r"\btalent community\b",
]

# MAILBOX names, not domains — read them with ``_is_digest_mailbox`` below and
# not with ``rules.domain_matches``, which is for domains. Adding an entry here
# widens what gets forced to OTHER, so keep them the names a bulk sender
# actually puts in front of the ``@`` or uses as a mail subdomain.
NON_APPLICATION_SENDERS = [
    "jobalerts",
    "jobs-noreply",
    "alerts-noreply",
    "newsletter",
    "marketing",
    "promotions",
]

#: LinkedIn's own mail. Matched as a domain (``linkedin.com`` or any subdomain
#: of it), never as a substring of the address.
LINKEDIN_DOMAIN = "linkedin.com"

def _is_digest_mailbox(sender_email: Optional[str]) -> bool:
    """Does this address NAME one of the digest/marketing mailboxes?

    Anchored, and anchored differently from ``rules.domain_matches`` on
    purpose: ``NON_APPLICATION_SENDERS`` holds mailbox names, so a token counts
    when it is part of the local part (``jobalerts-noreply@acme.com``) or IS a
    whole label of the domain (``no-reply@marketing.acme.com``). It is not a
    domain list and parsing it as one would drop the first of those.

    It used to be ``token in sender_email`` — an arbitrary substring of the
    whole address, so any registrable domain could carry a token past the
    guard: ``hello@acme-newsletterhub.example`` read as a newsletter mailbox.
    Same defect class as the LinkedIn check below it, which is the one CodeQL
    ``py/incomplete-url-substring-sanitization`` noticed (alert 50); this one it
    did not. The stake is a classification, not an authorisation: the reachable
    harm is a crafted sender steering mail into or out of the digest bucket.

    Measured over the 185 distinct addresses in ``backend/`` and every sender
    the adversarial corpus generates, this answers identically to the old
    containment on all of them.
    """

    if not sender_email:
        return False
    lowered = sender_email.lower()
    local, _, domain = lowered.rpartition("@")
    if not local:  # no "@" at all: the whole value is the mailbox name
        local, domain = lowered, ""
    labels = [label for label in domain.split(".") if label]
    return any(
        token in local or token in labels for token in NON_APPLICATION_SENDERS
    )


LIFECYCLE_PATTERNS = [
    r"\bthank(?:s| you) for applying\b",
    r"\byour application\b",
    r"\bapplication (received|submitted)\b",
    r"\bregret to inform\b",
    r"\bunfortunately\b",
    r"\binterview\b",
    r"\bphone screen\b",
    r"\btechnical (assessment|challenge|test)\b",
    r"\boffer letter\b",
    r"\bcompensation package\b",
    r"\bposition has been filled\b",
]


# =============================================================================
# Classification Result
# =============================================================================


@dataclass
class ClassificationResult:
    """Result from hybrid classification."""

    category: EmailCategory
    confidence: float
    method: str  # "rules", "embeddings", "setfit", "fallback"
    needs_review: bool  # True if confidence < 0.85
    details: Optional[dict] = None


# =============================================================================
# Confidence Thresholds
# =============================================================================

#: THE ROUTING BOUNDARY, not a display threshold. At or above this the rules
#: layer's answer is returned immediately and neither SetFit nor embeddings is
#: consulted, so an edit that pushes an item over this line silently removes the
#: rest of the cascade from that item's decision (#775). It was the only one of
#: these three thresholds left as an inline literal, which is why the tests that
#: reason about it had to type it a second time -- and a number typed twice is a
#: number that can disagree with itself.
RULES_SHORT_CIRCUIT = 0.90

CONFIDENCE_AUTO = 0.85  # Auto-classify without review
CONFIDENCE_MIN_CLASSIFICATION = 0.70  # Minimum confidence to trust semantic layer output
# Below 0.85: Add to review queue


# =============================================================================
# Hybrid Classifier
# =============================================================================


class HybridClassifier:
    """
    3-layer hybrid email classifier.

    Usage:
        classifier = HybridClassifier()
        result = await classifier.classify(subject, body, sender_email)
        print(f"Category: {result.category.value}")
        print(f"Confidence: {result.confidence}")
        print(f"Method: {result.method}")
    """

    def __init__(self):
        self._rules = get_rules_classifier()
        # Embeddings (Layer 2) and SetFit (Layer 3) are loaded lazily via
        # the ``_embeddings`` / ``_setfit`` properties so the cloud import
        # graph never pays the torch / sentence-transformers / setfit cost.
        # See ``_load_embeddings`` and ``_load_setfit`` below.
        self._embeddings_instance: Optional["EmbeddingsClassifier"] = None
        self._setfit_instance: Optional["SetFitClassifier"] = None
        # Cloud deployment implies lite-mode (no SetFit, no embeddings)
        # regardless of the explicit ``lite_mode`` setting.
        self._lite_mode = settings.lite_mode or settings.deployment == "cloud"
        self._cloud_rules_only = settings.deployment == "cloud"
        self._non_application_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in NON_APPLICATION_PATTERNS
        ]
        self._lifecycle_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in LIFECYCLE_PATTERNS
        ]

    # ------------------------------------------------------------------
    # Lazy Layer Loaders
    # ------------------------------------------------------------------
    # Accessing ``self._embeddings`` or ``self._setfit`` triggers the
    # first-time import of the heavy submodule. On cloud deployments the
    # short-circuit in ``classify()`` returns before either property is
    # read, which is what keeps torch / sentence-transformers / setfit
    # out of ``sys.modules``.

    def _load_embeddings(self) -> "EmbeddingsClassifier":
        if self._embeddings_instance is None:
            # Local import — must stay inside the method body so that the
            # cloud import graph never imports ``embeddings`` (which pulls
            # ``numpy`` plus transitive sentence-transformers use sites).
            from .embeddings import get_embeddings_classifier

            self._embeddings_instance = get_embeddings_classifier()
        return self._embeddings_instance

    def _load_setfit(self) -> "SetFitClassifier":
        if self._setfit_instance is None:
            # Local import — must stay inside the method body so that the
            # cloud import graph never imports ``setfit_model``.
            from .setfit_model import get_setfit_classifier

            self._setfit_instance = get_setfit_classifier()
        return self._setfit_instance

    @property
    def _embeddings(self) -> "EmbeddingsClassifier":
        return self._load_embeddings()

    @_embeddings.setter
    def _embeddings(self, value: "EmbeddingsClassifier") -> None:
        # Allow tests / callers to swap in a fake embeddings instance.
        self._embeddings_instance = value

    @property
    def _setfit(self) -> "SetFitClassifier":
        return self._load_setfit()

    @_setfit.setter
    def _setfit(self, value: "SetFitClassifier") -> None:
        # Allow tests / callers to swap in a fake setfit instance.
        self._setfit_instance = value

    async def classify(
        self,
        subject: str,
        body: str,
        sender_email: Optional[str] = None,
    ) -> ClassificationResult:
        """
        Classify an email using the 3-layer hybrid approach.

        Args:
            subject: Email subject line
            body: Email body text (plain text preferred)
            sender_email: Sender email address (for ATS detection)

        Returns:
            ClassificationResult with category, confidence, and metadata
        """
        forced_other_reason = self._forced_other_reason(subject, body, sender_email)
        if forced_other_reason:
            logger.debug(
                "Content guard forced OTHER classification: reason=%s sender=%s subject=%s",
                forced_other_reason,
                sender_email,
                subject[:120],
            )
            return ClassificationResult(
                category=EmailCategory.OTHER,
                confidence=0.96,
                method="content_filter",
                needs_review=False,
                details={"reason": forced_other_reason},
            )

        # =====================================================================
        # Layer 1: Rule-Based Classification
        # =====================================================================
        rules_result = self._rules.classify(subject, body, sender_email)

        if rules_result.confidence >= RULES_SHORT_CIRCUIT:
            logger.debug(
                f"Rules classified as {rules_result.category.value} "
                f"with confidence {rules_result.confidence:.2f}"
            )
            return ClassificationResult(
                category=rules_result.category,
                confidence=rules_result.confidence,
                method="rules",
                needs_review=False,
                details={
                    "matched_patterns": rules_result.matched_patterns[:5],
                    "scores": rules_result.scores,
                },
            )

        # =====================================================================
        # Cloud Short-Circuit: Rules-Only Deployment
        # =====================================================================
        # On Vercel the classifier runs in a 50 MB / 60 s serverless slot,
        # so torch / sentence-transformers / setfit are neither bundled
        # nor importable. We must return after the rules layer — even if
        # rules were unsure — without touching ``self._embeddings`` or
        # ``self._setfit`` (whose property access would lazy-import the
        # heavy submodules). User-corrected labels still persist to
        # ``TrainingData`` and sync back to macOS where full SetFit
        # remains canonical.
        #
        # THIS RETURN IS ALSO WHAT MAKES THE ``OTHER`` -> ``NEEDS_REVIEW``
        # SAFETY NET AT THE BOTTOM OF THIS METHOD DEAD IN PRODUCTION. Removing
        # or narrowing this branch does not just re-enable the semantic layers,
        # it switches that net on for every message in a scan. Read #253 and
        # the note at the fallback block first; ``tests/test_safety_net_is_dead_253.py``
        # will stop you.
        if self._cloud_rules_only:
            # ``rules.py`` returns ``OTHER`` + 0.5 confidence when no
            # category scored above zero. Distinguish that "miss" case by
            # inspecting the raw category scores so cloud responses can
            # surface ``confidence=0.0`` for genuine rule misses.
            max_score = (
                max(rules_result.scores.values()) if rules_result.scores else 0
            )
            rules_miss = (
                rules_result.category == EmailCategory.OTHER and max_score <= 0
            )
            if rules_miss:
                return ClassificationResult(
                    category=EmailCategory.OTHER,
                    confidence=0.0,
                    method="rules",
                    needs_review=False,
                    details={
                        "matched_patterns": rules_result.matched_patterns[:5],
                        "scores": rules_result.scores,
                    },
                )
            return ClassificationResult(
                category=rules_result.category,
                confidence=rules_result.confidence,
                method="rules",
                needs_review=rules_result.confidence < CONFIDENCE_AUTO,
                details={
                    "matched_patterns": rules_result.matched_patterns[:5],
                    "scores": rules_result.scores,
                },
            )

        # =====================================================================
        # Layer 2: Embedding Similarity
        # =====================================================================
        # BUT: Don't trust embeddings if rules found strong negative signals
        # (e.g., marketing/promotional patterns that indicate NOT job-related)
        has_negative_signals = any(
            "[NEGATIVE]" in p for p in rules_result.matched_patterns
        )
        rules_says_other = rules_result.category == EmailCategory.OTHER
        has_lifecycle_content = any(
            pattern.search(f"{subject}\n{body}") for pattern in self._lifecycle_patterns
        )
        allow_semantic_override = not rules_says_other or has_lifecycle_content

        if (
            self._embeddings.is_available()
            and allow_semantic_override
            and not (has_negative_signals and rules_says_other)
        ):
            emb_result = await self._embeddings.classify(subject, body)

            if emb_result is not None:
                emb_category, emb_confidence = emb_result

                # Only trust embeddings if rules doesn't strongly disagree.
                #
                # The floor is the EMBEDDING classifier's own similarity
                # threshold, not the auto-file gate — the same number, a
                # different quantity. ``EmbeddingsClassifier.classify`` already
                # returns ``None`` below it (``find_most_similar`` does), so a
                # hand-written ``0.85`` here was tautologically true and, worse,
                # silently overrode the threshold the day someone lowered it.
                # Read it off the instance so lowering ``SIMILARITY_THRESHOLD``
                # actually takes effect. Do NOT bind this to ``CONFIDENCE_AUTO``:
                # that would make the ``needs_review=emb_confidence <
                # CONFIDENCE_AUTO`` three lines below dead by construction and
                # would drop every verdict in the review band instead of
                # queueing it.
                #
                # Import-safe despite the lazy-import rule in ``_load_embeddings``:
                # ``is_available()`` above already read the property on this
                # path, so the heavy submodule is loaded by the time we get here.
                if (
                    emb_confidence >= self._embeddings.SIMILARITY_THRESHOLD
                    and not has_negative_signals
                ):
                    if (
                        emb_category == EmailCategory.OTHER
                        and rules_result.category != EmailCategory.OTHER
                        and rules_result.confidence >= CONFIDENCE_MIN_CLASSIFICATION
                    ):
                        logger.debug(
                            "Ignoring embeddings OTHER override due to stronger rules signal"
                        )
                    elif emb_category in (
                        EmailCategory.APPLIED,
                        EmailCategory.PENDING_APPLICATION,
                    ) and not has_lifecycle_content:
                        logger.debug(
                            "Ignoring embeddings lifecycle prediction without lifecycle content"
                        )
                    elif self._forced_other_reason(subject, body, sender_email):
                        return ClassificationResult(
                            category=EmailCategory.OTHER,
                            confidence=0.95,
                            method="content_filter",
                            needs_review=False,
                            details={"reason": "embedding_blocked_by_content_guard"},
                        )
                    else:
                        logger.debug(
                            f"Embeddings classified as {emb_category.value} "
                            f"with confidence {emb_confidence:.2f}"
                        )
                        return ClassificationResult(
                            category=emb_category,
                            confidence=emb_confidence,
                            method="embeddings",
                            needs_review=emb_confidence < CONFIDENCE_AUTO,
                        )

        # =====================================================================
        # Layer 3: SetFit ML Model
        # =====================================================================
        if not self._lite_mode and self._setfit.is_available() and allow_semantic_override:
            setfit_result = self._setfit.classify(subject, body)

            if setfit_result is not None:
                sf_category, sf_confidence = setfit_result

                if sf_confidence >= CONFIDENCE_MIN_CLASSIFICATION:
                    if (
                        sf_category == EmailCategory.OTHER
                        and rules_result.category != EmailCategory.OTHER
                        and rules_result.confidence >= CONFIDENCE_MIN_CLASSIFICATION
                    ):
                        logger.debug(
                            "Ignoring SetFit OTHER override due to stronger rules signal"
                        )
                    elif sf_category in (
                        EmailCategory.APPLIED,
                        EmailCategory.PENDING_APPLICATION,
                    ) and not has_lifecycle_content:
                        logger.debug(
                            "Ignoring SetFit lifecycle prediction without lifecycle content"
                        )
                    elif self._forced_other_reason(subject, body, sender_email):
                        return ClassificationResult(
                            category=EmailCategory.OTHER,
                            confidence=0.95,
                            method="content_filter",
                            needs_review=False,
                            details={"reason": "setfit_blocked_by_content_guard"},
                        )
                    else:
                        logger.debug(
                            f"SetFit classified as {sf_category.value} "
                            f"with confidence {sf_confidence:.2f}"
                        )
                        return ClassificationResult(
                            category=sf_category,
                            confidence=sf_confidence,
                            method="setfit",
                            needs_review=sf_confidence < CONFIDENCE_AUTO,
                        )

        # =====================================================================
        # Fallback: Use best available result with NEEDS_REVIEW safety net
        # =====================================================================
        # For job tracking, we must be conservative about marking as OTHER
        # If there's a reasonable chance it's job-related, mark as NEEDS_REVIEW
        #
        # UNREACHABLE FROM THE CLOUD ENTRYPOINT, AND THE NET BELOW NEVER FIRES
        # ANYWHERE. Read this before trusting the block that follows — it looks
        # like a guarantee and it is not one. See #253 for the measurement.
        #
        # 1. Deployment. ``self._cloud_rules_only`` returns ~130 lines above, so
        #    on Vercel — the only place production mail is classified — nothing
        #    below this line runs at all.
        # 2. The guard is unsatisfiable, on every deployment. ``rules.py``
        #    seeds ``scores`` with an entry per ``EmailCategory``, so
        #    ``scores["other"]`` is always exactly 0 and the winning score is
        #    therefore never negative. Rules returns OTHER on exactly one
        #    branch — ``if winner_score <= 0`` — which given that floor means
        #    ``winner_score == 0``, i.e. EVERY category scored <= 0. So
        #    ``final_category == OTHER`` already implies ``max_job_score <= 0``,
        #    and ``max_job_score >= 2`` cannot hold. ``rules_result`` is never
        #    rebound between there and here, so this holds on the desktop
        #    fallback path too.
        #
        # What the net was reaching for does exist — a message whose job
        # patterns matched and were then erased by ``negative`` (-5) or ``veto``
        # (clamp to 0) arithmetic lands OTHER with real evidence behind it. But
        # that evidence survives only in ``matched_patterns``; ``scores`` records
        # the post-arithmetic total, which for such a message is NEGATIVE, not
        # >= 2. The net reads the wrong side of the subtraction.
        #
        # Measured before being left alone (#253): over the committed evaluation
        # corpus (200 messages) plus production ``emails`` metadata replayed
        # read-only (51), the net fires on 0. That 0 is a proof, not a sample —
        # but note the corpus is also thin here, holding 26 OTHER verdicts of
        # which 13 are content-guard forces. Do not read it as evidence the
        # THRESHOLD is well chosen; it is evidence the guard cannot be met.
        #
        # Pinned by ``tests/test_safety_net_is_dead_253.py``. If you rewire the
        # cloud short-circuit or relax the OTHER branch in ``rules.py``, that
        # file goes red on purpose: you have switched this net on, and #253 is
        # the argument about whether it should be.

        final_category = rules_result.category
        final_confidence = rules_result.confidence
        needs_review = final_confidence < CONFIDENCE_AUTO

        # Safety net: If rules says OTHER but there are meaningful job signals
        if final_category == EmailCategory.OTHER:
            # Check if there were significant job-related scores (might be a borderline case)
            # Only flag if score >= 2 (at least one strong match or two weak matches)
            job_categories = [
                "applied",
                "pending_application",
                "interview",
                "rejection",
                "offer",
                "assessment",
            ]
            job_scores = {cat: rules_result.scores.get(cat, 0) for cat in job_categories}
            max_job_score = max(job_scores.values()) if job_scores else 0

            # Only mark for review if there are meaningful job signals
            # (score >= 2 means at least some job-related patterns matched)
            if max_job_score >= 2:  # unreachable — see the note above
                final_category = EmailCategory.NEEDS_REVIEW
                needs_review = True
                logger.debug(
                    f"Marking as NEEDS_REVIEW (was OTHER, job_scores={job_scores})"
                )

        # Final protection: job-alert/newsletter/promotional content should stay OTHER.
        #
        # Also dead, and for a third reason worth writing down (#253 asks): this
        # is the SAME call, with the same arguments, as the one at the top of
        # ``classify()``. If it returned a reason, that earlier call already
        # returned OTHER at 0.96 and we never got here. Kept as belt-and-braces
        # in case a future path reaches this block without the entry guard —
        # but it is not the reason the net above is safe, so do not cite it as
        # one when arguing about #253.
        if final_category != EmailCategory.OTHER:
            late_other_reason = self._forced_other_reason(subject, body, sender_email)
            if late_other_reason:
                final_category = EmailCategory.OTHER
                final_confidence = max(final_confidence, 0.90)
                needs_review = False
                logger.debug(
                    "Late content guard override to OTHER: reason=%s",
                    late_other_reason,
                )

        logger.debug(
            f"Fallback to rules: {final_category.value} "
            f"with confidence {final_confidence:.2f}"
        )

        return ClassificationResult(
            category=final_category,
            confidence=final_confidence,
            method="fallback",
            needs_review=needs_review,
            details={
                "matched_patterns": rules_result.matched_patterns[:5],
                "scores": rules_result.scores,
            },
        )

    def is_lite_mode(self) -> bool:
        """Return whether SetFit is currently disabled."""
        return self._lite_mode

    def set_lite_mode(self, enabled: bool) -> None:
        """Enable/disable Lite Mode at runtime."""
        self._lite_mode = enabled
        logger.info("Lite mode %s", "enabled" if enabled else "disabled")

    def _forced_other_reason(
        self,
        subject: str,
        body: str,
        sender_email: Optional[str],
    ) -> Optional[str]:
        """
        Return reason string when message should be force-classified as OTHER.

        Uses combined content signals (subject + body), not sender alone.
        """
        text = f"{subject or ''}\n{body or ''}".lower()
        lifecycle_hit = any(pattern.search(text) for pattern in self._lifecycle_patterns)
        if lifecycle_hit:
            return None

        content_hits = sum(
            1 for pattern in self._non_application_patterns if pattern.search(text)
        )

        sender_hit = _is_digest_mailbox(sender_email)

        if content_hits >= 2:
            return "digest_or_promotional_content"
        if sender_hit and content_hits >= 1:
            return "sender_plus_digest_content"
        if domain_matches(sender_domain(sender_email), LINKEDIN_DOMAIN) and content_hits >= 1:
            return "linkedin_job_alert_content"
        return None

    async def add_correction(
        self,
        email_id: int,
        subject: str,
        body: str,
        correct_category: EmailCategory,
    ):
        """
        Add a user correction for learning.

        This:
        1. Adds the example to the embeddings store (immediate improvement)
        2. Stores in training_data table (for SetFit retraining)
        3. Checks if enough data to retrain SetFit

        Args:
            email_id: ID of the corrected email
            subject: Email subject
            body: Email body
            correct_category: The correct category (from user)
        """
        # Add to embeddings store (Layer 2 improves immediately)
        if self._embeddings.is_available():
            await self._embeddings.add_example(
                email_id, subject, body, correct_category
            )

        # Store in training_data for SetFit
        await self._store_training_data(email_id, subject, body, correct_category)

        # Check if we should retrain SetFit.
        #
        # SCOPE: this auto-retrain reads ``training_data`` directly. Applied's
        # Gmail access is the restricted ``gmail.readonly`` scope, and Google's
        # Workspace API user-data policy only permits training a model
        # personalized to a single end user — no co-mingling across users. So
        # the corpus is scoped to one ``user_id``, never "everything in the
        # table". On desktop that resolves to the ``LOCAL_USER_ID`` sentinel
        # every local row carries, which is why the desktop loop is unchanged.
        # Do not "simplify" this back to an unscoped call: see
        # ``setfit_model.CrossUserTrainingError``.
        from .setfit_model import resolve_training_user_id

        training_user_id = resolve_training_user_id()
        if await self._setfit.should_retrain(user_id=training_user_id):
            logger.info("Triggering SetFit retraining...")
            # Run in background (non-blocking)
            import asyncio

            asyncio.create_task(self._setfit.train(user_id=training_user_id))

    async def _store_training_data(
        self,
        email_id: int,
        subject: str,
        body: str,
        category: EmailCategory,
    ):
        """Store a training example in the database."""
        try:
            from sqlalchemy import select

            from jobtracker.database import get_session
            from jobtracker.database.models import TrainingData

            async with get_session() as session:
                # Check if already exists
                result = await session.exec(
                    select(TrainingData).where(TrainingData.email_id == email_id)
                )
                existing = result.first()

                if existing:
                    # Update existing
                    data = existing[0] if hasattr(existing, "__getitem__") else existing
                    data.label = category.value
                    data.subject = subject
                    data.body_text = body
                    session.add(data)
                else:
                    # Create new
                    new_data = TrainingData(
                        email_id=email_id,
                        label=category.value,
                        subject=subject,
                        body_text=body,
                    )
                    session.add(new_data)

                await session.commit()
                logger.info(f"Stored training data for email {email_id}")

        except Exception as e:
            logger.error(f"Failed to store training data: {e}")

    async def get_status(self) -> dict:
        """Get status of all classification layers."""
        if self._cloud_rules_only:
            # Deliberately avoid touching ``self._embeddings`` /
            # ``self._setfit`` so the cloud import graph stays light.
            return {
                "rules": {
                    "available": True,
                    "description": "Pattern matching with weighted scoring",
                },
                "embeddings": {
                    "available": False,
                    "example_count": 0,
                    "has_examples": False,
                    "description": "Disabled on cloud (rules-only deployment)",
                },
                "setfit": {
                    "available": False,
                    "is_training": False,
                    "disabled_by_lite_mode": True,
                    "description": "Disabled on cloud (rules-only deployment)",
                },
            }

        embedding_count = await self._embeddings.get_example_count()
        return {
            "rules": {
                "available": True,
                "description": "Pattern matching with weighted scoring",
            },
            "embeddings": {
                "available": self._embeddings.is_available(),
                "example_count": embedding_count,
                "has_examples": embedding_count > 0,
                "description": "Sentence similarity using e5-small-v2",
            },
            "setfit": {
                "available": (not self._lite_mode) and self._setfit.is_available(),
                "is_training": self._setfit.is_training(),
                "disabled_by_lite_mode": self._lite_mode,
                "description": "Few-shot ML classifier",
            },
        }

    async def retrain_setfit(self, *, user_id: uuid.UUID):
        """Manually trigger SetFit retraining for exactly one user.

        Args:
            user_id: Whose corrections to train on. Required and undefaulted on
                purpose — this is the entry point reached by
                ``POST /classify/retrain`` and ``scripts/ml_cycle.sh --retrain``,
                i.e. the one an operator could point at a production database.
                Gmail's restricted ``gmail.readonly`` scope permits only a
                per-user personalized model, so there is no "all users" option
                to default to. Callers without an authenticated identity pass
                ``setfit_model.resolve_training_user_id()``.
        """
        if self._setfit.is_training():
            raise RuntimeError("Training already in progress")

        await self._setfit.train(user_id=user_id)


# =============================================================================
# Singleton Instance
# =============================================================================

_classifier: Optional[HybridClassifier] = None


def get_hybrid_classifier() -> HybridClassifier:
    """Get singleton hybrid classifier instance."""
    global _classifier
    if _classifier is None:
        _classifier = HybridClassifier()
    return _classifier
