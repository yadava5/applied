"""The interview and offer defects of #348, pinned as behaviour.

Production had **never** auto-detected an interview or an offer: zero
``INTERVIEW`` and zero ``OFFER`` rows in ``emails`` on 2026-08-15. #353 then
measured the rules layer against 400 independently-written messages
(``tests/corpus/mail.py``) and found interview at **4.5%** correct with 62.7%
abstaining — 92 of its 110 authentic invitations matched **nothing at all**.

Two mechanisms, and the second is not the one #348 originally named:

1. **Missing positives, not firing negatives.** Every ``INTERVIEW.strong``
   pattern demanded a specific verb+noun collocation — ``invite you TO
   interview`` but not ``FOR an interview``, ``please book a time`` only with a
   trailing ``(interview|call|meet)``, availability only with the noun
   ``(meeting|call|interview)`` after it. This is the same over-narrowness
   ``EmailCategory.ASSESSMENT`` already records in its bare-noun block. The
   fix names what an invitation *does* rather than how one template says it.

   (The #348 write-up reported ``thank you for applying`` "vetoing 69" of the
   110. That figure is a count of pattern-string occurrences summed across
   *every* category's negative list — the string appears in three of them, and
   23 × 3 = 69. It fired on 23 cases. Likewise 55 = 11 × 5 for
   ``unfortunately``, and the 68 for bare ``interview`` is ``OFFER``'s negative,
   not ``INTERVIEW``'s. Negatives cost 13 cases; missing positives cost 92.)

2. **Cross-class negatives that could only fire where they were wrong.**
   ``INTERVIEW.negative`` carried six of ``APPLIED``'s own positives, and a real
   invitation OPENS with them: "Thank you for applying to <Company>. Your
   application for the <Role> position stood out to us and we would like to
   invite you for an interview" scored applied +6 and interview −10. A −5 on a
   category sitting at 0 changes no verdict, so those patterns were reachable
   only on a message that already had interview evidence — precisely the case
   in which subtracting was the wrong answer. ``OFFER`` carried bare
   ``interview`` for the same reason and paid it on every offer letter, all of
   which open "thank you for taking the time to interview with the team".

   ``APPLIED`` carried the mirror image, ``schedule.{0,20}interview``, and paid
   it on every acknowledgement that says what happens next — "a recruiter will
   reach out to schedule an interview" is a promise, by a third party, in the
   future tense, and it arranges nothing. That one was the whole of
   ``applied``'s error: 45/50 → 50/50 on its removal, with no other class
   moving.

And one weight, rather than a pattern: ``your application for <Role> at
<Company>`` is a THREAD SUBJECT. It says which application the mail concerns,
every reply inherits it, and as a ``strong`` SUBJECT match it was worth +6 — the
most any single pattern can earn. A recruiter replying on that thread to invite
the candidate to an interview was filed as an acknowledgement at 0.95. It is
``weak`` now.

Measured over the 400-case corpus, before → after:

    interview    5/110   4.5%  ->  93/110  84.5%
    offer       60/85   70.6%  ->  69/85   81.2%
    rejection   45/75   60.0%  ->  62/75   82.7%
    applied     45/50   90.0%  ->  50/50  100.0%
    assessment  32/45   71.1%  ->  32/45   71.1%   (unmoved)
    other       29/35   82.9%  ->  29/35   82.9%   (unmoved, deliberately)
    ALL        216/400  54.0%  -> 335/400  83.8%
    wrong auto-files 41 -> 14

Transitions, which matter more than the headline, because "correct" going up is
compatible with the product getting worse:

    wrong     -> correct     37   win
    abstained -> correct     82   win
    wrong     -> abstained    0
    abstained -> wrong        2   LOSS
    correct   -> wrong        0
    correct   -> abstained    0

**The two losses are real and are named**: ``c0012`` and ``c0095`` in the
corpus, both threads whose new text invites and whose quoted history rejects,
now read as ``rejection`` at 0.95 and 0.90 — confident, and wrong. They are the
cost of ``REJECTION`` learning the sentence it was blind to. The mirror case
(``c0011``: the quote invites, the new text rejects) was already a confident
wrong answer before this change, so the family always failed; it now fails
symmetrically instead of one way round. The fix is a quote-boundary parser,
which is not a pattern change and is not attempted here.

What else is still broken, so nobody reads the table as a claim it is not: of
the 14 remaining wrong auto-files, 6 are truncation cases where the verdict is
not in the text the classifier receives at all (an ingestion defect, #348 §3,
not a pattern one), 3 are the quoted threads above, 3 are assessment
invitations whose subject genuinely says "interview", 1 is a ``display:none``
preheader carrying the opposite verdict, and 1 is a follow-up subject.

Assertions are on the category a user would see and the confidence BAND the
rest of the system keys off (``pipeline.AUTO_FILE_GATE`` = 0.85 files a row;
``REVIEW_FLOOR`` = 0.70 holds it for review; below that it is dropped), never
on which regex fired, so the patterns stay free to be rewritten. The regression
guards at the bottom are the other half of the change: a fix that reclassified
acknowledgements as invitations would be a worse product and a better score.

EVERY test here was run red under a mutation that removes the behaviour it
tests, and green with it restored. The mutations are named in each docstring.
"""

