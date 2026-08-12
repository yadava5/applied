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

/**
 * Pretend this browser was here before.
 *
 * The demo's fixture store is rebuilt on every mount, so a real second visit
 * is byte-identical to the first and the change ledger is honestly quiet — the
 * product must not fabricate a prior visit to look busy. The SPEC may, because
 * it owns the fixture: this writes the marker record the ledger reads
 * (`lib/dashboard/lastLook.ts`) describing the same board minus two rows, with
 * Northstar's interviewing row still at applied and Kestrel's mail-read
 * deadline not yet known. `v` is the record version — if the shape changes and
 * this is not updated, `parseLastLook` rejects it and the ledger renders the
 * first-visit line, which every assertion below then fails on.
 *
 * It seeds ONCE, and the guard is load-bearing. `addInitScript` runs again on
 * every navigation, `page.reload()` included, so an unconditional write would
 * put the seeded visit back after the reload that checks "Mark as seen" stuck
 * — the ledger would read loud again and the test would fail whether the
 * product was right or wrong. A real prior visit is written once and then
 * lives in the browser; so is this one.
 */
async function seedPriorVisit(page: Page): Promise<void> {
  await page.addInitScript(() => {
    if (window.localStorage.getItem("applied:lastlook:demo") !== null) return;
    // ONE anchor day, with every date below written as an offset from it —
    // the same shape `demoData.ts` seeds the fixtures with. Which day the
    // anchor IS does not matter (this one is UTC; the board re-dates itself
    // onto the reader's local day when the two differ): a stored deadline is
    // measured against its own row's filed day, so a record written in one day
    // basis reads correctly against a board settled in another. What matters
    // is that a row's `d` and `f` come from the SAME anchor, which is why they
    // share one.
    const anchor = Date.parse(`${new Date().toISOString().slice(0, 10)}T00:00:00Z`);
    const day = (offset: number) =>
      new Date(anchor + offset * 86_400_000).toISOString().slice(0, 10);
    const dueDay = (offset: number) => `${day(offset)}T23:59:59Z`;
    // Fixture ids 1–17 under the board's column words, minus 13 (Copperline)
    // and 14 (Waypoint Robotics) — the two "filed" rows. Id 1 (Northstar, now
    // interviewing) sits at applied; id 16 (Kestrel) carries no deadline yet.
    const stages: Record<string, string> = {
      1: "applied",
      2: "applied",
      3: "applied",
      4: "applied",
      5: "closed",
      6: "applied",
      7: "applied",
      8: "applied",
      9: "applied",
      10: "closed",
      11: "closed",
      12: "applied",
      15: "interviewing",
      16: "interviewing",
      17: "interviewing",
    };
    const rows: Record<string, { s: string; d?: string; f?: string }> = {};
    for (const [id, s] of Object.entries(stages)) rows[id] = { s };
    // A deadline never travels without the filed day it is measured against —
    // the record `snapshotOf` writes carries both, and so must this one, or the
    // ledger has nothing to tell a re-dated board from a board of new dates.
    // The filed offsets are the fixtures' own (`demoData.ts`: a15 filed 1 day
    // ago, a17 filed 7).
    rows["15"].d = dueDay(9);
    rows["15"].f = day(-1);
    rows["17"].d = dueDay(-2);
    rows["17"].f = day(-7);
    window.localStorage.setItem(
      "applied:lastlook:demo",
      JSON.stringify({
        v: 2,
        scope: "demo",
        at: Date.now() - 15 * 60 * 60 * 1000,
        floor: null,
        rows,
      }),
    );
  });
}

