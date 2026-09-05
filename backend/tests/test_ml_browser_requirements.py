"""Every module ``export_onnx.py`` imports is declared somewhere (#759).

`ml/browser/export_onnx.py` imported `optimum` and `onnxruntime` while **no**
manifest in the repository declared either -- seven were checked. The
consequence was not that the script broke; it ran fine, because both happened
to be installed in `backend/.venv311` since 2026-07-17. The consequence was that
no resolver was ever given `optimum-onnx`'s `transformers<4.58.0` ceiling, so
the conflict with `backend/requirements.txt` could not be found by installing
anything.

WHY THIS CHECK IS STATIC AND DOES NOT READ PACKAGE METADATA

The obvious check -- compare the declared range against what the installed
distributions require -- cannot run in CI, because CI does not install
`optimum`. A check that silently skips where it is meant to run is the defect
this repository keeps re-finding, so this reads the SOURCE and the MANIFEST,
both of which are tracked, and is therefore identical everywhere.

The version bound itself is documented in the manifest with the measurement
that produced it. This file guards the thing a static reader can actually
settle: that nothing is imported which nothing declares.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "ml" / "browser" / "export_onnx.py"
MANIFEST = REPO_ROOT / "ml" / "browser" / "requirements.txt"

#: Import name -> distribution name, where they differ. Kept tiny and explicit;
#: a general mapping would need the package index and this check would then
#: depend on the network to answer a question about two tracked files.
DISTRIBUTION_OF = {"sentence_transformers": "sentence-transformers"}

#: Modules the standard library provides. Imported by the script, declared by
#: nobody, and correctly so.
STDLIB = {"json", "pathlib", "__future__"}


def _imported_top_level(path: Path) -> set[str]:
    """Every top-level module name imported anywhere in the file.

    Walks the whole tree rather than the module header: this script does its
    heavy imports INSIDE ``main()``, which is why a header-only reader would
    have reported a clean file for the entire life of the defect.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def _declared() -> dict[str, str]:
    """Distribution name -> the full requirement line, from the manifest."""

    out: dict[str, str] = {}
    for raw in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = raw.split("#")[0].strip()
        if not line:
            continue
        name = line.split("[")[0]
        for sep in (">=", "<=", "==", "!=", "~=", ">", "<"):
            name = name.split(sep)[0]
        out[name.strip().lower()] = line
    return out


def test_the_script_still_imports_things_worth_checking() -> None:
    """Anti-vacuity. If the walk finds nothing, every assertion below is free."""

    found = _imported_top_level(SCRIPT)
    assert "optimum" in found, found
    assert "onnxruntime" in found, found
    assert "transformers" in found, found
    # And prove the walk reaches INSIDE `main()`, which is where they live.
    header_only = {
        n.split(".")[0]
        for node in ast.parse(SCRIPT.read_text(encoding="utf-8")).body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for n in ([a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""])
    }
    assert "optimum" not in header_only, (
        "the heavy imports moved to the module header; this test's reason for "
        "walking the whole tree is gone and the docstring is now wrong"
    )


@pytest.mark.parametrize("module", sorted(_imported_top_level(SCRIPT) - STDLIB))
def test_every_third_party_import_is_declared(module: str) -> None:
    dist = DISTRIBUTION_OF.get(module, module).lower()
    declared = _declared()
    assert dist in declared, (
        f"ml/browser/export_onnx.py imports {module!r} and "
        f"ml/browser/requirements.txt declares no {dist!r}. An undeclared "
        f"import is one no resolver can be given a constraint for, which is "
        f"exactly how optimum-onnx's transformers ceiling stayed invisible."
    )


def test_the_transformers_bound_is_not_the_backend_s() -> None:
    """The two manifests disagree ON PURPOSE, and that must stay visible.

    `backend/requirements.txt` declares a transformers floor this script cannot
    satisfy. Silently widening this manifest to match would put the two back
    into agreement on paper and leave the script broken in fact -- which is the
    state #759 describes.
    """

    line = _declared()["transformers"]
    assert "<4.58" in line, (
        f"ml/browser declares {line!r}. The ceiling comes from optimum-onnx "
        f"(transformers<4.58.0,>=4.36); dropping it is not a widening, it is "
        f"the removal of the only place a resolver can see the conflict."
    )

    backend = (REPO_ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8")
    backend_line = next(
        ln for ln in backend.splitlines() if ln.strip().startswith("transformers")
    )
    assert backend_line.split("#")[0].strip() != line, (
        "the two manifests now declare the same transformers range. Either the "
        "backend moved back under 4.58 -- in which case this test should be "
        "deleted along with the separate manifest -- or this one was widened to "
        "silence the disagreement."
    )
