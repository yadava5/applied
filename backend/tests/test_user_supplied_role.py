"""A role the sync can never know, typed by the person who applied.

Issue #72. Every application filed from Gmail lands with ``position = ""`` for
two independent reasons: at the time, the Gmail path fetched ``format=metadata``
so no body was ever read, and ``_role_from_subject`` runs four regexes over a
subject line that names the COMPANY — "Thanks for applying to Supabase" — and
never the role. The first reason has since changed (the fetch reads bodies now,
and discards them), but the field is still the human's: nothing extracts a role
from the body, and the stored row still holds only the snippet.
Both hold for all three of the owner's real production subjects.

The chosen answer is the cheapest honest one: let the user type it, and remember
it. What that costs is a way to say "this field is the human's now", because a
sync that later learns to extract roles must not overwrite one.

The mechanism is ``position_source``, and the tests below are mostly about why
it is a NEW column rather than the ``source`` flip ``record_status_correction``
uses. ``_is_auto_row(source)`` gates the status advance, the reopen-after-
rejection evidence and the employer-name restyle as well as the role, all inside
one ``if`` at ``upsert_applications_for_user``. Flipping ``source`` to protect a
typed job title would therefore also stop a later rejection email from moving
the row to REJECTED — a real regression, caused by filling in a job title.
``due_source`` is the precedent that fits: per-field provenance, set by the user
route, honoured by the sync, touching nothing else.

``role_token`` is deliberately NOT written here; see
:func:`test_a_typed_role_leaves_the_rows_identity_alone` for the reasoning.
"""

from __future__ import annotations

import datetime
import time
import uuid as _uuid
from collections.abc import AsyncIterator
from typing import Any

import jwt as pyjwt
import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from jobtracker.cloud import applications as apps
from jobtracker.cloud import pipeline as p
from jobtracker.database.models import Application, ApplicationStatus

USER = _uuid.UUID("7c1d9e40-5b2a-4f18-9a63-2e8c4d0b7f51")
OTHER = _uuid.UUID("11111111-2222-3333-4444-555555555555")

BASE = datetime.datetime(2026, 8, 13, 9, 0)
SUPABASE = "no-reply@ashbyhq.com"

# The real shape from the issue: the subject names the employer, the snippet
# says nothing about a role either, so the pipeline extracts none.
ACK_SUBJECT = "Thanks for applying to Supabase"
ACK_SNIPPET = (
    "Hi Ayush, thanks for applying! We&#39;ve received your application and the "
    "team will review it shortly."
)

# A LATER message that does name a role. Nothing in the Gmail path produces one
# today, which is exactly why the guard has to be tested against mail that does
# — the protection is worth nothing if it is only ever exercised by a sync that
# had nothing to write in the first place.
ROLED_SUBJECT = "Your application for the Data Scientist role at Supabase"
ROLED_SNIPPET = "Hi Ayush, an update on your Data Scientist application."


def at(minutes: int) -> datetime.datetime:
    return BASE + datetime.timedelta(minutes=minutes)


def item(
    message_id: str,
    *,
    subject: str = ACK_SUBJECT,
    snippet: str = ACK_SNIPPET,
    category: str = "applied",
    minutes: int = 0,
) -> p.PipelineItem:
    return p.PipelineItem(
        message_id=message_id,
        thread_id=f"th-{message_id}",
        subject=subject,
        sender_email=SUPABASE,
        sender_name="Supabase",
        received_at=at(minutes),
        category=category,
        confidence=0.95,
        snippet=snippet,
    )


ACK = item("m1", minutes=0)
ROLED = item("m2", subject=ROLED_SUBJECT, snippet=ROLED_SNIPPET, minutes=100)
REJECTION = item(
    "m3",
    subject="Update on your application",
    snippet="We have decided not to move forward at this time.",
    category="rejection",
    minutes=200,
)


def _rolled(items: list[p.PipelineItem]):
    return p.roll_up_applications(items)


async def _rows(session, user=USER) -> list[Application]:
    return list(
        (await session.exec(select(Application).where(Application.user_id == user))).all()
    )


