"""``FOLLOW_UP.veto`` repeats ``REJECTION.strong``, and nothing checked it (#876).

The block at ``classifier/rules.py`` carrying ``EmailCategory.FOLLOW_UP``'s veto
opens by saying it is ``REJECTION.strong`` "repeated verbatim … Change one,
change the other". That instruction was written down and not followed:
``REJECTION.strong`` reached 33 entries while the copy stayed at the 25 it was
taken with, and the 8 that never arrived were contiguous at the tail — appended
to one list, forgotten in the other.

WHY IT MATTERED, and it is worse than a misfiling. A strong ``follow_up``
subject match ("Following up on your application …") scores +6. The veto exists
because a rejection body only TIES that, and a tie is settled by enum order at
0.60. With the veto entry missing there is nothing to overturn the subject, so
the message files as ``follow_up`` at 0.90 — and ``follow_up`` reaches neither
``pipeline._qualifies_for_hard_row`` nor ``pipeline.collect_review_items``.

Off an ATS domain it is not even appended to ``dropped_out``, so it is absent
from the "N discarded" figure a sync reports. One log line, and the rejection is
gone. That is the same disappearance the header comment on ``rules.py`` records
for the real 2026-08 rejection that forced this veto into existence in the first
place; the drift reproduced the defect the block was built to prevent.

WHY NOTHING CAUGHT IT. No test compared the two lists. The one test written for
this block — ``test_rules_classifier_rejection.py::
test_a_rejection_body_beats_a_genuine_follow_up_subject`` — passes a body whose
wording is among the 25 that WERE copied, so it goes red only if the veto tier
is deleted wholesale and can never go red for an entry that drifts. One wording
per shape grades nothing.

WHY THE COPY IS NOT REPLACED BY A SHARED CONSTANT. The note above ``PATTERNS``
refuses that with a measurement: ``scripts/readme_facts.py`` parses the file
statically for the pattern counts three surfaces publish, and a shared constant
"silently under-counted this file by 12 and turned a checked claim into a wrong
one". So the duplication stays and this file makes "keep them in step by hand"
a checked property instead of a comment.

DIRECTION MATTERS. The assertion is one-way: every ``REJECTION.strong`` entry
must appear in ``FOLLOW_UP.veto``. The five ``INTERVIEW.strong`` scheduling
frames in the same list are a deliberate curated subset (5 of 27) — a message
that ARRANGES something is not a nudge either — and a symmetric rule would drag
the other 22 in and veto ``follow_up`` on any mail mentioning an interview.
:func:`test_the_interview_frames_are_a_subset_and_not_a_copy` pins that
asymmetry so a later reader does not "fix" it.

THE CORPUS CANNOT SEE ANY OF THIS. Both corpora were re-scored across the change
and every family held exactly (304 wrong before, 304 after, no family moved):
neither has a family that puts a tail-entry rejection under a follow-up subject.
The behavioural tests below are the only instrument that reds on it.
"""
from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jobtracker.classifier.rules import PATTERNS, EmailCategory, RulesClassifier
from jobtracker.cloud import pipeline

CLASSIFIER = RulesClassifier()

#: The repository root, from ``backend/tests/``.
ROOT = Path(__file__).resolve().parents[2]

#: Every copy of the rules a running engine reads.
PY_RULES = (
    "backend/jobtracker/classifier/rules.py",
    "ml/demo/space/jobtracker/classifier/rules.py",
)
JSON_RULES = (
    "apps/web/lib/demo/rules.json",
    "ml/browser/site/rules.json",
)

#: A genuine strong ``follow_up`` subject — the shape the veto exists to
#: overturn. Invented; the real one is a person's job search (#593).
FOLLOW_UP_SUBJECT = "Following up on your application - Cedarhollow"

#: NOT an ATS domain. That is the whole point: ``collect_review_items``
#: re-admits a relayed ``follow_up`` at any confidence (#458), so on an ATS
#: sender the drift merely misfiles. Off one, it deletes.
OWN_DOMAIN = "recruiting@cedarhollow.example"

