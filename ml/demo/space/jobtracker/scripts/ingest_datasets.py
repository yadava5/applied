#!/usr/bin/env python3
"""
Dataset Ingestion Pipeline
==========================

Parses raw external dataset files into a unified intermediate format
(candidates.jsonl) with auto-labeling for the JobTracker classifier.

Datasets supported:
1. Berkeley Enron (category-labeled emails)
2. SpamAssassin Public Corpus (spam/ham)
3. Charlie9 Enron Intent Dataset (intent_pos/intent_neg)
4. Kaggle Job Application Emails (applied/rejection/interview/assessment)
5. Kaggle Application Rejection Emails (reject/not_reject)

Usage:
    python -m jobtracker.scripts.ingest_datasets [--data-dir PATH] [--output PATH]

Output:
    backend/data/processed/candidates.jsonl
"""

import argparse
import csv
import email
import hashlib
import json
import logging
import os
import re
import sys
from collections import defaultdict
from email import policy
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Add backend/ to sys.path so jobtracker imports work when run standalone
# ---------------------------------------------------------------------------
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from jobtracker.classifier.rules import get_rules_classifier  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_DIR = _BACKEND_DIR / "data" / "external"
OUTPUT_DIR = _BACKEND_DIR / "data" / "processed"
OUTPUT_FILE = OUTPUT_DIR / "candidates.jsonl"

# Class balance caps — prevent model bias
MAX_OTHER = 60
MAX_PER_JOB_CATEGORY = 30

# Quality filters
MIN_TEXT_LENGTH = 30
MAX_TEXT_LENGTH = 10_000

# Valid job-related labels (excluding needs_review)
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
# Candidate dataclass
# ---------------------------------------------------------------------------

def make_candidate(
    source: str,
    subject: str,
    body_text: str,
    sender: str = "",
    auto_label: str = "other",
    confidence: float = 0.0,
    needs_review: bool = True,
) -> Optional[dict]:
    """Create a candidate dict if it passes quality filters."""
    # Clean up whitespace
    subject = (subject or "").strip()
    body_text = (body_text or "").strip()

    combined = f"{subject}\n{body_text}".strip()
    if len(combined) < MIN_TEXT_LENGTH:
        return None
    if len(combined) > MAX_TEXT_LENGTH:
        body_text = body_text[: MAX_TEXT_LENGTH - len(subject) - 1]

    return {
        "source": source,
        "subject": subject,
        "body_text": body_text,
        "sender": sender.strip(),
        "auto_label": auto_label,
        "confidence": round(confidence, 3),
        "needs_review": needs_review,
    }


def content_hash(subject: str, body_text: str) -> str:
    """Dedup hash based on subject + first 200 chars of body."""
    key = f"{subject}|{body_text[:200]}"
    return hashlib.md5(key.encode("utf-8", errors="replace")).hexdigest()


# ===========================================================================
# Parser: Berkeley Enron
# ===========================================================================

# Berkeley category 1,5 = "Employment arrangements (job seeking, hiring,
# recommendations, etc)"
# In .cats files, format is: top_cat,sub_cat,frequency per line
BERKELEY_EMPLOYMENT_TOP = "1"
BERKELEY_EMPLOYMENT_SUB = "5"


def _parse_cats_file(cats_file: Path) -> list[tuple[str, str]]:
    """
    Parse a per-email .cats annotation file.

    Each line: top_category,sub_category,frequency
    Returns list of (top, sub) tuples.
    """
    categories: list[tuple[str, str]] = []
    if not cats_file.exists():
        return categories

    try:
        for line in cats_file.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) >= 2:
                top = parts[0].strip()
                sub = parts[1].strip()
                categories.append((top, sub))
    except Exception:
        pass

    return categories


def _is_employment_email(cats_file: Path) -> bool:
    """Check if a .cats file contains the employment category (1,5)."""
    categories = _parse_cats_file(cats_file)
    return any(
        top == BERKELEY_EMPLOYMENT_TOP and sub == BERKELEY_EMPLOYMENT_SUB
        for top, sub in categories
    )


def _extract_email_parts(filepath: Path) -> tuple[str, str, str]:
    """Extract subject, body_text, sender from a raw .txt email file."""
    try:
        raw = filepath.read_text(errors="replace")
        msg = email.message_from_string(raw, policy=policy.default)
        subject = str(msg.get("Subject", ""))
        sender = str(msg.get("From", ""))
        body = msg.get_body(preferencelist=("plain",))
        body_text = body.get_content() if body else ""
        return subject, body_text, sender
    except Exception:
        # Fallback: treat entire file as body
        try:
            raw = filepath.read_text(errors="replace")
            return "", raw[:5000], ""
        except Exception:
            return "", "", ""


