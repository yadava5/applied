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
* **SUPPRESSED AS SETTLED** — offered to the review queue and refused by
  ``_persist_review_items_additive``, because the sync had already settled this
  message's (thread, application). Reaching NOTHING for a designed reason is
  still a different thing from reaching nothing, so it gets its own bucket and
  stays out of ``total``. It reads 0 on this corpus; see ``BoardScore``.

* **WRONG COMPANY / WRONG ROLE** — the card holds the right mail and is NAMED
  after something else. Everything above this line is about which messages
  ended up together; these two are about the two fields a user actually reads,
  and until #487 nothing here compared them at all. The proof is PR #486: it
  turned 44 blank roles into correct ones and moved not one recorded number,
  because gaining a title changes a card's NAME and not its partition. Both
  carry a DENOMINATOR (``titles_graded``, ``roles_graded``) for the reason a
  zero needs one — a grader that graded nothing would report a perfect board.

  Two near neighbours are reported and kept OUT of ``total``, because
  collapsing them into the counters above would make a cosmetic difference and
  an absence read as a wrong record: **COMPANY-DRIFT**, the same employer
  spelled differently ("Arcgrove" for "Arcgrove Systems", which is the leading
  word the resolver keeps on purpose), and **ROLE-MISSING**, a blank title
  where the mail named a job. That last sentence was not true until #533: 146
  cards were counted here for mail that named no job at all, because ground
  truth had been handed a role the message never contained. They are asserted
  as blank now, which is what makes the definition above the definition.

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
    _not_filed_on_an_application_that_answers,
    classify_review_item,
    employers_with_several_applications,
    reconcile_orphaned_classifications,
    sync_gmail_pipeline_additive,
    threads_naming_one_application,
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
#: character with production — because it now CALLS production's own
#: normalisation instead of restating it.
#:
#: IT USED TO RESTATE IT, and #430 is what that cost. This said
#: ``gmail_client._extract_body`` ends ``_WHITESPACE.sub(" ", text)[:_MAX_BODY_CHARS]``
#: and derived ``" ".join(case.body.split())`` to match. When the extractor
#: stopped collapsing newlines — it had to, because the classifier's quote
#: boundary is ``^``-anchored and a one-line body disabled it — this file went
#: on collapsing them, and the sentence above became a false claim about
#: production inside the one file whose whole purpose is parity. Nothing could
#: have caught it: a hand-copied mirror has no gate, which is exactly why the
#: normalisation is a named function now.
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
#:
#: IMPORTED RATHER THAN COPIED, since 2026-08-27. It was hand-written as 4000
#: here — a THIRD copy of a number that also lives in the product and in
#: ``generate._READABLE_CHARS`` — and nothing pinned it. The corpus's
#: independence doctrine is about GROUND TRUTH, not about plumbing, and this
#: file already imports ``pipeline.role_from_message`` wholesale; hand-copying
#: the size of that function's input window buys no independence and one way to
#: drift. If it drifted, the harness would feed the extractor a different window
#: than both the product and the ground-truth derivation assume, and every role
#: counter would be quietly wrong.
#:
#: THE CAP IS NO LONGER NAMED HERE AT ALL, which is the same argument carried
#: one step further: ``normalise_body_text`` applies it, so the harness borrows
#: the window and the whitespace rule together and cannot hold a right answer
#: about one and a stale answer about the other.
from jobtracker.cloud.gmail_client import normalise_body_text  # noqa: E402


def _readable(case: Case) -> str:
    """The message body as the server would hold it. Production's own function."""

    return normalise_body_text(case.body)


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
class SyncTotals:
    """``MergeResult`` summed over the day-batches, which nothing here could see.

    ``sync_gmail_pipeline_additive`` returns what each sync DID — rows created,
    rows advanced, rows taken off the board, items surfaced to the queue — and
    the hand-assembled loop this replaced never called it, so those five numbers
    existed only in production. They are not a second reading of the board: the
    board says what is there NOW, and these say how it got there. A rebuild and
    a steady accumulation can leave the same board.

    ``purged`` is ``len(MergeResult.removed)`` by construction, so only one of
    the two is kept; carrying both would be a pair that cannot disagree.
    """

    #: Day-batches handed to the sync. Every day, including one whose mail rolls
    #: up to nothing — that is a sync a user really makes, and it is where the
    #: per-batch catch-up and the emptied-row dismissal get their chance.
    syncs: int = 0
    created: int = 0
    updated: int = 0
    purged: int = 0
    needs_review: int = 0

    def add(self, result) -> None:
        self.syncs += 1
        self.created += result.created
        self.updated += result.updated
        self.purged += result.purged
        self.needs_review += result.needs_review


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
    #: Offered to the review queue and REFUSED a row by the additive persist,
    #: which is a fourth outcome and had nowhere to go until the harness started
    #: calling that function (#624). Observed rather than re-derived: the ids the
    #: sync handed :func:`_persist_review_items_additive`, minus the ids the
    #: database holds a row for afterwards. Spelling the settled predicate out
    #: here a second time would make this a copy of the thing it is measuring.
    suppressed: set[str]
    #: What the syncs REPORTED, summed. See :class:`SyncTotals`.
    synced: SyncTotals
    #: card label -> the stage the board shows for it.
    status: dict[str, str]
    #: card label -> the two fields a user actually READS on the card:
    #: ``(company, position)``, exactly as stored. Carried separately from the
    #: label because the label is an identity for the harness's own bookkeeping
    #: and comparing it to ground truth would compare an id, not a title.
    title: dict[str, tuple[str, str]]
    #: message id -> the CATEGORY the classifier returned for it. Carried so the
    #: board score can say which of three mechanisms held an update, which the
    #: groups and the queue cannot distinguish on their own: an `offer` the
    #: auto-file gate would not clear and an `other` floored into the queue by
    #: ``references_an_application`` are the same membership of ``reviewed`` and
    #: two different issues (#448 against #417). Defaulted, so the hand-built
    #: ``Replay``s in the unit tests below keep working; an update with no
    #: recorded verdict falls to the non-offer bucket and the SUM — which is all
    #: those fixtures read — is unaffected.
    verdict: dict[str, str] = field(default_factory=dict)


