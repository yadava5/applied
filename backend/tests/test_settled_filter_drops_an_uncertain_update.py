"""Issue #630, as a NUMBER: the class the additive persist refuses, constructed.

What this measures, and what it deliberately does not
-----------------------------------------------------

``_persist_review_items_additive`` drops an arriving review ref whose
``review_dedup_key`` matches a stored message that is already settled — filed on
an application that answers, or reviewed by hand. The drop happens BEFORE
``_persist_message_refs``, so the message gets no ``emails`` row, no queue entry
and no counter. ``_persist_review_items``, the rebuild path behind the explicit
"Re-sync" button, has no such filter.

Over the 17,260-message independent corpus that filter fires ZERO times
(``suppressed_as_settled`` in ``test_independent_corpus.py``): 2,873 refs
offered, 2,873 persisted. Not for want of running — its settled query returns
602 rows across 62 of the 240 day-batches — but no arriving key collides with a
stored one, because every family that puts an update on a filed thread either
names a different application (#454's identity component doing its job) or
scores above the auto-file gate and never reaches the review path at all.

So the population is empty by construction, and an empty population cannot say
whether the machinery is right. This module constructs it.

IT MEASURES REACHABILITY AND COST. IT CANNOT MEASURE A RATE. Everything here is
invented mail chosen to land in the class; the frequency of the class in a real
mailbox is not a thing a corpus can report, and no number in this file should
ever be extrapolated to one. The read-only count against real stored mail is the
only instrument that can answer that, and it is not this one.

The class, and the two routes into it
-------------------------------------

An UNCERTAIN UPDATE — a lifecycle verdict in ``[REVIEW_FLOOR, AUTO_FILE_GATE)``,
so the queue and not the board — arriving on the SAME thread AND the SAME
identity as a message already filed on a live card.

The asymmetry that makes it constructible is in the plumbing rather than in the
predicate. ``pipeline.ReviewItem`` carries no identity fields, so
``_persist_review_items_additive`` builds its ``MessageRef`` with
``identity_role=None, identity_req_id=None`` and ``review_dedup_key`` RE-DERIVES
the sub-key from subject and snippet; the stored side reads the columns the
scan wrote from the body. Two routes make those agree:

* **requisition id** — both messages print the employer's own number. The
  cascade is ``req_id or role_token``, so both sides key on the number.
  ``trigger-req-id`` and ``trigger-second-wording``.
* **neither names anything** — the stored row holds ``("", "")``, which
  ``identity_parts`` reads as a derived "names nothing" and resolves to
  ``None``; the arriving message derives ``None`` from text that names nothing
  either. Two ``None`` sub-keys are the SAME unknown by design (it is what keeps
  one employer's two identical acknowledgements a single decision), so the keys
  collide with no requisition id anywhere. ``trigger-anonymous``.

The second route matters more than the first: it means the class does not need
an ATS that prints a number. It needs an employer whose acknowledgement and
whose later update both decline to name the job — which is the ordinary shape
``update-joins-one-application`` is built from, and the reason that family
misses this is that its update scores 0.90+ and auto-files.

The controls
------------

A drop count with nothing beside it proves nothing about the boundary, so three
messages sit one edit away from a trigger and must be KEPT — and "kept" is
asserted as *offered to the filter AND holding a row afterwards*, never as
"absent from the dropped set", which a message that never reached the filter
would also satisfy.

* ``control-other-req-id``   — the same offer, one digit different in the
  requisition number. Different application, same thread. #454's component.
* ``control-other-thread``   — the same offer, same requisition number, a
  different Gmail conversation. The thread component.
* ``control-queued-not-filed`` — the same collision, but the earlier message
  scored 0.70 and is sitting in the QUEUE rather than on a card, so nothing
  answers for it. The settlement arm.

Test data
---------

Wholly invented employers on RFC-reserved, un-routable domains (``.test``), per
``docs/TEST_DATA_POLICY.md``. No wording, employer, requisition number or
address here comes from a real mailbox: the bodies are written to land in a
confidence band, and the band is the only thing about them that is real. Every
body is shorter than Gmail's snippet cut, so ``delivered`` and the stored
snippet are the same text and the identity derivation cannot depend on which
one a reader takes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlmodel import select

from jobtracker.cloud import applications, pipeline
from jobtracker.cloud.applications import Email
from tests.corpus_independent import harness
from tests.corpus_independent.generate import Case, snippet_of
from tests.corpus_independent.harness import classify_all, replay

#: The harness's user. Imported rather than re-declared: a second uuid here
#: would read the board of a user the replay never wrote to, and every count
#: would be zero for the wrong reason.
_USER: uuid.UUID = harness._USER

_EPOCH = datetime(2026, 3, 2, 9, 15)

_FAMILY = "settled-filter-class"

#: WRITTEN OUT, one literal per employer, and never assembled from the token at
#: runtime. `scripts/check_test_data.py` matches ADDRESSES IN THE TEXT with a
#: regex, and `careers@{token}.test` contains a brace where the domain starts —
#: so an f-string address matches nothing and the gate stays green whatever the
#: domain later becomes. Measured: the same file with `.test` swapped for a real
#: TLD still scanned as zero hits while the senders were interpolated. A gate
#: that cannot see the material it exists to police is this repository's
#: recurring defect, so the material is put where it can see it. Every domain
#: here is RFC-reserved and un-routable (`docs/TEST_DATA_POLICY.md`).
_SENDERS = {
    "kelvedon": "careers@kelvedon.test",
    "marrowby": "careers@marrowby.test",
    "penhale": "careers@penhale.test",
    "quillon": "careers@quillon.test",
    "tarnwick": "careers@tarnwick.test",
    "vexley": "careers@vexley.test",
    "zarnow": "careers@zarnow.test",
}


def _case(
    *,
    mid: str,
    thread: str,
    subject: str,
    body: str,
    sender: str,
    sender_name: str,
    day: int,
    expected_category: str,
    identity: str,
    employer: str,
    note: str,
) -> Case:
    """One message, in the shape ``harness.replay`` consumes.

    ``delivered`` is the SNIPPET and not the body, which is what a cloud scan
    hands the classifier for mail whose body it never fetched. Every body below
    is under the 186-character cut, so the two are byte-identical here and the
    choice changes no number — it is written this way so that lengthening a body
    later cannot silently make the instrument more generous than the product.
    """

    return Case(
        message_id=mid,
        thread_id=thread,
        subject=subject,
        sender=sender,
        sender_name=sender_name,
        body=body,
        delivered=snippet_of(body),
        received_at=_EPOCH + timedelta(days=day),
        family=_FAMILY,
        expected_category=expected_category,
        identity=identity,
        employer=employer,
        note=note,
    )


def _confirmation_named(
    display: str, token: str, req: str, thread: str, mid: str, day: int
) -> Case:
    """An acknowledgement that prints the role AND the requisition id. Auto-files."""

    return _case(
        mid=mid,
        thread=thread,
        subject=f"Thank you for applying to {display} ({req})",
        body=(
            f"Hi Ayush, Thank you for applying to the Backend Engineer position at "
            f"{display} (requisition {req}). Your application has been received and "
            "is being reviewed."
        ),
        sender=_SENDERS[token],
        sender_name=f"{display} Recruiting",
        day=day,
        expected_category="applied",
        identity=f"{token}|{req}",
        employer=token,
        note="clears the auto-file gate and mints the card the update must join",
    )


def _confirmation_anonymous(display: str, token: str, thread: str, mid: str, day: int) -> Case:
    """An acknowledgement that names no role and no number. Still auto-files."""

    return _case(
        mid=mid,
        thread=thread,
        subject="Your application has been received",
        body=(
            f"Hi Ayush, Thanks for applying to {display}. Our team will review your "
            "application shortly."
        ),
        sender=_SENDERS[token],
        sender_name=f"{display} Recruiting",
        day=day,
        expected_category="applied",
        identity=f"{token}|__ack__",
        employer=token,
        note="names nothing; the card is correctly blank and the sub-key is None",
    )


def _offer_named(
    display: str, token: str, req: str, thread: str, mid: str, day: int, note: str
) -> Case:
    """An offer that prints the requisition id. Scores below the auto-file gate."""

    return _case(
        mid=mid,
        thread=thread,
        subject=f"An offer from {display} ({req})",
        body=(
            f"Hi Ayush, We are delighted to extend you an offer to join us on "
            f"requisition {req}. The written terms are attached for your review."
        ),
        sender=_SENDERS[token],
        sender_name=f"{display} Recruiting",
        day=day,
        expected_category="offer",
        identity=f"{token}|{req}",
        employer=token,
        note=note,
    )


def _offer_anonymous(display: str, token: str, thread: str, mid: str, day: int, note: str) -> Case:
    """An offer that names neither role nor number. Below the gate."""

    return _case(
        mid=mid,
        thread=thread,
        subject=f"An offer from {display}",
        body=(
            "Hi Ayush, We are delighted to extend you an offer to join us. The "
            "written terms are attached for your review."
        ),
        sender=_SENDERS[token],
        sender_name=f"{display} Recruiting",
        day=day,
        expected_category="offer",
        identity=f"{token}|__ack__",
        employer=token,
        note=note,
    )


def _soft_interview(
    display: str, token: str, req: str, thread: str, mid: str, day: int, note: str
) -> Case:
    """A second WORDING in the same band, so the number is not one template's."""

    return _case(
        mid=mid,
        thread=thread,
        subject=f"{display} ({req})",
        body=(
            f"Hi Ayush, The hiring team for requisition {req} would like to speak "
            "with you further. Someone will reach out to arrange a conversation."
        ),
        sender=_SENDERS[token],
        sender_name=f"{display} Recruiting",
        day=day,
        expected_category="interview",
        identity=f"{token}|{req}",
        employer=token,
        note=note,
    )


