"""Run the corpus through the WHOLE product and score what ends up on the board.

Two scores, because a message can pass one and fail the other and the product
only works when it passes both:

**Classification.** ``RulesClassifier.classify`` over what production would
actually hand it — ``extract_body_text(payload) or snippet``, expressed here as
each case's ``delivered`` field. Scored three ways rather than two: CORRECT,
WRONG (a confident verdict that is not the right one), and ABSTAINED (below
``REVIEW_FLOOR``, so the product says nothing). Abstention is the safe failure
and must not be averaged into the same number as being confidently wrong.

**The board.** The classified messages are fed through the real
``roll_up_applications`` / ``collect_review_items`` and the real
``upsert_applications_for_user`` against a real session, IN DAY-SIZED BATCHES —
which is what an incremental sync is. Then the board is read back out of the
``applications`` and ``emails`` tables and compared to ground truth.

WHY BATCHES OF A DAY. A sync rolls up whatever arrived since the last one. One
message at a time would be 10,040 syncs and is not what happens; the whole
mailbox at once is a rebuild and hides every defect that only appears in a
delta — which is exactly how a fix shipped on 2026-08-21 that worked on a
rebuild and did nothing on the syncs that run. A day is the honest middle and
the one the corpus's dates are built for.

Board failure modes, scored per MESSAGE against ground truth rather than by
per-employer cardinality, because "2 cards where 2 were expected" is satisfied
even when both messages sit on the wrong cards:

* **SPLIT** — one ground-truth application over more than one card. Counted as
  extra cards, so a three-way split scores 2.
* **MERGE** — one card holding more than one ground-truth application. The
  strictly worse failure: it destroys a record silently, and a rejection landing
  on the wrong one of four cards settles a live application terminally.
* **NOISE ON A CARD** — mail that must never become an application, on one.
* **SHOULD HAVE GONE TO REVIEW** — role-less mail at a multi-application
  employer that got guessed onto a card instead of being asked about.
* **UPDATE OPENED A CARD** — a message that must join an existing application
  (``Case.joins``) that landed on a DIFFERENT card. This overlaps SPLIT and
  MERGE by construction and is scored anyway, because those name a SHAPE and
  this names a DIAGNOSIS: what a user reports is "a second Google appeared",
  and the ranked table should say which message opened it.

  An update that lands in the REVIEW QUEUE instead is not this. The pipeline
  was not confident enough to file it and asked, which is the designed answer
  and the one the product is built around: below the gate, a human decides.
  It is counted as ``update_held_for_review`` so the number is visible, and
  kept out of ``total`` so designed behaviour cannot read as failure.
* **LOST** — a message about a real application that reached NOTHING. No card,
  no review queue, no counter. This is the defect that cost four Microsoft
  applications on 2026-08-21, and from the product's side it is
  indistinguishable from a quiet mailbox.
* **DROPPED** — a lifecycle verdict under the review floor. Also not addressed,
  but the product NAMES it (``pipeline.DroppedVerdict``), so a person can find
  out. Counted separately from LOST for exactly that reason: one of these is
  invisible and the other is merely bad.

``expect_review`` cases are scored in their own bucket: being unplaceable is the
DESIGNED answer there, and counting designed behaviour as failure would swamp
the table.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlmodel import select

from jobtracker.classifier.rules import RulesClassifier
from jobtracker.cloud import pipeline
from jobtracker.database.models import EmailCategory
from jobtracker.cloud.applications import (
    Application,
    Email,
    _persist_review_items,
    employers_with_several_applications,
    threads_naming_one_application,
    upsert_applications_for_user,
)

from .generate import Case, snippet_of

_USER = uuid.UUID("00000000-0000-0000-0000-00000000c0de")

#: One classifier for the whole run. Constructing it per message would dominate
#: the wall clock and measure nothing.
_CLASSIFIER = RulesClassifier()

CORRECT, WRONG, ABSTAINED = "correct", "wrong", "abstained"


@dataclass(frozen=True)
class Verdict:
    case: Case
    category: str
    confidence: float
    bucket: str
    auto_filed: bool


def classify_all(cases: list[Case]) -> list[Verdict]:
    """The classifier's answer for every message, as production would get it."""

    out: list[Verdict] = []
    for case in cases:
        result = _CLASSIFIER.classify(case.subject, case.delivered, case.sender)
        category = result.category.value
        confidence = result.confidence
        # NOISE IS SCORED ON ITS CONTRACT, NOT ITS LABEL. For mail that must
        # never become an application (``identity is None``), the product's job
        # is to do nothing, and saying nothing IS doing nothing — an abstention
        # below ``REVIEW_FLOOR`` and a confident ``other`` are the same correct
        # outcome from the user's side. Scoring the abstention as neither right
        # nor wrong put 700 messages the product handles perfectly into a
        # neutral bucket and understated accuracy by seven points.
        #
        # The strict half is still checked, and by the half that can see it:
        # whether any of this mail reached a card is the BOARD score's
        # NOISE-ON-CARD, which is where a failure here would actually hurt.
        # Keyed on the EXPECTED CATEGORY, not on ``identity is None``. Those are
        # different claims and conflating them cost 200 false failures: a bare
        # ATS relay carries a genuine confirmation and ``applied`` is the right
        # verdict for it — what it cannot do is name an employer, which is a
        # BOARD question and is scored as one.
        if case.expected_category == "other":
            bucket = (
                CORRECT
                if confidence < pipeline.REVIEW_FLOOR or category == "other"
                else WRONG
            )
        elif confidence < pipeline.REVIEW_FLOOR:
            bucket = ABSTAINED
        elif category == case.expected_category:
            bucket = CORRECT
        else:
            bucket = WRONG
        out.append(
            Verdict(
                case=case,
                category=category,
                confidence=confidence,
                bucket=bucket,
                auto_filed=confidence >= pipeline.AUTO_FILE_GATE,
            )
        )
    return out


