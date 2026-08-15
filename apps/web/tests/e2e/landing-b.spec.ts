import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, MOBILE_375, startConsoleWatch } from "./helpers";

/**
 * E2E for the merged landing candidate (`/landing-b`) — the page that is
 * meant to replace `/`.
 *
 * WHY THIS FILE EXISTS. `landing.spec.ts` visits `/` in all eight of its
 * tests, so nothing in this suite had ever loaded `/landing-b`; the only
 * automated cover was `tests/unit/landing-variants.test.mjs`, which is a
 * SOURCE SCAN. It greps the modules for strings and shapes, which is the
 * right instrument for "no landing page can reach the live transport" and the
 * wrong one for everything this file asserts: the page's two honesty
 * guarantees are GEOMETRIC, and a source scan cannot see a pixel. Both would
 * be silently broken by an ordinary copy edit with every existing gate green:
 *
 *  1. THE PROVENANCE LINE. The descent's exhibit ends with "A synthetic email
 *     — the verdicts are computed live in this tab…". That sentence is what
 *     stops a visitor reading the two live classifications above it as
 *     verdicts on real mail, so it is an honesty guarantee, not decoration. It
 *     is also the LAST line of a 470px card in a sticky column, and at the
 *     shortest viewport this page is designed for (600px) it clears the fold
 *     by 2.9px — measured here, on this build, not asserted as a number (see
 *     the test). `ClaimsDescent`'s docblock records that `top-24 py-16`, the
 *     offsets this staging replaced, cropped it away entirely. One more line
 *     of copy in that card, or one more rem of offset, and the sentence is
 *     below the fold again while every source-level gate stays green.
 *
 *  2. THE MOVED ROW AT BEAT 2. The window act's third scene captions itself
 *     "The row opens on the mail that moved it." The camera was deliberately
 *     changed to HOLD the board's foot there (`LandingBoard`'s `beat < 1 ? 0`)
 *     precisely so the Larkspur row is in frame while the pane it belongs to
 *     is docked open. The unit gate asserts that ternary as a STRING; this
 *     asserts the row's rect actually lies inside the stage's clip rect, which
 *     is the property the string exists to produce.
 *
 * HOW THE SCENES ARE DRIVEN. `WindowAct` and `ClaimsDescent` both key off an
 * IntersectionObserver over a centre band (`-45%`/`-40%` root margins). There
 * is no scroll-jacking: the page scrolls normally and the components respond.
 * So every test here scrolls the page to put the sentinel's own midpoint at
 * the viewport's midpoint — computed from the sentinel, never from a magic
 * offset — and then ASSERTS IT ARRIVED (the scene's caption, the exhibit's
 * wall label, the docked pane) before it measures anything. Without that
 * arrival gate a mis-scroll produces a green geometry assertion about a scene
 * that never composed, which is this repo's recurring defect shape.
 *
 * WHY PRODUCTION-ONLY. `next dev` re-renders every route per request and this
 * page is a static prerender whose board mounts client-side; a dev run has
 * already produced false reds on a clean commit here. Same gate and same
 * mechanism as `production.spec.ts`, so the dev-server job skips this file and
 * the `playwright (production build)` job — which runs `playwright test` with
 * no `--project` or path filter — executes it.
 *
 * MUTATION-TESTED AT INTRODUCTION (2026-08-15, `next build && next start` in a
 * detached worktree, headless Chromium, 1024×600). Every assertion below was
 * watched go red against a deliberate break and green again after the restore:
 *
 *   `ClaimsDescent` `py-6`→`py-16` ......... provenance 37.1px below the fold
 *   the provenance <p> deleted ............. its `toHaveCount(1)`
 *   `[data-claim=1]`→`[data-claim=3]` ...... the split-stage arrival gate
 *   `LandingBoard` `beat < 1`→`beat !== 1` . row 315.6px BELOW the clip
 *   `room` 0→400 at beat 2 ................. row 117.5px ABOVE the clip
 *   `LG` 1024px→1200px ..................... the live-board guard (2 tests)
 *   `[data-beat=2]`→`[data-beat=0]` ........ the beat-2 caption gate
 *   `MarketingBoard` beat-1 gate disabled .. the verdict/docked-pane gates
 *   the row locator → the board ............ the row-size guard (746.5px)
 *   the clip walk → the row's parent ....... the clip-is-the-stage guard
 *   `<ClosingAct />` unmounted ............. the act's presence (2 tests)
 *   `act-dot` `translateY(271.2px)`→`0` .... the verdict never left the lane
 *   `DOT_SEAT_Y` 335.2→240 ................. seated 81.2px off its own seat
 *   the closing observer re-armed .......... the "and holds" half
 *   the closing observer fired at load ..... the "not before it is seen" half
 *   a 2400px box in the hero ............... all three overflow readings
 *
 * TWO ASSERTIONS IN THE FIRST DRAFT COULD NOT FAIL, and both were caught by
 * running the mutation rather than by reading the code. `toHaveText(/rejected/)`
 * on the moved row stayed GREEN with the act's beat-1 effect disabled — the
 * row's stage control is a native <select> carrying every status as an
 * <option>, so its text always contains "rejected"; it reads the control's
 * VALUE now. And "the closing act has not played at load" stayed green with the
 * sequence firing at load, because it was read before hydration; it now waits
 * on the client-mounted board first. Companion bounds not independently
 * reddened, and named as such rather than claimed: the provenance line's
 * `y >= 0`, the access section's `top < fold`, and `data-detail-open` on the
 * row (its sibling `application-detail` assertion is the one that was watched
 * fail).
 */

