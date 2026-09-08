#!/usr/bin/env python3
"""Refuse a citation that no longer resolves to what it claims.

The compliance pack — `docs/google/` (the Gmail restricted-scope filing) and
`docs/casa/` (the CASA evidence documents) — is read by assessors who check it
against the code. Its authority is entirely in its `file:line` citations, and a
line number is **uncheckable by construction**: it is a bare integer with no
relationship to anything, so it rots the moment an unrelated edit inserts a line
above it, and nothing anywhere says so.

That is not hypothetical. #754 found ~25 of the filing's citations pointing at
unrelated code; the worst named a security control and landed in connection
pooling. Every one of them was correct when written. A reader following a cite
and landing somewhere unrelated cannot tell rot from error, and neither can
anyone else — which is the whole damage.

WHAT MAKES THIS CHECKABLE

    A citation names a SYMBOL, and the line is recomputed from the source.

`_verify_state` is findable in `gmail_oauth.py` whatever line it moved to. So
each citation is bound to an anchor — the nearest backticked identifier before
it — the anchor is resolved **in the source file** (Python via AST, TypeScript
and YAML via a declaration match), and the line the source gives is what the
document must say. `--write` rewrites the numbers the way
`scripts/readme_facts.py --write` does.

The direction of the check matters. The expectation comes from the source, never
from the document: the document supplies only the symbol's NAME and the claim
being tested. A citation whose anchor cannot be found in the source is a
FAILURE, not a skip — otherwise a renamed symbol would quietly stop being
checked, which is the same defect one level up.

WHY IT DOES NOT RED ON EVERY REFACTOR

A gate that reds whenever code moves gets overridden, and an overridden gate is
worse than none. So a symbol that MOVED is not an error — it is a `--write`.
The gate reds only when

  * a cited file or line does not exist (deletion, truncation);
  * an anchor cannot be resolved in the source (the symbol is GONE or renamed);
  * the document disagrees with what a run of `--write` would produce;
  * a citation has no anchor at all, so nothing recomputes it;
  * a published transcript no longer reproduces.

`--write` is a fixed point: on an honest tree it changes nothing.

THREE KINDS OF ANCHOR

  symbol      the default. The nearest backticked identifier before the
              citation, resolved in the cited file. Covers a `def`, a class, a
              module-level constant, a TypeScript `const`/`function`, a YAML
              job or step key.

  block       for a cited range with no symbol to name — a comment block, a
              workflow step, a run of GRANT statements. Both ends come from
              literal source text, so the extent is pinned exactly. Registered
              in BLOCKS below, and a registration whose site matches nothing is
              a failure (a reworded sentence must not silently drop its check).

  transcript  for a block that publishes a command AND its output. That is a
              strictly harsher claim than a `file:line`, because a reader
              falsifies it in one keystroke and the document has told them
              which keystroke. The command is registered HERE, not taken from
              the document — a document is untrusted input in a public repo —
              and the document's printed command must equal the registered one.

A RANGE'S END IS TRANSLATED, AND THAT IS A STATED LIMIT

A symbol anchor pins the START. The end of a range moves by the same delta, so
an insertion above a cited region — the mechanism behind every drift #754
documented, including two identical +34s from one edit — is corrected exactly.
A region that grows *in place* keeps a range one or two lines short and this
gate will not notice. Where the exact extent is the claim, use a `block`, which
reads both ends from the source.

Exit 0 when the pack agrees with the tree, 1 when it does not. Stdlib only, no
network, no install — the same contract as `check_decisions.py`.

USAGE
  python3 scripts/check_citations.py            # --check: verify, exit 1 on drift
  python3 scripts/check_citations.py --write    # rewrite the numbers in place
  python3 scripts/check_citations.py --audit    # print every citation and its anchor
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Globbed, not enumerated. A new document dropped into either directory is
#: covered without editing this script — a file list is a registration list,
#: and a registration list is unchecked coverage.
DOC_ROOTS = ("docs/google", "docs/casa")

#: `ml/demo/space/` is a vendored copy of parts of the backend for a Hugging
#: Face demo. It duplicates `config.py`, `credentials/cloud.py`, `types.py` and
#: `classifier/rules.py`, so a short citation like `cloud.py:116` matches two
#: files. The pack documents the deployed backend; the demo copy is never what
#: it means.
EXCLUDED_PREFIXES = ("ml/demo/space/",)

#: The gate has to be RUN to be a gate. Both documents now say a gate checks
#: their citations, so this script verifies that a workflow actually invokes it
#: — otherwise the pack would carry a fresh ungated self-claim in place of the
#: stale one #754 deleted.
SELF = "scripts/check_citations.py"
WORKFLOWS = ".github/workflows"


# ──────────────────────────────────────────────────────────────────────────
# Source-side resolvers. Every one of these reads the SOURCE FILE. None of
# them consults the document, which is the point: the document is the claim
# under test, not evidence for it.
# ──────────────────────────────────────────────────────────────────────────


class Unresolved(Exception):
    """The anchor is not in the source, or is there more than once."""


_source_cache: dict[str, str] = {}


def source(rel: str) -> str:
    if rel not in _source_cache:
        _source_cache[rel] = (REPO_ROOT / rel).read_text(encoding="utf-8")
    return _source_cache[rel]


def line_count(rel: str) -> int:
    return len(source(rel).splitlines())


def py_symbol(rel: str, name: str) -> int:
    """The line a Python def/class/assignment named `name` starts on.

    `node.lineno` of a decorated function is its `def` line, not the decorator,
    which is what these documents cite. Two definitions of one name is an
    ambiguity the author has to break by naming something else — resolving it
    silently would pick a side and call it verified.

    Assignments count only at module or class level. A LOCAL variable is not a
    citable symbol, and treating one as an anchor binds citations to accidents:
    `range` as a `Query(...)` parameter resolved to an unrelated local 1,200
    lines away on the first run of this script.
    """
    try:
        tree = ast.parse(source(rel))
    except SyntaxError as exc:  # pragma: no cover - a broken tree is CI's job
        raise Unresolved(f"{rel} does not parse: {exc}") from exc
    hits: list[int] = []

    def walk(body: list[ast.stmt], bindings: bool) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == name:
                    hits.append(node.lineno)
                walk(node.body, isinstance(node, ast.ClassDef))
            elif bindings and isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == name:
                        hits.append(node.lineno)
            elif bindings and isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.target.id == name:
                    hits.append(node.lineno)

    walk(tree.body, True)
    return _one(hits, rel, name)


def ts_symbol(rel: str, name: str) -> int:
    """The line a TypeScript declaration of `name` starts on."""
    pattern = re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?"
        r"(?:const|let|var|function|async function|class|interface|type|enum)\s+"
        + re.escape(name)
        + r"\b"
    )
    hits = [i for i, line in enumerate(source(rel).splitlines(), 1) if pattern.match(line)]
    return _one(hits, rel, name)


def yaml_key(rel: str, name: str) -> int:
    """The line a YAML mapping key `name:` is defined on."""
    pattern = re.compile(r"^\s*" + re.escape(name) + r":\s*(?:#.*)?$")
    hits = [i for i, line in enumerate(source(rel).splitlines(), 1) if pattern.match(line)]
    return _one(hits, rel, name)


def _one(hits: list[int], rel: str, name: str) -> int:
    if not hits:
        raise Unresolved(f"no definition of `{name}` in {rel}")
    if len(set(hits)) > 1:
        raise Unresolved(
            f"`{name}` is defined {len(hits)} times in {rel} (lines "
            f"{', '.join(str(h) for h in sorted(set(hits)))})"
        )
    return hits[0]


def text_line(rel: str, pattern: str, after: int = 0) -> int:
    """The one line of `rel` matching `pattern`. Zero or many is a failure."""
    rx = re.compile(pattern)
    hits = [
        i
        for i, line in enumerate(source(rel).splitlines(), 1)
        if i > after and rx.search(line)
    ]
    if not hits:
        raise Unresolved(f"no line of {rel} matches /{pattern}/")
    if len(hits) > 1 and after == 0:
        raise Unresolved(
            f"{len(hits)} lines of {rel} match /{pattern}/ (lines "
            f"{', '.join(str(h) for h in hits)}); the anchor has to be unique"
        )
    return hits[0]


def text_lines(rel: str, pattern: str) -> list[int]:
    """Every line of `rel` matching `pattern`, in order."""
    rx = re.compile(pattern)
    hits = [i for i, line in enumerate(source(rel).splitlines(), 1) if rx.search(line)]
    if not hits:
        raise Unresolved(f"no line of {rel} matches /{pattern}/")
    return hits


def resolve_symbol(rel: str, name: str) -> int:
    """Resolve `name` in `rel` by the language the file is written in."""
    if rel.endswith(".py"):
        return py_symbol(rel, name)
    if rel.endswith((".ts", ".tsx")):
        return ts_symbol(rel, name)
    if rel.endswith((".yml", ".yaml")):
        return yaml_key(rel, name)
    raise Unresolved(f"no symbol resolver for {rel}")


def fragment(rel: str, text: str) -> int:
    """The one line of `rel` containing `text` verbatim.

    This is what lets a citation point INSIDE a function without a registry
    entry: the document quotes the line it cites — `getattr(self, name)`,
    `in:anywhere -in:sent`, `mail_scope = "anywhere" if rebuild` — and the
    quotation is looked up in the source. The reviewer gets to see what is at
    the line without opening the file, which is the same thing that makes it
    checkable. Non-unique is a failure: quote more of the line.
    """
    hits = [i for i, line in enumerate(source(rel).splitlines(), 1) if text in line]
    if not hits:
        raise Unresolved(f"the quoted fragment is nowhere in {rel}")
    if len(hits) > 1:
        raise Unresolved(
            f"the quoted fragment is on {len(hits)} lines of {rel} "
            f"({', '.join(str(h) for h in hits[:6])}"
            f"{', …' if len(hits) > 6 else ''}); quote more of the line"
        )
    return hits[0]


def resolve_anchor(rel: str, token: str) -> tuple[int, str]:
    """Resolve one backticked token against the source. Returns (line, how)."""
    ident = IDENT.match(token)
    if ident:
        try:
            return resolve_symbol(rel, ident.group("name")), "symbol"
        except Unresolved as exc:
            symbol_why = str(exc)
        try:
            return fragment(rel, token.removesuffix("()")), "fragment"
        except Unresolved:
            raise Unresolved(symbol_why) from None
    return fragment(rel, token), "fragment"


# ──────────────────────────────────────────────────────────────────────────
# BLOCKS — the ranges with no symbol to name.
#
# Each entry claims the numbers its `site` regex captures and computes them
# from the source. `start`/`end` are literal source anchors, so both ends of
# the range are pinned rather than translated. A site matching NOTHING is a
# failure: it means the sentence was reworded and the citation quietly stopped
# being checked.
# ──────────────────────────────────────────────────────────────────────────

GOOGLE = "docs/google/RESTRICTED-SCOPE-JUSTIFICATION.md"
ARCH = "docs/casa/ARCHITECTURE-AND-TENANT-ISOLATION.md"
CRYPTO = "docs/casa/CRYPTOGRAPHY.md"
SECRETS = "docs/casa/SECRET-ACCESS-POLICY.md"
COOKIES = "docs/casa/SESSION-COOKIES.md"

BLOCKS: list[dict] = []


def block(doc: str, site: str, compute, why: str) -> None:
    BLOCKS.append({"doc": doc, "site": site, "compute": compute, "why": why})


def span(rel: str, start: str, end: str):
    """A range delimited by two literal source anchors."""

    def compute() -> tuple[int, ...]:
        first = text_line(rel, start)
        last = text_line(rel, end, after=first - 1)
        return (first, last)

    return compute


def at(rel: str, pattern: str):
    """A single line carrying a literal source anchor."""

    def compute() -> tuple[int, ...]:
        return (text_line(rel, pattern),)

    return compute


def within(rel: str, symbol: str, start: str, end: str | None = None):
    """A line, or a range, anchored INSIDE a named symbol.

    `if value is None:` is on two lines of `gmail_oauth.py` and `return
    disposition === "remove"` on two of `sync-plan.ts`. Scoping the search to
    the function the prose already names makes the anchor unique without
    padding the regex with incidental context — and it fails loudly if the
    function is gone, which is the case a human has to look at.
    """

    def compute() -> tuple[int, ...]:
        base = resolve_symbol(rel, symbol)
        first = text_line(rel, start, after=base)
        if end is None:
            return (first,)
        return (first, text_line(rel, end, after=first))

    return compute


def trail(rel: str, symbol: str, *patterns: str):
    """A range inside `symbol`, walked through waypoints to reach its end.

    `^\\s+\\)$` closes four things inside `delete_gmail_credentials`; the one the
    citation means is the one after the log call. Naming the waypoint is how
    the anchor stays exact without spelling out incidental context.
    """

    def compute() -> tuple[int, ...]:
        at_line = resolve_symbol(rel, symbol)
        seen: list[int] = []
        for pattern in patterns:
            at_line = text_line(rel, pattern, after=at_line)
            seen.append(at_line)
        return (seen[0], seen[-1])

    return compute


def every(rel: str, pattern: str, expect: int | None = None):
    """Every line matching `pattern` — a claim about a whole set of sites."""

    def compute() -> tuple[int, ...]:
        hits = text_lines(rel, pattern)
        if expect is not None and len(hits) != expect:
            raise Unresolved(
                f"{rel} has {len(hits)} lines matching /{pattern}/, not {expect}. "
                f"The document's COUNT is wrong, not just its line numbers — fix "
                f"the prose, because --write can only move numbers, not add them."
            )
        return tuple(hits)

    return compute


# ── docs/google ──────────────────────────────────────────────────────────

GC = "backend/jobtracker/cloud/gmail_client.py"
GO = "backend/jobtracker/cloud/gmail_oauth.py"
HY = "backend/jobtracker/classifier/hybrid.py"
SF = "backend/jobtracker/classifier/setfit_model.py"
SP = "apps/web/lib/gmail/sync-plan.ts"
TY = "apps/web/lib/gmail/types.ts"
IW = "apps/web/components/gmail/InboxWorkbench.tsx"
SB = "apps/web/components/dashboard/SyncBar.tsx"
TB = "backend/tests/test_body_is_never_persisted.py"

block(
    GOOGLE,
    r"`backend/jobtracker/cloud/gmail_client\.py:(\d+)-(\d+)`",
    span(GC, r"^This module used to fetch ``format=", r"^a rejection without a human\.$"),
    "the module docstring's metadata measurement — a comment, not a symbol",
)
block(
    GOOGLE,
    r"\(`backend/jobtracker/classifier/hybrid\.py:(\d+)-(\d+)`\); `classify`",
    span(
        HY,
        r"^\s+self\._lite_mode = settings\.lite_mode or settings\.deployment == \"cloud\"",
        r"^\s+self\._cloud_rules_only = settings\.deployment == \"cloud\"",
    ),
    "the two assignments in __init__ that put the hosted classifier in lite mode",
)
block(
    GOOGLE,
    r"short-circuit itself\) \| `backend/jobtracker/classifier/hybrid\.py:(\d+)-(\d+)` \|",
    span(HY, r"^\s+# Cloud Short-Circuit: Rules-Only Deployment", r"^\s+if self\._cloud_rules_only:"),
    "the short-circuit's comment and its branch, inside classify",
)
block(
    GOOGLE,
    r"`backend/jobtracker/classifier/setfit_model\.py:(\d+)-(\d+)`",
    span(
        SF,
        r"^# One user per model — a Google Workspace API policy constraint",
        r"^# refuses everyone — the desired state, since no deployed path retrains\.$",
    ),
    "the default-deny rationale — a comment block above the guard",
)
block(
    GOOGLE,
    r"`build_gmail_query`,\n\s*`gmail_client\.py:(\d+)-(\d+)`",
    span(GC, r"^def build_gmail_query\($", r"^\s+return base$"),
    "build_gmail_query cited by its whole body",
)
block(
    GOOGLE,
    r"documents at `apps/web/lib/gmail/sync-plan\.ts:(\d+)-(\d+)`",
    span(
        SP,
        r"^ \*   - `scope` is ASYMMETRIC, and it is the trap in this file\.",
        r"^ \*     opposite action; `tests/unit/sync-plan\.test\.mjs` asserts the pair\.",
    ),
    "a JSDoc paragraph, no symbol to name",
)
block(
    GOOGLE,
    r"sent \(`gmail_oauth\.py:(\d+)-(\d+)`\)",
    span(
        GO,
        r"^\s+# A scan that can REMOVE rows must be able to see everything it is judging,",
        r'^\s+mail_scope = "anywhere" if rebuild else _parse_scope\(payload\.scope\)',
    ),
    "the rebuild scope override and the comment that explains it",
)
block(
    GOOGLE,
    r"has no say \(`scanRequestBody`,\n\s*`sync-plan\.ts:(\d+)-(\d+)`\)",
    within(
        SP,
        "scanRequestBody",
        r'^\s+return disposition === "remove"$',
        r'^\s+\? \{ mode: "rebuild", count: depth, range \}$',
    ),
    "the rebuild branch of scanRequestBody, which omits scope",
)
block(
    GOOGLE,
    r"body \(`sync-plan\.ts:(\d+)`\), so that scan reads archived mail",
    at(SP, r'^\s+: \{ mode: "additive", count: depth, range, scope: "anywhere" \};$'),
    "the additive branch of scanRequestBody, which always sends scope",
)
block(
    GOOGLE,
    r'"All mail" segment \(`InboxWorkbench\.tsx:(\d+)-(\d+)`\)',
    span(
        IW,
        r'^\s+\{ value: "inbox", label: "Inbox" \},$',
        r'^\s+\{ value: "anywhere", label: "All mail" \},$',
    ),
    "the two scope options — a JSX literal, no symbol to name",
)
block(
    GOOGLE,
    r"always sends `scope` \(`types\.ts:(\d+)`\)",
    at(TY, r'^\s+params\.set\("scope", filters\.scope\);$'),
    "one line inside buildInboxParams; the line IS the claim",
)
block(
    GOOGLE,
    r"\(`types\.ts:(\d+)-(\d+)`, rendered at",
    span(TY, r"^export const RANGE_OPTIONS = \[$", r"^\] as const;$"),
    "RANGE_OPTIONS cited by extent, because the last entry is the point",
)
block(
    GOOGLE,
    r"`InboxWorkbench\.tsx:(\d+)-(\d+)`\)\. `buildInboxParams`",
    span(IW, r"^\s+<Segmented<RangeValue>$", r"^\s+/>$"),
    "the age control — a JSX fragment, no symbol to name",
)
block(
    GOOGLE,
    r"when it is `\"all\"` \(`types\.ts:(\d+)`\)",
    at(TY, r'^\s+if \(filters\.range !== "all"\) params\.set\("range", filters\.range\);$'),
    "the omission itself — one line inside buildInboxParams",
)
block(
    GOOGLE,
    r"with `default=None` \(`gmail_oauth\.py:(\d+)`\)",
    at(GO, r"^\s+range: str \| None = Query\(default=None\),"),
    "the parameter declaration inside gmail_inbox",
)
block(
    GOOGLE,
    r"which returns `None` for `None` \(`:(\d+)-(\d+)`\)",
    within(GO, "_parse_range_months", r"^\s+if value is None:$", r"^\s+return None$"),
    "the None branch of _parse_range_months; a sub-range",
)
block(
    GOOGLE,
    r"rendered at `SyncBar\.tsx:(\d+)-(\d+)`",
    span(SB, r"^\s+<Segmented<ScanRange>$", r"^\s+/>$"),
    "the scan dialog's window control — a JSX fragment",
)
block(
    GOOGLE,
    r"twelve months \(`gmail_oauth\.py:(\d+)-(\d+)`\)",
    span(
        GO,
        r"^\s+# Not-provided range → default backfill window; explicit \"all\" → no bound\.$",
        r"^\s+\)$",
    ),
    "the sync path's range default; a sub-range of _scan_server_side",
)
block(
    GOOGLE,
    r"`sync-plan\.ts:(\d+)-(\d+)` records the bug",
    span(
        SP,
        r"^ \*   - `range` is ALWAYS sent, including `\"all\"`\.",
        r"^ \*     unreachable by the one control that promises to reach it\.$",
    ),
    "a JSDoc paragraph recording the bug the asymmetry caused",
)
block(
    GOOGLE,
    r"by equality \| `backend/tests/test_body_is_never_persisted\.py:(\d+)` \|",
    at(TB, r"^\s+assert row\.body_snippet == REJECTION_SNIPPET, \($"),
    "the assertion itself — the line IS the evidence",
)
block(
    GOOGLE,
    r"characters\. `test_body_is_never_persisted\.py:(\d+)` pins it",
    at(TB, r"^\s+assert row\.body_text == REJECTION_SNIPPET, \($"),
    "the assertion itself — the line IS the evidence",
)

block(
    GOOGLE,
    r"inside `_collect_page` at `:(\d+)`",
    at(GC, r'^\s+\.list\(userId="me", q=query, maxResults=limit, pageToken=page_token\),$'),
    "the users.messages.list call itself — the line IS the claim",
)
block(
    GOOGLE,
    r"escalating past it \(`:(\d+)`\)",
    within(HY, "classify", r"^\s+if self\._cloud_rules_only:$"),
    "the short-circuit branch inside classify; `if` is not a symbol",
)
block(
    GOOGLE,
    r"and the label filter\s+itself at `:(\d+)-(\d+)`",
    span(
        GC,
        r'^\s+if scope != "anywhere" and "INBOX" not in labels:$',
        r"^\s+continue$",
    ),
    "the history path's label narrowing; a sub-range with no symbol",
)


# ── docs/casa ────────────────────────────────────────────────────────────

APP = "backend/jobtracker/cloud/applications.py"
CC = "backend/jobtracker/credentials/cloud.py"
CONFIG = "backend/jobtracker/config.py"
CONN = "backend/jobtracker/database/connection.py"
CRON = "backend/jobtracker/cloud/cron.py"
MODELS = "backend/jobtracker/database/models.py"
SJ = "backend/jobtracker/auth/supabase_jwt.py"
TSA = "backend/tests/test_secret_access_logging.py"
E2B = "backend/alembic/versions/e2b6f0a4d517_gmail_sync_enrollment.py"
A8D = "backend/alembic/versions/a8d4ec5fba26_enable_rls_policies_postgres_only.py"
C4 = "backend/alembic/versions/c4_user_credentials_rls.py"
CI = ".github/workflows/backend-ci.yml"
DBM = ".github/workflows/db-migrate.yml"
WEB_SERVER = "apps/web/lib/supabase/server.ts"
WEB_MIDDLEWARE = "apps/web/lib/supabase/middleware.ts"
WEB_CLIENT = "apps/web/lib/supabase/client.ts"
WEB_RECOVERY = "apps/web/lib/auth/recoverySession.ts"
WEB_PKCE = "apps/web/lib/supabase/pkceVerifierCookies.ts"

#: Every endpoint that takes identity as a parameter writes the same line, so
#: the anchor is only unique inside the function the prose names.
DEPENDS_PARAM = r"^\s+user_id: uuid\.UUID = Depends\(current_user\),$"

# ARCHITECTURE-AND-TENANT-ISOLATION.md

block(
    ARCH,
    r"\(`backend/jobtracker/cloud/gmail_client\.py:(\d+)-(\d+)`\)",
    span(
        GC,
        r"^So the body is now fetched\.",
        r"^\s+claim true rather than aspirational\.$",
    ),
    "the module docstring's body-handling paragraph — a comment, not a symbol",
)
block(
    ARCH,
    r"the copy itself at `:(\d+)`",
    within(
        APP,
        "_add_training_example",
        r"^\s+text = \(email\.body_snippet if email is not None else body\) or body$",
    ),
    "the copy itself — one line inside _add_training_example",
)
block(
    ARCH,
    r"\(`backend/tests/test_body_is_never_persisted\.py:(\d+)`\) asserts",
    at(TB, r"^\s+assert row\.body_text == REJECTION_SNIPPET, \($"),
    "the assertion itself — the line IS the evidence",
)
block(
    ARCH,
    r"`(?:backend/alembic/versions/)?e2b6f0a4d517_gmail_sync_enrollment\.py:(\d+)`",
    at(E2B, r"^GRANT SELECT, INSERT, DELETE ON gmail_sync_enrollment TO \{RUNTIME_ROLE\};$"),
    "the only GRANT in the migration chain — a line inside a SQL string",
)
block(
    ARCH,
    r"`backend/alembic/versions/e2b6f0a4d517_gmail_sync_enrollment\.py:(\d+),(\d+),(\d+)`",
    every(E2B, r"^\s+FOR (?:SELECT|INSERT|DELETE) TO \{RUNTIME_ROLE\}", expect=3),
    "the three role-scoped policies, cited as a set; the COUNT is the claim",
)
block(
    ARCH,
    r"`a8d4ec5fba26_enable_rls_policies_postgres_only\.py:(\d+)-(\d+)`",
    span(
        A8D,
        r"^\s+CREATE POLICY \{table\}_select ON \{table\}$",
        r"^\s+CREATE POLICY \{table\}_delete ON \{table\}$",
    ),
    "the four CREATE POLICY statements — SQL inside f-strings, no symbol",
)
block(
    ARCH,
    r"`c4_user_credentials_rls\.py:(\d+)-(\d+)`",
    span(
        C4,
        r"^\s*CREATE POLICY user_credentials_owner_select ON user_credentials$",
        r"^\s*FOR DELETE USING \(user_id = auth\.uid\(\)\);$",
    ),
    "the user_credentials policies — SQL inside a string, no symbol",
)
block(
    ARCH,
    r"`backend/jobtracker/database/models\.py:(\d+)-(\d+)`",
    span(
        MODELS,
        r"^\s+THE DELIBERATE EXPOSURE, stated rather than buried\.",
        r"^\s+purpose\.$",
    ),
    "the docstring section the prose names by its heading",
)
block(
    ARCH,
    r"the count itself at `:(\d+)`",
    within(
        GO,
        "gmail_connection_census",
        r"^\s+select\(sa_func\.count\(\)\)\.select_from\(GmailSyncEnrollment\)$",
    ),
    "the count itself — one line inside gmail_connection_census",
)
block(
    ARCH,
    r"its docstring at `:(\d+)-(\d+)`",
    span(
        GO,
        r"^\s+WHY ``gmail_sync_enrollment`` AND NOT ``user_credentials``$",
        r"^\s+enrollment carries no secret, so there is nothing to scope down to\.$",
    ),
    "a docstring section, cited by extent",
)
block(
    ARCH,
    r"`backend/jobtracker/database/connection\.py:(\d+)-(\d+)`",
    span(
        CONN,
        r"^# Row-Level Security: per-request user identity \+ per-transaction GUC wiring$",
        r"^# on the physical connection\.$",
    ),
    "the module's RLS note — a comment block",
)
block(
    ARCH,
    r"connection\.py:\d+-\d+`, `:(\d+)-(\d+)`",
    span(
        CONN,
        r"^\s+search_path_guc = \"set_config\('search_path', 'public', true\)\"$",
        r"^\s+f\"set_config\('request\.jwt\.claims', '\{claims\}', true\)\"$",
    ),
    "the GUC statement builder, from the search_path pin to the claims write",
)
block(
    ARCH,
    r"service container \(`\.github/workflows/backend-ci\.yml:(\d+)-(\d+)`\)",
    within(CI, "rls-postgres", r"^\s+services:$", r"^\s+image: postgres:17$"),
    "a workflow service block; a YAML key is not a symbol the pack can name",
)
block(
    ARCH,
    r"any skip \(`:(\d+)-(\d+)`\)",
    span(CI, r"^\s+- name: Assert the RLS suite actually ran$", r"^\s+PY$"),
    "the skip-is-green guard — a workflow step",
)
block(
    ARCH,
    r"parameter on `gmail_status` \(`gmail_oauth\.py:(\d+)`\)",
    within(GO, "gmail_status", DEPENDS_PARAM),
    "the per-endpoint identity parameter; identical text in six endpoints",
)
block(
    ARCH,
    r"`gmail_authorize` \(`:(\d+)`\)",
    within(GO, "gmail_authorize", DEPENDS_PARAM),
    "the per-endpoint identity parameter; identical text in six endpoints",
)
block(
    ARCH,
    r"`gmail_disconnect` \(`:(\d+)`\)",
    within(GO, "gmail_disconnect", DEPENDS_PARAM),
    "the per-endpoint identity parameter; identical text in six endpoints",
)
block(
    ARCH,
    r"`gmail_inbox` \(`:(\d+)`\)",
    within(GO, "gmail_inbox", DEPENDS_PARAM),
    "the per-endpoint identity parameter; identical text in six endpoints",
)
block(
    ARCH,
    r"`gmail_sync`\s*\n\s*\(`:(\d+)`\)",
    within(GO, "gmail_sync", DEPENDS_PARAM),
    "the per-endpoint identity parameter; identical text in six endpoints",
)
block(
    ARCH,
    r"`gmail_pipeline` \(`:(\d+)`\)",
    at(GO, r"^\s+dependencies=\[Depends\(current_user\)\],$"),
    "the decorator's dependency list — ABOVE the def, so not inside the symbol",
)
block(
    ARCH,
    r"before binding the RLS identity\s*\n\s*\(`:(\d+)`\)",
    at(GO, r"^\s+verified = _verify_state\(state\)$"),
    "the callback's state verification — the line IS the claim",
)
block(
    ARCH,
    r"bearer token \(`cron\.py:(\d+)`, `:(\d+)`\)",
    lambda: (
        text_line(CRON, r"^\s+configured = settings\.vercel_cron_secret$"),
        text_line(CRON, r"^\s+authorization = request\.headers\.get\(\"authorization\"\)$"),
    ),
    "the two carriers the cron secret is read from",
)

# CRYPTOGRAPHY.md

block(
    CRYPTO,
    r"`backend/jobtracker/credentials/cloud\.py:(\d+)`\)\.\nFernet is a specified",
    at(CC, r"^from cryptography\.fernet import Fernet, InvalidToken$"),
    "the import that fixes the construction — the line IS the claim",
)
block(
    CRYPTO,
    r"\(`backend/jobtracker/credentials/cloud\.py:(\d+)-(\d+)`\)",
    span(
        CC,
        r"^- Fernet embeds its own IV in the token, so the ``nonce`` column is$",
        r"^  separate nonce\.$",
    ),
    "the module docstring's nonce paragraph — a comment, not a symbol",
)
block(
    CRYPTO,
    r"not one: `credentials/cloud\.py:(\d+)`",
    at(CC, r"^\s+key = settings\.secret_encryption_key$"),
    "the read itself — this line is what the four-reads claim counts",
)
block(
    CRYPTO,
    r"`cloud/gmail_oauth\.py:(\d+)` and `:(\d+)`, which sign",
    lambda: (
        text_line(
            GO,
            r"^\s+return jwt\.encode\(payload, settings\.secret_encryption_key, "
            r'algorithm="HS256"\)$',
        ),
        within(GO, "_verify_state", r"^\s+settings\.secret_encryption_key,$")()[0],
    ),
    "the two OAuth-state reads of the key — the lines ARE the claim",
)
block(
    CRYPTO,
    r"\(`backend/jobtracker/config\.py:(\d+)`\), which reaches it by name",
    at(CONFIG, r"^\s+if not getattr\(self, name\)$"),
    "the reflective read — the line IS the claim",
)
block(
    CRYPTO,
    r"module docstring \(`cloud\.py:(\d+)-(\d+)`\)",
    span(
        CC,
        r"^- Key rotation is scaffolded via ``key_id`` but v1 ships single-key\.$",
        r"^  old-key decrypt, the row is re-encrypted with the active key\.$",
    ),
    "the module docstring's rotation design — a comment, not a symbol",
)
block(
    CRYPTO,
    r"returns `None` \(`cloud\.py:(\d+)-(\d+)`\)",
    within(CC, "get_gmail_credentials", r"^\s+try:$", r"^\s+return None$"),
    "the decrypt-failure path inside get_gmail_credentials",
)
block(
    CRYPTO,
    r"is identical \(`cloud\.py:(\d+)-(\d+)`\)",
    within(CC, "get_icloud_credentials", r"^\s+try:$", r"^\s+return None$"),
    "the decrypt-failure path inside get_icloud_credentials",
)
block(
    CRYPTO,
    r"\(`backend/tests/test_secret_access_logging\.py:(\d+)`\) asserts",
    at(TSA, r"^\s+assert record\.levelno == logging\.ERROR, record\.levelname$"),
    "the assertion itself — the line IS the evidence",
)
block(
    CRYPTO,
    r"sync again \(`cloud\.py:(\d+)-(\d+)` on Postgres, `:(\d+)`",
    lambda: span(
        CC,
        r"^\s+stmt = stmt\.on_conflict_do_update\($",
        r"^\s+\)$",
    )()
    + (text_line(CC, r"^\s+row\.revoked_at = None  # see the ON CONFLICT branch above$"),),
    "the un-revoke on reconnect, on both the Postgres and SQLite paths",
)
block(
    CRYPTO,
    r"in `_sign_state` \(`backend/jobtracker/cloud/gmail_oauth\.py:(\d+)`\)",
    at(
        GO,
        r"^\s+return jwt\.encode\(payload, settings\.secret_encryption_key, "
        r'algorithm="HS256"\)$',
    ),
    "the signing call — the line IS the claim",
)
block(
    CRYPTO,
    r"verified in `_verify_state` at `:(\d+)`",
    within(GO, "_verify_state", r"^\s+settings\.secret_encryption_key,$"),
    "the verifying read — the line IS the claim",
)
block(
    CRYPTO,
    r"`_SUPABASE_ASYMMETRIC_ALGORITHMS = \[\"ES256\"\]`, `supabase_jwt\.py:(\d+)`",
    at(SJ, r'^_SUPABASE_ASYMMETRIC_ALGORITHMS: list\[str\] = \["ES256"\]$'),
    "the asymmetric allowlist — a module constant, cited by its own line",
)
block(
    CRYPTO,
    r"`_SUPABASE_ALGORITHMS = \[\"HS256\"\]`,\s*\n?\s*`:(\d+)`",
    at(SJ, r'^_SUPABASE_ALGORITHMS: list\[str\] = \["HS256"\]$'),
    "the symmetric allowlist — a module constant, cited by its own line",
)
block(
    CRYPTO,
    r"`backend/jobtracker/auth/supabase_jwt\.py:(\d+)-(\d+)`",
    within(
        SJ,
        "_decode_token",
        r"^\s+jwks_url = settings\.supabase_jwks_url$",
        r"^\s+try:$",
    ),
    "the fail-closed branch inside _decode_token",
)
block(
    CRYPTO,
    r"`_get_jwks_client`,\s*\n`backend/jobtracker/auth/supabase_jwt\.py:(\d+)`",
    within(SJ, "_get_jwks_client", r"^\s+_jwks_client = jwt\.PyJWKClient\("),
    "the cache lifespan — the line IS the claim",
)

# SECRET-ACCESS-POLICY.md

block(
    SECRETS,
    r"docstring mentions —\s*\n?\s*`gmail_oauth\.py:(\d+)` and\s*\n?\s*`credentials/cloud\.py:(\d+)`",
    lambda: (
        text_line(
            GO, r"^\s+Fernet-encrypted with ``settings\.secret_encryption_key``: the signed$"
        ),
        text_line(CC, r'^\s+"""Build a Fernet instance from ``settings\.secret_encryption_key``\.$'),
    ),
    "the two docstring mentions the published grep deliberately drops",
)
block(
    SECRETS,
    r"\(`gmail_oauth\.py:(\d+)`\), verified in `_verify_state` \(`:(\d+)`\)",
    lambda: (
        text_line(
            GO,
            r"^\s+return jwt\.encode\(payload, settings\.secret_encryption_key, "
            r'algorithm="HS256"\)$',
        ),
        within(GO, "_verify_state", r"^\s+settings\.secret_encryption_key,$")()[0],
    ),
    "the two OAuth-state reads of the key",
)
block(
    SECRETS,
    r"\(`config\.py:(\d+)-(\d+)`, the entry itself at `:(\d+)`\)",
    lambda: span(
        CONFIG,
        r"^\s+_GMAIL_OAUTH_REQUIRED_FIELDS: ClassVar\[tuple\[str, \.\.\.\]\] = \($",
        r"^\s+\)$",
    )()
    + (text_line(CONFIG, r'^\s+"secret_encryption_key",$'),),
    "the required-fields tuple and the entry inside it",
)
block(
    SECRETS,
    r"`getattr\(self, name\)` at `:(\d+)`",
    at(CONFIG, r"^\s+if not getattr\(self, name\)$"),
    "the reflective read — the line IS the claim",
)
block(
    SECRETS,
    r"computed field \(`:(\d+)-(\d+)`\)",
    lambda: (
        resolve_symbol(CONFIG, "gmail_oauth_configured"),
        text_line(CONFIG, r"^\s+return not self\.gmail_oauth_missing_fields$"),
    ),
    "the computed field, from its def to its return",
)
block(
    SECRETS,
    r"`_require_configured\(\)` \(`gmail_oauth\.py:(\d+)`\), the status\n"
    r"\s*endpoint \(`:(\d+)`\) and the OAuth callback \(`:(\d+)`\)",
    every(GO, r"^\s+if not settings\.gmail_oauth_configured:$", expect=3),
    "the three request paths that reach the configured check; the COUNT is the claim",
)
block(
    SECRETS,
    r"docstring \(`config\.py:(\d+)-(\d+)`\)",
    span(
        CONFIG,
        r"^\s+var and see exactly what to set\. Only field \*names\* are exposed here —$",
        r"^\s+a 503 detail\. An empty list means the flow is fully configured\.$",
    ),
    "the docstring sentences that make the 503 safe — a comment, not a symbol",
)
block(
    SECRETS,
    r"`CronSyncUserIdsError` \(`backend/jobtracker/config\.py:(\d+)-(\d+)`\)",
    span(CONFIG, r"^class CronSyncUserIdsError", r'^\s+"""$'),
    "the class, cited by the extent of the docstring that explains it",
)
block(
    SECRETS,
    r"\(`cloud\.py:(\d+)-(\d+)` on Postgres, `:(\d+)` on the SQLite test path\)",
    lambda: span(
        CC,
        r"^\s+stmt = stmt\.on_conflict_do_update\($",
        r"^\s+\)$",
    )()
    + (text_line(CC, r"^\s+row\.revoked_at = None  # see the ON CONFLICT branch above$"),),
    "the un-revoke on reconnect, on both the Postgres and SQLite paths",
)
block(
    SECRETS,
    r"`get_gmail_credentials`\n\s*\(`cloud\.py:(\d+)`\) and in `get_icloud_credentials` \(`:(\d+)`\)",
    lambda: (
        within(CC, "get_gmail_credentials", r"^\s+logger\.error\($")()[0],
        within(CC, "get_icloud_credentials", r"^\s+logger\.error\($")()[0],
    ),
    "the two logger.error calls; identical text, so each is scoped to its function",
)
block(
    SECRETS,
    r"\(`backend/tests/test_secret_access_logging\.py:(\d+)`\) asserts",
    at(TSA, r"^\s+assert record\.levelno == logging\.ERROR, record\.levelname$"),
    "the assertion itself — the line IS the evidence",
)
block(
    SECRETS,
    r"\(`cloud\.py:(\d+)-(\d+)`\) and `delete_icloud_credentials` \(`:(\d+)-(\d+)`\)",
    lambda: trail(
        CC,
        "delete_gmail_credentials",
        r"^\s+async with get_session\(\) as session:$",
        r"^\s+_log_secret_access\($",
        r"^\s+\)$",
    )()
    + trail(
        CC,
        "delete_icloud_credentials",
        r"^\s+async with get_session\(\) as session:$",
        r"^\s+_log_secret_access\($",
        r"^\s+\)$",
    )(),
    "the two delete paths, each cited by the extent of its session block",
)
block(
    SECRETS,
    r"`credentials/cloud\.py:(\d+)`; for the OAuth `state` HMAC",
    at(CC, r"^\s+key = settings\.secret_encryption_key$"),
    "the read itself — this line is what the four-reads claim counts",
)
block(
    SECRETS,
    r"`cloud/gmail_oauth\.py:(\d+)` and `:(\d+)`; and, as a truthiness check",
    lambda: (
        text_line(
            GO,
            r"^\s+return jwt\.encode\(payload, settings\.secret_encryption_key, "
            r'algorithm="HS256"\)$',
        ),
        within(GO, "_verify_state", r"^\s+settings\.secret_encryption_key,$")()[0],
    ),
    "the two OAuth-state reads of the key",
)
block(
    SECRETS,
    r"\(`backend/jobtracker/config\.py:(\d+)`\), driven by",
    at(CONFIG, r"^\s+if not getattr\(self, name\)$"),
    "the reflective read — the line IS the claim",
)
block(
    SECRETS,
    r"`\.github/workflows/db-migrate\.yml:(\d+)-(\d+)`",
    span(
        DBM,
        r"^\s+# Scopes DIRECT_URL to an environment so the credential is auditable and$",
        r"^\s+environment: production$",
    ),
    "the environment pin and the comment that explains it",
)
block(
    SECRETS,
    r"credential is present\* \(`:(\d+)`\), \*Confirm the database is reachable\*\s*\n"
    r"\s*\(`:(\d+)`\), \*Record the revision before\* \(`:(\d+)`\), \*alembic upgrade head\*\s*\n"
    r"\s*\(`:(\d+)`\), \*Verify the database reached the revision the code expects\*\s*\n"
    r"\s*\(`:(\d+)`\) and \*Verify row-level security survived the migration\* \(`:(\d+)`\)",
    every(DBM, r"secrets\.DIRECT_URL", expect=6),
    "the six DIRECT_URL reads — the published grep, re-derived from the workflow",
)