async def _only(session, user=USER) -> Application:
    rows = await _rows(session, user)
    assert len(rows) == 1, [(r.id, r.company, r.position) for r in rows]
    return rows[0]


# --- the premise ---------------------------------------------------------------


def test_the_acknowledgement_really_does_name_no_role():
    """Guard on the fixture, not on the product.

    If a future extraction improvement starts finding a role in this subject,
    every test below would still pass while testing nothing — the sync would be
    writing a role the user never had to type. This fails loudly instead.
    """

    assert p.role_from_message(ACK_SUBJECT, ACK_SNIPPET) is None
    # And the one that DOES name a role is genuinely extracted, or the guard
    # tests below are exercising a no-op.
    assert p.role_from_message(ROLED_SUBJECT, ROLED_SNIPPET) is not None


async def test_a_gmail_row_starts_with_no_role_and_no_source(test_session):
    await apps.sync_gmail_pipeline_additive(test_session, USER, _rolled([ACK]), [])

    row = await _only(test_session)
    assert row.position == ""
    assert row.position_source is None
    assert row.source == apps.SOURCE_GMAIL_AUTO


# --- the feature ---------------------------------------------------------------


async def test_a_typed_role_is_stored_and_marked_as_the_users(test_session):
    await apps.sync_gmail_pipeline_additive(test_session, USER, _rolled([ACK]), [])
    row_id = (await _only(test_session)).id

    updated = await apps.record_role_correction(
        test_session, USER, row_id, "Backend Engineer"
    )

    assert updated is not None
    assert updated.position == "Backend Engineer"
    assert updated.position_source == apps.ROLE_FROM_USER


async def test_a_typed_role_survives_a_sync_that_extracts_one(test_session):
    """The whole point. A later sync that DOES find a role must not overrule it.

    Without the ``position_source`` guard the second sync overwrites the typed
    title, because the row is still an auto row and ``r.role`` now differs from
    what is stored — the exact branch at ``upsert_applications_for_user``.
    """

    await apps.sync_gmail_pipeline_additive(test_session, USER, _rolled([ACK]), [])
    row_id = (await _only(test_session)).id
    await apps.record_role_correction(test_session, USER, row_id, "Backend Engineer")

    await apps.sync_gmail_pipeline_additive(
        test_session, USER, _rolled([ACK, ROLED]), []
    )

    row = await _only(test_session)
    assert row.id == row_id
    assert row.position == "Backend Engineer"
    assert row.position_source == apps.ROLE_FROM_USER


async def test_a_typed_role_does_not_freeze_the_rows_status(test_session):
    """Why this is not the ``source`` flip.

    ``record_status_correction`` makes a status sticky by moving the row off
    ``gmail`` — and ``_is_auto_row`` gates the status advance and the reopen
    evidence too, so the same trick applied to a role would mean typing a job
    title silently stops rejections from ever landing on that card again. The
    row stays the sync's for everything except the one field the human filled.
    """

    await apps.sync_gmail_pipeline_additive(test_session, USER, _rolled([ACK]), [])
    row_id = (await _only(test_session)).id
    await apps.record_role_correction(test_session, USER, row_id, "Backend Engineer")

    await apps.sync_gmail_pipeline_additive(
        test_session, USER, _rolled([ACK, REJECTION]), []
    )

    row = await _only(test_session)
    assert row.id == row_id
    assert row.status == ApplicationStatus.REJECTED
    assert row.source == apps.SOURCE_GMAIL_AUTO  # still the sync's row
    assert row.position == "Backend Engineer"  # except for this


