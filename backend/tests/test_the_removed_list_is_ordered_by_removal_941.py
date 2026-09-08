"""``GET /applications?dismissed=true`` sorts by REMOVAL, not by filing.

Issue #941. The ``dismissed`` flag switched the PREDICATE — ``dismissed_at IS
NOT NULL`` instead of ``IS NULL`` — and nothing about the sort, so the removed
list came back in ``created_at DESC`` order, which for that predicate is close
to arbitrary:

* the undo surface exists for ONE moment, when somebody has just taken the
  wrong row off the board and wants it back. The row they want is the most
  recently DISMISSED and it can sit anywhere in a filed-order list;
* a rebuild purge carries dozens of rows here at once, all still wearing
  whatever ``created_at`` they were filed with, so one Re-sync buries the row
  removed thirty seconds ago;
* paging makes it worse rather than better. Ordering happens before
  ``LIMIT``/``OFFSET``, so a row that sorts late is not merely lower on screen —
  it is behind a request the reader has to think to make.

WHY THE FIXTURE FILES IN ONE ORDER AND DISMISSES IN ANOTHER
------------------------------------------------------------
Because otherwise this module could not fail. If rows are dismissed in the same
sequence they were filed, the two sort keys agree row for row and swapping one
for the other is byte-identical output — the test would pass with the defect
fully present. So the three rows are filed ``old``, ``mid``, ``new`` and
dismissed ``new``, ``old``, ``mid``, which puts the expected answer
(``mid, old, new``) in a different position from the buggy one
(``new, mid, old``) at EVERY index, and :func:`test_the_two_orders_actually_differ`
asserts that separation directly rather than trusting it.

The live board keeps filed order, and that is asserted here too. A change that
reordered both would satisfy the headline assertion while breaking the board.

WHAT THE MUTATIONS SAID, INCLUDING THE ONE THAT SURVIVED
---------------------------------------------------------
Three arms, each run with the file's sha printed before and after so a mutation
that silently no-ops cannot read as a surviving gate:

===============================================  ==========================
mutation                                          result
===============================================  ==========================
revert to ``created_at`` for both predicates       3 red (the removed tests)
``dismissed_at`` for both predicates               **0 red**
``.asc()`` instead of ``.desc()``                  4 red, board control among
                                                   them
===============================================  ==========================

The middle arm survived, and it is worth reading why, because "a mutation
survived" normally means the control is broken. Here it means the mutant is
**equivalent on that surface**. On the live predicate every row has
``dismissed_at IS NULL``, so ``ORDER BY dismissed_at DESC, id DESC`` degenerates
to ``id DESC`` — and ``id`` is a monotonic integer primary key assigned in the
same order ``created_at`` is stamped, so it reproduces filed order exactly. Not
argued: the two live-board responses were captured and compared and are
byte-identical, ``[[5, Elmridge], [4, Dunmore Ltd], [3, Cedar Works],
[2, Bracken Labs]]`` under both.

No fixture can separate an equivalent mutant, which is why the third arm is
here: it establishes that the board control can fail at all, and it is the arm
that would catch a real reordering of the board.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

JWT_SECRET = "removed-order-941-test-jwt-secret-at-least-32-bytes-long-hs256"
USER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _token_for(user_id: str) -> str:
    """Minted PER CALL, never at import.

    #942 is the module that mints one at import time and then passes only while
    the suite is fast enough to reach it before the 300 seconds run out.
    """

    now = int(time.time())
    return pyjwt.encode(
        {"sub": user_id, "aud": "authenticated", "iat": now, "exp": now + 300},
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture
async def cloud_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """The cloud app on in-memory SQLite with auth on.

    Patches attributes on the ``settings`` SINGLETON rather than reloading
    ``jobtracker.config``: a reload mints a new instance while every
    ``from jobtracker.config import settings`` binding still points at the old
    one, and the JWT secret then outlives the fixture that set it. See
    ``test_application_create_is_bounded.py``, where that trap turned six tests
    red purely through collection order.
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


#: Filed oldest to newest. The labels are the filing order and are used below to
#: talk about rows without depending on their ids.
FILED = ("Alder Systems", "Bracken Labs", "Cedar Works")

#: Dismissed in a DELIBERATELY different order — newest, then oldest, then the
#: middle one. See the module docstring.
DISMISS_ORDER = ("Cedar Works", "Alder Systems", "Bracken Labs")

#: What the removed list must return: most recently dismissed first.
BY_REMOVAL = ("Bracken Labs", "Alder Systems", "Cedar Works")

#: What it returned before #941 — the board's order, on the wrong predicate.
BY_FILING = ("Cedar Works", "Bracken Labs", "Alder Systems")


