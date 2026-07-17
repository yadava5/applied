"""
Classification API endpoints.

Provides endpoints for:
- Classifying emails
- User corrections
- ML model status and retraining
- Batch classification
"""

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from jobtracker.classifier import get_classifier
from jobtracker.database import get_session
from jobtracker.database.models import Email, EmailCategory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/classify", tags=["classification"])
REVIEW_QUEUE_CONFIDENCE_THRESHOLD = 0.85


# =============================================================================
# Request/Response Models
# =============================================================================


class ClassifyRequest(BaseModel):
    """Request to classify text."""

    subject: str = Field(..., description="Email subject")
    body: str = Field(..., description="Email body text")
    sender_email: Optional[str] = Field(None, description="Sender email address")


class ClassificationResponse(BaseModel):
    """Classification result."""

    category: str
    confidence: float
    method: str
    needs_review: bool


class CorrectionRequest(BaseModel):
    """Request to correct a classification."""

    category: str = Field(
        ...,
        description="Correct category",
        examples=[
            "rejection",
            "interview",
            "offer",
            "applied",
            "pending_application",
            "assessment",
        ],
    )


class ClassifierStatusResponse(BaseModel):
    """Status of the classifier layers."""

    rules: dict
    embeddings: dict
    setfit: dict


class BatchClassifyResponse(BaseModel):
    """Result of batch classification."""

    processed: int
    classified: int
    errors: int
    categories: dict[str, int]


class LiteModeStateResponse(BaseModel):
    """Lite mode runtime state."""

    enabled: bool
    setfit_available: bool
    disabled_by_lite_mode: bool


class LiteModeUpdateRequest(BaseModel):
    """Request to toggle lite mode."""

    enabled: bool


# =============================================================================
# Endpoints
# =============================================================================


@router.post("", response_model=ClassificationResponse)
async def classify_text(request: ClassifyRequest) -> ClassificationResponse:
    """
    Classify text using the hybrid classifier.

    Useful for testing classification without an actual email.
    """
    classifier = get_classifier()
    result = await classifier.classify(
        request.subject,
        request.body,
        request.sender_email,
    )

    return ClassificationResponse(
        category=result.category.value,
        confidence=result.confidence,
        method=result.method,
        needs_review=result.needs_review,
    )


@router.post("/email/{email_id}", response_model=ClassificationResponse)
async def classify_email(email_id: int) -> ClassificationResponse:
    """
    Classify a specific email by ID.

    Updates the email's classification in the database.
    """
    async with get_session() as session:
        result = await session.exec(select(Email).where(Email.id == email_id))
        row = result.first()

        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Email {email_id} not found",
            )

        email = row[0] if hasattr(row, "__getitem__") else row

        # Classify
        classifier = get_classifier()
        classification = await classifier.classify(
            email.subject or "",
            email.body_text or "",
            email.sender_email,
        )

        # Update email
        stmt = (
            update(Email)
            .where(Email.id == email_id)
            .values(
                classified_as=classification.category,
                classification_confidence=classification.confidence,
                classification_method=classification.method,
            )
        )
        await session.exec(stmt)
        await session.commit()

        return ClassificationResponse(
            category=classification.category.value,
            confidence=classification.confidence,
            method=classification.method,
            needs_review=classification.needs_review,
        )


@router.put("/email/{email_id}/correct", response_model=dict)
async def correct_classification(
    email_id: int,
    request: CorrectionRequest,
) -> dict:
    """
    Correct an email's classification.

    This:
    1. Updates the email's classification
    2. Marks it as user-corrected
    3. Adds to training data for future ML improvement
    4. May trigger SetFit retraining if enough corrections accumulated
    """
    # Validate category
    try:
        category = EmailCategory(request.category)
    except ValueError:
        valid = [c.value for c in EmailCategory]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid category: {request.category}. Valid: {valid}",
        )

    async with get_session() as session:
        result = await session.exec(select(Email).where(Email.id == email_id))
        row = result.first()

        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Email {email_id} not found",
            )

        email = row[0] if hasattr(row, "__getitem__") else row

        # Update email classification
        stmt = (
            update(Email)
            .where(Email.id == email_id)
            .values(
                classified_as=category,
                classification_confidence=1.0,  # User correction = 100% confidence
                classification_method="user_correction",
                user_corrected=True,
                is_reviewed=True,
            )
        )
        await session.exec(stmt)
        await session.commit()

        # Add to classifier's training data
        classifier = get_classifier()
        await classifier.add_correction(
            email_id,
            email.subject or "",
            email.body_text or "",
            category,
        )

        return {
            "success": True,
            "message": f"Email {email_id} corrected to {category.value}",
            "category": category.value,
        }


