import { expect, test, type Page } from "@playwright/test";

/**
 * What the board does to the reader when a row leaves it, and when it comes
 * back (#903's mechanical half, and #904).
 *
 * Both defects were measured on /demo at 1024 with an in-page sampler, because
 * that is the only board CI can reach without a Supabase session and it mounts
 * the real components over fixtures:
 *
 *  - focus was on `<body>` from the instant the undo slot unmounted (t=6.02s
 *    after the dismissal) to the end of the trace. The reader had been standing
 *    on `Undo`, deciding about a destructive action;
 *  - `Harbor Analytics` (filed Aug 27) sat THIRD in `applied`, and after
 *    dismiss-then-Undo it sat last, below a row filed Sep 7.
 *
 * WHAT THE ASSERTIONS HAVE TO BE, given that. "Focus is somewhere" and "the row
 * is back" are both true of the broken build — the first defect ends with focus
 * on a real element (`<body>` is one) and the second ends with the row on the
 * board. So the assertions name the exact successor the rule chooses, and
 * compare the column's WHOLE order; and the removal case picks a row that is
 * demonstrably not last, with that fact asserted first, because on a row that
 * genuinely was last both builds agree.
 *
 * The clock is real here and cannot be stalled, so the countdown's own
 * behaviour under a starved thread is not this file's — that is
 * `tests/unit/undo-window-is-a-deadline.test.mjs`. What this file does prove
 * about #902 is the plain case: a window that opens at 6 and closes once.
 */

/** The owner's width. Every measurement quoted above was taken here. */
const OWNER_VIEWPORT = { width: 1024, height: 768 };

/** The row this file removes: third of eight in `applied`, so not last. */
const TARGET = "Harbor Analytics";
/** The row directly below it, which the list closes up onto. */
const SUCCESSOR = "Quarry Data";

/** The `applied` column's rows, in the order the board draws them. */
async function appliedColumn(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const column = document.querySelector('section[aria-label^="applied —"] ul');
    if (column === null) throw new Error("row-removal: no applied column on the page");
    return [...column.children].map((row) =>
      (row.textContent ?? "").replace(/\s+/g, " ").slice(0, 40),
    );
  });
}

/** `document.activeElement`, named the way a reader would name it: its
 *  `aria-label`, else its own text, else the bare tag — so a blur to the
 *  document body reads as the literal "BODY". */
async function activeElement(page: Page): Promise<string> {
  return page.evaluate(() => {
    const el = document.activeElement;
    if (el === null || el === document.body) return "BODY";
    const label = el.getAttribute("aria-label");
    if (label !== null) return label;
    const text = (el.textContent ?? "").replace(/\s+/g, " ").trim();
    return text === "" ? el.tagName : text;
  });
}

/**
 * Record every change of `document.activeElement` in the page, on animation
 * frames, until it is read back.
 *
 * A sampler rather than a pair of reads, for the reason `stage-focus.spec.ts`
 * runs one: what goes wrong here is a SEQUENCE — focused, dropped, and either
 * recovered or not — and a test that only looks at the end cannot say which of
 * those steps it is describing. It costs one rAF loop and it puts the whole
 * story in the failure message.
 */
