"""The Gmail connection cap — a guard on a resource that cannot be bought back.

WHAT IS AT STAKE
----------------
Applied was published to Google production on 2026-08-15. That moves it off the
Testing allowlist and onto Google's other limit for a restricted scope: a fixed
number of users **over the entire lifetime of the project**, which Google's own
wording says "cannot be reset or changed". A slot is spent when a person
*reaches the consent screen*; finishing, disconnecting, deleting the account and
revoking at Google all leave it spent. Until this shipped, one stray visitor
clicking "Connect Gmail" cost one of those slots permanently and nothing in the
product could stop it.

WHY THE PLACEMENT IS THE ASSERTION
----------------------------------
A cap enforced at ``/auth/gmail/callback`` would pass a naive "a stranger cannot
connect" test while being useless: by the time Google redirects back, the user
has already been counted. So the tests below refuse at
``/auth/gmail/authorize`` and one of them
(``test_nothing_is_minted_when_the_beta_is_full``) makes the consent-URL builder
explode, so a refusal that still mints would be a red rather than a green.

WHY THE EXEMPTION IS ALSO ASSERTED
----------------------------------
An already-connected user re-consenting an account Google has already counted
spends no new slot, and blocking them would break exactly the people the cap
exists to keep — the operator first. That branch has its own mutation proof; see
below.

PROVED ABLE TO FAIL — TWO MUTATIONS, NOT ONE
--------------------------------------------
One mutation proves the suite notices *a* change, not that each branch carries
weight, and an "admit everyone" mutation leaves the reconnect test green by
construction. Both mutations were run against
``gmail_oauth._enforce_connection_cap`` and both runs are quoted in the PR body:

1. **Admit everyone** — replace the refusal with an unconditional ``return``.
   The ``REFUSES`` tests go red; the ``ADMITS`` tests stay green.
2. **Drop the already-connected exemption** — change
   ``if already_connected or connected < ceiling`` to
   ``if connected < ceiling``. Only ``test_a_connected_user_may_reconnect_at_
   capacity`` and its zero-ceiling twin go red — which is the point: without
   this pair, that exemption would be a branch no test could break.

WHAT THIS FILE CANNOT PROVE
---------------------------
Anything about RLS. SQLite has no row-level security, so the argument for
counting ``gmail_sync_enrollment`` rather than ``user_credentials`` — that the
latter is FORCE-RLS and would answer 0-or-1 inside a request, or nothing at all
without an identity — is an argument from source here, not a measurement. The
Postgres-backed proofs for that table live in ``tests/test_rls_postgres.py``.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import jwt as pyjwt
import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

JWT_SECRET = "gmail-cap-test-jwt-secret-at-least-32-bytes-long-hs256"
ENC_KEY = Fernet.generate_key().decode()
CLIENT_ID = "test-client-id.apps.googleusercontent.com"
CLIENT_SECRET = "test-client-secret"
REDIRECT_URI = "https://api.example.test/auth/gmail/callback"
WEB_APP_URL = "https://web.example.test"

# Real UUIDs, not strings: the connection module's GUC listener binds an
# identity only for a ``uuid.UUID`` and silently binds nothing for a ``str``,
# so seeding with strings would exercise a path production cannot take.
USER_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
USER_C = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

# The address the refusal must carry. Asserted as a literal because it IS the
# product decision: a cap with no way to appeal it is a dead end.
CONTACT = "aesh.03.23@gmail.com"


def _token_for(user_id: uuid.UUID) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {"sub": str(user_id), "aud": "authenticated", "iat": now, "exp": now + 300},
        JWT_SECRET,
        algorithm="HS256",
    )


async def _build_cloud_app(monkeypatch: pytest.MonkeyPatch, *, cap: int | None) -> Any:
    """Reload the cloud app with a given connection ceiling and an empty DB.

    ``cap`` is set through the ENVIRONMENT, never by poking ``settings``: the
    requirement is that the operator can change the number without a code edit,
    so the tests have to travel the same road. ``None`` deletes the variable and
    exercises the shipped default.

    The reload sequence mirrors ``test_cron_sync._build_cloud_app`` — config
    first, then every module holding a ``settings`` or router global, then
    ``main_cloud``, then a fresh in-memory database.
    """

    # NOT ``Settings`` fields: ``config.trusted_web_hosts`` reads these two out
    # of ``os.environ`` on every call.
    monkeypatch.setenv("VERCEL_URL", "")
    monkeypatch.setenv("VERCEL_PROJECT_PRODUCTION_URL", "")

    import jobtracker.auth.supabase_jwt as auth_module
    import jobtracker.cloud.gmail_oauth as gmail_module
    import jobtracker.config as config_module
    import jobtracker.credentials.cloud as cred_cloud_module
    import jobtracker.database.connection as connection_module

    # Every settings instance the request path holds, de-duplicated by object
    # identity -- not ``importlib.reload(jobtracker.config)``, which minted a
    # new one and left the verifier holding the old (#582).
    holders = {
        id(module.settings): module.settings
        for module in (config_module, auth_module, connection_module, cred_cloud_module)
    }
    # ``cap=None`` means "the deployment sets no cap", so the DECLARED default
    # is asserted rather than inherited: an ambient
    # ``JOBTRACKER_GMAIL_CONNECTION_CAP`` used to be cleared by ``delenv`` plus
    # a rebuild, and leaving the attribute alone would let it through.
    declared_cap = type(config_module.settings).model_fields["gmail_connection_cap"].default
    for instance in holders.values():
        monkeypatch.setattr(instance, "deployment", "cloud")
        monkeypatch.setattr(instance, "environment", "test")
        monkeypatch.setattr(instance, "supabase_jwt_secret", JWT_SECRET)
        monkeypatch.setattr(instance, "secret_encryption_key", ENC_KEY)
        monkeypatch.setattr(instance, "google_oauth_client_id", CLIENT_ID)
        monkeypatch.setattr(instance, "google_oauth_client_secret", CLIENT_SECRET)
        monkeypatch.setattr(instance, "gmail_oauth_redirect_uri", REDIRECT_URI)
        monkeypatch.setattr(instance, "web_app_url", WEB_APP_URL)
        monkeypatch.setattr(
            instance, "cors_allowed_hosts", ["web.example.test", "api.example.test"]
        )
        monkeypatch.setattr(
            instance, "gmail_connection_cap", declared_cap if cap is None else cap
        )

    connection_module._engine = None
    gmail_module._INBOX_CACHE.clear()

    from jobtracker.database import init_db

    await init_db()

    import jobtracker.main_cloud as main_cloud_module

    return main_cloud_module.app


async def _teardown(monkeypatch: pytest.MonkeyPatch) -> None:
    import jobtracker.database.connection as connection_module

    if connection_module._engine is not None:
        await connection_module._engine.dispose()
    connection_module._engine = None


@pytest.fixture
async def cloud_app(monkeypatch: pytest.MonkeyPatch, request: Any) -> AsyncIterator[Any]:
    """The cloud app. Indirectly parametrizable with the ceiling."""

    cap = getattr(request, "param", 2)
    yield await _build_cloud_app(monkeypatch, cap=cap)
    await _teardown(monkeypatch)


@pytest.fixture
async def client(cloud_app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=cloud_app)
    async with AsyncClient(
        transport=transport, base_url="http://cap-test", follow_redirects=False
    ) as c:
        yield c


async def _connect(user_id: uuid.UUID, *, revoked: bool = False) -> None:
    """Give ``user_id`` the pair production writes when a mailbox connects.

    Both rows, in one transaction, because that is what
    ``credentials.cloud.save_gmail_credentials`` does — the enrollment fact and
    the credential cannot drift apart in production and must not here.

    ``revoked`` marks the credential the way a permanent ``invalid_grant``
    does. The enrollment row deliberately survives that (the cap counts spent
    Google slots, and revoking at Google does not return one), so a test can
    assert the count still includes them.
    """

    from jobtracker.database import get_session
    from jobtracker.database.models import GmailSyncEnrollment, UserCredential

    from datetime import datetime

    async with get_session() as session:
        session.add(
            UserCredential(
                user_id=user_id,
                kind="gmail_oauth",
                ciphertext=b"not-a-real-token",
                revoked_at=datetime.utcnow() if revoked else None,
            )
        )
        session.add(GmailSyncEnrollment(user_id=user_id))
        await session.commit()


async def _authorize(client: AsyncClient, user_id: uuid.UUID):
    return await client.get(
        "/auth/gmail/authorize",
        headers={"Authorization": f"Bearer {_token_for(user_id)}"},
    )


# ── ADMITS: the guard must not be a wall ──────────────────────────────────


async def test_a_new_user_is_admitted_below_the_ceiling(client: AsyncClient) -> None:
    """ADMITS. One seat of two taken, so the next person connects normally.

    This test is also what stops every 409 below from passing for the wrong
    reason: a route that does not exist answers 404, and a refusal test that is
    really testing a missing route is the defect shape this repo keeps finding.
    """

    await _connect(USER_A)

    resp = await _authorize(client, USER_B)

    assert resp.status_code == 200, resp.text
    assert resp.json()["authorization_url"].startswith(
        "https://accounts.google.com/o/oauth2/auth"
    )


@pytest.mark.parametrize("cloud_app", [3], indirect=True)
async def test_the_ceiling_is_read_from_the_environment(client: AsyncClient) -> None:
    """ADMITS. The same population that is refused at 2 is admitted at 3.

    The ONLY difference between this test and
    ``test_a_new_user_is_refused_at_the_ceiling`` is the value of
    ``JOBTRACKER_GMAIL_CONNECTION_CAP``. That is the requirement — the operator
    raises the number without touching code — stated as an executable pair
    rather than as an assertion that a settings attribute exists.
    """

    await _connect(USER_A)
    await _connect(USER_C)

    resp = await _authorize(client, USER_B)

    assert resp.status_code == 200, resp.text


async def test_a_connected_user_may_reconnect_at_capacity(client: AsyncClient) -> None:
    """ADMITS. RED under mutation 2. The exemption that keeps the beta usable.

    USER_A already holds a connection and the beta is full. Re-consenting an
    account Google has already counted spends no new slot, so refusing here
    would lock the existing users — the operator included — out of their own
    mailboxes the first time a grant needed re-granting, while protecting
    nothing.
    """

    await _connect(USER_A)
    await _connect(USER_C)

    resp = await _authorize(client, USER_A)

    assert resp.status_code == 200, resp.text
    assert "authorization_url" in resp.json()


@pytest.mark.parametrize("cloud_app", [0], indirect=True)
async def test_a_zero_ceiling_still_lets_the_connected_reconnect(
    client: AsyncClient,
) -> None:
    """ADMITS. RED under mutation 2. Closed to the world, open to its users.

    Zero is the operator's "no new mailboxes" switch — there is no sentinel and
    no 'off' value, deliberately — and it must not become "nobody may ever
    re-grant a token". ``0 <= 0`` is true for everyone, so this passes only
    because the membership probe runs.
    """

    await _connect(USER_A)

    resp = await _authorize(client, USER_A)

    assert resp.status_code == 200, resp.text


# ── REFUSES: the guard must actually be a wall ────────────────────────────


async def test_a_new_user_is_refused_at_the_ceiling(client: AsyncClient) -> None:
    """REFUSES. RED under mutation 1. Two of two seats taken; a stranger clicks.

    409 rather than 403: ``apps/web/lib/gmail/server.ts`` maps 401/403 onto
    "your session couldn't be verified — sign in again", which is false here
    and leaves the reader nothing to do. The status is the only thing the web
    can classify on without sniffing a body that will rot.
    """

    await _connect(USER_A)
    await _connect(USER_C)

    resp = await _authorize(client, USER_B)

    assert resp.status_code == 409, resp.text
    body = resp.json()
    # Nothing was minted. Asserted on the response rather than trusted from
    # reading the handler: a body carrying a consent URL would mean the slot
    # was spent regardless of the status code.
    assert "authorization_url" not in body
    detail = body["detail"]
    assert "capacity" in detail.lower()
    assert CONTACT in detail, (
        "a refusal a human cannot act on is a dead end — the message must "
        f"carry the contact route. Got: {detail}"
    )
    assert "2 of 2" in detail, (
        f"the operator reading this in a log needs the numbers. Got: {detail}"
    )


@pytest.mark.parametrize("cloud_app", [0], indirect=True)
async def test_a_zero_ceiling_refuses_every_new_connection(
    client: AsyncClient,
) -> None:
    """REFUSES. RED under mutation 1. Empty database, ceiling of zero."""

    resp = await _authorize(client, USER_B)

    assert resp.status_code == 409, resp.text


@pytest.mark.parametrize("cloud_app", [1], indirect=True)
async def test_lowering_the_ceiling_below_the_count_refuses(
    client: AsyncClient,
) -> None:
    """REFUSES. RED under mutation 1. Three connected, ceiling since cut to one.

    The over-subscribed case is not hypothetical: the operator's remedy for
    "too many people got in" is to lower the number, and a guard written as
    ``connected == ceiling`` would sail straight past it.
    """

    await _connect(USER_A)
    await _connect(USER_C)
    await _connect(uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd"))

    resp = await _authorize(client, USER_B)

    assert resp.status_code == 409, resp.text


async def test_a_revoked_grant_still_occupies_its_seat(client: AsyncClient) -> None:
    """REFUSES. RED under mutation 1. Google does not refund a revoked user.

    USER_C revoked at Google, so their credential is marked and the cron will
    skip them — but the Google slot they spent is gone forever. The enrollment
    row survives revocation precisely so this count keeps including them. The
    opposite reading (subtract revoked users, as ``cron._probe_sync_position``
    correctly does for sync candidates) would hand out a seat Google still
    considers occupied.
    """

    await _connect(USER_A)
    await _connect(USER_C, revoked=True)

    resp = await _authorize(client, USER_B)

    assert resp.status_code == 409, resp.text


async def test_nothing_is_minted_when_the_beta_is_full(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REFUSES, BEFORE GOOGLE. The placement claim, made executable.

    The whole guard rests on running before a consent URL exists — the slot is
    spent when the user reaches Google's screen, so a check in the callback is a
    check after the loss. Here the consent-URL builder is replaced with an
    explosion: if the cap were enforced anywhere downstream of it, this test
    fails with that explosion instead of a 409, and no amount of reading the
    source could have told the two apart.
    """

    import jobtracker.cloud.gmail_oauth as gmail_module

    def _detonate(*_args: Any, **_kwargs: Any):
        raise AssertionError("the consent URL was built for a refused user")

    monkeypatch.setattr(gmail_module, "_build_flow", _detonate)

    await _connect(USER_A)
    await _connect(USER_C)

    resp = await _authorize(client, USER_B)

    assert resp.status_code == 409, resp.text


