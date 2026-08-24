"""The body is read to classify and never retained. Proven, not promised.

Why this file exists
--------------------

``cloud/gmail_client.py`` now fetches ``format="full"`` and hands the message
body to the classifier, because Gmail's ~200-character snippet is not enough
text to recognise a rejection (measured: of four real rejections in the owner's
mailbox, one was decidable from the snippet and three were not).

That changes what the product PUBLISHES about itself. ``/privacy`` used to say
"It never requests a message body", and the strength of that page is that its
claims are checked rather than asserted. The replacement claim is about
RETENTION — the body is read in flight and discarded, and only Gmail's own
short snippet is stored — and this file is what makes it true.

The method is a SENTINEL. Every faked message body contains a string that
appears nowhere else in the system. The scan is then driven end to end and the
sentinel is searched for in:

  * every column of every ``emails`` row,
  * every column of every ``training_data`` row (the SetFit retrain corpus,
    which is fed from ``email.body_snippet`` and must stay that way),
  * the full serialised body of every API response involved.

WHAT CHANGED ON 2026-08-23, and what the claim now is
-----------------------------------------------------

``emails.identity_role`` and ``emails.identity_req_id`` store a job title and a
requisition number DERIVED from the body. So a value computed from the body is
now retained, and the page has to say so rather than implying nothing crosses.

The claim that stays true is the one that always mattered: the body itself is
read in flight and discarded, and what is kept is bounded and of a kind the
product already stored — ``applications.position``, ``applications.role_token``
and ``applications.req_id`` have held exactly these values since
``f1a2c9b73d40``. What changed is where the title is read from, not what sort of
thing is kept.

That distinction is only worth anything if a capture running past the title
would be caught, so ``test_a_capture_that_overruns_drags_the_sentinel_in``
places the sentinel IMMEDIATELY after the point a role capture must stop. A
marker anywhere else makes the assertion vacuous: the column could never have
received it. That test is the one that can fail.

Searching the whole serialised row/response rather than named fields is
deliberate. Field-by-field assertions only cover the fields somebody thought
of, and the failure this guards against is precisely a body reaching a field
nobody considered — a column added later, a response model gaining a passthrough.

The positive control is not optional here. An assertion that a string is ABSENT
passes trivially if the string was never fetched in the first place, which would
make this whole file green while proving nothing — so
``test_the_body_really_was_fetched`` asserts the sentinel IS present in the
in-flight bodies, and the persistence tests are only meaningful because it
passes.
"""

from __future__ import annotations

import importlib
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from cryptography.fernet import Fernet
import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

from jobtracker.cloud import gmail_client as gc
from tests.test_gmail_client_fetch import FakeService

# Spelled to match the shape `.gitleaks.toml` already allowlists BY VALUE for
# every other cloud test file ("…-test-jwt-secret-at-least-32-bytes-long-hs256").
# Widening the allowlist for a new spelling would make it match more real
# secrets; matching the established one costs nothing.
JWT_SECRET = "body-never-persisted-test-jwt-secret-at-least-32-bytes-long-hs256"
OWNER = "aaaaaaaa-1111-2222-3333-444444444444"
ENC_KEY = Fernet.generate_key().decode()

# Appears nowhere else in the repo or the test data. If this string is ever
# found in the database or in a response, a body has been retained.
SENTINEL = "ZZQX-body-sentinel-must-never-be-stored-9f4c2a"

# A real ATS rejection's shape: the decision sentence sits AFTER the polite
# preamble, which is exactly why the snippet cannot see it. The snippet here is
# truncated before the verdict, the way Gmail's really is.
REJECTION_SNIPPET = (
    "Hi Ayush, Thank you for your interest in the Embedded Software Engineer, "
    "Access Control opportunity. It means a lot to us that you would consider "
    "joining our mission here at Verkada. Although your"
)
REJECTION_BODY = (
    f"{REJECTION_SNIPPET} background is impressive, we regret to inform you "
    f"that we will not be proceeding with your candidacy for this role. "
    f"{SENTINEL} We wish you the best in your search."
)


