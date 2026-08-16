"""Run the mail corpus through the production classifier and report.

    PYTHONPATH=. python -m tests.corpus.mail_report

An INSTRUMENT, not a gate. It prints numbers and exits 0 whatever they are.
No threshold is asserted here or anywhere else in this change: the honest pass
rate is not yet known, and choosing a threshold to match today's output builds
a gate that cannot fail — the defect shape this corpus exists to hunt.

Scoring is THREE-WAY, not two
-----------------------------
``NEEDS_REVIEW`` is this codebase's typed null, not a category, and ``OTHER``
at 0.50 with no positive evidence is the rules layer's way of saying the same
thing. Abstaining is CORRECT behaviour when the classifier is genuinely unsure;
writing a verdict there would forge a human decision. So a case lands in one of

* **CORRECT**   the verdict matches the gold label.
* **ABSTAINED** the classifier asserted nothing: ``OTHER`` or ``NEEDS_REVIEW``,
  below the auto-file gate, with no category scoring above zero.
* **WRONG**     it asserted a different verdict.

A rule that abstains on 40% of authentic interview invitations is a finding
that must stay visible, so abstention is reported per class and never folded
into error. ``no_positive_evidence`` is recorded per case as well, so anyone
who dislikes the fold above can recompute from the raw rows.

TWO VOCABULARIES, AND THE ASYMMETRY BETWEEN THEM. Gold labels use six classes
(applied, interview, offer, rejection, assessment, other); ``EmailCategory``
has nine. ``follow_up``, ``pending_application`` and ``needs_review`` can
therefore only ever appear as an ACTUAL, never as an expectation, so they show
up in the confusion matrix exclusively on the error side. That is a property of
the gold vocabulary and not a measured defect of those three categories — with
one exception worth stating: ``pending_application`` is inside
``JOB_LIFECYCLE_CATEGORIES``, which pipeline.py persists to the applications
table, so a message routed there does mint a row. A marketing nudge landing on
``pending_application`` is a real error, not a labelling artefact.

Separately: how many cases would AUTO-FILE (confidence >= ``AUTO_FILE_GATE``),
and how many of those auto-file WRONGLY. A confident wrong answer is far worse
than an abstention and must not average away into an accuracy figure.

What this measures, precisely
-----------------------------
``RulesClassifier`` alone. Production is rules-only — ``hybrid.py`` returns
before embeddings or SetFit whenever ``settings.deployment == "cloud"`` — while
a LOCAL run of the same product is a three-layer cascade. Numbers here describe
the layer Vercel runs, and do not describe the local cascade.

The classified text is derived by production's own expression,
``extract_body_text(payload) or snippet`` (``cloud/gmail_oauth.py:1332``,
``:1530``), so HTML-only bodies, calendar parts with no plain sibling,
header-only messages and 4000-character truncation are all exercised through
the real decode path rather than pre-decoded into something convenient.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass

from jobtracker.classifier.rules import RulesClassifier
from jobtracker.cloud.gmail_client import extract_body_text
from jobtracker.cloud.pipeline import AUTO_FILE_GATE
from jobtracker.database.models import EmailCategory

from .mail import CATEGORIES, METADATA, MailCase, generate

#: The verdicts that mean "I have nothing to say", as opposed to a category.
ABSTAIN_CATEGORIES = {EmailCategory.OTHER.value, EmailCategory.NEEDS_REVIEW.value}

CORRECT, WRONG, ABSTAINED = "correct", "wrong", "abstained"


def derive(case: MailCase) -> str:
    """Production's own expression for the string that reaches ``classify()``."""

    return extract_body_text(case.payload) or case.snippet


@dataclass
class Outcome:
    case_id: str
    axis: str
    pair: str | None
    expected: str
    actual: str
    confidence: float
    bucket: str
    auto_filed: bool
    no_positive_evidence: bool
    provenance: str
    defects: tuple[str, ...]
    matched: tuple[str, ...]
    scores: dict[str, int]
    derived_chars: int
    #: Did the verdict phrase START inside what the classifier could see?
    verdict_starts_visible: bool | None
    #: Was the WHOLE phrase there? The distinction is the point: a verdict
    #: beginning at offset 150 still runs off the end of a 186-character
    #: snippet, so "the snippet reached the verdict" and "the snippet contained
    #: the verdict" are different questions with different answers.
    verdict_complete: bool | None
    note: str