@router.post("/batch", response_model=BatchClassifyResponse)
async def classify_batch(
    background_tasks: BackgroundTasks,
    limit: int = 100,
    unclassified_only: bool = True,
    force_reclassify: bool = False,
) -> BatchClassifyResponse:
    """
    Classify multiple emails in batch.

    Runs in background for large batches.
    """
    classifier = get_classifier()
    processed = 0
    classified = 0
    errors = 0
    categories: dict[str, int] = {}

    async with get_session() as session:
        # Build query
        query = select(Email)
        if force_reclassify:
            # Reclassify all emails (but not user-corrected ones)
            query = query.where(Email.user_corrected == False)  # noqa: E712
        elif unclassified_only:
            query = query.where(Email.classified_as == None)  # noqa: E711
        query = query.limit(limit)

        result = await session.exec(query)
        emails = result.all()

        for row in emails:
            email = row[0] if hasattr(row, "__getitem__") else row
            processed += 1

            try:
                # Classify
                classification = await classifier.classify(
                    email.subject or "",
                    email.body_text or "",
                    email.sender_email,
                )

                # Update email
                stmt = (
                    update(Email)
                    .where(Email.id == email.id)
                    .values(
                        classified_as=classification.category,
                        classification_confidence=classification.confidence,
                        classification_method=classification.method,
                    )
                )
                await session.exec(stmt)

                classified += 1
                cat_name = classification.category.value
                categories[cat_name] = categories.get(cat_name, 0) + 1

            except Exception as e:
                logger.error(f"Failed to classify email {email.id}: {e}")
                errors += 1

        await session.commit()

    return BatchClassifyResponse(
        processed=processed,
        classified=classified,
        errors=errors,
        categories=categories,
    )


@router.get("/status", response_model=ClassifierStatusResponse)
async def get_classifier_status() -> ClassifierStatusResponse:
    """Get status of all classifier layers."""
    classifier = get_classifier()
    status_info = await classifier.get_status()

    return ClassifierStatusResponse(
        rules=status_info["rules"],
        embeddings=status_info["embeddings"],
        setfit=status_info["setfit"],
    )


@router.get("/lite-mode", response_model=LiteModeStateResponse)
async def get_lite_mode_state() -> LiteModeStateResponse:
    """Get current lite-mode state."""
    classifier = get_classifier()
    status_info = await classifier.get_status()
    setfit_info = status_info["setfit"]

    return LiteModeStateResponse(
        enabled=classifier.is_lite_mode(),
        setfit_available=bool(setfit_info.get("available", False)),
        disabled_by_lite_mode=bool(setfit_info.get("disabled_by_lite_mode", False)),
    )


@router.put("/lite-mode", response_model=LiteModeStateResponse)
async def update_lite_mode(request: LiteModeUpdateRequest) -> LiteModeStateResponse:
    """Enable/disable lite mode (rules + embeddings only)."""
    classifier = get_classifier()
    classifier.set_lite_mode(request.enabled)
    status_info = await classifier.get_status()
    setfit_info = status_info["setfit"]

    return LiteModeStateResponse(
        enabled=classifier.is_lite_mode(),
        setfit_available=bool(setfit_info.get("available", False)),
        disabled_by_lite_mode=bool(setfit_info.get("disabled_by_lite_mode", False)),
    )


@router.post("/retrain")
async def trigger_retraining(background_tasks: BackgroundTasks) -> dict:
    """
    Manually trigger SetFit model retraining.

    Runs in background (2-5 minutes on CPU).
    """
    classifier = get_classifier()
    status_info = await classifier.get_status()

    if status_info["setfit"]["is_training"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Training already in progress",
        )

    # Run in background
    background_tasks.add_task(classifier.retrain_setfit)

    return {
        "success": True,
        "message": "SetFit retraining started in background",
    }


