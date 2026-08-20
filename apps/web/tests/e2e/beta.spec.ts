import { expect, test } from "@playwright/test";

import {
  expectNoHorizontalOverflow,
  MOBILE_375,
  startConsoleWatch,
} from "./helpers";

/**
 * E2E for the beta-access notice and the privacy positioning.
 *
 * The rich <BetaCard> lives on /settings and the not-connected /inbox, which
 * are auth-gated and unreachable without a session — so these specs exercise
 * the publicly reachable surfaces: the dismissible site-wide banner (whose
 * popover carries the same verified copy + actions as the card) and the
 * landing's privacy section.
 */

// encodeURIComponent("Applied beta access request") === "Applied%20beta%20access%20request"
const ADMIN_MAILTO =
  /^mailto:aesh\.03\.23@gmail\.com\?subject=Applied%20beta%20access%20request/;

test.describe("beta access notice", () => {
  test("the beta pill renders and expands into the beta details", async ({ page }) => {
    const watch = startConsoleWatch(page);
    await page.goto("/");

    const toggle = page.getByRole("button", { name: /limited access/i });
    await expect(toggle).toBeVisible();

    // The card/details are collapsed until asked for.
    const panel = page.getByRole("region", { name: /beta access/i });
    await expect(panel).toHaveCount(0);

    await toggle.click();
    await expect(panel).toBeVisible();
    // The seat cap is the honest Google OAuth test-user limit — always 100,
    // never a hydration-stranded 0/-1. (This shared BETA_SEATS constant also
    // feeds the rich <BetaCard> seat panel on the auth-gated /settings & /inbox,
    // where it is rendered as a static server number for the same reason.)
    await expect(panel.getByText(/\b100 beta testers\b/i)).toBeVisible();
    await expect(panel.getByText(/Google's OAuth test-user cap/i)).toBeVisible();

    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });

  /**
   * `HIDE_ON` in BetaBanner.tsx had NO test of any kind until 2026-08-20, so
   * every entry on it was an unchecked assertion: a typo, a route rename or a
   * dropped line would have silently put a fixed app toast back over a surface
   * that was deliberately cleared of one.
   *
   * THE FIRST VERSION OF THIS TEST WAS DECORATION, and the way it failed is
   * worth keeping written down. It navigated, waited for the `<h1>`, then
   * asserted `toHaveCount(0)`. Both halves were individually reasonable and the
   * pair was useless: the heading is server-rendered, so waiting for it gates
   * on nothing, and `toHaveCount(0)` is a wait-UNTIL-TRUE that was already true
   * in the window before the banner's post-hydration mount. Removing
   * "/motion-lab" from HIDE_ON entirely left it green, 5 runs out of 5, while
   * the pill demonstrably rendered on the page.
   *
   * So absence here is asserted as a HOLD, not as an instant. Two things make
   * it real:
   *
   *   1. a hydration anchor — the take controls exist only once a client
   *      effect has resolved the reduced-motion query, so their presence
   *      proves this route hydrated rather than merely responded;
   *   2. a sustained window — the banner mounts on a `setTimeout(0)` that lands
   *      AFTER effects, so a single sample taken at the anchor can still beat
   *      it. Sampling until a deadline is what closes that gap, and it is why
   *      this is not a `waitForTimeout` in disguise: a bare sleep would move
   *      one sample later, while this fails on ANY sample that sees the pill.
   *
   * Asserting one route ON the list and one OFF it also keeps the test from
   * passing by finding nothing anywhere — but note that anti-vacuity argument
   * only ever protected the safe half, which is exactly how the first version
   * slipped through.
   */
  test("the pill is hidden on the surfaces HIDE_ON names, and only those", async ({ page }) => {
    const toggle = page.getByRole("button", { name: /limited access/i });

    // OFF the list: the landing is a narrative surface designed around it.
    await page.goto("/");
    await expect(toggle).toBeVisible();

    // ON the list: app chrome does not leak onto the selection surface.
    await page.goto("/motion-lab");
    await expect(
      page.getByRole("button", { name: /replay the take/i }).first(),
    ).toBeVisible();

    const deadline = Date.now() + 2_000;
    let samples = 0;
    while (Date.now() < deadline) {
      expect(await toggle.count(), `beta pill appeared on /motion-lab after ${samples} clean samples`).toBe(0);
      samples += 1;
      await page.waitForTimeout(100);
    }
    // Guards the guard: if the loop ever degenerates to a single pass, the
    // hold has stopped being a hold and this test is back to what it was.
    expect(samples, "the absence hold collected too few samples to mean anything").toBeGreaterThan(10);
  });

  test("the email-admin action composes to the admin mailbox with the right subject", async ({
    page,
  }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /limited access/i }).click();

    const mailto = page.getByRole("link", { name: "Email admin for beta access" });
    await expect(mailto).toHaveAttribute("href", ADMIN_MAILTO);
    // It only composes an email — never a live navigation target.
    await expect(mailto).toHaveAttribute("href", /body=/);
  });

  test("the sample-inbox link routes to /demo/inbox", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /limited access/i }).click();

    await page
      .getByRole("region", { name: /beta access/i })
      .getByRole("link", { name: /try the sample inbox/i })
      .click();

    await expect(page).toHaveURL(/\/demo\/inbox$/);
    await expect(page.getByRole("heading", { name: "Sample inbox" })).toBeVisible();
  });

  test("the banner is dismissible and stays dismissed across reloads", async ({ page }) => {
    await page.goto("/");

    const toggle = page.getByRole("button", { name: /limited access/i });
    await expect(toggle).toBeVisible();

    await page.getByRole("button", { name: /dismiss beta notice/i }).click();
    await expect(toggle).toHaveCount(0);

    // Persisted in localStorage — still gone after a reload.
    await page.reload();
    await expect(
      page.getByRole("heading", { name: /Your inbox already holds the verdict/i }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: /limited access/i })).toHaveCount(0);
  });

  test("no console errors and no horizontal overflow at 375px with the popover open", async ({
    page,
  }) => {
    const watch = startConsoleWatch(page);
    await page.setViewportSize(MOBILE_375);
    await page.goto("/");

    const toggle = page.getByRole("button", { name: /limited access/i });
    await expect(toggle).toBeVisible();
    await toggle.click();
    await expect(page.getByRole("region", { name: /beta access/i })).toBeVisible();

    await expectNoHorizontalOverflow(page);
    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });
});

