"""The ten-thousand-message corpus, as a gate.

``scripts/run_independent_corpus.py`` is the instrument; this is the ratchet.
Every number below was MEASURED, not chosen, and each is pinned so a change to
the rules or the resolver has to move it deliberately rather than silently.

Read the headline with its corpus. This one is 18% adversarial by construction —
mail written to defeat the classifier, not mail that happens to be hard — so
88.94% describes behaviour on a stress corpus and not the accuracy a user would
see on their own inbox. The families are reported separately for that reason.

The known defects are pinned AS DEFECTS, at their measured size, rather than
excluded. A corpus that only asserts what already passes is a check that cannot
fail, and this estate has a documented history of those. When one is fixed, its
number moves and this file has to say so.
"""

from __future__ import annotations

import pytest

from tests.corpus_independent.generate import digest, generate
from tests.corpus_independent.harness import (
    classify_all,
    replay,
    score_board,
    score_classifier,
)

#: Recorded 2026-08-22. A corpus that differs between runs cannot be a gate, and
#: a digest is the only way to say "the same mail" without shipping 24MB.
CORPUS_DIGEST = "37a772421fd5a143"
CORPUS_SIZE = 10040

#: THE RECORDED RUN, in one place, because the README quotes it.
#:
#: ``scripts/readme_facts.py`` registers these and fails the build when the
#: README and this dict disagree, which is the whole reason they are a dict and
#: not literals inside the asserts. A published number that nothing recomputes
#: is a claim, and this repository has a ledger of those.
RECORDED = {
    "size": 10040,
    "companies": 5670,
    "correct": 8930,
    "wrong": 464,
    "abstained": 646,
    "cards": 5693,
}


@pytest.fixture(scope="module")
def cases():
    return generate()


@pytest.fixture(scope="module")
def verdicts(cases):
    return classify_all(cases)


def test_the_corpus_is_the_same_corpus(cases) -> None:
    assert CORPUS_SIZE == RECORDED["size"]
    assert len(cases) == CORPUS_SIZE
    assert digest(cases)[:16] == CORPUS_DIGEST, (
        "the corpus changed. That is allowed — but every number in this file "
        "describes the OLD mail until it is re-measured, so re-record them in "
        "the same commit or they become decoration."
    )
    # Determinism is the property that matters: the generator must not depend on
    # set or dict iteration order anywhere.
    assert digest(generate()) == digest(generate())


def test_the_corpus_actually_reaches_the_product(cases, verdicts) -> None:
    """The self-check every number below rests on.

    A corpus that never clears the auto-file gate produces no failures and looks
    perfect. This estate has shipped that shape before.
    """

    auto = sum(1 for v in verdicts if v.auto_filed)
    assert auto > 7000, f"only {auto} of {len(cases)} messages cleared the auto-file gate"
    assert len({c.employer for c in cases if c.employer}) > 4000


def test_classifier_accuracy_has_not_regressed(verdicts) -> None:
    score = score_classifier(verdicts)
    assert score.correct == RECORDED["correct"], f"correct moved to {score.correct}"
    assert score.wrong == RECORDED["wrong"], f"wrong moved to {score.wrong}"
    assert score.abstained == RECORDED["abstained"], f"abstained moved to {score.abstained}"


def test_every_wrong_verdict_is_confidently_wrong(verdicts) -> None:
    """The shape of the failure, which matters more than its size.

    There is no such thing here as a wrong-but-hedged verdict: every one clears
    ``AUTO_FILE_GATE`` and are filed without review. The review queue is
    therefore not a safety net for being WRONG — it catches being UNSURE, and
    the classifier is never unsure and wrong at the same time.
    """

    score = score_classifier(verdicts)
    assert score.auto_filed_wrong == score.wrong == RECORDED["wrong"]


@pytest.mark.parametrize(
    ("family", "wrong", "why"),
    [
        (
            "rescinded-offer",
            164,
            "issue #417. A withdrawal that quotes the original offer scores the "
            "QUOTED text, so the board shows an offer the person does not have. "
            "The only error here that asserts something false about a user's "
            "life rather than leaving them where they were. Measured at 164 of "
            "260 withdrawals, not the 60 of 60 the issue reports — and it is the "
            "one defect here that MOVES with the seed (164/171/170 at three), "
            "because which withdrawal wording a case draws decides whether the "
            "quoted offer or the withdrawal reaches the classifier first.",
        ),
        (
            "quoted-history",
            200,
            "the general case behind #417, and wider than it: EVERY follow-up "
            "that quotes its own confirmation reads as `applied`, so an "
            "interview invite never advances the card it belongs to.",
        ),
        (
            "hostile-zero-width",
            100,
            "a zero-width space inside 'moving' defeats the rejection pattern "
            "while rendering identically. #424 is the sender-name half of this "
            "gap; this is the body half.",
        ),
    ],
)
def test_the_known_defects_are_exactly_this_big(verdicts, family, wrong, why) -> None:
    """Pinned as defects, at their measured size.

    Each of these is a bug. Recording the number is what makes a fix visible and
    a regression loud; excluding them would leave a corpus that asserts only
    what already passes.
    """

    score = score_classifier(verdicts)
    assert score.by_family[family]["wrong"] == wrong, why


