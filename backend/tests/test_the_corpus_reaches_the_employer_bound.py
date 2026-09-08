"""The corpus can now disprove the 300-character employer bound — #737.

WHAT WAS WRONG WITH THE OLD EVIDENCE. #581 bounds an employer display name at
``pipeline._MAX_COMPANY_LEN`` on four separate paths, and what was offered for
"300 does not refuse real mail" was a per-message diff of the corpus against
the same run with the bound lifted to 1e9: **zero movers**. Measured on
``tests/corpus/`` at the commit before this module existed:

    cases                                          202
    longest sender_name                             36
    longest subject                                 67
    longest display ``resolve_employer`` produced   19
    movers with the bound lifted to 1e9              0

Nothing came within 264 characters of the bound. The zero was arithmetic, not
evidence — a control whose expected value is exactly what the failure mode also
returns, which is the shape the estate records as
``a-measurement-that-cannot-return-positive``. A bound of 300 and a bound of 30
would both have produced it.

WHAT THIS MODULE PINS. ``tests/corpus/generator.py``'s
``_axis_employer_name_length`` puts a message on each side of the threshold on
every door this corpus can reach, and this asserts the diff MOVES for the
past-bound ones and does NOT move for the on-bound ones. Measured 2026-09-08,
in one run, over a corpus of 210 cases of which 202 predate the axis — the two
sizes are dated rather than asserted on purpose, because
``test_adversarial_corpus.py`` deliberately declines to pin the corpus's size
and a figure in prose is not a constant:

    movers, cases predating the axis                 0     <- the old zero
    movers, whole corpus                             4     <- one per door
    longest display, cases predating the axis       19
    longest display, whole corpus                  300

Everything in that table except the two sizes IS asserted below, so the numbers
that carry the argument cannot go stale silently.

WHAT IT DOES NOT PIN, and this is the honest half. It does not show that 300 is
the RIGHT number. Nothing in a corpus of invented mail can: no invented
employer name is evidence about real ones. What it shows is that the corpus can
now register the difference, so the next person raising or lowering the
constant has a measurement to re-run instead of a zero that was never able to
be anything else.

THESE FIXTURES ARE ADVERSARIAL BUT ADMISSIBLE. No employer registers a
300-character name and DNS caps a label at 63, so none of this is realistic
mail — but every past-bound case fits through ``ScannedMessageIn``, the wire
model that carries exactly these three fields (313 of 512 for the display name,
317 of 512 for the address, 321 of 2000 for the subject). Nothing in front of
the pipeline refuses them, so ``_MAX_COMPANY_LEN`` really is the only thing
that does, which is what makes the corpus able to argue about its value.
``test_every_past_bound_fixture_is_admissible_at_the_wire`` asserts it rather
than leaving it here as a claim.

THE FOUR DOORS AND WHICH ARE REACHABLE. ``jobtracker/limits.py`` names them;
this corpus mints ``PipelineItem`` mail, so:

===  ==========================================  ==========================
#    door                                        reachable from this corpus
===  ==========================================  ==========================
1    ``ReviewClassifyRequest.company``           NO — an HTTP body, not mail
2    sender display name, step 3                 yes, ``item.sender_name``
3    ``sender_email`` -> ``_brand_display``      yes, ``item.sender_email``
4    subject (anchored, and leading segment)     yes, ``item.subject``
===  ==========================================  ==========================

Door 1 keeps its synthetic on-boundary cover in
``test_an_employer_name_is_bounded.py``. It is not merely absent from the
corpus: ``test_lifting_the_bound_does_not_reach_door_one`` below shows the
lifting instrument used by every number above is BLIND to it, because
``ReviewClassifyRequest.company``'s ``max_length`` is frozen at class
definition and no monkeypatch of the module constant reaches it. A door-1
"non-mover" would therefore have meant nothing at all.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jobtracker.cloud import pipeline
from jobtracker.cloud.applications import ReviewClassifyRequest, ScannedMessageIn
from tests.corpus.generator import (
    BOUND_AT,
    BOUND_AXIS,
    BOUND_CASES,
    PAST_BOUND,
    Case,
    generate,
)

CASES = generate()

#: How many of the corpus resolve to an employer at all, as a FLOOR. This is
#: the positive control the whole module rests on and the reason it is stated
#: as a number rather than assumed: a census written against the wrong shape
#: resolves nothing, reports a clean "0 movers", and is indistinguishable from
#: a pass. Measured at 187 of 210 on 2026-09-08. Floor, not a target — it may
#: rise freely and a fall means messages stopped naming an employer.
RESOLVED_FLOOR = 150

#: Longest display the corpus produced BEFORE this axis existed, and the whole
#: reason #737 was filed: 19 characters against a 300-character bound. A
#: CEILING on the cases that predate the axis, so if ordinary corpus growth
#: ever reaches into the bound's neighbourhood on its own, this reds and says
#: the axis's claim to be the only thing with reach needs re-measuring.
REACH_WITHOUT_THE_AXIS = 40


def _census(cases: list[Case]) -> dict[str, tuple[str, str] | None]:
    """Every case's resolved ``(token, display)``, keyed by message id.

    NO ``getattr`` WITH A DEFAULT, ANYWHERE, and that is the point of this
    docstring. ``Case`` has no ``sender`` or ``subject`` attribute — it wraps a
    ``PipelineItem`` and the fields are reached through ``case.item``. A census
    written against the wrong shape and read defensively resolves 0 of 202
    cases and reports a clean zero movers, which looks identical to a real
    pass; that exact mistake was made and caught during #581's verification and
    is the reason #737 exists. Reached through ``case.item``, a wrong shape
    raises ``AttributeError`` and is loud.
    """

    return {
        case.item.message_id: pipeline.resolve_employer(
            case.item.sender_email, case.item.subject, case.item.sender_name
        )
        for case in cases
    }


def _ids(side: str) -> set[str]:
    """Message ids of the bound axis's ``on`` or ``past`` cases.

    Matched on the mail itself — sender, display name, subject — rather than on
    a hard-coded id, so a renumbering of the corpus cannot silently empty the
    set this module compares against.
    """

    wanted = {(c.sender, c.sender_name, c.subject) for c in BOUND_CASES if c.side == side}
    found = {
        case.item.message_id
        for case in CASES
        if (case.item.sender_email, case.item.sender_name, case.item.subject) in wanted
    }
    assert len(found) == len(wanted), (
        f"{len(found)} corpus cases matched {len(wanted)} declared {side!r} "
        "fixtures. Every BOUND_CASES entry must reach the corpus; an "
        "unregistered one is invisible to every count below."
    )
    return found


# --------------------------------------------------------------------------
# The positive control, first, because nothing under it means anything without.
# --------------------------------------------------------------------------


def test_the_census_resolves_a_nonzero_number_of_cases() -> None:
    resolved = [v for v in _census(CASES).values() if v is not None]
    assert len(resolved) >= RESOLVED_FLOOR, (
        f"the census resolved only {len(resolved)} of {len(CASES)} cases. "
        "Below this floor every mover count in this module is measuring an "
        "empty set rather than the pipeline."
    )


def test_every_past_bound_fixture_is_admissible_at_the_wire() -> None:
    """Nothing in FRONT of the pipeline refuses these, so the bound is alone.

    ``ScannedMessageIn`` is the model the review-classify endpoint mints from a
    live scan, and it bounds the same three fields these fixtures load: 512 for
    ``sender_email`` and ``sender_name``, 2000 for ``subject``. They are NOT
    bounded at ``_MAX_COMPANY_LEN`` on purpose — a sender name is what an
    employer is extracted from, not an employer — and this asserts that on
    purpose too. A fixture the wire already rejected would prove nothing about
    the bound under test: it would never have reached it.
    """

    admitted = 0
    for case in BOUND_CASES:
        if case.side != "past":
            continue
        ScannedMessageIn(
            sender_email=case.sender,
            sender_name=case.sender_name,
            subject=case.subject,
            received_at="2026-09-08T00:00:00Z",
        )
        admitted += 1
    assert admitted == len([c for c in BOUND_CASES if c.side == "past"]) > 0


def test_the_bound_the_fixtures_were_built_against_is_the_shipped_one() -> None:
    """A recorded literal against the live constant, so a change is loud.

    ``BOUND_AT`` is hand-written in the generator, NOT imported from the
    pipeline: an expectation read from the thing it checks compares a value to
    itself and passes for every value. Provenance for 300 is the comment above
    ``_MAX_COMPANY_LEN`` in ``cloud/pipeline.py`` — 300 characters is at most
    1,200 UTF-8 bytes against the 2,704-byte btree index-row ceiling on
    ``ix_applications_company``, measured in #406.

    If this reds, the constant moved and the fixtures no longer sit on the
    bound. Re-measure them; do not re-baseline this line.
    """

    assert BOUND_AT == 300
    assert PAST_BOUND == 301
    assert pipeline._MAX_COMPANY_LEN == BOUND_AT


def test_every_reachable_door_has_a_case_on_each_side() -> None:
    """A threshold needs a case sitting ON it, and one just past it.

    Door 1 is absent by construction and by argument; see the module docstring
    and ``test_lifting_the_bound_does_not_reach_door_one``.
    """

    by_door: dict[str, set[str]] = {}
    for case in BOUND_CASES:
        by_door.setdefault(case.door, set()).add(case.side)
    assert by_door, "no bound fixtures are registered at all"
    for door, sides in sorted(by_door.items()):
        assert sides == {"on", "past"}, f"door {door} has only {sorted(sides)}"
    assert not any(door.startswith("1 ") for door in by_door), (
        "door 1 is an HTTP body, not mail; a corpus case claiming to cover it "
        "would be covering something else"
    )


def test_the_axis_carries_the_fields_the_other_gate_does_not_compare() -> None:
    """Determinism, for the two fields this axis puts the measurement in.

    ``test_adversarial_corpus.py::test_corpus_is_deterministic`` compares
    message id, subject, snippet and identity. This axis's payload is the
    SENDER NAME and the SENDER ADDRESS, so that gate would not have noticed a
    non-deterministic name here — and a corpus that differs between runs cannot
    be a regression gate.
    """

    def fields(cases: list[Case]) -> list[tuple[str, str | None, str]]:
        return [
            (c.item.sender_email, c.item.sender_name, c.item.subject)
            for c in cases
            if c.axis == BOUND_AXIS
        ]

    first, second = fields(generate()), fields(generate())
    assert first == second
    assert len(first) == len(BOUND_CASES) > 0


# --------------------------------------------------------------------------
# Directional: on the bound it resolves, one past it the corpus names nobody.
# --------------------------------------------------------------------------


def test_a_case_sits_exactly_on_the_bound() -> None:
    census = _census(CASES)
    for mid in sorted(_ids("on")):
        resolved = census[mid]
        assert resolved is not None, (
            f"{mid} sits exactly ON the bound and was refused. The bound is "
            "inclusive; refusing here means it is one lower than it claims."
        )
        assert len(resolved[1]) == BOUND_AT, (
            f"{mid} resolved to a {len(resolved[1])}-character display, not "
            f"{BOUND_AT}. The fixture reports its CONTENT, not its intent — a "
            "case that only means to sit on the boundary is not sitting on it."
        )


def test_a_case_one_character_past_the_bound_is_refused() -> None:
    census = _census(CASES)
    for mid in sorted(_ids("past")):
        assert census[mid] is None, (
            f"{mid} is {PAST_BOUND} characters and resolved to "
            f"{census[mid]!r}. Past the bound the message must name nobody and "
            "go to the review queue, not mint a card."
        )


def test_the_corpus_now_reaches_the_bound_and_did_not_before() -> None:
    census = _census(CASES)
    on_bound = _ids("on")
    older = [c for c in CASES if c.axis != BOUND_AXIS]
    older_reach = max((len(v[1]) for v in _census(older).values() if v is not None), default=0)
    whole_reach = max((len(v[1]) for v in census.values() if v is not None), default=0)
    assert older_reach <= REACH_WITHOUT_THE_AXIS, (
        f"the cases predating this axis now reach {older_reach} characters. "
        "If ordinary corpus growth has reached the bound's neighbourhood, this "
        "module's claim that the axis is what gives it reach needs re-measuring."
    )
    assert whole_reach == BOUND_AT, f"the corpus reaches {whole_reach} characters, not {BOUND_AT}"
    assert on_bound, "no on-bound case is in the corpus"


# --------------------------------------------------------------------------
# The measurement #737 asked for: run it both ways and watch the diff move.
# --------------------------------------------------------------------------


def test_lifting_the_bound_moves_the_corpus(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both numbers, from one run, and the older one is the issue's zero.

    Lifting ``_MAX_COMPANY_LEN`` in-process removes the cover on doors 2, 3 and
    4 at once — ``_clean_sender_display_name``, ``_clean_company_display`` and
    the ``corporate`` gate's length conjunct all read the module global at call
    time. Whatever then resolves differently is a message the bound was
    refusing.

    The mover SET is asserted, not just the count: "some number greater than
    zero moved" passes for the wrong reason as easily as the right one.
    """

    shipped = _census(CASES)
    monkeypatch.setattr(pipeline, "_MAX_COMPANY_LEN", 10**9)
    lifted = _census(CASES)

    movers = {mid for mid in shipped if shipped[mid] != lifted[mid]}
    older = {c.item.message_id for c in CASES if c.axis != BOUND_AXIS}

    assert movers & older == set(), (
        f"{len(movers & older)} of the {len(older)} cases predating this axis "
        "moved. They are 264 characters short of the bound and must not."
    )
    assert movers == _ids("past"), (
        f"{len(movers)} case(s) moved when the bound was lifted; expected "
        f"exactly the {len(_ids('past'))} past-bound fixtures. If this is "
        "empty the corpus is back to being unable to disprove the bound, "
        "which is the whole of #737."
    )
    for mid in sorted(movers):
        assert shipped[mid] is None and lifted[mid] is not None
        assert len(lifted[mid][1]) == PAST_BOUND, (
            f"{mid} resolved to {len(lifted[mid][1])} characters with the "
            f"bound lifted, not {PAST_BOUND}: it moved for some other reason "
            "than the length refusal, so it is not evidence about the bound."
        )


