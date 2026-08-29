"""A skip is green. This makes the green ones say what they cost — issue #470.

WHY THIS EXISTS

Five modules resolve a Postgres at import and are ``skipif not ADMIN_URL``:
``test_rls_postgres``, ``test_migrations_postgres``, and the three that share
``pg_support``. On a machine with no Docker daemon — or with
``testcontainers[postgres]`` / ``psycopg[binary]`` missing — every one of them
skips, and ``pytest -q`` prints::

    1726 passed, 56 skipped in 640.31s

56 tests, including all 21 row-level-security tests, are the only proof the
repository has that tenant isolation is enforced by the DATABASE rather than by
application code that could forget a WHERE clause. That line is what a person
reads before deciding a change is safe, and it does not say which 56.

WHY THIS IS A REPORT AND NOT A GATE

Failing the run would be the stronger mechanism and the wrong one. A laptop with
no Docker is a legitimate place to run the other 1,726 tests, and a gate that
refuses to work there gets deleted or routed around within the week — the repo
says so in its own voice about the advisory ruff and mypy jobs. CI covers the
Postgres modules with real service containers and asserts a zero skip count, so
the published guarantee does not rest on this. What was missing locally was not
enforcement, it was *visibility*.

Kept apart from ``conftest.py`` so the formatting is a pure function over
``(nodeid, reason)`` pairs, testable without arranging for a machine to lack
Docker.
"""

from __future__ import annotations

import re
from collections import defaultdict

#: pytest stores a skip as ``("path", lineno, "Skipped: <reason>")``.
_SKIPPED_PREFIX = re.compile(r"^Skipped:\s*", re.IGNORECASE)


def clean_reason(raw: str) -> str:
    """The reason without pytest's own prefix, collapsed onto one line."""

    return " ".join(_SKIPPED_PREFIX.sub("", raw).split())


def summarise_skips(entries: list[tuple[str, str]]) -> list[str] | None:
    """Lines naming every module that skipped, how many, and why.

    ``entries`` are ``(nodeid, reason)``. Returns ``None`` when nothing skipped,
    so the caller prints nothing at all on the overwhelmingly common path —
    a report that appears on every green run is one nobody reads.
    """

    if not entries:
        return None

    by_module: dict[str, list[str]] = defaultdict(list)
    for nodeid, reason in entries:
        by_module[nodeid.partition("::")[0]].append(clean_reason(reason))

    total = len(entries)
    lines = [
        f"{total} test{'s' if total != 1 else ''} did not run. "
        "A skip is green: this run does NOT support any claim about them."
    ]
    for module in sorted(by_module):
        reasons = by_module[module]
        # One line per distinct reason, so a module skipping for two different
        # causes cannot hide the second behind the first.
        for reason in sorted(set(reasons)):
            n = sum(1 for r in reasons if r == reason)
            lines.append(f"  {module}: {n} skipped — {reason}")
    return lines
