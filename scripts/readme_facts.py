#!/usr/bin/env python3
"""
Verify — and repair — every number the README asserts.

WHY THIS EXISTS

A prose document has no mechanism that makes a stale number *fail*. This
README already carries the scar: its coverage paragraph documents its own
correction from "54% overall, 61% excluding one-off scripts … 2,163 statements
of dataset importers", three of whose four figures were wrong, and which
survived because the portfolio was citing this README instead of citing a run.
Nobody was careless. Hand-maintained figures drift, always, and they drift
silently — which is the part that matters, because a README whose numbers are
quietly wrong is worse than one with no numbers. It spends credibility it no
longer has.

So the numbers stop being prose and become assertions.

THE DESIGN, AND WHY IT IS NOT MARKERS

The obvious approach is to fence each number in an HTML comment and regenerate
it. That fails here for two reasons: several counts appear inside mermaid
diagrams, where an HTML comment is a syntax error, and markers make the source
unreadable at exactly the density this README uses them.

Instead each fact declares the SITES where it is asserted, as regexes that
capture the digits. The checker recomputes the fact and compares.

The load-bearing rule is this:

    A SITE REGEX THAT MATCHES ZERO TIMES IS A FAILURE.

Not a skip. A failure. That is the whole point. If a claim is reworded so its
regex no longer matches, the fact has escaped its check and the file has
silently stopped being verified. A checker that quietly passes when it can no
longer find what it was checking is not a checker.

TWO CLASSES OF FACT

  static   — recomputable from source, cheaply, with no build, no database and
             no network. Regex patterns in a dict literal, CREATE POLICY
             statements in a migration, bytes on disk. Recomputed every run.

  recorded — require executing something (the suite, a coverage pass). Read
             from docs/readme-facts.json, which carries the value, the command
             that produced it and the date it was taken. A checker that runs
             pytest becomes slow, then flaky, then disabled — and a disabled
             checker is how drift starts. So the fast path never runs the
             suite; `--record` does, deliberately.

The two classes are tied together by INVARIANTS (see below), so a recorded
figure cannot go stale without a static one noticing.

COUNT AT THE DEFINITION SITE, NOT THE USE SITE

Every `compute` below reads the place a thing is DEFINED. The pattern count
comes from AST-parsing the `PATTERNS` dict literal in
`backend/jobtracker/classifier/rules.py` — not from any call site, not from the
JavaScript ports, and not from the second copy of rules.py that lives under
`ml/demo/space/`. The ports and the second copy are checked *against* that
number by invariants instead, which is what catches them diverging.

The same discipline applies to two 0.85s that are not the same 0.85: the
auto-classify gate is the named constant `CONFIDENCE_AUTO`, while the
embeddings layer accepts on a bare `emb_confidence >= 0.85` literal a few
hundred lines away. They are equal today and are separate facts, because
nothing in the code makes them move together.

WHAT IS DELIBERATELY NOT CHECKED

Numbers the README presents as history, or as a measurement taken elsewhere,
are prose about the past and are not eligible to be facts — recomputing them
would overwrite a documented correction with today's reading. Listed in full,
so each omission is a decision rather than an oversight:

  - The whole "this paragraph read 54% … until 2026-08-03" correction
    paragraph: 54%, 8,018, the 192-statement gap, 13 Pydantic models, 61%,
    60.5%, 1,234, 2,163, 662. Rewriting any of them would erase the record of
    a correction, which is the one thing that paragraph exists to preserve.
    NOTE that 8,210 appears there as history and is no longer the current
    total; that sentence is about a comparison made on 2026-08-03.
  - The ruff (379) and mypy (879 across 65 of 92 files) counts. Attributed to
    a named CI run on 2026-08-07, and neither tool is on this script's path.
  - The pip-audit findings (0, and 8 in 2 packages). Dated, and they need the
    network — an advisory that changes when a CVE is published, not when this
    repository changes.
  - Every per-layer latency figure — 0.036 / 0.176 / 0.262 / 17.649 ms, the
    p95s, the 15 / 174 / 39 / 60 answered counts, the 288 classifications and
    the 100× ratio. The README states outright that no results artifact is
    committed and that the machine was not recorded. There is nothing on disk
    to recompute them from, and inventing one would be worse than the gap.
  - The 18 OpenSSF Scorecard checks. Computed by someone else, which the
    README correctly says is the entire value of the number.

Two figures that LOOK like they belong on that list are checked anyway, because
they have a committed source of record: the cascade's 0.9583 / 4 misclassified
on v3, and the 0.9843 / 0.9686 v2 comparison. The README names
`docs/ML_EXECUTION_TRACKER.md` as their source, so the tracker is their
definition site and `tracker_metric` reads it. Reproducing them from scratch
would need a `--hybrid-profile full` run with torch and SetFit resident; that
is a `--record` job nobody has wired, and until somebody does, agreeing with
the tracker is a real and checkable constraint rather than no constraint.

USAGE
  python3 scripts/readme_facts.py            # --check: verify, exit 1 on drift
  python3 scripts/readme_facts.py --write    # rewrite the numbers in place
  python3 scripts/readme_facts.py --record   # re-run the suite, refresh the artifact
"""

from __future__ import annotations

import ast
import json
import os
import platform
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"
ARTIFACT = REPO / "docs" / "readme-facts.json"


# ── helpers ──────────────────────────────────────────────────────────────


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def count_in(rel: str, pattern: str) -> int:
    return len(re.findall(pattern, read(rel)))


WORDS = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen", "twenty",
]


def to_word(n) -> str:
    n = int(n)
    return WORDS[n] if 0 <= n < len(WORDS) else str(n)


def with_commas(n) -> str:
    return f"{int(n):,}"


def strip_commas(s: str) -> str:
    return s.replace(",", "")


# ── computing from Python source, at the definition site ─────────────────


def _module(rel: str) -> ast.Module:
    return ast.parse(read(rel), filename=rel)


def _assigned(rel: str, name: str) -> ast.expr:
    """The value node of a module-level `name = ...` / `name: T = ...`."""
    for node in _module(rel).body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name and node.value:
                return node.value
    raise SystemExit(f"  ✗ {rel}: no module-level assignment to `{name}`")


