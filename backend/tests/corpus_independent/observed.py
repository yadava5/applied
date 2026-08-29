"""Real applicant-tracking wordings, transcribed rather than invented.

WHY THIS FILE EXISTS, and it is the most important thing in the corpus.

Every other family in ``generate.py`` was written by the same person who writes
``rules.py``. That is a closed loop, and it was measured on 2026-08-22 rather
than suspected. Re-measured 2026-08-29 by ``reach.py``, which is what turned it
from a paragraph in this docstring into a gate:

    invented lifecycle messages matching >=1 STRONG engine pattern:
        13,760 / 13,760  =  100.0%   (27 families)
    positive engine patterns never exercised by ANY of the 17,260:
        111 / 159  =  69.8%

Not one invented message was phrased in language the classifier had never been
taught. A corpus like that cannot discover a gap; it can only confirm the
pattern list against itself — and #530's measurement is that it does not even
manage that: it confirms 30% of the pattern list against itself. A headline
accuracy computed over it describes the author's vocabulary rather than the
product's reach.

So these are transcribed from mail that arrived in the owner's inbox, from
twenty-odd senders across Greenhouse, Lever, Ashby, iCIMS, SmartRecruiters,
Rippling and seven in-house systems. They were written by recruiting teams with
no knowledge of this repository, which is the whole point.

THE ACCEPTANCE TEST FOR THIS FILE IS NOT WHAT THIS DOCSTRING USED TO SAY. It
said "the verbatim-pattern rate is near ZERO", nothing ever computed it, and
#530 computed it for the first time on 2026-08-26 and showed the criterion is
the wrong one. These transcriptions match a strong engine pattern at 98.7%
(confirmations), 82.7% (rejections), 82.0% (assessments) and 70.4% (pending).
Near-zero would not be a good result. It would mean these had drifted away from
how ATS mail is actually written: real ATS mail says "thank you for applying",
and the engine has that pattern BECAUSE real mail says it. **A verbatim match is
agreement, not contamination.**

What actually bounds what this file can find is the DISCOVERY RATE — the share
of its messages matching no strong pattern at all, which is the only place a
corpus can find something the engine does not already know. Every invented
family is 0.0% by construction; these run 17-51%, and that is the whole of this
product's non-circular evidence. ``tests/test_corpus_reach.py`` pins them with
the direction that matters: they may not FALL.

WHAT IS AND IS NOT COPIED. Employer and role are PARAMETERS, filled from the
corpus's invented pool. Two reasons, and the second is the load-bearing one:

  1. Publishing the list of employers the owner applied to, and which of them
     rejected him, is career-sensitive in a way the wording is not. Provenance
     cites the ATS platform and the Gmail thread id, which is opaque to everyone
     but him and still lets him audit any line here against the original.
  2. Parameterising makes each template reusable across all 8,130 invented
     employers, so a defect that depends on the employer or role string — #455
     is exactly that, a job title carrying "Career" into the verdict — is
     reachable from every one of these shapes instead of one.

These are FORM LETTERS: machine-sent boilerplate, identical to every applicant,
with no personal correspondence in them. Nothing here was written to Ayush as a
person. Named recruiter mail and any thread with a human reply in it is
deliberately absent and must stay absent.

DO NOT EDIT A WORDING TO MAKE A TEST PASS. If the classifier misses one of
these, the classifier is what is wrong; these are the ground truth. Editing them
would rebuild the closed loop this file exists to break, one layer up.

That prohibition is now ENFORCED rather than merely stated. Copy an engine
pattern into one of these templates and the family's discovery rate collapses,
which ``test_corpus_reach.py`` measures and reds on — proven by the mutation in
``test_copying_an_engine_pattern_into_an_observed_wording_reds_this_gate``.
"""

from __future__ import annotations

#: ``(subject, body, provenance)``. ``{display}`` is the employer, ``{role}``
#: the job title, ``{req}`` a requisition number where the sender used one.
Template = tuple[str, str, str]

