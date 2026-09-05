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

/**
 * The four-message mbox the /import page used to ship behind a "Try a sample
 * export" button. #495 deleted that button — nothing inside the app is the
 * demo — so the bytes live here and reach the page the way a real user's file
 * does, through the file input. They are byte-identical to the fixture the
 * button pressed, deliberately: the verdicts asserted below (a clear applied /
 * interview / rejection, plus one below-gate review) are real classifier
 * output over exactly these four messages, and any edit to them re-writes the
 * assertions too.
 */
const SAMPLE_MBOX = `From 1@import Thu Jul 16 09:00:00 2026
From: Cedar Labs Recruiting <no-reply@greenhouse.io>
Subject: We received your application
Date: Thu, 16 Jul 2026 09:00:00 +0000
Content-Type: text/plain; charset="utf-8"

Thank you for applying to the Software Engineer role at Cedar Labs. Your application has been received and our team is reviewing it.

From 2@import Thu Jul 16 10:00:00 2026
From: Juniper Cloud <recruiting@junipercloud.io>
Subject: Let's schedule your technical interview
Date: Thu, 16 Jul 2026 10:00:00 +0000
Content-Type: text/plain; charset="utf-8"

We'd like to schedule a 45-minute technical interview next week. Please use the Calendly link to book a time to meet the hiring team.

From 3@import Thu Jul 16 11:00:00 2026
From: Atlas Freight Careers <careers@atlasfreight.com>
Subject: Update on your application to Atlas Freight
Date: Thu, 16 Jul 2026 11:00:00 +0000
Content-Type: text/plain; charset="utf-8"

After careful consideration we have decided to move forward with other candidates at this time. We wish you the best in your search.

From 4@import Thu Jul 16 12:00:00 2026
From: Maya Chen <maya@earlystage.xyz>
Subject: Quick question about your background
Date: Thu, 16 Jul 2026 12:00:00 +0000
Content-Type: text/plain; charset="utf-8"

Hi, I had a quick question about your background and some recent projects. Do you have a few minutes this week?
`;

