"""The ``needs_review`` tile goes through ``_review_queue_rows_statement`` (#827).

WHY THIS MODULE EXISTS
----------------------
#827 measured the tile's read and #827's own acceptance criterion asked that
whatever the statement becomes be EXPOSED, so
``tests/test_read_path_indexes_postgres.py`` can EXPLAIN what the endpoint
actually issues instead of retyping its six columns. It now imports
:func:`~jobtracker.cloud.applications._review_queue_rows_statement`.

That import is only worth anything while the ENDPOINT reaches the same builder.
If somebody re-inlines the ``select()`` in ``application_summary_cloud`` — which
is exactly where it lived until #827 — the builder keeps compiling, the plan
test keeps EXPLAINing it and keeps passing, and it is measuring a statement no
request issues. A registration nobody checks is unchecked coverage; this module
is the check. It is the same shape as the mutation recorded in
``test_the_orm_emits_the_predicates_these_indexes_were_measured_against``, where
the handler's entire application filter was deleted and every plan assertion
stayed green because the test held a copy.

WHAT IS ASSERTED, AND WHAT IS NOT
---------------------------------
NOT that the projection is right — nothing here reads the six columns, and
nothing in the plan test does either, because a plan does not care which columns
are fetched. Sharing ``_REVIEW_KEY_COLUMNS`` between the tile and the additive
persist removes a copy; it does not create a gate, and claiming otherwise would
be the drift this repo keeps finding.

What is asserted is behaviour: the number the endpoint renders moves when and
only when the builder does, and the tile counts a set the queue it links to
cannot show all of.

SQLITE IS ENOUGH HERE. Every claim is about which Python function produced a
number. The planner facts live in the Postgres module and are not repeated.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

from jobtracker.database.models import Email, EmailCategory, EmailSource

# 32+ bytes so PyJWT does not warn; the value only has to match the token helper.
JWT_SECRET = "tile-reads-through-its-statement-secret-at-least-32"
OWNER = "6f1c0d2a-93b4-4e57-8a01-2c7d5e9b4f13"

RECEIVED_AT = datetime(2026, 9, 1, 12, 0, 0)

#: Six un-reviewed ``NEEDS_REVIEW`` messages on six threads, none linked to an
#: application. One thread each, so ``pipeline.review_dedup_key`` collapses
#: nothing and the tile's number is the row count — which is what makes the
#: bound case below measure a BOUND rather than a dedupe.
QUEUED_MAIL = tuple(f"m-{n}" for n in range(1, 7))

#: Spelled out rather than ``len(QUEUED_MAIL)``. An expectation derived from the
#: corpus it grades agrees with any corpus, including an empty one, and every
#: assertion below turns on this number being non-zero.
EXPECTED_TILE = 6

#: The queue's page for the bound case. Supplied by the test rather than read
#: from ``review_queue_cloud``'s default, which would compare the endpoint's
#: configuration with itself and stay green at every value of it.
QUEUE_PAGE = 3


def _token_for(user_id: str) -> str:
    """A Supabase-shaped HS256 JWT for ``user_id``."""

    now = int(time.time())
    return pyjwt.encode(
        {"sub": user_id, "aud": "authenticated", "iat": now, "exp": now + 300},
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture
async def cloud_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """The cloud app over the in-memory SQLite test DB, auth enabled.

    ``monkeypatch``-on-``settings``, patched on every instance the request path
    holds and de-duplicated by identity — the form
    ``tests/test_no_fixture_reloads_the_config_module.py`` requires and #582
    explains. Patching only ``config_module.settings`` passes this module alone
    and 401s in a full run behind whichever module reloaded config last.
    """

    import jobtracker.auth.supabase_jwt as auth_module
    import jobtracker.config as config_module
    import jobtracker.database.connection as connection_module

    holders = {
        id(module.settings): module.settings
        for module in (config_module, auth_module, connection_module)
    }
    for instance in holders.values():
        monkeypatch.setattr(instance, "environment", "test")
        monkeypatch.setattr(instance, "deployment", "cloud")
        monkeypatch.setattr(instance, "supabase_jwt_secret", JWT_SECRET)

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


@pytest.fixture
def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token_for(OWNER)}"}


@pytest.fixture
async def seeded(cloud_app: Any) -> None:
    """``QUEUED_MAIL`` at ``NEEDS_REVIEW``, unlinked and un-reviewed.

    Written at the session rather than through an endpoint: there is no route
    that mints a queued message, and the queue's own predicate is what is being
    exercised, not the sync that produces one.
    """

    from jobtracker.database import get_session

    owner = uuid.UUID(OWNER)
    async with get_session() as session:
        for index, message_id in enumerate(QUEUED_MAIL):
            session.add(
                Email(
                    user_id=owner,
                    application_id=None,
                    source_account=EmailSource.GMAIL,
                    message_id=message_id,
                    thread_id=f"t-{message_id}",
                    subject="Thanks for applying",
                    sender_name="Careers",
                    sender_email="donotreply@email.careers.example.test",
                    received_at=RECEIVED_AT - timedelta(minutes=index),
                    body_snippet="We have received your application.",
                    classified_as=EmailCategory.NEEDS_REVIEW,
                    classification_confidence=0.80,
                    is_reviewed=False,
                )
            )
        await session.commit()


async def _tile(client: AsyncClient, headers: dict[str, str]) -> int:
    resp = await client.get("/applications/summary", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["needs_review"]


async def _queue_ids(
    client: AsyncClient, headers: dict[str, str], limit: int | None = None
) -> set[str]:
    url = "/applications/review"
    if limit is not None:
        url = f"{url}?limit={limit}"
    resp = await client.get(url, headers=headers)
    assert resp.status_code == 200, resp.text
    return {item["message_id"] for item in resp.json()["items"]}


# =============================================================================
# The positive control — every assertion below reads zero on an empty corpus
# =============================================================================


async def test_the_fixture_is_what_these_tests_assume(client, headers, seeded):
    """Runs first. Without it, a stub that returned nothing would look correct.

    ``test_the_endpoint_counts_through_the_statement_builder`` asserts the tile
    drops to 0. On a corpus that seeded nothing it is already 0 and the stub
    proves nothing at all — `equality-cannot-separate-equal-operands`, in the
    form where both operands are the empty set.
    """

    assert await _tile(client, headers) == EXPECTED_TILE == len(QUEUED_MAIL)
    assert await _queue_ids(client, headers) == set(QUEUED_MAIL)


# =============================================================================
# The endpoint reaches the builder the plan test EXPLAINs
# =============================================================================


async def test_the_endpoint_counts_through_the_statement_builder(
    client, headers, seeded, monkeypatch
):
    """Replace the builder and the tile's number follows it.

    The builder is swapped for one whose statement carries an extra predicate no
    row satisfies. If ``application_summary_cloud`` builds its own ``select()``
    the swap is inert, the tile still reads 6, and this fails — which is the
    only thing that keeps ``test_read_path_indexes_postgres`` measuring a
    statement production actually issues.

    THE CALL COUNT IS ASSERTED TOO, and not as decoration. A stub that is never
    invoked and a stub whose result is discarded both leave the number at 6, but
    they are different defects: the first says the endpoint does not call this
    function, the second says it calls it and ignores it. Reporting which one
    happened is the difference between a red that names the cause and a red that
    only says a number was wrong.

    MUTATION: restore the pre-#827 body of the tile — the inline
    ``select(Email.message_id, ...).where(...)`` — and this fails with
    ``calls == 0`` and ``needs_review == 6``.
    """

    import jobtracker.cloud.applications as applications_module

    calls = 0
    real = applications_module._review_queue_rows_statement

    def _nothing_matches(user_id):
        nonlocal calls
        calls += 1
        return real(user_id).where(Email.message_id == "no-message-has-this-id")

    monkeypatch.setattr(
        applications_module, "_review_queue_rows_statement", _nothing_matches
    )

    assert await _tile(client, headers) == 0
    assert calls == 1, (
        "the summary endpoint did not call `_review_queue_rows_statement` — the "
        "tile is building its own statement again, and the plan test in "
        "`test_read_path_indexes_postgres` is EXPLAINing a statement no request "
        "issues."
    )


async def test_stubbing_the_builder_moves_the_tile_and_nothing_else(
    client, headers, seeded, monkeypatch
):
    """The control varies one thing.

    A stub that broke every read would satisfy the case above without saying
    anything about WHICH reader goes through the builder. ``GET
    /applications/review`` shares the tile's predicate but builds its own
    statement — it has an ``ORDER BY`` and a ``LIMIT`` the tile does not — so it
    must be untouched by the same patch.

    MUTATION: point ``review_queue_cloud`` at the builder as well and this
    fails, the queue coming back empty.
    """

    import jobtracker.cloud.applications as applications_module

    real = applications_module._review_queue_rows_statement
    monkeypatch.setattr(
        applications_module,
        "_review_queue_rows_statement",
        lambda user_id: real(user_id).where(Email.message_id == "no-message-has-this-id"),
    )

    assert await _tile(client, headers) == 0
    assert await _queue_ids(client, headers) == set(QUEUED_MAIL)


# =============================================================================
# The tile counts past what the queue can show — #827's bound question
# =============================================================================


async def test_the_tile_counts_rows_the_queue_page_cannot_show(
    client, headers, seeded
):
    """The tile is unbounded; the queue it links to is not. Measured, not implied.

    ``_not_filed_on_an_application_that_answers`` is shared by both readers so
    they cannot count different SETS, and its docstring says so. They can still
    render different NUMBERS, because only one of them reads the whole set:
    ``review_queue_cloud`` reads at most ``limit`` rows and collapses those,
    while the tile reads every matching row and collapses all of them. Measured
    on Postgres at #827's sizes, the two part company the moment the matching
    rows pass the queue's limit — at 6,000 matching rows the tile said 3,334 and
    the queue could show 56.

    This is the fact that would source a bound if one is ever taken: the honest
    ceiling for this number is the queue's own page, and past it the tile can
    only say "and more", never a cap dressed up as a count.

    ``QUEUE_PAGE`` is the test's parameter and not ``review_queue_cloud``'s
    default. Reading the endpoint's own constant here would compare the
    configuration with itself and pass at every value of it.

    IF THE BOUNDED READ IS EVER BUILT this case changes on purpose: the tile
    would report ``QUEUE_PAGE`` with a "more than this" flag rather than
    ``EXPECTED_TILE``. Changing it then is not the same act as loosening it now,
    and it should not be edited for any other reason.
    """

    assert len(await _queue_ids(client, headers, limit=QUEUE_PAGE)) == QUEUE_PAGE
    assert await _tile(client, headers) == EXPECTED_TILE > QUEUE_PAGE
