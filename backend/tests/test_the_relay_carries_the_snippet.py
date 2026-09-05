"""What the client relay may say about a message, and what it must not (#484).

THE RESIDUAL. ``apps/web/lib/gmail/transport.ts`` declared seven fields on
``PipelineItem`` and ``toPipelineItems`` forwarded seven. ``snippet`` was not
among them — although ``InboxVerdict.snippet`` exists, the mine returns one on
every verdict, and ``PipelineItemIn.snippet`` has accepted one (bounded at
2000) all along. So the client held Gmail's preview and dropped it on relay.

The server comments describe this path as sending the reader BACK to the
snippet. There was no snippet to go back to. Measured on a row this path
wrote, before the client was fixed::

    PipelineItemIn.snippet = '' len 0
    stored body_snippet    = ''
    identity_parts(...)    -> (None, None)

    [positive control] identity_parts(same subject, the real 180-char preview)
                           -> ('Backend Platform Engineer', None)

Nothing-grade, not snippet-grade.

WHERE THE GATE FOR THAT LIVES. In the WEB suite —
``apps/web/tests/unit/relay-carries-the-snippet.test.mjs`` — because the fix is
one field in a TypeScript object literal and the backend was never the broken
half. A backend test that posts a relay item WITH a snippet passes identically
before and after that change and would gate nothing. What this module pins is
the contract the client is written against, which is the other way the relay
can break: the two facts below are the reason ``toPipelineItems`` coalesces
``null`` to ``""`` rather than forwarding the field as-is, and the reason it
forwards no identity at all.

THE SECOND HALF IS THE ONE THAT MATTERS MOST. ``PipelineItemIn`` deliberately
does not accept ``identity_role``/``identity_req_id``: they decide which
application a message is filed against and how the queue groups decisions, so a
client that could state them could reshape dedup keys and file its own mail onto
whichever application it named. Widening the relay is exactly the change someone
would make next, having just watched a field be added to it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import pytest
from sqlmodel import select as sm_select

USER = uuid.UUID("66666666-6666-6666-6666-666666666666")

SENDER = "careers@northwind.test"
SUBJECT = "Your application to Northwind Labs"

#: Gmail's preview, the length Gmail actually emits, and it DOES name the job —
#: which is the point: snippet-grade identity is what the relay path is
#: supposed to have, and what it had none of.
PREVIEW = (
    "Thank you for applying to the Backend Platform Engineer position at "
    "Northwind Labs. Our recruiting team has received your application and "
    "will review it over the next several days."
)

ROLE = "Backend Platform Engineer"


def _relay_in(**overrides: Any) -> Any:
    """One item as ``POST /gmail/sync`` receives it from the browser."""

    from jobtracker.cloud.gmail_oauth import PipelineItemIn

    fields = {
        "message_id": "relay-1",
        "category": "applied",
        "sender_email": SENDER,
        "subject": SUBJECT,
        "sender_name": "Northwind Labs",
        "received_at": "2026-08-01T12:00:00+00:00",
        "confidence": 0.95,
        "snippet": PREVIEW,
    }
    fields.update(overrides)
    return PipelineItemIn(**fields)


def _as_the_handler_does(payload: Any) -> Any:
    """The ``PipelineItem`` ``gmail_sync`` builds from a relayed item, verbatim."""

    from jobtracker.cloud import pipeline

    return pipeline.PipelineItem(
        message_id=payload.message_id,
        category=payload.category,
        sender_email=payload.sender_email,
        subject=payload.subject,
        sender_name=payload.sender_name,
        received_at=datetime(2026, 8, 1, 12, 0),
        confidence=payload.confidence,
        thread_id=payload.thread_id,
        snippet=payload.snippet,
    )


async def _persisted(session: Any, payload: Any) -> Any:
    from jobtracker.cloud import pipeline
    from jobtracker.cloud.applications import _persist_message_refs
    from jobtracker.database.models import Email

    ref = pipeline._message_ref(_as_the_handler_does(payload))
    await _persist_message_refs(session, USER, None, [ref])
    await session.commit()
    return (
        await session.exec(sm_select(Email).where(Email.message_id == payload.message_id))
    ).first()


def test_a_null_snippet_would_reject_the_whole_batch() -> None:
    """WHY the client coalesces instead of forwarding the field as-is.

    ``InboxVerdict.snippet`` is ``string | null | undefined`` — null is the
    documented value for a message with no preview — while
    ``PipelineItemIn.snippet`` is a plain ``str``. ``undefined`` is harmless
    (``JSON.stringify`` drops the key and the default applies); a literal
    ``null`` is a 422, and ``SyncRequest.items`` is a homogeneous list, so ONE
    preview-less message would reject the entire sync and file nothing.

    That would have been strictly worse than the bug being fixed, which is why
    it is written down here rather than left to a code comment.
    """

    from pydantic import ValidationError

    from jobtracker.cloud.gmail_oauth import PipelineItemIn

    with pytest.raises(ValidationError) as caught:
        _relay_in(snippet=None)
    assert "snippet" in str(caught.value)

    # The two shapes the client may legitimately send, and what each yields.
    assert _relay_in().snippet == PREVIEW
    omitted = PipelineItemIn(message_id="relay-omitted", category="applied")
    assert omitted.snippet == ""


async def test_a_relayed_snippet_reaches_storage_and_names_the_application(
    test_session: Any,
) -> None:
    """The forwarded preview is the fallback every stored-text reader uses.

    ``identity_parts`` with both parts unset is the documented relay behaviour —
    "not derived, go and read the text" — and this asserts what the text now
    says. Before the client forwarded the field it said nothing, because there
    was nothing there.
    """

    from jobtracker.cloud import pipeline

    row = await _persisted(test_session, _relay_in())
    assert row is not None
    assert row.body_snippet == PREVIEW
    assert pipeline.identity_parts(
        req_id=row.identity_req_id,
        role=row.identity_role,
        subject=row.subject,
        snippet=row.body_snippet or "",
    ) == (ROLE, None)


async def test_the_client_cannot_state_which_application_a_message_names(
    test_session: Any,
) -> None:
    """Non-interference, asserted on the value that lands rather than on a null.

    The schema IGNORES the smuggled fields (pydantic's default for unknown
    keys), so they never reach a model attribute, never reach the dump, and
    never reach the database. The assertion that carries the weight is the last
    one: the identity this message resolves to is the one READ FROM ITS TEXT,
    not the one the caller asserted — a client that names "Chief Executive"
    still gets the role its own snippet names.
    """

    from jobtracker.cloud import pipeline
    from jobtracker.cloud.gmail_oauth import PipelineItemIn

    assert sorted(PipelineItemIn.model_fields) == [
        "category",
        "confidence",
        "message_id",
        "received_at",
        "sender_email",
        "sender_name",
        "snippet",
        "subject",
        "thread_id",
    ]

    smuggled = _relay_in(
        message_id="relay-smuggled",
        identity_role="Chief Executive",
        identity_req_id="REQ-0",
    )
    assert sorted(smuggled.model_dump()) == sorted(PipelineItemIn.model_fields)

    row = await _persisted(test_session, smuggled)
    assert pipeline.identity_parts(
        req_id=row.identity_req_id,
        role=row.identity_role,
        subject=row.subject,
        snippet=row.body_snippet or "",
    ) == (ROLE, None)