def rules_pattern_counts(rel: str) -> dict[str, int]:
    """
    The `PATTERNS` dict literal in a rules.py, counted by AST.

    Shape: `PATTERNS: dict[EmailCategory, CategoryPatterns] = {
                EmailCategory.X: CategoryPatterns(strong=[...], weak=[...], negative=[...]),
                ...}`

    Counting by AST rather than by grepping for quotes is what makes this a
    definition-site count: a regex that mentions `strong` in a comment, or a
    pattern list built somewhere else and never placed in PATTERNS, cannot
    contribute.
    """
    node = _assigned(rel, "PATTERNS")
    if not isinstance(node, ast.Dict):
        raise SystemExit(f"  ✗ {rel}: PATTERNS is not a dict literal")
    out = {"strong": 0, "weak": 0, "negative": 0, "categories": len(node.keys)}
    for value in node.values:
        if not isinstance(value, ast.Call):
            raise SystemExit(f"  ✗ {rel}: a PATTERNS value is not a CategoryPatterns(...) call")
        for kw in value.keywords:
            if kw.arg in out and isinstance(kw.value, ast.List):
                out[kw.arg] += len(kw.value.elts)
    out["total"] = out["strong"] + out["weak"] + out["negative"]
    return out


BACKEND_RULES = "backend/jobtracker/classifier/rules.py"
DEMO_SPACE_RULES = "ml/demo/space/jobtracker/classifier/rules.py"
RLS_MIGRATION = "backend/alembic/versions/a8d4ec5fba26_enable_rls_policies_postgres_only.py"
USER_CREDS_RLS = "backend/alembic/versions/c4_user_credentials_rls.py"
HYBRID = "backend/jobtracker/classifier/hybrid.py"


def _rules(rel: str = BACKEND_RULES) -> dict[str, int]:
    return rules_pattern_counts(rel)


def json_patterns(rel: str) -> int:
    """Pattern count in one of the JS ports' rules.json (categories → lists)."""
    data = json.loads(read(rel))
    cats = data["categories"] if "categories" in data else data
    return sum(
        len(group.get(k, []))
        for group in cats.values()
        if isinstance(group, dict)
        for k in ("strong", "weak", "negative")
    )


def rls_tables() -> int:
    """`RLS_TABLES` in the RLS migration, plus user_credentials from its own revision."""
    node = _assigned(RLS_MIGRATION, "RLS_TABLES")
    if not isinstance(node, ast.List):
        raise SystemExit(f"  ✗ {RLS_MIGRATION}: RLS_TABLES is not a list literal")
    return len(node.elts) + 1


def policies_per_table() -> int:
    """CREATE POLICY statements inside the `for table in RLS_TABLES:` loop body."""
    for node in ast.walk(_module(RLS_MIGRATION)):
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            if isinstance(node.iter, ast.Name) and node.iter.id == "RLS_TABLES":
                body = "\n".join(ast.dump(s) for s in node.body)
                return body.count("CREATE POLICY")
    raise SystemExit(f"  ✗ {RLS_MIGRATION}: no `for table in RLS_TABLES:` loop found")


def rls_policies() -> int:
    """Not hard-coded as tables×4: the loop is counted, the one-off revision added."""
    loop = (rls_tables() - 1) * policies_per_table()
    return loop + count_in(USER_CREDS_RLS, r"CREATE POLICY")


def float_const(rel: str, name: str) -> float:
    return float(ast.literal_eval(_assigned(rel, name)))


def embeddings_accept_threshold() -> float:
    """
    The bare literal the embeddings layer accepts on.

    Deliberately not read from CONFIDENCE_AUTO. The line is
    `if emb_confidence >= 0.85 and not has_negative_signals:` — a magic number
    that happens to equal the gate constant. Two facts, because nothing makes
    them move together.
    """
    m = re.search(r"emb_confidence\s*>=\s*([\d.]+)", read(HYBRID))
    if not m:
        raise SystemExit(f"  ✗ {HYBRID}: no `emb_confidence >= <float>` comparison found")
    return float(m.group(1))


def enum_members(rel: str, name: str) -> int:
    for node in ast.walk(_module(rel)):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return sum(
                1
                for s in node.body
                if isinstance(s, ast.Assign)
                and len(s.targets) == 1
                and isinstance(s.targets[0], ast.Name)
            )
    raise SystemExit(f"  ✗ {rel}: no class {name}")


def eval_rows() -> list[dict]:
    return [
        json.loads(line)
        for line in read("backend/data/evaluation/classifier_eval_v3.jsonl").splitlines()
        if line.strip()
    ]


def scenario_count(group: str) -> int:
    return sum(1 for r in eval_rows() if r.get("scenario_group") == group)


def baseline(name: str) -> dict:
    return json.loads(read(f"backend/data/evaluation/{name}"))


TRACKER = "docs/ML_EXECUTION_TRACKER.md"


def tracker_metric(row: str, metric: str) -> float:
    """
    A metric off one of ML_EXECUTION_TRACKER.md's result rows, e.g.

        - rules: `accuracy=0.9792`, `macro_f1=0.9791`, `misclassified=2`
        - hybrid: `accuracy=0.9583`, `macro_f1=0.9583`, `misclassified=4`
        - v2 hybrid: `accuracy=0.9844`, `macro_f1=0.9843`

    The tracker is the definition site for the cascade's numbers, not a peer
    document: the README says so itself, in the Documentation table, and there
    is nowhere else for them to come from. `baseline_hybrid_v3.json` cannot
    supply them — it was generated under the `deterministic` profile and reads
    0.9791, which is the whole trap the Classifier-evaluation section exists to
    defuse. Recomputing them for real needs a `--hybrid-profile full` run with
    torch and SetFit resident, which is exactly the kind of thing that must not
    live on the fast path.

    Anchored on `- <row>: ` at the start of a line so the v2 rows cannot be
    confused with the v3 rows; each of the four is unique in the file, and the
    `theNumber`-style single-value requirement below enforces that it stays so.
    """
    hits = set(
        re.findall(
            rf"^- {re.escape(row)}: .*?`{metric}=([\d.]+)`", read(TRACKER), re.M
        )
    )
    if not hits:
        raise SystemExit(f"  ✗ {TRACKER}: no `- {row}:` row carrying {metric}=")
    if len(hits) > 1:
        raise SystemExit(
            f"  ✗ {TRACKER}: `- {row}:` rows disagree on {metric}: {sorted(hits)}"
        )
    return float(hits.pop())


def test_modules() -> list[Path]:
    return sorted((REPO / "backend" / "tests").glob("test_*.py"))


def test_functions(only: str | None = None) -> int:
    total = 0
    for p in test_modules():
        if only and p.name != only:
            continue
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"), filename=str(p))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                total += 1
    return total


def ci_min_macro_f1() -> float:
    """The floor CI actually enforces, read out of the workflow that enforces it."""
    hits = set(re.findall(r"--min-macro-f1[= ]([\d.]+)", read(".github/workflows/backend-ci.yml")))
    if not hits:
        raise SystemExit("  ✗ backend-ci.yml: no --min-macro-f1 argument found")
    if len(hits) > 1:
        raise SystemExit(f"  ✗ backend-ci.yml: disagreeing --min-macro-f1 floors {sorted(hits)}")
    return float(hits.pop())


