"""Ten thousand invented emails that exercise the WHOLE product, not one layer.

This module is the instrument issue #417 cited and the repository did not have.
Its numbers — 54.11% accuracy, 60 of 60 rescinded offers filed as offers, 5.0%
of auto-filed mail confidently wrong — were quoted from a generator at
``backend/tests/corpus_independent/generate.py`` that has never existed in this
repository under any ref (``git log --all -S corpus_independent`` returns
nothing). A measurement nobody can re-run is a claim, not a measurement, so this
is that file: written to make those numbers reproducible and to keep them
honest from here on.

What makes it different from its two siblings
---------------------------------------------
``tests/corpus/mail.py`` measures CLASSIFICATION (does the verdict in the
message reach the right category). ``tests/corpus/generator.py`` measures
IDENTITY (does one application land on one card). Each is right about its own
layer and blind past it — and the blindness has cost real defects: on
2026-08-21 the identity corpus scored a rebuild clean while every real sync,
which is a delta, folded three applications onto one card.

This corpus runs the path a MESSAGE actually takes::

    Gmail delivers  ->  RulesClassifier.classify  ->  PipelineItem
                    ->  roll_up_applications / collect_review_items
                    ->  upsert_applications_for_user  ->  the board

and scores what is on the board at the end. A rule that classifies perfectly
and files onto the wrong card fails here, which is the point.

What is DELIVERED, and why that is its own field
------------------------------------------------
Production classifies ``extract_body_text(payload) or snippet``: the body when
one can be extracted, otherwise Gmail's ~186-character snippet. Which one it got
decides the verdict for a whole family of mail — an ATS rejection spends the
entire snippet budget on a polite preamble, so the classifier reads the
preamble, scores a CONFIRMATION, and files it. Every case therefore carries both
``body`` (what the mail says) and ``delivered`` (what the classifier sees), and
the families that turn on the difference set them apart deliberately.

Ground truth, and the trap in it
--------------------------------
``identity`` is opaque: two cases sharing it MUST end on one card, two with
different keys MUST NOT, and ``None`` means the message must never become an
application at all. It has to agree with the PRODUCT's identity rule, which is
``(employer, req_id or role_token)`` — so employers come from a disjoint pool
and no two families share one unless the family is deliberately about sharing.

The hard rule: every employer, role, sender and body below is invented. What is
borrowed from reality is the shape — relay domains, subject conventions, and
the exact phrasings that break things.

Determinism
-----------
Seeded; every choice derives from the seed and the case index. The same seed
produces a byte-identical corpus under any ``PYTHONHASHSEED``, which
``test_independent_corpus.py`` checks by digest. A corpus that differs between
runs cannot be a regression gate.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from .employers import EmployerPool

#: Day zero. Everything is dated forward from here so the replay can batch by
#: day the way an incremental sync does.
EPOCH = datetime(2026, 3, 2, 9, 0, 0)

#: Gmail's snippet is documented at ~200 characters and measures ~186 in the
#: owner's mailbox. The families that turn on truncation cut here.
SNIPPET_CHARS = 186

ROLES: tuple[str, ...] = (
    "Software Engineer I",
    "Software Engineer, New Grad",
    "Backend Engineer",
    "Frontend Engineer",
    "Platform Engineer",
    "Data Engineer",
    "Infrastructure Engineer",
    "Machine Learning Engineer",
    "Systems Engineer",
    "Product Engineer",
    "Associate Software Engineer",
    "Software Engineer, Early Career",
)

#: Relay domains, borrowed as SHAPES. Every employer sending through them is
#: invented; the domains are what real applicant tracking systems use and what
#: ``rules.ATS_DOMAINS`` is keyed on, so inventing those too would leave the ATS
#: floor unexercised.
ATS_SENDERS: tuple[str, ...] = (
    "no-reply@us.greenhouse-mail.io",
    "no-reply@ashbyhq.com",
    "no-reply@hire.lever.co",
    "no-reply@myworkday.com",
    "notification@smartrecruiters.com",
    "no-reply@ats.rippling.com",
)


@dataclass(frozen=True)
class Case:
    """One generated email plus everything the product is supposed to do with it."""

    message_id: str
    thread_id: str | None
    subject: str
    sender: str
    sender_name: str | None
    #: What the mail says, in full.
    body: str
    #: What reaches ``classify()`` — the body, or the snippet when no body can
    #: be extracted. See the module docstring.
    delivered: str
    received_at: datetime
    family: str
    #: Ground truth for the CLASSIFIER.
    expected_category: str
    #: Ground truth for the BOARD. None = must never become an application.
    identity: str | None
    employer: str | None
    #: Deliberately constructed to defeat the classifier, rather than ordinary
    #: mail that happens to be hard. Reported separately: a headline accuracy
    #: number over a corpus that is a third adversarial describes the corpus.
    adversarial: bool = False
    #: Role-less mail at a multi-application employer is SUPPOSED to be
    #: unplaceable. Scored in its own bucket so designed behaviour does not read
    #: as failure.
    expect_review: bool = False
    note: str = ""


def snippet_of(body: str) -> str:
    """Gmail's snippet, as production receives it.

    Whitespace collapsed, then truncated — which is what makes the truncation
    families measure something: a verdict beginning at offset 150 still runs off
    the end, so "the snippet reached the verdict" and "the snippet contained the
    verdict" are different questions with different answers.
    """

    return " ".join(body.split())[:SNIPPET_CHARS]


class _Builder:
    """Builds the corpus. Every VARIABLE choice comes from ``self.rng``.

    THE SEED USED TO BE DEAD. ``random.Random(seed)`` was constructed here and
    never called once: every choice in the file was ``[i % len(...)]``, so all
    three seeds produced a byte-identical 10,040 messages and a run at three
    seeds measured the same corpus three times. It read as reassurance and was
    a check that could not fail — this file's own docstring claimed "every
    choice derives from the seed and the case index" while nothing did.

    What is seeded and what is not is the load-bearing distinction. The seed
    varies WHICH employer, role, ATS sender and wording a case gets. It never
    varies how many cases a family has, what category each is, or what the
    board should look like — those are the ground truth, and a corpus whose
    expectations move with its seed measures nothing. So a re-seed is a
    different sample of the same population, which is exactly what makes
    running three of them worth the minutes.

    Determinism is unaffected: one ``Random`` drawn from in a fixed order, so
    the same seed still gives byte-identical output and the digest gate still
    holds.
    """

    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.employers = EmployerPool(self.rng)
        self.cases: list[Case] = []
        self._n = 0

    def employer(self) -> tuple[str, str]:
        return self.employers.take()

    def pick(self, options):
        """One of ``options``, from the seed.

        Replaces ``options[i % len(options)]``. The round-robin was not merely
        unseeded, it also locked wording to position: every third confirmation
        got template 3 forever, so a defect that only fires on one wording was
        pinned to exactly n/3 across every run and looked like a property of
        the product.
        """

        return options[self.rng.randrange(len(options))]

    def role(self, _i: int = 0) -> str:
        return self.pick(ROLES)

    def ats(self, _i: int = 0) -> str:
        return self.pick(ATS_SENDERS)

    def add(
        self,
        *,
        family: str,
        subject: str,
        sender: str,
        body: str,
        expected_category: str,
        identity: str | None,
        employer: str | None,
        sender_name: str | None = None,
        delivered: str | None = None,
        thread: str | None = None,
        day: int | None = None,
        adversarial: bool = False,
        expect_review: bool = False,
        note: str = "",
    ) -> Case:
        self._n += 1
        mid = f"c{self._n:05d}"
        when = EPOCH + timedelta(
            days=(self._n % 240) if day is None else day, minutes=self._n % 53
        )
        case = Case(
            message_id=mid,
            thread_id=thread,
            subject=subject,
            sender=sender,
            sender_name=sender_name,
            body=body,
            delivered=body if delivered is None else delivered,
            received_at=when,
            family=family,
            expected_category=expected_category,
            identity=identity,
            employer=employer,
            adversarial=adversarial,
            expect_review=expect_review,
            note=note,
        )
        self.cases.append(case)
        return case


# ── the ordinary lifecycle ───────────────────────────────────────────────────
#
# Roughly two thirds of the corpus. Mail that says plainly what it is, because a
# corpus made only of hard cases measures how the classifier fails and says
# nothing about whether it still works.


def _confirmations(b: _Builder, n: int) -> None:
    """"We received your application" in the wordings ATS vendors ship."""

    templates = (
        ("Thank you for applying to {e}",
         "Hi Ayush, Thank you for applying to the {r} position at {e}. "
         "Your application has been received and our team will review it shortly."),
        ("Your application to {e}",
         "Hello Ayush, We have received your application for the {r} role at {e}. "
         "We review every application carefully and will be in touch if there is a fit."),
        ("{e} | Application Received",
         "Hi Ayush, Thank you for applying to our role: {r}. We appreciate your "
         "interest in joining the team and will review your application shortly."),
        ("Thanks for applying to {e}!",
         "Hi Ayush, Thanks for your interest in the {r} opening at {e}. "
         "We have received your application and will be reviewing it this week."),
    )
    for i in range(n):
        display, token = b.employer()
        role = b.role(i)
        subject, body = b.pick(templates)
        b.add(
            family="confirmation",
            subject=subject.format(e=display, r=role),
            sender=b.ats(i),
            sender_name=f"{display} Recruiting",
            body=body.format(e=display, r=role),
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
        )


def _rejections_plain(b: _Builder, n: int) -> None:
    """The verdict is in the first sentence, where the classifier can see it."""

    templates = (
        ("Update on your application to {e}",
         "Hi Ayush, After careful consideration we have decided not to move forward "
         "with your application for the {r} role at {e}. We appreciate your interest."),
        ("Your {e} application",
         "Hello Ayush, Unfortunately we will not be moving forward with your "
         "candidacy for the {r} position. We wish you the very best in your search."),
        ("Thank you from {e}",
         "Dear Ayush, We regret to inform you that we have decided to proceed with "
         "other candidates for the {r} role. Thank you for the time you invested."),
    )
    for i in range(n):
        display, token = b.employer()
        role = b.role(i)
        subject, body = b.pick(templates)
        # The confirmation first, so the rejection has an application to settle.
        b.add(
            family="rejection-plain",
            subject=f"Thank you for applying to {display}",
            sender=b.ats(i),
            sender_name=f"{display} Recruiting",
            body=(
                f"Hi Ayush, Thank you for applying to the {role} position at "
                f"{display}. We have received your application."
            ),
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 60,
        )
        b.add(
            family="rejection-plain",
            subject=subject.format(e=display, r=role),
            sender=b.ats(i),
            sender_name=f"{display} Recruiting",
            body=body.format(e=display, r=role),
            expected_category="rejection",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 60 + 14,
        )


def _rejections_past_the_snippet(b: _Builder, n: int) -> None:
    """THE KNOWN ONE, and the reason ``delivered`` exists as a field.

    An applicant tracking system spends its whole opening paragraph thanking the
    candidate before it says no. Gmail's snippet is ~186 characters, so what
    reaches the classifier is pure preamble — it reads a CONFIRMATION and scores
    one. Measured on the owner's real mail: four rejections, 4/4 correct from
    the full body, 0/4 from the snippet (two wrong, two dropped).

    The body is here in full so the same case can be scored both ways; only the
    snippet is delivered, which is what production does when no body part can be
    extracted.
    """

    for i in range(n):
        display, token = b.employer()
        role = b.role(i)
        body = (
            f"Hi Ayush, Thank you so much for taking the time to apply for the "
            f"{role} opening at {display}. We know a lot of thought and "
            f"consideration went into your application, and the team genuinely "
            f"appreciates your interest in what we are building here. "
            f"After careful review we have decided not to move forward with your "
            f"candidacy at this time. We wish you the very best."
        )
        b.add(
            family="rejection-past-the-snippet",
            subject=f"Important information about your application to {display}",
            sender=b.ats(i),
            sender_name=None,
            body=(
                f"Hi Ayush, Thank you for applying to the {role} position at "
                f"{display}. Your application has been received."
            ),
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 60,
        )
        b.add(
            family="rejection-past-the-snippet",
            subject=f"Important information about your application to {display}",
            sender=b.ats(i),
            sender_name=None,
            body=body,
            delivered=snippet_of(body),
            expected_category="rejection",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 60 + 21,
            adversarial=True,
            note="the verdict is at character ~330; the snippet ends at 186",
        )


def _interviews(b: _Builder, n: int) -> None:
    for i in range(n):
        display, token = b.employer()
        role = b.role(i)
        b.add(
            family="interview",
            subject=f"Thank you for applying to {display}",
            sender=b.ats(i),
            sender_name=f"{display} Talent",
            body=f"Hi Ayush, We have received your application for the {role} role at {display}.",
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 60,
        )
        b.add(
            family="interview",
            subject=f"Interview with {display} — {role}",
            sender=b.ats(i),
            sender_name=f"{display} Talent",
            body=(
                f"Hi Ayush, We would like to schedule an interview with you for the "
                f"{role} position. Please use the link below to pick a time that works."
            ),
            expected_category="interview",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 60 + 9,
        )


def _assessments(b: _Builder, n: int) -> None:
    for i in range(n):
        display, token = b.employer()
        role = b.role(i)
        b.add(
            family="assessment",
            subject=f"Thank you for applying to {display}",
            sender=b.ats(i),
            sender_name=f"{display} Talent",
            body=f"Hi Ayush, Thank you for applying to the {role} position at {display}.",
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 60,
        )
        b.add(
            family="assessment",
            subject=f"[Action Required] Your {display} assessment",
            sender=b.ats(i),
            sender_name=f"{display} Talent",
            body=(
                "Hi Ayush, The next step is a short online assessment. Please "
                "complete the coding exercise linked below within five days."
            ),
            expected_category="assessment",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 60 + 6,
        )


def _offers(b: _Builder, n: int) -> None:
    for i in range(n):
        display, token = b.employer()
        role = b.role(i)
        b.add(
            family="offer",
            subject=f"Thank you for applying to {display}",
            sender=b.ats(i),
            sender_name=f"{display} Talent",
            body=f"Hi Ayush, Thank you for applying to the {role} position at {display}.",
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 60,
        )
        b.add(
            family="offer",
            subject=f"Your offer from {display}",
            sender=b.ats(i),
            sender_name=f"{display} Talent",
            body=(
                f"Hi Ayush, We are delighted to extend you an offer to join {display} "
                f"as a {role}. The written offer is attached and we are thrilled at "
                "the prospect of you joining the team."
            ),
            expected_category="offer",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 60 + 30,
        )


# ── the adversarial third ────────────────────────────────────────────────────
#
# Mail constructed to defeat the classifier. Reported separately, always: a
# headline accuracy number over a corpus that is a third adversarial by
# construction describes the corpus, not the product.


def _rescinded_offers(b: _Builder, n: int) -> None:
    """Issue #417, reconstructed so the claim can be re-measured.

    A withdrawal that quotes its own thread history. The quoted history carries
    the original offer's language, that language scores ``offer``, and the
    withdrawal's own words do not score against it hard enough to win — so the
    board shows an offer the person does not have, above the auto-file gate,
    with no review.

    This is the one error in the corpus that ASSERTS SOMETHING FALSE about a
    user's life rather than leaving them where they were. Someone checking their
    board to decide whether to keep interviewing gets the wrong answer, and the
    mail that would correct it has already been filed as the thing it
    contradicts.

    It is the exact inverse of the rejection problem: the classifier is reluctant
    to assert a negative outcome and eager to assert a positive one.
    """

    withdrawals = (
        "Hi Ayush, I am writing with difficult news. Due to a change in headcount "
        "we have had to withdraw the offer for this position. I am very sorry to "
        "be sending this and I know it is disruptive.",
        "Hi Ayush, Unfortunately the role has been put on hold and we are no longer "
        "able to proceed with the offer we sent last week. We are truly sorry.",
        "Hello Ayush, Following a company-wide hiring freeze announced this morning, "
        "we must rescind the offer extended to you. This is not a reflection of your "
        "candidacy and we are sorry for the disruption.",
    )
    for i in range(n):
        display, token = b.employer()
        role = b.role(i)
        thread = f"offer-thread-{token}"
        b.add(
            family="rescinded-offer",
            subject=f"Your offer from {display}",
            sender=b.ats(i),
            sender_name=f"{display} Talent",
            body=(
                f"Hi Ayush, We are delighted to extend you an offer to join {display} "
                f"as a {role}. We are thrilled at the prospect of you joining the team."
            ),
            expected_category="offer",
            identity=f"{token}|{role}",
            employer=token,
            thread=thread,
            day=i % 60,
        )
        withdrawal = b.pick(withdrawals)
        b.add(
            family="rescinded-offer",
            subject=f"Re: Your offer from {display}",
            sender=b.ats(i),
            sender_name=f"{display} Talent",
            body=(
                f"{withdrawal}\n\n"
                f"On Monday, {display} Talent wrote:\n"
                f"> Hi Ayush, We are delighted to extend you an offer to join\n"
                f"> {display} as a {role}. We are thrilled at the prospect of\n"
                f"> you joining the team.\n"
            ),
            expected_category="rejection",
            identity=f"{token}|{role}",
            employer=token,
            thread=thread,
            day=i % 60 + 3,
            adversarial=True,
            note="the offer language is in QUOTED HISTORY; the mail's own words withdraw it",
        )


def _quoted_history(b: _Builder, n: int) -> None:
    """The family #417 points at as the general case behind the specific one.

    The scoring walk does not distinguish the mail's own text from history it
    quotes. Here the two disagree in both directions, so a fix that simply
    ignores everything after a quote marker has to survive the case where the
    quote is the only thing that names the role.
    """

    for i in range(n):
        display, token = b.employer()
        role = b.role(i)
        thread = f"reply-{token}"
        b.add(
            family="quoted-history",
            subject=f"Thank you for applying to {display}",
            sender=b.ats(i),
            sender_name=f"{display} Recruiting",
            body=f"Hi Ayush, Thank you for applying to the {role} position at {display}.",
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
            thread=thread,
            day=i % 60,
        )
        b.add(
            family="quoted-history",
            subject=f"Re: Thank you for applying to {display}",
            sender=b.ats(i),
            sender_name=f"{display} Recruiting",
            body=(
                "Hi Ayush, Following up on the below — we would love to set up a "
                "conversation with you next week. Are you free Thursday?\n\n"
                f"On Tuesday, {display} Recruiting wrote:\n"
                f"> Hi Ayush, Thank you for applying to the {role} position at\n"
                f"> {display}. Your application has been received.\n"
            ),
            expected_category="interview",
            identity=f"{token}|{role}",
            employer=token,
            thread=thread,
            day=i % 60 + 5,
            adversarial=True,
            note="the quote is the only place the ROLE appears; identity needs it",
        )


def _conditional_explainers(b: _Builder, n: int) -> None:
    """Fixed on 2026-08-21 (#431). Here so it stays fixed.

    A confirmation that explains, in a conditional, what a rejection would look
    like: "if you are not selected for the role, your profile will remain on
    file". The classifier used to read "not selected for the role" as a verdict
    and score REJECTION, and the four Microsoft confirmations the owner reported
    were dropped on exactly this.

    Paired with the same clause ASSERTED, which must still read as a rejection —
    without that control, "never score this phrase" would pass.
    """

    for i in range(n):
        display, token = b.employer()
        role = b.role(i)
        b.add(
            family="conditional-explainer",
            subject=f"Thank you for your application to {display}",
            sender=b.ats(i),
            sender_name=f"{display} Careers",
            body=(
                f"Hi Ayush, Thank you for taking the time to submit your application "
                f"for {role} at {display}. We are glad you are interested in a career "
                "here. If you are not selected for the role, your profile will remain "
                "on file and our recruiters may contact you about other openings.",
            )[0],
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 60,
            adversarial=True,
            note="'not selected for the role' sits inside an IF",
        )
        b.add(
            family="conditional-explainer",
            subject=f"Update on your application to {display}",
            sender=b.ats(i),
            sender_name=f"{display} Careers",
            body=(
                f"Hi Ayush, Thank you for your interest in {display}. You were not "
                f"selected for the {role} role. Your profile will remain on file."
            ),
            expected_category="rejection",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 60 + 11,
            note="THE CONTROL: the same clause asserted is still a rejection",
        )


def _verdict_past_the_body_cap(b: _Builder, n: int) -> None:
    """``_MAX_BODY_CHARS`` is 4000 and a long thread runs past it.

    Not the same defect as the snippet cut and worth separating: here a body IS
    extractable, it is simply longer than the classifier reads. A newsletter-
    length signature block plus a legal footer gets there faster than anyone
    expects.
    """

    filler = (
        "This message and any attachments are confidential and intended solely "
        "for the addressee. If you have received it in error please notify the "
        "sender and delete it from your system. "
    )
    for i in range(n):
        display, token = b.employer()
        role = b.role(i)
        body = (
            f"Hi Ayush, Thank you for your continued interest in {display}. "
            + filler * 40
            + f"After careful consideration we are not moving forward with your "
            f"application for the {role} role."
        )
        b.add(
            family="verdict-past-the-body-cap",
            subject=f"Thank you for applying to {display}",
            sender=b.ats(i),
            sender_name=None,
            body=f"Hi Ayush, Thank you for applying to the {role} position at {display}.",
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 60,
        )
        b.add(
            family="verdict-past-the-body-cap",
            subject=f"Update on your {display} application",
            sender=b.ats(i),
            sender_name=None,
            body=body,
            expected_category="rejection",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 60 + 15,
            adversarial=True,
            note=f"the verdict starts at character ~{len(body) - 90}; the cap is 4000",
        )


# ── mail that must never become an application ───────────────────────────────


def _not_job_mail(b: _Builder, n: int) -> None:
    """Job alerts, newsletters, receipts, security codes, recruiter outreach.

    ``identity=None`` means the board must stay untouched. A job ALERT is the
    dangerous one and is deliberately over-represented: it is about jobs, it
    names roles and employers, and every phrase the confirmation patterns look
    for appears in it. A board that mints a card per alert is worse than useless.
    """

    for i in range(n):
        display, token = b.employer()
        role = b.role(i)
        kind = i % 5
        if kind == 0:
            subject, body, sender = (
                f"{role} and 12 more jobs for you",
                f"New roles matching your search: {role} at {display}, and 12 others. "
                "Apply now — these openings are filling quickly. Manage your job alerts "
                "in your account settings.",
                "jobs-noreply@boardsite.test",
            )
        elif kind == 1:
            subject, body, sender = (
                "Your weekly engineering digest",
                "This week: what we learned shipping a distributed scheduler, plus five "
                "links worth your time. You are receiving this because you subscribed. "
                "Unsubscribe at any time.",
                "digest@newsletter.test",
            )
        elif kind == 2:
            subject, body, sender = (
                "Your order has shipped",
                "Good news — your order has shipped. Tracking number: 992837465521. "
                "Estimated delivery is Thursday. View your order details in your account.",
                "orders@shop.test",
            )
        elif kind == 3:
            subject, body, sender = (
                "Your verification code",
                "Your one-time passcode is 448120. It expires in ten minutes. If you did "
                "not request this, secure your account immediately.",
                "security@accounts.test",
            )
        else:
            subject, body, sender = (
                f"Opportunity at {display}",
                f"Hi Ayush, I came across your profile and thought you might be a fit "
                f"for a {role} opening at {display}. Would you be open to a quick chat "
                "this week? I would love to tell you more about the team.",
                "recruiter@agency.test",
            )
        b.add(
            family="not-job-mail",
            subject=subject,
            sender=sender,
            sender_name=None,
            body=body,
            expected_category="other",
            identity=None,
            employer=None,
            adversarial=(kind == 0),
            note="a job alert names roles and employers and must still mint nothing"
            if kind == 0
            else "",
        )


# ── identity ─────────────────────────────────────────────────────────────────


def _repeat_anonymous(b: _Builder, n: int) -> None:
    """Applying more than once where the mail names nothing.

    The defect the owner reported on 2026-08-21. Three confirmations from one
    employer, byte-identical, no role and no requisition number in any of them —
    three applications that showed as one card dated the first, so a sync that
    classified every message correctly showed a board that had not moved.
    """

    for i in range(n):
        display, token = b.employer()
        for k in range(3):
            b.add(
                family="repeat-anonymous",
                subject=f"Thanks for applying to {display}",
                sender=f"noreply@{token.split()[0]}.test",
                sender_name=f"{display} Recruiting",
                body=(
                    f"Hi Ayush, Thanks for applying to {display}! There are a ton of "
                    "great companies out there, so we appreciate your interest in "
                    "joining our team. While we are not able to reach out to every "
                    "applicant, our recruiting team will contact you if your skills "
                    "and experience are a strong match for the role."
                ),
                expected_category="applied",
                identity=f"{token}|__apply{k}__",
                employer=token,
                day=(i % 40) + k * 6,
                note="nothing in the mail tells these three apart",
            )


def _req_id_same_title(b: _Builder, n: int) -> None:
    """Two openings, one title, different requisition numbers.

    The employer's own number is the only thing that separates them, and it
    outranks everything — a role-token match must not collapse them.
    """

    for i in range(n):
        display, token = b.employer()
        role = b.role(i)
        thread = f"reqs-{token}"
        for k, req in enumerate((f"R-{40000 + i}", f"R-{50000 + i}")):
            b.add(
                family="req-id-same-title",
                subject=f"Thank you for applying to {display}",
                sender=b.ats(i),
                sender_name=f"{display} Careers",
                body=(
                    f"Hi Ayush, Thanks for applying to {display}! We have received your "
                    f"application for the {role} ({req}) position."
                ),
                expected_category="applied",
                identity=f"{token}|{req}",
                employer=token,
                thread=thread,
                day=(i % 40) + k,
                note="same title, different requisition — and ONE Gmail thread",
            )


def _update_in_thread(b: _Builder, n: int) -> None:
    """Two applications, and an update that says which one by conversation.

    The update names no role. Its thread does. Guessing wrong is not cosmetic:
    ``advance_application_status`` treats a terminal status as final, so a
    misfiled rejection freezes a live application against every later interview
    and offer.
    """

    for i in range(n):
        display, token = b.employer()
        for k in range(2):
            thread = f"conv-{token}-{k}"
            b.add(
                family="update-in-thread",
                subject="Your application has been received!",
                sender=b.ats(i),
                sender_name=f"{display} via Relay",
                body=(
                    f"Hi Ayush, Thanks for applying to {display}. Our team will review "
                    "your application shortly."
                ),
                expected_category="applied",
                identity=f"{token}|__apply{k}__",
                employer=token,
                thread=thread,
                day=(i % 40) + k,
            )
            b.add(
                family="update-in-thread",
                subject=f"Next step in your {display} application",
                sender=b.ats(i),
                sender_name=f"{display} via Relay",
                body=(
                    "Hi Ayush, Please complete the take-home exercise linked below "
                    "within five days to move to the next stage."
                ),
                expected_category="assessment",
                identity=f"{token}|__apply{k}__",
                employer=token,
                thread=thread,
                day=(i % 40) + k + 7,
                note="an update in its own application's conversation must not open a card",
            )


def _ambiguous_update(b: _Builder, n: int) -> None:
    """Two applications and an update that names neither. MUST be asked about.

    Not a failure — the designed answer. Scored in its own bucket so the correct
    behaviour does not swamp the ranked table.
    """

    for i in range(n):
        display, token = b.employer()
        for k, role in enumerate(b.rng.sample(ROLES, 2)):
            b.add(
                family="ambiguous-update",
                subject=f"Thank you for applying to {display}",
                sender=b.ats(i),
                sender_name=f"{display} Careers",
                body=f"Hi Ayush, Thank you for your interest in the {role} position at {display}.",
                expected_category="applied",
                identity=f"{token}|{role}",
                employer=token,
                day=(i % 40) + k,
            )
        b.add(
            family="ambiguous-update",
            subject=f"Update from {display}",
            sender=b.ats(i),
            sender_name=f"{display} Careers",
            body=(
                "Hi Ayush, Thank you for your time. After careful consideration we "
                "have decided to move forward with other candidates."
            ),
            expected_category="rejection",
            identity=None,
            employer=token,
            expect_review=True,
            day=(i % 40) + 12,
            note="names no role at a two-application employer: the queue, not a guess",
        )


def _bare_relay(b: _Builder, n: int) -> None:
    """A relay whose display name names nobody.

    Applying THROUGH an ATS is not applying TO one. These must resolve to no
    employer at all rather than minting a "Greenhouse" card.
    """

    for i in range(n):
        b.add(
            family="bare-relay",
            subject="Your application has been received",
            sender=b.ats(),
            sender_name=None,
            body=(
                "Hi Ayush, Your application has been received. The hiring team will "
                "review it and be in touch if there is a fit."
            ),
            expected_category="applied",
            identity=None,
            employer=None,
            adversarial=True,
            note="no employer is nameable; the board must not invent one",
        )


def _hostile_text(b: _Builder, n: int) -> None:
    """Text engineered to read as one thing and be another.

    Three separate attacks, each its own family in the report so a fix to one
    cannot be read as progress on the others.
    """

    for i in range(n):
        display, token = b.employer()
        role = b.role(i)
        kind = i % 3
        if kind == 0:
            # A RIGHT-TO-LEFT OVERRIDE plus a zero-width space in the sender's
            # display name, so the rendered name is byte-for-byte what the real
            # employer's would be (#424). The mail is genuinely from
            # ``forged``, and the assertion is that the board says so: the
            # DOMAIN wins and the display name does not get to impersonate an
            # employer the user really applied to.
            #
            # Ground truth deliberately names the forged employer rather than
            # nobody. The first version of this case expected no card at all,
            # which is a stricter claim than the product makes and than it
            # should: a confirmation from a real domain is a real application at
            # that domain's employer. It reported a hundred false failures.
            forged_display, forged_token = b.employer()
            b.add(
                family="hostile-bidi-sender",
                subject=f"Thank you for applying to {display}",
                sender=f"no-reply@{forged_token.split()[0]}.test",
                sender_name=f"{display}\u202e\u200b Careers",
                body=f"Hi Ayush, Thank you for applying to the {role} role at {display}.",
                expected_category="applied",
                identity=f"{forged_token.split()[0]}|{role}",
                employer=forged_token.split()[0],
                adversarial=True,
                note=f"display name impersonates {display}; must file under the domain",
            )
        elif kind == 1:
            # PREHEADER TEXT: the first thing the classifier reads and the last
            # thing a person sees. Here it asserts the opposite of the mail.
            b.add(
                family="hostile-preheader",
                subject=f"Update on your application to {display}",
                sender=b.ats(i),
                sender_name=f"{display} Careers",
                body=(
                    "Congratulations on your offer! We are delighted to welcome you. "
                    "\n\n"
                    f"Hi Ayush, After careful consideration we will not be moving "
                    f"forward with your application for the {role} role at {display}."
                ),
                expected_category="rejection",
                identity=f"{token}|{role}",
                employer=token,
                adversarial=True,
                note="a hidden preheader asserts the opposite of the mail's own words",
            )
        else:
            # A ZERO-WIDTH SPACE inside the verdict phrase. Renders identically
            # and defeats a literal pattern.
            b.add(
                family="hostile-zero-width",
                subject=f"Update on your application to {display}",
                sender=b.ats(i),
                sender_name=f"{display} Careers",
                body=(
                    f"Hi Ayush, We will not be mov\u200bing forward with your "
                    f"application for the {role} role at {display}."
                ),
                expected_category="rejection",
                identity=f"{token}|{role}",
                employer=token,
                adversarial=True,
                note="a zero-width space splits the verdict phrase",
            )


def _employer_spelling(b: _Builder, n: int) -> None:
    """One employer, several spellings across its own mail.

    The display name in the relay, the name in the subject, and the domain brand
    disagree — routinely, in real ATS mail. Identity is employer plus role, so a
    near miss on the employer half defeats the whole key before the role is ever
    consulted.
    """

    for i in range(n):
        display, token = b.employer()
        role = b.role(i)
        head = display.split()[0]
        for k, name in enumerate((display, head, display.upper())):
            b.add(
                family="employer-spelling",
                subject=f"Thank you for applying to {name}",
                sender=b.ats(i),
                sender_name=f"{name} Recruiting",
                body=f"Hi Ayush, Thank you for applying to the {role} position at {name}.",
                expected_category="applied",
                identity=f"{token}|{role}",
                employer=token,
                day=(i % 40) + k * 3,
                note="three spellings of ONE employer; one application",
            )


#: Every family, with how many GROUPS of it to build. A group is one employer's
#: worth, which is one to three messages depending on the family — the counts
#: below are chosen so the corpus lands near ten thousand messages with roughly
#: a third of them adversarial by construction.
_FAMILIES: tuple[tuple[str, object, int], ...] = (
    ("confirmation", _confirmations, 1100),
    ("rejection-plain", _rejections_plain, 550),
    ("rejection-past-the-snippet", _rejections_past_the_snippet, 350),
    ("interview", _interviews, 350),
    ("assessment", _assessments, 330),
    ("offer", _offers, 220),
    ("rescinded-offer", _rescinded_offers, 260),
    ("quoted-history", _quoted_history, 200),
    ("conditional-explainer", _conditional_explainers, 200),
    ("verdict-past-the-body-cap", _verdict_past_the_body_cap, 160),
    ("not-job-mail", _not_job_mail, 700),
    ("repeat-anonymous", _repeat_anonymous, 200),
    ("req-id-same-title", _req_id_same_title, 200),
    ("update-in-thread", _update_in_thread, 150),
    ("ambiguous-update", _ambiguous_update, 150),
    ("bare-relay", _bare_relay, 200),
    ("hostile-text", _hostile_text, 300),
    ("employer-spelling", _employer_spelling, 150),
)


def generate(seed: int = 20260822) -> list[Case]:
    """Build the corpus. Deterministic: same seed, byte-identical output."""

    b = _Builder(seed)
    for _name, family, n in _FAMILIES:
        family(b, n)
    return b.cases


@dataclass(frozen=True)
class Stats:
    """What the corpus IS, counted by the builder rather than read back off it.

    Derived at build time on purpose. Recomputing the count from
    ``{c.employer for c in cases}`` reads the same number off the mail, and a
    static analyser cannot tell a count of invented company names from a count
    of real ones — CodeQL flagged printing it as clear-text logging of private
    data, correctly in the general case. It is also simply the better number:
    the builder knows how many it handed out, including the forged ones the
    impersonation family mints and deliberately never files under.

    The field is ``companies`` rather than ``employers`` for the same reason
    and it is the more accurate word: CodeQL classifies ``employ*`` as private
    information about a PERSON (employment status is PII), which is exactly
    right for a field naming somebody's employer and exactly wrong for a count
    of invented corporate names. Naming it for what it counts settles both.
    """

    messages: int
    companies: int
    adversarial: int


def stats(seed: int = 20260822) -> Stats:
    b = _Builder(seed)
    for _name, family, n in _FAMILIES:
        family(b, n)
    return Stats(
        messages=len(b.cases),
        companies=b.employers.used,
        adversarial=sum(1 for c in b.cases if c.adversarial),
    )


def digest(cases: list[Case]) -> str:
    """A stable hash of the whole corpus, for the determinism gate.

    Over the FIELDS rather than over ``repr``: a dataclass repr would change
    when a field is added and the digest would have to be re-recorded for a
    change that altered no mail.
    """

    import hashlib

    h = hashlib.sha256()
    for c in cases:
        h.update(
            "\x1f".join(
                (
                    c.message_id,
                    c.thread_id or "",
                    c.subject,
                    c.sender,
                    c.sender_name or "",
                    c.body,
                    c.delivered,
                    c.received_at.isoformat(),
                    c.family,
                    c.expected_category,
                    c.identity or "",
                    c.employer or "",
                    str(c.adversarial),
                    str(c.expect_review),
                )
            ).encode()
        )
        h.update(b"\x1e")
    return h.hexdigest()


if __name__ == "__main__":  # pragma: no cover - human inspection aid
    from collections import Counter

    cases = generate()
    st = stats()
    print(f"{st.messages} messages, digest {digest(cases)[:16]}")
    print(f"{st.adversarial} adversarial ({st.adversarial / st.messages:.1%})")
    print(f"{st.companies} companies\n")
    for family, n in sorted(Counter(c.family for c in cases).items()):
        print(f"  {family:30s} {n:5d}")