@dataclass
class ClassifierScore:
    total: int = 0
    correct: int = 0
    wrong: int = 0
    abstained: int = 0
    auto_filed: int = 0
    auto_filed_wrong: int = 0
    by_family: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0


def score_classifier(verdicts: list[Verdict]) -> ClassifierScore:
    score = ClassifierScore(total=len(verdicts))
    for v in verdicts:
        setattr(score, v.bucket, getattr(score, v.bucket) + 1)
        score.by_family[v.case.family][v.bucket] += 1
        if v.auto_filed:
            score.auto_filed += 1
            if v.bucket == WRONG:
                score.auto_filed_wrong += 1
                score.by_family[v.case.family]["auto_filed_wrong"] += 1
    return score


# ── the board ────────────────────────────────────────────────────────────────


#: What the reader can actually derive an identity FROM, character for
#: character with production. ``gmail_client._extract_body`` ends
#: ``_WHITESPACE.sub(" ", text)[:_MAX_BODY_CHARS]``, so every whitespace run is
#: one space and nothing past 4,000 characters exists as far as the server is
#: concerned.
#:
#: BOTH HALVES WERE MEASURED BEFORE BEING COPIED HERE, because a cap nobody
#: checks is decoration. Collapsing changes the identity of **0** of 17,260
#: cases — the generator never splits a role phrase across a line — while the
#: cap changes **160**, every one of them in ``verdict-past-the-body-cap``,
#: the family named for it.
#:
#: The classifier in this harness still reads the UNCAPPED ``delivered``, which
#: is a separate instrument defect and is filed rather than fixed here: that
#: family builds a 7,351-character body with its verdict at ~7,261 to test what
#: happens when the verdict is out of reach, and hands the classifier all 7,351.
#: Correcting it moves classifier numbers, not identity ones, and belongs with
#: its own re-record.
_MAX_BODY_CHARS = 4000


def _readable(case: Case) -> str:
    """The message body as the server would hold it."""

    return " ".join(case.body.split())[:_MAX_BODY_CHARS]