const PROD_BUILD = process.env.PLAYWRIGHT_PROD_BUILD === "1";

/** The shortest desktop viewport this page is designed for. Both seeds are
 *  measured here because it is the tight case: the descent's exhibit clears
 *  600px by single-digit pixels. */
const DESKTOP_1024 = { width: 1024, height: 600 };
const TABLET_768 = { width: 768, height: 1024 };

/** The exhibit's closing sentence — the honesty guarantee, matched on the
 *  clause that carries it rather than on the whole sentence, so a wording
 *  tweak that keeps the promise does not turn CI red. */
const PROVENANCE = /A synthetic email .* computed live in this tab/;

/** The descent's sticky artifact column (`lg`+ only). Below `lg` each screen
 *  carries its own inline snapshot, and those are the copies this must NOT
 *  measure. */
const STICKY_EXHIBIT = "div.sticky.top-20";

/**
 * Scroll the page so `selector`'s midpoint sits at the viewport's midpoint —
 * which is where both components' centre bands live. Derived from the
 * element, so it survives any change to the runway's height or the sentinel
 * shares; a hard-coded scroll offset would not.
 */
async function centreOn(page: Page, selector: string): Promise<void> {
  await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) throw new Error(`nothing matches ${sel} — the scene's sentinel is gone`);
    const rect = el.getBoundingClientRect();
    const midpoint = window.scrollY + rect.top + rect.height / 2;
    window.scrollTo({ top: Math.max(0, midpoint - window.innerHeight / 2), behavior: "instant" });
  }, selector);
}

/**
 * Wait for an element's height to stop changing, then return it.
 *
 * The exhibit's three regions transition `grid-template-rows` over 500ms, and
 * the seed-1 margin is single-digit pixels — measuring mid-transition reads a
 * height that is wrong in either direction. Two consecutive equal readings
 * after the transition has had time to start is the settle; a bare
 * `waitForTimeout` would be a guess that gets worse under load.
 */
