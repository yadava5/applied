/**
 * The header's this-week correction, ASSERTED BY EXECUTION end to end (#518).
 *
 * `reader-week.test.mjs` covers the decision — `summaryWeekCorrection`, a pure
 * function — and covers it well. What it could not cover is the DELIVERY: that
 * the decision is fed the reader's day rather than the server's, that the
 * request is actually issued, that the answer reaches the rendered line, and
 * that the query parameter survives the same-origin proxy. Those four steps
 * were gated by `source.includes(...)` scans, and a scan cannot see the one
 * mutation that matters here — an argument replaced by another of the same
 * type. Three of them, each restoring #518 fully or in part, were green across
 * the whole 625-test suite:
 *
 *   1. `summaryWeekCorrection(readerToday, servedWeekStart)`
 *      -> `summaryWeekCorrection(servedWeekStart, servedWeekStart)`
 *      `wanted` is permanently null, nothing is ever requested, the header
 *      keeps the UTC count. #518, entirely back. Both scanned substrings
 *      survive it.
 *   2. `corrected.thisWeek` -> `summary.thisWeek` in the render. The
 *      correction is requested, parsed, validated and stored — and discarded.
 *   3. `query: weekStart === null ? {} : { week_start: weekStart }` -> `{}`
 *      in `app/api/applications/summary/route.ts`. The browser asks for its
 *      own Monday and the backend is asked for the server's.
 *
 * Each test below names the mutation it reds on. All three are red now.
 *
 * HOW A CLIENT COMPONENT RUNS UNDER `node --test`. `helpers/clientHarness.mjs`
 * substitutes React's `useState`/`useEffect` for a small dispatcher and drives
 * the render/effect/re-render cycle by hand; its docstring states exactly what
 * that is and is not. The component's own body is the real one and really
 * runs, which is the entire point — the swapped argument is *executed* here,
 * not read.
 *
 * THE TWO CONTROLS THIS FILE CANNOT DO WITHOUT. A dead harness (effects never
 * fire) would red the "the corrected number arrives" test, which announces
 * itself — but it would make "no request outside the window" pass for the
 * wrong reason. So the request count is asserted on both sides: exactly one
 * inside the window, exactly zero outside it. And `useLocalToday` is a
 * recording stub, so a component that stopped reading the reader's clock at
 * all reds on a call count rather than on a substring.
 *
 * NO CLOCK IS READ HERE and no zone is assumed: the two day strings are the
 * literals a New York browser and a UTC server hold at 2026-08-31T00:30:00Z.
 * That `localTodayISO` really returns the reader's day is `local-today.test.mjs`'s
 * job, under four zones.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import { createClientHarness, recordingFetch } from "./helpers/clientHarness.mjs";
import { importTsx, stubModule } from "./helpers/renderTsx.mjs";

/** Sunday 20:30 in Eastern — the reader is still in the 30th… */
const READER_TODAY = "2026-08-30";
/** …while UTC has been in Monday the 31st for half an hour, so that is the
 *  Monday the server-rendered header counted from. */
const SERVED_WEEK_START = "2026-08-31";
/** The reader's own Monday, and the only week they should be asked about. */
const READER_WEEK_START = "2026-08-24";
const CORRECTED_URL = `/api/applications/summary?week_start=${READER_WEEK_START}`;

/** The board as the server rendered it: the UTC week has just begun, so the
 *  ` · +N this wk` segment is omitted entirely at zero. */
const SERVED_SUMMARY = {
  total: 50,
  thisWeek: 0,
  inMotion: 38,
  offers: 1,
  closed: 11,
  advancedPct: 24,
  stages: [],
};

const UNCORRECTED_LINE = "50 filed · 38 open · 1 offer";
const CORRECTED_LINE = "50 filed · +12 this wk · 38 open · 1 offer";

