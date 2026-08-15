/**
 * The post-auth boot flag (`lib/boot/flag.ts`) — the half of the boot that
 * decides whether it plays AT ALL.
 *
 * Three claims the module makes, none of which had a test:
 *
 *  1. The boot only ever covers the four signed-in routes. `/demo` and the
 *     public pages have no auth transition to dramatise, and a boot over one
 *     is a full-screen animation nobody asked for.
 *  2. An armed flag expires after ten minutes, so an abandoned OAuth attempt
 *     cannot replay the boot on an unrelated later visit.
 *  3. `BOOT_INIT_SCRIPT` — the string that runs in <head> before paint —
 *     carries its OWN inlined copy of the path pattern, because it must stay
 *     dependency-free. The file says "Mirrored in BOOT_INIT_SCRIPT", and a
 *     mirror is exactly the thing that drifts. The last block here EXECUTES
 *     that script in a sandbox and compares it against `isBootPath`, so the
 *     two are checked against each other rather than read side by side.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";

/** A sessionStorage that behaves like the real one, or throws like a blocked
 *  one when `blocked` is set — the module claims to survive both. */
function memoryStorage({ blocked = false } = {}) {
  const map = new Map();
  const guard = () => {
    if (blocked) throw new Error("storage blocked");
  };
  return {
    map,
    getItem(k) {
      guard();
      return map.has(k) ? map.get(k) : null;
    },
    setItem(k, v) {
      guard();
      map.set(k, String(v));
    },
    removeItem(k) {
      guard();
      map.delete(k);
    },
  };
}

globalThis.sessionStorage = memoryStorage();
globalThis.window = { events: [], dispatchEvent(e) { this.events.push(e); return true; } };

const {
  BOOT_FLAG_KEY,
  BOOT_FLAG_MAX_AGE_MS,
  BOOT_INIT_SCRIPT,
  armBoot,
  clearBootFlag,
  isBootPath,
  readBootFlag,
} = await import("../../lib/boot/flag.ts");

/** Paths the boot may cover, and paths it must not. Shared by the direct
 *  `isBootPath` test and the sandboxed pre-paint script below. */
const BOOT_PATHS = [
  "/dashboard",
  "/inbox",
  "/settings",
  "/import",
  "/dashboard/",
  "/settings/notifications",
  "/inbox?filter=review",
  "/import#top",
];
const NON_BOOT_PATHS = [
  "/",
  "/demo",
  "/demo/shell",
  "/login",
  "/signup",
  "/privacy",
  "/dashboards",
  "/importer",
  "/inboxes",
  "/beta",
];

function reset() {
  globalThis.sessionStorage = memoryStorage();
  globalThis.window.events = [];
}

test("the boot may cover the four signed-in routes and nothing else", () => {
  for (const p of BOOT_PATHS) assert.equal(isBootPath(p), true, `${p} is a boot path`);
  for (const p of NON_BOOT_PATHS) assert.equal(isBootPath(p), false, `${p} is not a boot path`);
});

test("arming writes a flag a later read can find, and announces it in-tab", () => {
  reset();
  armBoot("/dashboard");
  assert.equal(readBootFlag(), "/dashboard");
  assert.equal(globalThis.window.events.length, 1, "the same-tab sign-in path is notified");
  assert.equal(globalThis.window.events[0].type, "jt-boot-begin");
  assert.equal(globalThis.window.events[0].detail, "/dashboard");
});

test("the OAuth path arms silently — no event to race the redirect", () => {
  reset();
  armBoot("/dashboard", { notify: false });
  assert.equal(readBootFlag(), "/dashboard");
  assert.equal(globalThis.window.events.length, 0);
});