def _item(v: Verdict) -> pipeline.PipelineItem:
    """A verdict as the pipeline receives it.

    The CLASSIFIER's category and confidence, never the ground truth: feeding
    the expected category here would measure the identity layer over a mailbox
    the product never sees, and every number would be optimistic by exactly the
    classifier's error rate.

    ``snippet`` IS THE SAME ARGUMENT, one field along, and it was wrong until
    2026-08-23. This used to pass ``v.case.delivered`` — the text that reaches
    ``classify()``, which for most families is the FULL BODY. Production never
    does that. ``_classify_messages`` hands the classifier the body and hands
    the ``PipelineItem`` ``msg.snippet``, so identity resolution sees Gmail's
    own ~200 characters and nothing more; every ``emails`` row in the live
    database has ``body_text IS NULL`` and a ``body_snippet`` between 182 and
    201 characters long.

    Measured on the day it was corrected: **723 of 17,260 cases resolved to a
    different application identity** under a production-shaped snippet, 699 of
    them losing identity entirely and none gaining it. So the instrument was
    uniformly more generous than the product, and a family written to prove
    "identity survives when the role is only in the body" passed before any
    such fix existed. That is the defect shape this repository keeps finding,
    and the corpus was carrying it.

    The classifier still reads ``delivered``. Only identity is narrowed, and it
    is narrowed to exactly what production stores.
    """

    return pipeline.PipelineItem(
        message_id=v.case.message_id,
        thread_id=v.case.thread_id,
        subject=v.case.subject,
        sender_email=v.case.sender,
        sender_name=v.case.sender_name,
        received_at=v.case.received_at,
        category=v.category,
        confidence=v.confidence,
        snippet=snippet_of(v.case.body),
        # WHAT THE READER DERIVED, from the same text it handed the classifier.
        # ``_classify_messages`` does exactly this, on the body Gmail returned,
        # and stores the result — which is what lets identity resolution see a
        # title printed past the snippet without any of the text following it
        # downstream. ``""`` and not ``None`` when nothing is named: None means
        # "never derived" and would send the pipeline back to the snippet, which
        # is the relay path's behaviour and not this one's.
        identity_role=pipeline.role_from_message(v.case.subject, _readable(v.case))
        or "",
        identity_req_id=pipeline.extract_req_id(v.case.subject, _readable(v.case))
        or "",
    )


@dataclass
class Replay:
    """Where every message ended up, which is the whole question.

    ``groups`` alone cannot answer "was this mail addressed?" — a message that
    is on no card is either in the queue waiting for a person, dropped under
    the review floor with a counter naming it, or gone. Those are three
    different products from the user's side and the first version of this
    harness could not tell them apart, because it never ran the review path at
    all.
    """

    groups: list[tuple[str, list[str]]]
    reviewed: set[str]
    dropped: set[str]
    #: card label -> the stage the board shows for it.
    status: dict[str, str]


async def replay(session, verdicts: list[Verdict]) -> Replay:
    """Sync the corpus in day-sized batches; return where everything landed.

    The WHOLE sync, not just the rollup: ``collect_review_items`` and
    ``_persist_review_items`` run too, and the dropped verdicts are collected.
    Skipping them was not a shortcut, it was a blind spot — the queue is where
    a message goes when the product is honest about not knowing, and a harness
    that cannot see the queue scores that as the same outcome as losing the
    message.
    """

    by_day: dict[int, list[Verdict]] = defaultdict(list)
    for v in verdicts:
        by_day[v.case.received_at.toordinal()].append(v)

    dropped: set[str] = set()
    for day in sorted(by_day):
        batch = [_item(v) for v in by_day[day]]
        known_multi = await employers_with_several_applications(session, _USER)
        known_threads = await threads_naming_one_application(session, _USER)
        rolled = pipeline.roll_up_applications(batch, known_multi, known_threads)
        fell_out: list[pipeline.DroppedVerdict] = []
        review = pipeline.collect_review_items(
            batch, fell_out, known_multi, known_threads
        )
        dropped.update(d.message_id for d in fell_out)
        if rolled:
            await upsert_applications_for_user(session, _USER, rolled)
        if review:
            await _persist_review_items(session, _USER, review)
        if rolled or review:
            await session.commit()

    rows = (
        await session.exec(
            select(Application)
            .where(Application.user_id == _USER)
            .order_by(Application.id)
        )
    ).all()
    emails = (
        await session.exec(
            select(Email).where(
                Email.user_id == _USER, Email.application_id.is_not(None)
            )
        )
    ).all()
    filed: dict[int, list[str]] = defaultdict(list)
    for e in emails:
        filed[e.application_id].append(e.message_id)
    # THE REVIEW QUEUE, by the predicate the product itself uses.
    #
    # ``GET /applications/summary`` and ``GET /applications/review`` both filter
    # on all three of these (``applications.py``), and getting it wrong here is
    # not neutral: a looser predicate counts any unlinked row as "the user was
    # asked about it", which makes LOST an undercount and errs toward the gate
    # passing. The first version of this read ``application_id IS NULL`` alone
    # and claimed in a comment to match the product. It did not.
    queued = (
        await session.exec(
            select(Email.message_id).where(
                Email.user_id == _USER,
                Email.application_id.is_(None),
                Email.classified_as == EmailCategory.NEEDS_REVIEW,
                Email.is_reviewed == False,  # noqa: E712 — SQL boolean
            )
        )
    ).all()
    # A dismissed row is not on the board; counting one would report a card the
    # user cannot see.
    live = [r for r in rows if r.dismissed_at is None]
    return Replay(
        groups=[
            (f"row{r.id}:{r.company}", sorted(filed.get(r.id, []))) for r in live
        ],
        reviewed=set(queued),
        dropped=dropped,
        status={
            f"row{r.id}:{r.company}": getattr(r.status, "value", str(r.status))
            for r in live
        },
    )