#: One invented body per drifted entry, each written to match ONLY that
#: pattern's vocabulary. These are ordinary ATS closing boilerplate.
DRIFTED_WORDINGS = {
    "(role|position).{0,20}(closed|filled)": (
        "Hi there, the position has been closed and we are no longer "
        "considering applicants."
    ),
    "decision on (your |my )?candidacy": (
        "Hi there, we have reached a decision on your candidacy for this role."
    ),
    "after careful (consideration|review).{0,30}(not|decided|unfortunately)": (
        "Hi there, after careful consideration we have decided not to continue "
        "with your application at this stage."
    ),
    "wish you (all |only |nothing but )?(the (very )?best|well|success|luck) in your": (
        "Hi there, we wish you all the best in your job search and thank you "
        "for your time."
    ),
    "encourage you to apply (for )?future.{0,20}(position|role|opening)": (
        "Hi there, we encourage you to apply for future positions with us."
    ),
    "keep your (resume|application) on file": (
        "Hi there, we will keep your resume on file for future openings."
    ),
    "not a (good )?fit.{0,20}(at this time|for this role)": (
        "Hi there, you are not a good fit for this role at this time."
    ),
    # THE EIGHTH, and its body is shaped deliberately rather than written like
    # the seven above. `unfortunately` is ALSO a FOLLOW_UP.negative at -5
    # (`rules.py:919`), so on an ordinary body follow_up scores 6-5=1 and
    # already loses to rejection's 3 -- this entry's veto changes nothing and a
    # plain fixture would pass with the entry removed, grading the letter of
    # the list and not the loss.
    #
    # It is load-bearing only where follow_up reaches >= 9, which needs a strong
    # follow_up match in the BODY as well as the subject. Measured on this body:
    # veto absent -> follow_up 0.90 (dropped); veto present -> rejection 0.70.
    "unfortunately.{0,50}(not|won't|will not|unable)": (
        "We wanted to check in on your application. Unfortunately we will "
        "not have an update until Friday."
    ),
}


def _patterns_from_source(rel: str) -> dict[str, dict[str, list[str]]]:
    """Read the ``PATTERNS`` dict out of a rules.py without importing it.

    ``ml/demo/space/jobtracker/classifier/rules.py`` is a second copy that no
    backend test imports, so only a source-level read can see it drift. AST
    rather than string splitting: the lists carry commented-out entries and
    section markers, and a split on ``veto=[`` would happily read a comment.
    """
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"), filename=rel)
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign):
            continue
        if not (isinstance(node.target, ast.Name) and node.target.id == "PATTERNS"):
            continue
        assert isinstance(node.value, ast.Dict), rel
        out: dict[str, dict[str, list[str]]] = {}
        for key, value in zip(node.value.keys, node.value.values, strict=True):
            assert isinstance(key, ast.Attribute), rel
            assert isinstance(value, ast.Call), rel
            tiers: dict[str, list[str]] = {}
            for kw in value.keywords:
                if kw.arg is None or not isinstance(kw.value, ast.List):
                    continue
                tiers[kw.arg] = [
                    e.value
                    for e in kw.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                ]
            out[key.attr] = tiers
        return out
    raise AssertionError(f"{rel} has no PATTERNS annotated assignment")


# ===========================================================================
# 1. The invariant, on every surface that carries these as literals.
# ===========================================================================


def test_the_veto_carries_every_rejection_pattern_at_runtime() -> None:
    """The engine the hosted product actually runs."""
    strong = set(PATTERNS[EmailCategory.REJECTION].strong)
    veto = set(PATTERNS[EmailCategory.FOLLOW_UP].veto)
    missing = sorted(strong - veto)
    assert not missing, (
        f"{len(missing)} REJECTION.strong pattern(s) are not in FOLLOW_UP.veto. "
        "A rejection using one of them under a follow-up subject files as "
        "follow_up and, off an ATS domain, is discarded with no row, no queue "
        f"entry and no discard count: {missing}"
    )


