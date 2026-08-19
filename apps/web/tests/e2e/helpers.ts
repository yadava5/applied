import { expect, type Page } from "@playwright/test";

/**
 * Shared E2E helpers.
 *
 * `startConsoleWatch` collects genuine console errors and uncaught page
 * exceptions so a spec can assert a page is clean. It deliberately filters
 * ONE class of noise: the dev-only `eval()` / `unsafe-eval` message React
 * emits because the app ships a strict CSP (`script-src 'self' 'nonce-…'
 * 'strict-dynamic'`
 * — no `unsafe-eval`; see `next.config.ts`). React itself prints
 * "React will never use eval() in production mode", i.e. this line cannot
 * appear in a production build; it only shows under `next dev`, which is how
 * CI serves the app (`.github/workflows/e2e-ci.yml`). Everything else — real
 * errors and uncaught exceptions — is kept.
 */
const DEV_ONLY_NOISE = [
  /eval\(\) is not supported in this environment/i,
  /unsafe-eval/i,
  /React requires eval\(\)/i,
  /React will never use eval\(\)/i,
];

function isDevOnlyNoise(text: string): boolean {
  return DEV_ONLY_NOISE.some((re) => re.test(text));
}

export interface ConsoleWatch {
  errors: string[];
}

export function startConsoleWatch(page: Page): ConsoleWatch {
  const watch: ConsoleWatch = { errors: [] };

  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (isDevOnlyNoise(text)) return;
    watch.errors.push(text);
  });

  page.on("pageerror", (err) => {
    const text = err.message ?? String(err);
    if (isDevOnlyNoise(text)) return;
    watch.errors.push(`pageerror: ${text}`);
  });

  return watch;
}

/**
 * Assert the page does not scroll horizontally at the current viewport — the
 * classic mobile-layout regression. A 1px tolerance absorbs sub-pixel rounding.
 */
export async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => {
    const doc = document.documentElement;
    return {
      scrollWidth: doc.scrollWidth,
      clientWidth: doc.clientWidth,
      innerWidth: window.innerWidth,
    };
  });
  expect(
    overflow.scrollWidth,
    `horizontal overflow: scrollWidth=${overflow.scrollWidth} > innerWidth=${overflow.innerWidth}`,
  ).toBeLessThanOrEqual(overflow.innerWidth + 1);
}

export const MOBILE_375 = { width: 375, height: 812 };

/**
 * WHERE the needs-review queue sits inside the worklist, read off the DOM
 * rather than off the URL or the preference that asked for it.
 *
 * Presence alone would be a check that cannot fail: if a `before` request
 * silently rendered in the `after` slot, an assertion about the queue existing
 * would still pass and the two states would be one state measured twice. The
 * queue and the stage groups are all direct <section> children of the pane, so
 * their order settles it.
 *
 * Shared, not duplicated: `shell.spec.ts` drives the slots from the
 * `/demo/shell?queue=` harness knob and this probe is what keeps that knob
 * honest; `settings.spec.ts` drives them from a real notification PREFERENCE
 * (#216) and needs the identical reading, or the two specs could disagree
 * about what "before" means.
 */
export async function queuePlacement(page: Page): Promise<string> {
  return page.evaluate(() => {
    const pane = document.querySelector('[data-testid="worklist-pane"]');
    if (!pane) return "no pane";
    const kids = Array.from(pane.children);
    const queue = kids.find((el) => el.id === "needs-classification");
    if (!queue) return "absent";
    const firstGroup = kids.find((el) => el.tagName === "SECTION" && el !== queue);
    if (!firstGroup) return "no stage groups";
    return kids.indexOf(queue) < kids.indexOf(firstGroup) ? "before" : "after";
  });
}
