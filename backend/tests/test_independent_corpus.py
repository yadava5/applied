"""The ten-thousand-message corpus, as a gate.

``scripts/run_independent_corpus.py`` is the instrument; this is the ratchet.
Every number below was MEASURED, not chosen, and each is pinned so a change to
the rules or the resolver has to move it deliberately rather than silently.

Read the headline with its corpus. This one is 18% adversarial by construction —
mail written to defeat the classifier, not mail that happens to be hard — so
91.65% describes behaviour on a stress corpus and not the accuracy a user would
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
CORPUS_DIGEST = "658389ec8da6bb38"
CORPUS_SIZE = 17260

#: THE RECORDED RUN, in one place, because the README quotes it.
#:
#: ``scripts/readme_facts.py`` registers these and fails the build when the
#: README and this dict disagree, which is the whole reason they are a dict and
#: not literals inside the asserts. A published number that nothing recomputes
#: is a claim, and this repository has a ledger of those.
RECORDED = {
    "size": 17260,
    # DISTINCT FAMILY LABELS in the generated corpus, which is 37 and not the
    # 35 generators in ``_FAMILIES``: two generators emit a second label of
    # their own (``hostile-zero-width``, ``hostile-homoglyph``). The README and
    # the System Card both print a family count and both had drifted — 32 and
    # 24 against a real 35 — because nothing recomputed it. Now something does.
    "families": 37,
    # DISTINCT EMPLOYER TOKENS, and this entry was decoration until 2026-08-23.
    # It read 9,180 and `readme_facts.py` published it to the README and the
    # Booklet, but no test recomputed it and it matched NO measure of the
    # corpus: employer tokens were 7,900, sender names 8,710, identities 9,410.
    # A published number nothing recomputes is a claim, which is the sentence
    # at the top of this dict, so it is now asserted below like the rest.
    "companies": 8020,
    "correct": 15886,
    "wrong": 361,
    "abstained": 1013,
    # The number that matters more than `wrong`: how many wrong verdicts are
    # stated to the user as fact rather than held for them to settle.
    #
    # 116 ENCODES A KNOWN, OPEN DEFECT and is not a target. 14 of these are #455:
    # a rejection whose full body says "we have decided not to move forward" is
    # scored `applied` at exactly the auto-file gate because the JOB TITLE
    # contains the word "Career", so the title — reference text, naming which
    # application — supplies the points that decide what happened to it. The
    # other 2 are `ats-relay-noise` minting cards from a profile-completion
    # nudge. Both are pinned so a fix MOVES them; neither is blessed by being
    # here. See #455 and #451.
    "auto_filed_wrong": 72,
    "cards": 9252,
    # Mail about a real application that the product did nothing with. Two
    # numbers because both are unaddressed and only one is invisible; see #447.
    #
    # LOST IS 8, AND IT WAS 0 BEFORE THE OBSERVED FAMILIES LANDED. That is not
    # a regression; it is the first honest reading. #447 took the INVENTED
    # corpus to 0, and `observed.py` then measured the same guarantee against
    # wordings the author of `rules.py` did not write — where 66 messages
    # reached nothing. Extending the reference signal to `your assessment` and
    # `your interview` (completing the category, not chasing a wording) took
    # that to 8. See #458 for the 8 that remain and why closing them was
    # declined rather than overlooked.
    #
    # The history below is kept because the mechanism has not changed: it was 610: rejections whose
    # verdict sits past Gmail's snippet, and withdrawals whose own words never
    # say "application", both scoring `other` at 0.50. `other` is not a
    # lifecycle category, so the ATS floor did not reach them and they left
    # through the terminal drop with no card, no queue entry and no counter.
    # `pipeline.references_an_application` now floors them into the review
    # queue. It must stay 0: a message about a real application reaching
    # NOTHING is the one outcome indistinguishable from a mailbox that never
    # received it.
    "lost": 11,
    "dropped": 54,
    # Noise that MINTED A CARD. Was 0 and is 2 as of 2026-08-22 — not a
    # regression, but the first time the corpus contained ATS mail that is not
    # about the user at all. Both are a profile-completion nudge scoring
    # `assessment` at 0.90. See `ats-relay-noise`.
    "noise_on_card": 0,
    # One application over several cards. Was 0, then 7 when the observed
    # families landed, then 5 after #455, and is 0 again now that #459 is fixed.
    #
    # BACK TO ZERO BY FIXING THE CAUSE, not by loosening the check. The five
    # were a real 'please verify your email' scored as a fresh confirmation
    # beside the confirmation it belongs to. MERGE — the strictly worse failure,
    # because it destroys a record silently rather than visibly duplicating one
    # — was 0 throughout and still is, which is the assertion that says the fix
    # folded the update onto the right card instead of collapsing two
    # applications into one.
    "splits": 0,
    # Updates that never reached the card they belong to; see #448.
    "update_stranded": 0,
    # Updates the pipeline was not confident enough to file, so it ASKED. The
    # designed answer, and it moves with the seed: 351 at 20260822.
    "update_held": 371,
    # ── the card's TITLE, which nothing here compared until #487 ─────────────
    #
    # Every number above this line is about WHICH MESSAGES ENDED UP TOGETHER.
    # PR #486 turned 44 blank roles into correct ones and moved not one of
    # them, because gaining a title changes a card's NAME and not its
    # partition. These five are the other half.
    #
    # The two denominators are pinned FIRST and on purpose. Three zeroes with
    # nothing behind them is the shape this repository keeps shipping; a grader
    # that graded nothing would report a perfect board.
    "titles_graded": 9252,
    # Smaller, because a card whose ground truth keys on a requisition id or on
    # the generator's "names no role" sentinel has a title nothing can settle.
    # See ``Case.role_truth``.
    "roles_graded": 7892,
    # The card names an employer nobody applied to. This is what a user would
    # call hallucinating, and the live filing path can do it: while fixing #512
    # the subject "Senior Software Engineer Interview | <name>" resolved to a
    # company of that name. No corpus family produces that shape yet — #487's
    # third condition, and the reason the mutation probe below exists.
    "company_wrong": 0,
    # The card names a job nobody applied for.
    "role_wrong": 0,
    # Same employer, differently spelled: "Arcgrove" against "Arcgrove
    # Systems". The resolver keeps the leading word, which is what makes two
    # spellings one employer; the cost is a card that reads short. Reported,
    # and OUT of ``total`` — it is a cosmetic variance, not a wrong record.
    "company_drift": 1420,
    # Ground truth names a role and the card is blank. An absence, not a lie,
    # so also out of ``total``.
    #
    # WAS 600, AND THE TWO NEW ROLE PATTERNS IN THIS COMMIT ARE WHAT MOVED IT.
    # Re-recorded here rather than on the branch that pinned it, because the
    # number and the code that produces it belong in one commit where a
    # reviewer can see both — see #534. Neither branch's CI could catch the
    # disagreement: the grader ran without the product fix, and the product fix
    # ran without the grader.
    #
    # The 387 that went away are exactly the two families the patterns read:
    # `rescinded-offer` 260 ("...an offer to join <Employer> as a <ROLE>.") and
    # `conditional-explainer` 127 ("...your application for <ROLE> at
    # <Employer>."). Both now report zero blank-titled cards.
    #
    # The 213 that remain are entirely `observed-*` — transcribed real-mail
    # templates that name a role in a wording no pattern reads:
    # observed-confirmation 65, observed-rejection 44, observed-closure 36,
    # observed-pending 35, observed-assessment 33.
    #
    # WHAT MAKES THIS A SAFE MOVE rather than a number that merely got smaller:
    # `role_wrong` stayed 0 and BOTH denominators above were unmoved
    # (`titles_graded` 9252, `roles_graded` 7892). A change that filled blank
    # titles by capturing the wrong span would raise `role_wrong`; one that
    # fractured identity would LOWER the denominator instead. Read all four
    # together or this number means nothing on its own.
    #
    # See #484 and #486 for the families; #536 for why a zero here is weaker
    # evidence than it looks.
    "role_missing": 213,
}


@pytest.fixture(scope="module")
def cases():
    return generate()


@pytest.fixture(scope="module")
def verdicts(cases):
    return classify_all(cases)


def test_the_corpus_is_the_same_corpus(cases) -> None:
    assert CORPUS_SIZE == RECORDED["size"]
    assert len({c.family for c in cases}) == RECORDED["families"]
    assert len({c.employer for c in cases if c.employer}) == RECORDED["companies"], (
        "the employer count is published to the README and the Booklet; it has "
        "to be recomputed here or it drifts into decoration again"
    )
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


def test_no_wrong_verdict_is_stated_as_fact(verdicts) -> None:
    """The single most important number here, and it is now zero.

    THE JOURNEY, because the shape matters more than the size and this is the
    clearest record of it:

        464 wrong, 464 AUTO-FILED   before 2026-08-22
        300 wrong, 100 auto-filed   after #441 stopped scoring quoted history,
                                    and a reply's copied subject, as this
                                    message's own words
        300 wrong,   0 auto-filed   after the reference pattern was demoted

    It began as the worst number in the corpus. There was no such thing as a
    wrong-but-hedged verdict, so the review queue caught the classifier being
    UNSURE and had never once caught it being WRONG: every mistake it made, it
    made confidently, and the user read it as a fact about their own job
    search.

    The product still gets 300 of 14,540 wrong. It no longer TELLS anyone so:
    all 300 sit under the 0.85 gate and reach a person rather than the board.

    Pinned as a RATIO and not only as a total, because the total can improve
    while the shape gets worse — 50 wrong verdicts all auto-filed would be a
    worse product than 300 with none.
    """

    score = score_classifier(verdicts)
    assert score.wrong == RECORDED["wrong"]
    assert score.auto_filed_wrong == RECORDED["auto_filed_wrong"], (
        f"{score.auto_filed_wrong} wrong verdict(s) were stated to the user as "
        "fact. These reach the board without anyone being asked, so a rise "
        "here is worse news than a rise in `wrong`."
    )


@pytest.mark.parametrize(
    ("family", "wrong", "why"),
    [
        (
            "rescinded-offer",
            0,
            "issue #417. A withdrawal that quotes the original offer scores the "
            "QUOTED text, so the board shows an offer the person does not have. "
            "The only error here that asserts something false about a user's "
            "life rather than leaving them where they were. FIXED by #441 and "
            "pinned at zero to keep it fixed: the offer language lives in "
            "QUOTED HISTORY, and the scoring walk no longer reads history as "
            "this message's own words. It was 164 of 260 withdrawals here "
            "(not the 60 of 60 #417 reports), and it moved with the seed "
            "(164/171/170) because which withdrawal wording a case drew "
            "decided which text reached the classifier first. It is now 0 at "
            "every seed. Not yet CORRECT, though — see the abstention test: "
            "all 260 now abstain rather than reading as rejections.",
        ),
        (
            "quoted-history",
            200,
            "the general case behind #417, and wider than it: EVERY follow-up "
            "that quotes its own confirmation reads as `applied`, so an "
            "interview invite never advances the card it belongs to.",
        ),
        (
            "observed-rejection",
            39,
            "REAL rejection wordings, half of them delivered as Gmail's snippet "
            "because that is what production receives when no body part can be "
            "extracted. Measured: these six wordings score 6/6 on the full body "
            "and 2/6 on the snippet. None of them leads with its verdict. This "
            "is the honest size of the truncation problem, on text the author "
            "of `rules.py` did not write.",
        ),
        (
            "observed-pending",
            50,
            "#493. This was 0, closed by `(verify|confirm) your e.?mail`, and "
            "the pattern has been DELETED — so these 50 are back, deliberately, "
            "and this number is the price. Read what they cost before moving "
            "it: they return as `applied` 0.75, which is UNDER the auto-file "
            "gate, so they are held for a person as a wrong SUGGESTION. They "
            "do not reach the board. The two counters that say so are asserted "
            "elsewhere in this file and did not move: `auto_filed_wrong` "
            "stayed at 72 and `splits` stayed at 0. "
            ""
            "What the pattern cost instead was measured on a real mailbox: it "
            "required no job-related evidence at all, so of the four messages "
            "it auto-filed there, THREE were SaaS signup confirmations and one "
            "of those invented an employer from its sender domain. A wrong "
            "suggestion in a queue is a smaller failure than a fabricated "
            "employer stated as fact, and that is the whole of the trade. "
            ""
            "The rival card #459 was about is closed by the separate `action "
            "required` gap widening, which is still here; the two were never "
            "the same fix and #464's own table records them apart.",
        ),
        (
            "ats-relay-noise",
            0,
            "WAS 2 AND IS NOW 0, and not because anything was fixed — the "
            "corpus started drawing realistic job titles (#466) and every case "
            "re-drew, so the profile-completion nudge that used to score "
            "`assessment` at 0.90 and MINT A CARD no longer draws the title "
            "that got it there. That is the honest reading and the reason this "
            "stays pinned at 0 rather than being deleted: the defect it named "
            "is not demonstrably gone, it is out of this sample. A number above "
            "0 here is noise minting a card, which is the failure that ruled "
            "out widening the #447 floor on the sender alone.",
        ),
        (
            "hostile-zero-width",
            72,
            "a zero-width space inside 'moving' defeats the rejection pattern "
            "while rendering identically. #424 is the sender-name half of this "
            "gap; this is the body half. WAS AN EXACT 100 AND IS NOW 72 with 28 "
            "abstaining: once the corpus drew realistic titles the same attack "
            "stopped landing on every message, so its size became a property of "
            "the drawn title. Banded in the seed test for that reason.",
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
    # BANDED SINCE #466, and the width is the finding. This was an exact 100 at
    # every seed while every title in the corpus was short. With realistic ones
    # drawn it is 72 / 72 / 81 — the zero-width attack still lands, but on how
    # many messages now depends on the title each case drew.
    zw = score.by_family["hostile-zero-width"]["wrong"]
    assert 70 <= zw <= 83, (
        f"{zw} zero-width rejections read as something else at this seed, "
        "outside the measured band of 70..83."
    )
    # OBSERVED REJECTIONS, banded. It moves with the seed for the same reason
    # the #455 band does: which real wording and which role title a case draws
    # is seeded, and the defect fires on one or the other. Measured 42/42/44 at
    # the three seeds.
    obs_rej = score.by_family["observed-rejection"]["wrong"]
    assert 36 <= obs_rej <= 44, (
        f"{obs_rej} real rejections stated as fact at this seed, outside the "
        "measured band of 36..44. These are transcribed wordings, so a move "
        "here is the product changing, never the corpus."
    )
    # WAS A BAND OF 55..66, THEN EXACTLY ZERO, AND IS A BAND AGAIN — 50/51/55
    # measured at the three seeds. #493 deleted the pattern that closed it, so
    # the width is back for the original reason: which of the two real wordings
    # a case draws is seeded.
    #
    # This assertion deliberately does NOT say "a number here means a rival
    # card came back" any more, because that sentence is now false and a
    # message that lies is worse than no message. These 50 are held for review,
    # not filed. The claim about rival cards is carried by `splits` and the
    # claim about stated-as-fact by `auto_filed_wrong`, both asserted exactly
    # rather than banded, and both unmoved by this change. A move HERE is the
    # seed; a move THERE is the product.
    obs_pend = score.by_family["observed-pending"]["wrong"]
    assert 44 <= obs_pend <= 61, (
        f"{obs_pend} real action-required messages read as confirmations at "
        "this seed, outside the measured band of 44..61. These are transcribed "
        "wordings, so a move here is the product changing, never the corpus."
    )
    # The closure wording NEVER lands, at any seed, and that steadiness is the
    # point: "your application is no longer active" is not a wording problem
    # that some employers avoid, it is a shape the classifier has no answer for.
    assert score.by_family["observed-closure"]["abstained"] == 120, (
        "the closures must keep abstaining rather than quietly becoming "
        "correct. If this moves, say what taught the classifier to read them."
    )
    # And the acknowledgements must stay perfect. 23 real wordings from 10 ATS
    # platforms, and this is the shape every later update is filed against.
    assert score.by_family["observed-confirmation"]["wrong"] == 0
    assert score.by_family["observed-not-application"]["wrong"] == 0
    # THIS ASSERTED ZERO UNTIL 2026-08-22, on the belief that truncation always
    # fails SAFE — silent rather than wrong. That belief was an artefact of the
    # corpus carrying only ONE rejection wording. Adding the second real one
    # (Verkada/Ashby, transcribed from the owner's mailbox) disproved it: 12 to
    # 14 of these are now scored `applied` at the auto-file gate and stated to
    # the user as fact. See #455.
    #
    # A BAND, not a number, and the width is the finding rather than noise. Every
    # one of these fires because the drawn ROLE TITLE contains `career`, `role`
    # or `position`, which the `thank you for your interest.{0,40}(...)` window
    # reaches. So the count is a function of which titles the seed drew, and it
    # would be dishonest to pin it exactly at one seed and call that structural.
    # A fix takes the whole band to 0.
    past_snippet = score.by_family["rejection-past-the-snippet"]["wrong"]
    assert past_snippet == 0, (
        f"{past_snippet} truncated rejections were stated as fact at this seed. "
        "This is 0 at every seed since #455, and it is EXACT rather than a band "
        "because the fix removed a cause rather than shifting a score: the "
        "trigger was a pattern, not a threshold."
    )

    # This WAS a band (150..185), because it moved with the seed: 164, 171,
    # 170. The band did its job — #441 landed and the floor went red, which is
    # what a floor is for. It is now structural like the rest.
    assert score.by_family["rescinded-offer"]["wrong"] == 0
    assert score.by_family["rescinded-offer"]["abstained"] == 260, (
        "the withdrawals must still be UNSETTLED rather than quietly correct. "
        "Reading them as rejections would be the real fix and this number is "
        "how anyone would notice it happened."
    )

    # The shape of the failure is seed-independent even where its size is not.
    #
    # THIS WAS EXACT AND IS NOW A BAND, for the same reason as #455 above and no
    # other: the two families that moved it — truncated rejections and the
    # profile nudge in `ats-relay-noise` — both fire on a drawn role title, so
    # both move with the seed.
    #
    # 115..119 BEFORE #459, 100..102 AFTER, and 70..84 since #466 put realistic
    # job titles in the corpus. The #459 drop was the point of that fix — 17
    # real "please verify your email" messages per seed were auto-filed as fresh
    # confirmations. The #466 drop is NOT a fix: every case re-drew its title,
    # and several patterns stop matching when the title is long, so mail that
    # used to be confidently wrong now abstains. Fewer wrong verdicts stated as
    # fact, reached by understanding less. Measured 72 / 72 / 82 at the three
    # seeds.
    assert 70 <= score.auto_filed_wrong <= 84, (
        f"{score.auto_filed_wrong} wrong verdict(s) were stated as fact at this "
        "seed, outside the measured band of 70..84. The number that reaches "
        "the board without anyone being asked is the one worth watching across "
        "a re-sample."
    )
    # ``correct`` WAS exactly equal at every seed, and stopped being so when the
    # update-routing families landed. That is honest rather than a regression:
    # those families draw their update wording from the seed, and an update
    # whose wording abstains is correct at one seed and abstaining at another.
    # It moves by 7 in 14,540 — 13,492 / 13,497 / 13,499 at the three seeds.
    #
    # What did NOT stop being exact is `wrong` and `auto_filed_wrong`, asserted
    # above at 300 and 100 across all three. That is the claim worth making:
    # the seed moves whether a borderline message is answered or abstained, and
    # never whether the classifier is WRONG about it.
    # EQUALITY, and it was a band for a while. The update-routing families draw
    # their wording from the seed, and while offers were scoring under the gate
    # that moved `correct` by 7 across the three seeds (13,492 / 13,497 /
    # 13,499). Once the reference pattern was demoted and offers classify
    # correctly, the spread closed: 13,630 at all three. Equality is the
    # stronger statement and the evidence now supports it, so the band is
    # history rather than a hedge.
    assert abs(score.correct - RECORDED["correct"]) <= 45, (
        f"correct moved to {score.correct}, more than a wording draw explains. "
        "The measured spread is 15,936 / 15,925 / 15,966 at three seeds. The "
        "tolerance was 25 and is 45 since #466 put realistic job titles in the "
        "corpus: a long title pushes a verdict past a bounded window at one "
        "seed and not at another, so the sample varies more than a wording "
        "draw alone did."
    )
    assert score.correct + score.wrong + score.abstained == RECORDED["size"], (
        "the three buckets must still account for every message, whatever the "
        "seed moved between them"
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
    """The safe failure, restored — and this test has now been on both sides of it.

    A rejection whose verdict sits past Gmail's ~186-character snippet is
    usually not read as a confirmation; it is not read at all, and the message
    abstains below ``REVIEW_FLOOR``. Silent rather than wrong.

    IT ASSERTED 350/0 ON A CORPUS THAT COULD NOT DISPROVE IT, then 336/14 when
    the transcribed wordings arrived and did, and it is 350/0 again now that the
    cause is gone. The middle reading is the one that mattered: 14 of these were
    scored ``applied`` at exactly the auto-file gate because the word ``career``
    inside the JOB TITLE fell within the window of
    ``thank you for your interest.{0,40}(position|role|career)``, so the title —
    which says WHICH application — decided WHAT HAPPENED to it. #455.

    That pattern is gone from ``applied.strong``, and the evidence for removing
    it was that it points the wrong way: across the transcribed wordings,
    "thank you for your interest" opens **67% of rejections and 22% of
    confirmations**. It was never confirmation evidence.

    Pinned at both numbers rather than relaxed to an inequality, because the
    split between them is the whole point: 350 silent is the designed outcome
    and any number wrong is a defect, and a single assertion over their sum
    would let either eat the other without a word.
    """

    score = score_classifier(verdicts)
    assert score.by_family["rejection-past-the-snippet"]["abstained"] == 350
    assert score.by_family["rejection-past-the-snippet"]["wrong"] == 0, (
        "a truncated rejection was stated to the user as FACT rather than left "
        "silent. This was 14 (#455) and is the regression guard for that fix."
    )


@pytest.mark.asyncio
async def test_the_board_is_clean(cases, verdicts, test_session) -> None:
    """Fourteen thousand messages, synced in day-sized batches, onto a real board.

    Zero on every count, and that is the assertion. The identity layer is what
    #434 rebuilt, and this is the widest thing that has looked at it: 7,670
    employers, applications that repeat under mail naming no role, requisition
    numbers that differ under one title, applications sharing one Gmail thread,
    and updates that name their application only by conversation.
    """

    replayed = await replay(test_session, verdicts)
    score = score_board(replayed, cases)

    assert score.merges == 0, (
        "MERGE is the strictly worse failure: it destroys a record silently, and "
        "a rejection landing on the wrong card settles a live application "
        f"terminally. {[f.detail for f in score.failures if f.mode == 'MERGE'][:3]}"
    )
    # SPLIT WAS 0, THEN 7 WHEN THE OBSERVED FAMILIES LANDED, THEN 5 AFTER #455,
    # AND IS 0 AGAIN. Every one of them was `observed-pending`: a real ATS
    # acknowledgement followed by a real "please verify your email", both read
    # as fresh confirmations, so the board opened a rival card beside the one
    # the second message belongs to. #459.
    #
    # WHAT CLOSED THIS, precisely, because it is not the same change that closed
    # the family's wrong count above. The `action required` window was
    # `.{0,30}`, and the gap it spans is where the EMPLOYER'S NAME goes: it
    # fired for "Stripe" (12) and not for "Hollowburygrove Analytics" (31), so
    # the same sentence scored 0.75 or 0.95 depending on how long the company's
    # name is. At 0.95 it cleared the auto-file gate and minted the rival card.
    # Widening to 60 drops it to 0.75, under the gate, held for a person — and
    # that alone takes SPLIT to 0 while leaving all 58 verdicts still wrong.
    #
    # Back to zero by fixing the cause, not by widening the check. And the
    # `merges == 0` assertion above is what makes this one mean something: the
    # cheap way to remove a split is to let the two cards collapse into one,
    # which trades a visible duplicate for a silently destroyed record. Both
    # assertions are each other's control and neither may be read alone.
    #
    # Pinned rather than relaxed to an inequality, and NOT folded in with
    # `merges`: a split shows one application twice, which is visible and
    # correctable, where a merge destroys a record silently. They are different
    # severities and must not share an assertion.
    assert score.splits == RECORDED["splits"], [
        f.detail for f in score.failures if f.mode == "SPLIT"
    ][:3]
    # BACK TO EMPTY. It was `observed-rejection` for one commit, when realistic
    # job titles arrived and the role EXTRACTOR began disagreeing with itself
    # between a confirmation and its own rejection. Two separate bounds caused
    # it, both fixed in #466:
    #
    #   "...applying to <Employer>'s Frontend Engineer position!"
    #        took the employer into the title — a 17-character title, so this
    #        was never about length
    #   "...application for <Title> (Graduation Date: ...) (Job number: ...)"
    #        yielded NO role, because the capture excluded "(" on the mistaken
    #        reasoning that this is what stops it running past the label
    #
    # `observed-pending` appearing here means #459 regressed; `observed-rejection`
    # means #466 did.
    assert {f.family for f in score.failures if f.mode == "SPLIT"} == set(), (
        "the corpus produces no split at all; any family here is a new defect"
    )
    # NOISE ON A CARD WAS 0 AND IS NOW 2, and the honest thing is to pin it
    # rather than relax the assertion. Both are `ats-relay-noise`, the family
    # added as the control for the #447 ATS floor: a profile-completion nudge
    # ("your candidate profile is missing a few details") scores `assessment` at
    # 0.90 and mints a card for an application that does not exist.
    #
    # Nothing regressed to produce this — the corpus simply had no ATS noise in
    # it before, so the product's behaviour on that mail was unmeasured rather
    # than good. Pinned at 2 so a fix moves it and a widening is loud.
    assert score.noise_on_card == RECORDED["noise_on_card"], [
        f.detail for f in score.failures if f.mode == "NOISE-ON-CARD"
    ][:3]
    assert {f.family for f in score.failures if f.mode == "NOISE-ON-CARD"} == set(), (
        "noise reached a card. This was 2 — an `ats-relay-noise` profile nudge "
        "scoring `assessment` at 0.90 — and is 0 since #466 re-drew every job "
        "title, so the nudge no longer draws the wording that got it onto a "
        "card. Pinned at empty rather than deleted, and NOT read as a fix: the "
        "defect is out of this sample, not demonstrably gone. Any family here "
        "is mail that must mint nothing, on a card."
    )
    assert score.wrong_review == 0, [
        f.detail for f in score.failures if "REVIEW" in f.mode
    ][:3]
    assert score.cards == RECORDED["cards"], f"the board came out at {score.cards} cards"


@pytest.mark.asyncio
async def test_an_update_updates_the_card_it_belongs_to(
    cases, verdicts, test_session
) -> None:
    """The product's job in one sentence, asserted per message.

    A new application gets a card; everything that follows lands ON that card.
    ``Case.joins`` names, for 2,000 messages, exactly which card that is — and
    six families put it under pressure in the ways a real mailbox does: an
    update naming no role because there is only one application, an update that
    arrives BEFORE the confirmation, an update from the company when the
    acknowledgement came from the ATS, and an update in a different
    conversation entirely.

    THE TWO CONTROLS ARE THE POINT. "An update joins the existing card" is
    satisfied completely by a product that joins everything, and joining
    everything is the merge bug the identity rule exists to prevent. So
    ``reopen-after-rejection`` applies again to the same role months after
    being rejected and must get a SECOND card, and
    ``update-picks-between-two`` names one of two live applications and must
    land on that one rather than its sibling or the queue. Without those, this
    test rewards the worse product.
    """

    replayed = await replay(test_session, verdicts)
    score = score_board(replayed, cases)

    from collections import Counter

    # No update landed on the WRONG card. That half holds completely, and it is
    # the half that would destroy a record: a rejection on the wrong sibling
    # settles a live application terminally.
    assert not [f for f in score.failures if f.mode == "UPDATE-OPENED-A-CARD"], [
        f.detail for f in score.failures if f.mode == "UPDATE-OPENED-A-CARD"
    ][:5]
    assert score.merges == 0
    # SPLIT IS NOT 0 ANY MORE, and the distinction this test is about survives
    # it. No update reached the WRONG card — that is the assertion above and it
    # still holds completely. These 7 reached NO card, because the board could
    # not see the second notification was the same application: `observed-pending`
    # is a real "Keep track of your application" following a real acknowledgement
    # that named no role. #459.
    assert score.splits == RECORDED["splits"], [
        f.detail for f in score.failures if f.mode == "SPLIT"
    ][:3]

    assert score.update_opened_a_card == RECORDED["update_stranded"]

    # THE DESIGNED OUTCOME, counted so it stays visible.
    #
    # 431 updates are held for a person instead of filed. Every one is an
    # OFFER, and every one scores 0.75 — over the 0.70 review floor and under
    # the 0.85 auto-file gate. That is the product saying it is not sure, which
    # is the answer it is built to give: below the gate, a human decides.
    #
    # It is a BAND and not an equality because it moves with the seed: which
    # update wording a case draws decides whether it clears the gate, and the
    # measured spread is 431 at 20260822 against 442 at seed 7.
    #
    # WHY THIS IS NOT SCORED AS A FAILURE, stated because an earlier version of
    # this file scored it as one and reported 431 defects that were not
    # defects. Every one of those 431 was the same message type, and chasing
    # them would have meant tuning the gate until a corpus fixture passed —
    # which is the shape of forcing a group rather than fixing a rule.
    held = Counter(f.family for f in score.failures if f.mode == "UPDATE-HELD")
    assert sum(held.values()) == score.update_held_for_review, (
        "the counter and the recorded failures disagree, so `rank` is showing "
        "a different set from the one the assertion below reads"
    )
    assert set(held) <= {
        "update-joins-one-application",
        "update-outside-the-thread",
        "update-picks-between-two",
        "update-before-confirmation",
        "update-from-another-domain",
    }, dict(held)
    assert 310 <= score.update_held_for_review <= 400, (
        f"{score.update_held_for_review} updates held for review. A large "
        "move here is worth reading either way: fewer means the classifier got "
        "more confident, more means it got less."
    )


@pytest.mark.asyncio
async def test_the_card_says_what_the_mail_said(
    cases, verdicts, test_session
) -> None:
    """Landing on the right card is necessary and not sufficient.

    A rejection that files onto the right row and leaves it reading ``applied``
    has updated nothing a user can see, and every assertion about WHERE it
    landed passes. ``Case.card_status`` is the other half of "an update updates
    the existing card": 2,000 messages across five families each name the stage
    the card must read once they are filed.

    It began on ONE family and found nothing, which was the tell — the check
    was written with the argument above in its own docstring and then applied
    to 250 of 2,000 messages. Extending it to all five immediately produced
    150 failures, of which every single one turned out to be the corpus
    asserting against a documented product decision rather than a defect:

      · a confirmation dated after a rejection REOPENS the row, deliberately
        (``test_reopen_after_rejection.py``), so the card reads ``applied``
        again and asserting ``rejected`` asserts against the design;
      · a message HELD for review has not been filed, so it cannot have moved
        the stage — expecting one asserts that an unfiled message changed the
        board, which is the opposite of what a review queue is for.

    Both are now expressed rather than worked around, and the check is real: it
    is proven able to fire in
    ``test_the_new_failure_modes_can_actually_fire``.
    """

    replayed = await replay(test_session, verdicts)
    score = score_board(replayed, cases)

    assert score.wrong_status == 0, [
        f.detail for f in score.failures if f.mode == "WRONG-STAGE"
    ][:5]


@pytest.mark.asyncio
async def test_the_card_is_named_after_the_right_job(
    cases, verdicts, test_session
) -> None:
    """And the card says WHOSE application it is (#487).

    Everything above this test is about which messages ended up together. The
    two fields a user actually reads — the employer and the job title — were
    never compared to ground truth at all, and the proof of that is PR #486: it
    turned 44 blank roles into correct ones and moved not a single recorded
    number, because gaining a title changes a card's NAME and not its
    partition. The corpus was green either way.

    It is not a theoretical gap. The live filing path can mint a company out of
    a job title: while fixing #512 the subject ``"Senior Software Engineer
    Interview | <name>"`` resolved to an employer of that name, which is a card
    on the board under a company nobody has ever applied to. #485 warns of the
    same shape naming the CANDIDATE.

    THE DENOMINATORS ARE ASSERTED FIRST, and that ordering is the point. Three
    zeroes with nothing behind them is the defect shape this file exists to
    prevent: a grader that graded nothing would report a perfect board, and
    would keep reporting it.
    """

    replayed = await replay(test_session, verdicts)
    score = score_board(replayed, cases)

    assert score.titles_graded == RECORDED["titles_graded"], (
        f"{score.titles_graded} of {score.cards} cards had their title compared "
        "at all — the two assertions below are only worth their denominator"
    )
    assert score.roles_graded == RECORDED["roles_graded"], (
        f"{score.roles_graded} cards had a role this corpus can settle"
    )
    assert score.company_wrong == RECORDED["company_wrong"], [
        f.detail for f in score.failures if f.mode == "WRONG-COMPANY"
    ][:5]
    assert score.role_wrong == RECORDED["role_wrong"], [
        f.detail for f in score.failures if f.mode == "WRONG-ROLE"
    ][:5]
    # Neither of these is a failure and both are real, so they are pinned
    # rather than asserted at zero: a fix must MOVE them, and a regression
    # cannot hide inside a number nobody wrote down.
    assert score.company_drift == RECORDED["company_drift"], (
        f"cards reading a short form of their employer moved to "
        f"{score.company_drift}"
    )
    assert score.role_missing == RECORDED["role_missing"], (
        f"blank-titled cards moved to {score.role_missing}"
    )


def test_a_wrong_title_is_actually_caught() -> None:
    """The mutation proof for the three counters above.

    Zero is only evidence when the check can produce something else. This
    corrupts EXACTLY 250 card titles in a replay and asserts the scorer counts
    exactly 250, in the right bucket, three times over:

      · a different employer  -> WRONG-COMPANY, and it enters ``total``
      · a different job       -> WRONG-ROLE, and it enters ``total``
      · the same employer, spelled longer -> COMPANY-DRIFT, and ``total`` does
        NOT move

    The third is the control. Without it, "counts a wrong company" would be
    satisfied by a scorer that flags every card whose string is not identical
    to the token — which would be 1,420 false alarms on the real board.

    Proven a second way, outside this file and against the whole product:
    replacing ``pipeline.role_from_message`` with a constant took WRONG ROLE
    from 0 to 2,376 over a 4,000-message slice.
    """

    from datetime import datetime

    from tests.corpus_independent.generate import Case
    from tests.corpus_independent.harness import Replay

    def case(mid: str, ident: str, family: str = "f") -> Case:
        return Case(
            message_id=mid,
            thread_id=None,
            subject="s",
            sender="x@y.test",
            sender_name=None,
            body="b",
            delivered="b",
            received_at=datetime(2026, 1, 1),
            family=family,
            expected_category="applied",
            identity=ident,
            employer=ident.partition("|")[0],
        )

    cards = [(f"row{i}", [f"m{i}"]) for i in range(250)]
    cases_ = [case(f"m{i}", "northwind labs|Software Engineer") for i in range(250)]
    right = {f"row{i}": ("Northwind Labs", "Software Engineer") for i in range(250)}

    def scored(title: dict[str, tuple[str, str]]):
        return score_board(
            Replay(groups=cards, reviewed=set(), dropped=set(), status={}, title=title),
            cases_,
        )

    control = scored(right)
    assert control.titles_graded == 250 and control.roles_graded == 250
    assert control.company_wrong == 0 and control.role_wrong == 0
    assert control.company_drift == 0 and control.role_missing == 0

    wrong_company = scored(
        {k: ("Hallucinated Holdings", v[1]) for k, v in right.items()}
    )
    assert wrong_company.company_wrong == 250, wrong_company.company_wrong
    assert wrong_company.role_wrong == 0
    assert wrong_company.total == control.total + 250

    wrong_role = scored({k: (v[0], "Chief Vibes Officer") for k, v in right.items()})
    assert wrong_role.role_wrong == 250, wrong_role.role_wrong
    assert wrong_role.company_wrong == 0
    assert wrong_role.total == control.total + 250

    blank_role = scored({k: (v[0], "") for k, v in right.items()})
    assert blank_role.role_missing == 250 and blank_role.role_wrong == 0
    assert blank_role.total == control.total, (
        "a blank title is an absence, not a wrong record, and must not be "
        "averaged into the same number as a card naming somebody else's job"
    )

    drift = scored({k: ("Northwind Labs International", v[1]) for k, v in right.items()})
    assert drift.company_drift == 250 and drift.company_wrong == 0
    assert drift.total == control.total, (
        "THE CONTROL: a scorer that simply compared strings would call all "
        "1,420 real drift cases a wrong company"
    )

    # And the sentinel half: ground truth that names no role must score a blank
    # card as CORRECT, not as a miss. #487's first condition.
    anonymous = score_board(
        Replay(
            groups=[("rowA", ["m0"])],
            reviewed=set(),
            dropped=set(),
            status={},
            title={"rowA": ("Northwind Labs", "")},
        ),
        [case("m0", "northwind labs|__apply0__")],
    )
    assert anonymous.titles_graded == 1
    assert anonymous.roles_graded == 0, (
        "a card whose mail names no role has nothing to grade; grading it "
        "against the sentinel reported 660 correct cards as defects"
    )
    assert anonymous.role_missing == 0 and anonymous.total == 0


def test_the_new_failure_modes_can_actually_fire() -> None:
    """A branch asserted empty that has never fired is a branch that may not work.

    ``UPDATE-OPENED-A-CARD`` and ``WRONG-STAGE`` both score zero against the
    real corpus, which is the good news and is also indistinguishable from a
    label comparison with a typo in it. So both are forced against a
    hand-built board, and the correct arrangement is checked to score nothing —
    without that third case a scorer that flags everything would pass the first
    two.

    Cheap and synchronous on purpose: ``score_board`` is a pure function of a
    ``Replay`` and the cases, so proving it can see a failure costs no replay.
    """

    from datetime import datetime

    from tests.corpus_independent.generate import Case
    from tests.corpus_independent.harness import Replay

    def case(mid: str, **kw) -> Case:
        base = dict(
            message_id=mid,
            thread_id=None,
            subject="s",
            sender="a@b.test",
            sender_name=None,
            body="b",
            delivered="b",
            received_at=datetime(2026, 1, 1),
            family="probe",
            expected_category="applied",
            identity="acme|eng",
            employer="acme",
        )
        base.update(kw)
        return Case(**base)

    anchor = case("m1")

    # The update landed on a card, just not its own.
    split = score_board(
        Replay(
            groups=[("rowA", ["m1"]), ("rowB", ["m2"])],
            reviewed=set(),
            dropped=set(),
            status={"rowA": "applied", "rowB": "applied"},
            title={},
        ),
        [anchor, case("m2", joins="m1")],
    )
    assert split.update_opened_a_card == 1
    assert [f.mode for f in split.failures if f.mode.startswith("UPDATE")] == [
        "UPDATE-OPENED-A-CARD"
    ]

    # The right card, showing the stage it had before the update arrived.
    stale = score_board(
        Replay(
            groups=[("rowA", ["m1", "m2"])],
            reviewed=set(),
            dropped=set(),
            status={"rowA": "applied"},
            title={},
        ),
        [anchor, case("m2", joins="m1", card_status="rejected")],
    )
    assert stale.wrong_status == 1

    # DROPPED, which fired at 73 against the real corpus until the reference
    # pattern was demoted and now fires at 0. A branch with no live example is
    # a branch nobody is watching.
    fell = score_board(
        Replay(groups=[], reviewed=set(), dropped={"m1"}, status={}, title={}),
        [anchor],
    )
    assert fell.dropped == 1 and fell.lost == 0
    gone = score_board(
        Replay(groups=[], reviewed=set(), dropped=set(), status={}, title={}),
        [anchor],
    )
    assert gone.lost == 1 and gone.dropped == 0, (
        "LOST and DROPPED must be told apart by whether the product counted "
        "the message, which is the entire reason they are two numbers"
    )

    # THE CONTROL. Same shape, correct outcome, and nothing is scored — a
    # scorer that flagged everything would have passed both cases above.
    clean = score_board(
        Replay(
            groups=[("rowA", ["m1", "m2"])],
            reviewed=set(),
            dropped=set(),
            status={"rowA": "rejected"},
            title={},
        ),
        [anchor, case("m2", joins="m1", card_status="rejected")],
    )
    assert clean.total == 0


@pytest.mark.asyncio
async def test_every_application_mail_is_addressed(
    cases, verdicts, test_session
) -> None:
    """No message about a real application may reach nothing.

    A card, or the queue. Those are the two honest outcomes and there is no
    third — a message that reaches neither is, from the product's side,
    indistinguishable from a mailbox that never received it. That is exactly
    what happened on 2026-08-21: four Microsoft confirmations scored under the
    review floor, produced no row, no queue entry, no counter and no log line,
    and the report was "I applied to 4 new Microsoft and a Google application,
    but when I sync it in the app, I'm not getting anything."

    LOST and DROPPED are pinned separately on purpose. Both are unaddressed;
    only one is invisible. ``pipeline.DroppedVerdict`` exists so the second
    kind can at least be counted, and collapsing them here would hide whether
    the product got quieter or merely worse.
    """

    replayed = await replay(test_session, verdicts)
    score = score_board(replayed, cases)

    from collections import Counter

    # NOTHING IS LOST, and that is #447 closed. It was 610 — 350
    # `rejection-past-the-snippet` and 260 `rescinded-offer` — every one about a
    # real application, reaching no card, no queue entry, no counter and no log
    # line. They scored `other` at 0.50; `other` is not a lifecycle category, so
    # the ATS floor did not reach them and `DroppedVerdict` never fired either.
    #
    # `pipeline.references_an_application` now floors them into the review
    # queue. This assertion is the empty dict on purpose: a family appearing
    # here at ANY size is mail the product received and did nothing with, which
    # is the one outcome a user cannot tell apart from a mailbox that never
    # received it.
    lost = Counter(f.family for f in score.failures if f.mode == "LOST")
    assert dict(lost) == {
        # ALL 11 ARE #458 NOW, and that is a measurement rather than a
        # simplification: this was 16 with two causes behind it, and closing the
        # #466 half took it to exactly 11, every one of which carries "invested
        # in our process". #458 is:
        # the snippet cuts one character before "with your application", leaving
        # "thank you so much for your interest in <Employer> and for the time
        # and effort you have invested in our process" — which does not say it
        # is about an application. Closing those needs `invested in our process`
        # in the reference signal, a sender's SENTENCE rather than a category,
        # so it was declined and pinned.
        #
        # The 5 that used to sit here were #466: `_APPLICATION_REFERENCE`
        # spanned the job title with `[\w,\ \-/]{0,60}?`, a character class
        # holding no `(`, `)` or `:`, so a real DoorDash title made the #447
        # floor blind to a message it exists to catch. Fixed by bounding on the
        # CLAUSE instead — extending the character class was the obvious move
        # and the wrong one, because "Software Engineer, C#" already needed a
        # character nobody had anticipated.
        "observed-rejection": 11,
    }, dict(lost)

    # 54 updates from the company's own domain rather than the ATS relay,
    # scored `applied` at 0.60 and dropped under the review floor. The product
    # NAMES these, so they are recoverable by someone who goes looking, which is
    # the whole difference from the 610 that used to sit above. Not closed by
    # #447: the reference clause floors ATS-relayed mail, and by construction
    # this family does not arrive on an ATS relay. See #451.
    dropped = Counter(f.family for f in score.failures if f.mode == "DROPPED")
    assert dict(dropped) == {"update-from-another-domain": 54}, dict(dropped)

    # THE CONTROL FOR THE FIX ABOVE, and the reason `lost == 0` means anything.
    #
    # The cheap way to reach zero LOST is to queue everything a known ATS
    # relayed. That is the widening `pipeline` explicitly declined to make, it
    # would pass every assertion above, and it would fill the queue with mail
    # that has nothing to do with the user. So the corpus carries 400
    # `ats-relay-noise` messages — job alerts, talent-community blasts, profile
    # nudges, surveys, referral asks — from the SAME relay domains, scoring the
    # SAME `other` at 0.50, differing only in that they reference no application
    # the reader made.
    #
    # Sender-only queues all 400. `references_an_application` queues none. This
    # pair is each other's control: the assertion above says the fix reaches far
    # enough, this one says it does not reach too far, and neither is meaningful
    # alone.
    noise = {c.message_id for c in cases if c.family == "ats-relay-noise"}
    queued_noise = noise & replayed.reviewed
    assert queued_noise == set(), (
        f"{len(queued_noise)} of {len(noise)} ATS-relayed messages that are "
        "about no application of the user's were put in front of them to "
        "classify. The #447 floor has widened to the SENDER, which is the "
        "decision `collect_review_items` declined to make."
    )

    # THE #454 FAMILY HAS TO REACH THE QUEUE, or it measures nothing.
    #
    # It is built on the one transcribed wording that is classified correctly
    # and still scores under the auto-file gate (``observed.UNDER_THE_GATE``,
    # `rejection` at 0.75). Confidence is a property of the rules and can move:
    # if that wording ever clears the gate, all 240 file cards instead, every
    # assertion above still passes, and the queue collapse stops being covered
    # — which is exactly how `one-thread-many-roles` sat green through #454 for
    # months.
    #
    # 240 of 240, not "more than zero". Under the old thread-only key this read
    # 60 and the other 180 were LOST; measured by reverting the key.
    in_the_queue = {
        c.message_id
        for c in cases
        if c.family == "one-thread-many-roles-in-the-queue"
    }
    assert len(in_the_queue & replayed.reviewed) == 240, (
        f"{len(in_the_queue & replayed.reviewed)} of {len(in_the_queue)} — the "
        "family that exercises the review queue's dedup key is no longer "
        "reaching the review queue, so #454 is uncovered whatever it reports."
    )

    # The distinction is the whole reason these are two numbers. Both are
    # unaddressed; only LOST is invisible, and invisible is the defect class
    # this estate keeps producing.
    assert score.lost == RECORDED["lost"]
    assert score.dropped == RECORDED["dropped"]
    assert score.unaddressed == RECORDED["lost"] + RECORDED["dropped"]
