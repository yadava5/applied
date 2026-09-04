/**
 * Does the deferral countdown actually count? (#750)
 *
 * The line reads `Gmail asked us to slow down · resuming in 59s`. It shipped
 * with the number computed ONCE, on entering the wait, and rendered straight
 * out of state — so over a wait of up to a minute it never moved.
 *
 * WHY A PRESENCE ASSERTION WOULD NOT HAVE CAUGHT IT, which is the whole reason
 * this file exists rather than a cheaper one. "the deferral line is rendered"
 * and "the deferral line contains a number" are both TRUE of the frozen
 * version. The only property that separates the two versions is that the
 * number is SMALLER the second time you look, so that is what is asserted,
 * with two samples and a real second of wall clock between them.
 *
 * WHY NOT PLAYWRIGHT. The only surface that mounts this component over a live
 * mailbox is the signed-in `/inbox`, and every session-gated e2e test in this
 * repo skips — both e2e jobs boot against a placeholder Supabase project. A
 * gate there would be dead coverage wearing a green tick. `mountApp.mjs` makes
 * the same argument at greater length and it applies unchanged here.
 *
 * WHAT IS REAL: the component, its transport, its timers, and the arithmetic.
 * `fetch` is stubbed to refuse with 429 + `Retry-After`, which is exactly what
 * `lib/gmail/transport.ts:104-113` reads, so the deferral this drives is the
 * production one and not a test-only branch.
 */
import assert from "node:assert/strict";
import test from "node:test";

import { React, importApp, mount } from "./helpers/mountApp.mjs";

const { InboxWorkbench } = await importApp("components/gmail/InboxWorkbench.tsx");

/** Seconds read out of the rendered line, or null if the line is not up. */
function secondsOnScreen(view) {
  const m = /resuming in (\d+)s/.exec(view.html());
  return m ? Number(m[1]) : null;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

test("the deferral countdown decreases while the wait is running", async () => {
  const realFetch = globalThis.fetch;
  let calls = 0;

  // Every page refused, with a wait long enough to sample twice inside it and
  // short enough not to hold the suite. 8s clears MIN_DEFERRAL_WAIT_MS (5s), so
  // the floor is not what decides the number here, and the test unmounts long
  // before the wait elapses — leaving it to run would add 8 idle seconds to a
  // suite that finishes in three.
  globalThis.fetch = async (url) => {
    if (String(url).includes("/api/gmail/inbox")) {
      calls += 1;
      return new Response(null, {
        status: 429,
        headers: { "Retry-After": "8" },
      });
    }
    return new Response("{}", { status: 200 });
  };

  let view;
  try {
    view = await mount(React.createElement(InboxWorkbench, { email: "reader@example.com" }));

    // Let the first page go out and be refused.
    await React.act(async () => {
      await sleep(150);
    });

    assert.ok(
      calls > 0,
      "the component never requested a page, so nothing below is about a deferral",
    );

    const first = secondsOnScreen(view);
    assert.ok(
      first !== null,
      `the deferral line never appeared, so there is no countdown to test.\n${view.html().slice(0, 400)}`,
    );
    assert.ok(
      first > 1,
      `the countdown started at ${first}s, which is too near zero to be able to fall. ` +
        "This assertion would pass vacuously.",
    );

    // A real second and a bit, because the ticker is a one-second interval.
    await React.act(async () => {
      await sleep(1300);
    });

    const second = secondsOnScreen(view);
    assert.ok(second !== null, "the deferral line vanished mid-wait");
    assert.ok(
      second < first,
      `the countdown did not count: ${first}s then ${second}s, 1.3s apart, ` +
        "inside one deferral. This is #750 — a duration captured once instead " +
        "of a deadline recomputed.",
    );
    // Unmount before the wait elapses. The component aborts its run, which
    // clears the pending timer — without this the process stays alive for the
    // rest of the deferral and the test costs its whole duration.
    await view.unmount();
  } finally {
    globalThis.fetch = realFetch;
  }
});
