"""
Rule-Based Email Classifier (Layer 1)
=====================================

Pattern matching with weighted scoring for job application emails.
This is the first layer of classification - works on Day 1 without training data.

Scoring system:
- Strong patterns: +3 points (highly specific phrases)
- Weak patterns: +1 point (suggestive but ambiguous)
- Negative patterns: -5 points (contradicting phrases)
- Veto patterns: the category cannot win, whatever else matched
- Subject patterns: 2x weight (subjects are more predictable)
- ATS sender domains: bonus confidence

A negative pattern cannot actually veto anything: a strong pattern in the
subject is +6 and one negative is -5, so "Newsletter: 2026 skills assessment
trends" still scored +1 and won as `assessment`. Veto patterns exist for the
cases where a phrase means the category is wrong regardless of what else the
text says — see EmailCategory.ASSESSMENT and EmailCategory.FOLLOW_UP below.

The category with highest score wins; at equal score a category that REPORTS on
an application outranks one that merely ASSERTS one exists, because the first
entails the second (#451). Confidence is based on margin and match strength.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from jobtracker.database.models import EmailCategory

logger = logging.getLogger(__name__)


# =============================================================================
# Pattern Definitions
# =============================================================================


@dataclass
class CategoryPatterns:
    """Pattern definitions for a single category."""

    strong: list[str] = field(default_factory=list)  # +3 points
    weak: list[str] = field(default_factory=list)  # +1 point
    negative: list[str] = field(default_factory=list)  # -5 points
    # A match here caps the category's score at 0, so it can neither win nor
    # be out-voted by a strong subject match. Use it only for phrases that
    # make the category *wrong*, not merely less likely.
    veto: list[str] = field(default_factory=list)


# The sentences that state the hiring decision has gone AGAINST the candidate.
# DECISION SENTENCES — the block below appears TWICE on purpose, once as
# REJECTION's strongest evidence and once as FOLLOW_UP's veto (a message that
# says the decision is made is not a nudge, whatever its subject line reads).
#
# It is duplicated rather than shared through a module constant, and that is
# not an oversight. Three things read these lists as LITERALS in the PATTERNS
# dict and cannot see through a splat or a `list(...)` call:
#   * ``scripts/readme_facts.py`` parses this file statically for the pattern
#     counts the README, `apps/web/lib/demo/rulesLayer.ts` and
#     `ml/browser/site/app.js` all publish — a shared constant silently
#     under-counted this file by 12 and turned a checked claim into a wrong one;
#   * ``ml/demo/space/jobtracker/classifier/rules.py`` is a byte-identical copy;
#   * ``apps/web/lib/demo/rules.json`` enumerates every pattern for the browser
#     port, so it can never agree with a count that hides some of them.
# Keep them in step by hand, and keep them in step with those three files.
#
# The mail that forced this is a real rejection whose subject followed the
# common ATS template `<Company> Follow-Up for <Role> | <Candidate>`, with the
# decision in the body: "…we have decided not to move forward with your
# application". The employer, role and candidate are left out on purpose -- the
# shape is the fact, and the particulars were one person's job search (#593).
# The word "Follow-Up" in the subject scored follow_up +6 and the rejection
# sentence scored NOTHING, so
# it classified as follow_up at 0.90 — and ``follow_up`` reaches neither
# ``pipeline._qualifies_for_hard_row`` nor ``pipeline.collect_review_items``, so
# the message was never persisted at all.


# BEFORE YOU ADD OR CHANGE A PATTERN, read `docs/CLASSIFIER_RULES_GOVERNANCE.md`.
# It is a transcription of the standard four commits on `main` already apply by
# citing issue #10, and it is short. The two rules that catch people: a new
# pattern must be strictly NARROWER than one that already fires, and a change
# ships with a named near-miss case that must NOT move. "Macro-F1 is unchanged"
# is necessary and never sufficient — the failure mode this guards is a narrow
# patch, and a narrow patch is benchmark-neutral by construction.

# Pattern definitions for each category
PATTERNS: dict[EmailCategory, CategoryPatterns] = {
    EmailCategory.REJECTION: CategoryPatterns(
        strong=[
            r"regret to inform",
            r"decided not to proceed",
            # The INFINITIVE. "we have decided not to move forward with your
            # application" is the most standard rejection sentence there is and
            # it matched nothing here: every pattern below wanted the participle
            # ("moving") or the bare "not …forward" with no "to" in between. The
            # participle already carries a general form AND a noun-anchored one,
            # which is how it reaches +6 from a body alone; the infinitive gets
            # the same pair so the two inflections are worth the same.
            r"not to (move|proceed|go) forward",
            r"not to (move|proceed|go) forward.{0,30}(application|candidacy)",
            r"not (be )?(moving|proceeding) forward",
            # The verb that takes "with" instead of "forward". Every pattern
            # above wants the word "forward" somewhere, and the nearest of them
            # — `not (be )?(moving|proceeding) forward` — misses "we will not be
            # proceeding with your candidacy for this role at this time"
            # outright. That is Lever's standard rejection wording and it is
            # what the owner's real Palantir rejection says, so the sentence
            # stating the decision scored ZERO: `regret to inform` carried the
            # whole message alone at +3, which is the 0.70 rung, which is under
            # AUTO_FILE_GATE. The verdict was right and the mail was held for
            # review anyway.
            #
            # Paired general + noun-anchored, exactly like the infinitive above,
            # and for a structural reason rather than a stylistic one: a strong
            # SUBJECT match is +6 and a strong BODY match is +3, but rejections
            # state their verdict in the body while their subject reads "Thank
            # you from Palantir Technologies". One body match can never reach
            # 0.90. Two can — which is the only way this category clears a gate
            # that acknowledgements clear from their subject line alone.
            #
            # The contraction arm is not decoration either. Supernova's real
            # rejection says "it is unfortunate that we won't be proceeding
            # with your application" — and with only the literal "not" spelling
            # here, reading the whole body still classified it `applied`. That
            # is the same defect `(won't|will not) be advancing` below already
            # records, in the mirror direction: whichever spelling gets written
            # first, the other one scores zero. Both inflections, always.
            r"(won't|will not|not) (be )?(proceeding|continuing) with",
            r"(won't|will not|not) (be )?(proceeding|continuing) with.{0,30}(application|candidacy)",
            r"will not be moving forward.{0,30}(application|candidacy)",
            r"not.{0,20}moving forward.{0,20}(application|your candidacy)",
            # SIX PAIRS FOLLOW, and the twins are not decoration.
            #
            # Eight of the sixteen sentences in
            # ``tests/test_rules_classifier_rejection.py`` matched exactly ONE
            # pattern here. One strong BODY match is +3, which is the 0.70 rung
            # — the review queue. ``pipeline.AUTO_FILE_GATE`` is 0.85, so the
            # classifier could recognise those eight and never act on one of
            # them, and the gate over them asserted 0.70 and was green about it.
            # An acknowledgement states its verdict in the SUBJECT, where a
            # strong match is +6 and clears the gate alone; a rejection states
            # its verdict in the body under "Thank you from <Company>". That is
            # a structural bias against this one category, not a gap in any
            # single pattern.
            #
            # The fix is the same mechanical one the infinitive and
            # ``(proceeding|continuing) with`` already carry above: pair a
            # general form with a narrower anchored one, so a body with no
            # subject support reaches +6 and clears the gate. It is deliberately
            # NOT a reweighting of body matches — that would move every verdict
            # in the corpus at once and risk misfiling the acknowledgements,
            # which is the failure mode #10 is about. Each twin below is
            # strictly narrower than its partner and can only fire where the
            # partner already did.
            #
            # Measured, not assumed. Replayed over all 200 rows of the committed
            # evaluation corpora (``data/evaluation/classifier_eval_v{1,2,3}
            # .jsonl``) before and after: NO row changed category, and exactly
            # four moved confidence — every one of them gold-labelled
            # ``rejection``, and every one upward.
            #
            #   v2:027  "You were not selected at this time…"          0.70 → 0.90
            #   v2:029  "We will not be advancing your candidacy."     0.90 → 0.95
            #   v3:039  "We will not be advancing your candidacy…"     0.90 → 0.95
            #   v3:045  "…unable to proceed with your candidacy."      0.70 → 0.90
            #
            # Two of those four crossed ``AUTO_FILE_GATE``, which is the whole
            # point. Not one acknowledgement moved in any direction.
            #
            # Replaces `move(d)? forward with other candidates` and
            # `chosen to move forward with another candidate`: neither had the
            # participle, so "we will be moving forward with other candidates
            # whose qualifications more closely match" scored 0.
            #
            # `different` joins `other|another` (#348). English has three ways
            # to say "not you" in this slot and the alternation carried two:
            # "we have chosen to move forward with a DIFFERENT candidate" is
            # Workable's published rejection template, the most-reproduced
            # rejection copy on the web, and it scored literally ZERO. The
            # optional article is what lets the singular "a different
            # candidate" reach the same pattern as the bare plural.
            r"(move|moved|moving) forward with (a |an |the )?(other|another|different) (candidate|applicant)",
            # Anchored on the decision verb, which is what makes "we have decided
            # to move forward with other candidates" and "we will be moving
            # forward with other candidates" reach the gate rather than the queue.
            r"(decided|chosen|elected|will be|are)\b.{0,20}(move|moving) forward with (a |an |the )?(other|another|different) (candidate|applicant)",
            # Replaces `decided to pursue other candidates`, which required both
            # the lead-in and the noun "candidates"; "pursue other applicants"
            # scored 0.
            r"pursu(e|ing) other (candidates|applicants)",
            # The lead-in the general form dropped, restored as the twin.
            r"(decided|chosen|elected|opted) to pursue other (candidates|applicants)",
            r"not (been )?selected.{0,30}(position|role|interview)",
            # "You have not been selected." — a complete rejection with no
            # trailing noun for the pattern above to anchor on.
            r"\bnot been selected\b",
            # Subject-anchored rather than object-anchored, which is what lets it
            # be the SECOND match for both spellings: "You have not been
            # selected" (the bare form) and "You were not selected for this
            # position" (the trailing-noun form). Neither reached +6 alone.
            r"\byou (have|were)\b.{0,10}not (been )?selected\b",
            r"not (be )?able to offer.{0,20}(position|role|interview)",
            # "unable" is not "not able", and it is the form ATS templates use:
            # "we are unable to offer you a position at this time".
            r"unable to (offer|extend).{0,25}(position|role|offer|interview|opportunity)",
            # The pronoun rather than the noun. It cannot reach an actual offer:
            # `(pleased|delighted|…) to offer` and `offer (letter|of employment)`
            # are rejection NEGATIVES below, and an offer letter does not open
            # with "unable to".
            r"unable to (offer|extend) you\b",
            r"unable to (proceed|continue|move forward) with",
            r"unable to (proceed|continue|move forward) with.{0,25}(application|candidacy|process)",
            # Was `won't be advancing…` — contraction only, so "we will not be
            # advancing your candidacy" missed.
            r"(won't|will not) be advancing.{0,20}(application|candidacy)",
            # Drops the modal entirely, so it is the second match for the
            # "will not" spelling AND covers "we are not advancing your
            # application", which neither form above reaches.
            r"not (be )?advancing (your|the) (application|candidacy)",
            r"position has been filled",
            r"we('ve| have) decided to go in (a )?different direction",
            # --- end of the block FOLLOW_UP.veto repeats -------------------
            r"unfortunately.{0,50}(not|won't|will not|unable)",
            r"(role|position).{0,20}(closed|filled)",
            r"decision on (your |my )?candidacy",
            r"after careful (consideration|review).{0,30}(not|decided|unfortunately)",
            # The sign-off, and it broke on an intensifier (#348). "we wish you
            # ALL the best in your job search" is the other half of the Workable
            # template above, and the literal `(the best|well|success)` could not
            # see past the word "all". The trailing noun is dropped with it:
            # "in your job search", "in your search", "in your future endeavors"
            # and "in your career" are the same sentence, and requiring one
            # spelling of it was the same over-narrowness one alternation up.
            r"wish you (all |only |nothing but )?(the (very )?best|well|success|luck) in your",
            r"encourage you to apply (for )?future.{0,20}(position|role|opening)",
            r"keep your (resume|application) on file",
            r"not a (good )?fit.{0,20}(at this time|for this role)",
        ],
        weak=[
            r"competitive (applicant )?(pool|field)",
            r"many qualified (candidates|applicants)",
            r"difficult decision",
        ],
        negative=[
            r"schedule.{0,20}interview",
            r"excited to (meet|speak)",
            # Was one pattern, `offer (you|letter|of employment)`. The bare
            # "offer you" arm fired on "we are unable to offer you a position at
            # this time" — a rejection stated as an offer that isn't — for -5,
            # cancelling the +3 that sentence had just earned and landing the
            # mail in `other` at 0.50. Split so the "you" arm needs the
            # affirmative lead-in an actual offer carries. Deliberately NOT a
            # lookbehind: `apps/web/lib/demo/rules.json` compiles every one of
            # these with `new RegExp(p, "i")` in the browser, the port declares
            # an ES2017 baseline, and lookbehind is ES2018 — one unsupported
            # pattern throws at construction and takes the whole layer with it.
            r"offer (letter|of employment)",
            r"(pleased|delighted|happy|excited|glad|would like) to offer",
            r"looking forward to speaking",
            # TWO NEGATIVES WERE REMOVED HERE (#658), and the argument is the
            # one EmailCategory.INTERVIEW already records above for the seven
            # it removed in #348: they were EmailCategory.APPLIED's own
            # positives, copied in to stop an acknowledgement reading as a
            # rejection, and a real rejection OPENS with them.
            #
            #   thank you for applying · application.{0,20}received
            #
            # The second is `APPLIED.strong[0]` verbatim; the first is its
            # sibling `thank(s| you) for applying` less the alternation.
            #
            # "Thank you for applying for the <Role> role at <Company>. We have
            # decided not to move forward with your application." is the
            # standard ATS rejection and it scored `applied`. The verdict
            # sentence matched BOTH of the infinitive twins above — +6, the
            # most a body can earn — and then this one courtesy line took -5
            # off it, leaving rejection 1 against applied 3. The whole verdict
            # turned on the word "careful": `after careful (consideration|
            # review).{0,30}(not|decided|unfortunately)` was the only thing
            # that could pay the -5 back, so "After thoughtful consideration",
            # "After much consideration" and the bare "We have decided not to
            # move forward with your application" all came out `applied` while
            # "After careful consideration" came out `rejection`.
            #
            # WHY DELETION AND NOT A SOFTER WEIGHT, which is #348's reasoning
            # transposed one category over. Note where the -5 could ever
            # matter: only on a message that ALREADY had positive rejection
            # evidence, because a category at 0 is not competing for the win
            # either way. So the subtraction was reachable exactly in the case
            # where it was wrong — a rejection that says thank you.
            #
            # ADDING THE ADJECTIVE WOULD NOT HAVE BEEN THE FIX. Widening the
            # "consideration" pattern past `careful` buys back the -5 for the
            # wordings somebody thought of and leaves every other one paying
            # it. The courtesy opener is not evidence against the verdict that
            # follows it; that is the general statement, and it is what makes
            # the bare form work without naming a single adjective.
            #
            # THE EXPOSURE WAS WORSE THAN THE REVIEW QUEUE. Add the other
            # standard opener — "We have received your application." — and
            # `applied` gains its own +3 (`we (have |'ve )received your
            # application`) for 6 against rejection's 1: 0.90, +0.05 for the
            # ATS relay, 0.95. That is over ``pipeline.AUTO_FILE_GATE`` (0.85),
            # so that rejection did not wait in the queue under a wrong label —
            # it auto-filed as an acknowledgement.
            #
            # The five negatives left above are kept deliberately: each names a
            # DIFFERENT STAGE ("schedule an interview", "pleased to offer"),
            # which is a real argument that this message is not a rejection. An
            # acknowledgement opener is not — it is what job mail of every
            # stage begins with.
            #
            # `tests/test_a_courtesy_opener_is_not_a_verdict.py` is the gate.
            r"\b(unsubscribe|manage preferences|newsletter|digest)\b",
            r"\b(discount|promo(?:tion)?|coupon|sale|limited time offer)\b",
            r"\b(order|purchase|shipment|tracking number)\b",
            r"\b(security alert|verification code|otp|one[- ]time (passcode|password|code)|sign[- ]in|login)\b",
        ],
    ),
    EmailCategory.INTERVIEW: CategoryPatterns(
        strong=[
            r"schedule.{0,20}interview",
            r"interview invitation",
            r"interview.{0,20}(scheduling|schedule|request|invitation)",
            # The trailing purpose clause was mandatory, and real mail does not
            # oblige (#348). "I'd like to set up a 45 minute call to walk
            # through your background" has the whole invitation in it and
            # matched nothing, because `.{0,30}` ran out before "with you" or
            # "discuss". Asking to arrange a call IS the evidence; what the call
            # is for is a detail this category does not need.
            r"(would |'d |)like to (schedule|set up|arrange|book).{0,25}(call|meeting|interview|chat|conversation)",
            r"meet (the )?(hiring )?team",
            r"phone screen.{0,20}(schedule|availability|available|call)",
            r"video (call|interview).{0,20}(schedule|discuss|talk)",
            r"calendly.{0,20}(link|schedule|book)",
            r"zoom (meeting|link|call).{0,20}(discuss|interview)",
            r"discuss.{0,30}(your candidacy|the role|the position|next steps)",
            r"technical (interview|round|screen)",
            r"onsite (interview|visit)",
            r"panel interview",
            r"hiring manager.{0,30}(speak|meet|call|would like)",
            r"recruiter.{0,20}(call|chat|speak).{0,20}(with you|to discuss)",
            r"(your |)availability.{0,30}(for an?|to) (meeting|call|interview)",
            r"please.{0,20}(book|schedule|pick).{0,20}time.{0,20}(interview|call|meet)",
            # The preposition varies and only one spelling was here (#348):
            # "invite you TO interview" was covered, "invite you FOR an
            # interview" — Workable's published invitation, and the single
            # most-reproduced invite copy there is — was not.
            r"invite you (to|for).{0,20}interview",
            r"interviewing.{0,20}candidates",
            # --- THE SCHEDULING FRAME, not the word ---------------------------
            # Every pattern above demands a specific verb+noun collocation, and
            # 92 of the 110 authentic invitations in tests/corpus/mail.py scored
            # ZERO against the whole list — not out-voted, not vetoed: no match
            # at all. That is the same defect EmailCategory.ASSESSMENT records
            # in its bare-noun block ("Everything above requires a verb or a
            # qualifier. Real mail does not oblige"), in the one category where
            # it costs the most: production has never auto-detected an interview.
            #
            # These name the four things an invitation actually DOES — offer a
            # slot, ask for availability, state the state of a booking, name
            # who you will meet — rather than any one template's wording. Each
            # is a frame with a tense, which is what keeps them off the two
            # shapes that talk about interviews without being one: a
            # confirmation promising that "a recruiter WILL reach out to
            # schedule an interview" (future, third party) and an offer opening
            # "thank you for taking the time to interview" (past). A bare
            # `interview (with|is|has been)` was tried first and failed exactly
            # there — it read nine offer letters as interview invitations.
            #
            # Completing the interview-type nouns already begun by `technical
            # interview` / `onsite (interview|visit)` / `panel interview`.
            r"\b(phone|video|final|first|second|initial|intro(ductory)?) (interview|round)\b",
            # SELF-SCHEDULE. `please.{0,20}(book|schedule|pick).{0,20}time.
            # {0,20}(interview|call|meet)` wanted a trailing noun that
            # "please book a time that works for you using the link below"
            # never supplies, and the lead-in "please" that half of them drop.
            r"\b(book|pick|choose|select|schedule|reserve|grab)\s+(a|your|another)\s+(time|slot)\b",
            # AVAILABILITY, asked for. The existing
            # `availability.{0,30}(for an?|to) (meeting|call|interview)` needs
            # the noun; "please share your availability for the coming week"
            # and "would you be available on Tuesday between 2pm and 5pm" are
            # the request with the noun left implicit, which is the normal way
            # to write it. The trailing preposition on the second keeps it off
            # the bare predicative "the link is available".
            r"\b(share|send|provide|confirm|know)\s+your\s+availability\b",
            r"\b(would|are) you (be )?available (on|for|at|any|next|this|to)\b",
            # THE STATE OF A BOOKING — confirmations and reschedules, which are
            # the two commonest interview mails after the invitation itself and
            # had no pattern of their own at all.
            r"interview.{0,40}\b(is|has been|was|will be) (confirmed|scheduled|booked|set|arranged|moved|rescheduled)\b",
            r"\b(moved|rescheduled|changed) your.{0,40}interview\b",
            # ITINERARY. An onsite day lists times and names and may never use
            # the word "interview"; what it always says is who you will meet.
            # `meet (the )?(hiring )?team` wants the literal noun "team".
            r"\b(you|we)('ll| will) meet with\b",
            # The request itself, with the medium left out.
            r"\b(would|'d) like to (speak|talk|chat|meet) with you\b",
        ],
        weak=[
            r"looking forward to (speaking|meeting|connecting) with you",
            r"learn more about (you|your background|your experience)",
            r"excited (about|to discuss).{0,20}(candidacy|application)",
            r"next step.{0,20}interview",
        ],
        negative=[
            # SEVEN NEGATIVES WERE REMOVED HERE (#348), and the argument is the
            # same one for all of them: they were EmailCategory.APPLIED's own
            # positives, copied in to stop an acknowledgement reading as an
            # invitation, and a real invitation opens with them.
            #
            #   thank you for applying · application.{0,20}received ·
            #   application was sent · next steps.{0,20}hear from us ·
            #   your application (for|to) \s+.+\s+at\s+[A-Z]
            #
            # "Thank you for applying to <Company>. Your application for the
            # <Role> position stood out to us and we would like to invite you
            # for an interview" is one sentence that scores applied +6 and,
            # before this, interview −10. Note where the −5s could ever matter:
            # only on a message that ALREADY had positive interview evidence,
            # because a category at 0 is not competing for the win either way.
            # So the subtraction was reachable exactly in the case where it was
            # wrong. That is why deletion is the fix and not a softer weight.
            # The acknowledgements are unharmed — they still win on their own
            # +6, and `applied` measured 45/50 unchanged across the change.
            #
            # `unfortunately` goes for a different reason: it is a hedge, not a
            # decision. "Unfortunately our hiring manager is travelling this
            # week, so we have moved your interview to Tuesday" is a
            # rescheduling apology. REJECTION does not lean on the bare word
            # either — its pattern is `unfortunately.{0,50}(not|won't|will
            # not|unable)`, the word plus an actual negation — so a real
            # rejection still outscores a stray "unfortunately" here.
            # Deliberately NOT removed from the other four categories that
            # carry it: measured, that moved no verdict and added a wrong
            # auto-file.
            r"regret to inform",
            r"not (be )?(moving|proceeding) forward",
            r"decided not to",
            r"position (has been )?filled",
            r"congratulations on completing",
            r"your course",
            r"trial.{0,20}(ended|ends|started)",
            r"free trial",
            r"premium features",
        ],
    ),
    EmailCategory.OFFER: CategoryPatterns(
        strong=[
            r"pleased to (offer|extend).{0,30}(position|role|job)",
            r"offer (you the|letter|of employment)",
            r"extend.{0,20}(job |employment )?offer",
            r"congratulations.{0,30}(job )?offer",
            r"formal (job )?offer",
            r"compensation package.{0,50}(details?|salary|annual)",
            r"(annual|base) salary.{0,20}\$?\d+",
            r"your.{0,20}start date.{0,20}(will be|is)",
            r"accept (this|the|our) (job )?offer",
            r"sign(ing)? bonus.{0,20}\$?\d+",
            r"stock options.{0,30}(vest|grant)",
            r"employment (agreement|contract|offer)",
            r"contingent upon.{0,30}background",
            r"offer (letter |)expires",
            r"please (confirm|accept|sign).{0,30}offer",
            r"offer.{0,30}(position|role) of",
        ],
        weak=[
            r"excited to have you.{0,20}(join|team)",
            r"welcome.{0,10}(to the |)(team|company|aboard)",
            r"joining.{0,20}(our |the )team",
            r"look forward to (you |)(working|joining|starting)",
        ],
        negative=[
            r"unfortunately",
            r"regret to inform",
            r"not (at this time|selected)",
            # BARE `interview` WAS HERE (#348). Every real offer letter opens
            # "thank you for taking the time to interview with the team", so
            # this −5 fired on the offers it was meant to protect: measured, it
            # was the whole reason 9 of the 12 verbal-confirmation offers in
            # tests/corpus/mail.py abstained. It was reaching for the
            # scheduling sense of the word, which `schedule.{0,20}call` below
            # already expresses without catching the past tense.
            r"schedule.{0,20}call",
            r"thank you for applying",
            r"application.{0,20}received",
            r"open.{0,20}account",
            r"premium.{0,20}(free|gift)",
            r"discount|promo|sale|off\b",
            r"subscribe|unsubscribe",
            r"newsletter",
        ],
    ),
    EmailCategory.APPLIED: CategoryPatterns(
        strong=[
            r"application.{0,20}received",
            r"application complete",
            r"thank(s| you) for applying",
            # MICROSOFT'S WORDING, and the reason five of the owner's real
            # applications have never once auto-filed. Nothing above matches
            # either the subject "Thank you for your application!" or the body
            # "Thank you for taking the time to submit your application for
            # Pre-Training (Job number: 200007619)", so a plain, unambiguous,
            # requisition-bearing confirmation scored 0.80 — under the 0.85
            # gate — and sat in the review queue forever. It was reported as
            # "I applied to 4 new Microsoft and a Google application, but when
            # I sync it in the app, I'm not getting anything", and the identity
            # work that followed fixed how those four would be TOLD APART
            # without fixing whether any of them arrives at all.
            #
            # Both are taken from the mailbox, not invented: message ids
            # 1a023464635139a1, 1a023453e5cd359d, 1a023443b385563f,
            # 1a02341f84f11426 and 19ff98d36594296d.
            r"thank(s| you) for (taking the time to )?submit(ting)? your application",
            r"successfully submitted",
            r"confirm(ing)? receipt",
            r"application.{0,30}has been (received|submitted)",
            r"we (have |'ve )received your application",
            r"we received your (job )?application",
            r"application (is|has been) (under|in) review",
            r"reviewing (applications|candidates)",
            r"be in touch (soon|shortly|if)",
            r"next steps.{0,30}hear from us",
            # ANCHORED IN THE SECOND PERSON, and the contiguity is the fix.
            #
            # It was a bare `applied.{0,20}(for|to)...`, which never said WHOSE
            # application it meant. An employer writes "you applied for the X
            # role"; a candidate writes "applied for the X role" — and a reply
            # copies the candidate's subject onto the employer's message, so
            # the pattern read the owner's own words as the employer asserting
            # them. Reported from the real board: a company he had cold-emailed
            # sat in the review queue at 0.70, on this one match, because their
            # autoresponder quoted his subject back. Nothing else in the
            # message contributed at all.
            #
            # THE PRONOUN MUST BE IN THE SAME CLAUSE, not merely nearby.
            # Outreach prose says "you" and "your" constantly ("…what your team
            # is building, applied for the X role"), so a proximity anchor is
            # defeated by the very text it defends against. Requiring "you"
            # (optionally "you've" / "you have recently") to run straight into
            # "applied" refuses the comma splice that a first-person pitch
            # always carries, and keeps the phrasing employers actually use.
            #
            # `your` is deliberately NOT in the alternation: "your application
            # for <Role> at <Company>" is a THREAD SUBJECT every reply
            # inherits, which #348 measured and demoted to `weak`. Admitting it
            # here would quietly promote a subset of it back to `strong`.
            #
            # Measured before the change: this pattern matches 0 of the 17,260
            # independent-corpus cases, and its sibling above matches 1,695.
            # The corpus can therefore neither justify nor refute this edit —
            # `tests/test_an_autoresponder_to_outreach_is_not_an_application.py`
            # is the gate that can actually fail on the defect.
            r"\byou(?:'ve|’ve)?(?:\s+(?:have|had|just|recently|successfully|now)){0,2}"
            r"\s+applied\b.{0,20}(for|to).{0,40}(position|role|job)",
            r"application was sent to",
            r"application.{0,20}is in",
        ],
        weak=[
            # WEAK AND NOT STRONG, for the same reason as the entry below it,
            # and measured rather than assumed. "Thank you for your
            # application" is a COURTESY OPENER, not a verdict: it prefixes
            # rejections, interview invitations and offers exactly as happily
            # as it prefixes confirmations. Tried at `strong` first, where a
            # subject match is worth +6 and swamps whatever the body says — it
            # turned a genuine offer, a genuine interview invitation and a
            # genuine assessment request all into `applied`. At weak it
            # contributes without deciding, which is what a courtesy is worth,
            # and Microsoft's confirmation still clears the gate because its
            # BODY carries the specific act ("submit your application").
            r"thank(s| you) for your application",
            # DEMOTED FROM `strong` (#348). "Your application for <Role> at
            # <Company>" is a THREAD SUBJECT, not a verdict: it says which
            # application the mail concerns, and every reply in the thread
            # inherits it. As a strong SUBJECT match it was worth +6 — double
            # weight, the highest score any single pattern can earn — so a
            # recruiter replying "Re: Your application for Backend Engineer at
            # Blackmoor Analytics" to invite the candidate to an interview was
            # scored as an acknowledgement, at 0.95, and auto-filed as one.
            # Weak is the honest weight for "this thread is about an
            # application". Genuine acknowledgements are untouched: they carry
            # `application.{0,20}received`, `thank(s| you) for applying` and
            # `successfully submitted` of their own, and `applied` measured
            # 45/50 both before and after this move.
            r"your application for\s+.+\s+at\s+[A-Z]",
            r"your application to\s+.+\s+at\s+[A-Z]",
            # DEMOTED FROM `strong` (#451), and it is the THIRD member of the
            # family #348 and #441 already moved. This says WHICH application
            # the mail is about; it says nothing about what happened to it.
            # Every category's mail carries it, because "regarding your
            # application for the Backend Engineer position" is simply how a
            # courteous recruiter names the thread they are answering.
            #
            # At `strong` it was +3, which is exactly what a REPORT of a later
            # stage earns. An offer reading "We are delighted to extend you an
            # offer to join us... This concerns your application for the
            # Backend Engineer position" therefore scored applied 3, offer 3 —
            # a dead tie, broken by `EmailCategory` declaration order, which
            # puts `applied` first. The board said "acknowledged" about an
            # offer, and nothing about the message decided it.
            #
            # Measured across the 17,260-case independent corpus: it produced
            # 109 positive-score ties, ALL of them a reference against a report
            # (94 applied/offer, 15 applied/rejection), and enum order got all
            # 109 wrong. At `weak` the reference contributes +1 — which is what
            # naming a thread is worth — and the report keeps its margin.
            #
            # The cost is named rather than buried: 135 messages that used to
            # arrive on the board by themselves now wait in the review queue.
            # DROPPED goes to 0 and LOST does not move, so nothing became
            # unreachable; what changed is that the product asks instead of
            # guessing. See the PR for the full before/after table.
            r"application.{0,20}(for|to).{0,40}(position|role|job)",
            r"thank you for your interest",
            r"interested in.{0,30}(position|role|opportunity)",
            r"review your (application|resume|qualifications)",
            r"hearing from us",
            r"reach out.{0,20}updates",
        ],
        negative=[
            r"unfortunately",
            r"pleased to offer",
            # `schedule.{0,20}interview` WAS HERE (#348), and it is the same
            # cross-class disambiguator, in the same direction, as the six this
            # change removed from INTERVIEW.negative. An acknowledgement that
            # says what happens next legitimately contains it — "if your
            # background matches what we are looking for, a recruiter will
            # reach out to schedule an interview" — and that sentence is a
            # promise, by a third party, in the future tense. It arranges
            # nothing. The −5 could only ever subtract from a message that
            # already had acknowledgement evidence, which is precisely where
            # subtracting is wrong; measured, it was the whole of `applied`'s
            # error on the 400-case corpus, 45/50 → 50/50, with no other class
            # moving. The scheduling sense it was reaching for still belongs to
            # INTERVIEW, which scores it as a positive.
            r"regret",
            r"not (moving|proceeding)",
            r"move(d)? forward with other",
            r"congratulations on completing",
            r"your course",
            # A CONTACT-FORM NEGATIVE WAS TRIED HERE AND DELIBERATELY NOT
            # SHIPPED — written down so it is not re-proposed as new.
            #
            # `thank(s| you) for (getting in touch|reaching out|contacting)`
            # acknowledges a MESSAGE, not an application, and it looked like
            # the obvious second half of the anchor above. Two measurements
            # stopped it. In `_NOISE_NEGATIVES` it is nearly inert: the careers
            # autoresponder it was written for carries "reviewing
            # applications", which is a strong BODY match, so `has_strong_body`
            # exempts the negative in exactly the case it was meant to catch.
            # Out of `_NOISE_NEGATIVES` it fires, and then a weak-but-genuine
            # confirmation that opens with the same courtesy — the Notion shape
            # already sits at 5, one point under the gate — goes to OTHER and
            # is dropped SILENTLY, which is the worst failure this pipeline has.
            #
            # Neither risk is measurable today: the phrase family appears 0
            # times in the 17,260-case independent corpus and once in the
            # owner's whole stored mailbox. So the rule ships nothing until the
            # corpus grows an outreach-autoresponder family to judge it
            # against; #521 carries it.
            r"\b(unsubscribe|manage preferences|newsletter|digest)\b",
            r"\b(discount|promo(?:tion)?|coupon|sale|limited time offer|flash sale)\b",
            r"\b(shop|buy|cart|checkout|order|purchase|shipment|tracking number)\b",
            r"\b(security alert|verification code|otp|one[- ]time (passcode|password|code)|sign[- ]in|login)\b",
        ],
    ),
    EmailCategory.PENDING_APPLICATION: CategoryPatterns(
        strong=[
            r"complete your application",
            r"finish your application",
            r"continue your application",
            r"application.{0,20}(incomplete|not complete)",
            r"your application is incomplete",
            # {0,60} AND NOT {0,30}, because the gap sits where the EMPLOYER'S
            # NAME goes. "[Action Required] Your <Employer> Application" is one
            # sentence, and at 30 it fired for Stripe and Notion (gap 12) and
            # not for "Hollowburygrove Analytics" (31) or "Bramfieldstead
            # Analytics" (30). A rule whose verdict depends on how long a
            # company's name is has no semantics; 60 fits a real employer name
            # and the phrase still has to be one clause.
            r"action required.{0,60}(application|submit)",
            # `(verify|confirm) your e.?mail` WAS HERE (#464), and it was the
            # only lifecycle pattern in this file that required no job-related
            # evidence of any kind. In a subject that is +6 — score 6, margin 6,
            # confidence 0.90 — which clears AUTO_FILE_GATE, so every product
            # that sends a double-opt-in became a job application with a card on
            # the board. Measured on a real mailbox: of the four messages this
            # category auto-filed, THREE were SaaS signup confirmations, and one
            # of those minted an employer that does not exist out of its sender
            # domain (#493).
            #
            # It is also redundant for the family it was added for. #464's own
            # table records that its OTHER change — the `action required` window
            # 30 → 60, directly above — already moved the reported message off
            # the auto-file gate. Re-measured here with nothing else changed:
            # both #459 cases keep auto-filing from the subject pattern alone,
            # and all three product-signup messages fall to `other` at 0.50.
            #
            # What this costs is written down so it is not re-fought: the 58
            # `observed-pending` corpus cases return, as `applied` 0.75. That is
            # UNDER the gate, so they are held for a person rather than filed —
            # a wrong suggestion in the queue, not a rival card on the board.
            # SPLIT stays 0 either way; the gap widening owns that, and the two
            # were always separate fixes.
            #
            # Do not "fix" this with a veto list. The disambiguator for a signup
            # confirmation lives in account vocabulary elsewhere in the body,
            # and genuine ATS verification mail carries the same words ("create
            # your candidate account"). A job-anchor requirement fails too: the
            # message that prompted #493 reads "you signed up for an
            # application", and that phrase is inside the ~200-character snippet
            # production actually classifies.
            r"complete additional steps",
            r"additional information.{0,20}(required|needed)",
            r"please complete.{0,30}(application|profile)",
            r"submit your application to be considered",
            r"before we can review your application",
        ],
        weak=[
            r"missing information",
            r"update your application",
            r"continue where you left off",
            r"application deadline.{0,20}(approaching|soon)",
        ],
        negative=[
            r"application.{0,20}received",
            r"thank(s| you) for applying",
            r"interview invitation",
            r"pleased to offer",
            r"regret to inform",
            r"not moving forward",
        ],
    ),
    EmailCategory.ASSESSMENT: CategoryPatterns(
        strong=[
            r"(technical|coding|take.?home).{0,20}(assessment|challenge|test|exercise)",
            r"complete.{0,30}(assessment|challenge|test)",
            r"hackerrank",
            r"codility",
            r"codesignal",
            r"leetcode",
            # HireVue also runs recorded/live interviews, but both senses land
            # on ApplicationStatus.INTERVIEWING, so the vendor name is safe to
            # treat the way hackerrank/codility already are.
            r"hirevue",
            r"take.?home (assignment|project|exercise|task|round)",
            r"coding (exercise|test|challenge)",
            r"online (assessment|test)",
            r"skills (assessment|test)",
            r"deadline.{0,30}(assessment|test|challenge)",
            r"time limit.{0,20}(hour|minute)",
            # --- the noun on its own ---------------------------------------
            # Everything above requires a verb ("complete", "take") or a
            # qualifier ("technical", "online"). Real mail does not oblige:
            # "[Action Required] Your Roblox Assessments Invitation" matched
            # none of them and fell through to `other` at 0.50. These patterns
            # fire on the noun plus the shape of an invitation. What keeps them
            # honest is `veto` below, not narrowness — the senses of
            # "assessment" that are not a candidate test are named there.
            r"assessments?\s+(invitation|invite)\b",
            r"invitation\s+(to|for)\s+[\w \-]{0,25}assessments?\b",
            r"assessments?\s+(link|reminder|instructions|deadline|details)\b",
            r"assessments?\s+(is|are)\s+(ready|available|waiting|live|open)\b",
            # The bare noun, hyphenated only: "take home" unhyphenated is a
            # verb phrase ("take home a free gift") and far too common.
            r"\btake-home\b(?!\s+(pay|message|gift|dose|salary))",
        ],
        weak=[
            r"next step.{0,30}(assessment|test)",
            r"assessment follow-?up",
            r"complete.{0,30}next",
            r"evaluation",
            r"demonstrate.{0,20}skills",
        ],
        negative=[
            r"unfortunately",
            r"regret",
            r"offer",
            r"not (moving|proceeding)",
        ],
        veto=[
            # "assessment" is an ordinary business noun. In these senses the
            # mail is never a candidate test, and a -5 negative cannot stop it:
            # "Complete your self-assessment before your review" scored +6 from
            # `complete.{0,30}(assessment|challenge|test)` and classified as
            # assessment at 0.90 before this list existed.
            r"\brisk assessment",
            r"\bself[- ]assessments?\b",
            r"\bneeds assessment",
            r"\bimpact assessment",
            # An HR review cycle, not a candidate test.
            r"\bperformance assessment",
            r"\bassessments? of damages",
            r"\b(damage|vulnerability|security|credit|tax|property|environmental|medical|clinical)\s+assessment",
            r"take.?home\s+pay",
            # Content ABOUT assessments, rather than an invitation to sit one.
            r"\bwebinar\b",
            r"\bassessments? quiz\b",
            # NOT here, on purpose: "newsletter", "digest", "coupon",
            # "flash sale", "limited time offer", "unsubscribe", "manage
            # preferences". Marketing vocabulary already belongs to the content
            # guard that runs BEFORE this layer
            # (hybrid.NON_APPLICATION_PATTERNS, applied in
            # `_forced_other_reason`), which requires two such signals — or one
            # plus a marketing sender — and lets a lifecycle phrase override it.
            # Repeating those words here, at a threshold of one and with no
            # override, would be a second marketing guard that disagrees with
            # the first. Worse, veto patterns match the BODY as well as the
            # subject, and a legitimate ATS assessment invitation routinely
            # carries "unsubscribe" or "you subscribed to our newsletter" in its
            # footer: a body-matched `newsletter` veto would suppress exactly
            # the mail this category exists to catch. See
            # test_ats_footer_does_not_veto_a_real_invitation.
        ],
    ),
    EmailCategory.FOLLOW_UP: CategoryPatterns(
        strong=[
            r"following up.{0,30}(application|interview|position|role)",
            r"check(ing)? in.{0,30}(application|status|interview)",
            r"any update(s)?.{0,20}(application|interview|position)",
            r"status (of|on).{0,20}(your |my )application",
            r"wanted to (follow up|check in).{0,30}(application|interview|candidacy|position|role)",
            r"reach(ing)? out.{0,30}(application |interview )?(status|update)",
            r"wondering.{0,30}(application|interview).{0,20}(status|update|progress)",
        ],
        weak=[
            r"circling back.{0,30}(application|interview|position|role)",
            # Demoted from `strong`. On its own the compound noun says only
            # that a thread is being continued — scheduling mail, recruiter
            # nudges and rejections all use it — yet as a strong SUBJECT match
            # it was worth +6, i.e. 0.90 confidence and an auto-file, from one
            # word and no other evidence whatsoever. Every pattern above it
            # names what is being followed up on; this one does not, so it is
            # weak evidence and now scores like it. The phrasal verb
            # ("following up on your application") is unaffected: it never
            # matched this pattern, it matches the first `strong` entry.
            r"follow-?up",
        ],
        negative=[
            r"unfortunately",
            r"offer",
            r"schedule.{0,20}interview",
            r"regret",
            r"application.{0,20}received",
            r"\b(unsubscribe|manage preferences|newsletter|digest)\b",
            r"\b(discount|promo(?:tion)?|coupon|sale|limited time offer|flash sale)\b",
            r"\b(order|purchase|shipment|tracking number)\b",
            r"\b(security alert|verification code|otp|one[- ]time (passcode|password|code)|sign[- ]in|login)\b",
        ],
        # A stated hiring decision makes this category WRONG, not merely less
        # likely — the exact bar the veto tier exists for. A -5 negative cannot
        # do it: "Following up on your application" is a genuine strong subject
        # match at +6, so a rejection body scoring +6 of its own only ties it,
        # and a tie is decided by enum order at confidence 0.60. Vetoing gives
        # the rejection the whole margin, which is what it has earned.
        #
        # This IS the decision block from EmailCategory.REJECTION.strong,
        # repeated verbatim. See the note above PATTERNS for why it is copied
        # rather than shared: three files count these as literals. Change one,
        # change the other.
        veto=[
            r"regret to inform",
            r"decided not to proceed",
            r"not to (move|proceed|go) forward",
            r"not to (move|proceed|go) forward.{0,30}(application|candidacy)",
            r"not (be )?(moving|proceeding) forward",
            r"(won't|will not|not) (be )?(proceeding|continuing) with",
            r"(won't|will not|not) (be )?(proceeding|continuing) with.{0,30}(application|candidacy)",
            r"will not be moving forward.{0,30}(application|candidacy)",
            r"not.{0,20}moving forward.{0,20}(application|your candidacy)",
            r"(move|moved|moving) forward with (a |an |the )?(other|another|different) (candidate|applicant)",
            r"(decided|chosen|elected|will be|are)\b.{0,20}(move|moving) forward with (a |an |the )?(other|another|different) (candidate|applicant)",
            r"pursu(e|ing) other (candidates|applicants)",
            r"(decided|chosen|elected|opted) to pursue other (candidates|applicants)",
            r"not (been )?selected.{0,30}(position|role|interview)",
            r"\bnot been selected\b",
            r"\byou (have|were)\b.{0,10}not (been )?selected\b",
            r"not (be )?able to offer.{0,20}(position|role|interview)",
            r"unable to (offer|extend).{0,25}(position|role|offer|interview|opportunity)",
            r"unable to (offer|extend) you\b",
            r"unable to (proceed|continue|move forward) with",
            r"unable to (proceed|continue|move forward) with.{0,25}(application|candidacy|process)",
            r"(won't|will not) be advancing.{0,20}(application|candidacy)",
            r"not (be )?advancing (your|the) (application|candidacy)",
            r"position has been filled",
            r"we('ve| have) decided to go in (a )?different direction",
            # --- end of the block copied from REJECTION.strong ---------------
            #
            # A SECOND GROUP, not part of that copy, and it must not be mirrored
            # back into REJECTION (#348). Same argument, other direction: a
            # message that ARRANGES something is not a nudge either. A recruiter
            # replying on the application thread — subject "Following up on your
            # application - <Company>", body "please share your availability" —
            # is a genuine strong subject match for this category at +6, which
            # beat the interview evidence in the body and filed the mail as
            # `follow_up` at 0.90.
            #
            # That is the worst place in the system to lose a message: unlike a
            # wrong lifecycle verdict, `follow_up` reaches neither
            # `pipeline._qualifies_for_hard_row` nor `pipeline.collect_review_items`,
            # so the mail is not misfiled — it is never persisted at all and the
            # user never sees it. The header comment on this file records the
            # same disappearance happening to a real rejection.
            #
            # These are INTERVIEW.strong scheduling frames, and only the ones
            # that state an arrangement rather than describe one.
            r"invite you (to|for).{0,20}interview",
            r"\b(book|pick|choose|select|schedule|reserve|grab)\s+(a|your|another)\s+(time|slot)\b",
            r"\b(share|send|provide|confirm|know)\s+your\s+availability\b",
            r"\b(would|are) you (be )?available (on|for|at|any|next|this|to)\b",
            r"(would |'d |)like to (schedule|set up|arrange|book).{0,25}(call|meeting|interview|chat|conversation)",
        ],
    ),
}

# Known ATS (Applicant Tracking System) sender domains.
#
# BEFORE ADDING AN ENTRY, know what it now costs. Since #166 this list does not
# only grant the +0.05 confidence bonus below — ``cloud.pipeline`` reads it to
# decide which mail is FLOATED INTO THE REVIEW QUEUE instead of dropped. A loose
# entry used to buy a harmless nudge; it now puts messages in front of the user.
# And the match is an unanchored substring, so it is easy to be loose by
# accident: ``"hire.com" in "newhire.company.com"`` is True. Keep entries
# specific enough that only the relay can match them. That example is written in
# the past tense on purpose — ``hire.com`` was on this list until #348 and is
# the reason the sentence exists; see the note where it used to sit.
#
# Matched as a SUBSTRING of the sender's domain, so an entry has to be the part
# the relay actually shares. That is what made ``greenhouse.io`` useless for two
# years: Greenhouse's transactional relay sends from ``us.greenhouse-mail.io``,
# which does not contain the string ``greenhouse.io`` at all. Greenhouse is the
# most common ATS in this corpus (15 of the 51 stored messages) and had never
# once received the +0.05 ATS bonus. ``greenhouse.io`` stays — it is the job
# board's own sender — and ``greenhouse-mail.io`` covers every regional relay
# (``us.``, ``eu.``, …).
#
# ``ats.rippling.com`` is deliberately narrow. Rippling is a payroll/HR product
# as well as an ATS, and a bare ``rippling.com`` would sweep in payroll mail
# that has nothing to do with an application.
#
# Two other modules already knew both of these — ``tracking/extractor.py`` maps
# ``greenhouse-mail.io`` and ``rippling.com`` to employers — which is how the
# gap survived: nothing compared the two lists.
ATS_DOMAINS = [
    "greenhouse.io",
    "greenhouse-mail.io",
    "lever.co",
    "myworkday.com",
    "workday.com",
    "icims.com",
    "jobvite.com",
    "smartrecruiters.com",
    "taleo.net",
    "successfactors.com",
    "breezy.hr",
    "ashbyhq.com",
    "applytojob.com",
    # ``hire.com`` WAS HERE and is gone (#348). It was the shortest entry on the
    # list and the one the comment above holds up as the example of being loose
    # by accident: it is what made ``sohire.comcast.net`` read as an ATS relay
    # under the old containment match. No ATS was found that sends from it, and
    # the domain it was presumably reaching for — Lever's ``hire.lever.co`` — is
    # already covered by ``lever.co``, both before and after anchoring. Nothing
    # in the tree depended on it: the only senders that matched through it are
    # ``…@hire.lever.co``, which still match, and the one lookalike in
    # ``tests/test_ingestion_hole_166.py`` that is asserted NOT to be an ATS.
    "recruitee.com",
    "ats.rippling.com",
]


# =============================================================================
# What the message is ASSERTING, as opposed to what it merely contains
# =============================================================================
#
# Every pattern in this module answers "does this phrase appear". None of them
# ask WHERE it appears, and a phrase can appear in a message without the sender
# asserting it. The clearest case, and the one that cost the owner four real
# applications on 2026-08-21:
#
#     Thank you for taking the time to submit your application for Software
#     Engineer II (Job number: 200045485). ... If you see the job moved to an
#     inactive state, that means the position is either no longer open, you
#     withdrew from consideration, or you were not selected for the role.
#
# Nothing has been decided. It is a confirmation explaining what the dashboard
# would show if things later went badly. Two STRONG rejection patterns fired on
# "you were not selected for the role", the message scored ``rejection`` at
# 0.60, and — being under ``pipeline.REVIEW_FLOOR`` from a sender that is not a
# known ATS relay — it was discarded with no card, no queue entry and no trace.
# Four of them, at one employer, inside five minutes.
#
# So the body is masked ONCE, here, and every pass in ``classify`` sees the
# masked text. Doing it per-pass is how the strong/weak passes and the veto pass
# drift apart on a later edit, and a category that cannot be scored by a phrase
# but can still be VETOED by it is a bug waiting on the next commit.
#
# ONE HAZARD LOOKED FOR AND NOT FOUND, recorded so nobody spends the afternoon
# on it twice. The real mail puts a tracking link immediately before the
# conditional:
#
#     ... Action Center[](https://microsoft.eightfold.ai/vsimp?d=.eJwViTEOgCAQ
#     wP5ys5LzDhCY_...Lj6ZStc7Wcyj5J3xAbkRi1vnryo&n=https%3A%2F%2F...). If you
#     see the job moved to an inactive state, ...
#
# That base64 is full of dots, so the obvious worry is that splitting sentences
# shatters it and separates the ``If`` from the phrase it governs. A first
# version therefore stripped URLs before splitting, with a confident comment
# saying why.
#
# It was removed. Mutation testing showed no test could tell whether the strip
# was there, and the test written to earn it then reported that a bare-dot split
# ALSO keeps the marker and the phrase in one fragment — there is no dot between
# them. The hazard is not real for this shape. Unproven machinery with a
# confident comment beside it is precisely how this codebase has shipped checks
# that cannot fail, so the machinery went and this note stayed.
#
# The boundary test still requires whitespace and a following capital. That is
# ordinary care against abbreviations, not a defence against the above, and it
# is not claimed as one.
#
# SCOPE, deliberately narrow:
#   - BODY ONLY. A subject is short and a conditional subject is not a real
#     shape; masking there would buy nothing and risk a lot.
#   - The mask runs from the conditional marker to the END OF ITS SENTENCE, not
#     over the whole sentence. "You were not selected for the role, and if you
#     would like feedback please ask" is a real rejection whose verdict sits
#     BEFORE the marker, and it must survive.

#: Markers that open a hypothetical scope running to the end of the sentence.
#: Kept small on purpose. Each one earns its place by appearing in real mail
#: ahead of a lifecycle phrase that is not being asserted.
_CONDITIONAL = re.compile(
    r"\b(?:if|should you|in the event(?:\s+that)?|unless|in case)\b",
    re.IGNORECASE,
)

#: Sentence boundary, in two deterministic steps rather than one regex.
#:
#: The obvious single pattern is ``(?<=[.!?])\s+(?=["\u201c(A-Z])``. It is a
#: POLYNOMIAL REDOS and CodeQL is right to flag it: the greedy ``\s+`` is
#: followed by a lookahead that can fail, so on a run of N spaces the engine
#: retries every shorter run at every starting offset — quadratic, on a body
#: that arrives from whoever emailed the user.
#:
#: Splitting on ``\s+`` with nothing after it cannot backtrack (a greedy run
#: with no following constraint always succeeds at its maximum), and the
#: capital-letter test then happens in ordinary code. Same boundaries, linear.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_STARTS_SENTENCE = re.compile("^[\"\u201c(A-Z]")


def _sentences(body: str) -> list[str]:
    """Split ``body`` into sentences without a backtracking regex.

    A fragment that does not begin like a sentence is glued back onto the one
    before it, which is what the old lookahead expressed: an abbreviation, a
    version number or a dot inside a URL is not a boundary.
    """

    out: list[str] = []
    for part in _SENTENCE_SPLIT.split(body):
        if out and not _STARTS_SENTENCE.match(part):
            out[-1] = f"{out[-1]} {part}"
        else:
            out.append(part)
    return out


#: Where a reply stops speaking and starts repeating.
#:
#: Three shapes, and all three are anchored to the START OF A LINE, which is
#: what keeps them from firing inside prose. "On Thursday, the team wrote:" is
#: an attribution when it opens a line and a sentence fragment when it does not,
#: and a rejection that reads "we wrote to you on Tuesday" must not lose its
#: verdict to a loose match.
#:
#:   · the attribution line every major client writes above the quote
#:     ("On Tuesday, X wrote:", "On 21 Aug 2026 at 09:14, X <a@b> wrote:")
#:   · Outlook's and Apple Mail's divider ("-----Original Message-----",
#:     "Begin forwarded message:")
#:   · the first ``>`` quote line, for clients that write no attribution at all
_QUOTE_BOUNDARY = re.compile(
    r"""^(?:
          [ \t]*>                                  # a quoted line
        | [ \t]*-{2,}\s*(?:original\s+message|forwarded\s+message)\s*-{2,}
        | [ \t]*begin\s+forwarded\s+message\s*:
        | [ \t]*on\b[^\n]{0,200}?\bwrote\s*:    # attribution
        | [ \t]*from\s*:[^\n]{0,200}\n[ \t]*sent\s*:   # Outlook header block
    )""",
    re.IGNORECASE | re.MULTILINE | re.VERBOSE,
)

#: Below this many characters, a reply's own words are treated as no words at
#: all and the quote is scored after all.
#:
#: NOT a tuning knob — it is the answer to "what does a bare forward mean?".
#: Someone forwarding a rejection to themselves with "fyi" above it has written
#: nothing the classifier can read, and scoring the eleven characters they did
#: write means scoring nothing, which abstains on a message whose verdict is
#: sitting right there in the quote. So a reply that adds no substance falls
#: back to the whole body, and only a reply that SAYS something gets to speak
#: over its history.
_MIN_ASSERTED_CHARS = 40

#: A subject that belongs to the CONVERSATION rather than to this message.
#:
#: Mail clients keep the original subject on every reply, so "Re: Thank you for
#: applying to X" is what an interview invitation, a rejection and a scheduling
#: note in that thread all look like from the outside. Scoring it at subject
#: weight tells the classifier the message is a confirmation before it has read
#: a word the sender wrote.
#: Bounded on every quantifier, and the optional counter carries its own
#: trailing space. The obvious form is ``^\s*(?:re|fw|fwd)\s*(?:\[\d+\])?\s*:``
#: and it is a polynomial ReDoS: when the counter does not match, the two
#: ``\s*`` sit adjacent and a run of N spaces after "Re" is re-partitioned at
#: every offset. Subjects come from whoever emailed the user. CodeQL caught
#: this one; the same reasoning is already written up for the sentence splitter
#: in the TypeScript port.
_REPLY_SUBJECT = re.compile(
    r"^[ \t]{0,8}(?:re|fw|fwd)[ \t]{0,8}(?:\[\d{1,4}\][ \t]{0,8})?:",
    re.IGNORECASE,
)


def strip_quoted_history(body: str) -> str:
    """Return only the part of ``body`` this message wrote itself.

    ISSUE #441. The scoring walk had no notion of whose words it was reading,
    so a follow-up that quoted its own confirmation scored the QUOTE: 200 of
    200 such messages in the adversarial corpus read as ``applied``, and an
    interview invitation never advanced the card it belonged to. It is also the
    mechanism behind #417 — a withdrawal that quotes the offer it is
    withdrawing scores the offer.

    WHAT THIS MUST NOT BREAK, and it is the reason the function is separate
    from the caller: the quote is often the only place the ROLE appears. A
    reply saying "we would love to set up a conversation" names no job. Role
    and requisition extraction read the raw snippet through
    ``pipeline.role_from_message`` and never come through here, so identity
    keeps the whole message and only SCORING loses the history. Anything that
    moves extraction behind this seam re-breaks grouping to fix classification.

    Returns ``body`` unchanged when there is no quote, and when what remains is
    too thin to be an assertion (see :data:`_MIN_ASSERTED_CHARS`).

    THE FLOOR IS NOT THE ONLY READER OF THAT SPAN. ``own_text_span`` below
    returns it whether or not it clears the floor, because "which words get
    SCORED" and "which words did the sender WRITE" are different questions and
    #417 lives exactly where they differ.
    """

    own = own_text_span(body)
    return body if own is None or len(own) < _MIN_ASSERTED_CHARS else own


def own_text_span(body: str) -> str | None:
    """The words this message wrote ABOVE its quoted history — floor or no floor.

    ``None`` when there is no quote at all, which is a different answer from
    ``""`` (a reply that quoted something and wrote nothing above it) and both
    are different from a span too short to be scored.

    ISSUE #417, the part that survived #441. ``strip_quoted_history`` refuses
    to strip below :data:`_MIN_ASSERTED_CHARS`, so the whole body — quote
    included — goes to the scorer. That is right for "fyi" over a forwarded
    rejection and wrong for "We must withdraw the offer.", which is 27
    characters. The floor cannot tell those apart because it counts characters,
    and nothing else was looking at the span at all. This is what looks.

    Deliberately NOT a lower floor: the floor is doing its job, which is to
    stop a substanceless reply from being reduced to nothing. Lowering it moves
    every short reply in the corpus; this moves only the ones whose own words
    contradict the verdict their quote produced.
    """

    if not body:
        return None
    marker = _QUOTE_BOUNDARY.search(body)
    if marker is None:
        return None
    return body[: marker.start()].strip()


def asserted_text(body: str) -> str:
    """Return ``body`` with the spans it does not assert removed.

    Two things now, in order: history this message merely quotes, then text
    inside a conditional clause. A caller should be reading "the part of the
    message the sender is claiming", not "the body minus if-clauses".

    Quotes are removed FIRST and the order matters: a conditional inside quoted
    history is not this message's hypothesis and should never have been walked
    sentence by sentence in the first place.

    Idempotent, and returns text unchanged when it holds neither.
    """

    if not body:
        return body

    body = strip_quoted_history(body)

    out: list[str] = []
    for sentence in _sentences(body):
        marker = _CONDITIONAL.search(sentence)
        # Keep everything up to the marker; the marker's scope runs to the end
        # of the sentence, so the remainder is hypothetical.
        out.append(sentence[: marker.start()] if marker else sentence)
    return " ".join(out)


# =============================================================================
# Which negatives a strong signal may outrank
# =============================================================================
#
# The ``negative`` lists hold two different kinds of claim, and only one of them
# should ever lose to strong positive evidence.
#
# GENRE FILTERS say "this is not job mail at all" — a receipt, a promotion, a
# security alert, a mailing list. They are listed here.
#
# SEMANTIC REFUTATIONS say "this IS job mail, and it is not THIS category":
# ``unfortunately`` and ``regret to inform`` on ``offer``, ``pleased to offer``
# on ``applied``, ``not (moving|proceeding)`` on ``applied``. These are the
# whole reason a rescission does not read as an offer, and they must keep their
# full weight however strong the positive evidence is. Letting a strong match
# outrank them takes c0029 in the corpus — "we must withdraw the offer of
# employment extended to you" — from wrong-and-uncertain to wrong AND
# AUTO-FILED, which is strictly worse than the bug being fixed. Measured, not
# assumed; see issue #417.
#
# WHY A SEPARATE FROZENSET RATHER THAN A FIELD ON ``CategoryPatterns``. Three
# things read the PATTERNS literals and cannot see through a restructure:
# ``scripts/readme_facts.py`` parses this file statically for the counts the
# README and two web surfaces publish, ``ml/demo/space/.../rules.py`` is a
# byte-identical copy, and ``apps/web/lib/demo/rules.json`` enumerates every
# pattern for the browser port. Naming the subset alongside leaves all three
# untouched.
#
# Membership is by EXACT pattern string, so a pattern that is edited in PATTERNS
# and not here silently returns to full weight rather than silently keeping the
# exemption. That is the safer direction to fail.
_NOISE_NEGATIVES = frozenset(
    {
        r"\b(unsubscribe|manage preferences|newsletter|digest)\b",
        r"subscribe|unsubscribe",
        r"newsletter",
        r"\b(discount|promo(?:tion)?|coupon|sale|limited time offer|flash sale)\b",
        r"\b(discount|promo(?:tion)?|coupon|sale|limited time offer)\b",
        r"discount|promo|sale|off\b",
        r"\b(order|purchase|shipment|tracking number)\b",
        r"\b(shop|buy|cart|checkout|order|purchase|shipment|tracking number)\b",
        r"\b(security alert|verification code|otp|one[- ]time (passcode|password|code)|sign[- ]in|login)\b",
        r"open.{0,20}account",
        r"premium.{0,20}(free|gift)",
        r"your course",
    }
)


def is_ats_sender(sender_email: Optional[str]) -> bool:
    """Is this address a known Applicant Tracking System relay?

    The single definition of "ATS sender". :meth:`RulesClassifier.classify` uses
    it for the +0.05 confidence bonus and ``cloud.pipeline.collect_review_items``
    uses it for the review-queue floor (#166), and those two must never disagree
    about which senders are ATS relays — a floor that fires on a sender the
    classifier does not recognise, or the reverse, is a bug nobody could read off
    either call site.

    The match is ANCHORED: a sender qualifies only when its domain IS a listed
    domain or is a proper subdomain of one (#260). Do not "simplify" this back
    to ``ats in domain`` — unanchored containment matched an ATS name anywhere
    in the host, so ``greenhouse.io.mailgun.net``, ``notlever.co.example.com``
    and (through the shortest entry, ``hire.com``, which #348 has since removed
    from the list entirely) ``sohire.comcast.net`` all
    read as ATS relays. Since #252 that answer decides ROUTING and not just a
    score, so a domain anyone can register was enough to reach the owner's
    review queue — and on the 0.80 rung the +0.05 bonus lands exactly on
    ``AUTO_FILE_GATE`` (0.85), the threshold at which the pipeline MAY assert a
    hard status. (Filing also needs a named employer, so the gate is necessary
    and not sufficient; the queue entry needed nothing else.)

    The argument is a bare address, never a raw ``From`` header: every ingestion
    path parses one first (``cloud/gmail_client.py``, ``email_clients/gmail.py``
    and ``email_clients/icloud.py`` all go through ``email.utils.parseaddr``).
    That matters here because containment tolerated the trailing ``>`` of
    ``… <no-reply@us.greenhouse-mail.io>`` and anchoring does not.

    Anchoring makes two list entries load-bearing that containment had made
    redundant: ``myworkday.com`` does not end with ``.workday.com`` and
    ``greenhouse-mail.io`` is not a suffix of ``greenhouse.io``. Both are real
    relays; neither may be deduplicated away. ``ats.rippling.com`` stays listed
    as the full host on purpose — bare ``rippling.com`` is payroll mail.
    """

    if not sender_email or "@" not in sender_email:
        return False
    domain = sender_email.lower().rsplit("@", 1)[-1]
    return any(domain == ats or domain.endswith(f".{ats}") for ats in ATS_DOMAINS)


def sender_domain(sender_email: Optional[str]) -> str:
    """The lowercased domain of an address, or ``""`` when there is not one.

    The argument is a bare address, never a raw ``From`` header — every
    ingestion path parses one with ``email.utils.parseaddr`` first. A value
    with no ``@`` has no domain and gets ``""``, which every predicate below
    reads as "no match" rather than as a wildcard.
    """

    if not sender_email or "@" not in sender_email:
        return ""
    return sender_email.lower().rsplit("@", 1)[-1].strip()


def domain_matches(domain: str, listed: str) -> bool:
    """Is ``domain`` the listed domain, or a PROPER subdomain of it?

    THE BOUNDARY IS A DOT, and that is the whole point. Containment
    (``listed in domain``) matches the name anywhere in the host, so
    ``evil-linkedin.com.attacker.io`` reads as LinkedIn — the shape CodeQL
    ``py/incomplete-url-substring-sanitization`` flags. The obvious repair,
    ``domain.endswith(listed)``, is the same bug one step in: it still accepts
    ``evil-linkedin.com``. Only ``==`` or a leading ``.`` is a real boundary.

    ``is_ats_sender`` above applies this same rule inline against
    ``ATS_DOMAINS``; it is deliberately left spelled out there, because its
    body is pinned by #166 / #252 / #260 routing behaviour and rewriting it is
    a separate change from fixing the guard that had no anchoring at all.
    """

    return bool(domain) and (domain == listed or domain.endswith(f".{listed}"))


# =============================================================================
# What a category CLAIMS about an application
# =============================================================================

#: The categories whose mail ASSERTS an application into existence.
#:
#: The same fact ``pipeline.APPLIED_SIGNAL_CATEGORIES`` states for a different
#: job — it is not imported from there because ``cloud.pipeline`` is
#: deliberately free of ``jobtracker`` imports at module level (see its
#: ``is_ats_sender``), and the classifier must not be the thing that puts
#: ``sqlmodel`` into its cold-start graph. The two are held together by
#: ``tests/test_a_reference_does_not_outrank_a_report.py`` instead of by an
#: import, so a change to one that is not made to the other goes red.
ASSERTS_AN_APPLICATION: frozenset[str] = frozenset({"applied"})

#: The categories whose mail says nothing about an application of yours at all.
#:
#: ``models.CATEGORY_TO_STATUS`` is the authority for this list and its own
#: comment is the reason: "a follow-up is chasing an application, not a stage
#: of one, and the other two are noise or a holding pen". Those three are
#: exactly the categories absent from that map.
#:
#: SPELLED HERE RATHER THAN READ FROM THE MAP, for one reason that is worth
#: naming: this file has a second copy at
#: ``ml/demo/space/jobtracker/classifier/rules.py`` which ships an older
#: ``models.py`` with no ``CATEGORY_TO_STATUS`` in it, and the two copies are
#: meant to stay identical. So the derivation is written out and then CHECKED
#: against the map by ``test_a_reference_does_not_outrank_a_report.py``, which
#: recomputes it and goes red if the map and this file disagree. The
#: single source of truth is preserved by a test instead of by an import.
_SAYS_NOTHING_ABOUT_AN_APPLICATION: frozenset[str] = frozenset(
    {"follow_up", "needs_review", "other"}
)

#: The categories whose mail REPORTS on an application that already exists.
#:
#: DERIVED, NOT RANKED, and that distinction is the whole point of this pair.
#: It is a two-class PARTITION of the categories that speak about an
#: application — one asserts, the rest report — and the members within each
#: class are unordered. Nothing here says an offer beats a rejection, because
#: nothing true would.
REPORTS_ON_AN_APPLICATION: frozenset[str] = (
    frozenset(c.value for c in EmailCategory)
    - ASSERTS_AN_APPLICATION
    - _SAYS_NOTHING_ABOUT_AN_APPLICATION
)


# =============================================================================
# When a reply's own words contradict the verdict its quote produced
# =============================================================================
#
# ISSUE #417. A reply under :data:`_MIN_ASSERTED_CHARS` keeps its quote, so the
# quote is what gets scored. For "fyi" over a forwarded offer that is correct
# and this machinery stays out of the way. For "We must withdraw the offer." it
# is the defect: 27 characters of the sender's own words are discarded, the
# quoted "we are pleased to offer you the position" wins at 0.95, and the board
# asserts an offer the person does not hold.
#
# THE FIX MAY NOT BE "DISTRUST THE FALLBACK", and that is the whole shape of
# what follows. "Thursday works for me" over a quoted interview invitation is
# also under the floor, also scores its quote, and is RIGHT to: the card should
# advance. Capping every fallback sends that correct auto-file to the review
# queue. So the span is read, and the verdict is capped only when the span
# REFUTES the category the quote won with.
#
# WHAT THE FILE ALREADY HAD, AND WHAT IT DID NOT. The comment on
# ``_NOISE_NEGATIVES`` names the split this reuses: a negative is either a
# GENRE FILTER ("this is not job mail") or a SEMANTIC REFUTATION ("this IS job
# mail and it is not THIS category"). The refutations are derived from
# ``PATTERNS`` below rather than restated, so a pattern edited there is edited
# here too and the three surfaces that read the PATTERNS literals statically
# (``scripts/readme_facts.py``, ``ml/demo/space/…/rules.py``,
# ``apps/web/lib/demo/rules.json``) are untouched — the same reasoning that put
# ``_NOISE_NEGATIVES`` in a frozenset rather than on ``CategoryPatterns``.
#
# But the derived set is NOT SUFFICIENT, measured rather than assumed:
# ``PATTERNS[offer].negative`` holds ``unfortunately``, ``regret to inform``,
# ``not (at this time|selected)``, ``schedule.{0,20}call``, ``thank you for
# applying`` and ``application.{0,20}received``, and not one of them matches
# "We must withdraw the offer." The vocabulary for a withdrawal was never
# written — ``test_a_reply_speaks_for_itself.py`` says so in as many words —
# so the derived half fixes nothing on its own and :data:`_RETRACTION` supplies
# what is missing.

#: "The thing this thread was about has been taken back."
#:
#: A STANCE, NOT A CATEGORY, which is why it is here and not in ``PATTERNS``.
#: It never scores and never names a verdict — there is no ``rescinded``
#: category and #10 forbids inventing one from three wordings invented by the
#: author of the rules. All it can do is stop a verdict from being asserted.
#:
#: SCOPED TO THE OPPORTUNITY AND NOT TO A DIARY. "no longer" and "closed" are
#: required to land near the role, the offer or the opening, because "Thursday
#: no longer works for me" above a quoted invitation is a rescheduling note and
#: the interview it belongs to still exists.
#:
#: Bounded on every quantifier and applied only to a span shorter than
#: :data:`_MIN_ASSERTED_CHARS`, so the ReDoS reasoning that shaped
#: ``_REPLY_SUBJECT`` has nothing to bite on here: the alternatives are
#: disjoint and the two gaps are capped at 30 characters of a class that
#: excludes the sentence delimiter.
_RETRACTION = re.compile(
    r"\b(?:withdraw|withdrawn|withdrawing|withdrawal|rescind(?:ed|ing)?"
    r"|revok(?:e|ed|ing)|retract(?:ed|ing)?)\b"
    r"|\bno longer\b[^.\n]{0,30}\b(?:available|able|open|hiring|proceeding|moving)\b"
    r"|\b(?:role|position|offer|opportunity|req|requisition|opening)\b"
    r"[^.\n]{0,30}\b(?:closed|cancell?ed|frozen|filled|eliminated|on hold)\b"
    r"|\b(?:hiring freeze|headcount freeze|put on hold)\b",
    re.IGNORECASE,
)

#: The categories a retraction can refute: everything that claims an
#: application is ALIVE.
#:
#: DERIVED, so it cannot drift from the enum. ``rejection`` is subtracted by
#: hand and it is the only judgement in this constant: "we have withdrawn your
#: application from consideration" is a rejection written in retraction words,
#: and the classifier is already too shy about asserting a negative outcome
#: (recall 25.5% at 100% precision) to have that one pushed back into the
#: queue.
_RETRACTABLE: frozenset[str] = (
    frozenset(c.value for c in EmailCategory)
    - _SAYS_NOTHING_ABOUT_AN_APPLICATION
    - {EmailCategory.REJECTION.value}
)

#: The semantic half of each category's negatives, compiled once.
_SEMANTIC_REFUTATIONS: dict[str, tuple[re.Pattern[str], ...]] = {
    category.value: tuple(
        re.compile(p, re.IGNORECASE) for p in patterns.negative if p not in _NOISE_NEGATIVES
    )
    for category, patterns in PATTERNS.items()
}

#: What a verdict is worth once the sender's own words have contradicted it.
#:
#: BETWEEN ``pipeline.REVIEW_FLOOR`` (0.70) AND ``pipeline.AUTO_FILE_GATE``
#: (0.85), and both bounds are load-bearing. At or over the gate this is the
#: bug. Under the floor the message is DROPPED rather than queued, which is why
#: the alternative shape — letting the refutation flip the category to
#: ``other`` — is worse: ``other`` lands at 0.50, so the mail that corrects the
#: board would be destroyed instead of shown to the user. Capping asks a
#: question; flipping deletes the evidence.
#:
#: Not imported from ``cloud.pipeline``: that module is deliberately free of
#: ``jobtracker`` imports and the dependency must not be created in the other
#: direction either. ``tests/test_confidence_gate_lockstep.py`` is what keeps
#: the numbers honest.
_REFUTED_CONFIDENCE = 0.80


def own_text_refutes(own: str, category: str) -> list[str]:
    """Which of ``own``'s words argue AGAINST ``category``.

    Empty when the sender wrote nothing readable against it, which is the
    common case and the one that must stay cheap. The patterns are returned
    rather than a bool so the caller can say WHY in ``matched_patterns``; a cap
    nobody can trace back to a phrase is a magic number in the making.
    """

    if not own:
        return []
    hits = [p.pattern for p in _SEMANTIC_REFUTATIONS.get(category, ()) if p.search(own)]
    if category in _RETRACTABLE and _RETRACTION.search(own):
        hits.append(_RETRACTION.pattern)
    return hits


# =============================================================================
# Rule-Based Classifier
# =============================================================================


def winner_first(scores: dict[str, int]) -> list[tuple[str, int]]:
    """Order the categories best-first, breaking ties on what they CLAIM.

    Pulled out of :meth:`RulesClassifier.classify` so the rule has a name and
    so a test can exercise the real one rather than a copy of it: building a
    message that ties ``applied`` against each of the five report categories
    means testing the PATTERNS, and this is a claim about the SORT.

    The second element of the key is the whole of #451. See
    :data:`REPORTS_ON_AN_APPLICATION` for why it is true, and the caller for
    what it replaces.
    """
    return sorted(
        scores.items(),
        key=lambda x: (x[1], x[0] in REPORTS_ON_AN_APPLICATION),
        reverse=True,
    )


@dataclass
class RuleClassificationResult:
    """Result from rule-based classification."""

    category: EmailCategory
    confidence: float
    matched_patterns: list[str]
    scores: dict[str, int]  # Category -> score


class RulesClassifier:
    """
    Rule-based email classifier using pattern matching.

    Uses weighted scoring:
    - Strong pattern match: +3
    - Weak pattern match: +1
    - Negative pattern match: -5
    - Veto pattern match: the category's score is capped at 0
    - Subject patterns: 2x weight

    Confidence is calculated from the winning category's score and its margin
    over the second-best category:
    - score >= 10 and margin >= 5: 0.95
    - score >= 6 and margin >= 3: 0.90
    - score >= 4 and margin >= 2: 0.80
    - score >= 2 and margin >= 1: 0.70
    - otherwise: 0.60

    Ties are broken by what the category CLAIMS, not by enum declaration
    order: at equal score a member of :data:`REPORTS_ON_AN_APPLICATION` beats a
    member of :data:`ASSERTS_AN_APPLICATION`. It cannot change the margin, so
    it cannot change the confidence.

    Three overrides apply:
    - A category with a veto match is capped at 0, so it cannot win. The cap
      never *raises* a score: a category already in the negative stays there,
      which keeps the runner-up margin (and therefore confidence) unchanged
      for whichever category does win.
    - A non-positive winning score short-circuits to 'other' at 0.5
    - A sender on a known ATS domain scoring as applied/rejection/interview/
      offer gets +0.05, capped at 0.95
    """

    def __init__(self):
        # Compile all patterns for efficiency
        self._compiled_patterns: dict[EmailCategory, dict[str, list[re.Pattern]]] = {}

        for category, patterns in PATTERNS.items():
            self._compiled_patterns[category] = {
                "strong": [re.compile(p, re.IGNORECASE) for p in patterns.strong],
                "weak": [re.compile(p, re.IGNORECASE) for p in patterns.weak],
                "negative": [re.compile(p, re.IGNORECASE) for p in patterns.negative],
                "veto": [re.compile(p, re.IGNORECASE) for p in patterns.veto],
            }

        logger.info(f"RulesClassifier initialized with {len(PATTERNS)} categories")

    def classify(
        self,
        subject: str,
        body: str,
        sender_email: Optional[str] = None,
    ) -> RuleClassificationResult:
        """
        Classify an email using pattern matching.

        Args:
            subject: Email subject line
            body: Email body text
            sender_email: Sender email address (for ATS detection)

        Returns:
            RuleClassificationResult with category, confidence, and details
        """
        scores: dict[str, int] = {cat.value: 0 for cat in EmailCategory}
        matched_patterns: list[str] = []

        # READ BEFORE ``asserted_text`` DESTROYS IT. When the span clears the
        # floor it IS what gets scored and there is no second reading to do;
        # when it does not, the quote is scored on its behalf and this is the
        # only remaining record of what the sender actually wrote. #417.
        own_text = own_text_span(body)
        quote_spoke_for_it = own_text is not None and 0 < len(own_text) < _MIN_ASSERTED_CHARS

        # ONCE, before any pattern sees it. Every ``pattern.search(body)`` below
        # is searching what the sender ASSERTS — see :func:`asserted_text`. The
        # subject's TEXT is left alone by design; what changes below is only how
        # much a match in it is worth.
        body = asserted_text(body)

        # A REPLY'S SUBJECT IS ABOUT THE THREAD, NOT ABOUT THIS MESSAGE.
        #
        # The subject doubler exists because a subject is a headline: a sender
        # who puts the verdict there means it. That reasoning does not survive
        # a reply, where the client copied the headline from a message someone
        # else wrote weeks ago. "Re: Thank you for applying to X" is what the
        # interview invitation, the rejection and the scheduling note in that
        # thread ALL look like, and doubling it hands every one of them to
        # ``applied`` before a word of the body is read.
        #
        # Demoted rather than discarded (issue #441). The thread's subject is
        # still evidence — a reply inside an offer thread is more likely to be
        # about an offer than a random message is — it is just not headline
        # evidence about THIS message. Discarding it outright loses the only
        # signal a bare "Re: Your application" carries.
        #
        # BELOW body weight, not equal to it, and that is measured rather than
        # tidy. At equal weight a copied subject still ties with what the
        # sender actually wrote, and a recruiter replying to their own
        # acknowledgement to invite someone to interview came out `applied` on
        # the tie-break — the exact message this exists to fix. What the
        # message says about itself has to outrank what its thread is called.
        strong_subject, weak_subject = (
            (2, 1) if _REPLY_SUBJECT.match(subject or "") else (6, 2)
        )

        # Check if sender is from a known ATS domain
        is_ats_email = is_ats_sender(sender_email)

        # Score each category
        for category, compiled in self._compiled_patterns.items():
            category_score = 0
            category_matches: list[str] = []

            # Check strong patterns (+3, 2x for subject)
            # Tracked separately from the subject case on purpose — see the
            # genre-filter rule in the negative pass below. A subject is a
            # headline and is the cheapest part of a message to make look like
            # job mail; the body is what the message actually is.
            has_strong_body = False
            for pattern in compiled["strong"]:
                in_subject = bool(pattern.search(subject))
                # ASKED SEPARATELY FROM THE SCORE, and that is the whole point.
                #
                # `has_strong_body` decides whether a genre filter ("unsubscribe",
                # "manage preferences") may be outranked, and the question it is
                # asking is "does the BODY state this plainly?" — which has
                # nothing to do with whether the subject happens to say it too.
                #
                # The `elif` used to answer both questions at once, so a pattern
                # matching subject AND body scored the subject and left
                # `has_strong_body` False. A confirmation reading "We have
                # received your application for the Software Engineer position"
                # under the subject "We have received your application" then lost
                # to its own marketing footer, because the one pattern that
                # proved the body was checked against the subject first.
                #
                # Found by the corpus: demoting a reference pattern out of
                # `strong` removed the ONLY body match those messages had, and
                # three tests that had passed for the wrong reason went red.
                in_body = bool(pattern.search(body))
                if in_body:
                    has_strong_body = True
                if in_subject:
                    category_score += strong_subject
                    category_matches.append(f"[STRONG-SUBJECT] {pattern.pattern}")
                elif in_body:
                    category_score += 3
                    category_matches.append(f"[STRONG] {pattern.pattern}")

            # Check weak patterns (+1, 2x for subject)
            for pattern in compiled["weak"]:
                if pattern.search(subject):
                    category_score += weak_subject
                    category_matches.append(f"[WEAK-SUBJECT] {pattern.pattern}")
                elif pattern.search(body):
                    category_score += 1
                    category_matches.append(f"[WEAK] {pattern.pattern}")

            # Check negative patterns (-5), unless STRONG evidence outranks them.
            #
            # A negative says "this only RESEMBLES the category". Strong evidence
            # says it does more than resemble it, and the two are not equal
            # claims — so a negative may not fire against a category that
            # matched a strong pattern in this message.
            #
            # WHAT THIS FIXES. The marketing negative
            # ``\b(unsubscribe|manage preferences|newsletter|digest)\b`` sits on
            # the negative list of applied, rejection, offer AND follow_up, and
            # every transactional ATS mail ends with an unsubscribe link. It
            # therefore hits each candidate equally and never changes the
            # WINNER — only the absolute score, which is what
            # ``confidence`` is computed from. On the message that lost the
            # owner four applications it was worth exactly this:
            #
            #     with the footer     applied -1, rejection  1  ->  0.60
            #     without the footer  applied  4, rejection  6  ->  0.80
            #
            # 0.60 is under ``pipeline.REVIEW_FLOOR`` and 0.80 is over it, which
            # is the difference between a queue entry and silent destruction. A
            # footer is the last thing in a message and the least of what it
            # says; it must not be able to erase what the message is about.
            #
            # It cannot re-admit the mail the negatives were written for: a job
            # alert matches no strong lifecycle pattern, so it is penalised
            # exactly as before. ``P11-marketing`` in the corpus is that
            # control, and c0031 is its explicit regression anchor.
            #
            # A STRONG SUBJECT MATCH DOES NOT COUNT, and that restriction was
            # earned rather than designed. Letting it count took the fixture in
            # ``test_safety_net_is_dead_253.py`` — subject "Thanks for
            # applying", body "your course is unfortunately over" — from OTHER
            # to APPLIED, because a +6 subject hit outranked the ``your course``
            # genre filter that had correctly identified it as course mail. The
            # subject is the one part of a message that is trivially made to
            # look like anything; a genre filter reading the body outranks it,
            # not the other way round.
            for pattern in compiled["negative"]:
                if not (pattern.search(subject) or pattern.search(body)):
                    continue
                if has_strong_body and pattern.pattern in _NOISE_NEGATIVES:
                    category_matches.append(f"[NEGATIVE-OUTRANKED] {pattern.pattern}")
                    continue
                category_score -= 5
                category_matches.append(f"[NEGATIVE] {pattern.pattern}")

            # Check veto patterns. Tagged "[VETO]" and not "[NEGATIVE]" on
            # purpose: hybrid.py reads the "[NEGATIVE]" tag to decide whether
            # to distrust the semantic layers, and a veto is a statement about
            # one category rather than about the mail being non-job-related.
            for pattern in compiled["veto"]:
                if pattern.search(subject) or pattern.search(body):
                    category_score = min(category_score, 0)
                    category_matches.append(f"[VETO] {pattern.pattern}")

            scores[category.value] = category_score
            if category_matches:
                matched_patterns.extend(category_matches)

        # Find winner. A REPORT OUTRANKS A REFERENCE AT EQUAL EVIDENCE (#451).
        #
        # The second element of the key is the tie-break, and it is the only
        # thing this sort does that the score does not: at equal score, a
        # category that REPORTS on an application sorts above one that merely
        # ASSERTS that an application exists.
        #
        # WHY THAT IS TRUE AND NOT A PREFERENCE. A report entails the
        # assertion — an offer for a job presupposes you applied for it, a
        # rejection presupposes the same — and the entailment does not run the
        # other way: "we received your application" says nothing about an
        # offer. So when the evidence is exactly balanced, the report is the
        # reading that accounts for ALL of it; the assertion is the reading
        # that throws half of it away. It is not that an offer matters more
        # than a confirmation. It is that one of the two readings is implied
        # by the other.
        #
        # WHAT IT REPLACES. `sorted(..., key=lambda x: x[1])` is a stable sort
        # over a dict built in ``EmailCategory`` declaration order, where
        # ``applied`` happens to be first. Every tie in this classifier was
        # therefore decided by the order somebody typed an enum in — not by
        # anything about the message. Across the 17,260-case independent
        # corpus that produced 109 positive-score ties, every one of them a
        # reference against a report, and enum order got every one wrong.
        #
        # THIS IS NOT A RANKED TABLE, which is the fix that would have been
        # the same defect with a nicer face. There are exactly two classes and
        # they are read off ``CATEGORY_TO_STATUS``; the members of each are
        # unordered, so a tie BETWEEN TWO REPORTS (``rejection`` against
        # ``interview``, say) is left exactly where it was — neither entails
        # the other and this rule has nothing true to say about it. That is
        # a real remaining hole and it is stated rather than papered over; the
        # corpus contains no such tie, so it is currently unobservable.
        #
        # THE MARGIN IS UNTOUCHED. A tie means the two scores are equal, so
        # reordering them cannot change ``runner_up_score`` and cannot change
        # ``confidence``. This rule decides WHICH verdict, never HOW SURE —
        # deliberately, because raising confidence on a zero margin is how a
        # coin toss gets stated to the user as a fact.
        sorted_scores = winner_first(scores)
        winner_name, winner_score = sorted_scores[0]
        runner_up_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0

        # Default to 'other' if no strong signal
        if winner_score <= 0:
            return RuleClassificationResult(
                category=EmailCategory.OTHER,
                confidence=0.5,
                matched_patterns=matched_patterns,
                scores=scores,
            )

        # Calculate confidence
        margin = winner_score - runner_up_score

        # Base confidence on score and margin
        if winner_score >= 10 and margin >= 5:
            confidence = 0.95
        elif winner_score >= 6 and margin >= 3:
            confidence = 0.90
        elif winner_score >= 4 and margin >= 2:
            confidence = 0.80
        elif winner_score >= 2 and margin >= 1:
            confidence = 0.70
        else:
            confidence = 0.60

        # Boost confidence for ATS emails
        if is_ats_email and winner_name in ["applied", "rejection", "interview", "offer"]:
            confidence = min(confidence + 0.05, 0.95)

        # THE QUOTE SPOKE, AND THE SENDER'S OWN WORDS CONTRADICT IT. #417.
        #
        # Only reachable when the floor refused to strip, so a message whose
        # own words WERE scored can never land here — that verdict already came
        # from the sender and there is nothing to distrust. And only when those
        # words refute this particular winner, which is what keeps "Thursday
        # works for me" over a quoted invitation auto-filing as it should.
        #
        # AFTER THE ATS BONUS, not before. The bonus is +0.05 and the cap is
        # 0.05 under the gate, so capping first hands every withdrawal from a
        # Greenhouse relay straight back over ``AUTO_FILE_GATE`` — the exact
        # arithmetic that made the anchored ``is_ats_sender`` check load-bearing
        # in #252. ``min`` and not assignment, so a verdict already below the
        # cap is not RAISED to it.
        if quote_spoke_for_it:
            refutations = own_text_refutes(own_text or "", winner_name)
            if refutations:
                confidence = min(confidence, _REFUTED_CONFIDENCE)
                matched_patterns.extend(f"[OWN-TEXT-REFUTES] {p}" for p in refutations)

        return RuleClassificationResult(
            category=EmailCategory(winner_name),
            confidence=confidence,
            matched_patterns=matched_patterns,
            scores=scores,
        )


# =============================================================================
# Singleton Instance
# =============================================================================

_classifier: Optional[RulesClassifier] = None


def get_rules_classifier() -> RulesClassifier:
    """Get singleton rules classifier instance."""
    global _classifier
    if _classifier is None:
        _classifier = RulesClassifier()
    return _classifier