#: The messages that MUST be refused by the settled filter on the additive path.
TRIGGERS = ("t630-offer-req", "t630-offer-anon", "t630-interview-req")

#: The messages one edit away that must NOT be refused.
CONTROLS = ("t630-offer-other-req", "t630-offer-other-thread", "t630-offer-unsettled")

#: The trigger that shares its DAY with the message that settles it, so the
#: whole loss happens inside one sync rather than across two.
SAME_BATCH_TRIGGER = "t630-offer-same-batch"


def family() -> list[Case]:
    """The corpus family. Six scenarios, each an employer of its own.

    ONE EMPLOYER AND ONE THREAD PER SCENARIO, deliberately. ``collect_review_items``
    de-duplicates within a batch on the same ``review_dedup_key`` this filter
    uses, so two scenarios sharing a thread would let a within-sync collapse
    masquerade as a cross-sync suppression.
    """

    return [
        # 1. THE CLASS, via the employer's own requisition number.
        _confirmation_named(
            "Kelvedon", "kelvedon", "R-40080", "t630-th-kelvedon", "t630-ack-kelvedon", 0
        ),
        _offer_named(
            "Kelvedon",
            "kelvedon",
            "R-40080",
            "t630-th-kelvedon",
            "t630-offer-req",
            9,
            note="same thread, same requisition, below the gate: the class",
        ),
        # 2. THE CLASS, with no requisition id anywhere. Both sub-keys are None.
        _confirmation_anonymous("Marrowby", "marrowby", "t630-th-marrowby", "t630-ack-marrowby", 0),
        _offer_anonymous(
            "Marrowby",
            "marrowby",
            "t630-th-marrowby",
            "t630-offer-anon",
            9,
            note="neither message names the job; the same unknown is the same key",
        ),
        # 3. THE CLASS again, different wording, so one template cannot own the number.
        _confirmation_named("Vexley", "vexley", "R-70030", "t630-th-vexley", "t630-ack-vexley", 0),
        _soft_interview(
            "Vexley",
            "vexley",
            "R-70030",
            "t630-th-vexley",
            "t630-interview-req",
            9,
            note="an interview nudge in the same band as the offers",
        ),
        # 4. CONTROL — one digit different in the requisition number.
        _confirmation_named(
            "Penhale", "penhale", "R-50010", "t630-th-penhale", "t630-ack-penhale", 0
        ),
        _offer_named(
            "Penhale",
            "penhale",
            "R-50011",
            "t630-th-penhale",
            "t630-offer-other-req",
            9,
            note="a DIFFERENT application on the same thread: must be asked about",
        ),
        # 5. CONTROL — same requisition number, a different conversation.
        _confirmation_named(
            "Quillon", "quillon", "R-60020", "t630-th-quillon-a", "t630-ack-quillon", 0
        ),
        _offer_named(
            "Quillon",
            "quillon",
            "R-60020",
            "t630-th-quillon-b",
            "t630-offer-other-thread",
            9,
            note="the identity matches and the thread does not: must be asked about",
        ),
        # 6. CONTROL — the same collision, but nothing is settled: the earlier
        #    message is itself below the gate, so it is in the queue and on no
        #    card, and no application answers for it.
        #
        #    THE COLLISION IS REAL HERE AND IS NOT RE-DERIVED TO PROVE IT.
        #    Spelling `review_dedup_key` out again would make this control a
        #    copy of the thing it is measuring, so the premise was established
        #    by EXECUTION instead: replacing the first message below with
        #    `_confirmation_named` at the same employer, thread and requisition
        #    — one edit, and the only one that changes is that it clears the
        #    auto-file gate and mints a card — takes `suppressed` from four
        #    messages to five, the extra being `t630-offer-unsettled`. So the
        #    two keys DO collide and the settlement arm is the only thing
        #    keeping this message. Without that check the control could pass
        #    for having no collision at all, which would prove nothing.
        _offer_named(
            "Zarnow",
            "zarnow",
            "R-80040",
            "t630-th-zarnow",
            "t630-offer-unsettled-first",
            0,
            note="uncertain itself: queued, unlinked, settles nothing",
        ),
        _offer_named(
            "Zarnow",
            "zarnow",
            "R-80040",
            "t630-th-zarnow",
            "t630-offer-unsettled",
            9,
            note="same thread, same requisition, and still must be asked about",
        ),
        # 7. THE CLASS inside ONE sync. `upsert_applications_for_user` runs
        #    before the additive persist in `sync_gmail_pipeline_additive`, and
        #    the prefetch is deliberately not shielded from autoflush, so the
        #    card exists by the time the filter looks.
        _confirmation_named(
            "Tarnwick", "tarnwick", "R-90050", "t630-th-tarnwick", "t630-ack-tarnwick", 4
        ),
        _offer_named(
            "Tarnwick",
            "tarnwick",
            "R-90050",
            "t630-th-tarnwick",
            SAME_BATCH_TRIGGER,
            4,
            note="filed and refused in the same sync",
        ),
    ]