#: Acknowledgements. The single largest shape in a job seeker's mailbox and the
#: one the product must never get wrong, because every later update is filed
#: against the card one of these opens.
OBSERVED_CONFIRMATIONS: tuple[Template, ...] = (
    (
        "Thank you for your application",
        "Dear Ayush, Thank you very much for your recent application to the "
        "{role} position at {display}. We have received your resume and will "
        "contact you should there be interest in discussing this opportunity "
        "further.",
        "iCIMS, thread 1a02724df6374cd5",
    ),
    (
        "Thanks for applying to {display}",
        "Hi Ayush Yadav, Thanks for applying to {display}! There are a ton of "
        "great companies out there, so we appreciate your interest in joining "
        "our team. While we're not able to reach out to every applicant, our "
        "recruiting team is reviewing applications.",
        "in-house, thread 1a0234892a062ff6 — note it never says 'received'",
    ),
    (
        "Thank you for your application!",
        "Hi Ayush, Thank you for taking the time to submit your application for "
        "{role} (Job number: {req}). We're glad you're interested in a career "
        "at {display}, and we're here to help you find the right fit.",
        "in-house, thread 1a02341f84f11426 — 'a career at' is in the BODY",
    ),
    (
        "Thank you for applying to {display}",
        "Hi Ayush, We appreciate you taking the time to submit an application "
        "for the {role} position, and are happy that you would consider joining "
        "our team! Please note that with the volume we receive we cannot always "
        "respond individually.",
        "Ashby, thread 19ff9c0591e517ea",
    ),
    (
        "Thank you for applying to {display}",
        "Hi Ayush, Thank you for taking the time and consideration to apply for "
        "the {role} role! We've received your application and will reach out if "
        "the hiring team decides to move forward.",
        "Greenhouse, thread 19ff9b96f09b478c",
    ),
    (
        "Thank you for applying to {display} | {role}",
        "Hi Ayush, Thank you for your interest in {display}! We have received "
        "your application for the {role} role and will be reviewing your "
        "background shortly. If there is a match we will be in touch.",
        "Ashby, thread 19ff9b86a7e1dc11",
    ),
    (
        "Thank you for your application to {display}, Ayush!",
        "Hi Ayush, Thank you for applying to {display} - we appreciate your "
        "interest in joining our team! If our team thinks you could be a good "
        "fit for the {role} position, we'll be in touch.",
        "in-house, thread 19ff97772e932c0f",
    ),
    (
        "Thank you for Applying to {display}!",
        "Hi Ayush, Thanks for applying to {display}! We've received your "
        "application for the {role} (ID: {req}) position. What happens next? If "
        "we decide to move forward, a recruiter will contact you.",
        "in-house, thread 19ff85460f8e6c7e",
    ),
    (
        "Thank you for applying to {display}!",
        "Dear Ayush, Thank you for your interest in potential opportunities "
        "with {display}. Your details have been added to our database and are "
        "under review. Should we feel that your background is a fit for a "
        "current opening, someone will reach out.",
        "in-house, thread 19ff3cb6dfa22cb3 — never says application or applied",
    ),
    (
        "Thank you for applying to {display}!",
        "Hey Ayush, Thanks so much for your interest in {display}! We "
        "successfully received your application for the {role} role and are "
        "pumped to look over it. Our team will review it shortly.",
        "Greenhouse, thread 19ff3ca8459059db",
    ),
    (
        "Thank you for applying to {display}",
        "Hi Ayush, Thank you so much for applying to the {role} role at "
        "{display}! We are always looking for great talent and we are excited "
        "to receive your application. We will review it as soon as we can.",
        "Greenhouse, thread 19ff36237eef1ef3",
    ),
    (
        "Thanks for applying to {display}!",
        "Hi Ayush, Thank you for applying for the {role} role at {display}! We "
        "appreciate your interest in joining the team. We will review your "
        "application and get back to you if there are next steps.",
        "Ashby, thread 19fef5b249d9f55b",
    ),
    (
        "Thank you for applying to {display}",
        "Dear Ayush, Thank you for your interest in the {role} position at "
        "{display}. We have successfully received your online application. If "
        "your experience and qualifications match our needs we will contact you.",
        "Greenhouse, thread 19fef5a6830c268a",
    ),
    (
        "Thank You for Applying to {display}!",
        "Hi Ayush, Thanks for your interest in {display}! We received your "
        "application for the {role} position. Here's a quick note on what "
        "happens next in our process.",
        "SmartRecruiters, thread 19fef5a0f8e73d01",
    ),
    (
        "Thank You for Applying to {display}",
        "Hi Ayush, Thank you for applying to {display}! We have received your "
        "application and will review it promptly. If we think there is a good "
        "fit, we will contact you at this email address.",
        "Rippling, thread 19fef583bc64ea8b — names NO role anywhere",
    ),
    (
        "Your application has been received!",
        "Hi Ayush, Thank you for submitting your application to be a {role} at "
        "{display}. Our team is reviewing your application and will be in touch "
        "if we think you're a potential match.",
        "Lever, thread 19fef5720d70b0c6 — subject names no employer",
    ),
    (
        "Thank You For Applying to {display}",
        "Hi Ayush, We appreciate you taking the time to submit an application "
        "for the {role} position, and are delighted that you would consider "
        "joining our team! Please note that with the high volume of applicants "
        "we may not respond to everyone.",
        "Greenhouse, thread 19fef5400019718a",
    ),
    (
        "Thank you for applying to {display}!",
        "Hi Ayush, Thank you for beginning your application process with "
        "{display}! We are excited to learn more about your interests and how "
        "your skill set will best contribute to our vision.",
        "in-house, thread 19fef5306e48fbe1 — 'beginning your application'",
    ),
    (
        "Thank you for applying to {display}",
        "Ayush, Thanks for applying to {display}. Your application has been "
        "received and we will review it right away. If your application seems "
        "like a good fit for the position we will contact you soon.",
        "in-house, thread 19feea170da07c85",
    ),
    (
        "Thank you for applying to {display}!",
        "Hi Ayush, Thank you for applying to {display}! We received your "
        "application for the {role} role and we're excited to learn more about "
        "your skills and experience.",
        "in-house, thread 19fee9eb031d902e",
    ),
    (
        "Thank you for applying to {display}",
        "Hi Ayush, Thank you for applying to {display}'s {role} position! We've "
        "received your application and will review it as soon as possible.",
        "in-house, thread 19fee9dc121e50ca",
    ),
    (
        "Thank you for applying to {display}",
        "Hi Ayush, Thanks for checking us out and applying for the {role} "
        "position with {display}! Your application has been received and we "
        "will review it right away. If we see a potential match we'll reach out.",
        "Greenhouse, thread 19fee9be6f27b36c",
    ),
    (
        "Thank you for applying to {display}!",
        "Hi Ayush, Thank you for applying to {display}. Our hiring team will "
        "review your resume soon! Please note, due to the high volume of "
        "applications we receive, we are only able to contact candidates whose "
        "background is a close match.",
        "in-house, thread 19fee9b27334bff3",
    ),
)

