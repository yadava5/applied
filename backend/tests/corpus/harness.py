"""Drive the REAL identity pipeline over the corpus and score where it breaks.

Two layers, scored separately, because a bug can be invisible in one and
user-visible in the other:

**Layer 1 — in-scan.** :func:`pipeline.partition_applications` over the whole
corpus at once. This is what one scan of a mailbox does. It catches identity
errors that exist purely in the extractor.

**Layer 2 — incremental, against the real database.** The user-visible layer,
and where the reported bug actually bit. Real syncs are incremental
(``gmail_oauth`` rolls up a *delta*, not the whole mailbox), so mail arrives
days apart and each delta is resolved against rows already stored. Layer 2
replays the corpus one message at a time through
:func:`pipeline.roll_up_applications` and the REAL
:func:`applications.upsert_applications_for_user`, against a real session, and
then reads the cards back out of the ``applications`` and ``emails`` tables. A
confirmation whose role extracted one way and a rejection whose role extracted
another produce a match in layer 1 (they land in one cluster keyed on whichever
token won) but a MISS in layer 2 — which mints the second card the user saw.

THIS LAYER USED TO BE A HAND-WRITTEN MIRROR of ``_pick_application`` over an
in-memory list of ``Application`` instances, and the mirror is why it is gone.
On 2026-08-21 the resolver learned to tell an employer's anonymous applications
apart by the ``message → application`` links already stored
(``_anonymous_homes``), and none of that lives in ``_pick_application``. The
mirror reported five MERGEs for behaviour the product had just fixed: it was
measuring a twin that had drifted, which is the failure this harness exists to
catch in the product. Everything now runs through the real function, so
anything the sync does — home resolution, the sibling guard in
``_persist_message_refs``, status advance, dismissal of an emptied row — is in
the numbers rather than approximated beside them.

Scoring
-------
Scoring is per MESSAGE against ground truth, never per-employer cardinality:
"2 cards where 2 were expected" is satisfied even when both messages sit on
the wrong cards.

* **SPLIT** — one ground-truth application spread over more than one card.
  Counted as the number of EXTRA cards, so a 3-way split scores 2.
* **MERGE** — one card holding messages from more than one ground-truth
  application. The strictly worse failure: it destroys a record silently, and
  a fix that refuses roles more aggressively pushes errors here.
* **NOISE-ON-CARD** — mail that must never become an application, on one.
* **SHOULD-HAVE-BEEN-REVIEWED** — role-less mail at a multi-application
  employer that got guessed onto a card instead of going to the queue.

There is deliberately no separate misattribution bucket; see the long comment
at its former site in :func:`_score_grouping` for why MERGE subsumes it.

``expect_review`` cases are scored in their own bucket: role-less mail at a
multi-application employer is SUPPOSED to be unplaceable, and counting the
designed behaviour as a failure would swamp the ranked table.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlmodel import select

from jobtracker.cloud import pipeline
from jobtracker.cloud.applications import (
    Application,
    Email,
    employers_with_several_applications,
    threads_naming_one_application,
    upsert_applications_for_user,
)

from .generator import Case

_USER = uuid.UUID("00000000-0000-0000-0000-0000000000aa")


# ── layer 2: the real persistence path ───────────────────────────────────────


async def replay_persisted(session, cases: list[Case]) -> list[tuple[str, list[str]]]:
    """Replay the corpus as successive one-message syncs against a real session.

    Each message is rolled up on its own and handed to the REAL
    :func:`upsert_applications_for_user`, exactly as an incremental Gmail sync
    delivers a delta. Returns the board as ``(card label, message ids)`` read
    back out of the database, which is the only place the answer actually is.

    Ordered by receive time, message id breaking a tie: the corpus is meant to
    arrive the way mail does, and a replay whose order changed between runs
    could not be a regression gate.
    """

    ordered = sorted(cases, key=lambda c: (c.item.received_at, c.item.message_id))
    for case in ordered:
        # Exactly what ``gmail_oauth`` does per delta, in the same order: read
        # what the board already holds, then roll up against it. Without the
        # first line the roll-up cannot tell an employer with four cards from an
        # employer with one — a delta of one message looks the same either way —
        # and a role-less rejection is filed against whichever card sorts first
        # instead of being queued.
        known_multi = await employers_with_several_applications(session, _USER)
        known_threads = await threads_naming_one_application(session, _USER)
        rolled = pipeline.roll_up_applications([case.item], known_multi, known_threads)
        if not rolled:
            continue
        await upsert_applications_for_user(session, _USER, rolled)
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
    for email in emails:
        filed[email.application_id].append(email.message_id)

    # A dismissed row is not on the board. Counting one would report a card the
    # user cannot see, and ``_dismiss_rows_left_without_mail`` dismisses exactly
    # the rows a re-resolution emptied — which is a real outcome worth NOT
    # scoring as a card.
    return [
        (f"row{row.id}:{row.company}", sorted(filed.get(row.id, [])))
        for row in rows
        if row.dismissed_at is None
    ]


# ── scoring ──────────────────────────────────────────────────────────────────


@dataclass
class Failure:
    mode: str
    axis: str
    identity: str | None
    detail: str
    message_ids: tuple[str, ...] = ()


@dataclass
class Score:
    layer: str
    splits: int = 0
    merges: int = 0
    minted_from_noise: int = 0
    wrong_review: int = 0
    gated_items: int = 0
    cards: int = 0
    failures: list[Failure] = field(default_factory=list)
    #: (card label, message ids) exactly as scored. Kept so the two layers can
    #: be compared to each other and not only to ground truth — see
    #: ``test_a_rebuild_and_a_delta_produce_the_same_board``.
    groups: list[tuple[str, list[str]]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (
            self.splits
            + self.merges
            + self.minted_from_noise
            + self.wrong_review
        )


def _score_grouping(
    layer: str,
    groups: list[tuple[str, list[str]]],
    by_mid: dict[str, Case],
    gated_items: int,
) -> Score:
    """Score any message→card grouping against ground truth.

    ``groups`` is a list of (card label, message ids). Shared by both layers so
    the two numbers are computed by identical logic and can be compared.
    """

    score = Score(
        layer=layer,
        gated_items=gated_items,
        cards=len(groups),
        groups=[(label, list(mids)) for label, mids in groups],
    )

    # Where did each ground-truth identity end up?
    ident_cards: dict[str, set[str]] = defaultdict(set)
    for label, mids in groups:
        for mid in mids:
            case = by_mid.get(mid)
            if case is None or case.identity is None:
                continue
            ident_cards[case.identity].add(label)

    for ident, labels in sorted(ident_cards.items()):
        if len(labels) > 1:
            example = next(c for c in by_mid.values() if c.identity == ident)
            score.splits += len(labels) - 1
            score.failures.append(
                Failure(
                    mode="SPLIT",
                    axis=example.axis,
                    identity=ident,
                    detail=f"one application spread over {len(labels)} cards",
                    message_ids=tuple(
                        sorted(m for m, c in by_mid.items() if c.identity == ident)
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
            axis = by_mid[mids[0]].axis if mids and mids[0] in by_mid else "?"
            score.merges += len(idents) - 1
            score.failures.append(
                Failure(
                    mode="MERGE",
                    axis=axis,
                    identity=None,
                    detail=(
                        f"card {label!r} holds {len(idents)} distinct applications: "
                        + ", ".join(sorted(str(i) for i in idents))
                    ),
                    message_ids=tuple(mids),
                )
            )

        # Mail that must never become an application, sitting on a card.
        noise = [m for m in mids if m in by_mid and by_mid[m].identity is None
                 and not by_mid[m].expect_review]
        if noise:
            score.minted_from_noise += len(noise)
            score.failures.append(
                Failure(
                    mode="NOISE-ON-CARD",
                    axis=by_mid[noise[0]].axis,
                    identity=None,
                    detail=f"{len(noise)} message(s) that must mint nothing landed on card {label!r}",
                    message_ids=tuple(noise),
                )
            )

        # NO SEPARATE MISATTRIBUTION BUCKET — deliberately, and this note is
        # here so it does not get "helpfully" re-added.
        #
        # The first version of this file counted "a message on a card whose
        # MAJORITY identity is not its own, at correct cardinality" with the
        # guard ``if strays and len(set(owned)) == 1``. Those two conditions are
        # mutually exclusive: ``strays`` is non-empty only when some identity
        # differs from the majority, while ``len(set(owned)) == 1`` requires
        # every identity to be equal. The branch could never execute, and every
        # run duly reported ``MISATTRIBUTED 0`` — a zero that reads as "checked,
        # clean" while meaning "never checked". That is precisely the
        # cannot-fail-check shape this harness exists to hunt.
        #
        # It is not replaced with a working version because MERGE already
        # subsumes the measurable case: if two applications' messages cross onto
        # each other's cards, each card holds two distinct identities and MERGE
        # fires. A pure swap — card A holding exactly B's messages and vice
        # versa — is undetectable in principle, because a card has no identity
        # apart from the messages grouped onto it.

    return score


def score_in_scan(cases: list[Case]) -> Score:
    """Layer 1 — one scan of the whole corpus."""

    by_mid = {c.item.message_id: c for c in cases}
    items = [c.item for c in cases]
    clusters, unplaced = pipeline.partition_applications(items)

    gated = sum(
        1 for c in cases if pipeline._qualifies_for_hard_row(c.item) is not None
    )
    groups = [
        (f"{c.company_token}#{i}", [it.message_id for it in c.items])
        for i, c in enumerate(clusters)
    ]
    score = _score_grouping("in-scan", groups, by_mid, gated)

    # Review routing, scored in its own bucket. Being unplaceable is the
    # DESIGNED answer for role-less mail at a multi-application employer.
    unplaced_ids = {it.message_id for it in unplaced}
    for case in cases:
        if case.expect_review and pipeline._qualifies_for_hard_row(case.item) is None:
            continue  # correctly held below the gate
        if case.expect_review and case.item.message_id not in unplaced_ids:
            score.wrong_review += 1
            score.failures.append(
                Failure(
                    mode="SHOULD-HAVE-BEEN-REVIEWED",
                    axis=case.axis,
                    identity=None,
                    detail="role-less mail at a multi-application employer was guessed onto a card",
                    message_ids=(case.item.message_id,),
                )
            )
    return score


async def score_incremental(session, cases: list[Case]) -> Score:
    """Layer 2 — successive incremental syncs against a real database."""

    by_mid = {c.item.message_id: c for c in cases}
    groups = await replay_persisted(session, cases)
    gated = sum(
        1 for c in cases if pipeline._qualifies_for_hard_row(c.item) is not None
    )
    return _score_grouping("incremental", groups, by_mid, gated)


def rank(score: Score) -> list[tuple[str, str, int]]:
    """Failure modes ranked by how often they fire: (mode, axis, count)."""

    tally: Counter[tuple[str, str]] = Counter()
    for f in score.failures:
        weight = 1
        if f.mode == "SPLIT":
            weight = max(1, len(f.message_ids) - 1)
        elif f.mode in {"MERGE", "NOISE-ON-CARD"}:
            weight = max(1, len(f.message_ids) - 1)
        tally[(f.mode, f.axis)] += weight
    return [(mode, axis, n) for (mode, axis), n in tally.most_common()]
