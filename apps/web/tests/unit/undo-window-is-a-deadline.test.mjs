/**
 * Is the undo window `UNDO_WINDOW_SECONDS` SECONDS, or that many wakeups?
 * (#902. It was six when this was written and is ten since #903, which is why
 * nothing below names a number it did not derive.)
 *
 * The row shipped holding `secondsLeft` in state and taking one off it inside a
 * `setTimeout(…, 1000)`. On a quiet main thread that is indistinguishable from
 * a six-second window — measured on /demo at 1024 on `fd803c79`, six steps of
 * ~1.00s and a window of 6.02s, which is why a presence assertion or a
 * fixed-cadence sample would have called this build correct.
 *
 * It is distinguishable the moment something else wants the thread. Same build,
 * same page, with an observer taking one snapshot of the page every 500ms:
 * steps of ~2.00s and a window of 11.5s, matching the `dt = 138 / 3060 / 5060 /
 * 7059 / 9060 / 11060` recorded in #902 almost exactly. Nothing about the app
 * changed between those two runs. A count of wakeups is not a length of time,
 * and the number on the screen is the entire safety story of a destructive
 * action — wrong by 2x in the permissive direction here, and one refactor from
 * being wrong in the direction that commits a removal while the reader still
 * believes they can undo it.
 *
 * SO THE CLOCK IS THE OTHER PARTY IN THIS TEST, and it is moved in uneven
 * jumps, because that is what a stalled tab does. Under mocked timers a jump is
 * exactly one wakeup, so a decremented counter can only ever take one second
 * off per jump however far the clock actually moved — which is the defect,
 * expressed without any dependence on how loaded the machine running the suite
 * happens to be.
 *
 * Two properties are asserted, and both are false on the shape this replaced:
 *
 *  1. the label never claims more time than the clock has left (it may claim
 *     LESS: a starved repaint makes the number skip, which is honest);
 *  2. the dismissal is sent when the window's own deadline passes — not one
 *     second per render later.
 *
 * WHY NOT PLAYWRIGHT: `tests/e2e/row-removal.spec.ts` does drive this on the
 * real /demo, and it is the reason the numbers above exist. What it cannot do
 * is stall the clock on purpose, so it measures the quiet case — where both
 * shapes agree — and this file measures the case that separates them.
 */
import assert from "node:assert/strict";
import test from "node:test";

import { UNDO_WINDOW_SECONDS } from "../../lib/dashboard/rowActions.ts";
import { React, mount } from "./helpers/mountApp.mjs";
import { importTsx, stubModule } from "./helpers/renderTsx.mjs";

const WINDOW_MS = UNDO_WINDOW_SECONDS * 1000;

const ROW = {
  id: 41,
  company: "Northwind",
  position: "Platform Engineer",
  position_source: null,
  status: "applied",
  source: "gmail",
  due_at: null,
  applied_date: "2026-08-01",
  created_at: "2026-08-01T00:00:00Z",
  url: "https://mail.google.com/mail/#all/t1",
};

/** The row menu reduced to buttons — a stand-in for WHICH ITEM was chosen,
 *  never for the removal path, which runs for real. */
function MenuStub({ items }) {
  return React.createElement(
    "div",
    null,
    items.map((item) =>
      React.createElement(
        "button",
        { key: item.key, type: "button", "data-menu": item.key, onClick: item.onSelect },
        item.label,
      ),
    ),
  );
}

/** The number the tombstone is showing, or null once it is gone. */
function labelSeconds(view) {
  const match = /undo within (\d+)s/.exec(view.html());
  return match === null ? null : Number(match[1]);
}

/** Mount a row over a recording transport and start a removal. */
async function openWindow() {
  const dismissedAt = [];
  const transport = {
    async changeStatus() {
      return { ok: true };
    },
    async setDeadline() {
      return { ok: true };
    },
    async setRole() {
      return { ok: true };
    },
    async dismiss() {
      dismissedAt.push(Date.now());
      return { ok: true };
    },
    async restore() {
      return { ok: true };
    },
    async detail() {
      return { ok: false, body: {} };
    },
  };
  const noop = () => {};
  const { ApplicationRow } = await importTsx("components/dashboard/ApplicationRow.tsx", {
    stubs: {
      "@/components/feedback/notify": stubModule({
        notifySuccess: noop,
        notifyError: noop,
        notifyUndo: noop,
      }),
      "@/components/dashboard/RowActionsMenu": stubModule({ RowActionsMenu: MenuStub }),
    },
  });
  const view = await mount(
    React.createElement(ApplicationRow, { app: ROW, today: "2026-08-04", transport }),
  );
  await view.click('[data-menu="dismiss"]');
  return { view, dismissedAt, openedAt: Date.now() };
}