@dataclass
class Failure:
    mode: str
    family: str
    detail: str
    message_ids: tuple[str, ...] = ()


@dataclass
class BoardScore:
    cards: int = 0
    splits: int = 0
    merges: int = 0
    noise_on_card: int = 0
    wrong_review: int = 0
    #: An update that landed on a DIFFERENT card from the one it belongs to.
    update_opened_a_card: int = 0
    #: An update the product was not confident enough to file, sitting in the
    #: review queue. THE DESIGNED ANSWER, not a failure — counted so it is
    #: visible rather than invisible, and excluded from ``total``.
    update_held_for_review: int = 0
    #: The right card, showing the wrong stage.
    wrong_status: int = 0
    #: About a real application and reached nothing at all.
    lost: int = 0
    #: About a real application and dropped under the review floor. Counted by
    #: the product, so recoverable by a person who goes looking.
    dropped: int = 0
    failures: list[Failure] = field(default_factory=list)

    @property
    def total(self) -> int:
        """Failures only. ``update_held_for_review`` is deliberately absent:
        it is the designed answer, and a score that counts it as a defect
        rewards a product that guesses over one that asks."""

        return (
            self.splits
            + self.merges
            + self.noise_on_card
            + self.wrong_review
            + self.update_opened_a_card
            + self.wrong_status
            + self.lost
            + self.dropped
        )

    @property
    def unaddressed(self) -> int:
        """Mail about a real application that the product did nothing with.

        The user's requirement in one number: "all the mails regarding the
        application in the gmail is addressed in the app". Both halves count —
        a named drop is still a message that never reached a screen.
        """

        return self.lost + self.dropped