from __future__ import annotations

import pytest

from jobtracker.classifier.rules import RulesClassifier, is_ats_sender
from jobtracker.cloud.pipeline import AUTO_FILE_GATE, REVIEW_FLOOR
from jobtracker.database.models import EmailCategory

# Instantiated directly rather than through get_rules_classifier(): the module
# singleton would make this file's behaviour depend on what ran before it.
CLASSIFIER = RulesClassifier()

# A sender on nobody's ATS list, so no test here can be carried by the +0.05
# bonus. Real invitations and real offers usually come from a named human on
# the company's own domain, which is exactly the case that had no bonus to lean
# on — see #348 on why the canonical offer template only ever cleared the gate
# through an ATS relay it would not have in practice.
HUMAN = "nils.berger@hollowmere.example"


def verdict(subject: str, body: str, sender: str = HUMAN):
    return CLASSIFIER.classify(subject, body, sender)


# ---------------------------------------------------------------------------
# 1. INTERVIEW — the invitation shapes that scored zero
# ---------------------------------------------------------------------------

# Workable's published interview-invitation template, the most reproduced invite
# copy on the web. It opens with two sentences that are APPLIED's strongest
# evidence and closes with an availability question, and it was classified
# `applied` at 0.95 — auto-filed as a confirmation of the application it was
# inviting the candidate to interview for.
WORKABLE_INVITE = (
    "Hi Alex, Thank you for applying to Hollowmere. Your application for the "
    "Machine Learning Engineer position stood out to us and we would like to "
    "invite you for an interview at our offices to get to know you a bit "
    "better. You will meet with the Data department manager, Nils Berger. The "
    "interview will last about 60 minutes and you'll have the chance to "
    "discuss the Machine Learning Engineer position and learn more about our "
    "company. Would you be available on Tuesday 19 August between 2pm and 5pm? "
    "Looking forward to hearing from you, Nils Berger"
)


def test_the_canonical_invitation_is_an_interview_and_not_a_confirmation() -> None:
    """RED under: revert ``invite you (to|for)`` to ``invite you to``.

    The whole defect in one message. Before #348 this produced
    ``applied`` at 0.95 — over ``AUTO_FILE_GATE``, so the product asserted a
    status the mail contradicts. The preposition is the load-bearing detail:
    the pattern list had ``invite you TO interview`` and this template, like
    most English, writes ``invite you FOR an interview``.

    THE BAND IS ``REVIEW_FLOOR``, NOT ``AUTO_FILE_GATE``, AND THAT IS A STATED
    LIMITATION RATHER THAN A CONVENIENT ASSERTION. From this human sender the
    verdict is interview at **0.80** — right category, held for review, not
    filed. The residue is the courtesy opener: "Thank you for applying" and
    "Your application for the <Role> position" are genuine ``APPLIED``
    evidence and still score +7, which cuts the margin to 2 and lands on the
    0.80 rung. The same message from an ATS relay earns the +0.05 bonus and
    does clear the gate, which is exactly the asymmetry #348 complains about in
    the other direction. Asserting the gate here would have meant tuning the
    confidence ladder until a number went green; wrong verdicts were the thing
    to remove, and a held message is not a wrong verdict.
    """
    result = verdict("Availability request: Machine Learning Engineer", WORKABLE_INVITE)

    assert result.category is EmailCategory.INTERVIEW
    assert result.confidence >= REVIEW_FLOOR
    # It does clear the gate off an ATS relay, which is the only difference.
    filed = verdict(
        "Availability request: Machine Learning Engineer",
        WORKABLE_INVITE,
        "no-reply@us.greenhouse-mail.io",
    )
    assert filed.category is EmailCategory.INTERVIEW
    assert filed.confidence >= AUTO_FILE_GATE


