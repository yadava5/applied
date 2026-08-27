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

#: Recorded 2026-08-27. A corpus that differs between runs cannot be a gate, and
#: a digest is the only way to say "the same corpus" without shipping 24MB.
#:
#: "The same CORPUS" and no longer "the same mail": `digest()` covers the ground
#: truth as well as the message from #533 on. It used to hash the mail alone, so
#: `joins`, `card_status` and the two title fields could be rewritten with this
#: number unmoved — a corpus is what it asserts as much as what it contains.
CORPUS_DIGEST = "af460ebc035261fc"
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
    # 72 ENCODES A KNOWN, OPEN DEFECT and is not a target. 14 of these are #455:
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
    # LOST IS 11, AND IT WAS 0 BEFORE THE OBSERVED FAMILIES LANDED. That is not
    # a regression; it is the first honest reading. #447 took the INVENTED
    # corpus to 0, and `observed.py` then measured the same guarantee against
    # wordings the author of `rules.py` did not write — where 66 messages
    # reached nothing. Extending the reference signal to `your assessment` and
    # `your interview` (completing the category, not chasing a wording) took
    # that to 11. See #458 for the ones that remain and why closing them was
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
    # Noise that MINTED A CARD. Went 0 -> 2 on 2026-08-22, when the corpus first
    # contained ATS mail that is not about the user at all (a profile-completion
    # nudge scoring `assessment` at 0.90), and back to 0 once the reference
    # signal stopped reading it as an application. Pinned at 0 rather than
    # deleted: this is the counter that says a stranger's mail never becomes
    # somebody's card. See `ats-relay-noise`.
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
    #
    # 371 UNTIL 2026-08-26 and 631 now, because `rescinded-offer` gained the
    # `joins` it should always have had. The extra 260 are not new behaviour —
    # they were always held, and the corpus simply had no way to say which card
    # they belonged to.
    "update_held": 631,
    # THE CARD IS AHEAD OF THE USER'S LIFE. A KNOWN, OPEN DEFECT, pinned so a
    # fix moves it; it is not blessed by being here.
    #
    # All 260 are `rescinded-offer`. The offer files a card at `offered`; the
    # withdrawal that revokes it scores `other` at 0.50 — nothing in the
    # rejection patterns matches "we must rescind the offer" — and lands in the
    # review queue. The board then shows an offer the person does not have,
    # which is the single failure #417 says matters more than any other,
    # because it asserts something false about their life rather than leaving
    # them where they were.
    #
    # The corpus scored this GREEN for as long as it existed: the family set
    # neither `joins` nor `card_status`, so the score watched the classifier
    # and never the card. Exactly #487's shape, one field over.
    #
    # HELD IS NOT AUTOMATICALLY A DEFECT and this counter is careful about it.
    # The 371 above leave a card reading `applied` when it should read
    # `offered` — BEHIND reality, incomplete, and true as far as it goes. Only
    # a card that is AHEAD counts, and the direction is read off the product's
    # own `_STATUS_RANK`. That is the control: it is what keeps this from
    # becoming a second, louder way of saying `update_held`.
    "card_overstates": 260,
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
    # Smaller, because a card whose ground truth keys on a requisition id, or
    # whose mail names no job at all, has a title this corpus either cannot
    # settle or must assert BLANK. See ``Case.role_truth``.
    #
    # 7892 -> 7746 with #533: 146 identities were carrying a role drawn from the
    # invented pool that appears in NO message on the card. They move to
    # `blank_required`, which is a stronger assertion than the grading they left.
    "roles_graded": 7746,
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
    # 213 -> 67 with #533, and NOT because anything about the product changed.
    # 146 of the 213 were ground truth asserting a job title that appears in no
    # message on the card — the generator writes `identity=f"{token}|{role}"`
    # for every case, including the `observed-*` transcriptions of real ATS mail
    # that names no role at all. Those 146 are now `blank_required`, where a
    # blank card is the CORRECT answer and a printed title would be a defect.
    # See `_settle_role_reachability`.
    #
    # The 67 that remain are the product gap: observed-rejection 44,
    # observed-pending 21, observed-assessment 2. In 41 of them
    # `role_from_message` returns nothing for every message on the card although
    # the role is spelled in a subject (20) or a body (21) — #485's shape. The
    # other 26 are stranger and are filed separately: the reader DOES return a
    # role for some message on the card and the card is still blank.
    #
    # WHAT MAKES THIS A SAFE MOVE rather than a number that merely got smaller:
    # `role_wrong` stayed 0, `titles_graded` was unmoved at 9252, and every card
    # that left `roles_graded` arrived in `blank_required` — the three
    # populations still close exactly against `titles_graded`, which is asserted
    # rather than described. A change that filled blank titles by capturing the
    # wrong span would raise `role_wrong`; one that fractured identity would
    # LOWER a denominator instead of moving a card between two of them. Read all
    # of them together or this number means nothing on its own.
    #
    # See #484 and #486 for the families; #536 for why a zero here is weaker
    # evidence than it looks.
    "role_missing": 67,
    # Mail that names NO job title, where the only correct card is a blank one.
    # These were SKIPPED entirely until the two counters below existed: "no role
    # to grade against" read as "nothing to assert", and 960 cards — 10.4% of
    # the board — could carry any title the product cared to print while every
    # counter stayed at zero. Probed directly: a card reading "Chief Vibes
    # Officer" scored titles_graded=1, roles_graded=0, role_wrong=0, total=0.
    #
    # 1106 = repeat-anonymous 600 + update-in-thread 300 +
    # double-acknowledgement 60 — the three sentinel families — plus the 146
    # identities #533 added, where the role the identity names is spelled in no
    # message the product can read.
    #
    # The board's three title populations close, and that is now an ASSERTION
    # rather than a sentence: 7746 graded + 1106 required-blank + 400 req-id
    # (genuinely unsettleable) = 9252 cards. Before `role_unsettleable` existed
    # the third term was a pasted 400 and the close could not be stated at all.
    "blank_required": 1106,
    # The third population: the corpus knows WHICH application the card is, by
    # requisition id, and does not know what the job is called. Not a defect and
    # not an assertion — the term that makes "every card is accounted for"
    # sayable. `req-id-same-title`, 400 cards.
    "role_unsettleable": 400,
    # …and none of them is wrong today. A zero here is only worth its
    # denominator above, which is why the denominator is asserted first — and
    # `test_mail_that_names_no_role_must_leave_the_card_blank` mutation-proves
    # it separately, because "all 1106 really are blank" and "this counter can
    # never fire" look identical from the corpus alone.
    "role_invented": 0,
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
        # The withdrawal of an offer. Held like the rest — and unlike the rest
        # it leaves the card claiming the offer still stands; see
        # `card_overstates` and `test_a_held_message_may_still_leave_a_lying_card`.
        "rescinded-offer",
    }, dict(held)
    assert 560 <= score.update_held_for_review <= 700, (
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
async def test_a_held_message_may_still_leave_a_lying_card(
    cases, verdicts, test_session
) -> None:
    """Holding is the designed answer. Holding is not always harmless.

    ``update_held_for_review`` is deliberately outside ``total``: below the
    gate, a person decides, and a score that punished asking would reward a
    product that guesses. That argument is sound for the 371 updates it was
    written for — an offer held while the card still reads ``applied`` leaves a
    row that is BEHIND the user's life. Incomplete, and true as far as it goes.

    It is not sound for a withdrawn offer. The offer files a card at
    ``offered``; the withdrawal is held; the board goes on showing an offer the
    person does not have. That row is AHEAD of their life, and #417 is right
    that it is the one failure worth ranking above the rest — every other error
    in this corpus leaves the user where they were, and this one tells them
    something false about it.

    The two outcomes were one number until 2026-08-26, which is why nobody had
    to look at the second: the `rescinded-offer` family set neither ``joins``
    nor ``card_status``, so the board score watched the classifier and never
    the card, and reported WRONG STAGE 0 over 260 cards reading ``offered``
    with all 260 withdrawals parked in the queue. Exactly #487's shape, one
    field over.
    """

    replayed = await replay(test_session, verdicts)
    score = score_board(replayed, cases)

    assert score.card_overstates == RECORDED["card_overstates"], [
        f.detail for f in score.failures if f.mode == "CARD-OVERSTATES"
    ][:5]
    families = {f.family for f in score.failures if f.mode == "CARD-OVERSTATES"}
    assert families == {"rescinded-offer"}, (
        f"a second family started overstating: {families}"
    )
    # THE CONTROL, and the reason this is not just `update_held` renamed: 631
    # messages are held and only 260 leave a card claiming too much. If the
    # direction test ever stops working, these two numbers converge.
    assert score.card_overstates < score.update_held_for_review


def test_only_a_card_that_is_AHEAD_of_reality_is_counted() -> None:
    """The mutation proof, and the direction is the whole check.

    A counter that fired on any held message whose card disagrees with ground
    truth would read 631 here and would be a second name for
    ``update_held_for_review``. Three cases, one held message each, identical
    but for which way the card is wrong:

      · card ``offered``, truth ``rejected``  -> counted. The offer was pulled.
      · card ``applied``,  truth ``offered``  -> NOT counted. Behind, honest.
      · card ``applied``,  truth ``applied``  -> NOT counted. Nothing wrong.
    """

    from datetime import datetime

    from tests.corpus_independent.generate import Case
    from tests.corpus_independent.harness import Replay

    def scenario(card_reads: str, truth: str):
        anchor = Case(
            message_id="m1",
            thread_id=None,
            subject="s",
            sender="x@y.test",
            sender_name=None,
            body="b",
            delivered="b",
            received_at=datetime(2026, 1, 1),
            family="rescinded-offer",
            expected_category="offer",
            identity="northwind|Software Engineer",
            employer="northwind",
        )
        update = Case(
            message_id="m2",
            thread_id=None,
            subject="s",
            sender="x@y.test",
            sender_name=None,
            body="b",
            delivered="b",
            received_at=datetime(2026, 1, 2),
            family="rescinded-offer",
            expected_category="rejection",
            identity="northwind|Software Engineer",
            employer="northwind",
            joins="m1",
            card_status=truth,
        )
        return score_board(
            Replay(
                groups=[("rowA", ["m1"])],
                reviewed={"m2"},  # HELD — the whole point
                dropped=set(),
                status={"rowA": card_reads},
                title={"rowA": ("Northwind", "Software Engineer")},
            ),
            [anchor, update],
        )

    pulled = scenario("offered", "rejected")
    assert pulled.card_overstates == 1, (
        "the board is showing an offer that was withdrawn and nothing counted it"
    )
    assert pulled.wrong_status == 0, (
        "a held message has not been filed, so it cannot have moved the stage — "
        "this must not ALSO fire as WRONG-STAGE or one defect reads as two"
    )
    assert pulled.total >= 1

    behind = scenario("applied", "offered")
    assert behind.card_overstates == 0, (
        "a card that has not caught up yet is incomplete, not lying, and "
        "counting it makes this a second name for update_held_for_review"
    )
    assert behind.update_held_for_review == 1

    agrees = scenario("applied", "applied")
    assert agrees.card_overstates == 0 and agrees.total == 0


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
    # …and as an equality with `cards`, which is BELT AND BRACES rather than an
    # independent check, stated plainly because the first draft of this comment
    # justified it with arithmetic that does not hold. Sitting after the pin
    # above, it can only fire when `cards != 9252` — and `cards` is itself
    # pinned in `test_the_board_is_clean`. The one genuinely reachable skip is
    # `len(idents) != 1`, which a MERGE causes and `merges == 0` already catches;
    # the other skip, a missing `title` entry, is structurally dead because
    # `replay()` writes one for every live row.
    #
    # It is kept because it costs nothing and says what the loop MEANS — every
    # card gets its title compared — where a pinned integer only says what it
    # measured once. It is not load-bearing, and a reader should not treat it as
    # the thing standing between a skipped card and a green board.
    assert score.titles_graded == score.cards, (
        f"{score.cards - score.titles_graded} card(s) were skipped by the title "
        "loop; a skipped card is one the product may name anything at all"
    )
    # The cards with no gradeable role split two ways, and only one of the two
    # is unanswerable. `blank_required` is the half this corpus CAN settle.
    assert score.blank_required == RECORDED["blank_required"], (
        f"cards required to be blank moved to {score.blank_required}"
    )
    assert score.role_unsettleable == RECORDED["role_unsettleable"], (
        f"cards whose title this corpus cannot settle moved to "
        f"{score.role_unsettleable}"
    )
    # EVERY CARD IS ACCOUNTED FOR, and this is the line the three pins above
    # cannot replace. Pinned integers say what was measured once; they go on
    # agreeing while a card moves from being GRADED to being skipped, because
    # both sides of that move are just numbers that were re-recorded together.
    #
    # The close is what makes a silent skip impossible: a card can only leave
    # one population by entering another, so a regression that stops grading N
    # cards has to say where they went. #536 documents the shape it catches —
    # a merge regression once took `role_missing` 213 -> 0 by LOWERING the
    # denominator, and every zero in this test read better afterwards.
    assert (
        score.roles_graded + score.blank_required + score.role_unsettleable
        == score.titles_graded
    ), (
        f"{score.titles_graded} cards were graded but only "
        f"{score.roles_graded + score.blank_required + score.role_unsettleable} "
        f"are in a title population — the rest are asserted by nothing"
    )
    assert score.role_invented == RECORDED["role_invented"], [
        f.detail for f in score.failures if f.mode == "ROLE-INVENTED"
    ][:5]
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
    replacing ``pipeline.role_from_message`` with a constant takes WRONG ROLE
    from 0 to every card the corpus can settle a role for — `roles_graded`,
    which is pinned in `RECORDED`. The earlier wording here claimed "2,376 over
    a 4,000-message slice"; `generate()` takes a seed and nothing else, there is
    no supported 4,000-message slice, and the mutation does not stop at 59%. An
    unreproducible number reads as evidence, so it is replaced by one whose
    recipe is in the sentence.
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


# ── the cards that must be blank ─────────────────────────────────────────────


def test_the_corpus_and_the_product_agree_on_what_a_status_is() -> None:
    """`_CARD_STATUSES` is written out in the generator, not imported from the code.

    That is deliberate — this corpus must not take its ground truth from what it
    grades — and the cost of writing it out is that the two can drift. This is
    the assertion that makes drift loud instead of silent.
    """
    from jobtracker.cloud import pipeline
    from jobtracker.database.models import APPLICATION_STATUSES
    from tests.corpus_independent.generate import _CARD_STATUSES

    # AGAINST THE CANONICAL VOCABULARY, not against `pipeline`'s two hand-written
    # tables. Comparing to those alone leaves the hop that actually matters
    # unguarded: adding a status to `APPLICATION_STATUSES` — the vocabulary the
    # board really shows — left this test GREEN, because both sides of the
    # comparison were downstream of the same omission.
    assert {s.lower() for s in _CARD_STATUSES} == {
        s.lower() for s in APPLICATION_STATUSES
    }, (
        "the corpus and the product's status vocabulary disagree; a status only "
        "one side knows is exactly the typo this set exists to make impossible"
    )
    # …and the two pipeline tables the scorer actually reads must cover it, or
    # `_overstates` resolves a real status through `.get(want, 0)` and ranks it
    # below every live card.
    assert _CARD_STATUSES <= (
        frozenset(pipeline._STATUS_RANK) | pipeline._TERMINAL_STATUSES
    ), "a status the board shows is unknown to the ranking the scorer uses"


def test_ground_truth_cannot_name_a_status_no_board_shows() -> None:
    """A wrong ``card_status`` was invisible rather than loud.

    ``_overstates`` resolves an unknown status through
    ``_STATUS_RANK.get(want, 0)``, which ranks it BELOW every live card — so
    every card silently reads as "ahead" of it. The ``_UPDATES`` offer entry
    said ``offer`` where boards store ``offered`` from the day it was written,
    and 425 assertions could only ever be false with nothing noticing.
    Restoring that one word moves ``card_overstates`` from 260 to 551, so
    correcting the value was never enough — the wrong value has to be
    impossible.
    """
    from datetime import datetime

    from tests.corpus_independent.generate import Case

    def build(status: str) -> Case:
        return Case(
            message_id="m1",
            thread_id=None,
            subject="s",
            sender="x@y.test",
            sender_name=None,
            body="b",
            delivered="b",
            received_at=datetime(2026, 1, 1),
            family="probe",
            expected_category="rejection",
            identity="northwind|Software Engineer",
            employer="northwind",
            card_status=status,
        )

    with pytest.raises(ValueError, match="not a status any board shows"):
        build("offer")  # the real typo, not an invented one

    # THE CONTROL: the correct spelling must still construct, or this guard is
    # satisfied by rejecting everything.
    assert build("offered").card_status == "offered"


def test_mail_that_names_no_role_must_leave_the_card_blank() -> None:
    """960 cards were skipped because "no role to grade" read as "nothing to assert".

    It is not nothing. A sentinel sub-key means the family's mail withholds the
    job title on purpose, so a blank card is the only correct card and any title
    is an invention. ``role_invented`` is in ``total`` because inventing a title
    is a lie, where ``role_missing`` is only a gap and stays out.

    TWO CASES THAT LOOK IDENTICAL TO A SCORER AND MEAN OPPOSITE THINGS: a
    req-id family also has no gradeable role, but there the corpus genuinely
    cannot settle the title, so its card must still be skipped. Both are
    asserted below; treating them alike is what left the 960 ungraded.
    """
    from datetime import datetime

    from tests.corpus_independent.generate import Case
    from tests.corpus_independent.harness import Replay

    def case(mid: str, family: str, identity: str) -> Case:
        return Case(
            message_id=mid,
            thread_id=None,
            subject="Thanks for applying",
            sender="no-reply@us.greenhouse-mail.io",
            sender_name=None,
            body="Thanks for applying. We will be in touch.",
            delivered="Thanks for applying. We will be in touch.",
            received_at=datetime(2026, 1, 1),
            family=family,
            expected_category="applied",
            identity=identity,
            employer="northwind",
        )

    anonymous = case("m1", "repeat-anonymous", "northwind|__apply0__")
    assert anonymous.names_no_role is True, "the sentinel was not recognised"
    assert anonymous.role_truth is None

    def scored(position: str):
        return score_board(
            Replay(
                groups=[("rowA", ["m1"])],
                reviewed=set(),
                dropped=set(),
                status={"rowA": "applied"},
                title={"rowA": ("Northwind", position)},
            ),
            [anonymous],
        )

    # THE MUTATION PROOF. On the real corpus this assertion passes only because
    # all 960 such cards really are blank — which is indistinguishable from a
    # counter that can never fire. A title the mail never named must move it.
    invented = scored("Chief Vibes Officer")
    assert invented.blank_required == 1
    assert invented.role_invented == 1, (
        "a card printed a job title for mail that names none and the score did "
        "not move — this counter cannot fail"
    )
    assert invented.total >= 1, "role_invented must reach `total`, not just the report"

    # …and a correct board must score clean, or the assertion above would be
    # satisfied by punishing every card.
    blank = scored("")
    assert blank.blank_required == 1
    assert blank.role_invented == 0 and blank.total == 0

    # The OTHER reason a role cannot be graded, which must still be skipped.
    req = case("m1", "req-id-same-title", "northwind|R-40080")
    assert req.names_no_role is False
    skipped = score_board(
        Replay(
            groups=[("rowA", ["m1"])],
            reviewed=set(),
            dropped=set(),
            status={"rowA": "applied"},
            title={"rowA": ("Northwind", "Chief Vibes Officer")},
        ),
        [req],
    )
    # THE DENOMINATOR FIRST. Two zeroes with nothing behind them is satisfied by
    # a card that was never graded at all — verified: pointing `mids` at an
    # unknown message, or dropping the `title` entry, makes both zeroes true
    # with titles_graded=0. That is the defect shape this whole file exists to
    # catch, and it had reappeared inside the test written to close it.
    assert skipped.titles_graded == 1, "the req-id card was not graded at all"
    assert skipped.blank_required == 0 and skipped.role_invented == 0


def test_the_readable_window_is_the_product_s_window() -> None:
    """The generator's idea of "what a message can be read from" must be the product's.

    ``_READABLE_CHARS`` decides which cards #533's derivation calls unreachable,
    and it is written out in ``generate.py`` rather than imported — deliberately,
    because a corpus that takes its ground truth from the code it grades proves
    nothing. The cost of writing a constant out is that it can drift from the
    thing it mirrors, so the drift is what this asserts, the same way
    `test_the_corpus_and_the_product_agree_on_what_a_status_is` does for
    statuses.

    If Gmail's cap moves and this does not, the derivation starts calling roles
    unreachable that the product can still read — which would convert real
    ROLE-MISSING defects into cards asserted BLANK, and the gate would go green
    on a product that got worse.
    """

    from jobtracker.cloud.gmail_client import _MAX_BODY_CHARS
    from tests.corpus_independent.generate import _READABLE_CHARS

    assert _READABLE_CHARS == _MAX_BODY_CHARS, (
        f"the corpus judges a role reachable within {_READABLE_CHARS} characters "
        f"of body and the product stores {_MAX_BODY_CHARS}"
    )


#: Identities whose title this corpus still asserts, after #533's derivation has
#: removed the ones no message spells. The DENOMINATOR for the test below: a
#: derivation that over-fired and deleted every role would satisfy the test's
#: main assertion perfectly, and this is the number that stops it.
RECORDED_ROLE_IDENTITIES = 8024


def test_ground_truth_never_asserts_a_title_no_message_spells(cases) -> None:
    """A role no message on the card ever spells is not ground truth, it is a wish.

    THE DEFECT (#533). The builder writes ``identity=f"{token}|{role}"`` for
    every case and draws the role from ``ROLES``. For the ``observed-*``
    families — transcriptions of real ATS wordings, plenty of which name no job
    at all, one of them saying only "your details have been added to our
    database" — that role appears nowhere in the mail. So the corpus asserted a
    title the product could not possibly know and scored the correct answer, a
    blank card, as a ROLE-MISSING miss.

    IT IS GROUND TRUTH THAT REWARDS GUESSING, which is why it is worth a test
    of its own rather than a re-recorded number. Driving ROLE-MISSING toward
    zero against it would require the extractor to invent a title for mail that
    names none — the mint-a-company defect (#512, #535) one field over, and on
    the filing path an invented role is an invented application identity.

    Asserted over the whole corpus rather than over a fixture: the derivation
    lives in ``generate()``, and a family added tomorrow gets it for free only
    if something checks the whole corpus. Removing ``_settle_role_reachability``
    fails this at 146 identities.
    """

    from tests.corpus_independent.generate import _readable_text

    by_identity: dict[str, list] = {}
    for case in cases:
        if case.identity is not None and case.role_truth is not None:
            by_identity.setdefault(case.identity, []).append(case)

    unspelled = [
        identity
        for identity, group in by_identity.items()
        if not any(
            " ".join(group[0].role_truth.split()).lower() in _readable_text(c)
            for c in group
        )
    ]
    assert not unspelled, (
        f"{len(unspelled)} card(s) are graded against a job title that appears "
        f"in no message on them, so the only way to satisfy the gate is to "
        f"invent one: {unspelled[:5]}"
    )
    # THE DENOMINATOR, because "no card is graded against an unspelled title" is
    # also true of a corpus that grades no card at all — and flipping every
    # identity to `names_no_role` would satisfy the assertion above perfectly.
    assert len(by_identity) == RECORDED_ROLE_IDENTITIES, (
        f"{len(by_identity)} identities still carry a role to grade against; "
        f"the assertion above is only worth this number"
    )



def test_a_role_the_mail_does_spell_survives_the_derivation() -> None:
    """The control for #533, and the half that makes it a fix rather than a mute.

    ``_settle_role_reachability`` is a rule that DELETES ground truth. A version
    of it that deleted all of it would satisfy every "no card is graded against
    an unspelled title" assertion in this file, and the corpus would grade
    nothing while reading green. So the two directions are asserted together
    here, on cases built by hand where the answer is not in doubt.

    Three shapes, because the third is the one that made the derivation live in
    ``generate()`` instead of ``Case.__post_init__``: a card whose FIRST message
    names no role and whose second does is a perfectly titled card, and judging
    either message alone gets it wrong.
    """

    from datetime import datetime

    from tests.corpus_independent.generate import Case, _settle_role_reachability

    def case(mid: str, ident: str, body: str, subject: str = "Update") -> Case:
        return Case(
            message_id=mid,
            thread_id=None,
            subject=subject,
            sender="no-reply@ashbyhq.com",
            sender_name=None,
            body=body,
            delivered=body,
            received_at=datetime(2026, 1, 1),
            family="hand-built",
            expected_category="applied",
            identity=ident,
            employer=ident.partition("|")[0],
        )

    spelled = case(
        "m1",
        "northwind|Backend Engineer",
        "Thank you for applying to the Backend Engineer position at Northwind.",
    )
    silent = case(
        "m2",
        "arcgrove|Data Engineer",
        "Your details have been added to our database. We will be in touch.",
    )
    # One card, two messages: the second names the job, the first does not.
    late_first = case("m3", "brightmoor|Platform Engineer", "Thanks for applying!")
    late_second = case(
        "m4",
        "brightmoor|Platform Engineer",
        "An update on your Platform Engineer application.",
    )

    corpus = [spelled, silent, late_first, late_second]
    assert all(c.role_truth is not None for c in corpus), "precondition"

    _settle_role_reachability(corpus)

    assert spelled.role_truth == "Backend Engineer" and not spelled.names_no_role, (
        "a role the mail spells out was deleted; the derivation is a mute, not a fix"
    )
    assert silent.role_truth is None and silent.names_no_role, (
        "a role no message spells is still being graded against"
    )
    assert late_first.role_truth == "Platform Engineer", (
        "the message that names no role was judged alone — reachability is a "
        "property of the CARD, and every message sharing an identity is on it"
    )
    assert not late_first.names_no_role and not late_second.names_no_role


def test_the_derivation_is_a_property_of_a_generated_corpus_not_of_a_case() -> None:
    """Where the derivation does NOT reach, said out loud so nobody relies on it.

    ``Case.__post_init__`` cannot run it — it sees one message and reachability
    is a property of a card — so a ``Case`` constructed directly keeps whatever
    ``role_truth`` its identity implies, unspelled or not. Several tests in this
    file depend on exactly that: the mutation probes build cases with
    ``body="b"`` and grade them against "Software Engineer".

    That is a real limit, not a bug, and the guard against it is that ground
    truth reaches the GATE only through ``generate()``. Asserted here so the
    limit is documented by something that fails if it changes.
    """

    from datetime import datetime

    from tests.corpus_independent.generate import Case

    bare = Case(
        message_id="m1",
        thread_id=None,
        subject="s",
        sender="x@y.test",
        sender_name=None,
        body="b",
        delivered="b",
        received_at=datetime(2026, 1, 1),
        family="hand-built",
        expected_category="applied",
        identity="northwind|Software Engineer",
        employer="northwind",
    )
    assert bare.role_truth == "Software Engineer"
    assert bare.names_no_role is False


def test_the_digest_covers_what_the_corpus_asserts_not_only_what_it_says(cases) -> None:
    """The determinism gate has to see a change to ground truth, and it did not.

    ``digest()`` hashed the MAIL — subject, body, delivered, identity, category —
    and stopped there. ``joins``, ``card_status``, ``role_truth`` and
    ``names_no_role`` are every bit as much the corpus: they are what the product
    is required to DO with that mail, and the whole file exists to state them. A
    rewrite of any of the four left ``CORPUS_DIGEST`` unmoved, so the one
    tripwire that says "this is not the same corpus, re-record it" could not see
    an edit to the half that decides pass from fail.

    Proved per field rather than in aggregate, because a digest that covered
    three of the four would satisfy any test that only changed one. Each field is
    perturbed on a single case out of 17,260 — a one-case change is the smallest
    thing the gate must not miss.
    """

    from dataclasses import fields as dataclass_fields

    from tests.corpus_independent.generate import digest

    base = digest(cases)
    victim = next(c for c in cases if c.card_status is not None)
    ident = next(c for c in cases if c.role_truth is not None)
    blank = next(c for c in cases if c.names_no_role)

    perturbations = {
        "card_status": (victim, "ghosted" if victim.card_status != "ghosted" else "applied"),
        "joins": (victim, "a-message-id-that-is-not-there"),
        "role_truth": (ident, "Chief Vibes Officer"),
        "names_no_role": (blank, False),
    }
    known = {f.name for f in dataclass_fields(cases[0])}
    for name, (case, value) in perturbations.items():
        assert name in known, f"{name} is no longer a field of Case"
        was = getattr(case, name)
        object.__setattr__(case, name, value)
        try:
            assert digest(cases) != base, (
                f"changing {name} on one case of {len(cases)} left the corpus "
                f"digest identical — the gate cannot see ground truth move"
            )
        finally:
            object.__setattr__(case, name, was)

    # …and the corpus is left exactly as it was found, or every test after this
    # one in the module is running against a different corpus.
    assert digest(cases) == base
