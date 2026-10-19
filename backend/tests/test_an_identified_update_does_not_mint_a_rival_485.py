"""Where an identified update lands when it matches no cluster — #485.

`_role_from_dash_run` turns a Lever rejection from mail carrying NO identity
into mail carrying one, and that is not a free improvement. It moves the
message from `partition_applications`' pass 2, where a role-less update is
placed by rule 3 or sent to the review queue, into pass 1, where an identified
item that matches nothing MINTS. At the employer this issue opens with — two
anonymous rows, then the rejection whose subject names the role — minting is
the failure: a third, rejected, card appears beside two open ones and the queue
row that had been asking WHICH application the mail was about goes silent.

So the reader ships with a placement ladder, and the ladder is written as a
DIFF AGAINST MINTING because that is the only safe way to read it. Every arm
that mints is what `main` does today; two arms diverge and both are asserted
below.

THE FIRST VERSION OF THAT LADDER WAS A NET REGRESSION AND THE CORPUS CAUGHT IT,
which is why this file exists in the shape it does. That version treated
"matches no cluster" as "cannot choose" and queued everything it could not
join, gated on `known_multi`. Replayed over the 18,980-case corpus it moved
`card_overstates` 260 -> 322 and `addressed_on_a_card` 14,137 -> 13,941: 196
messages lost their card, and 62 cards were left reading `offered` with the
mail that makes them `rejected` sitting in the queue. The cause was not thread
attribution, which was the first diagnosis and was wrong. It was that a minted
cluster is not the end of the story — :func:`roll_up_applications` keys the
resolver on ``(employer, req_id or role_token)`` and matches terminal rows too,
so an identified item that mints is carried onto the stored card its token
names. Queueing it severs that.

THE THREE COMPOSITIONS THE FIRST VERSION WAS DESIGNED AGAINST ALL PASSED UNDER
IT. They were its author's own targets, so they graded nothing; the corpus
caught it because the corpus is independent. The five compositions after them
here are the ones that were missing, and each is a case where the first version
answered differently from `main` for the worse.

WHAT `main` DOES, measured rather than reasoned about, by running the same
eight compositions against `origin/main`'s `partition_applications`:

    A  two anonymous rows + the rejection   main: QUEUED       here: QUEUED
    B  one anonymous row  + the rejection   main: joins, card UNTITLED
                                            here: joins, card TITLED
    C  the rejection alone                  main: own card, untitled
                                            here: own card, titled
    D  ONE NAMED card, rejection names a    main: JOINS THE NAMED CARD and
       DIFFERENT role                             settles it terminally
                                            here: mints its own
    E  two NAMED cards, a third role        main: QUEUED    here: mints its own
    F  one named + one anonymous, a third   main: JOINS THE NAMED CARD
       role                                 here: mints its own
    G  one anonymous row, board already      main: QUEUED    here: mints, and
       holds several (`known_multi`)               the resolver decides
    H  the rejection MATCHES a named card   main: joins      here: joins

D and F are the ones worth reading twice. On `main` the Lever rejection carries
no role, so pass 2 rule 3 — "names no role at all, and the employer has exactly
one cluster" — carries it onto that cluster whatever the cluster is about, and
`advance_application_status` treats the resulting terminal status as final. A
rejection for one job settles the card of another. That is correct handling of
mail that genuinely names nothing and it stops being correct the moment the
subject is read, which is what this ladder is for.

Every particular below is invented, per `docs/TEST_DATA_POLICY.md`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from jobtracker.cloud import pipeline

EMPLOYER = "Northwind Labs"
TOKEN = "northwind"
DOMAIN = "northwind.example"
CANDIDATE = "Jane Doe"
#: Three roles that share no leading word, so `matches_company_token` and
#: `_may_join` cannot confuse any two of them.
ROLE = "Backend Engineer"
OTHER_ROLE = "Mechanical Engineer"
THIRD_ROLE = "Data Scientist"

_EPOCH = datetime(2026, 3, 2, 9, 0)


def _item(message_id: str, category: str, subject: str, body: str, day: int):
    return pipeline.PipelineItem(
        message_id=message_id,
        category=category,
        sender_email=f"no-reply@{DOMAIN}",
        subject=subject,
        sender_name=f"{EMPLOYER} Recruiting",
        received_at=_EPOCH + timedelta(days=day),
        confidence=0.95,
        snippet=body,
    )


def _anonymous_ack(message_id: str, day: int):
    """A confirmation that names no role. Supabase's and Twitch's real shape."""
    return _item(
        message_id,
        "applied",
        f"Thank you for applying to {EMPLOYER}",
        f"Hi, thank you for applying to {EMPLOYER}. Your application has been "
        "received and our team will review it shortly.",
        day,
    )


def _named_ack(message_id: str, role: str, day: int):
    return _item(
        message_id,
        "applied",
        f"Thank you for applying to {EMPLOYER}",
        f"Hi, thank you for applying to the {role} position at {EMPLOYER}. "
        "Your application has been received.",
        day,
    )


def _lever_rejection(message_id: str, role: str, day: int):
    """The subject this whole issue is about, and it is what makes the item identified."""
    return _item(
        message_id,
        "rejection",
        f"Thank you from {EMPLOYER} - {CANDIDATE} - {role}",
        f"Hi, we will not be proceeding with your candidacy for this role at "
        f"{EMPLOYER}.",
        day,
    )


def _partition(items, known_multi: frozenset[str] = frozenset()):
    return pipeline.partition_applications(items, known_multi=known_multi)


def _tokens(clusters) -> list[str | None]:
    return [c.role_token for c in clusters]


def _cluster_holding(clusters, message_id: str):
    for cluster in clusters:
        if any(i.message_id == message_id for i in cluster.items):
            return cluster
    return None


def test_the_reader_makes_the_rejection_identified() -> None:
    """THE PREMISE, asserted rather than assumed.

    Every composition below turns on this message carrying an identity. If the
    reader stopped reading this subject the whole file would still pass — the
    item would take pass 2's role-less path and land where `main` lands it —
    and would be grading nothing at all.
    """

    subject = f"Thank you from {EMPLOYER} - {CANDIDATE} - {ROLE}"
    assert pipeline._role_from_subject(subject) == ROLE
    assert pipeline.application_sub_key(subject, "") == pipeline.normalize_role_token(
        ROLE
    )


# ------------------------------------------------- the three original targets


def test_two_anonymous_rows_do_not_gain_a_rival_card() -> None:
    """A. The composition #485 opens with, and the reason the ladder exists.

    Two applications at one employer, neither naming a role, then the rejection
    whose subject names one. There is no way to tell WHICH of the two it is
    about — the rows are anonymous, so nothing on either can be compared with
    the role that was just read — and answering that question is what the
    review queue is for.
    """

    clusters, unplaced = _partition(
        [
            _anonymous_ack("ack-1", day=0),
            _anonymous_ack("ack-2", day=3),
            _lever_rejection("rej-1", ROLE, day=6),
        ]
    )

    assert len(clusters) == 2, _tokens(clusters)
    assert _tokens(clusters) == [None, None]
    assert [i.message_id for i in unplaced] == ["rej-1"]


def test_a_single_anonymous_row_gains_the_title_it_was_missing() -> None:
    """B. The nine blank cards, and what the reader is FOR.

    One application, no role in the confirmation, and a rejection that spells
    it. The card keeps its identity and gains a name — which on `main` it never
    does, because the rejection carries no role there either.
    """

    clusters, unplaced = _partition(
        [_anonymous_ack("ack-1", day=0), _lever_rejection("rej-1", ROLE, day=6)]
    )

    assert len(clusters) == 1 and not unplaced
    assert clusters[0].role == ROLE
    assert clusters[0].role_token == pipeline.normalize_role_token(ROLE)
    assert {i.message_id for i in clusters[0].items} == {"ack-1", "rej-1"}


def test_a_rejection_whose_confirmation_never_arrived_is_an_application() -> None:
    """C. Mint, and mint TITLED.

    An employer whose only mail is a rejection really did receive an
    application; the acknowledgement was filtered, deleted, or never sent. A
    card is the right answer and it is the reader that lets that card have a
    name.
    """

    clusters, unplaced = _partition([_lever_rejection("rej-1", ROLE, day=6)])

    assert len(clusters) == 1 and not unplaced
    assert clusters[0].role == ROLE


# ------------------------------------------- the five the first version missed


def test_a_rejection_for_a_different_role_does_not_settle_the_named_card() -> None:
    """D. THE CONTRADICTION, and the one arm that fixes a `main` behaviour.

    The employer's single card is `Mechanical Engineer`. The rejection names
    `Backend Engineer`. `_may_join` refuses the pair — two different tokens is
    the one thing it treats as disqualifying — and a fallback that joined "the
    only cluster" anyway would file a rejection for one job onto the card of
    another and, because `advance_application_status` treats a terminal status
    as final, freeze it against every later interview or offer.

    `main` does exactly that, and correctly: there the rejection names nothing,
    so rule 3 carries it. Reading the role is what makes joining wrong.
    """

    clusters, unplaced = _partition(
        [
            _named_ack("ack-1", OTHER_ROLE, day=0),
            _lever_rejection("rej-1", ROLE, day=6),
        ]
    )

    assert not unplaced
    named = _cluster_holding(clusters, "ack-1")
    rejected = _cluster_holding(clusters, "rej-1")
    assert named is not rejected, "the rejection settled a card for another job"
    assert named.role_token == pipeline.normalize_role_token(OTHER_ROLE)
    assert rejected.role_token == pipeline.normalize_role_token(ROLE)
    assert [i.message_id for i in named.items] == ["ack-1"]


def test_two_named_cards_and_a_third_role_mints_rather_than_asks() -> None:
    """E. Not every unmatched update is an ambiguous one.

    Both cards name a role and neither is this one, so there is no question to
    put to the user: the answer is "neither". The item's own token is a better
    answer than a queue row, and it is what `roll_up_applications` keys the
    resolver on downstream. The first version of the ladder queued this.
    """

    clusters, unplaced = _partition(
        [
            _named_ack("ack-1", OTHER_ROLE, day=0),
            _named_ack("ack-2", THIRD_ROLE, day=3),
            _lever_rejection("rej-1", ROLE, day=6),
        ]
    )

    assert not unplaced
    minted = _cluster_holding(clusters, "rej-1")
    assert minted.role_token == pipeline.normalize_role_token(ROLE)
    assert [i.message_id for i in minted.items] == ["rej-1"]


def test_a_mixed_employer_does_not_reach_the_queue_arm() -> None:
    """F. The queue arm requires EVERY cluster to name nothing.

    One named card and one anonymous one. `all(...)` is false, so this takes
    the mint arm rather than the queue arm — and that is the residual named in
    `partition_applications`: minting here may put a rival beside the anonymous
    row. It is `main`'s answer, so the ladder is no worse than the tree it
    lands on, and it is recorded here rather than left to be discovered.
    """

    clusters, unplaced = _partition(
        [
            _named_ack("ack-1", OTHER_ROLE, day=0),
            _anonymous_ack("ack-2", day=3),
            _lever_rejection("rej-1", ROLE, day=6),
        ]
    )

    assert not unplaced
    minted = _cluster_holding(clusters, "rej-1")
    assert minted.role_token == pipeline.normalize_role_token(ROLE)
    assert [i.message_id for i in minted.items] == ["rej-1"]


def test_a_board_already_holding_several_mints_and_lets_the_resolver_decide() -> None:
    """G. `known_multi` gates the STAMP, never the mint.

    The board holds several applications at this employer and today's batch
    holds one anonymous confirmation. Stamping the rejection's title onto
    whichever row happened to arrive today is the guess this function's
    docstring refuses for role-less mail, so the stamp arm is gated. Minting is
    not a guess: the cluster carries the token, and the resolver keys on
    `(employer, req_id or role_token)` and matches terminal rows too, so the
    stored card this rejection is actually about is the one it reaches.

    ASSERTED ON THE TOKEN, not on "it did not reach the queue". An absence
    passes for the wrong reason; the token is the thing the resolver reads.
    """

    clusters, unplaced = _partition(
        [_anonymous_ack("ack-1", day=0), _lever_rejection("rej-1", ROLE, day=6)],
        known_multi=frozenset({TOKEN}),
    )

    assert not unplaced
    anonymous = _cluster_holding(clusters, "ack-1")
    minted = _cluster_holding(clusters, "rej-1")
    assert anonymous is not minted
    assert anonymous.role_token is None, "the stamp arm fired at a known_multi employer"
    assert minted.role_token == pipeline.normalize_role_token(ROLE)


def test_a_rejection_that_matches_a_named_card_joins_it() -> None:
    """H. Arm 1, and it is not a divergence at all.

    `_may_join` finds the cluster, so this never reaches the ladder. Here
    because a ladder that broke the ordinary case would still pass every test
    above it.
    """

    clusters, unplaced = _partition(
        [_named_ack("ack-1", ROLE, day=0), _lever_rejection("rej-1", ROLE, day=6)]
    )

    assert len(clusters) == 1 and not unplaced
    assert {i.message_id for i in clusters[0].items} == {"ack-1", "rej-1"}


# --------------------------------------------------------------- the controls


def test_a_confirmation_is_never_deferred() -> None:
    """The deferral is scoped to UPDATES, and this is what says so.

    "A NEW CONFIRMATION IS A NEW APPLICATION. AN UPDATE IS NOT" is pass 2's
    rule, and pass 1 now applies it to identified mail too. A confirmation
    naming a third role at an employer holding two anonymous rows must still
    mint — it asserts an application, and sending it to the queue is how a
    second application to one employer stops appearing at all.
    """

    clusters, unplaced = _partition(
        [
            _anonymous_ack("ack-1", day=0),
            _anonymous_ack("ack-2", day=3),
            _named_ack("ack-3", ROLE, day=6),
        ]
    )

    assert not unplaced, "a confirmation took the update ladder"
    minted = _cluster_holding(clusters, "ack-3")
    assert minted.role_token == pipeline.normalize_role_token(ROLE)
    assert [i.message_id for i in minted.items] == ["ack-3"]


@pytest.mark.parametrize("count", [2, 3, 4])
def test_the_queue_arm_needs_two_anonymous_clusters_not_one(count: int) -> None:
    """The boundary, sat on from both sides.

    One anonymous cluster is the stamp arm; two or more is the queue arm. A
    threshold asserted only at its far side is a threshold nothing pins.
    """

    acks = [_anonymous_ack(f"ack-{k}", day=k * 3) for k in range(count)]
    clusters, unplaced = _partition([*acks, _lever_rejection("rej-1", ROLE, day=30)])

    assert [i.message_id for i in unplaced] == ["rej-1"]
    assert _tokens(clusters) == [None] * count


def test_one_anonymous_cluster_is_the_stamp_arm() -> None:
    """The other side of the same boundary, written out so neither is implied."""

    clusters, unplaced = _partition(
        [_anonymous_ack("ack-0", day=0), _lever_rejection("rej-1", ROLE, day=30)]
    )

    assert not unplaced
    assert _tokens(clusters) == [pipeline.normalize_role_token(ROLE)]
