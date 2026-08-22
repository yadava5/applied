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

from . import observed
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
    # THE LONG TAIL, and it is not decoration — every title above is at most 31
    # characters, and that is why no gate in this repo had ever exercised a
    # bounded window against a realistic one. Measured in the owner's mailbox
    # 2026-08-22, real titles run to 78:
    #
    #   78  Software Development Engineer I - AI/ML Network Infra..., <Sub-brand>
    #   72  Software Engineer I, Entry-Level (Graduation Date: Fall 2025-Summer 2026)
    #   66  Software Development Engineer I, ML Infra Services, <Sub-brand>
    #   58  Software Engineer, Agentic AI Harness & Quality - <Product>
    #   47  Associate Software Engineer, Operator Experience
    #
    # SHAPES ARE REAL, NAMES ARE NOT, the same rule `observed.py` follows: the
    # employer sub-brands and product names in the originals are replaced with
    # invented ones of the same length, because which companies the owner
    # applied to is career-sensitive and the LENGTH is the whole point.
    #
    # `_ROLE_PATTERNS` bounds its capture at 90 characters and a real Amazon
    # confirmation puts the requisition id between the title and the word
    # "position" — 92 characters — so the regex backtracked and returned a
    # PARTIAL title, silently dropping the first word. The role token is the
    # application identity, so the confirmation and a later update disagreed
    # about which application they were. See #466.
    "Software Development Engineer I - AI/ML Network Infrastructure, Kestrel Labs",
    "Software Engineer I, Entry-Level (Graduation Date: Fall 2025-Summer 2026)",
    "Software Development Engineer I, ML Infra Services, Kestrel Labs",
    "Software Engineer, Agentic AI Harness & Quality - Talonflow",
    "Associate Software Engineer, Operator Experience",
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
    #: The message this one must end up sharing a CARD with.
    #:
    #: "If it is an update, it updates the existing card" stated per message
    #: rather than inferred. ``identity`` already catches the case where an
    #: update mints a second card at the same identity — it shows as a SPLIT —
    #: but SPLIT is a shape, not a diagnosis, and the failure a user actually
    #: reports is "a second Google appeared". Naming the join makes the report
    #: say which message opened the card it should have joined.
    joins: str | None = None
    #: What the card must READ once this message has been filed.
    #:
    #: The other half of "an update updates the existing card". Landing on the
    #: right card is necessary and not sufficient: a rejection that files onto
    #: the right row and leaves it at ``applied`` has updated nothing a user
    #: can see. Set on the LAST message of a scenario, because a status is a
    #: property of the card after everything has arrived, not of one message.
    card_status: str | None = None
    #: This message must be ADDRESSED: a card, or the review queue. Mail that
    #: must mint nothing leaves it False. See ``BoardScore.lost``.
    #:
    #: DERIVED IN ``__post_init__`` and not by the builder, which is where it
    #: started. A field the builder fills is a field that is wrong for every
    #: ``Case`` constructed any other way — the branch probe in
    #: ``test_independent_corpus.py`` builds cases directly, got ``False`` for
    #: all of them, and its LOST/DROPPED assertions silently exercised nothing.
    must_be_addressed: bool = False
    note: str = ""

    def __post_init__(self) -> None:
        # A message that names an application IS about an application, and one
        # that must go to the queue is about one too — it is only unplaceable,
        # not unrelated. Derived rather than passed so a family cannot forget
        # to opt in, which is how a coverage check quietly stops covering.
        if not self.must_be_addressed:
            object.__setattr__(
                self,
                "must_be_addressed",
                self.identity is not None or self.expect_review,
            )


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

    def roles(self, k: int) -> list[str]:
        """``k`` DISTINCT roles, from the seed.

        ``role()`` draws with replacement, which is right when each case is
        independent. It is wrong when one case needs several roles that must
        stay apart: two colliding draws would silently make a family about
        distinguishing applications into a family about merging duplicates, and
        the collision rate would be a property of ``len(ROLES)`` rather than of
        anything the product does.
        """

        return self.rng.sample(ROLES, k)

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
        joins: str | None = None,
        card_status: str | None = None,
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
            joins=joins,
            card_status=card_status,
            # `must_be_addressed` is derived in Case.__post_init__.
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
        # TWO REAL WORDINGS, because they fail differently. Both are transcribed
        # from rejections in the owner's mailbox (2026-08-22) and the difference
        # between them is load-bearing: Together AI's preamble says "your
        # application", so anything keying on that phrase reaches it, while
        # Verkada's says "your interest in the {role} opportunity" and never
        # uses the word application at all. A signal measured only against the
        # first would look perfect and miss one of the four real cases.
        body = b.pick(
            (
                # Together AI, thread 19ff7393d56eccfb.
                f"Hi Ayush, Thank you so much for taking the time to apply for "
                f"the {role} opening at {display}. We know a lot of thought and "
                f"consideration went into your application, and the team "
                f"genuinely appreciates your interest in what we are building "
                f"here. After careful review we have decided not to move forward "
                f"with your candidacy at this time. We wish you the very best.",
                # Verkada, thread 19ffc2cae1b51518.
                f"Hi Ayush, Thank you for your interest in the {role} "
                f"opportunity. It means a lot to us that you would consider "
                f"joining our mission here at {display}, and we were glad to "
                f"spend time with what you sent us. Although your background is "
                f"impressive, we have decided not to move forward at this time. "
                f"We hope you will keep an eye on our openings.",
            )
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


def _one_thread_many_roles_in_the_queue(b: _Builder, n: int) -> None:
    """The same lie about a thread, on the path that ASKS instead of filing.

    ``one-thread-many-roles`` covers the filing half and cannot cover this one:
    every message in it clears the auto-file gate, so it becomes a card and
    never reaches ``collect_review_items`` at all. That is exactly why #454
    shipped — the queue keyed on the thread alone for months with a green
    corpus behind it, and one ATS conversation collapsed to a single entry.

    So this family is the same shape at a confidence that reaches the QUEUE:
    four rejections, four roles, one Gmail thread, all drawn from
    ``observed.UNDER_THE_GATE`` — the one transcribed wording the classifier
    reads correctly and is not confident enough to file. Under the old key the
    queue asked about one of the four and the other three were LOST: no card, no
    entry, no counter.

    Four rejections and no confirmations is not the whole story of an
    application and does not need to be. What is being measured here is how many
    DECISIONS a conversation becomes, and adding an acknowledgement ahead of
    each one would file the card the rejection then joins, which is a different
    question that ``update-joins-one-application`` already asks.
    """

    subject_t, body_t, _note = observed.UNDER_THE_GATE
    for i in range(n):
        display, token = b.employer()
        sender = b.ats(i)
        # One subject, one sender — which is the whole reason Gmail threads
        # them, and the reason the rejections of four different applications
        # arrive looking like one conversation.
        thread = f"ats-verdict-{token}"
        for k, role in enumerate(b.roles(4)):
            fill = {"display": display, "role": role, "req": f"R-{700000 + i}"}
            b.add(
                family="one-thread-many-roles-in-the-queue",
                subject=subject_t.format(**fill),
                sender=sender,
                sender_name=f"{display} Recruiting",
                body=body_t.format(**fill),
                expected_category="rejection",
                identity=f"{token}|{role}",
                employer=token,
                thread=thread,
                # ALL FOUR ON ONE DAY, and that is not cosmetic. The harness
                # replays in day-sized batches because that is what a sync is,
                # so a thread spread over four days is four syncs of one message
                # each and the collapse being measured cannot even arise. The
                # first draft of this family did exactly that and stayed green
                # under a deliberately reverted fix. The real thread arrived
                # inside two hours.
                day=i % 40,
                adversarial=True,
                note=(
                    "four applications, one Gmail thread, one sync — and none "
                    "of them confident enough to file, so the QUEUE holds four"
                ),
            )


def _ats_relay_noise(b: _Builder, n: int) -> None:
    """Mail from a known ATS relay that is NOT about an application of yours.

    THE CONTROL FOR THE ATS FLOOR, and it is invented rather than drawn from
    life — say so plainly. Of 201 messages from ``rules.ATS_DOMAINS`` in the
    owner's mailbox over six months (2026-08-22), every single one was about one
    of his own applications; this mailbox contains no counter-example to sample.
    That is a fact about one job seeker, not about the domains, and a floor that
    routes on the sender needs something that can push back on it or it is a
    gate that cannot fail.

    So these are the shapes an ATS relay sends that are not yours: a job-alert
    digest, a talent-community blast, a profile-completion nudge, a candidate
    survey, a referral ask. Every one is transactional mail from a real relay
    domain, and none of them references an application the recipient made.

    That last clause is the whole point. These must stay OUT of the review
    queue, and the only thing separating them from the 610 messages that must go
    IN is whether the text speaks about the reader's own application. If a fix
    for #447 queues these too, it has widened the floor to "sender alone" — the
    exact widening ``pipeline`` declined to make — and this family is what says
    so out loud.
    """

    shapes = (
        (
            "New roles at {display} this week",
            "Hi Ayush, here are the latest openings at {display}: {role}, and "
            "several more on our careers page. Set up an alert to hear first.",
        ),
        (
            "Join the {display} talent community",
            "Hi Ayush, we are building a community of engineers interested in "
            "{display}. Join to hear about openings like {role} before they are "
            "posted publicly.",
        ),
        (
            "Complete your {display} candidate profile",
            "Hi Ayush, your candidate profile is missing a few details. Adding "
            "them helps our recruiters find you for roles such as {role}.",
        ),
        (
            "A quick survey from {display} recruiting",
            "Hi Ayush, we are asking engineers what matters most when choosing "
            "a team. Two minutes, and it helps us hire better.",
        ),
        (
            "Know someone for {role} at {display}?",
            "Hi Ayush, we are hiring a {role} and referrals are how we find the "
            "best people. Pass this along to anyone who would be a fit.",
        ),
    )

    for i in range(n):
        display, token = b.employer()
        role = b.role(i)
        subject, body = b.pick(shapes)
        b.add(
            family="ats-relay-noise",
            subject=subject.format(display=display, role=role),
            sender=b.ats(i),
            sender_name=f"{display} Talent",
            body=body.format(display=display, role=role),
            expected_category="other",
            identity=None,
            employer=None,
            day=i % 60,
            adversarial=True,
            note="a real ATS relay, and nothing to do with any application of yours",
        )


def _one_thread_many_roles(b: _Builder, n: int) -> None:
    """Four applications, four roles, ONE Gmail thread. Drawn from life.

    Applicant tracking systems send every acknowledgement for an employer under
    one subject line — "Thank you for applying to Verkada" — from one no-reply
    address. Gmail threads on subject plus sender, so it files four unrelated
    applications as one conversation. Measured in the owner's mailbox
    (2026-08-22): thread ``19ff36237eef1ef3`` holds five Verkada messages
    covering four distinct roles, and thread ``19fed820cd93d18e`` holds two
    Anthropic applications. The same shape is already verified in production on
    Amazon, where three Annapurna Labs roles share one thread.

    This is the OTHER direction of the thread mistake, and the reason the rule
    here is "thread is a delivery grouping, never identity" rather than "thread
    is unreliable". A thread's ABSENCE never means two applications; this family
    says a thread's PRESENCE never means one.

    Nothing but the role separates them, and the role is in the body of each.
    ``_req_id_same_title`` is the nearest existing family and does not cover
    this: there the two applications share a title and are separated by a
    requisition number, where here the titles genuinely differ and it is the
    THREAD that is lying about them being one thing.
    """

    for i in range(n):
        display, token = b.employer()
        sender = b.ats(i)
        thread = f"ats-blanket-{token}"
        for k, role in enumerate(b.roles(4)):
            b.add(
                family="one-thread-many-roles",
                subject=f"Thank you for applying to {display}",
                sender=sender,
                sender_name=f"{display} Careers",
                body=(
                    f"Hi Ayush, Thank you so much for applying to the {role} role "
                    f"at {display}! We are always looking for great talent and we "
                    f"are excited to receive your application. We will review it "
                    f"as soon as possible."
                ),
                expected_category="applied",
                identity=f"{token}|{role}",
                employer=token,
                thread=thread,
                day=(i % 40) + k,
                adversarial=True,
                note="one ATS subject line collapses four roles into one Gmail thread",
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


# ── new card, or update to an existing one ───────────────────────────────────
#
# The product's whole job in one sentence: a new application gets a card, and
# everything that follows lands ON that card. Six families, and the last two
# are controls — without them "always join" passes every test above and is the
# merge bug the assert/report rule exists to prevent. A wrong split is visible
# and fixable; a wrong merge destroys the record silently, because
# ``advance_application_status`` treats ``rejected`` as terminal and one
# requisition's rejection settles every application hiding behind it.


#: ``(category, subject, body, stage the card must read once it is filed)``.
#:
#: The fourth element is the half of "an update updates the existing card" that
#: a message-to-card mapping cannot express. A rejection that lands on the
#: right row and leaves it reading ``applied`` has updated nothing a user can
#: see, and every assertion about WHERE it landed passes.
#:
#: ``assessment`` maps to itself: it is both a category and a stage, decided
#: 2026-08-12 on the owner's own mail (see ``CATEGORY_TO_STATUS``).
_UPDATES: tuple[tuple[str, str, str, str], ...] = (
    (
        "rejection",
        "Update on your application to {e}",
        "Hi Ayush, After careful consideration we have decided not to move "
        "forward. We appreciate the time you invested with us.",
        "rejected",
    ),
    (
        "interview",
        "Next steps with {e}",
        "Hi Ayush, We would like to invite you to interview. Please choose a "
        "time from the scheduling link below.",
        "interviewing",
    ),
    (
        "assessment",
        "Your {e} take-home",
        "Hi Ayush, Please complete the take-home exercise linked below within "
        "five days to move to the next stage.",
        "assessment",
    ),
    (
        "offer",
        "An offer from {e}",
        "Hi Ayush, We are delighted to extend you an offer to join us. The "
        "written terms are attached for your review.",
        "offer",
    ),
)


def _confirmation_body(display: str, role: str) -> str:
    return (
        f"Hi Ayush, Thank you for applying to the {role} position at {display}. "
        "Your application has been received and is being reviewed."
    )


def _update_joins_one_application(b: _Builder, n: int) -> None:
    """THE COMMON CASE, and it was not covered until 2026-08-22.

    You apply to a company once. Weeks later: "Update on your application."
    It names no role, because there is only one and the sender knows it. It
    must land on the card that already exists.

    If it opens a second card the user sees a phantom application they never
    made, at an employer they did apply to, which is the hardest kind of wrong
    to disbelieve. Every other family here tests a HARD case; this one tests
    the ordinary one, and the ordinary one is most of a real mailbox.
    """

    for i in range(n):
        display, token = b.employer()
        role = b.role()
        first = b.add(
            family="update-joins-one-application",
            subject=f"Thank you for applying to {display}",
            sender=b.ats(),
            sender_name=f"{display} Recruiting",
            body=_confirmation_body(display, role),
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
            thread=f"one-{token}",
            day=i % 50,
        )
        category, subject, body, stage = b.pick(_UPDATES)
        b.add(
            family="update-joins-one-application",
            subject=subject.format(e=display),
            sender=b.ats(),
            sender_name=f"{display} Recruiting",
            body=body,
            expected_category=category,
            identity=f"{token}|{role}",
            employer=token,
            thread=f"one-{token}",
            day=(i % 50) + 9,
            joins=first.message_id,
            card_status=stage,
            note="names no role because there is only one; must join, not open",
        )


def _update_before_confirmation(b: _Builder, n: int) -> None:
    """The update arrives FIRST, and the board still ends with one card.

    Not exotic. A scan window that starts mid-conversation sees the rejection
    before it ever sees the acknowledgement, and the corpus replays in
    day-sized batches precisely so ordering is a real variable rather than an
    artefact of one big sort. The rebuild path sees everything at once and
    would hide this entirely.
    """

    for i in range(n):
        display, token = b.employer()
        role = b.role()
        category, subject, body, stage = b.pick(_UPDATES)
        first = b.add(
            family="update-before-confirmation",
            subject=subject.format(e=display),
            sender=b.ats(),
            sender_name=f"{display} Talent",
            body=body,
            expected_category=category,
            identity=f"{token}|{role}",
            employer=token,
            thread=f"early-{token}",
            day=i % 50,
            # THE STAGE RIDES ON THE UPDATE, not on the confirmation that
            # follows it, and the placement is the whole point: an expectation
            # attached to a message the product FILED is skipped when that
            # message is held for review instead, and an expectation attached
            # to a different message is not. 77 offers arriving before their
            # confirmation sit in the queue at 0.75 while the card correctly
            # reads `applied`; labelling the confirmation made that read as 77
            # defects.
            #
            # `applied` for the rejection variant, because this family dates
            # the confirmation AFTER the verdict and the product treats a
            # confirmation newer than the newest dated rejection as a new
            # journey segment — one row, reopened, keeping its first filing
            # date (``test_reopen_after_rejection.py``). The other three stages
            # outrank `applied` and are forward-only, so they keep their own.
            card_status="applied" if category == "rejection" else stage,
        )
        b.add(
            family="update-before-confirmation",
            subject=f"Thank you for applying to {display}",
            sender=b.ats(),
            sender_name=f"{display} Recruiting",
            body=_confirmation_body(display, role),
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
            thread=f"early-{token}",
            day=(i % 50) + 6,
            joins=first.message_id,
            note="the acknowledgement arrives after the verdict; still one card",
        )


def _update_from_another_domain(b: _Builder, n: int) -> None:
    """The confirmation comes from the ATS; the update comes from the company.

    This is what a real pipeline looks like — Greenhouse acknowledges, then a
    recruiter writes from their own address. The employer is the same and the
    application is the same, and nothing about the sender may split them.
    """

    for i in range(n):
        display, token = b.employer()
        role = b.role()
        first = b.add(
            family="update-from-another-domain",
            subject=f"Thank you for applying to {display}",
            sender=b.ats(),
            sender_name=f"{display} via Relay",
            body=_confirmation_body(display, role),
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 50,
        )
        category, subject, body, stage = b.pick(_UPDATES)
        b.add(
            family="update-from-another-domain",
            subject=subject.format(e=display),
            sender=f"talent@{token}.example",
            sender_name=f"{display} Talent",
            body=f"{body} Regarding your application for the {role} position.",
            expected_category=category,
            identity=f"{token}|{role}",
            employer=token,
            day=(i % 50) + 11,
            joins=first.message_id,
            card_status=stage,
            note="ATS acknowledges, the company follows up; one application",
        )


def _update_outside_the_thread(b: _Builder, n: int) -> None:
    """The update carries a DIFFERENT conversation, and still belongs.

    The mirror of the Microsoft case. There, one thread held four
    applications and the thread had to stop acting as identity. Here the same
    application is spread over two threads, and the ABSENCE of a shared thread
    must not be read as evidence of a second application either. A thread is a
    delivery grouping: it is not identity, and neither is its absence.
    """

    for i in range(n):
        display, token = b.employer()
        role = b.role()
        first = b.add(
            family="update-outside-the-thread",
            subject=f"Thank you for applying to {display}",
            sender=b.ats(),
            sender_name=f"{display} Recruiting",
            body=_confirmation_body(display, role),
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
            thread=f"ack-{token}",
            day=i % 50,
        )
        category, subject, body, stage = b.pick(_UPDATES)
        b.add(
            family="update-outside-the-thread",
            subject=subject.format(e=display),
            sender=b.ats(),
            sender_name=f"{display} Recruiting",
            body=f"{body} This concerns your {role} application.",
            expected_category=category,
            identity=f"{token}|{role}",
            employer=token,
            # A different conversation entirely, which is what a recruiter
            # composing a fresh message rather than replying produces.
            thread=f"followup-{token}",
            day=(i % 50) + 13,
            joins=first.message_id,
            card_status=stage,
            note="same application, two conversations; one card",
        )


def _reopen_after_rejection(b: _Builder, n: int) -> None:
    """Apply, get rejected, apply again months later. ONE card, reopened.

    I WROTE THIS FAMILY WITH THE WRONG GROUND TRUTH and the corpus reported
    250 merges against a product that was behaving exactly as designed. The
    expectation was two cards, on the reasoning that two applications are two
    applications. The product deliberately gives that up, and says so:
    ``test_reopen_after_rejection.py`` states "what this deliberately gives up
    is a second CARD ... two applications to one requisition are one row whose
    ``applied_date`` keeps the FIRST filing", because ``partition_applications``
    keys clusters with no temporal dimension and a full rebuild would merge
    both applications' mail into one cluster anyway.

    So the ground truth is one card — and the assertion that carries the weight
    is the STATUS. A settled card must REOPEN when a fresh confirmation arrives
    after its rejection. If it does not, the board says the person was rejected
    for a job they are currently being considered for, and
    ``advance_application_status`` will never let it leave ``rejected``.

    That is what makes this a control on the four families above rather than
    another instance of them: "an update joins the existing card" is satisfied
    completely by a product that joins everything, and joining everything is
    the merge the identity rule exists to prevent. Here joining is correct and
    the failure mode moves to the stage. ``update-picks-between-two`` is the
    other half of the control, where minting really is required.
    """

    for i in range(n):
        display, token = b.employer()
        role = b.role()
        first = b.add(
            family="reopen-after-rejection",
            subject=f"Thank you for applying to {display}",
            sender=b.ats(),
            sender_name=f"{display} Recruiting",
            body=_confirmation_body(display, role),
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
            thread=f"round1-{token}",
            day=i % 40,
        )
        b.add(
            family="reopen-after-rejection",
            subject=f"Update on your application to {display}",
            sender=b.ats(),
            sender_name=f"{display} Recruiting",
            body=(
                "Hi Ayush, After careful consideration we have decided not to "
                "move forward with your candidacy at this time."
            ),
            expected_category="rejection",
            identity=f"{token}|{role}",
            employer=token,
            thread=f"round1-{token}",
            day=(i % 40) + 8,
            joins=first.message_id,
        )
        b.add(
            family="reopen-after-rejection",
            subject=f"Thank you for applying to {display}",
            sender=b.ats(),
            sender_name=f"{display} Recruiting",
            body=_confirmation_body(display, role),
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
            # A new conversation, because it is a new application — and the
            # card still has to be the same one.
            thread=f"round2-{token}",
            day=(i % 40) + 130,
            joins=first.message_id,
            card_status="applied",
            note="applied again months later; the settled card must REOPEN",
        )


def _update_picks_between_two(b: _Builder, n: int) -> None:
    """The other control: two live applications, and an update that says which.

    ``ambiguous-update`` covers the update that names NEITHER and must be
    asked about. This covers the one that names ONE, which must land on that
    one and not on its sibling, and not in the queue — asking a question the
    mail already answers is its own failure.
    """

    for i in range(n):
        display, token = b.employer()
        first_role, second_role = b.rng.sample(ROLES, 2)
        b.add(
            family="update-picks-between-two",
            subject=f"Thank you for applying to {display}",
            sender=b.ats(),
            sender_name=f"{display} Careers",
            body=_confirmation_body(display, first_role),
            expected_category="applied",
            identity=f"{token}|{first_role}",
            employer=token,
            day=i % 40,
        )
        target = b.add(
            family="update-picks-between-two",
            subject=f"Thank you for applying to {display}",
            sender=b.ats(),
            sender_name=f"{display} Careers",
            body=_confirmation_body(display, second_role),
            expected_category="applied",
            identity=f"{token}|{second_role}",
            employer=token,
            day=(i % 40) + 2,
        )
        category, subject, body, stage = b.pick(_UPDATES)
        b.add(
            family="update-picks-between-two",
            subject=subject.format(e=display),
            sender=b.ats(),
            sender_name=f"{display} Careers",
            body=f"{body} This concerns your application for the {second_role} position.",
            expected_category=category,
            identity=f"{token}|{second_role}",
            employer=token,
            day=(i % 40) + 15,
            joins=target.message_id,
            card_status=stage,
            note="names one of two; landing on the sibling is a MERGE, "
            "and the queue is a question the mail already answered",
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
# ===========================================================================
# OBSERVED FAMILIES — wordings transcribed from real mail, not invented.
#
# See ``observed.py`` for why these exist. In one line: every other family here
# was written by the author of ``rules.py``, and 100.0% of the invented
# lifecycle messages contain an engine pattern verbatim, so the corpus could
# only ever confirm the pattern list against itself.
#
# These are scored exactly like any other family and are deliberately NOT
# excused. Where they fail, the product fails on mail that actually arrived.
# ===========================================================================


def _observed_confirmations(b: _Builder, n: int) -> None:
    """Real acknowledgement wordings, one application each.

    Twenty-three templates from Greenhouse, Lever, Ashby, iCIMS,
    SmartRecruiters, Rippling and seven in-house systems. Several never use the
    words this product keys on: one says only "your details have been added to
    our database", another "thank you for beginning your application process",
    a third names no role at all.
    """

    for i in range(n):
        display, token = b.employer()
        role = b.role(i)
        subject, body, _ = b.pick(observed.OBSERVED_CONFIRMATIONS)
        fill = {"display": display, "role": role, "req": f"R-{100000 + i}"}
        b.add(
            family="observed-confirmation",
            subject=subject.format(**fill),
            sender=b.ats(i),
            sender_name=f"{display} Recruiting",
            body=body.format(**fill),
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 60,
        )


def _observed_rejections(b: _Builder, n: int) -> None:
    """A real acknowledgement, then a real rejection for the same application.

    HALF ARE DELIVERED AS SNIPPETS, because that is what production receives
    when no body part can be extracted, and because it is the difference that
    matters: measured 2026-08-22, these six wordings score 6/6 correct on the
    full body and 2/6 on the snippet. Not one of them leads with its verdict.
    """

    for i in range(n):
        display, token = b.employer()
        role = b.role(i)
        csubj, cbody, _ = b.pick(observed.OBSERVED_CONFIRMATIONS)
        rsubj, rbody, _ = b.pick(observed.OBSERVED_REJECTIONS)
        fill = {"display": display, "role": role, "req": f"R-{200000 + i}"}
        b.add(
            family="observed-rejection",
            subject=csubj.format(**fill),
            sender=b.ats(i),
            sender_name=f"{display} Recruiting",
            body=cbody.format(**fill),
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 50,
        )
        body = rbody.format(**fill)
        truncated = i % 2 == 0
        b.add(
            family="observed-rejection",
            subject=rsubj.format(**fill),
            sender=b.ats(i),
            sender_name=f"{display} Recruiting",
            body=body,
            delivered=snippet_of(body) if truncated else None,
            expected_category="rejection",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 50 + 24,
            adversarial=truncated,
            note=(
                "a real rejection, delivered as Gmail's snippet"
                if truncated
                else "a real rejection, whole body"
            ),
        )


def _observed_assessments(b: _Builder, n: int) -> None:
    """An assessment invitation and the reminders that chase it.

    Three real wordings for one stage. The third never says "assessment
    invitation" — it says the team noticed you have not had a chance to
    complete yours — and it is an UPDATE to an application that already exists,
    so it must reach that card rather than open one.
    """

    for i in range(n):
        display, token = b.employer()
        role = b.role(i)
        csubj, cbody, _ = b.pick(observed.OBSERVED_CONFIRMATIONS)
        fill = {"display": display, "role": role, "req": f"R-{300000 + i}"}
        b.add(
            family="observed-assessment",
            subject=csubj.format(**fill),
            sender=b.ats(i),
            sender_name=f"{display} Recruiting",
            body=cbody.format(**fill),
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 50,
        )
        asubj, abody, _ = b.pick(observed.OBSERVED_ASSESSMENTS)
        b.add(
            family="observed-assessment",
            subject=asubj.format(**fill),
            sender=b.ats(i),
            sender_name=f"{display} Recruiting",
            body=abody.format(**fill),
            expected_category="assessment",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 50 + 9,
            note="an update to an application that already exists",
        )


def _observed_closures(b: _Builder, n: int) -> None:
    """The application is OVER, and nothing in the mail says so in the usual way.

    "The assessments for your application have expired and as a result, your
    application is no longer active." No regret, no decline, no not-moving-
    forward — and the card must not go on reading `applied` forever. Scored as
    a rejection because that is what it is from the user's side: this
    application is finished and no further mail about it will arrive.

    The sharpest wording in ``observed.py`` and the one the classifier has
    least chance with, which is exactly why it is here.
    """

    for i in range(n):
        display, token = b.employer()
        role = b.role(i)
        csubj, cbody, _ = b.pick(observed.OBSERVED_CONFIRMATIONS)
        fill = {"display": display, "role": role, "req": f"R-{400000 + i}"}
        b.add(
            family="observed-closure",
            subject=csubj.format(**fill),
            sender=b.ats(i),
            sender_name=f"{display} Recruiting",
            body=cbody.format(**fill),
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 50,
        )
        xsubj, xbody, _ = b.pick(observed.OBSERVED_CLOSURES)
        b.add(
            family="observed-closure",
            subject=xsubj.format(**fill),
            sender=b.ats(i),
            sender_name=f"{display} Recruiting",
            body=xbody.format(**fill),
            expected_category="rejection",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 50 + 30,
            adversarial=True,
            note="the application is closed and the mail never says a rejection word",
        )


def _observed_pending(b: _Builder, n: int) -> None:
    """Action-required mail on an application that is not finished.

    Both real. One asks the candidate to verify their email before the
    application counts; the other is a SECOND notification about an application
    already acknowledged, which must update that card rather than open a rival.
    """

    for i in range(n):
        display, token = b.employer()
        role = b.role(i)
        csubj, cbody, _ = b.pick(observed.OBSERVED_CONFIRMATIONS)
        fill = {"display": display, "role": role, "req": f"R-{500000 + i}"}
        b.add(
            family="observed-pending",
            subject=csubj.format(**fill),
            sender=b.ats(i),
            sender_name=f"{display} Recruiting",
            body=cbody.format(**fill),
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 50,
        )
        psubj, pbody, _ = b.pick(observed.OBSERVED_PENDING)
        b.add(
            family="observed-pending",
            subject=psubj.format(**fill),
            sender=b.ats(i),
            sender_name=f"{display} Recruiting",
            body=pbody.format(**fill),
            expected_category="pending_application",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 50 + 2,
            adversarial=True,
            note="action required on an application that already has a card",
        )


def _observed_not_applications(b: _Builder, n: int) -> None:
    """Real job-adjacent mail that must mint nothing.

    A careers-portal verification code. It says "Career" three times and is not
    a career event, which is the same confusion #455 turns on from the other
    direction.
    """

    for i in range(n):
        display, _token = b.employer()
        subject, body, _ = b.pick(observed.OBSERVED_NOT_APPLICATIONS)
        fill = {"display": display, "role": b.role(i), "req": f"R-{600000 + i}"}
        b.add(
            family="observed-not-application",
            subject=subject.format(**fill),
            sender=b.ats(i),
            sender_name=f"{display} Accounts",
            body=body.format(**fill),
            expected_category="other",
            identity=None,
            employer=None,
            day=i % 60,
            adversarial=True,
            note="real job-adjacent mail that is not about an application",
        )


_FAMILIES: tuple[tuple[str, object, int], ...] = (
    ("confirmation", _confirmations, 1100),
    ("rejection-plain", _rejections_plain, 550),
    ("rejection-past-the-snippet", _rejections_past_the_snippet, 350),
    ("one-thread-many-roles", _one_thread_many_roles, 60),
    ("ats-relay-noise", _ats_relay_noise, 400),
    # OBSERVED — real wordings, transcribed. See ``observed.py``.
    ("observed-confirmation", _observed_confirmations, 300),
    ("observed-rejection", _observed_rejections, 220),
    ("observed-assessment", _observed_assessments, 150),
    ("observed-closure", _observed_closures, 120),
    ("observed-pending", _observed_pending, 120),
    ("observed-not-application", _observed_not_applications, 80),
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
    # New card, or update to an existing one. The last two are the controls;
    # see the block comment above ``_update_joins_one_application``.
    ("update-joins-one-application", _update_joins_one_application, 600),
    ("update-before-confirmation", _update_before_confirmation, 300),
    ("update-from-another-domain", _update_from_another_domain, 300),
    ("update-outside-the-thread", _update_outside_the_thread, 300),
    ("reopen-after-rejection", _reopen_after_rejection, 250),
    ("update-picks-between-two", _update_picks_between_two, 250),
    # APPENDED LAST, deliberately. The builder shares one seeded RNG across
    # families, so inserting a family anywhere else re-draws every employer,
    # role and wording after it and the whole recorded run moves at once. At
    # the end, the delta is this family and nothing else.
    ("one-thread-many-roles-in-the-queue", _one_thread_many_roles_in_the_queue, 60),
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
