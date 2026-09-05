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

import re

import pytest

from jobtracker.cloud import pipeline
from tests.corpus_independent.generate import (
    _POST_NAME_RESOLVES,
    digest,
    generate,
)
from tests.corpus_independent.harness import (
    _ANSWERS,
    answer_the_queue,
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
#: c4b1e3b6c5a4b3b9 since #626: the corpus gained a family, so it gained mail.
#: 12ac85f9e15c0769 since #641, for the same reason — `anonymous-third-application`
#: is 180 more messages and 60 more employers.
CORPUS_DIGEST = "12ac85f9e15c0769"
CORPUS_SIZE = 18200

#: THE RECORDED RUN, in one place, because the README quotes it.
#:
#: ``scripts/readme_facts.py`` registers these and fails the build when the
#: README and this dict disagree, which is the whole reason they are a dict and
#: not literals inside the asserts. A published number that nothing recomputes
#: is a claim, and this repository has a ledger of those.
#: THE BOARD AFTER A PERSON ANSWERS THE QUEUE (#547), recorded separately from
#: `RECORDED` so that neither block moves the other. Every number above is the
#: board as the SYNC left it; every number here is the same board after every
#: held message has been answered with the category its mail carries.
#:
#: These are not aspirations. Several of them are defects the phase exists to
#: make visible, and they are pinned at what the product actually does so that a
#: change to it has to argue with a number.
RECORDED_AFTER_ANSWERING = {
    # THE HEADLINE, and the reason the phase was worth building: every one of
    # the 260 cards reading "Offered" for a withdrawn offer (#417) corrects
    # itself the moment a person answers the queue. Nothing in this corpus
    # could say that before, because it wrote the queue and never read it.
    "card_overstates": 0,
    # AND ANSWERING BREAKS THINGS, which is the other half of measuring it.
    # MERGE is the failure `test_the_board_is_clean` calls strictly worse than
    # any other: it discards a record silently. All 19 are the family
    # `update-picks-between-two` — an employer holding two applications and an
    # update that must choose — and all 19 misfile, because the queue's card
    # picker pre-selects "not one of these" (#554) and rule 4 then resolves by
    # age. 19 of 19 is the failure rate of that SHAPE, not of the queue.
    "merges": 19,
    # 19 of these are the same answers scattering the application they were
    # taken from. The other 39 are `observed-pending` and are a separate
    # defect: answering "pending application" mints a second card for an
    # application that already has one, with no sibling choice involved (#555).
    "splits": 58,
    # 9569 -> 10149 (#626): the 580 cards the new family puts on the board are
    # all there before the queue is answered, and answering mints none of its
    # own — `minted_a_card` below is unmoved at 421.
    # 10149 -> 10329 (#641): the same +180, all of it on the board before
    # the queue is answered. Answering mints none of it — `minted_a_card`
    # is unmoved at 421 — because none of the family's mail is ever held:
    # it produces no updates and nothing uncertain.
    "cards": 10329,
    "update_opened_a_card": 19,
    "noise_on_card": 0,
    # 62 BEFORE, 75 AFTER — and the interesting number is the one that is not
    # here. On the tree immediately before #548 the after-answering figure read
    # 106. #548 recovers exactly 26 of them, which is the figure #546 claimed
    # and which no instrument could check until this phase existed. The residual
    # +13 is blank cards minted by answers that landed nowhere existing, and it
    # is unchanged: 80 - 67 and 75 - 62 are the same 13.
    #
    # BOTH ENDS MOVED BY 5 TOGETHER (#553), which is the check that this is one
    # improvement and not two. The lead-segment role reader fills five cards
    # whose title was spelled out in their subject all along, so it fills them
    # before the queue is answered (67 -> 62) and they are still filled after
    # (80 -> 75). A change that moved only one end would mean the answering path
    # and the sync path disagree about the same five messages, which is the
    # shape of a bug rather than a fix. Every other counter on this score is
    # exactly where it was: cards 9569, splits 58, merges 19, wrong_review 150,
    # update_opened_a_card 19.
    #
    # 75 -> 71 WITH #458, AND THIS END MOVED ALONE, which is the opposite of
    # the paragraph above and is right here. The eleven recovered messages are
    # REJECTIONS that reach the queue; the sync files nothing for them either
    # way, so the before-answering figure stays where #451 left it, at 63.
    # Four of the eleven are answered onto a card that had no title, and
    # answering reads the role off the message. The other seven land on cards
    # that already had one. That split is DERIVED, not inspected: `cards`
    # (9569) and `minted_a_card` (421) are both unchanged, so all eleven filed
    # onto cards that already existed, and the only input that differs between
    # the two readings is those eleven answers.
    "role_missing": 71,
    # ZERO AGAINST A DENOMINATOR THAT HAS TO BE SAID OUT LOUD. #548 refuses to
    # stamp a title on a blind landing, and 421 of the 2,341 filed answers
    # landed where the employer held several cards — so those 421 are excluded
    # from this counter BY CONSTRUCTION and it can only be non-zero on the
    # 1,920 single-card landings and the 317 mints. Read as "no answer that was
    # allowed to name a card named it wrongly", not as "answering never
    # mis-titles". #536 is the standing note on zeros that cannot be non-zero.
    "role_wrong": 0,
    # The three title populations still close after answering:
    # 8744 + 1166 + 400 == 10310.
    #
    # 8044 -> 8624 and 9550 -> 10130 (#626), both by the same 580. Every card the
    # new family adds carries a title this corpus can settle, so the whole of the
    # move lands in `roles_graded` and neither of the other two populations moves.
    # +120 / +60 / +180 (#641), the same three moves as before answering, so
    # the populations still close after the phase: 8744 + 1166 + 400 == 10310.
    "roles_graded": 8744,
    "blank_required": 1166,
    "role_unsettleable": 400,
    "titles_graded": 10310,
    # `score_board`'s `wrong_review`, READ UNDER A NAME THAT IS TRUE HERE. That
    # counter means "the product guessed instead of asking". After the phase the
    # product DID ask and was answered, so 150 is not 150 failures — it is 150
    # cases that were correctly held and are now correctly filed. Recorded under
    # its own key so the sync-phase number (0, asserted above) keeps its meaning.
    # 150 -> 310 (#626). +160 is exactly the family's refusals: role-less
    # updates at two-application employers, correctly held by the sync and
    # correctly filed once a person answers. Read as "160 more cases that were
    # right to be held", not as 160 failures — the key exists for that reason.
    "held_cases_now_filed": 310,
}

#: What answering DOES, per call — the outcomes the board cannot show.
RECORDED_ANSWERS = {
    # 2701 -> 2862 (#451). +161 held for a person, and the two counters move
    # together because everything held is answered. This is the queue side of
    # the trade recorded on `auto_filed_wrong`: 107 messages left the
    # auto-filed bucket and 54 left the DROPPED counter, which is 161.
    #
    # 2862 -> 2873 WITH #458, and the eleven are exactly the eleven that used
    # to be LOST: a relayed `follow_up` now reaches the queue instead of the
    # terminal drop. They travel together through the two counters below —
    # `filed_on_an_existing_card` +11 and `landed_where_one_card_existed` +11
    # — and nothing else on this score moves. A queue that grew without those
    # two moving with it would mean the fix had found messages it cannot
    # settle.
    # 2873 -> 3033 (#626): +160, the new family's refusals, and the two move
    # together because everything held is answered.
    "queued": 3033,
    "answered": 3033,
    # THE GUARD THAT NEVER FIRES, said plainly rather than left to read as
    # coverage. `_settle_thread_siblings` can remove a queue entry when a
    # sibling is answered, and `classify_review_item` has no `is_reviewed`
    # guard, so the phase re-asks the queue predicate before every answer. On
    # this corpus the answer is always yes. The re-check is correct and is
    # currently exercised by nothing; a corpus family whose thread siblings
    # share an identity would exercise it.
    "settled_by_a_prior_answer": 0,
    # The branch that keeps the row in the queue and returns quietly. Measured
    # independently before these buckets were designed: 360 of the 17,260 cases
    # resolve no employer from sender + subject — all 200 `bare-relay`, and 160
    # of 320 `verdict-past-the-body-cap`. Every one of them is here.
    "refused_needs_employer": 360,
    # 2024 -> 2081 (#451), 2081 -> 2092 (#458): the eleven relayed follow-ups
    # #458 recovered are all answered onto a card their employer already had.
    # None minted one, which is why `minted_a_card` below does not move.
    # 2092 -> 2252 (#626). All 160 land on a card their employer already had —
    # which is what answering "this is a rejection of that application" does —
    # so `minted_a_card` does not move.
    "filed_on_an_existing_card": 2252,
    # 317 -> 421 (#451), and +104 is EXACTLY the number of cards the board no
    # longer produces on its own (`RECORDED["cards"]` 9252 -> 9148). The cards
    # are not lost; a person mints them by answering the question the product
    # now asks instead of guessing. `RECORDED_AFTER_ANSWERING["cards"]` is
    # unchanged at 9569, which is the same fact stated as a total.
    "minted_a_card": 421,
    "not_a_lifecycle_answer": 0,
    # HOW MUCH CHOICE THERE WAS. A landing at an employer holding one live card
    # is right by cardinality, not by understanding; folding the two together
    # would hide rule 4's coin toss inside a healthy headline.
    #
    # 1920/421 -> 1918/423 with #532, and the total is unchanged at 2341, as are
    # `filed_on_an_existing_card` and `minted_a_card`. Two answers moved from
    # "one card existed" to "several did" and nothing was gained or lost.
    #
    # THE CAUSE IS NOT A CHANGE OF GROUPING. Measured over all 17,260 cases:
    # `resolve_employer` returns the same TOKEN for every one of them before and
    # after — 0 token changes, 2,484 display-only changes. What moved is the
    # harness's sibling query, which compares `Application.company` as an exact
    # STRING (see `harness.py`, "CARDINALITY READ OFF THE BOARD"). The subject
    # path used to truncate "Alderpoint Labs" to "Alderpoint" while the sender
    # display-name path, which never ran `_clean_company_display`, kept it whole
    # — so one employer sat on the board under two spellings and its own cards
    # did not recognise each other as siblings. Now they do:
    #
    #     tokens with more than one display spelling   526 -> 150
    #     distinct display spellings in total         9260 -> 8916
    #     distinct employer tokens                    8676 -> 8676
    #
    # 376 tokens collapsed to a single spelling and NONE gained one. So these
    # two answers always had a choice; the board just could not see it.
    # 1918 -> 2079 (#451). `landed_where_several_did` does NOT move, so all
    # 161 extra answers landed at an employer holding exactly one live card
    # — right by cardinality, and keeping the two apart is what stops that
    # reading as understanding.
    #
    # 2079 -> 2090 (#458): all eleven recovered messages land at an employer
    # holding exactly one live card, so none of them exercises rule 4's choice
    # and `landed_where_several_did` is unchanged at 423.
    "landed_where_one_card_existed": 2090,
    # 423 -> 583 (#626), and this is the counter that says the family is built
    # correctly rather than merely large. All 160 refusals land at an employer
    # holding SEVERAL cards; `landed_where_one_card_existed` is unmoved at
    # 2090. A refusal at a single-card employer would have landed in the other
    # bucket and proved nothing — see `_post_name_refusal`.
    "landed_where_several_did": 583,
}

#: WHAT THE SYNCS REPORTED, summed over the 240 day-batches (#624).
#:
#: These five did not exist until `replay` began routing each batch through
#: `sync_gmail_pipeline_additive` whole. Every number above describes the BOARD —
#: what is there when the syncing stops. These describe the SYNCS: what each one
#: said it did. A rebuild and a steady accumulation can leave an identical board,
#: so the two are not restatements of each other.
#:
#: Two of them agree with a number recorded elsewhere, and the agreement is the
#: assertion rather than a duplicate:
#:
#:   created == RECORDED["cards"]           every row on the board was minted by
#:                                          a sync. It would DISAGREE if the
#:                                          per-batch catch-up minted one (it
#:                                          cannot here: `reconcile_orphaned_
#:                                          classifications` selects on
#:                                          `user_corrected` or `is_reviewed`,
#:                                          and the sync path writes neither), or
#:                                          if any row were dismissed.
#:   needs_review == RECORDED_ANSWERS["queued"]
#:                                          every item a sync surfaced was still
#:                                          in the queue when a person got to it.
#:                                          It would disagree if a later batch's
#:                                          rollup filed one.
#:
#: `purged` is `len(MergeResult.removed)`: rows `_dismiss_rows_left_without_mail`
#: took off the board. It is 0, and it is now REACHED on every batch rather than
#: never — the counter says the pass runs and removes nothing, which is not what
#: an absent pass says.
RECORDED_SYNC = {
    "syncs": 240,
    # created 9148 -> 9728 and needs_review 2873 -> 3033 (#626), which is the same
    # +580 / +160 the board and the queue report; the two agreements above still
    # hold. `updated` 3999 -> 4019 is the smallest of the family's numbers and the
    # most specific: 20 messages — one per group — are the both-placements pair's
    # ROLE-side acknowledgement landing on the card its TAIL-side twin opened. If
    # that ever mints instead of updating, this is the counter that says so before
    # `splits` does.
    # created 9728 -> 9908 (#641), the same +180 the board reports, and
    # `updated` does NOT move. The third confirmation used to be an UPDATE
    # to a row that already existed and is now a CREATION; if a later change
    # ever trades one for the other, these two counters say so together.
    "created": 9908,
    "updated": 4019,
    "purged": 0,
    "needs_review": 3033,
}

#: How many spellings the resolver gives one employer, over the whole corpus.
#:
#: THE DIRECTION IS THE POINT and it is one-way: neither number may RISE. They
#: measure the defect #532 was filed for — a card reading a shorter employer
#: name than the mail it came from — at its source rather than at the board, so
#: they move the moment a resolution path starts disagreeing with the others,
#: without waiting for the ten-minute replay to notice.
#:
#: 150 is not zero and is not a defect. MEASURED, not guessed: all 150 are in
#: the `employer-spelling` family and no other family contributes one. That
#: family exists to send the same employer three ways — "ALDERBURYWATCH
#: SYSTEMS", "Alderburywatch" and "Alderburywatch Systems" — so a token holding
#: several spellings there is the family doing its job. Anything outside it is
#: a resolution path disagreeing with the others, which is #532 returning.
#:
#: Both figures are deterministic: `generate()` is seeded and `resolve_employer`
#: reads nothing date-derived, so this gate cannot red on a calendar.
RECORDED_EMPLOYER_SPELLINGS = {
    # +420 on both (#626), which is the family's employer count exactly: it spells
    # every employer ONE way — lead segment, echo, sender display — so it adds a
    # token and a display apiece and NOT a second spelling of either.
    # +60 on both (#641), which is the new family's employer count exactly:
    # ONE sender for all three of its messages, so it adds a token and a
    # display apiece and never a second spelling of either.
    # -43 on both (#733), and the two moving together by the SAME amount is the
    # shape of the change: the person-as-employer guard refuses 43 bare
    # Title-Case display names outright, so each loses one token and its one
    # display. Nothing was re-keyed and nothing gained a second spelling —
    # `tokens_with_several_spellings` below is unmoved at 150, which is the
    # assertion that says so. All 43 sit in the corpus's `nowhere` bucket
    # (`must_be_addressed=False`), which is why the board counters do not move
    # at all: cards 9908 before and after, company_drift 0, splits 0, merges 0.
    "tokens": 9113,
    "distinct_displays": 9353,
    # UNMOVED, and that is the assertion. 150 is documented above as entirely the
    # `employer-spelling` family; a family that added one would be #532 returning.
    "tokens_with_several_spellings": 150,
}

RECORDED = {
#
#: ── EVERY NUMBER BELOW THAT CARRIES A "626" NOTE MOVED WITH THE FAMILY
#:    `concatenated-post-name` (#626) ──────────────────────────────────────
#:
#: 760 messages, 420 employers, appended LAST so nothing before it re-draws.
#: 240 acknowledgements whose job title exists ONLY in the subject's trailing
#: segment, 320 sibling confirmations that give those refusals somewhere to be
#: ambiguous, 160 role-less updates the reader declines, and 40 messages of the
#: both-placements pair. See the family's docstring in `generate.py`.
    "size": 18200,
    # DISTINCT FAMILY LABELS in the generated corpus, which is 37 and not the
    # 35 generators in ``_FAMILIES``: two generators emit a second label of
    # their own (``hostile-zero-width``, ``hostile-homoglyph``). The README and
    # the System Card both print a family count and both had drifted — 32 and
    # 24 against a real 35 — because nothing recomputed it. Now something does.
    "families": 39,
    # DISTINCT EMPLOYER TOKENS, and this entry was decoration until 2026-08-23.
    # It read 9,180 and `readme_facts.py` published it to the README and the
    # Booklet, but no test recomputed it and it matched NO measure of the
    # corpus: employer tokens were 7,900, sender names 8,710, identities 9,410.
    # A published number nothing recomputes is a claim, which is the sentence
    # at the top of this dict, so it is now asserted below like the rest.
    # 8440 -> 8500 (#641): 60 employers, and they are the first in this corpus
    # to carry BOTH a named identity and an anonymous one. Before the family
    # there were ZERO such employers out of 8,440, which is why a fix to #641
    # moved no number here and the bug could have been reinstated against a
    # green board.
    "companies": 8500,
    # ── #451 MOVED EVERY NUMBER BELOW THAT CARRIES A "451" NOTE ─────────────
    #
    # Two changes in one commit: the reference pattern
    # `application.{0,20}(for|to).{0,40}(position|role|job)` demoted from
    # `strong` to `weak` for `applied`, and ties broken by what a category
    # CLAIMS (a report of a later stage outranks an assertion that an
    # application exists) instead of by `EmailCategory` declaration order.
    # Baseline measured on 53f191b, the merge-base, at this seed.
    # 15886 -> 16030 (#451). +144, and 50 of them are the `observed-pending`
    # family alone: "please verify your email before we can review your
    # application" was read as a confirmation because the reference pattern
    # gave `applied` a report's worth of evidence. They are CORRECT now, not
    # merely abstained — that family's `correct` goes 120 -> 170.
    # 16030 -> 16790 (#626): +760, the whole of the new family. `wrong` and
    # `abstained` do not move at all, so every one of its messages is
    # classified correctly — which is expected and is not what it measures.
    # Its subject shape is an IDENTITY problem, not a classification one.
    # 16790 -> 16970 (#641): +180, the whole of the new family, which every
    # rule reads correctly. `wrong` and `abstained` do not move, so the family
    # adds no classifier defect and its board numbers are about identity alone.
    "correct": 16970,
    # 361 -> 304 (#451).
    "wrong": 304,
    # 1013 -> 926 (#451). It FELL, which is not what a demotion is supposed
    # to do and is worth saying plainly: the tie-break half moves messages
    # OUT of abstention by giving a tied report the verdict, and that more
    # than covers what the demotion pushed in.
    "abstained": 926,
    # The number that matters more than `wrong`: how many wrong verdicts are
    # stated to the user as fact rather than held for them to settle.
    #
    # 72 ENCODES KNOWN, OPEN DEFECTS and is not a target. The decomposition
    # below accounts for 16 of the 72 and the remaining 56 are UNATTRIBUTED —
    # said plainly, because this comment used to name two families under a
    # headline of 116 and read as though it explained the whole number. 14 are
    # #455:
    # a rejection whose full body says "we have decided not to move forward" is
    # scored `applied` at exactly the auto-file gate because the JOB TITLE
    # contains the word "Career", so the title — reference text, naming which
    # application — supplies the points that decide what happened to it. The
    # other 2 are `ats-relay-noise` scoring a profile-completion nudge as job
    # mail. The number is pinned so a fix MOVES it; nothing here is blessed by
    # being pinned. See #455 and #451.
    # 72 -> 0 (#451), and this is the headline of that change: the number
    # this repository calls the one that matters more than `wrong` — a
    # verdict stated to the user as fact without anyone being asked.
    #
    # ZERO IS NOT "ELIMINATED", and the difference is measurable. At the two
    # other seeds this file re-samples it reads 0 and 1 (from 72 and 82). So
    # the pinned 0 is this seed's value, not a proof that no wording can
    # still reach the gate wrongly. Nothing here is blessed by being pinned.
    #
    # WHAT IT COST, because it was not free. `auto_filed` goes 13824 ->
    # 13717, so 107 messages left the auto-filed bucket: the 72 wrong ones
    # and 35 CORRECT ones, which now wait in the review queue instead of
    # arriving on the board by themselves. That trade was taken
    # deliberately — a product whose pitch is that it can be trusted with a
    # job search should prefer asking to guessing — and it is recorded here
    # rather than left for someone to rediscover from `cards`.
    "auto_filed_wrong": 0,
    # 9252 -> 9148 (#451). 104 applications that used to appear on the board
    # by themselves now wait for the user. Fully accounted for and nothing
    # became unreachable: `lost` does not move, `dropped` goes 54 -> 0, and
    # `update_held` rises 631 -> 685. The messages moved from a card the
    # product guessed at to a question it asks. THE STATED COST OF #451.
    # 9148 -> 9728 (#626): +580, the family's own applications — 240 titled out
    # of the trailing segment, 320 siblings, 20 both-placements pairs. Its 160
    # refusals mint nothing, which is the point of them.
    # 9728 -> 9908 (#641): +180, the whole of the new family — two named
    # applications and the anonymous third one that used to fold onto the
    # older of them. Before the fix this read 9728 WITH the family present,
    # which is the measurement the family exists to make.
    "cards": 9908,
    # Mail about a real application that the product did nothing with. Two
    # numbers because both are unaddressed and only one is invisible; see #447.
    #
    # LOST IS 0, AND THE LAST 11 WERE NOT WHAT #458 SAID THEY WERE. It read 11
    # here — 66 when the observed families first landed, 8 after `your
    # assessment|interview` completed the reference category, 11 after #466 —
    # and the issue described all of them as scoring `other` at 0.50 with no
    # text that refers to an application. Measured instead of read, every one
    # of the 11 scored `follow_up` at 0.70: their subjects carry the SENDER'S
    # word "Follow-Up" and their verdict sentence sits one character past the
    # snippet cut, so the rejection veto never fires. `follow_up` is excluded
    # from filing, from the queue AND from `DroppedVerdict`, all three on the
    # premise that it is the reader's own chasing mail — which is false for a
    # message an ATS relayed. That is #458, and the fix is a sender-and-
    # category clause in `collect_review_items`, not a wording: see
    # `tests/test_relayed_follow_up_is_not_your_own.py`.
    #
    # The 11 were also the ONLY `follow_up` verdicts in the whole corpus, and
    # every one of them is truly a `rejection`. So this corpus can say nothing
    # about a correct `follow_up`, and a later change to how `follow_up` is
    # DETECTED cannot be graded here.
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
    "lost": 0,
    # 54 -> 0 (#451). The whole `update-from-another-domain` family leaves
    # "counted by the product but on no screen" and enters the queue.
    "dropped": 0,
    # ── and the four numbers that make those two mean something (#624) ───────
    #
    # `lost` and `dropped` are LEFTOVERS: what is neither on a card nor in the
    # queue. A leftover has no denominator, so a regression that stopped
    # GRADING n messages would take both to zero and read as a perfect board —
    # the shape that took `role_missing` from 213 to 0 while breaking the board
    # (#536). The three populations below plus those two are asserted to close
    # against `must_be_addressed`, which the test counts from `cases` and not
    # from any counter the scorer increments.
    # +600 / +160 (#626), and they close: 760 messages, 600 on a card and 160
    # in the queue, with `lost` and `dropped` still 0.
    # 13807 -> 13987 (#641): +180. All three of each group land on a card,
    # so the queue side is unmoved and the closure below still holds.
    "addressed_on_a_card": 13987,
    "addressed_in_the_queue": 2833,
    # THE ADDITIVE PERSIST'S OWN OUTCOME, and it is zero. `replay` calls
    # `_persist_review_items_additive` since #624, so an arriving item can now
    # be refused a row because the sync already settled its (thread,
    # application). Measured at this seed: 2,873 refs offered, 2,873 persisted,
    # 0 dropped. Not for want of running — the settled query returns 602 rows
    # across 62 of the 240 day-batches — but no arriving item's
    # `review_dedup_key` collides with one of theirs. The `is_reviewed` arm
    # cannot fire at all during a replay: nothing on the sync path writes that
    # flag, and 0 rows carry it when the replay ends.
    #
    # So this is a zero that cannot currently be non-zero, said plainly rather
    # than left to read as coverage (#536). It is pinned because it is what
    # catches the suppression the day a family produces a queued message
    # sharing a thread AND an identity with mail already on a card — which is
    # #614's half of the work, not this one's.
    "suppressed_as_settled": 0,
    # The population the five close against. Pinned as well as computed, so a
    # corpus that quietly stopped requiring mail to be addressed is loud.
    # 16640 -> 16820 (#641): every message of the new family is about a
    # real application, so all 180 must reach a card or the queue.
    "must_be_addressed": 16820,
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
    # 631 -> 685 (#451). +54, which is exactly the `dropped` family above:
    # those updates are now ASKED ABOUT rather than counted and discarded.
    "update_held": 685,
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
    # 9252 -> 9148 (#451): the denominator follows `cards` exactly.
    # 9148 -> 9728 (#626): the denominator follows `cards` exactly, as ever.
    # 9728 -> 9908 (#641): the denominator follows `cards` exactly, as ever.
    "titles_graded": 9908,
    # Smaller, because a card whose ground truth keys on a requisition id, or
    # whose mail names no job at all, has a title this corpus either cannot
    # settle or must assert BLANK. See ``Case.role_truth``.
    #
    # 7892 -> 7746 with #533: 146 identities were carrying a role drawn from the
    # invented pool that appears in NO message on the card. They move to
    # `blank_required`, which is a stronger assertion than the grading they left.
    # 7746 -> 7642 (#451), following `cards` for the same reason.
    # 7642 -> 8222 (#626): +580, the same 580, and NONE of it lands in
    # `blank_required` or `role_unsettleable` — every card the family adds has
    # a title spelled in its own mail.
    # 8222 -> 8342 (#641): +120, the family's two NAMED applications per
    # group. Its anonymous third lands in `blank_required` below, so the
    # three populations still close: 8342 + 1166 + 400 == 9908.
    "roles_graded": 8342,
    # The card names an employer nobody applied to. This is what a user would
    # call hallucinating, and the live filing path can do it: while fixing #512
    # the subject "Senior Software Engineer Interview | <name>" resolved to a
    # company of that name. No corpus family produces that shape yet — #487's
    # third condition, and the reason the mutation probe below exists.
    "company_wrong": 0,
    # The card names a job nobody applied for.
    "role_wrong": 0,
    # Same employer, differently spelled: "Arcgrove" against "Arcgrove
    # Systems". Reported, and OUT of ``total`` — it is a cosmetic variance,
    # not a wrong record.
    #
    # 1420 -> 0 with #532. The cause was never the leading-word grouping this
    # comment used to blame: ``_clean_company_display`` ran ``_CORP_TAIL`` as an
    # UNANCHORED substitution, so "Labs" and "Systems" were deleted from the
    # display of every employer that had one. Grouping never needed that —
    # ``matches_company_token`` collapses on the leading word — so removing it
    # cost nothing and returned the second half of 1,420 card titles.
    #
    # A RECORDED ZERO IS THE SHAPE THIS REPOSITORY KEEPS SHIPPING BADLY, so the
    # thing that makes this one honest is stated here rather than assumed: the
    # probe below (`a deliberately drifted board reports drift`) feeds the same
    # grader a board whose companies are spelled short and requires it to report
    # 250. This zero is a measurement that could have been non-zero.
    "company_drift": 0,
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
    # The 67 that remain are the product's, and they are not one defect.
    # Measured against the replay rather than reasoned about — a first reading
    # of them was wrong, and the mechanism below is what the board actually did:
    #
    #   * for ALL 67, no message ON the card yields a role from
    #     `role_from_message`. There is no card whose title was read and then
    #     dropped.
    # The partition below is COMPLETE — 26 + 15 + 26 = 67 — and it is stated
    # that way on purpose. An earlier version of this comment accounted for 43
    # of the 67 and left 24 with no mechanism, which reads as an explanation and
    # is a gap.
    #
    #   * 26 have a message that DOES yield the role, and it is in the REVIEW
    #     QUEUE, so the card never saw it. Holding a message for a human costs
    #     the card its job title, and answering the review item does not repair
    #     it: `classify_review_item` extracts the role and writes it only on the
    #     branch that MINTS a row, never on the branch that resolves onto the
    #     existing one. observed-rejection 24, observed-assessment 2. See #546.
    #   * 26 also have a message off the card, and that message names no role
    #     either, so nothing was lost by its absence.
    #   * 15 hold every message of their identity and the reader reads none of
    #     them.
    #
    # Cutting the same 67 a second way: 17 have the role spelled in the SUBJECT
    # of a message ON the card and nothing reads it. That is #485, and it is the
    # only part of this number a new pattern can close. The two cuts overlap and
    # neither is a sub-total of the other.
    #
    # "ON THE CARD" IS LOAD-BEARING IN THAT SENTENCE, not filler. Counted over
    # the card's own messages the answer is 17; counted over the identity's
    # messages minus the reviewed ones it is 21. Both describe something real
    # and only the first describes what a user would see, because a message in
    # the queue is not on the card. A reader who reproduces 21 has not found a
    # discrepancy, they have used the other definition.
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
    #
    # 67 -> 62 (#553). Five cards whose job title was spelled out in the subject
    # all along, in the segment the employer was already being read from:
    # "<Employer> Follow-Up for <Role> | <Candidate>". The employer half of that
    # shape was taught in #512/#525; the role half sat unread on the same
    # message, in the same request, and `identity_parts` returning (None, None)
    # is what sent the resolver into `_pick_application`'s rule 4 — so it cost a
    # title AND downgraded the filing decision.
    #
    # THE SAME READING OF THIS NUMBER APPLIES, and it is the reason the first
    # attempt was rejected rather than recorded. That draft bounded the segment
    # with `_SEGMENT_DELIMITER`, which accepts a spaced dash — and two of this
    # corpus's own job titles carry one, so they were truncated. It reached
    # role_missing 62 as well, and it was a REGRESSION: `splits` went 0 -> 1,
    # `role_wrong` 0 -> 1, `cards` and `titles_graded` +1, because a truncated
    # title minted a rival card for an application already tracked. Five filled
    # blanks do not pay for one destroyed identity.
    #
    # What makes THIS 62 a safe move is the same close the paragraph above
    # describes: `splits` 0, `merges` 0, `role_wrong` 0, `cards` 9252 and
    # `roles_graded` 7746 are all exactly where they were, so nothing moved
    # except five cards inside one population. Measured across all 17,260 cases,
    # the reader fires on 40 subjects and matches ground truth on 40 of 40.
    # 62 -> 63 (#451): one more card whose ground truth names a role and
    # whose title is blank. An absence, not a lie, and out of `total`.
    # UNMOVED AT 63 THROUGH #626, and that is the family's headline. It adds
    # 240 cards whose job title exists in ONE place — the subject's trailing
    # segment — plus 20 more from the both-placements pair, and every one of
    # the 260 is titled. Break `_role_from_trailing_segment` and this number
    # goes to 343 and `splits` to 20; measured under a stubbed reader, not
    # assumed. See `test_this_corpus_reaches_the_trailing_segment_reader`.
    "role_missing": 63,
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
    #
    # 1106 -> 1166 (#641): the new family's 60 anonymous acknowledgements. Each
    # must produce a BLANK card, and `role_invented` holding at 0 is what says
    # the cards the fix now mints did not acquire a title from anywhere.
    "blank_required": 1166,
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
            32,
            "39 -> 32 with #451: seven of these were a rejection tying `applied` "
            "on a reference to the application it rejects, and enum order gave "
            "the tie to `applied`. The rest are the original defect, unchanged. "
            "REAL rejection wordings, half of them delivered as Gmail's snippet "
            "because that is what production receives when no body part can be "
            "extracted. Measured: these six wordings score 6/6 on the full body "
            "and 2/6 on the snippet. None of them leads with its verdict. This "
            "is the honest size of the truncation problem, on text the author "
            "of `rules.py` did not write.",
        ),
        (
            "observed-pending",
            0,
            "50 -> 0 with #451, and they became CORRECT rather than merely "
            "abstaining: this family's `correct` goes 120 -> 170 while its "
            "`abstained` does not move. `pending_application` is a category "
            "that REPORTS on an application ('please verify your email before "
            "we can review your application' is an outstanding step in one that "
            "exists), so it was losing to `applied` on the reference pattern's "
            "+3 and then on the enum-order tie-break. Both halves of #451 were "
            "needed and neither alone would have done it. "
            ""
            "EXACT AND NOT A BAND, which is a real change from what stood here: "
            "it was 50/51/55 across the three seeds because which of two real "
            "wordings a case drew decided whether the defect fired. It is 0 at "
            "all three now, because the cause was removed rather than a score "
            "shifted — the same reason `rejection-past-the-snippet` is exact. "
            ""
            "The history, kept because the trade it records still stands: "
            "#493. This was 0, closed by `(verify|confirm) your e.?mail`, and "
            "the pattern was DELETED — so these 50 came back, deliberately, "
            "and this number was the price. They returned as "
            "`applied` 0.75, which is UNDER the auto-file "
            "gate, so they were held for a person as a wrong SUGGESTION. They "
            "did not reach the board. "
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
    # is seeded, and the defect fires on one or the other.
    #
    # WAS 36..44, ON MEASUREMENTS OF 39/37/42. #451 took it to 32/20/28 — the
    # cases it removed are the ones where a rejection TIED `applied` on a
    # reference to the application it rejects. The band is re-measured with
    # slack on both sides rather than clamped to the new min and max: the width
    # here is a property of which title each case draws, and a band pinned to a
    # passing measurement reds on the next seed for no reason.
    # A CEILING AND NOT A BAND, unlike the version this replaces. A floor under
    # a defect count reds when somebody FIXES it — the inverted-gate shape this
    # repository keeps shipping — and the `auto_filed_wrong` ceiling twenty
    # lines below had its floor removed in this same commit for that reason.
    # One convention, not two.
    obs_rej = score.by_family["observed-rejection"]["wrong"]
    assert obs_rej <= 38, (
        f"{obs_rej} real rejections stated as fact at this seed, above the "
        "measured ceiling of 38 (20/28/32 at the three seeds). These are "
        "transcribed wordings, so a move here is the product changing, never "
        "the corpus."
    )
    # BACK TO EXACTLY ZERO, AT EVERY SEED, and the history is why that is
    # worth a sentence rather than a number. It was a band of 55..66, then 0
    # when `(verify|confirm) your e.?mail` closed it, then a band of 44..61
    # when #493 deleted that pattern as too broad. It is 0/0/0 now for a third
    # reason, and the only one that is about the message: `pending_application`
    # REPORTS on an application, so #451 stopped a reference pattern outscoring
    # it and stopped enum order breaking the tie when it did not.
    #
    # EXACT rather than banded, deliberately. A band was honest while the
    # trigger was "which of two real wordings a case drew"; the cause is gone
    # now, not the score shifted, so the width would be slack nobody measured.
    obs_pend = score.by_family["observed-pending"]["wrong"]
    assert obs_pend == 0, (
        f"{obs_pend} real action-required messages read as confirmations at "
        "this seed. This is 0 at every seed since #451, and it is EXACT rather "
        "than a band because the fix removed a cause rather than shifting a "
        "score."
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
    # 115..119 BEFORE #459, 100..102 AFTER, 70..84 once #466 put realistic job
    # titles in the corpus, and 0..1 since #451. The #459 drop was the point of
    # that fix — 17 real "please verify your email" messages per seed were
    # auto-filed as fresh confirmations. The #466 drop was NOT a fix: every case
    # re-drew its title and several patterns stop matching when the title is
    # long, so mail that used to be confidently wrong now abstains — fewer wrong
    # verdicts stated as fact, reached by understanding less.
    #
    # #451 IS A FIX, and it is the difference between the two: the reference
    # pattern was giving `applied` a report's worth of evidence on every
    # category's mail, and it is the evidence that carried those verdicts over
    # the gate. Measured 72 / 72 / 82 before and 0 / 0 / 1 after.
    #
    # THE ONE IS NOT NOISE AND IS NOT ROUNDED AWAY. `auto_filed_wrong` is pinned
    # at exactly 0 for the recorded seed elsewhere in this file; a re-sample
    # still produces one. So the honest reading is "this defect no longer has a
    # population", not "it is impossible". The ceiling carries slack for the
    # same reason every band here does — the width is which title a case drew.
    assert score.auto_filed_wrong <= 3, (
        f"{score.auto_filed_wrong} wrong verdict(s) were stated as fact at this "
        "seed, above the measured ceiling of 3 (0 / 0 / 1 at the three seeds). "
        "The number that reaches the board without anyone being asked is the "
        "one worth watching across a re-sample."
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

    # ── AND WHAT THE SYNCS SAID THEY DID (#624) ─────────────────────────────
    #
    # `MergeResult` is returned by every production sync and was returned to
    # nothing here until each day-batch went through
    # `sync_gmail_pipeline_additive` whole. Asserted as a whole dict so a single
    # change cannot look like a single number.
    synced = {
        name: getattr(replayed.synced, name) for name in RECORDED_SYNC
    }
    assert synced == RECORDED_SYNC, f"the syncs reported {synced}"
    # THE TWO CROSS-CHECKS, which are the reason these are worth pinning: they
    # are not restatements, they are two instruments that can disagree. See
    # `RECORDED_SYNC`.
    assert replayed.synced.created == RECORDED["cards"], (
        f"{replayed.synced.created} applications were created by the syncs but "
        f"{RECORDED['cards']} are on the board — a row was dismissed, or the "
        "per-batch catch-up minted one"
    )
    assert replayed.synced.needs_review == RECORDED_ANSWERS["queued"], (
        f"{replayed.synced.needs_review} items were surfaced to the queue and "
        f"{RECORDED_ANSWERS['queued']} were in it when the answering began"
    )

    # ── and now a person answers the queue ───────────────────────────────────
    #
    # EMBEDDED HERE RATHER THAN GIVEN ITS OWN TEST, and the reason is arithmetic
    # rather than taste. `test_session` is function-scoped, so every test that
    # replays pays for its own full replay; a separate test would add a sixth to
    # the five this gate already runs, for roughly +2 minutes, to measure
    # something that costs seconds on a board that already exists.
    #
    # It also makes "the pre-answer numbers did not move" structurally true
    # instead of asserted: every assertion above ran, on this same snapshot,
    # before the first answer was given.
    answers, after = await answer_the_queue(test_session, cases, replayed)

    # THE BUCKETS CLOSE, which is the first thing to check about any of them.
    # A count of good outcomes with no denominator is a number that can only go
    # up. `refused_needs_employer` is in here because it is the branch that
    # leaves the row in the queue and returns quietly: uncounted, those messages
    # simply vanish from the accounting.
    assert (
        answers.answered + answers.settled_by_a_prior_answer == answers.queued
    ), (
        f"{answers.queued} were held, {answers.answered} were answered and "
        f"{answers.settled_by_a_prior_answer} left the queue with a sibling — "
        "the rest are unaccounted for"
    )
    assert (
        answers.filed_on_an_existing_card
        + answers.minted_a_card
        + answers.refused_needs_employer
        + answers.not_a_lifecycle_answer
        == answers.answered
    ), "an answer produced an outcome this score has no bucket for"

    filed = answers.filed_on_an_existing_card + answers.minted_a_card
    assert (
        answers.landed_where_one_card_existed + answers.landed_where_several_did
        == filed
    ), "a filed answer was not counted against how much choice there was"

    after_score = score_board(after, cases)

    # NOT ZERO, AND NOT ASSERTED AS ZERO. This phase is new and the point of it
    # is to make these numbers exist; pinning them to the recorded values is
    # what a later commit does once they have been read by a person. What is
    # asserted now is that answering the queue does not DESTROY anything: a
    # merge is the one failure that silently discards a record.
    assert after_score.merges == RECORDED_AFTER_ANSWERING["merges"], [
        f.detail for f in after_score.failures if f.mode == "MERGE"
    ][:3]
    assert after_score.splits == RECORDED_AFTER_ANSWERING["splits"]
    assert after_score.cards == RECORDED_AFTER_ANSWERING["cards"]
    assert after_score.card_overstates == RECORDED_AFTER_ANSWERING["card_overstates"]
    assert after_score.role_missing == RECORDED_AFTER_ANSWERING["role_missing"]
    assert after_score.role_wrong == RECORDED_AFTER_ANSWERING["role_wrong"]
    assert after_score.wrong_review == RECORDED_AFTER_ANSWERING["held_cases_now_filed"]
    assert after_score.noise_on_card == RECORDED_AFTER_ANSWERING["noise_on_card"]
    assert (
        after_score.update_opened_a_card
        == RECORDED_AFTER_ANSWERING["update_opened_a_card"]
    )
    # THE POPULATIONS STILL CLOSE. A title counter that stops closing after the
    # phase runs would mean answering had produced a card the grader cannot
    # place, which is exactly the state a zero elsewhere would hide.
    assert (
        after_score.roles_graded
        + after_score.blank_required
        + after_score.role_unsettleable
        == after_score.titles_graded
    )
    for name in ("roles_graded", "blank_required", "role_unsettleable", "titles_graded"):
        assert getattr(after_score, name) == RECORDED_AFTER_ANSWERING[name], (
            f"{name} is {getattr(after_score, name)}, "
            f"recorded {RECORDED_AFTER_ANSWERING[name]}"
        )

    # ALL OF THEM AT ONCE, not the first mismatch. These counters move
    # together — holding more mail raises `queued`, `answered` and whichever
    # landing bucket receives it — so a loop that stops at the first one makes a
    # single change look like a single number and costs a full replay per round
    # to discover otherwise.
    drifted = {
        name: (getattr(answers, name), want)
        for name, want in RECORDED_ANSWERS.items()
        if getattr(answers, name) != want
    }
    assert not drifted, "answering counters moved (measured vs recorded): " + ", ".join(
        f"{name}: {got} vs {want}" for name, (got, want) in sorted(drifted.items())
    )


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

    # THE DESIGNED OUTCOME, counted so it stays visible — AND IT IS THREE
    # OUTCOMES, NOT ONE (#448).
    #
    # 685 updates are held for a person instead of filed. That was a single
    # counter until now, described right here as "every one is an OFFER, and
    # every one scores 0.75". Measured, it is three unrelated mechanisms and
    # the description was true of half of them:
    #
    #   345  the update's OWN `offer` verdict landed in [0.70, 0.85) — over the
    #        review floor and under the auto-file gate. THE MECHANISM THIS
    #        ISSUE IS ABOUT: the product saying it is not sure, which is the
    #        answer it is built to give. 79 at 0.70, 266 at 0.75.
    #    80  the update itself cleared the gate (`applied` at 0.95) and its
    #        ANCHOR is the row sitting in the queue. All of them
    #        `update-before-confirmation`, where the confirmation arrives after
    #        the update that belongs to it. A gate change aimed at updates does
    #        not move these; one aimed at confirmations does.
    #   260  `rescinded-offer` — `other` at 0.50, UNDER the review floor, in
    #        the queue because `references_an_application` floors it there and
    #        not because of the gate at all. That is #417, a different issue,
    #        and it was 38% of a counter everyone read as this one.
    #
    # WHY THIS IS NOT SCORED AS A FAILURE, stated because an earlier version of
    # this file scored it as one and reported 431 defects that were not
    # defects. Chasing them would have meant tuning the gate until a corpus
    # fixture passed — which is the shape of forcing a group rather than fixing
    # a rule.
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
    # THE THREE CAUSES, ASSERTED AGAINST THE FAMILIES THAT PRODUCE THEM. Two
    # independent readings of the same 685: the counters are derived from each
    # message's VERDICT and its membership of the queue, the right-hand sides
    # from the family the generator wrote. They agree today. A family that
    # started reaching the queue by one of the other two mechanisms would make
    # them disagree, which is exactly the thing one number could never say.
    assert score.update_held_on_a_non_offer_verdict == held["rescinded-offer"], (
        f"{score.update_held_on_a_non_offer_verdict} updates are in the queue "
        f"on a verdict that is not an offer, but {held['rescinded-offer']} are "
        "`rescinded-offer`. #417's population and #448's have stopped being "
        "the same set, so one of them is being counted under the other's name."
    )
    assert score.update_held_on_its_anchor == held["update-before-confirmation"], (
        f"{score.update_held_on_its_anchor} updates are held because their "
        f"ANCHOR is in the queue, but {held['update-before-confirmation']} are "
        "`update-before-confirmation`. A second family has started being split "
        "by its anchor's uncertainty rather than by its own."
    )

    # THE UPPER BOUND, AND THERE IS NO LOWER ONE ANY MORE.
    #
    # This read `560 <= update_held_for_review <= 700`, and the floor was
    # INVERTED. `update_held_for_review` counts the defect the band is nominally
    # about, so a floor under it reds when the defect is FIXED and stays green
    # while it persists. Measured in process, without touching a rule: lift
    # every `offer` verdict under 0.85 to 0.95 — the class fixed — and the
    # counter falls 685 -> 260 and the old floor of 560 fails. The floor had
    # also drifted, from a 431 that was filed to a 560-700 that was recorded,
    # so it never held the number still either: it could grow 60% underneath it.
    #
    # THE CEILING IS SOURCED FROM THE GATE INSTEAD OF FROM TODAY'S COUNT. An
    # update can only be held if the auto-file gate failed to clear it at one
    # end or the other; a pair the gate cleared at BOTH ends has no business in
    # a queue. So the bound tracks the classifier rather than the defect, and
    # it does not have to be re-recorded when #448 is fixed — 685 <= 685 here,
    # 260 <= 260 under the probe above, 606 <= 685 under the mirror one below.
    #
    # IT IS TIGHT TODAY, and that is the assertion rather than a coincidence:
    # every update the gate did not clear is held, and no update it cleared is.
    # A red means a fully confident update reached the queue anyway, which is a
    # fourth mechanism and worth stopping for.
    auto_filed = {v.case.message_id: v.auto_filed for v in verdicts}
    the_gate_did_not_clear = sum(
        1
        for c in cases
        if c.joins is not None
        and not (auto_filed[c.message_id] and auto_filed[c.joins])
    )
    assert score.update_held_for_review <= the_gate_did_not_clear, (
        f"{score.update_held_for_review} updates are held, but the auto-file "
        f"gate failed to clear only {the_gate_did_not_clear} of them at either "
        "end. Something is holding an update the product was confident about."
    )

    # AND THE CLASS GETTING WORSE HAS TO RED TOO, which is why the ceiling is
    # not the only thing left here. Dropping the floor drops the only assertion
    # that noticed this counter FALLING, and it can fall the wrong way: push
    # those same `offer` verdicts UNDER the review floor instead of over the
    # gate and the rows are dropped rather than queued — strictly worse, and
    # the ceiling stays green at 606 <= 685. Measured at 0.65: `dropped` goes
    # 0 -> 79, all `update-from-another-domain`, and this is the assertion that
    # fails. The other direction — an update FILED onto the wrong card — is
    # covered by `merges`, `splits` and `update_opened_a_card` at the top of
    # this test.
    assert score.dropped == RECORDED["dropped"], (
        f"{score.dropped} lifecycle verdict(s) fell under the review floor "
        "instead of reaching the queue. Fewer updates held is an improvement "
        "only if they were FILED; a drop is the same message reaching nobody, "
        "with a counter to say so."
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
    from tests.corpus_independent.harness import Replay, SyncTotals

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
                suppressed=set(),
                synced=SyncTotals(),
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
    # WHAT IT ACTUALLY CATCHES, stated narrowly because an earlier draft of this
    # comment oversold it. Between `titles_graded += 1` and the three-way
    # partition below it, the close is tautological against the current control
    # flow — every path out increments exactly one term. It does NOT catch a
    # skip UPSTREAM of the increment (`len(idents) != 1`, or a missing title
    # entry): those shrink `titles_graded` and the partition together and the
    # equation still holds. The pins above are what catch those.
    #
    # What the close does catch is a careless JOINT re-record: three pinned
    # integers can be moved together to match a broken run and still look
    # deliberate, and this line refuses the ones that do not add up. #536
    # documents why that matters — a merge regression once took `role_missing`
    # 213 -> 0 by lowering the denominator, and every zero in this test read
    # BETTER afterwards.
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


def _employer_spellings(cases) -> dict[str, set[str]]:
    """Every display name the resolver gives each employer TOKEN, over the corpus.

    No database and no replay: this is `resolve_employer` alone, which is what
    makes it a seconds-long gate rather than a ten-minute one.
    """

    by: dict[str, set[str]] = {}
    for case in cases:
        resolved = pipeline.resolve_employer(case.sender, case.subject, case.sender_name)
        if resolved is None:
            continue
        by.setdefault(resolved[0], set()).add(resolved[1])
    return by


def test_one_employer_gets_one_spelling(cases) -> None:
    """#532: the resolution paths must not disagree about an employer's NAME.

    A token is how the product decides two messages are the same employer; a
    display is what the card reads and what an exact-string sibling query
    compares. Until #532 the subject path truncated "Alderpoint Labs" to
    "Alderpoint" while the sender display-name path kept it whole, so 526
    employers sat under two spellings at once — a card that reads short, and a
    board that cannot see its own siblings.

    NEITHER NUMBER MAY RISE. That is the whole assertion: `tokens` pins that the
    grouping did not move, and the other two pin that the naming did not
    fracture again. A drop is an improvement and wants re-recording with the
    change that caused it.
    """

    by = _employer_spellings(cases)
    several = {t: v for t, v in by.items() if len(v) > 1}
    got = {
        "tokens": len(by),
        "distinct_displays": sum(len(v) for v in by.values()),
        "tokens_with_several_spellings": len(several),
    }
    assert got["tokens"] == RECORDED_EMPLOYER_SPELLINGS["tokens"], (
        f"the employer TOKEN count moved to {got['tokens']}. Two different "
        "causes reach this line and they want opposite responses. A RISE is "
        "grouping: something re-keyed the board, and that is the defect this "
        "gate was written for. A DROP means messages stopped resolving an "
        "employer at all — check the board counters before assuming a re-key, "
        "because #733's guard dropped this by 43 while cards, company_drift, "
        "splits and merges all held exactly."
    )
    for name in ("distinct_displays", "tokens_with_several_spellings"):
        assert got[name] == RECORDED_EMPLOYER_SPELLINGS[name], (
            f"{name} is {got[name]}, recorded "
            f"{RECORDED_EMPLOYER_SPELLINGS[name]}. A RISE means a resolution "
            "path started spelling an employer differently from the others, "
            "which is #532 returning. A FALL is a fix — re-record it here.\n"
            + "\n".join(
                f"  {t}: {sorted(v)}" for t, v in sorted(several.items())[:5]
            )
        )


def test_the_spelling_gate_goes_red_for_the_defect_it_was_written_for(cases) -> None:
    """THE CONTROL. Put the old cleaner back and the numbers must move.

    Without this, three recorded values that happen to match today would look
    exactly like a gate. `_CORP_TAIL` is still in the module — it has another
    caller — so the pre-#532 `_clean_company_display` can be rebuilt here from
    the real constants rather than from a copy that could drift.
    """

    old_via_tail = re.compile(r"\s*(?:\bvia\b|\bthrough\b|\bon\b|[(\[]).*$", re.IGNORECASE)

    def pre_532(raw: str) -> str:
        text = old_via_tail.sub("", raw or "").strip()
        text = pipeline._CORP_TAIL.sub("", text).strip(" ,.-&")
        return re.sub(r"\s+", " ", text)

    real = pipeline._clean_company_display
    pipeline._clean_company_display = pre_532
    try:
        by = _employer_spellings(cases)
    finally:
        pipeline._clean_company_display = real

    several = sum(1 for v in by.values() if len(v) > 1)
    assert len(by) == RECORDED_EMPLOYER_SPELLINGS["tokens"], (
        "the old cleaner changed the TOKEN count, which it never did — this "
        "control is no longer reproducing the pre-#532 behaviour"
    )
    assert several > RECORDED_EMPLOYER_SPELLINGS["tokens_with_several_spellings"], (
        f"the pre-#532 cleaner produced {several} multiply-spelled employers, "
        f"not more than the recorded "
        f"{RECORDED_EMPLOYER_SPELLINGS['tokens_with_several_spellings']}. The "
        "gate above cannot tell the defect from the fix."
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
    from tests.corpus_independent.harness import Replay, SyncTotals

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
            Replay(groups=cards, reviewed=set(), dropped=set(), suppressed=set(), synced=SyncTotals(), status={}, title=title),
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
        "THE CONTROL: a scorer that simply compared strings would call every "
        "drift case a wrong company. It is also what keeps the recorded "
        "company_drift of 0 meaningful — #532 took the real count from 1,420 "
        "to 0, and a counter that can only ever read 0 proves nothing."
    )

    # And the sentinel half: ground truth that names no role must score a blank
    # card as CORRECT, not as a miss. #487's first condition.
    anonymous = score_board(
        Replay(
            groups=[("rowA", ["m0"])],
            reviewed=set(),
            dropped=set(),
            suppressed=set(),
            synced=SyncTotals(),
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
    from tests.corpus_independent.harness import Replay, SyncTotals

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
            suppressed=set(),
            synced=SyncTotals(),
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
            suppressed=set(),
            synced=SyncTotals(),
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
        Replay(groups=[], reviewed=set(), dropped={"m1"}, suppressed=set(), synced=SyncTotals(), status={}, title={}),
        [anchor],
    )
    assert fell.dropped == 1 and fell.lost == 0
    gone = score_board(
        Replay(groups=[], reviewed=set(), dropped=set(), suppressed=set(), synced=SyncTotals(), status={}, title={}),
        [anchor],
    )
    assert gone.lost == 1 and gone.dropped == 0, (
        "LOST and DROPPED must be told apart by whether the product counted "
        "the message, which is the entire reason they are two numbers"
    )

    # SUPPRESSED-AS-SETTLED, the third of the same kind (#624). It reads 0
    # against the real corpus and — measured, not assumed — currently CANNOT
    # read anything else there: no family produces a queued message sharing
    # both a thread and an identity with mail already on a card, so the
    # additive persist's settled filter never bites. That is exactly the
    # "asserted empty and never fired" shape this test exists for, so the
    # branch is forced here instead.
    #
    # Told apart from LOST deliberately. Both are "no card, no queue, no
    # counter"; they differ in whether the product CHOSE it, and collapsing
    # them would put a designed suppression in the counter that exists for
    # silent loss.
    refused = score_board(
        Replay(
            groups=[],
            reviewed=set(),
            dropped=set(),
            suppressed={"m1"},
            synced=SyncTotals(),
            status={},
            title={},
        ),
        [anchor],
    )
    assert refused.suppressed_as_settled == 1
    assert refused.lost == 0 and refused.dropped == 0
    assert refused.total == 0, "a designed suppression is not a defect"
    assert [f.mode for f in refused.failures] == ["SUPPRESSED-AS-SETTLED"]

    # THE CONTROL. Same shape, correct outcome, and nothing is scored — a
    # scorer that flagged everything would have passed both cases above.
    clean = score_board(
        Replay(
            groups=[("rowA", ["m1", "m2"])],
            reviewed=set(),
            dropped=set(),
            suppressed=set(),
            synced=SyncTotals(),
            status={"rowA": "rejected"},
            title={},
        ),
        [anchor, case("m2", joins="m1", card_status="rejected")],
    )
    assert clean.total == 0
    # AND THE GOOD OUTCOMES ARE COUNTED, which is the left-hand side of the
    # closure in `test_every_application_mail_is_addressed`. Both messages are
    # on a card here; a scorer that only counted the leftovers would report
    # zero for the whole population and the closure would be unstatable.
    assert clean.addressed_on_a_card == 2 and clean.addressed_in_the_queue == 0


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
        # EMPTY SINCE #458, and the 11 that used to sit here were not lost for
        # the reason the issue gave. They were `observed-rejection`, and #458
        # described them as `other` at 0.50 whose text never refers to an
        # application — which would have needed `invested in our process` in
        # the reference signal, a sender's SENTENCE rather than a category, so
        # closing them was declined.
        #
        # Executed rather than read, all 11 scored `follow_up` at 0.70. Their
        # subjects carry the sender's own word "Follow-Up" and their decision
        # sentence sits one character past Gmail's snippet cut, so the veto
        # that outranks the follow-up pattern never fires. `follow_up` is
        # dropped by filing, by the queue and by `DroppedVerdict` alike, on a
        # premise — "it is the reader's own chasing mail" — that is false for a
        # message an ATS relayed. Both wording extensions the issue proposes
        # would have missed them: `_APPLICATION_REFERENCE` is consulted only
        # when the category is `other`, and never sees a `follow_up` verdict.
        #
        # The 5 that used to sit alongside were #466: `_APPLICATION_REFERENCE`
        # spanned the job title with `[\w,\ \-/]{0,60}?`, a character class
        # holding no `(`, `)` or `:`, so a real title made the #447 floor blind
        # to a message it exists to catch. Fixed by bounding on the CLAUSE
        # instead — extending the character class was the obvious move and the
        # wrong one, because "Software Engineer, C#" already needed a character
        # nobody had anticipated.
    }, dict(lost)

    # EMPTY SINCE #451, and it held `{"update-from-another-domain": 54}` until
    # then. Those 54 are updates from the company's own domain rather than an
    # ATS relay, so the #447 reference clause could not floor them: they scored
    # `applied` at 0.60 on the reference pattern alone and left under the review
    # floor, counted by the product and on no screen. Demoting that pattern out
    # of `strong` does not raise their score — it stops `applied` OWNING them,
    # so the update reads as the update it is and reaches the queue. They are in
    # `update_held` now, which rose 631 -> 685 by exactly this 54.
    #
    # Asserted as the empty dict, like `lost` above: a family here at ANY size
    # is mail the product received and did nothing visible with.
    dropped = Counter(f.family for f in score.failures if f.mode == "DROPPED")
    assert dict(dropped) == {}, dict(dropped)

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
    #
    # #458 IS BOUNDED BY THE SAME 400, and its number is measured rather than
    # structural: zero of them score `follow_up`, so the clause that now routes
    # a relayed `follow_up` to the queue cannot touch one of them. That is a
    # fact about these 400 messages and not a guarantee about the category —
    # a relayed digest whose own text scored `follow_up` WOULD be queued, and
    # the module docstring in `test_relayed_follow_up_is_not_your_own.py` says
    # so out loud.
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

    # ── AND THE FIVE OUTCOMES CLOSE (#624) ──────────────────────────────────
    #
    # Everything above this line asserts that two counters are zero. Two zeroes
    # are worth exactly as much as the denominator behind them, and there was
    # none: `lost` and `dropped` are what is left after a message is found on a
    # card or in the queue, so a change that stopped examining n messages moves
    # both toward zero and every assertion above gets GREENER. That is the
    # defect shape this file exists to avoid, and it was here.
    #
    # The population is counted from `cases`, in the test, on purpose. A
    # denominator `score_board` maintained would fall with the buckets and this
    # could not fail; counting it here means a `continue` added to that loop
    # reds immediately.
    #
    # `lost` IS IN THE SUM, which #624's brief left out on the grounds that it
    # is zero. Leaving it out asserts `lost == 0` a second time, in arithmetic,
    # so a real regression would raise here instead of failing the pinned
    # assertion above that names the FAMILIES. Both spellings hold today; this
    # one keeps the diagnosis.
    must_be_addressed = sum(1 for c in cases if c.must_be_addressed)
    assert must_be_addressed == RECORDED["must_be_addressed"], (
        f"{must_be_addressed} messages must be addressed, recorded "
        f"{RECORDED['must_be_addressed']} — the corpus changed shape"
    )
    assert (
        score.addressed_on_a_card
        + score.addressed_in_the_queue
        + score.suppressed_as_settled
        + score.dropped
        + score.lost
        == must_be_addressed
    ), (
        f"{score.addressed_on_a_card} on a card + "
        f"{score.addressed_in_the_queue} in the queue + "
        f"{score.suppressed_as_settled} suppressed as settled + "
        f"{score.dropped} dropped + {score.lost} lost = "
        f"{score.addressed_on_a_card + score.addressed_in_the_queue + score.suppressed_as_settled + score.dropped + score.lost}"
        f", but {must_be_addressed} messages must be addressed. Some of them "
        "are being graded by nothing."
    )
    for name in (
        "addressed_on_a_card",
        "addressed_in_the_queue",
        "suppressed_as_settled",
    ):
        assert getattr(score, name) == RECORDED[name], (
            f"{name} is {getattr(score, name)}, recorded {RECORDED[name]}"
        )


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
    from tests.corpus_independent.harness import Replay, SyncTotals

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
                suppressed=set(),
                synced=SyncTotals(),
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
            suppressed=set(),
            synced=SyncTotals(),
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
# 8024 -> 8604 (#626): +580, one per application the new family files, and
# every one of them spelled in its own mail — 260 in the subject's trailing
# segment and 320 in a sibling confirmation's body. None is removed by the
# derivation, which is the check that the family's ground truth is readable
# rather than wished for.
# 8604 -> 8724 (#641): +120, the new family's two NAMED applications per
# employer. Its third is the sentinel sub-key and carries no title to grade,
# which is the whole point of it.
RECORDED_ROLE_IDENTITIES = 8724


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

    THE WINDOW IS SPELLED OUT HERE RATHER THAN IMPORTED, and that is the whole
    difference between this test and a restatement. An earlier draft called
    ``generate._readable_text``, which made the assertion true by construction:
    production and test computed the same predicate over the same objects, so
    any bug INSIDE the predicate was invisible to it. One was there — the window
    also concatenated ``delivered``, which is ``body`` uncapped, quietly undoing
    the 4,000-character cut the function exists to make.

    So the window is rebuilt from the product's own constant
    (``gmail_client._MAX_BODY_CHARS``) and the two fields the extractor is
    actually handed. A corpus-side window that drifts from what
    ``role_from_message`` can read now fails here instead of agreeing with
    itself.
    """

    from jobtracker.cloud.gmail_client import _MAX_BODY_CHARS

    def reachable_text(case) -> str:
        """Exactly what ``role_from_message`` is handed, and nothing else."""

        return " ".join(
            (case.subject, " ".join(case.body.split())[:_MAX_BODY_CHARS])
        ).lower()

    by_identity: dict[str, list] = {}
    for case in cases:
        if case.identity is not None and case.role_truth is not None:
            by_identity.setdefault(case.identity, []).append(case)

    unspelled = [
        identity
        for identity, group in by_identity.items()
        if not any(
            " ".join(group[0].role_truth.split()).lower() in reachable_text(c)
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

    # THE FOURTH SHAPE IS THE CAP, and it is the one that catches a window
    # that has quietly stopped being the extractor's window. The role is
    # spelled once, past `_MAX_BODY_CHARS`, on a card with no shorter sibling.
    # `role_from_message` structurally cannot reach it, so the correct ground
    # truth is a blank card — and any predicate that reads `delivered` (which
    # is the body UNCAPPED) finds it and leaves the card graded against a title
    # the product can never print.
    from jobtracker.cloud.gmail_client import _MAX_BODY_CHARS

    past_the_cap = case(
        "m5",
        "kestrelan|Systems Engineer",
        "Thank you for your application. " + ("filler " * ((_MAX_BODY_CHARS // 7) + 20))
        + "The role was Systems Engineer.",
        subject="Your application",
    )
    assert "Systems Engineer" not in past_the_cap.body[:_MAX_BODY_CHARS], (
        "the fixture no longer puts the role past the cap, so it gates nothing"
    )
    assert "Systems Engineer" in past_the_cap.delivered, (
        "…and it must still be inside `delivered`, or the mutation this shape "
        "exists to catch cannot happen"
    )

    corpus = [spelled, silent, late_first, late_second, past_the_cap]
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
    assert past_the_cap.role_truth is None and past_the_cap.names_no_role, (
        "a role spelled only past the body cap was called reachable — the "
        "window has drifted from what `role_from_message` is handed, which is "
        "#533's own defect moved past character 4,000 instead of fixed"
    )


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
    perturbed on a single case out of 18,020 — a one-case change is the smallest
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


def test_a_card_required_to_be_blank_names_no_job_anywhere(cases) -> None:
    """`names_no_role` claims more than the derivation proves. Close the gap.

    `_settle_role_reachability` establishes one thing: the role THIS IDENTITY IS
    KEYED ON is spelled in no message on the card. `names_no_role` then asserts
    something stronger — that the mail names no job at all — and `role_invented`
    enforces that stronger claim against the product, in `total`.

    Today the gap between the two is empty, because every `observed-*` template
    either interpolates `{role}` or contains no job title in any wording. But
    nothing held it empty. A template added tomorrow that names a job in words
    other than the interpolated one, or spells it a way this file's plain
    lowercase substring match misses, would be flipped to MUST-BE-BLANK — and
    then a correct extractor reading that title would fire ROLE-INVENTED, which
    is a gate going red because the product got it right. `Case.__post_init__`
    already warns about exactly this shape in its refusal message; nothing
    stopped the derivation from creating it.

    So: no card required to be blank may contain ANY title from the pool, in
    subject or readable body. Asserted over the sentinel families too, which the
    derivation never touches and which have carried the same unchecked claim
    since #487.
    """

    from jobtracker.cloud.gmail_client import _MAX_BODY_CHARS
    from tests.corpus_independent.generate import ROLES

    def reachable_text(case) -> str:
        """Rebuilt here, NOT imported from the module under test.

        Importing `generate._readable_text` would make this test move with the
        thing it is checking: narrowing that window would narrow this window
        too, so a derivation that flipped thousands of role-naming cards to
        MUST-BE-BLANK would still find no role to complain about. That is not
        hypothetical — it is what the first draft of this test did, and the
        mutation run that was supposed to prove the test caught nothing.
        """

        return " ".join(
            (case.subject, " ".join(case.body.split())[:_MAX_BODY_CHARS])
        ).lower()

    by_identity: dict[str, list] = {}
    for case in cases:
        if case.identity is not None and case.names_no_role:
            by_identity.setdefault(case.identity, []).append(case)

    named = []
    for identity, group in by_identity.items():
        text = " ".join(reachable_text(c) for c in group)
        hit = next((r for r in ROLES if r.lower() in text), None)
        if hit is not None:
            named.append((identity, hit))

    assert not named, (
        f"{len(named)} card(s) are asserted to be BLANK for mail that names a "
        f"job from the pool. A correct extractor reading it would be scored as "
        f"an invention: {named[:5]}"
    )
    # THE DENOMINATOR. "No blank-required card names a job" is also true of a
    # corpus with no blank-required cards, and the derivation that produces them
    # is one line away in the same module.
    assert len(by_identity) == RECORDED["blank_required"], (
        f"{len(by_identity)} identities are required to be blank; the assertion "
        f"above is worth exactly that many"
    )


def test_every_category_the_corpus_carries_is_an_answer_a_person_can_give(cases):
    """The answer mapping is exactly total, in both directions.

    Cheap, and it guards two different mistakes. A family that introduces a new
    `expected_category` would otherwise reach `answer_the_queue` and raise
    mid-replay, nine minutes in. And a mapping entry the corpus never exercises
    is a wording nothing tests, which is how a table grows rows that are never
    read.

    `NEEDS_REVIEW` must be in neither set. It is the typed null of
    `classified_as`, not a verdict — answering with it would write a decision no
    person made, which is the commitment `classified_as` is documented to carry.
    """

    carried = {c.expected_category for c in cases}
    assert carried - set(_ANSWERS) == set(), (
        "the corpus carries a category the queue phase cannot answer with"
    )
    assert set(_ANSWERS) - carried == set(), (
        "the answer table has a row no case exercises"
    )
    assert "needs_review" not in _ANSWERS, (
        "needs_review is the absence of a verdict; sending it as one forges a "
        "human decision"
    )


#: WHAT THE #626 READER MUST DO WITH THE FAMILY WRITTEN FOR IT.
#:
#: A blind cross-check swept 401,244 unique inputs against
#: `_role_from_trailing_segment` and found 1,098 that reach it — none of them in
#: this corpus and none of them a literal in backend source. So the reader
#: shipped graded only by mail its own author wrote, and this table is the
#: measurement that says the corpus can now see it at all.
#:
#: The three numbers close: 260 + 180 == 440.
RECORDED_TRAILING_SEGMENT = {
    # Messages of the family carrying the shape — at least two pipes, so a
    # trailing segment exists to read. The family's 320 sibling confirmations
    # are not among them; they carry an ordinary one-segment subject.
    #
    # AT LEAST, not exactly, and the difference is 40 of these messages: two of
    # the public board LOCATIONS contain pipes inside a single location value,
    # which is the whole reason they are in the family. A pipe is not reliably
    # a segment boundary, and an `== 2` filter here would have silently dropped
    # exactly the cases that say so.
    "post_name_messages": 440,
    # 240 acknowledgements plus the 20 TAIL-side halves of the both-placements
    # pair. Each is a card whose title exists in exactly one place.
    "titles_read": 260,
    # 160 refusals plus the 20 ROLE-side halves, which must refuse for the
    # parenthetical rule to hold.
    "refused": 180,
}


def test_this_corpus_reaches_the_trailing_segment_reader(cases, monkeypatch) -> None:
    """The family reaches `_role_from_trailing_segment`, PROVEN not assumed.

    A corpus family that does not reach the code it was written for is this
    estate's named recurring defect and it looks exactly like a passing test —
    so reach is established twice here, in the two directions that can each be
    true while the other is false.

    FORWARD: the reader hands back the byte-exact public board title, for every
    one of the 260, and hands back NOTHING ELSE. The set equality is the half
    that matters: a reader that truncated at the first spaced dash would return
    "Research Engineer / Scientist, Alignment" — a string that is not in
    `_POST_NAME_RESOLVES` and would fail here even though it is a plausible
    title and would look right on a card. That is #553's exact defect, and a
    count would have passed it.

    BACKWARD, and this is the reach claim proper: with the reader replaced by a
    function that returns None, NOT ONE of the 440 yields a title from any other
    path. No `_ROLE_PATTERNS` entry, no body pattern and no leading-segment read
    covers this mail, so the 260 titles are this reader's or they are nothing.

    THE CORPUS-LEVEL CONSEQUENCE OF THE SAME MUTATION, measured on a full replay
    rather than inferred from here, is three counters and not one:

        role_missing   63 -> 343      splits   0 -> 20      cards  9728 -> 9748

    +280 blank titles is 240 acknowledgements plus both halves of every
    both-placements pair, and the +20 splits ARE that pair: with no title to
    join on, one posting written two ways opens two cards. That is the exact
    failure the reader's parenthetical rule exists to prevent, and before this
    family nothing in the corpus could produce it.

    Cheap on purpose — pure functions over 440 subjects, no replay — so it is
    the check that reds first when the reader moves.
    """

    post_name = [
        c
        for c in cases
        if c.family == "concatenated-post-name" and c.subject.count(" | ") >= 2
    ]
    assert len(post_name) == RECORDED_TRAILING_SEGMENT["post_name_messages"], (
        f"{len(post_name)} messages carry the shape, recorded "
        f"{RECORDED_TRAILING_SEGMENT['post_name_messages']}"
    )

    read = {c.message_id: pipeline.role_from_message(c.subject, c.body) for c in post_name}
    titles = {r for r in read.values() if r}
    assert titles == set(_POST_NAME_RESOLVES), (
        "the reader returned a title this family did not put in a subject: "
        f"{sorted(titles - set(_POST_NAME_RESOLVES))}, and missed "
        f"{sorted(set(_POST_NAME_RESOLVES) - titles)}"
    )
    assert sum(1 for r in read.values() if r) == RECORDED_TRAILING_SEGMENT["titles_read"]
    assert sum(1 for r in read.values() if not r) == RECORDED_TRAILING_SEGMENT["refused"]

    monkeypatch.setattr(pipeline, "_role_from_trailing_segment", lambda subject: None)
    without = [
        (c.message_id, c.subject, pipeline.role_from_message(c.subject, c.body))
        for c in post_name
    ]
    still_read = [(mid, subject, role) for mid, subject, role in without if role]
    assert not still_read, (
        f"{len(still_read)} of these subjects are read by something OTHER than "
        f"the trailing-segment reader, so this family does not measure it: "
        f"{still_read[:3]}"
    )