# SESSION-COOKIES.md

block(
    COOKIES,
    r"`apps/web/lib/supabase/server\.ts:(\d+)`",
    at(WEB_SERVER, r"^\s+const supabase = createServerClient\($"),
    "the factory call itself — the table's whole subject",
)
block(
    COOKIES,
    r"`apps/web/lib/supabase/middleware\.ts:(\d+)`",
    at(WEB_MIDDLEWARE, r"^\s+const supabase = createServerClient\($"),
    "the factory call itself — the table's whole subject",
)
block(
    COOKIES,
    r"`apps/web/lib/supabase/client\.ts:(\d+)`",
    at(WEB_CLIENT, r"^\s+return createBrowserClient\($"),
    "the factory call itself — the table's whole subject",
)
block(
    COOKIES,
    r"`apps/web/lib/auth/recoverySession\.ts:(\d+)-(\d+)`",
    span(WEB_RECOVERY, r"^\s+httpOnly: true,$", r"^\s+path: RECOVERY_MARKER_PATH,$"),
    "the recovery marker's attribute block",
)
block(
    COOKIES,
    r"`apps/web/lib/supabase/pkceVerifierCookies\.ts:(\d+)-(\d+)`",
    span(WEB_PKCE, r'^\s+response\.cookies\.set\(name, "", \{$', r"^\s+\}\);$"),
    "the deletion write's attribute block",
)
block(
    COOKIES,
    r"pattern already established at\n`apps/web/lib/auth/recoverySession\.ts:(\d+)`",
    at(WEB_RECOVERY, r"^\s+secure: isProduction,$"),
    "the attribute the pattern is named for",
)


