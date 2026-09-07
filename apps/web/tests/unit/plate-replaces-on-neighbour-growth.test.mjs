/**
 * THE HALF OF #610 THAT WAS ACTUALLY BROKEN: the plate's placement is a
 * function of three widths, and it used to be computed before one of them
 * arrived.
 *
 * THE DEFECT, measured before the fix (headless Chrome, `next dev`, 1024×768,
 * `/demo/shell?session=1` in the `N changes` state, 2026-09-07):
 *
 *     subtitle "17 filed · 14 open · 0 offers"          right edge 511.1
 *     plate, centred on the bar                         576.0 … 688.0
 *     clearance from the totals                              65.0px
 *
 *     the reader's-week segment appears (+69.7px of subtitle):
 *     subtitle "17 filed · +7 this wk · 14 open · 0 offers"  right edge 580.8
 *     plate                                             576.0 … 688.0  (unmoved)
 *     clearance from the totals                              −4.7px
 *
 * `placePlate` ran on mount and on `window.resize`, and its ref callback is
 * stable, so React never re-invokes it for a re-render. `BoardSubtitle`'s
 * correction (#518) re-renders a SIBLING subtree: no resize, no branch swap,
 * nothing that re-places the plate — and because `buildSubtitle` omits the
 * whole ` · +N this wk` segment at zero, the correction does not change a
 * digit, it makes ~70px appear. On the owner's board, where the totals already
 * bind at the 16px budget, that is ~53px of the line under the chip.
 *
 * WHY THIS IS A UNIT TEST AND NOT A BROWSER ONE. The collision needs the
 * signed-in board. The public twin reaches the `N changes` state — proved, and
 * `tests/e2e/shell.spec.ts` now measures the plate there — but it cannot host
 * this defect, and the reason is STRUCTURAL rather than arithmetic. The
 * mid-session appearance is `BoardSubtitle`'s, and the only file that imports
 * it is `app/(app)/(protected)/dashboard/page.tsx`; `DemoDashboard.tsx` calls
 * `buildSubtitle` directly and nothing corrects the line after hydration, so
 * nothing on the twin makes the reader's-week segment appear after mount.
 * Both renderings ARE reachable there — `weekly` is a cookie pref, off by
 * default, so the segment is simply absent until a reader flips it, which
 * makes both subtitle widths above readable on this surface. What the twin
 * cannot produce is the TRANSITION between them after mount — the readings
 * above compose two states rather than record a sequence this surface can
 * run. Its plate also has 65px of slack at 1024 where the live board has 16.
 * So the browser gate can say the loud plate is placed correctly, and only
 * this file can say the placement is RE-DERIVED when an input changes.
 *
 * WHAT IS REAL HERE AND WHAT IS NOT, in the terms `helpers/mountApp.mjs` sets:
 * the component is the real one, React is real, the DOM is jsdom. jsdom has no
 * layout and no `ResizeObserver`, so the boxes and the observer are stubs —
 * which is exactly the seam under test. The arithmetic those boxes feed is
 * executed for real in `tests/unit/plate-placement.test.mjs`, against the same
 * measurements.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  LAST_LOOK_DEMO_KEY,
  LAST_LOOK_DEMO_SCOPE,
  snapshotOf,
} from "../../lib/dashboard/lastLook.ts";
import { PLATE_CLEAR } from "../../lib/dashboard/platePlacement.ts";
import { React, importApp, mount } from "./helpers/mountApp.mjs";

const { SinceLastLook } = await importApp("components/dashboard/SinceLastLook.tsx");

/** One line of the header row, in the boxes the placement reads. `totals.right`
 *  is the value the reader's-week correction moves; everything else is fixed
 *  for the width under test. Numbers as measured — see the header. */
const LINE = { top: 100, bottom: 126 };
const EDGES = {
  plate: { left: 576, right: 688 },
  totals: { left: 352, right: 511.1 },
  cluster: { left: 755.5, right: 1000 },
};
const SERVED_RIGHT = 511.1;
const CORRECTED_RIGHT = 580.8;

const rect = ({ left, right }) => ({
  left,
  right,
  top: LINE.top,
  bottom: LINE.bottom,
  x: left,
  y: LINE.top,
  width: right - left,
  height: LINE.bottom - LINE.top,
  toJSON() {
    return this;
  },
});

// `placePlate` asks whether the overlay is out of flow before it nudges
// anything — the guard that makes it a no-op in the stacked header below `lg`.
// jsdom answers it from the inline style the row below sets; the global is not
// one `helpers/mountApp.mjs` installs, because no component it mounts had
// reached for it until this one.
globalThis.getComputedStyle = (element) => globalThis.window.getComputedStyle(element);

// Layout, which jsdom does not do. Keyed off what the element IS rather than a
// registry of nodes, so a re-render that replaces the plate keeps its box.
globalThis.window.Element.prototype.getBoundingClientRect = function () {
  if (this.matches("[data-sync-subtitle]")) return rect(EDGES.totals);
  if (this.matches("[data-sync-cluster]")) return rect(EDGES.cluster);
  if (this.closest('[data-testid="since-last-look"]') !== null) return rect(EDGES.plate);
  return rect({ left: 0, right: 0 });
};

/** A `ResizeObserver` that records what it was aimed at and fires on demand.
 *  Both halves matter: a watcher that is constructed and observes nothing
 *  fails the same way as one that is never constructed, and only the target
 *  list tells them apart. */
class Watcher {
  static made = [];

  constructor(callback) {
    this.callback = callback;
    this.targets = [];
    Watcher.made.push(this);
  }

  observe(target) {
    this.targets.push(target);
  }