/**
 * Mount `BoardSubtitle` with a recorded clock and a recorded `fetch`, run it to
 * a settled state, and hand back everything the assertions need.
 *
 * `useLocalToday` is stubbed rather than left real because the real one reads
 * the machine's clock — which would make every assertion below depend on the
 * day the suite runs. `local-today.test.mjs` is what holds that hook honest.
 * The stub COUNTS its calls, so "the component stopped asking the reader what
 * day it is" is a behavioural failure here and not a missing substring.
 */
async function mount({ readerToday = READER_TODAY, weekly = true, routes } = {}) {
  const harness = createClientHarness();
  const fetcher = recordingFetch(
    routes ?? { [CORRECTED_URL]: { this_week: 12, week_start: READER_WEEK_START } },
  );
  const clock = { calls: 0 };

  const { BoardSubtitle } = await importTsx("components/dashboard/BoardSubtitle.tsx", {
    stubs: {
      react: stubModule(harness.reactStub),
      "@/lib/dashboard/useLocalToday": stubModule({
        useLocalToday: () => {
          clock.calls += 1;
          return readerToday;
        },
      }),
    },
  });

  const realFetch = globalThis.fetch;
  globalThis.fetch = fetcher.impl;
  try {
    const settled = await harness.settle(BoardSubtitle, {
      summary: SERVED_SUMMARY,
      weekly,
      servedWeekStart: SERVED_WEEK_START,
    });
    return { ...settled, calls: fetcher.calls, clock, harness };
  } finally {
    globalThis.fetch = realFetch;
    harness.unmount();
  }
}

// ---------------------------------------------------------------------------
// Inside the offset window: the request is made, and its answer is rendered
// ---------------------------------------------------------------------------

test("the header asks the endpoint for the READER's Monday, exactly once", async () => {
  // RED WHEN: `summaryWeekCorrection` is fed `servedWeekStart` as its first
  // argument instead of the reader's day (mutation 1) — `wanted` is null and
  // nothing is requested at all.
  const { calls, clock } = await mount();

  assert.ok(clock.calls > 0, "BoardSubtitle never read the reader's day — the clock is the bug");
  assert.equal(calls.length, 1, "exactly one correction request");
  assert.equal(calls[0].url, CORRECTED_URL);
  assert.equal(
    new URL(calls[0].url, "http://x").searchParams.get("week_start"),
    READER_WEEK_START,
    "the week asked about is not the reader's Monday",
  );
});

test("the corrected count is the one the line renders", async () => {
  // RED WHEN: the render reads `summary.thisWeek` instead of `corrected.thisWeek`
  // (mutation 2) — the answer is fetched, validated, stored and then dropped.
  //
  // The segment is ABSENT before the correction and PRESENT after it, because
  // `buildSubtitle` omits ` · +N this wk` at zero. So this asserts the whole
  // line both ways rather than a digit: a mutation that keeps the served value
  // cannot produce the corrected string by accident.
  const { text, passes } = await mount();

  assert.equal(text, CORRECTED_LINE);
  assert.ok(passes >= 2, "the component never re-rendered, so nothing could have been corrected");
  assert.notEqual(text, UNCORRECTED_LINE);
});

// ---------------------------------------------------------------------------
// The zero-call side — without which the tests above could pass on a dead
// harness that never runs an effect
// ---------------------------------------------------------------------------

test("no request at all when the server already counted the reader's week", async () => {
  // The common case: every hour of the week outside the offset window. Nothing
  // is fetched and the served line is what stays on screen.
  const { text, calls } = await mount({ readerToday: SERVED_WEEK_START });

  assert.equal(calls.length, 0);
  assert.equal(text, UNCORRECTED_LINE);
});

test("the weekly pref gates the request, not just the segment", async () => {
  // A line that has been told not to print `+N this wk` must not pay for a
  // round trip nobody can see.
  const { text, calls } = await mount({ weekly: false });

  assert.equal(calls.length, 0);
  assert.equal(text, UNCORRECTED_LINE);
});

// ---------------------------------------------------------------------------
// Every failure keeps the honest number already on screen
// ---------------------------------------------------------------------------