# ──────────────────────────────────────────────────────────────────────────
# TRANSCRIPTS — a block that publishes a command AND what it prints.
#
# The command is registered here and run with `bash -c`; the document's own
# `$ …` line must equal it. Taking the command from the document would let a
# pull request put anything it liked into CI's shell, and the document is
# exactly the untrusted half of this check.
#
# Comparison is order-insensitive because `grep -r` walks a directory in
# readdir order, which differs between BSD and GNU grep. The published block
# is kept sorted, which is what `--write` produces.
# ──────────────────────────────────────────────────────────────────────────

TRANSCRIPTS: list[dict] = [
    {
        "doc": SECRETS,
        # The `$ …` line as the document prints it, continuations joined.
        "command": (
            "grep -rn 'settings\\.secret_encryption_key' backend/jobtracker/ \\\n"
            "    | grep -v __pycache__ | grep -v '``'"
        ),
        "why": "§2.3 rule 1 — the three literal reads of the Fernet key variable",
    },
]


# ──────────────────────────────────────────────────────────────────────────
# Document-side parsing.
# ──────────────────────────────────────────────────────────────────────────

#: A citation is always its own inline-code span: `path:123`, `path:12-34`,
#: `path:1,2,3`, or a bare `:123` continuing the previous citation's file.
#: Restricting to inline code is what keeps the transcript block's own output
#: lines from being read as citations — they are checked by re-running the
#: command instead.
CITE_BODY = re.compile(
    r"^(?P<path>(?:[\w.@+-]+/)*[\w.@+-]+\.(?:py|tsx|ts|yml|yaml|sql|json|sh|mjs))?"
    r":(?P<lines>\d+(?:-\d+)?(?:,\d+)*)$"
)
INLINE_CODE = re.compile(r"`([^`\n]+)`")
FENCE = re.compile(r"^ *```", re.MULTILINE)
NUMBER = re.compile(r"\d+")

