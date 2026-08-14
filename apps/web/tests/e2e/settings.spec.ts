import { readFile } from "node:fs/promises";

import { expect, test, type Page } from "@playwright/test";

import { queuePlacement, startConsoleWatch } from "./helpers";
import { requireSession } from "./session";

/**
 * E2E for Settings.
 *
 * Settings is auth-gated (the `(app)` layout bounces a signed-out visitor to
 * `/login`), so the full section coverage below is guarded by
 * `requireSession()` and becomes real the moment the suite runs against a
 * session. Without one it skips — but under the shared, greppable
 * `E2E_NO_SESSION_SKIP (#188):` token that CI counts into the job summary, and
 * `E2E_REQUIRE_SESSION=1` turns those skips into failures. What we CAN drive
 * without a session is the Appearance theme mechanism itself — the same
 * pre-paint script the theme switch persists into — proven on a publicly
 * reachable, theme-honoring page.
 *
 * The guard probes `/dashboard`, not `/settings`: both sit behind the same
 * `(app)` layout, so one probe answers for both, and each test navigates to
 * `/settings` itself once the session is known to be real.
 */

test.describe("appearance theme (public mechanism)", () => {
  test("a saved light theme is applied before paint, and dark restores it", async ({ page }) => {
    const watch = startConsoleWatch(page);

    // Import is a real, theme-honoring page reachable without auth.
    await page.goto("/import");
    await page.evaluate(() => localStorage.setItem("jt-theme", "light"));
    await page.reload();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.dataset.theme))
      .toBe("light");

    await page.evaluate(() => localStorage.setItem("jt-theme", "dark"));
    await page.reload();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.dataset.theme))
      .toBe("dark");

    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });
});

