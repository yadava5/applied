import { expect, test, type Page } from "@playwright/test";

import { startConsoleWatch } from "./helpers";

/**
 * THE QUEUE GROUPS WHAT IT ASKS ABOUT, AND STILL ASKS EVERY QUESTION (#517).
 *
 * Four held messages from one employer are four separate questions to the
 * classifier and one thing to READ. The queue now renders them as one
 * expandable line. What it must NOT do is answer any of them: the alternative
 * — declining to queue (or quietly attaching) a row whose suggested stage would
 * not move its card — was built and measured, and 69 of the 137 rows it touched
 * were ground-truth rejections misread as status-quo confirmations. In this
 * band every field the classifier produced IS the doubted object; it may order
 * and group the asking and may never answer it.
 *
 * WHY THIS FILE HAS TO EXIST IN A BROWSER. `tests/unit/` mounts the component
 * through jsdom and proves the structure eighteen ways, and none of it can see
 * the two things below: that a real `?review=` knob over the REAL demo board
 * actually produces a group at all (the client-side key is `haystack.includes`
 * against board names — a board name longer than the name the mail uses matches
 * nothing, so the key firing is an empirical claim, not a structural one), and
 * that the collapsed line survives at 1024px, the width the owner works at.
 *
 * WHY /demo/shell AND NOT /dashboard. Every session-gated spec in this suite
 * skips in CI and always has (`session.ts` — 13 tests that have never run), and
 * a spec that skips is green. `/demo/shell?review=N` mounts the REAL
 * `ReviewQueue` over the demo board with no session, so these execute.
 *
 * THE TWO KNOBS ARE A CONTROL ON EACH OTHER. `?review=12` and `?review=13`
 * differ by exactly one seed — a third Copperline row whose `suggested_category`
 * disagrees with the other two. Twelve collapses, thirteen does not. A single
 * screen showing one of those states would not tell you the gate was consulted.
 */

/**
 * `queue=before` is EXPLICIT on both, the way `shell.spec.ts` drives this knob.
 * Absent, the slot falls through to the preference the Settings twin wrote and
 * the queue lands UNDER all seventeen board rows — a full board's height below
 * the fold at 1024, where "is the collapsed line legible" cannot be asked.
 */
/** Two Copperline rows agreeing about the machine's guess — collapses. */
const UNIFORM_PAIR = "/demo/shell?review=12&queue=before";
/** The same pair plus one row that disagrees — opens, per the gate. */
const MIXED_TRIO = "/demo/shell?review=13&queue=before";

/** The demo employer the appended seeds name; it holds exactly one board card. */
const BRAND = "Copperline";

/** The group's header line, located by its role rather than by a class. */
function groupHeader(page: Page, count: number) {
  return page.getByRole("button", { name: new RegExp(`${count} held messages · ${BRAND}`) });
}

/** Every per-row stage select in the document — one per ANSWERABLE row. */
function stageSelects(page: Page) {
  return page.locator('select[id^="cat-"]');
}