#: Rejections. NOT ONE of these leads with its verdict; every one spends the
#: opening on courtesy, which is why the snippet families exist.
#: The one observed rejection that is classified CORRECTLY and still scores
#: under the auto-file gate — ``rejection`` at 0.75, on the full body and on the
#: snippet alike (measured 2026-08-22). Named because a family that needs to
#: exercise the REVIEW QUEUE needs exactly this: mail the product understands
#: and is not confident enough to file. Mail that clears the gate goes straight
#: to a card and never reaches the queue at all, which is why
#: ``one-thread-many-roles`` could not red on #454.
#:
#: Its confidence is a property of the rules and may move. The corpus test
#: therefore asserts that the family built on it actually reaches the queue,
#: rather than trusting this note to stay true.
UNDER_THE_GATE: Template = (
    "Thank you for your interest in {display}, Ayush",
    "Hi Ayush, Thank you for your interest in the {role} opportunity. It "
    "means a lot to us that you would consider joining our mission here at "
    "{display}. Although your background is impressive, we have decided not "
    "to move forward at this time.",
    "Greenhouse, thread 19ffc2cae1b51518 — never uses the word application",
)

OBSERVED_REJECTIONS: tuple[Template, ...] = (
    (
        "Thank you from {display} - Ayush Yadav - {role}",
        "Dear Ayush, Thank you for your interest in {display}. After careful "
        "consideration, we regret to inform you that we will not be proceeding "
        "with your candidacy for this role at this time. Please note that we "
        "will keep your details on file.",
        "Lever, thread 1a001b68983e59a3 — verdict IS inside the snippet",
    ),
    (
        "Important information about your application to {display}",
        "Hi Ayush, Thank you for your interest in {display} and our {role} "
        "position. As you can imagine we received many qualified applicants and "
        "some aligned better than others. We will not be moving forward with "
        "your application at this time.",
        "in-house, thread 1a0007799088bec6 — verdict past the snippet",
    ),
    UNDER_THE_GATE,
    (
        "Thank You from {display}",
        "Hi Ayush, Thank you for taking the time to apply to the {role} role "
        "here at {display}. Please note, we have received many applications for "
        "this role and the search has been closed. We will not be proceeding "
        "with your candidacy.",
        "Rippling, thread 19ffb782c89c1988",
    ),
    (
        "Important information about your application to {role} @ {display}",
        "Hi Ayush, Thank you so much for taking the time to apply for the "
        "{role} opening at {display}. We know a lot of thought and "
        "consideration went into your application, and the team genuinely "
        "appreciates your interest. After careful review we have decided not to "
        "move forward with your candidacy at this time.",
        "Greenhouse, thread 19ff7393d56eccfb — verdict at ~character 330",
    ),
    (
        "{display} Follow-Up for {role} | Ayush Yadav",
        "Hi Ayush, Thank you so much for your interest in {display} and for the "
        "time and effort you have invested in our process. After consideration, "
        "we have decided not to move forward with your application at this time.",
        "Greenhouse, thread 19ff4d11faa3721d",
    ),
)

