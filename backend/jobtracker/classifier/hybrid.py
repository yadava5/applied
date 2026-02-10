"""
Hybrid Email Classifier
=======================

Combines all 3 classification layers:
1. Rules (regex patterns) - instant, catches obvious patterns
2. Embeddings (similarity) - catches variations of labeled examples
3. SetFit (few-shot ML) - trained on user corrections

Decision flow:
- High-confidence rule match (≥0.9) → accept immediately
- Embedding similarity match (≥0.85) → accept
- SetFit prediction (≥0.7) → accept
- Otherwise → return best guess with lower confidence

Confidence thresholds:
- ≥0.85: Auto-classify (no review needed)
- 0.70-0.84: Auto-classify but flag for review queue
- <0.70: Manual review required
"""

import logging
from dataclasses import dataclass
from typing import Optional

from jobtracker.database.models import EmailCategory

from .embeddings import get_embeddings_classifier
from .rules import get_rules_classifier
from .setfit_model import get_setfit_classifier

logger = logging.getLogger(__name__)


# =============================================================================
# Classification Result
# =============================================================================


@dataclass
class ClassificationResult:
    """Result from hybrid classification."""

    category: EmailCategory
    confidence: float
    method: str  # "rules", "embeddings", "setfit", "fallback"
    needs_review: bool  # True if confidence < 0.70
    details: Optional[dict] = None


# =============================================================================
# Confidence Thresholds
# =============================================================================

CONFIDENCE_AUTO = 0.85  # Auto-classify without review
CONFIDENCE_REVIEW = 0.70  # Auto-classify but add to review queue
# Below 0.70: Flag for manual review


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
        self._embeddings = get_embeddings_classifier()
        self._setfit = get_setfit_classifier()

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
        # =====================================================================
        # Layer 1: Rule-Based Classification
        # =====================================================================
        rules_result = self._rules.classify(subject, body, sender_email)

        if rules_result.confidence >= 0.90:
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
        # Layer 2: Embedding Similarity
        # =====================================================================
        # BUT: Don't trust embeddings if rules found strong negative signals
        # (e.g., marketing/promotional patterns that indicate NOT job-related)
        has_negative_signals = any(
            "[NEGATIVE]" in p for p in rules_result.matched_patterns
        )
        rules_says_other = rules_result.category == EmailCategory.OTHER
        
        if self._embeddings.is_available() and not (has_negative_signals and rules_says_other):
            emb_result = await self._embeddings.classify(subject, body)

            if emb_result is not None:
                emb_category, emb_confidence = emb_result

                # Only trust embeddings if rules doesn't strongly disagree
                if emb_confidence >= 0.85 and not has_negative_signals:
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
        if self._setfit.is_available():
            setfit_result = self._setfit.classify(subject, body)

            if setfit_result is not None:
                sf_category, sf_confidence = setfit_result

                if sf_confidence >= CONFIDENCE_REVIEW:
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
        
        final_category = rules_result.category
        final_confidence = rules_result.confidence
        needs_review = final_confidence < CONFIDENCE_REVIEW
        
        # Safety net: If rules says OTHER but there are meaningful job signals
        if final_category == EmailCategory.OTHER:
            # Check if there were significant job-related scores (might be a borderline case)
            # Only flag if score >= 2 (at least one strong match or two weak matches)
            job_categories = ["applied", "interview", "rejection", "offer", "assessment"]
            job_scores = {cat: rules_result.scores.get(cat, 0) for cat in job_categories}
            max_job_score = max(job_scores.values()) if job_scores else 0
            
            # Only mark for review if there are meaningful job signals
            # (score >= 2 means at least some job-related patterns matched)
            if max_job_score >= 2:
                final_category = EmailCategory.NEEDS_REVIEW
                needs_review = True
                logger.debug(
                    f"Marking as NEEDS_REVIEW (was OTHER, job_scores={job_scores})"
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

        # Check if we should retrain SetFit
        if await self._setfit.should_retrain():
            logger.info("Triggering SetFit retraining...")
            # Run in background (non-blocking)
            import asyncio

            asyncio.create_task(self._setfit.train())

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
                "available": self._setfit.is_available(),
                "is_training": self._setfit.is_training(),
                "description": "Few-shot ML classifier",
            },
        }

    async def retrain_setfit(self):
        """Manually trigger SetFit retraining."""
        if self._setfit.is_training():
            raise RuntimeError("Training already in progress")

        await self._setfit.train()


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