async def test_a_typed_role_leaves_the_rows_identity_alone(test_session):
    """``role_token`` is the MAIL's identity key, and stays the mail's.

    ``_pick_application`` matches a cluster's ``role_token`` — normalised from
    what a message says — against the stored one, and treats a row with both
    ``req_id`` and ``role_token`` NULL as adoptable in place (rule 3). Stamping
    a user's phrasing into it would therefore change which future clusters
    resolve onto this row: a cluster that would have adopted it now finds no
    unidentified row and mints a second card instead. And since the Gmail path
    extracts no role for these rows, a token in the user's words could never be
    matched by anything anyway. All risk, no benefit — so it is left NULL and
    the sync stays free to identify the row from real mail evidence later.
    """

    await apps.sync_gmail_pipeline_additive(test_session, USER, _rolled([ACK]), [])
    row = await _only(test_session)
    assert row.role_token is None and row.req_id is None

    await apps.record_role_correction(test_session, USER, row.id, "Backend Engineer")

    row = await _only(test_session)
    assert row.role_token is None
    assert row.req_id is None

    # And the sync may still stamp the identity it does learn from mail.
    await apps.sync_gmail_pipeline_additive(
        test_session, USER, _rolled([ACK, ROLED]), []
    )
    row = await _only(test_session)
    assert row.role_token is not None
    assert row.position == "Backend Engineer"


async def test_a_typed_role_survives_a_full_rebuild(test_session):
    """The other entry point — and the one with a button on it.

    ``purge_and_rebuild_gmail_pipeline`` re-reads the whole history and is what
    "Rebuild" runs. It reaches the role through the same
    :func:`upsert_applications_for_user` the delta sync does, so the guard
    covers it — but that is an implementation fact today, and the destructive
    -feeling action silently discarding the one field the user had to type in by
    hand is exactly the regression worth catching if it ever stops being true.

    The rebuild may still DISMISS this row if a later scan stops concluding an
    application from its mail: the design deliberately leaves ``source`` as
    ``gmail``, so the row stays purge-able. That is the same exposure a user-set
    deadline already carries — ``due_source`` does not flip ``source`` either —
    and the removal is recoverable, so it is precedent rather than a defect.
    """

    await apps.sync_gmail_pipeline_additive(test_session, USER, _rolled([ACK]), [])
    row_id = (await _only(test_session)).id
    await apps.record_role_correction(test_session, USER, row_id, "Backend Engineer")

    corpus = [ACK, ROLED]
    await apps.purge_and_rebuild_gmail_pipeline(
        test_session,
        USER,
        _rolled(corpus),
        p.collect_review_items(corpus),
        apps.ScanCoverage.from_items(corpus),
    )

    row = await _only(test_session)
    assert row.id == row_id
    assert row.position == "Backend Engineer"
    assert row.position_source == apps.ROLE_FROM_USER
    assert row.dismissed_at is None


# --- the split ------------------------------------------------------------------

# Amazon's confirmations DO name a role in the snippet, which is what makes them
# splittable at all — and what makes them the right fixture here: the split has
# a real title to re-derive, so a guard that did nothing would be invisible.
AMAZON_SENDER = "noreply@mail.amazon.jobs"
AMAZON_SUBJECT = "Thank you for Applying to Amazon!"
REQ_LIVE = "3177934"
REQ_DEAD = "3130865"
ROLE_LIVE = "Software Development Engineer - 2026 (US)"
ROLE_DEAD = "Software Development Engineer – Database 2026 (US)"


def _amazon_mail(message_id: str, *, role: str, req: str, minutes: int, application_id: int):
    from jobtracker.database.models import Email, EmailCategory, EmailSource

    return Email(
        user_id=USER,
        application_id=application_id,
        source_account=EmailSource.GMAIL,
        message_id=message_id,
        thread_id=None,
        subject=AMAZON_SUBJECT,
        sender_email=AMAZON_SENDER,
        body_snippet=(
            "Amazon.jobs Hi Ayush, Thanks for applying to Amazon! We've received your "
            f"application for the {role} (ID: {req}) position. What happens next?"
        ),
        received_at=BASE + datetime.timedelta(minutes=minutes),
        classified_as=EmailCategory.APPLIED,
        classification_confidence=0.9,
    )