@dataclass
class PersistCalls:
    """WHICH persist function the replay actually crossed, counted rather than assumed.

    The defect this guards against has already happened here: a harness called
    ``_persist_review_items`` — the REBUILD persist — inside an additive-shaped
    loop, so the additive machinery was never exercised and a number attributed
    to it described a function that had not run. Both functions are wrapped, in
    both directions, so "the additive one ran" and "the rebuild one did not" are
    two assertions and not one.
    """

    additive: list[tuple[int, int]] = field(default_factory=list)
    rebuild: list[tuple[int, int]] = field(default_factory=list)
    offered_ids: set[str] = field(default_factory=set)

    @property
    def offered(self) -> int:
        return sum(o for o, _ in self.additive) + sum(o for o, _ in self.rebuild)

    @property
    def persisted(self) -> int:
        return sum(p for _, p in self.additive) + sum(p for _, p in self.rebuild)

    @property
    def dropped(self) -> int:
        """Offered minus persisted.

        Exact only while every ref is dated — the persist functions return a
        count of DATED refs — which :func:`_every_message_is_dated` asserts.
        """

        return self.offered - self.persisted


def _instrument(monkeypatch) -> PersistCalls:
    """Wrap both persist functions where their CALLERS look them up."""

    calls = PersistCalls()
    real_additive = applications._persist_review_items_additive
    real_rebuild = applications._persist_review_items

    async def additive(session, user_id, review):
        offered = len(review)
        calls.offered_ids.update(item.message_id for item in review)
        persisted = await real_additive(session, user_id, review)
        calls.additive.append((offered, persisted))
        return persisted

    async def rebuild(session, user_id, review):
        offered = len(review)
        calls.offered_ids.update(item.message_id for item in review)
        persisted = await real_rebuild(session, user_id, review)
        calls.rebuild.append((offered, persisted))
        return persisted

    monkeypatch.setattr(applications, "_persist_review_items_additive", additive)
    monkeypatch.setattr(applications, "_persist_review_items", rebuild)
    return calls