#: An anchor candidate: a backticked identifier, optionally with `()` or a
#: dotted qualifier. `settings.secret_encryption_key` resolves on its last
#: segment, which is how the pack writes attribute references.
IDENT = re.compile(r"^(?:[A-Za-z_][\w.]*\.)?(?P<name>[A-Za-z_]\w*)(?:\(\))?$")


@dataclass
class Cite:
    doc: str
    raw: str
    line: int
    path: str | None
    target: str | None
    numbers: list[int]
    spans: list[tuple[int, int]]  # char span of each number in the document
    start: int  # char offset of the whole inline-code span
    ranged: bool
    anchor: str | None = None
    expected: list[int] | None = None
    note: str = ""
    claimed_by: str = ""


def fenced_regions(text: str) -> list[tuple[int, int]]:
    """Character spans of fenced code blocks, which are not citation ground."""
    marks = [m.start() for m in FENCE.finditer(text)]
    return [(marks[i], marks[i + 1]) for i in range(0, len(marks) - 1, 2)]


def in_any(pos: int, regions: list[tuple[int, int]]) -> bool:
    return any(a <= pos < b for a, b in regions)


def docs_in_scope() -> list[str]:
    out: list[str] = []
    for root in DOC_ROOTS:
        out += sorted(str(p.relative_to(REPO_ROOT)) for p in (REPO_ROOT / root).glob("*.md"))
    return out


