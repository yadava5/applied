"""A shared dependency's floor is declared in exactly one file (#704).

The repository carries two pip manifests. ``requirements.txt`` at the root is
what Vercel installs for ``api/index.py``; ``backend/requirements.txt`` is what
the test suite installs, via ``requirements-dev.txt``'s ``-r requirements.txt``.

They were two hand-maintained lists of overlapping packages with nothing
keeping them equal, and the root file admitted as much in its own comment:
"Nothing checks this mechanically." It drifted — five shared packages by
2026-08-15, and three still disagreed after the 2026-09-02 sync:

    sqlmodel             root >=0.0.39   backend >=0.0.14   (25 releases apart)
    sqlalchemy[asyncio]  root >=2.0.52   backend >=2.0.25
    cryptography         root >=50.0.0   backend >=50.0.0,<51

A pip dry-run resolved production to sqlmodel 0.0.42 and the suite to 0.0.32,
so the suite could go green against a version production never runs.

WHY THIS TEST IS SHAPED THIS WAY, AND NOT AS A FLOOR-EQUALITY CHECK. The
obvious gate — "the two files declare the same floor for every shared package"
— is one this repository would have shipped and then trusted, and it does not
work. Floors can be identical while a transitive cap somewhere in the dev stack
still pulls the RESOLVED version below production's. Equal strings, different
installs, green gate. So the invariant asserted here is structural instead:
there is only ever ONE declaration of a shared floor, because
``backend/requirements.txt`` includes the root file rather than restating it.
Nothing can drift if nothing is duplicated.

An upper bound in the backend file is fine and is not a redeclaration — pip
intersects it with the inherited floor. ``cryptography<51`` is the live
example, and it resolves to 50.0.1.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_MANIFEST = REPO_ROOT / "requirements.txt"
BACKEND_MANIFEST = REPO_ROOT / "backend" / "requirements.txt"

INCLUDE_LINE = "-r ../requirements.txt"

#: A requirement line that declares a lower bound, e.g. ``fastapi>=0.141.1``.
#: Deliberately does NOT match a bare upper bound like ``cryptography<51``,
#: which is the one form the backend file is still allowed to carry.
_FLOOR = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)(?:\[[^\]]*\])?\s*>=")


def _declared_floors(path: Path) -> dict[str, str]:
    floors: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = _FLOOR.match(line)
        if match:
            floors[match.group("name").lower().replace("_", "-")] = line
    return floors


def test_the_backend_manifest_includes_the_root_one() -> None:
    text = BACKEND_MANIFEST.read_text(encoding="utf-8")
    assert INCLUDE_LINE in text, (
        f"{BACKEND_MANIFEST.name} must pull the shared floor from the manifest "
        "production installs, rather than restating it"
    )


def test_the_parser_finds_floors_and_ignores_bare_upper_bounds() -> None:
    """The control. Without it, a parser that matched nothing would make the
    duplicate check below pass against an empty set, forever."""
    root = _declared_floors(ROOT_MANIFEST)
    assert len(root) > 10, f"only parsed {len(root)} floors from the root manifest"
    assert "fastapi" in root and "cryptography" in root

    # An upper bound alone is not a floor, and must not be reported as one:
    # that is exactly the line the backend file is allowed to keep.
    backend = _declared_floors(BACKEND_MANIFEST)
    assert "cryptography" not in backend, (
        "a bare upper bound was read as a floor declaration; the duplicate "
        "check would then fail on the one legitimate case"
    )
    assert "sentence-transformers" in backend, "backend-only floors must parse"


def test_no_package_declares_a_floor_in_both_manifests() -> None:
    root = _declared_floors(ROOT_MANIFEST)
    backend = _declared_floors(BACKEND_MANIFEST)
    duplicated = sorted(set(root) & set(backend))
    assert duplicated == [], (
        "these packages declare a lower bound in BOTH manifests, so the two can "
        "drift apart again:\n"
        + "\n".join(f"  {name}: root {root[name]!r} / backend {backend[name]!r}" for name in duplicated)
        + f"\nRaise a shared floor in {ROOT_MANIFEST.name} only; "
        f"{BACKEND_MANIFEST.name} inherits it through '{INCLUDE_LINE}'."
    )