test("the label never claims more time than the clock has left", async (t) => {
  // `Date` too, not just the timers: the deadline is READ off the clock, so a
  // test that moved the timers without moving the clock would be asking the
  // component to be wrong.
  t.mock.timers.enable({ apis: ["setTimeout", "setInterval", "Date"] });
  const { view, openedAt } = await openWindow();

  // Uneven on purpose. A metronome is the one wake-up pattern under which the
  // two shapes agree, so it is the one pattern this must not use.
  const stalls = [1000, 500, 2500, 1000];
  const seen = [{ elapsed: 0, shown: labelSeconds(view) }];
  let elapsed = 0;
  for (const stall of stalls) {
    await React.act(async () => {
      t.mock.timers.tick(stall);
    });
    elapsed += stall;
    seen.push({ elapsed, shown: labelSeconds(view) });
  }

  const trace = JSON.stringify(seen);
  assert.equal(seen[0].shown, UNDO_WINDOW_SECONDS, `the window opened at ${trace}`);

  for (const { elapsed: at, shown } of seen) {
    assert.ok(shown !== null, `the tombstone vanished mid-window at ${at}ms: ${trace}`);
    const left = Math.ceil((WINDOW_MS - at) / 1000);
    assert.ok(
      shown <= left,
      `${at}ms into a ${WINDOW_MS}ms window the label said ${shown}s with ${left}s left. ` +
        `A label that outlives the clock is a promise the row cannot keep — ${trace}`,
    );
  }

  // Directional, the way #750's control was: it has to FALL, and it may never
  // climb. "A number is shown" is true of every broken version of this.
  for (let i = 1; i < seen.length; i += 1) {
    assert.ok(
      seen[i].shown <= seen[i - 1].shown,
      `the countdown went up: ${trace}`,
    );
  }
  assert.ok(
    seen.at(-1).shown < seen[0].shown,
    `the countdown never moved across ${elapsed}ms: ${trace}`,
  );
  assert.equal(Date.now() - openedAt, elapsed, "the mocked clock did not move as asked");
  await view.unmount();
});

test("the dismissal is sent when the deadline passes, not one second per render later", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout", "setInterval", "Date"] });
  const { view, dismissedAt, openedAt } = await openWindow();

  // One long stall over most of the window, then small steps: the small steps
  // are what makes the bound tight enough to mean something. A decremented
  // counter spends one second per step whatever the clock did during the
  // stall, so it is still counting long after this bound.
  //
  // DERIVED FROM THE WINDOW, not written next to it. These were `4500` and 24
  // steps, sized when the window was 6s; at 10s that plan still reached the
  // deadline, with 500ms of the run to spare and the "long stall" covering
  // under half of what it claims to. A step plan that has to be re-checked by
  // hand every time the constant moves is a red waiting for whoever moves it.
  const FINE_STEP = 250;
  const FINE_SPAN = 3000;
  const steps = [
    WINDOW_MS - FINE_SPAN / 2,
    ...Array.from({ length: FINE_SPAN / FINE_STEP }, () => FINE_STEP),
  ];
  let elapsed = 0;
  for (const step of steps) {
    if (dismissedAt.length > 0) break;
    await React.act(async () => {
      t.mock.timers.tick(step);
    });
    elapsed += step;
  }

  assert.equal(
    dismissedAt.length,
    1,
    `the window never closed: ${elapsed}ms of clock passed on a ${WINDOW_MS}ms window ` +
      "and the dismissal was never sent",
  );
  const lasted = dismissedAt[0] - openedAt;
  assert.ok(
    lasted >= WINDOW_MS,
    `the removal committed after ${lasted}ms, inside its own ${WINDOW_MS}ms window`,
  );
  assert.ok(
    lasted <= WINDOW_MS + FINE_STEP,
    `the removal committed after ${lasted}ms on a ${WINDOW_MS}ms window. The window is ` +
      "being spent in wakeups rather than in time — #902's shape, and #750's before it",
  );
  await view.unmount();
});
