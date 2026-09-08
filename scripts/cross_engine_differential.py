#!/usr/bin/env python3
"""Run BOTH rules engines over one corpus and red on a category or a confidence divergence (#427 item 2).

This repository ships the layer-1 rules classifier twice:

  * ``backend/jobtracker/classifier/rules.py``  -- Python, and the one running
    in the hosted product.
  * ``apps/web/lib/demo/rulesLayer.ts``          -- a TypeScript port that runs
    live in the visitor's tab on ``/demo/inbox`` and ``/import``.

Nothing compared them on the inputs where they differ. ``#427`` filed two
parity defects and attributed the miss to ``test_confidence_gate_lockstep.py``
"comparing confidence" -- that file is an AST census of ``0.85`` literals and
never invokes either engine, so the gap was not a weak comparison but the
absence of one. This script is the comparison.

WHY IT IS A PYTHON DRIVER THAT SPAWNS NODE, and not the reverse or a shared
script. Three reasons, in the order they decided it:

  1. Production runs Python. The reference and the subject are not
     interchangeable, and the driver reads better as "the engine that ships,
     compared against its port" than as the other way round.
  2. The corpus is Python-side data (``backend/data/evaluation/*.jsonl``) and
     the reference engine is an in-process import from ``backend/``. The node
     half needs a spawned process either way, because its module graph needs
     ``apps/web`` as the working directory for ``node_modules`` resolution.
  3. There is exactly ONE definition of "diverged", and it lives here. A
     shared script with an assertion on each side is two definitions that can
     drift, which is the defect this file exists to catch, one level up.

WHY IT IS NOT A TEST IN EITHER SUITE, and this is the load-bearing decision.
``pnpm test:unit`` runs under ``frontend-ci.yml``, which sets up node and no
Python. ``pytest`` runs under ``backend-ci.yml``, which sets up Python and no
node. In either suite a differential has two available shapes and both are
defects: fail hard because the other toolchain is absent, reddening a check for
a reason that is not a divergence; or detect the absence and skip -- and a
skipped test is collected, reported and GREEN. This repository has already paid
for both shapes. So the file is a standalone script, collected by neither
runner (it is not ``test_*.py``), and invoked explicitly from the one job that
has both toolchains installed: ``.github/workflows/e2e-ci.yml``.

IT CANNOT BE A REQUIRED STATUS CHECK, and nobody should count it as one.
``e2e-ci.yml`` is path-filtered, and per ``#864`` a path-filtered workflow
cannot be made a required context -- a required context that never reports
wedges the pull request. So this runs on every change that touches either
engine and is still not required. That is ``#864``'s gap rather than this
one's, and it is stated here so the differential is not mistaken for a gate it
is not.

THE THIRD IMPLEMENTATION IS OUT OF REACH, AND IT IS ALREADY KNOWN TO DIVERGE.
This is the honest headline of this file's coverage: it differences TWO of the
three ports, and the one it cannot reach is the one #427 names as untested.

``ml/browser/site/app.js`` cannot be loaded by this harness. Three independent
blockers, measured rather than assumed -- ``node -e "await import('./app.js')"``
from ``ml/browser/site`` fails on the first of them:

  * ``app.js:16`` imports from ``https://cdn.jsdelivr.net/...`` at the top
    level, and Node's ESM loader refuses a non-``file:``/``data:`` scheme
    (``ERR_UNSUPPORTED_ESM_URL_SCHEME``).
  * The file has ZERO ``export`` statements. ``rulesClassify`` (``:49``) is
    module-local, so there is nothing to import even with a loader that could.
  * ``app.js:22`` calls ``document.getElementById`` at the top level.

Reaching it means a browser -- Playwright -- or extracting its scorer into a
FOURTH copy, which is the defect this file exists to detect.

AND THE DATA BEING IDENTICAL DOES NOT MAKE THE BEHAVIOUR IDENTICAL, which is
the trap in the obvious reading. ``ml/browser/site/rules.json`` and
``apps/web/lib/demo/rules.json`` really are byte-identical, and
``backend/tests/test_the_veto_copy_cannot_drift.py`` and
``test_a_reference_does_not_outrank_a_report.py`` pin that. The SCORING still
differs: ``app.js:60`` tests every strong and weak pattern against the RAW
body, with no ``asserted_text`` mask, no quoted-history strip and no reflow,
where ``rules.py`` and ``rulesLayer.ts`` both mask first. Two engines reading
the same patterns through different preprocessing are not the same classifier.

The concrete instance, confirmed on this tree and owned by #928:
``be in touch (soon|shortly|if)`` is present in all three ports here. The ``if``
arm is DEAD in Python and TypeScript, because the mask removes the conditional
clause before matching, and LIVE in the browser port, which never masks. #928
deletes the arm from ``rules.py`` alone and deliberately does not propagate to
either ``rules.json`` -- removing it there is a real behaviour change, and
``test_the_two_json_ports_are_still_byte_identical`` makes it all-or-nothing
across both JSON copies. That decision is #928's, not this file's, and nothing
here widens it.

Usage::

    python3 scripts/cross_engine_differential.py            # from the repo root
    python3 scripts/cross_engine_differential.py --verbose  # print every verdict

    # Diagnostic only, and CI never passes it: answer "would the labelled set
    # alone have caught this?" by running it rather than by arguing about it.
    python3 scripts/cross_engine_differential.py --corpus labelled

Exit status::

    0  the engines agree, apart from the divergences recorded below
    1  a divergence
    2  the harness could not run, or could not prove it ran
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND = REPO_ROOT / "backend"
WEB = REPO_ROOT / "apps" / "web"

#: The labelled evaluation set. 96 cases, 8 labels x 12.
LABELLED_CORPUS = BACKEND / "data" / "evaluation" / "classifier_eval_v3.jsonl"

#: Hand-authored divergence bait: cases aimed at the seams where two
#: independent implementations of one spec drift. See the file's own `why`
#: field on every row.
#:
#: WHY BOTH AND NOT JUST THE EVAL SET. Measured, not assumed -- the mutation
#: controls in this commit's message were run against the 96 cases ALONE first
#: and then against 96 + bait. The eval corpus is a labelled ACCURACY set: it
#: samples the categories evenly and says nothing about the veto cap, the
#: anchored ATS match, the quoted-history floor, the reply-subject rung or the
#: reflow seam, because none of those is what it was built to grade. A gate
#: written against it alone is graded on a population that does not contain the
#: defect class.
BAIT_CORPUS = BACKEND / "data" / "evaluation" / "cross_engine_bait.jsonl"

#: The node worker, run with `apps/web` as its working directory.
TS_WORKER = WEB / "tests" / "unit" / "helpers" / "crossEngineWorker.mjs"

#: Per-corpus floors. A corpus smaller than its floor is a wrong path, not a
#: small corpus: one bad path in a multi-file load yields zero rows, exits 0,
#: and reads exactly like a clean run. The floors sit under the two files'
#: committed sizes (96 and 39) so that deleting a case does not have to touch
#: this line, and far enough under nothing that a truncated read survives.
CORPUS_FLOORS = {"labelled": 90, "bait": 30}

#: The reference engine must emit at least this many distinct categories across
#: the corpus. NOT a measurement: it is the floor below which the engine is not
#: classifying at all. A dead import, a worker returning a constant, or a
#: pattern table that failed to compile all present as "everything is `other`",
#: and `other` on both sides reads as perfect agreement. The eval corpus alone
#: carries 8 distinct labels, so 3 is wide of anything a working engine does.
MIN_DISTINCT_CATEGORIES = 3


class HarnessError(Exception):
    """The harness could not run, or could not prove that it ran.

    Distinct from a divergence, and it exits 2 rather than 1 so the workflow log
    separates "these two engines disagree" from "this measured nothing". Every
    guard in this file raises it: a missing corpus, a corpus under its floor, a
    node worker that exited non-zero, a mismatched case set, a vocabulary
    mismatch, and a reference engine that emitted too few distinct categories.
    None of them may degrade to a verdict -- an absent engine reporting `other`
    would read as agreement with a Python engine that also says `other`.
    """


@dataclass(frozen=True)
class Divergence:
    """One case the two engines answered differently."""

    case_id: str
    family: str
    py_category: str
    py_confidence: float
    ts_category: str
    ts_confidence: float

    @property
    def axis(self) -> str:
        axes = []
        if self.py_category != self.ts_category:
            axes.append("category")
        if self.py_confidence != self.ts_confidence:
            axes.append("confidence")
        return "+".join(axes)

    def render(self) -> str:
        return (
            f"  {self.case_id}  [{self.family}]  ({self.axis})\n"
            f"      python     {self.py_category} {self.py_confidence}\n"
            f"      typescript {self.ts_category} {self.ts_confidence}"
        )


@dataclass(frozen=True)
class Recorded:
    """A divergence that is known, owned and pinned to its exact values.

    IT IS A PIN, NOT A HOLE. An entry here does not suppress a case; it asserts
    the case diverges in EXACTLY this way. Three outcomes, and two of them are
    red:

      * diverges exactly as recorded  -> reported, not fatal
      * diverges differently          -> FAIL (the defect moved)
      * no longer diverges            -> FAIL (delete the entry; it is fixed)

    So an exception cannot rot into a permanent exemption, and it cannot be
    widened to swallow a second defect. Nothing here is a tolerance: no
    comparison in this file is loosened by any amount, ever. A tolerance
    sourced from the measurement it has to survive is worthless, and this
    repository has already paid for that lesson once.
    """

    py_category: str
    py_confidence: float
    ts_category: str
    ts_confidence: float
    reason: str


#: Divergences that are real, understood, and deliberately not fixed in the
#: commit that added this harness.
RECORDED_DIVERGENCES: dict[str, Recorded] = {
    # ------------------------------------------------------------------
    # THE PORT HAS NO `reflow_paragraphs`. Found by this harness on its
    # first run, and it is not the divergence #427 predicted.
    #
    # `rules.py:1902` runs `body = reflow_paragraphs(asserted_text(body))`
    # before scoring, and again on `own_text` before the refutation check at
    # `:2134`. `rulesLayer.ts` has no counterpart -- the identifier does not
    # occur in the file. `#430` records why Python has it: real `text/plain`
    # from an ATS is hard-wrapped at 72-78 columns, `.` does not match `\n`,
    # and nothing sets DOTALL, so every bounded gap in the pattern table
    # (`next step.{0,30}(assessment|test)`, ~60 of them) stops bridging a
    # wrap point the moment one exists. Measured there at the time: auto-files
    # fell from 244 to 212 on wrapped bodies.
    #
    # `backend/tests/test_wrap_invariance.py` pins that property for Python.
    # Nothing pins it for the port, which is exactly why it drifted.
    #
    # WHICH ENGINE IS WRONG: the TypeScript one. Python's behaviour is the
    # specified one, it is the engine that ships, and its invariance is
    # already under test. The port is missing a stage, not carrying an extra
    # one.
    #
    # WHY IT IS RECORDED HERE AND NOT FIXED IN THIS COMMIT. Porting
    # `reflow_paragraphs` changes the verdicts of a live, public,
    # unauthenticated surface (`/demo/inbox` and `/import` both classify in
    # the visitor's tab). That is an engine change and it needs its own
    # change, its own wrap-invariance cases on the port, and its own review --
    # not a rider on the commit that added the instrument which found it.
    # Widening scope silently is how a commit closes more than it says, and
    # this issue's own history records that exact objection being raised and
    # respected once already.
    #
    # IT COSTS A CATEGORY, NOT ONLY A CONFIDENCE. The assessment row below is
    # the worse of the two and was not predicted: Python reads a hard-wrapped
    # take-home as `assessment`, the port reads the same bytes as `applied`.
    # On `/demo/inbox` and `/import` that is the wrong row in the wrong column,
    # not a slightly softer number.
    #
    # NOT EVERY WRAPPED BODY DIVERGES, which is why the corpus keeps three
    # wrapped rows and their flat controls rather than one. `wrap/interview-
    # hard-wrapped` agrees on both axes: its patterns carry no gap across the
    # wrap point it happens to have. A family built from one wording would have
    # concluded either "wrapping always diverges" or "wrapping never does", and
    # both are false.
    #
    # OWNED BY: #427 item 2, until the port lands — and #427 MUST STAY OPEN
    # while these entries exist, or is superseded by an issue that inherits
    # them. This harness is the only thing in the repository that knows about
    # this drift; closing the issue because the differential landed would leave
    # two recorded defects pointing at a closed thread.
    #
    # The entries below pin the
    # MEASURED values, so the day someone ports the reflow, this harness goes
    # red and tells them to delete these lines.
    "wrap/rejection-hard-wrapped": Recorded(
        "rejection", 0.95, "rejection", 0.9,
        "rulesLayer.ts has no reflow_paragraphs; the wrap point breaks a bounded "
        "gap, costing 0.05 of confidence",
    ),
    "wrap/assessment-hard-wrapped": Recorded(
        "assessment", 0.6, "applied", 0.7,
        "rulesLayer.ts has no reflow_paragraphs; the wrap point breaks "
        "`next step.{0,30}(assessment|test)` and the CATEGORY changes",
    ),
}


def load_corpus(path: Path, kind: str) -> list[dict[str, Any]]:
    """Read one JSONL corpus into normalised cases.

    The two files have different shapes -- the eval set is labelled accuracy
    data (`body_text`, `sender_email`, `label`), the bait set is hand-authored
    (`body`, `sender`, `family`, `why`) -- and both are normalised here so the
    comparison below sees one shape.

    NOTHING IS COERCED. Neither corpus carries a null in a scored field
    (asserted below), so both engines are handed the bytes the file holds. A
    driver that quietly mapped `None` to `""` would be answering item 1's
    question on the engines' behalf instead of asking it.
    """
    if not path.exists():
        raise HarnessError(
            f"[harness] {kind} corpus is not at {path}.\n"
            f"          A missing corpus loads zero cases and reads like a pass, "
            f"so this is fatal rather than skipped."
        )

    cases: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if kind == "labelled":
            case_id = f"eval/{lineno:03d}/{row['label']}"
            subject, body, sender = row["subject"], row["body_text"], row["sender_email"]
            family = f"eval:{row.get('scenario_group', 'unknown')}"
        else:
            case_id = row["id"]
            subject, body, sender = row["subject"], row["body"], row["sender"]
            family = row["family"]

        for field, value in (("subject", subject), ("body", body)):
            if value is None:
                raise HarnessError(
                    f"[harness] {path.name}:{lineno} has a null {field}. Both engines "
                    f"accept a null today, but the corpora are declared non-null and "
                    f"a silent coercion here would hide which engine handles it how."
                )

        cases.append(
            {
                "id": case_id,
                "family": family,
                "subject": subject,
                "body": body,
                "sender": sender,
            }
        )
    return cases


def python_verdicts(cases: list[dict[str, Any]]) -> dict[str, tuple[str, float]]:
    """Classify every case with the shipped Python engine, in process."""
    sys.path.insert(0, str(BACKEND))
    try:
        from jobtracker.classifier.rules import get_rules_classifier
    except ImportError as err:  # pragma: no cover - environment, not logic
        raise HarnessError(
            f"[harness] could not import the Python engine from {BACKEND}: {err}\n"
            f"          Install backend/requirements-dev.txt. This is fatal rather "
            f"than skipped: an absent engine must not read as agreement."
        ) from err

    classifier = get_rules_classifier()
    out: dict[str, tuple[str, float]] = {}
    for case in cases:
        result = classifier.classify(case["subject"], case["body"], case["sender"])
        out[case["id"]] = (result.category.value, result.confidence)
    return out


def typescript_verdicts(cases: list[dict[str, Any]]) -> dict[str, tuple[str, float]]:
    """Classify every case with the TypeScript port, in one spawned node process."""
    if not TS_WORKER.exists():
        raise HarnessError(f"[harness] the node worker is not at {TS_WORKER}")

    payload = json.dumps(
        [
            {"id": c["id"], "subject": c["subject"], "body": c["body"], "sender": c["sender"]}
            for c in cases
        ]
    )
    proc = subprocess.run(
        ["node", str(TS_WORKER)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(WEB),
        check=False,
    )
    if proc.returncode != 0:
        raise HarnessError(
            f"[harness] the node worker exited {proc.returncode}. This is fatal: a "
            f"worker that cannot classify must not report a verdict, because "
            f"`other`/0.5 -- what an error would most naturally degrade to -- is "
            f"also what the Python engine answers for anything that does not "
            f"score, and the two would read as agreement.\n"
            f"--- worker stderr ---\n{proc.stderr.strip()}"
        )

    out: dict[str, tuple[str, float]] = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        out[row["id"]] = (row["category"], row["confidence"])
    return out


def assert_vocabularies_match() -> None:
    """The two engines must be able to emit the same set of categories.

    Python answers an ``EmailCategory`` and the port answers a bare string, so
    the comparison below normalises through ``.value``. That normalisation is
    exactly where a real divergence could hide -- a category present in one
    engine's table and absent from the other's would simply never be compared.
    So the vocabularies are asserted equal rather than assumed.

    ``needs_review`` and ``other`` are in ``EmailCategory`` but are not
    scoring categories: ``other`` is what either engine returns when nothing
    scores above zero, and ``needs_review`` is the pipeline's typed null and is
    never produced by the rules layer. Both are excluded on that basis, not
    because they were inconvenient.
    """
    sys.path.insert(0, str(BACKEND))
    from jobtracker.classifier.rules import PATTERNS

    python_scoring = {c.value for c in PATTERNS}
    ts_scoring = set(json.loads((WEB / "lib" / "demo" / "rules.json").read_text())["categories"])

    if python_scoring != ts_scoring:
        only_py = sorted(python_scoring - ts_scoring)
        only_ts = sorted(ts_scoring - python_scoring)
        raise HarnessError(
            "[harness] the engines do not share a category vocabulary, so a "
            "per-case comparison could not see a divergence in the categories "
            "that differ.\n"
            f"          only in rules.py:    {only_py}\n"
            f"          only in rules.json:  {only_ts}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--verbose", action="store_true", help="print every case's pair of verdicts"
    )
    # A DIAGNOSTIC, AND CI PASSES IT NEVER. It exists because "is the labelled
    # corpus on its own enough to catch a divergence?" is a question worth
    # being able to answer by running it rather than by arguing about it --
    # that experiment is what sized the corpus, and its result is in this
    # commit's message: a mutation to `REFUTED_CONFIDENCE` is GREEN on the 96
    # labelled cases and RED on 96 + bait. A CI step that passed
    # `--corpus labelled` would therefore be grading on a population MEASURED
    # not to contain the defect class this issue was filed about, so the
    # workflow step passes no flag at all and every partial run stamps itself.
    parser.add_argument(
        "--corpus",
        choices=("both", "labelled", "bait"),
        default="both",
        help="diagnostic: restrict the run to one corpus (CI always uses 'both')",
    )
    args = parser.parse_args()

    assert_vocabularies_match()

    selected = ("labelled", "bait") if args.corpus == "both" else (args.corpus,)
    per_corpus = {
        kind: load_corpus(LABELLED_CORPUS if kind == "labelled" else BAIT_CORPUS, kind)
        for kind in selected
    }
    for kind, rows in per_corpus.items():
        if len(rows) < CORPUS_FLOORS[kind]:
            raise HarnessError(
                f"[harness] the {kind} corpus loaded {len(rows)} cases, under its "
                f"floor of {CORPUS_FLOORS[kind]}. A wrong path collects zero "
                f"silently and exits 0, which is indistinguishable from a clean run."
            )
    cases = [c for kind in selected for c in per_corpus[kind]]

    # The marker goes on STDOUT, next to the verdict, not on stderr. A reader
    # (or a log scraper) looking at stdout would otherwise see "diverged 0 ...
    # OK" with nothing attached saying the population was cut in half.
    banner = (
        ""
        if args.corpus == "both"
        else f"  !! DIAGNOSTIC: {args.corpus} corpus ONLY — this is not the gate\n"
    )

    py = python_verdicts(cases)
    ts = typescript_verdicts(cases)

    # COUNT AND IDENTITY EQUALITY, not `>=`. A worker that dropped a case would
    # otherwise shrink the population being graded without changing the verdict.
    if set(py) != set(ts) or len(ts) != len(cases):
        missing = sorted(set(py) - set(ts))
        extra = sorted(set(ts) - set(py))
        raise HarnessError(
            f"[harness] the two engines answered different case sets: "
            f"{len(py)} python, {len(ts)} typescript, {len(cases)} sent.\n"
            f"          missing from typescript: {missing[:10]}\n"
            f"          unexpected from typescript: {extra[:10]}"
        )

    # PROVE THE INSTRUMENT RAN. "Everything is `other`" is what a dead engine,
    # a failed pattern compile and a stubbed worker all produce, and `other` on
    # both sides is perfect agreement.
    distinct = {cat for cat, _ in py.values()}
    if len(distinct) < MIN_DISTINCT_CATEGORIES:
        raise HarnessError(
            f"[harness] the reference engine emitted only {len(distinct)} distinct "
            f"categories ({sorted(distinct)}) across {len(cases)} cases. It is not "
            f"classifying, and a run in that state reports agreement it did not "
            f"measure."
        )

    divergences: list[Divergence] = []
    for case in cases:
        cid = case["id"]
        py_cat, py_conf = py[cid]
        ts_cat, ts_conf = ts[cid]
        if args.verbose:
            print(f"  {cid:<44} py={py_cat}/{py_conf}  ts={ts_cat}/{ts_conf}")
        # EXACT COMPARISON, ON BOTH AXES. Neither engine rounds: both read the
        # same five literals off the same tier table, both add 0.05 and clamp
        # with min(), and JSON round-trips an IEEE double without loss. There is
        # therefore no allowance to grant and none is granted. The engines'
        # own granularity is 0.05; any difference this finds is a real one.
        if py_cat != ts_cat or py_conf != ts_conf:
            divergences.append(
                Divergence(cid, case["family"], py_cat, py_conf, ts_cat, ts_conf)
            )

    diverged_ids = {d.case_id for d in divergences}
    unexpected: list[Divergence] = []
    matched_records: list[Divergence] = []
    failures: list[str] = []

    for d in divergences:
        rec = RECORDED_DIVERGENCES.get(d.case_id)
        if rec is None:
            unexpected.append(d)
        elif (rec.py_category, rec.py_confidence, rec.ts_category, rec.ts_confidence) == (
            d.py_category,
            d.py_confidence,
            d.ts_category,
            d.ts_confidence,
        ):
            matched_records.append(d)
        else:
            failures.append(
                f"  {d.case_id}: a RECORDED divergence moved.\n"
                f"      recorded  python {rec.py_category} {rec.py_confidence} / "
                f"typescript {rec.ts_category} {rec.ts_confidence}\n"
                f"      measured  python {d.py_category} {d.py_confidence} / "
                f"typescript {d.ts_category} {d.ts_confidence}\n"
                f"      Update the entry in RECORDED_DIVERGENCES, or fix the port."
            )

    present = {c["id"] for c in cases}
    for cid, rec in RECORDED_DIVERGENCES.items():
        # A recorded case the current selection does not contain is not
        # evidence that it stopped diverging. Only reachable under --corpus.
        if cid not in present:
            continue
        if cid not in diverged_ids:
            failures.append(
                f"  {cid}: recorded as diverging, and it no longer does.\n"
                f"      Recorded reason: {rec.reason}\n"
                f"      DELETE the entry from RECORDED_DIVERGENCES. Leaving it is "
                f"how a pin rots into a permanent exemption."
            )

    print()
    if banner:
        print(banner, end="")
    print(f"cross-engine differential: {len(cases)} cases")
    print("  corpus         "
          + " + ".join(f"{kind} ({len(per_corpus[kind])})" for kind in selected))
    print(f"  categories     {sorted(distinct)}")
    print(f"  agreed         {len(cases) - len(divergences)}")
    print(f"  diverged       {len(divergences)} "
          f"({len(matched_records)} recorded, {len(unexpected)} unexpected)")

    if matched_records:
        print("\nRECORDED divergences (known, owned, pinned to exact values):")
        for d in matched_records:
            print(d.render())
            print(f"      recorded: {RECORDED_DIVERGENCES[d.case_id].reason}")

    if unexpected:
        print("\nUNEXPECTED divergences:")
        for d in sorted(unexpected, key=lambda d: d.case_id):
            print(d.render())

    if failures:
        print("\nRECORD FAILURES:")
        for f in failures:
            print(f)

    if unexpected or failures:
        print(
            "\nFAILED. The two engines are one classifier written twice; a case "
            "they answer differently is a defect in one of them.\n"
            "Do not widen a comparison or add a tolerance to make this pass. "
            "Either fix the engine that is wrong, or record the divergence in "
            "RECORDED_DIVERGENCES with the issue that owns it."
        )
        return 1

    if banner:
        print("\nOK on this SUBSET only — a partial run is not a passing gate. "
              "Re-run without --corpus before believing it.")
        return 0
    print("\nOK: the engines agree on category and confidence for every case "
          "except those recorded above.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except HarnessError as err:
        print(err, file=sys.stderr)
        sys.exit(2)