def file_bytes(rel: str) -> int:
    return (REPO / rel).stat().st_size


# ── the facts ────────────────────────────────────────────────────────────
#
# Each `sites` regex MUST contain exactly one capture group, around the number.
#
# A site is either a bare pattern string (checked against README.md) or a dict:
#   {"re": ..., "file": ...}  — check some other file instead
#   {"re": ..., "word": True} — the number is spelled out in English ("Eight")
#
# Claim sites outside the README matter more than they look. "Same 201
# patterns" is asserted in the header comment of the browser port and again in
# the Hugging Face Space's app.js; a number repeated in a second file is a
# number that gets corrected in one file and not the other.

FACTS: dict[str, dict] = {
    # ── the rules engine ──
    "rulesPatterns": {
        "kind": "static",
        "describe": f"regex patterns in the PATTERNS dict of {BACKEND_RULES}",
        "compute": lambda: _rules()["total"],
        "sites": [
            r"rules layer\*\* — (\d+) regex patterns, no model",
            r"a port of the same (\d+) patterns",
            r"1 · rules<br/>(\d+) regex patterns over",
            r"The (\d+) patterns are counted at their definition site",
            r"Hand-written regex engine, (\d+) patterns across",
            r"— (\d+) regex patterns and no model —",
            r"\*\*The rules engine\.\*\* (\d+) regex patterns across",
            r"rules\.py \((\d+) patterns\)",
            {"re": r"Same (\d+) patterns,", "file": "apps/web/lib/demo/rulesLayer.ts"},
            {"re": r"same (\d+) regexes,", "file": "ml/browser/site/app.js"},
        ],
    },
    "rulesStrong": {
        "kind": "static",
        "describe": "strong patterns in PATTERNS",
        "compute": lambda: _rules()["strong"],
        "sites": [
            r"(\d+) strong · \d+ weak · \d+ negative",
            r"\((\d+) strong, \d+ weak, \d+ negative\)",
        ],
    },
    "rulesWeak": {
        "kind": "static",
        "describe": "weak patterns in PATTERNS",
        "compute": lambda: _rules()["weak"],
        "sites": [
            r"\d+ strong · (\d+) weak · \d+ negative",
            r"\(\d+ strong, (\d+) weak, \d+ negative\)",
        ],
    },
    "rulesNegative": {
        "kind": "static",
        "describe": "negative patterns in PATTERNS",
        "compute": lambda: _rules()["negative"],
        "sites": [
            r"\d+ strong · \d+ weak · (\d+) negative",
            r"\(\d+ strong, \d+ weak, (\d+) negative\)",
        ],
    },
    "rulesCategories": {
        "kind": "static",
        "describe": "categories keyed in PATTERNS",
        "compute": lambda: _rules()["categories"],
        "sites": [
            r"regex patterns over (\d+) categories",
            r"regex engine, \d+ patterns across (\d+) categories",
            r"\*\*The rules engine\.\*\* \d+ regex patterns across (\d+) categories",
        ],
    },
    # ── row-level security ──
    "rlsTenantTables": {
        "kind": "static",
        "describe": "tenant tables under RLS (RLS_TABLES + user_credentials)",
        "compute": rls_tables,
        "sites": [
            {"re": r"(\w+) tenant tables carry", "word": True},
            {"re": r"\*\*(\w+) tenant tables\*\*", "word": True},
        ],
    },
    "rlsPoliciesPerTable": {
        "kind": "static",
        "describe": "CREATE POLICY statements inside the RLS_TABLES loop body",
        "compute": policies_per_table,
        "sites": [
            {"re": r"with (\w+) policies each", "word": True},
            {"re": r"and (\w+) policies \(`SELECT`", "word": True},
        ],
    },
    "rlsPolicies": {
        "kind": "static",
        "describe": "CREATE POLICY statements across the RLS migrations",
        "compute": rls_policies,
        "sites": [
            r"— \*\*(\d+) policies\*\* —",
            r"RLS: (\d+) policies, FORCE",
            r"That is \*\*(\d+) policies\*\*",
            r"\*\*All (\d+) predicates are",
            r"the (\d+) RLS policies",
        ],
    },
    # ── the evaluation set ──
    "evalRows": {
        "kind": "static",
        "describe": "rows in classifier_eval_v3.jsonl",
        "compute": lambda: len(eval_rows()),
        "sites": [
            r"on the (\d+)-example v3 evaluation set",
            r"of (\d+) misclassified\)",
            r"\*\*(\d+) examples, \d+ per label across \d+ labels\*\*",
            r"and (\d+) examples is a small sample",
            r"(\d+)-example v3 set, warm",
            r"the (\d+) examples and the coverage contract",
        ],
    },
    "evalLabels": {
        "kind": "static",
        "describe": "distinct labels in classifier_eval_v3.jsonl (the SetFit label set)",
        "compute": lambda: len({r["label"] for r in eval_rows()}),
        "sites": [
            r"\*\*\d+ examples, \d+ per label across (\d+) labels\*\*",
            r"paraphrase-MiniLM-L6-v2`, (\d+) labels",
            r"over (\d+) labels, with a provenance",
            r"<br/>(\d+) labels · accepts at",
            {"re": r"(\w+) of the \w+ are predicted labels", "word": True},
        ],
    },
    "evalPerLabel": {
        "kind": "static",
        "describe": "rows per label in classifier_eval_v3.jsonl",
        "compute": lambda: min(
            sum(1 for r in eval_rows() if r["label"] == lbl)
            for lbl in {r["label"] for r in eval_rows()}
        ),
        "sites": [r"\*\*\d+ examples, (\d+) per label across \d+ labels\*\*"],
    },
    "evalCorePositive": {
        "kind": "static",
        "describe": "rows tagged scenario_group=core_positive",
        "compute": lambda: scenario_count("core_positive"),
        "sites": [r"grouped as (\d+) core-positive"],
    },
    "evalEdgeNoise": {
        "kind": "static",
        "describe": "rows tagged scenario_group=edge_noise",
        "compute": lambda: scenario_count("edge_noise"),
        "sites": [r"core-positive, (\d+) edge-noise"],
    },
    "evalHistoricalMiss": {
        "kind": "static",
        "describe": "rows tagged scenario_group=historical_miss",
        "compute": lambda: scenario_count("historical_miss"),
        "sites": [r"edge-noise, (\d+) historical-miss"],
    },
    "evalCoreNegative": {
        "kind": "static",
        "describe": "rows tagged scenario_group=core_negative",
        "compute": lambda: scenario_count("core_negative"),
        "sites": [r"historical-miss and (\d+) core-negative"],
    },
    # ── the committed baseline ──
    "rulesMacroF1": {
        "kind": "static",
        "describe": "macro_f1 in baseline_rules_v3.json",
        "compute": lambda: baseline("baseline_rules_v3.json")["overall"]["macro_f1"],
        "sites": [
            r"macro--F1-([\d.]+)%20\(CI",
            r"scores \*\*([\d.]+) macro-F1\*\*",
            r"\*\*The ([\d.]+) belongs to the rules layer",
            r"reports ([\d.]+) too",
            r"how far ([\d.]+) generalizes",
            r"reports ([\d.]+) again",
            r"where ([\d.]+) lives",
            r"against a measured ([\d.]+)",
        ],
    },
    "rulesAccuracy": {
        "kind": "static",
        "describe": "accuracy in baseline_rules_v3.json",
        "compute": lambda: baseline("baseline_rules_v3.json")["overall"]["accuracy"],
        "sites": [r"\(accuracy ([\d.]+), \d+ of \d+ misclassified\)"],
    },
    "rulesMismatches": {
        "kind": "static",
        "describe": "mismatch records in baseline_rules_v3.json",
        "compute": lambda: len(baseline("baseline_rules_v3.json")["mismatches"]),
        "sites": [r"\(accuracy [\d.]+, (\d+) of \d+ misclassified\)"],
    },
    # ── the cascade, whose numbers live in the tracker and nowhere else ──
    "cascadeMacroF1": {
        "kind": "static",
        "describe": f"macro_f1 on the `- hybrid:` v3 row of {TRACKER}",
        "compute": lambda: tracker_metric("hybrid", "macro_f1"),
        "sites": [
            r"full three-layer cascade\*\* scores \*\*([\d.]+)\*\*",
            r"\(accuracy ([\d.]+), \d+ misclassified\)",
            r"the one that reads ([\d.]+)",
            r"the source for the cascade's ([\d.]+)",
        ],
    },
    "cascadeMismatches": {
        "kind": "static",
        "describe": f"misclassified on the `- hybrid:` v3 row of {TRACKER}",
        "compute": lambda: int(tracker_metric("hybrid", "misclassified")),
        "sites": [r"\(accuracy [\d.]+, (\d+) misclassified\)"],
    },
    "cascadeV2MacroF1": {
        "kind": "static",
        "describe": f"macro_f1 on the `- v2 hybrid:` row of {TRACKER}",
        "compute": lambda: tracker_metric("v2 hybrid", "macro_f1"),
        "sites": [r"— ([\d.]+) against [\d.]+ macro-F1"],
    },
    "rulesV2MacroF1": {
        "kind": "static",
        "describe": f"macro_f1 on the `- v2 rules:` row of {TRACKER}",
        "compute": lambda: tracker_metric("v2 rules", "macro_f1"),
        "sites": [r"— [\d.]+ against ([\d.]+) macro-F1"],
    },
    "macroF1Floor": {
        "kind": "static",
        "describe": "the --min-macro-f1 floor in .github/workflows/backend-ci.yml",
        "compute": ci_min_macro_f1,
        "sites": [
            r"\(CI%20floor%20([\d.]+)\)",
            r"below a \*\*([\d.]+)\*\* floor",
            r"gated at the ([\d.]+) floor",
            r"--min-macro-f1 ([\d.]+)",
            r"promotion past the ([\d.]+) floor",
            r"The macro-F1 floor is ([\d.]+) against",
        ],
    },
    # ── the cascade's thresholds ──
    "confidenceAuto": {
        "kind": "static",
        "describe": f"CONFIDENCE_AUTO in {HYBRID}",
        "compute": lambda: float_const(HYBRID, "CONFIDENCE_AUTO"),
        "sites": [
            r"below a ([\d.]+) confidence gate",
            r"CONFIDENCE_AUTO = ([\d.]+)",
            r"confidence ≥ ([\d.]+) \?",
            r"the ([\d.]+) auto-classify threshold",
        ],
    },
    "confidenceMin": {
        "kind": "static",
        "describe": f"CONFIDENCE_MIN_CLASSIFICATION in {HYBRID}",
        "compute": lambda: float_const(HYBRID, "CONFIDENCE_MIN_CLASSIFICATION"),
        "sites": [
            r"labels · accepts at ≥ ([\d.]+)",
            r'S -->\|"≥ ([\d.]+)"\|',
            r"CONFIDENCE_MIN_CLASSIFICATION = ([\d.]+)",
            r"the ([\d.]+) minimum for trusting",
        ],
    },
    "embeddingsAccept": {
        "kind": "static",
        "describe": f"the bare `emb_confidence >= ...` literal in {HYBRID}",
        "compute": embeddings_accept_threshold,
        "sites": [
            r"cosine similarity vs stored examples<br/>accepts at ≥ ([\d.]+)",
            r'E -->\|"≥ ([\d.]+)"\| Out4',
        ],
    },
    "emailCategories": {
        "kind": "static",
        "describe": "members of the EmailCategory enum",
        "compute": lambda: enum_members("backend/jobtracker/database/models.py", "EmailCategory"),
        "sites": [
            {"re": r"into the (\w+) `EmailCategory` enum values", "word": True},
            {"re": r"of the (\w+) are predicted labels", "word": True},
        ],
    },
    # ── artifacts on disk ──
    "onnxFloat32Bytes": {
        "kind": "static",
        "describe": "bytes of ml/browser/artifacts/model.onnx",
        "compute": lambda: file_bytes("ml/browser/artifacts/model.onnx"),
        "sites": [
            r"from ([\d,]+) bytes of float32",
            r"exports to ONNX at \*\*([\d,]+) bytes\*\* float32",
        ],
    },
    "onnxInt8Bytes": {
        "kind": "static",
        "describe": "bytes of ml/browser/artifacts/model_quantized.onnx",
        "compute": lambda: file_bytes("ml/browser/artifacts/model_quantized.onnx"),
        "sites": [
            r"\*\*([\d,]+)-byte int8 ONNX\*\*",
            r"quantizes to \*\*([\d,]+) bytes\*\* int8",
            r"— ([\d,]+) bytes; check it with",
        ],
    },
    "onnxInt8Mb": {
        # Its own fact, not a formatting of onnxInt8Bytes: a byte-count site
        # regex must never capture "22.8" and rewrite it to "22843695 MB".
        "kind": "static",
        "describe": "ml/browser/artifacts/model_quantized.onnx in MB, 1 decimal",
        "compute": lambda: round(file_bytes("ml/browser/artifacts/model_quantized.onnx") / 1e6, 1),
        "sites": [r"The ([\d.]+) MB int8 ONNX build"],
    },
    # ── the repository itself ──
    "e2eSpecs": {
        "kind": "static",
        "describe": "*.spec.ts files under apps/web/tests/e2e/",
        "compute": lambda: len(list((REPO / "apps/web/tests/e2e").glob("*.spec.ts"))),
        "sites": [
            r"\((\d+) spec files under",
            r"\| (\d+) spec files — landing",
            r"# (\d+) Playwright specs",
        ],
    },
    "workflows": {
        "kind": "static",
        "describe": "workflow files in .github/workflows/",
        "compute": lambda: len(
            [p for p in (REPO / ".github/workflows").iterdir() if p.suffix in (".yml", ".yaml")]
        ),
        "sites": [r"GitHub Actions — (\d+) workflows", r"# (\d+) workflows"],
    },
    "alembicRevisions": {
        "kind": "static",
        "describe": "revision modules in backend/alembic/versions/",
        "compute": lambda: len(
            [p for p in (REPO / "backend/alembic/versions").glob("*.py") if p.name != "__init__.py"]
        ),
        "sites": [r"# (\d+) revisions incl\."],
    },
    "testModules": {
        "kind": "static",
        "describe": "test_*.py modules under backend/tests/",
        "compute": lambda: len(test_modules()),
        # Anchored on "at HEAD" because the same sentence also states the module
        # count at the original commit ("the same 25 modules at `37dd805`"). An
        # unanchored `across (\d+) modules` would match both and could not tell
        # the current figure from the historical one.
        "sites": [r"across (\d+) modules at HEAD", r"# (\d+) modules"],
    },
    "testFunctions": {
        # NOTE for --write: the sentence carrying this number also asserts the
        # count held at commit 37dd805. If this ever moves, rewriting the digit
        # leaves a sentence claiming a historical equality that no longer holds
        # — re-read the prose, do not just accept the rewrite.
        "kind": "static",
        "describe": "test_* functions across backend/tests/, by AST",
        "compute": test_functions,
        "sites": [r"a static parse counts (\d+) `test_\*` functions"],
    },
    "rlsTests": {
        "kind": "static",
        "describe": "test_* functions in backend/tests/test_rls_postgres.py",
        "compute": lambda: test_functions(only="test_rls_postgres.py"),
        "sites": [
            {"re": r"(\w+) tests drive the real connection machinery", "word": True},
            r"The (\d+) that used to skip",
            r"(\d+) RLS enforcement tests",
        ],
    },
    # ── recorded: these need a run ──
    "testsCollected": {
        "kind": "recorded",
        "describe": "tests collected by `pytest tests` in backend/",
        "sites": [
            r"tests-(\d+)%20collected",
            r"\*\*(\d+) tests collected, \d+ skipped\.\*\*",
            r"The remaining difference from (\d+) is parametrization",
        ],
    },
    "testsSkipped": {
        "kind": "recorded",
        "describe": "tests skipped by `pytest tests` in backend/",
        "sites": [
            r"%C2%B7%20(\d+)%20skipped",
            r"\*\*\d+ tests collected, (\d+) skipped\.\*\*",
        ],
    },
    "coveragePercent": {
        "kind": "recorded",
        "describe": "overall line coverage of jobtracker/, 2 decimals",
        "sites": [r"\*\*([\d.]+)%\*\* overall — [\d,]+ statements"],
    },
    "coverageStatements": {
        "kind": "recorded",
        "describe": "statements measured over jobtracker/",
        "sites": [r"overall — ([\d,]+) statements"],
    },
    "coverageMissed": {
        "kind": "recorded",
        "describe": "statements missed over jobtracker/",
        "sites": [r"statements, ([\d,]+) missed"],
    },
    "coverageCloud": {
        "kind": "recorded",
        "describe": "line coverage of jobtracker/cloud/",
        "sites": [r"is at \*\*([\d.]+)%\*\*; `auth`"],
    },
    "coverageAuth": {
        "kind": "recorded",
        "describe": "line coverage of jobtracker/auth/",
        "sites": [r"`auth` ([\d.]+)%"],
    },
    "coverageDatabase": {
        "kind": "recorded",
        "describe": "line coverage of jobtracker/database/",
        "sites": [r"`database` ([\d.]+)%"],
    },
    "coverageScriptsStatements": {
        "kind": "recorded",
        "describe": "statements in jobtracker/scripts/",
        "sites": [r"`jobtracker/scripts` at ([\d,]+) statements"],
    },
    "coverageScripts": {
        "kind": "recorded",
        "describe": "line coverage of jobtracker/scripts/",
        "sites": [r"statements and ([\d.]+)%, of which"],
    },
    "scriptsZeroModules": {
        "kind": "recorded",
        "describe": "modules under jobtracker/scripts/ at 0% coverage",
        "sites": [{"re": r"of which (\w+) modules no test imports", "word": True}],
    },
    "scriptsZeroStatements": {
        "kind": "recorded",
        "describe": "statements in the 0%-coverage jobtracker/scripts/ modules",
        "sites": [r"account for ([\d,]+) statements at 0%"],
    },
}


