"""Drive the REAL identity pipeline over the corpus and score where it breaks.

Two layers, scored separately, because a bug can be invisible in one and
user-visible in the other:

**Layer 1 — in-scan.** :func:`pipeline.partition_applications` over the whole
corpus at once. This is what one scan of a mailbox does. It catches identity
errors that exist purely in the extractor.

**Layer 2 — incremental.** The user-visible layer, and where the reported bug
actually bit. Real syncs are incremental (``gmail_oauth`` rolls up a *delta*,
not the whole mailbox), so mail arrives days apart and each delta is resolved
against rows already stored. Layer 2 replays the corpus one message at a time
through :func:`pipeline.roll_up_applications` and the REAL
:func:`applications._pick_application`, against an in-memory store of real
``Application`` model instances. A confirmation whose role extracted one way
and a rejection whose role extracted another produce a match in layer 1 (they
land in one cluster keyed on whichever token won) but a MISS in layer 2 — which
mints the second card the user saw.

What layer 2 deliberately does NOT model: status advance, reopen-after-
rejection, dismissal and resurrection. Those are orthogonal to identity, and
including them would let a status bug masquerade as an identity failure.

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

from jobtracker.cloud import pipeline
from jobtracker.cloud.applications import (
    SOURCE_GMAIL_AUTO,
    Application,
    _pick_application,
)

from .generator import Case

_USER = uuid.UUID("00000000-0000-0000-0000-0000000000aa")


# ── layer 2: an in-memory mirror of the persistent resolver ──────────────────


class RowStore:
    """The rows a board would hold, ordered exactly as ``_company_rows`` does.

    Ordering matters and is not cosmetic: ``_pick_application`` rule 4 returns
    ``rows[0]`` for an identity-less cluster. An unordered store changes which
    row that is and every number downstream with it. ``_company_rows`` orders
    live-first, then ``created_at`` ascending, then ``id`` ascending; nothing
    here is ever dismissed, so insertion order IS that order.
    """

    def __init__(self) -> None:
        self.rows: list[Application] = []
        self._next_id = 1
        # row id -> the message ids filed against it
        self.filed: dict[int, list[str]] = defaultdict(list)

    def company_rows(self, token: str) -> list[Application]:
        """Faithful to ``_company_rows``: exact OR leading-word, unioned.

        The union is the part that matters — the early-return version of this
        query is what grew six rows for one employer, and a harness that only
        did the exact match would never see that class of bug.
        """

        return [
            row
            for row in self.rows
            if pipeline.normalize_company_name(row.company) == token
            or pipeline.matches_company_token(row.company, token)
        ]

    def mint(self, rolled: pipeline.RolledApplication) -> Application:
        row = Application(
            user_id=_USER,
            company=rolled.company_display,
            status=rolled.status,
            source=SOURCE_GMAIL_AUTO,
            req_id=rolled.req_id,
            role_token=rolled.role_token,
        )
        row.id = self._next_id
        self._next_id += 1
        row.dismissed_at = None
        self.rows.append(row)
        return row


def replay_incremental(cases: list[Case]) -> RowStore:
    """Replay the corpus as successive one-message syncs.

    Mirrors ``upsert_applications_for_user``'s identity half: resolve against
    stored rows, mint on a miss, and stamp whichever half of the identity the
    landed-on row was missing. Nothing else.
    """

    store = RowStore()
    ordered = sorted(cases, key=lambda c: (c.item.received_at, c.item.message_id))
    for case in ordered:
        rolled = pipeline.roll_up_applications([case.item])
        for r in sorted(rolled, key=lambda x: (x.company_token, x.applied_at or _MAX)):
            rows = store.company_rows(r.company_token)
            existing = _pick_application(rows, r.req_id, r.role_token)
            if existing is None:
                existing = store.mint(r)
            else:
                # The upsert stamps the half the row lacked — that is how a
                # pre-identity row is migrated in place rather than duplicated.
                if existing.req_id is None and r.req_id is not None:
                    existing.req_id = r.req_id
                if existing.role_token is None and r.role_token is not None:
                    existing.role_token = r.role_token
            for ref in r.messages:
                store.filed[existing.id].append(ref.message_id)
    return store


from datetime import datetime as _dt  # noqa: E402  (used only for the sort key)

_MAX = _dt.max


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

    score = Score(layer=layer, gated_items=gated_items, cards=len(groups))

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


def score_incremental(cases: list[Case]) -> Score:
    """Layer 2 — successive incremental syncs against stored rows."""

    by_mid = {c.item.message_id: c for c in cases}
    store = replay_incremental(cases)
    gated = sum(
        1 for c in cases if pipeline._qualifies_for_hard_row(c.item) is not None
    )
    groups = [
        (f"row{row.id}:{row.company}", store.filed.get(row.id, []))
        for row in store.rows
    ]
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
