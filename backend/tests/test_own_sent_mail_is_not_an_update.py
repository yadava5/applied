"""A message the user SENT is never an inbound update about their application.

Found the first time a windowed additive scan ran against the owner's real
mailbox. `in:anywhere` means anywhere, and that includes Sent: four of the five
new review-queue rows were his own job-search outreach, with subjects like
"…applied for the Member of Technical Staff role". The classifier scored them
`applied` at 0.9 — a fair reading of that text, and completely wrong about the
message.

THE GUARD HAS TO BE STRUCTURAL. The text really is application-shaped, so no
pattern work fixes it; only "who sent this" does.

THERE ARE TWO HALVES AND THEY COVER DIFFERENT PATHS, which is why each is
tested with the other's failure in mind:

  * `build_gmail_query` adds `-in:sent`, which reaches the FULL SCAN only.
  * `_classify_messages` drops messages from the account owner, which is the
    only thing covering the INCREMENTAL path — `users.history.list` takes no
    query and reports every change in the mailbox, including a reply the user
    sent thirty seconds ago.

Delete either one and a real population walks through the gap.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from jobtracker.cloud import gmail_oauth
from jobtracker.cloud.gmail_client import build_gmail_query

OWNER = "owner@example.com"


@dataclass
class _Msg:
    message_id: str
    subject: str
    sender_email: str
    sender_name: str | None = None
    snippet: str = "Some body text about a role."
    thread_id: str | None = None
    received_at: Any = None


class _StubClassifier:
    """Scores everything as a confident application, on purpose.

    The defect is NOT that the classifier was unsure — it was 0.9 sure, and
    right about the words. A stub that hedged would let a filter pass for the
    wrong reason.
    """

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def classify(self, subject: str, text: str, sender_email: str) -> Any:
        self.seen.append(sender_email)

        class _R:
            category = type("C", (), {"value": "applied"})()
            confidence = 0.9
            method = "rules"

        return _R()


def _classify(messages: list[_Msg], account_email: str | None) -> list[Any]:
    from jobtracker.cloud import pipeline

    return asyncio.run(
        gmail_oauth._classify_messages(
            messages, _StubClassifier(), pipeline, None, account_email
        )
    )


# --- the query half ---------------------------------------------------------


def test_the_anywhere_query_excludes_sent_mail() -> None:
    assert "-in:sent" in build_gmail_query(12, "anywhere")
    assert "-in:sent" in build_gmail_query(None, "anywhere")


def test_the_inbox_query_is_unchanged() -> None:
    """The CONTROL. `in:inbox` cannot contain sent mail, so the inbox query
    must not gain a no-op term — a change there would be noise in every
    query log and a needless difference from what the inbox endpoint sends."""

    assert build_gmail_query(6, "inbox") == "in:inbox newer_than:6m"
    assert build_gmail_query(None, "inbox") == "in:inbox"


# --- the owner half, which is what covers the incremental path --------------


def test_a_message_the_owner_sent_never_becomes_an_item() -> None:
    items = _classify(
        [
            _Msg(
                "m1",
                "Built a thing, applied for the Member of Technical Staff role",
                OWNER,
            )
        ],
        OWNER,
    )
    assert items == []


def test_real_inbound_mail_still_becomes_an_item() -> None:
    """The CONTROL that stops the filter being 'drop everything'."""

    items = _classify([_Msg("m2", "Thanks for applying", "no-reply@acme.com")], OWNER)
    assert len(items) == 1
    assert items[0].sender_email == "no-reply@acme.com"


def test_the_owner_check_is_case_and_whitespace_insensitive() -> None:
    """Gmail does not promise a canonical case in the From header."""

    items = _classify([_Msg("m3", "Re: my application", "  OWNER@Example.COM ")], OWNER)
    assert items == []


@pytest.mark.parametrize("account_email", [None, ""])
def test_an_unknown_owner_drops_nothing(account_email: str | None) -> None:
    """Degrade toward keeping mail, never toward silently discarding it.

    When the account address could not be read, the safe failure is a row in
    the review queue — recoverable by one click — not a message that vanishes.
    """

    items = _classify([_Msg("m4", "Thanks for applying", "no-reply@acme.com")], account_email)
    assert len(items) == 1


def test_the_owner_message_is_never_even_classified() -> None:
    """Skipped BEFORE the classifier, not after.

    An item that is classified and then dropped has still been scored, and this
    repo writes `training_data` from scored items. The user's own outreach must
    not become a training example of an 'application'.
    """
    from jobtracker.cloud import pipeline

    classifier = _StubClassifier()
    asyncio.run(
        gmail_oauth._classify_messages(
            [_Msg("m5", "applied for the role", OWNER), _Msg("m6", "Thanks", "hr@acme.com")],
            classifier,
            pipeline,
            None,
            OWNER,
        )
    )
    assert classifier.seen == ["hr@acme.com"], (
        "the owner's own message reached the classifier"
    )
