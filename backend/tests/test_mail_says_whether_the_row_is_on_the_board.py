"""``GET /applications/mail`` must distinguish a LIVE row from a removed one.

Why this file exists
--------------------

Dismissal is not a delete. A removed application keeps its id and KEEPS ITS
EMAILS, on purpose, so the removal stays restorable. That makes
``application_id is not None`` mean "a row was built at some point" and NOT
"a row is on the board", and the web app read it as the second: every message
whose application had been dismissed rendered the chip "on your board" (#489).

Found in production on 2026-08-23, on the owner's own account. The single
needs-review message pointed at application 115 — dismissed by a rebuild the
previous day — and the Inbox stated it was on a board that did not contain it.

What this file pins
-------------------

``on_board`` is a SEPARATE field from ``application_id``, and both are
reported. The id must survive the dismissal because a restore surface needs
it; blanking the id to fix a label would break recovery to fix a caption.

The control that makes these assertions worth anything is the LIVE row seeded
alongside the dismissed one. A test with only dismissed rows passes just as
happily against ``on_board = False`` hardcoded, and a test with only live rows
passes against the original bug. Both cases have to be in one response.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

JWT_SECRET = "on-board-test-jwt-secret-at-least-32-bytes-long-for-hs256"
OWNER = "cccccccc-cccc-cccc-cccc-cccccccccccc"

LIVE_COMPANY = "Northwind Robotics"
REMOVED_COMPANY = "Crusoe Energy"
RECEIVED_AT = datetime(2026, 8, 13, 5, 16, 49)
DISMISSED_AT = datetime(2026, 8, 22, 5, 2, 29)

MSG_ON_LIVE = "m-live"
MSG_ON_REMOVED = "m-removed"
MSG_UNFILED = "m-unfiled"


def _token_for(user_id: str) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {"sub": user_id, "aud": "authenticated", "iat": now, "exp": now + 300},
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture
async def cloud_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
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


async def _seed() -> dict[str, int]:
    """One live application, one dismissed, and three messages across them."""

    from jobtracker.database.connection import get_session
    from jobtracker.database.models import (
        Application,
        ApplicationStatus,
        Email,
        EmailCategory,
        EmailSource,
    )

    ids: dict[str, int] = {}
    async with get_session() as session:
        live = Application(
            user_id=uuid.UUID(OWNER),
            company=LIVE_COMPANY,
            position="Software Engineer",
            status=ApplicationStatus.APPLIED,
        )
        session.add(live)
        await session.flush()
        ids[LIVE_COMPANY] = live.id

        # Removed by a rebuild, exactly as production does it: off the board,
        # still holding its mail.
        removed = Application(
            user_id=uuid.UUID(OWNER),
            company=REMOVED_COMPANY,
            position="Software Engineer",
            status=ApplicationStatus.APPLIED,
            dismissed_at=DISMISSED_AT,
            dismissed_reason="resync",
        )
        session.add(removed)
        await session.flush()
        ids[REMOVED_COMPANY] = removed.id

        for message_id, application_id, category in (
            (MSG_ON_LIVE, live.id, EmailCategory.APPLIED),
            (MSG_ON_REMOVED, removed.id, EmailCategory.NEEDS_REVIEW),
            (MSG_UNFILED, None, EmailCategory.NEEDS_REVIEW),
        ):
            session.add(
                Email(
                    user_id=uuid.UUID(OWNER),
                    source_account=EmailSource.GMAIL,
                    message_id=message_id,
                    thread_id=f"thread-{message_id}",
                    subject="Thank you for your application!",
                    sender_name="Careers",
                    sender_email="careers@example.com",
                    received_at=RECEIVED_AT,
                    body_snippet=f"snippet for {message_id}",
                    classified_as=category,
                    classification_confidence=0.8,
                    classification_method="rules",
                    application_id=application_id,
                )
            )
        await session.commit()
    return ids


async def _messages(cloud_app) -> dict[str, Any]:
    async with AsyncClient(
        transport=ASGITransport(app=cloud_app), base_url="http://test"
    ) as client:
        res = await client.get(
            "/applications/mail",
            headers={"Authorization": f"Bearer {_token_for(OWNER)}"},
        )
    assert res.status_code == 200, res.text
    return {m["message_id"]: m for m in res.json()["messages"]}


async def test_the_fixture_holds_both_a_live_and_a_removed_row(cloud_app):
    """Pin the fixture before asserting over it.

    Both cases must exist in ONE response or the assertions below are
    vacuous — see the module docstring.
    """

    ids = await _seed()
    assert set(ids) == {LIVE_COMPANY, REMOVED_COMPANY}
    assert ids[LIVE_COMPANY] != ids[REMOVED_COMPANY]

    messages = await _messages(cloud_app)
    assert set(messages) == {MSG_ON_LIVE, MSG_ON_REMOVED, MSG_UNFILED}

    # The discriminating property: one linked row is live, the other is not.
    assert messages[MSG_ON_LIVE]["application_id"] == ids[LIVE_COMPANY]
    assert messages[MSG_ON_REMOVED]["application_id"] == ids[REMOVED_COMPANY]
    assert messages[MSG_UNFILED]["application_id"] is None


async def test_a_message_on_a_live_row_is_on_the_board(cloud_app):
    await _seed()
    messages = await _messages(cloud_app)
    assert messages[MSG_ON_LIVE]["on_board"] is True


async def test_a_message_on_a_dismissed_row_is_not_on_the_board(cloud_app):
    """The defect. `application_id` is set and `on_board` must still be False."""

    await _seed()
    messages = await _messages(cloud_app)
    row = messages[MSG_ON_REMOVED]

    assert row["on_board"] is False
    # The id SURVIVES: it is what an undo surface reads. Reporting the removal
    # by blanking the link would break restoration to fix a caption.
    assert row["application_id"] is not None


async def test_an_unfiled_message_is_not_on_the_board(cloud_app):
    """No link at all — the third state, and neither of the other two."""

    await _seed()
    messages = await _messages(cloud_app)
    assert messages[MSG_UNFILED]["on_board"] is False
    assert messages[MSG_UNFILED]["application_id"] is None


async def test_on_board_is_not_just_application_id_restated(cloud_app):
    """The two fields must DISAGREE somewhere in this response.

    This is the assertion that fails against the original code. If `on_board`
    is ever derived from `application_id is not None`, every row satisfies
    `on_board == (application_id is not None)` and the field carries no
    information the client did not already have.
    """

    await _seed()
    messages = await _messages(cloud_app)

    disagreements = [
        message_id
        for message_id, row in messages.items()
        if row["on_board"] != (row["application_id"] is not None)
    ]
    assert disagreements == [MSG_ON_REMOVED], (
        "on_board must differ from 'has a link' for exactly the dismissed row; "
        f"got {disagreements}"
    )


async def test_the_employer_still_resolves_for_a_removed_row(cloud_app):
    """Removal must not cost the reader the company name.

    `company` and `on_board` come from the same query. A fix that filtered
    dismissed rows OUT of that lookup would set `on_board` correctly and
    silently blank the employer, which is a worse listing than the bug.
    """

    await _seed()
    messages = await _messages(cloud_app)
    assert messages[MSG_ON_REMOVED]["company"] == REMOVED_COMPANY
    assert messages[MSG_ON_LIVE]["company"] == LIVE_COMPANY
