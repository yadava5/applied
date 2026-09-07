/**
 * The toast system's CALL SITES — #511's second half.
 *
 * `feedback-coalesce.test.mjs` pins the policy: what a merged toast says, that
 * errors never time out, that a `sync` key is suppressed. All of it is asserted
 * against hand-written events, which means every one of those tests stays green
 * on a build where nothing in the app calls `notify*` at all. That was the
 * state this file was written to end: `notifyUndo` shipped with ZERO call sites
 * repo-wide, so the affordance the issue is largely about existed as dead code
 * behind a fully green suite.
 *
 * So these read the app instead of a fixture:
 *
 *  1. Every key the app actually emits is a key the channel would let through —
 *     with the control that a `sync.*` key IS caught, because "nothing emits
 *     for sync" is the rule the issue says the next change will break.
 *  2. `notifyUndo` is reached, and every undo key names its target.
 *  3. A committed dismissal offers an Undo that CALLS RESTORE. Mounted,
 *     clicked, timer run out — not a regex over the source, which is how the
 *     neighbouring #560 gate was defeated twice.
 *  4. Two rows removed in one breath produce TWO undo toasts. Fed through the
 *     real `FeedbackChannel`, so the assertion is on the rendered text: this is
 *     the count-collapse acceptance test read from the other end. Break the key
 *     back to a bare `"application.dismiss"` and it goes red with
 *     "2 applications updated"-shaped merging over rows one button cannot both
 *     restore.
 *
 * Run:  node --test --experimental-strip-types tests/unit/feedback-call-sites.test.mjs
 */
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { undoableVerdict } from "../../lib/dashboard/review.ts";
import { FeedbackChannel, isSilentAction, renderToast } from "../../lib/feedback/coalesce.ts";
import { React, importApp, mount } from "./helpers/mountApp.mjs";
import { importTsx, markup, stubModule } from "./helpers/renderTsx.mjs";

const WEB_ROOT = resolve(fileURLToPath(import.meta.url), "../../..");

/** Where a call site may legitimately live. */
const SEARCH_ROOTS = ["components", "lib", "app"];

/** The definition module, skipped: `export function notifySuccess(` is not a
 *  call site, and counting the three declarations is how "two hits, both in its
 *  own file" read as coverage while the affordance was dead. */
const DEFINITION_MODULE = join("components", "feedback", "notify.tsx");

function* sourceFiles(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) yield* sourceFiles(path);
    else if (/\.tsx?$/.test(entry.name) && !path.endsWith(DEFINITION_MODULE)) yield path;
  }
}

/**
 * Every `notify*` call in the app, as `{ fn, key, file }`.
 *
 * A template key keeps its static shape with the interpolations marked, so
 * `application.dismiss.${app.id}` is harvested as `application.dismiss.${}` —
 * enough to answer both questions asked of it here: what prefix the channel
 * would match it on, and whether it names a target at all.
 */
function harvestKeys() {
  const found = [];
  let calls = 0;
  const pattern = /notify(Success|Error|Undo)\(\s*(?:"([^"]*)"|`([^`]*)`)/g;
  for (const root of SEARCH_ROOTS) {
    for (const file of sourceFiles(join(WEB_ROOT, root))) {
      const src = readFileSync(file, "utf8");
      calls += [...src.matchAll(/notify(?:Success|Error|Undo)\(/g)].length;
      for (const [, fn, quoted, templated] of src.matchAll(pattern)) {
        found.push({
          fn: `notify${fn}`,
          key: (quoted ?? templated).replaceAll(/\$\{[^}]*\}/g, "${}"),
          file: relative(WEB_ROOT, file),
        });
      }
    }
  }
  found.calls = calls;
  return found;
}

