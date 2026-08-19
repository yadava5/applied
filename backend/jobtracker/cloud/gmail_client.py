"""Cloud-safe Gmail *read* client (issue C5).

This is the cloud twin of ``jobtracker.email_clients.gmail.GmailClient``.
The desktop client cannot run on Vercel: it uses ``run_local_server`` (a
desktop consent flow) and the macOS-Keychain credential backend, whose
module (``jobtracker.credentials.desktop``) imports ``keyring``. Pulling
that into the serverless import graph would break the deploy and the
import-hygiene test in ``tests/test_main_cloud.py``.

So this module deliberately:

- reads/writes tokens **only** through ``jobtracker.credentials.cloud``
  (Fernet-encrypted Postgres rows, keyed by ``user_id``);
- builds a ``google.oauth2.credentials.Credentials`` from the stored
  token + the operator-supplied web client id/secret, refreshing (and
  re-persisting) the access token when it has expired;
- fetches a small, bounded batch of recent messages with ``format="full"``
  — Subject/From/Date headers, Gmail's own ``snippet``, and the message
  body, which is READ FOR CLASSIFICATION AND DISCARDED. See below.

Scope stays least-privilege ``gmail.readonly`` throughout. Tokens are
never logged and never returned to callers of the HTTP layer.

Reading the body, and why it is not stored
------------------------------------------

This module used to fetch ``format="metadata"``, so the classifier only ever
saw the Subject and Gmail's ~200-character ``snippet``. That is not enough
text to recognise a rejection. Measured on the owner's 52 stored messages:
the snippet averages 186 characters, an ATS rejection spends that budget on
its polite preamble, and the sentence carrying the decision falls off the end.
Of four real rejections, one was decidable from the snippet and three were
not — one of them has no snippet at all. The classifier had never once filed
a rejection without a human.

So the body is now fetched. It is **read in flight and never retained**, and
that is a structural property of the code rather than a promise:

- ``CloudGmailMessage`` — the object every persist path receives — has no
  body field and must not gain one. Bodies travel beside it in a separate
  ``dict[message_id, str]`` on :class:`MessagePage`, are handed to
  ``classifier.classify(...)`` as its ``body`` argument, and fall out of
  scope when the request ends.
- ``body_snippet`` continues to be Gmail's OWN snippet, never derived from
  the body we just read, so what is stored is unchanged by this module.
- ``tests/test_body_is_never_persisted.py`` drives a real scan whose bodies
  carry a sentinel and asserts the sentinel reaches no column of any table in
  the schema, no log record, and no response of any endpoint the scan touches
  — ``GET /gmail/inbox`` included. It also asserts the stored snippet EQUALS
  Gmail's, because a sentinel search alone passes for a body prefix that stops
  short of the sentinel. That test is what makes the privacy page's retention
  claim true rather than aspirational.

Bodies are capped at ``_MAX_BODY_CHARS`` and batched more tightly than
metadata was: ``format="full"`` costs the same 5 quota units per message but
returns a far larger payload, and ``batch.execute()`` materialises a whole
batch before the callback drains it, inside a 50 MB serverless slot.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any, Literal, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from jobtracker.config import settings
from jobtracker.credentials.cloud import (
    get_gmail_credentials,
    update_gmail_access_token,
)
from jobtracker.credentials.types import GmailCredentials

logger = logging.getLogger(__name__)

_TOKEN_URI = "https://oauth2.googleapis.com/token"

# Only fetch messages that plausibly belong to a job search. This mirrors
# the desktop default of scanning inbox mail but keeps the cloud read
# cheap; the classifier does the real filtering.
DEFAULT_QUERY = "in:inbox"

# Gmail's own ceiling on ``messages.list`` maxResults per page.
_GMAIL_LIST_PAGE_MAX = 500

# Where to look for mail. ``inbox`` is least-surprising; ``anywhere`` also
# searches archived / other-tab / all-mail so interview & offer emails that
# were filed away (the #1 "lost invite" pain point) are still found.
MailScope = Literal["inbox", "anywhere"]


@dataclass
class CloudGmailMessage:
    """A single Gmail message reduced to the fields classification needs."""

    message_id: str
    thread_id: str
    subject: str
    sender_name: Optional[str]
    sender_email: str
    snippet: str
    received_at: Optional[datetime]


@dataclass
class HistoryPage:
    """What ``users.history.list`` yielded for a stored ``historyId`` cursor.

    ``expired`` — Gmail keeps mailbox history for roughly a week; past that a
    ``startHistoryId`` is answered with **404**. That is documented, normal
    operation (the user simply did not sync for a while), not a failure: the
    caller re-baselines with a full scan.

    ``truncated`` — more mail arrived since the cursor than one invocation is
    willing to walk. Also a full-scan signal: partially consuming the history
    and then advancing the cursor would silently skip the remainder.

    Either flag means ``messages`` is empty and must not be treated as "nothing
    new happened".

    ``unreadable`` is the same number :class:`MessagePage` carries, for the same
    reason: ids the history walk named but whose metadata could not be read
    back. Without it an incremental sync reports ``unreadable: 0`` however much
    it dropped, which is the defect the full-scan path just stopped having.
    """

    messages: list[CloudGmailMessage]
    expired: bool = False
    truncated: bool = False
    unreadable: int = 0
    # See :class:`MetadataBatch.bodies`. The incremental path classifies the
    # same way the full scan does, so it needs the same text — otherwise a
    # message caught by a history walk would be judged on its snippet while
    # the identical message caught by a full scan was judged on its body.
    bodies: dict[str, str] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        """True when this page can stand in for a full scan."""

        return not (self.expired or self.truncated)


# How much of a body the classifier is allowed to see.
#
# Not a privacy control — the body is discarded either way — but a memory one,
# and an honesty one. `format="full"` returns whole marketing emails, and a
# batch is materialised before it is drained inside a 50 MB slot. 4,000
# characters is ~600 words: an ATS decision sentence sits in the first
# paragraph or two, well inside it, while a newsletter's 80 KB of markup is
# truncated to something the rules layer can scan quickly.
_MAX_BODY_CHARS = 4000

# `format="full"` payloads are one to two orders of magnitude larger than
# metadata ones, so the batch that was right for headers is not right here.
# Quota is unchanged (messages.get is 5 units at any format); this is purely
# about how much arrives at once.
_FULL_BATCH_SIZE = 25

# The end tag is NOT the literal ``</script>``. HTML5 leaves the
# script-data-end-tag-name state on whitespace, ``/`` or ``>``, so a browser
# closes the element on ``</script >``, ``</style\n>``, ``</script/>`` and
# ``</script foo>`` — and the literal spelling matched none of them, leaving the
# element body to survive tag stripping and reach the classifier as prose
# (CodeQL ``py/bad-tag-filter``, fixed in step with the three copies in
# ``email_clients/``). ``\b`` so ``<scripture>`` is not a script element.
#
# ``email_clients/html_text.py`` holds the same pattern and carries the full
# note, including why ``html.parser`` was weighed and not taken. It is spelled
# out again here rather than imported because ``cloud/`` deliberately does not
# depend on ``email_clients/`` — the deployed bundle is the desktop package's
# twin, not its consumer. ``tests/test_html_end_tag_whitespace.py`` pins both
# against the same payloads, which is what keeps them honest.
_SCRIPT_OR_STYLE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1(?:[\s/][^>]*)?>", re.DOTALL | re.IGNORECASE
)
_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


def _html_to_text(html: str) -> str:
    """Rough HTML → text for classification only.

    Regex rather than BeautifulSoup deliberately. bs4 and lxml are both in the
    cloud bundle, but this runs once per message inside a 60 s serverless
    budget and the rules layer only needs word order, not a DOM. The same
    approach is used by ``email_clients/parser.py:_html_to_text``.

    Script and style bodies are removed BEFORE tags are stripped, or their
    contents survive as text and a CSS block reads to the classifier as prose.
    An element whose end tag carries whitespace used to survive anyway; see the
    note on ``_SCRIPT_OR_STYLE``.
    """

    html = _SCRIPT_OR_STYLE.sub(" ", html)
    return _WHITESPACE.sub(" ", _TAG.sub(" ", html)).strip()


def _decode_part(part: dict) -> str:
    """Decode one MIME part's base64url body to text, or "" if undecodable."""

    data = (part.get("body") or {}).get("data")
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def extract_body_text(payload: dict | None) -> str:
    """Pull readable text out of a ``format="full"`` payload.

    Prefers ``text/plain``; falls back to ``text/html`` stripped to text. The
    fallback is not a nicety — it is the case that motivated reading bodies at
    all. A message with no ``text/plain`` part is exactly the one Gmail tends
    to give a poor snippet for, and the owner's Anthropic rejection is stored
    with NO snippet whatsoever.

    Walks the part tree iteratively rather than recursively: ``multipart/*``
    nests arbitrarily (``multipart/mixed`` → ``multipart/alternative`` →
    parts), the depth is attacker-influenced in the sense that anyone can mail
    you a deeply nested message, and a recursive walk would rather not be the
    thing that finds the recursion limit inside a serverless handler.

    Returns at most ``_MAX_BODY_CHARS`` characters.
    """

    if not payload:
        return ""

    plain: list[str] = []
    html: list[str] = []
    stack = [payload]
    while stack:
        part = stack.pop()
        if not isinstance(part, dict):
            continue
        mime = (part.get("mimeType") or "").lower()
        if mime.startswith("multipart/"):
            stack.extend(reversed(part.get("parts") or []))
            continue
        if mime == "text/plain":
            plain.append(_decode_part(part))
        elif mime == "text/html":
            html.append(_decode_part(part))
        elif part.get("parts"):
            stack.extend(reversed(part["parts"]))

    text = " ".join(t for t in plain if t).strip()
    if not text:
        text = _html_to_text(" ".join(t for t in html if t)).strip()
    return _WHITESPACE.sub(" ", text)[:_MAX_BODY_CHARS]