def _through_the_rebuild(monkeypatch) -> None:
    """Send ``harness.replay``'s day-batches to the Re-sync entrypoint instead.

    The batch construction, the rollup, ``collect_review_items`` and the board
    read are then IDENTICAL between the two runs, and the only thing that
    differs is which merge function the batch is handed to. Writing a second
    loop here would reintroduce exactly the defect :class:`PersistCalls`
    documents: two loops that are additive-shaped in different ways.

    ``coverage`` is deliberately omitted. With ``None`` the rebuild's two
    destructive steps — the contradiction sweep and ``_reset_review_queue`` —
    both no-op, which isolates the persist difference the issue is about from
    everything else the Re-sync button does.
    """

    async def shim(session, user_id, rolled, review):
        return await applications.purge_and_rebuild_gmail_pipeline(session, user_id, rolled, review)

    monkeypatch.setattr(harness, "sync_gmail_pipeline_additive", shim)


async def _rows_for(session, message_ids) -> set[str]:
    """The message ids the ``emails`` table holds a row for."""

    return set(
        (
            await session.exec(
                select(Email.message_id).where(
                    Email.user_id == _USER, Email.message_id.in_(list(message_ids))
                )
            )
        ).all()
    )


def _every_message_is_dated(cases: list[Case]) -> None:
    """The precondition that makes ``offered - persisted`` an exact drop count."""

    undated = [c.message_id for c in cases if c.received_at is None]
    assert undated == [], f"undated cases would be miscounted by the persist return: {undated}"