def score_one(case: MailCase, clf: RulesClassifier) -> Outcome:
    text = derive(case)
    result = clf.classify(case.subject, text, case.sender)
    actual = result.category.value
    scores = dict(result.scores)
    no_positive = max(scores.values(), default=0) <= 0

    if actual == case.expected:
        bucket = CORRECT
    elif (
        actual in ABSTAIN_CATEGORIES
        and result.confidence < AUTO_FILE_GATE
        and no_positive
    ):
        bucket = ABSTAINED
    else:
        bucket = WRONG

    # For truncation cases, what did the classifier ACTUALLY have in front of
    # it? Measured against the derived string, never inferred from the label:
    # whitespace collapse happens BEFORE the 4000-character cap, so a body
    # padded with blank lines can land a nominally-truncated verdict inside the
    # budget and pass for the wrong reason.
    starts: bool | None = None
    complete: bool | None = None
    if case.verdict_offset is not None and case.verdict_text is not None:
        window = case.subject if case.verdict_in == "subject" else text
        starts = case.verdict_offset < len(window)
        complete = " ".join(case.verdict_text.split()) in " ".join(window.split())

    return Outcome(
        case_id=case.case_id,
        axis=case.axis,
        pair=case.pair,
        expected=case.expected,
        actual=actual,
        confidence=round(result.confidence, 3),
        bucket=bucket,
        auto_filed=result.confidence >= AUTO_FILE_GATE,
        no_positive_evidence=no_positive,
        provenance=case.provenance,
        defects=tuple(case.defects) or ("none",),
        matched=tuple(result.matched_patterns),
        scores={k: v for k, v in scores.items() if v},
        derived_chars=len(text),
        verdict_starts_visible=starts,
        verdict_complete=complete,
        note=case.note,
    )


def run() -> list[Outcome]:
    clf = RulesClassifier()
    return [score_one(c, clf) for c in generate()]


# ── printing ─────────────────────────────────────────────────────────────────


