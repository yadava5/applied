import { expect, test } from "@playwright/test";

import { expectNoHorizontalOverflow, MOBILE_375, startConsoleWatch } from "./helpers";

/**
 * E2E for "Import your mail" — the no-OAuth, no-sign-in, on-device path.
 *
 * The whole feature runs client-side: a file is read, parsed, and classified
 * with the layer-1 rules engine in the tab. These tests prove the pipeline
 * end to end (parse → classify → verdicts + the 0.85 gate) for each accepted
 * format, and that the page stays clean and free of horizontal overflow.
 */

test.describe("import your mail", () => {
  test("is reachable without auth and explains the privacy guarantee", async ({ page }) => {
    const watch = startConsoleWatch(page);
    await page.goto("/import");
    await expect(page).toHaveURL(/\/import$/);
    await expect(page.getByRole("heading", { name: "Import your mail" })).toBeVisible();
    await expect(page.getByText(/On-device only/i)).toBeVisible();
    await expect(page.getByText(/the mail never leaves your device/i)).toBeVisible();
    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });

  test("the sample export parses and classifies four messages on-device", async ({ page }) => {
    await page.goto("/import");
    await page.getByTestId("import-sample").click();

    const results = page.getByTestId("import-results");
    await expect(results).toBeVisible();
    await expect(page.getByTestId("import-row")).toHaveCount(4);

    // The verdicts are real classifier output, not canned: the sample carries
    // a clear applied / interview / rejection, plus one below-gate review.
    await expect(results.getByText("applied", { exact: true }).first()).toBeVisible();
    await expect(results.getByText("interview", { exact: true }).first()).toBeVisible();
    await expect(results.getByText("rejection", { exact: true }).first()).toBeVisible();
    await expect(results.getByText("review", { exact: true }).first()).toBeVisible();

    // The 0.85 gate shows in an expanded trace.
    await page.getByTestId("import-row").first().click();
    await expect(page.getByText(/gate 0\.85/).first()).toBeVisible();
  });

  test("a JSON batch is parsed and classified", async ({ page }) => {
    await page.goto("/import");
    const json = JSON.stringify([
      {
        subject: "We received your application",
        from: "Cedar Labs <no-reply@greenhouse.io>",
        body: "Thank you for applying. Your application has been received and is under review.",
      },
      {
        subject: "Congratulations — offer details inside",
        from: "people@beaconhealth.io",
        body: "We are pleased to extend an offer. The compensation and start date are attached.",
      },
    ]);
    await page.getByTestId("import-file").setInputFiles({
      name: "mail.json",
      mimeType: "application/json",
      buffer: Buffer.from(json, "utf-8"),
    });

    await expect(page.getByTestId("import-results")).toBeVisible();
    await expect(page.getByTestId("import-row")).toHaveCount(2);
    await expect(page.getByText("offer", { exact: true }).first()).toBeVisible();
  });

  test("a single .eml message is parsed", async ({ page }) => {
    await page.goto("/import");
    const eml = [
      "From: Juniper Cloud <recruiting@junipercloud.io>",
      "Subject: Let's schedule your technical interview",
      'Content-Type: text/plain; charset="utf-8"',
      "",
      "We'd like to schedule a 45-minute technical interview next week. Use the Calendly link to book.",
      "",
    ].join("\n");
    await page.getByTestId("import-file").setInputFiles({
      name: "message.eml",
      mimeType: "message/rfc822",
      buffer: Buffer.from(eml, "utf-8"),
    });

    await expect(page.getByTestId("import-row")).toHaveCount(1);
    await expect(page.getByText("interview", { exact: true }).first()).toBeVisible();
  });

  test("an unparseable file shows an honest error, not a crash", async ({ page }) => {
    await page.goto("/import");
    await page.getByTestId("import-file").setInputFiles({
      name: "broken.json",
      mimeType: "application/json",
      buffer: Buffer.from("{ this is not valid json ", "utf-8"),
    });
    await expect(page.getByTestId("import-error")).toBeVisible();
    await expect(page.getByTestId("import-results")).toHaveCount(0);
  });

  test("no horizontal overflow on mobile with results", async ({ page }) => {
    await page.setViewportSize(MOBILE_375);
    await page.goto("/import");
    await page.getByTestId("import-sample").click();
    await expect(page.getByTestId("import-results")).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });
});
