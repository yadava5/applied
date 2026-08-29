"""End-to-end test for per-user row scoping on the cloud app (issue #20, C3).

Two distinct Supabase users each insert their own applications via the
cloud ``/applications`` endpoint. Each user's ``GET /applications`` must
return only their own rows. This is the contract C3 exists to enforce;
every subsequent cloud issue (C5, C7, C11+) depends on it.

We stand up the cloud FastAPI app with the in-memory SQLite test DB,
patch ``settings.supabase_jwt_secret`` so HS256 tokens validate, and
issue signed JWTs with two different ``sub`` claims. RLS is a
Postgres-only defence-in-depth layer (SQLite tests exercise only the
application-level ``user_id`` filter in the cloud router), but that is
sufficient to prove the correctness of the scoping logic — RLS is
additive security, not the primary check.
"""

from __future__ import annotations

import importlib
import time
import uuid
from datetime import datetime
from typing import Any, AsyncIterator

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient


# 32+ bytes of entropy to satisfy PyJWT's HMAC length warning; value
# is irrelevant as long as it's consistent within the test module.
JWT_SECRET = "scoping-test-jwt-secret-at-least-32-bytes-long-for-hs256"
USER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _token_for(user_id: str, secret: str = JWT_SECRET) -> str:
    """Build a Supabase-shaped HS256 JWT for ``user_id``."""

    now = int(time.time())
    return pyjwt.encode(
        {
            "sub": user_id,
            "aud": "authenticated",
            "iat": now,
            "exp": now + 300,
        },
        secret,
        algorithm="HS256",
    )


@pytest.fixture
async def cloud_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """Build a cloud FastAPI app with a JWT secret and initialized DB.

    We drive everything through env vars (not direct attribute patches)
    so a single ``importlib.reload(config)`` picks up all three of:

    - ``JOBTRACKER_DEPLOYMENT=cloud`` — selects the cloud code paths.
    - ``JOBTRACKER_ENVIRONMENT=test`` — pins the in-memory SQLite URL.
    - ``JOBTRACKER_SUPABASE_JWT_SECRET=<secret>`` — enables the auth
      dependency for all three of our test JWT signatures.

    After the env vars are in place we reload ``jobtracker.config``,
    ``jobtracker.database.connection`` (so the engine is rebuilt
    against the fresh in-memory URL, not the stale on-disk path
    cached from an earlier import), and ``jobtracker.main_cloud`` (so
    every route uses the reloaded settings).

    Teardown undoes every env var and reloads config once more so
    later tests in the same session see an unmodified settings
    singleton.
    """

    monkeypatch.setenv("JOBTRACKER_DEPLOYMENT", "cloud")
    monkeypatch.setenv("JOBTRACKER_ENVIRONMENT", "test")
    monkeypatch.setenv("JOBTRACKER_SUPABASE_JWT_SECRET", JWT_SECRET)

    import jobtracker.config as config_module
    import jobtracker.database.connection as connection_module

    importlib.reload(config_module)
    # Reset the cached engine so the in-memory DB URL takes effect.
    connection_module._engine = None

    # Reload auth + cloud modules so their ``from jobtracker.config
    # import settings`` bindings pick up the reloaded module.
    import jobtracker.auth.supabase_jwt as auth_module

    importlib.reload(auth_module)

    import jobtracker.cloud.applications as cloud_apps_module

    importlib.reload(cloud_apps_module)

    import jobtracker.main_cloud as main_cloud_module

    importlib.reload(main_cloud_module)

    from jobtracker.database import init_db

    await init_db()

    yield main_cloud_module.app

    # Reset engine so the next test's on-disk URL isn't still bound to
    # the in-memory one.
    await connection_module._engine.dispose() if connection_module._engine else None
    connection_module._engine = None

    monkeypatch.undo()
    importlib.reload(config_module)


@pytest.fixture
async def client(cloud_app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=cloud_app)
    async with AsyncClient(transport=transport, base_url="http://cloud-test") as c:
        yield c


async def test_auth_me_echoes_user_uuid(client: AsyncClient) -> None:
    """Smoke test: ``/auth/me`` returns the ``sub`` claim verbatim."""

    resp = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {_token_for(USER_A)}"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user_id"] == USER_A
    assert body["authenticated"] is True


async def test_missing_jwt_rejected(client: AsyncClient) -> None:
    """Applications endpoint must 401 without a bearer token."""

    resp = await client.get("/applications")
    assert resp.status_code == 401