async function settledHeight(page: Page, selector: string): Promise<number> {
  const read = () =>
    page.evaluate(
      (sel) => document.querySelector(sel)?.getBoundingClientRect().height ?? -1,
      selector,
    );
  await page.waitForTimeout(600);
  let previous = await read();
  for (let i = 0; i < 40; i += 1) {
    await page.waitForTimeout(100);
    const current = await read();
    if (current > 0 && current === previous) return current;
    previous = current;
  }
  throw new Error(`${selector} never settled (last height ${previous})`);
}

/**
 * Put the window act at beat 2 and prove it got there.
 *
 * The order matters and is not decoration: beat 2's docked pane is gated on
 * the verdict having ALREADY landed (`MarketingBoard` waits for the row to
 * read `rejected`), and beat 1's move is on a 750ms timer. Jumping straight to
 * zone 2 opens nothing. So the reader passes through beat 1 the way a real one
 * does, and each arrival is asserted rather than slept through.
 */
async function driveToBeatTwo(page: Page): Promise<void> {
  // The board is client-mounted at `lg`+ only (`LandingBoard`), so measuring
  // before it exists would measure `StageSkeleton` — a test that cannot fail.
  await expect(page.getByTestId("pipeline-board")).toBeVisible();

  await centreOn(page, "[data-beat='1']");
  await expect(activeCaption(page)).toHaveText("The reply lands, and the row moves without you.");
  // The verdict itself: the row leaves `applied` for the closed group. Read
  // off the row's own stage control, NOT off its text — the control is a
  // native <select> carrying every status as an option, so `toHaveText(
  // /rejected/)` matched a row that was still `applied`. Measured: with the
  // act's beat-1 effect disabled the text form stayed green and this form
  // goes red.
  await expect(page.getByLabel("Change stage for Larkspur Systems")).toHaveValue("rejected");

  await centreOn(page, "[data-beat='2']");
  await expect(activeCaption(page)).toHaveText("The row opens on the mail that moved it.");
  // The pane docks open ON that row — `data-detail-open` is set by
  // `PipelineBoard` for the row the detail is showing, so this is the scene
  // composing, not merely a pane existing somewhere.
  await expect(page.getByTestId("application-detail")).toBeVisible();
  await expect(movedRow(page)).toHaveAttribute("data-detail-open", "true");
}

/**
 * The act's four narration lines (three scenes plus scene 0 revisited), by
 * their opening words. Matching on the lines themselves rather than on the
 * strip's layout classes keeps this readable when the strip is restyled — and
 * it is what lets `activeCaption` be a single-element locator inside a section
 * that also contains the whole board's prose.
 */
const NARRATION = /^(The board, nineteen days|The reply lands|The row opens on|The same board, with)/;

/** The narration line for the scene currently on screen. Every line is in the
 *  DOM at once, stacked in one grid cell; the inactive ones are `aria-hidden`
 *  (and `opacity-0`), so the showing one is the one React rendered as
 *  `aria-hidden="false"` — and asserting through a strict locator means
 *  "exactly one line is showing" is part of the reading rather than a separate
 *  hope. */
const activeCaption = (page: Page) =>
  page
    .locator("section[aria-label='The board, live'] p[aria-hidden='false']")
    .filter({ hasText: NARRATION });

/** The Larkspur row inside the live board — the one the act moves. */
const movedRow = (page: Page) =>
  page.locator(".board-row").filter({ hasText: "Larkspur Systems" });

