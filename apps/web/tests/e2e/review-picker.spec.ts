import { expect, test, type Page, type Request } from "@playwright/test";

import { startConsoleWatch } from "./helpers";

/**
 * THE REVIEW QUEUE MUST NOT ANSWER ITS OWN QUESTION (#554).
 *
 * `ReviewQueue` asks "which application is this about?" when an employer holds
 * several cards and the chosen stage answers an existing one. Its default
 * answer was "not one of these" — the option that discards the question was
 * pre-selected — so a user who read the subject, chose a stage and clicked
 * classify had answered it without choosing it. On the backend that request is
 * indistinguishable from silence, and silence is answered by the employer's
 * OLDEST live row; on a rejection that moves a live application to a terminal
 * status nothing walks back. Replayed over 2,701 queue answers, requiring the
 * pick took applications destroyed from 19 to 0 — a one-off probe, whose
 * provenance is written out in
 * `backend/tests/test_none_of_these_opens_a_row.py`.
 *
 * WHY THIS FILE HAS TO EXIST IN A BROWSER. The decision itself is a pure
 * function in `lib/dashboard/review.ts` and `tests/unit/` proves it four ways.
 * None of that can see the wire between the component's state and the request
 * body: replacing the assignment the component sends with a literal `null`
 * leaves every unit assertion green, and the picker becomes theatre — the user
 * answers, the answer never leaves the browser, and the backend tie-breaks onto
 * the oldest row exactly as before. So the assertions below are about the
 * REQUEST, not about the radio.
 *
 * WHY /demo/shell AND NOT /dashboard. Every session-gated spec in this suite
 * skips in CI and always has (see `session.ts` — 13 tests that have never run).
 * A gate that skips is green, which is the failure mode this whole file is
 * about. `/demo/shell?review=N` mounts the REAL `ReviewQueue` over the demo
 * board with no session, so these execute on every run.
 */

/** The seed whose employer holds four cards — the picker's reason to exist. */
const MULTI_CARD = /thank you for your interest in northstar systems/i;
/** The seed whose employer holds exactly one — the control that must stay 1 click. */
const SINGLE_CARD = /thank you for your interest in quarry data/i;
/** Exactly TWO — the threshold's own value, and the direction a control misses. */
const TWO_CARDS = /thank you for your interest in cedar labs/i;

const QUEUE_URL = "/demo/shell?review=10";

/** The row's `<li>`, located by its own subject text. */
function rowFor(page: Page, subject: RegExp) {
  return page.locator("li").filter({ hasText: subject }).first();
}

/**
 * Open the queue with every row on screen.
 *
 * `ReviewQueue` collapses to its first four rows, and both seeds this file
 * needs are appended at the end of the fixture list — deliberately, because
 * seeds cycle by index and inserting one would re-date and re-order the queue
 * every geometry spec in `shell.spec.ts` measures. So the expander is clicked
 * rather than worked around.
 */
async function openQueue(page: Page) {
  await page.goto(QUEUE_URL);
  await page.getByRole("button", { name: /show all 10/i }).click();
}

/**
 * Every classify POST this page makes, with its parsed body.
 *
 * Fulfilled locally rather than allowed through: /demo has no session, so the
 * real route answers 401 and the row would show an error instead of the state
 * under test. What is being measured is what the browser SENT.
 */
async function captureClassifyPosts(page: Page): Promise<Record<string, unknown>[]> {
  const sent: Record<string, unknown>[] = [];
  await page.route("**/api/applications/review/*/classify", async (route, request: Request) => {
    sent.push(JSON.parse(request.postData() ?? "{}"));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ classified_as: "rejection", application_id: 1, needs_employer: false }),
    });
  });
  return sent;
}