@router.post("/seed-training-data")
async def seed_training_data(
    min_confidence: float = 0.85,
    max_per_category: int = 20,
) -> dict:
    """
    Pre-seed training data from high-confidence rule classifications.

    This jumpstarts the ML layers by using already-classified emails
    as training examples. Only uses emails classified with high confidence
    by the rules layer.

    Args:
        min_confidence: Minimum confidence threshold (default 0.85)
        max_per_category: Maximum examples per category (default 20)
    """
    from collections import defaultdict

    from jobtracker.classifier.embeddings import (
        EmbeddingModel,
        embedding_to_bytes,
    )
    from jobtracker.database.models import EmailEmbedding, TrainingData

    seeded = defaultdict(int)
    embedding_model = EmbeddingModel()

    async with get_session() as session:
        # Get high-confidence classified emails (not user-corrected)
        query = (
            select(Email)
            .where(Email.classified_as != None)  # noqa: E711
            .where(Email.classification_confidence >= min_confidence)
            .where(Email.classification_method == "rules")
            .where(Email.user_corrected == False)  # noqa: E712
            .where(Email.classified_as != EmailCategory.OTHER)  # Skip "other"
        )

        result = await session.exec(query)
        emails = result.all()

        for row in emails:
            email = row[0] if hasattr(row, "__getitem__") else row
            category = email.classified_as

            # Skip if we have enough for this category
            if seeded[category.value] >= max_per_category:
                continue

            # Check if already in training data
            existing = await session.exec(
                select(TrainingData).where(TrainingData.email_id == email.id)
            )
            if existing.first():
                continue

            # Add to training_data
            training_entry = TrainingData(
                email_id=email.id,
                subject=email.subject,
                body_text=email.body_text,
                label=category.value,
                source="auto_seed",
            )
            session.add(training_entry)

            # Add embedding if model is available
            if embedding_model.is_available():
                text = f"{email.subject or ''}\n\n{email.body_text or ''}"
                embedding = embedding_model.encode(text)

                if embedding is not None:
                    # Check if embedding already exists
                    existing_emb = await session.exec(
                        select(EmailEmbedding).where(
                            EmailEmbedding.email_id == email.id
                        )
                    )
                    if not existing_emb.first():
                        emb_entry = EmailEmbedding(
                            email_id=email.id,
                            label=category.value,
                            embedding=embedding_to_bytes(embedding),
                            model_version="e5-small-v2",
                        )
                        session.add(emb_entry)

            seeded[category.value] += 1

        await session.commit()

    return {
        "success": True,
        "seeded_per_category": dict(seeded),
        "total_seeded": sum(seeded.values()),
        "message": f"Seeded {sum(seeded.values())} training examples",
    }


# =============================================================================
# NEEDS REVIEW Endpoints
# =============================================================================


class ReviewEmailResponse(BaseModel):
    """Email that needs review."""

    id: int
    subject: Optional[str]
    sender_email: Optional[str]
    sender_name: Optional[str]
    snippet: Optional[str]
    body_text: Optional[str]
    body_html: Optional[str]
    current_category: str
    confidence: float
    received_at: Optional[str]


class NeedsReviewListResponse(BaseModel):
    """List of emails needing review."""

    emails: list[ReviewEmailResponse]
    total_count: int


