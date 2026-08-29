"""One application's mail is a BOUNDED read, on both paths (issue #293).

``GET /applications/{id}`` and ``POST /applications/{id}/split`` both asked the
database for *every* email linked to an application, with no ``LIMIT``. Bounded
by one application's own mail, so never a tenant leak — but an unbounded read is
a latent outage rather than a slow page, and nothing in the product stops a
rebuild from linking a thousand messages to one employer.

WHY A CAP IS NOT ENOUGH ON ITS OWN, which is what these tests are really about
-----------------------------------------------------------------------------
Truncating this read is not "shows fewer messages". ``cluster_stored_mail``
sorts clusters by their EARLIEST message and hands the application id to cluster
0; both reads are newest-first; so a cap silently drops exactly the mail that
decides which cluster keeps the row. A bare ``.limit()`` would have converted an
unbounded read into a *wrong* answer — the same defect ``_warn_if_capped``
exists to shout about on the company lookup.

So the cap comes with a refusal:

* the detail read returns the messages it got and NO split candidates;
* the split — which commits, and re-points real mail — answers 422 and writes
  nothing at all.

THE CONSTANT IS PATCHED DOWN, NOT SEEDED UP
--------------------------------------------
``_APPLICATION_MAIL_CAP`` is 1000. Seeding 1,001 rows per test to reach it would
buy nothing but runtime: both the ``LIMIT`` and the truncation check read the
module global at call time, so a small cap exercises the identical code path.
Every test that patches it also has a below-the-cap twin, so "the cap binds"
cannot pass because the cap is simply always on.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

JWT_SECRET = "mail-cap-test-jwt-secret-at-least-32-bytes-long-hs256"
OWNER = "dddddddd-dddd-dddd-dddd-dddddddddddd"

BASE = datetime(2026, 8, 11, 2, 0)

AMAZON_SENDER = "noreply@mail.amazon.jobs"
AMAZON_SUBJECT = "Thank you for Applying to Amazon!"

# Four real Amazon requisitions, oldest first. Verbatim from the corpus in
# tests/test_application_identity.py — the clustering depends on what those
# templates actually contain, and a snippet written from memory would prove
# nothing about them.
REQUISITIONS = (
    ("Software Development Engineer - 2026 (US)", "3177934"),
    ("Software Development Engineer – Embedded Systems 2026 (US)", "3183020"),
    ("Software Development Engineer, AWS Data Services - 2026 (US)", "10414316"),
    ("Software Development Engineer – Database 2026 (US)", "3130865"),
)


def _token_for(user_id: str) -> str:
    import time

    now = int(time.time())
    return pyjwt.encode(
        {"sub": user_id, "aud": "authenticated", "iat": now, "exp": now + 300},
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture
async def cloud_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """The cloud app over the in-memory SQLite test DB."""

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

    connection_module._engine = None

    from jobtracker.database import init_db

    await init_db()

    import jobtracker.main_cloud as main_cloud_module

    yield main_cloud_module.app

    if connection_module._engine is not None:
        await connection_module._engine.dispose()
    connection_module._engine = None


async def _seed() -> int:
    """One Amazon row holding four requisitions' worth of mail. Returns its id."""

    from jobtracker.database.connection import get_session
    from jobtracker.database.models import (
        Application,
        ApplicationStatus,
        Email,
        EmailCategory,
        EmailSource,
    )

    async with get_session() as session:
        row = Application(
            user_id=uuid.UUID(OWNER),
            company="Amazon",
            position="Software Development Engineer",
            status=ApplicationStatus.APPLIED,
        )
        session.add(row)
        await session.flush()
        application_id = row.id

        for index, (role, req) in enumerate(REQUISITIONS):
            session.add(
                Email(
                    user_id=uuid.UUID(OWNER),
                    source_account=EmailSource.GMAIL,
                    message_id=f"a{index + 1}",
                    thread_id="19fee99ce7d5feb8",
                    subject=AMAZON_SUBJECT,
                    sender_name="Amazon.jobs",
                    sender_email=AMAZON_SENDER,
                    received_at=BASE + timedelta(minutes=index),
                    body_snippet=(
                        "Amazon.jobs Hi Ayush, Thanks for applying to Amazon! "
                        "We&#39;ve received your application for the "
                        f"{role} (ID: {req}) position. What happens next?"
                    ),
                    classified_as=EmailCategory.APPLIED,
                    classification_confidence=0.95,
                    classification_method="rules",
                    application_id=application_id,
                )
            )
        await session.commit()

    return application_id


def _cap(monkeypatch: pytest.MonkeyPatch, value: int) -> None:
    import jobtracker.cloud.applications as cloud_apps_module

    monkeypatch.setattr(cloud_apps_module, "_APPLICATION_MAIL_CAP", value)


async def _detail(cloud_app, application_id: int) -> Any:
    async with AsyncClient(
        transport=ASGITransport(app=cloud_app), base_url="http://cap-test"
    ) as client:
        return await client.get(
            f"/applications/{application_id}",
            headers={"Authorization": f"Bearer {_token_for(OWNER)}"},
        )


async def _split(cloud_app, application_id: int) -> Any:
    async with AsyncClient(
        transport=ASGITransport(app=cloud_app), base_url="http://cap-test"
    ) as client:
        return await client.post(
            f"/applications/{application_id}/split",
            headers={"Authorization": f"Bearer {_token_for(OWNER)}"},
        )


