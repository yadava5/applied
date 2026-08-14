import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, MOBILE_375 } from "./helpers";
import { requireSession } from "./session";

/**
 * Geometry for the signed-in /inbox (#197): the page opts into the shell's
 * locked-page contract (`LOCKED_PAGE_CLASS`), so at `lg`+ the view switch and
 * the filter plate hold still while the filed list — and ONLY the filed list
 * — scrolls. The page also surrendered its in-pane title: the rail and the
 * top bar already name the place, so one `sr-only` <h1> carries the outline.
 *
 * WHY SESSION-GATED, AND WHY THE FILE EXISTS AT ALL. `shell.spec.ts` measures
 * the viewport lock on /demo/shell, which mounts the DASHBOARD twin — no
 * fixture route mounts the inbox, and `/demo/inbox` is `SampleInbox`, its own
 * markup entirely. So nothing else in this repo can see a defeated inbox
 * scroll lock: one missing `min-h-0` hands the scroll silently back to
 * <main> with every other gate green, which is this repo's recurring defect
 * shape. In CI these tests skip — loudly, under the #188 token — and they
 * execute wherever a session exists (`E2E_REQUIRE_SESSION=1` makes a missing
 * one a failure).
 *
 * Mutation-tested at introduction (next start, headless Chromium, 2026-08-14,
 * on a scratch route mounting the REAL `AppShellFrame` + locked section +
 * `FiledMailList` over 50 fixture messages, since no local session exists):
 * removing `lg:min-h-0` from `FiledMailList`'s root re-inflates the flex
 * column's content minimum, and the DOCUMENT lock stays green (768/768)
 * while <main> reads scrollHeight 5737 > clientHeight 720 at 1024×768
 * (5737 > 752 at 1280×800), the pane loses its own scroll (5505/5505, and
 * `scrollTop` stays 0 — which is why the "actually scrolled" guard below
 * exists; without it the hold-still assertion passes vacuously), and the
 * rogue sweep names <main> — four independent assertions red per viewport;
 * restored → every reading green. Same evaluate blocks in both harnesses.
 */

/** Both halves of a scroll-lock reading: what CAN scroll vs what fits. */
const heights = (page: Page, selector: string) =>
  page.locator(selector).evaluate((el) => ({
    scroll: el.scrollHeight,
    client: el.clientHeight,
  }));

const docHeights = (page: Page) =>
  page.evaluate(() => ({
    scroll: document.documentElement.scrollHeight,
    client: document.documentElement.clientHeight,
  }));

/**
 * Every element that scrolls vertically besides the sanctioned pane — the
 * same sweep shell.spec.ts runs on the dashboard twin, because "the document
 * holds" and "the pane scrolls" are both satisfiable while a THIRD region
 * scrolls the chrome (PR #122's sidebar did exactly that).
 */
const rogueScrollers = (page: Page, sanctioned: string) =>
  page.evaluate((allowed) => {
    const offenders: string[] = [];
    for (const el of Array.from(document.querySelectorAll("*"))) {
      const oy = getComputedStyle(el).overflowY;
      if (
        (oy === "auto" || oy === "scroll") &&
        el.scrollHeight > el.clientHeight + 1 &&
        el.getAttribute("data-testid") !== allowed
      ) {
        offenders.push(
          `${el.tagName.toLowerCase()}[${
            el.getAttribute("data-testid") ?? el.getAttribute("aria-label") ?? el.className
          }] ${el.scrollHeight}>${el.clientHeight}`,
        );
      }
    }
    return offenders;
  }, sanctioned);

