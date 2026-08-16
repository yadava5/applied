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
                EmailCategory.X: CategoryPatterns(strong=[...], weak=[...],
                                                  negative=[...], veto=[...]),
                ...}`

    Counting by AST rather than by grepping for quotes is what makes this a
    definition-site count: a regex that mentions `strong` in a comment, or a
    pattern list built somewhere else and never placed in PATTERNS, cannot
    contribute.

    `total` is the SCORED patterns — strong + weak + negative — and deliberately
    excludes `veto`, which contributes no points and instead caps a category at
    zero. Vetoes are counted separately and claimed separately, because folding
    them into one number would make the "N strong, M weak, K negative"
    breakdown stop summing to it.
    """
    node = _assigned(rel, "PATTERNS")
    if not isinstance(node, ast.Dict):
        raise SystemExit(f"  ✗ {rel}: PATTERNS is not a dict literal")
    out = {"strong": 0, "weak": 0, "negative": 0, "veto": 0, "categories": len(node.keys)}
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
ENROLLMENT_RLS = "backend/alembic/versions/e2b6f0a4d517_gmail_sync_enrollment.py"
HYBRID = "backend/jobtracker/classifier/hybrid.py"


def _rules(rel: str = BACKEND_RULES) -> dict[str, int]:
    return rules_pattern_counts(rel)


def json_patterns(rel: str) -> int:
    """Scored pattern count in one of the JS ports' rules.json (categories → lists)."""
    data = json.loads(read(rel))
    cats = data["categories"] if "categories" in data else data
    return sum(
        len(group.get(k, []))
        for group in cats.values()
        if isinstance(group, dict)
        for k in ("strong", "weak", "negative")
    )


def json_veto_patterns(rel: str) -> int:
    """Veto count in one of the JS ports' rules.json.

    Separate from `json_patterns` so the port invariants check the veto lists
    too. Without it, a port that carried every scored pattern and none of the
    vetoes would satisfy the count and ship the noun patterns with their guards
    missing — which is the failure the vetoes exist to prevent.
    """
    data = json.loads(read(rel))
    cats = data["categories"] if "categories" in data else data
    return sum(
        len(group.get("veto", []))
        for group in cats.values()
        if isinstance(group, dict)
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


def rls_owner_policies() -> int:
    """The owner-scoped policies: `user_id = auth.uid()` on the tenant tables.

    Not hard-coded as tables×4: the loop is counted, the one-off revision added.
    """
    loop = (rls_tables() - 1) * policies_per_table()
    return loop + count_in(USER_CREDS_RLS, r"CREATE POLICY")


def rls_enrollment_policies() -> int:
    """The policies on `gmail_sync_enrollment` (rev e2b6f0a4d517).

    Counted separately because they are NOT the owner-scoped shape: one of the
    three is a permissive SELECT for the runtime role, which is what lets the
    identity-less cron enumerate who has Gmail linked. Folding them into
    `rls_owner_policies` would make the README's "all N predicates are
    `user_id = (SELECT auth.uid())`" claim false while every gate stayed green.

    Read out of the `_POSTGRES_UPGRADE_SQL` assignment specifically, not out of
    the file: that revision's docstring quotes its own enumeration policy, and
    a whole-file `count_in` therefore returned 5 for a table that has 3 — a
    number nobody would have questioned because it was still "derived".

    `ast.dump` rather than `.value`, because the assignment is an f-string
    (a `JoinedStr`, whose literal halves are separate nodes) — the same shape
    `policies_per_table` reads for the same reason.
    """
    node = _assigned(ENROLLMENT_RLS, "_POSTGRES_UPGRADE_SQL")
    count = ast.dump(node).count("CREATE POLICY")
    if count == 0:
        raise SystemExit(
            f"  ✗ {ENROLLMENT_RLS}: _POSTGRES_UPGRADE_SQL issues no CREATE POLICY. "
            f"A table with no policy fails scripts/verify_rls.py on the deploy."
        )
    return count


def rls_policies() -> int:
    """Every CREATE POLICY the RLS migrations issue, of either shape."""
    return rls_owner_policies() + rls_enrollment_policies()


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


# ── the auto-file gate, across the language boundary ─────────────────────
#
# The gate is `CONFIDENCE_AUTO` in Python, and it is also drawn — in TypeScript
# — on every surface a user actually looks at. It is hand-written as a NAMED
# CONSTANT in twelve places across three trees:
#
#   backend/            4   pinned by tests/test_confidence_gate_lockstep.py
#   apps/web/ + booklet 4   pinned by nothing until #229 (one of the four, the
#                           duplicate `AUTO_FILE_GATE` in components/viz/
#                           GateMeter.tsx, was deleted; booklet's is the third
#                           TypeScript tree and was never counted at all)
#   ml/demo/space/      1   the vendored second copy of the classifier, also
#                           pinned by nothing. It was 3 until #295: the other
#                           two lived in `api/classification.py`, a vendored
#                           copy of a desktop router #298 had already deleted
#                           from `backend/`. A copy that no longer exists
#                           cannot drift, so this is not a loss of coverage —
#                           it is two fewer places for the number to be wrong.
#
# and the comment that claimed to keep them in step named `lib/dashboard/
# model.ts`, which the dashboard barely read: `ReviewQueue` and
# `ApplicationDetail` imported a SECOND `AUTO_FILE_GATE` from
# `components/viz/GateMeter.tsx`. So the named invariant could hold while the
# number a user sees drifted — the same shape as a check that cannot fail.
#
# `backend/tests/test_confidence_gate_lockstep.py` pins the four Python copies
# under `backend/` to each other. It cannot see TypeScript, does not import
# `ml/demo/space`, and no web test can see Python — a check that reads one side
# cannot fail on drift ACROSS the boundary, and that is the drift being guarded
# here. This script already parses all three trees, and `readme-facts.yml` is
# the only workflow with no path filter, so it is the one gate that fires
# whichever side moves. See the invariants at the bottom.
#
# NOT covered, and deliberately so: `0.85` also appears as a bare literal in
# comparisons (`hybrid.py`'s `emb_confidence >= 0.85`, `ml/browser/site/app.js`)
# and as rendered prose in a dozen components and the booklet's content map.
# The literals are a separate fact by the rule stated at the top of this file;
# the prose is not a definition and is left to the README's own claim sites.