@dataclass
class MetadataBatch:
    """What one batched ``messages.get`` round actually brought back.

    ``dropped`` is the number of requested ids that produced NO metadata — a
    failed sub-request, an empty response, or an id Gmail simply did not answer
    for. It exists because dropping them silently makes a scan shrink without
    saying so: the caller reports the smaller number as if it were the whole
    page, and "scanned 1,940" reads identically whether the mailbox held 1,940
    messages or 2,000 with 60 unreadable.
    """

    messages: dict[str, dict]
    dropped: int = 0
    # Body text per message id, for classification only. Kept OUT of the
    # parsed ``CloudGmailMessage`` on purpose: that object is what every
    # persist path receives, and a body field on it would be mapped onto an
    # ``Email`` row by the next person who adds a column. Here it has to be
    # asked for by id, which is a thing you can only do deliberately.
    bodies: dict[str, str] = field(default_factory=dict)


@dataclass
class MessagePage:
    """One server-side page of fetched messages plus the cursor to continue.

    ``next_page_token`` is Gmail's own opaque continuation token: ``None`` when
    the query is exhausted. ``list_pages_walked`` is the number of
    ``messages.list`` calls this page made (always 1 with the default
    page-size = list-ceiling alignment) — surfaced for observability/tests.

    ``unreadable`` is how many ids this page LISTED but could not turn into a
    message (a dropped metadata sub-request, or metadata that would not parse).
    ``len(messages) + unreadable`` is what the page set out to fetch, so a
    caller can say "1,940 of 2,000, 60 unreadable" instead of quietly reporting
    1,940 as the whole.

    ``result_size_estimate`` is Gmail's own ``resultSizeEstimate`` for the
    query. It is an ESTIMATE and is documented as unreliable for large result
    sets — it moves between pages of the same query. Anything using it as a
    progress denominator must clamp it (never let it fall below what has
    already been fetched, never present it as a count).
    """

    messages: list[CloudGmailMessage]
    next_page_token: Optional[str]
    list_pages_walked: int = 1
    unreadable: int = 0
    # See :class:`MetadataBatch.bodies`. Read at the ``classifier.classify``
    # call sites in ``gmail_oauth.py`` and nowhere else; never persisted, never
    # serialised into a response, never logged.
    bodies: dict[str, str] = field(default_factory=dict)
    # PEP 604 rather than this module's older ``Optional[...]`` habit: the
    # project's ruff config selects UP, and new lines should not add to the
    # advisory count it is trying to drive to zero.
    result_size_estimate: int | None = None


