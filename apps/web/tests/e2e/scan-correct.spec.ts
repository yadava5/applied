import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, MOBILE_375, startConsoleWatch } from "./helpers";

/**
 * E2E for correcting a verdict in the LIVE SCAN view.
 *
 * The complaint: "this is clearly an assessment, but I don't see anywhere to
 * classify, and there is no field for showing anything for assessment anywhere".
 * Both halves are exercised here — the control that did not exist, and the chip
 * that cannot exist until some message holds the category.
 *
 * WHY /demo/scan AND NOT /inbox?view=scan. That page needs a Supabase session
 * AND a linked Gmail account; CI has neither, so a spec pointed at it could
 * only `test.skip` itself. Thirteen of this suite's tests are already parked
 * behind session guards and a fourteenth would be one more thing that
 * cannot fail. (The count read "twenty-one" until it was measured: that
 * conflated the session guard with `production.spec.ts`'s twelve
 * `PLAYWRIGHT_PROD_BUILD` skips, which are a build-mode gate and DO run on
 * the production job. Two different gates, two different numbers — see
 * `session.ts` and #188.) `/demo/scan` is the same pattern `/demo/settings` established
 * for exactly this reason: the REAL `InboxWorkbench`, the REAL
 * `ReclassifyControl`, the real chip vocabulary and the real session-snapshot
 * cache, over the simulated transport in `lib/gmail/transport.ts`. The only
 * thing simulated is the network, and the simulated classify reproduces the
 * response contract that makes this feature hard — `needs_employer: true`, a
 * 2xx that files nothing.
 *
 * What this spec deliberately does NOT prove: that the backend stores a
 * scanned message. That is `backend/tests/test_scan_classify.py`, which drives
 * the real endpoint against a real database.
 */

/** The fixture row the complaint is about: an assessment called "other" at 0%. */
const ASSESSMENT_SUBJECT = "Your HackerRank assessment for Software Engineer II";
/** Sent from a personal address, so no employer can be read out of it. */
const ANONYMOUS_SUBJECT = "Next steps + take-home details";
/** Listed by Gmail with an unparseable Date header — unstorable, so uncorrectable. */
const UNDATED_SUBJECT = "Coding challenge invitation (no date header)";

async function openScan(page: Page) {
  await page.goto("/demo/scan");
  // The mine is asynchronous even in the demo (it renders its progress bar), so
  // wait for a row rather than for the page.
  await expect(page.getByText(ASSESSMENT_SUBJECT)).toBeVisible();
}

/** The row `<li>` carrying a given subject. */
function row(page: Page, subject: string) {
  return page.locator("li").filter({ hasText: subject }).first();
}

/** A filter chip by its category name, e.g. /^assessment \d+$/. */
function chip(page: Page, label: string) {
  return page.getByRole("button", { name: new RegExp(`^${label} \\d+$`) });
}

async function reclassify(page: Page, subject: string, category: string) {
  const target = row(page, subject);
  await target.getByRole("button", { name: /^reclassify/i }).click();
  await target.getByLabel(/new category for/i).selectOption(category);
  await target.getByRole("button", { name: /^apply$/i }).click();
}

test.describe("live scan — correcting a verdict", () => {
  test("every storable row offers a correction; an unstorable one says why", async ({ page }) => {
    const watch = startConsoleWatch(page);
    await openScan(page);

    // The row from the screenshot: labelled "other", and now pressable.
    await expect(
      row(page, ASSESSMENT_SUBJECT).getByRole("button", { name: /^reclassify/i }),
    ).toBeVisible();

    // The undated one refuses honestly instead of offering a control that
    // would fail: `Email.received_at` is NOT NULL and is never fabricated.
    const undated = row(page, UNDATED_SUBJECT);
    await expect(undated.getByRole("button", { name: /^reclassify/i })).toHaveCount(0);
    await expect(undated).toContainText(/won't store it/i);

    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });

  test("assessment has nowhere to show until a message holds it — then it does", async ({
    page,
  }) => {
    await openScan(page);

    // The state the owner is complaining about: chips for what the classifier
    // found, and no assessment anywhere on the page.
    await expect(chip(page, "other")).toBeVisible();
    await expect(chip(page, "assessment")).toHaveCount(0);

    await reclassify(page, ASSESSMENT_SUBJECT, "assessment");

    // The row moved...
    const corrected = row(page, ASSESSMENT_SUBJECT);
    await expect(corrected).toContainText(/corrected/i);
    // ...and so did the counts the chips are drawn from, which is the only way
    // the category becomes visible or filterable at all.
    await expect(chip(page, "assessment")).toHaveText(/^assessment 1$/);

    // And the chip filters: pressing it leaves the corrected row and nothing else.
    await chip(page, "assessment").click();
    await expect(page.getByText(ASSESSMENT_SUBJECT)).toBeVisible();
    await expect(page.getByText(UNDATED_SUBJECT)).toHaveCount(0);
  });

  test("the correction survives leaving the view and coming back", async ({ page }) => {
    await openScan(page);
    await reclassify(page, ASSESSMENT_SUBJECT, "assessment");
    await expect(chip(page, "assessment")).toBeVisible();

    // This view rehydrates from a per-tab snapshot on remount, so a correction
    // that lived only in React state would be silently replaced by the
    // classifier's rejected verdict — the "did my click do anything?" bug with
    // an extra step. sessionStorage survives this navigation, as it does the
    // real Inbox → Dashboard → Inbox trip.
    await page.goto("/demo");
    await page.goto("/demo/scan");

    await expect(page.getByText(ASSESSMENT_SUBJECT)).toBeVisible();
    await expect(chip(page, "assessment")).toHaveText(/^assessment 1$/);
    await expect(row(page, ASSESSMENT_SUBJECT)).toContainText(/corrected/i);
  });

  test("a 2xx that filed nothing asks for the company instead of claiming success", async ({
    page,
  }) => {
    await openScan(page);

    // `assessment` maps to a real stage, so it cannot file without an employer —
    // and nothing in this message names one.
    await reclassify(page, ANONYMOUS_SUBJECT, "assessment");

    const target = row(page, ANONYMOUS_SUBJECT);
    await expect(target.getByRole("status")).toContainText(/which company/i);
    // The row must NOT have reported success, and must still be correctable.
    await expect(target).not.toContainText(/your call is the verdict now/i);
    await expect(chip(page, "assessment")).toHaveCount(0);

    await target.getByLabel(/company this email is from/i).fill("Cedar Labs");
    await target.getByRole("button", { name: /^apply$/i }).click();

    await expect(target).toContainText(/your call is the verdict now/i);
    await expect(chip(page, "assessment")).toHaveText(/^assessment 1$/);
  });

  test("no horizontal overflow with a correction panel open on mobile", async ({ page }) => {
    await page.setViewportSize(MOBILE_375);
    await openScan(page);
    await row(page, ASSESSMENT_SUBJECT)
      .getByRole("button", { name: /^reclassify/i })
      .click();
    await expectNoHorizontalOverflow(page);
  });
});