test.describe("inbox — the filed view's scroll lock (needs a session)", () => {
  // 1024 FIRST: `lg` is min-width 1024, so the lock is ON at exactly the
  // width the owner works at — the width where three prior rounds of
  // "responsive fixes" shipped invisible.
  for (const viewport of [
    { width: 1024, height: 768 },
    { width: 1280, height: 800 },
  ]) {
    test(`the filed list is the one scroller and the filters hold still at ${viewport.width}×${viewport.height}`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      await requireSession(
        page,
        "the inbox scroll lock (#197): fixed filters over a scrolling filed list",
      );
      await page.goto("/inbox");

      const searchBox = page.getByRole("searchbox", {
        name: "Search stored mail",
      });
      await expect(searchBox).toBeVisible();

      // ONE heading in the DOM, the sr-only outline entry — counted as nodes,
      // not visibility, because a hidden twin is exactly how the duplicate-h1
      // defect shipped before (see shell.spec.ts's TopBar war story). And the
      // retired subtitle prose must not resurface anywhere on the page.
      await expect(page.locator("h1")).toHaveCount(1);
      await expect(page.locator("h1")).toHaveText("Inbox");
      await expect(page.getByText(/everything Applied has read/)).toHaveCount(0);

      // The document never scrolls, and neither does the shell pane. The
      // <main> half is the load-bearing one: a broken min-h-0 link scrolls
      // the whole page inside <main> while the document lock stays green —
      // measured on the dashboard (993px in a 744px pane, geometry.ts).
      const doc = await docHeights(page);
      expect(doc.scroll, `the document scrolls: ${doc.scroll} > ${doc.client}`).toBeLessThanOrEqual(
        doc.client + 1,
      );
      const main = await heights(page, "main");
      expect(
        main.scroll,
        `<main> scrolls (${main.scroll} > ${main.client}) — the min-h-0 chain is broken somewhere between the page root and the list`,
      ).toBeLessThanOrEqual(main.client + 1);

      // Positive control: the pane genuinely overflows. Without this, every
      // assertion here is satisfied by an account with three messages and the
      // lock is asserted against nothing. It needs more stored mail than one
      // screen holds — the real account carries 50+ messages.
      const pane = page.getByTestId("filed-mail-pane");
      const before = await pane.evaluate((el) => ({
        scroll: el.scrollHeight,
        client: el.clientHeight,
      }));
      expect(
        before.scroll,
        `the filed list does not overflow (${before.scroll} ≤ ${before.client}) — the lock is being asserted against nothing; this account needs more stored mail than one screen holds`,
      ).toBeGreaterThan(before.client + 1);

      // …and it is the ONLY scroller on the page.
      const rogue = await rogueScrollers(page, "filed-mail-pane");
      expect(rogue, `inner panes scroll besides the filed list: ${rogue.join(", ")}`).toEqual([]);

      // Scroll the pane for real; the chrome above it holds to the pixel.
      const viewSwitch = page.getByRole("navigation", { name: "Inbox views" });
      const switchBefore = await viewSwitch.boundingBox();
      const searchBefore = await searchBox.boundingBox();
      const scrolled = await pane.evaluate((el) => {
        el.scrollTop = 600;
        return el.scrollTop;
      });
      expect(scrolled, "the pane did not actually scroll").toBeGreaterThan(0);
      const searchAfter = await searchBox.boundingBox();
      const switchAfter = await viewSwitch.boundingBox();
      expect(
        Math.abs((searchAfter?.y ?? -1) - (searchBefore?.y ?? 1)),
        "the search row moved when the list scrolled",
      ).toBeLessThanOrEqual(1);
      expect(
        Math.abs((switchAfter?.y ?? -1) - (switchBefore?.y ?? 1)),
        "the Filed / Live scan switch moved when the list scrolled",
      ).toBeLessThanOrEqual(1);

      await expectNoHorizontalOverflow(page);
    });
  }

  test("below lg the lock releases and the page flows in <main> — by design", async ({ page }) => {
    await page.setViewportSize(MOBILE_375);
    await requireSession(page, "the inbox lock RELEASING below lg (#197)");
    await page.goto("/inbox");
    await expect(page.getByRole("searchbox", { name: "Search stored mail" })).toBeVisible();

    // The document still never scrolls (the frame is h-dvh at every width)…
    const doc = await docHeights(page);
    expect(doc.scroll, `the document scrolls: ${doc.scroll} > ${doc.client}`).toBeLessThanOrEqual(
      doc.client + 1,
    );

    // …but the pane is NOT its own scroller here: geometry.ts releases the
    // lock below `lg` on purpose (pinning a phone's only content pane behind
    // a nested scroller helps nobody), so <main> carries the scroll and the
    // filter row scrolls away with the flow. This test expects that release;
    // if it goes red because the pane started scrolling on phones, that is a
    // shell-contract change to raise, not a regression to "fix" here.
    const overflowY = await page
      .getByTestId("filed-mail-pane")
      .evaluate((el) => getComputedStyle(el).overflowY);
    expect(overflowY, "the pane must not nest a scroller below lg").toBe("visible");
    const main = await heights(page, "main");
    expect(
      main.scroll,
      `<main> does not scroll (${main.scroll} ≤ ${main.client}) — with 50+ stored messages the flow page must overflow the pane, so something is clipping content`,
    ).toBeGreaterThan(main.client + 1);

    await expectNoHorizontalOverflow(page);
  });

  test("the scan view keeps one heading and the document lock", async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 768 });
    await requireSession(page, "the scan view's single heading + document lock (#197)");
    await page.goto("/inbox?view=scan");
    await expect(page.getByRole("navigation", { name: "Inbox views" })).toBeVisible();

    // Same one-heading contract as the filed view. The scan view's own
    // results pane (`scan-results-pane`) only overflows after a mine has run
    // against a connected Gmail, which no automated environment here can
    // stand up — its scroller shares every class and the same chain with the
    // filed pane asserted above, and the browser pass covers it by hand.
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.locator("h1")).toHaveText("Inbox");

    const doc = await docHeights(page);
    expect(doc.scroll, `the document scrolls: ${doc.scroll} > ${doc.client}`).toBeLessThanOrEqual(
      doc.client + 1,
    );
    await expectNoHorizontalOverflow(page);
  });
});