def build_gmail_query(
    range_months: Optional[int] = None,
    scope: MailScope = "inbox",
) -> str:
    """Compose a Gmail search query from the UI's range + scope filters.

    - ``scope="inbox"`` → base ``in:inbox``; ``scope="anywhere"`` → ``in:anywhere``
      (includes archived / all-mail so filed-away interview & offer mail is found).
    - ``range_months`` adds Gmail's ``newer_than:<N>m`` age filter; ``None`` /
      non-positive means "all time" (no age bound).

    Gmail's query grammar is space-separated AND terms, so we just join the
    base scope with the optional age term.
    """

    base = "in:anywhere" if scope == "anywhere" else "in:inbox"
    if range_months and range_months > 0:
        return f"{base} newer_than:{int(range_months)}m"
    return base


def _google_credentials_from_stored(stored: GmailCredentials) -> Credentials:
    """Build a google-auth ``Credentials`` from an encrypted stored token.

    The client id/secret come from settings (operator env), never from the
    stored blob — so a leaked DB row alone cannot mint new access tokens.
    """

    return Credentials(
        token=stored.access_token,
        refresh_token=stored.refresh_token or None,
        token_uri=_TOKEN_URI,
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret,
        scopes=list(stored.scopes or settings.gmail_scopes),
    )