def _rule(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def _pct(n: int, d: int) -> str:
    return f"{100.0 * n / d:5.1f}%" if d else "    - "


def print_report(outcomes: list[Outcome]) -> None:
    total = len(outcomes)
    actual_labels = sorted({o.actual for o in outcomes} | set(CATEGORIES))

    print("=" * 78)
    print("MAIL CLASSIFICATION CORPUS — RulesClassifier (the production layer)")
    print("=" * 78)
    print(f"cases: {total}    auto-file gate: {AUTO_FILE_GATE}")
    print("weighting: judgement, not data —", METADATA["weighting"])
    print("instrument, not a gate: no threshold is asserted anywhere in this run.")

    # -- confusion matrix --------------------------------------------------
    _rule("CONFUSION MATRIX  (rows = expected, columns = actual)")
    matrix: dict[str, Counter[str]] = defaultdict(Counter)
    for o in outcomes:
        matrix[o.expected][o.actual] += 1
    width = max(len(c) for c in actual_labels) + 1
    header = " " * 14 + "".join(f"{c[:width - 1]:>{width}}" for c in actual_labels) + "     n"
    print(header)
    for expected in CATEGORIES:
        row = matrix[expected]
        n = sum(row.values())
        cells = "".join(f"{(row[c] or '.'):>{width}}" for c in actual_labels)
        print(f"{expected:<14}{cells}  {n:>4}")

    # -- three-way buckets -------------------------------------------------
    _rule("CORRECT / WRONG / ABSTAINED, per expected class")
    print(f"{'class':<14}{'n':>5}{'correct':>10}{'':>8}{'wrong':>8}{'':>8}"
          f"{'abstain':>9}{'':>8}")
    for expected in CATEGORIES:
        rows = [o for o in outcomes if o.expected == expected]
        n = len(rows)
        c = sum(1 for o in rows if o.bucket == CORRECT)
        w = sum(1 for o in rows if o.bucket == WRONG)
        a = sum(1 for o in rows if o.bucket == ABSTAINED)
        print(f"{expected:<14}{n:>5}{c:>10}{_pct(c, n):>8}{w:>8}{_pct(w, n):>8}"
              f"{a:>9}{_pct(a, n):>8}")
    c = sum(1 for o in outcomes if o.bucket == CORRECT)
    w = sum(1 for o in outcomes if o.bucket == WRONG)
    a = sum(1 for o in outcomes if o.bucket == ABSTAINED)
    print(f"{'ALL':<14}{total:>5}{c:>10}{_pct(c, total):>8}{w:>8}{_pct(w, total):>8}"
          f"{a:>9}{_pct(a, total):>8}")

    # -- auto-file ---------------------------------------------------------
    _rule("AUTO-FILE  (confidence >= gate: the classifier asserts a status)")
    filed = [o for o in outcomes if o.auto_filed]
    bad = [o for o in filed if o.bucket != CORRECT]
    print(f"auto-filed          {len(filed):>4} / {total}  {_pct(len(filed), total)}")
    print(f"auto-filed WRONGLY  {len(bad):>4}        {_pct(len(bad), total)} of the corpus,"
          f" {_pct(len(bad), len(filed))} of auto-files")
    print("\nwrong auto-files by (expected -> actual):")
    for (e, act), n in Counter((o.expected, o.actual) for o in bad).most_common():
        print(f"  {e:<12} -> {act:<14} {n:>4}")

    # -- per-defect --------------------------------------------------------
    _rule("PER DEFECT CLASS  (a case with several defects counts under each)")
    per: dict[str, Counter[str]] = defaultdict(Counter)
    for o in outcomes:
        for d in o.defects:
            per[d][o.bucket] += 1
            if o.auto_filed and o.bucket != CORRECT:
                per[d]["bad_autofile"] += 1
    print(f"{'defect':<44}{'n':>5}{'corr':>6}{'wrong':>7}{'abst':>6}{'bad-af':>8}")
    for defect in sorted(per, key=lambda d: (-sum(
            per[d][k] for k in (CORRECT, WRONG, ABSTAINED)), d)):
        row = per[defect]
        n = row[CORRECT] + row[WRONG] + row[ABSTAINED]
        print(f"{defect:<44}{n:>5}{row[CORRECT]:>6}{row[WRONG]:>7}"
              f"{row[ABSTAINED]:>6}{row['bad_autofile']:>8}")

    # -- per-axis and per-pair --------------------------------------------
    _rule("PER AXIS")
    axes: dict[str, Counter[str]] = defaultdict(Counter)
    for o in outcomes:
        axes[o.axis][o.bucket] += 1
        if o.auto_filed and o.bucket != CORRECT:
            axes[o.axis]["bad_autofile"] += 1
    print(f"{'axis':<28}{'n':>5}{'corr':>6}{'wrong':>7}{'abst':>6}{'bad-af':>8}")
    for axis in sorted(axes):
        row = axes[axis]
        n = row[CORRECT] + row[WRONG] + row[ABSTAINED]
        print(f"{axis:<28}{n:>5}{row[CORRECT]:>6}{row[WRONG]:>7}"
              f"{row[ABSTAINED]:>6}{row['bad_autofile']:>8}")

    _rule("THE ELEVEN CONFUSION PAIRS, case by case")
    for pair in sorted({o.pair for o in outcomes if o.pair}, key=lambda p: int(p[1:])):
        print(f"\n{pair}")
        for o in [x for x in outcomes if x.pair == pair]:
            flag = "AUTO-FILED" if o.auto_filed else ""
            print(f"  {o.case_id}  {o.expected:<11} -> {o.actual:<14} {o.confidence:.2f} "
                  f"{o.bucket:<9} {flag:<10} {o.note[:44]}")

    # -- provenance --------------------------------------------------------
    _rule("BY PROVENANCE  (so nobody cites a flavour-derived number as evidence)")
    prov: dict[str, Counter[str]] = defaultdict(Counter)
    for o in outcomes:
        prov[o.provenance][o.bucket] += 1
    print(f"{'provenance':<14}{'n':>5}{'corr':>6}{'wrong':>7}{'abst':>6}")
    for p in ("VERIFIED", "MEASURED", "COLLECTED", "INFERRED"):
        row = prov[p]
        n = row[CORRECT] + row[WRONG] + row[ABSTAINED]
        print(f"{p:<14}{n:>5}{row[CORRECT]:>6}{row[WRONG]:>7}{row[ABSTAINED]:>6}")

    # -- truncation audit --------------------------------------------------
    _rule("TRUNCATION AUDIT  (was the verdict inside what the classifier saw?)")
    trunc = [o for o in outcomes if o.verdict_starts_visible is not None]
    by_defect: dict[str, list[Outcome]] = defaultdict(list)
    for o in trunc:
        for d in o.defects:
            if d.startswith("truncation:") or d.startswith("subject:overlong"):
                by_defect[d].append(o)
    print(f"{'placement':<38}{'n':>4}{'starts in view':>16}{'phrase whole':>14}"
          f"{'correct':>9}{'abst':>6}{'wrong':>7}")
    for d in sorted(by_defect, key=lambda x: (x.split("-")[0], len(x), x)):
        rows = by_defect[d]
        print(f"{d:<38}{len(rows):>4}"
              f"{sum(1 for o in rows if o.verdict_starts_visible):>16}"
              f"{sum(1 for o in rows if o.verdict_complete):>14}"
              f"{sum(1 for o in rows if o.bucket == CORRECT):>9}"
              f"{sum(1 for o in rows if o.bucket == ABSTAINED):>6}"
              f"{sum(1 for o in rows if o.bucket == WRONG):>7}")

    # -- the loudest individual failures -----------------------------------
    _rule("CONFIDENT AND WRONG — the worst 25 (auto-filed, wrong verdict)")
    worst = sorted(bad, key=lambda o: -o.confidence)[:25]
    for o in worst:
        print(f"  {o.case_id} {o.confidence:.2f}  {o.expected:<11} -> {o.actual:<14} "
              f"[{','.join(o.defects)[:34]}] {o.note[:34]}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", metavar="PATH", help="also write every row as JSONL")
    args = ap.parse_args()
    outcomes = run()
    print_report(outcomes)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            for o in outcomes:
                fh.write(json.dumps(asdict(o), default=list) + "\n")
        print(f"\nrows written to {args.json}")


if __name__ == "__main__":
    main()