def test_the_family_lands_in_the_band_the_class_needs() -> None:
    """Before any replay: the classifier puts these where the class requires.

    A trigger that auto-filed would never reach the review path, and a trigger
    under the floor would be dropped by ``collect_review_items`` long before the
    settled filter saw it. Either way the drop count would be 0 for a reason
    that has nothing to do with #630, so the band is asserted rather than
    assumed — and asserted per message, because "the family is in the band" is
    satisfied by one message being in it.
    """

    cases = family()
    _every_message_is_dated(cases)
    verdicts = {v.case.message_id: v for v in classify_all(cases)}

    uncertain = set(TRIGGERS) | set(CONTROLS) | {SAME_BATCH_TRIGGER, "t630-offer-unsettled-first"}
    for mid in sorted(uncertain):
        v = verdicts[mid]
        assert pipeline.REVIEW_FLOOR <= v.confidence < pipeline.AUTO_FILE_GATE, (
            f"{mid} scored {v.category} at {v.confidence}, outside "
            f"[{pipeline.REVIEW_FLOOR}, {pipeline.AUTO_FILE_GATE})"
        )
        assert v.category in pipeline.JOB_LIFECYCLE_CATEGORIES and v.category != "follow_up"

    for mid in sorted(set(verdicts) - uncertain):
        v = verdicts[mid]
        assert v.confidence >= pipeline.AUTO_FILE_GATE, (
            f"{mid} scored {v.category} at {v.confidence}; it must auto-file to "
            "mint the card that settles the thread"
        )


