import { test, type Page } from "@playwright/test";

/**
 * The one gate for every test that needs an authenticated Supabase session.
 *
 * WHY THIS FILE EXISTS (#188). Four spec files — `shell.spec.ts`,
 * `settings.spec.ts`, `dashboard.spec.ts`, `file-application.spec.ts` — hold 13
 * tests behind a session. Each had its own private copy of the same guard:
 * navigate to `/dashboard`, and if the `(app)` layout bounced the visitor to
 * `/login`, `test.skip()` with a reason of its own wording. Both e2e jobs boot
 * the app against a placeholder Supabase project
 * (`NEXT_PUBLIC_SUPABASE_URL: https://example.supabase.co`), so that bounce is
 * unconditional in CI and every one of those 13 tests has skipped on every run
 * the suite has ever done. They have never executed. Not once.
 *
 * That is not a theoretical loss. `shell.spec.ts` asserts
 * `toHaveCount(1)` on `a[aria-current="page"]`, which is exactly the invariant
 * /inbox broke when it shipped TWO current-page elements (#163) — a correct
 * assertion, sitting on top of the defect, unable to see it. PR #184 merged
 * with zero of these tests having run, and the checks were green, because a
 * skip is green.
 *
 * WHAT CHANGED. The skip is still a skip by default: this repo has no seeded
 * test account, minting one is the owner's decision, and it needs credentials
 * that must not live in this tree. So the gap is NOT closed here. What is fixed
 * is that it was also SILENT — four different reason strings, none greppable as
 * a class, no count anywhere an operator would look. Now:
 *
 *   1. Every call site routes through `requireSession()`, so there is one
 *      behaviour and one place to change it.
 *   2. Every skip reason starts with the byte-identical token
 *      `NO_SESSION_SKIP_PREFIX` below, so the whole class is one grep — in a
 *      log, in the HTML report, or in the JSON reporter's output. `e2e-ci.yml`
 *      counts them from that JSON and writes the number to the job summary, so
 *      the size of the hole is visible in the PR checks UI without opening a
 *      log.
 *   3. `E2E_REQUIRE_SESSION=1` turns the skip into a hard failure.
 *
 * WHAT FLIPPING `E2E_REQUIRE_SESSION=1` DOES. It changes the meaning of a
 * missing session from "this environment cannot do this, carry on" to "this
 * environment PROMISED this and did not deliver". Once a seeded account exists
 * and its credentials are wired into the workflow, the owner sets the
 * repository variable `E2E_REQUIRE_SESSION` to `1` — one setting, no code
 * change — and from that moment a broken or expired session fails the job
 * loudly instead of quietly deleting 13 tests from the run. Unset (the default,
 * and what `vars.E2E_REQUIRE_SESSION` evaluates to today) it is inert.
 *
 * `what` is mandatory and has NO default on purpose: a uniform prefix makes the
 * class greppable, and the human tail makes the individual loss readable. A
 * default would let a call site skip without saying what coverage went with it,
 * which is most of what was wrong with the four copies this replaces.
 *
 * THE OTHER GATE, AND WHY IT IS NOT THIS ONE. `production.spec.ts` also skips
 * — 12 tests, on `PLAYWRIGHT_PROD_BUILD !== "1"`. That is a BUILD-MODE gate,
 * not a session gate, and it is satisfied: the `playwright (production build)`
 * job sets the variable and those 12 run and pass there. It is deliberately NOT
 * routed through this helper, because "needs `next start`" and "needs a signed-in
 * user" are different questions with different answers.
 *
 * That distinction is load-bearing, because the two totals add up: a dev-server
 * run reports 25 skips, of which only 13 are this class. Reading 25 as one
 * number is how "the suite covers the signed-in app" survived unexamined. So
 * the count CI publishes is prefix-matched to this file, and it is 13 on BOTH
 * jobs — not 25 on one and 13 on the other. A skip total nobody can attribute
 * to a gate is worth nothing.
 */

/**
 * The one token every no-session skip and no-session failure carries, at the
 * head of the message. Machine-readable on purpose — `e2e-ci.yml` matches on
 * it. If you change it, change the workflow's census step in the same commit;
 * a census that matches nothing reports 0 and looks like good news.
 */
export const NO_SESSION_SKIP_PREFIX = "E2E_NO_SESSION_SKIP (#188):";

/**
 * Reach the authenticated app shell, or refuse to pretend the test ran.
 *
 * Probes `/dashboard` because it is the cheapest route behind the `(app)`
 * layout: signed out, the layout redirects before any API call, so this costs
 * one navigation and needs no backend. Every session-gated route in the app
 * sits behind that same layout, so the probe answers for all of them — a
 * caller that wants a different route navigates there itself after this
 * returns.
 *
 * On success the page is left ON `/dashboard`, which several call sites rely on.
 *
 * @param page the test's page
 * @param what a short human description of the coverage that is lost when there
 *   is no session — e.g. "the app shell's active-state indicator". It is read
 *   by a person scanning a log, so name the behaviour, not the file.
 */
export async function requireSession(page: Page, what: string): Promise<void> {
  await page.goto("/dashboard");
  if (!/\/login/.test(page.url())) return;

  // The prefix leads, unconditionally and byte-identically, so that skips and
  // failures are one grep and the human tail is what varies.
  const head = `${NO_SESSION_SKIP_PREFIX} ${what} — no authenticated Supabase session was reachable (/dashboard bounced to ${page.url()}).`;

  if (process.env.E2E_REQUIRE_SESSION === "1") {
    throw new Error(
      [
        head,
        "",
        "E2E_REQUIRE_SESSION=1 says this environment is supposed to HAVE a session,",
        "so a missing one is a failure, not a skip. Check, in this order:",
        "  1. NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY point at a real",
        "     Supabase project, not the CI placeholder https://example.supabase.co.",
        "  2. The seeded test account still exists and its password has not been rotated.",
        "  3. The step that signs that account in ran, and wrote its storage state where",
        "     Playwright loads it from.",
        "  4. The session has not simply expired — Supabase access tokens are short-lived.",
        "",
        "If this environment genuinely cannot mint a session, unset E2E_REQUIRE_SESSION",
        "and these tests go back to skipping loudly. See issue #188.",
      ].join("\n"),
    );
  }

  // Measured, not assumed: `test.skip()`'s reason reaches the JSON reporter and
  // the HTML report, but NOT the terminal — Playwright 1.59's `list` reporter
  // prints a skipped test's title and nothing else, so a raw CI log shows six
  // dashes and no explanation. That invisibility IS the defect #188 is about,
  // so emit the line ourselves; it is what makes the class greppable in a log
  // as well as countable from the JSON.
  console.log(head);

  test.skip(
    true,
    `${head} Skipped, not failed, because E2E_REQUIRE_SESSION is not "1" — set it to "1" (or the repository variable of the same name) to make this a hard failure. See issue #188.`,
  );
}
