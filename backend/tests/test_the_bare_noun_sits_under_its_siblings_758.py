"""#758 — the bare-noun ``take-home`` pattern must sit UNDER its two siblings.

WHAT WENT WRONG. ``c7014620`` (#119) added ``\\btake-home\\b(?!...)`` to fire the
assessment category on the noun alone, which was a real gap: a production
subject carrying only the bare noun scored zero. But the pattern as written is
strictly BROADER than ``take.?home (assignment|project|exercise|task|round)``,
which was already in the same list. On every message the sibling already
matched, the new pattern matched too and the category collected +3 for a phrase
it had already scored.

The measurable consequence was in the cascade, not in the benchmark. For
``Follow-up after completing assessment`` — a candidate's follow-up whose body
is "I submitted the take-home exercise and wanted to check on timeline." — the
one 18-character phrase "take-home exercise" matched THREE assessment patterns
for a score of 9, which is ``confidence`` 0.90, which is
``hybrid.classify``'s earliest return. SetFit never saw the message, and SetFit
answers it ``follow_up`` at 0.9951. #119's own commit body records the score
going 6 -> 9 and the confidence 0.60 -> 0.90 and says it was "left unguarded on
purpose".

WHAT THIS FILE PINS, and why it is a file rather than three asserts appended to
``test_rules_classifier_assessment.py``: the fix is a lookahead that NAMES the
nouns its siblings claim, and a hand-maintained copy of a vocabulary rots. The
first test derives that list from the sibling patterns at runtime, so adding a
noun to a sibling without adding it to the lookahead goes red here instead of
quietly reintroducing the double count.

``docs/CLASSIFIER_RULES_GOVERNANCE.md`` is the standard these tests are written
against: narrower never broader, derive rather than copy, name a near-miss that
must NOT move, and measure the body against a ``None`` sender so no ATS bonus
sits under the number.
"""

from __future__ import annotations

import re

import pytest

from jobtracker.classifier.hybrid import RULES_SHORT_CIRCUIT
from jobtracker.classifier.rules import PATTERNS, RulesClassifier
from jobtracker.cloud.pipeline import AUTO_FILE_GATE
from jobtracker.database.models import EmailCategory

#: ``hybrid.classify`` returns from the rules layer at this confidence, before
#: embeddings or SetFit are consulted. Read from the caller's own threshold
#: rather than typed here as 0.90, because a number typed twice is a number
#: that can disagree with itself.
#:
#: IT USED TO SAY THAT AND TYPE 0.90 ANYWAY, because `hybrid` had no name to
#: import -- the boundary was an inline literal at its one call site. Naming it
#: there is what let this line become what its comment always claimed (#775).
#: The consequence of the duplicate was not cosmetic: tuning hybrid's literal
#: down to 0.65 would have put the target back on the short circuit while
#: ``0.70 < 0.90`` went on passing.

#: The one message this issue is about. Committed in
#: ``data/evaluation/classifier_eval_v3.jsonl`` with ``confusion_pair``
#: ``follow_up_vs_assessment``, so the collision is deliberate rather than an
#: accident of fixture writing.
TARGET_SUBJECT = "Follow-up after completing assessment"
TARGET_BODY = "I submitted the take-home exercise and wanted to check on timeline."

#: The near-miss that must NOT move: the same phrase, in the employer's voice,
#: gold-labelled ``assessment`` in the same committed evaluation set.
NEAR_MISS_SUBJECT = "Take-home assignment"
NEAR_MISS_BODY = "This take-home exercise is part of our hiring process."

