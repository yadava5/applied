import { expect, test, type Page } from "@playwright/test";

import { startConsoleWatch } from "./helpers";

/**
 * The post-auth boot, EXECUTED — the overlay's orchestration
 * (`components/boot/BootOverlay.tsx` + `lib/boot/flag.ts`) rather than its
 * engine, which `tests/unit/boot-triage.test.mjs` covers.
 *
 * WHY THIS CAN RUN WITHOUT A SESSION, which is the whole reason the file
 * exists. The boot plays on four routes, and one of them — `/import` — is the
 * on-device mail importer: it answers 200 to a signed-out request AND
 * `isBootPath("/import")` is true. So arming the flag and navigating there
 * drives the real boot, on a real boot route, with no Supabase session. The
 * other three would bounce to /login and skip (#188), and a spec that skips is
 * not a gate.
 *
 * HOW THE ASSERTIONS ARE TAKEN. `data-boot` on <html> is the boot's whole
 * visible contract: raised before paint by the inline BOOT_INIT_SCRIPT so no
 * half-loaded shell flashes, and removed when the boot has resolved and the
 * mark has landed. An init script installs a MutationObserver on that one
 * attribute BEFORE any page script runs, recording each change with
 * `document.readyState`, whether <body> exists yet, and `performance.now()` —
 * which on a fresh document is time since navigation start, the same clock the
 * overlay measures its floor against. Reading the log afterwards is therefore
 * a record of what happened, not a sample of what is true when the test looks.
 *
 * TIMING IS ASSERTED AS ORDERING AND BOUNDS, NEVER AS A MILLISECOND. The boot
 * has a 1500 ms floor and an 8 s cap (both private to BootOverlay); a healthy
 * run clears at ~1900 ms. The lower bounds are the floors themselves — they
 * can only be exceeded, never undershot, so they are safe to assert exactly.
 * The upper bounds are deliberately generous: they exist to catch an overlay
 * that never leaves, not to measure one that is a few hundred ms late.
 */

type BootLogEntry = {
  value: string | null;
  readyState: string;
  hasBody: boolean;
  t: number;
};

/**
 * Installed with `addInitScript`, so it is evaluated on document creation —
 * before the BOOT_INIT_SCRIPT in <head>, which is what makes "the cover was up
 * before hydration" provable rather than assumed. `document.documentElement`
 * may not exist yet at that point, so the observer is attached to the Document
 * and reaches the <html> element through `subtree`.
 */
function watchBootFlag() {
  const log: BootLogEntry[] = [];
  (window as unknown as { __bootLog: BootLogEntry[] }).__bootLog = log;
  new MutationObserver((records) => {
    for (const record of records) {
      if (record.attributeName !== "data-boot") continue;
      log.push({
        value: document.documentElement.getAttribute("data-boot"),
        readyState: document.readyState,
        hasBody: Boolean(document.body),
        t: performance.now(),
      });
    }
  }).observe(document, { attributes: true, subtree: true, attributeFilter: ["data-boot"] });
}

/**
 * A route-level pending surface that never goes away, for the cap test.
 * BootOverlay holds while `[aria-busy="true"][aria-label^="Loading"]` is on
 * screen, so this stands in for a route that never reports ready — the case
 * MAX_HOLD exists for, and one a healthy /import can never produce on its own.
 *
 * It goes in <head>: the UA stylesheet gives `head { display: none }` so it
 * paints nothing, and it is outside the <body> React hydrates, so it cannot
 * cause a hydration mismatch. This is a test-side input to the product's own
 * ready check — no product code is changed to accommodate it.
 */
function stallReadySignal() {
  const add = () => {
    const el = document.createElement("div");
    el.setAttribute("aria-busy", "true");
    el.setAttribute("aria-label", "Loading (e2e stall)");
    el.setAttribute("data-e2e-stall", "1");
    document.head.appendChild(el);
  };
  if (document.head) add();
  else document.addEventListener("DOMContentLoaded", add);
}

/**
 * `lib/boot/flag.ts`'s BOOT_FLAG_KEY, written out because the spec runs in the
 * browser and the app's `@/` alias is not resolvable from here. It is not a
 * silent duplicate: if the real key is renamed, arming here stops working and
 * every test below goes red on "the cover was never raised" rather than
 * quietly passing.
 */
const BOOT_FLAG_KEY = "jt-boot";

