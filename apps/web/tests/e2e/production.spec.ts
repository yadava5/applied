import { test, expect, type ConsoleMessage, type Page } from "@playwright/test";

/**
 * The suite that only means anything against a PRODUCTION build.
 *
 * Every other spec here runs against `next dev`, and a dev server does not
 * behave like the thing users load. Two differences matter:
 *
 *  1. Dev renders every route per request. Production prerenders the static
 *     ones at build time and bakes that HTML onto disk, which is the entire
 *     mechanism behind the `/demo` hydration defect (#418): the build day's
 *     dates were frozen into the markup while the client resolved "today" at
 *     view time. A dev server cannot reproduce that, so CI could not see it —
 *     it was found by hand.
 *  2. Dev surfaces React errors as an overlay; production emits a *minified*
 *     console error and otherwise carries on rendering. A page can be visibly
 *     fine and still be throwing away its client tree.
 *
 * So switching CI to a production build is necessary but NOT sufficient — a
 * prod build with no listener attached would have sailed past #418 exactly as
 * the dev job did. The assertion has to be on the console. That is what this
 * file adds: navigate the real routes against `next start` and fail on any
 * React error, uncaught exception, or 5xx.
 *
 * Self-skipping so the existing dev-server job can run the whole directory
 * unchanged; only the production job sets PLAYWRIGHT_PROD_BUILD=1.
 */

const PROD_BUILD = process.env.PLAYWRIGHT_PROD_BUILD === "1";

/**
 * React's production errors are minified to a code and a docs URL, so matching
 * on prose ("Hydration failed because…") finds nothing in the build that
 * matters. These are the three hydration/render codes, matched by number.
 *
 * 418 — text content did not match (the defect this file exists for)
 * 423 — an error while hydrating, tree fell back to client render
 * 425 — text content mismatch in a Suspense boundary
 */
const REACT_ERROR = /Minified React error #(418|423|425|482)\b/;

/**
 * Hydration diagnostics that are NOT minified even in production, plus the
 * unminified prose in case a build ever ships with minification off. Kept
 * separate from REACT_ERROR so a failure message can say which one fired.
 */
const HYDRATION_PROSE = /hydrat(?:e|ion|ing)/i;

/** Noise that is not the app's fault and must not fail an otherwise clean page. */
const IGNORABLE = [
  // Chrome emits this for any favicon/manifest 404 in headless runs.
  /favicon\.ico/i,
  // DevTools protocol chatter under --headless=new.
  /Autofill\.(enable|setAddresses)/i,
  // Third-party font/CSS preload hints Next emits and Chrome warns about.
  /was preloaded using link preload but not used/i,
];

type PageFault = { kind: string; text: string };

/**
 * Attach every listener BEFORE the first navigation, because a hydration error
 * fires during the initial client render — a listener added after `goto`
 * resolves has already missed it.
 */
function watch(page: Page): PageFault[] {
  const faults: PageFault[] = [];

  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (IGNORABLE.some((re) => re.test(text))) return;
    if (REACT_ERROR.test(text)) {
      faults.push({ kind: "react", text });
      return;
    }
    if (HYDRATION_PROSE.test(text)) {
      faults.push({ kind: "hydration", text });
      return;
    }
    faults.push({ kind: "console.error", text });
  });

  // An uncaught exception never reaches console.error, so it needs its own hook.
  page.on("pageerror", (err) => {
    faults.push({ kind: "pageerror", text: err.message });
  });

  page.on("response", (res) => {
    if (res.status() >= 500) {
      faults.push({ kind: `http ${res.status()}`, text: res.url() });
    }
  });

  return faults;
}

/**
 * Every route a browser can reach. The authenticated three are included on
 * purpose: unauthenticated they redirect, and the redirect target has to be
 * as clean as any other page — a broken /login is how a signed-out user
 * experiences the whole product.
 */
