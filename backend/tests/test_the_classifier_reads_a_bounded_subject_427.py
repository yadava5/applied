"""Item 3 of #427: the subject was capped on neither engine, and the
``text/plain`` body was decoded and scanned in full to produce 4,000 characters.

WHAT WAS MEASURED, on the shipped functions, min of three runs
---------------------------------------------------------------
The subject reaches ``classify`` as its first argument and every pattern in the
set is run against it, so the cost is linear in a header nothing bounded::

    subject       100 chars ->     0.26 ms
    subject    10,000       ->    23.09 ms
    subject 1,000,000       -> 2,332.39 ms

And the body, where the control is what makes it a defect rather than a cost —
the SAME bytes, on the two branches of one function::

    text/plain 5,000,000 chars -> 221.30 ms   (returns 4000)
    text/html  5,000,000 chars ->  15.92 ms   (returns 4000)

13.9x apart, because ``_cap_html`` bounds one branch at ``_MAX_HTML_CHARS`` and
nothing bounded the other. Worse across parts, because ``_decode_part`` was
called on every one of them before anything was capped::

    20 x 1 MB text/plain parts -> 907.21 ms   (returns 4000)

After: 11.23 ms for the 5 MB single part and 11.22 ms for the 20 MB multipart —
the curve is flat where it was linear.

WHY THE ASSERTIONS ARE SHAPED THE WAY THEY ARE
------------------------------------------------
An output assertion on a truncation is nearly always trivially true: assert
``len(out) == CAP`` with a fixture shorter than the cap and it passes for every
cap, and import the constant as the expectation and it compares the config to
itself (both are scars in this repository's ledger). So:

* the subject fixtures are **50x the cap**, and the expected length is written
  out as a **literal 2000**. Output is ``min(input, cap)``, so any cap below the
  fixture length that is not 2000 fails, and removing the cap fails;
* the constant is separately pinned to ``PipelineItemIn``'s ``max_length`` —
  sourced from what CONSTRAINS it rather than from itself, so the two paths
  cannot drift apart silently;
* the body cap is proved by **bracketing sentinels** rather than by a length or
  a duration. One marker sits just under the raw bound and one just over it, in
  a carrier that collapses to nothing, so the assertion is two-sided: removing
  the cap lets ABOVE through, setting it too low loses BELOW, setting it too
  high lets ABOVE through. No timing, nothing flaky, no imported expectation.
"""

from __future__ import annotations

import base64

import pytest

from jobtracker.cloud import gmail_client as gc
from jobtracker.cloud.gmail_client import (
    CloudGmailMessage,
    _MAX_RAW_BODY_CHARS,
    _MAX_SENDER_CHARS,
    _MAX_SUBJECT_CHARS,
    _parse_metadata_message,
    extract_body_text,
)

#: 50x the cap. Big enough that `min(input, cap)` cannot equal the input.
OVERSIZE = 100_000

#: Written out, never imported from the module under test.
EXPECTED_SUBJECT_CAP = 2000
EXPECTED_SENDER_CAP = 512


def _plain(text: str) -> dict:
    return {
        "mimeType": "text/plain",
        "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()},
    }


# =============================================================================
# The subject, and the two fields beside it that share its provenance
# =============================================================================


def test_an_oversized_subject_is_cut_at_the_bound() -> None:
    msg = CloudGmailMessage(
        message_id="m",
        thread_id="t",
        subject="S" * OVERSIZE,
        sender_name=None,
        sender_email="jobs@cedar.example",
        snippet="",
        received_at=None,
    )
    assert len(msg.subject) == EXPECTED_SUBJECT_CAP
    # A prefix, not a hash or a placeholder: the classifier must still read the
    # beginning of the real subject, which is where a lifecycle phrase sits.
    assert msg.subject == "S" * EXPECTED_SUBJECT_CAP


def test_an_ordinary_subject_is_untouched() -> None:
    """NON-VACUITY. A cap that mangled every subject would pass the test above."""

    subject = "Thank you for applying to Cedar Systems"
    msg = CloudGmailMessage(
        message_id="m",
        thread_id="t",
        subject=subject,
        sender_name="Cedar Recruiting",
        sender_email="jobs@cedar.example",
        snippet="We received your application.",
        received_at=None,
    )
    assert msg.subject == subject
    assert msg.sender_name == "Cedar Recruiting"
    assert msg.snippet == "We received your application."


def test_the_sender_fields_are_bounded_too() -> None:
    """The same asymmetry, one field over.

    Bounding only the subject would repeat exactly the shape this issue is
    about: the repository decides a class of input must be bounded and applies
    the decision to one member of the class. ``sender_email`` and
    ``sender_name`` reach ``classify`` and ``resolve_employer`` from the same
    unbounded header block.
    """

    msg = CloudGmailMessage(
        message_id="m",
        thread_id="t",
        subject="s",
        sender_name="N" * OVERSIZE,
        sender_email="E" * OVERSIZE,
        snippet="",
        received_at=None,
    )
    assert len(msg.sender_email) == EXPECTED_SENDER_CAP
    assert msg.sender_name is not None and len(msg.sender_name) == EXPECTED_SENDER_CAP


def test_the_bound_holds_through_the_real_parser() -> None:
    """Through ``_parse_metadata_message``, the function the input reaches.

    Constructing the dataclass by hand proves ``__post_init__`` runs; this
    proves the production path goes through it. Benchmarking the rewritten
    function instead of the one the caller enters is its own scar here.
    """

    raw = {
        "id": "i",
        "threadId": "t",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "S" * OVERSIZE},
                {"name": "From", "value": f'"{"N" * OVERSIZE}" <{"e" * OVERSIZE}@cedar.example>'},
            ]
        },
        "snippet": "p" * OVERSIZE,
    }
    msg = _parse_metadata_message(raw)
    assert msg is not None
    assert len(msg.subject) == EXPECTED_SUBJECT_CAP
    assert len(msg.sender_email) == EXPECTED_SENDER_CAP