#: Two more seeds. See :func:`test_the_defects_are_not_a_seed_artefact`.
OTHER_SEEDS = (7, 991773)


@pytest.mark.parametrize("seed", OTHER_SEEDS)
def test_the_defects_are_not_a_seed_artefact(seed: int) -> None:
    """Re-sample the population and check the same things break.

    "Run it three times" on a seeded generator is three identical runs, which
    is what the digest gate above already asserts. Re-SEEDING is the question
    worth asking: is 200 of 400 a property of the product, or of which wording
    case 3,117 happened to draw?

    The seed varies which employer, role, sender and wording each case gets. It
    never varies the family sizes or the ground truth, so this is a different
    sample of the same population — and every number below either holds exactly
    or is stated as the band it moves in.

    THE SEED WAS DEAD UNTIL 2026-08-22. ``_Builder`` built a ``random.Random``
    and never drew from it; every choice was ``[i % len(...)]``, so three seeds
    gave one byte-identical corpus and this test would have passed by tautology.
    ``test_the_seeds_are_actually_different`` is the control that keeps it real.

    Classification only, no board replay: 5s a seed against ~45s, and the board
    invariants are structural rather than statistical — one seed proves them.
    """

    score = score_classifier(classify_all(generate(seed)))

    # Structural. These do not move, and if one ever does it is news either way.
    assert score.by_family["quoted-history"]["wrong"] == 200, (
        "quoted-history is 200 of 400 at every seed tried. A change here means "
        "the defect became wording-sensitive, which is a different bug."
    )
    assert score.by_family["hostile-zero-width"]["wrong"] == 100
    assert score.by_family["rejection-past-the-snippet"]["wrong"] == 0, (
        "truncation must keep failing SAFE at every seed. This is the control "
        "on the three defects above: a board that is silent, not wrong."
    )

    # Statistical, and stated as a band because it genuinely moves: 164, 171,
    # 170 across the three seeds. A band and not a ceiling — the number falling
    # out of the bottom is a fix worth noticing, not a pass.
    assert 150 <= score.by_family["rescinded-offer"]["wrong"] <= 185

    # The shape of the failure is seed-independent even where its size is not.
    assert score.auto_filed_wrong == score.wrong, (
        "a wrong-but-hedged verdict appeared at this seed and at none of the "
        "others. That would be the review queue finally earning its keep, and "
        "it should be recorded rather than absorbed."
    )
    assert score.correct == RECORDED["correct"], (
        f"correct moved to {score.correct}. It has been exactly "
        f"{RECORDED['correct']} at every seed: the errors are structural, and "
        "what the seed moves is only whether a borderline case lands wrong or "
        "abstains."
    )


def test_the_seeds_are_actually_different() -> None:
    """The control on the test above, and it is not hypothetical.

    Without this, a regression that re-deadens the seed turns
    ``test_the_defects_are_not_a_seed_artefact`` into three runs of the default
    corpus that pass forever and prove nothing. That is exactly the state this
    file shipped in.
    """

    digests = {digest(generate(s))[:16] for s in (None, *OTHER_SEEDS) if s is not None}
    digests.add(CORPUS_DIGEST)
    assert len(digests) == 1 + len(OTHER_SEEDS), (
        f"{len(digests)} distinct corpora from {1 + len(OTHER_SEEDS)} seeds. "
        "The seed is not reaching the mail, so re-seeding measures nothing."
    )


def test_abstention_is_where_truncation_lands(verdicts) -> None:
    """The safe failure, and the control on the dangerous ones above.

    A rejection whose verdict sits past Gmail's ~186-character snippet is not
    read as a confirmation — it is not read at all, and the message abstains
    below ``REVIEW_FLOOR``. That is the difference between a board that is
    silent and a board that is wrong, and it must not quietly become the latter.
    """

    score = score_classifier(verdicts)
    assert score.by_family["rejection-past-the-snippet"]["abstained"] == 350
    assert score.by_family["rejection-past-the-snippet"]["wrong"] == 0


@pytest.mark.asyncio
async def test_the_board_is_clean(cases, verdicts, test_session) -> None:
    """Ten thousand messages, synced in day-sized batches, onto a real board.

    Zero on every count, and that is the assertion. The identity layer is what
    #434 rebuilt, and this is the widest thing that has looked at it: 4,870
    employers, applications that repeat under mail naming no role, requisition
    numbers that differ under one title, applications sharing one Gmail thread,
    and updates that name their application only by conversation.
    """

    groups = await replay(test_session, verdicts)
    score = score_board(groups, cases)

    assert score.merges == 0, (
        "MERGE is the strictly worse failure: it destroys a record silently, and "
        "a rejection landing on the wrong card settles a live application "
        f"terminally. {[f.detail for f in score.failures if f.mode == 'MERGE'][:3]}"
    )
    assert score.splits == 0, [f.detail for f in score.failures if f.mode == "SPLIT"][:3]
    assert score.noise_on_card == 0, [
        f.detail for f in score.failures if f.mode == "NOISE-ON-CARD"
    ][:3]
    assert score.wrong_review == 0, [
        f.detail for f in score.failures if "REVIEW" in f.mode
    ][:3]
    assert score.cards == RECORDED["cards"], f"the board came out at {score.cards} cards"
