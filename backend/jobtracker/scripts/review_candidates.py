#!/usr/bin/env python3
"""
Manual Review Terminal UI
=========================

Interactive terminal tool for reviewing auto-labeled candidates that
need human verification before import into the training database.

Shows each ambiguous candidate and lets you:
- Accept the auto-label (Enter)
- Assign a different label (1-8 keys)
- Skip (s)
- Quit and save progress (q)

Usage:
    python -m jobtracker.scripts.review_candidates [--input PATH]
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = _BACKEND_DIR / "data" / "processed"
CANDIDATES_FILE = OUTPUT_DIR / "candidates.jsonl"

# ---------------------------------------------------------------------------
# Label definitions
# ---------------------------------------------------------------------------

LABELS = [
    ("1", "applied", "Application submitted/confirmed"),
    ("2", "pending_application", "Pre-application / invite to apply"),
    ("3", "interview", "Interview scheduling or invitation"),
    ("4", "rejection", "Application rejected"),
    ("5", "offer", "Job offer received"),
    ("6", "assessment", "Technical assessment / test"),
    ("7", "follow_up", "Follow-up communication"),
    ("8", "other", "Not job-related"),
]

LABEL_MAP = {key: label for key, label, _ in LABELS}


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def clear_screen():
    os.system("clear" if os.name != "nt" else "cls")


def color(text: str, code: str) -> str:
    """ANSI color wrapper."""
    return f"\033[{code}m{text}\033[0m"


def print_header(reviewed: int, total: int, stats: dict[str, int]):
    """Print the review status header."""
    print(color("=" * 70, "1;36"))
    print(color("  JobTracker — Manual Label Review", "1;36"))
    print(color("=" * 70, "1;36"))
    print(f"  Progress: {reviewed}/{total} reviewed")
    if stats:
        parts = [f"{k}: {v}" for k, v in sorted(stats.items()) if v > 0]
        print(f"  Labels assigned: {', '.join(parts)}")
    print(color("-" * 70, "36"))
    print()


def print_candidate(candidate: dict, index: int, total: int):
    """Print a candidate for review."""
    subject = candidate.get("subject", "(no subject)")
    body = candidate.get("body_text", "")
    source = candidate.get("source", "unknown")
    auto_label = candidate.get("auto_label", "?")
    confidence = candidate.get("confidence", 0)

    print(f"  [{index + 1}/{total}]  Source: {color(source, '33')}")
    print(f"  Auto-label: {color(auto_label, '1;33')}  (confidence: {confidence:.2f})")
    print()
    if subject:
        print(f"  Subject: {color(subject[:100], '1;37')}")
    print()

    # Show body preview (max 400 chars, wrapped)
    preview = body[:400]
    if len(body) > 400:
        preview += "..."
    for line in preview.split("\n")[:12]:
        print(f"  │ {line[:80]}")
    print()


def print_label_options():
    """Print the label option menu."""
    print(color("  Labels:", "1;32"))
    for key, label, desc in LABELS:
        print(f"    {color(key, '1;33')} = {label:<22} {color(desc, '90')}")
    print()
    print(f"  {color('Enter', '1;33')} = Accept auto-label   "
          f"{color('s', '1;33')} = Skip   "
          f"{color('q', '1;33')} = Quit & save")
    print()


# ---------------------------------------------------------------------------
# Core review loop
# ---------------------------------------------------------------------------

def load_candidates(filepath: Path) -> list[dict]:
    """Load candidates from JSONL file."""
    candidates = []
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                candidates.append(json.loads(line))
    return candidates


def save_candidates(candidates: list[dict], filepath: Path):
    """Save all candidates back to JSONL file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w") as f:
        for c in candidates:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")


def run_review(filepath: Path):
    """Run the interactive review session."""
    if not filepath.exists():
        print(f"Error: {filepath} not found.")
        print("Run first: python -m jobtracker.scripts.ingest_datasets")
        sys.exit(1)

    all_candidates = load_candidates(filepath)
    to_review = [c for c in all_candidates if c.get("needs_review", False)]

    if not to_review:
        print("No candidates need review! All are auto-verified.")
        print("Run: python -m jobtracker.scripts.import_to_db")
        return

    print(f"\nLoaded {len(all_candidates)} candidates, {len(to_review)} need review.\n")

    stats: dict[str, int] = defaultdict(int)
    reviewed = 0
    skipped = 0

    for i, candidate in enumerate(to_review):
        clear_screen()
        print_header(reviewed, len(to_review), stats)
        print_candidate(candidate, i, len(to_review))
        print_label_options()

        while True:
            try:
                choice = input("  Your choice: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                choice = "q"

            if choice == "q":
                # Save and quit
                save_candidates(all_candidates, filepath)
                print(f"\n  Saved! Reviewed {reviewed}, skipped {skipped}.")
                print(f"  Remaining: {len(to_review) - i} candidates.")
                print(f"  Re-run to continue, or import what's ready:")
                print(f"    python -m jobtracker.scripts.import_to_db")
                return

            elif choice == "s":
                skipped += 1
                break

            elif choice == "" or choice == "\n":
                # Accept auto-label
                candidate["needs_review"] = False
                stats[candidate["auto_label"]] += 1
                reviewed += 1
                break

            elif choice in LABEL_MAP:
                # Assign new label
                new_label = LABEL_MAP[choice]
                candidate["auto_label"] = new_label
                candidate["needs_review"] = False
                candidate["confidence"] = 1.0  # Manual = 100%
                stats[new_label] += 1
                reviewed += 1
                break

            else:
                print(color("  Invalid choice. Use 1-8, Enter, s, or q.", "31"))

    # All done
    save_candidates(all_candidates, filepath)
    clear_screen()
    print(color("=" * 70, "1;32"))
    print(color("  Review Complete!", "1;32"))
    print(color("=" * 70, "1;32"))
    print(f"  Reviewed: {reviewed}")
    print(f"  Skipped:  {skipped}")
    print()
    print("  Label distribution:")
    for label in sorted(stats.keys()):
        print(f"    {label:<22} {stats[label]}")
    print()
    print("  Next step:")
    print("    python -m jobtracker.scripts.import_to_db")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Manually review auto-labeled candidates",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=CANDIDATES_FILE,
        help="Path to candidates.jsonl",
    )
    args = parser.parse_args()
    run_review(args.input)


if __name__ == "__main__":
    main()