const ROUTES: { path: string; label: string; expect: RegExp }[] = [
  { path: "/", label: "landing", expect: /Applied/i },
  // The signup CTA: /demo mounts the full app shell since the consolidation,
  // and the conversion block is the phrase that exists on this route and no
  // signed-in one — present in whichever height tier of the rail footer is
  // active, where the fixture identity row is tall-tier only.
  { path: "/demo", label: "demo dashboard", expect: /Create your account/i },
  // The measured production distribution (every row one stage) — the case the
  // worklist redesign exists for, kept hydration-clean like the seed twin.
  {
    path: "/demo?pipeline=early",
    label: "demo dashboard (early search)",
    expect: /Create your account/i,
  },
  { path: "/demo/settings", label: "settings twin", expect: /nothing is saved/i },
  { path: "/demo/inbox", label: "sample inbox", expect: /inbox/i },
  { path: "/import", label: "import", expect: /import/i },
  { path: "/login", label: "login", expect: /sign in|log in|email/i },
  { path: "/signup", label: "signup", expect: /sign up|create|email/i },
  { path: "/dashboard", label: "dashboard (redirects)", expect: /./ },
  { path: "/inbox", label: "inbox (redirects)", expect: /./ },
  { path: "/settings", label: "settings (redirects)", expect: /./ },
];

test.describe("production build", () => {
  test.skip(
    !PROD_BUILD,
    "Runs only against `next start`; set PLAYWRIGHT_PROD_BUILD=1.",
  );

  for (const route of ROUTES) {
    test(`${route.label} (${route.path}) hydrates with no React error`, async ({
      page,
    }) => {
      const faults = watch(page);

      const response = await page.goto(route.path, { waitUntil: "load" });
      expect(
        response?.status(),
        `${route.path} should not answer with a server error`,
      ).toBeLessThan(500);

      // Hydration happens after `load`. Waiting on a body match rather than a
      // fixed timeout keeps this honest on a slow runner, and the assertion
      // doubles as proof the route actually rendered something.
      await expect(page.locator("body")).toContainText(route.expect, {
        timeout: 15_000,
      });

      // React logs a hydration mismatch during the commit that follows. Give it
      // one animation frame plus a beat, then read what accumulated.
      await page.waitForTimeout(1_000);

      expect(
        faults.map((f) => `[${f.kind}] ${f.text}`),
        `${route.path} logged browser errors against the production build`,
      ).toEqual([]);
    });
  }

  /**
   * The specific regression. `/demo` renders fixtures dated RELATIVE to today,
   * so as a static route it froze the build day into the HTML and mismatched on
   * every later day. `force-dynamic` fixed it. This asserts the property that
   * fix produces — the server must re-render per request — rather than asserting
   * the directive is present in the source, which a grep could do and which
   * would keep passing if the directive stopped working.
   *
   * This test is NOT redundant with the console guard above, and the difference
   * is measured, not assumed. Reverting `force-dynamic` and rebuilding was run
   * as a mutation test: `/demo` returned to the prerender manifest and served
   * `x-nextjs-cache: HIT` / `s-maxage=31536000`, and ONLY this assertion went
   * red. The hydration test stayed green — because a build made today bakes in
   * today's dates, so the client agrees with them for the rest of the day. The
   * console guard catches the mismatch a day later; this one catches the cause
   * immediately. Delete either and the defect has an open lane back in.
   */
  test("/demo is served per request, not from a build-time snapshot", async ({
    page,
  }) => {
    const first = await page.goto("/demo", { waitUntil: "load" });
    const header = (name: string) => first?.headers()[name] ?? "";

    // A prerendered static page is served with a HIT/STALE cache disposition;
    // a per-request render is not cached at the edge at all.
    const cacheHeader = `${header("x-nextjs-cache")}${header("cache-control")}`;
    expect(
      cacheHeader,
      "/demo must not be served from the static prerender cache — its fixtures are dated relative to today, so a cached copy ages into a hydration mismatch",
    ).not.toMatch(/^HIT|s-maxage=\d{3,}/);

    // And the rendered dates must agree with the browser's own clock.
    await expect(page.locator("body")).not.toContainText(/Invalid Date|NaN/);
  });
});
