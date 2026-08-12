"""One stage vocabulary, and every copy of it checked against that one.

Measured against the live app on 2026-08-10: setting a card's stage to
``assessment`` returned 422. Three vocabularies disagreed —

- the board card's ``<select>``: 7 values, INCLUDING ``assessment``;
- the file-by-hand dialog's ``<select>``: 6 values, no ``assessment``, no
  ``ghosted``;
- the API enum: 7 values, no ``assessment``, WITH ``ghosted``.

``assessment`` is a stage AND a classifier category — as of 2026-08-12. It is
the one member the two vocabularies share, and it got there by reversing the
decision this module used to assert.

The old decision folded it into ``interviewing`` because "the product does not
make that distinction". The product's OWNER does. The mail that settled it was
five self-serve timed tasks with a seven-day expiry — no human, no scheduling,
no call — and the board said "interviewing" about it, on the one screen he
looks at. The distinction was also already made everywhere except the enum:
``pipeline._STAGE_RANK`` has always ranked ``assessment`` between applied and
interview, and since ``b7c31e0d94aa`` a row carries ``due_at``, so an expiry and
a scheduled slot are already different facts in the schema.

What did NOT change, and must not be quietly changed later: the classifier's
nine-value :class:`EmailCategory` vocabulary and the corpus labelled with it;
the terminal set; the monotonic rule (an in-flight row only moves forward, so
``interviewing`` + an assessment mail stays ``interviewing``); and application
identity. See :data:`jobtracker.database.models.CATEGORY_TO_STATUS` for the
full statement.

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
    "assessment",
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


def test_assessment_is_a_stage_as_well_as_a_classifier_category() -> None:
    """The decision, stated where a future change has to walk past it.

    The mirror image of the test that stood here until 2026-08-12. If this ever
    starts failing, the fold back into ``interviewing`` was reinstated, and the
    enum, the rank tables, the Postgres type and the web's mirror all have to
    have moved with it.
    """

    from jobtracker.cloud import pipeline

    assert "assessment" in pipeline.CANONICAL_CATEGORIES
    assert "assessment" in APPLICATION_STATUSES
    assert CATEGORY_TO_STATUS[EmailCategory.ASSESSMENT] is ApplicationStatus.ASSESSMENT
    # ... and the rollup agrees: the stage rank it always had now rolls up to
    # itself instead of folding one stage further along.
    assert pipeline._rank_to_status(pipeline._STAGE_RANK["assessment"]) == "assessment"
    # It sits between applied and interviewing, in the enum and in the ranks.
    assert APPLICATION_STATUSES.index("assessment") == 1
    assert (
        pipeline._STATUS_RANK["applied"]
        < pipeline._STATUS_RANK["assessment"]
        < pipeline._STATUS_RANK["interviewing"]
    )
    # An assessment is in flight, not settled.
    assert "assessment" not in pipeline._TERMINAL_STATUSES


def test_the_two_vocabularies_still_are_not_the_same_list() -> None:
    """Sharing one member must not make them interchangeable.

    ``assessment`` is now in both, which is exactly when the original defect —
    treating a classifier category as a stage — becomes easy to reintroduce. A
    category is a claim about a MESSAGE; a status is a fact about an
    APPLICATION; the overlap is one word, not a relationship.
    """

    from jobtracker.cloud import pipeline

    categories = set(pipeline.CANONICAL_CATEGORIES)
    statuses = set(APPLICATION_STATUSES)

    assert categories & statuses == {"applied", "assessment"}
    # Categories that are not stages, and stages that are not categories.
    assert {"follow_up", "needs_review", "other", "interview", "offer", "rejection"} <= categories
    assert not {"follow_up", "needs_review", "other"} & statuses
    assert {"interviewing", "offered", "rejected", "withdrawn", "ghosted"} <= statuses
    assert not {"withdrawn", "ghosted"} & categories


def test_the_monotonic_rule_survived_assessment_becoming_a_stage() -> None:
    """Which moves advance a row, stated as a decision rather than left to luck.

    ``applied`` → ``assessment`` → ``interviewing`` advances, because that is
    the order the ranks put them in. ``interviewing`` + an assessment mail STAYS
    ``interviewing``: mail may only push a row forward, and a re-test does not
    un-interview anybody. That is deliberate and it costs nothing, because the
    deadline that re-test carries lands via ``due_at``, which is recomputed from
    the mail independently of the status. A second requisition is a separate row
    under the existing identity rules and starts its own journey.
    """

    from jobtracker.cloud.pipeline import advance_application_status as advance

    assert advance("applied", "assessment") == "assessment"
    assert advance("assessment", "interviewing") == "interviewing"
    assert advance("assessment", "offered") == "offered"
    assert advance("applied", "interviewing") == "interviewing"

    # Backwards moves are refused, including the new one.
    assert advance("interviewing", "assessment") == "interviewing"
    assert advance("assessment", "applied") == "assessment"
    assert advance("offered", "assessment") == "offered"

    # A rejection still wins from any in-flight stage, and a terminal status is
    # still never left.
    assert advance("assessment", "rejected") == "rejected"
    assert advance("rejected", "assessment") == "rejected"
    assert advance("accepted", "assessment") == "accepted"
    assert advance("withdrawn", "assessment") == "withdrawn"
    assert advance("ghosted", "assessment") == "ghosted"


def test_the_rollup_rank_tables_account_for_every_canonical_status() -> None:
    """Every stage is either advanceable-to or terminal — no status may be
    unknown to ``advance_application_status``, which would silently ignore it."""

    from jobtracker.cloud import pipeline

    known = set(pipeline._STATUS_RANK) | set(pipeline._TERMINAL_STATUSES)
    assert known == set(APPLICATION_STATUSES)


def test_a_stage_is_not_convertible_into_a_message_label() -> None:
    """The status→training-label map is GONE, and must not come back.

    It existed so a stage correction could write a ``training_data`` example for
    every linked email. That is a category error with measured damage — an
    assessment invite entered the corpus as a ``rejection``, and
    ``withdrawn``/``ghosted`` mapped to ``other`` — so the map was deleted along
    with the loop that read it. Re-adding one puts the defect back, which is why
    this asserts its absence rather than its completeness.
    """

    from jobtracker.cloud import applications as cloud_apps

    assert not [
        name
        for name in vars(cloud_apps)
        if "TRAINING_LABEL" in name.upper()
    ], (
        "a status→training-label map is back in cloud/applications.py. A stage "
        "is a fact about an application; a training example is a claim about "
        "one message. Per-message labels come from the review queue."
    )


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
    assert body["category_to_status"]["assessment"] == "assessment"
    # The categories are a DIFFERENT vocabulary and stay visibly different —
    # they now overlap on `assessment` (and `applied`), which is the whole
    # reason the endpoint keeps serving both lists rather than one.
    assert "assessment" in body["classifier_categories"]
    assert "assessment" in body["statuses"]
    assert "follow_up" in body["classifier_categories"]
    assert "follow_up" not in body["statuses"]
    assert "ghosted" in body["statuses"]
    assert "ghosted" not in body["classifier_categories"]
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


async def test_assessment_is_settable_as_a_stage(client: AsyncClient) -> None:
    """The mirror of the test that asserted this was a 422.

    Measured on the live app on 2026-08-10, setting a card to ``assessment``
    answered ``422 · Input should be 'applied', 'interviewing', ...``. It is a
    stage now, so it must answer 200 and the row must actually hold it — not be
    silently coerced to ``interviewing``, which is the failure this whole change
    exists to end.
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
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "assessment"

    fetched = await client.get(f"/applications/{app_id}", headers=_headers())
    assert fetched.json()["application"]["status"] == "assessment"


