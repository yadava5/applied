import { expect, test, type Page } from "@playwright/test";

/**
 * What the board does to the reader when a row leaves it, and when it comes
 * back (#903, and what is left of #904 — see below).
 *
 * #903's second half landed here too, and it deleted a surface rather than
 * repairing one: the corner toast that used to carry a second Undo after the
 * commit measured at focusable index 0 of 69 while painted bottom-right at
 * 1024 — 32 Shift+Tabs behind the row the board had just handed focus to — and
 * its card covered the stage select and the menu trigger of the row beneath it
 * for 8.2 s. The acknowledgement now lives in the removed row's own cell for
 * the whole of `UNDO_WINDOW_SECONDS` and the corner is left empty, so "the
 * Undo is adjacent to the control that spawned it" is a fact about the DOM
 * rather than a tab-order claim laid over a fixed overlay.
 *
 * Every defect here was measured on /demo at 1024 with an in-page sampler,
 * because that is the only board CI can reach without a Supabase session and
 * it mounts the real components over fixtures. Focus was on `<body>` from the
 * instant the undo slot unmounted (t=6.02s after the dismissal) to the end of
 * the trace, with the reader standing on `Undo`, deciding about a destructive
 * action.
 *
 * #904 USED TO HAVE A CASE IN THIS FILE AND NO LONGER DOES. It drove the
 * toast's Undo — a RESTORE of a dismissal the server had made — and compared
 * the whole column, because `Harbor Analytics` sat third in `applied` and came
 * back last. #903 deleted that affordance, so the case went with it rather
 * than being pointed at the in-cell Undo, which cancels and cannot reorder
 * anything. The order a restore puts a row back in is pinned by
 * `tests/unit/undo-restores-in-place.test.mjs`, and `POST /restore` keeps its
 * browser coverage in `demo.spec.ts`'s scan-receipt case.
 *
 * WHAT THE ASSERTIONS HAVE TO BE, given that. "Focus is somewhere" is true of
 * the broken build too — `<body>` is a real element — so the assertions name
 * the exact successor the rule chooses rather than refuting a value.
 *
 * The clock is real here and cannot be stalled, so the countdown's own
 * behaviour under a starved thread is not this file's — that is
 * `tests/unit/undo-window-is-a-deadline.test.mjs`. What this file does prove
 * about #902 is the plain case: a window that opens at `UNDO_WINDOW_SECONDS`
 * and closes once.
 */

/** The owner's width. Every measurement quoted above was taken here. */
const OWNER_VIEWPORT = { width: 1024, height: 768 };

/** The row this file removes: third of eight in `applied`, so not last — the
 *  successor rule has somewhere to go in both directions from it. */
const TARGET = "Harbor Analytics";
/** The row directly below it, which the list closes up onto. */
const SUCCESSOR = "Quarry Data";

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
    // The trace follows ELEMENTS, not names: two buttons on this page used to
    // be called "Undo" (the row's and the toast's) and a hand-off between them
    // read as nothing happening at all. The toast's is gone with #903 and the
    // identity stamping stays, because that is what makes a future second
    // "Undo" visible instead of invisible.
    const seen = new WeakMap<Element, number>();
    let serial = 0;
    const stamp = (el: Element | null): string => {
      if (el === null || el === document.body) return "BODY";
      if (!seen.has(el)) seen.set(el, (serial += 1));
      const where = el.closest("[data-sonner-toast]") === null ? "" : " (in the toast)";
      return `${name(el)}${where} #${seen.get(el)}`;
    };
    // The toast half of that stamp is kept deliberately though nothing should
    // ever land in one on this path any more: if a corner card starts taking
    // focus again, the trace has to say so by name rather than showing a
    // second anonymous "Undo".
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
 * would do everything below inside the cancellable window and pass while
 * exercising the cancel path. That happened here, so the wait is the
 * disappearance of the countdown, and what follows it is the row leaving.
 *
 * The timeout has to clear `UNDO_WINDOW_SECONDS` plus the dismiss round trip
 * with room to spare; it is not the window's length and must never be read as
 * one.
 */