@router.get("/needs-review", response_model=NeedsReviewListResponse)
async def get_emails_needing_review(
    limit: int = 50,
    offset: int = 0,
) -> NeedsReviewListResponse:
    """
    Get emails that need human review.

    These are emails that:
    1. Are explicitly marked as NEEDS_REVIEW (borderline job-related)
    2. Are job-related categories below 85% confidence (might be wrong)

    Review these to ensure you don't miss any job opportunities!
    """
    # Job-related categories that warrant review if low confidence
    job_categories = [
        EmailCategory.APPLIED,
        EmailCategory.PENDING_APPLICATION,
        EmailCategory.INTERVIEW,
        EmailCategory.REJECTION,
        EmailCategory.OFFER,
        EmailCategory.ASSESSMENT,
        EmailCategory.FOLLOW_UP,
        EmailCategory.NEEDS_REVIEW,
    ]

    async with get_session() as session:
        # Get emails that are NEEDS_REVIEW or job-related with low confidence
        query = (
            select(Email)
            .where(
                (Email.classified_as == EmailCategory.NEEDS_REVIEW)
                | (
                    Email.classified_as.in_(job_categories)
                    & (Email.classification_confidence != None)  # noqa: E711
                    & (Email.classification_confidence < REVIEW_QUEUE_CONFIDENCE_THRESHOLD)
                    & (Email.user_corrected == False)  # noqa: E712
                )
            )
            .order_by(Email.received_at.desc())
            .offset(offset)
            .limit(limit)
        )

        result = await session.exec(query)
        emails = result.all()

        # Get total count
        count_query = select(Email).where(
            (Email.classified_as == EmailCategory.NEEDS_REVIEW)
            | (
                Email.classified_as.in_(job_categories)
                & (Email.classification_confidence != None)  # noqa: E711
                & (Email.classification_confidence < REVIEW_QUEUE_CONFIDENCE_THRESHOLD)
                & (Email.user_corrected == False)  # noqa: E712
            )
        )
        count_result = await session.exec(count_query)
        total = len(count_result.all())

        response_emails = []
        for row in emails:
            email = row[0] if hasattr(row, "__getitem__") else row
            response_emails.append(
                ReviewEmailResponse(
                    id=email.id,
                    subject=email.subject,
                    sender_email=email.sender_email,
                    sender_name=email.sender_name,
                    snippet=email.body_snippet,
                    body_text=email.body_text,
                    body_html=email.body_html,
                    current_category=(
                        email.classified_as.value if email.classified_as else "unknown"
                    ),
                    confidence=email.classification_confidence or 0.0,
                    received_at=(
                        email.received_at.isoformat() if email.received_at else None
                    ),
                )
            )

        return NeedsReviewListResponse(
            emails=response_emails,
            total_count=total,
        )


@router.get("/needs-review/count")
async def get_needs_review_count() -> dict:
    """Get count of emails needing review."""
    async with get_session() as session:
        from sqlalchemy import text

        # Only count NEEDS_REVIEW or sub-85%-confidence job-related emails.
        result = await session.execute(
            text("""
                SELECT COUNT(*) FROM emails
                WHERE UPPER(classified_as) = 'NEEDS_REVIEW'
                OR (
                    UPPER(classified_as) IN (
                        'APPLIED',
                        'PENDING_APPLICATION',
                        'INTERVIEW',
                        'REJECTION',
                        'OFFER',
                        'ASSESSMENT',
                        'FOLLOW_UP'
                    )
                    AND classification_confidence IS NOT NULL
                    AND classification_confidence < :threshold
                    AND user_corrected = 0
                )
            """),
            {"threshold": REVIEW_QUEUE_CONFIDENCE_THRESHOLD},
        )
        row = result.first()
        count = row[0] if row else 0

        return {
            "needs_review_count": count,
            "message": f"{count} emails need your review" if count > 0 else "No emails need review",
        }


@router.post("/needs-review/{email_id}/approve")
async def approve_classification(email_id: int) -> dict:
    """
    Approve the current classification for an email.

    This marks the email as reviewed and adds it to training data
    to improve future classifications.
    """
    async with get_session() as session:
        result = await session.exec(select(Email).where(Email.id == email_id))
        email = result.first()

        if not email:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Email {email_id} not found",
            )

        email = email[0] if hasattr(email, "__getitem__") else email

        if not email.classified_as:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email has not been classified yet",
            )

        # If it was NEEDS_REVIEW, we need the user to specify a category
        if email.classified_as == EmailCategory.NEEDS_REVIEW:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot approve NEEDS_REVIEW - use /correct endpoint to specify category",
            )

        approved_category = email.classified_as

        # Mark as user-reviewed (approved)
        email.user_corrected = True
        email.is_reviewed = True
        email.classification_confidence = 1.0  # User confirmed
        email.classification_method = "user"

        await session.commit()

        # Feed approved examples into training so review queue decisions
        # improve future classifications.
        classifier = get_classifier()
        await classifier.add_correction(
            email_id,
            email.subject or "",
            email.body_text or "",
            approved_category,
        )

        return {
            "success": True,
            "email_id": email_id,
            "approved_category": approved_category.value,
            "message": f"Approved classification as {approved_category.value}",
        }


