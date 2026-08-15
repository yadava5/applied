#!/usr/bin/env python3
"""Regenerate the adversarial mail corpus and report where identity breaks.

One command:

    cd backend && python ../scripts/run_mail_corpus.py

Prints, for each layer, the ranked failure table with counts and a
representative example per mode. Exit status is 0 always — this is an
instrument, not a gate. The gate is ``backend/tests/test_adversarial_corpus.py``,
which pins the counts so a regression cannot land silently.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Run from anywhere: the backend package is the import root.
_BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from tests.corpus.generator import generate  # noqa: E402
from tests.corpus.harness import (  # noqa: E402
    Score,
    rank,
    score_in_scan,
    score_incremental,
)


def _report(score: Score, cases_n: int, verbose: bool) -> None:
    print(f"\n{'=' * 74}")
    print(f"LAYER: {score.layer}")
    print(f"{'=' * 74}")
    print(f"  corpus            {cases_n} emails")
    print(f"  cleared the gate  {score.gated_items} "
          f"(AUTO_FILE_GATE + lifecycle category + nameable employer)")
    print(f"  cards produced    {score.cards}")
    print()
    print(f"  SPLIT   (one application → several cards)   {score.splits}")
    print(f"  MERGE   (several applications → one card)   {score.merges}")
    print(f"  MISATTRIBUTED (right count, wrong card)     {score.misattributed}")
    print(f"  NOISE ON A CARD                             {score.minted_from_noise}")
    print(f"  SHOULD HAVE GONE TO REVIEW                  {score.wrong_review}")
    print(f"  {'-' * 44}")
    print(f"  TOTAL FAILURES                              {score.total}")

    table = rank(score)
    if table:
        print("\n  ranked by frequency:")
        print(f"    {'mode':<26} {'axis':<26} {'count':>5}")
        for mode, axis, n in table:
            print(f"    {mode:<26} {axis:<26} {n:>5}")

    seen: set[str] = set()
    examples = [f for f in score.failures if not (f.mode in seen or seen.add(f.mode))]
    if examples:
        print("\n  representative example per mode:")
        for f in examples:
            print(f"    [{f.mode}] axis={f.axis}")
            print(f"      {f.detail}")
            print(f"      messages: {', '.join(f.message_ids[:6])}")

    if verbose:
        print("\n  all failures:")
        for f in score.failures:
            print(f"    [{f.mode}] {f.axis}: {f.detail}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=20260815)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    cases = generate(args.seed)
    print(f"adversarial mail corpus — seed {args.seed}, {len(cases)} invented emails")

    by_axis: dict[str, int] = {}
    for c in cases:
        by_axis[c.axis] = by_axis.get(c.axis, 0) + 1
    print("\naxes:")
    for axis, n in sorted(by_axis.items()):
        print(f"  {axis:<28} {n:>4}")

    for score in (score_in_scan(cases), score_incremental(cases)):
        # The self-check the whole report rests on. A corpus that never clears
        # the gate produces zero failures and looks perfect; this estate has a
        # documented history of gates that could not fire.
        if score.gated_items == 0:
            print("\nFATAL: no message cleared the auto-file gate. "
                  "The harness is measuring nothing; every number below is void.")
            return 2
        _report(score, len(cases), args.verbose)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