#: THE PAST TENSE, and the only thing the word boundary in ``\bcomplete\b``
#: exists for. Unanchored, ``complete`` matches inside "completed", so this
#: sentence fires the twin AND its partner: two strong body hits, 6 points,
#: margin >= 3, confidence 0.90 -- the cascade short-circuits and the
#: candidate's own report is read as the employer's imperative, which is this
#: issue with the roles swapped.
#:
#: NOTHING ELSE CAN NOTICE THE ANCHOR GOING AWAY. The independent corpus's
#: take-home family is entirely invite-shaped (758 cases, all imperative), so a
#: replay cannot see it; the cascade gate cannot see it; reach cannot see it,
#: because the pattern still fires either way. This test is the whole guard.
REPORT_BODY = "I completed the take-home exercise last night. Any update on next steps?"

#: The wording the independent corpus carries 300 times, employer-voiced. It is
#: the reason the fix needs the ``\bcomplete\b.{0,30}`` twin: without it this mail
#: scores 3, falls to 0.70, and the board replay puts every one of the 300 in
#: SUPPRESSED-AS-SETTLED rather than in the review queue.
CORPUS_UPDATE_SUBJECT = "Next step in your application"
CORPUS_UPDATE_BODY = (
    "Please complete the take-home exercise linked below within five days to move to the next step."
)


@pytest.fixture(scope="module")
def strong() -> list[str]:
    return list(PATTERNS[EmailCategory.ASSESSMENT].strong)


@pytest.fixture(scope="module")
def classifier() -> RulesClassifier:
    return RulesClassifier()


def _one(strong: list[str], needle: str, *, exclude: str = "\x00") -> str:
    """The single assessment pattern containing ``needle``. Exactly one, or fail."""
    hits = [p for p in strong if needle in p and exclude not in p]
    assert len(hits) == 1, f"expected exactly one pattern containing {needle!r}, got {hits}"
    return hits[0]


def _alternation_after(pattern: str, anchor: str) -> set[str]:
    """The `(a|b|c)` group that follows ``anchor`` in ``pattern``, as a set."""
    tail = pattern.split(anchor, 1)[1]
    group = re.match(r"\(([^)]*)\)", tail)
    assert group, f"no alternation follows {anchor!r} in {pattern!r}"
    return set(group.group(1).split("|"))


# ─────────────────────────────────────────────────────────────────────────────
# 1. The derivation invariant — this is the test that stops the copy rotting
# ─────────────────────────────────────────────────────────────────────────────


def test_the_bare_noun_excludes_every_noun_its_siblings_claim(strong: list[str]) -> None:
    """Derived from the siblings, not typed out a second time.

    The lookahead in the bare-noun pattern is a hand-maintained copy of two
    alternations that live elsewhere in the same list. This test is what makes
    the copy safe: it reads the alternations off the siblings and requires the
    lookahead to contain all of them. Add ``round`` to the qualified pattern
    without adding it to the lookahead and this goes red, instead of silently
    restoring the +3 that #758 removed.
    """
    qualified = _one(strong, "take.?home (")
    general = _one(strong, "(technical|coding|take.?home)", exclude=r"\bcomplete\b")
    bare = _one(strong, r"\btake-home\b")

    claimed = _alternation_after(qualified, "take.?home ") | _alternation_after(
        general, "(technical|coding|take.?home).{0,20}"
    )
    excluded = _alternation_after(bare, r"\btake-home\b(?!\s+")

    assert claimed, "the sibling alternations parsed empty — this test measured nothing"
    missing = claimed - excluded
    assert not missing, (
        f"the bare-noun pattern does not exclude {sorted(missing)}, so a message "
        f"saying 'take-home <noun>' would be scored twice for one phrase — the "
        f"#758 defect. Add them to the lookahead in {bare!r}."
    )


