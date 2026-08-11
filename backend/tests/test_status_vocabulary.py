"""One stage vocabulary, and every copy of it checked against that one.

Measured against the live app on 2026-08-10: setting a card's stage to
``assessment`` returned 422. Three vocabularies disagreed —

- the board card's ``<select>``: 7 values, INCLUDING ``assessment``;
- the file-by-hand dialog's ``<select>``: 6 values, no ``assessment``, no
  ``ghosted``;
- the API enum: 7 values, no ``assessment``, WITH ``ghosted``.

``assessment`` is a classifier CATEGORY, not a stage. A message can *be* an
assessment request, which is why the classifier predicts it; the application it
belongs to is at the interviewing stage. That was already the behaviour
everywhere the two meet (``pipeline._STAGE_RANK`` ranks it between applied and
interview and ``_rank_to_status`` folds it into ``interviewing``; the orphan
reconciler files it as ``interviewing``; the web's own stage grouping puts
``interviewing``/``interview``/``assessment`` in one column). Promoting it to an
``ApplicationStatus`` would mean an ``ALTER TYPE applicationstatus ADD VALUE``
against live Postgres to encode a distinction the product does not make.

So :class:`ApplicationStatus` is the single definition, ``APPLICATION_STATUSES``
is derived from it, and these tests fail if any of the four backend restatements
of that vocabulary drifts from it — including the endpoint, which is the copy
the 422 actually came from.
"""

from __future__ import annotations

import importlib
import time
from collections.abc import AsyncIterator
from typing import Any

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

from jobtracker.database.models import (
    APPLICATION_STATUSES,
    CATEGORY_TO_STATUS,
    DEFAULT_APPLICATION_STATUS,
    ApplicationStatus,
    EmailCategory,
)

JWT_SECRET = "status-vocab-test-jwt-secret-at-least-32-bytes-long-hs256"
USER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

# The canonical list, written out ONCE in the test suite so a change to the enum
# has to be made deliberately rather than absorbed by a derived assertion.
EXPECTED_STATUSES = (
    "applied",
    "interviewing",
    "offered",
    "rejected",
    "accepted",
    "withdrawn",
    "ghosted",
)


def _token_for(user_id: str) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {"sub": user_id, "aud": "authenticated", "iat": now, "exp": now + 300},
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture
async def cloud_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """Cloud app on the in-memory DB — the reload sequence from C3's tests."""

    monkeypatch.setenv("JOBTRACKER_DEPLOYMENT", "cloud")
    monkeypatch.setenv("JOBTRACKER_ENVIRONMENT", "test")
    monkeypatch.setenv("JOBTRACKER_SUPABASE_JWT_SECRET", JWT_SECRET)

    import jobtracker.config as config_module
    import jobtracker.database.connection as connection_module

    importlib.reload(config_module)
    connection_module._engine = None

    import jobtracker.auth.supabase_jwt as auth_module

    importlib.reload(auth_module)

    import jobtracker.cloud.applications as cloud_apps_module

    importlib.reload(cloud_apps_module)

    import jobtracker.main_cloud as main_cloud_module

    importlib.reload(main_cloud_module)

    from jobtracker.database import init_db

    await init_db()

    yield main_cloud_module.app

    if connection_module._engine is not None:
        await connection_module._engine.dispose()
    connection_module._engine = None

    monkeypatch.undo()
    importlib.reload(config_module)


@pytest.fixture
async def client(cloud_app: Any) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=cloud_app)
    async with AsyncClient(transport=transport, base_url="http://cloud-test") as c:
        yield c


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token_for(USER_A)}"}


# =============================================================================
# One definition
# =============================================================================


def test_the_canonical_list_is_derived_from_the_enum() -> None:
    """``APPLICATION_STATUSES`` is not a second list; it is the enum's values."""

    assert APPLICATION_STATUSES == EXPECTED_STATUSES
    assert tuple(s.value for s in ApplicationStatus) == APPLICATION_STATUSES
    assert DEFAULT_APPLICATION_STATUS.value in APPLICATION_STATUSES


def test_assessment_is_a_classifier_category_and_not_a_stage() -> None:
    """The decision, stated where a future change has to walk past it."""

    from jobtracker.cloud import pipeline

    assert "assessment" in pipeline.CANONICAL_CATEGORIES
    assert "assessment" not in APPLICATION_STATUSES
    assert CATEGORY_TO_STATUS[EmailCategory.ASSESSMENT] is ApplicationStatus.INTERVIEWING
    # ... and the rollup independently agrees, which is why it is not a stage.
    assert pipeline._rank_to_status(pipeline._STAGE_RANK["assessment"]) == "interviewing"