def tracked_files() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return set(out.split())


def resolve_path(cited: str, tracked: set[str]) -> tuple[str | None, str]:
    """Map a citation's path — often a suffix — onto one tracked file."""
    exact = [
        t
        for t in tracked
        if (t == cited or t.endswith("/" + cited))
        and not t.startswith(EXCLUDED_PREFIXES)
    ]
    if len(exact) == 1:
        return exact[0], ""
    if not exact:
        return None, f"no tracked file matches `{cited}`"
    return None, (
        f"`{cited}` matches {len(exact)} tracked files "
        f"({', '.join(sorted(exact))}); cite a longer path"
    )


def parse_cites(doc: str, text: str, tracked: set[str]) -> tuple[list[Cite], list[str]]:
    problems: list[str] = []
    cites: list[Cite] = []
    fences = fenced_regions(text)
    last_target: str | None = None
    for m in INLINE_CODE.finditer(text):
        if in_any(m.start(), fences):
            continue
        body = CITE_BODY.match(m.group(1))
        if not body:
            continue
        raw = m.group(0)
        line = text.count("\n", 0, m.start()) + 1
        path = body.group("path")
        if path:
            target, why = resolve_path(path, tracked)
            if target is None:
                problems.append(f"{doc}:{line}: {raw} — {why}.")
            else:
                last_target = target
        else:
            target = last_target
            if target is None:
                problems.append(
                    f"{doc}:{line}: {raw} continues a file that was never named."
                )
        base = m.start(1) + (len(path) if path else 0) + 1
        numbers, spans = [], []
        for nm in NUMBER.finditer(body.group("lines")):
            numbers.append(int(nm.group(0)))
            spans.append((base + nm.start(), base + nm.end()))
        cites.append(
            Cite(
                doc=doc,
                raw=raw,
                line=line,
                path=path,
                target=target,
                numbers=numbers,
                spans=spans,
                start=m.start(),
                ranged="-" in body.group("lines"),
            )
        )
    return cites, problems


