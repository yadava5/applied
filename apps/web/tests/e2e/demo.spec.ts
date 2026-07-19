import { expect, test } from "@playwright/test";

import {
  expectNoHorizontalOverflow,
  MOBILE_375,
  startConsoleWatch,
} from "./helpers";

/**
 * E2E for the auth-free product demo (`/demo`): the pipeline board + the
 * interactive decision trace, and the new bridge into the sample inbox.
 */
test.describe("live demo (/demo)", () => {
  test("renders the pipeline board and review sections cleanly", async ({ page }) => {
    const watch = startConsoleWatch(page);
    await page.goto("/demo");

    await expect(page.getByText("01 · pipeline")).toBeVisible();
    await expect(page.getByRole("heading", { name: /decision trace/i })).toBeVisible();
    // Pipeline columns render the fixture applications.
    await expect(page.getByText("Beacon Health")).toBeVisible();

    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });

  test("the decision trace rows expand on click (real effect)", async ({ page }) => {
    await page.goto("/demo");
    // The first trace row is open by default; open another and assert its
    // adjudication copy appears.
    const offerRow = page.getByRole("button", { name: /offer details inside/i });
    await offerRow.click();
    await expect(page.getByText(/clears the 0.85 gate/i).first()).toBeVisible();
  });

  test("the sample-inbox bridge routes to /demo/inbox", async ({ page }) => {
    await page.goto("/demo");
    await page
      .getByRole("link", { name: /Run a full sample inbox through the real classifier/i })
      .click();
    await expect(page).toHaveURL(/\/demo\/inbox$/);
    await expect(page.getByRole("heading", { name: "Sample inbox" })).toBeVisible();
  });

  test("no horizontal overflow at 375px", async ({ page }) => {
    const watch = startConsoleWatch(page);
    await page.setViewportSize(MOBILE_375);
    await page.goto("/demo");
    await expect(page.getByText("01 · pipeline")).toBeVisible();
    await expectNoHorizontalOverflow(page);
    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });
});
