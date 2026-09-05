"""The 0.90 crossing is a ROUTING change, and nothing watched it. #775.

``hybrid.classify`` returns at ``rules_result.confidence >= 0.90`` before any
profile-dependent branch. So an item at 0.89 reaches SetFit and embeddings, and
the same item at 0.90 does not. **A pattern edit that raises a score past that
line silently removes the rest of the cascade from that item's decision**, and
the cascade gate reports it as a per-label F1 movement in the two labels
involved rather than as a layer change.

That is not hypothetical. ``c7014620`` (#119, 2026-08-12) moved
``Follow-up after completing assessment`` from 0.60 to 0.90 and its own commit
body records the numbers and says it was "left unguarded on purpose" -- one day
after ``baseline_cascade_v3.json`` was recorded. The gate went red and stayed
red, and no instrument in the repository could say which layer had changed
hands. #758 is the eight-month bill for that.

WHAT THIS RECORDS, and why it is subjects rather than a count. A count is
satisfied by ANY set of that size, so one item crossing in each direction
cancels and the ratchet reports nothing. That exact offsetting shape is why
``main`` carried this defect invisibly: its aggregates equalled the baseline's
(accuracy 0.9583, macro_f1 0.9582, 4 misclassified, all identical) because two
per-label gains offset the two regressions. A gate reading totals called it
green.

`docs/CLASSIFIER_RULES_GOVERNANCE.md`'s near-miss requirement does not cover
this: a near-miss control asks "did the verdict move", and the whole point here
is an item whose verdict does NOT move while its reachability does.

RULES-ONLY, deliberately. No checkpoint, no Docker, no ML stack -- 96
classifications and a set comparison, so this can be a cheap always-on gate
rather than something that skips when an extra is missing. A skipped security
test and a passing one produce the same green tick.
"""

from __future__ import annotations

import json
from pathlib import Path

from jobtracker.classifier.hybrid import RULES_SHORT_CIRCUIT
from jobtracker.classifier.rules import PATTERNS, EmailCategory, RulesClassifier

# IMPORTED, not typed again, and the reasoning is worth stating because the
# opposite call is usually right in this repository.
#
# The usual rule is that an expectation read from the module under test compares
# the config to itself. That rule does not apply here, because 0.90 is not the
# expectation -- THE RECORDED SET IS. This file asks "which items does the rules
# layer answer before the cascade continues", and if somebody retunes the
# boundary the answer to that question genuinely changes; the ratchet below then
# reds and names every item that crossed, which is exactly the notification a
# threshold change should produce.
#
# Typing it a second time buys nothing and costs correctness in both directions:
# at a retuned 0.65 a test asserting `< 0.90` certifies reachability that no
# longer exists, and at 0.95 a test asserting `>= 0.90` certifies rules
# ownership that has ended. The boundary is live tuning surface -- that is the
# whole premise of #775 -- so a frozen copy of it decouples precisely when it
# matters.

EVAL_SET = (
    Path(__file__).resolve().parents[1] / "data" / "evaluation" / "classifier_eval_v3.jsonl"
)


#: The subjects whose RULES-ONLY confidence reaches the short circuit, recorded
#: at the tree that fixed #758. 61 of 96 evaluation rows -- so roughly two
#: thirds of this evaluation set never reaches the learned layers at all, which
#: is worth knowing when reading any cascade accuracy figure.
RECORDED_SHORT_CIRCUIT: frozenset[str] = frozenset(
    {
        'Action required: continue your application',
        'Additional information required to continue',
        'Any updates on my application?',
        'Application acknowledgement',
        'Application complete: Security Engineer',
        'Application deadline reminder',
        'Application decision',
        'Application in review for Senior iOS Engineer',
        'Application not complete',
        'Application received - Staff Backend Engineer',
        'Assessment follow-up',
        'Before we can review your application',
        'Book your interview slot',
        'Candidate outcome',
        'Candidate portal update: application submitted',
        'Checking in after interview',
        'Checking in on interview feedback',
        'CodeSignal evaluation invite',
        'Codility test link',
        'Coding assessment invitation',
        'Compensation package details',
        'Complete challenge before interview',
        'Complete your application for Data Engineer',
        'Congratulations! Offer for Senior Backend Engineer',
        'Continue where you left off',
        'Decision on candidacy',
        'Employment agreement and offer',
        'Following up on my application status',
        'Formal offer for Product Engineer',
        'HackerRank challenge for Backend Engineer',
        'Interview invitation for Backend Engineer',
        'Interview scheduling request',
        'Invitation to speak with hiring manager',
        'Next step: technical interview',
        'Not moving forward',
        'Offer expires soon',
        'Offer letter attached',
        'Offer of employment',
        'Online assessment reminder',
        'Panel interview confirmation',
        'Please accept this offer',
        'Please share phone screen availability',
        'Position has been filled',
        'Recruiter chat request',
        'Reminder: submit your application',
        'Role closed',
        'Schedule your introductory interview',
        'Skills assessment pending',
        'Status of my application',
        'Take-home assignment',
        'Technical exercise instructions',
        'Thank you for interviewing with us',
        'Thanks for applying to Platform Engineer',
        'Thanks for your interest in Data Engineer',
        'Update on your application',
        'Wanted to follow up on my candidacy',
        'We got your application (preferences link included)',
        'We regret to inform you',
        'Welcome aboard',
        'Your application was sent to Orbit Labs',
        'Zoom interview details',
    }
)