def test_the_bound_is_the_relay_contracts_and_not_a_second_opinion() -> None:
    """Sourced from what CONSTRAINS it, never from itself.

    ``assert _MAX_SUBJECT_CHARS == _MAX_SUBJECT_CHARS`` is the shape that passes
    for every value. The number has to come from ``PipelineItemIn``, which is
    the contract the relay path has always enforced: mail admissible by relay
    must classify from identical text however it arrives, or there is a band in
    which the same message resolves two ways depending on which door it used.
    """

    from annotated_types import MaxLen

    from jobtracker.cloud.gmail_oauth import PipelineItemIn

    def relay_bound(field: str) -> int:
        meta = PipelineItemIn.model_fields[field].metadata
        return next(m.max_length for m in meta if isinstance(m, MaxLen))

    assert _MAX_SUBJECT_CHARS == relay_bound("subject")
    assert _MAX_SENDER_CHARS == relay_bound("sender_email")
    assert _MAX_SENDER_CHARS == relay_bound("sender_name")


# =============================================================================
# The body: bounded BEFORE the work, not after it
# =============================================================================

#: A carrier that survives none of ``normalise_body_text``'s three passes, so
#: the output is the sentinels and nothing else and the assertion cannot be
#: satisfied by an accident of position.
CARRIER = "   \n"


def _bracketed(below_at: int, above_at: int, total: int = 300_000) -> str:
    chars = list((CARRIER * (total // len(CARRIER) + 1))[:total])
    for pos, tag in ((below_at, "SENTINELBELOW"), (above_at, "SENTINELABOVE")):
        for i, ch in enumerate(tag):
            chars[pos + i] = ch
    return "".join(chars)


#: LITERAL offsets, and this is the whole point of them.
#:
#: The first draft placed these at ``_MAX_RAW_BODY_CHARS -/+ 2000`` and the
#: mutation harness caught it: halving the constant to 128,000 moved the
#: sentinels with it and all nine tests stayed green. An expectation read from
#: the value under test compares the config to itself — it catches a deleted
#: cap and nothing else. Written out, they bracket 256,000 and only 256,000.
SENTINEL_BELOW_AT = 254_000
SENTINEL_ABOVE_AT = 258_000


def test_text_past_the_raw_bound_never_reaches_the_classifier() -> None:
    """Two-sided, which is the only kind of truncation assertion worth writing.

    BELOW must arrive and ABOVE must not, at offsets that do not move when the
    constant does. Remove the cap and ABOVE arrives (the carrier collapses, so
    both fit the 4,000-character window). Halve the cap and BELOW stops
    arriving. Raise it and ABOVE arrives. All three directions red.
    """

    body = _bracketed(SENTINEL_BELOW_AT, SENTINEL_ABOVE_AT)
    out = extract_body_text(_plain(body))

    assert "SENTINELBELOW" in out
    assert "SENTINELABOVE" not in out


def test_the_bracket_actually_straddles_the_shipped_bound() -> None:
    """PROVE THE CONTROL RAN.

    Two literals and a constant that could drift apart into a bracket sitting
    wholly on one side of the bound — where the test above would still pass and
    would be measuring nothing. This is the assertion that notices.
    """

    assert SENTINEL_BELOW_AT < _MAX_RAW_BODY_CHARS < SENTINEL_ABOVE_AT


def test_a_body_inside_the_bound_is_not_truncated() -> None:
    """NON-VACUITY for the pair above: an empty return satisfies half of it."""

    out = extract_body_text(_plain("Thanks for applying to Cedar Systems.\n"))
    assert out == "Thanks for applying to Cedar Systems."


def test_a_part_past_the_budget_is_never_decoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The early exit, counted rather than timed.

    Capping the JOIN would leave every part decoded — 20 x 1 MB cost 907 ms to
    return 4,000 characters. The walk must stop handing parts to the decoder
    once the branch is full, so this counts calls: one part fills the budget, so
    the second is never decoded.
    """

    calls: list[int] = []
    real = gc._decode_part

    def counting(part: dict, budget: int = _MAX_RAW_BODY_CHARS) -> str:
        calls.append(budget)
        return real(part, budget)

    monkeypatch.setattr(gc, "_decode_part", counting)

    filler = "x" * (_MAX_RAW_BODY_CHARS + 10_000)
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [_plain(filler), _plain("SENTINELSECONDPART")],
    }
    out = gc.extract_body_text(payload)

    assert len(calls) == 1, calls
    assert "SENTINELSECONDPART" not in out


def test_both_parts_are_decoded_when_the_budget_allows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE DIRECTIONAL CONTROL for the test above.

    A walk that stopped after the first part unconditionally would satisfy the
    call count and silently drop the rest of every ordinary multipart message.
    """

    calls: list[int] = []
    real = gc._decode_part

    def counting(part: dict, budget: int = _MAX_RAW_BODY_CHARS) -> str:
        calls.append(budget)
        return real(part, budget)

    monkeypatch.setattr(gc, "_decode_part", counting)

    payload = {
        "mimeType": "multipart/mixed",
        "parts": [_plain("First part.\n"), _plain("SENTINELSECONDPART\n")],
    }
    out = gc.extract_body_text(payload)

    assert len(calls) == 2, calls
    assert "SENTINELSECONDPART" in out