test.describe("settings (via the public /demo/settings twin)", () => {
  // The REAL settings sections over the simulated settings transport — the
  // only executing coverage these components have: `/settings` needs a
  // Supabase session that neither CI nor a local checkout can mint, so the
  // signed-in describe below skips everywhere it matters.

  test("renders every wired section, with the section rail", async ({ page }) => {
    const watch = startConsoleWatch(page);
    await page.goto("/demo/settings");

    await expect(page.getByRole("heading", { name: /^settings$/i })).toBeVisible();
    for (const name of [
      /^profile$/i,
      /^appearance$/i,
      /^gmail$/i,
      /^notifications$/i,
      /your data/i,
      /^account$/i,
    ]) {
      await expect(page.getByRole("heading", { name })).toBeVisible();
    }
    // Classification was a card of prose with no control on it — #208 had
    // already taken the one (inert) control off it — so it is gone from this
    // twin AND from the signed-in page, which render the same sections by
    // construction. Its absence is asserted the way #200's captions are, so a
    // reintroduction fails here rather than shipping: the heading, and the
    // rail entry that would jump to it.
    await expect(page.getByRole("heading", { name: /^classification$/i })).toHaveCount(0);
    await expect(page.getByRole("link", { name: /^classification$/i })).toHaveCount(0);
    await expect(page.getByRole("navigation", { name: /settings sections/i })).toBeVisible();
    // The provenance badge — this page must never read as a real account.
    await expect(page.getByText("demo · fixture account · nothing is saved")).toBeVisible();
    // #199: the sign-in method is DERIVED from the identity list (the fixture
    // is the measured email-only shape), no longer a hardcoded literal.
    await expect(page.getByText("Email & password", { exact: true })).toBeVisible();
    // #200: two of the named captions used to render on this twin — their
    // absence is asserted so a reintroduction fails here.
    await expect(page.getByText(/stored on your account/i)).toHaveCount(0);
    await expect(page.getByText(/export downloads your rows/i)).toHaveCount(0);
    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });

  test("change password: a centred dialog, signup floor enforced, success reported transiently", async ({
    page,
  }) => {
    await page.goto("/demo/settings");

    // #213: the page itself never grows a field — until the dialog opens
    // there is no password input anywhere in the document.
    await expect(page.getByLabel("new password", { exact: true })).toHaveCount(0);

    await page.getByRole("button", { name: /^change password$/i }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    // Everything is scoped to the dialog, and the alert queries have to be:
    // /demo/settings renders other `role="alert"` nodes — DataSection's export
    // failure and AccountSection's delete error — so an unscoped
    // getByRole("alert") is a strict-mode violation rather than an assertion,
    // and dies before it can mean anything. Caught by CI, deterministically,
    // on all three retries.
    const newPassword = dialog.getByLabel("new password", { exact: true });
    const confirm = dialog.getByLabel("confirm new password", { exact: true });
    const submit = dialog.getByRole("button", { name: /^update password$/i });

    // Below the signup floor → refused before any network, on the app's copy.
    await newPassword.fill("short");
    await confirm.fill("short");
    await submit.click();
    await expect(dialog.getByRole("alert")).toContainText(/at least 8 characters/i);

    // Long enough but unconfirmed → the confirm field is the problem.
    await newPassword.fill("long enough password");
    await confirm.fill("long enough passw0rd");
    await submit.click();
    await expect(dialog.getByRole("alert")).toContainText(/don’t match/i);

    // A matching pair runs the whole machine: the dialog closes and success
    // is reported next to the trigger.
    await confirm.fill("long enough password");
    await submit.click();
    await expect(dialog).toBeHidden();
    const status = page.getByRole("status").filter({ hasText: "Password updated" });
    await expect(status).toBeVisible();

    // …and does NOT persist (#213: it used to sit there for the life of the
    // mount). The line clears itself after STATUS_LINGER_MS (4s); the timeout
    // covers the linger plus the exit fade.
    await expect(status).toBeHidden({ timeout: 8000 });
  });

  test("change password: cancelling the dialog leaves no field behind", async ({ page }) => {
    await page.goto("/demo/settings");
    await page.getByRole("button", { name: /^change password$/i }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(page.getByLabel("new password", { exact: true })).toHaveCount(0);
  });

  test("the export produces a real file, named for today, that parses and describes itself", async ({
    page,
  }) => {
    // #217. Nothing exercised the download itself: the blob, the object URL,
    // the anchor and the filename in `DataSection.exportData` were covered by
    // review only, and the file's shape by nothing at all. The twin is where
    // this can run — `/settings` needs a Supabase session CI cannot mint — and
    // it is a fair test of the file because the ENVELOPE is built by the same
    // `buildExportFile` both modes call. Only the rows differ.
    const watch = startConsoleWatch(page);
    await page.goto("/demo/settings");

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: /^export applications and mail \(json\)$/i }).click(),
    ]);

    // The user's own calendar day, not UTC: `toISOString()` here once stamped
    // tomorrow's date on an evening export west of Greenwich. This asserts the
    // shape and that it is the browser's local day — under the UTC project the
    // two agree, so the day half only discriminates in an offset zone; the
    // name itself is what goes red if the download path breaks.
    const localDay = await page.evaluate(() => {
      const now = new Date();
      const pad = (n: number) => String(n).padStart(2, "0");
      return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
    });
    expect(download.suggestedFilename()).toMatch(/^applied-export-\d{4}-\d{2}-\d{2}\.json$/);
    expect(download.suggestedFilename()).toBe(`applied-export-${localDay}.json`);

    const path = await download.path();
    expect(path).toBeTruthy();
    const file = JSON.parse(await readFile(path!, "utf8"));

    // A file opened six months from now has no context but its own envelope.
    expect(file.source).toBe("Applied");
    expect(Number.isNaN(Date.parse(file.exported_at))).toBe(false);
    expect(String(file.about.excluded)).toMatch(/credentials/i);

    // Real rows, and counts DERIVED from them — the summary and the contents
    // cannot disagree, which is the whole point of deriving them.
    expect(Array.isArray(file.applications)).toBe(true);
    expect(Array.isArray(file.messages)).toBe(true);
    expect(file.applications.length).toBeGreaterThan(0);
    expect(file.counts.applications).toBe(file.applications.length);
    expect(file.counts.messages).toBe(file.messages.length);
    expect(file.applications[0]).toHaveProperty("company");
    expect(file.applications[0]).toHaveProperty("status");

    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });

  test("the appearance switch is a working radiogroup — the real theme mechanism", async ({
    page,
  }) => {
    await page.goto("/demo/settings");
    const group = page.getByRole("radiogroup", { name: /theme/i });
    await expect(group).toBeVisible();
    await group.getByRole("radio", { name: /light/i }).click();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.dataset.theme))
      .toBe("light");
    // Reset so the run doesn't leave the app themed light.
    await group.getByRole("radio", { name: /dark/i }).click();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.dataset.theme))
      .toBe("dark");
  });

  test("a profile save runs the whole machine, reports Saved, and the report clears itself", async ({
    page,
  }) => {
    await page.goto("/demo/settings");
    const name = page.getByPlaceholder("e.g. Ayush Yadav");
    await name.fill("Sam Fixture II");
    await page.getByRole("button", { name: "Save profile" }).click();
    const saved = page.getByText("Saved", { exact: true });
    await expect(saved).toBeVisible();
    // #213: "Saved" is a report of an event, not a standing fact — it removes
    // itself after STATUS_LINGER_MS rather than asserting the save forever.
    await expect(saved).toBeHidden({ timeout: 8000 });
  });

  /**
   * #216 — THE PREFERENCE-TO-BOARD WIRING, which had no executable check of
   * any kind: `grep "readNotificationPrefs\|reviewAlerts\|buildSubtitle"
   * tests/` matched nothing. `shell.spec.ts` covers the two queue SLOTS well,
   * but drives them from `/demo/shell?queue=`, so it proves the slots work and
   * never that a preference reaches them — `readNotificationPrefs` could have
   * returned constants and stayed green.
   *
   * These two drive the REAL toggles, on the real sections, and read the
   * result off the demo board. The twin's prefs live in a session cookie the
   * demo transport writes (`lib/demo/notificationPrefs.ts`) and the demo pages
   * read on the server — the same topology as the live metadata read — and
   * both flags reach the board through the SAME functions the signed-in page
   * calls (`lib/dashboard/boardPrefs.ts`). That sharing is what gives a
   * demo-driven test purchase on a session-gated surface: inverting
   * `reviewSlotFor` or ignoring `buildSubtitle`'s `weekly` argument fails
   * here AND changes `/dashboard`.
   *
   * Both cases are deliberately non-degenerate. On a board with
   * `needsReview === 0` both `reviewAlerts` branches render nothing, and with
   * `thisWeek === 0` both subtitles are identical (#216 records this as the
   * innocent reason the controls look dead on a real account) — so the queue
   * case forces four held verdicts and the subtitle case runs on the seed
   * fixture, which files several rows inside the last seven days.
   */

  /** The board's one prose data line, inside the sync header row. Scoped:
   *  "this wk" also appears in the pulse band's momentum chart, so an
   *  unscoped text query would pass no matter what the subtitle said. */
  const boardSubtitle = (page: Page) =>
    page.locator("[data-sync-header-row]").getByText(/ filed · /);

  const notificationToggle = (page: Page, name: string) => page.getByRole("switch", { name });

  test("the weekly-summary toggle reaches the board's header line — without waiting out the router cache", async ({
    page,
  }) => {
    const watch = startConsoleWatch(page);
    await page.goto("/demo/settings");

    const weekly = notificationToggle(page, "Weekly summary");
    // The twin seeds from the same cookie the board reads, so a first visit
    // shows the live default: off.
    await expect(weekly).toHaveAttribute("aria-checked", "false");

    // Visit the board FIRST, by client navigation. This is the whole point of
    // the case: that visit puts /demo's RSC payload in Next's client router
    // cache, which `next.config.ts` keeps for 300 s
    // (`experimental.staleTimes.dynamic`, #211). Without a `router.refresh()`
    // on the save below, the second visit re-serves THIS payload and the
    // preference appears to do nothing for the whole window — the defect, and
    // the reason it self-corrects instead of failing outright. The window
    // moved from 30 s to 300 s, which only makes this case harder to pass by
    // accident: a run slow enough to wait the old one out no longer can.
    const toBoard = page.getByRole("link", { name: /dashboard demo/i });
    await toBoard.click();
    await expect(page).toHaveURL(/\/demo$/);
    await expect(boardSubtitle(page)).not.toContainText("this wk");

    // Back to Settings, still without a document load, and flip the pref.
    await page.goBack();
    await expect(page).toHaveURL(/\/demo\/settings$/);
    await weekly.click();
    await expect(weekly).toHaveAttribute("aria-checked", "true");
    await expect(page.getByText("Saved", { exact: true })).toBeVisible();

    // …and the board says so on the very next navigation. The count itself is
    // relative to the fixture dates and the hour of the run, so the assertion
    // is on the fold, not on a number that would go flaky at a day boundary.
    await toBoard.click();
    await expect(page).toHaveURL(/\/demo$/);
    await expect(boardSubtitle(page)).toContainText(/\+\d+ this wk/);

    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });

  test("the needs-review-alerts toggle moves the queue between the board's two slots", async ({
    page,
  }) => {
    const watch = startConsoleWatch(page);
    // Four held verdicts — the fixture queue's collapse threshold, and the
    // non-degenerate case: at zero, neither branch renders anything.
    const board = "/demo/shell?review=4";

    await page.goto("/demo/settings");
    const alerts = notificationToggle(page, "Needs-review alerts");
    await expect(alerts).toHaveAttribute("aria-checked", "false");

    // OFF (the default): held mail waits UNDER the rows.
    await page.goto(board);
    expect(await queuePlacement(page), "queue slot with the pref off").toBe("after");

    // ON: it interrupts the board, above the stage groups.
    await page.goto("/demo/settings");
    await alerts.click();
    await expect(page.getByText("Saved", { exact: true })).toBeVisible();
    await page.goto(board);
    expect(await queuePlacement(page), "queue slot with the pref on").toBe("before");

    // Back off again — asserted in both directions, because a wiring that
    // only ever answers "before" would pass a one-way test.
    await page.goto("/demo/settings");
    await alerts.click();
    await expect(alerts).toHaveAttribute("aria-checked", "false");
    await expect(page.getByText("Saved", { exact: true })).toBeVisible();
    await page.goto(board);
    expect(await queuePlacement(page), "queue slot after switching back off").toBe("after");

    // …and the geometry harness still overrides the preference: shell.spec.ts
    // measures both placements through `?queue=`, and a knob silently
    // shadowed by a cookie would make a third of that suite vacuous.
    await page.goto(`${board}&queue=before`);
    expect(await queuePlacement(page), "?queue=before with the pref off").toBe("before");

    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });

  test("account deletion is gated behind a typed confirmation — and the demo refuses honestly", async ({
    page,
  }) => {
    await page.goto("/demo/settings");
    await page.getByRole("button", { name: /delete account/i }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    const confirmButton = dialog.getByRole("button", { name: /permanently delete/i });
    await expect(confirmButton).toBeDisabled();
    await dialog.getByRole("textbox").fill("DELETE");
    await expect(confirmButton).toBeEnabled();
    // On the twin the transport answers with the one honest difference —
    // nothing exists to delete — through the same error surface the live
    // route uses for a deployment without deletion enabled.
    await confirmButton.click();
    await expect(dialog.getByRole("alert")).toContainText(/simulated account/i);
  });

  test("disconnect opens a confirming dialog; the demo confirm is disabled with a reason, never a dead button that lies", async ({
    page,
  }) => {
    await page.goto("/demo/settings");
    // #213: revocation is no longer one bare click — the trigger opens the
    // same centred dialog family as delete and change-password.
    await page.getByRole("button", { name: /^disconnect$/i }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    // The dialog says what confirming does, in the privacy policy's words.
    await expect(dialog.getByText(/revokes applied’s access at google/i)).toBeVisible();
    // On the twin the POST would 401, so the destructive confirm — not the
    // reviewable flow — is the dead control, with the reason as visible text.
    const confirm = dialog.getByRole("button", { name: /disconnect and revoke/i });
    await expect(confirm).toBeDisabled();
    await expect(dialog.getByText(/simulated account/i)).toBeVisible();
    // Escape backs out without touching anything.
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
  });
});

