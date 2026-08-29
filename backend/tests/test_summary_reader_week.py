""""This week" is the READER's week, not the server's (#518).

THE DEFECT. Two surfaces render the same number and they did not share a clock.
The header (``50 filed · +N this wk``) came from this endpoint, counted from
``_week_start(datetime.utcnow().date())`` — a UTC Monday. The momentum caption
beside it (``N this wk · up from M by now``) is computed in the browser from
``useLocalToday()`` — the reader's Monday — deliberately, because the bars next
to the caption bucket on the reader's day and the panel has to agree with
itself.

So for a reader west of UTC there was a window each week the size of their
offset — Sunday 20:00 to midnight in Eastern — where the header had rolled into
the new week and the caption had not. The header read ~0 while the caption
still reported all of last week. Every fixture below is frozen inside that
window; a test written against the real clock would agree with the old code six
days out of seven and only discriminate on the seventh, which is the flake
shape this repo has a scar from.

THE FIX IS A PARAMETER, and this file is where its contract is stated as
behaviour: what ``?week_start=`` accepts, what it refuses, and what the two
bounds of the counted window actually are. ``test_this_week_is_a_calendar_week``
pins WHERE a week begins against the table the web suite shares; this pins
WHOSE week is counted.

WHY THE REFUSALS GET AS MUCH ROOM AS THE HAPPY PATH. This is a client-supplied
date on a query string that decides which rows an account is told about. A
malformed value, a value that is not a Monday and a value naming a week no
reader can be standing in are each a defined answer (422) rather than a
best-effort guess, and each is asserted — including the one that is easiest to
get wrong by kindness, snapping a non-Monday to the nearest Monday.
"""

from __future__ import annotations

import importlib
import time
from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta
from typing import Any

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

JWT_SECRET = "reader-week-test-jwt-secret-at-least-32-bytes-long-hs256"
USER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _token_for(user_id: str) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {"sub": user_id, "aud": "authenticated", "iat": now, "exp": now + 300},
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture
async def cloud_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """Cloud app on the in-memory DB.

    THE SETTINGS ARE PATCHED, NOT RELOADED (#582). ``importlib.reload`` on
    ``jobtracker.config`` rebuilds the ``Settings`` class and rebinds
    ``config.settings`` to a NEW instance; every module that did
    ``from jobtracker.config import settings`` at import time keeps the old one.
    The process then holds two settings objects, the JWT verifier reads the one
    this fixture never touched, and every request here comes back
    ``401 Invalid signature`` — green when this module runs alone, red in a full
    run behind whichever module reloaded config last.
    ``tests/test_no_fixture_reloads_the_config_module.py`` forbids the
    mechanism; this is the replacement it names.

    Every settings holder the request path carries, de-duplicated BY OBJECT
    IDENTITY: patching ``config_module.settings`` alone passes this module in
    isolation and fails it in a full run. The env vars are still set because the
    three modules reloaded below re-run their import-time wiring, and that
    wiring reads the environment as well as ``settings``.

    The reloads of ``auth``, ``cloud.applications`` and ``main_cloud`` STAY.
    They are what rebuilds the router this test drives and none of them mints a
    second ``Settings`` — the gate forbids reloading ``jobtracker.config``
    specifically, not ``importlib.reload``.
    """

    monkeypatch.setenv("JOBTRACKER_DEPLOYMENT", "cloud")
    monkeypatch.setenv("JOBTRACKER_ENVIRONMENT", "test")
    monkeypatch.setenv("JOBTRACKER_SUPABASE_JWT_SECRET", JWT_SECRET)

    import jobtracker.auth.supabase_jwt as auth_module
    import jobtracker.config as config_module
    import jobtracker.database.connection as connection_module

    holders = {
        id(module.settings): module.settings
        for module in (config_module, auth_module, connection_module)
    }
    for instance in holders.values():
        monkeypatch.setattr(instance, "deployment", "cloud")
        monkeypatch.setattr(instance, "environment", "test")
        monkeypatch.setattr(instance, "supabase_jwt_secret", JWT_SECRET)

    connection_module._engine = None

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

    # No teardown reload. ``monkeypatch`` undoes each attribute write exactly,
    # on the same objects it wrote them to, which the old
    # ``undo() + reload(config)`` never did — that second reload minted a THIRD
    # ``Settings`` rather than restoring the first.