# ── invariants ───────────────────────────────────────────────────────────
#
# These are what stop a recorded number from going stale unnoticed, and what
# catch the duplicated sources of truth this repo carries on purpose: two
# copies of rules.py and two JavaScript ports of the same pattern table.

INVARIANTS = [
    {
        "name": "the strong/weak/negative split accounts for every pattern",
        "holds": lambda f: f["rulesStrong"] + f["rulesWeak"] + f["rulesNegative"] == f["rulesPatterns"],
        "explain": lambda f: (
            f"{f['rulesStrong']} + {f['rulesWeak']} + {f['rulesNegative']} = "
            f"{f['rulesStrong'] + f['rulesWeak'] + f['rulesNegative']}, not {f['rulesPatterns']}."
        ),
    },
    {
        "name": "every tenant table gets the same four policies",
        "holds": lambda f: f["rlsPolicies"] == f["rlsTenantTables"] * f["rlsPoliciesPerTable"],
        "explain": lambda f: (
            f"{f['rlsTenantTables']} tables x {f['rlsPoliciesPerTable']} policies = "
            f"{f['rlsTenantTables'] * f['rlsPoliciesPerTable']}, but the migrations issue "
            f"{f['rlsPolicies']} CREATE POLICY statements. One table is short a policy."
        ),
    },
    {
        "name": "the eval set is balanced: rows == labels x per-label",
        "holds": lambda f: f["evalRows"] == f["evalLabels"] * f["evalPerLabel"],
        "explain": lambda f: (
            f"{f['evalLabels']} labels x {f['evalPerLabel']} = "
            f"{f['evalLabels'] * f['evalPerLabel']}, not {f['evalRows']} rows."
        ),
    },
    {
        "name": "the four scenario groups partition the eval set",
        "holds": lambda f: (
            f["evalCorePositive"] + f["evalEdgeNoise"] + f["evalHistoricalMiss"] + f["evalCoreNegative"]
            == f["evalRows"]
        ),
        "explain": lambda f: (
            f"{f['evalCorePositive']} + {f['evalEdgeNoise']} + {f['evalHistoricalMiss']} + "
            f"{f['evalCoreNegative']} = "
            f"{f['evalCorePositive'] + f['evalEdgeNoise'] + f['evalHistoricalMiss'] + f['evalCoreNegative']},"
            f" not {f['evalRows']}. A row carries an unrecognised scenario_group."
        ),
    },
    {
        "name": "EmailCategory is the label set plus needs_review",
        "holds": lambda f: f["emailCategories"] == f["evalLabels"] + 1,
        "explain": lambda f: (
            f"{f['emailCategories']} enum members vs {f['evalLabels']} labels + needs_review. "
            f"The README's 'eight of the nine are predicted labels' no longer holds."
        ),
    },
    {
        "name": "the second copy of rules.py under ml/demo/space carries the same patterns",
        "holds": lambda f: _rules(DEMO_SPACE_RULES)["total"] == f["rulesPatterns"],
        "explain": lambda f: (
            f"{DEMO_SPACE_RULES} has {_rules(DEMO_SPACE_RULES)['total']} patterns, "
            f"{BACKEND_RULES} has {f['rulesPatterns']}. There are two copies of this file on "
            f"purpose; they have diverged."
        ),
    },
    {
        "name": "the browser port's rules.json carries the same patterns",
        "holds": lambda f: json_patterns("apps/web/lib/demo/rules.json") == f["rulesPatterns"],
        "explain": lambda f: (
            f"apps/web/lib/demo/rules.json has {json_patterns('apps/web/lib/demo/rules.json')} "
            f"patterns, {BACKEND_RULES} has {f['rulesPatterns']}. The /demo page is running a "
            f"different layer 1 from the product."
        ),
    },
    {
        "name": "baseline_rules_v3.json and baseline_hybrid_v3.json differ only in `meta`",
        # The README's central defusing claim. If the two files ever differ in a
        # metric block, the paragraph explaining why they read the same is wrong.
        "holds": lambda f: (
            {k: v for k, v in baseline("baseline_rules_v3.json").items() if k != "meta"}
            == {k: v for k, v in baseline("baseline_hybrid_v3.json").items() if k != "meta"}
        ),
        "explain": lambda f: (
            "the two v3 baselines no longer agree outside `meta`. The README says every metric "
            "block is identical and only `mode`/`hybrid_profile`/timestamp differ; that is now false."
        ),
    },
    {
        "name": "the tracker's v3 rules row agrees with the committed rules baseline",
        # The tracker is the source for the cascade's numbers and the baseline
        # JSON is the source for the rules layer's. They both report the rules
        # layer on the same 96 rows, so they have to agree — and if they ever
        # stop, one of the two documents the README leans on has drifted, which
        # is invisible from either one alone.
        "holds": lambda f: (
            tracker_metric("rules", "macro_f1") == round(f["rulesMacroF1"], 4)
            and int(tracker_metric("rules", "misclassified")) == f["rulesMismatches"]
        ),
        "explain": lambda f: (
            f"{TRACKER} says the rules layer scores {tracker_metric('rules', 'macro_f1')} with "
            f"{int(tracker_metric('rules', 'misclassified'))} misclassified; "
            f"baseline_rules_v3.json says {round(f['rulesMacroF1'], 4)} with {f['rulesMismatches']}."
        ),
    },
    {
        "name": "the cascade won on v2 and lost on v3, which is the README's whole point",
        # Not decoration. The README's argument is "the learned layers are not
        # decoration; they lost on v3" — an ordering claim, not a value claim.
        # If a retrain flips either comparison, four paragraphs of prose become
        # wrong while every individual number still checks out.
        "holds": lambda f: (
            f["cascadeV2MacroF1"] > f["rulesV2MacroF1"] and f["cascadeMacroF1"] < f["rulesMacroF1"]
        ),
        "explain": lambda f: (
            f"v2: cascade {f['cascadeV2MacroF1']} vs rules {f['rulesV2MacroF1']}; "
            f"v3: cascade {f['cascadeMacroF1']} vs rules {round(f['rulesMacroF1'], 4)}. "
            f"The README says the cascade beat the rules on v2 and lost on v3; one of those "
            f"comparisons has flipped and the surrounding prose no longer follows."
        ),
    },
    {
        "name": "collected tests are at least the statically-parsed test_* functions",
        "holds": lambda f: f["testsCollected"] >= f["testFunctions"],
        "explain": lambda f: (
            f"pytest collected {f['testsCollected']} but a static parse finds {f['testFunctions']} "
            f"test_* functions. Parametrization can only add. Re-run --record."
        ),
    },
    {
        "name": "the coverage percentage follows from the statement counts",
        "holds": lambda f: (
            abs(
                round(
                    100
                    * (f["coverageStatements"] - f["coverageMissed"])
                    / f["coverageStatements"],
                    2,
                )
                - f["coveragePercent"]
            )
            < 0.005
        ),
        "explain": lambda f: (
            f"({f['coverageStatements']} - {f['coverageMissed']}) / {f['coverageStatements']} = "
            f"{100 * (f['coverageStatements'] - f['coverageMissed']) / f['coverageStatements']:.2f}%, "
            f"but the artifact records {f['coveragePercent']}%."
        ),
    },
]