#: Assessments, and the reminder cadence around them. All four are the same
#: application at different moments, which is what makes them updates.
OBSERVED_ASSESSMENTS: tuple[Template, ...] = (
    (
        "[Action Required] Your {display} Assessments Invitation",
        "{display} Assessments Invitation Hi Ayush, We're thrilled to invite "
        "you to the next step of the recruiting process — the assessments! Our "
        "hiring assessments are a mix of technical and non-technical exercises.",
        "in-house, thread 19ff40b2535c5a0a",
    ),
    (
        "[Action Required] Your {display} Assessments Expire in 24 hours",
        "Your Assessments Expire in 24 Hours Hi Ayush, Thank you for your "
        "continued interest in {display}! Quick reminder that your assessments "
        "expire in 24 hours. Please complete them before then to stay in the "
        "process.",
        "in-house, thread 1a01322a12d04776",
    ),
    (
        "Reminder from {display}!",
        "Hey Ayush, We hope you're doing well. Our team noticed you haven't had "
        "a chance to complete your assessments yet. We understand it's a busy "
        "time of year; if you need more time or your link has expired, let us "
        "know.",
        "in-house, thread 1a00f380a6de6b0c — never says assessment invitation",
    ),
)

#: Mail that CLOSES an application without ever using a rejection word. The
#: sharpest shape in this file: the application is over, and nothing in the text
#: says regret, decline, or not moving forward.
OBSERVED_CLOSURES: tuple[Template, ...] = (
    (
        "Your {display} Assessments Have Expired",
        "Your {display} Assessments Have Expired Hi Ayush, The assessments for "
        "your application have expired and as a result, your application is no "
        "longer active. If you're still interested in our openings you are "
        "welcome to apply again in the future.",
        "in-house, thread 1a0188225c95eca6 — a rejection in effect",
    ),
)

#: Action-required mail that is NOT an assessment: the application exists but is
#: not finished. ``pending_application`` in the product's vocabulary.
OBSERVED_PENDING: tuple[Template, ...] = (
    (
        "[Action Required] Your {display} Application",
        "Email Verification Hi Ayush, Thank you for submitting your application "
        "for a position at {display}! Please click here to verify your email "
        "address and move to the next application step.",
        "in-house, thread 19fee9ebfef4b967",
    ),
    (
        "Keep track of your application",
        "Hi Ayush, Thank you for your interest in {role} (ID: {req}). If you "
        "have completed the application: Great! You can now check the "
        "application status in your candidate portal.",
        "in-house, thread 19ff8301447def4c — a SECOND mail per application",
    ),
)

#: Job-adjacent mail that must mint nothing. Observed, not invented — the
#: counterpart to ``ats-relay-noise``, which is disclosed as invented because
#: this mailbox held no ATS job-alert digest to sample.
OBSERVED_NOT_APPLICATIONS: tuple[Template, ...] = (
    (
        "Your {display} Career Profile verification code",
        "Enter this code in Career Profile. Career Profile Your {display} "
        "Career Profile verification code Hi Ayush, Your verification code is: "
        "500108 This code expires in 10 minutes. If you didn't request a code "
        "you can ignore this message.",
        "in-house, thread 19ff828f23c57701 — says Career three times, is not one",
    ),
)