def test_the_derivation_invariant_can_actually_fail(strong: list[str]) -> None:
    """The negative control, and it is the pattern as #119 actually shipped it.

    A check that cannot go red is not a check. Rebuilding the pre-#758 lookahead
    — the five senses of 'take-home' that are not a test at all, and nothing
    else — must fail the assertion the test above passes.
    """
    qualified = _one(strong, "take.?home (")
    general = _one(strong, "(technical|coding|take.?home)", exclude=r"\bcomplete\b")
    claimed = _alternation_after(qualified, "take.?home ") | _alternation_after(
        general, "(technical|coding|take.?home).{0,20}"
    )

    as_119_shipped = r"\btake-home\b(?!\s+(pay|message|gift|dose|salary))"
    excluded = _alternation_after(as_119_shipped, r"\btake-home\b(?!\s+")

    assert claimed - excluded == {
        "assignment",
        "project",
        "task",
        "round",
        "assessment",
        "challenge",
        "test",
        "exercise",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. Narrower, never broader — proved by execution, not by reading
# ─────────────────────────────────────────────────────────────────────────────


#: The leading alternation the general assessment pattern opens with. Named
#: once, because the derivation below and its tamper arm both need it.
_HEAD = "(technical|coding|take.?home)"

#: The one branch of that alternation the imperative twin keeps.
_BRANCH = "take.?home"


def _derive(general: str) -> str:
    """The twin, derived from the general pattern by two mechanical steps.

    SELECT one branch of the leading alternation, then PREFIX the imperative.
    Both steps preserve containment: a branch's language is a subset of its
    alternation's, and a prefixed pattern fires only where its suffix fires
    under ``search``. So the twin cannot match text the general form does not,
    and that is a proof rather than an observation.
    """

    assert general.startswith(_HEAD), (
        f"the general pattern no longer opens with {_HEAD!r}, so the derivation "
        f"below is about a shape that is gone: {general!r}"
    )
    branches = _HEAD[1:-1].split("|")
    assert _BRANCH in branches, (
        f"{_BRANCH!r} is not one of the alternation's branches {branches}, so "
        "selecting it is not a narrowing"
    )
    return r"\bcomplete\b.{0,30}" + _BRANCH + general.removeprefix(_HEAD)


def test_the_imperative_twin_is_derived_from_its_partner(strong: list[str]) -> None:
    """The twin is one branch of the general form, under the imperative.

    It USED to be the whole general pattern with a prefix, which made the
    derivation a single concatenation. It is not any more, and the reason is
    the point of #758: the general form's `technical` and `coding` branches are
    already claimed by ``complete.{0,30}(assessment|challenge|test)``, so a twin
    carrying them scored one phrase a THIRD time. Narrowing to the one branch
    that has no imperative sibling removes that without touching reach —
    measured across the independent corpus as 26 (expected, predicted,
    confidence) cells, none of which moved.

    The literal stays a single string in ``rules.py`` because three static
    consumers read PATTERNS as literals; the derivation is performed here, on
    the two live patterns, so drift on either side reds.
    """

    general = _one(strong, _HEAD, exclude=r"\bcomplete\b")
    twin = _one(strong, r"\bcomplete\b")
    assert twin == _derive(general)


def test_the_derivation_reds_when_its_partner_moves(strong: list[str]) -> None:
    """SHOWN TO FAIL: tamper with the general form and the derivation complains.

    Without this, the equality above is a check nobody has watched break — and
    a derivation that cannot red is decoration, whatever it proves on paper.
    """

    general = _one(strong, _HEAD, exclude=r"\bcomplete\b")
    twin = _one(strong, r"\bcomplete\b")

    tampered = general.replace("|exercise)", "|exercise|drill)")
    assert tampered != general, "the tamper changed nothing, so it tests nothing"
    assert twin != _derive(tampered), (
        "adding a noun to the general form left the derived twin unchanged, so "
        "the equality above cannot notice its partner drifting"
    )

    headless = general.replace(_HEAD, "(coding|take.?home)", 1)
    try:
        _derive(headless)
    except AssertionError:
        pass
    else:
        raise AssertionError("removing a branch from the alternation did not red the derivation")


def test_the_twin_witnesses_both_directions_of_the_containment(
    strong: list[str],
) -> None:
    """Two witnesses, each with a stated meaning, subordinate to the proof above.

    They observe the theorem rather than standing in for it: one shows the twin
    firing inside its partner, the other shows the imperative anchor still
    gating. Twenty probes instead of a derivation would be decoration; two
    attached to one are a sanity check.
    """

    general = _one(strong, _HEAD, exclude=r"\bcomplete\b")
    twin = _one(strong, r"\bcomplete\b")
    partner, narrower = re.compile(general, re.I), re.compile(twin, re.I)

    invite = "Please complete the take-home exercise by Friday."
    assert narrower.search(invite), "the twin fired on nothing — this measured nothing"
    assert partner.search(invite), "the twin matched where its partner does not"

    assert partner.search(TARGET_BODY), "the partner should still read the phrase"
    assert not narrower.search(TARGET_BODY), (
        "the twin must stay silent on the candidate's own words — the imperative "
        "is the whole of what it adds"
    )


def test_one_phrase_is_not_three_pieces_of_evidence(classifier: RulesClassifier) -> None:
    """The score, measured against a ``None`` sender so no ATS bonus is under it.

    ``take-home exercise`` is one phrase. Before #758 it matched three
    assessment patterns for 9 points; the general form is the only one that
    should read it, for 3.
    """
    result = classifier.classify("", TARGET_BODY, None)
    assert result.scores["assessment"] == 3, result.matched_patterns
    strong_hits = [p for p in result.matched_patterns if p.startswith("[STRONG]")]
    assert len(strong_hits) == 1, strong_hits


# ─────────────────────────────────────────────────────────────────────────────
# 3. The verdict this issue is about, and the near-miss that must not move
# ─────────────────────────────────────────────────────────────────────────────


def test_the_candidates_follow_up_no_longer_short_circuits_the_cascade(
    classifier: RulesClassifier,
) -> None:
    """The #758 case. The rules layer is still wrong here — it says
    ``assessment`` — and that is tracked separately. What it must not do is say
    so confidently enough that the learned layer never runs.
    """
    result = classifier.classify(TARGET_SUBJECT, TARGET_BODY, "candidate@example.com")
    assert result.confidence < RULES_SHORT_CIRCUIT, (
        f"rules answered {result.category.value} at {result.confidence}, which "
        f"returns from hybrid.classify before SetFit is consulted"
    )


@pytest.mark.parametrize(
    "subject,body,sender",
    [
        (NEAR_MISS_SUBJECT, NEAR_MISS_BODY, "recruiter@example.com"),
        (CORPUS_UPDATE_SUBJECT, CORPUS_UPDATE_BODY, "talent@relay.example.test"),
        ("", NEAR_MISS_BODY, None),
    ],
    ids=["v3-take-home-assignment", "corpus-update-in-thread", "body-only-no-sender"],
)
def test_the_employers_assessment_mail_does_not_move(
    classifier: RulesClassifier, subject: str, body: str, sender: str | None
) -> None:
    """The near-miss control. A narrowing that also breaks real assessment mail
    is worse than the bug it fixes.
    """
    result = classifier.classify(subject, body, sender)
    assert result.category is EmailCategory.ASSESSMENT, result.matched_patterns


def test_the_corpus_update_still_clears_the_auto_file_gate(
    classifier: RulesClassifier,
) -> None:
    """The 300, and the reason the twin exists.

    Measured on the independent corpus: without ``\bcomplete\b.{0,30}…`` this mail
    scores 3, lands at 0.70, and the board replay moves 300 messages out of
    ``addressed_on_a_card`` into ``suppressed_as_settled`` — dropped, not
    queued.
    """
    result = classifier.classify(
        CORPUS_UPDATE_SUBJECT, CORPUS_UPDATE_BODY, "talent@relay.example.test"
    )
    assert result.confidence >= AUTO_FILE_GATE, result.matched_patterns


# ─────────────────────────────────────────────────────────────────────────────
# 4. #119's own purpose has to survive the narrowing
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "subject,body",
    [
        ("Your take-home", "The take-home is due Friday."),
        ("[Action Required] Your Take-Home", "Details are inside."),
        ("Take-home for the Backend Engineer role", "Link enclosed."),
    ],
)
def test_the_bare_noun_still_fires_on_its_own(
    classifier: RulesClassifier, subject: str, body: str
) -> None:
    """#119 exists because a bare 'take-home' scored zero. The lookahead added
    for #758 must not take that back: it excludes only the nouns a sibling
    already claims, which is precisely where the pattern was never needed.
    """
    result = classifier.classify(subject, body, None)
    assert result.category is EmailCategory.ASSESSMENT
    assert any(r"\btake-home\b" in p for p in result.matched_patterns), result.matched_patterns