def parse_berkeley_enron(data_dir: Path) -> list[dict]:
    """
    Parse Berkeley-labeled Enron emails.

    The dataset structure is:
      enron_with_categories/<1-8>/<id>.txt  (email)
      enron_with_categories/<1-8>/<id>.cats (per-email category annotations)

    Strategy:
    - Category 1,5 (Employment) → run through rules engine → auto-label
    - All other categories → auto-label as 'other'
    """
    enron_dir = data_dir / "enron_berkeley"
    if not enron_dir.exists():
        logger.warning("Berkeley Enron not found at %s — skipping", enron_dir)
        return []

    logger.info("Parsing Berkeley Enron from %s", enron_dir)

    # The tar extracts into enron_with_categories/ subfolder
    inner_dir = enron_dir / "enron_with_categories"
    if not inner_dir.exists():
        inner_dir = enron_dir  # fallback if extracted flat

    rules = get_rules_classifier()
    candidates = []
    employment_count = 0
    other_count = 0

    # Find all .txt email files (skip categories.txt description file)
    email_files = sorted(inner_dir.rglob("*.txt"))
    email_files = [
        f for f in email_files
        if f.name != "categories.txt"
        and f.name != "enron_categories.txt"
        and f.name != "enron_with_categories.txt"
    ]

    logger.info("  Found %d email files", len(email_files))

    for filepath in email_files:
        # Check for corresponding .cats file
        cats_file = filepath.with_suffix(".cats")
        is_employment = _is_employment_email(cats_file) if cats_file.exists() else False

        subject, body_text, sender = _extract_email_parts(filepath)

        if is_employment:
            employment_count += 1
            # Run through rules engine for auto-labeling
            rules_result = rules.classify(subject, body_text, sender)
            label = rules_result.category.value
            conf = rules_result.confidence

            if label == "other":
                # Rules didn't find job patterns — still useful for review
                candidate = make_candidate(
                    source="berkeley_enron_employment",
                    subject=subject,
                    body_text=body_text,
                    sender=sender,
                    auto_label="other",
                    confidence=0.50,
                    needs_review=True,  # employment-tagged but rules says other → worth reviewing
                )
            elif conf >= 0.85:
                candidate = make_candidate(
                    source="berkeley_enron_employment",
                    subject=subject,
                    body_text=body_text,
                    sender=sender,
                    auto_label=label,
                    confidence=conf,
                    needs_review=False,
                )
            else:
                candidate = make_candidate(
                    source="berkeley_enron_employment",
                    subject=subject,
                    body_text=body_text,
                    sender=sender,
                    auto_label=label,
                    confidence=conf,
                    needs_review=True,
                )

            if candidate:
                candidates.append(candidate)
        else:
            # Non-employment → 'other' (strong negative)
            other_count += 1
            candidate = make_candidate(
                source="berkeley_enron_other",
                subject=subject,
                body_text=body_text,
                sender=sender,
                auto_label="other",
                confidence=0.90,
                needs_review=False,
            )
            if candidate:
                candidates.append(candidate)

    logger.info(
        "  Berkeley Enron: %d employment, %d other → %d candidates",
        employment_count,
        other_count,
        len(candidates),
    )
    return candidates


# ===========================================================================
# Parser: SpamAssassin
# ===========================================================================


def parse_spamassassin(data_dir: Path) -> list[dict]:
    """
    Parse SpamAssassin corpus.

    spam/ → auto-label 'other' (confidence 0.95)
    ham/  → auto-label 'other' (confidence 0.80)
    """
    sa_dir = data_dir / "spamassassin"
    if not sa_dir.exists():
        logger.warning("SpamAssassin not found at %s — skipping", sa_dir)
        return []

    logger.info("Parsing SpamAssassin from %s", sa_dir)
    candidates = []

    for subdir, conf, src_tag in [
        ("spam", 0.95, "spamassassin_spam"),
        ("ham", 0.80, "spamassassin_ham"),
    ]:
        folder = sa_dir / subdir
        if not folder.exists():
            continue

        count = 0
        for filepath in sorted(folder.iterdir()):
            if filepath.name.startswith(".") or filepath.is_dir():
                continue

            subject, body_text, sender = _extract_email_parts(filepath)
            candidate = make_candidate(
                source=src_tag,
                subject=subject,
                body_text=body_text,
                sender=sender,
                auto_label="other",
                confidence=conf,
                needs_review=False,
            )
            if candidate:
                candidates.append(candidate)
                count += 1

        logger.info("  SpamAssassin %s: %d candidates", subdir, count)

    return candidates


