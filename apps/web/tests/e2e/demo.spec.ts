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
    // Pipeline columns render the fixture applications. (`exact` everywhere a
    // company is asserted visible: each interactive card also carries an
    // sr-only "Change stage for {company}" label, which substring matching
    // resolves as a second element and trips strict mode.)
    await expect(page.getByText("Beacon Health", { exact: true })).toBeVisible();
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

  test("the populated column claims the space empty ones don't use", async ({ page }) => {
    // A real search is one heavy column and three near-empty ones. An even
    // split starved the only column with cards until four real Amazon roles
    // ellipsized into identical text; now space follows content at desktop.
    await page.setViewportSize({ width: 1600, height: 1000 });
    await page.goto("/demo");
    const applied = await page.getByRole("region", { name: /applied — 10/i }).boundingBox();
    const offered = await page.getByRole("region", { name: /offered — 0/i }).boundingBox();
    expect(applied, "applied column renders").not.toBeNull();
    expect(offered, "offered column renders").not.toBeNull();
    expect(applied!.width).toBeGreaterThan(offered!.width * 1.5);

    // And the full role is always reachable on the card itself: it wraps to
    // two lines rather than ellipsizing its discriminating tail, with the
    // complete text in `title` as the floor.
    await expect(page.getByTitle("ML Engineer, Platform")).toBeVisible();
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
      page.getByRole("region", { name: /interviewing/i }).getByText("Quarry Data", { exact: true }),
    ).toBeVisible();

    // The pointer path: drag a card into another column.
    const card = page
      .locator("li")
      .filter({ has: page.getByText("Harbor Analytics", { exact: true }) })
      .first();
    await card.dragTo(page.getByRole("region", { name: /interviewing/i }));
    await expect(page.getByRole("region", { name: /interviewing — 3/i })).toBeVisible();
    await expect(
      page
        .getByRole("region", { name: /interviewing/i })
        .getByText("Harbor Analytics", { exact: true }),
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

  test("a scan that stops early never claims completion", async ({ page }) => {
    // The defect shape this guards: a bounded scan gave up early and the UI
    // reported "up to date" anyway — converging a real board once took six
    // presses, each reported as completion. A shallow depth-100 rebuild in the
    // simulation stops at its message limit, and the receipt must say so, show
    // how far it got, warn that removals were judged against a partial scan,
    // and offer continue — never the finished heading.
    await page.goto("/demo");
    await page.getByRole("button", { name: "Sync options" }).click();
    await page.getByRole("menuitem", { name: /rebuild from gmail/i }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Number of messages to scan").selectOption("100");
    await dialog.getByRole("button", { name: "Rebuild from the last 12 months" }).click();

    const surface = syncSurface(page);
    await expect(surface.getByText("rebuild stopped early · just now")).toBeVisible({
      timeout: 6000,
    });
    await expect(surface.getByText(/the scan hit its message limit/)).toBeVisible();
    // Gmail's match count is an estimate and is worded as one — no percentage,
    // no bar, same honesty rule as the elapsed clock.
    await expect(surface.getByText(/scanned 100 of roughly 240/)).toBeVisible();
    await expect(surface.getByText("removals were judged against this partial scan")).toBeVisible();
    await expect(surface.getByText(/rebuild finished/)).toHaveCount(0);
    await expect(surface).not.toContainText("%");

    // Continue re-runs the same window; only the pass that actually completed
    // may say finished — and it confirms the board rather than claiming work.
    await surface.getByRole("button", { name: "continue the scan" }).click();
    await expect(surface.getByText("rebuild finished · just now")).toBeVisible({ timeout: 6000 });
    await expect(surface.getByText(/nothing changed · 140 scanned/)).toBeVisible();
    await expect(surface.getByText(/stopped early/)).toHaveCount(0);
  });

  test("the pulse strip renders all three derived signals over the fixtures", async ({ page }) => {
    await page.goto("/demo");
    const pulse = page.getByTestId("pipeline-pulse");
    await expect(pulse).toBeVisible();

    // Momentum: exactly 8 week-bars plus the delta sentence derived from them.
    await expect(pulse.getByTestId("pulse-week")).toHaveCount(8);
    await expect(pulse.getByText(/last 4 wk/)).toBeVisible();

    // Ageing: the fixture board's open rows are weeks old, so the quiet share
    // is non-zero. `\d+` would also match "0 quiet", which is the claim this
    // is here to make — so require a non-zero leading digit.
    await expect(pulse.getByText(/[1-9]\d* quiet ≥2 wk/)).toBeVisible();

    // Classifier: every fixture row is source="gmail", and nothing is held.
    await expect(pulse.getByText("14 of 14 auto-filed from mail")).toBeVisible();
    await expect(pulse.getByText("queue clear · gate 0.85")).toBeVisible();

    // The card-level ageing tag agrees with the strip's threshold.
    await expect(page.getByText(/quiet \d+d/).first()).toBeVisible();
  });

  test("the pulse strip moves when Sync files fresh mail", async ({ page }) => {
    await page.goto("/demo");
    await expect(page.getByText("14 of 14 auto-filed from mail")).toBeVisible();
    await page.getByRole("button", { name: "Sync new mail from Gmail" }).click();
    // Two fixture rows arrive → the classifier fraction re-derives from the
    // new board. (No assertion on the ageing buckets here: the fixture dates
    // are static while real time passes, so any exact bucket count would rot.)
    await expect(page.getByText("16 of 16 auto-filed from mail")).toBeVisible();
  });

  test("a company opens as a set: band on, chips suppressed, clear restores", async ({ page }) => {
    await page.goto("/demo");
    // Three Northstar cards each carry the "+2 at" chip while unfiltered.
    const chips = page.getByRole("button", { name: "Show all applications at Northstar Systems" });
    await expect(chips).toHaveCount(3);

    await chips.first().click();
    // The band names the set…
    const band = page.getByTestId("company-band");
    await expect(band).toBeVisible();
    await expect(band.getByText("Northstar Systems")).toBeVisible();
    await expect(band.getByText(/3 applications/)).toBeVisible();
    // …and the chip must NOT render while the active filter already is this
    // company ("2 more at Northstar" inside Northstar's own set was the bug).
    await expect(chips).toHaveCount(0);
    await expect(page.getByText(/at Northstar Systems/)).toHaveCount(0);

    // Clear via the band restores the board and the chips.
    await page.getByRole("button", { name: "Stop filtering by Northstar Systems" }).click();
    await expect(page.getByText("Harbor Analytics", { exact: true })).toBeVisible();
    await expect(chips).toHaveCount(3);
  });

  test("with reduced motion, every surface is fully present — nothing gated", async ({ page }) => {
    // The motion layer (board layout glides, band/dialog entrances, pulse bar
    // draws) must be pure enhancement: under prefers-reduced-motion the same
    // content renders statically, immediately.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/demo");
    await expect(page.getByText("Beacon Health", { exact: true })).toBeVisible();

    // `toBeVisible()` on a bordered, padded <section> passes on an EMPTY strip,
    // so assert the content itself — the three derived signals and eight drawn
    // bars — exactly as the motion-on test does. A guard that survives its own
    // component rendering nothing is the shape this estate keeps producing.
    const pulse = page.getByTestId("pipeline-pulse");
    await expect(pulse.getByTestId("pulse-week")).toHaveCount(8);
    await expect(pulse.getByText("14 of 14 auto-filed from mail")).toBeVisible();
    await expect(pulse.getByText("queue clear · gate 0.85")).toBeVisible();
    // A bar with zero drawn height would satisfy the count above.
    const barHeights = await pulse.getByTestId("pulse-week").evaluateAll((els) =>
      els.map((el) => el.getBoundingClientRect().height),
    );
    expect(Math.max(...barHeights)).toBeGreaterThan(0);

    // The board's own row-actions menu must keep its accessible name. Branching
    // element type on `useReducedMotion` desynced the server and client trees,
    // which shifted every descendant `useId` and left `aria-labelledby` pointing
    // at an id that no longer existed — for exactly the people this mode serves.
    const trigger = page.getByRole("button", { name: /^Row actions for / }).first();
    await trigger.click();
    const menu = page.getByRole("menu").first();
    await expect(menu).toBeVisible();
    const labelledBy = await menu.getAttribute("aria-labelledby");
    expect(labelledBy).toBeTruthy();
    // Attribute selector, not `#${CSS.escape(id)}` — `CSS` is a browser global
    // and this runs in the Node test context, where referencing it throws
    // before the assertion can mean anything. React's `useId` values also
    // contain characters that are not valid bare CSS id selectors.
    await expect(page.locator(`[id="${labelledBy}"]`)).toHaveCount(1);
    await page.keyboard.press("Escape");

    await page
      .getByRole("button", { name: "Show all applications at Northstar Systems" })
      .first()
      .click();
    const band = page.getByTestId("company-band");
    await expect(band.getByText("Northstar Systems")).toBeVisible();
    await expect(band.getByText(/3 applications/)).toBeVisible();
    // The set view keeps only Northstar cards, so open one of those.
    await page
      .getByRole("button", { name: "Open Northstar Systems — ML Engineer, Platform" })
      .click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toBeHidden();
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