async def _linked_message_ids() -> dict[int, list[str]]:
    """Which messages are filed under which application, right now."""

    from sqlmodel import select

    from jobtracker.database.connection import get_session
    from jobtracker.database.models import Email

    async with get_session() as session:
        rows = (
            await session.exec(
                select(Email).where(Email.user_id == uuid.UUID(OWNER))
            )
        ).all()
    out: dict[int, list[str]] = {}
    for email in rows:
        out.setdefault(email.application_id, []).append(email.message_id)
    for key in out:
        out[key].sort()
    return out


# =============================================================================
# Below the cap — the behaviour that must NOT change
# =============================================================================


async def test_under_the_cap_the_detail_view_still_proposes_the_split(cloud_app):
    """The non-vacuity control for every assertion below.

    Four requisitions on one row is exactly the state the split exists for. If
    this did not return four candidates, "no candidates when truncated" would be
    true for the boring reason and prove nothing about the cap.
    """

    application_id = await _seed()

    response = await _detail(cloud_app, application_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["messages"]) == 4
    assert len(body["split_candidates"]) == 4, body["split_candidates"]
    assert [c["retains_row"] for c in body["split_candidates"]] == [
        True,
        False,
        False,
        False,
    ]


async def test_under_the_cap_the_split_still_splits(cloud_app):
    """Same control for the write path."""

    application_id = await _seed()

    response = await _split(cloud_app, application_id)

    assert response.status_code == 200, response.text
    assert len(response.json()) == 4
    assert len(await _linked_message_ids()) == 4, "the mail was not re-pointed"


# =============================================================================
# At the cap — bounded, loud, and refusing to guess
# =============================================================================


async def test_the_detail_read_is_bounded_and_withholds_the_split(
    cloud_app, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """The read stops at the cap, says so, and proposes nothing.

    Three assertions, and the third is the one that matters: the response still
    renders the messages it has (the user is not shown an error for a page that
    works), but ``split_candidates`` is empty, because the oldest mail — the mail
    that decides which cluster keeps the row — was not read.
    """

    application_id = await _seed()
    _cap(monkeypatch, 2)

    with caplog.at_level(logging.WARNING, logger="jobtracker.cloud.applications"):
        response = await _detail(cloud_app, application_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["messages"]) == 2, "the read was not bounded by the cap"
    assert body["split_candidates"] == [], (
        "a split was proposed from a truncated read; acting on it would file "
        "real mail under the wrong application"
    )
    assert any(
        "hit its 2-message cap" in record.message for record in caplog.records
    ), f"the cap bound in silence: {[r.message for r in caplog.records]}"


async def test_the_split_refuses_on_a_truncated_read_and_writes_nothing(
    cloud_app, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """422, and the database is byte-identical afterwards.

    This handler COMMITS. A truncated read here does not show fewer messages, it
    re-points real mail onto a row chosen from a subset — and there is no undo.
    The "wrote nothing" assertion is the point; the status code alone would pass
    even if the write had already happened before the refusal.

    422 rather than the 409 the handler uses for "nothing to split": that answer
    is benign and expected and the UI renders it quietly, and this is not that.
    """

    application_id = await _seed()
    before = await _linked_message_ids()
    assert before == {application_id: ["a1", "a2", "a3", "a4"]}, before

    _cap(monkeypatch, 2)

    with caplog.at_level(logging.WARNING, logger="jobtracker.cloud.applications"):
        response = await _split(cloud_app, application_id)

    assert response.status_code == 422, response.text
    assert "read safely" in response.json()["detail"]
    assert await _linked_message_ids() == before, (
        "the refused split still moved mail between applications"
    )
    assert any(
        "hit its 2-message cap" in record.message for record in caplog.records
    ), f"the cap bound in silence: {[r.message for r in caplog.records]}"


async def test_a_cap_that_exactly_equals_the_row_count_is_treated_as_truncation(
    cloud_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The off-by-one that would make the whole guard useless.

    A read that returned exactly ``cap`` rows cannot tell "that was all of them"
    from "there is more". ``_application_mail_truncated`` therefore triggers on
    ``>=``, not ``>`` — the same rule ``_warn_if_capped`` uses. With ``>`` this
    test goes green on the detail view and the split would proceed on a set it
    has no reason to believe is complete.
    """

    application_id = await _seed()
    _cap(monkeypatch, 4)  # exactly the number of rows seeded

    response = await _detail(cloud_app, application_id)

    assert response.status_code == 200, response.text
    assert len(response.json()["messages"]) == 4
    assert response.json()["split_candidates"] == []
    assert (await _split(cloud_app, application_id)).status_code == 422


def test_the_shipped_cap_is_far_above_production(cloud_app) -> None:
    """The constant is a rail, not a business rule — pin that it stays one.

    Production holds 52 stored emails in total. A cap that drifted down towards
    a real mailbox's size would start withholding splits on ordinary rows, which
    is a product regression wearing the costume of a safety limit.
    """

    import jobtracker.cloud.applications as cloud_apps_module

    assert cloud_apps_module._APPLICATION_MAIL_CAP >= 500