# ===========================================================================
# Parser: Charlie9 Enron Intent Dataset
# ===========================================================================


def parse_charlie9_intent(data_dir: Path) -> list[dict]:
    """
    Parse Charlie9 intent dataset.

    The dataset has two plain text files (one sentence per line):
      intent_pos — sentences requiring action/response
      intent_neg — sentences not requiring action

    intent_pos → auto-label 'follow_up' (needs review)
    intent_neg → auto-label 'other'
    """
    c9_dir = data_dir / "charlie9_intent"
    pos_file = c9_dir / "intent_pos"
    neg_file = c9_dir / "intent_neg"

    if not pos_file.exists() and not neg_file.exists():
        # Fallback: check for the old CSV format
        csv_file = c9_dir / "verified_dataset.csv"
        if csv_file.exists():
            return _parse_charlie9_csv(csv_file)
        logger.warning("Charlie9 Intent not found at %s — skipping", c9_dir)
        return []

    logger.info("Parsing Charlie9 Intent from %s", c9_dir)
    candidates = []
    pos_count = 0
    neg_count = 0

    # Parse intent_pos → follow_up
    if pos_file.exists():
        for line in pos_file.read_text(errors="replace").splitlines():
            text = line.strip()
            if not text:
                continue
            pos_count += 1
            candidate = make_candidate(
                source="charlie9_intent_pos",
                subject="",
                body_text=text,
                auto_label="follow_up",
                confidence=0.70,
                needs_review=True,
            )
            if candidate:
                candidates.append(candidate)

    # Parse intent_neg → other
    if neg_file.exists():
        for line in neg_file.read_text(errors="replace").splitlines():
            text = line.strip()
            if not text:
                continue
            neg_count += 1
            candidate = make_candidate(
                source="charlie9_intent_neg",
                subject="",
                body_text=text,
                auto_label="other",
                confidence=0.80,
                needs_review=False,
            )
            if candidate:
                candidates.append(candidate)

    logger.info(
        "  Charlie9 Intent: %d pos (follow_up), %d neg (other) → %d candidates",
        pos_count,
        neg_count,
        len(candidates),
    )
    return candidates