def score_board(
    replayed: Replay, cases: list[Case]
) -> BoardScore:
    groups = replayed.groups
    by_mid = {c.message_id: c for c in cases}
    score = BoardScore(cards=len(groups))

    ident_cards: dict[str, set[str]] = defaultdict(set)
    for label, mids in groups:
        for mid in mids:
            case = by_mid.get(mid)
            if case is not None and case.identity is not None:
                ident_cards[case.identity].add(label)

    for ident, labels in sorted(ident_cards.items()):
        if len(labels) > 1:
            example = next(c for c in cases if c.identity == ident)
            score.splits += len(labels) - 1
            score.failures.append(
                Failure(
                    mode="SPLIT",
                    family=example.family,
                    detail=f"one application over {len(labels)} cards",
                    message_ids=tuple(
                        sorted(c.message_id for c in cases if c.identity == ident)
                    ),
                )
            )

    for label, mids in groups:
        idents = {
            by_mid[m].identity
            for m in mids
            if m in by_mid and by_mid[m].identity is not None
        }
        if len(idents) > 1:
            family = by_mid[mids[0]].family if mids and mids[0] in by_mid else "?"
            score.merges += len(idents) - 1
            score.failures.append(
                Failure(
                    mode="MERGE",
                    family=family,
                    detail=f"card {label!r} holds {len(idents)} applications",
                    message_ids=tuple(mids),
                )
            )
        noise = [
            m
            for m in mids
            if m in by_mid and by_mid[m].identity is None and not by_mid[m].expect_review
        ]
        if noise:
            score.noise_on_card += len(noise)
            score.failures.append(
                Failure(
                    mode="NOISE-ON-CARD",
                    family=by_mid[noise[0]].family,
                    detail=f"{len(noise)} message(s) that must mint nothing landed on {label!r}",
                    message_ids=tuple(noise),
                )
            )

    on_a_card = {m for _label, mids in groups for m in mids}
    card_of = {m: label for label, mids in groups for m in mids}

    # ── if it is an update, it updates the existing card ─────────────────────
    #
    # Three outcomes and only one is a failure, which is the distinction the
    # product's own design turns on:
    #
    #   same card                    correct
    #   in the review queue          DESIGNED — the pipeline was not confident
    #                                enough to file, and asking beats guessing.
    #                                Counted, and kept out of `total`.
    #   a different card             FAILURE. This is the one that destroys a
    #                                record: a rejection on a sibling settles a
    #                                live application terminally.
    #
    # Reaching NOTHING is not scored here at all — it is LOST below, where it
    # belongs, and counting it twice would let one defect read as two.
    for case in cases:
        if case.joins is None:
            continue
        here, there = card_of.get(case.message_id), card_of.get(case.joins)
        if here is not None and here == there:
            continue
        if case.message_id in replayed.reviewed or case.joins in replayed.reviewed:
            score.update_held_for_review += 1
            # Recorded as a Failure so ``rank`` can show WHICH families are
            # being held, and excluded from ``total`` by ``BoardScore`` rather
            # than by not existing. A designed outcome that leaves no trace is
            # a designed outcome nobody can audit.
            score.failures.append(
                Failure(
                    mode="UPDATE-HELD",
                    family=case.family,
                    detail="under the auto-file gate, so the product asked",
                    message_ids=(case.joins, case.message_id),
                )
            )
            continue
        if here is None or there is None:
            continue  # LOST, and counted there
        score.update_opened_a_card += 1
        score.failures.append(
            Failure(
                mode="UPDATE-OPENED-A-CARD",
                family=case.family,
                detail=f"belongs on {there!r}, landed on {here!r}",
                message_ids=(case.joins, case.message_id),
            )
        )

    # ── and the card SAYS so ─────────────────────────────────────────────────
    #
    # Landing on the right card is necessary and not sufficient. A rejection
    # that files onto the right row and leaves it reading `applied` has updated
    # nothing the user can see, and this is the half of "updates the existing
    # card" that a message-to-card mapping cannot express.
    for case in cases:
        if case.card_status is None:
            continue
        if case.message_id in replayed.reviewed:
            # HELD FOR A PERSON, so it has not been filed, so it cannot have
            # moved the stage. Asserting a stage here asserts that an unfiled
            # message changed the board, which is the opposite of what the
            # review queue is for. Measured: 77 offers arriving before their
            # confirmation sat in the queue at 0.75 while the card correctly
            # read `applied`, and scoring that as WRONG-STAGE would have made
            # the designed answer look like a defect for the second time.
            continue
        label = card_of.get(case.message_id)
        if label is None:
            continue  # already counted as UPDATE-REACHED-NO-CARD or LOST
        actual = replayed.status.get(label)
        if actual == case.card_status:
            continue
        score.wrong_status += 1
        score.failures.append(
            Failure(
                mode="WRONG-STAGE",
                family=case.family,
                detail=f"card {label!r} reads {actual!r}, must read {case.card_status!r}",
                message_ids=(case.message_id,),
            )
        )

    # ── every application mail is addressed ──────────────────────────────────
    for case in cases:
        if not case.must_be_addressed:
            continue
        if case.message_id in on_a_card or case.message_id in replayed.reviewed:
            continue
        named = case.message_id in replayed.dropped
        if named:
            score.dropped += 1
        else:
            score.lost += 1
        score.failures.append(
            Failure(
                mode="DROPPED" if named else "LOST",
                family=case.family,
                detail=(
                    "under the review floor; counted by the product but on no screen"
                    if named
                    else "no card, no queue, no counter — indistinguishable from a quiet mailbox"
                ),
                message_ids=(case.message_id,),
            )
        )

    for case in cases:
        if case.expect_review and case.message_id in on_a_card:
            score.wrong_review += 1
            score.failures.append(
                Failure(
                    mode="SHOULD-HAVE-GONE-TO-REVIEW",
                    family=case.family,
                    detail="role-less mail at a multi-application employer was guessed onto a card",
                    message_ids=(case.message_id,),
                )
            )
    return score


def rank(score: BoardScore) -> list[tuple[str, str, int]]:
    tally: Counter[tuple[str, str]] = Counter()
    for f in score.failures:
        weight = max(1, len(f.message_ids) - 1) if f.mode != "SHOULD-HAVE-GONE-TO-REVIEW" else 1
        tally[(f.mode, f.family)] += weight
    return [(mode, family, n) for (mode, family), n in tally.most_common()]