# ── resolve ──────────────────────────────────────────────────────────────


def fail(msg: str) -> None:
    print(f"\n  ✗ {msg}\n", file=sys.stderr)
    raise SystemExit(1)


def load_artifact() -> dict:
    if not ARTIFACT.exists():
        fail(
            f"{ARTIFACT.relative_to(REPO)} is missing.\n"
            f"      Recorded facts (test counts, coverage) have no source without it.\n"
            f"      Run: python3 scripts/readme_facts.py --record"
        )
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def resolve_facts() -> tuple[dict, dict]:
    artifact = load_artifact()
    values: dict = {}
    for fid, fact in FACTS.items():
        if fact["kind"] == "static":
            values[fid] = fact["compute"]()
        else:
            rec = (artifact.get("facts") or {}).get(fid)
            if rec is None:
                fail(
                    f'fact "{fid}" is recorded, but {ARTIFACT.relative_to(REPO)} has no entry '
                    f"for it.\n      Run: python3 scripts/readme_facts.py --record"
                )
            values[fid] = rec["value"]
    return values, artifact


# ── check / write ────────────────────────────────────────────────────────


def _decimals(found: str) -> int | None:
    return len(found.split(".")[1]) if "." in found else None


def same_number(found: str, expected) -> bool:
    """
    Compare at the precision the site itself uses.

    `baseline_rules_v3.json` stores macro_f1 as 0.9791304347826086; the README
    quotes 0.9791. Demanding string equality against the stored float would put
    sixteen digits in a sentence, and truncating the truth to four before
    comparing would let 0.97913 and 0.97919 both satisfy a site claiming 0.9791
    — they do, and correctly so, because that is what "0.9791" asserts. So the
    truth is rounded to the site's own number of decimal places. A site that
    wants a tighter claim simply writes more digits.
    """
    try:
        f = float(strip_commas(found))
    except ValueError:
        return False
    d = _decimals(found)
    return round(float(expected), d) == f if d is not None else float(expected) == f