async def _stored(session, message_ids: list[str]) -> set[str]:
    """Which of these messages the database holds a row for, right now."""

    return set(
        (
            await session.exec(
                select(Email.message_id).where(
                    Email.user_id == _USER, Email.message_id.in_(message_ids)
                )
            )
        ).all()
    )


async def replay(session, verdicts: list[Verdict]) -> Replay:
    """Sync the corpus in day-sized batches, through the real additive sync.

    ONE ENTRYPOINT OF TWO, NAMED, because "the WHOLE sync" is what this
    docstring used to claim and it was not true (#624). Each day-batch is handed
    to ``sync_gmail_pipeline_additive`` whole — the function the ROUTINE and AUTO
    syncs call, which is the dashboard's connect-time backfill and the inbox
    relay. So ``upsert_applications_for_user``, the per-batch
    ``reconcile_orphaned_classifications``, ``_dismiss_rows_left_without_mail``
    (reached through the upsert), ``_persist_review_items_additive`` with its
    cross-sync settled test and ``settled_applications`` suppression, and the
    ``MergeResult`` accounting all run here exactly as they run for a user.

    NOT CROSSED, and this is the half a passing gate does not cover:
    ``purge_and_rebuild_gmail_pipeline``, the explicit "Re-sync" button. It
    removes AUTO rows a scan contradicts, calls ``_reset_review_queue``, and
    persists review items through ``_persist_review_items`` unfiltered. None of
    that is exercised by this harness at any seed. Crossing one entrypoint is
    progress, not coverage of both.

    THE DAY BATCH IS THE HARNESS'S CHOICE, not the product's. A real sync rolls
    up whatever arrived since the last cursor; a day is the honest middle
    between one-message-at-a-time (10,040 syncs, which is not what happens) and
    the whole mailbox at once (a rebuild, which hides every delta-only defect).
    See the module docstring.

    The rollup, ``collect_review_items`` and the dropped verdicts run and are
    collected. Skipping them was not a shortcut, it was a blind spot — the queue
    is where a message goes when the product is honest about not knowing, and a
    harness that cannot see the queue scores that as the same outcome as losing
    the message.

    HOW IT USED TO BE WRONG, kept because the shape recurs. The loop called
    ``_persist_review_items`` — the REBUILD persist — while being additive in
    every other respect: day batches, nothing purged, no ``_reset_review_queue``.
    That combination exists nowhere in the product, and the two functions share
    a name stem and most of a shape, so nothing in the file said the choice had
    been made rather than inherited.

    IT CHANGED NO NUMBER, and that is worth stating rather than discovering
    again. Measured over the whole corpus at seed 20260822: 2,873 review refs
    offered, 2,873 persisted, 0 dropped by the additive filter. The filter is not
    inert for want of running — its settled query returned 602 rows across 62 of
    the 240 day-batches — but not one of those rows' ``review_dedup_key``
    collides with an arriving item's. They are thread-mates naming a DIFFERENT
    application, which is #454's key doing exactly its job. So this corpus can
    now say the suppression does not over-fire; it still cannot say it fires
    correctly, because no family produces a queued message sharing both a thread
    and an identity with mail already on a card. That is #614's half.
    """

    by_day: dict[int, list[Verdict]] = defaultdict(list)
    for v in verdicts:
        by_day[v.case.received_at.toordinal()].append(v)

    dropped: set[str] = set()
    suppressed: set[str] = set()
    synced = SyncTotals()
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
        # UNCONDITIONALLY, including on a day whose mail rolls up to nothing and
        # asks nothing. That is a sync a user really makes — the auto sync runs
        # on a schedule, not on there being something to find — and it is the
        # only way the per-batch catch-up and the emptied-row dismissal get the
        # chance production gives them. The old loop skipped both.
        offered = [r.message_id for r in review]
        synced.add(
            await sync_gmail_pipeline_additive(session, _USER, rolled, review)
        )
        if offered:
            suppressed |= set(offered) - await _stored(session, offered)

    return await _read_the_board(
        session,
        dropped,
        suppressed,
        synced,
        {v.case.message_id: v.category for v in verdicts},
    )


