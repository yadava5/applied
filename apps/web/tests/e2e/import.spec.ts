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

  test("a real multipart mbox with a mixed-case boundary decodes cleanly", async ({ page }) => {
    // Regression: MIME boundaries are case-sensitive (RFC 2046), but the parser
    // used to lowercase the whole Content-Type — so a mixed-case boundary
    // (`Apple-Mail=_…`, Outlook `_000_…`) failed to split and the raw MIME (both
    // parts + boundary lines + undecoded QP) leaked into the classifier as body.
    // A short plain part makes any leak land inside the visible snippet.
    await page.goto("/import");
    const mbox = [
      "From 1@import Thu Jul 16 10:00:00 2026",
      "From: Juniper Cloud <recruiting@junipercloud.io>",
      "Subject: Let's schedule your technical interview",
      "MIME-Version: 1.0",
      'Content-Type: multipart/alternative; boundary="Apple-Mail=_AbC123XyZ"',
      "",
      "--Apple-Mail=_AbC123XyZ",
      'Content-Type: text/plain; charset="utf-8"',
      "Content-Transfer-Encoding: quoted-printable",
      "",
      "Please pick a slot for your interview at our caf=C3=A9.",
      "--Apple-Mail=_AbC123XyZ",
      'Content-Type: text/html; charset="utf-8"',
      "",
      "<html><body><p>Please pick a slot.</p></body></html>",
      "--Apple-Mail=_AbC123XyZ--",
      "",
    ].join("\n");
    await page.getByTestId("import-file").setInputFiles({
      name: "takeout.mbox",
      mimeType: "application/mbox",
      buffer: Buffer.from(mbox, "utf-8"),
    });

    await expect(page.getByTestId("import-row")).toHaveCount(1);
    await expect(page.getByText("interview", { exact: true }).first()).toBeVisible();

    // Expand the row: the decoded body must be the clean plain text (QP `=C3=A9`
    // → café), never the raw boundary / html that the lowercasing bug leaked.
    await page.getByTestId("import-row").click();
    const results = page.getByTestId("import-results");
    await expect(results.getByText(/café/)).toBeVisible();
    await expect(results.getByText(/Apple-Mail=_AbC123XyZ/)).toHaveCount(0);
    await expect(results.getByText(/text\/html/)).toHaveCount(0);
  });

  /**
   * "HONEST" HAS TO MEAN THE WORDS, not the presence of a banner.
   *
   * This asserted only that `import-error` was visible, and that is satisfied
   * by a message saying the opposite of the truth. A valid 1.1GB Takeout mbox
   * of 1,664,400 messages produced:
   *
   *   "No messages found in that file. Expected a Google Takeout .mbox..."
   *
   * on the page whose own instructions tell you to produce that file. This
   * test went green on exactly that input. So it now reads the text.
   */
  test("an unparseable file shows an honest error, not a crash", async ({ page }) => {
    await page.goto("/import");
    await page.getByTestId("import-file").setInputFiles({
      name: "broken.json",
      mimeType: "application/json",
      buffer: Buffer.from("{ this is not valid json ", "utf-8"),
    });
    const error = page.getByTestId("import-error");
    await expect(error).toBeVisible();
    // The file IS malformed, so naming the format is the true statement here.
    await expect(error).toContainText(/valid \.mbox, \.eml, or JSON/i);
    await expect(page.getByTestId("import-results")).toHaveCount(0);
  });

  /**
   * THE COUNTS ON SCREEN ADD UP.
   *
   * Nothing asserted the found / classified / skipped triple, which is why a
   * 400-message batch could quietly list 393 and a 1,000-record file could
   * claim it "classified the first 280" after reading the first 400. Both
   * were found by driving this page with an adversarial corpus, and neither
   * was representable in this spec.
   */
  test("every message found is accounted for on screen", async ({ page }) => {
    const records = [
      ...Array.from({ length: 6 }, (_, i) => ({
        subject: `Interview ${i}`,
        from: `recruiter${i}@acme.test`,
        body: "We would like to schedule a technical interview with the team.",
      })),
      ...Array.from({ length: 4 }, () => ({ subject: "", from: "", body: "" })),
    ];

    await page.goto("/import");
    await page.getByTestId("import-file").setInputFiles({
      name: "accounting.json",
      mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify(records), "utf-8"),
    });

    await expect(page.getByTestId("import-results")).toBeVisible();
    const summary = page.getByText(/messages found/);
    await expect(summary).toContainText("10 messages found");
    await expect(summary).toContainText("classified 6");
    await expect(
      summary,
      "the 4 blank records were read and produced nothing, and the page must say so rather than listing 6 rows under '10 found'",
    ).toContainText(/4 could not be read/);
    await expect(page.getByTestId("import-row")).toHaveCount(6);
  });

  test("no horizontal overflow on mobile with results", async ({ page }) => {
    await page.setViewportSize(MOBILE_375);
    await page.goto("/import");
    await page.getByTestId("import-sample").click();
    await expect(page.getByTestId("import-results")).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });
});
