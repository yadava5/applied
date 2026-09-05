import { expect, test } from "@playwright/test";

import {
  expectNoHorizontalOverflow,
  MOBILE_375,
  startConsoleWatch,
} from "./helpers";

/**
 * E2E for the public sample inbox at `/demo/inbox` — the zero-connection
 * classification demo. Drives every control and asserts each has a real
 * effect: rows expand into their decision trace, the live layer-1 recompute
 * agrees with the stored verdict, and the playground reclassifies on input.
 */
test.describe("sample inbox (/demo/inbox)", () => {
  test("renders the header, provenance note, and derived stats", async ({ page }) => {
    const watch = startConsoleWatch(page);
    await page.goto("/demo/inbox");

    await expect(page.getByRole("heading", { name: "Sample inbox" })).toBeVisible();
    await expect(page.getByText(/How these verdicts are produced/i)).toBeVisible();

    // Stats are derived from the fixtures, not hardcoded: 11 scanned, 9 auto, 2 held.
    await expect(page.getByTestId("stat-scanned")).toHaveText("11");
    await expect(page.getByTestId("stat-auto-classified")).toHaveText("9 · 82%");
    await expect(page.getByTestId("stat-held-for-review")).toHaveText("2");

    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });

  test("lists all eleven sample emails", async ({ page }) => {
    await page.goto("/demo/inbox");
    await expect(page.getByTestId("sample-row")).toHaveCount(11);
  });

  test("clicking a row toggles its decision trace (real effect)", async ({ page }) => {
    await page.goto("/demo/inbox");
    const rows = page.getByTestId("sample-row");

    // First row is expanded by default.
    await expect(rows.first()).toHaveAttribute("aria-expanded", "true");

    // A collapsed row expands on click, and its trace becomes visible.
    const rejection = page.getByRole("button", { name: /Update on your application to Atlas Freight/i });
    await expect(rejection).toHaveAttribute("aria-expanded", "false");
    await rejection.click();
    await expect(rejection).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByText(/rejection @ 95% — regex answered/i)).toBeVisible();

    // Clicking again collapses it.
    await rejection.click();
    await expect(rejection).toHaveAttribute("aria-expanded", "false");
  });

  test("layer 1 is recomputed LIVE and agrees with the stored verdict", async ({ page }) => {
    await page.goto("/demo/inbox");
    // First row (s01, applied via rules) is open by default.
    const live = page.getByTestId("live-rules").first();
    await expect(live).toBeVisible();
    await expect(live).toHaveAttribute("data-live-answered", "yes");
    await expect(live).toHaveAttribute("data-live-reproduces", "yes");
    await expect(live).toContainText(/layer 1 recomputed live in your browser/i);
    await expect(live).toContainText(/applied @ 95%/i);
  });

  test("the embedding layer answers the onsite-loop email", async ({ page }) => {
    await page.goto("/demo/inbox");
    const onsite = page.getByRole("button", { name: /Your onsite loop/i });
    await onsite.click();
    await expect(page.getByText(/interview @ 88% cosine/i)).toBeVisible();
    // Layer 1 passed here — the live recompute should say so, not "final verdict".
    const live = page.getByTestId("live-rules");
    await expect(live).toHaveAttribute("data-live-answered", "no");
    await expect(live).toContainText(/layer 1 passed to a deeper layer/i);
  });

  test("low-confidence mail is held below the 0.85 gate for review", async ({ page }) => {
    await page.goto("/demo/inbox");
    const vague = page.getByRole("button", { name: /Quick question about your background/i });
    // The row carries a visible "review" badge.
    await expect(vague.getByText("review", { exact: true })).toBeVisible();
    await vague.click();
    await expect(page.getByText(/below the 0.85 gate/i)).toBeVisible();
    await expect(page.getByText(/follow_up @ 19% softmax/i)).toBeVisible();
  });

  test("the live playground reclassifies on input (real effect)", async ({ page }) => {
    await page.goto("/demo/inbox");
    const subject = page.getByTestId("playground-subject");
    const body = page.getByTestId("playground-body");
    const verdict = page.getByTestId("playground-verdict");

    // A clear "applied" email.
    await subject.fill("We received your application");
    await body.fill("Thank you for applying to the role. Your application has been received.");
    await expect(verdict).toHaveText(/applied/i);

    // Text with no job signal falls to "other".
    await subject.fill("lunch plans");
    await body.fill("are we still on for tacos");
    await expect(verdict).toHaveText(/other/i);

    // A clear offer email.
    await subject.fill("We are pleased to extend an offer");
    await body.fill("Please sign the attached offer letter to accept.");
    await expect(verdict).toHaveText(/offer/i);
  });

  /**
   * THE PLAYGROUND'S TWO INPUTS ARE BOUNDED, and the bound is only real in a
   * browser: `maxLength` is enforced by the input element, so nothing outside
   * a rendered page can see whether it is there.
   *
   * `classifyWithRules` runs synchronously inside a `useMemo` keyed on both
   * fields, so it runs on every keystroke on the main thread. Measured, one
   * pass: 11 ms at 20 KB, 107 ms at 1,000 KB, 542 ms at 5,000 KB. It is linear
   * rather than a ReDoS, which is exactly what makes an unbounded input a
   * problem — paste a 5 MB body once and every character typed afterwards
   * costs half a second.
   *
   * The numbers are the ones the product already uses: the body bound is
   * MAX_BODY_CHARS from `lib/import/parseMail` (the most decoded text the
   * shipped pipeline ever scores for one message) and the subject bound is
   * `PipelineItemIn.subject`'s `max_length` (what the API already refuses
   * above).
   */
  const PLAYGROUND_SUBJECT_MAX = 2000;
  const PLAYGROUND_BODY_MAX = 8000;

  test("the playground refuses more text than the classifier is ever given", async ({ page }) => {
    await page.goto("/demo/inbox");
    const subject = page.getByTestId("playground-subject");
    const body = page.getByTestId("playground-body");

    await expect(subject).toHaveAttribute("maxlength", String(PLAYGROUND_SUBJECT_MAX));
    await expect(body).toHaveAttribute("maxlength", String(PLAYGROUND_BODY_MAX));

    // The attribute is a claim; this is the behaviour. `fill` sets the value
    // through the element, so the element's own limit applies exactly as it
    // does to a paste.
    await body.fill("x".repeat(PLAYGROUND_BODY_MAX * 2));
    expect((await body.inputValue()).length).toBe(PLAYGROUND_BODY_MAX);

    await subject.fill("y".repeat(PLAYGROUND_SUBJECT_MAX * 2));
    expect((await subject.inputValue()).length).toBe(PLAYGROUND_SUBJECT_MAX);
  });

  test("a bound this loose is invisible to anyone typing a real email", async ({ page }) => {
    /**
     * THE OTHER SIDE OF THE BOUND. A limit that refuses ordinary input is not
     * a fix, and this playground is the one place a visitor is invited to type
     * their own mail into. A long-but-real message goes in whole and still
     * scores.
     */
    await page.goto("/demo/inbox");
    const subject = page.getByTestId("playground-subject");
    const body = page.getByTestId("playground-body");
    const verdict = page.getByTestId("playground-verdict");

    const realistic =
      "Hi Nadia, thank you for applying to the Backend Engineer role. " +
      "We would like to schedule a 30 minute interview with the team next week. ".repeat(20);
    expect(realistic.length).toBeLessThan(PLAYGROUND_BODY_MAX);

    await subject.fill("Interview scheduling for the Backend Engineer role");
    await body.fill(realistic);

    expect((await body.inputValue()).length).toBe(realistic.length);
    await expect(verdict).toHaveText(/interview/i);
  });

  test("no console errors and no horizontal overflow at 375px", async ({ page }) => {
    const watch = startConsoleWatch(page);
    await page.setViewportSize(MOBILE_375);
    await page.goto("/demo/inbox");

    await expect(page.getByRole("heading", { name: "Sample inbox" })).toBeVisible();
    // Expand a row so the trace + meter are measured for overflow too.
    await page.getByRole("button", { name: /Interested in chatting about a Backend Engineer role/i }).click();
    await expectNoHorizontalOverflow(page);

    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });
});