@pytest.fixture
async def client(cloud_app: Any) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=cloud_app)
    async with AsyncClient(transport=transport, base_url="http://cloud-test") as c:
        yield c


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token_for(USER_A)}"}


def _freeze(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> None:
    """Pin ``datetime.utcnow()`` inside the applications module.

    The fixture above reloads that module, so this has to run after the client
    fixture has been built or the patch lands on an object no route is using.
    """

    import jobtracker.cloud.applications as applications_module

    class _FrozenDatetime(datetime):
        @classmethod
        def utcnow(cls) -> datetime:  # type: ignore[override]
            return moment

    monkeypatch.setattr(applications_module, "datetime", _FrozenDatetime)


async def _file(client: AsyncClient, company: str, applied: str) -> None:
    resp = await client.post(
        "/applications",
        json={
            "company": company,
            "position": "SWE",
            "status": "applied",
            "applied_date": applied,
        },
        headers=_headers(),
    )
    assert resp.status_code == 201, resp.text


async def _summary(client: AsyncClient, week_start: str | None = None) -> Any:
    url = "/applications/summary"
    if week_start is not None:
        url = f"{url}?week_start={week_start}"
    return await client.get(url, headers=_headers())


# =============================================================================
# The window this defect lives in
# =============================================================================

#: 2026-08-31T00:30:00Z is Sunday 2026-08-30, 20:30 in New York. The server's
#: Monday is the 31st; the reader's is the 24th. This single instant is the bug.
WEST_MOMENT = datetime(2026, 8, 31, 0, 30, 0)
WEST_SERVER_MONDAY = "2026-08-31"
WEST_READER_MONDAY = "2026-08-24"

#: 2026-08-30T23:30:00Z is Monday 2026-08-31, 08:30 in Tokyo — the mirror. The
#: reader's Monday is AHEAD of the server's, which is the direction that turns a
#: seven-day week into an eight-day one if the far bound is not held.
EAST_MOMENT = datetime(2026, 8, 30, 23, 30, 0)
EAST_READER_MONDAY = "2026-08-31"


async def test_without_the_parameter_the_answer_is_still_the_utc_week(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SSR renders this, so it must not have moved.

    The server does not know the reader's zone at first paint, and a server
    render that guessed one would hydrate into a text mismatch. So the
    parameterless answer is exactly what it was before #518 — the UTC Monday —
    and the response now says which Monday that was.
    """

    _freeze(monkeypatch, WEST_MOMENT)
    for company, applied in (
        ("Tuesday Co", "2026-08-25"),
        ("Thursday Co", "2026-08-27"),
        ("Sunday Co", "2026-08-30"),
    ):
        await _file(client, company, applied)

    body = (await _summary(client)).json()

    assert body["week_start"] == WEST_SERVER_MONDAY
    assert body["this_week"] == 0, (
        "the un-parameterised count is no longer the UTC week — this is the "
        "number every server render ships, and changing it is a hydration "
        "mismatch waiting to happen"
    )
    assert body["total"] == 3


async def test_the_readers_monday_counts_the_readers_week(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE FIX, as the reader experiences it.

    At this instant the header used to read 0 while the momentum caption beside
    it read 3 — a whole week's filings, present in the picture and absent from
    the line above it. Asking for the reader's Monday returns the caption's
    number.
    """

    _freeze(monkeypatch, WEST_MOMENT)
    for company, applied in (
        ("Tuesday Co", "2026-08-25"),
        ("Thursday Co", "2026-08-27"),
        ("Sunday Co", "2026-08-30"),
    ):
        await _file(client, company, applied)

    body = (await _summary(client, WEST_READER_MONDAY)).json()

    assert body["week_start"] == WEST_READER_MONDAY, (
        "the response must name the Monday it actually counted, or the client "
        "cannot tell a corrected answer from an uncorrected one"
    )
    assert body["this_week"] == 3, (
        "the reader's week was not counted — the parameter is being ignored, "
        f"which is exactly the pre-#518 behaviour (got {body['this_week']})"
    )


async def test_the_readers_week_runs_neither_backwards_nor_forwards(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seven days, and only the reader's seven.

    Two rows sit one day outside the requested week on either side, and both
    are days the naive implementations reach:

    * 2026-08-23 is the Sunday BEFORE the reader's Monday — inside any trailing
      seven-day window, outside this calendar week.
    * 2026-08-31 is the server's own today and the reader's TOMORROW. Bounding
      the window at ``now.date()`` alone would count it into a week the reader
      has not reached; the momentum caption drops it (a negative age), so
      counting it here would re-open the disagreement this parameter closes.
    """

    _freeze(monkeypatch, WEST_MOMENT)
    for company, applied in (
        ("Sunday Before", "2026-08-23"),
        ("Monday Co", "2026-08-24"),
        ("Sunday Co", "2026-08-30"),
        ("Server Today", "2026-08-31"),
    ):
        await _file(client, company, applied)

    body = (await _summary(client, WEST_READER_MONDAY)).json()

    assert body["total"] == 4
    assert body["this_week"] == 2, (
        "the counted window is not exactly [Monday, Monday+6] — it picked up "
        "the Sunday before it, the server's own today, or both"
    )


async def test_a_reader_ahead_of_the_server_is_not_given_eight_days(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mirror image, east of UTC.

    In Tokyo's Monday morning the reader's week has begun and the server's has
    not. The rows below are all in the server's current (previous) week, and
    none of them is in the reader's. An implementation that kept
    ``applied_date <= now.date()`` as its only far bound would still count them
    and report a brand-new week as though it already held five days of work.
    """

    _freeze(monkeypatch, EAST_MOMENT)
    for company, applied in (
        ("Tuesday Co", "2026-08-25"),
        ("Thursday Co", "2026-08-27"),
        ("Sunday Co", "2026-08-30"),
    ):
        await _file(client, company, applied)

    body = (await _summary(client, EAST_READER_MONDAY)).json()

    assert body["week_start"] == EAST_READER_MONDAY
    assert body["this_week"] == 0, (
        "last week's rows were counted into the reader's new week — the far "
        "bound of the window is not the week's own edge"
    )


# =============================================================================
# What the parameter refuses, and why it refuses rather than repairs
# =============================================================================


@pytest.mark.parametrize(
    "value",
    [
        "not-a-date",
        "",
        "2026-8-24",
        "20260824",
        "2026-W35-1",
        "2026-08-24T00:00:00",
        "2026-08-24Z",
        "monday",
        "2026-08-24; DROP TABLE applications",
    ],
)
async def test_a_value_that_is_not_YYYY_MM_DD_is_refused(
    client: AsyncClient, value: str
) -> None:
    """ONE spelling on the wire.

    Both of the obvious parsers are laxer than that and were measured to be:
    ``date.fromisoformat`` on 3.11 accepts ``20260824`` and ``2026-W35-1``,
    and pydantic's ``date`` accepts ``2026-08-24T00:00:00``. A parameter the
    client generates from one function has no reason to admit five spellings,
    and every extra spelling is one more thing the two sides can format
    differently while both believing they agree.
    """

    resp = await _summary(client, value)
    assert resp.status_code == 422, resp.text


async def test_a_date_shaped_string_that_is_not_a_day_is_refused(
    client: AsyncClient,
) -> None:
    """``2026-02-30`` satisfies the pattern and is not a date.

    The pattern is a shape check; this is the reason the parse behind it is not
    redundant. Without it the value reaches ``date.fromisoformat`` inside the
    handler and raises a bare ``ValueError``, which is a 500.
    """

    resp = await _summary(client, "2026-02-30")
    assert resp.status_code == 422, resp.text


async def test_a_non_monday_is_refused_and_never_snapped(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The kind failure mode, refused on purpose.

    Snapping 2026-08-26 to 2026-08-24 would return a count for a week the
    caller did not ask about, which the client would then render as though it
    had. The parameter is machine-generated from the reader's clock, so a
    non-Monday means the caller is broken — and a 422 leaves the already
    rendered UTC answer on screen, which is the safe fallback.
    """

    _freeze(monkeypatch, WEST_MOMENT)
    for company, applied in (
        ("Tuesday Co", "2026-08-25"),
        ("Thursday Co", "2026-08-27"),
        ("Sunday Co", "2026-08-30"),
    ):
        await _file(client, company, applied)

    resp = await _summary(client, "2026-08-26")  # a Wednesday, inside the week
    assert resp.status_code == 422, (
        "a non-Monday was accepted — if it was snapped to 2026-08-24 the body "
        f"will read this_week 3: {resp.text}"
    )
    assert "Monday" in resp.json()["detail"]


@pytest.mark.parametrize(
    ("label", "value"),
    [
        ("two weeks back", "2026-08-17"),
        ("a month back", "2026-08-03"),
        ("two weeks on", "2026-09-14"),
        ("a year on", "2027-08-30"),
        ("a decade back", "2016-08-29"),
    ],
)
async def test_a_monday_no_reader_can_be_standing_in_is_refused(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, label: str, value: str
) -> None:
    """The bound is derived, not chosen.

    UTC offsets run from -12 to +14, so a browser's local day is at most one
    day either side of the UTC day and its Monday is therefore the server's
    Monday, the one before it or the one after it. Anything past that is a
    caller whose clock is wrong or a request no browser made, and an endpoint
    that answered it would let a query string ask this account about any week
    in its history.
    """

    _freeze(monkeypatch, WEST_MOMENT)
    resp = await _summary(client, value)
    assert resp.status_code == 422, f"{label} was accepted: {resp.text}"


@pytest.mark.parametrize(
    ("label", "value"),
    [
        ("the Monday before the server's", "2026-08-24"),
        ("the server's own Monday", "2026-08-31"),
        ("the Monday after the server's", "2026-09-07"),
    ],
)
async def test_the_three_mondays_a_real_reader_can_send_are_accepted(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, label: str, value: str
) -> None:
    """Both edges of the bound are exercised, not just its middle.

    A range check tested only at its centre passes whatever the limits are. The
    two outer rows here sit exactly ON the limit — seven days either side — and
    are the values a genuine reader in Honolulu and in Kiritimati send.
    """

    _freeze(monkeypatch, WEST_MOMENT)
    resp = await _summary(client, value)
    assert resp.status_code == 200, f"{label} was refused: {resp.text}"
    assert resp.json()["week_start"] == value


async def test_a_refusal_leaves_the_account_readable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rejected parameter is not a broken dashboard.

    The client's correction is an enhancement over an answer already on screen,
    so the failure mode of every refusal above has to be "the header keeps the
    UTC number", not "the header breaks". The same request without the
    parameter still works, which is what the client falls back to.
    """

    _freeze(monkeypatch, WEST_MOMENT)
    await _file(client, "Sunday Co", "2026-08-30")

    assert (await _summary(client, "2026-08-26")).status_code == 422
    ok = await _summary(client)
    assert ok.status_code == 200
    assert ok.json()["week_start"] == WEST_SERVER_MONDAY


# =============================================================================
# The bound, as arithmetic
# =============================================================================


def test_the_slack_is_exactly_one_day_of_zone_either_side() -> None:
    """Why seven, stated as the derivation rather than as the number.

    ``_WEEK_START_SLACK_DAYS`` is not a comfort margin. A local day one day
    either side of the UTC day moves the Monday by a whole week or not at all,
    so the reachable set has exactly three members and the widest gap in it is
    seven days. This asserts that, so lowering the constant to 1 (which looks
    reasonable) or raising it to 30 (which looks harmless) fails here.
    """

    from jobtracker.cloud.applications import _WEEK_START_SLACK_DAYS, _week_start

    # Every Monday a real browser can send the server, over a full year of
    # server days: the Monday of the UTC day, and of the day either side of it.
    distances = [
        abs(
            (
                _week_start(day + timedelta(days=shift))
                - _week_start(day)
            ).days
        )
        for offset in range(0, 371)
        for day in [date(2026, 1, 1) + timedelta(days=offset)]
        for shift in (-1, 0, 1)
    ]

    # ADMITS EVERY ONE OF THEM. Lowering the constant starts refusing readers
    # in real timezones — at 6 it refuses everyone in the offset window, which
    # is the only window this parameter exists for.
    assert max(distances) <= _WEEK_START_SLACK_DAYS

    # …AND NOT ONE DAY MORE. Written as equality rather than an upper bound
    # because a bound alone passes for any larger number, and "30 looks
    # harmless" is how a range check becomes a way to ask this account about
    # any week in its history. Mutation-checked: 1, 6, 8 and 14 all red here.
    assert max(distances) == _WEEK_START_SLACK_DAYS