def test_a_self_schedule_link_is_an_interview() -> None:
    """RED under: delete BOTH the ``(book|pick|choose|…) (a|your|another)
    (time|slot)`` frame and the ``(would|'d) like to (speak|…) with you`` one.
    Either alone leaves the other carrying this message — the frames overlap on
    purpose, and a mutation that removes only one proves nothing.

    The commonest scheduling mail there is, and it never says "interview".
    ``please.{0,20}(book|schedule|pick).{0,20}time.{0,20}(interview|call|meet)``
    wanted a trailing noun this sentence does not supply and a lead-in "please"
    half of these drop, so the mail scored zero and abstained.
    """
    result = verdict(
        "Next steps with Ospreybank",
        "Hi Alex, The hiring team for the Infrastructure Engineer role would "
        "like to speak with you. Please book a time that works for you using "
        "the link below; the calendar is open for the next two weeks. "
        "https://scheduling.example/r-10725 Camille Rousseau",
    )

    assert result.category is EmailCategory.INTERVIEW


def test_an_availability_request_is_an_interview() -> None:
    """RED under: delete ``(share|send|provide|confirm|know)\\s+your\\s+availability``.

    ``availability.{0,30}(for an?|to) (meeting|call|interview)`` needs the noun
    spelled out. Recruiters leave it implicit — the noun is what the whole
    thread is about — so the request scored zero.
    """
    result = verdict(
        "Lumafold - next step",
        "Hi Alex, We'd like to move ahead with the Product Engineer process. "
        "Please share your availability for the coming week and I will send an "
        "invitation once we have a time. Lena Hoffmann",
    )

    assert result.category is EmailCategory.INTERVIEW


def test_a_confirmed_booking_is_an_interview() -> None:
    """RED under: delete BOTH that frame and the itinerary frame below it —
    "You will meet with the platform team" carries this message on its own.

    Confirmations and reschedules are the two commonest interview mails after
    the invitation itself and had no pattern of their own at all. Note this
    fires on the STATE of a booking, not on the word: it is deliberately unable
    to match an offer letter's "thank you for taking the time to interview with
    the team. I am delighted to confirm the details we discussed" — a bare
    ``interview (with|is|has been)`` was tried first and read nine offers as
    invitations.
    """
    result = verdict(
        "Foxglove Systems",
        "Hi Alex, Your interview with Foxglove Systems is confirmed for "
        "Tuesday 14 August at 2:00pm ET. You will meet with the platform team "
        "for 30 minutes. Joining info: https://meet.example/r-10508 "
        "Looking forward to meeting you, Lena Hoffmann",
    )

    assert result.category is EmailCategory.INTERVIEW


def test_an_onsite_itinerary_is_an_interview() -> None:
    """RED under: delete ``(you|we) ('ll|will) meet with``.

    An onsite day lists times and names and may never use the word
    "interview". What it always says is who you will meet;
    ``meet (the )?(hiring )?team`` wants the literal noun "team".
    """
    result = verdict(
        "Halcyon Grid - your day with us",
        "Hi Alex, Here is your itinerary for Tuesday 17 August at our office. "
        "10:00 System Design with Priya Raman 11:00 Coding with Nils Berger "
        "12:00 Lunch 13:00 Values conversation with Imani Osei. You will meet "
        "with four members of the Site Reliability Engineer team over the "
        "course of the day. Rowan Blake",
    )

    assert result.category is EmailCategory.INTERVIEW


def test_a_reschedule_is_not_read_as_a_rejection_for_saying_unfortunately() -> None:
    """RED under: restore ``unfortunately`` to ``INTERVIEW.negative``.

    A hedge is not a decision. ``REJECTION`` does not lean on the bare word
    either — its pattern is ``unfortunately.{0,50}(not|won't|will not|unable)``,
    the word plus an actual negation — but ``INTERVIEW`` paid −5 for a
    logistics apology, which is how scheduling mail routinely opens.
    """
    result = verdict(
        "Let's find a time to chat, Alex",
        "Hi Alex, Unfortunately our hiring manager is travelling this week, so "
        "we have moved your Data Engineer interview to Tuesday 18 August at "
        "3:00pm. The format is unchanged: 45 minutes with the platform team. "
        "Imani Osei",
    )

    assert result.category is EmailCategory.INTERVIEW