def _full_message(mid: str, *, subject: str, sender: str, body: str, snippet: str) -> dict:
    """A ``format="full"`` Gmail response with a real multipart body."""

    import base64

    return {
        "id": mid,
        "threadId": f"t-{mid}",
        "snippet": snippet,
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
                {"name": "Date", "value": "Tue, 11 Aug 2026 09:00:00 +0000"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()},
                },
            ],
        },
    }


RAW = {
    "m-rejection": _full_message(
        "m-rejection",
        subject="Thank you for your interest in Verkada, Ayush",
        sender="Verkada <no-reply@us.greenhouse-mail.io>",
        body=REJECTION_BODY,
        snippet=REJECTION_SNIPPET,
    )
}


def _token_for(user_id: str) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {"sub": user_id, "aud": "authenticated", "iat": now, "exp": now + 300},
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture(autouse=True)
def _no_batch_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gc.settings, "gmail_batch_pause_seconds", 0.0)


@pytest.fixture
async def cloud_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    monkeypatch.setenv("JOBTRACKER_DEPLOYMENT", "cloud")
    monkeypatch.setenv("JOBTRACKER_ENVIRONMENT", "test")
    monkeypatch.setenv("JOBTRACKER_SUPABASE_JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("JOBTRACKER_SECRET_ENCRYPTION_KEY", ENC_KEY)
    # ``GET /gmail/inbox`` calls ``_require_configured()`` before anything else
    # and 503s without these two. Without them the inbox test below would get a
    # 503 whose body trivially lacks the sentinel — an absence assertion that
    # passes because the endpoint never ran.
    monkeypatch.setenv("JOBTRACKER_GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("JOBTRACKER_GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv(
        "JOBTRACKER_GMAIL_OAUTH_REDIRECT_URI", "http://test/gmail/callback"
    )
    monkeypatch.setenv("JOBTRACKER_WEB_APP_URL", "http://test")

    import jobtracker.config as config_module
    import jobtracker.database.connection as connection_module

    importlib.reload(config_module)
    connection_module._engine = None

    import jobtracker.auth.supabase_jwt as auth_module

    importlib.reload(auth_module)

    # Rebind the credential store's ``settings`` global to the reloaded config,
    # or ``secret_encryption_key`` is invisible here because an earlier test
    # file imported this module against a keyless settings object.
    import jobtracker.credentials.cloud as cred_cloud_module

    importlib.reload(cred_cloud_module)

    import jobtracker.cloud.applications as cloud_apps_module

    importlib.reload(cloud_apps_module)

    import jobtracker.cloud.gmail_oauth as gmail_module

    importlib.reload(gmail_module)

    import jobtracker.main_cloud as main_cloud_module

    importlib.reload(main_cloud_module)

    # Make the classifier the CLOUD one. Two separate things are needed and
    # neither alone is enough:
    #
    #   * ``hybrid.settings`` is bound at import, so reloading the config module
    #     leaves it pointing at the old, non-cloud settings object and
    #     ``_cloud_rules_only`` comes out False. Rebound rather than reloaded so
    #     that every existing reference to ``get_hybrid_classifier`` keeps
    #     working — the package's ``__init__`` holds one.
    #   * the singleton captures that flag at CONSTRUCTION, so a classifier
    #     built by an earlier, non-cloud test survives the rebinding.
    #
    # Without both, this file runs the full SetFit cascade, which production
    # does not run, and which silently overrode the rules verdict — the tests
    # below asserted ``rejection`` and got ``applied`` from a model that never
    # executes on the deployment they are describing.
    import jobtracker.classifier.hybrid as hybrid_module

    hybrid_module.settings = config_module.settings
    hybrid_module._classifier = None

    # ``GET /gmail/inbox`` consults a MODULE-LEVEL cache before it does any
    # work. A page left there by an earlier test would be served straight back,
    # so the inbox test below would assert against a response the handler under
    # test never built.
    gmail_module._INBOX_CACHE.clear()

    from jobtracker.database import init_db

    await init_db()

    yield main_cloud_module.app

    if connection_module._engine is not None:
        await connection_module._engine.dispose()
    connection_module._engine = None
    hybrid_module._classifier = None
    monkeypatch.undo()
    importlib.reload(config_module)


def _collect(service: Any = None) -> Any:
    """Drive the REAL fetch path against a fake Gmail service."""

    service = service or FakeService(pages=[(["m-rejection"], None)], metadata=RAW)
    return gc._collect_page(service, query="in:inbox", page_size=10, page_token=None)


# The tables the sweep below MUST reach for the privacy page's "every column of
# every stored row" to be a true sentence. Named so that a table disappearing
# from the schema fails loudly rather than shrinking the sweep in silence. The
# sweep itself is not limited to these — it walks whatever `sqlite_master`
# reports, so a table added later is covered the day it is added.
TABLES_THAT_MUST_BE_SWEPT = frozenset(
    {
        "applications",
        "contacts",
        "email_embeddings",
        "emails",
        "gmail_sync_enrollment",
        "interviews",
        "sync_state",
        "training_data",
        "user_credentials",
    }
)


async def _sweep_every_table(session: Any) -> tuple[dict[str, int], list[str]]:
    """``SELECT *`` every table in the schema; return row counts + haystacks.

    Deliberately schema-driven rather than a hand-written list of models. The
    privacy page says "every column of every stored row", and a list of three
    ORM classes is not that sentence — it is the subset somebody remembered.
    This also reaches the FTS5 shadow tables (``emails_fts_data`` and friends),
    which hold indexed COPIES of whatever text columns are indexed and would
    otherwise be a body's second home.
    """

    from sqlalchemy import text

    names = sorted(
        r[0]
        for r in (
            await session.exec(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        ).all()
    )

    counts: dict[str, int] = {}
    haystacks: list[str] = []
    for name in names:
        rows = (await session.exec(text(f'SELECT * FROM "{name}"'))).all()
        counts[name] = len(rows)
        for row in rows:
            for value in row:
                # bytes columns (the FTS shadow blobs) are decoded as well as
                # repr'd: a body indexed into an FTS b-tree is a byte run, and
                # `repr(b"...")` escapes it out of reach of a plain substring
                # search.
                if isinstance(value, (bytes, bytearray)):
                    haystacks.append(bytes(value).decode("utf-8", errors="ignore"))
                haystacks.append(f"{name}:{value!r}")

    return counts, haystacks


# =============================================================================
# Positive control — without this the rest of the file proves nothing
# =============================================================================


def test_the_body_really_was_fetched() -> None:
    """The sentinel IS in the in-flight bodies, and the fetch asked for `full`.

    Every other test here asserts an ABSENCE, and an absence is free if nothing
    was ever fetched. This is the test that makes the others mean something.
    """

    service = FakeService(pages=[(["m-rejection"], None)], metadata=RAW)
    page = _collect(service)

    assert len(page.messages) == 1
    assert SENTINEL in page.bodies["m-rejection"], (
        "the body never reached the classifier — the absence tests below would "
        "then pass without proving anything"
    )
    # And it was asked for as a body, not inferred from a snippet.
    assert service.get_formats == ["full"], service.get_formats


def test_fetching_twice_returns_the_body_twice() -> None:
    """The fetch must not consume what it reads.

    ``_batch_fetch_metadata`` reduces each full payload to text and then slims
    the stored response down, and the first version of that did it by popping
    ``parts`` off the dict Gmail returned — mutating an object it did not own.
    Against a shared fixture the second call then found no parts, extracted no
    body, and fell back to the snippet, reporting a perfectly successful scan
    that had quietly stopped reading bodies.

    In production each response is freshly deserialised, so this would not have
    shown up until something retried or cached a payload. It is pinned here
    because the failure is silent by construction: a scan with no bodies looks
    exactly like a scan with bodies, only less accurate.
    """

    first = _collect()
    second = _collect()

    assert SENTINEL in first.bodies["m-rejection"]
    assert SENTINEL in second.bodies["m-rejection"], (
        "the second fetch got no body — something consumed the first one"
    )
    assert first.messages[0].subject == second.messages[0].subject


def test_the_fetched_body_is_what_makes_the_verdict_right() -> None:
    """And the point of fetching it: the snippet alone gets this message wrong.

    Not decoration. If the body did not change the verdict there would be no
    reason to read it, and no reason to rewrite the privacy page.
    """

    from jobtracker.classifier.rules import RulesClassifier
    from jobtracker.database.models import EmailCategory

    rules = RulesClassifier()
    subject = "Thank you for your interest in Verkada, Ayush"
    sender = "no-reply@us.greenhouse-mail.io"

    from_snippet = rules.classify(subject, REJECTION_SNIPPET, sender)
    from_body = rules.classify(subject, REJECTION_BODY, sender)

    assert from_snippet.category is EmailCategory.APPLIED, from_snippet.scores
    assert from_body.category is EmailCategory.REJECTION, from_body.scores


# =============================================================================
# The prohibition
# =============================================================================


def test_the_body_is_not_on_the_parsed_message() -> None:
    """``CloudGmailMessage`` is what every persist path receives.

    It must carry no body, by shape — that is what stops a future column
    addition from mapping one onto an ``Email`` row.

    Mutation: adding ``body`` to the dataclass and populating it → fails.
    """

    page = _collect()
    msg = page.messages[0]

    assert not hasattr(msg, "body")
    assert not hasattr(msg, "body_text")
    assert SENTINEL not in repr(msg)
    # Gmail's own snippet, unchanged — never re-derived from the body we read.
    assert msg.snippet == REJECTION_SNIPPET


async def test_the_body_reaches_no_pipeline_item(cloud_app) -> None:
    """The classifier consumes it; the item it produces does not carry it.

    Takes ``cloud_app`` purely for its ENVIRONMENT, not its app. Without it
    ``get_classifier()`` returns whatever singleton an earlier test built, and
    off the cloud deployment that is the full hybrid cascade — which loads
    SetFit, overrides the rules verdict, and answered ``applied`` here. In
    production this path is rules-only, so a test that lets the semantic layers
    run is not testing the deployed classifier at all.

    Mutation: adding ``body=text`` to the PipelineItem → fails.
    """

    from jobtracker.classifier import get_classifier
    from jobtracker.cloud import gmail_oauth, pipeline

    page = _collect()
    items = await gmail_oauth._classify_messages(
        page.messages, get_classifier(), pipeline, page.bodies
    )

    assert len(items) == 1
    assert SENTINEL not in repr(items[0]), "the body rode along on the pipeline item"
    # And it did its job on the way through. This assertion is load-bearing in
    # a way the absence checks are not: it can only hold if a BODY was
    # classified, so it doubles as a guard that the fetch is still working.
    # It caught a real one — `_batch_fetch_metadata` used to strip `parts` off
    # the response dict in place, so the second call against a shared fixture
    # silently classified on the snippet and answered `applied`.
    assert items[0].category == "rejection", (
        f"classified on the snippet, not the body — bodies={list(page.bodies)}"
    )


async def test_the_inbox_endpoint_never_serves_the_body(cloud_app, monkeypatch) -> None:
    """``GET /gmail/inbox`` is the public endpoint that reads bodies. Sweep it.

    This is the gap that mattered most. The file used to check four responses
    and this was not one of them, even though it is the handler that fetches
    bodies in the first place and the one whose docstring is published as
    OpenAPI contract text. A full body in this response passed the whole file
    green.

    The fake page is the REAL fetch path's output — ``_collect()`` returns the
    same ``MessagePage`` the Gmail client builds, sentinel-carrying ``bodies``
    and all — so this drives the handler with exactly what production hands it.

    Mutation: ``snippet=unescape(page.bodies.get(mid) or msg.snippet)[:500]``
    at the ``InboxVerdict`` construction → fails.
    """

    import jobtracker.cloud.gmail_client as gmail_client_module

    page = _collect()
    assert SENTINEL in page.bodies["m-rejection"], "fixture regressed"

    async def _fake_page(user_id: Any, **_kwargs: Any) -> Any:
        return page

    monkeypatch.setattr(gmail_client_module, "fetch_message_page", _fake_page)

    headers = {"Authorization": f"Bearer {_token_for(OWNER)}"}
    async with AsyncClient(
        transport=ASGITransport(app=cloud_app), base_url="http://test"
    ) as client:
        res = await client.get("/gmail/inbox", headers=headers)

    assert res.status_code == 200, res.text
    body = res.json()

    # POSITIVE CONTROL, and the only reason the absence below means anything.
    # `test_the_fetched_body_is_what_makes_the_verdict_right` proves the snippet
    # alone yields APPLIED and only the body yields REJECTION. So a `rejection`
    # verdict here is proof the BODY reached the classifier on THIS path. Without
    # it, an empty `bodies` dict would make the sentinel absent for free.
    assert body["scanned"] == 1, body
    verdict = body["verdicts"][0]
    assert verdict["category"] == "rejection", (
        f"the inbox path classified on the snippet, not the body: {verdict}"
    )

    # And having read it, the response does not carry it — whole serialised
    # response, not the fields anyone thought to name.
    assert SENTINEL not in res.text, "GET /gmail/inbox served the body"
    # The verdict carries GMAIL's snippet, not a slice of the text it judged.
    assert verdict["snippet"] == REJECTION_SNIPPET


async def test_the_body_is_never_logged(cloud_app, caplog, monkeypatch) -> None:
    """"…never logged" is a third of the published claim and had no test at all.

    ``caplog`` appeared zero times in this file. Logging the body at INFO inside
    the very function the other tests drive left every one of them green, which
    is exactly the shape of defect the rest of this file exists to prevent.

    Captured at DEBUG across the whole fetch → classify → sync → inbox path,
    because a body reaches a log most plausibly through a debug line somebody
    added while chasing a misclassification and forgot to remove.

    Mutation: ``logger.info("classifying %s", text)`` in ``gmail_inbox`` → fails.
    """

    import logging

    import jobtracker.cloud.gmail_client as gmail_client_module
    from jobtracker.classifier import get_classifier
    from jobtracker.cloud import gmail_oauth, pipeline

    caplog.set_level(logging.DEBUG)

    page = _collect()
    items = await gmail_oauth._classify_messages(
        page.messages, get_classifier(), pipeline, page.bodies
    )
    payload = [
        {
            "message_id": i.message_id,
            "category": i.category,
            "sender_email": i.sender_email,
            "subject": i.subject,
            "sender_name": i.sender_name,
            "received_at": i.received_at.isoformat() if i.received_at else None,
            "confidence": i.confidence,
            "thread_id": i.thread_id,
            "snippet": i.snippet,
        }
        for i in items
    ]

    async def _fake_page(user_id: Any, **_kwargs: Any) -> Any:
        return page

    monkeypatch.setattr(gmail_client_module, "fetch_message_page", _fake_page)

    headers = {"Authorization": f"Bearer {_token_for(OWNER)}"}
    async with AsyncClient(
        transport=ASGITransport(app=cloud_app), base_url="http://test"
    ) as client:
        sync = await client.post("/gmail/sync", json={"items": payload}, headers=headers)
        assert sync.status_code == 200, sync.text
        inbox = await client.get("/gmail/inbox", headers=headers)
        assert inbox.status_code == 200, inbox.text

    # POSITIVE CONTROL on the INSTRUMENT. An assertion that no record contains
    # the sentinel is free if caplog captured nothing — and caplog defaults to
    # WARNING and only sees records that propagate to root, so "captured
    # nothing" is the likely state, not a far-fetched one. The sync path emits
    # its summary at INFO from `jobtracker.cloud.gmail_oauth`; requiring a
    # record from that logger proves the handler's own records are visible here.
    assert caplog.records, "caplog captured nothing — the sweep below proves nothing"
    assert any(r.name.startswith("jobtracker.") for r in caplog.records), (
        "no record from a jobtracker logger reached caplog; product logging is "
        f"invisible to this test: {sorted({r.name for r in caplog.records})}"
    )

    # The sweep. `getMessage()` renders %-args, so a body passed as a lazy
    # logging argument is caught as well as one f-string'd into the message.
    for record in caplog.records:
        haystack = f"{record.name} {record.msg!r} {record.args!r} {record.getMessage()}"
        assert SENTINEL not in haystack, (
            f"a body was logged by {record.name} at {record.levelname}: "
            f"{record.getMessage()[:200]}"
        )


async def test_no_database_row_and_no_response_holds_the_body(cloud_app) -> None:
    """End to end: fetch → classify → sync → store → read back.

    Searches whole serialised rows and whole response bodies rather than named
    fields, because the failure this guards against is a body reaching a field
    nobody thought to assert on.

    Mutation: setting ``body_text=<the body>`` at the persist site in
    ``_persist_message_refs`` → fails on the ``emails`` sweep.
    """

    from sqlmodel import select

    from jobtracker.classifier import get_classifier
    from jobtracker.cloud import gmail_oauth, pipeline
    from jobtracker.database.connection import get_session
    from jobtracker.database.models import Email, TrainingData

    page = _collect()
    items = await gmail_oauth._classify_messages(
        page.messages, get_classifier(), pipeline, page.bodies
    )

    payload = [
        {
            "message_id": i.message_id,
            "category": i.category,
            "sender_email": i.sender_email,
            "subject": i.subject,
            "sender_name": i.sender_name,
            "received_at": i.received_at.isoformat() if i.received_at else None,
            "confidence": i.confidence,
            "thread_id": i.thread_id,
            "snippet": i.snippet,
        }
        for i in items
    ]

    headers = {"Authorization": f"Bearer {_token_for(OWNER)}"}
    async with AsyncClient(
        transport=ASGITransport(app=cloud_app), base_url="http://test"
    ) as client:
        sync = await client.post("/gmail/sync", json={"items": payload}, headers=headers)
        assert sync.status_code == 200, sync.text
        assert SENTINEL not in sync.text, "the sync response echoed the body back"

        mail = await client.get(
            "/applications/mail", params={"page_size": 50}, headers=headers
        )
        assert mail.status_code == 200, mail.text
        assert SENTINEL not in mail.text, "the filed ledger served the body"

        apps = await client.get("/applications", headers=headers)
        assert SENTINEL not in apps.text, "the board served the body"

    # Now the database itself — every column of every row, not a chosen few.
    async with get_session() as session:
        emails = (await session.exec(select(Email))).all()
        training = (await session.exec(select(TrainingData))).all()

    assert emails, "nothing was stored, so this test proved nothing"
    for row in emails:
        dumped = row.model_dump()
        assert SENTINEL not in str(dumped), f"a body reached emails: {dumped.keys()}"
        # The stored preview must remain GMAIL's snippet.
        assert row.body_text is None
        assert row.body_html is None
        # STRUCTURAL, not positional. The sentinel check above only catches a
        # body because the sentinel happens to sit at offset 313 of a 396-char
        # body and the column truncates at 500 — a body PREFIX that stops short
        # of the sentinel is a retained body and passed every assertion in this
        # file. What the privacy page promises is that the stored preview is
        # Gmail's own snippet, so assert exactly that: equality, not absence.
        assert row.body_snippet == REJECTION_SNIPPET, (
            "the stored preview is not Gmail's snippet — something re-derived "
            f"it from the body we read: {row.body_snippet!r}"
        )

    for row in training:
        assert SENTINEL not in str(row.model_dump()), "a body reached training_data"

    # And every OTHER table. "Any stored column" is the published claim; two ORM
    # classes are not that. `applications` in particular holds `req_id` and
    # `role_token`, both derived from message text and neither swept nor served
    # by any response this file checks.
    async with get_session() as session:
        counts, haystacks = await _sweep_every_table(session)

    missing = TABLES_THAT_MUST_BE_SWEPT - counts.keys()
    assert not missing, f"the sweep never reached: {sorted(missing)}"
    # Positive controls: a sweep over empty tables proves nothing, so require
    # rows in the two the scan is supposed to have written.
    assert counts["emails"] > 0, "no emails row — the sweep proved nothing"
    assert counts["applications"] > 0, "no applications row — the sweep proved nothing"

    for haystack in haystacks:
        assert SENTINEL not in haystack, f"a body reached a stored column: {haystack[:200]}"


async def test_a_correction_does_not_carry_the_body_into_training_data(
    cloud_app,
) -> None:
    """``training_data`` is fed from ``email.body_snippet``, and must stay so.

    This is the path a body would most plausibly leak down later: a correction
    writes the SetFit retrain corpus, and the obvious "improvement" is to give
    it the full text it was classified on. That would retain the body in a
    second table, one the privacy page's field list does not even cover.

    Mutation: passing the body to ``_add_training_example`` → fails.
    """

    from sqlmodel import select

    from jobtracker.classifier import get_classifier
    from jobtracker.cloud import gmail_oauth, pipeline
    from jobtracker.database.connection import get_session
    from jobtracker.database.models import TrainingData

    page = _collect()
    items = await gmail_oauth._classify_messages(
        page.messages, get_classifier(), pipeline, page.bodies
    )
    payload = [
        {
            "message_id": i.message_id,
            "category": i.category,
            "sender_email": i.sender_email,
            "subject": i.subject,
            "sender_name": i.sender_name,
            "received_at": i.received_at.isoformat() if i.received_at else None,
            "confidence": i.confidence,
            "thread_id": i.thread_id,
            "snippet": i.snippet,
        }
        for i in items
    ]

    headers = {"Authorization": f"Bearer {_token_for(OWNER)}"}
    async with AsyncClient(
        transport=ASGITransport(app=cloud_app), base_url="http://test"
    ) as client:
        await client.post("/gmail/sync", json={"items": payload}, headers=headers)
        res = await client.post(
            "/applications/review/m-rejection/classify",
            json={"category": "rejection", "company": "Verkada"},
            headers=headers,
        )
        assert res.status_code == 200, res.text
        assert SENTINEL not in res.text

    async with get_session() as session:
        training = (await session.exec(select(TrainingData))).all()

    assert training, "no training example was written, so this proved nothing"
    for row in training:
        assert SENTINEL not in str(row.model_dump())
        assert row.body_text == REJECTION_SNIPPET or SENTINEL not in (
            row.body_text or ""
        )
        # The line above is satisfied by its second branch whenever the sentinel
        # is absent, so it does not actually pin the text. This does, and it is
        # what makes `training_data` an INDEPENDENT check rather than a second
        # detector on the same leak: `_add_training_example` reads
        # `email.body_snippet`, so a sentinel can only arrive here if it already
        # reached `emails`. Equality catches the case the sentinel cannot — a
        # future "improvement" that feeds the corpus the full text the message
        # was classified on reddens here even with no sentinel in play.
        assert row.body_text == REJECTION_SNIPPET, (
            "the retrain corpus is no longer being fed Gmail's snippet: "
            f"{row.body_text!r}"
        )


# ── the derived identity is bounded, and the boundary is tested ──────────────

#: A body whose job title is followed IMMEDIATELY by the sentinel. There is no
#: punctuation between the title's terminator and the marker beyond the single
#: space the capture must stop at, so a role pattern that runs one token long
#: takes the sentinel with it into ``emails.identity_role``.
#:
#: This is the only arrangement that makes the absence assertion mean anything.
#: A sentinel further into the body could never reach the column whatever the
#: pattern did, and the test would pass on a capture of any length.
BOUNDARY_BODY = (
    "Hi Ayush, Thank you for applying to the Staff Platform Engineer position "
    f"{SENTINEL} at Northwind Systems. We review every application carefully "
    "and someone from the team will be in touch."
)


def test_a_capture_that_overruns_drags_the_sentinel_in() -> None:
    """The boundary, asserted from both sides.

    POSITIVE CONTROL FIRST: the identity really was derived from this text, and
    it is the title. Without that, "the sentinel is absent" is satisfied by an
    extractor that returns None for everything.
    """

    from jobtracker.cloud import pipeline

    role = pipeline.role_from_message("Thanks for applying", BOUNDARY_BODY)

    assert role == "Staff Platform Engineer", (
        "the positive control failed: if no role is captured here, the absence "
        "assertion below proves nothing about where a capture stops"
    )
    assert SENTINEL not in role


def test_the_boundary_case_can_actually_fail() -> None:
    """The mutation, run rather than described.

    A pattern whose capture is allowed to cross the terminator DOES take the
    sentinel, which is what makes the test above a real check and not a
    restatement of the extractor's current behaviour.
    """

    import re

    from jobtracker.cloud.pipeline import _clean_role

    overrunning = re.compile(
        r"\bapplying\s+to\s+the\s+(?P<role>[^.!?\n]{3,120}?)\s+at\s+[A-Z]"
    )
    match = overrunning.search(BOUNDARY_BODY)
    assert match is not None
    assert SENTINEL in (_clean_role(match.group("role")) or ""), (
        "the mutation did not overrun, so it does not demonstrate the boundary"
    )


@pytest.mark.asyncio
async def test_the_derived_identity_is_stored_and_the_body_is_not(cloud_app) -> None:
    """Both halves of the claim, on one row, end to end.

    The row must carry the identity the reader derived from the BODY — that is
    the whole point of the columns, and asserting only the absence of the
    sentinel would pass just as well if nothing were derived at all — and it
    must not carry the body.

    Mutation: dropping ``identity_role`` from the ``PipelineItem`` built in
    ``_classify_messages`` → the stored value falls back to what the snippet
    yields, which for this fixture is nothing, and the first assertion fails.
    """

    from sqlmodel import select

    from jobtracker.classifier import get_classifier
    from jobtracker.cloud import gmail_oauth, pipeline
    from jobtracker.database.connection import get_session
    from jobtracker.database.models import Email

    page = _collect()
    items = await gmail_oauth._classify_messages(
        page.messages, get_classifier(), pipeline, page.bodies
    )

    derived = {i.message_id: (i.identity_role, i.identity_req_id) for i in items}
    assert any(role for role, _ in derived.values()), (
        "no message derived a role at all, so this test would pass without the "
        "reader deriving anything"
    )
    for role, req in derived.values():
        assert role is not None and req is not None, (
            "a message this function READ must record 'derived, names nothing' "
            "as an empty string, never None — None means the reader never ran "
            "and sends every downstream site back to the snippet"
        )
        assert SENTINEL not in role and SENTINEL not in req

    async with get_session() as session:
        rows = (await session.exec(select(Email))).all()
        for row in rows:
            assert SENTINEL not in repr(row), (
                "a body reached a stored column; the derived identity must be a "
                "bounded title, never the text it was read from"
            )
