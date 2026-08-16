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
 * The visitor's-pane test was added the same way (2026-08-15, same rig, both
 * heights). `MarketingBoard`'s release condition disabled — `if (id !==
 * seededRef.current)` → `if (id === -1)`, so a visitor open never reaches
 * `onVisitorOpen` and the camera stays panned — put the pane's × 270–274px
 * above the clip at 1024×768 and 480–624px above it at 1024×600, red on both
 * viewports across two runs, with the other eight tests green; green again on
 * restore, 10/10 three runs running. Companion bounds not independently
 * reddened, and named as such: the × `toHaveCount(1)`,
 * `stage.contains(control)`, the stage-really-crops-the-board guard, the
 * `below` edge and the two horizontal ones.
 *
 * THREE TESTS HERE HAVE NOT BEEN THROUGH ANY OF THAT, and the header would be
 * lying if it did not say so: the re-open pair (SEED 4) and the takeover
 * suppression (SEED 5), all added 2026-08-15 in sessions that could not run
 * Playwright at all. No run of any of them has been watched go red, or green.
 * Each docblock names the mutation to run first and what the other tests
 * should do under it; until those runs exist a green from them proves nothing.
 *
 * A THIRD ASSERTION THAT COULD NOT HOLD, caught the same way. That test first
 * gated on the act still being at beat 1 after the click, and it went red on
 * the UNMUTATED build: a visitor open moves focus into the pane
 * (`ApplicationDetail`'s `focusOnOpen`) and `focus()` scrolls the viewport to
 * reach a pane the crop has pushed off-screen, which can carry the act into
 * the next zone. Where that scroll lands is the browser's business; the
 * product's promise is the pane's chrome, so the arrival gate is the pane
 * being open on the row the visitor clicked. Chasing that down is also what
 * surfaced the release race recorded on `visitorRow` — a defect in the page,
 * not in this file, which was reported rather than retried into green and has
 * since been fixed in `MarketingBoard` (the page's claim on a card load is
 * armed in the same task that hands the seed to the board, so a visitor's load
 * is always scheduled first; the row's identity no longer decides anything).
 * The race is why this file's own coverage of the moved row used to stop at the
 * camera. It no longer does: `visitorRow` has been pointed at Larkspur on the
 * evidence its docblock demanded, because clicking any other row made SEED 3
 * unable to fail at all — the guarded branch is reachable only on the one id the
 * page's claim ever holds. What that gate needs to stay honest is a run shape
 * `--retries=2` cannot give it; see `landing-b-race.yml`.
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
/** The other height the act is verified at. Both are measured for the visitor's
 *  pane (see the test): the stage is `calc(100dvh - 13.5rem)`, so the crop is
 *  552px tall here and 384px at 600 — two different amounts of room for a
 *  control the camera can push off the top. */
const DESKTOP_1024_768 = { width: 1024, height: 768 };
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
 * Wait for an element's top edge to stop moving, then return it.
 *
 * Same instrument as `settledHeight`, for the other axis: the camera is a
 * 700ms eased `translateY`, and `getBoundingClientRect` reports the animating
 * value, so anything read mid-pan is a coordinate the visitor never sees.
 *
 * Sampled every 150ms on this build the pan reads −391.5px at the click and
 * has settled by 750ms at both heights. The 1.5s floor is deliberately past
 * twice that: a pan that has not STARTED yet returns the same pre-pan rect on
 * every read, which two equal readings would report as a settle. (The reds
 * that first sent this helper looking for a mid-flight read were not that —
 * they were a genuinely un-released camera, and they are recorded in the
 * test.)
 *
 * It settles just as readily on a camera that is not moving, which is what the
 * mutation produces: a broken build fails on the geometry, with the geometry's
 * own message, rather than timing out here.
 */
async function settledTop(page: Page, selector: string): Promise<number> {
  const read = () =>
    page.evaluate(
      (sel) => document.querySelector(sel)?.getBoundingClientRect().top ?? Number.NaN,
      selector,
    );
  await page.waitForTimeout(1_500);
  let previous = await read();
  for (let i = 0; i < 40; i += 1) {
    await page.waitForTimeout(200);
    const current = await read();
    if (Number.isFinite(current) && current === previous) return current;
    previous = current;
  }
  throw new Error(`${selector} never settled (last top ${previous})`);
}

/**
 * Put the window act at beat 1 and prove it got there — the camera panned to
 * the board's foot, and the verdict actually landed on the row.
 */
async function driveToBeatOne(page: Page): Promise<void> {
  // The board is client-mounted at `lg`+ only (`LandingBoard`), so measuring
  // before it exists would measure `StageSkeleton` — a test that cannot fail.
  await expect(page.getByTestId("pipeline-board")).toBeVisible();

  await centreOn(page, "[data-beat='1']");
  await expect(activeCaption(page)).toHaveText("The offer lands, and the row moves without you.");
  // The verdict itself: the row leaves `applied` for the offered group (the
  // act's payoff is a WIN as of 2026-08-16 — the moving row is the offer the
  // headline names, never a rejection). Read off the row's own stage control,
  // NOT off its text — the control is a native <select> carrying every status
  // as an option, so a text match would pass on a row that had not moved.
  // The beat-1 breath plus the slowed glide is ~3.4s (tempo.ts); toHaveValue
  // retries within its own timeout, so no explicit wait belongs here.
  await expect(page.getByLabel("Change stage for Larkspur Systems")).toHaveValue("offered");
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
  await driveToBeatOne(page);

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
const NARRATION = /^(The board, nineteen days|The offer lands|The row opens on|The same board, with)/;

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

/** The detail pane's own close control, by the label `ApplicationDetail`
 *  gives it — used as a raw selector inside `page.evaluate`, where a
 *  Playwright locator cannot go. */
const CLOSE_CONTROL = 'button[aria-label="Close detail"]';

/** The one company the act ever touches: the row it moves at beat 1 and the id
 *  it seeds at beat 2. ONE literal, read by every locator below that means this
 *  row — see `visitorRow` for what two independent literals cost. */
const MOVED_COMPANY = "Larkspur Systems";

/** The Larkspur row inside the live board — the one the act moves. */
const movedRow = (page: Page) =>
  page.locator(".board-row").filter({ hasText: MOVED_COMPANY });

/**
 * The row the VISITOR opens. It is now the SAME row the act moves, and that is
 * the point — the history is worth keeping because it is why this gate spent a
 * while unable to fail.
 *
 * `MarketingBoard` used to tell a visitor's open from the page's own by id —
 * the beat-2 seed being the one id the page ever opens — with both sides of
 * that comparison set from effects that defer off the effect body. Clicking
 * Larkspur at beat 1 scrolls further to reach its pane, which carries the act
 * into zone 2, which set the seed to Larkspur's own id; if the pane's
 * `transport.detail` call landed after that, the visitor's open was read as
 * the page's and the camera never released. Measured on a production build:
 * about four full-file runs in ten went red that way at both heights, with the
 * camera resting un-released at −279.5px and −263.5px. So this pointed at Atlas
 * Freight — the last row of the closed group, in frame at beat 1 by the same
 * camera, and never seeded — and the act stayed at beat 1 in every run.
 *
 * THAT CHOICE MADE SEED 3 UNABLE TO FAIL, which is the reason it has moved.
 * The misclassification the test guards is reachable only through
 * `pendingSeedRef.current === id`, and `pendingSeedRef` only ever holds
 * Larkspur's id. Pointed at Atlas Freight the comparison is deterministically
 * false, so the guarded branch was unreachable and the compound mutant below
 * could not redden this test at all — 0%, structurally, not improbably.
 *
 * IT MOVED ON THE EVIDENCE THIS DOCBLOCK USED TO DEMAND. The precondition was
 * `--repeat-each=10` at 1024×768 and 1024×600 with the click retargeted, ten of
 * ten at both. Run on a frozen tree at `59c2bcc` against `next build && next
 * start`: 20/20 with the click retargeted, and 20/20 again on the restored
 * tree — twice, so the green is the page's and not one lucky pass.
 *
 * `visitorRow` and `movedRow` now name the same row by design. Both are kept:
 * they are read by different tests asking different questions (SEED 4 clicks
 * the row the PAGE opened; SEED 3 clicks it as a visitor at beat 1), and
 * collapsing them would lose which gesture each test is about. Do not "clean up"
 * one into the other.
 */
const visitorRow = movedRow;

/**
 * The board's own "open the mail behind this row" control for `MOVED_COMPANY`'s
 * row — the gesture SEED 3 and SEED 4 both perform, at different beats.
 *
 * Derived from the SAME constant the locators filter on, and that is not
 * tidiness. The locator and the click used to be two independent literals; when
 * only one of them was reasoned about, the test clicked one row and asserted
 * against another's premise, which is exactly how the gate above became
 * unreachable. One constant, so they cannot drift apart again.
 */
const visitorOpener = (page: Page) =>
  page.getByRole("button", { name: new RegExp(`^Open ${MOVED_COMPANY}`) });

/**
 * The docked pane's × measured against the box that actually CROPS the board.
 *
 * A control panned out of an `overflow-clip` ancestor still reports real
 * coordinates and still passes every visibility check Playwright has, so the
 * only honest reading is containment in the clip's own rect. The clipping
 * ancestor is walked up from the BOARD, not from the ×: the pane is itself
 * `overflow-hidden`, so a walk from the button would stop at the pane and
 * "inside the clip" would be trivially true.
 *
 * Shared by the two tests that ask the same question of two different
 * gestures — a first open and a re-open — so both read one box one way.
 */
async function closeControlFrame(page: Page) {
  return page.evaluate((sel) => {
    const control = document.querySelector<HTMLElement>(sel);
    const board = document.querySelector<HTMLElement>("[data-testid='pipeline-board']");
    if (!control || !board) return { error: "no close control on the docked pane" } as const;
    let stage: HTMLElement | null = board.parentElement;
    while (stage && !/clip|hidden|auto|scroll/.test(getComputedStyle(stage).overflowY)) {
      stage = stage.parentElement;
    }
    if (!stage) return { error: "the board has no clipping ancestor" } as const;
    return {
      control: control.getBoundingClientRect().toJSON(),
      stage: stage.getBoundingClientRect().toJSON(),
      stageHoldsControl: stage.contains(control),
      boardHeight: board.getBoundingClientRect().height,
    };
  }, CLOSE_CONTROL);
}

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
      page.getByRole("heading", { name: /You lose the email/i }),
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
   * SEED 3, and the one defect on this page that SHIPPED. The window crops a
   * live product, so every control the crop pushes off-stage becomes
   * unreachable — and at beat 1 the camera is panned to the board's foot, so
   * a visitor who clicks a row got a detail pane whose own × was rendered
   * ABOVE the visible frame (measured then: 304px above it at a 768-tall
   * viewport). The pane could only be closed with Escape, which nothing on the
   * page announced.
   *
   * `d2144ec` fixed it in `MarketingBoard`: `transport.detail(id)` is the call
   * every pane load passes through, so a load the page did not cause is the
   * visitor's hand on the wheel, and `LandingBoard` returns the camera to
   * `translateY(0)` — beat 0's frame, where the pane renders its whole header.
   * That first cut read the id and raced (see `visitorRow`); the page's claim
   * is now armed in the same task that hands the seed to the board, and a
   * gesture recorded in the capture phase settles anything the ordering leaves
   * open. Both are causes, and neither depends on which row was clicked.
   *
   * This asserts the PROPERTY, not the mechanism: the close control's box
   * lies inside the stage's clip rect. The unit gate cannot see it — the
   * release is a runtime pan, not a string — and neither can a `toBeVisible`,
   * because a control panned out of an `overflow-clip` ancestor still reports
   * real coordinates and still passes every visibility check Playwright has.
   *
   * Both heights, because they are different amounts of room (552px of stage
   * at 768, 384px at 600) and the original defect was found across both.
   *
   * The row clicked is `visitorRow`, which IS the row the act moves. It used to
   * be Atlas Freight, and that is what made this test structurally unable to
   * fail: the misclassification is only reachable through
   * `pendingSeedRef.current === id`, and the page's claim only ever holds the
   * moved row's id, so on any other row the guarded branch was dead. Read the
   * locator's docblock before changing it — including the evidence that had to
   * exist before it could move.
   */
  for (const viewport of [DESKTOP_1024_768, DESKTOP_1024]) {
    const size = `${viewport.width}x${viewport.height}`;
    test(`a pane the visitor opens keeps its close control in frame at ${size}`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      await page.goto("/landing-b");

      await driveToBeatOne(page);

      // The visitor takes the wheel: a click on the row's own identity button,
      // the gesture the board exposes for "open the mail behind this row".
      // THE MOVED ROW, and that is the whole point — it is the only id the
      // page's claim ever holds, so it is the only click that can reach the
      // misclassification this test guards. See `visitorRow`.
      await visitorOpener(page).click();
      // The arrival gate is the PANE ON THAT ROW, not the beat: a visitor open
      // moves focus into the pane (`ApplicationDetail`'s `focusOnOpen`, true
      // for every open a person performed) and `focus()` scrolls the viewport
      // to reach it, so the act's scene index after the click is the browser's
      // business, not the product's promise. What is promised is this: a pane
      // the VISITOR opened has its own chrome in frame.
      const close = page.getByRole("button", { name: "Close detail" });
      await expect(page.getByTestId("application-detail")).toBeVisible();
      await expect(visitorRow(page)).toHaveAttribute("data-detail-open", "true");
      // ApplicationDetail has a docked path and a Dialog path; at `lg`+ this
      // is the docked one, and exactly one × exists to measure.
      await expect(close).toHaveCount(1);

      // The release is a 700ms eased pan. Measure after it stops.
      await settledTop(page, CLOSE_CONTROL);

      const frame = await closeControlFrame(page);

      expect("error" in frame ? frame.error : "", "the scene did not compose").toBe("");
      if ("error" in frame) return;

      // The stage has to be the box that actually crops the board, or every
      // containment reading below is about an unrelated rectangle.
      expect(frame.stageHoldsControl, "the pane is not inside the board's stage").toBe(true);
      expect(
        frame.stage.height,
        `the stage is ${frame.stage.height}px for a ${frame.boardHeight}px board — it is not cropping anything, so this test is measuring the wrong box`,
      ).toBeLessThan(frame.boardHeight);

      const above = frame.control.top - frame.stage.top;
      const below = frame.stage.bottom - frame.control.bottom;
      expect(
        above,
        `the pane's close control is ${-above}px ABOVE the framed window at ${size} — the camera never handed the frame back, so a visitor who opened this card can only close it with Escape`,
      ).toBeGreaterThanOrEqual(-1);
      expect(
        below,
        `the pane's close control is ${-below}px below the framed window at ${size}`,
      ).toBeGreaterThanOrEqual(-1);
      expect(frame.control.left).toBeGreaterThanOrEqual(frame.stage.left - 1);
      expect(frame.control.right).toBeLessThanOrEqual(frame.stage.right + 1);
    });
  }

  /**
   * SEED 4, and the last hole in SEED 3's promise: the row the PAGE opened.
   *
   * SEED 3 covers every card a visitor opens that the page did not — a real
   * change of card, so the pane loads, `transport.detail` fires, and the camera
   * lets go. Clicking the row that is ALREADY open used to do nothing at all:
   * `PipelineBoard` keeps the row OBJECT it was handed, the row hands the same
   * one back, `useState` bails on the identical reference, and with no commit
   * there is no load and no call for `MarketingBoard` to read. The frame stayed
   * at the board's foot with the pane's × cropped above it (`LandingBoard`
   * measured ~97px at beat 2), and Escape — which nothing announces — was again
   * the only way out. It is the most likely click in the scene: the pane is
   * open on that row, and the row is the thing the caption points at.
   *
   * The fix is in `MarketingBoard` (`50d8d4d`): once the page's own open has
   * been consumed, the seeded row is handed a fresh object carrying the same
   * values, so the visitor's re-open is a real state change and reaches the
   * release through the product's existing path. This test asserts the
   * PROPERTY that fix exists for — the × inside the stage's clip — and never
   * mentions the mechanism.
   *
   * THE ATTRIBUTION ABOVE WAS WRITTEN BEFORE THE FIX EXISTED. When this test
   * was introduced, the paragraph before it described the identity-refresh in
   * the past tense — "used to do nothing at all" — while the tree still did
   * nothing at all, so a green here would have been a green on a defect the
   * comment claimed was already gone. The mechanism landed one commit later;
   * the tense is honest now, and the sentence is left as a record of how
   * easily it was not.
   *
   * IT MEASURES A RELEASE, not a frame that was already right: the pre-click
   * read asserts the × is cropped while the page is still driving, so a page
   * that never moved fails here instead of passing everything below.
   *
   * This one should be steadier than SEED 3, and the reason is a falsifiable
   * prediction rather than a hope: the pane is already open, so there is no
   * `dockedOpen` transition, so `ApplicationDetail` performs no `focus()` and
   * nothing scrolls the viewport — the act should still be at beat 2 when the
   * camera releases. It is left unasserted (SEED 3's docblock records what
   * gating on the beat cost there); a run that finds the act elsewhere means
   * the model behind this test is wrong and is worth reporting.
   *
   * NOT MUTATION-VERIFIED AT INTRODUCTION — the author could not run Playwright
   * in that session, and no run of this test has been watched go red. The
   * mutation to run first, before trusting a green: delete the identity-refresh
   * `commit(...)` from the seed-consuming branch of `MarketingBoard`'s
   * `transport.detail`. The click then bails on the identical reference exactly
   * as before, and this test should go red on the `above` reading at both
   * heights while SEED 3 stays GREEN. The reason SEED 3 survives is NOT that it
   * clicks a different row — since the retarget it clicks the same one — but
   * that it clicks at beat 1, before the page has seeded anything: `detailApp`
   * is still null there, so the visitor's open is a real state change whatever
   * the identity-refresh does. A red on both would mean this is measuring the
   * camera in general rather than this specific hole.
   *
   * SEED 3 has since BEEN retargeted onto this same row — read `visitorRow`'s
   * docblock for the evidence that allowed it. The two tests are still distinct:
   * this is a different gesture at a different beat, on a pane the PAGE opened.
   */
  for (const viewport of [DESKTOP_1024_768, DESKTOP_1024]) {
    const size = `${viewport.width}x${viewport.height}`;
    test(`re-opening the page's own pane returns the frame at ${size}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await page.goto("/landing-b");

      await driveToBeatTwo(page);
      await expect(page.getByRole("button", { name: "Close detail" })).toHaveCount(1);

      // Beat 2's own pan is a 700ms ease; read the premise after it stops.
      await settledTop(page, CLOSE_CONTROL);
      const before = await closeControlFrame(page);
      expect("error" in before ? before.error : "", "the scene did not compose").toBe("");
      if ("error" in before) return;
      expect(
        before.control.top - before.stage.top,
        `the pane's × is already inside the framed window at ${size} before the visitor has touched anything — beat 2 is no longer cropping the pane it opened, so there is nothing here to release and this test can no longer fail`,
      ).toBeLessThan(0);

      // The gesture: the row that is already open, clicked by its own identity
      // button — the same control SEED 3 uses, pointed at the one card whose
      // re-open the board cannot tell from no gesture at all.
      await visitorOpener(page).click();
      await expect(page.getByTestId("application-detail")).toBeVisible();
      await expect(movedRow(page)).toHaveAttribute("data-detail-open", "true");

      await settledTop(page, CLOSE_CONTROL);
      const frame = await closeControlFrame(page);
      expect("error" in frame ? frame.error : "", "the pane left with the gesture").toBe("");
      if ("error" in frame) return;

      expect(frame.stageHoldsControl, "the pane is not inside the board's stage").toBe(true);
      expect(
        frame.stage.height,
        `the stage is ${frame.stage.height}px for a ${frame.boardHeight}px board — it is not cropping anything, so this test is measuring the wrong box`,
      ).toBeLessThan(frame.boardHeight);

      const above = frame.control.top - frame.stage.top;
      const below = frame.stage.bottom - frame.control.bottom;
      expect(
        above,
        `the pane's close control is ${-above}px ABOVE the framed window at ${size} after the visitor clicked the open row — clicking the card the page opened is the one open the camera never sees, so it can only be closed with Escape`,
      ).toBeGreaterThanOrEqual(-1);
      expect(
        below,
        `the pane's close control is ${-below}px below the framed window at ${size}`,
      ).toBeGreaterThanOrEqual(-1);
      expect(frame.control.left).toBeGreaterThanOrEqual(frame.stage.left - 1);
      expect(frame.control.right).toBeLessThanOrEqual(frame.stage.right + 1);
    });
  }

  /**
   * SEED 5. The page stops driving once the visitor takes the wheel — and
   * "stops" has to include the beat it has not played yet.
   *
   * SEED 3 and SEED 4 both measure the CAMERA giving the frame back. This
   * measures the other half, which nothing else here can see: after a visitor
   * has opened a card, scrolling on to zone 2 must not push a pane on them.
   * The gesture is the plainest one in the scene — open a card, close it with
   * Escape, keep reading — and it is exactly the state the walls that predate
   * this test do NOT cover. `PipelineBoard` stands its seed down over a
   * pane the visitor already has open (`detailApp !== null`), and Escape has
   * just made that null; `LandingBoard`'s camera latch stays released, so the
   * pane would arrive in frame and be closeable. It would simply be a pane
   * nobody asked for, appearing under a caption that says the page opened it.
   *
   * So this asserts a COUNT, not a rectangle: the beat-2 caption is on screen
   * (the arrival gate — without it a mis-scroll gives a green about a scene
   * that never composed) and no detail pane exists. It samples for 1.5s rather
   * than reading once, because the seed the takeover suppresses is itself a
   * deferred timer: a single read taken too early passes on a page that is
   * about to open one.
   *
   * THE TAKEOVER HAPPENS AT BEAT 0, AND THAT IS THE WHOLE DESIGN OF THIS TEST.
   * The obvious staging — take over at beat 1, the way SEED 3 does — cannot
   * fail. A visitor open at beat 1 moves focus into a pane the crop has pushed
   * off-screen, so `focus()` scrolls and can carry the act into zone 2 with
   * that pane still up (this file's header records exactly that happening on
   * an unmutated build). A broken build then seeds at that arrival,
   * `PipelineBoard` marks the seed CONSUMED and only then bails on the
   * visitor's open (`consumedDetailSeed.current = openDetailId` is assigned
   * before the `detailApp !== null` return) — and `MarketingBoard`'s own effect
   * has latched `openDetailId`. The one seed is spent. Escape, scroll back to
   * zone 2, and a broken build opens nothing either, for a reason that has
   * nothing to do with the fix. Beat 0 is before the act can have visited zone
   * 2 at all, so the arrival this measures is the FIRST one.
   *
   * Hence the premise gate after the click: the act must not already have
   * reached zone 2. It is the one assertion here that could go red on a clean
   * build — if it does, `focus()` at beat 0 is scrolling further than the model
   * behind this test predicts, and that is a finding to report rather than a
   * number to relax.
   *
   * The row clicked is MEASURED, not named: the stage is `overflow-clip`, a row
   * the camera has not brought into frame cannot be clicked (Playwright cannot
   * scroll a clipped box into view), and which rows are in frame at beat 0 is a
   * fact about the fixture and the camera, not a constant worth hard-coding. It
   * takes the first row whose opener lies inside the clip and is not Larkspur.
   * Larkspur is excluded here even though `visitorRow` now points AT it: this is
   * a different gesture at a different beat, and clicking Larkspur would ask
   * SEED 4's question with these words.
   *
   * One viewport, deliberately, and it is not the geometric argument the other
   * seeds make — a count does not change at 768 vs 600.
   *
   * NOT MUTATION-VERIFIED AT INTRODUCTION — written in a session that could
   * not run Playwright, and no run of it has been watched go red or green.
   * The mutation to run first: delete BOTH takeover reads from
   * `MarketingBoard`'s beat-2 effect (the `tookOverRef.current` term in the
   * early return AND the guard on the timer's first line). The page then seeds
   * its open over a visitor who has already used the board, and this test
   * should go red on the pane count while everything else here stays green —
   * a red anywhere else means it is measuring the act in general rather than
   * this hole. Deleting only ONE of the two should leave it green, and that is
   * not slack: they mutually mask on this path (the effect-body read stops the
   * timer being scheduled, the timer read is the one that holds when the
   * effect body runs before the visitor's load has been classified), the same
   * relationship the belt and the arm-site have in `MarketingBoard`.
   */
  test("the page does not seed a pane at beat 2 once the visitor has taken over", async ({
    page,
  }) => {
    await page.setViewportSize(DESKTOP_1024);
    await page.goto("/landing-b");

    // Beat 0: the board is mounted, the camera is at rest, and the act has
    // never been to zone 2.
    await expect(page.getByTestId("pipeline-board")).toBeVisible();
    await expect(activeCaption(page)).toHaveText(
      "The board, nineteen days after you stopped updating it.",
    );

    // Which row is reachable here is a measurement — see the docblock.
    const opener = await page.evaluate(() => {
      const board = document.querySelector<HTMLElement>("[data-testid='pipeline-board']");
      if (!board) return null;
      let stage: HTMLElement | null = board.parentElement;
      while (stage && !/clip|hidden|auto|scroll/.test(getComputedStyle(stage).overflowY)) {
        stage = stage.parentElement;
      }
      if (!stage) return null;
      const clip = stage.getBoundingClientRect();
      for (const row of Array.from(document.querySelectorAll<HTMLElement>(".board-row"))) {
        if (row.textContent?.includes("Larkspur Systems")) continue;
        const button = row.querySelector<HTMLElement>("button[aria-label^='Open ']");
        if (!button) continue;
        const box = button.getBoundingClientRect();
        if (box.top >= clip.top && box.bottom <= clip.bottom) return button.getAttribute("aria-label");
      }
      return null;
    });
    expect(
      opener,
      "no row's opener is inside the stage clip at beat 0 — the visitor cannot take the wheel in the scene this test is about",
    ).not.toBeNull();

    // The visitor takes the wheel: a card of their own, opened by the row's own
    // identity button — the same control SEED 3 uses.
    const clicked = page.locator(`button[aria-label="${opener}"]`);
    const clickedRow = page.locator(".board-row").filter({ has: clicked });
    await clicked.click();
    await expect(page.getByTestId("application-detail")).toBeVisible();
    await expect(clickedRow).toHaveAttribute("data-detail-open", "true");

    // …and closes it. Escape is the docked pane's own closer, and once the act
    // reaches beat 1 it is the only one the crop leaves reachable — which is
    // why "opened a card, then closed it" is the state worth testing.
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("application-detail")).toHaveCount(0);

    // The premise: that gesture has not carried the act into zone 2 behind our
    // backs. If it had, a broken build would already have spent its one seed
    // here and the reading below would be green for the wrong reason.
    await expect(
      activeCaption(page),
      "the visitor's open at beat 0 scrolled the act all the way into zone 2 — this test's arrival at zone 2 is no longer the first one, so its green would prove nothing",
    ).not.toHaveText("The row opens on the mail that moved it.");

    // Then they keep reading. Beat 1 is passed through the way a real reader
    // passes it, and it is load-bearing here rather than scenery: the seed is
    // gated on the verdict having landed, so without this a broken build has
    // nothing to seed and goes green on an empty premise.
    await driveToBeatOne(page);

    // On into the zone whose whole job is to open a pane.
    await centreOn(page, "[data-beat='2']");
    await expect(activeCaption(page)).toHaveText("The row opens on the mail that moved it.");

    // The scene is composing and the page has opened nothing — held over a
    // window wide enough that a deferred seed cannot land after the reading.
    const panesSeen = await page.evaluate(async () => {
      let most = 0;
      const deadline = performance.now() + 1_500;
      while (performance.now() < deadline) {
        most = Math.max(most, document.querySelectorAll("[data-testid='application-detail']").length);
        await new Promise((resolve) => window.setTimeout(resolve, 50));
      }
      return most;
    });

    expect(
      panesSeen,
      "the page opened a detail pane at beat 2 on a visitor who had already opened a card themselves — the act kept driving after the wheel changed hands",
    ).toBe(0);
    // And the row the page would have seeded is not carrying one either, which
    // is the same fact read off the board rather than off the pane.
    await expect(movedRow(page)).not.toHaveAttribute("data-detail-open", "true");
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
        page.getByRole("heading", { name: /You lose the email/i }),
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