test("the app emits at least one of each kind — a harvest of nothing proves nothing", () => {
  const keys = harvestKeys();
  // The floor that makes every assertion below mean something. Without it a
  // renamed directory or a changed call shape turns this whole file into a
  // green that measured zero call sites.
  assert.ok(keys.length >= 8, `only ${keys.length} notify call sites found`);
  for (const fn of ["notifySuccess", "notifyError", "notifyUndo"]) {
    assert.ok(
      keys.some((k) => k.fn === fn),
      `${fn} has no call site outside its own module — it is dead code`,
    );
  }
});

test("every notify call site is one the harvest can read", () => {
  // THE HOLE THIS CLOSES, and it is in the gate's whole reason for existing.
  // `harvestKeys` only sees a key written as a literal at the call. A site
  // written `notifyError(key, message)` — or with a key built by concatenation
  // — matches nothing, is never handed to `isSilentAction`, and the sync
  // assertion below passes for it VACUOUSLY. The floor above does not notice,
  // because the existing sites already clear it.
  //
  // So the calls are counted separately from the keys read, and the two must
  // agree. An unreadable call site is a red with an instruction, not an
  // invisible exemption.
  const keys = harvestKeys();
  assert.equal(
    keys.calls,
    keys.length,
    "a notify call site keys on something other than a literal, so nothing " +
      "below can check it — pass a literal, or teach harvestKeys() to read it",
  );
});

test("nothing in the app emits for sync — and the check can catch one", () => {
  const offenders = harvestKeys().filter((k) => isSilentAction(k.key));
  assert.deepEqual(
    offenders,
    [],
    `a call site emits on a silent action: ${offenders.map((o) => `${o.key} (${o.file})`).join(", ")}`,
  );

  // THE CONTROL. The assertion above is an absence, and an absence passes just
  // as well when the instrument is broken — a harvester that returns [] on a
  // renamed directory, a predicate that says false to everything. Both halves
  // are exercised: a sync key IS refused, and a real one is NOT.
  assert.equal(isSilentAction("sync.done"), true, "the guard would not catch a sync emit");
  assert.equal(isSilentAction("sync"), true);
  assert.equal(isSilentAction("application.dismiss.${}"), false);
});

test("every undo key names its target — one Undo cannot restore two rows", () => {
  const undos = harvestKeys().filter((k) => k.fn === "notifyUndo");
  assert.ok(undos.length > 0, "notifyUndo is still unreached");
  for (const undo of undos) {
    assert.match(
      undo.key,
      /\$\{\}/,
      `${undo.file} keys an undo on "${undo.key}", which is target-free: a second ` +
        "occurrence merges into it and the surviving button can only put one of them back",
    );
  }
});

test("the transport the Undo calls reaches the restore endpoint, not a local no-op", async () => {
  // The last link. The mounted test above proves the button calls
  // `transport.restore`; this proves the LIVE transport's `restore` is a
  // request to the recoverable endpoint — without it, a stub that resolved
  // `{ ok: true }` and touched nothing would satisfy everything else here.
  // `importApp`, not a static import: `lib/dashboard/transport.ts` reaches
  // `@/lib/*`, and a hoisted import would run before `mountApp.mjs` registers
  // the hooks that resolve the alias.
  const { liveBoardTransport } = await importApp("lib/dashboard/transport.ts");
  const seen = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (path, init) => {
    seen.push({ path, method: init?.method });
    return { ok: true, json: async () => ({}) };
  };
  try {
    const result = await liveBoardTransport.restore(41);
    assert.equal(result.ok, true);
  } finally {
    globalThis.fetch = realFetch;
  }
  assert.deepEqual(seen, [{ path: "/api/applications/41/restore", method: "POST" }]);
});

test("a correction offers an undo only for a verdict it could send back", () => {
  // The undo re-sends the message's PREVIOUS category through the same
  // endpoint, so the affordance is real exactly when that category is one the
  // control offers. `needs_review` is the case: a genuine stored verdict the
  // classify endpoint does not accept, and a button that would 422 is the
  // decorative undo `notifyUndo` forbids.
  assert.equal(undoableVerdict("rejection"), "rejection");
  assert.equal(undoableVerdict("other"), "other");
  assert.equal(undoableVerdict("needs_review"), null);
  assert.equal(undoableVerdict(null), null);
  assert.equal(undoableVerdict(""), null);
  assert.equal(undoableVerdict("  interview  "), "interview");
});