def _rows() -> list[dict]:
    return [json.loads(line) for line in EVAL_SET.read_text(encoding="utf-8").splitlines() if line.strip()]


def _short_circuiting() -> set[str]:
    """Subjects the rules layer answers confidently enough to end the cascade."""

    classifier = RulesClassifier()
    return {
        row["subject"]
        for row in _rows()
        if classifier.classify(
            row["subject"], row["body_text"], row.get("sender_email")
        ).confidence
        >= RULES_SHORT_CIRCUIT
    }


def test_no_evaluation_item_has_crossed_the_short_circuit() -> None:
    """The ratchet. Names the items, and says which direction each moved."""

    live = _short_circuiting()
    entered = sorted(live - RECORDED_SHORT_CIRCUIT)
    left = sorted(RECORDED_SHORT_CIRCUIT - live)
    assert not entered and not left, (
        "the rules layer's reach over the evaluation set has moved.\n"
        f"  no longer reaches the learned layers ({len(entered)}): {entered}\n"
        f"  now reaches them again ({len(left)}): {left}\n"
        "Either is a routing change. A verdict need not have moved for this to "
        "matter: an item above the line cannot be corrected by SetFit or "
        "embeddings at all. If the change is intended, re-record this set in "
        "the same commit and say which items moved and why."
    )


def test_the_recorded_set_only_names_rows_the_evaluation_set_still_has() -> None:
    """A record naming a deleted row would shrink coverage silently.

    Without this, deleting an evaluation row that sits above the line reds the
    ratchet as "now reaches them again", which reads as a classifier change and
    is not one.
    """

    subjects = {row["subject"] for row in _rows()}
    orphans = sorted(RECORDED_SHORT_CIRCUIT - subjects)
    assert not orphans, f"recorded subjects no longer in the evaluation set: {orphans}"


def test_the_ratchet_reds_when_a_pattern_edit_moves_an_item_across_the_line() -> None:
    """SHOWN TO FAIL, against the edit that actually caused this.

    Restores the redundant ``exercise`` branch that #758 removed -- the branch
    whose presence made one 18-character phrase match three ASSESSMENT patterns
    for a score of 9, which is exactly 0.90. That is #119's routing change,
    reproduced.

    Mutates ``PATTERNS`` itself rather than a copy: the accessor hands back a
    list, and mutating the copy would leave the engine untouched and this test
    passing for the wrong reason.
    """

    strong = PATTERNS[EmailCategory.ASSESSMENT].strong
    narrowed = "take.?home (assignment|project|task|round)"
    assert narrowed in strong, (
        "the pattern this control mutates is gone, so the control no longer "
        "reproduces #119 and this test proves nothing. Re-point it."
    )
    saved = list(strong)
    try:
        strong[strong.index(narrowed)] = "take.?home (assignment|project|exercise|task|round)"
        moved = _short_circuiting() - RECORDED_SHORT_CIRCUIT
    finally:
        strong[:] = saved

    assert moved == {"Follow-up after completing assessment"}, (
        "re-adding the redundant branch should push exactly the #758 item over "
        f"the short circuit; got {sorted(moved)}"
    )
    assert _short_circuiting() == RECORDED_SHORT_CIRCUIT, "the mutation was not restored"