def anchor_window(text: str, cite: Cite) -> str:
    """The text a citation may take its anchor from.

    The enclosing paragraph, or — inside a table — the enclosing row, because a
    row above is a different claim about a different file.
    """
    line_start = text.rfind("\n", 0, cite.start) + 1
    if text[line_start : line_start + 1] == "|":
        return text[line_start : cite.start]
    return text[max(text.rfind("\n\n", 0, cite.start) + 2, cite.start - 700) : cite.start]


def bind_anchor(text: str, cite: Cite) -> str:
    """Resolve `cite` against the source; fill in `expected`. Returns a problem."""
    if cite.target is None:
        return ""  # already reported by parse_cites
    tried: list[tuple[str, str]] = []
    for m in reversed(list(INLINE_CODE.finditer(anchor_window(text, cite)))):
        token = m.group(1)
        if any(token == t for t, _ in tried) or CITE_BODY.match(token):
            continue
        try:
            start, how = resolve_anchor(cite.target, token)
        except Unresolved as exc:
            tried.append((token, str(exc)))
            continue
        cite.anchor = token
        cite.note = how
        if cite.ranged:
            delta = start - cite.numbers[0]
            cite.expected = [start, cite.numbers[1] + delta]
        else:
            cite.expected = [start]
        return ""
    detail = (
        "\n".join(f"      `{n}` — {why}" for n, why in tried)
        if tried
        else "      nothing backticked precedes it in this paragraph"
    )
    return (
        f"{cite.doc}:{cite.line}: {cite.raw} is not anchored to anything.\n"
        f"{detail}\n"
        f"      A line number on its own cannot be checked, which is why this "
        f"pack rotted.\n"
        f"      Name — in backticks, before the citation — the function, class or "
        f"constant it\n"
        f"      points at, or quote the line itself. If the range is a comment "
        f"block, a workflow\n"
        f"      step or a JSX fragment with nothing to name, register it in BLOCKS "
        f"in {SELF}."
    )


