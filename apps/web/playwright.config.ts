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
 */
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI
    ? [["html", { open: "never" }], ["list"]]
    : [["list"]],
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000",
    trace: "on-first-retry",
    video: "on",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
      },
    },
  ],
});