@pytest.mark.parametrize("rel", PY_RULES)
def test_the_veto_carries_every_rejection_pattern_in_every_python_copy(rel: str) -> None:
    pats = _patterns_from_source(rel)
    strong = set(pats["REJECTION"]["strong"])
    veto = set(pats["FOLLOW_UP"]["veto"])
    assert strong, f"{rel} parsed no REJECTION.strong at all"
    assert veto, f"{rel} parsed no FOLLOW_UP.veto at all"
    assert not (strong - veto), (rel, sorted(strong - veto))


@pytest.mark.parametrize("rel", JSON_RULES)
def test_the_veto_carries_every_rejection_pattern_in_every_json_port(rel: str) -> None:
    cats = json.loads((ROOT / rel).read_text(encoding="utf-8"))["categories"]
    strong = set(cats["rejection"]["strong"])
    veto = set(cats["follow_up"]["veto"])
    assert strong and veto, rel
    assert not (strong - veto), (rel, sorted(strong - veto))


def test_every_surface_agrees_on_the_two_lists() -> None:
    """Four copies, one vocabulary.

    The superset checks above pass independently on a file that has drifted in
    BOTH lists at once. This one pins the copies to each other, so a pattern
    added to the backend and forgotten in the browser port is caught by the
    same run.
    """
    runtime = (
        sorted(PATTERNS[EmailCategory.REJECTION].strong),
        sorted(PATTERNS[EmailCategory.FOLLOW_UP].veto),
    )
    for rel in PY_RULES:
        pats = _patterns_from_source(rel)
        assert (sorted(pats["REJECTION"]["strong"]), sorted(pats["FOLLOW_UP"]["veto"])) == runtime, rel
    for rel in JSON_RULES:
        cats = json.loads((ROOT / rel).read_text(encoding="utf-8"))["categories"]
        assert (sorted(cats["rejection"]["strong"]), sorted(cats["follow_up"]["veto"])) == runtime, rel


#: The five INTERVIEW.strong scheduling frames the veto legitimately carries,
#: written out as LITERALS on purpose. Deriving them from
#: ``PATTERNS[INTERVIEW].strong`` would compare the list to itself and pass for
#: any set the code happens to hold — the imported-expectation trap. Typed from
#: the veto list by hand, so adding a sixth frame is a decision someone makes
#: here rather than a diff nothing reads.
EXPECTED_FRAMES = frozenset(
    {
        r"invite you (to|for).{0,20}interview",
        r"\b(book|pick|choose|select|schedule|reserve|grab)\s+(a|your|another)\s+(time|slot)\b",
        r"\b(share|send|provide|confirm|know)\s+your\s+availability\b",
        r"\b(would|are) you (be )?available (on|for|at|any|next|this|to)\b",
        r"(would |'d |)like to (schedule|set up|arrange|book).{0,25}(call|meeting|interview|chat|conversation)",
    }
)


def test_the_veto_is_exactly_the_rejections_plus_the_named_frames() -> None:
    """The partition, closed on BOTH sides.

    The superset tests above are open upward: an entry added to
    ``FOLLOW_UP.veto`` that is in neither source list satisfies every one of
    them, and satisfies ``test_every_surface_agrees_on_the_two_lists`` too as
    soon as it is added to all four surfaces. An unaudited veto entry silences
    ``follow_up`` with nothing to red on it — the same product harm this file
    exists to prevent, arriving from the other direction.

    So the assertion is equality against a hand-written frame set, and the
    mutation ledger carries an arm that adds a bogus entry to all four surfaces
    to prove this row is the one that catches it.
    """
    veto = set(PATTERNS[EmailCategory.FOLLOW_UP].veto)
    strong = set(PATTERNS[EmailCategory.REJECTION].strong)
    unaccounted = veto - strong - EXPECTED_FRAMES
    assert not unaccounted, (
        f"{len(unaccounted)} veto pattern(s) are neither a REJECTION.strong "
        f"entry nor one of the named scheduling frames: {sorted(unaccounted)}. "
        "A veto silences follow_up outright; every entry must be accounted for."
    )
    missing_frames = EXPECTED_FRAMES - veto
    assert not missing_frames, (
        f"named scheduling frames have left the veto: {sorted(missing_frames)}"
    )
    assert veto == strong | EXPECTED_FRAMES


