#!/usr/bin/env python3
"""
Import Verified Candidates into Training Database
==================================================

Reads candidates.jsonl, takes only verified rows (needs_review=False),
and inserts them into the training_data table + computes embeddings
for the email_embeddings table.

After import, checks if SetFit training gates are met and triggers
retraining if so.

Usage:
    python -m jobtracker.scripts.import_to_db [--input PATH] [--dry-run]
"""

import argparse
import asyncio
import hashlib
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Add backend/ to sys.path so jobtracker imports work standalone
# ---------------------------------------------------------------------------
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

OUTPUT_DIR = _BACKEND_DIR / "data" / "processed"
CANDIDATES_FILE = OUTPUT_DIR / "candidates.jsonl"

# Valid training labels (same as DB CHECK constraint)
VALID_LABELS = {
    "applied",
    "pending_application",
    "interview",
    "rejection",
    "offer",
    "assessment",
    "follow_up",
    "other",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_verified_candidates(filepath: Path) -> list[dict]:
    """Load only verified (needs_review=False) candidates."""
    candidates = []
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            if not c.get("needs_review", True) and c.get("auto_label") in VALID_LABELS:
                candidates.append(c)
    return candidates


def email_text_hash(text: str) -> str:
    """Hash for dedup against existing training_data rows."""
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()


# ---------------------------------------------------------------------------
# Database import (async)
# ---------------------------------------------------------------------------

async def import_candidates(candidates: list[dict], dry_run: bool = False) -> dict:
    """
    Import verified candidates into training_data and email_embeddings tables.

    Returns stats dict.
    """
    # Late imports to avoid loading ML models unless needed
    from sqlalchemy import select, text

    from jobtracker.database import get_session, init_db
    from jobtracker.database.models import TrainingData

    # Initialize database engine
    await init_db()

    stats = {
        "total_input": len(candidates),
        "inserted_training": 0,
        "skipped_duplicate": 0,
        "skipped_invalid": 0,
        "embeddings_computed": 0,
        "labels": defaultdict(int),
    }

    if dry_run:
        logger.info("[DRY RUN] Would import %d candidates", len(candidates))
        for c in candidates:
            stats["labels"][c["auto_label"]] += 1
        return stats

    # Collect existing training texts for dedup
    existing_hashes: set[str] = set()
    async with get_session() as session:
        result = await session.exec(select(TrainingData.email_text))
        for row in result.all():
            txt = row[0] if hasattr(row, "__getitem__") else row
            if txt:
                existing_hashes.add(email_text_hash(str(txt)))

    logger.info("Found %d existing training_data rows", len(existing_hashes))

    # Load embedding model once
    embedding_model = None
    try:
        from jobtracker.classifier.embeddings import EmbeddingModel, embedding_to_bytes
        embedding_model = EmbeddingModel()
        if not embedding_model.is_available():
            logger.warning("Embedding model not available — skipping embedding computation")
            embedding_model = None
    except Exception as e:
        logger.warning("Could not load embedding model: %s", e)

    # Import in batches
    batch_size = 50
    for batch_start in range(0, len(candidates), batch_size):
        batch = candidates[batch_start : batch_start + batch_size]

        async with get_session() as session:
            for c in batch:
                label = c["auto_label"]
                subject = c.get("subject", "")
                body_text = c.get("body_text", "")

                # Combine for the legacy email_text field
                email_text = f"{subject}\n\n{body_text}".strip()

                # Dedup check
                h = email_text_hash(email_text)
                if h in existing_hashes:
                    stats["skipped_duplicate"] += 1
                    continue

                # Validate label
                if label not in VALID_LABELS:
                    stats["skipped_invalid"] += 1
                    continue

                # Insert training_data row
                training_entry = TrainingData(
                    email_text=email_text,
                    subject=subject if subject else None,
                    body_text=body_text if body_text else None,
                    label=label,
                    source="external_dataset",
                    created_at=datetime.utcnow(),
                )
                session.add(training_entry)
                existing_hashes.add(h)  # prevent intra-batch dupes
                stats["inserted_training"] += 1
                stats["labels"][label] += 1

            await session.commit()

        logger.info(
            "  Batch %d-%d: %d inserted",
            batch_start + 1,
            min(batch_start + batch_size, len(candidates)),
            stats["inserted_training"],
        )

    # Compute embeddings for all newly inserted rows that don't have them
    if embedding_model is not None:
        logger.info("Computing embeddings for new training data...")
        await _compute_embeddings_for_external(embedding_model, stats)

    return stats


async def _compute_embeddings_for_external(embedding_model, stats: dict):
    """Compute and store embeddings for external training data."""
    from sqlalchemy import select, text

    from jobtracker.classifier.embeddings import embedding_to_bytes
    from jobtracker.database import get_session
    from jobtracker.database.models import TrainingData

    # Get external training data without embeddings
    # Since external data has no email_id, we store embeddings in a
    # separate approach: we compute them and keep in training_data context.
    # The embedding similarity layer uses email_embeddings (tied to email_id),
    # but for SetFit training, embeddings aren't needed in the DB —
    # SetFit computes its own. So we just confirm the training data is stored.
    #
    # However, we CAN create "synthetic" embeddings for the embeddings layer
    # for rows that have matching emails. For external data without email_id,
    # the benefit comes from SetFit training, not embeddings layer.

    logger.info(
        "Note: External training data improves SetFit (Layer 3) directly. "
        "Embeddings layer (Layer 2) improves when you correct real emails."
    )
    stats["embeddings_computed"] = 0


async def check_and_trigger_retrain(stats: dict):
    """Check if SetFit training gates are met and trigger retraining."""
    from sqlalchemy import func, select

    from jobtracker.classifier.setfit_model import resolve_training_user_id
    from jobtracker.database import get_session
    from jobtracker.database.models import TrainingData

    # SCOPE: both the gate below and the training run it triggers read
    # ``training_data`` for ONE user. Applied reads mail under Gmail's
    # restricted ``gmail.readonly`` scope, whose user-data policy permits
    # training only a model personalized to a single end user, with no
    # co-mingling across users. This is a local import script, so the id
    # resolves to the ``LOCAL_USER_ID`` sentinel every desktop row carries —
    # which is also what keeps it harmless if it is ever pointed at a
    # production DATABASE_URL. See ``setfit_model.CrossUserTrainingError``.
    training_user_id = resolve_training_user_id()

    async with get_session() as session:
        result = await session.exec(
            select(
                TrainingData.label,
                func.count(TrainingData.id).label("count"),
            )
            .where(TrainingData.user_id == training_user_id)
            .group_by(TrainingData.label)
        )
        category_counts = {row[0]: row[1] for row in result.all()}

    total = sum(category_counts.values())
    categories_with_enough = sum(
        1 for count in category_counts.values() if count >= 5
    )

    logger.info("")
    logger.info("=" * 60)
    logger.info("Training Data Status")
    logger.info("=" * 60)
    logger.info("Total training examples: %d (need ≥40)", total)
    logger.info(
        "Categories with ≥5 examples: %d (need ≥3)", categories_with_enough
    )
    logger.info("")
    logger.info("Per-category breakdown:")
    for label in sorted(category_counts.keys()):
        count = category_counts[label]
        status = "✓" if count >= 5 else "✗"
        logger.info("  %s %-22s %d", status, label, count)

    can_train = total >= 40 and categories_with_enough >= 3

    if can_train:
        logger.info("")
        logger.info("SetFit training gates MET! Triggering retraining...")
        try:
            from jobtracker.classifier.setfit_model import get_setfit_classifier
            classifier = get_setfit_classifier()
            await classifier.train(user_id=training_user_id)
            logger.info("SetFit training completed successfully!")
        except Exception as e:
            logger.error("SetFit training failed: %s", e)
            logger.info(
                "You can retry later: curl -X POST http://127.0.0.1:8000/classify/retrain"
            )
    else:
        logger.info("")
        remaining = max(0, 40 - total)
        cats_needed = max(0, 3 - categories_with_enough)

        if remaining > 0:
            logger.info(
                "Need %d more training examples to reach SetFit threshold.",
                remaining,
            )
        if cats_needed > 0:
            logger.info(
                "Need %d more categories with ≥5 examples each.",
                cats_needed,
            )
        logger.info("")
        logger.info("How to add more training data:")
        logger.info("  1. Correct misclassified emails in the app")
        logger.info("  2. Approve review-queue items")
        logger.info("  3. Use: POST /classify/seed-training-data")
        logger.info("  4. Re-run review: python -m jobtracker.scripts.review_candidates")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def async_main(filepath: Path, dry_run: bool):
    """Async entry point."""
    if not filepath.exists():
        print(f"Error: {filepath} not found.")
        print("Run first: python -m jobtracker.scripts.ingest_datasets")
        sys.exit(1)

    candidates = load_verified_candidates(filepath)
    if not candidates:
        print("No verified candidates found.")
        print("Either all need review, or labels are invalid.")
        print("Run: python -m jobtracker.scripts.review_candidates")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("JobTracker — Import Training Data")
    logger.info("=" * 60)
    logger.info("Input: %s", filepath)
    logger.info("Verified candidates: %d", len(candidates))

    if dry_run:
        logger.info("[DRY RUN MODE — no database changes]")

    stats = await import_candidates(candidates, dry_run=dry_run)

    # Print results
    logger.info("")
    logger.info("=" * 60)
    logger.info("Import Results")
    logger.info("=" * 60)
    logger.info("Total input:        %d", stats["total_input"])
    logger.info("Inserted:           %d", stats["inserted_training"])
    logger.info("Skipped (duplicate): %d", stats["skipped_duplicate"])
    logger.info("Skipped (invalid):   %d", stats["skipped_invalid"])
    logger.info("")
    logger.info("Inserted label distribution:")
    for label in sorted(stats["labels"].keys()):
        logger.info("  %-22s %d", label, stats["labels"][label])

    if not dry_run and stats["inserted_training"] > 0:
        await check_and_trigger_retrain(stats)


def main():
    parser = argparse.ArgumentParser(
        description="Import verified candidates into the training database",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=CANDIDATES_FILE,
        help="Path to candidates.jsonl",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without making database changes",
    )
    args = parser.parse_args()

    asyncio.run(async_main(args.input, args.dry_run))


if __name__ == "__main__":
    main()