def test_an_invitation_replying_on_the_application_thread_is_not_a_confirmation() -> None:
    """RED under: move the two ``your application (for|to) … at [A-Z]`` patterns
    back from ``APPLIED.weak`` to ``APPLIED.strong``.

    The subject is a thread identifier every reply inherits, and at +6 in the
    subject it outscored the invitation in the body: ``applied`` at 0.95,
    auto-filed. This is the single highest-scoring pattern in the file being
    spent on a sentence that says only *which* application the mail is about.
    """
    result = verdict(
        "Re: Your application for Backend Engineer at Glasshouse Labs",
        "Hi Alex, I look after recruiting for the Backend Engineer opening at "
        "Glasshouse Labs. I'd like to set up a 45 minute call to walk through "
        "your background and what the team is working on. Are you available on "
        "Tuesday 15 August? Camille Rousseau",
    )

    assert result.category is EmailCategory.INTERVIEW


def test_an_invitation_under_a_follow_up_subject_is_not_discarded() -> None:
    """RED under: delete the five scheduling frames from ``FOLLOW_UP.veto``.

    The worst outcome in the system, and not merely a wrong verdict:
    ``follow_up`` reaches neither ``pipeline._qualifies_for_hard_row`` nor
    ``pipeline.collect_review_items``, so a message routed there is never
    persisted at all — no row, no queue entry, nothing the user can see. A
    recruiter replying "Following up on your application" with a scheduling
    request scored +6 in the subject and vanished.

    Same argument the veto tier already carries for stated hiring decisions,
    other direction: a message that ARRANGES something is not a nudge either.

    The body deliberately carries ONE scheduling frame and no more. An earlier
    draft used two, which scored interview +6 against follow_up's +6 and won on
    the enum tie-break — so deleting the whole veto group left it green and the
    test proved nothing. One frame is +3 against +6, which is the case the veto
    is actually for.
    """
    result = verdict(
        "Following up on your application - Lumafold",
        "Hi Alex, We'd like to move ahead with the Product Engineer process. "
        "Could you send two or three windows that work for you next week? I "
        "will send an invitation once we have a time. Please share your "
        "availability for the coming week. Lena Hoffmann",
    )

    assert result.category is not EmailCategory.FOLLOW_UP
    assert result.category is EmailCategory.INTERVIEW


# ---------------------------------------------------------------------------
# 2. OFFER — the word every offer letter contains
# ---------------------------------------------------------------------------


def test_an_offer_thanking_you_for_interviewing_is_still_an_offer() -> None:
    """RED under: restore bare ``interview`` to ``OFFER.negative``.

    "Thank you for taking the time to interview with the team" is how offer
    letters open, and it cost −5 — measured, the whole reason 9 of the 12
    verbal-confirmation offers in the corpus abstained. The negative was
    reaching for the SCHEDULING sense of the word; ``schedule.{0,20}call``
    still expresses that without catching the past tense.
    """
    result = verdict(
        "Ironvale job offer",
        "Hi Alex, Thank you for taking the time to interview with the team. I "
        "am delighted to confirm the details we discussed on Friday for the "
        "Full Stack Engineer role. Your start date will be 8 September 2026 "
        "and employment is at will. Let me know if anything looks wrong. "
        "Camille Rousseau",
    )

    assert result.category is EmailCategory.OFFER


# ---------------------------------------------------------------------------
# 3. REJECTION — two words, and the most reproduced rejection copy on the web
# ---------------------------------------------------------------------------

WORKABLE_REJECTION = (
    "Dear Alex, Thank you for taking the time to consider Foxglove Systems. We "
    "wanted to let you know that we have chosen to move forward with a "
    "different candidate for the Data Engineer position. Our team was "
    "impressed by your skills and accomplishments. We think you could be a "
    "good fit for other future openings and will reach out again if we find a "
    "good match. We wish you all the best in your job search and future "
    "professional endeavors. Regards, Camille Rousseau"
)


def test_the_canonical_rejection_template_is_a_rejection() -> None:
    """RED under: revert BOTH ``(a |an |the )?(other|another|different)`` and
    the ``wish you`` sign-off. This template carries both halves, so reverting
    one leaves the other scoring it — which is exactly why the corpus caught
    the first draft of the article group (``(an?|the )?``, with no trailing
    space) being DEAD: nine renderings still passed on the sign-off alone.

    Workable's published rejection, and it scored **literally zero** at full
    body length. Two words: ``(other|another) (candidate|applicant)`` has no
    third arm for "a **different** candidate", and
    ``wish you (the best|well|success)`` could not see past "all". Nine of its
    ten renderings in the corpus abstained and the tenth filed as ``applied``.
    """
    result = verdict("Your application to Foxglove Systems", WORKABLE_REJECTION)

    assert result.category is EmailCategory.REJECTION