# OAuth 2.0 error codes (RFC 6749 §5.2) that mean the grant is GONE — the user
# revoked access, or the refresh token was expired/reissued. Retrying cannot
# help; only the user reconnecting can.
#
# Deliberately narrow. Everything NOT on this list — a TransportError, a DNS
# failure, a timeout, an HTTP 500 from Google, a rate limit — is transient, and
# treating one of those as a revocation would disconnect a perfectly good
# account the first time the network hiccuped. When in doubt the answer is "not
# revoked": the cost of missing a real revocation is one wasted cron slot until
# the next failure, while the cost of a false positive is telling a user their
# working mailbox needs reconnecting.
_PERMANENT_GRANT_FAILURES = ("invalid_grant", "invalid_client", "unauthorized_client")


def _is_permanently_revoked(exc: BaseException) -> bool:
    """Is this refresh failure the definitive "this grant is gone"?

    Matched on ``RefreshError`` — google-auth's OAuth-level failure — AND on
    the error code inside it. The type alone is not enough: google-auth raises
    ``RefreshError`` for some retryable server-side conditions too. The string
    alone is not enough either, because a transport exception could carry a URL
    containing any of these words.

    ``str(exc)`` here holds the OAuth error document, not a token: google-auth
    puts the response *body* of a FAILED exchange in the message, and a failed
    exchange returns ``{"error": "invalid_grant", ...}`` with no credential in
    it. Nothing from this is logged or stored regardless — only the verdict is.
    """

    from google.auth.exceptions import RefreshError

    if not isinstance(exc, RefreshError):
        return False
    haystack = " ".join(str(arg) for arg in exc.args).lower()
    return any(code in haystack for code in _PERMANENT_GRANT_FAILURES)


async def mark_gmail_credential_revoked(user_id: uuid.UUID) -> None:
    """Record that this user's Gmail grant is gone. Never raises.

    WHY THIS MATTERS BEYOND TIDINESS. ``cron._gmail_sync_position`` decides who
    is syncable by asking whether a credential row exists. A revoked user's row
    stayed, so they answered "yes" forever: every scheduled run picked them as a
    candidate, spent one of the ~4 slots a 45 s budget affords on a sync that
    could only fail, and pushed a user whose mailbox still works out of the
    batch. The failure was visible in ``errors[]`` and changed nothing.

    MARKED, NOT DELETED. The row keeps the address the UI needs to name which
    account to reconnect, and the OAuth callback's upsert clears ``revoked_at``
    — so reconnecting is self-service and this is reversible. Deleting on the
    strength of an exception-type heuristic would not be.

    Its own session and its own swallow: this is bookkeeping on a path that is
    already returning ``None`` to a caller which will degrade correctly without
    it. A failure to record must never become the error the user sees.
    """

    from sqlalchemy import update as sa_update

    from jobtracker.credentials.cloud import KIND_GMAIL
    from jobtracker.database import get_session
    from jobtracker.database.models import UserCredential

    try:
        async with get_session() as session:
            await session.exec(
                sa_update(UserCredential)
                .where(
                    UserCredential.user_id == user_id,
                    UserCredential.kind == KIND_GMAIL,
                    UserCredential.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.utcnow())
            )
            await session.commit()
        logger.warning(
            "Gmail grant for user_id=%s is revoked at the provider; marked "
            "disconnected so the schedule stops spending a slot on it. The "
            "user must reconnect.",
            user_id,
        )
    except Exception as exc:  # noqa: BLE001 — bookkeeping may not mask the cause
        logger.warning(
            "Could not mark the Gmail credential revoked for user_id=%s (%s).",
            user_id,
            type(exc).__name__,
        )