/**
 * A page that is NOT a boot route, which is where the flag has to be armed.
 *
 * `BootOverlay` consumes the flag in a `setTimeout(…, 0)` after mount, guarded
 * by `isBootPath(window.location.pathname)` — so an overlay sitting on a boot
 * route eats any flag it finds there. Arming on `/import` itself therefore
 * raced its own consumer: whether the test won depended on whether that mount
 * timeout had already fired by the time `page.goto` returned at `load`.
 *
 * That is why this is a wrong SEQUENCE, not a timing nicety. In production the
 * flag is written on the sign-in page — never a boot path — and read once on
 * arrival at the destination. Arming on the destination is a sequence no user
 * performs, and it was the test asserting against itself.
 *
 * The race was invisible until a `<FeedbackToaster />` joined the signed-out
 * layout: its client JS pushes hydration on `/import` past `load`, which moved
 * the consume from before the arm to after it, and three tests began failing in
 * CI for a reason that had nothing to do with toasts. Measured: 11 of 12 arms
 * lost with the toaster present, 0 of 12 lost without it, and 12 of 12 raised
 * with the toaster still present once the arm moved here. The corroboration was
 * already in this file — the one test that armed off a non-boot page is the one
 * test that never flaked.
 */
const ARM_FROM = "/demo";

/** Arm the flag the way a sign-in does, then arrive on a boot route.
 *  `waitUntil: "commit"` returns as soon as the document commits, which puts
 *  the assertions inside the boot's window instead of after `load`. */
async function armAndArrive(page: Page, target = "/import") {
  await page.goto(ARM_FROM);
  await page.evaluate(
    ([key, value]) => window.sessionStorage.setItem(key, `${value}|${Date.now()}`),
    [BOOT_FLAG_KEY, target],
  );
  await page.goto(target, { waitUntil: "commit" });
}

async function bootLog(page: Page): Promise<BootLogEntry[]> {
  return page.evaluate(() => (window as unknown as { __bootLog?: BootLogEntry[] }).__bootLog ?? []);
}

/** Wait for the cover to retire itself, and return the entry that did it. */
async function waitForCover(page: Page, state: "raised" | "cleared", timeout = 15000) {
  const want = state === "raised" ? "1" : null;
  await expect
    .poll(
      async () => {
        const log = await bootLog(page);
        return log.length > 0 ? log[log.length - 1].value : "none";
      },
      {
        timeout,
        // Says WHICH of the two it was. This poll reads only the LAST entry, so
        // a cover that raised and cleared normally reports the same
        // "never reached raised" as one that was never armed at all — and those
        // have opposite causes. Distinguishing them cost a full re-instrument
        // of the page once; the message now carries the distinction.
        message:
          `data-boot never reached ${state} — an empty log means never armed, ` +
          `a log containing "1" means it raised and then cleared`,
      },
    )
    .toBe(want);
  const log = await bootLog(page);
  return log[log.length - 1];
}

/**
 * WHY THIS FILE IS PRODUCTION-ONLY. Every assertion below hangs off the cover
 * being raised BEFORE paint, by the inline BOOT_INIT_SCRIPT in <head>. Under
 * `next dev` that script is served from an on-demand compile, so whether it
 * runs while the document is still parsing depends on how warm the compiler
 * happens to be — the dev-server job fails three of these and flakes the
 * fourth, always as `data-boot never reached raised`. That is a real
 * dev-versus-production difference, not a slow machine, and it cannot be
 * waited out without giving up the "before hydration" claim that is the point.
 * So the file is collected by the job that can satisfy it: the same idiom
 * `tests/e2e/production.spec.ts` uses, and only `playwright (production
 * build)` sets PLAYWRIGHT_PROD_BUILD=1. No bound below is loosened by this —
 * the gate changes which job runs the file, nothing about what it demands.
 */
const PROD_BUILD = process.env.PLAYWRIGHT_PROD_BUILD === "1";