async def _read_the_board(
    session,
    dropped: set[str],
    suppressed: set[str],
    synced: SyncTotals,
    verdict: dict[str, str],
) -> Replay:
    """The board, exactly as :func:`replay` left it.

    Extracted verbatim so :func:`answer_the_queue` can take the SAME reading
    afterwards. A second reader written by hand would be a second definition of
    "what the board says", and the delta between the two phases would then be
    partly a difference between two readers.
    """

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
    # THE REVIEW QUEUE, by the predicate the product itself uses — IMPORTED,
    # not retyped.
    #
    # ``GET /applications/summary`` and ``GET /applications/review`` both filter
    # on these three clauses, and getting it wrong here is not neutral: a looser
    # predicate counts any unlinked row as "the user was asked about it", which
    # makes LOST an undercount and errs toward the gate passing. This has now
    # drifted twice. The first version read ``application_id IS NULL`` alone and
    # claimed in a comment to match the product; it did not. The second spelled
    # the product's three clauses out by hand, and #587 then replaced the link
    # clause with :func:`_not_filed_on_an_application_that_answers` — "no
    # application of mine answers this", which since #597 counts a card the
    # user dismissed BY HAND as answering — leaving this copy asserting the OLD
    # product while its comment said it asserted the current one. A copy cannot
    # be kept honest by a comment, so the middle clause is the function itself.
    queued = (
        await session.exec(
            select(Email.message_id).where(
                Email.user_id == _USER,
                _not_filed_on_an_application_that_answers(_USER),
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
        suppressed=suppressed,
        synced=synced,
        status={
            f"row{r.id}:{r.company}": getattr(r.status, "value", str(r.status))
            for r in live
        },
        title={
            f"row{r.id}:{r.company}": (r.company or "", r.position or "")
            for r in live
        },
        verdict=verdict,
    )


@dataclass
class AnswerScore:
    """What answering the queue DOES, counted so the buckets close.

    Only the per-call outcomes the board cannot show. Everything about where
    the mail ended up is graded by re-running :func:`score_board` on the board
    afterwards — a second set of hand-rolled "did it land right" counters would
    be a weaker copy of instruments that already carry denominators, a closure
    assertion and mutation probes.
    """

    #: The denominator. Items in the queue when the phase starts.
    queued: int = 0
    answered: int = 0
    #: Left the queue because answering a SIBLING settled it. The queue offers
    #: one entry per conversation, so this is the product working, not a loss —
    #: but an accounting that does not name it reads as messages going missing.
    settled_by_a_prior_answer: int = 0
    #: `classify_review_item` could not name the employer, so it kept the label,
    #: kept the row in the queue and returned `needs_employer`. A silent branch
    #: until it is counted: over the whole corpus 360 of 17,260 cases resolve no
    #: employer from sender + subject (200 `bare-relay`, 160 of 320
    #: `verdict-past-the-body-cap`).
    refused_needs_employer: int = 0
    filed_on_an_existing_card: int = 0
    minted_a_card: int = 0
    #: Answered with a category that files nothing (`other`).
    not_a_lifecycle_answer: int = 0

    #: HOW MUCH CHOICE THERE WAS, for the filed ones. Reported apart because a
    #: landing at an employer holding ONE live card is right by cardinality, not
    #: by understanding, and folding the two together hides rule 4's coin toss
    #: inside a healthy-looking headline.
    landed_where_one_card_existed: int = 0
    landed_where_several_did: int = 0


#: The corpus's categories, mapped to the enum the endpoint takes.
#:
#: PLUMBING, not ground truth — the same distinction `_MAX_BODY_CHARS` is
#: imported under. `NEEDS_REVIEW` is deliberately absent and unmappable: it is
#: the typed null of `classified_as`, not a verdict a person can give, and
#: sending it as an answer would forge a decision nobody made.
_ANSWERS = {
    "applied": EmailCategory.APPLIED,
    "pending_application": EmailCategory.PENDING_APPLICATION,
    "interview": EmailCategory.INTERVIEW,
    "rejection": EmailCategory.REJECTION,
    "offer": EmailCategory.OFFER,
    "assessment": EmailCategory.ASSESSMENT,
    "other": EmailCategory.OTHER,
}


async def _still_in_the_queue(session, message_id: str) -> bool:
    """The product's own queue predicate, IMPORTED and re-asked per message.

    `_settle_thread_siblings` marks same-identity siblings reviewed and linked
    when one of them is answered, and `classify_review_item` has no
    `is_reviewed` guard — it selects on `message_id` alone. So a loop over the
    queue snapshot would re-answer rows that have already left it, producing
    duplicate training examples and a call path no UI can make. Re-checking is
    what the user sees: the row is gone from the list.
    """

    return (
        await session.exec(
            select(Email.message_id).where(
                Email.user_id == _USER,
                Email.message_id == message_id,
                _not_filed_on_an_application_that_answers(_USER),
                Email.classified_as == EmailCategory.NEEDS_REVIEW,
                Email.is_reviewed == False,  # noqa: E712 — SQL boolean
            )
        )
    ).first() is not None


async def answer_the_queue(
    session, cases: list[Case], replayed: Replay
) -> tuple[AnswerScore, Replay]:
    """Answer every held message with the category its mail really carries.

    THE HARNESS WROTE THE QUEUE AND NEVER READ IT. `replay` runs the sync and
    stops; `classify_review_item` and `reconcile_orphaned_classifications` were
    called nowhere under `tests/corpus_independent/`, so every product behaviour
    that begins with a person answering "what is this?" was ungraded (#547).
    The queue is where a message goes when the product is honest about not
    knowing, and a harness that cannot see it being ANSWERED scores "the user
    resolved it and the card is right" the same as "the user resolved it and the
    card is wrong".

    THIS MODELS A PERFECT ANSWERER, NOT A USER. Every held message is answered,
    and answered correctly, because `Case.expected_category` is the category the
    MAIL carries — what a person reading the whole thing in Gmail would say —
    while the pipeline only ever saw a ~200-character snippet. Wrong answers are
    a different instrument and out of scope. What this measures is the filing
    path under ideal answers: given the right answer, does the product put the
    mail on the right card and say the right thing about it?

    NO CARD IS PICKED, deliberately. `ReviewQueue.tsx` initialises its selection
    to null and pre-checks "not one of these" (#554), and sends null outright
    whenever the picker is not shown — so this is not merely the default path,
    it is the only path for most items. Passing `application_id` would measure a
    product the user does not have.

    OLDEST FIRST, and the order is part of the instrument. `Replay.reviewed` is
    a set, so iterating it directly is hash-order and therefore
    PYTHONHASHSEED-dependent; and order is load-bearing here, because the first
    answer at an employer mints the row the later ones land on. Sorted by
    `(received_at, message_id)`, which is also the order a person works a queue.

    Returns the per-call score and the board as it stands afterwards, read by
    the same function that read it the first time.
    """

    by_mid = {c.message_id: c for c in cases}
    held = sorted(
        (by_mid[mid] for mid in replayed.reviewed if mid in by_mid),
        key=lambda c: (c.received_at, c.message_id),
    )
    score = AnswerScore(queued=len(replayed.reviewed))
    existing = _row_ids(replayed)

    for case in held:
        if not await _still_in_the_queue(session, case.message_id):
            score.settled_by_a_prior_answer += 1
            continue
        answer = _ANSWERS.get(case.expected_category)
        if answer is None:  # pragma: no cover — the mapping is asserted total
            raise AssertionError(
                f"{case.expected_category!r} is not an answer a person can give"
            )

        result = await classify_review_item(
            session, _USER, case.message_id, answer
        )
        await session.commit()
        score.answered += 1

        if result.get("needs_employer"):
            score.refused_needs_employer += 1
            continue
        app_id = result.get("application_id")
        if app_id is None:
            score.not_a_lifecycle_answer += 1
            continue

        if app_id in existing:
            score.filed_on_an_existing_card += 1
        else:
            score.minted_a_card += 1
            existing.add(app_id)

        # CARDINALITY READ OFF THE BOARD, not derived from the case. The token
        # space `employers_with_several_applications` counts in is the leading
        # word of a display name, not the normalized company, and the comment on
        # that function records what happened the last time this was rederived:
        # a set that never contained the token being looked up, so the rule
        # silently did nothing. Counting the rows that share the landed row's
        # own `company` asks the board instead of guessing its vocabulary.
        landed = await session.get(Application, app_id)
        siblings = (
            await session.exec(
                select(Application.id).where(
                    Application.user_id == _USER,
                    Application.company == landed.company,
                    Application.dismissed_at.is_(None),
                )
            )
        ).all()
        if len(siblings) > 1:
            score.landed_where_several_did += 1
        else:
            score.landed_where_one_card_existed += 1

    # THE CATCH-UP, which #547 names alongside the answer path. It is the
    # designed repair for the `needs_employer` refusals above, and it was
    # equally unreachable from this harness.
    await reconcile_orphaned_classifications(session, _USER)
    await session.commit()

    # The same totals, unchanged: they describe what the SYNCS did, and
    # answering the queue is not a sync. Re-reading the board is not a second
    # measurement of them.
    return score, await _read_the_board(
        session,
        replayed.dropped,
        replayed.suppressed,
        replayed.synced,
        replayed.verdict,
    )


def _row_ids(replayed: Replay) -> set[int]:
    """The application ids behind the labels, which carry `row<id>:`."""

    return {int(label.split(":", 1)[0][3:]) for label, _ in replayed.groups}


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
    #: ── AN UPDATE THAT SAT IN THE REVIEW QUEUE, IN THREE CAUSES ────────────
    #:
    #: THE DESIGNED ANSWER, not a failure — counted so it is visible rather than
    #: invisible, and excluded from ``total``. It was ONE counter until #448,
    #: and one counter is what let three unrelated mechanisms be read as one:
    #: measured at seed 20260822 the 685 are 345 + 80 + 260, and only the first
    #: 345 are the mechanism the issue is about. A number that moves for three
    #: reasons cannot say which one moved it.
    #:
    #: The update's own verdict is an ``offer`` that did not clear the auto-file
    #: gate, so the product asked instead of guessing. THE #448 POPULATION: all
    #: 345 sit in ``[REVIEW_FLOOR, AUTO_FILE_GATE)`` — 79 at 0.70 and 266 at
    #: 0.75 — and lifting them over the gate is what "fixing" this means.
    update_held_on_its_own_confidence: int = 0
    #: The update itself was filed and its ANCHOR is the row in the queue, so
    #: the pair is split by the anchor's uncertainty rather than the update's.
    #: All 80 are ``update-before-confirmation``, whose confirmation arrives
    #: AFTER the update that belongs to it and is the message being held. A gate
    #: change aimed at updates does not move these; a change aimed at
    #: confirmations does.
    update_held_on_its_anchor: int = 0
    #: The update is in the queue on a verdict that is not an ``offer`` at all,
    #: so the auto-file gate is not what put it there. All 260 are
    #: ``rescinded-offer`` — ``other`` at 0.50, under the review FLOOR, floored
    #: into the queue by ``references_an_application`` — which is #417 and a
    #: different issue. They were 38% of a counter people read as this one.
    update_held_on_a_non_offer_verdict: int = 0
    #: The right card, showing the wrong stage.
    wrong_status: int = 0
    #: The card claims a BETTER outcome than the user has, and the mail that
    #: would correct it is sitting in the review queue. A card that is BEHIND
    #: reality is honest and incomplete; a card that is AHEAD of it is a lie
    #: the product is telling, and the two must not be counted as one thing.
    card_overstates: int = 0
    #: How many cards had their TITLE compared to ground truth at all. Not a
    #: defect count — the denominator. A grader that silently graded nothing
    #: would report three zeroes below and read as perfect, which is the
    #: check-that-cannot-fail shape this whole file exists to avoid.
    titles_graded: int = 0
    #: The same denominator for the ROLE half, which is smaller: a card whose
    #: ground truth keys on a requisition id, or on this generator's "the mail
    #: names no role" sentinel, has a title nothing here can settle. See
    #: ``Case.role_truth``.
    roles_graded: int = 0

    #: Cards whose mail names NO job title, so the only correct card is blank.
    #: The denominator for ``role_invented``. These were SKIPPED until now: a
    #: card with no gradeable role read as "nothing to assert", which let 960
    #: cards — 10.4% of the board — carry any title the product cared to print
    #: while every counter stayed at zero. "The mail names no role" is a claim,
    #: not an absence, and a claim can be checked.
    #:
    #: 1106 now: #533 found 146 more of them hiding in the opposite counter,
    #: scored as ROLE-MISSING defects for not printing a title their mail never
    #: contained.
    blank_required: int = 0

    #: A card that must be blank and is not: the product printed a job title for
    #: mail that names none. In ``total``, because it is an invention rather
    #: than a gap — the opposite direction from ``role_missing``, which is an
    #: absence and stays out.
    role_invented: int = 0

    #: Cards this corpus genuinely cannot settle a title for: the identity keys
    #: on a requisition id, so the key names the application without naming the
    #: job. Not a defect and not an assertion — the THIRD population, and it
    #: exists so the three can be made to close against ``titles_graded``.
    #:
    #: Without it, "every card is accounted for" is unstatable: a regression
    #: that stopped grading N cards would move ``roles_graded`` down and nothing
    #: would move up, and the only visible effect would be a smaller
    #: denominator — which is how a merge regression once took ``role_missing``
    #: from 213 to 0 while breaking the board (#536).
    role_unsettleable: int = 0
    #: The card names an employer that is not the one the mail is from.
    company_wrong: int = 0
    #: Same employer by the product's own matching rule, different string —
    #: "Northwind" against "Northwind Labs". Reported, and kept OUT of
    #: ``total``: it is a cosmetic variance, not a wrong record.
    company_drift: int = 0
    #: The card names a role that is not the one applied for.
    role_wrong: int = 0
    #: Ground truth has a role and the card's is blank. Not a lie, an absence —
    #: reported and kept out of ``total`` for the same reason ``company_drift``
    #: is. #486's Palantir case was this, and it is a real defect; it is simply
    #: a different one from a card carrying somebody else's job title.
    role_missing: int = 0
    #: About a real application and reached nothing at all.
    lost: int = 0
    #: About a real application and dropped under the review floor. Counted by
    #: the product, so recoverable by a person who goes looking.
    dropped: int = 0

    #: ── what happened to mail that MUST be addressed ────────────────────────
    #:
    #: The two good outcomes, counted rather than skipped. ``lost`` and
    #: ``dropped`` above are leftovers, so on their own they have no
    #: denominator: a change that stopped GRADING n messages would take both to
    #: zero and read as a perfect board, which is how a merge regression once
    #: took ``role_missing`` from 213 to 0 (#536). With these two the five
    #: populations can be made to close against a count taken from ``cases``,
    #: and the closure is arithmetic — see
    #: ``test_every_application_mail_is_addressed``.
    addressed_on_a_card: int = 0
    addressed_in_the_queue: int = 0
    #: THE FOURTH OUTCOME, and it exists because :func:`replay` now calls the
    #: additive persist (#624). ``_persist_review_items_additive`` refuses a row
    #: to an arriving item whose (thread, application) the sync has already
    #: settled — either a sibling is ``is_reviewed``, or a sibling is filed on a
    #: card that answers for it. The message then reaches no card, no queue and
    #: no counter, which is LOST's definition for an outcome the product chose;
    #: scoring designed behaviour as the estate's worst failure mode would put a
    #: deliberate suppression in the counter that exists for silent loss.
    #:
    #: OUT OF ``total`` for that reason, and NOT a blessing: whether suppressing
    #: an uncertain update to an application already on a card is right is not
    #: settled by this commit. The bucket makes the population visible, which is
    #: the precondition for deciding.
    #:
    #: 0 ON THIS CORPUS, AND THE ZERO IS MEASURED. Both arms were checked at
    #: seed 20260822. ``is_reviewed`` CANNOT fire during a replay — the flag is
    #: written only by ``classify_review_item`` and ``_settle_thread_siblings``,
    #: neither of which the sync path calls, and there are 0 such rows when the
    #: replay ends. The filed arm DOES select rows (602 across 62 of the 240
    #: day-batches) and none of their dedup keys collides with an arriving
    #: item's. So this counter is currently a zero that cannot be non-zero, in
    #: the sense #536 names, and it is pinned anyway: it is what will catch the
    #: suppression the moment a family produces a queued message sharing a
    #: thread AND an identity with mail already on a card.
    #:
    #: WHEN THE ZERO EXPIRES, so that a later reader does not cite it as a
    #: product fact. Two #614 families are expected to make it legitimately
    #: non-zero, and until one of them lands this number says "the corpus has no
    #: case of this shape", NOT "the sync suppresses nothing":
    #:
    #:   * the same-thread-same-identity uncertain follow-up (#630) — a reply
    #:     quoting the confirmation's subject, so Gmail threads it and the role
    #:     derives to the same token, arriving below the auto-file gate;
    #:   * the interleaved family — answer the queue, THEN deliver more mail.
    #:     Today the harness answers once, after the last day, so the
    #:     ``is_reviewed`` arm of the settled filter cannot fire at all. That is
    #:     a property of the harness's phase ordering, not of the product, and
    #:     it is the same "an arm no fixture can reach" shape #624 removed one
    #:     arm over.
    #:
    #: The only evidence today that the FILTER itself bites — as opposed to this
    #: counter counting — is an uncommitted control that reverts #454's identity
    #: component inside the additive persist and takes this to 602. That control
    #: belongs in the tree; it is named as the first item of #614's control set.
    suppressed_as_settled: int = 0
    failures: list[Failure] = field(default_factory=list)

    @property
    def update_held_for_review(self) -> int:
        """The three causes above, summed, under the name they used to share.

        Kept because four readers ask for it and mean "how many updates did the
        product ask about" — the ranked table, ``card_overstates``'s control,
        the UPDATE-HELD closure check, and ``run_independent_corpus.py``. It is
        a PROPERTY and not a field so the sum cannot drift from its parts:
        incrementing this without incrementing one of the three raises
        ``AttributeError`` rather than opening a silent fourth population.
        """

        return (
            self.update_held_on_its_own_confidence
            + self.update_held_on_its_anchor
            + self.update_held_on_a_non_offer_verdict
        )

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
            + self.card_overstates
            + self.company_wrong
            + self.role_wrong
            + self.role_invented
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


def _overstates(
    score: BoardScore,
    replayed: Replay,
    card_of: dict[str, str],
    case: Case,
) -> None:
    """Count a held message whose card is left claiming a better outcome.

    Ground truth (``case.card_status``) says where the row belongs once this
    message is understood. The card shows something else because the message is
    in the queue. Two directions and only one is a defect:

      * the card ranks LOWER — it has not caught up yet. Honest.
      * the card ranks HIGHER, or ground truth is TERMINAL and the card is not
        — the row is asserting a stage the user does not have.

    ``_TERMINAL_STATUSES`` carries no rank (a rejection is not "further along"
    than an offer), so it is handled explicitly: ground truth ``rejected`` with
    the card on any live stage is the rescinded-offer shape, and it overstates.
    """

    want = case.card_status
    # The message is in the QUEUE, so it is on no card — the card at issue is
    # the one it belongs to. ``Case.joins`` names it. Without this the lookup
    # is always None and the counter is one of the checks that cannot fail:
    # it read 0 against 260 cards that were demonstrably overstating.
    label = card_of.get(case.message_id) or (
        card_of.get(case.joins) if case.joins else None
    )
    if want is None or label is None:
        return
    actual = replayed.status.get(label)
    if actual is None or actual == want:
        return

    want_terminal = want in pipeline._TERMINAL_STATUSES
    actual_terminal = actual in pipeline._TERMINAL_STATUSES
    if want_terminal and actual_terminal:
        return  # two terminal answers; not an overstatement, and not this counter
    ahead = want_terminal or (
        not actual_terminal
        and pipeline._STATUS_RANK.get(actual, 0) > pipeline._STATUS_RANK.get(want, 0)
    )
    if not ahead:
        return

    score.card_overstates += 1
    score.failures.append(
        Failure(
            mode="CARD-OVERSTATES",
            family=case.family,
            detail=(
                f"card {label!r} still reads {actual!r}; the mail that makes it "
                f"{want!r} is in the review queue"
            ),
            message_ids=(case.message_id,),
        )
    )


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
        held_itself = case.message_id in replayed.reviewed
        if held_itself or case.joins in replayed.reviewed:
            # WHICH OF THREE MECHANISMS HELD IT, because they are three issues
            # and were one number until #448. See the three counters on
            # ``BoardScore`` for what each population is.
            #
            # ITS OWN HOLD WINS when both rows are in the queue: an update the
            # product is already unsure about does not become somebody else's
            # problem because its anchor is unsure too. No case in this corpus
            # reaches that arm — every held pair is (self, not anchor) or
            # (anchor, not self) at seed 20260822 — so the precedence is stated
            # rather than exercised.
            if not held_itself:
                score.update_held_on_its_anchor += 1
                why = "its ANCHOR is in the queue, so the pair is split there"
            elif replayed.verdict.get(case.message_id) == "offer":
                score.update_held_on_its_own_confidence += 1
                why = "under the auto-file gate, so the product asked"
            else:
                score.update_held_on_a_non_offer_verdict += 1
                why = "in the queue on a verdict the auto-file gate never saw"
            # Recorded as a Failure so ``rank`` can show WHICH families are
            # being held, and excluded from ``total`` by ``BoardScore`` rather
            # than by not existing. A designed outcome that leaves no trace is
            # a designed outcome nobody can audit.
            score.failures.append(
                Failure(
                    mode="UPDATE-HELD",
                    family=case.family,
                    detail=why,
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
            # moved the stage. Asserting WRONG-STAGE here asserts that an
            # unfiled message changed the board, which is the opposite of what
            # the review queue is for. Measured: 77 offers arriving before their
            # confirmation sat in the queue at 0.75 while the card correctly
            # read `applied`, and scoring that as WRONG-STAGE would have made
            # the designed answer look like a defect for the second time.
            #
            # BUT NOT EVERY HELD MESSAGE LEAVES AN HONEST CARD, and collapsing
            # the two outcomes is how this went unmeasured. Those 77 leave a
            # card reading `applied` when it should read `offered`: BEHIND
            # reality, incomplete, and true as far as it goes. The withdrawal
            # of an offer leaves a card reading `offered` when the offer has
            # been rescinded: AHEAD of reality, and the board is asserting
            # something about the user's life that is not so — which is the
            # single failure #417 says matters more than the rest.
            #
            # The direction is the whole distinction, so it is read off the
            # product's own ``_STATUS_RANK`` rather than a list kept here.
            _overstates(score, replayed, card_of, case)
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

    # ── and the card is NAMED right ──────────────────────────────────────────
    #
    # The half this scorer could not see until #487. Everything above is about
    # WHICH MESSAGES ENDED UP TOGETHER; none of it looks at the two fields a
    # user actually reads. A card holding exactly the right mail, under a
    # company called "Senior Software Engineer Interview" — a real capture, off
    # the live filing path, found while fixing #512 — scores perfectly above.
    # PR #486 is the other proof: it turned 44 blank roles into correct ones
    # and moved not one number, because gaining a title changes a card's NAME
    # and not its partition.
    #
    # Graded only where ground truth can settle it:
    #
    #   * the card must map to exactly ONE ground-truth application. A card
    #     holding two is a MERGE, already counted, and "which of the two is it
    #     supposed to be named after" has no answer.
    #   * ``expect_review`` mail carries no identity, so a card built only from
    #     it is not graded — there is nothing to grade against.
    #
    # Company is compared with ``matches_company_token``, the product's OWN
    # "is this the same employer" rule, so that "Northwind" against "Northwind
    # Labs" reports as drift rather than as a wrong record. Role is compared
    # with ``normalize_role_token``, for the reason that function exists: an
    # employer's confirmation and its own later mail punctuate the same title
    # differently, and a comparison on display strings would read that as a
    # wrong title several thousand times.
    for label, mids in groups:
        title = replayed.title.get(label)
        if title is None:
            continue
        idents = {
            by_mid[m].identity
            for m in mids
            if m in by_mid and by_mid[m].identity is not None
        }
        if len(idents) != 1:
            continue  # no identity to grade against, or a MERGE already counted
        ident = idents.pop()
        want_employer = ident.partition("|")[0]
        want_role = next(
            (
                by_mid[m].role_truth
                for m in mids
                if m in by_mid and by_mid[m].role_truth is not None
            ),
            None,
        )
        company, position = title
        family = next(
            (by_mid[m].family for m in mids if m in by_mid), "?"
        )
        score.titles_graded += 1

        if not pipeline.matches_company_token(company, want_employer):
            score.company_wrong += 1
            score.failures.append(
                Failure(
                    mode="WRONG-COMPANY",
                    family=family,
                    detail=f"card reads company {company!r}, applied to {want_employer!r}",
                    message_ids=tuple(mids[:5]),
                )
            )
        elif pipeline.normalize_company_name(company) != pipeline.normalize_company_name(
            want_employer
        ):
            score.company_drift += 1
            score.failures.append(
                Failure(
                    mode="COMPANY-DRIFT",
                    family=family,
                    detail=f"card reads company {company!r}, applied to {want_employer!r}",
                    message_ids=tuple(mids[:5]),
                )
            )

        got_role = pipeline.normalize_role_token(position)
        want_token = pipeline.normalize_role_token(want_role)
        if want_token is None:
            # TWO REASONS A CARD HAS NO ROLE TO GRADE AGAINST, and they mean
            # opposite things. A req-id family keys on the requisition, so this
            # corpus genuinely cannot settle the title and the card is skipped.
            # A SENTINEL family withholds the title on purpose, so a blank card
            # is the only correct card and any title is an invention. Only the
            # first is unanswerable; treating both as unanswerable is what left
            # 960 cards ungraded.
            blank = [by_mid[m].names_no_role for m in mids if m in by_mid]
            # ``all`` RATHER THAN ``any``, and the empty list guarded, because
            # the two differ only on a card this corpus cannot build: reaching
            # here means every case on the card has ``role_truth is None``, and
            # cases sharing an identity share a sub-key, so they share the
            # reason. If one ever did arrive mixed, ``all`` sends it to the
            # skipped population instead of asserting a blank the card was
            # never required to have — a false ROLE-INVENTED naming a real
            # defect that is not there costs more than one unasserted card.
            if not blank or not all(blank):
                score.role_unsettleable += 1
            else:
                score.blank_required += 1
                if got_role is not None:
                    score.role_invented += 1
                    score.failures.append(
                        Failure(
                            mode="ROLE-INVENTED",
                            family=family,
                            detail=(
                                f"card reads position {position!r}; this mail "
                                f"names no job title at all"
                            ),
                            message_ids=tuple(mids[:5]),
                        )
                    )
            continue
        score.roles_graded += 1
        if got_role is None:
            score.role_missing += 1
            score.failures.append(
                Failure(
                    mode="ROLE-MISSING",
                    family=family,
                    detail=f"card has no position; applied for {want_role!r}",
                    message_ids=tuple(mids[:5]),
                )
            )
        elif got_role != want_token:
            score.role_wrong += 1
            score.failures.append(
                Failure(
                    mode="WRONG-ROLE",
                    family=family,
                    detail=f"card reads position {position!r}, applied for {want_role!r}",
                    message_ids=tuple(mids[:5]),
                )
            )

    # ── every application mail is addressed ──────────────────────────────────
    #
    # FIVE OUTCOMES, ALL COUNTED, because four of them used to be a `continue`.
    # A message that must be addressed is on a card, in the queue, suppressed by
    # the additive persist, dropped under the floor, or lost — and the first two
    # were invisible here, which left `lost` and `dropped` as leftovers with no
    # denominator. The five are asserted to close against a population counted
    # from `cases` rather than from a counter this loop increments; a
    # denominator this loop maintains would fall with the buckets and the
    # closure could not fail.
    for case in cases:
        if not case.must_be_addressed:
            continue
        if case.message_id in on_a_card:
            score.addressed_on_a_card += 1
            continue
        if case.message_id in replayed.reviewed:
            score.addressed_in_the_queue += 1
            continue
        if case.message_id in replayed.suppressed:
            # Recorded as a Failure so `rank` can name the FAMILIES being
            # suppressed, and excluded from `total` by `BoardScore` rather than
            # by not existing — the same shape `update_held_for_review` uses. A
            # designed outcome that leaves no trace is one nobody can audit.
            score.suppressed_as_settled += 1
            score.failures.append(
                Failure(
                    mode="SUPPRESSED-AS-SETTLED",
                    family=case.family,
                    detail=(
                        "the additive persist refused it a row: the sync had "
                        "already settled this thread's application"
                    ),
                    message_ids=(case.message_id,),
                )
            )
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