@pytest.mark.parametrize(
    "sentence",
    [
        "We have chosen to move forward with a different candidate.",
        "We decided to move forward with a different applicant for this role.",
        "We are moving forward with another candidate.",
        "We have decided to move forward with other candidates.",
    ],
)
def test_all_three_ways_of_saying_not_you_score(sentence: str) -> None:
    """RED under: revert ``(an?|the )?(other|another|different)`` — the first two
    sentences go to ``other`` at 0.50.

    English has three words for this slot and the alternation carried two. The
    last two are the pre-existing spellings and are here to prove the
    generalisation is strictly wider, not a swap.
    """
    result = verdict("Update on your application", f"Dear Alex, {sentence}")

    assert result.category is EmailCategory.REJECTION


# ---------------------------------------------------------------------------
# 4. THE REGRESSION GUARDS — what must NOT have moved
# ---------------------------------------------------------------------------
# Loosening interview and dropping six APPLIED positives out of
# INTERVIEW.negative is only correct if acknowledgements still read as
# acknowledgements. `applied` measured 45/50 and `other` 29/35 on the corpus
# both before and after, unchanged; these pin the two shapes that could
# plausibly have flipped.


def test_a_plain_acknowledgement_is_still_applied() -> None:
    """RED under: remove the four acknowledgement patterns from
    ``APPLIED.strong`` (``application.{0,20}received``, ``we have received your
    application``, ``application (is|has been) (under|in) review``,
    ``application.{0,20}(for|to).{0,40}(position|role|job)``).

    Deliberately stated: this passes on the pre-#348 code too. It is a guard,
    not a proof of a fix — it is here so a future loosening of INTERVIEW that
    DOES catch confirmations fails something. The mutation above is what shows
    it is wired up at all rather than green by construction.
    """
    result = verdict(
        "Application submitted successfully",
        "Hi Alex, Thanks for your interest in Mosswright. We have received "
        "your application for the Full Stack Engineer position and it is now "
        "under review. Do not reply to this message.",
    )

    assert result.category is EmailCategory.APPLIED


def test_a_confirmation_promising_a_future_interview_is_still_applied() -> None:
    """RED under: restore ``schedule.{0,20}interview`` to ``APPLIED.negative``
    — i.e. revert this change. On the pre-#348 code this exact message
    classified ``interview`` at 0.60, measured.

    The trap the new interview patterns are shaped to avoid, and the reason
    they carry a tense. This confirmation talks about an interview at length — "a recruiter
    WILL reach out to schedule an interview" — but promises one in the future,
    through a third party, and arranges nothing. It is an acknowledgement.
    """
    result = verdict(
        "Application submitted successfully",
        "Hi Alex, Thanks for your interest in Mosswright. We have received "
        "your application for the Full Stack Engineer position. If your "
        "background matches what we are looking for, a recruiter will reach "
        "out to schedule an interview, and you may be invited to complete an "
        "assessment. We will be in touch to schedule next steps either way.",
    )

    assert result.category is EmailCategory.APPLIED


# ---------------------------------------------------------------------------
# 5. ATS_DOMAINS — the removal of ``hire.com``
# ---------------------------------------------------------------------------


def test_lever_relays_survive_the_removal_of_hire_com() -> None:
    """RED under: this cannot go red by re-adding ``hire.com`` — that is the
    point. Turn it red by removing ``lever.co`` instead.

    ``hire.com`` was the shortest entry on ``ATS_DOMAINS`` and no ATS was found
    that sends from it. The domain it was presumably reaching for is Lever's
    ``hire.lever.co``, which ``lever.co`` covers as a proper subdomain both
    before and after the anchoring of #260 — so the entry was doing nothing
    that survived its removal. This asserts the coverage that had to hold.
    """
    assert is_ats_sender("no-reply@hire.lever.co")
    assert is_ats_sender("applicant@hire.lever.co")
    assert is_ats_sender("no-reply@lever.co")


def test_hire_com_no_longer_reaches_the_review_queue() -> None:
    """RED under: restore ``"hire.com"`` to ``ATS_DOMAINS``.

    The other half. ``is_ats_sender`` is not only a +0.05 bonus: since #166 and
    #252 ``cloud.pipeline`` reads it to decide which mail is floated into the
    review queue, so a domain anyone can register was enough to reach the
    owner's queue. Anchoring (#260) closed the ``sohire.comcast.net`` hole;
    this closes the entry itself, which nothing was using.

    ``hire.com`` is a live registered domain, so an exact-match sender on it is
    the assertion that fails when the entry comes back — the lookalike in
    ``tests/test_ingestion_hole_166.py`` cannot see the difference, because
    anchoring already rejects it for a second reason.
    """
    assert not is_ats_sender("careers@hire.com")
    assert not is_ats_sender("careers@jobs.hire.com")