test("the undo card is prose with a real button — the variant nothing rendered before", async () => {
  // `notifyUndo` had no call sites, so this card has never been on a screen:
  // the amber kind dot and the action button are both first drawn by this
  // change. Two things the issue is explicit about, asserted on the markup —
  // the action is a focusable <button> (not a link, not a div), and the toast
  // is PROSE, with mono reserved for the one machine value on the card.
  const { ToastCard } = await importTsx("components/feedback/ToastCard.tsx");
  const html = markup(
    React.createElement(ToastCard, {
      kind: "undo",
      text: "Northwind removed from the board",
      countBadge: null,
      actionLabel: "Undo",
      onAction: () => {},
      onDismiss: () => {},
    }),
  );

  assert.match(html, /<button[^>]*>Undo<\/button>/);
  assert.match(html, /Northwind removed from the board/);
  // The prose paragraph carries no mono class; the only `font-mono` the card
  // may ever draw is the count badge, which is absent here.
  const prose = /<p [^>]*class="([^"]*)"[^>]*>Northwind/.exec(html)?.[1] ?? "";
  assert.doesNotMatch(prose, /font-mono/, "the toast's sentence is set in mono");
  assert.equal(html.includes("font-mono"), false, "an undo card drew a mono run");
  // With a count it does — and that is the one exception, not a second face.
  const counted = markup(
    React.createElement(ToastCard, {
      kind: "undo",
      text: "Northwind removed from the board",
      countBadge: "×2",
      onDismiss: () => {},
    }),
  );
  assert.match(counted, /font-mono[^"]*"[^>]*>×2</);
});

// --- The dismissal, mounted ---------------------------------------------------

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

/** The row menu, reduced to its items as buttons. A stand-in for an INPUT to
 *  the code under test (which item was chosen), never for the removal path
 *  itself — that runs for real below. */
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

/**
 * Mount a row over a recording transport and run its removal to the commit.
 *
 * The undo window is real seconds (`UNDO_WINDOW_SECONDS`), so the clock is
 * ticked out: the point of the window is that the request is NOT sent until it
 * expires, and a test that skipped it would be asserting the toast fires on the
 * cancellable state — the one case where it must not. `t.mock.timers.enable`
 * belongs to the TEST and not to this helper, because it throws on a second
 * call and the burst below dismisses two rows.
 */
async function dismissRow(t, app) {
  const calls = { dismissed: [], restored: [], toasts: [] };
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
    async dismiss(id) {
      calls.dismissed.push(id);
      return { ok: true };
    },
    async restore(id) {
      calls.restored.push(id);
      return { ok: true };
    },
    async detail() {
      return { ok: false, body: {} };
    },
  };

  const record = (kind) => (key, message, action) => {
    calls.toasts.push({ kind, key, message, action });
  };
  const { ApplicationRow } = await importTsx("components/dashboard/ApplicationRow.tsx", {
    stubs: {
      "@/components/feedback/notify": stubModule({
        notifySuccess: record("success"),
        notifyError: record("error"),
        notifyUndo: record("undo"),
      }),
      "@/components/dashboard/RowActionsMenu": stubModule({ RowActionsMenu: MenuStub }),
    },
  });

  const view = await mount(
    React.createElement(ApplicationRow, { app, today: "2026-08-04", transport }),
  );
  await view.click('[data-menu="dismiss"]');
  // NOTHING has been sent and nothing may be said yet: the row is in its
  // cancellable window, the card owns a tombstone and an Undo of its own, and
  // a toast here would acknowledge a dismissal the server has never seen.
  // Asserted rather than described, or ticking the clock below would be the
  // only thing standing between this test and a false pass.
  assert.deepEqual(calls.toasts, [], "a toast fired while the removal was still cancellable");
  assert.deepEqual(calls.dismissed, []);
  // The window, second by second, exactly as the card counts it down.
  for (let i = 0; i < 8; i += 1) {
    await React.act(async () => {
      t.mock.timers.tick(1000);
    });
  }
  return { calls, view, transport };
}