def test_the_interview_frames_are_a_subset_and_not_a_copy() -> None:
    """The asymmetry, pinned so nobody "completes" it.

    Five INTERVIEW.strong scheduling frames sit in the same veto list because a
    message that ARRANGES something is not a nudge. They are chosen — only the
    ones that state an arrangement rather than describe one — and the other 22
    must stay out: ``interview.{0,40}(is|has been) (confirmed|scheduled)`` in a
    veto would silence a genuine follow-up that mentions a booked interview.
    """
    strong = set(PATTERNS[EmailCategory.INTERVIEW].strong)
    veto = set(PATTERNS[EmailCategory.FOLLOW_UP].veto)
    shared = strong & veto
    assert shared, "the scheduling frames have vanished from the veto entirely"
    assert strong - veto, (
        "every INTERVIEW.strong pattern is now a follow_up veto. That is the "
        "symmetric rule this test exists to refuse."
    )
    assert len(shared) < len(strong) / 2, (
        f"{len(shared)} of {len(strong)} interview patterns veto follow_up; "
        "this was a curated 5 and is meant to stay small"
    )


# ===========================================================================
# 2. What the drift cost, asserted on behaviour rather than on list membership.
# ===========================================================================


@pytest.mark.parametrize("pattern,body", sorted(DRIFTED_WORDINGS.items()))
def test_a_drifted_rejection_wording_reaches_a_person(pattern: str, body: str) -> None:
    """The end-to-end claim: this message must not disappear.

    Deliberately NOT "it classifies as rejection". What the user loses when the
    veto is missing is the message itself, so the assertion is made where the
    loss happens — through the real ``_qualifies_for_hard_row`` and
    ``collect_review_items``, on a non-ATS sender so #458's relay carve-out
    cannot answer for the fix.

    Removing any one of these patterns from ``FOLLOW_UP.veto`` turns its row
    here red; that is the mutation this file was built against.
    """
    result = CLASSIFIER.classify(FOLLOW_UP_SUBJECT, body, OWN_DOMAIN)
    assert result.category is EmailCategory.REJECTION, (
        f"{pattern} scored {result.category.value}; {result.scores}"
    )

    item = pipeline.PipelineItem(
        message_id="m",
        category=result.category.value,
        sender_email=OWN_DOMAIN,
        subject=FOLLOW_UP_SUBJECT,
        sender_name="Cedarhollow Recruiting",
        received_at=datetime(2026, 9, 1, tzinfo=UTC),
        confidence=result.confidence,
        thread_id="t",
        snippet=body[:120],
        identity_role=None,
        identity_req_id=None,
        method="rules",
    )
    dropped: list[pipeline.DroppedVerdict] = []
    filed = pipeline._qualifies_for_hard_row(item)
    queued = pipeline.collect_review_items([item], dropped_out=dropped)
    assert filed or queued, (
        f"{pattern} at {result.confidence} produced no row and no queue entry, "
        f"and dropped_out holds {len(dropped)} — the message is gone"
    )


def test_the_control_wording_was_never_lost() -> None:
    """A pattern that WAS copied, so this row passes before and after the fix.

    Without it the parametrised test above proves only that something changed,
    not that the change was the missing eight. This is the near-miss on the
    other side: same subject, same sender, a rejection that always worked.
    """
    result = CLASSIFIER.classify(
        FOLLOW_UP_SUBJECT,
        "Hi there, we regret to inform you that we are not moving forward.",
        OWN_DOMAIN,
    )
    assert result.category is EmailCategory.REJECTION
    assert result.confidence >= 0.85, result.scores