test.describe("the post-auth boot (/import — a boot route that needs no session)", () => {
  test.skip(
    !PROD_BUILD,
    "Runs only against `next start`; set PLAYWRIGHT_PROD_BUILD=1.",
  );

  test("covers the screen before hydration and clears itself once resolved", async ({ page }) => {
    const watch = startConsoleWatch(page);
    await page.addInitScript(watchBootFlag);
    await armAndArrive(page);

    await waitForCover(page, "raised", 5000);
    const [first] = await bootLog(page);
    expect(first.value, "the cover is raised, not lowered").toBe("1");
    expect(first.readyState, "…while the document is still parsing").toBe("loading");
    expect(first.hasBody, "…and before <body> exists, i.e. before hydration").toBe(false);

    // The overlay itself is on screen, with its canvas — the engine really
    // mounted, this is not CSS alone.
    await expect(page.getByRole("status", { name: "Signing you in" })).toBeVisible();
    await expect(page.locator("canvas.boot-overlay__canvas")).toBeAttached();

    const cleared = await waitForCover(page, "cleared");
    // The floor: BootOverlay holds for MIN_VISIBLE (1500 ms) measured from
    // navigation start, then plays a 400 ms exit. Observed ≈1900 ms; 1500 is
    // asserted because a floor can only be exceeded.
    expect(cleared.t, "the boot cleared before its own minimum").toBeGreaterThanOrEqual(1500);
    // The ceiling here is loose on purpose — MAX_HOLD is gated properly in the
    // stalled-route test below. This one only says the overlay is not immortal.
    expect(cleared.t, "the boot never let go").toBeLessThan(12000);

    // And the app underneath is the real one.
    await expect(page.getByRole("heading", { name: "Import your mail" })).toBeVisible();
    await expect(page.locator("canvas.boot-overlay__canvas")).toHaveCount(0);

    // A 4xx/5xx on one of the routes the boot warms is a network fact, not a
    // page defect; everything else — hydration failures above all — must be
    // absent, since the cover is raised by an inline script the app then has
    // to agree with.
    const real = watch.errors.filter((e) => !/Failed to load resource/i.test(e));
    expect(real, real.join("\n")).toEqual([]);
  });

  test("a plain reload does not replay it", async ({ page }) => {
    await page.addInitScript(watchBootFlag);
    await armAndArrive(page);

    // Prove the observer is live on this page before asserting a negative.
    await waitForCover(page, "raised", 5000);
    await waitForCover(page, "cleared");

    await page.reload();
    await page.waitForLoadState("load");
    // The overlay reads the flag in a setTimeout(…, 0) macrotask after mount,
    // so a replay would raise the cover within a frame or two of hydration —
    // and would then hold it for at least MIN_VISIBLE. A second is ample.
    await page.waitForTimeout(1000);

    const log = await bootLog(page);
    expect(
      log.map((e) => e.value),
      "the boot replayed on a reload — the flag was not consumed",
    ).not.toContain("1");
    await expect(page.locator("canvas.boot-overlay__canvas")).toHaveCount(0);
    expect(await page.evaluate((key) => window.sessionStorage.getItem(key), BOOT_FLAG_KEY)).toBeNull();
  });

  test("an armed flag does not fire on a page the boot may not cover", async ({ page }) => {
    await page.addInitScript(watchBootFlag);
    await page.goto("/demo");
    await page.evaluate(
      ([key, value]) => window.sessionStorage.setItem(key, `${value}|${Date.now()}`),
      [BOOT_FLAG_KEY, "/import"],
    );

    await page.goto("/demo", { waitUntil: "commit" });
    await page.waitForLoadState("load");
    await page.waitForTimeout(1000);
    const onDemo = await bootLog(page);
    expect(
      onDemo.map((e) => e.value),
      "/demo has no auth transition to dramatise",
    ).not.toContain("1");
    // The same claim taken a second way, and the one that does not depend on
    // the mutation log having been recorded at all: a page the boot may not
    // cover must also leave the flag alone. Measured — with `demo` added to
    // the path rule, the log assertion above passed under a five-worker run
    // while this one goes red, so the log alone is not enough.
    expect(
      await page.evaluate((key) => window.sessionStorage.getItem(key), BOOT_FLAG_KEY),
      "/demo consumed a flag it was not allowed to act on",
    ).not.toBeNull();

    // The positive control for that negative, in the same lifecycle: the flag
    // was not consumed by the page that ignored it, so arriving on a route the
    // boot MAY cover still plays it.
    await page.goto("/import", { waitUntil: "commit" });
    const raised = await waitForCover(page, "raised", 5000);
    expect(raised.value).toBe("1");
  });

  test("never outlives its cap, even when the route never reports ready", async ({ page }) => {
    test.setTimeout(45000);
    await page.addInitScript(watchBootFlag);
    await page.addInitScript(stallReadySignal);
    await armAndArrive(page);
    await waitForCover(page, "raised", 5000);

    // Well past the 1500 ms floor: a boot that only respected the floor would
    // be long gone. If the stall element failed to install, this is where the
    // test goes red — the assertion IS the positive control.
    await page.waitForTimeout(4000);
    await expect(page.locator("[data-e2e-stall]")).toHaveCount(1);
    const held = await bootLog(page);
    expect(held[held.length - 1].value, "a stalled route should still be held").toBe("1");

    // MAX_HOLD is 8 s, then the 400 ms exit. The upper bound carries slack for
    // a loaded runner but stays under the 10 s CSS failsafe's own tail.
    const cleared = await waitForCover(page, "cleared", 12000);
    expect(cleared.t, "the hold was not the cap").toBeGreaterThan(8000);
    expect(cleared.t, "the cap did not fire").toBeLessThan(11000);
  });

  test("resolves under prefers-reduced-motion too, on its shorter floor", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.addInitScript(watchBootFlag);
    await armAndArrive(page);

    await waitForCover(page, "raised", 5000);
    const cleared = await waitForCover(page, "cleared");
    // The reduced floor is 700 ms (a poster, then a 200 ms crossfade — no
    // flight). Only the floor is asserted: an upper bound tight enough to tell
    // 700 from 1500 would be racing the page load itself, which is exactly the
    // kind of gate that flakes.
    expect(cleared.t).toBeGreaterThanOrEqual(700);
    expect(cleared.t).toBeLessThan(12000);
    await expect(page.getByRole("heading", { name: "Import your mail" })).toBeVisible();
  });
});