async def load_valid_credentials(user_id: uuid.UUID) -> Optional[Credentials]:
    """Return refreshed, ready-to-use google credentials for ``user_id``.

    Returns ``None`` when the user has not connected Gmail. Refreshes the
    access token when it is within the expiry buffer and persists the new
    token (encrypted) so subsequent invocations reuse it. Refresh failures
    (e.g. a revoked grant) are logged without the token value and surfaced
    as ``None`` so the caller degrades to "reconnect required".
    """

    stored = await get_gmail_credentials(user_id)
    if stored is None:
        return None

    creds = _google_credentials_from_stored(stored)

    if stored.is_expired():
        if not stored.refresh_token:
            logger.warning(
                "Gmail token expired and no refresh_token on file for user_id=%s; "
                "user must reconnect.",
                user_id,
            )
            return None
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: creds.refresh(Request()))
        except Exception as exc:  # noqa: BLE001 — google refresh raises broadly
            # Never log the exception's token-bearing repr; log its type only.
            logger.error(
                "Gmail token refresh failed for user_id=%s (%s); reconnect required.",
                user_id,
                type(exc).__name__,
            )
            # A REVOKED grant is permanent and must be written down; a network
            # blip is not. Only the former.
            if _is_permanently_revoked(exc):
                await mark_gmail_credential_revoked(user_id)
            return None

        await update_gmail_access_token(
            user_id,
            access_token=creds.token,
            token_expiry=creds.expiry or (datetime.utcnow() + timedelta(hours=1)),
        )

    return creds


def _batch_fetch_metadata(
    service: Any,
    ids: list[str],
    *,
    batch_size: int,
    pause_seconds: float,
) -> MetadataBatch:
    """Fetch Subject/From/Date + snippet for ``ids`` via Gmail batch requests.

    Instead of one ``messages.get`` round-trip per id (which turns a 1000-id
    page into 1000 serial HTTP calls and a serverless timeout), we group the
    gets into ``new_batch_http_request`` batches of at most ``batch_size``
    (Gmail caps a batch at 100). Each 100-message metadata batch costs ~500
    quota units, so we sleep ``pause_seconds`` between batches to stay under
    the per-user ~250 units/sec limit.

    Returns the ``{message_id: raw_metadata_response}`` map AND the number of
    requested ids it could not produce one for. Individual failed sub-requests
    are still dropped (logged by type only) rather than raised — one bad
    message must not sink the whole page — but they are no longer silent: the
    count is derived from what came back, not from the callback's exception
    argument, so an id answered with an empty body counts as lost too.
    """

    results: dict[str, dict] = {}

    def _on_result(request_id: str, response: Any, exception: Any) -> None:
        if exception is not None:
            logger.warning(
                "Gmail metadata sub-request failed: %s", type(exception).__name__
            )
            return
        if response is not None:
            results[request_id] = response

    # Clamped to ``_FULL_BATCH_SIZE`` rather than Gmail's 100 ceiling: the
    # configured ``gmail_batch_size`` was chosen when this fetched metadata.
    # Honouring it verbatim against ``format="full"`` would put up to 100 whole
    # messages in memory at once.
    chunk = max(1, min(batch_size, _FULL_BATCH_SIZE))
    bodies: dict[str, str] = {}
    for start in range(0, len(ids), chunk):
        window = ids[start : start + chunk]
        batch = service.new_batch_http_request(callback=_on_result)
        for message_id in window:
            batch.add(
                service.users()
                .messages()
                .get(userId="me", id=message_id, format="full"),
                request_id=message_id,
            )
        batch.execute()
        # Reduce each full payload to text, then REPLACE it with a slim copy
        # carrying only what `_parse_metadata_message` reads. Without this the
        # map accumulates whole message bodies across every batch of a
        # 2,000-message mine inside a 50 MB slot; the batch itself is transient,
        # but `results` is not.
        #
        # A new dict rather than popping `parts`/`body` off the one Gmail
        # handed back. Mutating a response this function does not own is how a
        # second read of the same object silently returns no body — which is
        # exactly what happened to the fixture in
        # `tests/test_body_is_never_persisted.py`, where the first call stripped
        # a module-level payload and every later call then classified on the
        # snippet while still reporting success.
        for message_id in window:
            raw = results.get(message_id)
            if not isinstance(raw, dict):
                continue
            payload = raw.get("payload")
            if not isinstance(payload, dict):
                # Malformed, and it must STAY malformed. Normalising it into a
                # slim well-formed shape here would make it parse, and a
                # message manufactured from garbage is precisely what
                # ``unreadable`` exists to count instead of inventing. Left
                # exactly as Gmail sent it so `_parse_metadata_message` still
                # rejects it (test_unparseable_metadata_also_counts_as_unreadable).
                continue
            text = extract_body_text(payload)
            if text:
                bodies[message_id] = text
            results[message_id] = {
                "id": raw.get("id", message_id),
                "threadId": raw.get("threadId", ""),
                "snippet": raw.get("snippet", ""),
                "payload": {"headers": payload.get("headers", [])},
            }
        if pause_seconds and (start + chunk) < len(ids):
            time.sleep(pause_seconds)

    # Count against the DISTINCT ids asked for: the results map is keyed by id,
    # so a repeated id could otherwise manufacture a phantom drop.
    dropped = len(set(ids)) - len(results)
    if dropped > 0:
        logger.warning(
            "Gmail metadata fetch lost %s of %s message(s); the scan is that "
            "much smaller than the mailbox.",
            dropped,
            len(set(ids)),
        )

    return MetadataBatch(messages=results, dropped=dropped, bodies=bodies)