@pytest.mark.parametrize(
    "body",
    [
        "Hi, just checking in on my application - has the position been filled?",
        "Hi, has the role been filled? I applied three weeks ago.",
    ],
)
def test_what_this_change_costs_is_written_down(body: str) -> None:
    """The boundary case that MOVED, pinned so it is a decision and not a surprise.

    `(role|position).{0,20}(closed|filled)` is position-blind and cannot see an
    interrogative, so the reader's OWN chase — "has the position been filled?",
    which is the literal meaning of `follow_up` — now matches a rejection
    pattern that the veto lets win.

    MEASURED both ways, against the pristine list at HEAD and the mirrored one:

        pre-fix   follow_up 0.90  ->  no row, no queue entry, DROPPED
        post-fix  rejection 0.70  ->  review queue

    Accepted, for three reasons, and the third is the one that decides it:

    1. It is bounded to the queue. 0.70 is `REVIEW_FLOOR` exactly and
       `_qualifies_for_hard_row` refuses anything under `AUTO_FILE_GATE`, so a
       false veto can produce a wrong SUGGESTION and never a rejected card.
       This test asserts that bound rather than assuming it.
    2. Silently dropped is not better than queued. Pre-fix this mail vanished;
       post-fix a person sees it and dismisses it.
    3. The alternative is the defect. Narrowing the pattern here would break
       "this IS REJECTION.strong, repeated in full", which is the invariant
       whose absence loses real rejections off non-ATS senders.

    NOT every wording of the chase moves: "I saw the posting was closed" stays
    `follow_up` 0.90, because the pattern wants `role` or `position` and
    "posting" is neither. The blast radius is narrower than the pattern reads.
    """
    result = CLASSIFIER.classify("Following up on my application", body, "user@example.com")
    assert result.category is EmailCategory.REJECTION, result.scores
    assert result.confidence < 0.85, (
        f"{result.confidence} is at or above the auto-file gate: the reader's own "
        "chase would now FILE a rejected card, which is not an accepted cost"
    )
    assert result.confidence >= 0.70, "and it must still reach a person"


@pytest.mark.parametrize(
    "subject,body",
    [
        (
            "Re: your application",
            "The role hasn't been filled yet - we're still reviewing candidates.",
        ),
    ],
)
def test_the_negation_case_is_not_a_cost_of_this_change(subject: str, body: str) -> None:
    """A near-miss that looked like a cost and measured as pre-existing.

    A reassurance that the role is still open matches `(role|position)…filled`
    straight through the negation, so it scores `rejection`. That is real, and
    it is `closing-keyword-ignores-negation` again — but it is NOT this change's
    doing: measured against the pristine list at HEAD it already read
    `rejection` 0.60, because the subject here is not a strong `follow_up`
    match and there was never a `follow_up` verdict for the veto to overturn.

    Pinned at the value it had BEFORE the mirror so the two cannot be confused
    later. 0.60 is under `REVIEW_FLOOR`, so this mail is dropped either way —
    which is a defect, and belongs to whoever fixes negation, not here.
    """
    result = CLASSIFIER.classify(subject, body, "recruiting@cedarhollow.example")
    assert result.category is EmailCategory.REJECTION, result.scores
    assert result.confidence == pytest.approx(0.60), (
        f"{result.confidence} moved; pre-fix this measured 0.60 and this change "
        "was not supposed to touch it"
    )


@pytest.mark.parametrize(
    "subject,body",
    [
        (
            "Following up on my application",
            "Hi, I wanted to check in on the status of my application for the "
            "Backend Engineer role. Thank you!",
        ),
        (
            "Following up on my application - Cedarhollow",
            "Just circling back on my application from two weeks ago. Please "
            "let me know if you need anything further.",
        ),
    ],
)
def test_a_genuine_follow_up_still_reads_as_one(subject: str, body: str) -> None:
    """The near-miss the governance doc requires, and the risk this change runs.

    Widening a veto can only ever REMOVE ``follow_up`` verdicts. The mail that
    must survive is the reader's own chasing mail, which is what the category
    means. Measured at 0.95 and 0.90 across the change — unmoved.
    """
    result = CLASSIFIER.classify(subject, body, "ayush@example.com")
    assert result.category is EmailCategory.FOLLOW_UP, result.scores
    assert result.confidence >= 0.85, result.scores