test.describe("settings sections (signed in — needs a session)", () => {
  test("renders every wired section", async ({ page }) => {
    await requireSession(page, "every wired Settings section rendering on the real /settings");
    await page.goto("/settings");

    // Re-pointed for #199: the visible page name now lives in the shell
    // TopBar's location label; the page keeps exactly one sr-only h1 for the
    // document outline, so this asserts presence-and-uniqueness, not
    // visibility.
    await expect(page.getByRole("heading", { level: 1, name: /^settings$/i })).toHaveCount(1);
    for (const name of [
      /^profile$/i,
      /^appearance$/i,
      /^gmail$/i,
      /^notifications$/i,
      /your data/i,
      /^account$/i,
    ]) {
      await expect(page.getByRole("heading", { name })).toBeVisible();
    }
    // The signed-in half of the absence the twin asserts above.
    await expect(page.getByRole("heading", { name: /^classification$/i })).toHaveCount(0);
  });

  test("the appearance switch is a working radiogroup", async ({ page }) => {
    await requireSession(page, "the Appearance theme radiogroup on the real /settings");
    await page.goto("/settings");
    const group = page.getByRole("radiogroup", { name: /theme/i });
    await expect(group).toBeVisible();
    await group.getByRole("radio", { name: /light/i }).click();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.dataset.theme))
      .toBe("light");
    // Reset so the run doesn't leave the app themed light.
    await group.getByRole("radio", { name: /dark/i }).click();
  });

  test("account deletion is gated behind a typed confirmation", async ({ page }) => {
    await requireSession(page, "the real account-deletion confirmation gate");
    await page.goto("/settings");

    // #218: the deployment's own capability is now server-rendered, and it is
    // a real fork rather than a fallback — a deployment WITH the service-role
    // key and one WITHOUT it are two states this app genuinely ships in, and
    // the second is the one production has been in since it was created. Both
    // branches assert the whole story, so neither can pass by being skipped:
    // either the arming completes, or the user was told before typing why it
    // cannot. What is asserted unconditionally is the part that must hold in
    // both — the confirm is dead until DELETE is typed.
    const unavailable = page.getByText(/deletion isn’t enabled on this deployment/i).first();
    const deletionEnabled = (await unavailable.count()) === 0;

    await page.getByRole("button", { name: /delete account/i }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    const confirmButton = dialog.getByRole("button", { name: /permanently delete/i });
    await expect(confirmButton).toBeDisabled();
    await dialog.getByRole("textbox").fill("DELETE");

    if (deletionEnabled) {
      await expect(confirmButton).toBeEnabled();
    } else {
      // The honest dead-button case: still disabled, and the reason is visible
      // text inside the dialog rather than a surprise after pressing it.
      await expect(confirmButton).toBeDisabled();
      await expect(dialog.getByText(/deletion isn’t enabled on this deployment/i)).toBeVisible();
    }
  });
});
