#!/usr/bin/env python3
"""Import labeled JSONL examples into training_data with source tagging."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from jobtracker.classifier import get_classifier
from jobtracker.database import get_session, init_db
from jobtracker.database.models import EmailCategory, TrainingData


def _hash_text(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()


def _load_items(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)

    items: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if not isinstance(payload, dict):
                raise ValueError(f"Line {line_no}: expected JSON object")
            items.append(
                {
                    "subject": str(payload.get("subject", "") or "").strip(),
                    "body_text": str(payload.get("body_text", payload.get("body", "")) or "").strip(),
                    "label": str(payload.get("label", "") or "").strip(),
                }
            )
    return items


async def import_jsonl(
    path: Path,
    source: str,
    trigger_retrain: bool,
) -> dict:
    await init_db()

    valid_labels = {c.value for c in EmailCategory if c != EmailCategory.NEEDS_REVIEW}

    existing_hashes: set[str] = set()
    async with get_session() as session:
        result = await session.exec(select(TrainingData.email_text))
        for row in result.all():
            text = row[0] if hasattr(row, "__getitem__") else row
            if text:
                existing_hashes.add(_hash_text(str(text)))

    stats = {
        "total_rows": 0,
        "inserted": 0,
        "skipped_duplicate": 0,
        "skipped_invalid": 0,
        "labels": defaultdict(int),
        "retrain_triggered": False,
    }

    items = _load_items(path)
    stats["total_rows"] = len(items)

    async with get_session() as session:
        for item in items:
            label = item["label"]
            if label not in valid_labels:
                stats["skipped_invalid"] += 1
                continue

            email_text = f"{item['subject']}\n\n{item['body_text']}".strip()
            text_hash = _hash_text(email_text)
            if text_hash in existing_hashes:
                stats["skipped_duplicate"] += 1
                continue

            session.add(
                TrainingData(
                    email_text=email_text,
                    subject=item["subject"] or None,
                    body_text=item["body_text"] or None,
                    label=label,
                    source=source,
                    created_at=datetime.utcnow(),
                )
            )
            existing_hashes.add(text_hash)
            stats["inserted"] += 1
            stats["labels"][label] += 1

        await session.commit()

    if trigger_retrain and stats["inserted"] > 0:
        # SCOPE: training reads ``training_data`` for ONE user. Applied's Gmail
        # access is the restricted ``gmail.readonly`` scope, whose user-data
        # policy permits training only a model personalized to a single end
        # user, with no co-mingling across users. This is a local script, so it
        # resolves to the ``LOCAL_USER_ID`` sentinel — which is also what makes
        # it harmless if someone aims it at a production DATABASE_URL: it
        # matches no rows there instead of pooling every tenant's mail.
        # See ``setfit_model.CrossUserTrainingError``.
        from jobtracker.classifier.setfit_model import resolve_training_user_id

        classifier = get_classifier()
        training_user_id = resolve_training_user_id()
        if await classifier._setfit.should_retrain(user_id=training_user_id):
            await classifier.retrain_setfit(user_id=training_user_id)
            stats["retrain_triggered"] = True

    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import labeled JSONL into training_data")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "data" / "external" / "mock_training_data.jsonl",
    )
    parser.add_argument("--source", type=str, default="mock_seed")
    parser.add_argument(
        "--trigger-retrain",
        action="store_true",
        help="Retrain SetFit after import if thresholds are met",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stats = asyncio.run(import_jsonl(args.input, args.source, args.trigger_retrain))

    print(f"input_rows={stats['total_rows']}")
    print(f"inserted={stats['inserted']}")
    print(f"skipped_duplicate={stats['skipped_duplicate']}")
    print(f"skipped_invalid={stats['skipped_invalid']}")
    print(f"retrain_triggered={stats['retrain_triggered']}")

    for label, count in sorted(stats["labels"].items()):
        print(f"label_{label}={count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