async function armFocusTrace(page: Page): Promise<void> {
  await page.evaluate(() => {
    const w = window as unknown as { __focusTrace?: string[] };
    const name = (el: Element | null): string => {
      if (el === null || el === document.body) return "BODY";
      const label = el.getAttribute("aria-label");
      if (label !== null) return label;
      const text = (el.textContent ?? "").replace(/\s+/g, " ").trim();
      return text === "" ? el.tagName : text;
    };
    // Two different buttons on this page are both called "Undo" — the row's
    // and the toast's — so the trace has to follow ELEMENTS, not names, or a
    // hand-off between them reads as nothing happening at all.
    const seen = new WeakMap<Element, number>();
    let serial = 0;
    const stamp = (el: Element | null): string => {
      if (el === null || el === document.body) return "BODY";
      if (!seen.has(el)) seen.set(el, (serial += 1));
      const where = el.closest("[data-sonner-toast]") === null ? "" : " (in the toast)";
      return `${name(el)}${where} #${seen.get(el)}`;
    };
    const trace: string[] = [stamp(document.activeElement)];
    w.__focusTrace = trace;
    const loop = () => {
      const here = stamp(document.activeElement);
      if (here !== trace[trace.length - 1]) trace.push(here);
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  });
}

const focusTrace = (page: Page): Promise<string[]> =>
  page.evaluate(() => (window as unknown as { __focusTrace: string[] }).__focusTrace);

/** Open a row's `···` menu and choose "Not an application". */
async function dismiss(page: Page, company: string): Promise<void> {
  const trigger = page.locator(`button[aria-label^="Row actions for ${company}"]`);
  await trigger.click();
  await page.getByRole("menuitem", { name: /Not an application/ }).click();
}

/**
 * Wait out the undo window and the commit behind it.
 *
 * THE WAIT HAS TO BE ON THE COUNTDOWN GOING, and this is the trap: the inline
 * tombstone reads "<company> removed from the board · undo within Ns", so
 * `getByText("<company> removed from the board")` matches it INSTANTLY — the
 * text is a substring of the pending sentence. A test that waited on that
 * would do everything below inside the cancellable window, click the row's own
 * Undo instead of the toast's, and pass while exercising the cancel path. That
 * happened here, so the wait is the disappearance of the countdown, and the
 * acknowledgement is then found inside the toast and nowhere else.
 */
async function waitForCommit(page: Page, company: string) {
  await expect(page.getByText(/undo within \d+s/)).toHaveCount(0, { timeout: 15_000 });
  const toast = page.locator("[data-sonner-toast]");
  await expect(toast.getByText(`${company} removed from the board`)).toBeVisible();
  await expect(page.locator(`button[aria-label^="Row actions for ${company}"]`)).toHaveCount(0);
  return toast;
}

test.describe("a row leaving the board", () => {
  test.use({ viewport: OWNER_VIEWPORT });

  test("the reader is not dropped at <body> when the undo window closes", async ({ page }) => {
    await page.goto("/demo");
    await expect(page.locator('section[aria-label^="applied —"]')).toBeVisible();
    await armFocusTrace(page);

    await dismiss(page, TARGET);

    // The inline slot's own keyboard story, which is the part that already
    // worked and the part the successor has to be as good as.
    const inlineUndo = page.locator("[data-row-id]").getByRole("button", { name: "Undo" });
    await expect(inlineUndo).toBeFocused();
    await expect(page.getByRole("status").filter({ hasText: /undo within \d+s/ })).toBeVisible();
    expect(
      await activeElement(page),
      "the reader has to be standing on Undo, or the blur this test is about cannot happen",
    ).toBe("Undo");

    // Out of the window and past the commit: the row is gone from the board
    // and the acknowledgement that outlives it is up.
    await waitForCommit(page, TARGET);

    // THE DEFECT. Named exactly, not "not BODY": a rule that dropped the
    // reader at the top of the board would satisfy "somewhere" and would be
    // the same defect wearing a different label.
    await expect
      .poll(async () => (await focusTrace(page)).join(" → "), { timeout: 5_000 })
      .toContain(`Row actions for ${SUCCESSOR}`);
    const trace = await focusTrace(page);
    expect(
      trace.some((where) => where.startsWith("Undo")),
      `the reader was never on the row's Undo, so this trace is not the case ` +
        `#903 is about: ${trace.join(" → ")}`,
    ).toBe(true);
    // The `<body>` step is expected to still be in this trace and is NOT
    // asserted: it is one commit wide (measured at 359ms on /demo — the gap
    // between the slot unmounting and the row leaving `applications`), it is
    // named on the effect in `PipelineBoard`, and closing it belongs to
    // #903's other half. Asserting it here would make that repair red.
    expect(
      trace[trace.length - 1].replace(/ #\d+$/, ""),
      `focus did not settle on the row that took ${TARGET}'s place: ${trace.join(" → ")}`,
    ).toBe(`Row actions for ${SUCCESSOR} — Data Engineer`);
    expect(
      await activeElement(page),
      "the successor holds focus once everything has settled",
    ).toBe(`Row actions for ${SUCCESSOR} — Data Engineer`);
  });

  test("undo puts the row back where it was, not at the bottom of its column", async ({
    page,
  }) => {
    await page.goto("/demo");
    await expect(page.locator('section[aria-label^="applied —"]')).toBeVisible();

    const before = await appliedColumn(page);
    const at = before.findIndex((row) => row.startsWith(TARGET));
    expect(at, `${TARGET} is not in the applied column any more`).toBeGreaterThanOrEqual(0);
    // THE GUARD THAT MAKES THE ASSERTION MEAN SOMETHING. On a row that really
    // was last, appending and reinserting agree, and this test would pass on
    // the build it exists to catch.
    expect(at, `${TARGET} is last in its column, so this case proves nothing`).toBeLessThan(
      before.length - 1,
    );

    await dismiss(page, TARGET);
    const toast = await waitForCommit(page, TARGET);

    // The toast's Undo — a different affordance from the inline one: this
    // reverses a dismissal the server saw, the other cancels one it never did.
    // Scoped to the toast for exactly that reason.
    await toast.getByRole("button", { name: "Undo" }).click();
    await expect(page.locator(`button[aria-label^="Row actions for ${TARGET}"]`)).toHaveCount(1);

    expect(
      await appliedColumn(page),
      "the row came back, but the column did not come back with it",
    ).toEqual(before);
  });
});
