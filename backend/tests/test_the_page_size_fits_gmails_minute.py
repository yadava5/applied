"""The scan's page size is an arithmetic result, so it needs an arithmetic gate.

Gmail charges per call, and a page is one `messages.list` plus N
`messages.get`. Throughput is therefore not linear in N — it is

    N * floor(UNITS_PER_MINUTE / (UNITS_PER_GET * N + UNITS_PER_LIST))

a step function whose steps fall in awkward places. The round numbers land
badly: 100 costs 2,005 units so only TWO pages fit a 6,000-unit minute, while
99 costs 1,985 so THREE fit. **Changing the number by one changes throughput by
48%**, and for a 2,000-message scan that is ten minutes against 6.7.

This file exists because that is not visible by reading. `page_size = 100` looks
like the obvious choice and is the one somebody will "tidy" the constant back
to.

The quota constants below are HARD-CODED rather than imported from anything the
application also reads. An expectation taken from the same source as the code
compares a config against itself: it catches drift and passes every edit. These
three numbers were read from this project's own Google Cloud Console and from
Gmail's published quota table on 2026-09-04, and if Google changes them the
right outcome is that this file reds and a human re-derives the constant.
"""

from __future__ import annotations

from jobtracker.config import settings

# Read from Cloud Console (project jobtracker-502918) and Gmail's quota table,
# 2026-09-04. The per-user ceiling was cut 15,000 -> 6,000 and messages.get
# rose 5 -> 20 on 2026-05-01; both halves matter and neither is derivable from
# the codebase.
UNITS_PER_MINUTE = 6000
UNITS_PER_GET = 20
UNITS_PER_LIST = 5

# The handler's own ceiling (`cloud/gmail_oauth.py`), restated rather than
# imported for the reason in the module docstring.
HANDLER_CLAMP = 250


def units_per_page(size: int) -> int:
    return UNITS_PER_GET * size + UNITS_PER_LIST


def messages_per_minute(size: int) -> int:
    """Whole pages only: a page that cannot finish delivers nothing."""

    return size * (UNITS_PER_MINUTE // units_per_page(size))


def test_the_round_number_really_is_worse() -> None:
    """The directional control, and the reason this file exists.

    Without it, every assertion below could be satisfied by a constant chosen
    for any reason at all. This pins the specific trap: that 100 and 150 look
    like sensible page sizes and are markedly worse than a number nobody would
    pick on purpose.
    """

    assert messages_per_minute(99) == 297
    assert messages_per_minute(100) == 200
    assert messages_per_minute(150) == 150

    # One more message per page costs a third of the throughput.
    assert messages_per_minute(100) < messages_per_minute(99) * 0.7


def test_the_configured_page_size_does_not_waste_the_minute() -> None:
    """Within 3% of the best throughput any allowed page size can reach.

    MUST RED ON: `gmail_fetch_page_size` set to 100, 150 or 200.
    """

    best = max(messages_per_minute(n) for n in range(1, HANDLER_CLAMP + 1))
    actual = messages_per_minute(settings.gmail_fetch_page_size)

    assert actual >= best * 0.97, (
        f"page size {settings.gmail_fetch_page_size} delivers {actual} "
        f"messages/minute where {best} is reachable under the clamp. "
        f"Throughput is N * floor({UNITS_PER_MINUTE} / (20N + 5)); the +5 for "
        f"messages.list puts round numbers on the wrong side of a step."
    )


def test_one_page_never_costs_more_than_half_a_minute() -> None:
    """A page must not be able to monopolise the bucket.

    This is what rules out the other end of the curve. 249 also scores well on
    throughput alone (249/min) but costs 4,985 units — five sixths of the whole
    minute in ONE serverless invocation, so a single deferral wastes almost all
    of it and a single page has to finish inside the 60 s function budget with
    249 full message bodies in memory.

    MUST RED ON: raising the page size toward the handler clamp for throughput.
    """

    cost = units_per_page(settings.gmail_fetch_page_size)

    assert cost <= UNITS_PER_MINUTE // 2, (
        f"one page costs {cost} of {UNITS_PER_MINUTE} units per minute; a page "
        f"that large leaves no room for the scheduled sync, and a deferral "
        f"throws away most of the bucket."
    )


def test_the_client_asks_for_the_same_size_the_server_is_tuned_for() -> None:
    """The web mine drives the pace, so its constant must match this one.

    The client loops pages; the server only clamps. If `PAGE_SIZE` in
    `apps/web/lib/gmail/types.ts` drifts to a round number, the server's
    careful default never applies to the interactive scan at all — it is a
    ceiling, not a floor.

    MUST RED ON: either constant moving without the other.
    """

    from pathlib import Path

    types_ts = (
        Path(__file__).resolve().parents[2]
        / "apps"
        / "web"
        / "lib"
        / "gmail"
        / "types.ts"
    )
    if not types_ts.exists():  # pragma: no cover - web tree absent
        return

    import re

    match = re.search(
        r"export const PAGE_SIZE = (\d+);", types_ts.read_text(encoding="utf-8")
    )
    assert match, "PAGE_SIZE is no longer declared where this gate can read it"
    assert int(match.group(1)) == settings.gmail_fetch_page_size
