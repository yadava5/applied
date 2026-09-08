"""Every hand-written ``auth.uid()`` must be the one Supabase deploys (#634).

The defect
----------
Five copies of the shim existed. One matched production; **four cast before
they nullified**, and the difference is invisible until a connection is reused.

Measured on ``postgres:16``, one backend pid throughout. ``set_config(..., true)``
is transaction-local, and reverting it at COMMIT leaves the EMPTY STRING rather
than restoring "never set"::

    1. virgin, before anything            current_setting -> None
    2. inside an identified transaction   current_setting -> '{"sub":...}'
    3. next transaction, no identity      current_setting -> ''

Run each shim against both states::

    VIRGIN (GUC unset)
      deployed shape                 -> None
      the other four                 -> None      <- they agree here
    REUSED (GUC = '')
      deployed shape                 -> None
      the other four                 -> RAISES invalid input syntax for type json

The virgin row is why this survived: on a fresh connection all five agree, and
a test suite that opens a connection per test never sees the other row. One of
the four is ``scripts/check_expand_only.py``, which is a CI gate, so this was
not test-only.

Why the check SEARCHES instead of listing
------------------------------------------
A registration list is unchecked coverage: a sixth copy added tomorrow is
invisible to a gate that names five files. This walks the tree and grades every
definition it finds, so a new copy is covered by existing, and the only way to
add one that disagrees is to make this red.

What it does NOT check
----------------------
That the deployed function in Supabase matches this text. Nothing in this
repository can see that; the shims are a local stand-in, and the strongest
available statement is that they agree with each other and with the shape
``test_rls_postgres.py`` records as production's.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

#: Repo root: this file is ``<root>/backend/tests/``.
ROOT = Path(__file__).resolve().parents[2]

#: Directories whose contents are not ours.
SKIP = {".git", "node_modules", ".venv", ".venv311", ".next", "__pycache__", "worktrees", ".claude"}

#: A definition and everything up to its terminating ``$$``.
DEFINITION = re.compile(
    r"CREATE OR REPLACE FUNCTION auth\.uid\(\).*?\$\$(?P<body>.*?)\$\$",
    re.IGNORECASE | re.DOTALL,
)

#: Python string-concatenation artefacts, so a shim spelled across adjacent
#: string literals compares equal to the same SQL written in a heredoc.
_PY_JOIN = re.compile(r'"\s*\n\s*"')


def _normalise(body: str) -> str:
    """The SQL, with spelling that carries no meaning removed.

    Whitespace AROUND punctuation goes too, not just runs of it. A heredoc
    puts a newline before the closing paren where a Python string concatenation
    puts nothing, and both spell the same function — without this the gate
    reds on the difference between `'sub') )::uuid` and `'sub'))::uuid`, which
    is a formatting choice rather than a drift.
    """
    text = re.sub(r"\s+", " ", _PY_JOIN.sub("", body)).strip().lower()
    return re.sub(r"\s*([(),])\s*", r"\1", text)


def _shims() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".md", ".sql", ".yml", ".yaml"}:
            continue
        # RELATIVE TO ROOT, NOT THE ABSOLUTE PATH. `path.parts` carries every
        # directory above the repository too, so a checkout living under a
        # skipped NAME matched itself: inside `<repo>/.claude/worktrees/<agent>`
        # every file's absolute path contains both `.claude` and `worktrees`,
        # the scan returned nothing, and the control below — which refuses to
        # grade an empty scan — went red for reasons that had nothing to do with
        # any shim. The gate could not run at all where most of the work happens.
        #
        # It is the mirror of the defect this file exists to prevent: not a check
        # that cannot fail, but one that cannot pass. Both are the same mistake
        # about what the instrument is measuring.
        if SKIP & set(path.relative_to(ROOT).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for match in DEFINITION.finditer(text):
            found.append((str(path.relative_to(ROOT)), _normalise(match.group("body"))))
    return sorted(found)


#: The shape `test_rls_postgres.py` carries verbatim and the reason it is the
#: reference: `nullif` is applied to the RAW setting, BEFORE the `::jsonb`
#: cast, so an empty string reads as "no identity" instead of raising.
DEPLOYED = _normalise(
    "select coalesce("
    "  nullif(current_setting('request.jwt.claim.sub', true), ''),"
    "  (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')"
    ")::uuid"
)


def test_the_tree_still_contains_shims_to_grade() -> None:
    """The control. An empty scan satisfies every assertion below.

    A path change, a rename or a tightened suffix filter would make this file
    pass while checking nothing, which is the failure mode a search-based gate
    trades for the one it removes.
    """
    found = _shims()

    assert len(found) >= 4, f"expected the known copies, found {[p for p, _ in found]}"


@pytest.mark.parametrize("path", [p for p, _ in _shims()])
def test_every_auth_uid_shim_is_the_deployed_one(path: str) -> None:
    """Parametrised per file so a red names the file that drifted."""
    body = dict(_shims())[path]

    assert body == DEPLOYED, (
        f"{path} does not match the deployed auth.uid().\n"
        f"  found   : {body}\n"
        f"  deployed: {DEPLOYED}\n"
        "A shim that casts before it nullifies raises on a REUSED connection, "
        "where the GUC is '' rather than unset. See this module's docstring."
    )


def test_the_reference_is_not_compared_to_itself() -> None:
    """``DEPLOYED`` is written out here, not read from one of the files.

    Sourcing it from `test_rls_postgres.py` would make the check "the files
    agree with the file we picked", which is green for a tree where every copy
    drifted the same way. This asserts the literal is genuinely present in the
    tree as well, so the reference cannot silently stop describing anything.
    """
    assert DEPLOYED in {body for _p, body in _shims()}
