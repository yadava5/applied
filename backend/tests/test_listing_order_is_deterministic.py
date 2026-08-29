"""The applications listing must impose a total order, not a partial one.

Why this file exists
--------------------

``GET /applications`` orders by ``created_at DESC, id DESC``. The ``id`` term is
not decoration. A first Gmail rebuild writes hundreds of rows inside the same
second, so ordering on ``created_at`` alone leaves them tied *en masse*, and
Postgres is explicitly free to return tied rows in a different order per
request. Paging through a non-deterministic order silently drops some rows and
repeats others across pages — which the JSON export now walks page by page, and
which the board's "showing the newest 200 of 250" claim depends on being true.

The tiebreak shipped with no executing test. Writing one has a trap worth
stating, because it is the reason the obvious test would be worthless:

**SQLite cannot reproduce this bug.** With equal ``created_at`` values SQLite
returns rows in rowid order, which is stable, so a SQLite test that walks the
pages passes whether or not the tiebreak is there. Deleting ``id.desc()`` would
leave it green. That is a check that cannot fail, and this codebase has shipped
several of those.

So the coverage is split deliberately:

* :func:`test_paging_returns_every_row_exactly_once` executes the real endpoint
  and proves the paging arithmetic itself — offsets, limits, the last partial
  page. This one *can* fail, on offset/limit mistakes.
* :func:`test_the_listing_asks_the_database_for_a_total_order` inspects the SQL
  actually emitted to the driver and asserts the tiebreak is in it. This is the
  one that catches the tiebreak being removed, and it works on SQLite because
  it asserts about the *statement*, not about the row order the statement
  happens to produce here.

Neither is a substitute for the other, and neither is a grep: both run the
endpoint.

The split is not a guess — it was measured. Deleting ``Application.id.desc()``
from the listing and re-running this file gives **1 failed, 2 passed**: the
SQL-shape test fails with ``ORDER BY applications.created_at DESC`` and both
paging tests stay green. That is the whole argument for the third test in one
line of output.
"""

from __future__ import annotations

import re
import time
import uuid
from datetime import datetime
from typing import Any, AsyncIterator

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event


JWT_SECRET = "listing-order-test-jwt-secret-at-least-32-bytes-long-hs256"
USER = "cccccccc-cccc-cccc-cccc-cccccccccccc"

# Every row is written with the SAME timestamp on purpose: that is the state a
# rebuild leaves behind, and the only state in which the tiebreak matters.
TIED_AT = datetime(2026, 8, 11, 12, 0, 0)
ROW_COUNT = 25
PAGE_SIZE = 10


def _token_for(user_id: str) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {"sub": user_id, "aud": "authenticated", "iat": now, "exp": now + 300},
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture
async def cloud_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """The cloud app over the in-memory SQLite test DB (see test_user_id_scoping)."""

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


async def _seed_tied_rows() -> list[int]:
    """Insert ROW_COUNT applications that all share one ``created_at``."""

    from jobtracker.database.connection import get_session
    from jobtracker.database.models import Application, ApplicationStatus

    ids: list[int] = []
    async with get_session() as session:
        for i in range(ROW_COUNT):
            app = Application(
                user_id=uuid.UUID(USER),
                company=f"Company {i:02d}",
                position=f"Engineer {i:02d}",
                status=ApplicationStatus.APPLIED,
                created_at=TIED_AT,
            )
            session.add(app)
        await session.commit()

        from sqlmodel import select

        rows = (
            await session.exec(
                select(Application).where(Application.user_id == uuid.UUID(USER))
            )
        ).all()
        ids = [r.id for r in rows]
    return ids


async def test_paging_returns_every_row_exactly_once(cloud_app):
    """Walk every page and rebuild the set — no row dropped, none repeated.

    This is what the export does. It is also the failure the tiebreak prevents
    on Postgres, though here it proves the offset/limit arithmetic rather than
    the ordering (see the module docstring for why SQLite cannot show the
    ordering half).
    """

    seeded = await _seed_tied_rows()
    assert len(seeded) == ROW_COUNT

    headers = {"Authorization": f"Bearer {_token_for(USER)}"}
    collected: list[int] = []

    async with AsyncClient(
        transport=ASGITransport(app=cloud_app), base_url="http://test"
    ) as client:
        page = 1
        while True:
            res = await client.get(
                "/applications",
                params={"page": page, "page_size": PAGE_SIZE},
                headers=headers,
            )
            assert res.status_code == 200, res.text
            body = res.json()
            assert body["total"] == ROW_COUNT
            got = [a["id"] for a in body["applications"]]
            if not got:
                break
            collected.extend(got)
            if len(collected) >= body["total"]:
                break
            page += 1

    assert len(collected) == ROW_COUNT, "paging dropped or duplicated rows"
    assert sorted(collected) == sorted(seeded)
    assert len(set(collected)) == ROW_COUNT, "a row appeared on two pages"


async def test_the_same_request_twice_gives_the_same_page(cloud_app):
    """A second identical read must not reshuffle a tied page."""

    await _seed_tied_rows()
    headers = {"Authorization": f"Bearer {_token_for(USER)}"}

    async with AsyncClient(
        transport=ASGITransport(app=cloud_app), base_url="http://test"
    ) as client:
        first = await client.get(
            "/applications", params={"page": 1, "page_size": PAGE_SIZE}, headers=headers
        )
        second = await client.get(
            "/applications", params={"page": 1, "page_size": PAGE_SIZE}, headers=headers
        )

    assert first.status_code == second.status_code == 200
    assert [a["id"] for a in first.json()["applications"]] == [
        a["id"] for a in second.json()["applications"]
    ]


async def test_the_listing_asks_the_database_for_a_total_order(cloud_app):
    """The emitted SQL must order by ``created_at`` AND ``id``.

    The one assertion in this file that catches the tiebreak being deleted.
    It reads the statement handed to the driver, so it is checking what
    Postgres would receive in production rather than what SQLite chooses to do
    with a partial order in the test.
    """

    await _seed_tied_rows()

    import jobtracker.database.connection as connection_module

    engine = connection_module._engine
    assert engine is not None, "the fixture should have built an engine"

    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _capture(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        statements.append(statement)

    try:
        headers = {"Authorization": f"Bearer {_token_for(USER)}"}
        async with AsyncClient(
            transport=ASGITransport(app=cloud_app), base_url="http://test"
        ) as client:
            res = await client.get(
                "/applications",
                params={"page": 1, "page_size": PAGE_SIZE},
                headers=headers,
            )
        assert res.status_code == 200, res.text
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _capture)

    ordered = [
        s
        for s in statements
        if "FROM applications" in s and "ORDER BY" in s.upper()
    ]
    assert ordered, f"no ordered SELECT against applications was issued: {statements}"

    order_clause = re.split(r"ORDER BY", ordered[-1], flags=re.IGNORECASE)[1]
    lowered = order_clause.lower()

    assert "created_at" in lowered, f"created_at is not in the ORDER BY: {order_clause}"
    # The tiebreak. Without it, tied `created_at` values leave the order
    # undefined and Postgres may vary it between two requests, which is how
    # paging drops and repeats rows.
    assert re.search(r"\bid\b", lowered), (
        "the listing no longer breaks ties on id — tied created_at rows are "
        f"free to reorder per request on Postgres. ORDER BY was: {order_clause}"
    )
    assert lowered.index("created_at") < lowered.rindex("id"), (
        "id must come after created_at, otherwise it is the primary sort and "
        f"the newest-first contract is broken. ORDER BY was: {order_clause}"
    )