def test_the_deleted_alternation_lost_no_reach(strong: list[str]) -> None:
    """``exercise`` was removed from the qualified pattern because the general
    one already covers it: a single space fits inside ``.{0,20}`` and
    ``exercise`` is in its tail. Proved by running both, not by reading them.
    """
    general = re.compile(
        _one(strong, "(technical|coding|take.?home)", exclude=r"\bcomplete\b"), re.I
    )
    deleted = re.compile(r"take.?home (exercise)", re.I)

    matched = 0
    for head in ("", "the ", "Please complete the ", "x" * 40):
        for middle in ("take home ", "take-home ", "takehome ", "TAKE-HOME "):
            for tail in ("exercise", "exercises", "exercise now", "exercise."):
                probe = head + middle + tail
                if not deleted.search(probe):
                    continue
                matched += 1
                assert general.search(probe), probe
    assert matched >= 48, f"the control only reached {matched} strings"


def test_the_candidates_report_does_not_reach_the_short_circuit(
    classifier: RulesClassifier,
) -> None:
    """The past tense stays under the gate; the imperative keeps its score."""

    report = classifier.classify("Re: Backend Engineer", REPORT_BODY, None)
    assert report.confidence < AUTO_FILE_GATE, (
        "the candidate's own report reached "
        f"{report.confidence}, so it auto-files or short-circuits the cascade: "
        f"{report.matched_patterns}"
    )

    invite = classifier.classify(
        "Next step for your application",
        "Please complete the take-home exercise by Friday using the link below.",
        None,
    )
    assert invite.confidence >= RULES_SHORT_CIRCUIT, (
        "the employer's imperative must keep the score the twin was added for, "
        f"got {invite.confidence}: {invite.matched_patterns}"
    )