async def test_an_uncountable_census_refuses_rather_than_guessing(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REFUSES. Fail closed: an unknown count is not a free slot.

    Supabase pauses a free-tier project after seven days idle, and this is the
    only database read on the authorize path — so "the count raised" is a state
    production will genuinely reach. Letting the request through on a failed
    read is the classic way a guard stops guarding while every happy-path test
    stays green. 503, and no consent URL.
    """

    import jobtracker.cloud.gmail_oauth as gmail_module

    async def _boom(*_args: Any, **_kwargs: Any):
        raise RuntimeError("database unreachable")

    monkeypatch.setattr(gmail_module, "gmail_connection_census", _boom)

    resp = await _authorize(client, USER_B)

    assert resp.status_code == 503, resp.text
    assert "authorization_url" not in resp.json()


# ── the operator's number, without a SQL client ───────────────────────────


async def test_capacity_endpoint_reports_the_counts(client: AsyncClient) -> None:
    """The whole point of the endpoint: slots spent, without opening psql."""

    await _connect(USER_A)

    resp = await client.get("/health/gmail-capacity")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "connected": 1,
        "ceiling": 2,
        "remaining": 1,
        "at_capacity": False,
    }


async def test_capacity_endpoint_says_when_it_is_full(client: AsyncClient) -> None:
    await _connect(USER_A)
    await _connect(USER_C)

    body = (await client.get("/health/gmail-capacity")).json()

    assert body["at_capacity"] is True
    assert body["remaining"] == 0


@pytest.mark.parametrize("cloud_app", [1], indirect=True)
async def test_capacity_endpoint_never_goes_negative(client: AsyncClient) -> None:
    """Over-subscribed reads as zero left, not as "-1 remaining"."""

    await _connect(USER_A)
    await _connect(USER_C)

    body = (await client.get("/health/gmail-capacity")).json()

    assert body["connected"] == 2
    assert body["remaining"] == 0
    assert body["at_capacity"] is True


async def test_capacity_endpoint_leaks_no_identities(client: AsyncClient) -> None:
    """Counts only. A membership fact per user is not the operator's answer.

    ``gmail_sync_enrollment`` holds user ids, and the natural sloppy
    implementation returns the list it just counted. Asserted on the raw body
    text so a nested or renamed field cannot smuggle one through.
    """

    await _connect(USER_A)
    await _connect(USER_C)

    text = (await client.get("/health/gmail-capacity")).text

    assert str(USER_A) not in text
    assert str(USER_C) not in text


async def test_capacity_endpoint_reports_null_when_it_cannot_count(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Null, never zero. Zero would read as "24 slots free" on a dead database."""

    import jobtracker.cloud.gmail_oauth as gmail_module

    async def _boom(*_args: Any, **_kwargs: Any):
        raise RuntimeError("database unreachable")

    monkeypatch.setattr(gmail_module, "gmail_connection_census", _boom)

    resp = await client.get("/health/gmail-capacity")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["connected"] is None
    assert body["remaining"] is None
    assert body["at_capacity"] is None
    assert body["ceiling"] == 2


# ── the shipped default ───────────────────────────────────────────────────


@pytest.mark.parametrize("cloud_app", [None], indirect=True)
async def test_the_default_ceiling_is_conservative(client: AsyncClient) -> None:
    """With no variable set at all, the deployment is already capped.

    A guard that only works once the operator remembers to configure it is not a
    guard. The default also has to sit well below Google's own number, because
    this deployment can only count completed connections: an abandoned consent
    screen spends a slot and writes no row anywhere.
    """

    body = (await client.get("/health/gmail-capacity")).json()

    assert body["ceiling"] == 25
    assert 0 < body["ceiling"] < 100