@pytest.fixture
def split_session(test_session, monkeypatch: pytest.MonkeyPatch):
    """Run the split handler against the fixture session, not the app engine.

    The same fixture ``test_stage_write_policy.py`` uses for the same reason.
    """
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _session():
        yield test_session

    monkeypatch.setattr(apps, "get_session", _session)

    async def _no_account(_user_id):
        return None

    monkeypatch.setattr(apps, "_connected_account_email", _no_account)
    return test_session


async def test_a_split_never_rewrites_a_role_the_user_typed(split_session):
    """A split re-reads the mail — and the mail is what never had a role in it.

    ``split_application_cloud`` rewrites ``req_id``, ``role_token`` AND
    ``position`` from the retained cluster. The first two are the mail's own
    identity and are still re-derived; the title the human typed is not, exactly
    as a human-set STAGE already survives the same call.
    """

    row = Application(
        user_id=USER,
        company="Amazon",
        position="",
        status=ApplicationStatus.APPLIED,
        source=apps.SOURCE_GMAIL_AUTO,
    )
    split_session.add(row)
    await split_session.commit()
    await split_session.refresh(row)

    split_session.add(_amazon_mail("s1", role=ROLE_LIVE, req=REQ_LIVE, minutes=0, application_id=row.id))
    split_session.add(_amazon_mail("s2", role=ROLE_DEAD, req=REQ_DEAD, minutes=5, application_id=row.id))
    await split_session.commit()

    await apps.record_role_correction(split_session, USER, row.id, "The Job I Actually Applied For")

    result = await apps.split_application_cloud(row.id, user_id=USER)

    assert len(result) == 2
    retained = result[0]
    assert retained.id == row.id
    assert retained.position == "The Job I Actually Applied For"
    # The identity the split exists to recompute still IS recomputed.
    persisted = (
        await split_session.exec(select(Application).where(Application.id == row.id))
    ).first()
    assert persisted.req_id == REQ_LIVE
    assert persisted.role_token is not None
    # The sibling is the mail's entirely — it gets the title the mail states.
    assert result[1].position == ROLE_DEAD


# --- clearing ------------------------------------------------------------------


async def test_clearing_a_role_hands_the_field_back_to_the_sync(test_session):
    """Set and clear are one decision, as they are for a deadline.

    Clearing drops the provenance with the value: a source without a value is a
    claim about nothing, and leaving it set would freeze the field as empty
    forever.
    """

    await apps.sync_gmail_pipeline_additive(test_session, USER, _rolled([ACK]), [])
    row_id = (await _only(test_session)).id
    await apps.record_role_correction(test_session, USER, row_id, "Backend Engineer")

    cleared = await apps.record_role_correction(test_session, USER, row_id, None)
    assert cleared is not None
    assert cleared.position == ""
    assert cleared.position_source is None

    await apps.sync_gmail_pipeline_additive(
        test_session, USER, _rolled([ACK, ROLED]), []
    )
    assert (await _only(test_session)).position == "Data Scientist"


@pytest.mark.parametrize("blank", ["", "   ", "\t\n "])
async def test_a_blank_role_clears_rather_than_storing_whitespace(
    test_session, blank: str
):
    """#72 exists to stop invented data; a row that LOOKS filled is the same lie."""

    await apps.sync_gmail_pipeline_additive(test_session, USER, _rolled([ACK]), [])
    row_id = (await _only(test_session)).id
    await apps.record_role_correction(test_session, USER, row_id, "Backend Engineer")

    cleared = await apps.record_role_correction(test_session, USER, row_id, blank)
    assert cleared is not None
    assert cleared.position == ""
    assert cleared.position_source is None


async def test_a_typed_role_is_trimmed(test_session):
    await apps.sync_gmail_pipeline_additive(test_session, USER, _rolled([ACK]), [])
    row_id = (await _only(test_session)).id

    updated = await apps.record_role_correction(
        test_session, USER, row_id, "  Backend Engineer  "
    )
    assert updated is not None
    assert updated.position == "Backend Engineer"


# --- ownership -----------------------------------------------------------------