test.describe("the review queue groups one employer's held mail", () => {
  test("a uniform group collapses, and its rows are absent until it is opened", async ({ page }) => {
    const watch = startConsoleWatch(page);
    await page.goto(UNIFORM_PAIR);

    const header = groupHeader(page, 2);
    await expect(header).toBeVisible();
    await expect(header).toHaveAttribute("aria-expanded", "false");

    // ABSENT, not hidden. A collapsed group's rows are unmounted, so they are
    // physically unanswerable — the evidence has to be on screen before any
    // answer can be given, and that is the property that makes collapsing safe.
    // Twelve messages are held; ten of them are lone rows, and only the first
    // four UNITS render before the list expander.
    const collapsed = await stageSelects(page).count();

    await header.click();
    await expect(header).toHaveAttribute("aria-expanded", "true");
    expect(
      await stageSelects(page).count(),
      "opening the group did not add its two rows' own answers",
    ).toBe(collapsed + 2);

    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });

  test("a group whose members DISAGREE opens itself", async ({ page }) => {
    // Band data may buy MORE scrutiny and never less. #517's own four rows are
    // three assessment and one applied, so the pile this issue was filed about
    // renders expanded — correct rather than a failure. The win there is the
    // header saying the four are one employer.
    const watch = startConsoleWatch(page);
    await page.goto(MIXED_TRIO);

    const header = groupHeader(page, 3);
    await expect(header).toBeVisible();
    await expect(header).toHaveAttribute("aria-expanded", "true");

    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });

  test("the header says raw facts only — no classifier output anywhere on it", async ({ page }) => {
    await page.goto(UNIFORM_PAIR);

    const header = groupHeader(page, 2);
    const text = ((await header.textContent()) ?? "").trim();

    // The stage words the reader is about to choose between. Printing one of
    // them above the select that asks the question is the machine answering at
    // the strongest anchoring position on the page — the same defect shape
    // #554 measured, where a preselection-shaped default destroyed 19
    // applications until the answer had to be the user's.
    for (const label of ["applied", "interviewing", "assessment", "offer", "rejection", "not job related"]) {
      expect(text.toLowerCase(), `the group header leaked "${label}"`).not.toContain(label);
    }
    // …and it does not claim more than the key proves: same employer NAME and
    // same derived role is not "one application" (#454).
    expect(text.toLowerCase()).not.toContain("one application");
  });

  test("THE HAZARD: the group header carries no answer control of any kind", async ({ page }) => {
    // A bulk "these are all the assessment" affordance would let a rejection
    // misread as a confirmation be swept in as an AUTHORITATIVE USER ANSWER,
    // and a user answer outranks machine evidence permanently. Counted, not
    // absence-checked: a substring assertion survives both a widened condition
    // and a second control spelled differently.
    await page.goto(UNIFORM_PAIR);

    const heading = page.locator("h3").filter({ hasText: BRAND }).first();
    await expect(heading).toBeVisible();
    await expect(
      heading.locator('button, select, input, textarea, a[href], [role="button"]'),
    ).toHaveCount(1);
  });

  test("the counts on screen stay MESSAGES while the expander slices units", async ({ page }) => {
    // Twelve messages in eleven units. The section heading, the Inbox chip and
    // the summary tile all count messages, and this repo has already shipped a
    // "two renderers, one number" defect — so the queue may not be the surface
    // that starts quoting a smaller one.
    await page.goto(UNIFORM_PAIR);

    await expect(page.getByRole("heading", { name: /^12 to review$/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /^show all 12$/ })).toBeVisible();

    // Four UNITS before the expander, and the group is one of them — it sorts
    // first because its newest member is today's.
    await expect(page.locator("#needs-classification > ul > li")).toHaveCount(4);
    await page.getByRole("button", { name: /^show all 12$/ }).click();
    await expect(page.locator("#needs-classification > ul > li")).toHaveCount(11);
  });

  test("the group and its rows are legible at 1024, above the fold", async ({ page }) => {
    // 1024 is the width this product is actually used at; anything that only
    // resolves at Tailwind `xl` (1280) is invisible to its owner. The queue is
    // in the `before` slot, so the group header is the first thing in the card
    // and being below the fold here would be a real finding.
    await page.setViewportSize({ width: 1024, height: 768 });
    await page.goto(MIXED_TRIO);

    const header = groupHeader(page, 3);
    await expect(header).toBeVisible();
    await expect(header).toBeInViewport();

    // The three rows are the group's own, each with its own answer — the
    // grouping collapses the READING and never the asking.
    const group = page.locator("li").filter({ has: page.locator("h3") }).first();
    await expect(group.locator('select[id^="cat-"]')).toHaveCount(3);
    await expect(group.getByRole("button", { name: /^classify$/i })).toHaveCount(3);

    // NOTHING ABOUT ANSWERING A ROW IS ASSERTED HERE, on purpose. `/demo/shell`
    // has no session; fulfilling the classify POST locally makes `classify()`
    // reach `router.refresh()`, which re-runs the server component over the
    // SAME searchParams and the same thirteen seeds — same members, same order,
    // same unit position. The expansion state then survives whether the units
    // are keyed by their group key or by index, so an assertion here would pass
    // under the mutation it looks like it is guarding against. The real gate is
    // `tests/unit/review-queue-group-renders.test.mjs`, whose fixture makes the
    // group CHANGE POSITION when a member leaves, and which reds under
    // `key={index}`.

    // The document lock still holds with a group on screen — `ReviewQueue`
    // positions nothing of its own, and that is what put a box at document
    // scale the last time this subtree grew (#149).
    const scrolls = await page.evaluate(
      () => document.documentElement.scrollHeight > document.documentElement.clientHeight,
    );
    expect(scrolls, "the locked page scrolls as a whole document").toBe(false);
  });
});
