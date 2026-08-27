#!/usr/bin/env python3
"""Run the ten-thousand-message corpus through the whole product and report.

One command::

    cd backend && python ../scripts/run_independent_corpus.py

Exit status is 0 always — this is an INSTRUMENT, not a gate. The gate is
``backend/tests/test_independent_corpus.py``, which pins every number here so a
regression cannot land quietly.

What it prints, and how to read it
----------------------------------
Two scores, because a message can pass one and fail the other:

* **CLASSIFIER** — the verdict, over what production would actually hand it.
  Three buckets, never two: correct, WRONG (confident and not right), and
  ABSTAINED (below the review floor, so the product says nothing). Abstention is
  the safe failure and averaging it with being wrong hides the distinction that
  matters most.
* **BOARD** — the cards those verdicts produce, after a day-by-day replay
  through the real sync against a real database.

Read the headline accuracy WITH the corpus. It is 18% adversarial by
construction, so the number describes behaviour under stress, not what a user's
own inbox would produce. The per-family table is the useful part.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# The models bind to an in-memory SQLite when the environment says test, and the
# board half stands one up. Set before the app is imported, as conftest does.
os.environ.setdefault("JOBTRACKER_ENVIRONMENT", "test")

from tests.corpus_independent.generate import digest, generate, stats  # noqa: E402
from tests.corpus_independent.harness import (  # noqa: E402
    classify_all,
    rank,
    replay,
    score_board,
    score_classifier,
)


async def _board(verdicts, cases):
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel
    from sqlmodel.ext.asyncio.session import AsyncSession

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            replayed = await replay(session, verdicts)
    finally:
        await engine.dispose()
    return score_board(replayed, cases)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20260822)
    parser.add_argument(
        "--classifier-only",
        action="store_true",
        help="skip the board replay, which is where the wall clock goes",
    )
    args = parser.parse_args()

    cases = generate(args.seed)
    # From the BUILDER, not read back off the mail. See ``generate.Stats``.
    st = stats(args.seed)
    print(f"\n{'=' * 74}")
    print(f"independent corpus — {len(cases)} invented emails, seed {args.seed}")
    print(f"{'=' * 74}")
    print(f"  digest            {digest(cases)[:16]}")
    print(f"  adversarial       {st.adversarial} ({st.adversarial / st.messages:.1%}) — "
          "written to defeat the classifier, not merely hard")
    print(f"  companies         {st.companies}, no two sharing a leading word")

    t0 = time.time()
    verdicts = classify_all(cases)
    cs = score_classifier(verdicts)
    print(f"\n{'-' * 74}\nCLASSIFIER  ({time.time() - t0:.1f}s)\n{'-' * 74}")
    print(f"  correct           {cs.correct:6d}  ({cs.accuracy:.2%})")
    print(f"  wrong             {cs.wrong:6d}  — a confident verdict that is not right")
    print(f"  abstained         {cs.abstained:6d}  — below the review floor; the product says nothing")
    print(f"  auto-filed        {cs.auto_filed:6d}  of which WRONG {cs.auto_filed_wrong} "
          f"({cs.auto_filed_wrong / cs.auto_filed:.1%})")

    print(f"\n  {'family':30s} {'correct':>13s} {'wrong':>7s} {'abstained':>10s}")
    for family in sorted(cs.by_family):
        c = cs.by_family[family]
        total = c["correct"] + c["wrong"] + c["abstained"]
        flag = "  <-- ALL WRONG" if c["wrong"] == total else ""
        print(f"  {family:30s} {c['correct']:6d}/{total:<6d} {c['wrong']:7d} "
              f"{c['abstained']:10d}{flag}")

    if args.classifier_only:
        return 0

    t0 = time.time()
    bs = asyncio.run(_board(verdicts, cases))
    print(f"\n{'-' * 74}\nBOARD  ({time.time() - t0:.1f}s, replayed in day-sized batches)\n{'-' * 74}")
    print(f"  cards produced    {bs.cards:6d}")
    print(f"  SPLIT             {bs.splits:6d}  one application over several cards")
    print(f"  MERGE             {bs.merges:6d}  several applications on one card")
    print(f"  NOISE ON A CARD   {bs.noise_on_card:6d}  mail that must mint nothing, on a card")
    print(f"  SHOULD BE REVIEW  {bs.wrong_review:6d}  role-less mail at a multi-application employer, guessed")
    print(f"  UPDATE STRANDED   {bs.update_opened_a_card:6d}  an update that never reached the card it belongs to")
    print(f"  WRONG STAGE       {bs.wrong_status:6d}  the right card, showing the wrong stage")
    print(f"  WRONG COMPANY     {bs.company_wrong:6d}  the card names an employer nobody applied to")
    print(f"  WRONG ROLE        {bs.role_wrong:6d}  the card names a job nobody applied for")
    print(f"  LOST              {bs.lost:6d}  about a real application, and reached NOTHING")
    print(f"  DROPPED           {bs.dropped:6d}  under the review floor; counted, but on no screen")
    print("\n  not failures — the designed answer, or an absence rather than a lie:")
    print(f"  titles graded     {bs.titles_graded:6d}  of {bs.cards} cards; the denominator for WRONG COMPANY")
    print(f"  roles graded      {bs.roles_graded:6d}  the smaller denominator for WRONG ROLE — see Case.role_truth")
    print(f"  company drift     {bs.company_drift:6d}  same employer, differently spelled")
    print(f"  ROLE MISSING      {bs.role_missing:6d}  ground truth names a role, the card is blank")
    print(f"  UPDATE HELD       {bs.update_held_for_review:6d}  an update the product asked about instead of filing")
    if bs.total:
        print("\n  ranked:")
        for mode, family, n in rank(bs)[:15]:
            print(f"    {mode:28s} {family:28s} {n}")
        seen: set[str] = set()
        print("\n  one example per mode:")
        for f in bs.failures:
            if f.mode in seen:
                continue
            seen.add(f.mode)
            print(f"    [{f.mode}] family={f.family}\n      {f.detail}\n"
                  f"      messages: {', '.join(f.message_ids[:5])}")
    else:
        print("\n  nothing. Every application landed on exactly its own card, and\n"
              "  every message about one reached a card or the queue.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
