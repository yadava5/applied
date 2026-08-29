"""Issue #451 — a reference to an application is not a report about it.

The defect
----------
``application.{0,20}(for|to).{0,40}(position|role|job)`` was ``strong`` for
``applied``, worth +3. An offer that names which application it concerns —
"We are delighted to extend you an offer to join us... This concerns your
application for the Backend Engineer position" — therefore scored ``applied``
3 and ``offer`` 3, a dead tie, resolved by ``sorted(scores.items(), ...)``
over a dict built in ``EmailCategory`` declaration order. **The winner was
decided by the order somebody typed an enum in.** The board said
"acknowledged" about an offer.

Two halves, and they fix different things
-----------------------------------------
**The demotion** moves that pattern to ``weak``. It is a REFERENCE: it says
which application the mail is about, not what happened to it, and every
category's mail carries it because that is how a courteous recruiter names
the thread they are answering. It is the third member of the family #348 and
#441 already moved.

**The tie-break** is the part the demotion does not reach. Demoting one
pattern removes one tie; it leaves the RULE that resolved it — enum order —
exactly where it was. :func:`rules.winner_first` replaces that rule with a
true one: at equal score a category that REPORTS on an application outranks
one that merely ASSERTS one exists, because the report entails the assertion
and the entailment does not run back.

Why this file exists rather than the corpus
-------------------------------------------
The corpus can see the demotion and CANNOT SEE THE TIE-BREAK, and that is
said here rather than left for someone to discover. Measured on the
17,260-case independent corpus: as shipped there were 109 positive-score
ties, every one of them a reference against a report (94 applied/offer, 15
applied/rejection), and enum order got all 109 wrong. After the demotion 15
remain — all ``applied`` against ``rejection``, all at score 1, all at
confidence 0.65. Flipping their winner cannot move their confidence, and 0.65
is under ``REVIEW_FLOOR``, so they sit in the corpus's ABSTAINED bucket
before and after and no counter moves. A change no counter can see needs a
test that can.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobtracker.classifier.rules import (
    ASSERTS_AN_APPLICATION,
    REPORTS_ON_AN_APPLICATION,
    RulesClassifier,
    winner_first,
)
from jobtracker.cloud import pipeline
from jobtracker.database.models import CATEGORY_TO_STATUS, EmailCategory

CLASSIFIER = RulesClassifier()

#: The pattern this issue demoted, verbatim.
REFERENCE_PATTERN = r"application.{0,20}(for|to).{0,40}(position|role|job)"

#: The repository root, from ``backend/tests/``.
ROOT = Path(__file__).resolve().parents[2]

#: Every copy of the rules a running engine reads. All four move together or
#: the browser port and the backend disagree about the same message.
PY_RULES = (
    "backend/jobtracker/classifier/rules.py",
    "ml/demo/space/jobtracker/classifier/rules.py",
)
JSON_RULES = (
    "apps/web/lib/demo/rules.json",
    "ml/browser/site/rules.json",
)

# The message from the issue. Invented, and safe in a public repository.
OFFER_SUBJECT = "An offer from Cedarhollow"
OFFER_BODY = (
    "Hi Ayush, We are delighted to extend you an offer to join us. The written "
    "terms are attached for your review. This concerns your application for "
    "the Backend Engineer position."
)

# One of the 15 ties the demotion leaves behind, in the corpus's
# `observed-rejection` shape: a rejection whose only two signals are a
# courtesy opener (`applied`, weak) and a volume apology (`rejection`, weak).
# Also invented; the employer and role are the corpus's, not a mailbox's.
TIED_REJECTION_SUBJECT = "Important information about your application to Thorncombecross Dynamics"
TIED_REJECTION_BODY = (
    "Hi Ayush, Thank you for your interest in Thorncombecross Dynamics and our "
    "Systems Engineer position. As you can imagine we received many qualified "
    "applicants and some aligned better than others."
)
RIPPLING = "no-reply@ats.rippling.com"


# ===========================================================================
# 1. The two sets say something true, and it is what the pipeline already says.
# ===========================================================================


def test_the_classifier_and_the_pipeline_name_the_same_assertion() -> None:
    """One fact, stated in two modules, held equal by this line.

    ``pipeline.APPLIED_SIGNAL_CATEGORIES`` has encoded "a confirmation asserts
    an application, everything else reports on one" since long before this
    issue; the classifier simply had no access to it. It is not imported —
    ``cloud.pipeline`` keeps ``jobtracker`` out of its module-level import
    graph on purpose, which is what lets it be unit-tested without the
    classifier — so the two are held together here instead of by an import.
    """
    assert ASSERTS_AN_APPLICATION == pipeline.APPLIED_SIGNAL_CATEGORIES


def test_the_report_set_is_derived_and_not_hand_written() -> None:
    """The complement of the assertion inside the category-to-status map.

    ``models.CATEGORY_TO_STATUS`` is the one place that says which categories
    say anything at all about an application; its own comment gives the reason
    ``follow_up``, ``needs_review`` and ``other`` are absent. ``rules.py``
    spells the answer out rather than importing that map, because its second
    copy at ``ml/demo/space`` ships an older ``models.py`` that has no such
    map — so this line recomputes it. Adding a category to the map without
    deciding which side of the partition it falls on goes red here.
    """
    derived = frozenset(c.value for c in CATEGORY_TO_STATUS) - ASSERTS_AN_APPLICATION
    assert derived == REPORTS_ON_AN_APPLICATION


def test_the_two_classes_partition_the_categories_that_speak_of_an_application() -> None:
    assert not (ASSERTS_AN_APPLICATION & REPORTS_ON_AN_APPLICATION)
    speaks_of_an_application = {c.value for c in EmailCategory} - {
        "follow_up",
        "needs_review",
        "other",
    }
    assert speaks_of_an_application == ASSERTS_AN_APPLICATION | REPORTS_ON_AN_APPLICATION


# ===========================================================================
# 2. The tie-break, through the function that production calls.
# ===========================================================================


@pytest.mark.parametrize("report", sorted(REPORTS_ON_AN_APPLICATION))
def test_a_report_beats_the_assertion_at_equal_score(report: str) -> None:
    """One case per member of the set, and it calls the real sort.

    A set needs a case per member. The scores are handed to
    :func:`winner_first` directly rather than reached through a message,
    because what is under test is the SORT: constructing text that ties
    ``applied`` against each of five categories would be a test of the
    PATTERNS, and would pass or fail for reasons that have nothing to do with
    this rule. Section 3 supplies the end-to-end case.
    """
    scores = {c.value: 0 for c in EmailCategory}
    scores["applied"] = 3
    scores[report] = 3

    ordered = winner_first(scores)
    assert ordered[0][0] == report, ordered[:3]
    # The margin is untouched, which is what stops this rule changing how SURE
    # the product is about a coin toss.
    assert ordered[0][1] - ordered[1][1] == 0


@pytest.mark.parametrize("winner_by_score", ["applied", "offer"])
def test_the_tie_break_never_overturns_a_score(winner_by_score: str) -> None:
    """A one-point lead decides it, in either direction. Not a tie: no rule."""
    scores = {c.value: 0 for c in EmailCategory}
    scores["applied"] = 3
    scores["offer"] = 3
    scores[winner_by_score] = 4
    assert winner_first(scores)[0][0] == winner_by_score


def test_a_tie_between_two_reports_is_left_where_it_was() -> None:
    """The hole in this rule, asserted rather than left implicit.

    Neither a rejection nor an interview entails the other, so the entailment
    that makes the tie-break true has nothing to say about the pair — and it
    deliberately does not pretend to. Such a tie still falls out of
    declaration order. The corpus contains no instance, so it is unobservable
    today; this is here so the next reader takes it as a known limit rather
    than as coverage.
    """
    scores = {c.value: 0 for c in EmailCategory}
    scores["rejection"] = 3
    scores["interview"] = 3
    ordered = winner_first(scores)
    assert {ordered[0][0], ordered[1][0]} == {"rejection", "interview"}
    assert ordered[0][1] == ordered[1][1] == 3


# ===========================================================================
# 3. The two real messages: the issue's offer, and one of the ties it leaves.
# ===========================================================================


def test_the_offer_reads_as_an_offer_at_or_above_the_review_floor() -> None:
    """The issue's acceptance criterion, on the issue's own message."""
    result = CLASSIFIER.classify(
        OFFER_SUBJECT, OFFER_BODY, "careers@cedarhollow.example"
    )

    assert result.category is EmailCategory.OFFER, result.scores
    assert result.confidence >= pipeline.REVIEW_FLOOR, result.scores
    # The reference still contributes. Demoting it was never about discarding
    # it: it IS evidence, about which application, and worth a weak match.
    assert result.scores["applied"] == 1, result.scores
    assert result.scores["offer"] == 3, result.scores


def test_a_real_tie_is_now_decided_by_the_rule_and_not_by_enum_order() -> None:
    """End to end, through ``classify``, on a shape the corpus contains 15 of.

    Both signals are weak and the scores are 1–1. Before #451 this returned
    ``applied`` — not because the message said so, but because ``APPLIED`` is
    the first member of ``EmailCategory``. It is a rejection.
    """
    result = CLASSIFIER.classify(
        TIED_REJECTION_SUBJECT, TIED_REJECTION_BODY, RIPPLING
    )

    assert result.scores["applied"] == result.scores["rejection"] == 1, result.scores
    assert result.category is EmailCategory.REJECTION, result.scores
    # And the tie is still read as a tie: a coin toss does not become a fact.
    assert result.confidence < pipeline.REVIEW_FLOOR, result.scores


def test_the_reference_alone_no_longer_earns_a_reports_worth_of_evidence() -> None:
    """+1, not +3, and that difference is the whole issue.

    A body carrying the reference and nothing else scores 1. At ``strong`` it
    scored 3 — exactly what a report of a later stage earns, which is how it
    came to tie with one.
    """
    result = CLASSIFIER.classify(
        "A note", "Regarding your application for the Backend Engineer position.", None
    )
    assert result.scores["applied"] == 1, result.scores


# ===========================================================================
# 4. All four copies of the rules moved together.
# ===========================================================================


@pytest.mark.parametrize("rel", PY_RULES)
def test_the_reference_is_weak_in_every_python_copy(rel: str) -> None:
    """Read off the definition site, not off an import.

    ``ml/demo/space/jobtracker/classifier/rules.py`` is a second copy that no
    backend test imports, so only a source-level check can see it drift.
    """
    source = (ROOT / rel).read_text(encoding="utf-8")
    quoted = f'r"{REFERENCE_PATTERN}"'
    assert quoted in source, f"{rel} no longer contains the pattern at all"
    applied = source.split("EmailCategory.APPLIED: CategoryPatterns(", 1)[1]
    strong_block, rest = applied.split("weak=[", 1)
    weak_block = rest.split("negative=[", 1)[0]
    assert quoted not in strong_block, f"{rel} still scores the reference as strong"
    assert quoted in weak_block, f"{rel} does not carry the reference as weak"


@pytest.mark.parametrize("rel", JSON_RULES)
def test_the_reference_is_weak_in_every_json_port(rel: str) -> None:
    applied = json.loads((ROOT / rel).read_text(encoding="utf-8"))["categories"][
        "applied"
    ]
    assert REFERENCE_PATTERN not in applied["strong"], rel
    assert REFERENCE_PATTERN in applied["weak"], rel


def test_the_two_json_ports_are_still_byte_identical() -> None:
    """They are copies of each other. ``readme_facts.py`` checks this too, and
    moving a pattern between two lists is precisely the edit that touches one
    file and forgets the other."""
    first, second = (( ROOT / rel).read_bytes() for rel in JSON_RULES)
    assert first == second


@pytest.mark.parametrize("rel", ("apps/web/lib/demo/rulesLayer.ts", "ml/browser/site/app.js"))
def test_both_javascript_engines_carry_the_tie_break(rel: str) -> None:
    """The port is logic, not just patterns, and it is not covered by the
    pattern-count checks in ``readme_facts.py``.

    Both files' own headers claim "same margin→confidence tiers" as the
    backend. Both sort with ``Object.entries(scores).sort(...)``, which is
    stable over `rules.json`'s key order — not even the order Python ties on.
    A source check is what is available here; ``apps/web``'s unit suite
    exercises the TypeScript one for real.
    """
    source = (ROOT / rel).read_text(encoding="utf-8")
    assert "REPORTS_ON_AN_APPLICATION" in source, f"{rel} has no report set"
    for member in sorted(REPORTS_ON_AN_APPLICATION):
        assert f'"{member}"' in source or f"'{member}'" in source, (rel, member)
    assert "REPORTS_ON_AN_APPLICATION.has(b[0])" in source, (
        f"{rel} does not break its tie on what the categories claim"
    )
