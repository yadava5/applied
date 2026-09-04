"""``applications.company`` is indexed, so an oversized employer name is a 500.

The column carries two btree indexes — ``ix_applications_company`` on the raw
value and ``ix_applications_user_id_lower_company`` on ``lower(company)`` — and
a version 4 index row stops at 2704 bytes. ``test_company_index_postgres.py``
proves that against a real ``postgres:16``; this module protects the invariant
that keeps the write path away from it, on every engine.

WHY THIS IS NOT COVERED BY ``test_application_create_is_bounded.py``. That module
bounds ``CloudApplicationCreate.company``, the hand-filed ``POST /applications``
body. Issue #581 recorded a second unbounded writer. Measurement found FOUR, and
they do not share a chokepoint:

===  ==========================================  ===================================
#    door                                        what bounds it now
===  ==========================================  ===================================
1    ``ReviewClassifyRequest.company``           ``_clean_company_display``
2    sender display name, ``resolve_employer``   ``_clean_sender_display_name``
     step 3                                      
3    ``sender_email`` -> ``_brand_display``      the ``corporate`` gate's conjunct
4    subject segment                             ``_clean_company_display``
===  ==========================================  ===================================

Door 2 is the reason this module exists. The obvious single fix is to bound
``_clean_company_display``, which six of seven display producers call — and step
3 is the seventh. Stubbing that function to refuse EVERY input left a
1,907-character display completely untouched, because it is never called on that
path. ``pipeline.py`` says so in its own words above ``_apply_display_tail``.
``test_each_bound_is_load_bearing`` pins all three separately for that reason: a
fix that closed two doors of four would look finished.

ON THE FIXTURES. Every oversized string here is INCOMPRESSIBLE. Postgres
compresses a varlena datum before measuring it against 2704, so a single
codepoint repeated 2700 times inserts fine no matter how long it is. Entropy is
the discriminator, not character count, and a fixture of ``"a" * 3000`` would
assert against a failure the database does not actually have.
"""

from __future__ import annotations

import secrets
import string

import pytest
from pydantic import ValidationError

from jobtracker.cloud import pipeline
from jobtracker.cloud.applications import (
    _MAX_COMPANY_LEN,
    ReviewClassifyRequest,
    ScannedMessageIn,
)

# A relay, so the sender domain is not itself the employer and resolution is
# pushed onto the display name and the subject — the doors under test.
RELAY_SENDER = "no-reply@greenhouse.example"

# The widest a UTF-8 code point gets. The bound is in characters and the ceiling
# is in bytes, so every assertion about bytes goes through this.
MAX_UTF8_BYTES_PER_CHAR = 4


def noise(n: int) -> str:
    """``n`` incompressible characters. See the module docstring."""

    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def displays_for(**kwargs: object) -> str | None:
    """The display ``resolve_employer`` would put on a card, or None."""

    resolved = pipeline.resolve_employer(
        kwargs.get("sender_email", RELAY_SENDER),  # type: ignore[arg-type]
        kwargs.get("subject", "Your application"),  # type: ignore[arg-type]
        kwargs.get("sender_name"),  # type: ignore[arg-type]
    )
    return None if resolved is None else resolved[1]


# --------------------------------------------------------------------------
# The invariant, stated once and driven through every door.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "door,resolve",
    [
        (
            "1 review-classify company",
            lambda: (pipeline.employer_from_text("Acme " + noise(2700)) or (None, None))[1],
        ),
        (
            "2 sender display name",
            lambda: displays_for(sender_name="Acme 2 " + noise(2700)),
        ),
        (
            "3 domain brand fallback",
            lambda: displays_for(sender_email="hi@" + noise(3000) + ".example", sender_name=None),
        ),
        (
            "4 subject segment",
            lambda: displays_for(subject="Your application at A" + noise(2700), sender_name=None),
        ),
    ],
)
def test_no_door_produces_an_employer_name_over_the_bound(door: str, resolve) -> None:
    display = resolve()
    if display is None:
        return  # refused outright, which is the preferred answer
    assert len(display) <= _MAX_COMPANY_LEN, (
        f"door {door} produced a {len(display)}-character employer display. "
        f"The bound is {_MAX_COMPANY_LEN}. This value reaches the indexed column "
        "`applications.company` and an oversized one raises "
        "ProgramLimitExceededError on the INSERT, taking the whole sync batch "
        "with it (#581)."
    )


def test_the_bound_leaves_room_inside_the_index_row() -> None:
    """A character bound guarding a byte ceiling has to state its own headroom."""

    display = displays_for(sender_name="Acme 2 " + noise(2700))
    if display is not None:
        assert len(display.encode("utf-8")) <= _MAX_COMPANY_LEN * MAX_UTF8_BYTES_PER_CHAR


# --------------------------------------------------------------------------
# Directional: a threshold needs a case sitting ON it, not only past it.
# --------------------------------------------------------------------------


def test_a_name_at_exactly_the_bound_still_resolves() -> None:
    at_bound = "A" + noise(_MAX_COMPANY_LEN - 1)
    assert len(at_bound) == _MAX_COMPANY_LEN

    resolved = pipeline.employer_from_text(at_bound)

    assert resolved is not None, (
        f"a {_MAX_COMPANY_LEN}-character name was refused. The bound is "
        "inclusive; refusing here means it is one lower than it claims."
    )
    assert resolved[1] == at_bound


def test_a_name_one_character_past_the_bound_is_refused() -> None:
    assert pipeline.employer_from_text("A" + noise(_MAX_COMPANY_LEN)) is None