test("a committed dismissal offers an Undo, and the Undo restores the row", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { calls, view } = await dismissRow(t, ROW);

  assert.deepEqual(
    calls.dismissed,
    [ROW.id],
    "the window expired without sending the dismissal",
  );
  const undo = calls.toasts.find((toast) => toast.kind === "undo");
  assert.ok(undo, "a committed removal raised no undo toast");
  // Stated as the RELATIONSHIP — the action's namespace and THIS row's id —
  // rather than as one flat literal. That is the rule being pinned, and it also
  // keeps a dotted identifier ending in digits out of the tree: the generic
  // entropy rule in the secret scanner reads one as a candidate key, and
  // narrowing that rule to admit a toast fixture would be a poor trade.
  assert.equal(undo.key, `application.dismiss.${ROW.id}`);
  assert.equal(undo.message, `${ROW.company} removed from the board`);

  // THE PART THAT MATTERS. `notifyUndo`'s own docstring forbids rendering this
  // decoratively, and a button that closes its toast and does nothing is
  // exactly that. Run what it was given and watch the endpoint get hit.
  assert.deepEqual(calls.restored, []);
  await React.act(async () => {
    await undo.action.run();
  });
  assert.deepEqual(calls.restored, [ROW.id], "the Undo did not call restore");

  // And the card stops claiming to be removed: the refresh that would unmount
  // it is not guaranteed to have landed, and `removed` is client state.
  assert.doesNotMatch(view.html(), /removed from the board/);
});

test("two rows removed in one breath are two undos, not one counted toast", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const OTHER = { ...ROW, id: 42, company: "Kestrel" };
  const first = await dismissRow(t, ROW);
  const second = await dismissRow(t, OTHER);

  const keys = [first, second].map(
    ({ calls }) => calls.toasts.find((toast) => toast.kind === "undo").key,
  );

  // Read through the REAL channel and asserted on the RENDERED text — the
  // acceptance test the issue predicted would be skipped, run from the call
  // sites rather than from hand-written events. It comes FIRST so a regression
  // fails on what actually goes wrong: a target-free key merges these two into
  // one toast whose text says "×2" over one surviving Undo button, which can
  // put back at most one of the two rows.
  const channel = new FeedbackChannel();
  const decisions = keys.map((key, i) =>
    channel.decide({
      key,
      kind: "undo",
      message: `${[ROW, OTHER][i].company} removed from the board`,
    }),
  );
  assert.deepEqual(
    decisions.map((d) => renderToast(d.toast)),
    [
      { text: `${ROW.company} removed from the board`, countBadge: null },
      { text: `${OTHER.company} removed from the board`, countBadge: null },
    ],
    "two removed rows collapsed into one counted undo toast",
  );
  assert.deepEqual(
    decisions.map((d) => d.action),
    ["show", "show"],
  );
  assert.deepEqual(
    decisions.map((d) => d.toast.count),
    [1, 1],
  );
  assert.deepEqual(keys, [
    `application.dismiss.${ROW.id}`,
    `application.dismiss.${OTHER.id}`,
  ]);

  // The control for that: the SAME row twice does merge, and the count reaches
  // the text. Without this the assertion above passes on a channel that never
  // merges anything.
  const same = new FeedbackChannel();
  same.decide({ key: keys[0], kind: "undo", message: "Northwind removed from the board" });
  const again = same.decide({ key: keys[0], kind: "undo", message: "Northwind removed from the board" });
  assert.equal(again.action, "update");
  assert.deepEqual(renderToast(again.toast), {
    text: "Northwind removed from the board",
    countBadge: "×2",
  });
});
