import { expect, test, type Page } from "@playwright/test";

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

/**
 * A PHRASE IN A CONDITIONAL IS NOT A VERDICT — through the real page.
 *
 * Reported from live use on 2026-08-21: four application confirmations were
 * discarded by the Gmail sync and the owner was told nothing had changed. Each
 * carried this near the end of an otherwise ordinary confirmation:
 *
 *   "If you see the job moved to an inactive state, that means the position is
 *    either no longer open, you withdrew from consideration, or you were not
 *    selected for the role."
 *
 * Nothing has been decided. Two strong rejection patterns fired on it anyway.
 *
 * The fix landed in `backend/jobtracker/classifier/rules.py` AND in
 * `lib/demo/rulesLayer.ts`, because this page is the surface that runs the
 * second one — in the tab, with no account, which is where the landing page
 * sends people. A fix on only one layer is half a fix.
 *
 * It is asserted here rather than as a unit test because `rulesLayer.ts`
 * imports `rules.json` without an import attribute and so cannot be loaded by
 * `node --test`; driving the page runs the same code through the real bundler,
 * which is the stronger evidence in any case.
 *
 * The body is RECONSTRUCTED. The real message carries the owner's name, his
 * address and per-message tracking tokens, none of which belong in a committed
 * fixture. What is faithful is the shape — including the dot-laden tracking
 * link immediately before the conditional, which is what defeats a sentence
 * split on a bare `.` and would leave a clean-prose fixture passing while the
 * real mail stayed broken.
 */
test.describe("a conditional explainer is not a rejection", () => {
  const CONDITIONAL =
    "If you see the job moved to an inactive state, that means the position is " +
    "either no longer open, you withdrew from consideration, or you were not " +
    "selected for the role.";

  const TRACKING_LINK =
    "https://example-ats.test/vsimp?d=.eJwViTEOgCAQwP5ys5LzDhCY_IkhSIQoOmBcjH8Xly" +
    "ZtHyh1nfMCDq2RbFk3DJJJdRCLzzs48LEmIVkQT-ufRDgLtH3H42o77DlszY.Lj6ZStc7Wcyj5J3x";

  const CONFIRMATION =
    "Hi there, Thank you for taking the time to submit your application for " +
    "Software Engineer II (Job number: 200045485). We are glad you are interested " +
    "in a career here. You may not receive feedback on your application directly, " +
    "but please know that it is being evaluated. Updates regarding your " +
    `application status can be viewed through your Action Center (${TRACKING_LINK}). ` +
    `${CONDITIONAL} We encourage you to check back frequently. Thank you, ` +
    "Recruiting. This email was sent to you by us. Unsubscribe.";

  test("the confirmation that was thrown away reads as an application", async ({ page }) => {
    await page.goto("/import");
    await page.getByTestId("import-file").setInputFiles({
      name: "conditional.json",
      mimeType: "application/json",
      buffer: Buffer.from(
        JSON.stringify([
          {
            subject: "Thank you for your application!",
            from: "Careers <donotreply@email.careers.example>",
            body: CONFIRMATION,
          },
        ]),
        "utf-8",
      ),
    });

    await expect(page.getByTestId("import-row")).toHaveCount(1);
    const results = page.getByTestId("import-results");
    await expect(
      results.getByText("applied", { exact: true }).first(),
      "an application confirmation was read as something else; the only negative " +
        "language in it is a conditional explaining what an inactive dashboard " +
        "state would mean",
    ).toBeVisible();
    await expect(results.getByText("rejection", { exact: true })).toHaveCount(0);
  });

  /**
   * THE CONTROL. A fix that suppresses the PHRASE rather than its MOOD passes
   * the test above and silently stops the product ever detecting a rejection.
   */
  test("the same clause asserted is still a rejection", async ({ page }) => {
    await page.goto("/import");
    await page.getByTestId("import-file").setInputFiles({
      name: "asserted.json",
      mimeType: "application/json",
      buffer: Buffer.from(
        JSON.stringify([
          {
            subject: "Update on your application",
            from: "Talent <talent@acme.example>",
            body:
              "Hi there, Thank you for your interest in the Software Engineer II " +
              "position and for the time you spent with our team. After careful " +
              "consideration, you were not selected for the role. We had a number " +
              "of strong candidates and the decision was a difficult one. We wish " +
              "you the very best in your search.",
          },
        ]),
        "utf-8",
      ),
    });

    await expect(page.getByTestId("import-row")).toHaveCount(1);
    await expect(
      page.getByTestId("import-results").getByText("rejection", { exact: true }).first(),
      "suppressing the phrase rather than its mood would break exactly this",
    ).toBeVisible();
  });

  /**
   * THE GENRE-FILTER CONTROL. Relaxing the marketing negatives so a footer can
   * no longer erase a real verdict must not re-admit the marketing they were
   * written for.
   */
  test("a job alert carrying the whole vocabulary is still not an application", async ({ page }) => {
    await page.goto("/import");
    await page.getByTestId("import-file").setInputFiles({
      name: "alert.json",
      mimeType: "application/json",
      buffer: Buffer.from(
        JSON.stringify([
          {
            subject: "5 new Software Engineer jobs for you",
            from: "Job Alerts <alerts@jobboard.example>",
            body:
              "New jobs matching your alert. Ironvale is interviewing now. Apply " +
              "today and get an offer faster. Unsubscribe from job alerts.",
          },
        ]),
        "utf-8",
      ),
    });

    await expect(page.getByTestId("import-row")).toHaveCount(1);
    await expect(
      page.getByTestId("import-results").getByText("review", { exact: true }).first(),
      "a job alert must not be filed as a lifecycle verdict",
    ).toBeVisible();
  });
});