test.describe("the review queue's application picker", () => {
  test("asks, and will not send until it is answered", async ({ page }) => {
    const watch = startConsoleWatch(page);
    const sent = await captureClassifyPosts(page);
    await openQueue(page);

    const row = rowFor(page, MULTI_CARD);
    await expect(row).toBeVisible();
    const classify = row.getByRole("button", { name: /^classify$/i });

    // ORDER MATTERS, and getting it wrong makes this test true by construction:
    // the button is ALREADY disabled while the stage select sits on its
    // placeholder, so asserting "disabled" before choosing a stage would pass
    // forever. Choose the stage first, and only then is the button's state a
    // statement about the picker.
    await expect(row.getByRole("radio")).toHaveCount(0);
    await row.getByRole("combobox").selectOption("rejection");

    // Four candidate cards plus "none of these".
    const radios = row.getByRole("radio");
    await expect(radios).toHaveCount(5);

    // THE DEFECT, as an assertion: nothing is pre-selected. This is the line
    // that fails on the shipped code, where the last radio was checked.
    await expect(row.getByRole("radio", { checked: true })).toHaveCount(0);
    await expect(classify).toBeDisabled();

    // …and it stays unsent. A disabled button is not proof: three other
    // controls in this component re-send the same decision without consulting
    // it, which is why the guard lives inside `classify()`.
    expect(sent, "nothing may be sent before the question is answered").toEqual([]);

    await radios.nth(0).check();
    await expect(classify).toBeEnabled();

    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });

  test("sends the application the user picked, and only that one", async ({ page }) => {
    const sent = await captureClassifyPosts(page);
    await openQueue(page);

    const row = rowFor(page, MULTI_CARD);
    await row.getByRole("combobox").selectOption("rejection");
    // The SECOND candidate, deliberately: the failure this fixes files onto the
    // employer's oldest row, so picking the first would be satisfied by the bug.
    await row.getByRole("radio").nth(1).check();
    await row.getByRole("button", { name: /^classify$/i }).click();

    await expect.poll(() => sent.length).toBe(1);
    const body = sent[0]!;
    expect(body.category).toBe("rejection");
    expect(typeof body.application_id).toBe("number");
    expect("none_of_these" in body).toBe(false);

    // The id is the one the second radio names, not merely "a number". Without
    // this, mapping every pick to the same id passes everything above.
    const value = await row.getByRole("radio").nth(1).getAttribute("value");
    expect(String(body.application_id)).toBe(value);
  });

  test("'none of these' is sent as an answer, not as an absent id", async ({ page }) => {
    const sent = await captureClassifyPosts(page);
    await openQueue(page);

    const row = rowFor(page, MULTI_CARD);
    await row.getByRole("combobox").selectOption("rejection");
    await row.getByRole("radio", { name: /none of these/i }).check();
    await row.getByRole("button", { name: /^classify$/i }).click();

    await expect.poll(() => sent.length).toBe(1);
    const body = sent[0]!;
    // Both halves. An absent `application_id` alone is what the backend reads
    // as "nobody asked" and answers with the oldest row — the exact outcome the
    // user just declined — so the flag's presence is the assertion that matters.
    expect(body.none_of_these).toBe(true);
    expect("application_id" in body).toBe(false);
  });

  test("a single-application employer is still one click", async ({ page }) => {
    const sent = await captureClassifyPosts(page);
    await openQueue(page);

    // THE CONTROL. The fix adds a click to ambiguous rows only. Widening the
    // picker's predicate from "two or more candidates" to "one or more" would
    // put a mandatory question on most of the queue, and every other assertion
    // in this file would still pass.
    const row = rowFor(page, SINGLE_CARD);
    await expect(row).toBeVisible();
    await row.getByRole("combobox").selectOption("rejection");

    await expect(row.getByRole("radio")).toHaveCount(0);
    const classify = row.getByRole("button", { name: /^classify$/i });
    await expect(classify).toBeEnabled();

    await classify.click();
    await expect.poll(() => sent.length).toBe(1);
    expect("application_id" in sent[0]!).toBe(false);
    expect("none_of_these" in sent[0]!).toBe(false);
  });

  test("an employer with exactly TWO applications is still asked about", async ({ page }) => {
    /*
     * THE CONTROL THAT POINTS THE OTHER WAY, and the one this file shipped
     * without.
     *
     * `showPicker` is a threshold — `candidates.length >= 2` — and a threshold
     * needs a case on each side of it AND one sitting on it. The multi-card seed
     * yields four and the single-card control yields one, so `>= 2` could be
     * narrowed to `>= 3` and both stayed green: four is still >= 3, one is still
     * < 3. An employer holding exactly two applications would then be asked
     * nothing, the request would carry no answer, and the backend would
     * tie-break onto the oldest row — this defect, restored, for the smallest
     * ambiguous case there is.
     *
     * Narrowing is the direction that reintroduces the bug and widening is the
     * direction the other control catches. Both are needed; neither implies the
     * other.
     */
    const sent = await captureClassifyPosts(page);
    await openQueue(page);

    const row = rowFor(page, TWO_CARDS);
    await expect(row).toBeVisible();
    await row.getByRole("combobox").selectOption("rejection");

    // Two candidates plus "none of these" — the question IS asked here.
    await expect(row.getByRole("radio")).toHaveCount(3);
    await expect(row.getByRole("radio", { checked: true })).toHaveCount(0);
    await expect(row.getByRole("button", { name: /^classify$/i })).toBeDisabled();
    expect(sent).toEqual([]);
  });

  for (const stage of ["interview", "assessment", "offer", "rejection"]) {
    test(`a ${stage} at a multi-card employer is asked about, not guessed`, async ({
      page,
    }) => {
      /*
       * EVERY MEMBER OF `LIFECYCLE_ANSWERS`, one test each.
       *
       * The set decides whether the question is asked at all, and the rest of
       * this file only ever chooses "rejection". Deleting "offer" from it left
       * every other test here green while an offer at a multi-card employer
       * skipped the picker and tie-broke onto the oldest row. A set whose
       * members are not individually asserted is a set with one member.
       */
      await openQueue(page);
      const row = rowFor(page, MULTI_CARD);
      await row.getByRole("combobox").selectOption(stage);

      await expect(row.getByRole("radio")).toHaveCount(5);
      await expect(row.getByRole("button", { name: /^classify$/i })).toBeDisabled();
    });
  }

  test("a category that opens or closes nothing asks no question", async ({ page }) => {
    /*
     * The control for the loop above. `applied` opens a NEW application and
     * "not job related" opens none, so neither answers an existing card and
     * neither may put a picker on screen — which is what stops the loop being
     * satisfied by "always show the picker".
     */
    await openQueue(page);
    const row = rowFor(page, MULTI_CARD);

    for (const stage of ["applied", "other"]) {
      await row.getByRole("combobox").selectOption(stage);
      await expect(row.getByRole("radio")).toHaveCount(0);
      await expect(row.getByRole("button", { name: /^classify$/i })).toBeEnabled();
    }
  });

  test("changing the stage takes the pick back and blocks the send again", async ({ page }) => {
    const sent = await captureClassifyPosts(page);
    await openQueue(page);

    const row = rowFor(page, MULTI_CARD);
    const classify = row.getByRole("button", { name: /^classify$/i });
    await row.getByRole("combobox").selectOption("rejection");
    await row.getByRole("radio").nth(0).check();
    await expect(classify).toBeEnabled();

    // The pick answered a question about the PREVIOUS stage. It is cleared, and
    // the send must be blocked again rather than falling back to a default.
    await row.getByRole("combobox").selectOption("interview");
    await expect(row.getByRole("radio", { checked: true })).toHaveCount(0);
    await expect(classify).toBeDisabled();
    expect(sent).toEqual([]);
  });

  test("the side door stays shut after a needs_employer round trip", async ({ page }) => {
    /*
     * THE ONE SEQUENCE THAT BYPASSES THE SUBMIT BUTTON.
     *
     * Three controls in this component re-send the same decision — both
     * "did you mean…" buttons and the needs-employer form's own submit — and
     * none of them reads the button's `disabled`. So: answer the picker,
     * classify, have the backend come back `needs_employer` (it files nothing
     * and leaves the row in the queue), then change the stage. The stage change
     * clears the pick. If the prompt is still mounted, its "file it" button
     * fires `classify()` with no answer at all, and the request goes out blind
     * — the exact defect, through a door the disabled attribute does not cover.
     *
     * THREE THINGS HOLD THAT DOOR SHUT and this test names none of them,
     * deliberately: the prompts are cleared when the stage changes (they were
     * answers ABOUT the previous submission), the form's own submit consults
     * the same gate, and `classify()` refuses outright when `canSubmitReview`
     * says no. Any one of the three is sufficient, so removing one — or two —
     * leaves this green, correctly, because the door is still shut. Removing
     * all three turns it red. Measured, not assumed: each of the seven
     * combinations was run.
     *
     * That is the property worth asserting. "The guard exists" is a statement
     * about an implementation; "no reachable path sends a decision with no
     * answer" is a statement about the product, and it survives a rewrite that
     * moves the guard somewhere else.
     */
    const sent: Record<string, unknown>[] = [];
    await page.route("**/api/applications/review/*/classify", async (route, request: Request) => {
      sent.push(JSON.parse(request.postData() ?? "{}"));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          classified_as: "rejection",
          application_id: null,
          needs_employer: true,
          message_id: "demo-held-8",
          detail: "We couldn't tell which company this email is from.",
        }),
      });
    });
    await openQueue(page);

    const row = rowFor(page, MULTI_CARD);
    await row.getByRole("combobox").selectOption("rejection");
    await row.getByRole("radio").nth(0).check();
    await row.getByRole("button", { name: /^classify$/i }).click();
    await expect.poll(() => sent.length).toBe(1);
    expect(typeof sent[0]!.application_id).toBe("number");

    // The stage change takes the pick back. Whatever is on screen afterwards,
    // nothing may send a decision that does not carry an answer.
    await row.getByRole("combobox").selectOption("interview");
    const fileIt = row.getByRole("button", { name: /file it/i });
    if (await fileIt.count()) {
      const company = row.getByRole("textbox");
      if (await company.count()) await company.fill("Northstar Systems");
      await fileIt.click({ trial: false }).catch(() => {});
      await page.waitForTimeout(500);
    }

    for (const body of sent) {
      const answered = "application_id" in body || "none_of_these" in body;
      expect(answered, `a decision was sent with no answer: ${JSON.stringify(body)}`).toBe(true);
    }
  });
});
