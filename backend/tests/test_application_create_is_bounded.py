"""``POST /applications`` accepted a company the database cannot index.

Issue #406. ``company``, ``position`` and ``notes`` had no ``max_length``
anywhere — not on :class:`CloudApplicationCreate` and not on the table model —
so the endpoint took whatever the wire sent:

    POST /applications strings=5000000 -> 201 in 0.16s ; stored company len: 5000000

That is harmless on SQLite and fatal on the database production actually runs.
``company`` is indexed twice (``ix_applications_company`` on the raw column and
``ix_applications_user_id_lower_company`` on ``lower(company)``) and a btree
version 4 index row may not exceed 2704 bytes:

    company len=2000  -> INSERT OK
    company len=2700  -> ProgramLimitExceeded: index row size 2712 exceeds
                         btree version 4 maximum 2704
    smallest rejected incompressible company: 2677 characters
    position len=5,000,000 -> INSERT OK      # unindexed, so it is `company`

SQLite has no index-row limit, which is why the whole backend suite passes with
the field unbounded and none of this is visible on a laptop.

WHAT THIS MODULE PROVES AND WHAT IT DOES NOT
--------------------------------------------
It proves the API refuses over-long values with a 422 before anything is
allocated or written, and — the half that matters more — that an ordinary
application still returns 201. It runs on SQLite, so it CANNOT see the btree
ceiling; asserting anything about index rows here would be a check that cannot
fail. That half lives in ``test_company_index_postgres.py``, against the schema
``alembic upgrade head`` really builds, where the ceiling is real.

The bound is on the REQUEST model rather than the table model on purpose: the
table is also written by the sync, and the failure being fixed is an HTTP
request reaching an INSERT it was always going to break. A bound on the wire
also lands in the OpenAPI document the web app's bindings are generated from.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

from jobtracker.cloud.applications import (
    _MAX_COMPANY_LEN,
    _MAX_NOTES_LEN,
    _MAX_ROLE_LEN,
    ApplicationRoleUpdate,
    CloudApplicationCreate,
)

JWT_SECRET = "application-bounds-test-jwt-secret-at-least-32-bytes-long-hs256"
USER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

# The largest btree v4 index row Postgres will store, in bytes. Not a constant
# this repo gets to choose — it is a page-layout fact of the engine, quoted here
# so the arithmetic below has something to be checked against.
BTREE_MAX_INDEX_ROW_BYTES = 2704

# A UTF-8 code point is at most four bytes, and ``max_length`` counts
# CHARACTERS. Every conversion from one to the other has to assume the worst.
MAX_UTF8_BYTES_PER_CHAR = 4


def _token_for(user_id: str) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {"sub": user_id, "aud": "authenticated", "iat": now, "exp": now + 300},
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture
async def cloud_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """The cloud FastAPI app on the in-memory SQLite DB, with auth enabled.

    THE `importlib.reload(jobtracker.config)` FIXTURE IS THE WRONG ONE HERE,
    and this module is where that stops being theoretical. Reloading the config
    module mints a NEW settings instance while every
    ``from jobtracker.config import settings`` binding still points at the old
    one, so a JWT secret set that way outlives the fixture that set it.
    ``test_application_delete_children.py`` documents the trap and avoids it for
    exactly this reason — and this file sorts IMMEDIATELY BEFORE it, so the
    first draft of this module (which copied the reload fixture from
    ``test_status_vocabulary.py``) turned six of its tests red with
    ``401 {"detail":"Invalid signature"}``.

    Measured, and not caused by this change: running
    ``test_status_vocabulary.py`` immediately before
    ``test_application_delete_children.py`` fails the same six today. Collection
    order is what keeps that pair apart on main.

    ``settings`` is a singleton every module holds BY REFERENCE, so patching
    three attributes on it reaches all of them and ``monkeypatch`` undoes it
    exactly. ``database_url`` is a property derived from ``environment``, so the
    in-memory URL follows from the same patch; resetting ``_engine`` is what
    makes the next ``get_engine()`` build against it.
    """

    import jobtracker.config as config_module
    import jobtracker.database.connection as connection_module

    monkeypatch.setattr(config_module.settings, "environment", "test")
    monkeypatch.setattr(config_module.settings, "deployment", "cloud")
    monkeypatch.setattr(config_module.settings, "supabase_jwt_secret", JWT_SECRET)

    connection_module._engine = None

    from jobtracker.database import init_db

    await init_db()

    import jobtracker.main_cloud as main_cloud_module

    yield main_cloud_module.app

    if connection_module._engine is not None:
        await connection_module._engine.dispose()
    connection_module._engine = None


@pytest.fixture
async def client(cloud_app: Any) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=cloud_app)
    async with AsyncClient(transport=transport, base_url="http://cloud-test") as c:
        yield c


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token_for(USER_A)}"}


def _body(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"company": "Cedar Systems", "position": "Backend Engineer"}
    payload.update(overrides)
    return payload


# =============================================================================
# It still files an application
# =============================================================================


async def test_an_ordinary_application_is_created(client: AsyncClient) -> None:
    """NON-VACUITY. Every rejection below means nothing if this fails."""

    resp = await client.post(
        "/applications",
        headers=_headers(),
        json=_body(notes="Referred by Nadia. Take-home due Friday."),
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["company"] == "Cedar Systems"
    assert resp.json()["position"] == "Backend Engineer"


@pytest.mark.parametrize(
    "field,length",
    [
        ("company", _MAX_COMPANY_LEN),
        ("position", _MAX_ROLE_LEN),
        ("notes", _MAX_NOTES_LEN),
    ],
)
async def test_a_value_sitting_exactly_on_the_bound_is_accepted(
    client: AsyncClient, field: str, length: int
) -> None:
    """The boundary itself, from below.

    A bound is a decision about which values are legal, so the case ON it has
    to be exercised: an off-by-one in the schema — ``lt`` where ``le`` was
    meant — refuses a value the comment says is fine, and a test that only
    checked ``bound + 1`` would never see it.
    """

    resp = await client.post(
        "/applications", headers=_headers(), json=_body(**{field: "x" * length})
    )

    assert resp.status_code == 201, resp.text
    assert len(resp.json()[field]) == length


# =============================================================================
# It refuses what the database cannot take
# =============================================================================


@pytest.mark.parametrize(
    "field,length",
    [
        ("company", _MAX_COMPANY_LEN + 1),
        ("position", _MAX_ROLE_LEN + 1),
        ("notes", _MAX_NOTES_LEN + 1),
    ],
)
async def test_one_character_over_the_bound_is_refused(
    client: AsyncClient, field: str, length: int
) -> None:
    resp = await client.post(
        "/applications", headers=_headers(), json=_body(**{field: "x" * length})
    )

    assert resp.status_code == 422, resp.text
    assert field in resp.text


async def test_the_measured_payload_from_the_issue_is_refused(client: AsyncClient) -> None:
    """The exact body that answered 201, and the exact length Postgres rejects.

    5,000,000 characters is what the issue measured going in and coming back
    out of the API. 2,677 is the smallest incompressible ``company`` the real
    schema refused to index — under the old code both were 201.
    """

    huge = await client.post(
        "/applications",
        headers=_headers(),
        json={"company": "C" * 5_000_000, "position": "P" * 5_000_000, "notes": "N" * 5_000_000},
    )
    assert huge.status_code == 422, huge.text

    btree_fatal = await client.post(
        "/applications", headers=_headers(), json=_body(company="C" * 2677)
    )
    assert btree_fatal.status_code == 422, btree_fatal.text


@pytest.mark.parametrize("field", ["company", "position", "notes"])
async def test_the_issues_payload_is_refused_one_field_at_a_time(
    client: AsyncClient, field: str
) -> None:
    """5,000,000 characters in ONE field, with the other two ordinary.

    WHY THIS IS NOT THE TWO TESTS ABOVE, AND WHY IT IS THE ONE THAT BITES.

    ``test_one_character_over_the_bound_is_refused`` derives its length from
    the constant it is testing, so it moves with it: raise ``_MAX_NOTES_LEN``
    to 10,000,000 and it posts 10,000,001 characters and still reads 422. It
    can see an off-by-one in the schema. It cannot see the bound itself being
    dismantled, which is the failure #406 is about.

    ``test_the_measured_payload_from_the_issue_is_refused`` sends all three
    fields oversized at once and asserts one status code, so ANY single field
    refusing satisfies it — an early guard masking the later ones. With
    ``_MAX_NOTES_LEN`` raised a thousandfold, ``company`` alone still produces
    the 422 and the test stays green.

    Between them, ``_MAX_NOTES_LEN = 10_000 -> 10_000_000`` was green across
    the whole backend suite: ``company`` had the btree arithmetic and
    ``position`` had ``test_user_supplied_role.py``, and ``notes`` had nothing.

    So: a LITERAL length, taken from the issue's own measurement rather than
    from the constant, one field at a time, and the refusal has to name the
    field it is about — a 422 for some other reason is not this bound working.
    """

    resp = await client.post(
        "/applications", headers=_headers(), json=_body(**{field: "x" * 5_000_000})
    )

    assert resp.status_code == 422, (
        f"{field} accepted 5,000,000 characters. That is the payload issue #406 "
        f"measured answering 201, and the bound on this field is gone or has been "
        f"raised past any length a person types."
    )
    locations = [error.get("loc", []) for error in resp.json()["detail"]]
    assert any(field in location for location in locations), (
        f"the request was refused, but not because of {field} — the 422 names "
        f"{locations}, so this test would pass with {field} unbounded as long as "
        f"some other field happened to be invalid"
    )


# =============================================================================
# Where the numbers come from
# =============================================================================


def test_the_company_bound_cannot_reach_the_btree_ceiling() -> None:
    """The derivation, stated so a later widening has to face it.

    This is arithmetic, not a database test — ``test_company_index_postgres``
    is what actually inserts at the bound against a real btree. What it pins is
    that the number was chosen for a reason: at four bytes per character, the
    worst case UTF-8 allows, ``_MAX_COMPANY_LEN`` characters must still leave
    room inside 2,704 bytes for the index tuple's own overhead, the ``user_id``
    in the composite index, and the occasional code point whose ``lower()`` is
    longer than itself.
    """

    worst_case_bytes = _MAX_COMPANY_LEN * MAX_UTF8_BYTES_PER_CHAR

    assert worst_case_bytes * 2 < BTREE_MAX_INDEX_ROW_BYTES, (
        f"_MAX_COMPANY_LEN is {_MAX_COMPANY_LEN}, i.e. up to {worst_case_bytes} bytes "
        f"of UTF-8. That leaves under 2x headroom inside the {BTREE_MAX_INDEX_ROW_BYTES}-byte "
        "btree index row, which is not enough to absorb the tuple overhead and a "
        "case-folding expansion. The INSERT this bound exists to prevent becomes "
        "reachable again."
    )


def test_the_create_bound_and_the_role_update_bound_are_the_same_number() -> None:
    """``position`` and ``role`` are ONE column, so they get one ceiling.

    ``PUT /applications/{id}/role`` writes ``Application.position``. Two
    different limits on it would mean a title this endpoint accepts that the
    PUT then refuses, which is a bug nobody would look for in a schema.
    """

    def bound(model: Any, field: str) -> int:
        return next(
            m.max_length
            for m in model.model_fields[field].metadata
            if getattr(m, "max_length", None) is not None
        )

    assert bound(CloudApplicationCreate, "position") == bound(ApplicationRoleUpdate, "role")
    assert bound(CloudApplicationCreate, "position") == _MAX_ROLE_LEN