async def test_users_see_only_their_own_applications(client: AsyncClient) -> None:
    """The core C3 guarantee.

    User A creates two applications; user B creates one. Each user's
    GET /applications must return only their own rows and the
    ``user_id`` on every returned row must match the requester's JWT
    ``sub`` claim.
    """

    headers_a = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    headers_b = {"Authorization": f"Bearer {_token_for(USER_B)}"}

    # User A creates two applications.
    for payload in (
        {"company": "Acme", "position": "SWE"},
        {"company": "Initech", "position": "Backend"},
    ):
        resp = await client.post("/applications", json=payload, headers=headers_a)
        assert resp.status_code == 201, resp.text
        assert resp.json()["user_id"] == USER_A

    # User B creates one.
    resp = await client.post(
        "/applications",
        json={"company": "Hooli", "position": "Infra"},
        headers=headers_b,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["user_id"] == USER_B

    # User A sees only A's rows.
    resp_a = await client.get("/applications", headers=headers_a)
    assert resp_a.status_code == 200
    payload_a = resp_a.json()
    assert payload_a["total"] == 2
    assert {r["company"] for r in payload_a["applications"]} == {"Acme", "Initech"}
    assert all(r["user_id"] == USER_A for r in payload_a["applications"])

    # User B sees only B's row.
    resp_b = await client.get("/applications", headers=headers_b)
    assert resp_b.status_code == 200
    payload_b = resp_b.json()
    assert payload_b["total"] == 1
    assert payload_b["applications"][0]["company"] == "Hooli"
    assert payload_b["applications"][0]["user_id"] == USER_B


async def test_client_cannot_spoof_user_id_in_request_body(client: AsyncClient) -> None:
    """Sanity: even if a client sends a ``user_id`` in the JSON body,
    the cloud router ignores it and uses the JWT ``sub`` claim.

    ``CloudApplicationCreate`` doesn't declare a ``user_id`` field so
    Pydantic silently drops it; the handler then reads ``user_id`` from
    ``Depends(current_user)``. This test documents the invariant so a
    future refactor that adds the field by accident fails loudly.
    """

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    spoofed_user = str(uuid.uuid4())

    resp = await client.post(
        "/applications",
        json={
            "company": "Evil Corp",
            "position": "Attacker",
            "user_id": spoofed_user,
        },
        headers=headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["user_id"] == USER_A
    assert resp.json()["user_id"] != spoofed_user


# =============================================================================
# Summary endpoint (counts-only pipeline summary) — perf: O(1) transfer.
# =============================================================================


async def _create(client: AsyncClient, headers: dict, company: str, status: str) -> None:
    resp = await client.post(
        "/applications",
        json={"company": company, "position": "SWE", "status": status},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text


async def test_summary_requires_auth(client: AsyncClient) -> None:
    """The summary endpoint is behind the same router-level auth as the list."""

    resp = await client.get("/applications/summary")
    assert resp.status_code == 401


async def test_summary_counts_by_status(client: AsyncClient) -> None:
    """Summary returns per-status counts, a total, and a this-week count.

    Everything created here is created "now", so ``this_week`` equals
    ``total`` and every status is present in ``status_counts``.
    """

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    await _create(client, headers, "Acme", "applied")
    await _create(client, headers, "Initech", "applied")
    await _create(client, headers, "Hooli", "interviewing")
    await _create(client, headers, "Umbrella", "rejected")

    resp = await client.get("/applications/summary", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["total"] == 4
    assert body["this_week"] == 4
    assert body["status_counts"] == {"applied": 2, "interviewing": 1, "rejected": 1}


async def test_summary_scoped_per_user(client: AsyncClient) -> None:
    """One user's summary never leaks another user's counts."""

    headers_a = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    headers_b = {"Authorization": f"Bearer {_token_for(USER_B)}"}

    await _create(client, headers_a, "Acme", "applied")
    await _create(client, headers_a, "Initech", "offered")
    await _create(client, headers_b, "Hooli", "applied")

    resp_a = await client.get("/applications/summary", headers=headers_a)
    resp_b = await client.get("/applications/summary", headers=headers_b)

    assert resp_a.json()["total"] == 2
    assert resp_a.json()["status_counts"] == {"applied": 1, "offered": 1}
    assert resp_b.json()["total"] == 1
    assert resp_b.json()["status_counts"] == {"applied": 1}


async def test_summary_empty_is_zeroed(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A user with no applications gets an honest all-zero summary.

    WHOLE-BODY equality on purpose: this is the one assertion in the suite that
    notices a field being ADDED to the response as well as one going wrong.
    ``week_start`` (#518) is in it for that reason, and the clock is frozen so
    the expected value is a literal rather than a second derivation of the very
    function this endpoint uses — and so the test cannot flake by running
    across a real UTC midnight.
    """

    import jobtracker.cloud.applications as applications_module

    frozen = datetime(2026, 8, 31, 12, 0, 0)

    class _FrozenDatetime(datetime):
        @classmethod
        def utcnow(cls) -> datetime:  # type: ignore[override]
            return frozen

    monkeypatch.setattr(applications_module, "datetime", _FrozenDatetime)

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    resp = await client.get("/applications/summary", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "total": 0,
        "this_week": 0,
        "week_start": "2026-08-31",
        "status_counts": {},
        "needs_review": 0,
    }


async def test_summary_this_week_is_a_calendar_week_not_a_trailing_seven_days(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``this_week`` starts over on Monday (#519), through the real endpoint.

    ``test_this_week_is_a_calendar_week.py`` pins the boundary function against
    the table the web suite shares. This asserts the thing a user actually
    sees: the number the tile returns, out of the real query, over real rows.

    THE CLOCK IS FROZEN TO A MONDAY on purpose, and that is what makes the test
    discriminate rather than merely pass. Every fixture below is dated relative
    to Monday 2026-08-31:

        2026-08-31  Monday      — this week, the only row that counts
        2026-08-30  Sunday      — LAST week, and one day ago
        2026-08-25  Tuesday     — last week, and six days ago

    Both of the excluded rows are inside a trailing seven-day window, so the
    old derivation returned 3 for exactly this board. Written relative to the
    real ``today`` instead, the test would agree with the old code on Sundays
    and disagree the rest of the week — a gate whose verdict depends on the day
    it runs, which is the flake shape this repo has a scar from.
    """

    import jobtracker.cloud.applications as applications_module

    frozen = datetime(2026, 8, 31, 12, 0, 0)

    class _FrozenDatetime(datetime):
        @classmethod
        def utcnow(cls) -> datetime:  # type: ignore[override]
            return frozen

    monkeypatch.setattr(applications_module, "datetime", _FrozenDatetime)

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    for company, applied in (
        ("Monday Co", "2026-08-31"),
        ("Sunday Co", "2026-08-30"),
        ("Tuesday Co", "2026-08-25"),
    ):
        resp = await client.post(
            "/applications",
            json={
                "company": company,
                "position": "SWE",
                "status": "applied",
                "applied_date": applied,
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text

    body = (await client.get("/applications/summary", headers=headers)).json()

    assert body["total"] == 3
    assert body["this_week"] == 1, (
        "the week did not start over on Monday — a trailing seven-day window "
        f"would have counted all three of these rows, and returned {body['this_week']}"
    )


# =============================================================================
# List pagination + filtering — perf: bounded transfer, DB-side filtering.
# =============================================================================


async def test_list_pagination_bounds_the_page(client: AsyncClient) -> None:
    """``page``/``page_size`` bound the returned rows; ``total`` is the full count."""

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    for i in range(5):
        await _create(client, headers, f"Company{i}", "applied")

    page1 = await client.get("/applications?page=1&page_size=2", headers=headers)
    assert page1.status_code == 200, page1.text
    body1 = page1.json()
    assert body1["total"] == 5  # full count, not the page size
    assert len(body1["applications"]) == 2

    page3 = await client.get("/applications?page=3&page_size=2", headers=headers)
    body3 = page3.json()
    assert body3["total"] == 5
    assert len(body3["applications"]) == 1  # remainder

    # The three pages together cover every distinct application exactly once.
    page2 = await client.get("/applications?page=2&page_size=2", headers=headers)
    seen = {
        r["id"]
        for body in (body1, page2.json(), body3)
        for r in body["applications"]
    }
    assert len(seen) == 5


async def test_list_status_filter(client: AsyncClient) -> None:
    """``status`` filters server-side; ``total`` reflects the filtered count."""

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    await _create(client, headers, "Acme", "applied")
    await _create(client, headers, "Initech", "applied")
    await _create(client, headers, "Hooli", "rejected")

    resp = await client.get("/applications?status=applied", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert {r["company"] for r in body["applications"]} == {"Acme", "Initech"}
    assert all(r["status"] == "applied" for r in body["applications"])


async def test_list_search_matches_company_and_position(client: AsyncClient) -> None:
    """``search`` is a case-insensitive substring over company/position/notes."""

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    await _create(client, headers, "Acme Robotics", "applied")
    await _create(client, headers, "Globex", "applied")

    resp = await client.get("/applications?search=robot", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["applications"][0]["company"] == "Acme Robotics"


async def test_account_deletion_purges_only_caller(client: AsyncClient) -> None:
    """DELETE /account removes every row owned by the caller and nothing else.

    Regression for the orphaned-rows gap: the web "danger zone" deletes the
    Supabase auth user but relied on this backend endpoint — which did not
    exist — to purge the Postgres rows. User A seeds data, deletes their
    account, and must vanish entirely while user B's data is untouched.
    """

    headers_a = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    headers_b = {"Authorization": f"Bearer {_token_for(USER_B)}"}

    # Seed: A has two applications, B has one.
    for payload in (
        {"company": "Acme", "position": "SWE"},
        {"company": "Initech", "position": "Backend"},
    ):
        resp = await client.post("/applications", json=payload, headers=headers_a)
        assert resp.status_code == 201, resp.text
    resp = await client.post(
        "/applications",
        json={"company": "Hooli", "position": "Infra"},
        headers=headers_b,
    )
    assert resp.status_code == 201, resp.text

    # A deletes their account.
    resp = await client.delete("/account", headers=headers_a)
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] is True

    # A's data is gone...
    resp_a = await client.get("/applications", headers=headers_a)
    assert resp_a.status_code == 200, resp_a.text
    assert resp_a.json()["total"] == 0

    # ...while B is untouched.
    resp_b = await client.get("/applications", headers=headers_b)
    assert resp_b.status_code == 200, resp_b.text
    assert resp_b.json()["total"] == 1
    assert resp_b.json()["applications"][0]["company"] == "Hooli"


async def test_account_deletion_requires_auth(client: AsyncClient) -> None:
    """DELETE /account without a bearer token must 401 (never delete anything)."""

    resp = await client.delete("/account")
    assert resp.status_code == 401