async function waitForCommit(page: Page, company: string) {
  await expect(page.getByText(/undo within \d+s/)).toHaveCount(0, { timeout: 20_000 });
  await expect(page.locator(`button[aria-label^="Row actions for ${company}"]`)).toHaveCount(0);
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

    // Out of the window and past the commit: the row is gone from the board.
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
    // asserted: it is one commit wide (measured at 362-365ms on /demo, before
    // and after #903 — the gap between the slot unmounting and the row leaving
    // `applications`, which is the dismiss round trip) and it is named on the
    // effect in `PipelineBoard`. #903 did not close it and says so: the
    // obvious destination in that gap is the row's own `···`, and #777
    // deliberately disables that trigger while `busy`, so a disabled button
    // cannot hold the focus being handed to it. Asserting it here would make
    // that repair red when it comes.
    expect(
      trace[trace.length - 1].replace(/ #\d+$/, ""),
      `focus did not settle on the row that took ${TARGET}'s place: ${trace.join(" → ")}`,
    ).toBe(`Row actions for ${SUCCESSOR} — Data Engineer`);
    expect(
      await activeElement(page),
      "the successor holds focus once everything has settled",
    ).toBe(`Row actions for ${SUCCESSOR} — Data Engineer`);
  });

  test("the way back is in the row's own cell, and the corner says nothing", async ({ page }) => {
    await page.goto("/demo");
    await expect(page.locator('section[aria-label^="applied —"]')).toBeVisible();

    // Where the reader is standing when they open the menu, in TAB ORDER —
    // the only frame in which "the acknowledgement is reachable" means
    // anything. The build this replaces put the Undo the reader had to press
    // 32 stops behind this number, at index 0 of 69, while painting it
    // bottom-right.
    const focusables = (company: string) =>
      page.evaluate((company) => {
        const list = [
          ...document.querySelectorAll<HTMLElement>(
            'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),' +
              'textarea:not([disabled]),[tabindex]:not([tabindex="-1"])',
          ),
        ].filter((el) => {
          const box = el.getBoundingClientRect();
          return box.width > 0 || box.height > 0;
        });
        const index = (el: Element | null) => (el === null ? -1 : list.indexOf(el as HTMLElement));
        const cell = (el: Element | null) =>
          el?.closest("[data-row-id]")?.getAttribute("data-row-id") ?? null;
        const undo = list.find((el) => (el.textContent ?? "").trim() === "Undo") ?? null;
        const trigger = document.querySelector(`button[aria-label^="Row actions for ${company}"]`);
        return {
          total: list.length,
          undo: index(undo),
          undoCell: cell(undo),
          toast: index(document.querySelector("[data-sonner-toast]")),
          trigger: index(trigger),
          triggerCell: cell(trigger),
        };
      }, company);

    const { trigger: triggerIndex, triggerCell } = await focusables(TARGET);
    expect(triggerIndex).toBeGreaterThan(0);
    expect(triggerCell).not.toBeNull();

    await dismiss(page, TARGET);

    // ADJACENT, TWO WAYS. The structural fact first: the Undo is inside the
    // SAME cell the trigger was in, which is what makes it adjacent rather
    // than a claim laid over a fixed overlay — a `tabindex` cannot buy this
    // and the toast never had it.
    const open = await focusables(TARGET);
    expect(open.undo, "the Undo is not in the tab order at all").toBeGreaterThanOrEqual(0);
    expect(open.undoCell, "the Undo is not in the cell the removal came from").toBe(triggerCell);
    // Then what the reader pays in keystrokes. The bound is the number of
    // focusable controls one row cell can hold — open, Gmail link, stage
    // select, `···` — because the tombstone replaces all of them with one
    // button, so nothing inside a cell can be further than that from anything
    // else in it. Measured at 2 on /demo at 1024, against 29 for the toast
    // this replaced (its Undo at index 1, the trigger at 30).
    expect(
      Math.abs(open.undo - triggerIndex),
      `the Undo is ${Math.abs(open.undo - triggerIndex)} stops from the control that ` +
        `opened the menu (index ${open.undo} of ${open.total}, trigger was ${triggerIndex})`,
    ).toBeLessThanOrEqual(4);
    expect(open.toast, "a toast is up while the row's own window is still open").toBe(-1);

    // AND THE CORNER STAYS EMPTY THROUGH THE COMMIT — the assertion that is
    // red on the build before this one, where a card appeared here and stayed
    // for 8.2 s over the stage select of the row beneath.
    await waitForCommit(page, TARGET);
    await expect(page.locator("[data-sonner-toast]")).toHaveCount(0);
    // Given a second to be raised late, and still nothing.
    await page.waitForTimeout(1_000);
    await expect(page.locator("[data-sonner-toast]")).toHaveCount(0);
  });

  test("cancelling hands the reader back the control they opened", async ({ page }) => {
    // THIS IS NOT #904'S TEST WEARING NEW CLOTHES, and it must not be read as
    // one. The case that used to sit here drove the toast's Undo — a RESTORE
    // of a dismissal the server had made — and asserted the whole column came
    // back in order. That affordance is gone with #903, and with it this
    // file's coverage of `POST /restore`. Not relocated: REMOVED. What still
    // holds the ground it covered is `undo-restores-in-place.test.mjs` for the
    // order a restore puts a row back in, and `demo.spec.ts`'s "restoring a
    // row first does not trap the scan in a loop" for the endpoint.
    //
    // Asserting the column here instead would be a check that cannot fail: the
    // in-cell Undo CANCELS, the `<li>` never unmounts, and the row's place is
    // therefore preserved by construction rather than by any rule. So this
    // asserts the thing cancelling actually decides — where the reader is left
    // — which the old test never covered.
    await page.goto("/demo");
    await expect(page.locator('section[aria-label^="applied —"]')).toBeVisible();

    await dismiss(page, TARGET);
    const undo = page.locator("[data-row-id]").getByRole("button", { name: "Undo" });
    await expect(undo).toBeFocused();
    await undo.click();

    // The row's own controls are back — the trigger is the one that matters,
    // because it is where focus is going.
    await expect(page.locator(`button[aria-label^="Row actions for ${TARGET}"]`)).toHaveCount(1);
    // Named, not "not BODY": the trigger unmounts the instant Undo is pressed,
    // so the return has to wait a render, and "focus is somewhere" is true of
    // the build where it never comes back.
    expect(
      await activeElement(page),
      "cancelling left the reader somewhere other than the row they cancelled from",
    ).toMatch(new RegExp(`^Row actions for ${TARGET}`));
    await expect(page.locator("[data-sonner-toast]")).toHaveCount(0);
  });
});