/** The change ledger, scoped so a company name matches it and not the board. */
function ledger(page: Page) {
  return page.getByTestId("since-last-look");
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

  test("the two type voices hold: product speaks Atkinson, data stays mono", async ({ page }) => {
    // The type system's contract (globals.css): Atkinson Hyperlegible Next is
    // the default voice — anything read as language — and Geist Mono has to
    // earn each appearance as data. Guarded here because the demo mounts the
    // real components; a regression that re-monos the UI (or un-monos the
    // stamps) should fail loudly, not ship silently.
    await page.goto("/demo");

    // The FACE must actually be delivered, not merely declared. Every
    // `font-family` assertion below is satisfied by the size-adjusted fallback
    // ("atkinson Fallback", "Geist Mono Fallback") whose name contains the
    // matched substring — verified by aborting the woff2 at the network, where
    // the text rasterized as Arial and all of these still passed. So the wiring
    // checks stay, and this is the one that can fail on a missing font.
    await expect
      .poll(() => page.evaluate(() => document.fonts.check('16px atkinson')))
      .toBe(true);
    await expect
      .poll(() => page.evaluate(() => document.fonts.check('16px "Geist Mono"')))
      .toBe(true);

    await expect(page.locator("body")).toHaveCSS("font-family", /atkinson/i);
    // The page h1 and the board's structural column labels speak the product voice…
    await expect(page.getByRole("heading", { name: "Pipeline" })).toHaveCSS(
      "font-family",
      /atkinson/i,
    );
    await expect(page.locator(".board-col .label-caps").first()).toHaveCSS(
      "font-family",
      /atkinson/i,
    );
    // …while a card's date stamp (the "quiet Nd" ageing tag rides inside it)
    // and the demo's provenance badge remain data-voice mono.
    await expect(page.getByText(/quiet \d+d/).first()).toHaveCSS("font-family", /Geist Mono/);
    await expect(page.getByText("demo · fixture data · no inbox read")).toHaveCSS(
      "font-family",
      /Geist Mono/,
    );
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
    await expect(page.getByText("19 filed · 16 in motion · 0 offers")).toBeVisible();

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
    await expect(page.getByRole("region", { name: /interviewing — 4/i })).toBeVisible();

    // The accessible path: the per-card stage select.
    await page
      .getByLabel("Change stage for Quarry Data")
      .selectOption("interviewing");
    await expect(page.getByRole("region", { name: /interviewing — 5/i })).toBeVisible();
    await expect(
      page.getByRole("region", { name: /interviewing/i }).getByText("Quarry Data", { exact: true }),
    ).toBeVisible();

    // The pointer path: drag a card into another column.
    const card = page
      .locator("li")
      .filter({ has: page.getByText("Harbor Analytics", { exact: true }) })
      .first();
    // Drop near the TOP of the column, not its centre. Hovering the centre of a
    // 2249px-tall board scrolls the page ~147px between mouse-down and the first
    // move, so the HTML5 `dragstart` fires on whichever card has slid under the
    // cursor — Summit Platform moved while Harbor stayed put, and the count
    // assertion above was satisfied by the wrong card. A real drag has no
    // programmatic scroll between press and move; this is the harness, not the
    // product. The assertion below must keep naming Harbor: asserting whichever
    // card actually moved would restore green by deleting the coverage.
    await card.dragTo(page.getByRole("region", { name: /interviewing/i }), {
      targetPosition: { x: 140, y: 20 },
    });
    await expect(page.getByRole("region", { name: /interviewing — 6/i })).toBeVisible();
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
    //
    // Scoped to the trail's own `<li>`, and that scoping is the assertion.
    // "Your application was received" is BOTH this row's latest signal (the
    // `notes` paragraph the sheet renders straight from the row, above the
    // trail) and the fixture mail's subject, so an unscoped `getByText`
    // matched exactly one element while the trail was still loading and two
    // the moment it arrived. The assertion therefore passed only by beating
    // the detail transport's 250ms delay — and when it won, what it had
    // matched was the notes line, not the trail. Under load it lost: 5 of 12
    // repeats failed on `strict mode violation … resolved to 2 elements`.
    const trail = sheet.getByRole("listitem");
    await expect(trail).toHaveCount(1);
    await expect(trail.getByText("Your application was received")).toBeVisible();
    await expect(trail.getByText("Cedar Labs Talent")).toBeVisible();

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

  test("restoring a row first does not trap the scan in a loop", async ({ page }) => {
    // The defect: restore, then continue, and the receipt came back IDENTICAL
    // to the first pass — still stopped early, still 100 scanned, the offer
    // still there and the restored row removed again. The scanned count never
    // advanced and the offer never resolved, so the visitor could loop for
    // ever, each pass undoing the restore. Continuing after a restore must
    // read exactly like continuing without one.
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
    await expect(surface.getByText(/scanned 100 of roughly 240/)).toBeVisible();

    // Restore FIRST — the row is back on the board and marked as corrected.
    await page.getByRole("button", { name: "Restore Fernworks" }).click();
    await expect(surface.getByText("restored", { exact: true })).toBeVisible();
    await expect(page.getByRole("region", { name: /closed — 3/i })).toBeVisible();

    // …then continue. Same ending as the no-restore path: finished, nothing
    // changed, the full 140 scanned, no offer left to press.
    await surface.getByRole("button", { name: "continue the scan" }).click();
    await expect(surface.getByText("rebuild finished · just now")).toBeVisible({ timeout: 6000 });
    await expect(surface.getByText(/nothing changed · 140 scanned/)).toBeVisible();
    await expect(surface.getByText(/stopped early/)).toHaveCount(0);
    await expect(surface.getByText(/scanned 100 of roughly 240/)).toHaveCount(0);
    await expect(surface.getByRole("button", { name: "continue the scan" })).toHaveCount(0);

    // And the restored row survived the pass — it is a correction, not a
    // suggestion. (The row list on the finished receipt is empty, so this
    // reads the BOARD.)
    await expect(page.getByRole("region", { name: /closed — 3/i })).toBeVisible();
    await expect(
      page.getByRole("region", { name: /closed/i }).getByText("Fernworks", { exact: true }),
    ).toBeVisible();
  });

  test("every close path returns focus to the control that opened the dialog", async ({ page }) => {
    // A keyboard user who dismisses a dialog must land back where they were.
    // Escape and the × did that; a BACKDROP click left focus on <body>,
    // because the browser's own mousedown focus fix-up runs after React has
    // already restored focus and blows it away. Both dialogs on this page are
    // driven, and all three paths are asserted the same way.
    await page.goto("/demo");

    const opener = page.getByRole("button", {
      name: "Open Cedar Labs — Software Engineer, Platform",
    });
    const sheet = page.getByRole("dialog");
    /** The overlay behind the panel — the only backdrop there is. */
    const backdrop = sheet.locator("xpath=..");

    for (const close of ["escape", "close button", "backdrop"] as const) {
      await opener.click();
      await expect(sheet).toBeVisible();
      if (close === "escape") await page.keyboard.press("Escape");
      else if (close === "close button")
        await sheet.getByRole("button", { name: "Close dialog" }).click();
      // Top-left corner of the overlay: outside the right-pinned sheet panel
      // and outside the centred one, for either geometry.
      else await backdrop.click({ position: { x: 5, y: 5 } });
      await expect(sheet).toBeHidden();
      await expect(opener, `focus was lost closing via ${close}`).toBeFocused();
    }

    // The centre-variant dialog, same rule.
    const fileOpener = page.getByRole("button", { name: "File an application" });
    await fileOpener.click();
    const fileDialog = page.getByRole("dialog");
    await expect(fileDialog.getByRole("heading", { name: "File an application" })).toBeVisible();
    await fileDialog.locator("xpath=..").click({ position: { x: 5, y: 5 } });
    await expect(fileDialog).toBeHidden();
    await expect(fileOpener).toBeFocused();
  });

  test("the pulse strip renders all four derived signals over the fixtures", async ({ page }) => {
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

    // Deadlines: the three fixture states, counted, and the most urgent row
    // named. The counts derive from the same `dueInfo` that inks the cards.
    await expect(pulse.getByText(/1 overdue · 1 due ≤2d · 1 later/)).toBeVisible();
    await expect(pulse.getByText(/most urgent · Tidewater Labs/)).toBeVisible();
    await expect(pulse.getByText("overdue 2d", { exact: true })).toBeVisible();

    // Classifier: every fixture row is source="gmail", and nothing is held.
    await expect(pulse.getByText("17 of 17 auto-filed from mail")).toBeVisible();
    await expect(pulse.getByText("queue clear · gate 0.85")).toBeVisible();

    // The card-level ageing tag agrees with the strip's threshold.
    await expect(page.getByText(/quiet \d+d/).first()).toBeVisible();
  });

  test("the pulse strip moves when Sync files fresh mail", async ({ page }) => {
    await page.goto("/demo");
    await expect(page.getByText("17 of 17 auto-filed from mail")).toBeVisible();
    await page.getByRole("button", { name: "Sync new mail from Gmail" }).click();
    // Two fixture rows arrive → the classifier fraction re-derives from the
    // new board. (No assertion on the ageing buckets here: the fixture dates
    // are static while real time passes, so any exact bucket count would rot.)
    await expect(page.getByText("19 of 19 auto-filed from mail")).toBeVisible();
  });

  test("the change ledger claims nothing on a first visit", async ({ page }) => {
    // The first visit has no "last look", so there is nothing to compare
    // against and the 17 rows already on the board are not news. The line says
    // exactly that instead of counting them.
    await page.goto("/demo");
    const band = ledger(page);
    await expect(band).toContainText("No earlier visit recorded in this browser");
    await expect(band).not.toContainText("filed");
    await expect(band.getByRole("button", { name: "Mark as seen" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "since you last looked" })).toHaveCount(0);
  });

  test("a FIRST-VISIT ledger holds its line open, so appearing never moves the board", async ({
    browser,
  }) => {
    // Scope, because the title used to imply the whole feature: this measures
    // the first-visit line only. The loud state — a returning visitor with
    // changes, which is the case the feature exists for — is measured in the
    // test below, and used to shift the board 118.9px while this one passed.
    //
    // The ledger is read out of localStorage, so it has nothing to say until
    // hydration. Rendering NOTHING until then made it appear ~70ms after first
    // paint and push every card down 41.9px — and a pointer that pressed a
    // card inside that window released above it, so the browser retargeted the
    // click to the column's <ul> and the card never opened. That was measured
    // on /demo, and it is what took five tests here red or flaky in CI.
    //
    // The property, stated as geometry rather than as a class name: where the
    // board sits with no script at all — the server's own layout — is where it
    // sits once the ledger has rendered. Any future band that appears above
    // the board without reserving its space fails here.
    const noScript = await browser.newContext({
      javaScriptEnabled: false,
      viewport: { width: 1440, height: 900 },
    });
    const served = await noScript.newPage();
    await served.goto("/demo");
    const card = (p: Page) =>
      p.getByRole("button", { name: "Open Cedar Labs — Software Engineer, Platform" });
    const serverBox = await card(served).boundingBox();
    // Asserted on the page that can never hydrate, so it is a fact about the
    // served HTML rather than a race against the effect that replaces it.
    const reservedWhileSilent = await served.getByTestId("since-last-look-reserve").count();
    await noScript.close();

    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.goto("/demo");
    await expect(ledger(page)).toContainText("No earlier visit recorded in this browser");
    const hydratedBox = await card(page).boundingBox();
    const reservedAfter = await page.getByTestId("since-last-look-reserve").count();
    await page.close();

    // The geometry is the claim; the two counts below only name the mechanism.
    expect(serverBox, "the board's Open control must render without script").not.toBeNull();
    expect(hydratedBox).not.toBeNull();
    expect(
      Math.abs((hydratedBox?.y ?? 0) - (serverBox?.y ?? 0)),
      `the board moved ${(hydratedBox?.y ?? 0) - (serverBox?.y ?? 0)}px when the ledger rendered`,
    ).toBeLessThanOrEqual(1);
    expect(reservedWhileSilent, "the served HTML must hold the ledger's line open").toBe(1);
    expect(reservedAfter, "the placeholder must give way to the real line").toBe(0);
  });

  test("a LOUD ledger is the same one line, so a returning visitor's board never moves", async ({
    browser,
  }) => {
    // The state the feature exists for, and the one the reserved line did not
    // cover: a visitor with changes to read. The old block grew with the news
    // — 136.8px for these four rows — and moved the board 118.9px after first
    // paint, which is the same dead-first-click defect the test above pins,
    // in the case that actually happens to a returning user.
    //
    // Same instrument, same claim: the server's own layout is where the board
    // stays. With `javaScriptEnabled: false` the marker can never be read, so
    // the no-script page is the reserved line by construction — exactly what
    // the hydrated loud band has to match.
    const noScript = await browser.newContext({
      javaScriptEnabled: false,
      viewport: { width: 1440, height: 900 },
    });
    const served = await noScript.newPage();
    await served.goto("/demo");
    const card = (p: Page) =>
      p.getByRole("button", { name: "Open Cedar Labs — Software Engineer, Platform" });
    const serverBox = await card(served).boundingBox();
    const reserveBox = await served.getByTestId("since-last-look-reserve").boundingBox();
    await noScript.close();

    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await seedPriorVisit(page);
    await page.goto("/demo");
    const band = ledger(page);
    // Wait for the LOUD state specifically — a quiet band would pass the
    // geometry below while proving nothing about this case.
    await expect(band.getByText("2 filed")).toBeVisible();
    const loudBox = await card(page).boundingBox();
    const bandBox = await band.boundingBox();

    expect(serverBox, "the board's Open control must render without script").not.toBeNull();
    expect(loudBox).not.toBeNull();
    expect(
      Math.abs((loudBox?.y ?? 0) - (serverBox?.y ?? 0)),
      `the board moved ${(loudBox?.y ?? 0) - (serverBox?.y ?? 0)}px when the loud ledger rendered`,
    ).toBeLessThanOrEqual(1);
    // The mechanism, in the same units: the loud band is the line the server
    // held open, not a block that happens to sit somewhere harmless.
    expect(
      Math.abs((bandBox?.height ?? 0) - (reserveBox?.height ?? 0)),
      `the loud band is ${bandBox?.height}px against a reserved ${reserveBox?.height}px`,
    ).toBeLessThanOrEqual(1);

    // Positive control, measured the same way: naming the rows DOES move the
    // board, so the assertions above can fail. A reader presses for that —
    // it is the one movement on this band that is asked for.
    await band.getByRole("button", { name: /Name the rows/ }).click();
    await expect(band.getByText("Copperline", { exact: true })).toBeVisible();
    const openedBox = await card(page).boundingBox();
    expect(
      (openedBox?.y ?? 0) - (loudBox?.y ?? 0),
      "naming the rows must take space — without a real delta here the check above proves nothing",
    ).toBeGreaterThan(40);
    await page.close();
  });

  test("a prior visit turns the ledger loud: what arrived, what moved, what gained a date", async ({
    page,
  }) => {
    await seedPriorVisit(page);
    await page.goto("/demo");
    const band = ledger(page);
    await expect(band.getByRole("heading", { name: "since you last looked" })).toBeVisible();

    // The counts are the arrival line — one line, whatever the news is.
    await expect(band.getByText("2 filed")).toBeVisible();
    await expect(band.getByText("1 moved")).toBeVisible();
    await expect(band.getByText("1 new deadline")).toBeVisible();

    // Nobody is named until the reader asks: the band above the board holds
    // one line, and the space the names need is spent on a press.
    await expect(band).not.toContainText("Copperline");
    await expect(band).not.toContainText("Northstar Systems");
    await band.getByRole("button", { name: /Name the rows/ }).click();

    // …and then every claim names the row it is about, with the column to
    // look in.
    await expect(band.getByText("Copperline", { exact: true })).toBeVisible();
    await expect(band.getByText("Waypoint Robotics", { exact: true })).toBeVisible();
    const moved = band.locator("p").filter({ hasText: "Northstar Systems" });
    await expect(moved).toContainText("applied");
    await expect(moved).toContainText("interviewing");
    await expect(band.locator("p").filter({ hasText: "Kestrel Dynamics" })).toContainText(
      "due in 2d",
    );
    // A row that did not change is never named.
    await expect(band).not.toContainText("Harbor Analytics");

    // The two voices hold here too: names are language, the deadline is data.
    await expect(band.getByText("Copperline", { exact: true })).toHaveCSS(
      "font-family",
      /atkinson/i,
    );
    await expect(band.getByText("due in 2d")).toHaveCSS("font-family", /Geist Mono/);

    // Marking it seen is the only thing that advances the marker, and it holds
    // across a reload — the fixture board is identical on every mount, so any
    // reappearance would be the ledger re-deriving from a stale snapshot.
    await band.getByRole("button", { name: "Mark as seen" }).click();
    await expect(band).toContainText("Nothing new since");
    await expect(band.getByText("2 filed")).toHaveCount(0);
    await page.reload();
    await expect(ledger(page)).toContainText("Nothing new since");
  });

  test("a stage change the visitor makes is never reported back as news", async ({ page }) => {
    // First visit lays the baseline; the second has an unchanged board.
    await page.goto("/demo");
    await expect(ledger(page)).toContainText("No earlier visit recorded");
    await page.reload();
    const band = ledger(page);
    await expect(band).toContainText("Nothing new since");

    await page.getByLabel("Change stage for Quarry Data").selectOption("interviewing");
    await expect(page.getByRole("region", { name: /interviewing — 5/i })).toBeVisible();

    // The card moved. The ledger stays silent — it reports what happened while
    // you were away, and it must not report a move in the WRONG direction
    // while the board catches up with the write either.
    await expect(band).toContainText("Nothing new since");
    await expect(band).not.toContainText("moved");
  });

  test("assessment deadlines render in all three states — and only where a date exists", async ({
    page,
  }) => {
    await page.goto("/demo");
    const tag = (state: string) =>
      page.locator(`[data-testid="deadline-tag"][data-due-state="${state}"]`);

    // One fixture per state, phrase + calendar day, derived from the relative
    // offsets in demoData.ts (dueInDays 9 / 2 / -2).
    //
    // Wrapped in `toPass` because for a reader whose local day differs from
    // UTC this board passes through ONE inconsistent frame, and the assertions
    // below are strict-single locators that a two-element frame kills outright
    // (a strict-mode violation is thrown, not retried). Measured against the
    // production server under Pacific/Honolulu, sampling every 100ms:
    //
    //     145ms  ahead:due in 10d Aug 21 | ahead:due in 3d Aug 14 | overdue:overdue 1d
    //     247ms  ahead:due in  9d Aug 20 | soon:due in 2d Aug 13 | overdue:overdue 2d
    //
    // `useLocalToday` swaps the day AS PART of hydration, while the demo's
    // re-dating of its offset fixtures lands one macrotask later
    // (`DemoDashboard`'s effect defers with `setTimeout(…, 0)`), so in between,
    // a UTC-dated store is bucketed against the local day and Kestrel's
    // deadline is briefly in the wrong cell. It is a real ~100ms flicker on
    // /demo — worth knowing about, not what this test is for — and it made the
    // spec fail roughly one run in six.
    //
    // This does NOT weaken the check. The pre-hydration frame and the settled
    // frame both satisfy every assertion inside; only the transition does not,
    // and only until it ends. Delete the re-dating entirely and the wrong
    // buckets become permanent, so the block never passes and `toPass` times
    // out — which is the regression this file has to catch.
    await expect(async () => {
      await expect(tag("ahead")).toHaveCount(1, { timeout: 2000 });
      await expect(tag("ahead")).toContainText("due in 9d", { timeout: 2000 });
      await expect(tag("soon")).toHaveCount(1, { timeout: 2000 });
      await expect(tag("soon")).toContainText("due in 2d", { timeout: 2000 });
      await expect(tag("overdue")).toHaveCount(1, { timeout: 2000 });
      await expect(tag("overdue")).toContainText("overdue 2d", { timeout: 2000 });
      await expect(tag("overdue")).toContainText("was due", { timeout: 2000 });
    }).toPass({ timeout: 15000 });

    // A deadline is data: the tag speaks mono, like every date stamp.
    await expect(tag("overdue")).toHaveCSS("font-family", /Geist Mono/);

    // The tags sit on the rows that own them…
    const kestrel = page
      .locator("li")
      .filter({ has: page.getByText("Kestrel Dynamics", { exact: true }) });
    await expect(kestrel.locator('[data-testid="deadline-tag"]')).toContainText("due in 2d");
    // …and a row without a due_at renders NOTHING — no placeholder, no prompt.
    const harbor = page
      .locator("li")
      .filter({ has: page.getByText("Harbor Analytics", { exact: true }) });
    await expect(harbor.locator('[data-testid="deadline-tag"]')).toHaveCount(0);
    await expect(page.locator('[data-testid="deadline-tag"]')).toHaveCount(3);

    // The sheet states the deadline's provenance: this one was extracted from
    // mail — and the mail it came from, right below, spells the date out.
    await page
      .getByRole("button", { name: "Open Kestrel Dynamics — Software Engineer, Simulation" })
      .click();
    const sheet = page.getByRole("dialog");
    await expect(sheet.getByText("from your mail")).toBeVisible();
    await expect(sheet.getByText(/Complete your .* assessment by/)).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();
  });

  test("setting a deadline updates the card and the pulse; clearing removes both", async ({
    page,
  }) => {
    await page.goto("/demo");
    const pulse = page.getByTestId("pipeline-pulse");
    await expect(pulse.getByText(/1 overdue · 1 due ≤2d · 1 later/)).toBeVisible();

    // Cedar Labs (applied) has no deadline; give it one 5 days out.
    //
    // LOCAL calendar days, not UTC. A date input holds what the user typed,
    // and the card now buckets it against the reader's own midnight — so a
    // UTC-derived day here reads as `due in 6d` against this `due in 5d`
    // whenever the browser sits in the UTC-offset window (New York after
    // 20:00, Tokyo before 09:00). The old comment claimed UTC was "the way
    // the app computes everything", which is exactly the assumption the
    // local-day fix removed.
    //
    // `Intl("en-CA")` yields YYYY-MM-DD, and is computed independently of the
    // app's own helper (which hand-assembles the local accessors), so this
    // stays an oracle rather than a restatement of the code under test.
    //
    // Evaluated IN THE PAGE, not in this Node process. The two are different
    // zones now: the offset projects set the browser's zone per context
    // (`playwright.config.ts`), while this file runs in whatever zone the
    // runner's OS is in. Computed here it read the RUNNER's day and was right
    // only by the accident of both being the same machine — under
    // `demo-utc-plus-14` it produced `due in 3d`, and under the UTC-pinned
    // `chromium` project on a US-evening machine, `due in 4d`. `page.evaluate`
    // asks the browser under test what day it is, which is the only zone the
    // assertion below is about.
    const dayISO = await page.evaluate(() =>
      new Intl.DateTimeFormat("en-CA").format(new Date(Date.now() + 5 * 24 * 60 * 60 * 1000)),
    );
    const cedar = page
      .locator("li")
      .filter({ has: page.getByText("Software Engineer, Platform", { exact: true }) });
    await expect(cedar.locator('[data-testid="deadline-tag"]')).toHaveCount(0);

    await page
      .getByRole("button", { name: "Open Cedar Labs — Software Engineer, Platform" })
      .click();
    const sheet = page.getByRole("dialog");
    const deadline = sheet.getByTestId("detail-deadline");
    await deadline.getByRole("button", { name: "Add a deadline" }).click();
    await deadline.getByLabel(/Deadline date/).fill(dayISO);
    await deadline.getByRole("button", { name: "Save deadline" }).click();

    // The sheet shows the new claim and WHOSE claim it is.
    await expect(deadline.getByText("due in 5d", { exact: false })).toBeVisible();
    await expect(deadline.getByText("set by you")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();

    // The card gained the tag; the pulse cell re-derived.
    await expect(cedar.locator('[data-testid="deadline-tag"]')).toContainText("due in 5d");
    await expect(pulse.getByText(/1 overdue · 1 due ≤2d · 2 later/)).toBeVisible();

    // Clearing is one click, obviously reversible — the Add control returns —
    // and both surfaces drop the date.
    await page
      .getByRole("button", { name: "Open Cedar Labs — Software Engineer, Platform" })
      .click();
    await deadline.getByRole("button", { name: /Clear the deadline/ }).click();
    await expect(deadline.getByRole("button", { name: "Add a deadline" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();

    await expect(cedar.locator('[data-testid="deadline-tag"]')).toHaveCount(0);
    await expect(pulse.getByText(/1 overdue · 1 due ≤2d · 1 later/)).toBeVisible();
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
    await expect(pulse.getByText("17 of 17 auto-filed from mail")).toBeVisible();
    await expect(pulse.getByText("queue clear · gate 0.85")).toBeVisible();
    // The change ledger carries no animation at all, so there is nothing for
    // this mode to collapse — its sentence is simply present.
    await expect(ledger(page)).toContainText("No earlier visit recorded in this browser");
    // The deadline surfaces are content, not motion: all three tags and the
    // pulse counts render statically too.
    await expect(page.locator('[data-testid="deadline-tag"]')).toHaveCount(3);
    await expect(pulse.getByText(/1 overdue · 1 due ≤2d · 1 later/)).toBeVisible();
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
