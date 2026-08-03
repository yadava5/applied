import { expect, type Page } from "@playwright/test";

/**
 * Shared E2E helpers.
 *
 * `startConsoleWatch` collects genuine console errors and uncaught page
 * exceptions so a spec can assert a page is clean. It deliberately filters
 * ONE class of noise: the dev-only `eval()` / `unsafe-eval` message React
 * emits because the app ships a strict CSP (`script-src 'self' 'unsafe-inline'`
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