# ──────────────────────────────────────────────────────────────────────────
# The run.
# ──────────────────────────────────────────────────────────────────────────


def read_doc(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def transcript_block(text: str) -> tuple[int, int, str, list[str], str] | None:
    """Locate the one fenced block whose first line is a `$ ` command.

    Returns (body_start, body_end, command, output_lines, indent).
    """
    for a, b in fenced_regions(text):
        block_text = text[a:b]
        lines = block_text.splitlines(keepends=True)
        if len(lines) < 2 or lines[1].lstrip().startswith("$ ") is False:
            continue
        indent = lines[1][: len(lines[1]) - len(lines[1].lstrip())]
        cmd_lines = []
        i = 1
        while i < len(lines):
            cmd_lines.append(lines[i].rstrip("\n"))
            if not lines[i].rstrip("\n").endswith("\\"):
                break
            i += 1
        body_start = a + sum(len(x) for x in lines[: i + 1])
        body_end = a + sum(len(x) for x in lines)
        command = "\n".join(x[len(indent) :] if x.startswith(indent) else x for x in cmd_lines)
        command = command[2:] if command.startswith("$ ") else command
        out = [x[len(indent) :] if x.startswith(indent) else x for x in text[body_start:body_end].splitlines()]
        return body_start, body_end, command, out, indent
    return None


def check_transcripts(files: dict[str, dict], mode: str, problems: list[str]) -> int:
    rewrites = 0
    for spec in TRANSCRIPTS:
        entry = files[spec["doc"]]
        found = transcript_block(entry["text"])
        if found is None:
            problems.append(
                f"{spec['doc']}: the published transcript block is gone. It said "
                f"what a command prints; that claim is now unchecked."
            )
            continue
        body_start, body_end, command, printed, indent = found
        if command.strip() != spec["command"].strip():
            problems.append(
                f"{spec['doc']}: the printed command is not the one this gate runs.\n"
                f"      document  {command!r}\n"
                f"      gate      {spec['command']!r}\n"
                f"      The gate never runs the document's text — a document is "
                f"untrusted input.\n"
                f"      Change the command in {SELF} and the document together."
            )
            continue
        run = subprocess.run(
            ["bash", "-c", spec["command"]],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        actual = sorted(x for x in run.stdout.splitlines() if x.strip())
        published = sorted(x for x in printed if x.strip())
        if actual == published:
            continue
        if mode == "write":
            body = "".join(f"{indent}{x}\n" for x in actual)
            entry["text"] = entry["text"][:body_start] + body + entry["text"][body_end:]
            entry["dirty"] = True
            rewrites += 1
            continue
        problems.append(
            f"{spec['doc']}: the published transcript is not what the command "
            f"prints ({spec['why']}).\n"
            + "".join(f"      document  {x}\n" for x in published)
            + "".join(f"      actual    {x}\n" for x in actual)
            + "      The document says this was checked by running it. Re-run "
            "`--write`."
        )
    return rewrites


def check_self_is_run(problems: list[str]) -> None:
    """The pack now says a gate checks it. Verify a workflow runs the gate."""
    runners = [
        p.name
        for p in sorted((REPO_ROOT / WORKFLOWS).glob("*.yml"))
        if SELF in p.read_text(encoding="utf-8")
    ]
    if not runners:
        problems.append(
            f"no workflow under {WORKFLOWS}/ runs {SELF}. Both documents state "
            f"that a gate re-resolves their citations; a gate nothing runs is "
            f"the claim #754 deleted, wearing a script's name."
        )


def run(mode: str) -> int:
    tracked = tracked_files()
    docs = docs_in_scope()
    problems: list[str] = []
    files: dict[str, dict] = {d: {"text": read_doc(d), "dirty": False} for d in docs}
    rewrites = 0
    audit: list[Cite] = []

    check_self_is_run(problems)
    rewrites += check_transcripts(files, mode, problems)

    for doc in docs:
        text = files[doc]["text"]
        cites, bad = parse_cites(doc, text, tracked)
        problems += bad

        # BLOCKS first: they claim the numbers they capture, so a citation with
        # no symbol to name is not reported as unanchored.
        claimed: dict[tuple[int, int], tuple[int, str]] = {}
        for spec in [b for b in BLOCKS if b["doc"] == doc]:
            matches = list(re.finditer(spec["site"], text, re.DOTALL))
            if not matches:
                problems.append(
                    f"{doc}: a registered block site matched NOTHING.\n"
                    f"      pattern  {spec['site']}\n"
                    f"      ({spec['why']})\n"
                    f"      The sentence was reworded and this citation is no "
                    f"longer checked anywhere.\n"
                    f"      Update the pattern in {SELF}, or delete the entry if "
                    f"the claim is gone."
                )
                continue
            try:
                want = spec["compute"]()
            except Unresolved as exc:
                problems.append(
                    f"{doc}: a registered block no longer resolves — {exc}.\n"
                    f"      ({spec['why']})\n"
                    f"      The source it anchors on is GONE, which is the one "
                    f"thing --write cannot fix."
                )
                continue
            for m in matches:
                groups = [i for i in range(1, (m.re.groups or 0) + 1) if m.group(i) is not None]
                if len(groups) != len(want):
                    problems.append(
                        f"{doc}: a registered block captures {len(groups)} numbers "
                        f"but resolves {len(want)}.\n      pattern  {spec['site']}"
                    )
                    continue
                for gi, value in zip(groups, want):
                    claimed[m.span(gi)] = (value, spec["why"])

        for cite in cites:
            hits = [claimed.get(s) for s in cite.spans]
            if all(h is not None for h in hits):
                cite.expected = [h[0] for h in hits]  # type: ignore[index]
                cite.anchor = "block"
                cite.note = hits[0][1]  # type: ignore[index]
                cite.claimed_by = "block"
            elif any(h is not None for h in hits):
                problems.append(
                    f"{doc}:{cite.line}: {cite.raw} is only half claimed by a "
                    f"registered block. Widen the block's site pattern."
                )
            else:
                bad_anchor = bind_anchor(text, cite)
                if bad_anchor:
                    problems.append(bad_anchor)
                cite.claimed_by = "symbol"
            audit.append(cite)

        # Bounds. Cheap, and the only thing that catches deletion and truncation.
        for cite in cites:
            if cite.target is None:
                continue
            total = line_count(cite.target)
            for n in cite.numbers:
                if n > total:
                    problems.append(
                        f"{doc}:{cite.line}: {cite.raw} points past the end of "
                        f"{cite.target}, which has {total} lines."
                    )
            if cite.ranged and cite.numbers[0] > cite.numbers[1]:
                problems.append(
                    f"{doc}:{cite.line}: {cite.raw} is a backwards range."
                )

        # Compare, or rewrite. Right-to-left so earlier offsets stay valid.
        pending: list[tuple[tuple[int, int], int]] = []
        for cite in cites:
            if cite.expected is None:
                continue
            for span_, have, want in zip(cite.spans, cite.numbers, cite.expected):
                if have == want:
                    continue
                if mode == "write":
                    pending.append((span_, want))
                    rewrites += 1
                else:
                    what = (
                        f"`{cite.anchor}` is at"
                        if cite.claimed_by == "symbol"
                        else "the source says"
                    )
                    problems.append(
                        f"{doc}:{cite.line}: {cite.raw} says {have}, but "
                        f"{what} {want} in {cite.target}.\n"
                        f"      A reader following this citation lands somewhere "
                        f"else. Run `{SELF} --write`."
                    )
        for (a, b), want in sorted(pending, reverse=True):
            entry = files[doc]
            entry["text"] = entry["text"][:a] + str(want) + entry["text"][b:]
            entry["dirty"] = True

    if mode == "audit":
        for cite in audit:
            where = f"{cite.doc}:{cite.line}"
            got = ",".join(str(n) for n in cite.numbers)
            exp = ",".join(str(n) for n in (cite.expected or []))
            flag = "ok " if cite.expected and cite.numbers == cite.expected else "OUT"
            print(
                f"{flag} {where:<58} {cite.raw:<62} anchor={cite.anchor or '-':<34} "
                f"source={exp or '?'}"
            )
        print(f"\n{len(audit)} citations across {len(docs)} documents.")

    if mode == "write":
        for rel, entry in files.items():
            if entry["dirty"]:
                (REPO_ROOT / rel).write_text(entry["text"], encoding="utf-8")

    n = len(audit)
    if problems:
        print(f"citation gate: {n} citations across {len(docs)} documents, "
              f"{len(problems)} problem(s).\n")
        for p in problems:
            print(f"  {p}")
        print(
            "\nFAIL — the compliance pack disagrees with the tree. These documents "
            "are read by\nassessors who follow the citations; a citation that "
            "lands somewhere unrelated cannot\nbe told apart from an error. "
            f"`{SELF} --write` fixes drift; a symbol that is GONE\nneeds a human."
        )
        return 1
    if mode == "write":
        print(f"citation gate: {n} citations, {rewrites} rewritten.")
        return 0
    print(
        f"citation gate: {n} citations across {len(docs)} documents, every one "
        f"anchored to a symbol or a registered block, every one resolving."
    )
    print("OK")
    return 0


def main(argv: list[str]) -> int:
    arg = argv[1] if len(argv) > 1 else "--check"
    if arg not in ("--check", "--write", "--audit"):
        print(
            f"unknown option {arg}\n"
            f"usage: check_citations.py [--check|--write|--audit]",
            file=sys.stderr,
        )
        return 2
    return run(arg.lstrip("-"))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