def test_the_rollup_rank_tables_account_for_every_canonical_status() -> None:
    """Every stage is either advanceable-to or terminal — no status may be
    unknown to ``advance_application_status``, which would silently ignore it."""

    from jobtracker.cloud import pipeline

    known = set(pipeline._STATUS_RANK) | set(pipeline._TERMINAL_STATUSES)
    assert known == set(APPLICATION_STATUSES)


def test_every_status_has_a_training_label() -> None:
    """A status missing here is a correction that trains nothing."""

    from jobtracker.cloud.applications import _STATUS_TO_TRAINING_LABEL

    assert set(_STATUS_TO_TRAINING_LABEL) == set(ApplicationStatus)


def test_the_category_map_only_ever_targets_a_canonical_status() -> None:
    """A classifier verdict may only file into a real stage."""

    from jobtracker.cloud import pipeline
    from jobtracker.cloud.applications import _lifecycle_to_status

    for category, status in CATEGORY_TO_STATUS.items():
        assert category.value in pipeline.CANONICAL_CATEGORIES
        assert status.value in APPLICATION_STATUSES
        # The reconciler reads the map rather than holding a second copy.
        assert _lifecycle_to_status(category) == status.value

    # Categories that assert no stage at all stay unmapped, not defaulted.
    for category in (
        EmailCategory.FOLLOW_UP,
        EmailCategory.NEEDS_REVIEW,
        EmailCategory.OTHER,
    ):
        assert category not in CATEGORY_TO_STATUS
        assert _lifecycle_to_status(category) is None


# =============================================================================
# ... and the API agrees with it
# =============================================================================


async def test_the_statuses_endpoint_serves_exactly_the_canonical_list(
    client: AsyncClient,
) -> None:
    """The one place a client should read the vocabulary from."""

    resp = await client.get("/applications/statuses", headers=_headers())
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["statuses"] == list(EXPECTED_STATUSES)
    assert body["default"] == "applied"
    assert body["category_to_status"]["assessment"] == "interviewing"
    # The categories are a DIFFERENT vocabulary and stay visibly different.
    assert "assessment" in body["classifier_categories"]
    assert "assessment" not in body["statuses"]
    assert set(body["category_to_status"]) <= set(body["classifier_categories"])
    assert set(body["category_to_status"].values()) <= set(body["statuses"])


async def test_the_statuses_route_is_not_swallowed_by_the_id_route(
    client: AsyncClient,
) -> None:
    """``/applications/statuses`` must not be parsed as application id
    "statuses" — it is declared above ``GET /{application_id}`` for this."""

    resp = await client.get("/applications/statuses", headers=_headers())
    assert resp.status_code == 200
    assert (await client.get("/applications/9999", headers=_headers())).status_code == 404


@pytest.mark.parametrize("status_value", APPLICATION_STATUSES)
async def test_every_canonical_status_is_accepted_by_the_patch_endpoint(
    client: AsyncClient, status_value: str
) -> None:
    """The test that would have caught the shipped 422.

    Parametrized over the canonical list itself, so a status added to the enum
    without the endpoint accepting it fails here rather than in production.
    """

    created = await client.post(
        "/applications",
        json={"company": "Acme", "position": "SWE"},
        headers=_headers(),
    )
    assert created.status_code == 201, created.text
    app_id = created.json()["id"]

    resp = await client.patch(
        f"/applications/{app_id}",
        json={"status": status_value},
        headers=_headers(),
    )
    assert resp.status_code == 200, f"{status_value!r} rejected: {resp.text}"
    assert resp.json()["status"] == status_value


async def test_a_classifier_category_is_not_settable_as_a_stage(
    client: AsyncClient,
) -> None:
    """``assessment`` is deliberately a 422, and the message names the real list.

    If this ever starts passing, the decision above was reversed and the enum,
    the Postgres type, the rank tables and the training-label map all have to
    have moved with it.
    """

    created = await client.post(
        "/applications",
        json={"company": "Acme", "position": "SWE"},
        headers=_headers(),
    )
    app_id = created.json()["id"]

    resp = await client.patch(
        f"/applications/{app_id}",
        json={"status": "assessment"},
        headers=_headers(),
    )
    assert resp.status_code == 422
    assert "interviewing" in resp.text


async def test_the_openapi_enum_is_the_same_list(client: AsyncClient) -> None:
    """A client generating types from the schema gets the canonical list too."""

    schema = (await client.get("/openapi.json")).json()
    enum = schema["components"]["schemas"]["ApplicationStatus"]["enum"]
    assert enum == list(EXPECTED_STATUSES)