def test_the_on_bound_cases_do_not_move(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other half of the direction, and the one a mover count omits.

    Movers alone would be satisfied by a corpus that refuses everything. These
    four resolve identically whether the bound is 300 or a billion, which is
    what makes 300 a threshold here rather than two unrelated fixtures.
    """

    shipped = _census(CASES)
    monkeypatch.setattr(pipeline, "_MAX_COMPANY_LEN", 10**9)
    lifted = _census(CASES)

    for mid in sorted(_ids("on")):
        assert shipped[mid] == lifted[mid] is not None, (
            f"{mid} sits on the bound and answered differently with the bound "
            f"lifted: {shipped[mid]!r} then {lifted[mid]!r}"
        )


def test_lifting_the_bound_does_not_reach_door_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Why door 1's absence from the corpus is a fact, not an oversight.

    ``ReviewClassifyRequest.company`` carries ``Field(max_length=...)``,
    evaluated once at class definition from a value imported by ``applications``
    at import time. Monkeypatching the pipeline's module global does not reach
    it, so the instrument every number above is built on cannot move door 1 in
    either direction. Had a door-1 corpus case existed, its non-mover would
    have been another zero that could not have been anything else — the exact
    defect #737 is about, one layer down.
    """

    monkeypatch.setattr(pipeline, "_MAX_COMPANY_LEN", 10**9)
    ReviewClassifyRequest(category="rejection", company="Northwind Labs")
    with pytest.raises(ValidationError):
        ReviewClassifyRequest(category="rejection", company="n" * PAST_BOUND)