# =============================================================================
# Bulk Import Endpoint
# =============================================================================


class BulkTrainingItem(BaseModel):
    """Single training example for bulk import."""

    subject: str = Field(default="", description="Email subject")
    body_text: str = Field(..., description="Email body text")
    label: str = Field(
        ...,
        description="Classification label",
        examples=["applied", "interview", "rejection", "offer", "other"],
    )


class BulkImportRequest(BaseModel):
    """Request to bulk-import training data."""

    items: list[BulkTrainingItem] = Field(
        ..., description="Training examples to import", min_length=1
    )
    source: str = Field(
        default="bulk_import",
        description="Source tag for these training examples",
    )
    trigger_retrain: bool = Field(
        default=True,
        description="Auto-trigger SetFit retraining if gates are met",
    )


class BulkImportResponse(BaseModel):
    """Result of bulk training data import."""

    success: bool
    inserted: int
    skipped_duplicate: int
    skipped_invalid: int
    label_distribution: dict[str, int]
    retrain_triggered: bool
    message: str


@router.post("/import-training-data", response_model=BulkImportResponse)
async def import_training_data(
    request: BulkImportRequest,
    background_tasks: BackgroundTasks,
) -> BulkImportResponse:
    """
    Bulk-import labeled training data.

    Accepts a JSON array of {subject, body_text, label} objects.
    Validates labels, deduplicates against existing training_data,
    and optionally triggers SetFit retraining.

    Useful for:
    - Importing externally labeled datasets
    - Future drag-and-drop UI in the macOS app
    - Script-based data ingestion
    """
    from collections import defaultdict
    from datetime import datetime
    import hashlib

    from jobtracker.database.models import TrainingData

    # Valid labels (same as DB CHECK constraint, excluding needs_review)
    valid_labels = {c.value for c in EmailCategory if c != EmailCategory.NEEDS_REVIEW}

    inserted = 0
    skipped_duplicate = 0
    skipped_invalid = 0
    label_dist: dict[str, int] = defaultdict(int)

    # Collect existing training texts for dedup
    existing_hashes: set[str] = set()
    async with get_session() as session:
        result = await session.exec(select(TrainingData.email_text))
        for row in result.all():
            txt = row[0] if hasattr(row, "__getitem__") else row
            if txt:
                h = hashlib.md5(str(txt).encode("utf-8", errors="replace")).hexdigest()
                existing_hashes.add(h)

    # Insert new training data
    async with get_session() as session:
        for item in request.items:
            # Validate label
            if item.label not in valid_labels:
                skipped_invalid += 1
                continue

            email_text = f"{item.subject}\n\n{item.body_text}".strip()
            h = hashlib.md5(email_text.encode("utf-8", errors="replace")).hexdigest()

            if h in existing_hashes:
                skipped_duplicate += 1
                continue

            training_entry = TrainingData(
                email_text=email_text,
                subject=item.subject if item.subject else None,
                body_text=item.body_text if item.body_text else None,
                label=item.label,
                source=request.source,
                created_at=datetime.utcnow(),
            )
            session.add(training_entry)
            existing_hashes.add(h)
            inserted += 1
            label_dist[item.label] += 1

        await session.commit()

    # Check if we should trigger retraining
    retrain_triggered = False
    if request.trigger_retrain and inserted > 0:
        classifier = get_classifier()
        setfit = classifier._setfit
        if await setfit.should_retrain():
            background_tasks.add_task(classifier.retrain_setfit)
            retrain_triggered = True

    return BulkImportResponse(
        success=True,
        inserted=inserted,
        skipped_duplicate=skipped_duplicate,
        skipped_invalid=skipped_invalid,
        label_distribution=dict(label_dist),
        retrain_triggered=retrain_triggered,
        message=f"Imported {inserted} training examples"
        + (", retraining triggered" if retrain_triggered else ""),
    )