def render(found: str, expected, word: bool) -> str:
    """Format `expected` the way the site already formats its number."""
    if word:
        w = to_word(expected)
        return w.capitalize() if found[:1].isupper() else w
    d = _decimals(found)
    if d is not None:
        return f"{float(expected):.{d}f}"
    return with_commas(expected) if "," in found else str(int(expected))


DATE_SITE = re.compile(
    r"figures were recorded on (\d{4}-\d{2}-\d{2}) by `python3 scripts/readme_facts\.py --record`"
)


def run(mode: str) -> None:
    values, artifact = resolve_facts()
    problems: list[str] = []
    rewrites = 0

    files: dict[str, dict] = {}

    def load(rel: str) -> dict:
        if rel not in files:
            files[rel] = {"text": (REPO / rel).read_text(encoding="utf-8"), "dirty": False}
        return files[rel]

    def line_of(src: str, index: int) -> int:
        return src.count("\n", 0, index) + 1

    for fid, fact in FACTS.items():
        expected = values[fid]
        for raw in fact["sites"]:
            site = {"re": raw} if isinstance(raw, str) else raw
            rel = site.get("file", "README.md")
            word = site.get("word", False)
            entry = load(rel)
            matches = list(re.finditer(site["re"], entry["text"]))

            # The rule that makes this a checker and not a decoration.
            if not matches:
                problems.append(
                    f"{fid}: a claim site in {rel} matched NOTHING.\n"
                    f"      pattern  {site['re']}\n"
                    f"      This means the sentence was reworded and this fact is no longer\n"
                    f"      verified anywhere. Update the pattern in scripts/readme_facts.py,\n"
                    f"      or delete the site if the claim is genuinely gone."
                )
                continue

            # Right-to-left so earlier match offsets stay valid while rewriting.
            for m in reversed(matches):
                found = m.group(1)
                ok = (found.lower() == to_word(expected)) if word else same_number(found, expected)
                if ok:
                    continue
                want = render(found, expected, word)
                if mode == "write":
                    replaced = m.group(0).replace(found, want, 1)
                    entry["text"] = entry["text"][: m.start()] + replaced + entry["text"][m.end():]
                    entry["dirty"] = True
                    rewrites += 1
                else:
                    problems.append(
                        f"{fid}: {rel}:{line_of(entry['text'], m.start())} says {found}, "
                        f"but {fact['describe']} is {expected}.\n"
                        f"      context  {m.group(0).strip()[:100]}"
                    )

    for inv in INVARIANTS:
        if not inv["holds"](values):
            problems.append(f"invariant broken — {inv['name']}\n      {inv['explain'](values)}")

    # The README prints the date its recorded figures were taken. That date is
    # itself a claim, so it is checked against the artifact rather than trusted:
    # otherwise numbers can be refreshed while the date stays put, which reads
    # as more provenance than actually exists.
    #
    # It anchors on a sentence that names `--record`, and on nothing else. This
    # README is full of dated sentences — a coverage correction on 2026-08-03, a
    # ruff run on 2026-08-07, a benchmark commit on 2026-08-03 — and every one
    # of them describes a measurement this script does not take. Tying the
    # artifact's date to any of those would invent provenance for a figure that
    # is documented as having none.
    readme = load("README.md")
    dm = DATE_SITE.search(readme["text"])
    if not dm:
        problems.append(
            f"the recorded-figures date sentence no longer matches its pattern "
            f"({DATE_SITE.pattern}).\n"
            f"      A recorded number without its date is a number with no provenance."
        )
    elif dm.group(1) != artifact["recordedAt"]:
        if mode == "write":
            readme["text"] = (
                readme["text"][: dm.start()]
                + dm.group(0).replace(dm.group(1), artifact["recordedAt"])
                + readme["text"][dm.end():]
            )
            readme["dirty"] = True
            rewrites += 1
        else:
            problems.append(
                f"the README says the recorded figures were taken on {dm.group(1)}, but "
                f"{ARTIFACT.relative_to(REPO)} was recorded {artifact['recordedAt']}."
            )

    if mode == "write":
        written = []
        for rel, entry in files.items():
            if entry["dirty"]:
                (REPO / rel).write_text(entry["text"], encoding="utf-8")
                written.append(rel)
        print(
            "  ✓ Everything already agrees with the source. Nothing rewritten."
            if rewrites == 0
            else f"  ✓ rewrote {rewrites} number{'' if rewrites == 1 else 's'} in {', '.join(written)}."
        )
        if problems:
            print("\n  Some problems cannot be fixed by rewriting a number:\n", file=sys.stderr)
            for p in problems:
                print(f"  ✗ {p}\n", file=sys.stderr)
            raise SystemExit(1)
        return

    if problems:
        print(f"\n  README.md disagrees with the code in {len(problems)} place(s):\n", file=sys.stderr)
        for p in problems:
            print(f"  ✗ {p}\n", file=sys.stderr)
        print(
            "  Fix by re-running the source of truth, not by editing prose:\n"
            "    python3 scripts/readme_facts.py --record   # if the suite or coverage moved\n"
            "    python3 scripts/readme_facts.py --write    # then apply to the README\n",
            file=sys.stderr,
        )
        raise SystemExit(1)

    n = len(FACTS)
    sites = sum(len(f["sites"]) for f in FACTS.values())
    print(
        f"  ✓ {n} facts, asserted at {sites} sites across {len(files)} file(s), "
        f"all agree with the code ({len(INVARIANTS)} invariants hold)."
    )