# TypeScript trees that draw the gate. Roots, because a census that names files
# can only find the copies someone remembered to name.
TS_GATE_ROOTS = ("apps/web", "booklet/src")
WEB_MODEL = "apps/web/lib/dashboard/model.ts"

# Surfaces that DRAW the gate rather than define it — the rendered-string claim
# sites added by #247. Named here because several carry more than one claim and
# a path repeated inline is a path that gets corrected in one place only.
LANDING_CASCADE = "apps/web/components/landing/Cascade.tsx"
LANDING_SIGNATURE = "apps/web/components/landing/SignatureEnding.tsx"
WEB_SAMPLE_INBOX = "apps/web/components/demo/SampleInbox.tsx"
WEB_IMPORT_MAIL = "apps/web/components/import/ImportMail.tsx"
BROWSER_DEMO_JS = "ml/browser/site/app.js"
BOOKLET_CONTENT = "booklet/src/content.ts"

DEMO_SPACE_HYBRID = "ml/demo/space/jobtracker/classifier/hybrid.py"

# A `const NAME = <float>;` whose name is SCREAMING_CASE. Anchored at the start
# of a line so prose in a `//` or ` *` comment can never match — comments
# restate this number all over the tree and none of them is a definition.
#
# What this does NOT match, stated plainly rather than implied by the invariant
# names below: a lowerCamel or lowercase constant (`const gate = 0.85`), a
# non-const binding, a value built by an expression, and anything without a
# trailing semicolon. Prettier's config makes the semicolon reliable here and
# every existing copy is SCREAMING_CASE, but this is a pattern match and not a
# parser, so it is a floor on coverage rather than a proof of completeness.
TS_GATE_DEF = re.compile(
    r"^\s*(?:export\s+)?const\s+([A-Z_][A-Z0-9_]*)\s*(?::\s*number\s*)?=\s*([0-9]*\.?[0-9]+)\s*;",
    re.MULTILINE,
)

# name → (file, TypeScript constant) for every hand-written TS copy of the gate.
# Same shape, and the same reason, as ``AUTO_FILE_GATE_COPIES`` in the backend
# lock-step test: a red run has to name WHICH copy drifted.
TS_AUTO_FILE_GATE_COPIES: dict[str, tuple[str, str]] = {
    "apps/web/lib/dashboard/model.ts::AUTO_FILE_GATE": (WEB_MODEL, "AUTO_FILE_GATE"),
    "apps/web/components/viz/DecisionTrace.tsx::GATE": (
        "apps/web/components/viz/DecisionTrace.tsx",
        "GATE",
    ),
    "apps/web/lib/demo/sampleInbox.ts::GATE": ("apps/web/lib/demo/sampleInbox.ts", "GATE"),
    "booklet/src/visuals/DecisionTrace.tsx::GATE": (
        "booklet/src/visuals/DecisionTrace.tsx",
        "GATE",
    ),
}

# The vendored second copy of the classifier that ships to the Hugging Face
# Space. Python, but invisible to the backend suite, which never imports it —
# exactly the position `ml/demo/space/jobtracker/classifier/rules.py` is in, and
# it is held the same way: by invariant, from here.
DEMO_SPACE_AUTO_FILE_GATE_COPIES: dict[str, tuple[str, str, str]] = {
    "ml/demo/space::hybrid.py::CONFIDENCE_AUTO": (DEMO_SPACE_HYBRID, "CONFIDENCE_AUTO", ""),
    # Two more entries stood here until #295, both reading
    # `ml/demo/space/jobtracker/api/classification.py` — a module constant and a
    # function-signature default. That file was a vendored copy of a desktop
    # router `backend/` had not contained since #298, and it went with the rest
    # of the vendored `api/` + `services/` trees. The registry shrinks with the
    # copies it registers; the shape (name → file, constant, enclosing function)
    # is kept, since a `""` function still selects the module-constant reader
    # and the next vendored default has somewhere to go.
}

# Gate-shaped TypeScript constants that are NOT the auto-file gate. Listed by
# name so each exclusion is a decision rather than a hole: this one is the 0.95
# CI macro-F1 floor drawn as a marker on the per-class F1 chart. A different
# number that merely shares a variable name; folding it in would make the
# invariant below assert something false.
NOT_THE_AUTO_FILE_GATE = {"apps/web/components/landing/ClassF1Bars.tsx::GATE"}


def ts_float_const(rel: str, name: str) -> float:
    """Read a `const <name> = <float>;` out of a TypeScript module.

    Raises rather than returning a default when the constant is absent or
    defined twice. That is the same rule as a claim site matching zero times: a
    reader that quietly yields nothing when it can no longer find what it was
    reading is not a check, and renaming a constant is exactly how a copy
    escapes one.
    """

    hits = [m for m in TS_GATE_DEF.finditer(read(rel)) if m.group(1) == name]
    if not hits:
        raise SystemExit(
            f"  ✗ {rel}: no `const {name} = <float>;` found. It was renamed, moved or "
            f"deleted — update TS_AUTO_FILE_GATE_COPIES in scripts/readme_facts.py."
        )
    if len(hits) > 1:
        raise SystemExit(f"  ✗ {rel}: `{name}` is defined {len(hits)} times.")
    return float(hits[0].group(2))


