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
 *  3. A dismissal's acknowledgement is INSIDE THE ROW'S OWN CELL and the
 *     corner says nothing at all (#903). Mounted, clicked, timer run out — not
 *     a regex over the source, which is how the neighbouring #560 gate was
 *     defeated twice. This is the item that reds on the build before it: that
 *     one raised an undo toast at focusable index 0 of 69 while painting it
 *     bottom-right, 32 Shift+Tabs behind where it left the reader.
 *  4. Two undoable actions on different targets are TWO toasts, not one
 *     counted one. Fed through the real `FeedbackChannel` with the key shape
 *     the app actually emits, so the assertion is on the rendered text: this is
 *     the count-collapse acceptance test read from the other end. Break the key
 *     back to a target-free one and it goes red with "2 applications
 *     updated"-shaped merging over targets one button cannot both undo.
 *
 * Run:  node --test --experimental-strip-types tests/unit/feedback-call-sites.test.mjs
 */
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { UNDO_WINDOW_SECONDS } from "../../lib/dashboard/rowActions.ts";
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

test("the transport's restore reaches the restore endpoint, not a local no-op", async () => {
  // The last link, and it outlived the call site it was written for: the
  // board's own post-commit Undo went with #903, and the caller left is the
  // scan receipt's per-row `restore` (SyncBar), which answers for rows the
  // SYNC removed. This proves the LIVE transport's `restore` is a request to
  // the recoverable endpoint — without it, a stub that resolved `{ ok: true }`
  // and touched nothing would satisfy everything else here.
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
  // AND THE UNDO IS IN THIS ROW'S OWN MARKUP (#903). Not "an Undo exists
  // somewhere" — that was true of the build this replaces, in a corner card at
  // focusable index 0 of 69 while painted bottom-right. `view.html()` is this
  // row's subtree and nothing else, so a button found here is a button beside
  // the control that opened the menu, which is the property the issue is
  // about. Asserted before the clock is ticked, so a card that renders the
  // affordance only after the commit cannot satisfy it.
  assert.match(view.html(), /Undo<\/button>/, "the row's own cell carries no Undo");
  assert.match(view.html(), /undo within \d+s/, "the row's cell does not say how long is left");
  // The window, second by second, exactly as the card counts it down. Derived
  // from the constant: a literal here was two seconds clear of a six-second
  // window and would silently stop reaching the commit the moment it grew.
  for (let i = 0; i < UNDO_WINDOW_SECONDS + 2; i += 1) {
    await React.act(async () => {
      t.mock.timers.tick(1000);
    });
  }
  return { calls, view, transport };
}

test("a removal is acknowledged in the row's own cell, and nowhere else (#903)", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { calls, view } = await dismissRow(t, ROW);

  assert.deepEqual(
    calls.dismissed,
    [ROW.id],
    "the window expired without sending the dismissal",
  );

  // RED ON THE BUILD BEFORE THIS ONE, which is the point of it. That build
  // answered the commit with `notifyUndo("application.dismiss.41", …)`, and
  // the card it raised measured at focusable index 0 of 69 while painted
  // bottom-right at 1024 — 32 Shift+Tabs behind the successor row the board
  // had just handed focus to, over the stage select of the row beneath it.
  //
  // The rule replacing it: a removal's acknowledgement is the row's own cell
  // for the whole window (asserted in `dismissRow`), and the corner is left
  // for actions that have no surface of their own. `deepEqual` on the empty
  // array rather than a find-and-refute, so a success or an error raised here
  // is caught too — the point is that this path is silent, not that one kind
  // of card is missing.
  assert.deepEqual(
    calls.toasts,
    [],
    "the removal raised a corner toast; #903 is that nobody can reach one",
  );

  // The Undo is gone WITH the window, not before it and not after it: what is
  // left is the committed tombstone, which says which of the two outcomes
  // happened and offers nothing, because there is nothing left to offer.
  assert.match(view.html(), /removed from the board/);
  assert.doesNotMatch(view.html(), /Undo<\/button>/, "an Undo outlived the window it belongs to");
  assert.doesNotMatch(view.html(), /undo within/);
  assert.deepEqual(calls.restored, [], "the board sent a restore it has no affordance for");
});

test("two undoable actions on different targets are two toasts, not one counted toast", () => {
  // The key shape read off the APP rather than written here: whatever call
  // site `notifyUndo` still has, this is its key with two different targets in
  // it. The board's dismissal used to be that call site; the rule it was
  // pinning outlives it, because it is a rule about the channel.
  const templates = harvestKeys()
    .filter((k) => k.fn === "notifyUndo")
    .map((k) => k.key);
  assert.ok(templates.length > 0, "no undo call site to read a key shape from");
  const keys = ["41", "42"].map((id) => templates[0].replace("${}", id));
  assert.notEqual(keys[0], keys[1], "the harvested key does not vary with its target");
  const names = ["Northwind", "Kestrel"];

  // Read through the REAL channel and asserted on the RENDERED text — the
  // acceptance test the issue predicted would be skipped, run from the call
  // sites rather than from hand-written events. It comes FIRST so a regression
  // fails on what actually goes wrong: a target-free key merges these two into
  // one toast whose text says "×2" over one surviving Undo button, which can
  // undo at most one of the two.
  const channel = new FeedbackChannel();
  const decisions = keys.map((key, i) =>
    channel.decide({
      key,
      kind: "undo",
      message: `${names[i]} removed from the board`,
    }),
  );
  assert.deepEqual(
    decisions.map((d) => renderToast(d.toast)),
    [
      { text: `${names[0]} removed from the board`, countBadge: null },
      { text: `${names[1]} removed from the board`, countBadge: null },
    ],
    "two distinct targets collapsed into one counted undo toast",
  );
  assert.deepEqual(
    decisions.map((d) => d.action),
    ["show", "show"],
  );
  assert.deepEqual(
    decisions.map((d) => d.toast.count),
    [1, 1],
  );

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