def test_a_real_employer_name_is_untouched() -> None:
    """The half that matters: refusing everything would also pass the tests above."""

    for name in ("Northwind Labs", "IXL Learning", "Crusoe", "Ramp"):
        resolved = pipeline.employer_from_text(name)
        assert resolved is not None, f"{name!r} was refused"
        assert resolved[1] == name


# --------------------------------------------------------------------------
# Each bound is load-bearing. Delete one and a specific door reopens.
# --------------------------------------------------------------------------


def _door_one() -> int | None:
    resolved = pipeline.employer_from_text("Acme " + noise(2700))
    return None if resolved is None else len(resolved[1])


def _door_two() -> int | None:
    display = displays_for(sender_name="Acme 2 " + noise(2700))
    return None if display is None else len(display)


def _door_three() -> int | None:
    display = displays_for(sender_email="hi@" + noise(3000) + ".example", sender_name=None)
    return None if display is None else len(display)


def _passthrough(raw: str) -> str:
    return (raw or "").strip()


def test_each_bound_is_load_bearing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Three bounds, three doors, and no two of them overlap.

    Written because the first draft of this fix bounded ``_clean_company_display``
    alone and called the class closed. The suite is green either way, so the only
    way to show that is false is to remove each bound in turn and watch a
    specific door reopen. Removing a bound must red exactly one column below; a
    bound whose removal changes nothing is decoration, and a door no bound covers
    is one that ships open.

    ==========================================  ====  ====  ====
    stub                                          d1    d2    d3
    ==========================================  ====  ====  ====
    intact                                      None  None  None
    ``_clean_sender_display_name``              None  OVER  None
    ``_clean_company_display``                  OVER  None  None
    both cleaners                               OVER  OVER  None
    both cleaners + ``_MAX_COMPANY_LEN`` raised OVER  OVER  OVER
    ==========================================  ====  ====  ====
    """

    assert (_door_one(), _door_two(), _door_three()) == (None, None, None), (
        "with the fix intact every door refuses; nothing below discriminates "
        "unless this holds first"
    )

    # Door 2 has its OWN cover, and it is not the cleaner six other producers use.
    monkeypatch.setattr(pipeline, "_clean_sender_display_name", _passthrough)
    assert _door_two() is not None and _door_two() > _MAX_COMPANY_LEN, (
        "removing `_clean_sender_display_name`'s bound must reopen the sender "
        "display-name door. Step 3 of `resolve_employer` does not call "
        "`_clean_company_display`, so this is the only bound covering it."
    )
    assert _door_one() is None, "and it must not be the bound covering door 1"
    monkeypatch.undo()

    # Door 1 is covered by the other cleaner, and only by it.
    monkeypatch.setattr(pipeline, "_clean_company_display", _passthrough)
    assert _door_one() is not None and _door_one() > _MAX_COMPANY_LEN
    assert _door_two() is None, "and it must not be the bound covering door 2"
    monkeypatch.undo()

    # Door 3 runs NO cleaner. With both stubbed off it is still closed, and the
    # only thing closing it is the `corporate` gate's length conjunct — which
    # raising the constant is what removes, the cleaners being already inert.
    monkeypatch.setattr(pipeline, "_clean_company_display", _passthrough)
    monkeypatch.setattr(pipeline, "_clean_sender_display_name", _passthrough)
    assert _door_three() is None, (
        "with both cleaners neutered the domain-brand door must still be closed "
        "by the `corporate` gate's conjunct"
    )
    monkeypatch.setattr(pipeline, "_MAX_COMPANY_LEN", 10**9)
    assert _door_three() is not None and _door_three() > _MAX_COMPANY_LEN, (
        "and removing that conjunct must reopen it. `_brand_display` ends "
        "`brand.replace('-', ' ').title()` on a raw domain label; if this does "
        "not reopen, the conjunct is not what closes door 3 and the real cover "
        "is unidentified."
    )


# --------------------------------------------------------------------------
# The doors, refused at the wire where a caller can be told why.
# --------------------------------------------------------------------------


def test_the_review_classify_body_refuses_an_oversized_company() -> None:
    ReviewClassifyRequest(category="rejection", company="A" * _MAX_COMPANY_LEN)

    with pytest.raises(ValidationError):
        ReviewClassifyRequest(category="rejection", company="A" * (_MAX_COMPANY_LEN + 1))


@pytest.mark.parametrize(
    "field,limit",
    [
        ("sender_name", 512),
        ("subject", 2000),
        ("snippet", 2000),
        ("thread_id", 256),
        ("method", 64),
    ],
)
def test_the_scanned_message_bounds_every_string(field: str, limit: int) -> None:
    """The sibling carrier on the same body, and the half #581 did not name.

    These are NOT bounded at ``_MAX_COMPANY_LEN``: a sender name is what an
    employer is extracted from, not an employer, and 300 would refuse real mail.
    """

    base = {"sender_email": "careers@northwind.example", "received_at": "2026-09-04T00:00:00Z"}

    ScannedMessageIn(**base, **{field: "a" * limit})

    with pytest.raises(ValidationError):
        ScannedMessageIn(**base, **{field: "a" * (limit + 1)})


def test_the_scanned_message_bounds_its_sender_address() -> None:
    """``sender_email`` is door 3's carrier, so its own cap is load-bearing."""

    with pytest.raises(ValidationError):
        ScannedMessageIn(
            sender_email="hi@" + "a" * 512 + ".example",
            received_at="2026-09-04T00:00:00Z",
        )


def test_the_bound_is_one_number_in_one_place() -> None:
    """#581 asks for this explicitly: two ceilings on one column would drift."""

    from jobtracker.cloud.applications import _MAX_COMPANY_LEN as via_applications
    from jobtracker.cloud.pipeline import _MAX_COMPANY_LEN as via_pipeline

    assert via_applications is via_pipeline