# ── record ───────────────────────────────────────────────────────────────

PYTEST_CMD = "pytest tests -q --cov=jobtracker --cov-report=json:{json} --cov-report=term"


def parse_pytest(out: str) -> dict:
    """
    pytest's summary line. The shapes that matter:

        305 passed, 1 warning in 28.50s
        295 passed, 10 skipped in 31.02s
        2 failed, 303 passed in 33.10s

    Reading only "passed" would make a skipped suite indistinguishable from a
    complete one — and the ten RLS tests are exactly the ones that skip when no
    Postgres is reachable, which is the failure this repository has already had
    once. So every outcome is parsed, and `skipped` is a fact in its own right.
    """
    tail = out.strip().splitlines()[-1] if out.strip() else ""
    counts = {}
    for word in ("passed", "failed", "skipped", "error", "errors", "xfailed", "xpassed"):
        m = re.search(rf"(\d+)\s+{word}\b", tail)
        if m:
            counts[word.rstrip("s") if word == "errors" else word] = int(m.group(1))
    if not counts:
        raise SystemExit(f"  ✗ could not parse pytest's summary line:\n      {tail!r}")
    counts["collected"] = sum(
        counts.get(k, 0) for k in ("passed", "failed", "skipped", "xfailed", "xpassed")
    )
    return counts


