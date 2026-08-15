"""``POST /gmail/sync`` must not let a client name the size of the allocation.

Processing already discarded everything past ``gmail_fetch_hard_cap`` (2000)
and truncated ``snippet`` to 500 characters on the way into the database. Both
happen far too late to matter: Pydantic parses the WHOLE body into Python
objects before a single field is read, so an unbounded ``items`` list — or one
bounded item carrying a 50 MB string — is memory the process allocates on an
authenticated caller's say-so, inside a function with a fixed memory ceiling.
The truncation caps the WORK; it never capped the ALLOCATION.

These are model-level tests on purpose. The limits are a property of the
request schema, and asserting them through the HTTP stack would drag in auth,
the database and the Gmail client to prove something about validation.

The limits are generous multiples of what Gmail actually emits, so the
"a real payload is still accepted" tests are as load-bearing as the rejections:
a bound that also rejects legitimate traffic is not a fix.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jobtracker.cloud.gmail_oauth import PipelineItemIn, SyncRequest


def _item(**overrides):
    base = {"message_id": "18f0a1b2c3d4e5f6", "category": "applied"}
    base.update(overrides)
    return base


def test_a_realistic_item_is_accepted():
    """NON-VACUITY. Everything below is meaningless if this fails."""

    item = PipelineItemIn(
        **_item(
            sender_email="careers@a-very-long-company-domain-name.example.com",
            subject="Thank you for applying to the Software Engineer position " * 5,
            sender_name="Acme Talent Acquisition Team",
            received_at="2026-08-14T12:00:00+00:00",
            confidence=0.93,
            thread_id="18f0a1b2c3d4e5f6",
            snippet="Thanks for your interest in Acme. " * 20,
        )
    )
    assert item.message_id == "18f0a1b2c3d4e5f6"


@pytest.mark.parametrize(
    "field,length",
    [
        ("message_id", 257),
        ("category", 65),
        ("sender_email", 513),
        ("subject", 2001),
        ("sender_name", 513),
        ("received_at", 65),
        ("thread_id", 257),
        ("snippet", 2001),
    ],
)
def test_every_string_field_is_bounded(field, length):
    """One oversized field is enough to reject the item.

    Parametrised across ALL of them rather than spot-checking one: a bound on
    ``snippet`` alone would leave ``subject`` as the same unbounded hole, and
    the whole point is that no single string is left able to size the parse.
    """

    with pytest.raises(ValidationError):
        PipelineItemIn(**_item(**{field: "x" * length}))


def test_the_items_list_is_bounded():
    """The multiplier. One item is small; an unbounded LIST of them is not."""

    with pytest.raises(ValidationError):
        SyncRequest(items=[_item() for _ in range(2501)])


def test_the_items_bound_sits_above_the_processing_cap():
    """A client relaying a few too many items must not start getting 422s.

    ``gmail_fetch_hard_cap`` is 2000 and the handler already slices to it. The
    schema bound is set ABOVE that so the behaviour for an honest over-sender
    is unchanged — its surplus is still silently dropped — while an abusive
    body is refused before it is materialised.
    """

    from jobtracker.config import settings

    request = SyncRequest(items=[_item() for _ in range(settings.gmail_fetch_hard_cap)])

    assert request.items is not None
    assert len(request.items) == settings.gmail_fetch_hard_cap


def test_a_sync_request_with_no_items_is_still_valid():
    """The server-fetch path sends no items at all; bounding must not break it."""

    assert SyncRequest().items is None
    assert SyncRequest(count=50, range="6m", scope="anywhere", mode="rebuild").items is None
