import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for the JobTracker web app.
 *
 * Design notes:
 * - `webServer` is intentionally UNSET. In CI (`e2e-ci.yml`) we boot the
 *   Next.js dev server and FastAPI backend as separate steps so their
 *   stdout/stderr stream to artifacts and so we can probe their health
 *   endpoints before Playwright starts. Locally, developers run
 *   `pnpm dev` in one terminal and `pnpm e2e` in another.
 * - `baseURL` defaults to localhost but can be overridden with
 *   `PLAYWRIGHT_BASE_URL` to point at a Vercel Preview deployment once
 *   the Preview-URL wiring lands (out of scope for C17).
 * - `video: 'on'` and `trace: 'on-first-retry'` give us post-mortem
 *   artifacts for any red test in CI without bloating every green run
 *   with traces.
 * - There are THREE projects, and two of them exist to defeat the runner's
 *   timezone. See the block above `projects` before touching them.
 */

/** The one browser shape every project shares. */
const desktopChrome = {
  ...devices["Desktop Chrome"],
  viewport: { width: 1440, height: 900 },
};

/**
 * The specs whose assertions depend on WHICH CALENDAR DAY IT IS — the only
 * ones the offset projects below re-run. `demo.spec.ts` was the whole list
 * while it was the only file naming a deadline state (`overdue`, `due in Nd`,
 * the pulse cell's window claim), because /demo is the only surface CI can
 * reach without a Supabase session. `shell.spec.ts` joined it on 2026-08-13:
 * the deadline cell's caption and its detail panel are asserted there against
 * the same date-derived fixtures, so both are re-run at the two extreme
 * offsets. If a day-dependent assertion is ever added to another spec, add
 * that file here too.
 */