test.describe("privacy positioning (landing)", () => {
  test("the privacy section renders with the verified claims", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByRole("heading", { name: /your inbox stays yours/i }),
    ).toBeVisible();

    // The three verified pillars.
    await expect(page.getByRole("heading", { name: /no llm reads your mail/i })).toBeVisible();
    await expect(page.getByRole("heading", { name: /it can run in your browser/i })).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /read-only, by construction/i }),
    ).toBeVisible();

    // Load-bearing, code-verified facts — scoped to the privacy section so the
    // landing's other mentions of the same strings don't trip strict mode.
    const section = page
      .locator("section")
      .filter({ has: page.getByRole("heading", { name: /your inbox stays yours/i }) });
    await expect(section.getByText(/gmail\.readonly/)).toBeVisible();
    await expect(section.getByText(/allowRemoteModels = false/)).toBeVisible();
    await expect(section.getByText(/never handed to one/i)).toBeVisible();
    await expect(section.getByText(/22\.8 MB/)).toBeVisible();
  });

  test("the on-device link opens the sample inbox in a new tab", async ({ page }) => {
    await page.goto("/");
    // Landing → live-app link opens a new tab per the landing standard.
    const [popup] = await Promise.all([
      page.waitForEvent("popup"),
      page.getByRole("link", { name: /see it classify on-device/i }).click(),
    ]);
    await expect(popup).toHaveURL(/\/demo\/inbox$/);
  });
});