test("an answer about a DIFFERENT Monday is refused, not adopted", async () => {
  // RED WHEN: the `countedFrom !== wanted` guard is dropped. A cache, or a
  // retry that crossed midnight, can answer a question other than the one
  // asked; adopting it would put a number from some other week in the header.
  const { text, calls } = await mount({
    routes: { [CORRECTED_URL]: { this_week: 12, week_start: SERVED_WEEK_START } },
  });

  assert.equal(calls.length, 1, "the request was still made");
  assert.equal(text, UNCORRECTED_LINE);
});

test("a refusal or an unreachable backend leaves the served count alone", async () => {
  // No route registered -> 404. `res.ok` is false and the served answer stands.
  const { text, calls } = await mount({ routes: {} });

  assert.equal(calls.length, 1);
  assert.equal(text, UNCORRECTED_LINE);
});

// ---------------------------------------------------------------------------
// The proxy the request goes through
// ---------------------------------------------------------------------------

/**
 * Execute `app/api/applications/summary/route.ts` with a recording API client
 * in place of the real one, and hand back what it asked the backend for.
 *
 * Only `@/lib/api/server` is substituted — it is the module that reaches for
 * `next/headers` and a Supabase session, neither of which exists outside a
 * request. `next/server` and `@/lib/api/serverTiming` are the real ones, so the
 * status and the body this returns are the handler's own.
 */
async function callSummaryRoute(url, backend = { this_week: 12, week_start: READER_WEEK_START }) {
  const asked = [];
  const { GET } = await importTsx("app/api/applications/summary/route.ts", {
    stubs: {
      "@/lib/api/server": stubModule({
        createServerApiClient: async () => ({
          GET: async (path, init) => {
            asked.push({ path, init });
            return {
              data: backend,
              error: undefined,
              response: new Response(null, { status: 200 }),
            };
          },
        }),
      }),
    },
  });

  const response = await GET(new Request(`http://localhost${url}`));
  return { asked, response, body: await response.json() };
}

test("the proxy forwards week_start to the backend", async () => {
  // RED WHEN: the handler sends `query: {}` unconditionally (mutation 3) — the
  // browser asks about its own Monday and the backend is asked about the
  // server's, so the corrected answer is the uncorrected one and the client's
  // `countedFrom !== wanted` guard then throws it away. #518 survives the whole
  // round trip.
  const { asked, response, body } = await callSummaryRoute(CORRECTED_URL);

  assert.equal(asked.length, 1, "the backend was not called");
  assert.equal(asked[0].path, "/applications/summary");
  assert.deepEqual(
    asked[0].init.params.query,
    { week_start: READER_WEEK_START },
    "the reader's Monday did not reach the backend",
  );
  assert.equal(response.status, 200);
  assert.equal(body.week_start, READER_WEEK_START);
});

test("no parameter is sent when the caller supplied none", async () => {
  // The server-render path. An empty `week_start=` must not be invented, or
  // every SSR pass would 422 against `_reader_week_start`.
  const { asked } = await callSummaryRoute("/api/applications/summary");

  assert.equal(asked.length, 1);
  assert.deepEqual(asked[0].init.params.query, {});
});

test("a backend refusal is passed through rather than masked", async () => {
  const asked = [];
  const { GET } = await importTsx("app/api/applications/summary/route.ts", {
    stubs: {
      "@/lib/api/server": stubModule({
        createServerApiClient: async () => ({
          GET: async (path, init) => {
            asked.push({ path, init });
            return {
              data: undefined,
              error: { detail: "week_start must be a Monday" },
              response: new Response(null, { status: 422 }),
            };
          },
        }),
      }),
    },
  });

  const response = await GET(
    new Request("http://localhost/api/applications/summary?week_start=2026-08-25"),
  );

  assert.equal(asked.length, 1);
  assert.equal(response.status, 422, "a 422 must not be laundered into a 200 or a 502");
});