test.describe("landing B (/landing-b)", () => {
  test.skip(
    !PROD_BUILD,
    "Runs only against `next start`; set PLAYWRIGHT_PROD_BUILD=1. `next dev` has produced false reds on this page's geometry.",
  );

  test("the four acts render at 1024, with a clean console", async ({ page }) => {
    const watch = startConsoleWatch(page);
    await page.setViewportSize(DESKTOP_1024);
    await page.goto("/landing-b");

    // 1 — the promise.
    await expect(
      page.getByRole("heading", { name: /Never update a job tracker again/i }),
    ).toBeVisible();
    // 2 — the window, with the REAL board mounted in it (not the skeleton).
    await expect(page.locator("section[aria-label='The board, live']")).toBeVisible();
    await expect(page.getByTestId("pipeline-board")).toBeVisible();
    // 3 — the descent, and its sticky exhibit.
    await expect(
      page.getByRole("heading", { name: /The preview ends before the verdict/i }),
    ).toBeVisible();
    await expect(page.locator(STICKY_EXHIBIT)).toHaveCount(1);
    // 4 — the conversion surface and the closing act.
    await expect(page.getByRole("heading", { name: /One hundred seats/i })).toBeVisible();
    await expect(page.locator("section.act")).toHaveCount(1);

    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });

  /**
   * SEED 1. The provenance line is the exhibit's last line and the page's
   * honesty guarantee about the two verdicts above it. This asserts it is
   * INSIDE the viewport at the shortest viewport the page is designed for,
   * in the stage where the verdicts are actually on screen.
   *
   * It asserts CONTAINMENT, not a margin. The clearance measured here on
   * 2026-08-15 (`next build && next start`, headless Chromium, 1024×600) is
   * 2.9px — bottom 597.1 against a 600px fold — but pinning that number would
   * make a font-metric change a CI failure, which is not what this guards.
   * The margin is reported in the failure message so a red run says how far
   * out it went.
   */
  test("the exhibit's provenance line stays inside the fold at 1024x600", async ({ page }) => {
    await page.setViewportSize(DESKTOP_1024);
    await page.goto("/landing-b");

    await centreOn(page, "[data-claim='1']");

    // Arrived at the SPLIT stage: the wall label names it and both live
    // verdict chips have actually expanded (collapsed `grid-rows-[0fr]` gives
    // them a zero-height box, so `toBeVisible` discriminates).
    const exhibit = page.locator(STICKY_EXHIBIT);
    await expect(exhibit.locator("p").first()).toHaveText("The same body, classified twice");
    await expect(exhibit.getByText("preview only")).toBeVisible();
    await expect(exhibit.getByText("whole body")).toBeVisible();

    await settledHeight(page, `${STICKY_EXHIBIT} > div:last-child`);

    const provenance = exhibit.getByText(PROVENANCE);
    await expect(provenance).toHaveCount(1);
    const box = await provenance.boundingBox();
    expect(box, "the provenance line has no box — it is not rendered").not.toBeNull();
    const fold = await page.evaluate(() => window.innerHeight);
    const margin = fold - (box!.y + box!.height);

    expect(
      margin,
      `the provenance line is cropped at ${DESKTOP_1024.width}x${DESKTOP_1024.height}: its bottom sits ${-margin}px below the fold. It is the sentence that stops a visitor reading the live verdicts above it as verdicts on real mail.`,
    ).toBeGreaterThanOrEqual(0);
    // And it is genuinely on screen, not merely ending above the fold with its
    // top pushed off the other end by a sticky offset.
    expect(box!.y, "the provenance line starts above the viewport").toBeGreaterThanOrEqual(0);
  });

  /**
   * SEED 2. At beat 2 the caption claims "The row opens on the mail that moved
   * it." That is only true if the row is in frame, and the stage is
   * `overflow-clip`: a row panned out of shot still reports real coordinates
   * from `getBoundingClientRect`, so "is it visible" has to be asked against
   * the CLIP's rect, not against the viewport and not against the row's own
   * box.
   *
   * The clipping ancestor is found by walking up from the row and reading
   * computed `overflow`, rather than by a class selector, so a restyle of the
   * stage cannot silently point this at a different box — and it is checked to
   * contain the board, which is what makes it the stage.
   */
  test("the moved row sits inside the stage clip at beat 2", async ({ page }) => {
    await page.setViewportSize(DESKTOP_1024);
    await page.goto("/landing-b");

    await driveToBeatTwo(page);

    const frame = await page.evaluate(() => {
      const row = document.querySelector<HTMLElement>(".board-row[data-detail-open]");
      if (!row) return { error: "no row carries the docked pane" } as const;
      let clip: HTMLElement | null = row.parentElement;
      while (clip && !/clip|hidden|auto|scroll/.test(getComputedStyle(clip).overflowY)) {
        clip = clip.parentElement;
      }
      if (!clip) return { error: "the row has no clipping ancestor" } as const;
      const board = document.querySelector("[data-testid='pipeline-board']");
      return {
        row: row.getBoundingClientRect().toJSON(),
        clip: clip.getBoundingClientRect().toJSON(),
        clipHoldsBoard: board !== null && clip.contains(board),
      };
    });

    expect("error" in frame ? frame.error : "", "the scene did not compose").toBe("");
    if ("error" in frame) return;

    expect(frame.clipHoldsBoard, "the clipping ancestor found is not the board's stage").toBe(true);
    // A guard against locating a container instead of a row: "inside the clip"
    // is trivially true for a box the clip itself sized.
    expect(
      frame.row.height,
      `located a ${frame.row.height}px box — that is not a board row`,
    ).toBeGreaterThan(30);
    expect(frame.row.height).toBeLessThan(140);

    const above = frame.row.top - frame.clip.top;
    const below = frame.clip.bottom - frame.row.bottom;
    expect(
      above,
      `the moved row is ${-above}px above the stage's top edge — the camera is not holding the board's foot, so the scene captioned "The row opens on the mail that moved it" is arguing about a row nobody can see`,
    ).toBeGreaterThanOrEqual(-1);
    expect(
      below,
      `the moved row is ${-below}px below the stage's bottom edge — it is clipped out of frame at beat 2`,
    ).toBeGreaterThanOrEqual(-1);
  });

  /**
   * The closing act plays once on scroll-into-view and HOLDS. "Holds" is the
   * load-bearing half: the sequence is CSS with `forwards` fill and its
   * observer disconnects, so a reader who scrolls past and comes back finds
   * the composed end state rather than a blank band or a replay.
   *
   * The verdict's landing is asserted against the page's OWN declared seat —
   * the `.act__ripple` circle is drawn at the baseline seat and never moves —
   * so this is not a golden pixel: it says "the dot ends where the scene says
   * the full stop goes".
   */
  test("the closing act composes on scroll-into-view and holds", async ({ page }) => {
    await page.setViewportSize(DESKTOP_1024);
    await page.goto("/landing-b");

    const compose = () =>
      page.evaluate(() => {
        const centre = (sel: string) => {
          const el = document.querySelector(sel);
          if (!el) return null;
          const r = el.getBoundingClientRect();
          return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
        };
        const ask = document.querySelector(".act__ask");
        const stroke = document.querySelector(".act__word .act__draw path");
        return {
          playing: document.querySelector("section.act")?.className.includes("act--play") ?? false,
          dot: centre(".act__dot"),
          seat: centre(".act__ripple"),
          lane: centre(".act__guide"),
          askOpacity: ask ? Number(getComputedStyle(ask).opacity) : -1,
          dashoffset: stroke ? getComputedStyle(stroke).strokeDashoffset : "unset",
        };
      });

    // Nothing has played yet: the band is below the fold at load. Read AFTER
    // proof that the client tree is live — the board only mounts from an
    // effect, so waiting on it means the closing act's own observer has had
    // its chance to fire. Without that wait this assertion passes on a page
    // that simply has not hydrated, which is a check that cannot fail: a
    // mutation firing the sequence at load was measured green until the wait
    // was added.
    await expect(page.getByTestId("pipeline-board")).toBeVisible();
    expect((await compose()).playing, "the closing act played before it was seen").toBe(false);

    await page.locator("section.act").scrollIntoViewIfNeeded();
    // The sequence is ~1.5s of CSS with a 1.55s tail; poll rather than sleep.
    await expect
      .poll(async () => (await compose()).askOpacity, { timeout: 6_000 })
      .toBe(1);

    const played = await compose();
    expect(played.playing).toBe(true);
    expect(played.dot, "the verdict never entered").not.toBeNull();
    expect(played.seat, "the scene declares no seat for the full stop").not.toBeNull();
    // It fell out of the lane…
    expect(
      played.dot!.y - played.lane!.y,
      "the verdict never left the lane — it does not punctuate the wordmark",
    ).toBeGreaterThan(100);
    // …and seated itself exactly where the scene says the full stop goes.
    expect(Math.abs(played.dot!.x - played.seat!.x)).toBeLessThanOrEqual(2);
    expect(
      Math.abs(played.dot!.y - played.seat!.y),
      "the verdict did not seat on the wordmark's baseline",
    ).toBeLessThanOrEqual(2);
    // The sentence itself finished drawing.
    expect(played.dashoffset).toBe("0px");

    // …and it HOLDS. Scroll the whole way back up and return.
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
    await page.waitForTimeout(300);
    await page.locator("section.act").scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);

    const held = await compose();
    expect(held.askOpacity, "the ask fell back out of view after the reader scrolled away").toBe(1);
    expect(held.dashoffset, "the drawn sentence un-drew itself").toBe("0px");
    expect(
      Math.abs(held.dot!.y - held.seat!.y),
      "the verdict left its seat after the reader scrolled away and came back",
    ).toBeLessThanOrEqual(2);
  });

  /**
   * The nav's one persistent path. A URL-hash assertion would pass with no
   * target element at all, so this measures where the section LANDED: below
   * the sticky header (that is what `SectionShell`'s `scroll-mt` buys) and
   * inside the fold.
   */
  test("the nav's access anchor lands on the access section", async ({ page }) => {
    await page.setViewportSize(DESKTOP_1024);
    await page.goto("/landing-b");

    await page.getByRole("link", { name: /^Get access$/i }).click();
    await expect(page).toHaveURL(/#access$/);

    const heading = page.getByRole("heading", { name: /One hundred seats/i });
    await expect(heading).toBeVisible();

    const landing = await page.evaluate(() => {
      const nav = document.querySelector("header");
      const section = document.querySelector("#access");
      if (!nav || !section) return null;
      return {
        navBottom: nav.getBoundingClientRect().bottom,
        sectionTop: section.getBoundingClientRect().top,
        fold: window.innerHeight,
      };
    });
    expect(landing, "there is no #access section for the nav to reach").not.toBeNull();
    expect(
      landing!.sectionTop,
      `the access section landed ${landing!.navBottom - landing!.sectionTop}px UNDER the sticky nav`,
    ).toBeGreaterThanOrEqual(landing!.navBottom - 1);
    expect(landing!.sectionTop, "the access section landed below the fold").toBeLessThan(
      landing!.fold,
    );
  });

  for (const [label, viewport] of [
    ["1024", DESKTOP_1024],
    ["768", TABLET_768],
    ["375", MOBILE_375],
  ] as const) {
    test(`no horizontal overflow at ${label}px`, async ({ page }) => {
      const watch = startConsoleWatch(page);
      await page.setViewportSize(viewport);
      await page.goto("/landing-b");
      await expect(
        page.getByRole("heading", { name: /Never update a job tracker again/i }),
      ).toBeVisible();
      await expectNoHorizontalOverflow(page);

      // Below `lg` the whole page is the still/inline staging, so walk it to
      // the end — the closing act's 1200-unit scene and the descent's inline
      // snapshots are the parts most likely to spill.
      await page.evaluate(() => window.scrollTo({ top: document.body.scrollHeight }));
      await page.waitForTimeout(300);
      await expectNoHorizontalOverflow(page);

      expect(watch.errors, watch.errors.join("\n")).toEqual([]);
    });
  }
});