/**
 * A REPLY SPEAKS FOR ITSELF, IN THE TAB TOO.
 *
 * Issue #441 changed two things in the scoring walk, and both had to be ported
 * from `backend/jobtracker/classifier/rules.py` into `lib/demo/rulesLayer.ts`:
 * quoted history is no longer scored as this message's own words, and a
 * reply's subject is no longer scored as a headline. A fix on only one layer
 * is half a fix — this page is where the second one runs, in the tab, with no
 * account, which is where the landing page sends people.
 *
 * Asserted here rather than as a unit test for the reason the block above
 * gives: `rulesLayer.ts` imports `rules.json` without an import attribute and
 * cannot be loaded by `node --test`. Driving the page runs the same code
 * through the real bundler, which is the stronger evidence anyway.
 *
 * The parity numbers these three cases were written from, Python beside
 * TypeScript on the same inputs:
 *
 *     Microsoft confirmation      applied 0.90   applied 0.90   (was 0.80)
 *     reply quoting its own ack   interview 0.75 interview 0.75 (was applied 0.95)
 *     withdrawal quoting an offer offer 0.75     offer 0.75     (was offer 0.95)
 *
 * The withdrawal is stated as "not auto-filed" rather than "read as a
 * rejection", because the second is not true yet: stripping the quote stops
 * the product asserting an offer nobody made and starts it asking. Reading it
 * correctly needs withdrawal vocabulary the rules do not have, which is what
 * remains of #417.
 */
test.describe("a reply is not its own thread", () => {
  const QUOTED_INVITE =
    "Hi Ayush, Following up on the below - we would like to invite you to " +
    "interview next week. Are you available Thursday?\n\n" +
    "On Tuesday, Cedarhollow Systems Recruiting wrote:\n" +
    "> Hi Ayush, Thank you for applying to the Backend Engineer position at\n" +
    "> Cedarhollow Systems. Your application has been received.\n";

  const MICROSOFT =
    "Hi Ayush, Thank you for taking the time to submit your application for " +
    "Pre-Training (Job number: 200007619). We are glad you are interested in a " +
    "career at Microsoft, and we are here to help";

  async function classify(
    page: Page,
    subject: string,
    from: string,
    body: string,
  ) {
    await page.goto("/import");
    await page.getByTestId("import-file").setInputFiles({
      name: "reply.json",
      mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify([{ subject, from, body }]), "utf-8"),
    });
    await expect(page.getByTestId("import-row")).toHaveCount(1);
    return page.getByTestId("import-results");
  }

  test("a follow-up quoting its own confirmation is not a confirmation", async ({
    page,
  }) => {
    const results = await classify(
      page,
      "Re: Thank you for applying to Cedarhollow Systems",
      "Recruiting <no-reply@greenhouse.io>",
      QUOTED_INVITE,
    );
    await expect(
      results.getByText("interview", { exact: true }).first(),
      "the tab scored the QUOTE. Every invitation a recruiter sends by " +
        "replying to their own acknowledgement lands on this, and the card " +
        "never advances past applied.",
    ).toBeVisible();
    await expect(results.getByText("applied", { exact: true })).toHaveCount(0);
  });

  /**
   * THE CONTROL on the port. A fix that drops the quote unconditionally would
   * pass the test above and break this one: a bare forward has written nothing
   * readable, so its own words are not an assertion and the quote is all there
   * is. `MIN_ASSERTED_CHARS` is what separates the two.
   */
  test("a bare forward still reads its quote", async ({ page }) => {
    const results = await classify(
      page,
      "FW: your application",
      "Talent <talent@acme.example>",
      "fyi\n\nOn Tuesday, Talent wrote:\n> We regret to inform you that we are " +
        "not moving forward with your candidacy.\n",
    );
    await expect(
      results.getByText("rejection", { exact: true }).first(),
      "forwarding a rejection to yourself with 'fyi' over it left the tab " +
        "with eleven characters to score, which is nothing at all",
    ).toBeVisible();
  });

  test("Microsoft's confirmation files itself in the tab", async ({ page }) => {
    const results = await classify(
      page,
      "Thank you for your application!",
      "Microsoft Careers <donotreply@email.careers.microsoft.com>",
      MICROSOFT,
    );
    await expect(
      results.getByText("applied", { exact: true }).first(),
      "the wording of five real confirmations in the owner's mailbox, none of " +
        "which the product could file before #441",
    ).toBeVisible();
  });
});
