import { expect, test, type Page } from "@playwright/test";

import {
  expectNoHorizontalOverflow,
  MOBILE_375,
  startConsoleWatch,
} from "./helpers";

/**
 * E2E for the auth-free product demo (`/demo`).
 *
 * The demo runs the REAL dashboard components — SyncBar, the board, drag, the
 * detail sheet — over an in-memory fixture store (`DemoDashboard`), so this
 * file is the ONLY place the session-gated surfaces get executing coverage:
 * CI has no Supabase session and the `/dashboard` specs skip. What is walked
 * here is the component's own state machine, not a mock of it — only the
 * transport is simulated.
 *
 * (Static board content — search, filters, expanders, the removed metric
 * surfaces — is driven in dashboard.spec.ts, which uses this twin as its
 * stand-in for the auth-gated dashboard.)
 */

/** The sync surface's own live regions, scoped off its `data-sync-surface`. */
function syncSurface(page: Page) {
  return page.locator("[data-sync-surface]");
}

test.describe("live demo (/demo)", () => {
  test("renders the dashboard twin and the decision trace cleanly", async ({ page }) => {
    const watch = startConsoleWatch(page);
    await page.goto("/demo");

    await expect(page.getByRole("heading", { name: "Pipeline" })).toBeVisible();
    await expect(page.getByRole("heading", { name: /decision trace/i })).toBeVisible();
    // Pipeline columns render the fixture applications.
    await expect(page.getByText("Beacon Health")).toBeVisible();
    // The one honest frame for the simulated sync surface.
    await expect(page.getByText("simulated account · nothing is read")).toBeVisible();

    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });

  test("the sync vocabulary holds: one Sync button, nothing named Re-sync", async ({ page }) => {
    // This used to live in the session-gated dashboard spec, where CI could
    // never run it — a check that cannot fail. The demo mounts the same
    // SyncBar, so the retired word is guarded on every run here.
    await page.goto("/demo");
    await expect(page.getByRole("button", { name: "Sync new mail from Gmail" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Sync options" })).toBeVisible();
    await expect(page.getByText(/re-sync/i)).toHaveCount(0);
    await expect(page.getByRole("button", { name: /re-sync/i })).toHaveCount(0);
  });

  test("Sync files the unsynced fixture mail onto the board — and says so", async ({ page }) => {
    await page.goto("/demo");
    await expect(page.getByRole("region", { name: /applied — 10/i })).toBeVisible();

    await page.getByRole("button", { name: "Sync new mail from Gmail" }).click();
    // The additive path reports through the one status line…
    await expect(syncSurface(page).getByRole("status")).toContainText("2 filed, 3 already known");
    // …and the board actually gained the two filed fixture rows.
    await expect(page.getByRole("region", { name: /applied — 12/i })).toBeVisible();
    await expect(page.getByText("Twitch", { exact: true })).toBeVisible();
    await expect(page.getByText("16 filed · 13 in motion · 0 offers")).toBeVisible();

    // A second sync has nothing new, and the cursored zero case says exactly
    // that — never a claim about a window it did not check.
    await page.getByRole("button", { name: "Sync new mail from Gmail" }).click();
    await expect(syncSurface(page).getByRole("status")).toContainText(
      "no new application mail since your last sync",
    );
  });

  test("a card moves between stages by drag, and by its select", async ({ page }) => {
    await page.goto("/demo");
    await expect(page.getByRole("region", { name: /interviewing — 1/i })).toBeVisible();

    // The accessible path: the per-card stage select.
    await page
      .getByLabel("Change stage for Quarry Data")
      .selectOption("interviewing");
    await expect(page.getByRole("region", { name: /interviewing — 2/i })).toBeVisible();
    await expect(
      page.getByRole("region", { name: /interviewing/i }).getByText("Quarry Data"),
    ).toBeVisible();

    // The pointer path: drag a card into another column.
    const card = page
      .locator("li")
      .filter({ has: page.getByText("Harbor Analytics", { exact: true }) })
      .first();
    await card.dragTo(page.getByRole("region", { name: /interviewing/i }));
    await expect(page.getByRole("region", { name: /interviewing — 3/i })).toBeVisible();
    await expect(
      page.getByRole("region", { name: /interviewing/i }).getByText("Harbor Analytics"),
    ).toBeVisible();
  });

  test("a card opens into the mail behind it", async ({ page }) => {
    await page.goto("/demo");

    await page
      .getByRole("button", { name: "Open Cedar Labs — Software Engineer, Platform" })
      .click();
    const sheet = page.getByRole("dialog");
    await expect(sheet).toBeVisible();
    await expect(sheet.getByText("the mail behind this card")).toBeVisible();
    // The verdict trail renders the fixture message with its classification.
    await expect(sheet.getByText("Your application was received")).toBeVisible();
    await expect(sheet.getByText("Cedar Labs Talent")).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();
  });

  test("Rebuild: dialog → receipt naming the removed row → restore puts it back", async ({
    page,
  }) => {
    await page.goto("/demo");
    await expect(page.getByRole("region", { name: /closed — 3/i })).toBeVisible();

    // Rebuild lives behind the options menu, behind an explicit dialog.
    await page.getByRole("button", { name: "Sync options" }).click();
    await page.getByRole("menuitem", { name: /rebuild from gmail/i }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: "Rebuild from Gmail" })).toBeVisible();
    // The forced scope is stated, not offered.
    await expect(dialog.getByText(/scans all mail, including archive/i)).toBeVisible();

    await dialog.getByRole("button", { name: "Rebuild from the last 12 months" }).click();
    // The running line restates the chosen window; the only number ticking is
    // the elapsed clock — never a percentage, here or on the receipt.
    await expect(syncSurface(page).getByRole("status")).toContainText(
      "rebuilding · up to 750 messages · last 12 months · all mail",
    );
    await expect(syncSurface(page)).not.toContainText("%");

    // The receipt names what was removed, row by row.
    await expect(syncSurface(page).getByText("rebuild finished · just now")).toBeVisible();
    await expect(syncSurface(page).getByText("Fernworks")).toBeVisible();
    await expect(syncSurface(page)).not.toContainText("%");
    await expect(page.getByRole("region", { name: /closed — 2/i })).toBeVisible();

    // Per-row restore reverses it on the board, not just on the list.
    await page.getByRole("button", { name: "Restore Fernworks" }).click();
    await expect(syncSurface(page).getByText("restored", { exact: true })).toBeVisible();
    await expect(page.getByRole("region", { name: /closed — 3/i })).toBeVisible();
    await expect(
      page.getByRole("region", { name: /closed/i }).getByText("Fernworks", { exact: true }),
    ).toBeVisible();
  });

  test("the decision trace rows expand on click (real effect)", async ({ page }) => {
    await page.goto("/demo");
    // The first trace row is open by default; open another and assert its
    // adjudication copy appears.
    const offerRow = page.getByRole("button", { name: /offer details inside/i });
    await offerRow.click();
    await expect(page.getByText(/clears the 0.85 gate/i).first()).toBeVisible();
  });

  test("the sample-inbox bridge routes to /demo/inbox", async ({ page }) => {
    await page.goto("/demo");
    await page
      .getByRole("link", { name: /Run a full sample inbox through the real classifier/i })
      .click();
    await expect(page).toHaveURL(/\/demo\/inbox$/);
    await expect(page.getByRole("heading", { name: "Sample inbox" })).toBeVisible();
  });

  test("the beta note is in flow — the floating pill no longer overlaps the board", async ({
    page,
  }) => {
    await page.goto("/demo");
    // The fixed bottom-centre pill is hidden on the board twin; its beta fact
    // renders statically at the end of the page instead.
    await expect(page.getByRole("button", { name: /limited access/i })).toHaveCount(0);
    await expect(page.getByText(/direct Gmail connection is invite-only/i)).toBeVisible();
  });

  test("no horizontal overflow at 375px", async ({ page }) => {
    const watch = startConsoleWatch(page);
    await page.setViewportSize(MOBILE_375);
    await page.goto("/demo");
    await expect(page.getByRole("heading", { name: "Pipeline" })).toBeVisible();
    await expectNoHorizontalOverflow(page);
    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });
});