const DAY_DEPENDENT_SPECS = /(demo|shell)\.spec\.ts/;

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  // The JSON reporter is the machine-readable half, and it exists for one
  // reason: `e2e-ci.yml` counts the tests that skipped for want of a Supabase
  // session (issue #188) and writes the number to the job summary. Counting
  // that from `list` output would mean parsing prose meant for humans; the JSON
  // carries each test's status AND its skip annotation, so the count is derived
  // rather than pattern-matched out of a log. It lands inside `test-results/`,
  // which Playwright clears BEFORE the run and this job already uploads as an
  // artifact, so the file survives the run and needs no new ignore rule.
  reporter: process.env.CI
    ? [["html", { open: "never" }], ["json", { outputFile: "test-results/results.json" }], ["list"]]
    : [["list"]],
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000",
    trace: "on-first-retry",
    video: "on",
    screenshot: "only-on-failure",
  },
  /*
   * ---------------------------------------------------------------------------
   * WHY THERE ARE TWO EXTRA PROJECTS. DO NOT DELETE THEM AS REDUNDANT.
   * ---------------------------------------------------------------------------
   *
   * The dashboard renders the UTC day on the server and through hydration, then
   * swaps to the READER'S day once there is a reader (`lib/dashboard/useLocalToday.ts`).
   * That swap is a re-render, and it only happens when the browser's local
   * calendar day differs from the UTC one.
   *
   * WHAT THESE PROJECTS DO GATE. /demo's fixtures are stored as OFFSETS ("due
   * in 2d", "filed 16 days ago") against whichever day the store was built
   * for, so the swap has to re-date them (`lib/demo/redate.ts`) or every dated
   * phrase on the page is off by one. GitHub's runners are UTC, so on a
   * UTC-only run the swap never happens, nothing needs re-dating, and every
   * calendar-day assertion in `demo.spec.ts` passes whether or not that fix is
   * present — a regression test structurally incapable of going red, which is
   * the defect shape this repo keeps finding. Measured: with the spec's date
   * oracle reverted to its old UTC form, at 00:44 UTC `demo-utc-minus-10` went
   * red and both `chromium` and `demo-utc-plus-14` stayed green, and with the
   * `+14` slot temporarily pointed at an in-window zone it went red too. So
   * both projects discriminate; which one is red just depends on the hour.
   *
   * WHAT THEY DO NOT GATE, STATED PLAINLY. The reason the swap matters in
   * production is a second defect: React 19 re-asserts a controlled
   * `<select>`'s `value` onto the DOM on every commit that touches its fiber
   * (`commitUpdate` → `updateProperties` → `updateOptions`, no "did it change?"
   * guard). `input`/`change` are DISCRETE events, so React flushes pending work
   * synchronously INSIDE the `input` dispatch; a re-render landing there
   * overwrites the stage the user just picked with the row's old status before
   * `change` fires, `onChange` sees `next === app.status`, and
   * `transport.changeStatus` is never called — no request, no error, nothing
   * visible. `components/dashboard/ApplicationCard.tsx` fixes it with a
   * memoised `StageSelect`.
   *
   * NO TEST IN THIS SUITE EXECUTES THAT RACE, including under these projects.
   * It was checked, not assumed: defeating the bail-out with
   * `memo(StageSelect, () => false)` left "a card moves between stages by drag,
   * and by its select" green 3/3 on every project and 15/15 on the in-window
   * one under load. The race needs a render PENDING at the moment of the input
   * event, and that spec changes the stage long after hydration and the demo's
   * re-dating `setTimeout(0)` have both settled. Catching it needs a spec that
   * holds the window open — throttle the client chunk with `page.route`, then
   * change the stage before hydration completes — which does not exist yet. Do
   * not read a green run here as cover for deleting that memo.
   *
   * `use: { timezoneId }` rather than a `TZ=` env var: Playwright sets the zone
   * on the browser context via CDP, so it is a property of the page under test
   * rather than of whatever shell happened to launch the runner. `TZ` has to
   * survive the whole chain (shell → pnpm → playwright → browser process) and
   * has to be positive-controlled to prove it arrived at all.
   *
   * WHY TWO OFFSET PROJECTS AND NOT ONE — the part that is easy to get wrong.
   * A fixed offset is only inside the window for part of the UTC day:
   *
   *   Pacific/Honolulu is UTC−10 (Hawaii has never observed DST). Its local
   *   day is the PREVIOUS UTC day while the UTC hour is in [00:00, 10:00) and
   *   the same day from 10:00 on. At 00:00 UTC it reads 14:00 yesterday
   *   (differs); at 09:59 UTC, 23:59 yesterday (differs); at 10:00 UTC exactly,
   *   00:00 today (SAME — window closed); at 23:59 UTC, 13:59 today (same).
   *
   *   Pacific/Kiritimati is UTC+14 (Line Islands, no DST). Its local day is the
   *   NEXT UTC day from 10:00 UTC on. At 00:00 UTC it reads 14:00 today (same);
   *   at 09:59 UTC, 23:59 today (same); at 10:00 UTC exactly, 00:00 tomorrow
   *   (differs); at 23:59 UTC, 13:59 tomorrow (differs).
   *
   * [00:00,10:00) ∪ [10:00,24:00) = the whole day, with no gap and no overlap:
   * at EVERY instant exactly one of the two is inside the window, so a CI run
   * at any hour drives the swap for real. One project would leave 58% or 42% of
   * the clock silently uncovered. Both zones are fixed-offset and DST-free —
   * a zone whose offset moves could stop discriminating without anyone noticing,
   * which is the failure this whole arrangement exists to prevent.
   *
   * They run `demo.spec.ts` ONLY (see DAY_DEPENDENT_SPECS), not the whole
   * suite: nothing else asserts anything that depends on the day, and re-running
   * all 14 files twice would triple a serial CI run to catch nothing.
   *
   * `e2e-ci.yml` runs `playwright test` with NO `--project` filter precisely so
   * that this file is the single place projects are declared. If you re-add a
   * filter there, these two stop running and the gate is decoration.
   */
  projects: [
    {
      // Pinned to UTC rather than left to inherit the host's zone. CI is
      // already UTC, so this changes nothing there — but locally it means the
      // baseline is the same server-agreeing, never-swaps case CI runs, and
      // the two projects below are a deliberate contrast rather than an
      // accident of where the developer lives. Unpinned, a developer in
      // Honolulu would silently have no UTC coverage at all, and one in a DST
      // zone would have a baseline that changes twice a year.
      name: "chromium",
      use: { ...desktopChrome, timezoneId: "UTC" },
    },
    {
      name: "demo-utc-minus-10",
      testMatch: DAY_DEPENDENT_SPECS,
      use: { ...desktopChrome, timezoneId: "Pacific/Honolulu" },
    },
    {
      name: "demo-utc-plus-14",
      testMatch: DAY_DEPENDENT_SPECS,
      use: { ...desktopChrome, timezoneId: "Pacific/Kiritimati" },
    },
  ],
});