def _parse_charlie9_csv(csv_file: Path) -> list[dict]:
    """Fallback parser for CSV format of Charlie9 dataset."""
    logger.info("Parsing Charlie9 Intent (CSV) from %s", csv_file)
    candidates = []
    pos_count = 0
    neg_count = 0

    with open(csv_file, "r", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            text = row.get("sentence", row.get("text", "")).strip()
            intent = row.get("intent", row.get("label", "")).strip().lower()

            if not text:
                continue

            if "pos" in intent or intent == "1":
                pos_count += 1
                candidate = make_candidate(
                    source="charlie9_intent_pos",
                    subject="",
                    body_text=text,
                    auto_label="follow_up",
                    confidence=0.70,
                    needs_review=True,
                )
            else:
                neg_count += 1
                candidate = make_candidate(
                    source="charlie9_intent_neg",
                    subject="",
                    body_text=text,
                    auto_label="other",
                    confidence=0.80,
                    needs_review=False,
                )

            if candidate:
                candidates.append(candidate)

    logger.info(
        "  Charlie9 Intent (CSV): %d pos, %d neg → %d candidates",
        pos_count,
        neg_count,
        len(candidates),
    )
    return candidates


# ===========================================================================
# Parser: Kaggle Job Application Emails
# ===========================================================================

# Regex patterns for auto-labeling the Kaggle job application emails
_KAGGLE_REJECTION_RE = re.compile(
    r"unfortunately|regret to inform|not (been )?selected|"
    r"moved forward with other|not moving forward|decided not to proceed|"
    r"will not be (moving|proceeding)|position has been filled",
    re.I,
)
_KAGGLE_INTERVIEW_RE = re.compile(
    r"interview|schedule.*(call|meet)|invite you to.*(discuss|chat|speak)|"
    r"next (round|step|stage).*process|phone screen",
    re.I,
)
_KAGGLE_OFFER_RE = re.compile(
    r"pleased to offer|extend.*(an offer|offer)|congratulations.*offer|"
    r"offer letter|welcome aboard",
    re.I,
)
_KAGGLE_ASSESSMENT_RE = re.compile(
    r"assessment|coding (test|challenge)|technical (screen|test)|"
    r"take-home|hackerrank|codility|complete.*test|online test",
    re.I,
)
_KAGGLE_APPLIED_RE = re.compile(
    r"(received|got) your application|thank you for applying|"
    r"application (was )?(sent|submitted|received)|we.ve got your application|"
    r"confirm.*application|applied to",
    re.I,
)


def _classify_kaggle_job_email(subject: str, body: str) -> tuple[str, float]:
    """Classify a Kaggle job email using regex patterns.

    Returns (label, confidence).
    """
    text = f"{subject} {body}"

    # Order matters: more specific first
    if _KAGGLE_OFFER_RE.search(text):
        return "offer", 0.90
    if _KAGGLE_ASSESSMENT_RE.search(text):
        return "assessment", 0.85
    if _KAGGLE_INTERVIEW_RE.search(text):
        return "interview", 0.85
    if _KAGGLE_REJECTION_RE.search(text):
        return "rejection", 0.90
    if _KAGGLE_APPLIED_RE.search(text):
        return "applied", 0.90

    # Fallback: these are all job-application emails, run through rules
    return "applied", 0.60


def parse_kaggle_job_emails(data_dir: Path) -> list[dict]:
    """
    Parse Kaggle Job Application Emails dataset.

    Columns: sender, subject, email_body, company
    Auto-labels via regex: applied, rejection, interview, assessment, offer
    """
    csv_file = data_dir / "kaggle_job_emails" / "job_app_confirmation_emails_anonymized.csv"
    if not csv_file.exists():
        logger.warning("Kaggle Job Emails not found at %s — skipping", csv_file)
        return []

    logger.info("Parsing Kaggle Job Application Emails from %s", csv_file)
    candidates = []
    label_counts: dict[str, int] = defaultdict(int)

    with open(csv_file, "r", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            subject = (row.get("subject", "") or "").strip()
            body = (row.get("email_body", "") or "").strip()
            sender = (row.get("sender", "") or "").strip()

            label, confidence = _classify_kaggle_job_email(subject, body)
            label_counts[label] += 1

            # High-confidence regex matches are auto-verified
            needs_review = confidence < 0.80

            candidate = make_candidate(
                source=f"kaggle_job_{label}",
                subject=subject,
                body_text=body,
                sender=sender,
                auto_label=label,
                confidence=confidence,
                needs_review=needs_review,
            )
            if candidate:
                candidates.append(candidate)

    label_summary = ", ".join(f"{k}: {v}" for k, v in sorted(label_counts.items()))
    logger.info("  Kaggle Job Emails: %d candidates (%s)", len(candidates), label_summary)
    return candidates


# ===========================================================================
# Parser: Kaggle Application Rejection Emails
# ===========================================================================


def parse_kaggle_rejection_emails(data_dir: Path) -> list[dict]:
    """
    Parse Kaggle Application Rejection Emails dataset.

    Columns: Email, Status (reject / not_reject)
    reject → 'rejection' (high confidence)
    not_reject → run through rules, fallback to 'applied'
    """
    csv_file = data_dir / "kaggle_rejection_emails" / "Rejection Data - Sheet1.csv"
    if not csv_file.exists():
        logger.warning("Kaggle Rejection Emails not found at %s — skipping", csv_file)
        return []

    logger.info("Parsing Kaggle Rejection Emails from %s", csv_file)
    candidates = []
    reject_count = 0
    not_reject_count = 0

    rules = get_rules_classifier()

    with open(csv_file, "r", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            email_text = (row.get("Email", "") or "").strip()
            status = (row.get("Status", "") or "").strip().lower()

            if not email_text:
                continue

            # Split first line as pseudo-subject
            lines = email_text.split("\n", 1)
            pseudo_subject = lines[0][:200] if lines else ""
            body = lines[1] if len(lines) > 1 else email_text

            if status == "reject":
                reject_count += 1
                candidate = make_candidate(
                    source="kaggle_rejection",
                    subject=pseudo_subject,
                    body_text=body,
                    auto_label="rejection",
                    confidence=0.95,
                    needs_review=False,  # Human-labeled as reject
                )
            else:
                not_reject_count += 1
                # These are job-related but not rejections — use rules
                rules_result = rules.classify(pseudo_subject, body, "")
                label = rules_result.category.value
                conf = rules_result.confidence

                if label == "other" or label == "needs_review":
                    # It's a job email (came from job inbox), default to applied
                    label = "applied"
                    conf = 0.70

                candidate = make_candidate(
                    source="kaggle_not_reject",
                    subject=pseudo_subject,
                    body_text=body,
                    auto_label=label,
                    confidence=conf,
                    needs_review=conf < 0.80,
                )

            if candidate:
                candidates.append(candidate)

    logger.info(
        "  Kaggle Rejection: %d reject, %d not_reject → %d candidates",
        reject_count,
        not_reject_count,
        len(candidates),
    )
    return candidates


# ===========================================================================
# Deduplication & Balancing
# ===========================================================================


def deduplicate(candidates: list[dict]) -> list[dict]:
    """Remove exact-ish duplicates based on content hash."""
    seen: set[str] = set()
    unique = []
    for c in candidates:
        h = content_hash(c["subject"], c["body_text"])
        if h not in seen:
            seen.add(h)
            unique.append(c)
    removed = len(candidates) - len(unique)
    if removed:
        logger.info("Deduplication: removed %d duplicates", removed)
    return unique


def balance_classes(candidates: list[dict]) -> list[dict]:
    """
    Cap per-category counts to prevent class imbalance.

    Prioritizes needs_review=False (auto-labeled) first, then needs_review=True.
    Within each priority, keeps higher-confidence examples.
    """
    by_label: dict[str, list[dict]] = defaultdict(list)
    for c in candidates:
        by_label[c["auto_label"]].append(c)

    balanced = []
    for label, items in by_label.items():
        cap = MAX_OTHER if label == "other" else MAX_PER_JOB_CATEGORY

        # Sort: verified (needs_review=False) first, then by confidence desc
        items.sort(key=lambda x: (x["needs_review"], -x["confidence"]))

        selected = items[:cap]
        balanced.extend(selected)

        if len(items) > cap:
            logger.info(
                "  Capped '%s': %d → %d (dropped %d)",
                label,
                len(items),
                cap,
                len(items) - cap,
            )

    return balanced


# ===========================================================================
# Main Pipeline
# ===========================================================================


def run_ingestion(data_dir: Path, output_file: Path) -> list[dict]:
    """Run the full ingestion pipeline."""
    logger.info("=" * 60)
    logger.info("JobTracker External Dataset Ingestion")
    logger.info("=" * 60)
    logger.info("Data directory: %s", data_dir)

    # Phase A: Parse all datasets
    all_candidates = []
    all_candidates.extend(parse_berkeley_enron(data_dir))
    all_candidates.extend(parse_spamassassin(data_dir))
    all_candidates.extend(parse_charlie9_intent(data_dir))
    all_candidates.extend(parse_kaggle_job_emails(data_dir))
    all_candidates.extend(parse_kaggle_rejection_emails(data_dir))

    if not all_candidates:
        logger.warning(
            "No candidates found! Make sure you've run:\n"
            "  bash scripts/download_datasets.sh"
        )
        return []

    logger.info("Total raw candidates: %d", len(all_candidates))

    # Phase B: Deduplicate
    all_candidates = deduplicate(all_candidates)
    logger.info("After dedup: %d", len(all_candidates))

    # Phase C: Balance classes
    all_candidates = balance_classes(all_candidates)
    logger.info("After balancing: %d", len(all_candidates))

    # Write output
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        for c in all_candidates:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    # Summary
    label_counts: dict[str, int] = defaultdict(int)
    review_count = 0
    for c in all_candidates:
        label_counts[c["auto_label"]] += 1
        if c["needs_review"]:
            review_count += 1

    logger.info("")
    logger.info("=" * 60)
    logger.info("Ingestion Summary")
    logger.info("=" * 60)
    logger.info("Output: %s", output_file)
    logger.info("Total candidates: %d", len(all_candidates))
    logger.info("Needs manual review: %d", review_count)
    logger.info("Auto-verified: %d", len(all_candidates) - review_count)
    logger.info("")
    logger.info("Label distribution:")
    for label in sorted(label_counts.keys()):
        logger.info("  %-25s %d", label, label_counts[label])

    return all_candidates


def main():
    parser = argparse.ArgumentParser(
        description="Parse external datasets into candidates.jsonl",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DATA_DIR,
        help="Directory containing downloaded datasets",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_FILE,
        help="Path for candidates.jsonl output",
    )
    args = parser.parse_args()

    candidates = run_ingestion(args.data_dir, args.output)
    if not candidates:
        sys.exit(1)

    needs_review = sum(1 for c in candidates if c["needs_review"])
    if needs_review > 0:
        print(f"\n→ {needs_review} candidates need manual review.")
        print("  Run: python -m jobtracker.scripts.review_candidates")
    else:
        print("\n→ All candidates auto-verified.")
        print("  Run: python -m jobtracker.scripts.import_to_db")


if __name__ == "__main__":
    main()