def py_arg_default(rel: str, func: str, arg: str) -> float:
    """Read a function parameter's default out of a Python module, statically.

    `float_const` covers module constants; this covers the signature-default
    shape, which looks like coverage to a reader and is invisible to an
    attribute lookup. Raises when the function or the parameter is gone.
    """

    for node in ast.walk(_module(rel)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != func:
            continue
        positional = node.args.posonlyargs + node.args.args
        pairs: dict[str, ast.expr] = {
            a.arg: d for a, d in zip(positional[len(positional) - len(node.args.defaults):], node.args.defaults)
        }
        pairs.update(
            {a.arg: d for a, d in zip(node.args.kwonlyargs, node.args.kw_defaults) if d is not None}
        )
        if arg in pairs:
            return float(ast.literal_eval(pairs[arg]))
    raise SystemExit(f"  ✗ {rel}: no `{func}(..., {arg}=<float>)` default found.")


def demo_space_gate(rel: str, name: str, func: str) -> float:
    """One registry entry from DEMO_SPACE_AUTO_FILE_GATE_COPIES, resolved."""

    return py_arg_default(rel, func, name) if func else float_const(rel, name)


# ── the vendored Space is a COPY, and must stay a copy (#295) ────────────
#
# `ml/demo/space/jobtracker/` is not hand-maintained. `ml/demo/package_space.py`
# builds it with one `shutil.copytree(backend/jobtracker → space/jobtracker,
# ignore=("__pycache__", "*.pyc"))`, so the two module sets are equal BY
# CONSTRUCTION at the moment the Space is assembled.
#
# They had stopped being equal. #298 deleted `backend/jobtracker/api/`,
# `services/` and `main.py` — the unmounted desktop routers, ~55 queries with no
# `user_id` predicate anywhere in them — and did not touch the vendored copy,
# which kept all three. So the tree that ships to a PUBLIC Hugging Face Space
# still carried every full-table read, and `package_space.py` could no longer
# reproduce the thing checked in beside it. That is the state this invariant
# exists to make loud, in either direction: a module added to `backend/` and not
# re-vendored is drift too, and it is the direction that makes the Space stale.
#
# WHY THIS LIVES HERE AND NOT IN `backend/tests/`. `backend-ci.yml` is
# path-filtered to `backend/**` plus three named files, so a PR touching only
# `ml/demo/space/` would never run it — the exact change this guards. This
# script's workflow (`readme-facts.yml`) has no path filter at all. A gate that
# cannot fire on its own subject reads as coverage and is not; see the note on
# the desktop-router deletion in `backend/tests/test_the_deployed_app_is_the_
# cloud_app.py` for the same reasoning applied the other way.
#
# Top-level entries only. This is the `copytree` invariant, not a file-by-file
# diff: the Space legitimately lags `backend/` between re-packagings, and a
# deep comparison would go red on every ordinary classifier edit and get
# switched off. A whole module appearing or vanishing is the drift that matters.
VENDORED_SPACE_PKG = "ml/demo/space/jobtracker"
BACKEND_PKG = "backend/jobtracker"


def _package_modules(rel: str) -> set[str]:
    """Top-level module/package names under a package directory.

    `__pycache__` and `*.pyc` are excluded because `package_space.py` excludes
    them; anything else present on one side and not the other is real drift.
    Raises rather than returning an empty set when the directory is missing —
    a reader that quietly yields nothing when its subject moved is the
    check-that-cannot-fail shape this file is full of warnings about.
    """

    root = REPO / rel
    if not root.is_dir():
        raise SystemExit(
            f"  ✗ {rel}: not a directory. The package moved or was deleted — "
            f"update VENDORED_SPACE_PKG / BACKEND_PKG in scripts/readme_facts.py."
        )
    return {
        entry.name
        for entry in root.iterdir()
        if entry.name != "__pycache__" and entry.suffix != ".pyc"
    }


def ts_gate_definitions() -> dict[str, float]:
    """Census every SCREAMING_CASE gate-named float constant in the TS trees.

    The registry pins the copies it knows about; this finds the ones it does
    not. Without it a thirteenth copy could be hand-written tomorrow and the
    invariant would still pass, having checked four of five — the failure mode
    the backend test's count assertion exists to prevent, and the one that let
    `booklet/src/visuals/DecisionTrace.tsx` sit unnoticed while #229 was being
    written about `apps/web`.
    """

    found: dict[str, float] = {}
    for root_rel in TS_GATE_ROOTS:
        root = REPO / root_rel
        for path in sorted(root.rglob("*")):
            if path.suffix not in (".ts", ".tsx") or not path.is_file():
                continue
            if {"node_modules", ".next", "dist"} & set(path.relative_to(root).parts):
                continue
            rel = path.relative_to(REPO).as_posix()
            for m in TS_GATE_DEF.finditer(path.read_text(encoding="utf-8")):
                if "GATE" in m.group(1):
                    found[f"{rel}::{m.group(1)}"] = float(m.group(2))
    return found


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


def workflow_pin(pattern: str, what: str) -> int:
    """
    A toolchain version the workflows agree on, read out of the workflows.

    Same shape as `ci_min_macro_f1`: collect every pin, fail on disagreement.
    Returning the first hit would document half the truth, and two workflows
    pinning different Node majors is itself a defect worth a red build.

    This exists because of #182. `README.md` and `docs/DEPLOYMENT.md` both said
    Frontend CI ran Node 20 with `setup-node@v4` and `action-setup@v4` long
    after the workflow moved to 22 / v7 / v6 — and the Node number is not
    cosmetic. `pnpm test:unit` imports `.ts` modules from `.mjs` test files and
    needs the runtime's type stripping (>= 22.6); on Node 20 they raise
    ERR_UNKNOWN_FILE_EXTENSION, which is how that suite once existed while no
    job ran it. So the stale docs did not merely lag, they recommended a
    regression a maintainer could make in good faith. Nothing here could catch
    that before: this checker's coverage is declared fact by fact, and no fact
    named the toolchain.
    """
    hits: set[str] = set()
    for p in sorted((REPO / ".github/workflows").iterdir()):
        if p.suffix in (".yml", ".yaml"):
            hits.update(re.findall(pattern, p.read_text(encoding="utf-8")))
    if not hits:
        raise SystemExit(f"  ✗ .github/workflows: no {what} found")
    if len(hits) > 1:
        raise SystemExit(f"  ✗ .github/workflows: workflows disagree on {what}: {sorted(hits)}")
    return int(hits.pop())


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
    "rulesVeto": {
        "kind": "static",
        "describe": "veto patterns in PATTERNS (not scored, not in the total)",
        "compute": lambda: _rules()["veto"],
        "sites": [
            r"A further (\d+) \*\*veto\*\* patterns",
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
    "rlsOwnerPolicies": {
        "kind": "static",
        "describe": "owner-scoped CREATE POLICY statements (the tenant tables)",
        "compute": rls_owner_policies,
        "sites": [
            r"That is \*\*(\d+)\*\* owner policies",
            r"\*\*All (\d+) owner predicates are",
        ],
    },
    "rlsEnrollmentPolicies": {
        "kind": "static",
        "describe": "CREATE POLICY statements on gmail_sync_enrollment",
        "compute": rls_enrollment_policies,
        "sites": [r"\+ `FORCE` with \*\*(\d+)\*\* policies"],
    },
    "rlsPolicies": {
        "kind": "static",
        "describe": "CREATE POLICY statements across the RLS migrations",
        "compute": rls_policies,
        "sites": [
            r"— \*\*(\d+) policies\*\* —",
            r"RLS: (\d+) policies, FORCE",
            r"That is \*\*(\d+) policies\*\* across the nine",
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
    #
    # THE RENDERED STRINGS (#247). #229 pinned every place the gate is DEFINED —
    # twelve named constants across three trees — by invariant. It deliberately
    # did not pin the places it is DRAWN, and those are the ones a user reads.
    # The failure is asymmetric in the worst direction: retune the gate and every
    # definition moves as one while the landing page keeps saying the old number,
    # so the product would make a specific, checkable, false claim on its
    # marketing surface.
    #
    # These are `sites` and not an invariant, which is the opposite of the call
    # made for the constants at the bottom of this file — and for the same
    # reason. `--write` rewriting `const GATE = 0.85;` would let a Python edit
    # silently retune live TypeScript; `--write` rewriting "Below the 0.85 gate
    # nothing is auto-filed" only corrects a sentence, which is exactly what a
    # prose checker is for. So every pattern below is anchored on its
    # surrounding PROSE and cannot match a definition line.
    #
    # DELIBERATELY NOT PINNED, each an omission rather than an oversight:
    #   - `left: "85%"` in booklet/src/visuals/ConfidenceGate.tsx. A CSS
    #     position, not a claim. `same_number` sees no decimal point and would
    #     compare 85.0 against 0.85, so it would be red forever.
    #   - Every `const … = 0.85;` (apps/web/lib/demo/sampleInbox.ts,
    #     booklet/src/visuals/DecisionTrace.tsx). Held by the cross-language
    #     invariant already; a site there is the hazard described above.
    #   - `gate {GATE}` in SampleInbox.tsx and ImportMail.tsx. Interpolated from
    #     the pinned constant, so it cannot drift and there is nothing to check.
    #   - Comments and docstrings. They restate the number all over the tree and
    #     none of them is a surface.
    #   - apps/macos. De-scoped, and its 0.85s are float comparisons, not text.
    #
    # WIDER THAN THE SIX THE ISSUE LISTED, because #229's own lesson is that a
    # first grep finds the tree you were already looking at. #229's covered
    # .py/.ts/.tsx and missed two whole trees; this one adds `ml/browser/site`
    # (plain .js, the in-browser demo) and `ml/demo` + its vendored `ml/demo/
    # space` copy (Gradio, Python), neither of which any web check can see.
    "confidenceAuto": {
        "kind": "static",
        "describe": f"CONFIDENCE_AUTO in {HYBRID}",
        "compute": lambda: float_const(HYBRID, "CONFIDENCE_AUTO"),
        "sites": [
            r"below a ([\d.]+) confidence gate",
            r"CONFIDENCE_AUTO = ([\d.]+)",
            r"confidence ≥ ([\d.]+) \?",
            r"the ([\d.]+) auto-classify threshold",
            # ── drawn on apps/web: the landing page ──
            {"re": r"The ([\d.]+) confidence gate</p>", "file": LANDING_CASCADE},
            {"re": r'text-live">≥ ([\d.]+) <', "file": LANDING_CASCADE},
            {"re": r'text-review">&lt; ([\d.]+) <', "file": LANDING_CASCADE},
            # The label the signature band draws, and the label a screen reader
            # is read instead of it — both are the number a user is told.
            {"re": r"(?m)^\s+([\d.]+) · gate$", "file": LANDING_SIGNATURE},
            {"re": r"clears the ([\d.]+) gate, and resolves", "file": LANDING_SIGNATURE},
            # ── drawn on apps/web: /demo and the import flow ──
            #
            # `apps/web/app/demo/page.tsx` used to draw this claim too
            # ("Below the 0.85 gate nothing is auto-filed"). That site is gone,
            # deliberately: PR #283 rebuilt /demo as the signed-in shell over
            # fixtures, and the verdict-trace section it hosted was retired
            # because the landing renders the same component and the rail's
            # Inbox item now leads to /demo/inbox, where the traces carry real
            # model verdicts instead of fixture ones.
            #
            # Deleted rather than re-pointed, which is the branch this file's
            # own failure message offers when a claim is genuinely gone. It
            # opens no hole: the demo SURFACE still states the gate at
            # /demo/inbox (the next line) and through `SampleInbox`, which
            # /demo/inbox renders. Checked by execution, not by assumption —
            # with this entry removed `--check` reports 53 facts across 164
            # sites all agreeing, and corrupting a SIBLING site
            # (`SampleInbox`'s pattern) still fails, so the fact remains
            # genuinely guarded rather than merely quiet.
            {"re": r"([\d.]+) auto-file gate\.", "file": "apps/web/app/demo/inbox/page.tsx"},
            {"re": r"Confidence sits below the ([\d.]+) gate", "file": WEB_SAMPLE_INBOX},
            {"re": r"Confidence clears the ([\d.]+) gate", "file": WEB_SAMPLE_INBOX},
            {"re": r"Clears the ([\d.]+) gate — Applied would file", "file": WEB_IMPORT_MAIL},
            {"re": r"Below the ([\d.]+) gate — nothing is auto-filed", "file": WEB_IMPORT_MAIL},
            # ── drawn by the two demos no web or backend test can see ──
            {"re": r"below ([\d.]+) — production queues this", "file": BROWSER_DEMO_JS},
            {"re": r"auto-classified \(≥([\d.]+)\)", "file": "ml/demo/app.py"},
            {"re": r"auto-classified \(≥([\d.]+)\)", "file": "ml/demo/space/app.py"},
            # ── printed in the System Card booklet ──
            {"re": r"behind a ([\d.]+) confidence gate", "file": BOOKLET_CONTENT},
            {"re": r'key: "([\d.]+) gate", val:', "file": BOOKLET_CONTENT},
            # Reworded by #251, same reason the lede below it was: "cutoff to
            # auto-file" defined the gate as SUFFICIENT to file, and it is only
            # necessary — `_qualifies_for_hard_row` also needs a nameable
            # employer. A glossary entry is the form of that claim most likely
            # to be quoted, so it says "floor" now. Anchored on the full
            # "confidence floor — necessary to auto-file" rather than on
            # "([\d.]+) confidence", which would also match the kicker at :60
            # and quietly duplicate that site.
            {"re": r'def: "([\d.]+) confidence floor — necessary to auto-file', "file": BOOKLET_CONTENT},
            # THRESHOLDS is a table of hand-written strings. Nothing imports it
            # today, so it is not itself a surface — but it is a copy of the gate
            # in a TS tree that the float-shaped `TS_GATE_DEF` census cannot see,
            # which is precisely how booklet/src went unnoticed through #229.
            {"re": r'(?m)^  gate: "([\d.]+)",$', "file": BOOKLET_CONTENT},
            {"re": r'label: "Gate", detail: "human review", accept: "< ([\d.]+)"', "file": BOOKLET_CONTENT},
            {"re": r'headline: "Below ([\d.]+), a human decides', "file": BOOKLET_CONTENT},
            # Reworded by #251: the card used to say a "single" gate "separates"
            # auto-file from review, which was the defect — clearing the gate is
            # necessary, not sufficient, because the employer must also be
            # nameable. The claim site follows the corrected sentence. Anchored
            # on "is the first thing" rather than on the looser "confidence gate
            # at 0.85", which also matches the kicker at :60 and the glossary at
            # :114 and would silently make this site a duplicate of those.
            {
                "re": r"A confidence gate at ([\d.]+) is the first thing",
                "file": BOOKLET_CONTENT,
            },
            {"re": r'range: "≥ ([\d.]+)", verb: "AUTO-FILE"', "file": BOOKLET_CONTENT},
            {"re": r'stage: "gate", detail: "([\d.]+) → auto / human"', "file": BOOKLET_CONTENT},
            {"re": r"Confidence is drawn against the ([\d.]+) gate", "file": BOOKLET_CONTENT},
            {"re": r'legendGate: "below ([\d.]+) → human"', "file": BOOKLET_CONTENT},
            {"re": r"Confidence gate · ([\d.]+)", "file": "booklet/src/visuals/LayerCascade.tsx"},
            {"re": r'head="≥ ([\d.]+)"', "file": "booklet/src/visuals/LayerCascade.tsx"},
            {"re": r'head="< ([\d.]+)"', "file": "booklet/src/visuals/LayerCascade.tsx"},
            {"re": r"(?m)^\s+([\d.]+) gate$", "file": "booklet/src/visuals/ConfidenceGate.tsx"},
            # Line-anchored so it binds the drawn <text> and not the header
            # comment that describes it — comments are not surfaces.
            {"re": r"(?m)^\s+CONFIDENCE · ([\d.]+)$", "file": "booklet/src/visuals/CoverField.tsx"},
            {
                "re": r"confidence sits below the ([\d.]+) gate — nothing is auto-filed",
                "file": "booklet/src/visuals/DecisionTrace.tsx",
            },
            {"re": r"it is where the ([\d.]+) gate routes every email", "file": "booklet/src/visuals/ClassGrid.tsx"},
            {"re": r'<Fact value="([\d.]+)" unit="gate"', "file": "booklet/src/pages/EndpaperPage.tsx"},
            {"re": r"drop below ([\d.]+) and land in needs_review", "file": "booklet/src/pages/BuildClosingPage.tsx"},
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
    # The OTHER 0.85, and the reason the sites below are split off rather than
    # folded into `confidenceAuto`. Layer 2 accepts on a bare `emb_confidence >=
    # 0.85` literal; the auto-file gate is the named constant `CONFIDENCE_AUTO`.
    # They are equal today and nothing in the code makes them move together, so
    # a chip reading "accept ≥ 0.85" beside `2 · e5 similarity` is a claim about
    # the literal, not about the gate. Binding it to the gate would make the
    # check assert something false the moment either one is retuned — the same
    # count-the-definition-not-the-name discipline as the top of this file.
    "embeddingsAccept": {
        "kind": "static",
        "describe": f"the bare `emb_confidence >= ...` literal in {HYBRID}",
        "compute": embeddings_accept_threshold,
        "sites": [
            r"cosine similarity vs stored examples<br/>accepts at ≥ ([\d.]+)",
            r'E -->\|"≥ ([\d.]+)"\| Out4',
            # The layer-2 chip on the landing page's cascade. Anchored through
            # the layer's own label, because the same key holds 0.90 and 0.70
            # a few lines either side of it.
            {"re": r'label: "e5 similarity",[\s\S]*?accept: "accept ≥ ([\d.]+)"', "file": LANDING_CASCADE},
            # Trace notes on rows the embeddings layer PASSED ON, i.e. fell
            # short of this literal — not of the gate.
            {"re": r"% — below ([\d.]+)\", confidence:", "file": "apps/web/lib/demo/sampleInbox.ts"},
            {"re": r"% — below ([\d.]+)`", "file": BROWSER_DEMO_JS},
            {"re": r'label: "e5 similarity",[\s\S]*?accept: "accept ≥ ([\d.]+)"', "file": BOOKLET_CONTENT},
            {"re": r'(?m)^  embeddings: "([\d.]+)",$', "file": BOOKLET_CONTENT},
            {"re": r'label: "e5 similarity", detail: "cosine 1-NN", accept: "≥ ([\d.]+)"', "file": BOOKLET_CONTENT},
            {"re": r'stage: "e5", detail: "cosine 1-NN · ≥ ([\d.]+)"', "file": BOOKLET_CONTENT},
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
    # ── artifacts NO LONGER on disk ──
    #
    # These three used to be `file_bytes(...)` over ml/browser/artifacts/. The
    # weights were withdrawn on 2026-08-15 (a model fitted partly on
    # a real mailbox should not be published; see README "The published
    # checkpoint was withdrawn" and docs/ML_PROMOTION_POLICY.md), so there is
    # no file left to stat and `file_bytes` would raise.
    #
    # They are PINNED rather than deleted, deliberately. The numbers are real
    # measurements of a real export (2026-08-03) and they are still quoted in
    # four places; dropping the registrations would let that prose drift with
    # nothing watching it. What a pinned fact can no longer do is notice a
    # re-export that changes the size — so if the checkpoint is ever rebuilt
    # (synthetic-only), these must be re-measured by hand, not trusted.
    #
    # Note the failure mode that is being avoided: `file_bytes` raises on a
    # missing path, which is the safe direction. Had it returned 0, `--write`
    # would have cheerfully rewritten the README to "0 bytes" and gone green.
    "onnxFloat32Bytes": {
        "kind": "static",
        "describe": "bytes of the withdrawn model.onnx (pinned 2026-08-03)",
        "compute": lambda: 90362391,
        "sites": [
            r"from ([\d,]+) bytes of float32",
            r"exported to ONNX at \*\*([\d,]+) bytes\*\* float32",
        ],
    },
    "onnxInt8Bytes": {
        "kind": "static",
        "describe": "bytes of the withdrawn model_quantized.onnx (pinned 2026-08-03)",
        "compute": lambda: 22843695,
        "sites": [
            r"\*\*([\d,]+)-byte int8 ONNX\*\*",
            r"quantized to \*\*([\d,]+) bytes\*\* int8",
            r"— was ([\d,]+) bytes",
        ],
    },
    "onnxInt8Mb": {
        # Its own fact, not a formatting of onnxInt8Bytes: a byte-count site
        # regex must never capture "22.8" and rewrite it to "22843695 MB".
        "kind": "static",
        "describe": "the withdrawn model_quantized.onnx in MB, 1 decimal (pinned)",
        "compute": lambda: round(22843695 / 1e6, 1),
        "sites": [r"The ([\d.]+) MB int8 ONNX build"],
    },
    # ── the repository itself ──
    "e2eSpecs": {
        "kind": "static",
        "describe": "*.spec.ts files under apps/web/tests/e2e/",
        "compute": lambda: len(list((REPO / "apps/web/tests/e2e").glob("*.spec.ts"))),
        "sites": [
            r"\((\d+) spec files under",
            # Anchored on the em dash, not on whichever spec happened to be
            # named first. It used to read `— landing`, and the enumeration
            # after it is unchecked prose that had already drifted — 14 names
            # under a claim of 15. Sorting the list to match the directory
            # broke this pattern, which is the gate working: a site matching
            # NOTHING is a failure here, not a silent pass.
            r"\| (\d+) spec files —",
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
    # ── CI toolchain (#182) ──────────────────────────────────────────────
    # The only facts here whose sites live in docs/DEPLOYMENT.md as well as the
    # README, because that file carries the same four numbers in three places
    # and drifted with the README rather than against it.
    "ciNodeMajor": {
        # NOTE for --write: the pin and the floor are two different numbers and
        # they move independently. This fact is the MAJOR the workflows pin
        # (22). Every sentence carrying it also states the floor `test:unit`
        # actually needs — 22.6, plus 21 for the built-in glob — as unchecked
        # prose, because that floor is Node's, not this repository's. If the
        # major ever moves, re-read those clauses; rewriting the digit alone
        # leaves prose asserting a relationship that may no longer hold.
        "kind": "static",
        "describe": "node-version pinned across .github/workflows/",
        "compute": lambda: workflow_pin(r"node-version:\s*['\"]?(\d+)", "node-version"),
        # The quoted form matters: booklet.yml writes `node-version: '22'` while
        # the rest write it bare, and a pattern without `['\"]?` would miss it
        # and report agreement it never checked.
        "sites": [
            r"Node\.js (\d+) and pnpm \d+, for the web app",
            r"on Node (\d+) / pnpm \d+",
            {"re": r"ubuntu-latest, Node (\d+) \+ pnpm \d+", "file": "docs/DEPLOYMENT.md"},
            {"re": r"ubuntu-latest, Node (\d+) \+ Python 3\.11", "file": "docs/DEPLOYMENT.md"},
            {"re": r"`pnpm/action-setup@v\d+`, Node (\d+) via", "file": "docs/DEPLOYMENT.md"},
        ],
    },
    "ciPnpmMajor": {
        "kind": "static",
        "describe": "the `version:` input given to pnpm/action-setup",
        "compute": lambda: workflow_pin(
            r"pnpm/action-setup@v\d+\s*\n\s*with:\s*\n\s*version:\s*['\"]?(\d+)", "pnpm version"
        ),
        "sites": [
            r"Node\.js \d+ and pnpm (\d+), for the web app",
            r"on Node \d+ / pnpm (\d+)",
            {"re": r"ubuntu-latest, Node \d+ \+ pnpm (\d+)", "file": "docs/DEPLOYMENT.md"},
            {"re": r"- pnpm (\d+) via `pnpm/action-setup", "file": "docs/DEPLOYMENT.md"},
        ],
    },
    "setupNodeMajor": {
        "kind": "static",
        "describe": "actions/setup-node major used across .github/workflows/",
        "compute": lambda: workflow_pin(r"actions/setup-node@v(\d+)", "actions/setup-node version"),
        "sites": [
            {"re": r"Node \d+ via `actions/setup-node@v(\d+)`", "file": "docs/DEPLOYMENT.md"},
        ],
    },
    "pnpmActionSetupMajor": {
        "kind": "static",
        "describe": "pnpm/action-setup major used across .github/workflows/",
        "compute": lambda: workflow_pin(r"pnpm/action-setup@v(\d+)", "pnpm/action-setup version"),
        "sites": [
            {"re": r"pnpm \d+ via `pnpm/action-setup@v(\d+)`", "file": "docs/DEPLOYMENT.md"},
        ],
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
        # This fact used to be asserted inside the sentence that dates the
        # never-executed-anywhere finding, and `--write` therefore rewrote the
        # past every time the module grew: the clause read "The 10 that used to
        # skip … as of 2026-08-02" until the 11th test landed, then said 11,
        # then 12. On 2026-08-02 the module held 10 — see README:561's "ten
        # silently skipped ones", which is the same event and is deliberately
        # unbound. A count of what exists NOW cannot live in a clause about a
        # moment; the paragraph now states the current figure in its own
        # present-tense clause and leaves the historical 10 as a literal no
        # fact may touch. Same shape as `testFunctions`/`testModules` below,
        # whose sites are anchored on "at HEAD" so the unbound "300 across 25
        # modules at 37dd805" beside them survives a rewrite.
        "kind": "static",
        "describe": "test_* functions in backend/tests/test_rls_postgres.py",
        "compute": lambda: test_functions(only="test_rls_postgres.py"),
        "sites": [
            {"re": r"(\w+) tests drive the real connection machinery", "word": True},
            r"and \*\*(\d+) tests\*\* now exercise it",
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
            # Reworded 2026-08-12, same fact, still verified. The old sentence
            # ("The remaining difference from N is parametrization") compared
            # this recorded figure against the static function count, and that
            # comparison stopped being true the moment the parse caught up to
            # it — the two are refreshed by different commands and drift on
            # purpose. The site is kept rather than deleted because deleting it
            # is how a number stops being checked while still being published.
            r"The bold (\d+) is the artifact's",
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
        "name": "the strong/weak/negative split accounts for every scored pattern",
        "holds": lambda f: f["rulesStrong"] + f["rulesWeak"] + f["rulesNegative"] == f["rulesPatterns"],
        "explain": lambda f: (
            f"{f['rulesStrong']} + {f['rulesWeak']} + {f['rulesNegative']} = "
            f"{f['rulesStrong'] + f['rulesWeak'] + f['rulesNegative']}, not {f['rulesPatterns']}."
        ),
    },
    {
        "name": "every tenant table gets the same four policies",
        "holds": lambda f: f["rlsOwnerPolicies"] == f["rlsTenantTables"] * f["rlsPoliciesPerTable"],
        "explain": lambda f: (
            f"{f['rlsTenantTables']} tables x {f['rlsPoliciesPerTable']} policies = "
            f"{f['rlsTenantTables'] * f['rlsPoliciesPerTable']}, but the migrations issue "
            f"{f['rlsOwnerPolicies']} owner-scoped CREATE POLICY statements. "
            f"One table is short a policy."
        ),
    },
    {
        # The total is the sum of the two SHAPES, and they are counted apart on
        # purpose: gmail_sync_enrollment's SELECT policy is permissive, so
        # letting it be absorbed into the owner-policy count is exactly how
        # "all N predicates are user_id = auth.uid()" would become false with
        # every gate still green.
        "name": "the policy total is the owner policies plus the enrollment policies",
        "holds": lambda f: (
            f["rlsPolicies"] == f["rlsOwnerPolicies"] + f["rlsEnrollmentPolicies"]
        ),
        "explain": lambda f: (
            f"{f['rlsOwnerPolicies']} owner + {f['rlsEnrollmentPolicies']} enrollment = "
            f"{f['rlsOwnerPolicies'] + f['rlsEnrollmentPolicies']}, not {f['rlsPolicies']}."
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
        "holds": lambda f: (
            _rules(DEMO_SPACE_RULES)["total"] == f["rulesPatterns"]
            and _rules(DEMO_SPACE_RULES)["veto"] == f["rulesVeto"]
        ),
        "explain": lambda f: (
            f"{DEMO_SPACE_RULES} has {_rules(DEMO_SPACE_RULES)['total']} scored patterns and "
            f"{_rules(DEMO_SPACE_RULES)['veto']} vetoes, {BACKEND_RULES} has "
            f"{f['rulesPatterns']} and {f['rulesVeto']}. There are two copies of this file on "
            f"purpose; they have diverged."
        ),
    },
    {
        # Both JSON ports are byte-identical and only one is named here, which
        # is enough: `ml/browser/site/rules.json` is a copy of this file, and
        # the two engines that read them are checked by their own claim sites.
        "name": "the browser port's rules.json carries the same patterns",
        "holds": lambda f: (
            json_patterns("apps/web/lib/demo/rules.json") == f["rulesPatterns"]
            and json_veto_patterns("apps/web/lib/demo/rules.json") == f["rulesVeto"]
        ),
        "explain": lambda f: (
            f"apps/web/lib/demo/rules.json has {json_patterns('apps/web/lib/demo/rules.json')} "
            f"scored patterns and {json_veto_patterns('apps/web/lib/demo/rules.json')} vetoes, "
            f"{BACKEND_RULES} has {f['rulesPatterns']} and {f['rulesVeto']}. The /demo page is "
            f"running a different layer 1 from the product."
        ),
    },
    {
        "name": "the two JSON ports are the same file",
        "holds": lambda f: read("apps/web/lib/demo/rules.json") == read("ml/browser/site/rules.json"),
        "explain": lambda f: (
            "apps/web/lib/demo/rules.json and ml/browser/site/rules.json have diverged. They are "
            "the same pattern table served to two different pages; whichever was regenerated, the "
            "other was not."
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
        # THE CROSS-LANGUAGE ONE (#229). Everything else in this list compares
        # two Python facts, or Python against JSON. This compares Python
        # against TypeScript, because that boundary is where the gate actually
        # drifted and neither language's test suite can see across it.
        #
        # Deliberately an invariant and not a `sites` entry, even though the
        # sites mechanism already reaches into apps/web. `--write` REWRITES a
        # site match in place; pointing it at `const GATE = 0.85;` would let a
        # Python edit silently retune live TypeScript, turning a check into an
        # unreviewed code change. An invariant cannot be auto-repaired, so the
        # second edit stays deliberate — which is the whole point of pinning a
        # threshold that is the fix for a named production defect.
        "name": "every TypeScript copy of the auto-file gate equals the backend's CONFIDENCE_AUTO",
        "holds": lambda f: all(
            ts_float_const(*where) == f["confidenceAuto"]
            for where in TS_AUTO_FILE_GATE_COPIES.values()
        ),
        "explain": lambda f: (
            f"{HYBRID} sets CONFIDENCE_AUTO = {f['confidenceAuto']}, but "
            + "; ".join(
                f"{name} is {ts_float_const(*where)}"
                for name, where in sorted(TS_AUTO_FILE_GATE_COPIES.items())
                if ts_float_const(*where) != f["confidenceAuto"]
            )
            + ". The gate a user sees drawn has drifted from the gate the backend files on. "
            "Change every copy or none — and note the value is the fix for a named "
            "precision defect, not a dial."
        ),
    },
    {
        # Scope stated exactly: SCREAMING_CASE `const NAME = <float>;` whose
        # name contains GATE, under TS_GATE_ROOTS. Not "every gate in the web
        # tree" — see the note on TS_GATE_DEF for what slips past it.
        "name": (
            "the TS trees hand-write GATE-named constants in exactly the registered places"
        ),
        "holds": lambda f: (
            set(ts_gate_definitions()) - NOT_THE_AUTO_FILE_GATE
            == set(TS_AUTO_FILE_GATE_COPIES)
        ),
        "explain": lambda f: (
            f"registered: {sorted(TS_AUTO_FILE_GATE_COPIES)}; "
            f"found on disk: {sorted(set(ts_gate_definitions()) - NOT_THE_AUTO_FILE_GATE)}. "
            f"A gate constant was added, renamed or removed under {TS_GATE_ROOTS} without "
            f"being registered in scripts/readme_facts.py, so the invariant above would "
            f"check every copy but that one. Register it, or add it to "
            f"NOT_THE_AUTO_FILE_GATE with a reason if it is a different number that "
            f"happens to be gate-shaped."
        ),
    },
    {
        # The vendored classifier under ml/demo/space carries its own three
        # copies of the gate. The backend suite never imports that tree, so
        # test_confidence_gate_lockstep.py cannot see them — the same position
        # the second copy of rules.py is in, held the same way. Without this the
        # Space could auto-file at one threshold while the product used another.
        "name": "the vendored classifier under ml/demo/space carries the same auto-file gate",
        "holds": lambda f: all(
            demo_space_gate(*where) == f["confidenceAuto"]
            for where in DEMO_SPACE_AUTO_FILE_GATE_COPIES.values()
        ),
        "explain": lambda f: (
            f"{HYBRID} sets CONFIDENCE_AUTO = {f['confidenceAuto']}, but "
            + "; ".join(
                f"{name} is {demo_space_gate(*where)}"
                for name, where in sorted(DEMO_SPACE_AUTO_FILE_GATE_COPIES.items())
                if demo_space_gate(*where) != f["confidenceAuto"]
            )
            + ". There are two copies of the classifier on purpose; their gates have "
            "diverged, so the Hugging Face Space would auto-file at a threshold the "
            "product does not use."
        ),
    },
    {
        # See the block comment above `_package_modules`. The vendored Space is
        # produced by one `copytree`; this asserts it still looks like one.
        "name": "the vendored Space package holds exactly the backend's modules",
        "holds": lambda f: (
            _package_modules(VENDORED_SPACE_PKG) == _package_modules(BACKEND_PKG)
        ),
        "explain": lambda f: (
            f"only in {VENDORED_SPACE_PKG}: "
            f"{sorted(_package_modules(VENDORED_SPACE_PKG) - _package_modules(BACKEND_PKG))}; "
            f"only in {BACKEND_PKG}: "
            f"{sorted(_package_modules(BACKEND_PKG) - _package_modules(VENDORED_SPACE_PKG))}. "
            f"ml/demo/package_space.py builds the Space with a single copytree, so these "
            f"two sets are equal the moment it runs. Extra modules on the Space side are "
            f"code the backend has DELETED still shipping to a public Space — that is how "
            f"the unscoped desktop routers (#295) outlived #298 by a release. Missing "
            f"modules mean the Space is stale. Re-run ml/demo/package_space.py, or delete "
            f"the leftovers deliberately."
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

    # The recorded figures are only worth anything if the run that produced them
    # passed. `--record` writes `suiteOutcome` and warns when it is red, but a
    # warning is not a gate: nothing stopped a red run's numbers from being
    # written and then agreeing with the README forever after. That is the same
    # shape as a claim site matching zero times — a check that cannot fail.
    outcome = artifact.get("suiteOutcome") or {}
    if not outcome:
        problems.append(
            f"{ARTIFACT.relative_to(REPO)} carries no suiteOutcome, so there is no "
            "evidence the run behind these figures passed. Re-run --record."
        )
    elif not outcome.get("allGreen"):
        problems.append(
            "the recorded figures came from a suite that did not pass "
            f"(exit {outcome.get('exitCode')}, {outcome.get('failed')} failed, "
            f"{outcome.get('skipped')} skipped). Numbers from a red run are not "
            "evidence. Fix the suite, then re-run --record."
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
    complete one — and the RLS tests are exactly the ones that skip when no
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
        # because the RLS tests skip silently without it, and "0 skipped" is
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