def _collect_page(
    service: Any,
    *,
    query: str,
    page_size: int,
    page_token: Optional[str],
) -> MessagePage:
    """List one page of ids for ``query`` then batch-fetch their metadata.

    Pure with respect to Gmail *transport*: it drives whatever ``service`` it
    is handed, so tests inject a fake service and exercise pagination + batch
    collection + ordering without a token. ``page_size`` is clamped to Gmail's
    500-id ``messages.list`` ceiling, so exactly one list call feeds one page
    and Gmail's ``nextPageToken`` becomes our cursor.

    The page reports what it LOST as well as what it got (``unreadable``) and
    carries Gmail's ``resultSizeEstimate`` through untouched — see
    :class:`MessagePage` for what may and may not be concluded from either.
    """

    limit = max(1, min(page_size, _GMAIL_LIST_PAGE_MAX))
    listing = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=limit, pageToken=page_token)
        .execute()
    )
    refs = listing.get("messages", []) or []
    ids = [ref["id"] for ref in refs[:limit] if ref.get("id")]
    next_token = listing.get("nextPageToken")
    estimate = _result_size_estimate(listing)

    if not ids:
        return MessagePage(
            messages=[], next_page_token=next_token, result_size_estimate=estimate
        )

    fetched = _batch_fetch_metadata(
        service,
        ids,
        batch_size=settings.gmail_batch_size,
        pause_seconds=settings.gmail_batch_pause_seconds,
    )

    # Preserve Gmail's newest-first list order; drop ids whose metadata get
    # failed rather than emitting a hollow row.
    out: list[CloudGmailMessage] = []
    for message_id in ids:
        raw = fetched.messages.get(message_id)
        if raw is None:
            continue
        parsed = _parse_metadata_message(raw)
        if parsed is not None:
            out.append(parsed)

    # Everything listed but not emitted: the batch's own losses PLUS metadata
    # that came back and would not parse. Both shrink the page identically, so
    # reporting only the first would still understate the gap.
    return MessagePage(
        messages=out,
        next_page_token=next_token,
        unreadable=len(ids) - len(out),
        result_size_estimate=estimate,
        # Only for ids that actually produced a message: a body with no parsed
        # message beside it has nothing to be classified against, and carrying
        # it would be retaining body text for no reason at all.
        bodies={m.message_id: fetched.bodies[m.message_id] for m in out
                if m.message_id in fetched.bodies},
    )


def _result_size_estimate(listing: dict) -> int | None:
    """Gmail's ``resultSizeEstimate`` for a listing, as a non-negative int.

    An ESTIMATE, and a famously loose one for large result sets — it changes
    between pages of the same query and can differ from the number of messages
    that actually come back. Passed through because a progress denominator has
    to start somewhere, coerced defensively because a denominator that arrives
    as a string or a negative number is worse than none at all.
    """

    raw = listing.get("resultSizeEstimate")
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return max(value, 0)


async def fetch_message_page(
    user_id: uuid.UUID,
    *,
    query: str = DEFAULT_QUERY,
    page_size: Optional[int] = None,
    page_token: Optional[str] = None,
) -> Optional[MessagePage]:
    """Fetch one server-side page of messages for ``user_id``.

    Returns ``None`` when Gmail is not connected (so the router can answer
    409); otherwise a :class:`MessagePage` (possibly empty) with the cursor to
    request the next page. Read-only, metadata-only: ``messages.list`` +
    batched ``messages.get(format="metadata")`` — no bodies, no mutation.
    """

    creds = await load_valid_credentials(user_id)
    if creds is None:
        return None

    size = page_size or settings.gmail_fetch_page_size
    loop = asyncio.get_event_loop()

    def _run() -> MessagePage:
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return _collect_page(
            service, query=query, page_size=size, page_token=page_token
        )

    return await loop.run_in_executor(None, _run)