async function importSample(page: Page) {
  await page.getByTestId("import-file").setInputFiles({
    name: "sample.mbox",
    mimeType: "application/mbox",
    buffer: Buffer.from(SAMPLE_MBOX, "utf-8"),
  });
}

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

  test("a four-message mbox parses and classifies on-device", async ({ page }) => {
    await page.goto("/import");
    await importSample(page);

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
    await importSample(page);
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

/**
 * #426 — A ROW'S DISCLOSURE STATE BELONGS TO THE MESSAGE, NOT TO THE POSITION.
 *
 * Filed as "the rows are keyed by index; the messages have ids", and that
 * remedy was ALREADY in the tree and did nothing: the list is keyed by
 * `item.id` (`ImportMail.tsx`), but the id WAS the ordinal — `const id =
 * `m${i}`` in `parseMailFile`. So React saw the same key for a different
 * message across two files, kept the same `ImportRow` instances mounted, and
 * the second file inherited the first file's open rows. Measured before the
 * fix, on this page, with no click between the two imports:
 *
 *     file A (Alpha message 1..4)   expanded: row1=true, row3=true
 *     file B (Beta  message 1..4)   expanded: row1=true, row3=true
 *
 * The ids are content-derived now (`contentId` in `lib/import/parseMail.ts`),
 * so this cannot be satisfied by renaming the scheme while keeping it
 * positional.
 *
 * The two files carry the SAME NUMBER OF ROWS on purpose. With fewer rows in
 * the second file React unmounts the surplus, and a partially positional
 * scheme can pass by accident.
 */
test.describe("an expanded row belongs to its message", () => {
  /** Four ordinary messages. Only the employer and the bodies differ between files. */
  const fourFrom = (who: string, host: string) =>
    Array.from(
      { length: 4 },
      (_, i) =>
        `From ${i + 1}@import.test Thu Sep  3 0${9 + i}:00:00 2026\n` +
        `From: ${who} Recruiting <talent@${host}.test>\n` +
        `Subject: ${who} message ${i + 1}\n` +
        `Date: Thu, 03 Sep 2026 0${9 + i}:00:00 +0000\n` +
        `\n` +
        `Thank you for applying to ${who}. Your application has been received.\n`,
    ).join("\n");

  const ALPHA = fourFrom("Alpha", "alpha");
  const BETA = fourFrom("Beta", "beta");

  async function drop(page: Page, name: string, text: string) {
    await page.getByTestId("import-file").setInputFiles({
      name,
      mimeType: "application/mbox",
      buffer: Buffer.from(text, "utf-8"),
    });
  }

  /** The rows currently disclosed, counted from the DOM the reader sees. */
  const expanded = (page: Page) =>
    page.locator('[data-testid="import-row"][aria-expanded="true"]');

  test("expansion does not follow a row's position into a different file", async ({ page }) => {
    await page.goto("/import");
    await drop(page, "alpha.mbox", ALPHA);

    const rows = page.getByTestId("import-row");
    await expect(rows).toHaveCount(4);

    // THE POSITIVE CONTROL, and it is what keeps the assertion below honest:
    // "nothing is expanded" is also what a fix that broke disclosure entirely
    // would produce.
    await rows.nth(0).click();
    await rows.nth(2).click();
    await expect(rows.nth(0)).toHaveAttribute("aria-expanded", "true");
    await expect(rows.nth(2)).toHaveAttribute("aria-expanded", "true");
    await expect(expanded(page), "rows 1 and 3 must actually open").toHaveCount(2);

    // A different file, four different messages, and no click in between.
    await drop(page, "beta.mbox", BETA);
    await expect(rows).toHaveCount(4);
    await expect(rows.first(), "the second file really did land").toContainText("Beta message 1");
    await expect(
      expanded(page),
      "rows 1 and 3 stayed open over DIFFERENT mail — the id is positional again",
    ).toHaveCount(0);
  });

  /** The issue's own control: pressing Clear results in between must still work. */
  test("Clear results leaves nothing expanded", async ({ page }) => {
    await page.goto("/import");
    await drop(page, "alpha.mbox", ALPHA);

    const rows = page.getByTestId("import-row");
    await rows.nth(0).click();
    await rows.nth(2).click();
    await expect(expanded(page)).toHaveCount(2);

    await page.getByRole("button", { name: "Clear results" }).click();
    await expect(page.getByTestId("import-results")).toHaveCount(0);

    await drop(page, "beta.mbox", BETA);
    await expect(rows).toHaveCount(4);
    await expect(expanded(page)).toHaveCount(0);
  });
});

/**
 * #426 — AN UNESCAPED MBOX SAYS SO INSTEAD OF INVENTING ROWS.
 *
 * mboxrd escapes a body line beginning `From ` as `>From `, and Google Takeout
 * escapes correctly — so this is a malformed file rather than a mishandled
 * valid one. It is fixed anyway because of what the page did with the
 * ambiguity: five messages quoting a forwarded header became `10 messages
 * found`, and the five phantoms rendered beside the real rows with the same
 * confidence chrome, an invented subject and sender `(unknown sender)`.
 * Measured before the fix, both shapes:
 *
 *     totalFound=10  rendered=10  unreadable=0  phantoms=5
 *
 * THREE SHAPES, because no single rule catches more than two of them, and a
 * spec that asserted one would leave half the fix uncovered. Which rule each
 * shape needs is on `Shape` below; both were measured by deleting them one at
 * a time in `tests/unit/parse-mail-mbox-split.test.mjs`.
 */
test.describe("an ambiguous mbox is declared, not invented", () => {
  const PHANTOM = "INVENTED - this line was never a header";

  /**
   * How the quoted block is written. Each name is a different rule doing the
   * work — see `tests/unit/parse-mail-mbox-split.test.mjs`, which measures
   * that against both mutants:
   *
   *   prose     next line is prose and the block has no envelope: either rule.
   *   header    next line is `Subject:`, so only the re-join rule catches it.
   *   envelope  the block carries real `From:`/`Date:` headers, so only the
   *             next-line rule catches it.
   *   escaped   mboxrd's `>From `, i.e. a well-formed file. The control.
   */
  type Shape = "prose" | "header" | "envelope" | "escaped";

  const quotedBlock = (shape: Shape) => {
    const envelope =
      shape === "escaped"
        ? ">From talent@nimbus.test Thu Sep  3 08:00:00 2026"
        : "From talent@nimbus.test Thu Sep  3 08:00:00 2026";
    const quoted = "here is the note they sent, quoted verbatim";
    const middle =
      shape === "header"
        ? [`Subject: ${PHANTOM}`]
        : shape === "envelope"
          ? [
              quoted,
              "From: Nimbus Talent <talent@nimbus.test>",
              "Date: Thu, 03 Sep 2026 08:00:00 +0000",
              `Subject: ${PHANTOM}`,
            ]
          : [quoted, `Subject: ${PHANTOM}`];

    return [envelope, ...middle, "", "The quoted note runs on for another line."].join("\n");
  };

  const fiveForwards = (shape: Shape) =>
    Array.from(
      { length: 5 },
      (_, i) =>
        `From ${i + 1}@import.test Thu Sep  3 09:00:00 2026\n` +
        `From: Nimbus Talent <talent@nimbus.test>\n` +
        `Subject: Fwd: your application ${i + 1}\n` +
        `Date: Thu, 03 Sep 2026 09:0${i}:00 +0000\n` +
        `\n` +
        `Passing this along, see the quoted note below.\n` +
        `\n` +
        `${quotedBlock(shape)}\n`,
    ).join("\n");

  async function dropMbox(page: Page, shape: Shape) {
    await page.goto("/import");
    await page.getByTestId("import-file").setInputFiles({
      name: "forwarded.mbox",
      mimeType: "application/mbox",
      buffer: Buffer.from(fiveForwards(shape), "utf-8"),
    });
  }

  for (const shape of ["prose", "header", "envelope"] as const) {
    test(`five messages quoting a header (${shape}) are five rows, and the file is called malformed`, async ({
      page,
    }) => {
      await dropMbox(page, shape);

      await expect(page.getByTestId("import-row")).toHaveCount(5);
      await expect(page.getByText(/messages found/)).toContainText("5 messages found");
      await expect(
        page.getByTestId("import-results").getByText(PHANTOM),
        "a quoted line was rendered as a message of its own",
      ).toHaveCount(0);
      await expect(
        page.getByTestId("import-malformed"),
        "the page has to say the split was guessed rather than state a count as fact",
      ).toBeVisible();
      await expect(page.getByTestId("import-malformed")).toContainText(/mbox/i);
    });
  }

  /**
   * THE CONTROL THAT FAILS A BAD GUARD. The same five messages with mboxrd's
   * `>From ` escape are a WELL-FORMED file: five rows, and no warning at all.
   * A guard that fires on both files measures nothing.
   */
  test("the same file with >From escaping is five rows and raises no warning", async ({ page }) => {
    await dropMbox(page, "escaped");

    await expect(page.getByTestId("import-row")).toHaveCount(5);
    await expect(page.getByText(/messages found/)).toContainText("5 messages found");
    await expect(
      page.getByTestId("import-malformed"),
      "a correctly escaped export must not be called malformed",
    ).toHaveCount(0);
  });
});