  unobserve(target) {
    this.targets = this.targets.filter((t) => t !== target);
  }

  disconnect() {
    this.targets = [];
  }

  /** What the browser does when one of those boxes changes size. */
  fire() {
    this.callback(
      this.targets.map((target) => ({ target })),
      this,
    );
  }
}
globalThis.ResizeObserver = Watcher;

/**
 * The header row, in the shape `placePlate` walks: the plate's `<section>`
 * hangs inside an absolutely-positioned overlay, whose parent carries the two
 * neighbours. That walk (`closest("section")`, then two parents, then the
 * `position: absolute` test) is the component's own guard for "am I overlaying
 * a row or standing in a stacked column", so the test has to build the row it
 * is looking for rather than assert against a flat tree.
 */
function row(props) {
  return React.createElement(
    "div",
    null,
    React.createElement("p", { "data-sync-subtitle": "" }, "17 filed · 14 open · 0 offers"),
    React.createElement(
      "div",
      { style: { position: "absolute" } },
      React.createElement(SinceLastLook, props),
    ),
    React.createElement("div", { "data-sync-cluster": "" }, "Sync"),
  );
}

/** The chip itself — `shell.spec.ts` names it the same way, and for the same
 *  reason: the quiet plate is a `<p>` and the loud one a `<button>`. */
const plateIn = (view) => view.query('[data-testid="since-last-look"]').querySelector("p, button");

/** The slide the component wrote, in pixels. */
function slideOf(plate) {
  const written = plate.style.transform;
  if (written === "") return 0;
  const match = /^translateX\((-?[\d.]+)px\)$/.exec(written);
  assert.ok(match !== null, `the plate carries an unreadable transform: "${written}"`);
  return Math.round(Number(match[1]) * 100) / 100;
}

/** The one thing every case below asserts, in the terms the issue is in. */
function assertRePlaced(view, watcher) {
  const plate = plateIn(view);
  assert.equal(slideOf(plate), 0, "nothing binds at the served width — the plate holds the centre");

  EDGES.totals = { ...EDGES.totals, right: CORRECTED_RIGHT };
  watcher.fire();

  const slide = slideOf(plate);
  assert.equal(
    Math.round((EDGES.plate.left + slide - CORRECTED_RIGHT) * 100) / 100,
    PLATE_CLEAR,
    `the segment appeared and the plate stands ${EDGES.plate.left + slide - CORRECTED_RIGHT}px from the totals — it was placed against a width that has since changed (#610)`,
  );
}

/** The watcher the component built, with the failure spelled out where a green
 *  is impossible: no watcher at all is the pre-fix state. */
function watcherFor(view) {
  assert.equal(
    Watcher.made.length,
    1,
    "the placement built no ResizeObserver: it is computed once, before the width it budgets against arrives (#610)",
  );
  const watcher = Watcher.made[0];
  const plate = plateIn(view);
  for (const [what, node] of [
    ["the subtitle", view.query("[data-sync-subtitle]")],
    ["the sync cluster", view.query("[data-sync-cluster]")],
    ["the plate itself", plate],
  ]) {
    assert.ok(
      watcher.targets.includes(node),
      `${what} is an input to the placement and is not being watched`,
    );
  }
  assert.ok(plate.isConnected, "the watched plate is the one on screen, not a detached previous branch");
  return watcher;
}

const ROWS = [
  { id: 1, company: "Cedar Labs", position: "Software Engineer, Platform", stage: "applied", filed: "2026-09-01" },
];

test("the plate that ARRIVES after mount is watched — the reserve line has none", async () => {
  // First visit: storage is empty, so the first render is the reserve line
  // with NO plate in it, and the plate appears only once the component has
  // written its own baseline. The watcher is created by an effect, which runs
  // before that — so this is the case where a watcher aimed once at mount
  // would be aimed at nothing for the rest of the session.
  globalThis.window.localStorage.clear();
  Watcher.made.length = 0;
  EDGES.totals = { left: 352, right: SERVED_RIGHT };

  const view = await mount(
    row({ rows: ROWS, scope: LAST_LOOK_DEMO_SCOPE, storageKey: LAST_LOOK_DEMO_KEY }),
  );
  assert.match(
    view.query('[data-testid="since-last-look"]').textContent,
    /No earlier visit/,
    "the first-visit branch did not render — this case is measuring something else",
  );

  assertRePlaced(view, watcherFor(view));

  const watcher = Watcher.made[0];
  await view.unmount();
  assert.deepEqual(watcher.targets, [], "the watcher outlived the chip that built it");
});

test("the LOUD plate — the state #610 was reported in — is re-placed too", async () => {
  // A marker from an earlier visit that knows nothing about the board it is
  // being read against: one row it has never seen, so the ledger has something
  // to report and the chip mounts as the `N changes` press.
  globalThis.window.localStorage.clear();
  globalThis.window.localStorage.setItem(
    LAST_LOOK_DEMO_KEY,
    JSON.stringify(snapshotOf([], LAST_LOOK_DEMO_SCOPE, Date.now() - 3_600_000, false)),
  );
  Watcher.made.length = 0;
  EDGES.totals = { left: 352, right: SERVED_RIGHT };

  const view = await mount(
    row({ rows: ROWS, scope: LAST_LOOK_DEMO_SCOPE, storageKey: LAST_LOOK_DEMO_KEY }),
  );
  assert.match(
    view.query('[data-testid="since-last-look"]').textContent,
    /1 change/,
    "the loud branch did not render — the quiet chip is a different element and this case is about the press",
  );

  assertRePlaced(view, watcherFor(view));
  await view.unmount();
});