test("a flag older than ten minutes is not a sign-in in flight", () => {
  reset();
  // The ages are ABSOLUTE, not derived from BOOT_FLAG_MAX_AGE_MS. A fixture
  // computed from the constant moves with it, so widening the window to a week
  // would leave this test green — it would be checking the arithmetic against
  // itself. Ten minutes is the documented promise; nine and eleven straddle it.
  const MINUTE = 60 * 1000;
  sessionStorage.setItem(BOOT_FLAG_KEY, `/dashboard|${Date.now() - 9 * MINUTE}`);
  assert.equal(readBootFlag(), "/dashboard", "nine minutes: a sign-in still in flight");
  sessionStorage.setItem(BOOT_FLAG_KEY, `/dashboard|${Date.now() - 11 * MINUTE}`);
  assert.equal(readBootFlag(), null, "eleven minutes: an abandoned attempt");

  // …and the boundary is where the constant says it is.
  sessionStorage.setItem(BOOT_FLAG_KEY, `/dashboard|${Date.now() - BOOT_FLAG_MAX_AGE_MS - 1}`);
  assert.equal(readBootFlag(), null);
});

test("a flag naming somewhere the boot may not go is ignored", () => {
  reset();
  sessionStorage.setItem(BOOT_FLAG_KEY, `/demo|${Date.now()}`);
  assert.equal(readBootFlag(), null);
});

test("a malformed flag is ignored rather than thrown on", () => {
  reset();
  for (const junk of ["", "/dashboard", "/dashboard|", "/dashboard|not-a-number", "|123"]) {
    sessionStorage.setItem(BOOT_FLAG_KEY, junk);
    assert.equal(readBootFlag(), null, `"${junk}" is not a live flag`);
  }
});

test("consuming the flag is what stops a reload replaying the boot", () => {
  reset();
  armBoot("/import");
  assert.equal(readBootFlag(), "/import");
  clearBootFlag();
  assert.equal(readBootFlag(), null, "the second read — the reload's — finds nothing");
});

test("blocked storage degrades to no boot, never to an exception", () => {
  globalThis.sessionStorage = memoryStorage({ blocked: true });
  globalThis.window.events = [];
  assert.doesNotThrow(() => armBoot("/dashboard"));
  assert.equal(globalThis.window.events.length, 1, "the client-nav path still works without storage");
  assert.equal(readBootFlag(), null);
  assert.doesNotThrow(() => clearBootFlag());
});

/* -------------------------------------------------------------------------
 * The pre-paint script, executed.
 * ---------------------------------------------------------------------- */

/** Run BOOT_INIT_SCRIPT the way <head> does, against a made-up document. */
function runInitScript(pathname, stored) {
  const storage = memoryStorage();
  if (stored !== undefined) storage.map.set(BOOT_FLAG_KEY, stored);
  const documentStub = { documentElement: { dataset: {} } };
  vm.runInNewContext(BOOT_INIT_SCRIPT, {
    sessionStorage: storage,
    location: { pathname },
    document: documentStub,
  });
  return { dataset: documentStub.documentElement.dataset, stored: storage.map.get(BOOT_FLAG_KEY) };
}

test("the pre-paint script raises the cover for a live flag on a boot path", () => {
  const out = runInitScript("/dashboard", `/dashboard|${Date.now()}`);
  assert.equal(out.dataset.boot, "1");
  assert.ok(out.stored, "the script does not consume the flag — the overlay does");
});

test("the pre-paint script clears a stale flag instead of activating on it", () => {
  // Eleven minutes, absolute — the script inlines its own copy of the max age
  // as a literal, and a fixture derived from the constant would move with it.
  const out = runInitScript("/dashboard", `/dashboard|${Date.now() - 11 * 60 * 1000}`);
  assert.equal(out.dataset.boot, undefined, "no cover");
  assert.equal(out.stored, undefined, "and the dead flag is gone");
});

test("the pre-paint script does nothing with no flag, or with garbage", () => {
  assert.equal(runInitScript("/dashboard").dataset.boot, undefined);
  assert.equal(runInitScript("/dashboard", "nonsense").dataset.boot, undefined);
});

test("the pre-paint script's inlined path pattern still agrees with isBootPath", () => {
  // The one that would drift silently: two copies of the same rule, one of
  // them a string. A live flag is armed for every path so the ONLY thing that
  // can differ is the path test.
  for (const p of [...BOOT_PATHS, ...NON_BOOT_PATHS]) {
    const out = runInitScript(p, `/dashboard|${Date.now()}`);
    assert.equal(
      out.dataset.boot === "1",
      isBootPath(p),
      `the pre-paint script and isBootPath disagree about ${p}`,
    );
  }
});