def test_dropping_the_word_boundary_puts_the_report_back_on_the_short_circuit() -> None:
    """SHOWN TO FAIL: without ``\\b``, the report scores what the invite does.

    MUTATES ``PATTERNS`` ITSELF, not the ``strong`` fixture, and the difference
    is the whole reason this test is trustworthy: that fixture hands out
    ``list(...)`` — a COPY — so a mutation applied to it never reaches the
    engine, and this case would have reported "the anchor makes no difference"
    while never having removed it. ``RulesClassifier`` compiles from
    ``PATTERNS`` at construction (``rules.py:1700``), so the real list is what
    has to move, and it is restored in a ``finally``.
    """

    live = PATTERNS[EmailCategory.ASSESSMENT].strong
    twin = _one(list(live), r"\bcomplete\b")
    index = live.index(twin)
    unanchored = twin.replace(r"\bcomplete\b", "complete", 1)
    assert unanchored != twin, "the mutation changed nothing, so it tests nothing"

    live[index] = unanchored
    try:
        mutated = RulesClassifier().classify("Re: Backend Engineer", REPORT_BODY, None)
    finally:
        live[index] = twin

    assert live[index] == twin, "the mutation was not restored"
    assert mutated.confidence >= RULES_SHORT_CIRCUIT, (
        "removing the word boundary did NOT put the candidate's report back on "
        f"the short circuit ({mutated.confidence}), so the test above is not "
        "guarding what it claims to guard"
    )