def package_coverage(cov: dict, prefix: str) -> tuple[int, int, float]:
    stmts = missed = 0
    for path, entry in cov["files"].items():
        if path.startswith(prefix):
            stmts += entry["summary"]["num_statements"]
            missed += entry["summary"]["missing_lines"]
    pct = round(100 * (stmts - missed) / stmts, 1) if stmts else 0.0
    return stmts, missed, pct


def record() -> None:
    backend = REPO / "backend"
    venv_py = backend / ".venv311" / "bin" / "python"
    python = str(venv_py) if venv_py.exists() else sys.executable
    cov_json = backend / ".readme-facts-coverage.json"
    cmd = [python, "-m", "pytest", "tests", "-q", "--cov=jobtracker",
           f"--cov-report=json:{cov_json}", "--cov-report=term"]
    printable = PYTEST_CMD.format(json=cov_json.name)
    print(f"  → (cd backend && {printable})")

    env = dict(os.environ, JOBTRACKER_ENVIRONMENT="test")
    # pytest exits non-zero on a failing test but still prints its summary. We
    # want the summary either way — a red suite still has a real count, and
    # recording it is more honest than refusing to.
    proc = subprocess.run(cmd, cwd=backend, env=env, capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    counts = parse_pytest(out)
    if not cov_json.exists():
        raise SystemExit("  ✗ pytest-cov did not write the JSON report; is pytest-cov installed?")
    cov = json.loads(cov_json.read_text(encoding="utf-8"))
    cov_json.unlink()

    totals = cov["totals"]
    statements = totals["num_statements"]
    missed = totals["missing_lines"]
    percent = round(totals["percent_covered"], 2)

    scripts_stmts, _, scripts_pct = package_coverage(cov, "jobtracker/scripts/")
    zero = [
        (p, e["summary"]["num_statements"])
        for p, e in cov["files"].items()
        if p.startswith("jobtracker/scripts/") and e["summary"]["percent_covered"] == 0
    ]

    def pkg(prefix: str) -> float:
        return package_coverage(cov, prefix)[2]

    cmd_text = f"cd backend && {printable}"
    artifact = {
        "$comment": (
            "Recorded facts for README.md — figures that require executing something. "
            "Regenerate with `python3 scripts/readme_facts.py --record`, then apply with "
            "`--write`. Do not hand-edit: the point of this file is that these numbers have "
            "a command behind them."
        ),
        "recordedAt": date.today().isoformat(),
        "machine": f"{platform.system()}-{platform.machine()}, {platform.python_version()}",
        "facts": {
            "testsCollected": {"value": counts["collected"], "command": cmd_text},
            "testsSkipped": {"value": counts.get("skipped", 0), "command": cmd_text},
            "coveragePercent": {"value": percent, "command": cmd_text},
            "coverageStatements": {"value": statements, "command": cmd_text},
            "coverageMissed": {"value": missed, "command": cmd_text},
            "coverageCloud": {"value": pkg("jobtracker/cloud/"), "command": cmd_text},
            "coverageAuth": {"value": pkg("jobtracker/auth/"), "command": cmd_text},
            "coverageDatabase": {"value": pkg("jobtracker/database/"), "command": cmd_text},
            "coverageScriptsStatements": {"value": scripts_stmts, "command": cmd_text},
            "coverageScripts": {"value": scripts_pct, "command": cmd_text},
            "scriptsZeroModules": {"value": len(zero), "command": cmd_text},
            "scriptsZeroStatements": {"value": sum(s for _, s in zero), "command": cmd_text},
        },
        # Recorded but deliberately NOT asserted anywhere in the README. A green
        # artifact must not be mistakable for a green suite: --record keeps the
        # counts from a failing run on purpose, so without this block a red run
        # and a clean one leave identical files behind. `dockerAvailable` is here
        # because the ten RLS tests skip silently without it, and "0 skipped" is
        # the one claim on the page that a skip would quietly satisfy.
        "suiteOutcome": {
            "passed": counts.get("passed", 0),
            "failed": counts.get("failed", 0),
            "skipped": counts.get("skipped", 0),
            "errors": counts.get("error", 0),
            "exitCode": proc.returncode,
            "allGreen": proc.returncode == 0 and counts.get("failed", 0) == 0,
            "dockerAvailable": subprocess.run(
                ["docker", "info"], capture_output=True
            ).returncode == 0
            if _which("docker")
            else False,
        },
    }
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(f"\n  ✓ wrote {ARTIFACT.relative_to(REPO)} (recorded {artifact['recordedAt']})")
    if not artifact["suiteOutcome"]["allGreen"]:
        print("    NOTE: the suite was NOT green. The counts are recorded anyway; the outcome")
        print("          is in suiteOutcome so this file cannot be mistaken for a pass.")
    print("    Now run: python3 scripts/readme_facts.py --write")


def _which(prog: str) -> str | None:
    from shutil import which

    return which(prog)


# ── main ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--check"
    if arg == "--record":
        record()
    elif arg == "--write":
        run("write")
    elif arg == "--check":
        run("check")
    else:
        print(
            f"unknown option {arg}\nusage: readme_facts.py [--check|--write|--record]",
            file=sys.stderr,
        )
        raise SystemExit(2)