async def fetch_recent_messages(
    user_id: uuid.UUID,
    *,
    max_results: Optional[int] = None,
    query: str = DEFAULT_QUERY,
) -> Optional[list[CloudGmailMessage]]:
    """Fetch a single bounded page of recent messages for ``user_id``.

    Backwards-compatible convenience over :func:`fetch_message_page`: returns
    just the message list (no cursor) for callers that want one quick batch.
    Returns ``None`` when Gmail is not connected.
    """

    limit = max_results or settings.gmail_fetch_max_results
    page = await fetch_message_page(user_id, query=query, page_size=limit)
    if page is None:
        return None
    return page.messages


# =============================================================================
# Incremental read: mailbox historyId + users.history.list
# =============================================================================
#
# A full scan re-lists a fixed 12-month window on every sync — the reason the
# product "never remembers" it already synced. Gmail's own incremental
# primitive is the mailbox ``historyId``: store it once, then ask
# ``users.history.list(startHistoryId=…)`` for just what changed.

# Bounds on the history walk. Gmail returns history in ascending pages; a
# mailbox left unsynced for days can have a long tail, and one serverless
# invocation must not turn into an unbounded crawl. Blowing either bound is a
# ``truncated`` result → the caller full-scans instead (which is bounded too).
_HISTORY_MAX_PAGES = 10
_HISTORY_PAGE_SIZE = 500

# ``messagesAdded`` covers everything that entered the mailbox, including our
# own sends, drafts and junk. Filter those out so the incremental path sees the
# same kind of mail the ``in:inbox`` full scan does.
_HISTORY_EXCLUDED_LABELS = frozenset({"DRAFT", "SENT", "SPAM", "TRASH", "CHAT"})


def _is_history_expired(exc: HttpError) -> bool:
    """True when Gmail rejected ``startHistoryId`` as too old (HTTP 404).

    Gmail's documented signal that the stored cursor has aged out of the
    ~1-week history window. The caller must fall back to a full scan and
    re-baseline; surfacing it as an error would be wrong.
    """

    return getattr(getattr(exc, "resp", None), "status", None) == 404


def _mailbox_history_id(service: Any) -> Optional[str]:
    """Read the mailbox's CURRENT ``historyId`` via ``users.getProfile``."""

    profile = service.users().getProfile(userId="me").execute()
    value = profile.get("historyId")
    return str(value) if value else None


async def fetch_mailbox_history_id(user_id: uuid.UUID) -> Optional[str]:
    """Return the mailbox's current ``historyId`` for ``user_id``, or ``None``.

    ``None`` when Gmail is not connected *or* the profile read failed — the
    caller then simply does not advance its cursor, which costs one more full
    scan and never skips mail.

    Callers must capture this **before** they start reading messages: a message
    that lands mid-scan then falls after the recorded cursor and is picked up by
    the next run. Capturing it afterwards would silently skip it.
    """

    creds = await load_valid_credentials(user_id)
    if creds is None:
        return None

    loop = asyncio.get_event_loop()

    def _run() -> Optional[str]:
        try:
            service = build("gmail", "v1", credentials=creds, cache_discovery=False)
            return _mailbox_history_id(service)
        except Exception as exc:  # noqa: BLE001 — a profile read must never sink a sync
            logger.warning("Gmail getProfile failed: %s", type(exc).__name__)
            return None

    return await loop.run_in_executor(None, _run)


def _collect_history_ids(
    service: Any,
    *,
    start_history_id: str,
    max_messages: int,
    scope: MailScope,
) -> tuple[list[str], bool, bool]:
    """Walk ``users.history.list`` and return ``(ids, expired, truncated)``.

    Pure with respect to Gmail *transport* like :func:`_collect_page`, so tests
    drive it with a fake service — including one that raises a 404 ``HttpError``
    for an aged-out cursor.
    """

    ids: list[str] = []
    seen: set[str] = set()
    page_token: Optional[str] = None

    for _ in range(_HISTORY_MAX_PAGES):
        try:
            batch = (
                service.users()
                .history()
                .list(
                    userId="me",
                    startHistoryId=start_history_id,
                    historyTypes=["messageAdded"],
                    maxResults=_HISTORY_PAGE_SIZE,
                    pageToken=page_token,
                )
                .execute()
            )
        except HttpError as exc:
            if _is_history_expired(exc):
                logger.info(
                    "Gmail history cursor expired (404); falling back to a full scan."
                )
                return [], True, False
            raise

        for record in batch.get("history", []) or []:
            for added in record.get("messagesAdded", []) or []:
                message = added.get("message") or {}
                message_id = message.get("id")
                if not message_id or message_id in seen:
                    continue
                labels = set(message.get("labelIds") or [])
                if labels & _HISTORY_EXCLUDED_LABELS:
                    continue
                if scope != "anywhere" and "INBOX" not in labels:
                    continue
                seen.add(message_id)
                ids.append(message_id)
                if len(ids) > max_messages:
                    return ids[:max_messages], False, True

        page_token = batch.get("nextPageToken")
        if not page_token:
            return ids, False, False

    return ids, False, True