async def test_the_additive_persist_refuses_an_uncertain_update_to_a_filed_card(
    test_session, monkeypatch
) -> None:
    """THE NUMBER. The class is constructible, and the counter moves off 0.

    Four claims, each asserted rather than inferred:

    1. the replay crossed ``_persist_review_items_additive`` and NOT
       ``_persist_review_items``;
    2. the drop count, taken two independent ways that must agree — the persist
       function's own ``offered - returned``, and the harness's observation of
       which offered ids the database holds a row for afterwards;
    3. every dropped message has NO ``emails`` row and is in NO queue;
    4. the three controls reached the filter AND kept their row AND are in the
       queue, so the boundary is directional and not merely "nothing else moved".
    """

    cases = family()
    _every_message_is_dated(cases)
    calls = _instrument(monkeypatch)

    replayed = await replay(test_session, classify_all(cases))

    # 1 — the entrypoint, in both directions.
    assert calls.additive, "the replay never reached the additive persist"
    assert calls.rebuild == [], (
        "the replay crossed the REBUILD persist; the number would be another function's"
    )

    # 2 — the drop, two ways.
    expected = set(TRIGGERS) | {SAME_BATCH_TRIGGER}
    # WHAT THE DATABASE SAYS first — offered ids the tables hold no row for. It
    # is an observation, where the line below is the persist function's own
    # report of itself, and a report that disagreed with the tables would be the
    # more interesting failure of the two.
    assert replayed.suppressed == expected
    assert calls.dropped == len(expected)
    assert len(replayed.suppressed) == calls.dropped

    # 3 — what the drop costs: no row, no queue entry.
    assert await _rows_for(test_session, expected) == set()
    assert replayed.reviewed & expected == set()
    # And it is not that they never got as far as the filter.
    assert expected <= calls.offered_ids

    # 4 — the controls, one edit away, kept.
    controls = set(CONTROLS)
    assert controls <= calls.offered_ids, "a control that never reached the filter proves nothing"
    assert await _rows_for(test_session, controls) == controls
    assert controls <= replayed.reviewed
    assert replayed.suppressed & controls == set()


async def test_the_rebuild_persist_keeps_every_message_the_additive_one_drops(
    test_session, monkeypatch
) -> None:
    """THE ASYMMETRY, in the direction #630 claims.

    Same family, same batches, same rollup — the only change is which merge
    function each day-batch is handed to. The rebuild path has no settled
    filter, so it stores and queues every message the additive path refuses.

    That is the shape of the defect rather than a second defect: the path a
    user's routine and auto syncs take is the one that loses the message, and
    the path behind a button they have to press is the one that does not.
    """

    cases = family()
    _every_message_is_dated(cases)
    calls = _instrument(monkeypatch)
    _through_the_rebuild(monkeypatch)

    replayed = await replay(test_session, classify_all(cases))

    assert calls.rebuild, "the replay never reached the rebuild persist"
    assert calls.additive == [], "the replay crossed the ADDITIVE persist; this is the other run"

    dropped_by_the_additive_path = set(TRIGGERS) | {SAME_BATCH_TRIGGER}

    assert calls.dropped == 0
    assert replayed.suppressed == set()
    assert (
        await _rows_for(test_session, dropped_by_the_additive_path) == dropped_by_the_additive_path
    )
    assert dropped_by_the_additive_path <= replayed.reviewed
