"""One auto-file gate, and every copy of it checked against that one.

``0.85`` is hand-written in two separate backend modules, and until this file
existed the only thing holding them together was a comment in
``cloud/pipeline.py`` saying they were kept in lock-step.

It was four until the desktop routers were deleted (issue #73). Two of the four
lived in ``api/classification.py`` -- ``REVIEW_QUEUE_CONFIDENCE_THRESHOLD`` and
``seed_training_data``'s ``min_confidence`` default -- and went with it. The
count moved from 4 to 2 for that reason and no other; it is NOT a licence to
let a copy drop off the register.

Which raises the question the register could not answer for itself. Until
2026-08-30 the count was pinned by ``len(AUTO_FILE_GATE_COPIES) == 2`` -- the
dict literal below, asserted against itself, so no edit anywhere else in the
tree could move either side of it. It was a check that could not fail, and a
third 0.85 in ``hybrid.classify`` sat unregistered underneath it the whole time.
The count now comes from a CENSUS of ``backend/jobtracker/`` parsed with
``ast``, held against a register in which every entry names WHICH QUANTITY its
0.85 is -- see ``GATE_SHAPED_LITERALS`` at the bottom of this file. That third
copy turned out not to be the gate at all: it was the embedding similarity
floor, the same number for a different reason, and the noun is there so the
next one has to be identified before it can be registered.

A comment cannot fail. These tests can, which is the whole point: the day
someone tunes one copy — the pipeline's gate, the classifier's, the review
queue's, or the training pre-seed default — the suite goes red and names the
copy that drifted, instead of the product quietly filing at one threshold and
queueing at another.

That is not a hypothetical drift. The two copies do different jobs and are
edited for different reasons:

- ``pipeline.AUTO_FILE_GATE`` decides whether a message may assert a hard
  application status (with an employer that can be named — the gate is
  necessary, not sufficient);
- ``hybrid.CONFIDENCE_AUTO`` decides whether the cascade's own verdict is
  flagged ``needs_review``.

Split them and the product tells the user one story on the dashboard and trains
on a second — the classic shape where every gate is
green and the behaviour is still wrong. Filed with #208, which removed a
Settings slider that pretended this number was per-user: it is one number, for
every account, and this file is what keeps it one number *in Python*.

The other half is TypeScript. The gate is also drawn on every surface a user
looks at, and no pytest can import a `.tsx` file — a check that reads one side
cannot fail on drift across the boundary, which is precisely how the web copies
went unpinned while these four were covered (#229). That half lives in
``scripts/readme_facts.py``, which reads ``hybrid.CONFIDENCE_AUTO`` and each
TypeScript gate constant and fails when they disagree. Neither check subsumes
the other; changing this number means editing both languages deliberately.

The VENDORED classifier under ``ml/demo/space/`` carries ONE copy of the gate,
in its ``classifier/hybrid.py``, pinned by ``DEMO_SPACE_AUTO_FILE_GATE_COPIES``
in ``scripts/readme_facts.py``. It carried three until #295: the other two lived
in ``api/classification.py``, a vendored copy of a desktop router ``backend/``
had not contained since #298, and they went with the file. Two fewer copies to
keep in step, not two fewer checks — a copy that does not exist cannot drift.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from jobtracker.classifier import hybrid
from jobtracker.cloud import pipeline

# The canonical values, written out ONCE in the test suite so a change to a gate
# has to be made deliberately in every copy rather than absorbed by an
# assertion derived from one of them.
AUTO_FILE_GATE = 0.85
REVIEW_FLOOR = 0.70


# name → the live value, one entry per hand-written copy in the tree.
AUTO_FILE_GATE_COPIES: dict[str, object] = {
    "cloud/pipeline.py::AUTO_FILE_GATE": pipeline.AUTO_FILE_GATE,
    "classifier/hybrid.py::CONFIDENCE_AUTO": hybrid.CONFIDENCE_AUTO,
}

REVIEW_FLOOR_COPIES: dict[str, object] = {
    "cloud/pipeline.py::REVIEW_FLOOR": pipeline.REVIEW_FLOOR,
    "classifier/hybrid.py::CONFIDENCE_MIN_CLASSIFICATION": (
        hybrid.CONFIDENCE_MIN_CLASSIFICATION
    ),
}


@pytest.mark.parametrize("name", sorted(AUTO_FILE_GATE_COPIES))
def test_every_auto_file_gate_copy_is_the_canonical_gate(name: str) -> None:
    """Each copy of the auto-file gate equals 0.85 — named individually.

    Parametrized rather than folded into one set comparison so a red run says
    WHICH copy drifted, which is the difference between a failure you can act
    on and one you have to go looking for.
    """

    assert AUTO_FILE_GATE_COPIES[name] == AUTO_FILE_GATE, (
        f"{name} is {AUTO_FILE_GATE_COPIES[name]!r}, not the canonical auto-file "
        f"gate {AUTO_FILE_GATE!r}. These two are lock-stepped by THIS FILE — change "
        f"all of them or none. The web side draws the same gate and is held against "
        f"hybrid.CONFIDENCE_AUTO by an invariant in scripts/readme_facts.py, so a "
        f"real change to this number is an edit in two languages."
    )


def test_every_registered_gate_copy_holds_the_canonical_value() -> None:
    """The registered copies of the GATE agree with one another.

    What this does NOT do is count them. ``len(AUTO_FILE_GATE_COPIES) == 2``
    stood here until 2026-08-30 and could not fail: both sides of it were the
    dict literal forty lines above, so no edit anywhere else in the tree could
    move either one. Its docstring claimed "adding a gate without registering it
    is a deliberate edit to this file", which is backwards — an unregistered
    copy in the tree is exactly what it could not see. The count now comes from
    ``test_the_gate_shaped_literals_in_the_tree_are_all_registered`` below,
    which measures the tree.
    """

    assert set(AUTO_FILE_GATE_COPIES.values()) == {AUTO_FILE_GATE}


# =============================================================================
# The census: the register held against a MEASUREMENT OF THE TREE
# =============================================================================
#
# WHAT IS COLLECTED, and why those two shapes:
#
#   * module-level and class-level assignments of the literal 0.85 — how a
#     threshold gets named in this codebase (``CONFIDENCE_AUTO``,
#     ``AUTO_FILE_GATE``, ``SIMILARITY_THRESHOLD``);
#   * ``ast.Compare`` nodes with a 0.85 operand — how an UNNAMED one gets used,
#     which is the copy nobody registers.
#
# ``ast`` and not grep, deliberately. 0.85 appears 21 times textually under
# ``backend/jobtracker/``; most of those are prose — comments and docstrings
# explaining the gate — and a check that counted them would red on a reworded
# sentence. The parser cannot see a comment at all.
#
# EVERY ENTRY CARRIES ITS NOUN. That is the point of the register, not
# decoration. The literal in ``hybrid.classify`` was read as a third copy of the
# auto-file gate and was nothing of the kind — it was the EMBEDDING SIMILARITY
# floor: the same number, a different quantity, and binding it to
# ``CONFIDENCE_AUTO`` would have silently dropped every embedding verdict in the
# review band. Requiring a noun makes that mistake impossible to repeat quietly:
# a new hit cannot be added here without answering WHICH QUANTITY it is.
#
# WHAT IS NOT COLLECTED, named so each exclusion is a decision rather than a
# hole (the shape ``readme_facts.NOT_THE_AUTO_FILE_GATE`` uses):
#
#   * ``config.py::Settings.embedding_similarity_threshold`` — "embedding
#     similarity threshold", a pydantic ``Field(default=0.85)``. A keyword in a
#     call, not an assignment of the constant. Nothing in ``backend/`` reads
#     this field, so it decides nothing.
#   * ``classifier/embeddings.py::find_most_similar(threshold=0.85)`` —
#     "embedding similarity threshold, parameter default". A hand-written fourth
#     copy in this family, but a parameter default rather than either collected
#     shape, and dead as a value: ``find_most_similar`` has no caller outside
#     ``embeddings.py`` and the one call site passes
#     ``threshold=self.SIMILARITY_THRESHOLD`` explicitly, which IS registered.
#   * ``scripts/generate_ml_monitoring_report.py`` and
#     ``scripts/weekly_labeling_workflow.py`` — argparse ``default=0.85``, both
#     "report low-confidence cutoff". Call keywords, overridable from the
#     command line, not thresholds the product decides on.
#   * ``scripts/ingest_datasets.py``'s ``return "assessment", 0.85`` — a
#     hand-labelled confidence for one dataset row, not a threshold at all.
#
# THE VENDORED MIRROR under ``ml/demo/space/`` needs no exclusion here, and gets
# none: it sits at the REPOSITORY ROOT, outside this walk root
# (``backend/jobtracker/``), so a filter naming it could never fire — and a
# filter that cannot fire is this repo's named recurring defect (see the deleted
# ``scripts/install.sh`` path filters in ``backend-ci.yml``). It is also covered
# by construction: ``ml/demo/package_space.py`` builds that tree with one
# ``copytree`` from ``backend/jobtracker``, so a copy censused here is a copy
# vendored there. ``DEMO_SPACE_AUTO_FILE_GATE_COPIES`` in
# ``scripts/readme_facts.py`` pins the mirror's ``hybrid.CONFIDENCE_AUTO`` to
# this gate's value — one entry, the gate, not this whole family.

#: The package this census walks. Anchored to THIS FILE, not to the working
#: directory, so the measurement does not depend on where pytest was invoked.
BACKEND_PACKAGE = Path(__file__).resolve().parents[1] / "jobtracker"

#: found-key → the noun it names. Set equality against the census, in BOTH
#: directions: an unregistered new copy reds it, and so does a deleted one.
GATE_SHAPED_LITERALS: dict[str, str] = {
    "classifier/embeddings.py::EmbeddingsClassifier.SIMILARITY_THRESHOLD": (
        "embedding similarity threshold — the floor below which "
        "``find_most_similar`` returns None, i.e. layer 2 declines to answer"
    ),
    "classifier/hybrid.py::CONFIDENCE_AUTO": (
        "auto-file gate — whether the cascade's own verdict is flagged "
        "``needs_review``"
    ),
    "cloud/pipeline.py::AUTO_FILE_GATE": (
        "auto-file gate — whether a message may assert a hard application status"
    ),
    "scripts/ingest_datasets.py::conf >= 0.85": (
        "training-candidate auto-label gate — offline corpus ingest, whether a "
        "rules verdict is accepted as a label or queued for review"
    ),
}


def _is_gate_literal(node: ast.AST) -> bool:
    """Is this node the bare float ``0.85``?"""

    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, float)
        and node.value == AUTO_FILE_GATE
    )


def _census_module(tree: ast.Module, rel: str) -> set[str]:
    """Gate-shaped 0.85 literals in one parsed module, as stable keys."""

    found: set[str] = set()

    # (1) Assignments in the MODULE body and in CLASS bodies. Function-local
    #     assignments are deliberately out: a local is not a copy anyone else
    #     can read, and its comparison is caught by (2) anyway.
    bodies: list[tuple[str, list[ast.stmt]]] = [("", tree.body)]
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bodies.append((f"{node.name}.", node.body))

    for prefix, body in bodies:
        for stmt in body:
            targets: tuple[ast.expr, ...] = ()
            if isinstance(stmt, ast.Assign) and _is_gate_literal(stmt.value):
                targets = tuple(stmt.targets)
            elif (
                isinstance(stmt, ast.AnnAssign)
                and stmt.value is not None
                and _is_gate_literal(stmt.value)
            ):
                targets = (stmt.target,)
            for target in targets:
                found.add(f"{rel}::{prefix}{ast.unparse(target)}")

    # (2) Comparisons ANYWHERE, including inside functions — this is where an
    #     unnamed copy hides. Keyed by the unparsed comparison rather than a
    #     line number so an edit above it does not rewrite the register.
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and any(
            _is_gate_literal(operand) for operand in (node.left, *node.comparators)
        ):
            found.add(f"{rel}::{ast.unparse(node)}")

    return found


def census_gate_shaped_literals() -> set[str]:
    """Walk ``backend/jobtracker/`` and report every gate-shaped 0.85."""

    found: set[str] = set()
    for path in sorted(BACKEND_PACKAGE.rglob("*.py")):
        rel = path.relative_to(BACKEND_PACKAGE).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found |= _census_module(tree, rel)
    return found


def test_the_census_reads_a_real_package() -> None:
    """Positive control: a walk that finds nothing must not read as agreement.

    An empty ``rglob`` — a moved package, a renamed directory, a wrong
    ``parents[]`` index — would make the census return ``set()`` and the
    register would have to be emptied to match. Then the whole check passes
    while measuring nothing, which is the defect this file is being repaired
    for. Assert the walk root exists and is non-trivial before trusting it.
    """

    assert BACKEND_PACKAGE.is_dir(), f"{BACKEND_PACKAGE} is not a directory"

    walked = {
        path.relative_to(BACKEND_PACKAGE).as_posix()
        for path in BACKEND_PACKAGE.rglob("*.py")
    }
    # Named, not counted: a bare count is a number to relax when it goes red.
    # These two are the modules the register's gate entries live in, so if the
    # walk misses either of them the census below is measuring the wrong tree.
    for required in ("classifier/hybrid.py", "cloud/pipeline.py"):
        assert required in walked, (
            f"{required} was not reached by the walk of {BACKEND_PACKAGE} — the "
            f"census is not reading the package it claims to."
        )
    assert len(walked) > 20, f"only {len(walked)} modules under {BACKEND_PACKAGE}"


def test_the_gate_shaped_literals_in_the_tree_are_all_registered() -> None:
    """The register equals what is actually written in ``backend/jobtracker/``.

    Both directions, and each names a different failure:

    * something in the tree that is NOT registered — a new copy of a threshold
      slipped in without anyone saying which quantity it is;
    * something registered that is NOT in the tree — a copy was deleted or
      renamed, and the register is now describing a file that has moved on.

    Four entries, and that is a measurement rather than a target. 0.85 occurs
    21 times textually under this package; the rest are prose, call keywords and
    literal data, all of which fall out of the two collected shapes.
    """

    found = census_gate_shaped_literals()
    registered = set(GATE_SHAPED_LITERALS)

    unregistered = found - registered
    assert not unregistered, (
        f"gate-shaped 0.85 literals in backend/jobtracker/ that are not on the "
        f"register: {sorted(unregistered)}. Add each one to "
        f"GATE_SHAPED_LITERALS *with the noun it names* — which quantity is this "
        f"0.85? If it is the auto-file gate, it also belongs in "
        f"AUTO_FILE_GATE_COPIES above and in the web-side invariant in "
        f"scripts/readme_facts.py. If it is a different quantity that merely "
        f"shares the number, say so in the noun; do not lock it to the gate."
    )

    stale = registered - found
    assert not stale, (
        f"registered copies no longer found in backend/jobtracker/: "
        f"{sorted(stale)}. A copy was deleted, renamed, or had its 0.85 changed. "
        f"Confirm which, then remove the entry deliberately — a register that "
        f"only ever shrinks silently is how the count reached 2 with nobody able "
        f"to say whether a copy went away or merely stopped being watched."
    )


@pytest.mark.parametrize("name", sorted(GATE_SHAPED_LITERALS))
def test_every_registered_literal_names_its_quantity(name: str) -> None:
    """A register entry without a noun registers nothing.

    The noun is what stops the count-noun mistake this census exists to prevent:
    ``hybrid.classify``'s 0.85 was read as a third auto-file gate when it was
    the embedding similarity floor. An entry whose noun is blank, or is the bare
    word "gate", has not answered the question.
    """

    noun = GATE_SHAPED_LITERALS[name]
    assert noun.strip(), f"{name} is registered without naming its quantity"
    assert noun.strip().lower() not in {"gate", "threshold", "0.85"}, (
        f"{name}'s noun is {noun!r} — say WHICH gate or WHICH threshold."
    )


@pytest.mark.parametrize("name", sorted(REVIEW_FLOOR_COPIES))
def test_every_review_floor_copy_is_the_canonical_floor(name: str) -> None:
    """The gate's other half, named in the same comment, held the same way.

    ``REVIEW_FLOOR``/``CONFIDENCE_MIN_CLASSIFICATION`` is what separates "held
    for a human" from "dropped entirely" (``collect_review_items``). Leaving it
    uncovered while the 0.85 above is covered would just move the unguarded
    copy rather than remove it.
    """

    assert REVIEW_FLOOR_COPIES[name] == REVIEW_FLOOR, (
        f"{name} is {REVIEW_FLOOR_COPIES[name]!r}, not the canonical review "
        f"floor {REVIEW_FLOOR!r}."
    )


def test_the_gate_sits_above_the_review_floor() -> None:
    """The band between them is the review queue, and it must be non-empty.

    If the two ever meet, ``collect_review_items``' 0.70–0.85 band closes and
    every uncertain lifecycle verdict goes straight to the terminal drop —
    silently, because the drop's warning log only fires at/above the gate.
    """

    assert REVIEW_FLOOR < AUTO_FILE_GATE
