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
``body`` (what the mail says) and ``delivered`` (what the classifier is handed,
through ``harness.as_classified``, which applies production's window to it), and
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
import re
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
    "Software Development Engineer I - AI/ML Network Infrastructure, Kestrelan Labs",
    "Software Engineer I, Entry-Level (Graduation Date: Fall 2025-Summer 2026)",
    "Software Development Engineer I, ML Infra Services, Kestrelan Labs",
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


#: "the mail names no role" — this file's own sentinel spelling, currently
#: ``__apply0..2__`` (``repeat-anonymous``, ``update-in-thread``) and
#: ``__submission__`` (``double-acknowledgement``). Matched by SHAPE rather
#: than by listing them, so a family that invents a fourth sentinel is covered
#: the day it lands instead of quietly scoring 120 correct cards as defects.
#: No job title can be spelled this way. See ``Case.role_truth``.
_ROLE_SENTINEL = re.compile(r"^__[a-z0-9]+__$")

#: Every status a board can actually show. Ground truth that names anything
#: else is a typo, and a typo here is invisible rather than loud: `_overstates`
#: resolves an unknown status through ``_STATUS_RANK.get(want, 0)``, which ranks
#: it BELOW every live card, so every card silently becomes "ahead" of it. The
#: `_UPDATES` offer entry said ``offer`` where boards store ``offered`` from the
#: day it was written; 425 assertions could only ever be false and none had ever
#: been evaluated.
#:
#: THE DIRECTION MATTERS AND IS EASY TO STATE BACKWARDS. The typo produces
#: ``card_overstates = 551``; the correct spelling produces 260. So the typo
#: INVENTS 291 defects across four unrelated families that have nothing wrong
#: with them, and fixing the word removes them. It does not surface real ones.
#:
#: Written out here rather than imported from the product ON PURPOSE. This file
#: must not derive its ground truth from the code it grades — that is the
#: circularity the whole independent corpus exists to avoid. The cost is that
#: the two can drift, so `test_the_corpus_and_the_product_agree_on_what_a_status_is`
#: asserts this set equals `_STATUS_RANK | _TERMINAL_STATUSES` and fails if
#: either side gains a status the other has not heard of.
_CARD_STATUSES = frozenset(
    {
        "applied",
        "assessment",
        "interviewing",
        "offered",
        "accepted",
        "rejected",
        "withdrawn",
        "ghosted",
    }
)

#: A bare requisition id used as the identity sub-key — ``req-id-same-title``.
#: No job title can match it.
_REQ_SUB_KEY = re.compile(r"^(?:R-)?\d{4,}$")

#: Everything of a message the product can ever read a job title out of, in
#: characters of BODY. Gmail bodies are whitespace-collapsed and cut at 4,000
#: before anything downstream sees them (``gmail_client._MAX_BODY_CHARS``), and
#: the harness hands ``role_from_message`` exactly that text.
#:
#: Written out rather than imported, for the same reason ``_CARD_STATUSES`` is:
#: this file must not take its ground truth from the code it grades. The cost
#: is drift, so `test_the_readable_window_is_the_product_s_window` pins the two
#: together and fails if either moves.
#:
#: NOT the snippet. #533 prescribed testing reachability against ``delivered``,
#: which is what the CLASSIFIER sees; the extractor that titles the card is
#: handed the capped BODY, and matching the wrong one would quietly sweep #484's
#: cases — a role printed past the snippet — into "the mail names no role",
#: where a later fix that reached them would turn the gate RED for repairing the
#: defect. Worth 0 cases today and worth being right about.
_READABLE_CHARS = 4000


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
    #: What the server holds for this message — the body, or the snippet when no
    #: body can be extracted. NOT what reaches ``classify()``: production applies
    #: ``normalise_body_text`` (whitespace, then a 4,000-character cap) to a body
    #: and never to a snippet, and ``harness.as_classified`` is where that
    #: happens. This said "what reaches ``classify()``" until #767, and the
    #: harness passed it through raw, so the claim and the code agreed with each
    #: other and neither agreed with the product. See the module docstring.
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
    #: The ROLE the card must be titled with, or None when this corpus cannot
    #: settle it. Derived, never passed — see ``must_be_addressed`` above for
    #: why a field the builder fills is a field some builder forgets.
    #:
    #: ``identity`` is ``employer|sub_key`` and the sub-key is the product's own
    #: cascade, ``req_id or role_token``, so it is a role only SOMETIMES. Two
    #: shapes are not roles and grading a card against them would report a
    #: defect where the card is right:
    #:
    #:   * ``__…__`` — this generator's sentinel for "the mail names no role at
    #:     all", which is what ``repeat-anonymous``, ``update-in-thread`` and
    #:     ``double-acknowledgement`` are about. A BLANK card is the correct
    #:     answer there, and #487 names this as the first way the counter goes
    #:     wrong.
    #:   * a bare requisition id — ``req-id-same-title`` keys on ``R-40080``,
    #:     and the card it must produce reads "Infrastructure Engineer
    #:     (R-40080)". Right card, right title, and nothing here knows the
    #:     title, only the key.
    #:
    #: Both patterns describe what THIS FILE writes, not a guess about the
    #: product; a real role can never match either.
    role_truth: str | None = None

    #: The mail deliberately names NO role, so the only correct card is a blank
    #: one. Derived from the sentinel sub-key, and the reason it exists as a
    #: separate flag rather than as "role_truth is None": the two look identical
    #: to a scorer and mean opposite things. `role_truth is None` on a req-id
    #: family means "this corpus cannot settle the title"; here it means "any
    #: title at all is an invention". The first must be skipped, the second must
    #: be asserted, and skipping both left 960 cards where the product could
    #: print anything and no counter moved.
    #: DERIVED, never passed. A field a builder fills is a field that is wrong
    #: for every Case built any other way — the hazard `must_be_addressed`
    #: already documents. Passing it is refused below rather than trusted.
    names_no_role: bool = False

    #: WHICH MAILBOX this message arrives in. ``0`` is the corpus's owner and is
    #: every case's answer except ``another-mailbox-cannot-settle-mine``'s.
    #:
    #: The generator built ONE user until #614, and a one-user corpus cannot
    #: fail a ``user_id``-scoped predicate: every such clause is satisfied by
    #: construction, so removing one moves no number and the scoping is
    #: asserted by nothing. That is the check-that-cannot-fail shape one
    #: dimension over from the dismissal hole in the same issue.
    #:
    #: A slot rather than a UUID because this file must not import the
    #: harness's users — it states WHICH mailbox, and the harness owns what a
    #: mailbox is. Cases in slot 1 are FIXTURE: they exist to give the owner's
    #: board something it must not be confused by, and they are scored on
    #: their own board rather than folded into the owner's.
    user_slot: int = 0

    #: WHAT THE USER DOES once this message's day-batch has been synced.
    #:
    #: The corpus had no vocabulary for a user ACTION until #614, and that is
    #: the reason it could not grade dismissal: `dismissed_at` is written by
    #: `dismiss_application` and by a re-sync, and a replay that only ever
    #: delivers mail reaches neither. So no generated application was ever
    #: dismissed, `_filed_on_a_live_application` was equivalent by construction
    #: to the `application_id IS NOT NULL` it replaced, and the control #614
    #: names produced two identical runs.
    #:
    #: A message is where an instruction hangs because the instruction has to
    #: happen at a TIME — between two syncs — and a message is the only thing
    #: here that carries one. The harness executes it through the product's own
    #: function (`dismiss_application`, `classify_review_item`); this field
    #: names the act, never the state it leaves. Writing `dismissed_reason`
    #: into a row by hand would be the harness approximating a production input
    #: instead of calling one, which is a shape this corpus has already paid
    #: for three times.
    #:
    #:   ``"dismiss"``      — the user says "not an application" about the card
    #:                        THIS message opened, after its batch.
    #:   ``"answer_other"`` — the user answers THIS message in the review queue
    #:                        with a category that files nothing, leaving
    #:                        ``is_reviewed`` set and ``application_id`` NULL.
    standing_instruction: str | None = None

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
        if self.names_no_role:
            raise ValueError(
                "names_no_role is derived — from the identity sub-key here, "
                "and from the corpus text in `_settle_role_reachability` — "
                "never passed. Set by hand it can contradict the identity it "
                "is supposed to describe: `northwind|R-40080` with "
                "names_no_role=True asserts a blank card for mail that names a "
                "real job."
            )
        if self.card_status is not None and self.card_status not in _CARD_STATUSES:
            raise ValueError(
                f"card_status={self.card_status!r} is not a status any board "
                f"shows. Ground truth nothing validates is worse than no ground "
                f"truth: `_overstates` reads an unknown status through "
                f"`_STATUS_RANK.get(want, 0)`, so a typo silently ranks BELOW "
                f"every live card and every card becomes 'ahead' of it. This "
                f"entry said `offer` instead of `offered` from the day it was "
                f"written and no assertion could see it. The typo INVENTS "
                f"defects rather than hiding them: it takes card_overstates to "
                f"551 where the correct spelling gives 260, across four "
                f"families with nothing wrong. Correcting the one value was not "
                f"enough, so the wrong value is now impossible. "
                f"Known: {sorted(_CARD_STATUSES)}"
            )
        if self.role_truth is not None:
            # DERIVED, LIKE ``names_no_role`` BESIDE IT (#544). An authored
            # value skips the branch below entirely, so a family that wrote one
            # would put a role on a card whose sub-key says something else —
            # and `_settle_role_reachability` groups on exactly this field, so
            # an identity with an authored value on SOME of its cases would be
            # graded on a partial membership and renamed on a partial one too.
            # One application, two keys, a ground-truth SPLIT nobody wrote.
            #
            # A DISAGREEING VALUE, NOT ANY VALUE, AND THE FIRST DRAFT REFUSED
            # ANY. It was justified with "zero occurrences of `role_truth=`
            # anywhere under `backend/tests/`" — a grep for a literal, which is
            # the wrong instrument for this question. `dataclasses.replace`
            # passes EVERY field back through `__init__`, writing no such
            # literal anywhere, and #967's blinding control does exactly that
            # to one generated case. The refusal shipped green on its own
            # branch and went red the moment the two landed together.
            #
            # So the rule is the one the docstring always meant: the field and
            # the sub-key may not be two DIFFERENT answers to one question. A
            # value that agrees with the key is the key, restated.
            derived = (
                self.identity.partition("|")[2]
                if self.identity is not None
                else None
            )
            if derived is None or _ROLE_SENTINEL.match(derived) or (
                self.role_truth != derived
            ):
                raise ValueError(
                    "role_truth is derived from the identity sub-key, never "
                    f"authored. {self.role_truth!r} was handed in against a "
                    f"sub-key of {derived!r}, which would make the field and "
                    "the key two answers to one question."
                )
        if self.identity is not None and self.role_truth is None:
            sub_key = self.identity.partition("|")[2]
            if not sub_key:
                # AN EMPTY SUB-KEY IS THE 960-CARD HOLE ONE SPELLING OVER.
                # It matches no sentinel and fails the `elif`, so neither
                # `role_truth` nor `names_no_role` is set and the card leaves
                # BOTH grading and `blank_required` with nothing moving — the
                # exact shape this file was changed to close. Unreachable today
                # (0 of 15,730 identities), and refused rather than left to
                # become reachable quietly.
                raise ValueError(
                    f"identity={self.identity!r} has an empty sub-key. An "
                    f"identity is `employer|role`, `employer|<req id>` or "
                    f"`employer|__sentinel__`; an empty one is gradeable by "
                    f"nothing and would be silently skipped."
                )
            if _ROLE_SENTINEL.match(sub_key):
                # THE MAIL NAMES NO ROLE, and that is a CLAIM, not an absence.
                # A sentinel sub-key means this family's mail deliberately
                # withholds the job title, so the only correct card is a blank
                # one. Recorded here so the scorer can assert it instead of
                # skipping the card — see BoardScore.role_invented.
                object.__setattr__(self, "names_no_role", True)
            elif sub_key and not _REQ_SUB_KEY.match(sub_key):
                object.__setattr__(self, "role_truth", sub_key)


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
        user_slot: int = 0,
        standing_instruction: str | None = None,
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
            user_slot=user_slot,
            standing_instruction=standing_instruction,
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

    THE FAMILY ASSERTED NOTHING ABOUT THE BOARD until 2026-08-26, and that is
    how the defect above went on reading green. Both messages carried
    ``card_status=None`` and ``joins=None``, so the score watched the CLASSIFIER
    and never the card — the exact shape of #487, one field over. Replayed
    through the real sync, the family produces 260 cards reading ``offered``
    with all 260 withdrawals parked in the review queue, and the board score
    said WRONG STAGE 0.

    The withdrawal now names the card it joins and the stage that card must
    read. What that turns red is not WRONG-STAGE — a held message has not been
    filed and cannot have moved anything — but the counter that exists for this
    shape: the card is left ASSERTING A BETTER OUTCOME than the user has while
    the mail that corrects it waits behind a question. A card that is BEHIND is
    honest and incomplete; a card that is AHEAD is wrong.
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
        offer_id = f"c{b._n:05d}"
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
            joins=offer_id,
            # `rejected`, not `withdrawn`: on this board `withdrawn` is the
            # user pulling out, and nothing here says they did. The employer
            # ended it, so from the row's side it ended the way a rejection
            # does — which is also what `expected_category` above already says.
            card_status="rejected",
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
                # "would LIKE to", not "would love to". Measured across the 110
                # externally-provenanced interview cases in tests/corpus/mail.py
                # (VERIFIED = published ATS template text, COLLECTED, MEASURED):
                # `like to` appears 63 times, `love to` ZERO. The engine's
                # INTERVIEW.strong volition slot wants the attested verb, and a
                # fixture written in language no real invitation uses graded the
                # wording rather than the defect -- 200 of 400 "wrong" at every
                # seed, with the quote-strip this family exists to test never
                # reached. See #878.
                "Hi Ayush, Following up on the below — we would like to set up a "
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


def _anonymous_third_application(b: _Builder, n: int) -> None:
    """A third application where the first two named their jobs and this one does not.

    #641, and the shape this corpus was STRUCTURALLY unable to hold. Measured
    BEFORE this family existed, at 8,440 employers carrying an identity (8,500
    with it), ZERO held both a NAMED and an ANONYMOUS one — every family that produces an
    anonymous identity produces nothing else at that employer, and the employer
    pool is disjoint. So the defect could be reinstated and not one board count
    would move. A corpus that cannot see a defect is worse than one that reports
    it, because the green reads as evidence.

    Two identified confirmations, days apart, so the board really does hold two
    LIVE cards. Then an acknowledgement naming no role at all. Ground truth is
    THREE identities at one employer, so a third confirmation that folds onto
    either of the first two puts two applications on one card and scores as a
    MERGE — the failure ``test_the_board_is_clean`` calls strictly worse than a
    split, because it discards a record silently instead of showing it twice.

    THE DAYS ARE LOAD-BEARING AND ARE NOT DECORATION. ``replay`` batches by
    calendar day, and at a ``known_multi`` employer a confirmation arriving in
    the SAME batch as exactly one identified message joins that message's
    cluster in-scan — ``partition_applications``' ``len(keyed) != 1`` guard —
    and never reaches the resolver at all. That is deliberate: it is the
    single-card case's in-batch twin. So the three messages sit in three
    different day batches with the anonymous one last, when the board holds two
    cards and ``employers_with_several_applications`` names the employer.
    Putting them in one batch would measure the guard and report it as this
    family passing.

    ONE SENDER FOR ALL THREE, and that is a correctness requirement rather than
    a tidiness one. ``resolve_employer`` reads an ATS relay's display name and a
    direct domain's brand, and the two need not agree; mixing them would give
    the anonymous message a different employer token, so ``_company_rows`` would
    find no siblings and the mint would happen for the wrong reason. The family
    would then pass with the defect present.

    NEITHER IDENTIFIED WORDING MAY BE ANONYMOUS and the third may not name a
    role, or this measures the role reader instead of the composition. Both are
    asserted against the product's own extraction in
    ``test_independent_corpus.py`` rather than trusted to the prose here.
    """

    for i in range(n):
        display, token = b.employer()
        sender = b.ats(i)
        first, second = b.roles(2)
        base = i % 200
        for k, role in enumerate((first, second)):
            b.add(
                family="anonymous-third-application",
                subject=f"Thank you for applying to {display}",
                sender=sender,
                sender_name=f"{display} Recruiting",
                body=(
                    f"Hi Ayush, Thank you for applying to the {role} position at "
                    f"{display}. Your application has been received and our team "
                    "will review it shortly."
                ),
                expected_category="applied",
                identity=f"{token}|{role}",
                employer=token,
                day=base + k * 4,
                note="the board must hold TWO named cards before the third arrives",
            )
        b.add(
            family="anonymous-third-application",
            subject=f"Thanks for applying to {display}",
            sender=sender,
            sender_name=f"{display} Recruiting",
            body=(
                f"Hi Ayush, Thanks for applying to {display}! There are a ton of "
                "great companies out there, so we appreciate your interest in "
                "joining our team. While we are not able to reach out to every "
                "applicant, our recruiting team will contact you if your skills "
                "and experience are a strong match for the role."
            ),
            expected_category="applied",
            identity=f"{token}|__third__",
            employer=token,
            day=base + 12,
            note="a third application the mail names nothing about (#641)",
        )


def _double_acknowledgement(b: _Builder, n: int) -> None:
    """One submission, acknowledged twice, by two systems that word it differently.

    The shape ``repeat-anonymous`` is NOT. Both families are two-or-more
    anonymous confirmations from one employer — no role, no requisition, nothing
    in the mail that tells them apart — and they must come out at different card
    counts, so each is the other's control:

      repeat-anonymous        same template, days apart  -> one card each
      double-acknowledgement  two templates, hours apart -> ONE card for both

    Drawn from the owner's mailbox 2026-08-23. Supabase's ATS sent the generic
    "we confirm your application has been received" at 23:03 and the company's
    own "thanks for applying, we're glad you're interested" at 21:02, both for
    one submission. Every anonymous confirmation minted its own card, so the
    board showed two applications where he had made one — and because
    ``known_multi`` then treats that employer as holding several, every later
    role-less message from them goes to the review queue to be assigned to one
    of two rows that are the same row.

    NEITHER WORDING MAY NAME A ROLE, or the family measures role matching
    instead of the thing under test. Both templates below are deliberately about
    the application and never about the job.
    """

    for i in range(n):
        display, token = b.employer()
        sender = b.ats(i)
        first = b.add(
            family="double-acknowledgement",
            subject=f"Thanks for applying to {display}",
            sender=sender,
            sender_name=f"{display} Talent Team",
            body=(
                f"Hi Ayush, Thanks for applying to {display}. We are really glad you "
                "are interested in what we are building. We review every application "
                "carefully and someone from our team will reach out if there is a fit."
            ),
            expected_category="applied",
            identity=f"{token}|__submission__",
            employer=token,
            thread=f"ack-a-{token}",
            day=i % 40,
            adversarial=True,
            note="the company's own acknowledgement",
        )
        b.add(
            family="double-acknowledgement",
            subject=f"Thank you for applying to {display}!",
            sender=sender,
            sender_name=f"{display} Hiring",
            body=(
                f"Hey Ayush, Thanks for your interest in a role with {display}; we "
                "confirm your application has been received. What happens next? We "
                "respond to all candidates and will be in touch."
            ),
            expected_category="applied",
            identity=f"{token}|__submission__",
            employer=token,
            # ITS OWN THREAD, because that is how it arrives: two templates from
            # two emitters do not share a subject, and Gmail threads on subject
            # plus sender. A shared thread here would let the thread do the
            # joining and the family would measure nothing.
            thread=f"ack-b-{token}",
            # SAME DAY, two hours later. The harness replays day-sized batches,
            # so a second day would put the two acknowledgements in different
            # syncs and the merge under test could not arise at all.
            day=i % 40,
            joins=first.message_id,
            adversarial=True,
            note="the ATS's acknowledgement of the SAME submission, hours later",
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


#: The longest title in :data:`ROLES`, and the one this family is built on.
#: Selected by MEASUREMENT rather than by name so that editing ``ROLES`` cannot
#: quietly leave the family pointing at a title too short to reach the bound.
_LONGEST_ROLE: str = max(ROLES, key=len)

#: A requisition id printed the way Amazon prints one — bare ``ID:``, no "job"
#: in front of it, between the title and the word that terminates it.
_REQ_SUFFIX_TEMPLATE = " (ID: {req})"


#: THE CAPTURE CEILING IS 91, NOT THE 90 THE PATTERN APPEARS TO SAY. The role
#: group reads ``[A-Z](?:(?!'s\s)[^.!?\n]){3,90}?`` — one leading capital PLUS
#: three-to-ninety more characters, so a 91-character title fits and a
#: 92-character one does not.
#:
#: Getting this off by one is not academic; it is what made the first draft of
#: this family measure nothing. The invented sub-brand in ``ROLES`` was two
#: characters shorter than the real one it mirrors, which put the longest title
#: at 76 rather than the 78 the comment there states. 76 + " (ID: nnnnnnnn)" is
#: exactly 91 — it FITS, the capture succeeds whole, and reverting the fix left
#: the corpus completely green. The real Amazon title is 78, the real span is
#: 93, and the sub-brand is now 14 characters like the original.
_ROLE_CAPTURE_CEILING = 91


def _role_id_span_crosses_the_bound(role: str, req: str) -> bool:
    """Does title-plus-id exceed the capture ceiling while the title alone does not?

    This family only measures anything when the answer is yes, so the answer is
    computed rather than assumed. A fixture that sits on the harmless side of a
    bound is this estate's recurring defect — a corpus family whose messages
    never meet in one batch, a fixture past the largest N any test asks for —
    and it looks exactly like a passing test.
    """

    bare = len(role)
    with_id = bare + len(_REQ_SUFFIX_TEMPLATE.format(req=req))
    return bare <= _ROLE_CAPTURE_CEILING < with_id


def _requisition_inside_the_bound(b: _Builder, n: int) -> None:
    """The requisition id rides inside the title's width bound, and evicts a word.

    Amazon writes the confirmation as

        "...We've received your application for the <TITLE> (ID: 10475660)
         position."

    and the later verdict as

        "...regarding your application for the <TITLE> position..."

    with no id, because by then the conversation is about a decision rather than
    a submission. The role capture is bounded at 90 characters and that bound is
    spent while the id is STILL INSIDE the span, even though ``_clean_role``
    deletes the id immediately afterwards. On a 76-character title the span is
    91, the bound cannot be met, and the engine backtracks the preceding gap and
    restarts the capture one word later — so the confirmation is filed under
    "Development Engineer I ..." and the verdict arrives naming "Software
    Development Engineer I ...". Two role tokens, two identities, two cards for
    one application. Measured on the owner's live board 2026-08-23, applications
    112 and 126.

    WHY NO EXISTING FAMILY CATCHES IT. ``req-id-same-title`` already pairs a
    title with a parenthesised requisition, but prints it as ``(R-40001)`` — no
    ``ID:`` label — which ``_clean_role`` does not strip and which therefore is
    part of the title on both sides of the conversation, so the two sides still
    agree. ``ROLES`` grew its long tail on 2026-08-22 for exactly this bound,
    but no family combined a long title WITH a labelled id, and the whole corpus
    stayed green through the defect.

    THE ID IS ON THE CONFIRMATION ONLY, and that asymmetry is the point. Put it
    on both messages and both sides truncate identically, they agree again, and
    the family measures nothing.

    THE VERDICT ARRIVES ON ITS OWN THREAD, and that is the second thing this
    family had to be told. The first draft threaded the two messages together
    and measured NOTHING: reverting the fix left splits at 0 and the board at
    the same card count, because a shared Gmail thread joins the two messages
    whatever the role tokens say, and the truncation stays invisible behind it.
    A separate thread is also the real shape — ``update-outside-the-thread``
    exists for the same reason, and Amazon's own verdicts do not thread with
    their acknowledgements — and it leaves the ROLE TOKEN as the only thing that
    can join them. Which is precisely the thing the bound corrupts.
    """

    for i in range(n):
        display, token = b.employer()
        role = _LONGEST_ROLE
        req = f"{10400000 + i}"
        if not _role_id_span_crosses_the_bound(role, req):  # pragma: no cover
            raise AssertionError(
                f"corpus family 'requisition-inside-the-bound' cannot fire: "
                f"role is {len(role)} chars and the id suffix brings it to "
                f"{len(role) + len(_REQ_SUFFIX_TEMPLATE.format(req=req))}, "
                f"which does not straddle the {_ROLE_CAPTURE_CEILING}-character "
                "capture ceiling"
            )
        thread = f"req-bound-{token}"
        first = b.add(
            family="requisition-inside-the-bound",
            subject=f"Thank you for applying to {display}",
            sender=b.ats(i),
            sender_name=f"{display} Careers",
            body=(
                f"Hi Ayush, Thanks for applying to {display}! We've received your "
                f"application for the {role}"
                + _REQ_SUFFIX_TEMPLATE.format(req=req)
                + " position. What happens next? If we decide to move forward we "
                "will be in touch."
            ),
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
            thread=thread,
            day=i % 40,
            adversarial=True,
            note="the id sits between the title and 'position', inside the bound",
        )
        b.add(
            family="requisition-inside-the-bound",
            subject=f"Update on your application to {display}",
            sender=b.ats(i),
            sender_name=f"{display} Careers",
            body=(
                f"Hi Ayush, We are writing regarding your application for the {role} "
                "position. After careful consideration we have decided to move "
                "forward with other candidates."
            ),
            expected_category="rejection",
            identity=f"{token}|{role}",
            employer=token,
            thread=f"{thread}-verdict",
            day=(i % 40) + 6,
            joins=first.message_id,
            card_status="rejected",
            adversarial=True,
            note="same title, no id, own thread — the role token must join them",
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
        # `offered`, the STATUS, not `offer`, the mail CATEGORY. The two scales
        # differ by exactly this word (`pipeline._STATUS_RANK` against
        # `_STAGE_RANK`) and this entry said `offer` from the day it was
        # written. It could not match any stage a board ever shows, so all 425
        # cases carrying it were assertions that could only ever be false —
        # and not one of them was ever evaluated, because every one is held
        # under the auto-file gate and WRONG-STAGE skips held mail. A wrong
        # ground-truth value nothing reaches is invisible until something
        # reaches it, which is what the overstatement counter now does.
        "offered",
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
            sender=f"talent@{token.split()[0]}.example",
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


# ── #626: THE TRAILING SEGMENT NAMES THE ROLE ────────────────────────────────
#
# See ``_concatenated_post_names`` for the provenance of every string below.
# In one line: real job titles and real locations off two PUBLIC Greenhouse
# boards, in a subject shape no vendor documents, wrapped around invented
# employers.

#: Titles the shipped reader RESOLVES in this shape, and each is here for a
#: property the other two do not have:
#:
#:   * seven words and two commas — the reported #626 title's own shape, which
#:     ``_ROLE_PATTERNS`` cannot reach (``^``-anchored, comma-free capture
#:     class, five-word cap);
#:   * a slash inside the head noun, which ``_TITLE_SHAPED`` has to allow;
#:   * AN INTERIOR SPACED DASH, which must SURVIVE. This is the case #553 is
#:     about: the segment is cut at the LAST spaced dash, so "- London" stays
#:     inside the title and only "- <Employer>" is taken off. A reader that cut
#:     at the first dash would hand back "Research Engineer / Scientist,
#:     Alignment" and mint a rival card for a job the board already tracks.
_POST_NAME_RESOLVES: tuple[str, ...] = (
    "Director, Engineering, Platform Operations & Productivity",
    "ML/Research Engineer, Safeguards",
    "Research Engineer / Scientist, Alignment - London",
)

#: Titles the shipped reader REFUSES in this shape, and refusing is correct:
#: it fails closed, so the message reaches a person instead of a wrong card.
#: They are pinned so that a later change cannot quietly start resolving them
#: WRONG — which is what refusing protects against, not merely what it costs.
#:
#:   * "Commercial Account Executive, Named - West" carries a comma AND a
#:     spaced hyphen, so the last-dash cut would take "West" for the employer
#:     echo; the echo licence refuses because "West" is not the lead segment's
#:     company.
#:   * three carry a TRAILING PARENTHETICAL, which rule 1 refuses structurally
#:     rather than by vocabulary — the whole argument of the reader's
#:     "both placements or neither".
#:   * "Deal Desk Strategist, Philippines or India" has a bare space-joined
#:     continuation past the head noun.
_POST_NAME_QUEUES: tuple[str, ...] = (
    "Commercial Account Executive, Named - West",
    "Customer Success Engineer, LATAM (Spanish, Portugese)",
    "Account Executive - Public Sector (ASEAN)",
    "Backend Engineer (Ruby), AI Engineering: Agent Observability",
    "Deal Desk Strategist, Philippines or India",
)

#: Locations that behave like locations: whatever they say, the reader strips
#: the parenthetical and reads the title in front of it.
_POST_NAME_LOCATIONS: tuple[str, ...] = (
    "Remote, US",
    "Remote Ireland",
    "Bangalore, India",
)

#: A PIPE IS NOT RELIABLY A SEGMENT BOUNDARY, and these two are the proof. Both
#: are single ``location`` values on a public board — one posting, one field —
#: and both contain pipes. Appended to a subject that is already pipe-segmented,
#: the LAST pipe-segment stops being the post name and becomes a fragment of a
#: city list: "Seattle, WA".
#:
#: The reader returns None for them today, and the refusal is not incidental: a
#: city fragment carries no spaced dash and no employer echo, so the licence has
#: nothing to license. THE ASSERTION IS THAT THEY STAY REFUSED. If a later
#: change makes one of them resolve, it is reading a city as a job title, and
#: the card it titles is a lie of exactly the kind #553 describes.
_POST_NAME_PIPED_LOCATIONS: tuple[str, ...] = (
    "Remote-Friendly (Travel-Required) | San Francisco, CA | Seattle, WA",
    "New York City, NY; San Francisco, CA | New York City, NY | Seattle, WA",
)

#: The middle segment: the employer's own boilerplate. Invented, and varied
#: only so the family is not one wording repeated — the reader never looks at
#: this segment, and a family whose every message differs in a place nothing
#: reads is measuring its own decoration.
_POST_NAME_BOILERPLATE: tuple[str, ...] = (
    "Application Received",
    "Thank You For Applying",
    "Application Confirmation",
)

#: The same middle segment on an UPDATE rather than an acknowledgement. See
#: ``_post_name_refusal`` for why the refusals are updates.
_POST_NAME_UPDATE_BOILERPLATE: tuple[str, ...] = (
    "Application Update",
    "Update On Your Application",
    "Your Application Status",
)

#: Update wordings that name NO job title, so the subject's trailing segment is
#: again the only place a role could come from. Both are rejections; the
#: category is what makes the mail an update rather than an assertion that a new
#: application exists, and the verdict itself is not what this family measures.
_POST_NAME_UPDATE_BODIES: tuple[str, ...] = (
    "Hi Ayush, Thank you for your time. After careful consideration we have "
    "decided to move forward with other candidates for this role.",
    "Hello Ayush, We appreciate you taking the time to apply. We will not be "
    "moving forward with your candidacy for this role at this time.",
)


def _post_name_subject(
    display: str,
    boilerplate: str,
    title: str,
    location: str | None,
    echo: str | None = None,
) -> str:
    """``<Employer> | <Boilerplate> | <Role> - <Echo> (<Location>)``.

    ``echo`` defaults to the employer that opened the subject, which is the
    whole shape. Passing a different company is what the cross-company case
    does, and the reader must refuse it.
    """

    tail = f" ({location})" if location else ""
    return f"{display} | {boilerplate} | {title} - {echo or display}{tail}"


def _post_name_body(display: str) -> str:
    """A confirmation that names the employer and NEVER names the job.

    This is the reported #626 message, and it is the reason the family can
    measure the reader at all: the body says "this role" throughout, so
    ``_ROLE_BODY_PATTERNS`` has nothing to capture and the SUBJECT'S TRAILING
    SEGMENT is the only place the title exists. If the reader stops reading it,
    the card goes blank — there is no second path to the title that would keep
    the counter still.
    """

    return (
        f"Hi Ayush, Thank you for applying to {display}. We have received your "
        "application for this role and the recruiting team is reviewing it now. "
        "We will be in touch about this role if there is a fit."
    )


def _post_name_refusal(
    b: _Builder,
    i: int,
    *,
    title: str,
    location: str | None,
    echo_from: tuple[str, str] | None = None,
    note: str,
) -> None:
    """One refusal, at an employer that already holds TWO applications.

    THE SIBLINGS ARE THE INSTRUMENT, not scenery, and a family without them
    reports a confident pass for a reader that refuses nothing. At a
    SINGLE-card employer a message the reader declined still lands on that one
    card, through ``_pick_application``'s rule 4 — correct behaviour, and blind
    to whether the reader refused or resolved. Two live cards is the smallest
    board on which "the product could not tell which application this is" has
    an observable consequence.

    THE REFUSAL ARRIVES AS AN UPDATE, AND THAT IS THE PRODUCT'S RULE RATHER
    THAN THIS FAMILY'S CONVENIENCE. ``partition_applications`` states it in the
    tree — "A NEW CONFIRMATION IS A NEW APPLICATION. AN UPDATE IS NOT" — and
    acts on it: a role-less CONFIRMATION at a multi-application employer is
    deliberately NOT asked about, because "which of these is it about?" is the
    wrong question for mail asserting a new one.

    MEASURED ON A DISCARDED FIRST DRAFT OF THIS FAMILY, said that way because
    the draft is not in the tree and nobody can re-run it. 160 role-less
    CONFIRMATIONS in this shape, at two-card employers: 160 reached a card, 0
    were queued, and ``cards`` came out equal to the ground-truth identity count
    exactly — so none of them minted a row either. They folded onto a row their
    employer already had. A refusal family built on confirmations would
    therefore assert a queue the product does not use for that mail, and would
    grade the anchor rule instead of the reader. An update is the mail for which
    the queue IS the designed answer, which is what makes a refusal observable
    at all.
    """

    display, token = b.employer()
    for k, sibling in enumerate(b.roles(2)):
        b.add(
            family="concatenated-post-name",
            subject=f"Thank you for applying to {display}",
            sender=b.ats(i),
            sender_name=f"{display} Careers",
            body=_confirmation_body(display, sibling),
            expected_category="applied",
            identity=f"{token}|{sibling}",
            employer=token,
            day=(i % 40) + k,
            note="a sibling application, so the refusal below is observable",
        )
    b.add(
        family="concatenated-post-name",
        subject=_post_name_subject(
            display,
            b.pick(_POST_NAME_UPDATE_BOILERPLATE),
            title,
            location,
            echo=echo_from[0] if echo_from else None,
        ),
        sender=b.ats(i),
        sender_name=f"{display} Careers",
        body=b.pick(_POST_NAME_UPDATE_BODIES),
        expected_category="rejection",
        identity=None,
        employer=token,
        expect_review=True,
        day=(i % 40) + 12,
        note=note,
    )


def _concatenated_post_names(b: _Builder, n: int) -> None:
    """A job title read out of the subject's LAST pipe-segment (#626).

        <Employer> | <Boilerplate> | <Role> - <Employer> (<Location>)

    WHAT THIS SHAPE IS, AND WHAT IT IS NOT. It is a CONCATENATION ARTIFACT and
    not a vendor template, and stating it the second way would be a claim
    nobody can check. Independent research across ten applicant-tracking
    products found NO vendor documentation and NO verbatim public quote of this
    shape. In all ten the confirmation subject is EMPLOYER-authored: the vendor
    documents the MECHANISM — merge tokens an employer may insert into a
    subject line — and withholds the default string. So the property this
    reader's licence turns on, that the employer appears at BOTH ends, is
    UNSOURCED. What the shape is consistent with is an employer configuring
    something like ``{{Company}} | Application Received | {{Job Post Name}}``
    where the job post name it interpolates already ends ``- Company
    (Location)``: the employer bracketed its own subject twice without meaning
    to, and no vendor ever wrote it down.

    WHY THE FAMILY EXISTS. A blind cross-check swept 401,244 unique inputs
    against ``_role_from_trailing_segment``: 1,098 reach it, and ZERO of this
    corpus's 13,846 subjects and ZERO of 386,209 backend source literals do.
    This corpus is the only instrument that has ever caught this module's
    regressions — it is what caught the two titles #553 truncated — and until
    now it was blind to the reader entirely. Everything grading the reader was
    written by the hands that wrote it, which is the closed loop ``observed.py``
    exists to break.

    THE TITLES ARE REAL, and that is load-bearing rather than decorative: a
    corpus written in one author's phrasing can only grade one author's
    phrasing. Every job title and every location in this family is copied from
    a PUBLIC Greenhouse board API — ``boards-api.greenhouse.io/v1/boards/
    {anthropic,gitlab}/jobs``, read 2026-08-30. No mailbox content is involved;
    the employers, senders, bodies and boilerplate are invented, as everywhere
    else in this file.

    TWO OF THE EIGHT TITLES ARE NOT BYTE-EXACT, said here rather than smoothed
    over, because unsourced precision is the defect this repository keeps
    finding in its own claims:

      * ``Research Engineer / Scientist, Alignment - London`` appears on the
        board only as ``[Expression of Interest] Research Engineer / Scientist,
        Alignment - London``. The queue marker is dropped; the remainder is the
        posting's own text, and it is the remainder that carries the interior
        dash this family is about.
      * ``Customer Success Engineer, LATAM (Spanish, Portugese) `` carries a
        TRAILING SPACE on the board. It is dropped. The misspelling is the
        board's and is kept.

    The other six titles and all five locations are byte-exact.

    WHAT IS ASSERTED, in three parts.

    1. RESOLVING. Three titles across four tails — the three plain locations
       and no parenthetical at all — at one employer each. The body never names
       the job, so the trailing segment is the ONLY place the title exists and
       ``role_missing`` is the counter this family owns: break the reader and
       every one of these cards goes blank. They sit at SINGLE-application
       employers deliberately, so that a resolved title is measured by the
       card's NAME and no rule-4 filing decision is put in play.

    2. REFUSING, each at an employer holding two other applications. Five
       titles the reader declines, the two pipe-bearing locations, and one
       subject whose echo names a DIFFERENT company from the lead segment.
       Refusal is the designed answer — the reader fails closed — so ground
       truth here is the review queue and not a card. Two things make that
       observable and both are argued for in ``_post_name_refusal``: the
       sibling applications, and the fact that these arrive as UPDATES rather
       than acknowledgements, because the product deliberately never asks about
       a role-less acknowledgement.

    3. BOTH PLACEMENTS, ONE APPLICATION, and this is the case the reader's
       parenthetical rule exists for. The same posting is written two ways —
       ``<Role> - <Employer> (<Location>)`` and ``<Role> (<Location>) -
       <Employer>`` — and they must never become two identities. The tail-side
       strip reaches only the first; keeping the second would hand back
       "<Role> (<Location>)", and ``normalize_role_token`` deletes the brackets
       and KEEPS THE WORD, so one job would hold two role tokens and open two
       cards. Both messages carry one identity here, so that split shows up as
       a SPLIT rather than as a card nobody counted.
    """

    for i in range(n):
        for title in _POST_NAME_RESOLVES:
            for location in (*_POST_NAME_LOCATIONS, None):
                display, token = b.employer()
                b.add(
                    family="concatenated-post-name",
                    subject=_post_name_subject(
                        display, b.pick(_POST_NAME_BOILERPLATE), title, location
                    ),
                    sender=b.ats(i),
                    sender_name=f"{display} Recruiting",
                    body=_post_name_body(display),
                    expected_category="applied",
                    identity=f"{token}|{title}",
                    employer=token,
                    day=i % 40,
                    note=(
                        "the title is in the trailing segment and NOWHERE else; "
                        "a blank card here is the reader gone"
                    ),
                )

        for title in _POST_NAME_QUEUES:
            _post_name_refusal(
                b,
                i,
                title=title,
                location=b.pick(_POST_NAME_LOCATIONS),
                note=(
                    "the reader declines this title in this position; the queue "
                    "is the designed answer and a card would be a guess"
                ),
            )

        for location in _POST_NAME_PIPED_LOCATIONS:
            _post_name_refusal(
                b,
                i,
                title=_POST_NAME_RESOLVES[i % len(_POST_NAME_RESOLVES)],
                location=location,
                note=(
                    "the location carries pipes, so the last pipe-segment is a "
                    "city fragment; resolving one would title a card with a city"
                ),
            )

        # THE ECHO NAMES SOMEBODY ELSE. Drawn from the pool so it cannot
        # collide with a real employer by accident, and never filed under —
        # the same thing the impersonation family does with a forged name.
        _post_name_refusal(
            b,
            i,
            title=_POST_NAME_RESOLVES[(i + 1) % len(_POST_NAME_RESOLVES)],
            location=b.pick(_POST_NAME_LOCATIONS),
            echo_from=b.employer(),
            note=(
                "the echo names a different company from the lead segment, so "
                "the licence the dash depends on is absent"
            ),
        )

        display, token = b.employer()
        title = _POST_NAME_RESOLVES[i % len(_POST_NAME_RESOLVES)]
        location = _POST_NAME_LOCATIONS[i % len(_POST_NAME_LOCATIONS)]
        boilerplate = b.pick(_POST_NAME_BOILERPLATE)
        # THE TAIL PLACEMENT FIRST, on purpose. It is the one that resolves, so
        # it opens the card and titles it; the role-side placement then arrives
        # at an employer holding exactly one application and must join it. The
        # other order would have a blank-titled card opened first and would be
        # measuring the rollup's tolerance for that, which is a different
        # question.
        tail_placement = b.add(
            family="concatenated-post-name",
            subject=_post_name_subject(display, boilerplate, title, location),
            sender=b.ats(i),
            sender_name=f"{display} Recruiting",
            body=_post_name_body(display),
            expected_category="applied",
            identity=f"{token}|{title}",
            employer=token,
            day=i % 40,
            note="one posting, written with the location on the TAIL side",
        )
        b.add(
            family="concatenated-post-name",
            subject=(
                f"{display} | {boilerplate} | {title} ({location}) - {display}"
            ),
            sender=b.ats(i),
            sender_name=f"{display} Recruiting",
            body=_post_name_body(display),
            expected_category="applied",
            identity=f"{token}|{title}",
            employer=token,
            day=(i % 40) + 3,
            joins=tail_placement.message_id,
            note=(
                "the same posting with the location on the ROLE side; two cards "
                "here is the split the parenthetical rule exists to prevent"
            ),
        )


# ── eligibility and identity verification, both ways round ───────────────────


#: The genre this family exists for, and its near-twin, as (subject, sender,
#: body) triples paired by index: ``_ELIGIBILITY_REFUSALS[k]`` and
#: ``_ELIGIBILITY_TWINS[k]`` differ in the NOUN whose verification failed and in
#: nothing else that matters. See ``_eligibility_verification``.
_ELIGIBILITY_REFUSALS: tuple[tuple[str, str, str], ...] = (
    (
        "We need more information to approve your Student status",
        "verify@verifyfast.example",
        "An update on verifying your eligibility. Thank you for uploading your "
        "documentation for confirmation. Unfortunately we were unable to "
        "confirm your status. During the review process it was not possible to "
        "match the document you sent.",
    ),
    (
        "We could not verify your address",
        "no-reply@addrcheck.example",
        "Unfortunately we were unable to verify your address. Our review "
        "process could not match the proof of address you uploaded, so your "
        "submission was declined. Please upload a clearer document to continue.",
    ),
    (
        "Your identity check was unsuccessful",
        "compliance@ledgerpay.example",
        "Thank you for submitting your documents for our know your customer "
        "checks. Unfortunately we could not complete your KYC review, so the "
        "submission was not approved. You may try again with a clearer photo.",
    ),
    (
        "Identity verification declined",
        "trust@parcelhold.example",
        "Unfortunately we are unable to complete identity verification for "
        "your account. During the review process the document you sent could "
        "not be read, so the request was declined.",
    ),
    (
        "Your account recovery request was declined",
        "support@mailnest.example",
        "Unfortunately we could not complete your account recovery request. "
        "The review process was unable to match the details you provided "
        "against the account on file.",
    ),
    (
        "Student verification: more information needed",
        "students@campusverify.example",
        "Unfortunately we were unable to confirm your student status from the "
        "document you uploaded. Our review process needs a dated enrolment "
        "letter before the discount can be applied.",
    ),
)

#: The other way round. Same negative determination, same genre-neutral
#: vocabulary, one noun away — and every one of them IS a rejection.
#:
#: Index 3 is the expensive one and is not a near-miss at all: it carries the
#: refusal vocabulary ("identity verification") AND a full rejection verdict,
#: so it is what bounds the cost of the filter rather than avoiding it.
_ELIGIBILITY_TWINS: tuple[tuple[str, str], ...] = (
    (
        "Update on your application to {e}",
        "Unfortunately we were unable to verify your references for the {r} "
        "role, so we are not moving forward with your application at {e}.",
    ),
    (
        "Your {e} application",
        "Your background check is complete. Unfortunately we are unable to "
        "proceed with your application for the {r} position at {e}.",
    ),
    (
        "Thank you from {e}",
        "Unfortunately we were unable to verify your employment history, and "
        "we will not be proceeding with your candidacy for the {r} role at {e}.",
    ),
    (
        "Update on your {e} application",
        "We have completed identity verification for your candidate profile. "
        "After careful consideration we have decided not to move forward with "
        "your application for the {r} role at {e}. We wish you the best in "
        "your search.",
    ),
    (
        "Your application to the {e} student engineering programme",
        "Thank you for applying to the {e} student engineering programme. "
        "Unfortunately we are unable to offer you a position on this year's "
        "programme and will not be moving forward with your application.",
    ),
    (
        "Update on your {e} application",
        "Thank you for submitting your documents. Unfortunately, after review, "
        "we are not moving forward with your candidacy for the {r} position "
        "at {e}.",
    ),
)


def _eligibility_verification(b: _Builder, n: int) -> None:
    """A negative determination about a PERSON, not about an application (#522).

    "Unfortunately we were unable to confirm your student status. During the
    review process …" is a discount-eligibility refusal. It is not job mail at
    all, and the classifier scored it ``rejection`` 0.70 — into the review
    queue, under a suggestion the reader never applied for. The vocabulary it
    matched is genre-NEUTRAL: ``unfortunately … unable``, "review process",
    "declined", "was unsuccessful" describe any refusal, and nothing in the
    rules layer asked what KIND of determination it was.

    WHY THIS FAMILY HAD TO EXIST BEFORE THE FILTER DID. #521's finding, one
    category over: a negative added without a corpus case to judge it against
    cannot be shown to help OR to be safe. The 700-case ``not-job-mail`` family
    is the nearest thing here and nothing in it looks like this — a job alert,
    a newsletter, a receipt and an OTP all fail to score ``rejection`` for
    reasons that have nothing to do with #522.

    BUILT BOTH WAYS ROUND, which is the whole of the discipline. Even indices
    are REFUSALS (``identity=None``: the board must stay untouched); odd
    indices are their TWINS — the same courtesy, the same "unfortunately …
    unable", one noun away, and every one a real rejection that must keep its
    verdict. A family of refusals alone would be green for a filter that
    deleted the whole category.

    Measured at the recorded seed with the family present and the filter NOT
    yet added: 60 of the 60 refusals scored ``rejection`` 0.70 (wrong) and 60
    of the 60 twins scored ``rejection`` 0.95 (correct). Adding the filter
    moves exactly those 60 refusals, to ``other`` 0.50, and NOTHING else in the
    18,320 cases — per case, not per family total.

    Twin index 3 is the cost bound rather than a near-miss: it carries the
    filter's own vocabulary AND a full rejection verdict, so it is what pays
    the -5. WHAT THIS FAMILY CANNOT SHOW is that cost, and it is said here
    rather than left to read as coverage: its twins arrive over an ATS relay,
    12 - 5 = 7 lands on 0.90, and the +0.05 sender bonus takes it straight back
    to 0.95. The confidence drop is pinned off-relay, in
    ``tests/test_a_verification_refusal_is_not_a_rejection_522.py``, where it
    shows.
    """

    for i in range(n):
        shape = (i // 2) % len(_ELIGIBILITY_REFUSALS)
        if i % 2 == 0:
            subject, sender, body = _ELIGIBILITY_REFUSALS[shape]
            b.add(
                family="eligibility-verification",
                subject=subject,
                sender=sender,
                sender_name=None,
                body=body,
                expected_category="other",
                identity=None,
                employer=None,
                adversarial=True,
                note="a refusal about a person, in the vocabulary of a rejection",
            )
            continue
        display, token = b.employer()
        role = b.role(i)
        subject, body = _ELIGIBILITY_TWINS[shape]
        b.add(
            family="eligibility-verification",
            subject=subject.format(e=display, r=role),
            sender=b.ats(i),
            sender_name=f"{display} Recruiting",
            body=body.format(e=display, r=role),
            expected_category="rejection",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 60,
            note="one noun from the refusal above it, and still a rejection",
        )


# ── an autoresponder to the reader's OWN message, both ways round ────────────


#: One SHAPE per pair, and the pair is the point. Fields:
#: ``(subject, sender, sender_name_suffix, body, refusal_object, twin_object)``.
#:
#: ``{obj}`` is the ONLY slot that differs between the two members of a pair.
#: Subject, sender, sender display name, the courtesy opener and the closing
#: clause are character-identical; the refusal acknowledges a MESSAGE and the
#: twin acknowledges an APPLICATION. A pair that varied the sender as well
#: would prove neither half — the attribute under test here is what the
#: sentence is ABOUT, and nothing else may move with it. See
#: ``_outreach_autoresponders``, and
#: ``tests/test_an_autoresponder_to_outreach_is_not_an_application.py``, which
#: asserts the one-slot property rather than trusting this comment.
#:
#: ``{d}`` is the employer display, ``{r}`` the role, ``{t}`` the employer
#: token (the sender's domain). Every wording is INVENTED; see the family
#: docstring.
_OUTREACH_PAIRS: tuple[tuple[str, str, str, str, str, str], ...] = (
    # THE CASE #521 IS ABOUT: a careers autoresponder carrying "reviewing
    # applications", which is a strong `applied` BODY match and therefore the
    # exact message a genre negative parked behind `has_strong_body` cannot
    # touch. Its twin is a full confirmation and is the cost bound.
    (
        "Re: Compiler work for embedded targets, happy to talk",
        "careers@{t}.example",
        "Careers",
        "Thank you for reaching out to our careers team. We have {obj} and are "
        "reviewing applications on a rolling basis.",
        "read your note",
        "received your application for the {r} position",
    ),
    # The plain contact-form acknowledgement, which the product ALREADY gets
    # right — and whose twin is the weakest genuine confirmation here. This
    # pair is the one that says what a genre negative costs: nothing to gain
    # on the left, a silent drop on the right.
    (
        "Re: Question about your roadmap",
        "hello@{t}.example",
        "Team",
        "Thank you for getting in touch with us. We appreciate you taking the "
        "time to write, and {obj} is with the team now; you will be hearing "
        "from us.",
        "your message",
        "your application for the {r} position at {d}",
    ),
    # `confirm(ing)? receipt` is a strong `applied` pattern and a contact-form
    # autoresponder says it about a MESSAGE. The twin says it about an
    # application, so both sides of this pair carry a strong body match — which
    # is what makes it the sharpest pair in the family: inside
    # `_NOISE_NEGATIVES` a negative is exempted on BOTH.
    (
        "Re: Introduction from a systems engineer",
        "talent@{t}.example",
        "Talent",
        "Thanks for contacting our talent team. This note is confirming "
        "receipt of {obj}; one of us will read it this week.",
        "your introduction",
        "your application for the {r} position at {d}",
    ),
    (
        "Re: Following up on my note last week",
        "info@{t}.example",
        "People",
        "Thank you for reaching out. We will review {obj} and let you know if "
        "there is news worth sharing.",
        "your resume",
        "your application for the {r} position at {d}",
    ),
    (
        "Re: Enjoyed the launch write-up",
        "press@{t}.example",
        "Team",
        "Thanks for getting in touch, and thank you for your interest in the "
        "{r} position at {d}. {obj} is with the team and we read everything "
        "that arrives here.",
        "Your note",
        "Your application for the role",
    ),
    # NOT A REPLY, and the courtesy is in the SUBJECT. Negatives are checked
    # against subject OR body, so a family made only of `Re:` threads would
    # leave the subject arm of any proposed filter ungraded.
    (
        "Thank you for contacting {d}",
        "support@{t}.example",
        "Team",
        "Thank you for contacting us. {obj} has been received and a member of "
        "the team will be in touch shortly.",
        "Your message",
        "Your application",
    ),
    (
        "Re: Intro and portfolio",
        "recruiting@{t}.example",
        "Recruiting",
        "Thank you for reaching out. {obj} for the {r} position at {d} is with "
        "the hiring manager and you will be hearing from us shortly.",
        "Your note",
        "Your application",
    ),
    # The second subject-side wording, and the second `reviewing …` refusal.
    (
        "Thanks for reaching out to {d}",
        "jobs@{t}.example",
        "Recruiting Team",
        "Thank you for getting in touch about opportunities at {d}. {obj} Our "
        "recruiters are reviewing candidates for several teams this quarter.",
        "We keep every note on file.",
        "We have received your application for the {r} position.",
    ),
)


def _fill(body: str, display: str, role: str, obj: str) -> str:
    """One member of a pair. ``obj`` is the slot the pair varies, and nothing else.

    A module-level function rather than a closure over the loop variables:
    ruff's B023 is right that a closure reading `body_t`, `display` and `role`
    from the enclosing scope is a hazard, and here the three are exactly what
    must not drift between the two halves of a pair.
    """

    return body.format(d=display, r=role, obj=obj.format(d=display, r=role))


def _outreach_autoresponders(b: _Builder, n: int) -> None:
    """A robot acknowledging the reader's MESSAGE, and its genuine twin (#521).

    "Thank you for getting in touch / reaching out / contacting us"
    acknowledges a MESSAGE. #520 reported one on the real board: a company the
    owner had cold-emailed sat in his review queue as though it were an
    application update, and he had applied to the same company separately —
    which is why the two members of every pair here share an employer.

    THIS FAMILY IS INVENTED, AND THAT MAKES IT CIRCULAR WITH RESPECT TO THE
    ACCURACY HEADLINE. Every wording below was written by the author of
    ``rules.py``, so it can only confirm the pattern list against itself; it is
    not evidence that the classifier is accurate on real mail, and no number it
    moves may be read as evidence of reach. ``observed.py`` is where this
    corpus's non-circular evidence lives and NOTHING here belongs under it —
    that file is transcription and this is authorship. What this family DOES
    grade is one specific CODE behaviour, in both directions, which is what the
    corpus had no case for at all: measured at HEAD before it was written, the
    phrase family appeared **0 times** in 18,320 cases, so a green corpus run
    proved nothing either way.

    BOTH WAYS ROUND, AND ONE SLOT APART. Every shape in ``_OUTREACH_PAIRS``
    emits two messages that are character-identical except for the object of
    the acknowledgement: the REFUSAL says "your message / your note / your
    introduction" (``identity=None``: it must never reach a card), the TWIN
    says "your application for the <role> position" and is a genuine
    acknowledgement that must keep a verdict. A family made only of refusals
    would be green for a change that deleted the category.

    WHAT IT MEASURED, which is the reason it exists. Three arms, each run PER
    CASE over the whole 18,480 and diffed against the last — counted in cases
    and not in shapes, because the shapes are not uniform and a shape count
    would round the cost down:

      (a) no pattern, today          40 autoresponders score `applied` 0.70 and
                                     reach the review queue. 40 twins sit at
                                     0.70, 10 at 0.80 and 30 at 0.90.
      (b) inside `_NOISE_NEGATIVES`  ZERO of the 40 move — every one carries a
                                     strong `applied` BODY match, so
                                     `has_strong_body` exempts the negative in
                                     exactly the case it was written for — and
                                     40 genuine confirmations fall under
                                     `REVIEW_FLOOR` to `other` 0.50. A blast
                                     radius of nothing that should move and 40
                                     that must not: a regression, not a fix.
      (c) outside it                 all 40 are fixed. 55 genuine confirmations
                                     go under `REVIEW_FLOOR` — no card, no
                                     queue entry, nothing the reader can
                                     correct — and 25 more fall from auto-file
                                     to the queue. Corpus `correct` 17250 ->
                                     17235: the repair costs more than the
                                     defect.

    Nothing OUTSIDE this family moved in either arm, and that is a fact about
    the corpus rather than a reassurance: the phrase appears 160 times in
    18,480 cases and all 160 are here.

    So the negative stays out, and this family is the measurement that settles
    it rather than the pattern's regression test. ``rules.py`` records the same
    beside `applied`'s negatives.

    WHAT THIS FAMILY CANNOT SHOW, said here rather than left to read as
    coverage:

      * The genre reaches the queue through `follow_up` as well. "someone will
        reach out with updates" scores `follow_up` 3 against `applied` 2, and
        an `applied`-only genre filter cannot see it in any arm. No pair here
        can grade that, because a pair whose refusal leaks to `follow_up` has
        no twin that stays `applied`.
      * Its senders are the employer's own inboxes, never an ATS relay, so the
        +0.05 relay bonus is out of the arithmetic. That is deliberate — it
        keeps the confidence a property of the words — and it means this family
        says nothing about the same wording arriving over Greenhouse.

    Every wording is synthetic. The shape is the owner's; the words are not,
    and no real employer, address or thread appears anywhere in it.
    """

    if n % 2:  # pragma: no cover — a harness error, not a product finding
        raise AssertionError(f"{n} is odd; this family emits pairs")

    for i in range(n // 2):
        subject_t, sender_t, suffix, body_t, refusal_obj, twin_obj = _OUTREACH_PAIRS[
            i % len(_OUTREACH_PAIRS)
        ]
        display, token = b.employer()
        role = b.role(i)
        # ONE draw, used by both members. A pair whose employer or role moved
        # between its halves would vary two things and prove neither.
        subject = subject_t.format(d=display, r=role)
        sender = sender_t.format(t=token.split()[0])
        sender_name = f"{display} {suffix}"

        b.add(
            family="outreach-autoresponder",
            subject=subject,
            sender=sender,
            sender_name=sender_name,
            body=_fill(body_t, display, role, refusal_obj),
            expected_category="other",
            identity=None,
            employer=None,
            adversarial=True,
            day=i % 60,
            note="a robot acknowledging a MESSAGE, in an acknowledgement's words",
        )
        b.add(
            family="outreach-autoresponder",
            subject=subject,
            sender=sender,
            sender_name=sender_name,
            body=_fill(body_t, display, role, twin_obj),
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
            day=(i % 60) + 1,
            note="one slot from the refusal above it, and a real confirmation",
        )


# ── the four families the corpus could not express (#614, #630) ─────────────
#
# WHAT THEY HAVE IN COMMON, and why they are written together. Every one of them
# turns on a message that names NO JOB AT ALL. `application_sub_key` is
# `req_id or role_token or None`, and None is a VALUE: two messages that both
# name nothing are the SAME application by the product's own rule, which is what
# keeps one employer's two identical acknowledgements a single decision (#454).
# So a role-less acknowledgement and a later role-less update on one thread share
# a `review_dedup_key` exactly, and that collision is the precondition every one
# of these families needs.
#
# It is also the ordinary shape rather than a contrived one. "Crusoe |
# Application Received" names no role; so does most of what an ATS sends before
# a human is involved.
#
# EACH FAMILY VARIES SOMETHING, ON PURPOSE. A family written one way round
# cannot catch its own defect — every case would reach the product through one
# route, and a change that closed that route would empty the family while every
# number stayed put and read as coverage. What varies is stated per family.

#: Role-less acknowledgements that clear ``AUTO_FILE_GATE`` and file themselves.
#:
#: MEASURED, not assumed, and the check is the point: all three score `applied`
#: at 0.95 and `role_from_message` returns nothing for any of them, so each
#: files a card AND keys to ``(thread, None)``. A wording that named a job
#: would key differently from its own follow-up and the family would quietly
#: measure nothing. `test_the_settled_families_reach_the_filter` re-derives
#: this from the corpus rather than trusting this comment.
_ROLELESS_ACKS: tuple[tuple[str, str], ...] = (
    ("{e} | Application Received",
     "Hi Ayush, Thank you for applying to {e}. We have received your "
     "submission and our team will review it shortly."),
    ("Your application has been received!",
     "Hi Ayush, Thanks for applying to {e}. Our team will review your "
     "application shortly."),
    ("Thanks for applying to {e}!",
     "Hi Ayush, Thank you for your interest in joining {e}. Your submission "
     "has been received and is being reviewed."),
)

#: Role-less messages the product is NOT confident about, by BOTH routes into
#: the review queue. The pair is the variation that matters, because the two
#: reach the filter for unrelated reasons and a change that closes one leaves
#: the other:
#:
#:   * ``below_gate`` — an `offer` at 0.75. In ``[REVIEW_FLOOR, AUTO_FILE_GATE)``:
#:     a real proposal the product will not file alone. This is #448's mechanism
#:     and it scores in ``update_held_on_its_own_confidence``.
#:   * ``ats_floor`` — `other` at 0.50, UNDER the review floor, floored into the
#:     queue by ``references_an_application`` because a known ATS relayed it
#:     (#166/#417). It scores in ``update_held_on_a_non_offer_verdict``.
#:
#: Both are verified to become review refs, and both derive no role, so both
#: key to ``(thread, None)``.
#:
#: THE THIRD ENTRY IS THE CATEGORY A PERSON WOULD GIVE, which is not the
#: classifier's and must not be. `expected_category` is what the MAIL carries to
#: someone reading the whole thing in Gmail, and `answer_the_queue` models a
#: perfect answerer by replying with it. An `ats_floor` message says plainly
#: that an application exists and that nothing has been decided — which is
#: `pending_application`, a FILING category. Labelling it `other` would have the
#: perfect answerer file it nowhere, so the corpus would assert that the right
#: answer to "we have an update about your application" is "this is not job
#: mail", and every one of these cases would leave the queue for nothing.
_UNCERTAIN_ROLELESS: tuple[tuple[str, str, str, str], ...] = (
    ("below_gate", "An offer from {e}",
     "Hi Ayush, We are delighted to extend you an offer to join us. The "
     "written terms are attached for your review.", "offer"),
    ("ats_floor", "Your {e} application",
     "Hi Ayush, We have an update to share about your application. Please "
     "look out for a further message from the hiring team.", "pending_application"),
    ("ats_floor", "A note about your application",
     "Hello Ayush, We wanted to let you know where things stand with your "
     "application. Someone will write again once the panel has met.",
     "pending_application"),
    ("ats_floor", "Regarding your candidacy",
     "Hi Ayush, Thank you for your patience while we work through this. Your "
     "candidacy is still under discussion and we will be in touch.",
     "pending_application"),
)


def _settled_suppresses_an_update(b: _Builder, n: int) -> None:
    """#630. An uncertain update on a thread the board already answers for.

    THE CLASS THE CORPUS COULD NOT EXPRESS. ``_persist_review_items_additive``
    refuses an arriving review ref whose ``review_dedup_key`` matches a stored
    message that is filed on an application that answers — and a refused ref is
    dropped BEFORE ``_persist_message_refs``, so it gets no row, no queue entry
    and no counter. Measured over a full replay before this family existed:
    2,873 refs offered, 2,873 persisted, **0 dropped**. The machinery ran on
    every batch and never bit, because every other family's threads are held
    apart by the identity component and no arriving key could collide.

    So the population was empty by construction, and #630's counter was a zero
    that could not be anything else. This family makes it non-empty: an
    acknowledgement that names no job files a card, and a later message on the
    SAME thread that also names no job derives the same ``None`` sub-key.

    WHAT VARIES, and each of the three is load-bearing:

      * WHICH ACKNOWLEDGEMENT (3 wordings). One wording per shape grades
        nothing — a defect that fires on a single phrasing would be pinned to
        exactly n/3 and read as a property of the product.
      * WHICH ROUTE INTO THE QUEUE (``below_gate`` and ``ats_floor``, see
        ``_UNCERTAIN_ROLELESS``). The two are unrelated mechanisms. A family
        built only on the confidence band would empty itself the day the gate
        moved, silently.
      * THE GAP IN DAYS, **including zero**. A gap of 0 puts both messages in
        ONE day-batch, and the refusal then happens inside a single sync:
        ``upsert_applications_for_user`` files the acknowledgement before
        ``_persist_review_items_additive`` runs, and the prefetch is not
        shielded from autoflush. That is not a cross-sync artefact and a family
        that only ever spanned syncs would not contain it.

    THIS FAMILY ASSERTS NO FIX. Whether refusing these is right is a product
    decision about what "settled" should mean for an update to a card that
    exists, and #630 is explicit that it is not a predicate tweak. The corpus's
    job is to make the class countable; ``suppressed_as_settled`` is reported
    OUTSIDE ``total`` for exactly that reason.
    """

    gaps = (0, 1, 3, 9)
    for i in range(n):
        display, token = b.employer()
        thread = f"settled-{token}"
        subject, body = b.pick(_ROLELESS_ACKS)
        route, up_subject, up_body, up_truth = b.pick(_UNCERTAIN_ROLELESS)
        day = i % 200
        ack = b.add(
            family="settled-suppresses-an-update",
            subject=subject.format(e=display),
            sender=b.ats(i),
            sender_name=f"{display} Recruiting",
            body=body.format(e=display),
            expected_category="applied",
            identity=f"{token}|__settled__",
            employer=token,
            thread=thread,
            day=day,
            note="names no job, so its dedup key is (thread, None)",
        )
        b.add(
            family="settled-suppresses-an-update",
            subject=up_subject.format(e=display),
            sender=b.ats(i),
            sender_name=f"{display} Recruiting",
            body=up_body.format(e=display),
            expected_category=up_truth,
            identity=f"{token}|__settled__",
            employer=token,
            thread=thread,
            day=day + gaps[i % len(gaps)],
            joins=ack.message_id,
            note=(
                f"uncertain, reaches the queue by {route}, same (thread, None) "
                f"key as the acknowledgement above — the settled filter refuses it"
            ),
        )


def _hand_dismissal_swallows_later_mail(b: _Builder, n: int) -> None:
    """#614. The user removes a card; mail keeps arriving on its thread.

    THE STATE THE REPLAY NEVER CONSTRUCTED. ``generate.py`` contained zero
    occurrences of `dismiss` before this family, so `dismissed_at` was NULL over
    every row the corpus produced. That made ``_filed_on_a_live_application``
    equivalent BY CONSTRUCTION to the ``application_id IS NOT NULL`` it
    replaced, and #614's own control — reinstate the #596 predicate, confirm
    the figure moves — returned two byte-identical runs across all 24 counters.

    WHAT HAPPENS, verified by execution rather than read off the source:

      * the confirmation files a card;
      * the user hand-dismisses it (``dismiss_application``, the real endpoint's
        function, tagging ``dismissed_reason = 'user'``);
      * a later CONFIDENT lifecycle message on the same thread rolls up to that
        card, and ``upsert_applications_for_user`` ``continue``s on a
        user-dismissed row before ``_persist_message_refs`` is ever reached.

    The last message therefore gets NO ``emails`` row at all. Not on a card, not
    in the queue, not under the floor with a counter naming it — nothing. That
    is ``LOST``'s definition word for word: "indistinguishable from a quiet
    mailbox".

    THE CONFIRMATION IS NOT LOST AND MUST NOT BE COUNTED AS ONE. It keeps its
    row on the dismissed card, so ``restore_application`` brings it back intact.
    The later message has no row to restore. That difference is the whole
    distinction, and it is why the harness scores the confirmation in
    ``filed_on_a_card_the_user_removed`` instead: a family whose headline number
    were half mail the product filed correctly could not say which half was the
    finding.

    WHETHER THE LOSS IS A DEFECT IS NOT THIS FAMILY'S CALL. A hand dismissal is
    final on purpose (#597): the user's "no" answers for that card's mail, and
    re-filing it every sync is how a row the user just cleared keeps coming
    back. What the corpus can say is that the mail reaches nothing and nothing
    counts it, which was true before and unmeasurable.

    WHAT VARIES: which lifecycle verdict arrives after the dismissal
    (rejection / interview / assessment — three different rollup paths, not one
    wording three times), and whether an UNCERTAIN message follows as well.
    That last is the second outcome the dismissal produces: an uncertain message
    is offered to the persist, finds the confirmation settled — a hand-dismissed
    card ANSWERS for its mail — and is refused, which lands in
    ``suppressed_as_settled`` rather than in ``lost``. One user action, two
    different disappearances, and a family carrying only one of them would
    report half the behaviour.
    """

    afters = (
        ("rejection", "Update on your application to {e}",
         "Hi Ayush, After careful consideration we have decided not to move "
         "forward with your application. We appreciate your interest.",
         "rejected"),
        ("interview", "Next steps with {e}",
         "Hi Ayush, We would like to invite you to interview. Please choose a "
         "time from the scheduling link below.",
         "interviewing"),
        ("assessment", "Your {e} take-home",
         "Hi Ayush, Please complete the take-home exercise linked below within "
         "five days to move to the next stage.",
         "assessment"),
    )
    for i in range(n):
        display, token = b.employer()
        role = b.role(i)
        thread = f"dismissed-{token}"
        day = i % 200
        opener = b.add(
            family="hand-dismissal-swallows-later-mail",
            subject=f"Thank you for applying to {display}",
            sender=b.ats(i),
            sender_name=f"{display} Recruiting",
            body=_confirmation_body(display, role),
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
            thread=thread,
            day=day,
            standing_instruction="dismiss",
            note="opens the card the user then removes by hand",
        )
        category, subject, body, _stage = afters[i % len(afters)]
        b.add(
            family="hand-dismissal-swallows-later-mail",
            subject=subject.format(e=display),
            sender=b.ats(i),
            sender_name=f"{display} Recruiting",
            body=body.format(e=display),
            expected_category=category,
            identity=f"{token}|{role}",
            employer=token,
            thread=thread,
            day=day + 4,
            joins=opener.message_id,
            note="confident, arrives AFTER the dismissal, reaches nothing at all",
        )
        # Every third group also gets an uncertain follow-up, so the family
        # carries both disappearances rather than only the loud one.
        #
        # IT NAMES THE ROLE, and that is the whole reason it works. The opener
        # names one, so its stored key is ``(thread, role_token)``; a role-LESS
        # follow-up would key to ``(thread, None)``, collide with nothing, and
        # reach the queue — which is correct behaviour and not what this half of
        # the family is for. Measured: `offer` at 0.75, a review ref, role
        # derived. See `_UNCERTAIN_ROLELESS` for the two routes and why the band
        # is checked rather than assumed.
        if i % 3 == 0:
            b.add(
                family="hand-dismissal-swallows-later-mail",
                subject=f"An offer from {display}",
                sender=b.ats(i),
                sender_name=f"{display} Recruiting",
                body=(
                    f"Hi Ayush, We are delighted to extend you an offer for the "
                    f"{role} position. The written terms are attached for your "
                    f"review."
                ),
                expected_category="offer",
                identity=f"{token}|{role}",
                employer=token,
                thread=thread,
                day=day + 8,
                joins=opener.message_id,
                note="uncertain, same role key: refused because a hand-dismissed card ANSWERS",
            )


def _answered_then_more_mail(b: _Builder, n: int) -> None:
    """#614's control, and the ``is_reviewed`` arm nothing could reach.

    WHY THIS FAMILY IS THE ONE THAT MAKES THE CONTROL RUNNABLE. #614 asks for
    the #596 predicate to be reinstated and the figure to MOVE. The two
    spellings differ on exactly two populations:

      (i)  a row linked to a RESYNC-dismissed card — settled under
           ``application_id IS NOT NULL``, not settled under the shared
           predicate; and
      (ii) a row the user ANSWERED with a category that files nothing —
           ``is_reviewed`` set, ``application_id`` still NULL — which is settled
           under the shared predicate and NOT settled under ``IS NOT NULL``.

    Population (i) is unreachable here and says so with a number:
    ``RECORDED_SYNC["purged"]`` is 0, so no batch has ever left a row without
    mail and nothing in a replay resync-dismisses anything. Population (ii) was
    equally unreachable, for a different reason: ``is_reviewed`` is written by
    ``classify_review_item`` and ``_settle_thread_siblings`` and by nothing on
    the sync path, and the harness answered the queue ONCE, after the last day —
    so zero rows carried the flag while any batch was still arriving, and the
    ``is_reviewed`` arm of the settled filter could not fire at all.

    Production interleaves; the corpus did not. This family makes it: the user
    answers a held message mid-replay, through the product's own
    ``classify_review_item``, and more mail then arrives on the same thread.

    So the answered row settles the conversation, the later message keys to it,
    and reinstating #596 stops it being settled. THE DIRECTION, stated before
    the control was run rather than after: the reinstatement makes
    ``suppressed_as_settled`` FALL and ``addressed_in_the_queue`` RISE, because
    this is arm (ii). It is the opposite of the rise arm (i) would produce, and
    a correct control read backwards looks exactly like a failed one.

    WHAT VARIES: which uncertain wording opens the conversation, which one
    follows it, and the gap between them — never the same pair twice in a row.
    """

    for i in range(n):
        display, token = b.employer()
        thread = f"answered-{token}"
        day = i % 200
        first = _UNCERTAIN_ROLELESS[i % len(_UNCERTAIN_ROLELESS)]
        second = _UNCERTAIN_ROLELESS[(i + 1) % len(_UNCERTAIN_ROLELESS)]
        opener = b.add(
            family="answered-then-more-mail",
            subject=first[1].format(e=display),
            sender=b.ats(i),
            sender_name=f"{display} Recruiting",
            body=first[2].format(e=display),
            expected_category=first[3],
            identity=f"{token}|__answered__",
            employer=token,
            thread=thread,
            day=day,
            standing_instruction="answer_other",
            note="held in the queue, then answered 'not a lifecycle thing'",
        )
        b.add(
            family="answered-then-more-mail",
            subject=second[1].format(e=display),
            sender=b.ats(i),
            sender_name=f"{display} Recruiting",
            body=second[2].format(e=display),
            expected_category=second[3],
            identity=f"{token}|__answered__",
            employer=token,
            thread=thread,
            day=day + 5 + (i % 4),
            joins=opener.message_id,
            note="same (thread, None) key as a row the user has already answered",
        )


def _another_mailbox_cannot_settle_mine(b: _Builder, n: int) -> None:
    """#614's second half: a corpus with one user cannot fail a user predicate.

    THE HOLE. Every query in the harness and every settled test in the product
    is scoped by ``user_id``. With one generated user those clauses are
    satisfied by construction: deleting one moves no number, so nothing in
    18,480 messages asserted that a stranger's board cannot answer for your
    mail. That is the same shape as the dismissal hole in the same issue — a
    predicate whose failure mode no fixture can construct.

    THE COLLISION IS THE POINT, and it is the part that is easy to get wrong.
    Giving the other mailbox its own thread ids would leave the control inert:
    the settled query would find nothing to match whether or not it was scoped,
    and a green run would prove only that two unrelated sets do not overlap.
    So both mailboxes use the SAME thread id and the same role-less shape, and
    therefore the same ``review_dedup_key``. The only thing keeping the other
    mailbox's settled row from answering for the owner's arriving ref is the
    ``Email.user_id == user_id`` clause — which is now the one thing under test.

    The other mailbox's message is FIXTURE. It is not the owner's mail, it is
    not scored on the owner's board, and it must never appear there: a case in
    slot 1 that reached the owner's cards would be a tenant-isolation failure,
    which is a far larger finding than anything this family is about.

    TWO ARMS, HALF THE GROUPS EACH, because the settled test's cross-user
    defence is not one clause and a control that moved only one of them would
    leave the other asserted by nothing:

      * ``Email.user_id == user_id`` on the settled-row query itself. This is
        the ONLY thing scoping the ``is_reviewed`` arm — that arm is a bare
        ``Email.is_reviewed == True`` and carries no user predicate of its own.
        Groups with an EVEN index exercise it: the other mailbox's message is
        uncertain and its owner answers it, leaving a reviewed row.
      * ``Application.user_id == user_id`` inside
        :func:`_filed_on_an_application_that_answers`. Groups with an ODD index
        exercise it: the other mailbox's acknowledgement files a card, so the
        row is settled by being ON something rather than by being answered.

    So dropping the first clause alone leaks the even half, and dropping both
    leaks all of it. Two mutations with two different magnitudes, which is what
    tells the arms apart — a single number moving would not say which clause
    was carrying the isolation.

    WHAT ELSE VARIES: which acknowledgement the other mailbox sends and which
    uncertain route the owner's message takes, so the collision is not one
    wording pair repeated n times.
    """

    for i in range(n):
        display, token = b.employer()
        # ONE thread id, TWO mailboxes. See the docstring: without this the
        # control cannot fire.
        thread = f"xuser-{token}"
        day = i % 200
        if i % 2 == 0:
            # The other mailbox holds an ANSWERED row — the `is_reviewed` arm.
            route, x_subject, x_body, x_truth = _UNCERTAIN_ROLELESS[
                i % len(_UNCERTAIN_ROLELESS)
            ]
            b.add(
                family="another-mailbox-cannot-settle-mine",
                subject=x_subject.format(e=display),
                sender=b.ats(i),
                sender_name=f"{display} Recruiting",
                body=x_body.format(e=display),
                expected_category=x_truth,
                identity=f"{token}|__crossuser__",
                employer=token,
                thread=thread,
                day=day,
                user_slot=1,
                standing_instruction="answer_other",
                note="ANOTHER mailbox's REVIEWED row: the arm with no user predicate of its own",
            )
        else:
            # The other mailbox holds a FILED row — the `answers` arm.
            subject, body = _ROLELESS_ACKS[i % len(_ROLELESS_ACKS)]
            b.add(
                family="another-mailbox-cannot-settle-mine",
                subject=subject.format(e=display),
                sender=b.ats(i),
                sender_name=f"{display} Recruiting",
                body=body.format(e=display),
                expected_category="applied",
                identity=f"{token}|__crossuser__",
                employer=token,
                thread=thread,
                day=day,
                user_slot=1,
                note="ANOTHER mailbox's FILED row, on the same thread id",
            )
        route, up_subject, up_body, up_truth = _UNCERTAIN_ROLELESS[
            i % len(_UNCERTAIN_ROLELESS)
        ]
        b.add(
            family="another-mailbox-cannot-settle-mine",
            subject=up_subject.format(e=display),
            sender=b.ats(i),
            sender_name=f"{display} Recruiting",
            body=up_body.format(e=display),
            expected_category=up_truth,
            identity=f"{token}|__crossuser__",
            employer=token,
            thread=thread,
            day=day + 6,
            note="the OWNER's uncertain mail: must reach the queue, not be settled by a stranger",
        )


# ── a lifecycle outcome that belongs to SOMEBODY ELSE, both ways round ───────


#: One SHAPE per pair, and the pair is the point. Fields:
#: ``(subject, body, third_party_object, reader_object, reader_category)``.
#:
#: ``{obj}`` is the ONLY slot that differs between the two members of a pair.
#: Subject, sender, sender display name and every other character of the body
#: are identical; the left member says the sentence is about a person the
#: reader REFERRED, the right member says it is about the reader. A pair that
#: moved the subject as well would prove neither half — the attribute under
#: test is who the sentence is ABOUT, and nothing else may travel with it.
#: ``test_someone_elses_outcome_is_not_the_readers.py`` asserts that one-slot
#: property rather than trusting this comment.
#:
#: EVERY PAIR HERE WAS MEASURED BEFORE IT WAS WRITTEN DOWN, on main @ 2b49a2e7,
#: and a sixth was DISCARDED for failing the screen: "invite {obj} to the next
#: round" scores ``other`` 0.50 for the third party, which buckets ``correct``
#: and would have pinned a case that cannot fail. That is the defect this
#: family is named after, and building the family out of unscreened wordings
#: would have rebuilt it inside its own fix. The five below all score a
#: lifecycle category for the third party today; three of them do it at 0.90,
#: above the 0.85 auto-file gate.
#:
#: ``{d}`` is the employer display, ``{r}`` the role. Every wording is INVENTED
#: and names no person: the policy slot for a human name is a placeholder, and
#: "the candidate you referred" needs none.
_SOMEONE_ELSE_PAIRS: tuple[tuple[str, str, str, str, str], ...] = (
    # The auto-filed core of the issue: a referral rejection carries a
    # rejection's whole vocabulary and nothing asks who was not selected.
    (
        "Update on the {r} position at {d}",
        "Hi Ayush, We wanted to let you know {obj} not selected for the "
        "position. We have decided to move forward with other candidates.",
        "the candidate you referred was",
        "you were",
        "rejection",
    ),
    (
        "An update from {d}",
        "Hi Ayush, Unfortunately we will not be moving forward with {obj} "
        "application at this time. We appreciate the interest in the {r} role.",
        "your referral's",
        "your",
        "rejection",
    ),
    # The tightest pair in the family: both members score `rejection` at the
    # SAME 0.90. The classifier is not weighing this evidence and losing, it
    # cannot see the distinction at all.
    (
        "After careful consideration",
        "Hi Ayush, After careful consideration we have decided not to proceed "
        "with {obj} at this time. Thank you for the time invested in the {r} "
        "process.",
        "the candidate you referred",
        "your application",
        "rejection",
    ),
    # Not rejection-specific. The same blindness files a stage ADVANCE.
    (
        "Scheduling for the {r} position at {d}",
        "Hi Ayush, We have scheduled an interview with {obj} for next Tuesday. "
        "Please let us know if that time works.",
        "the candidate you referred",
        "you",
        "interview",
    ),
    (
        "News about the {r} position at {d}",
        "Hi Ayush, We are pleased to extend an offer to {obj}. Thank you for "
        "the time invested throughout this process.",
        "the candidate you referred",
        "you",
        "offer",
    ),
)

#: ARM THREE: the reader's OWN outcome in mail that ALSO says "referral".
#:
#: THE ONLY CONTROL HERE THAT CAN BITE A REFERRAL-KEYED RULE, and the reason it
#: exists separately from the twins above. A twin says "you were not selected"
#: and carries no referral token at all, so a rule keyed on ``referr*`` cannot
#: move it however badly that rule is written — a control that cannot fail is
#: decoration. These five carry the token and are genuinely about the reader,
#: so they are the mail a careless suppression breaks. All five score their
#: category correctly today (three of them above the auto-file gate), measured
#: on main @ 2b49a2e7; if any of them ever scores ``other``, a fix has bought
#: its third-party accuracy by dropping real outcomes on the floor.
_REFERRAL_BEARING_OWN: tuple[tuple[str, str, str], ...] = (
    (
        "News about the {r} position at {d}",
        "Hi Ayush, Thank you for the referral from a member of our team, which "
        "is how your name reached us. We are pleased to extend an offer to you "
        "for the {r} role.",
        "offer",
    ),
    (
        "Update on the {r} position at {d}",
        "Hi Ayush, You came to us through a referral. Unfortunately we have "
        "decided to move forward with other candidates and will not be "
        "proceeding with your application.",
        "rejection",
    ),
    (
        "Scheduling for the {r} position at {d}",
        "Hi Ayush, Your referral from a teammate was a strong signal. We have "
        "scheduled an interview with you for next Tuesday.",
        "interview",
    ),
    (
        "After careful consideration",
        "Hi Ayush, We appreciate the referral that introduced you to us. After "
        "careful consideration we have decided not to proceed with your "
        "application at this time.",
        "rejection",
    ),
    (
        "Next steps at {d}",
        "Hi Ayush, Thanks for referring a colleague to us as well. Separately, "
        "we would like to schedule an interview with you for the {r} role.",
        "interview",
    ),
)

#: The stage a card must read once its own lifecycle mail has been filed.
_SOMEONE_ELSE_STAGE = {
    "rejection": "rejected",
    "interview": "interviewing",
    "offer": "offered",
}


def _someone_elses_outcome(b: _Builder, n: int) -> None:
    """A lifecycle phrase about SOMEBODY ELSE, scored as the reader's own (#768).

    "The candidate you referred was not selected" scores ``rejection`` 0.90 —
    above the auto-file gate — and there is no mechanism anywhere in
    ``classifier/rules.py`` that asks who a sentence is about. Searched for
    ``referr*``, ``third party``, ``another candidate`` and ``on behalf``; the
    only adjacent thing is ``\\breferral bonus\\b`` in ``hybrid.py``'s
    ``NON_APPLICATION_PATTERNS``, which needs two content hits and is not in
    the loop for the rules layer at all.

    WHY THE FAMILY IS ABOUT THE BOARD AND NOT ONLY THE VERDICT. Measured
    through ``harness.replay``: a referral notification from a company the
    reader HAS applied to joins the reader's own card and settles it. The card
    reads ``rejected`` and ``reviewed`` is empty — nobody is asked. That is the
    failure ``test_the_board_is_clean`` calls the strictly worse one, "a
    rejection landing on the wrong card settles a live application terminally",
    and it read green because no family constructed the shape. So every group
    here seeds the reader's OWN live card first and the third-party message
    arrives at that same employer, where the damage is.

    BUILT BOTH WAYS ROUND, which is the whole of the discipline. Even indices
    are the CASE: a confirmation for the reader's own application, then a
    third-party message (``identity=None``) that must never reach the card and
    must leave the stage at ``applied``. Odd indices are the TWINS: the same
    confirmation, then the reader's OWN lifecycle mail, which must keep its
    verdict and must carry the card to its stage. A family of third-party mail
    alone would go green for a rule that suppressed the whole lifecycle
    vocabulary near the word "referral" — and that rule is one bad
    generalisation away, because the twins are the mail it would break.

    THE TWINS ARE ADVERSARIALLY CLOSE ON PURPOSE. "We are pleased to extend you
    an offer" contains no referral token and so cannot fail against a rule
    keyed on one; a control that cannot fail is decoration. Each twin here is
    one slot from its case, so any rule that separates them has to do it on who
    the sentence is about rather than on which words appear.

    THERE IS NO FIX, ON PURPOSE, and DEC-013 is where that is argued. Every
    wording here is AUTHORED — ``observed.py`` holds no referral or reference
    mail at all — so this family can show that the classifier is blind to
    attribution and it CANNOT say how often real mail asks it not to be. Its
    counts are a defect pinned at its size, never a baseline to be defended.
    """

    for i in range(n):
        display, token = b.employer()
        role = b.role(i)
        arm = i % 3
        if arm == 2:
            subject, body, category = b.pick(_REFERRAL_BEARING_OWN)
            third = reader = ""
        else:
            subject, body, third, reader, category = b.pick(_SOMEONE_ELSE_PAIRS)
        sender = b.ats(i)
        case_arm = arm == 0
        # ONLY THE CASE ARM MAKES A BOARD CLAIM, and the claim is that nothing
        # happened: the card must still read `applied` after the third-party
        # message has been through the sync.
        #
        # The reader arms deliberately assert NO stage. Their lifecycle mail is
        # graded on its VERDICT, and several of those verdicts land between
        # `REVIEW_FLOOR` and `AUTO_FILE_GATE` — held for review, not filed —
        # so the card correctly stays `applied` and a `card_status` here would
        # pin the product's own "ask rather than assert" as a WRONG-STAGE.
        # Measured before it was removed: it cost 27 false WRONG-STAGE rows
        # against 30 real ones, which is a fixture over-claim of nearly half.
        stage = "applied" if case_arm else None
        anchor = f"c{b._n + 1:05d}"
        b.add(
            family="someone-elses-outcome",
            subject=f"Thank you for applying to {display}",
            sender=sender,
            sender_name=f"{display} Talent",
            body=(
                f"Hi Ayush, Thank you for applying to the {role} role at "
                f"{display}. We have received your application and the team is "
                f"reviewing it."
            ),
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 60,
            # The stage the card must READ once this group's second message has
            # been handled. On the case arm that is still `applied`: the
            # third-party message below must not have moved it.
            card_status=stage,
        )
        if case_arm:
            b.add(
                family="someone-elses-outcome",
                subject=subject.format(r=role, d=display),
                sender=sender,
                sender_name=f"{display} Talent",
                body=body.format(obj=third, r=role, d=display),
                # NOT job mail for this reader. `identity=None` is the whole
                # claim: it must never become an application and must never
                # land on one.
                expected_category="other",
                identity=None,
                employer=None,
                day=i % 60 + 4,
                adversarial=True,
                note="a lifecycle outcome belonging to a person the reader referred",
            )
        else:
            b.add(
                family="someone-elses-outcome",
                subject=subject.format(r=role, d=display),
                sender=sender,
                sender_name=f"{display} Talent",
                body=(
                    body.format(r=role, d=display)
                    if arm == 2
                    else body.format(obj=reader, r=role, d=display)
                ),
                expected_category=category,
                identity=f"{token}|{role}",
                employer=token,
                day=i % 60 + 4,
                joins=anchor,
                note=(
                    "carries the referral token and is STILL the reader's own"
                    if arm == 2
                    else "one slot from the case above it, and genuinely the reader's own"
                ),
            )


#: An employer's OWN mail addresses, on the reserved ``.example`` TLD (#523).
#:
#: ``{t}`` IS THE LEADING WORD OF THE EMPLOYER TOKEN, NOT THE WHOLE TOKEN, and
#: that is load-bearing twice over.
#:
#:   * **It is the only spelling that can route.** Two thirds of the invented
#:     pool carry a suffix ("Copperthwaitegate Labs"), so the whole token has a
#:     space in it and ``careers@{token}.example`` is an address no mail system
#:     could deliver. 281 cases already in this corpus carry one —
#:     ``outreach-autoresponder`` 110 and ``update-from-another-domain`` 171 —
#:     and they resolve correctly only BECAUSE of it: ``_domain_brand`` splits
#:     on dots, so the space survives into the brand and the brand happens to
#:     equal the token. Filed separately; not repeated here.
#:   * **It still resolves to the right employer**, by the product's own rule
#:     rather than by a harness convenience. ``pipeline.matches_company_token``
#:     accepts a match on the LEADING WORD — the same grouping
#:     ``roll_up_applications`` applies — so ``careers@copperthwaitegate.example``
#:     identifies "Copperthwaitegate Labs". Verified against that function
#:     rather than asserted here.
#:
#: SO THE IDENTITY OUTCOME IS HELD FIXED WHILE THE SENDER CLASS VARIES.
#: ``company_key`` takes the sender-domain brand first whenever that brand is
#: not a relay, so this arm resolves its employer off the DOMAIN while the relay
#: arm (``observed-confirmation``) resolves the same employer off the subject
#: and the display name. Same answer, different path. A domain whose brand did
#: NOT match the employer — the real message is ``makenotion.com`` for "Notion"
#: — would vary two things at once, and is filed as its own issue rather than
#: smuggled in here.
_IN_HOUSE_SENDERS: tuple[str, ...] = (
    "careers@{t}.example",
    "recruiting@{t}.example",
    "talent@{t}.example",
    "no-reply@{t}.example",
    "jobs@{t}.example",
)

#: The acknowledgements the owner received from an employer's own mail system.
_IN_HOUSE_CONFIRMATIONS = observed.in_house(observed.OBSERVED_CONFIRMATIONS)


def _observed_confirmations_in_house(b: _Builder, n: int) -> None:
    """Real acknowledgements delivered from the sender that actually sent them.

    ``observed.py`` records, per template, where the message came from, and ten
    of the twenty-three acknowledgements say ``in-house`` — the employer's own
    mail system, not an ATS relay. Every family above hands all twenty-three to
    ``b.ats(i)``. So the corpus's only non-circular evidence arrived over a
    sender it never had, and ``rules.classify``'s +0.05 relay bonus was applied
    to every one of them.

    WHAT THAT ERASED. #523 reports a production message held at ``applied``
    0.80 — one point of score under the 0.90 rung, and no relay bonus to carry
    it over ``AUTO_FILE_GATE``. Measured before this family existed, across
    19,220 cases: the base-0.80 rung holds 816 verdicts, 806 of them from a
    relay and auto-filed, 10 from an employer's own domain and held. All ten
    were ``outreach-autoresponder``, whose own docstring says every wording in
    it is synthetic. The corpus could neither justify nor refuse a fix, and
    two issues (#523, #448) recorded "the shape has zero witnesses" as though
    that were a fact about mail rather than about this generator.

    THE WITNESS IS ONE TEMPLATE AND IT IS NAMED. Scored under both sender
    classes, exactly one of the thirty-six observed templates changes side of
    the gate: ``OBSERVED_CONFIRMATIONS[6]``, provenance ``in-house, thread
    19ff97772e932c0f``, which is the transcription of the message #523 quotes.
    Relay 0.85 and files; in-house 0.80 and waits for a person. The other nine
    in-house acknowledgements score six or more and land at 0.90 either way,
    which is why this family is a THIN witness rather than a broad one and is
    described as one. It is not thin in the way that matters: the one wording
    it turns on is the one the owner actually received.

    WHAT IT DELIBERATELY DOES NOT CARRY. Four observed templates — one
    assessment, the closure, one pending notice and the not-an-application —
    score under ``REVIEW_FLOOR``. Over a relay, ``pipeline``'s ATS floor puts
    three of them in the review queue; from an employer's own domain they reach
    nothing at all. That is a second defect this generator hides and it is
    filed on its own rather than buried in a family about the ladder, because
    it needs a fix this issue has no answer for.

    Its relay twin is ``observed-confirmation`` (300 cases, the same twenty-
    three templates), so the pair is across families and not inside this one.
    The exact one-slot claim — identical rendered text, relay sender against
    in-house sender — is asserted against ``RulesClassifier`` directly in
    ``test_the_ladder_reads_margin_when_nothing_competes_523.py``, where it is
    exact and cannot be moved by anything the board does.
    """

    for i in range(n):
        display, token = b.employer()
        role = b.role(i)
        subject, body, _ = b.pick(_IN_HOUSE_CONFIRMATIONS)
        fill = {"display": display, "role": role, "req": f"R-{800000 + i}"}
        b.add(
            family="observed-confirmation-in-house",
            subject=subject.format(**fill),
            sender=b.pick(_IN_HOUSE_SENDERS).format(t=token.split()[0]),
            sender_name=f"{display} Recruiting",
            body=body.format(**fill),
            expected_category="applied",
            identity=f"{token}|{role}",
            employer=token,
            day=i % 60,
            note="a real acknowledgement, from the employer's own mail system",
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
    ("requisition-inside-the-bound", _requisition_inside_the_bound, 60),
    ("double-acknowledgement", _double_acknowledgement, 60),
    # 38 messages a group and 21 employers: 12 resolving cards, 8 refusals
    # with two sibling applications apiece, and the both-placements pair.
    # See ``_concatenated_post_names`` — and note the block comment above
    # ``one-thread-many-roles-in-the-queue``: appended LAST because the
    # builder shares one seeded RNG, so anywhere else re-draws every
    # employer, role and wording after it.
    ("concatenated-post-name", _concatenated_post_names, 20),
    # #641. Appended last for the reason stated two entries above — the builder
    # shares one seeded RNG — and it is the first family in this file whose
    # employer carries BOTH a named identity and an anonymous one. Nothing else
    # here could produce the composition the issue is about.
    ("anonymous-third-application", _anonymous_third_application, 60),
    # #522. Appended last for the reason three entries above states — the
    # builder shares one seeded RNG — and it is the first family here whose
    # refusals carry a REJECTION's whole vocabulary while being about a person
    # rather than an application. 120 messages: 60 refusals (``identity=None``)
    # and the 60 twins that keep them honest.
    ("eligibility-verification", _eligibility_verification, 120),
    # #521. Appended last for the reason four entries above states — the
    # builder shares one seeded RNG, so anywhere else re-draws every employer,
    # role and wording after it. 160 messages: 80 outreach/contact-form
    # autoresponders (`identity=None`) and the 80 genuine confirmations that
    # are one slot away from them. It is the first family here whose refusal
    # and its twin share a sender, a subject and an employer, which is what
    # makes it a control rather than two unrelated samples.
    ("outreach-autoresponder", _outreach_autoresponders, 160),
    # #614 and #630. Appended last for the reason every entry above states —
    # the builder shares one seeded RNG, so a family anywhere else re-draws
    # every employer, role and wording after it and the whole recorded run
    # moves at once. At the end, the delta is these four families and nothing
    # else, which is what made re-recording this file tractable.
    #
    # THEY ARE THE FIRST FAMILIES HERE THAT ARE NOT ONLY MAIL. Three of them
    # carry a user ACTION (`standing_instruction`) and one carries a second
    # MAILBOX (`user_slot`), because the states #614 and #630 are about cannot
    # be reached by delivering messages alone — which is precisely why the
    # corpus could not express either defect class.
    ("settled-suppresses-an-update", _settled_suppresses_an_update, 60),
    ("hand-dismissal-swallows-later-mail", _hand_dismissal_swallows_later_mail, 60),
    ("answered-then-more-mail", _answered_then_more_mail, 60),
    ("another-mailbox-cannot-settle-mine", _another_mailbox_cannot_settle_mine, 60),
    # #768. Appended last for the reason every entry above states — the
    # builder shares one seeded RNG, so a family anywhere else re-draws every
    # employer, role and wording after it and the whole recorded run moves at
    # once. 240 messages in 120 groups: each group seeds the reader's OWN live
    # card, then 60 groups add a third-party outcome (`identity=None`) and 60
    # add the reader's own, one slot away from it. It is the first family here
    # whose refusal and its twin differ by a single NOUN PHRASE inside an
    # otherwise character-identical message.
    ("someone-elses-outcome", _someone_elses_outcome, 120),
    # #523. Appended last for the reason every entry above states — the
    # builder shares one seeded RNG, so a family anywhere else re-draws every
    # employer, role and wording after it and the whole recorded run moves at
    # once. 200 messages over the ten acknowledgements `observed.py`
    # provenances `in-house`, delivered from the employer's own domain
    # instead of the ATS relay every other observed family hands them to.
    # It is the first family here whose subject and body are drawn from the
    # transcribed set while the SENDER is what it varies.
    ("observed-confirmation-in-house", _observed_confirmations_in_house, 200),
)


def _readable_text(case: Case) -> str:
    """Every character of one message a job title could be read out of.

    Subject, then the body as the server holds it — collapsed and cut at
    ``_READABLE_CHARS``. Lowered once here so the caller compares like with
    like.

    ``delivered`` IS DELIBERATELY ABSENT, and an earlier draft had it. It is
    what the CLASSIFIER reads; ``role_from_message`` is handed ``subject`` and
    the capped body and never sees it (``harness._item``). Including it did
    nothing visible — re-derived 2026-09-06 at the current size, ``delivered`` is a
    substring of ``body`` in all 18,200 cases and the flip count is 146 either
    way (the figure read 17,260 and is corrected rather than dated because the
    measurement was re-run, #828) — but it is
    ``body`` UNCAPPED, so it silently restored the 4,000 characters this
    function exists to cut off. A family whose only mention of a role sat past
    the cap, with no shorter sibling on the card, would have been called
    reachable for text the extractor structurally cannot reach: #533's own
    defect, moved from "never mentioned" to "mentioned past character 4,000".
    """

    return " ".join(
        (
            case.subject,
            " ".join(case.body.split())[:_READABLE_CHARS],
        )
    ).lower()


def _settle_role_reachability(cases: list[Case]) -> None:
    """A role no message on the card ever spells is not ground truth, it is a wish.

    THE SECOND DERIVATION SITE, and it has to be here rather than in
    ``Case.__post_init__`` for one reason: reachability is a property of the
    CARD, not of a message. ``update-joins-one-application`` sends an update
    that names no role onto a card the confirmation already titled, and judging
    that update alone would call a perfectly good title an invention. So the
    question is asked once per identity, over every message that shares it.

    WHAT IT FIXES (#533). The builder writes ``identity=f"{token}|{role}"`` for
    every case, drawing the role from ``ROLES`` — including for the
    ``observed-*`` families, which are transcriptions of real ATS wordings and
    plenty of them name no job at all. One says only "your details have been
    added to our database". Ground truth therefore asserted a title the product
    could not possibly know, and the correct behaviour — a blank card — was
    scored as a ROLE-MISSING defect.

    Measured at the recorded seed when #533 shipped: 146 identities over 227
    messages. RE-MEASURED FOR #544 AT 19,420 CASES: **260 identities over 341
    messages**, 81 of them pairs — ``observed-confirmation-in-house`` 94,
    ``observed-confirmation`` 65, ``observed-closure`` 36,
    ``observed-assessment`` 31, ``observed-pending`` 14,
    ``eligibility-verification`` 10, ``outreach-autoresponder`` 10. The growth is
    families added since, not new instances of a defect; the 81 pairs are the
    same 81. ``RECORDED_NO_ROLE`` in
    ``tests/test_a_role_less_identity_says_so_544.py`` is where that population
    is pinned, so this paragraph cannot go stale silently again.
    ``role_from_message`` returns ``None`` for all of them, so every one of those
    cards is blank today and the counter was punishing the product for being
    right.

    ``observed-rejection`` FLIPS NOTHING, and that is the check that says the
    rule is reading the mail rather than the family name: every one of its
    templates names the role, two of them in the subject alone. Its 44
    blank-titled cards are the honest half of ROLE-MISSING — mail that named a
    job the reader could not read — and a derivation that swept them up would
    have deleted the defect instead of the mis-statement.

    THE ISSUE PREDICTED 27 OF THEM WOULD FLIP, and following its measurement
    would have done exactly that damage. #533 reports 196 flips including
    ``observed-rejection`` 27; this rule finds 146 and rejection 0. The
    difference is the window: measured over the four candidate windows, three
    agree at 146 — ``subject`` + capped body (this rule), ``subject`` +
    ``delivered`` (what the issue PRESCRIBED), and ``subject`` + uncapped body —
    while ``delivered`` alone, with no subject, gives 166 and picks up 20
    rejection identities. The issue's number came from a window that could not
    see the subject, and rejection templates name the role there. Twenty real
    #485 defects, one window away from being deleted as ground-truth error.

    WHY IT MATTERS MORE THAN THE NUMBER. #533 calls this "ground truth that
    rewards guessing". An earlier draft of this docstring called that an
    overstatement, on the grounds that "no guess can match" a role drawn from an
    invented pool. That was itself wrong, and in the direction that flatters the
    fix: ``ROLES`` holds seventeen strings and every identity's role is one of
    them, so a guesser that printed the pool's most common title scored CORRECT
    on roughly one card in seventeen — and anything fitted on this corpus would
    do far better than that. The old truth was matchable, so #533's wording was
    closer to right than the correction.

    The real harm is that it set a target NO CORRECT BEHAVIOUR CAN REACH. 146 of
    the 213 could not be closed by any pattern, ever, because the text does not
    contain the answer — so a reader of the ledger sees a ranked table of
    "misses" whose largest families are unfixable, and the only way to move the
    number is to make the extractor guess, which the neighbouring counter then
    punishes. A ledger that points at work which cannot succeed is worse than a
    number that is merely wrong, and this one is published.

    The card is not skipped afterwards. ``names_no_role`` asserts the blank,
    which is the #540 lesson: "the mail names no role" is a claim, and a claim
    can fail. What used to be 146 cards scored as defects becomes 146 cards
    asserted to be blank.

    THE KEY LOSES THE ROLE TOO, SINCE #544, and this paragraph used to say the
    opposite. It read "KNOWN AND NOT FIXED HERE: the identity key still reads
    ``employer|Machine Learning Engineer``" — true when #533 shipped, and false
    from the moment the collapse below landed. 81 of these identities hold two
    messages, none of them threaded, so what joined each pair was employer plus
    an EMPTY role token: the identity assertion passed for a reason unrelated to
    what it stated, and the day the extractor reads a role out of one of the two
    the pair splits while the key that was meant to predict it had been
    describing something else. The key is the sentinel now and the flag is read
    off it.
    """

    by_identity: dict[str, list[Case]] = {}
    for case in cases:
        if case.identity is not None and case.role_truth is not None:
            by_identity.setdefault(case.identity, []).append(case)

    keys = {case.identity for case in cases if case.identity is not None}
    for identity, group in by_identity.items():
        role = " ".join(group[0].role_truth.split()).lower()
        if any(role in _readable_text(case) for case in group):
            continue
        # THE KEY LOSES THE ROLE TOO (#544). Nulling ``role_truth`` and leaving
        # the identity reading `marshburyshore|Software Development Engineer I`
        # for mail whose entire text is "your details have been added to our
        # database" left the corpus asserting one thing and grading another.
        # ``identity`` is not decoration: it is ground truth for SPLIT and
        # MERGE, so two cases sharing it MUST land on one card and two with
        # different keys MUST NOT. 81 of these identities hold two messages,
        # none of them threaded, so what actually joined those pairs was
        # employer plus an EMPTY role token — the assertion passed for a reason
        # unrelated to what it stated, and the day the extractor learned to read
        # a role out of one of the two, the pair would split while the key that
        # was supposed to predict it had been describing something else.
        #
        # ``__norole__`` is the spelling the sentinel families already use
        # (`__apply0__`, `__third__`, `__submission__`), and #544's own text
        # proposed `__noRole__`, which ``_ROLE_SENTINEL`` — `^__[a-z0-9]+__$` —
        # does not match. A sub-key that matched no sentinel would set neither
        # ``role_truth`` nor ``names_no_role``, which is the 960-card hole the
        # empty-sub-key guard above refuses by name.
        token = identity.partition("|")[0]
        collapsed = f"{token}|__norole__"
        if collapsed in keys and collapsed != identity:
            # A MERGE, NOT A RENAME, and it must not happen quietly. Two
            # distinct applications at one employer collapsing onto one key
            # would assert that the product must put them on ONE card — a
            # ground-truth claim nobody wrote, arriving as a side effect of a
            # role being unreadable. Measured at seed 20260822 this cannot
            # fire: 0 of the 260 identities the rule touches shares an employer
            # token with any other identity, touched or not. It is refused
            # rather than left to become reachable when a family is added.
            raise ValueError(
                f"collapsing {identity!r} to {collapsed!r} would merge it with "
                f"an identity that already exists. Two applications at one "
                f"employer would then be asserted to share a card because "
                f"neither message spelled its role — a claim no family made."
            )
        keys.discard(identity)
        keys.add(collapsed)
        for case in group:
            # ``object.__setattr__`` because ``Case`` is frozen and because
            # ``dataclasses.replace`` would re-run ``__post_init__``, whose
            # guard refuses a PASSED ``names_no_role`` — correctly. This is a
            # derivation, the same as the guard's own branch; the guard exists
            # to stop a BUILDER asserting it, and no builder can reach here.
            object.__setattr__(case, "identity", collapsed)
            object.__setattr__(case, "role_truth", None)
            # DERIVED FROM THE KEY THIS PASS JUST WROTE, exactly as
            # ``__post_init__`` derives it for every family that spells a
            # sentinel by hand. After #544 there is one definition of "this mail
            # names no job" — the sub-key — and this pass makes the key true
            # rather than working around it being false.
            #
            # THE SUB-KEY IS READ, NOT SPELLED AGAIN. A first draft wrote
            # ``_ROLE_SENTINEL.match("__norole__")``, which is a constant
            # dressed as a derivation: it says nothing about the value actually
            # stored, and under the one perturbation it responds to — a
            # ``_ROLE_SENTINEL`` that stops matching this spelling — it would
            # write ``False`` for every case while the gate comparing flag to
            # sub-key stayed green, because both sides move together. Reading
            # ``collapsed`` is what makes the line true to its own comment.
            object.__setattr__(
                case,
                "names_no_role",
                bool(_ROLE_SENTINEL.match(collapsed.partition("|")[2])),
            )


def generate(seed: int = 20260822) -> list[Case]:
    """Build the corpus. Deterministic: same seed, byte-identical output."""

    b = _Builder(seed)
    for _name, family, n in _FAMILIES:
        family(b, n)
    _settle_role_reachability(b.cases)
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

    GROUND TRUTH IS PART OF THE CORPUS, and it was outside this hash until
    #533. The digest covered the mail — subject, body, delivered, identity —
    and not what the product is supposed to DO with it, so ``joins``,
    ``card_status``, ``role_truth`` and ``names_no_role`` could all be rewritten
    with the tripwire staying green. A corpus whose expectations moved silently
    is exactly what a determinism gate is for; the fields are in now, and the
    cost is that a truth-only edit re-records the digest, which is the point
    rather than the price.
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
                    c.joins or "",
                    c.card_status or "",
                    c.role_truth or "",
                    str(c.names_no_role),
                    # WHICH MAILBOX and WHAT THE USER DID are part of the
                    # corpus, not decoration on it: a case that moved to the
                    # other mailbox, or lost its dismissal, is different mail
                    # asserting a different thing. Outside this hash they could
                    # both be rewritten with the determinism gate green — the
                    # hole #533 closed for `joins` and `card_status`.
                    str(c.user_slot),
                    c.standing_instruction or "",
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