def _collect_history(
    service: Any,
    *,
    start_history_id: str,
    max_messages: int,
    scope: MailScope,
) -> HistoryPage:
    """Resolve the ids added since ``start_history_id`` into full messages."""

    ids, expired, truncated = _collect_history_ids(
        service,
        start_history_id=start_history_id,
        max_messages=max_messages,
        scope=scope,
    )
    if expired or truncated:
        return HistoryPage(messages=[], expired=expired, truncated=truncated)
    if not ids:
        return HistoryPage(messages=[])

    # Same batched metadata fetch the full scan uses — which also drops ids
    # whose ``get`` failed, and ``messagesAdded`` can name a message the user
    # has since deleted.
    fetched = _batch_fetch_metadata(
        service,
        ids,
        batch_size=settings.gmail_batch_size,
        pause_seconds=settings.gmail_batch_pause_seconds,
    )
    out: list[CloudGmailMessage] = []
    for message_id in ids:
        raw = fetched.messages.get(message_id)
        if raw is None:
            continue
        parsed = _parse_metadata_message(raw)
        if parsed is not None:
            out.append(parsed)

    # Gmail returns history oldest-first; the full scan returns newest-first.
    # Normalize so the two paths hand the pipeline the same ordering.
    out.sort(key=_received_sort_key, reverse=True)
    return HistoryPage(
        messages=out,
        unreadable=len(ids) - len(out),
        bodies={m.message_id: fetched.bodies[m.message_id] for m in out
                if m.message_id in fetched.bodies},
    )


def _received_sort_key(message: CloudGmailMessage) -> float:
    """Epoch-seconds sort key that never compares aware to naive datetimes.

    ``Date`` headers arrive both with and without a zone, and sorting a mix of
    aware and naive ``datetime`` objects raises. Undated mail sorts last.
    """

    received = message.received_at
    if received is None:
        return float("-inf")
    try:
        if received.tzinfo is None:
            received = received.replace(tzinfo=UTC)
        return received.timestamp()
    except (OverflowError, OSError, ValueError):
        return float("-inf")


async def fetch_history_messages(
    user_id: uuid.UUID,
    *,
    start_history_id: str,
    max_messages: int,
    scope: MailScope = "inbox",
) -> Optional[HistoryPage]:
    """Fetch the messages added since ``start_history_id`` for ``user_id``.

    Returns ``None`` when Gmail is not connected. Otherwise a
    :class:`HistoryPage` — possibly empty (nothing new), possibly flagged
    ``expired``/``truncated``, in which case the caller must full-scan.
    Read-only and metadata-only, exactly like the full-scan path.
    """

    creds = await load_valid_credentials(user_id)
    if creds is None:
        return None

    loop = asyncio.get_event_loop()

    def _run() -> HistoryPage:
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return _collect_history(
            service,
            start_history_id=start_history_id,
            max_messages=max_messages,
            scope=scope,
        )

    return await loop.run_in_executor(None, _run)


def _parse_metadata_message(raw: dict) -> Optional[CloudGmailMessage]:
    """Parse a ``format=metadata`` Gmail response into a CloudGmailMessage."""

    try:
        headers = {
            h["name"].lower(): h["value"]
            for h in raw.get("payload", {}).get("headers", [])
        }
        sender_name, sender_email = parseaddr(headers.get("from", ""))
        received_at: Optional[datetime]
        try:
            received_at = parsedate_to_datetime(headers.get("date", ""))
        except (TypeError, ValueError):
            received_at = None
        return CloudGmailMessage(
            message_id=raw.get("id", ""),
            thread_id=raw.get("threadId", ""),
            subject=headers.get("subject", "(No Subject)"),
            sender_name=sender_name or None,
            sender_email=sender_email,
            snippet=raw.get("snippet", "") or "",
            received_at=received_at,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to parse Gmail metadata message: %s", type(exc).__name__)
        return None