async def _file_three(client: AsyncClient) -> dict[str, str]:
    """File the three rows in ``FILED`` order and return company -> id."""

    ids: dict[str, str] = {}
    for company in FILED:
        resp = await client.post(
            "/applications",
            headers=_headers(),
            json={"company": company, "position": "Backend Engineer"},
        )
        assert resp.status_code == 201, resp.text
        ids[company] = resp.json()["id"]
    return ids


async def _dismiss_all(client: AsyncClient, ids: dict[str, str]) -> None:
    for company in DISMISS_ORDER:
        resp = await client.post(
            f"/applications/{ids[company]}/dismiss", headers=_headers()
        )
        assert resp.status_code == 200, resp.text


async def _removed(client: AsyncClient, **params: Any) -> list[dict[str, Any]]:
    query = "&".join(f"{k}={v}" for k, v in {"dismissed": "true", **params}.items())
    resp = await client.get(f"/applications?{query}", headers=_headers())
    assert resp.status_code == 200, resp.text
    return resp.json()["applications"]


def test_the_two_orders_actually_differ() -> None:
    """THE PREMISE, asserted rather than assumed.

    If filing order and removal order agreed, every assertion in this module
    would hold with the defect fully present. They must disagree at every
    index, so that reading the wrong column cannot produce the right answer by
    coincidence at any position.
    """

    assert set(BY_REMOVAL) == set(BY_FILING) == set(FILED)
    assert all(a != b for a, b in zip(BY_REMOVAL, BY_FILING, strict=True)), (
        BY_REMOVAL,
        BY_FILING,
    )


async def test_the_removed_list_leads_with_the_most_recently_removed(
    client: AsyncClient,
) -> None:
    """The headline. The row somebody just took off the board is first."""

    ids = await _file_three(client)
    await _dismiss_all(client, ids)

    rows = await _removed(client)
    assert [r["company"] for r in rows] == list(BY_REMOVAL)

    # And it is genuinely sorted on the column, not merely reversed: the
    # timestamps come back in descending order too.
    stamps = [r["dismissed_at"] for r in rows]
    assert all(s is not None for s in stamps), stamps
    assert stamps == sorted(stamps, reverse=True), stamps


async def test_the_live_board_still_leads_with_the_most_recently_filed(
    client: AsyncClient,
) -> None:
    """THE DIRECTIONAL CONTROL.

    A change that swapped the sort for BOTH predicates would satisfy the test
    above and break the board, whose filed order has been right since the
    beginning and which a partial index is built for.
    """

    ids = await _file_three(client)
    await _dismiss_all(client, ids)
    # Put one back, so the live predicate has something to return and the
    # assertion is about ordering rather than about an empty list.
    for company in FILED:
        resp = await client.post(
            f"/applications/{ids[company]}/restore", headers=_headers()
        )
        assert resp.status_code == 200, resp.text

    resp = await client.get("/applications", headers=_headers())
    assert resp.status_code == 200, resp.text
    assert [r["company"] for r in resp.json()["applications"]] == list(BY_FILING)


async def test_the_ordering_is_applied_before_the_page_is_cut(
    client: AsyncClient,
) -> None:
    """Paging is where the defect actually bites.

    A row that sorts late is not merely lower on screen — it is behind a second
    request. So the first page must hold the two most recently removed rows,
    not whichever two happen to be newest by filing.
    """

    ids = await _file_three(client)
    await _dismiss_all(client, ids)

    first = await _removed(client, page_size=2, page=1)
    second = await _removed(client, page_size=2, page=2)

    assert [r["company"] for r in first] == list(BY_REMOVAL[:2])
    assert [r["company"] for r in second] == list(BY_REMOVAL[2:])
    # The row the reader wants is on page one. Under filing order it was not.
    assert BY_REMOVAL[0] not in [r["company"] for r in second]


async def test_a_row_dismissed_last_beats_a_row_filed_last(
    client: AsyncClient,
) -> None:
    """The Re-sync shape, reduced to two rows and stated as the user sees it.

    A purge removes an old row; the user then removes today's row by hand. The
    hand-removed row is the one they will want back, and it is the one filing
    order puts first ONLY BY ACCIDENT here — so this case pins the pair whose
    relative order the two sort keys disagree about.
    """

    ids = await _file_three(client)
    # Remove the NEWEST-filed row first, then the OLDEST. Filing order would
    # lead with the newest; removal order must lead with the oldest.
    for company in ("Cedar Works", "Alder Systems"):
        resp = await client.post(
            f"/applications/{ids[company]}/dismiss", headers=_headers()
        )
        assert resp.status_code == 200, resp.text

    rows = await _removed(client)
    assert [r["company"] for r in rows] == ["Alder Systems", "Cedar Works"]
