import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, MOBILE_375, startConsoleWatch } from "./helpers";

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

/** The sync surface's own live regions, scoped off its `data-sync-surface`.
 *  The sync STATUS line specifically is `[data-sync-status]` within it: the
 *  surface holds a second `role="status"` since #81 (the `+`'s filing
 *  receipt), so a bare-role locator resolves to two elements. */
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

    // The board twin has no in-page h1 anymore (the signed-in shell's top bar
    // carries the route title); its one line of state is the anchor.
    await expect(page.getByText("17 filed · 14 open · 0 offers")).toBeVisible();
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
    await expect.poll(() => page.evaluate(() => document.fonts.check("16px atkinson"))).toBe(true);
    await expect
      .poll(() => page.evaluate(() => document.fonts.check('16px "Geist Mono"')))
      .toBe(true);

    await expect(page.locator("body")).toHaveCSS("font-family", /atkinson/i);
    // The board's state line and its structural column labels speak the
    // product voice…
    await expect(page.getByText("17 filed · 14 open · 0 offers")).toHaveCSS(
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
    await expect(syncSurface(page).locator("[data-sync-status]")).toContainText("2 filed, 3 already known");
    // …and the board actually gained the two filed fixture rows.
    await expect(page.getByRole("region", { name: /applied — 12/i })).toBeVisible();
    await expect(page.getByText("Twitch", { exact: true })).toBeVisible();
    // …and the totals carry the NEW numbers. Since #160 they never leave the
    // row at all: the status rides beside them and borrows the change
    // ledger's width instead (shell.spec's zero-shift test guards both halves
    // — that the row still never grows, and that the numbers stay put while
    // it checks). So what this waits on is the store, not the slot; the
    // generous timeout stays because SYNCED_NOTE_MS still gates the ledger's
    // own return, and with no decay one sync hid the ledger for the session.
    await expect(page.getByText("19 filed · 16 open · 0 offers")).toBeVisible({
      timeout: 15_000,
    });

    // A second sync has nothing new, and the cursored zero case says exactly
    // that — never a claim about a window it did not check.
    await page.getByRole("button", { name: "Sync new mail from Gmail" }).click();
    // Shortened for width (#160): the old sentence measured 231px in this
    // row's 208px status slot at 1024 and was clipped mid-word. `toContainText`
    // so the measured duration the receipt now appends ("· 1 s") does not
    // make this assertion race the fixture's own timing.
    await expect(syncSurface(page).locator("[data-sync-status]")).toContainText(
      "no new mail since last sync",
    );
  });

  test("rows are even: a missing role never changes a row's height", async ({ page }) => {
    // Half of the raggedness complaint, measured: 8 of the real board's 29
    // live rows have no role, and the old cards rendered them visibly shorter.
    // The worklist row keeps a fixed skeleton — company and the role slot
    // share one line, and an absent role prints the honest placeholder — so a
    // role-less row (Beacon Health, the fixture for this case) must measure
    // exactly as tall as a role-carrying one.
    await page.setViewportSize({ width: 1600, height: 1000 });
    await page.goto("/demo");

    const beacon = page
      .locator("li")
      .filter({ has: page.getByText("Beacon Health", { exact: true }) })
      .first();
    await expect(beacon.getByText("role not captured")).toBeVisible();
    const quarry = page
      .locator("li")
      .filter({ has: page.getByText("Quarry Data", { exact: true }) })
      .first();

    const beaconBox = await beacon.boundingBox();
    const quarryBox = await quarry.boundingBox();
    expect(beaconBox, "role-less row renders").not.toBeNull();
    expect(quarryBox, "role-carrying row renders").not.toBeNull();
    expect(Math.abs(beaconBox!.height - quarryBox!.height)).toBeLessThanOrEqual(2);

    // And the full role is always reachable on the row itself: it may wrap
    // rather than ellipsize its discriminating tail, with the complete text
    // in `title` as the floor. (A singleton's role — Northstar's rows sit
    // inside a collapsed employer set on this view.)
    await expect(page.getByTitle("Software Engineer, Platform")).toBeVisible();
  });

  test("a card moves between stages by drag, and by its select", async ({ page }) => {
    await page.goto("/demo");
    await expect(page.getByRole("region", { name: /interviewing — 4/i })).toBeVisible();

    // The accessible path: the per-card stage select.
    await page.getByLabel("Change stage for Quarry Data").selectOption("interviewing");
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
    // cursor — the neighbouring card moved while Harbor stayed put, and the count
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
    // The shared handle for BOTH detail geometries (#157): at the suite's
    // 1440 default this is the docked pane; below `lg` it is the sheet's
    // content. The mail-trail contract is identical either way.
    const sheet = page.getByTestId("application-detail");
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
    await expect(syncSurface(page).locator("[data-sync-status]")).toContainText(
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
    //
    // Below `lg` on purpose: the card detail renders as this sheet (with the
    // backdrop the third path clicks) only under 1024, the dock floor — from
    // `lg` up it docks as a pane with no backdrop at all, and that
    // geometry's close/focus contract is the next test's. The centre-variant
    // dialog exists at every width; it just shares the page.
    await page.setViewportSize({ width: 960, height: 800 });
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

  test("from lg the detail docks beside the worklist — no overlay, and ↑/↓ traverse the board", async ({
    page,
  }) => {
    // #157, the accepted geometry at the suite's 1440 default (docked from
    // `lg` — 1024 — since the threshold fix): the detail is a PANE in the
    // board's own row, not a modal — the worklist stays readable and usable
    // while a card is open, because the overlay's exclusivity contract was
    // itself the complaint.
    await page.goto("/demo");

    const opener = page.getByRole("button", {
      name: "Open Cedar Labs — Software Engineer, Platform",
    });
    await opener.click();
    const pane = page.getByTestId("application-detail");
    await expect(pane).toBeVisible();
    await expect(pane).toBeFocused();
    // Docked means NOT modal: no dialog role, no backdrop, no scroll lock.
    await expect(page.getByRole("dialog")).toHaveCount(0);

    // The rows fold their stage select + Gmail slot while the pane is open —
    // the 176px that pay for its width. Since #173 the fold is a container
    // query on the worklist's own measure (< 32rem folds, display not
    // unmount — hence :visible, not node counts): /demo's max-w-6xl run
    // leaves 504px beside the open pane at the suite's 1440 default, under
    // the floor, so every per-row select is folded here and the pane's own
    // stage control is the one left standing. The signed-in shell measures
    // 588px+ at 1280+ and KEEPS its row controls; /demo/shell carries that
    // geometry. Exactly one row carries the open mark.
    await expect(page.locator("select[id^='detail-status-']")).toHaveCount(1);
    await expect(page.locator("select[id^='status-']:visible")).toHaveCount(0);
    await expect(page.locator("[data-detail-open]")).toHaveCount(1);

    // "N of M · ↑ ↓": the header reports position over the board's visible
    // order, and the arrow keys move through it without closing anything.
    const counter = pane.locator("header").getByText(/^\d+ of \d+$/);
    await expect(counter).toBeVisible();
    const start = (await counter.textContent())!.split(" of ").map(Number);
    const [n, m] = start;
    expect(m).toBeGreaterThan(1);
    const step = n < m ? 1 : -1;
    const heading = pane.getByRole("heading");
    const startCompany = await heading.textContent();
    await page.keyboard.press(step === 1 ? "ArrowDown" : "ArrowUp");
    await expect(counter).toHaveText(`${n + step} of ${m}`);
    await expect(heading).not.toHaveText(startCompany!);
    await page.keyboard.press(step === 1 ? "ArrowUp" : "ArrowDown");
    await expect(counter).toHaveText(`${n} of ${m}`);

    // The board behind the pane is still a work surface: another row's
    // opener works directly, retargeting the pane — no close, no reopen.
    await page.getByRole("button", { name: /^Open Harbor Analytics/ }).click();
    await expect(pane.getByRole("heading", { name: "Harbor Analytics" })).toBeVisible();

    // Escape closes the pane; focus is NOT yanked from the control the user
    // chose since — it stays on the opener they clicked last. The folded
    // controls come back with the width.
    await page.keyboard.press("Escape");
    await expect(pane).toBeHidden();
    await expect(page.getByRole("button", { name: /^Open Harbor Analytics/ })).toBeFocused();
    await expect(page.locator("select[id^='status-']:visible")).not.toHaveCount(0);
  });

  test("the pulse renders all four derived signals in the board's band", async ({ page }) => {
    await page.goto("/demo");
    // ONE copy, and it is the board's full-width band — back in the
    // dashboard's content area, where the owner keeps putting it. The stage
    // spine (#136) and the shell rail (PR #122) are the closed homes.
    const pulse = page.getByTestId("pipeline-pulse");
    await expect(pulse).toHaveCount(1);
    await expect(page.getByTestId("pipeline-board").getByTestId("pipeline-pulse")).toBeVisible();
    await expect(
      page.locator('aside[aria-label="Stages"]').getByTestId("pipeline-pulse"),
    ).toHaveCount(0);

    // Momentum: exactly 30 day-bars plus the delta sentence derived from them
    // (#156 — daily resolution; weekly buckets flattened real filing bursts).
    await expect(pulse.getByTestId("pulse-day")).toHaveCount(30);
    // The week's filings must be NON-ZERO, the same shape as the quiet
    // assertion below and for the same reason: `/this wk/` alone matches
    // "0 this wk", so it is green on exactly the defect it looks like it
    // guards. applied#80 was that defect — the fixtures were absolute dates,
    // the demo's first number aged to 0, and no spec noticed for 28 days.
    //
    // Safe at both offset projects: the seeds inside the 7-day window are at
    // 1,2,3,3,5,6 days (`demoData.ts`), so the count is 6, and the ±1 day a
    // UTC−10/+14 reader's calendar can shift it by moves it to 5 or 7 — never
    // near 0. It is a staleness gate, not a fixture-census one; the exact
    // count deliberately is not asserted so re-spreading the seeds does not
    // have to touch this line.
    await expect(pulse.getByText(/[1-9]\d* this wk/)).toBeVisible();

    // Ageing: the fixture board's open rows are weeks old, so the quiet share
    // is non-zero. `\d+` would also match "0 quiet", which is the claim this
    // is here to make — so require a non-zero leading digit.
    await expect(pulse.getByText(/[1-9]\d* quiet/)).toBeVisible();

    // Deadlines: the claim the cell makes about the three fixture states, and
    // the most urgent row named on the cell's label line. The claim derives
    // from the same `dueInfo` that inks the cards, and it is a claim rather
    // than a bucket recitation since 2026-08-13 — the row due later is real,
    // counted, and deliberately silent here (`deadlineCaption`). (Name and
    // phrase are separate spans — the name truncates before the phrase ever
    // does — so they are asserted separately rather than as one string.)
    await expect(pulse.getByText(/1 overdue · 1 due within 2 days/)).toBeVisible();
    await expect(pulse.getByText("next ·")).toBeVisible();
    await expect(pulse.getByText("Tidewater Labs")).toBeVisible();
    await expect(pulse.getByText("overdue 2d", { exact: true })).toBeVisible();

    // Auto-filed: every fixture row is source="gmail", and nothing is held —
    // said as one whole claim, not as a fraction whose remainder is zero
    // (#158: an unexplained remainder read as rows unaccounted for).
    await expect(pulse.getByText("all 17 from your mail")).toBeVisible();

    // The card-level ageing tag agrees with the pulse's threshold. `.last()`,
    // not `.first()`: the filed stamp renders a phone-width twin earlier in
    // the row's DOM that is display:none at this viewport.
    await expect(page.getByText(/quiet \d+d/).last()).toBeVisible();
  });

  test("the pulse moves when Sync files fresh mail", async ({ page }) => {
    await page.goto("/demo");
    const pulse = page.getByTestId("pipeline-pulse");
    await expect(pulse.getByText("all 17 from your mail")).toBeVisible();
    await page.getByRole("button", { name: "Sync new mail from Gmail" }).click();
    // Two fixture rows arrive → the auto-filed count re-derives from the
    // new board. (No assertion on the ageing buckets here: the fixture dates
    // are static while real time passes, so any exact bucket count would rot.)
    await expect(pulse.getByText("all 19 from your mail")).toBeVisible();
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
    // geometry below while proving nothing about this case. The disclosure
    // trigger exists only on the loud chip, at every chip width ("Mark as
    // seen" no longer marks it: since #212 that control rides inside the
    // panel, so it does not exist until the panel opens).
    await expect(band.getByRole("button", { name: /Name the rows/ })).toBeVisible();
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

    // Naming the rows is an OVERLAY now, not a reflow: the panel floats over
    // the board, so even the one movement this feature used to make on
    // request is no movement at all. The names still appear — over the
    // board, not instead of it.
    await band.getByRole("button", { name: /Name the rows/ }).click();
    await expect(band.getByText("Copperline", { exact: true })).toBeVisible();
    const openedBox = await card(page).boundingBox();
    expect(
      Math.abs((openedBox?.y ?? 0) - (loudBox?.y ?? 0)),
      "the board moved when the names panel opened — the panel must float, not push",
    ).toBeLessThanOrEqual(1);
    await page.close();
  });

  test("a prior visit turns the ledger loud: what arrived, what moved, what gained a date", async ({
    page,
  }) => {
    await seedPriorVisit(page);
    await page.goto("/demo");
    const band = ledger(page);

    // The chip is the arrival line — the counts by kind when its share of the
    // row can say them, the total when it cannot. BOTH renderings are in the
    // DOM (container queries pick one), so a text locator across them is a
    // guaranteed strict-mode violation — assert the one accessible control
    // instead: its name is computed from rendered text only, whichever
    // variant is showing. The opened panel below is the width-independent
    // claim about the content. "Mark as seen" is deliberately NOT here:
    // since #212 it lives inside the panel (asserted after the open below),
    // so the closed chip is one object with one control.
    await expect(band.getByRole("button", { name: /Name the rows/ })).toBeVisible();
    await expect(band.getByRole("button", { name: "Mark as seen" })).toHaveCount(0);

    // Nobody is named until the reader asks: the chip holds its line, and
    // the names appear on a press.
    await expect(band).not.toContainText("Copperline");
    await expect(band).not.toContainText("Northstar Systems");
    await band.getByRole("button", { name: /Name the rows/ }).click();

    // The panel groups by kind — the two-level shape, one press deep.
    await expect(band.getByText("filed", { exact: true })).toBeVisible();
    await expect(band.getByText("moved", { exact: true })).toBeVisible();
    await expect(band.getByText("new deadline", { exact: true })).toBeVisible();

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
    // The control lives in the opened panel (#212): the digest can only be
    // spent with the named rows on screen, which is rule 2's own spirit.
    await expect(band.getByRole("button", { name: "Mark as seen" })).toBeVisible();
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

    // The detail states the deadline's provenance: this one was extracted from
    // mail — and the mail it came from, right below, spells the date out.
    // (`application-detail` is the docked pane at this width — see #157.)
    await page
      .getByRole("button", { name: "Open Kestrel Dynamics — Software Engineer, Simulation" })
      .click();
    const sheet = page.getByTestId("application-detail");
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
    await expect(pulse.getByText(/1 overdue · 1 due within 2 days/)).toBeVisible();

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
    // The docked pane at this width (#157); the deadline contract is the
    // same in both detail geometries.
    const sheet = page.getByTestId("application-detail");
    const deadline = sheet.getByTestId("detail-deadline");
    await deadline.getByRole("button", { name: "Add a deadline" }).click();
    await deadline.getByLabel(/Deadline date/).fill(dayISO);
    await deadline.getByRole("button", { name: "Save deadline" }).click();

    // The sheet shows the new claim and WHOSE claim it is.
    await expect(deadline.getByText("due in 5d", { exact: false })).toBeVisible();
    await expect(deadline.getByText("set by you")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();

    // The card gained the tag; the pulse re-derived. NOT read off the caption:
    // a deadline five days out changes no claim the caption makes (it names
    // what is overdue and what is inside the window, and this row is neither),
    // so asserting the caption here would be a check that cannot fail. The
    // tracked total lives in the cell's own panel, and that is where the new
    // row has to show up.
    await expect(cedar.locator('[data-testid="deadline-tag"]')).toContainText("due in 5d");
    await pulse.getByRole("button", { name: "Deadlines detail" }).click();
    await expect(page.getByTestId("pulse-detail").getByText("4 with a deadline")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("pulse-detail")).toBeHidden();

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
    await expect(pulse.getByText(/1 overdue · 1 due within 2 days/)).toBeVisible();
    await pulse.getByRole("button", { name: "Deadlines detail" }).click();
    await expect(page.getByTestId("pulse-detail").getByText("3 with a deadline")).toBeVisible();
    await page.keyboard.press("Escape");
  });

  test("one employer, one card: the set opens inline and hides no application's stage", async ({
    page,
  }) => {
    await page.goto("/demo");

    // Northstar's three APPLIED applications fold into one employer card;
    // the interviewing one keeps its own row under its own stage heading —
    // grouping is per stage, so a row's true stage is never behind a summary.
    const header = page.getByRole("button", { name: "Northstar Systems — 3 applications" });
    await expect(header).toBeVisible();
    await expect(header).toHaveAttribute("aria-expanded", "false");
    // Collapsed, only the interviewing row's Open control is on the board…
    await expect(page.getByRole("button", { name: /^Open Northstar Systems — / })).toHaveCount(1);
    // …but the stage heading still counts APPLICATIONS, not cards.
    await expect(page.getByRole("region", { name: /applied — 10/i })).toBeVisible();

    // Opening the set reveals every member as a full row: its own Open
    // control, its own stage select — one select per application, no merge.
    await header.click();
    await expect(header).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("button", { name: /^Open Northstar Systems — / })).toHaveCount(4);
    await expect(page.getByLabel("Change stage for Northstar Systems")).toHaveCount(4);
    await header.click();
    await expect(page.getByRole("button", { name: /^Open Northstar Systems — / })).toHaveCount(1);
  });

  test("a company opens as a set view: band on, chips suppressed, clear restores", async ({
    page,
  }) => {
    await page.goto("/demo");
    // The cross-stage chip renders twice while unfiltered: on the applied
    // set's header ("+1 in interviewing") and on the interviewing singleton
    // ("+3 in applied"). Its accessible name is the stable contract.
    const chips = page.getByRole("button", { name: "Show all applications at Northstar Systems" });
    await expect(chips).toHaveCount(2);

    await chips.first().click();
    // The set view disperses the employer card: all four applications render
    // flat, one row each, under their own stage headings.
    await expect(page.getByRole("button", { name: /^Open Northstar Systems — / })).toHaveCount(4);

    // The band states the filter and stops there. It used to add "3
    // applications", a per-stage dot list and the filing span — all three of
    // which the four cards on screen already say, each carrying its own stage
    // and its own date. A count here is the metrics-poster defect coming back
    // through a side door.
    const band = page.getByTestId("company-band");
    await expect(band).toBeVisible();
    await expect(band.getByText("filtered to")).toBeVisible();
    await expect(band.getByText("Northstar Systems")).toBeVisible();
    await expect(band.getByText(/\d+\s+applications?/)).toHaveCount(0);
    // …and the chip must NOT render while the active filter already is this
    // company (a "+N" chip inside Northstar's own set view was the bug).
    await expect(chips).toHaveCount(0);

    // Clear via the band restores the grouped board and the chips.
    await page.getByRole("button", { name: "Stop filtering by Northstar Systems" }).click();
    await expect(page.getByText("Harbor Analytics", { exact: true })).toBeVisible();
    await expect(chips).toHaveCount(2);
    await expect(
      page.getByRole("button", { name: "Northstar Systems — 3 applications" }),
    ).toBeVisible();
  });

  test("a four-deep employer on the early board opens four applications from one card", async ({
    page,
  }) => {
    // `?pipeline=early` holds every row at applied, so Northstar's four
    // applications share ONE stage — the owner's own shape (four Amazon
    // requisitions, all applied), and the case the grouping exists for.
    await page.goto("/demo?pipeline=early");

    const header = page.getByRole("button", { name: "Northstar Systems — 4 applications" });
    await expect(header).toBeVisible();
    // Nothing of Northstar's lives outside this stage → no cross-stage chip.
    await expect(
      page.getByRole("button", { name: "Show all applications at Northstar Systems" }),
    ).toHaveCount(0);
    // The stage heading and the spine keep the real number — 17 applications,
    // however few cards the grouped list draws.
    await expect(page.getByRole("region", { name: /applied — 17/i })).toBeVisible();

    await header.click();
    await expect(page.getByRole("button", { name: /^Open Northstar Systems/ })).toHaveCount(4);
    // Cedar Labs' pair folds the same way.
    await expect(page.getByRole("button", { name: "Cedar Labs — 2 applications" })).toBeVisible();
  });

  test("with reduced motion, every surface is fully present — nothing gated", async ({ page }) => {
    // The motion layer (board layout glides, band/dialog entrances, pulse bar
    // draws) must be pure enhancement: under prefers-reduced-motion the same
    // content renders statically, immediately.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/demo");
    await expect(page.getByText("Beacon Health", { exact: true })).toBeVisible();

    // `toBeVisible()` on a bordered, padded <section> passes on an EMPTY section,
    // so assert the content itself — the three derived signals and thirty drawn
    // bars — exactly as the motion-on test does. A guard that survives its own
    // component rendering nothing is the shape this estate keeps producing.
    const pulse = page.getByTestId("pipeline-pulse");
    await expect(pulse.getByTestId("pulse-day")).toHaveCount(30);
    await expect(pulse.getByText("all 17 from your mail")).toBeVisible();
    // The change ledger carries no animation at all, so there is nothing for
    // this mode to collapse — its sentence is simply present.
    await expect(ledger(page)).toContainText("No earlier visit recorded in this browser");
    // The deadline surfaces are content, not motion: all three tags and the
    // pulse counts render statically too.
    await expect(page.locator('[data-testid="deadline-tag"]')).toHaveCount(3);
    await expect(pulse.getByText(/1 overdue · 1 due within 2 days/)).toBeVisible();
    // A bar with zero drawn height would satisfy the count above.
    const barHeights = await pulse
      .getByTestId("pulse-day")
      .evaluateAll((els) => els.map((el) => el.getBoundingClientRect().height));
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
    // The band's whole content, statically: the state it names and the control
    // that undoes it. `toBeVisible()` on the bordered bar alone would pass on
    // an empty one.
    await expect(band.getByText("filtered to")).toBeVisible();
    await expect(
      band.getByRole("button", { name: "Stop filtering by Northstar Systems" }),
    ).toBeVisible();
    // The set view keeps only Northstar cards, so open one of those. (The
    // docked pane at this width — the set view is exactly where an exclusive
    // overlay hurt most, hiding the sibling applications being compared.)
    await page
      .getByRole("button", { name: "Open Northstar Systems — ML Engineer, Platform" })
      .click();
    await expect(page.getByTestId("application-detail")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("application-detail")).toBeHidden();
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
    await expect(page.getByText("17 filed · 14 open · 0 offers")).toBeVisible();
    await expectNoHorizontalOverflow(page);
    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });
});
