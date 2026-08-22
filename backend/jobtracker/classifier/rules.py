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

The category with highest score wins. Confidence is based on margin and match strength.
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
# The mail that forced this is a real rejection from Anthropic, subject
# "Anthropic Follow-Up for TPU Kernel Engineer | Ayush Yadav", body "…we have
# decided not to move forward with your application". The word "Follow-Up" in
# the subject scored follow_up +6 and the rejection sentence scored NOTHING, so
# it classified as follow_up at 0.90 — and ``follow_up`` reaches neither
# ``pipeline._qualifies_for_hard_row`` nor ``pipeline.collect_review_items``, so
# the message was never persisted at all.


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
            r"thank you for applying",
            r"application.{0,20}received",
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
            r"application.{0,20}(for|to).{0,40}(position|role|job)",
            r"applied.{0,20}(for|to).{0,40}(position|role|job)",
            r"thank you for your interest.{0,40}(position|role|career)",
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
            r"action required.{0,30}(application|submit)",
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
_REPLY_SUBJECT = re.compile(r"^\s*(?:re|fw|fwd)\s*(?:\[\d+\])?\s*:", re.IGNORECASE)


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
    """

    if not body:
        return body
    marker = _QUOTE_BOUNDARY.search(body)
    if marker is None:
        return body
    own = body[: marker.start()].strip()
    return body if len(own) < _MIN_ASSERTED_CHARS else own


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
# Rule-Based Classifier
# =============================================================================


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
                if pattern.search(subject):
                    category_score += strong_subject
                    category_matches.append(f"[STRONG-SUBJECT] {pattern.pattern}")
                elif pattern.search(body):
                    category_score += 3
                    has_strong_body = True
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

        # Find winner
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
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