async def test_a_role_correction_is_scoped_to_its_owner(test_session):
    await apps.sync_gmail_pipeline_additive(test_session, USER, _rolled([ACK]), [])
    row_id = (await _only(test_session)).id

    assert (
        await apps.record_role_correction(test_session, OTHER, row_id, "Anything")
        is None
    )
    assert (await _only(test_session)).position == ""


# --- the HTTP surface ----------------------------------------------------------

JWT_SECRET = "role-fill-test-jwt-secret-at-least-32-bytes-long-hs256"
ENC_KEY = Fernet.generate_key().decode()
USER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _token_for(user_id: str) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {"sub": user_id, "aud": "authenticated", "iat": now, "exp": now + 300},
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture
async def cloud_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """The cloud app on an in-memory DB — the reload sequence used repo-wide."""

    import jobtracker.auth.supabase_jwt as auth_module
    import jobtracker.config as config_module
    import jobtracker.database.connection as connection_module

    # Every settings instance the request path holds, de-duplicated by object
    # identity -- not ``importlib.reload(jobtracker.config)``, which minted a
    # new one and left the verifier holding the old (#582).
    holders = {
        id(module.settings): module.settings
        for module in (config_module, auth_module, connection_module)
    }

    for instance in holders.values():
        monkeypatch.setattr(instance, "deployment", "cloud")
        monkeypatch.setattr(instance, "environment", "test")
        monkeypatch.setattr(instance, "supabase_jwt_secret", JWT_SECRET)
        monkeypatch.setattr(instance, "secret_encryption_key", ENC_KEY)

    connection_module._engine = None

    from jobtracker.database import init_db

    await init_db()

    import jobtracker.main_cloud as main_cloud_module

    yield main_cloud_module.app

    if connection_module._engine is not None:
        await connection_module._engine.dispose()
    connection_module._engine = None


@pytest.fixture
async def client(cloud_app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=cloud_app)
    async with AsyncClient(
        transport=transport, base_url="http://cloud-test", follow_redirects=False
    ) as c:
        yield c


async def _make_row(client: AsyncClient, user: str) -> int:
    resp = await client.post(
        "/applications",
        json={"company": "Supabase", "position": ""},
        headers={"Authorization": f"Bearer {_token_for(user)}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_put_role_sets_it(client: AsyncClient) -> None:
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    app_id = await _make_row(client, USER_A)

    resp = await client.put(
        f"/applications/{app_id}/role",
        json={"role": "Backend Engineer"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["position"] == "Backend Engineer"

    listed = (await client.get("/applications", headers=headers)).json()[
        "applications"
    ][0]
    assert listed["position"] == "Backend Engineer"


async def test_put_role_null_clears_it(client: AsyncClient) -> None:
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    app_id = await _make_row(client, USER_A)

    await client.put(
        f"/applications/{app_id}/role", json={"role": "Backend Engineer"}, headers=headers
    )
    resp = await client.put(
        f"/applications/{app_id}/role", json={"role": None}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["position"] == ""


async def test_put_role_requires_a_bearer_token(client: AsyncClient) -> None:
    app_id = await _make_row(client, USER_A)
    resp = await client.put(f"/applications/{app_id}/role", json={"role": "X"})
    assert resp.status_code == 401, resp.text


async def test_put_role_cannot_reach_another_users_row(client: AsyncClient) -> None:
    app_id = await _make_row(client, USER_A)

    resp = await client.put(
        f"/applications/{app_id}/role",
        json={"role": "Backend Engineer"},
        headers={"Authorization": f"Bearer {_token_for(USER_B)}"},
    )
    assert resp.status_code == 404, resp.text

    listed = (
        await client.get(
            "/applications", headers={"Authorization": f"Bearer {_token_for(USER_A)}"}
        )
    ).json()["applications"][0]
    assert listed["position"] == ""


async def test_put_role_rejects_an_over_long_title(client: AsyncClient) -> None:
    """``position`` is NOT NULL TEXT with no length ceiling in the schema, so the
    ceiling has to be here or the column is an unbounded write primitive."""

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    app_id = await _make_row(client, USER_A)

    resp = await client.put(
        f"/applications/{app_id}/role",
        json={"role": "x" * 201},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
