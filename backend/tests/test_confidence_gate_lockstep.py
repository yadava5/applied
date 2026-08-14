"""One auto-file gate, and every copy of it checked against that one.

``0.85`` is hand-written in four separate backend modules, and until this file
existed the only thing holding them together was a comment::

    # Confidence gates — kept in lock-step with classifier/hybrid.py
    # (CONFIDENCE_AUTO / CONFIDENCE_MIN_CLASSIFICATION) …
    AUTO_FILE_GATE = 0.85  # cloud/pipeline.py

A comment cannot fail. These tests can, which is the whole point: the day
someone tunes one copy — the pipeline's gate, the classifier's, the review
queue's, or the training pre-seed default — the suite goes red and names the
copy that drifted, instead of the product quietly filing at one threshold and
queueing at another.

That is not a hypothetical drift. The four copies do different jobs and are
edited for different reasons:

- ``pipeline.AUTO_FILE_GATE`` decides whether a message may assert a hard
  application status (with an employer that can be named — the gate is
  necessary, not sufficient);
- ``hybrid.CONFIDENCE_AUTO`` decides whether the cascade's own verdict is
  flagged ``needs_review``;
- ``classification.REVIEW_QUEUE_CONFIDENCE_THRESHOLD`` decides what the review
  queue endpoint hands back to the user;
- ``classification.seed_training_data``'s ``min_confidence`` decides which
  already-classified mail is trusted enough to become training data.

Split them and the product tells the user one story on the dashboard, a second
in the queue, and trains on a third — the classic shape where every gate is
green and the behaviour is still wrong. Filed with #208, which removed a
Settings slider that pretended this number was per-user: it is one number, for
every account, and this file is what keeps it one number.

The fourth copy is a FUNCTION SIGNATURE DEFAULT, not a module constant, so it
is read with :mod:`inspect` rather than an attribute lookup. Asserting on the
three constants alone would look like coverage and check three of four.
"""

from __future__ import annotations

import inspect

import pytest

from jobtracker.api import classification as classification_api
from jobtracker.classifier import hybrid
from jobtracker.cloud import pipeline

# The canonical values, written out ONCE in the test suite so a change to a gate
# has to be made deliberately in every copy rather than absorbed by an
# assertion derived from one of them.
AUTO_FILE_GATE = 0.85
REVIEW_FLOOR = 0.70


def _seed_training_data_min_confidence() -> float:
    """Return ``seed_training_data``'s ``min_confidence`` default.

    ``@router.post`` returns the undecorated function, so the signature is the
    real one. If FastAPI ever stops doing that, ``default`` becomes
    ``inspect.Parameter.empty`` and the assertion below fails loudly rather
    than passing on a value nobody read.
    """

    parameter = inspect.signature(classification_api.seed_training_data).parameters[
        "min_confidence"
    ]
    return parameter.default


# name → the live value, one entry per hand-written copy in the tree.
AUTO_FILE_GATE_COPIES: dict[str, object] = {
    "cloud/pipeline.py::AUTO_FILE_GATE": pipeline.AUTO_FILE_GATE,
    "classifier/hybrid.py::CONFIDENCE_AUTO": hybrid.CONFIDENCE_AUTO,
    "api/classification.py::REVIEW_QUEUE_CONFIDENCE_THRESHOLD": (
        classification_api.REVIEW_QUEUE_CONFIDENCE_THRESHOLD
    ),
    "api/classification.py::seed_training_data(min_confidence=…)": (
        _seed_training_data_min_confidence()
    ),
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
        f"gate {AUTO_FILE_GATE!r}. These four are lock-stepped by comment in "
        f"cloud/pipeline.py:500-501 — change all of them or none."
    )


def test_the_four_auto_file_gate_copies_are_one_value() -> None:
    """…and there are exactly four of them, all agreeing.

    The per-copy test above would still pass if a fifth copy appeared and was
    never added here. This one pins the count, so adding a gate without
    registering it is a deliberate edit to this file.
    """

    assert len(AUTO_FILE_GATE_COPIES) == 4
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
