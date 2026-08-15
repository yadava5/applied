"""One auto-file gate, and every copy of it checked against that one.

``0.85`` is hand-written in two separate backend modules, and until this file
existed the only thing holding them together was a comment in
``cloud/pipeline.py`` saying they were kept in lock-step.

It was four until the desktop routers were deleted (issue #73). Two of the four
lived in ``api/classification.py`` -- ``REVIEW_QUEUE_CONFIDENCE_THRESHOLD`` and
``seed_training_data``'s ``min_confidence`` default -- and went with it. The
count below moved from 4 to 2 for that reason and no other; it is NOT a licence
to let a copy drop off the register. If a copy of this gate is added anywhere
under ``backend/``, it belongs here, and the count moves with it.

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


def test_the_two_auto_file_gate_copies_are_one_value() -> None:
    """…and there are exactly two of them, all agreeing.

    The per-copy test above would still pass if a third copy appeared and was
    never added here. This one pins the count, so adding a gate without
    registering it is a deliberate edit to this file.

    Two, not four, since the desktop routers were deleted. A count that only
    ever falls is the failure mode to watch for: if this number goes down again,
    the question to answer is whether a copy was DELETED or merely dropped off
    the register.
    """

    assert len(AUTO_FILE_GATE_COPIES) == 2
    assert set(AUTO_FILE_GATE_COPIES.values()) == {AUTO_FILE_GATE}


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