async def test_a_category_that_is_not_a_stage_is_still_not_settable(
    client: AsyncClient,
) -> None:
    """The guard the inverted test above used to provide, kept alive.

    ``assessment`` moved; the RULE did not. A classifier category that asserts
    no stage — ``follow_up`` is the clearest, a nudge is not a stage of anything
    — is still a 422, and the message still names the real list.
    """

    created = await client.post(
        "/applications",
        json={"company": "Acme", "position": "SWE"},
        headers=_headers(),
    )
    app_id = created.json()["id"]

    resp = await client.patch(
        f"/applications/{app_id}",
        json={"status": "follow_up"},
        headers=_headers(),
    )
    assert resp.status_code == 422
    assert "assessment" in resp.text
    assert "interviewing" in resp.text


async def test_the_openapi_enum_is_the_same_list(cloud_app: Any) -> None:
    """A client generating types from the schema gets the canonical list too.

    Reads the document from ``app.openapi()`` rather than over HTTP from
    ``/openapi.json``. The route is opt-in as of 2026-08-12 (see
    tests/test_api_docs_are_opt_in.py) and is absent unless
    JOBTRACKER_ENABLE_DOCS is set, so fetching it here would test the docs
    switch instead of the enum. The document itself is unaffected, and
    ``app.openapi()`` is exactly what scripts/generate_api_schema.sh calls to
    build apps/web/lib/api/schema.d.ts -- so this now checks the same object
    the real type generator consumes.
    """

    schema = cloud_app.openapi()
    enum = schema["components"]["schemas"]["ApplicationStatus"]["enum"]
    assert enum == list(EXPECTED_STATUSES)
