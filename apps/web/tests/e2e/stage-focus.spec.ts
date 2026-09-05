import { expect, test, type Page } from "@playwright/test";

/**
 * E2E for one defect and one repair: correcting a stage must not take the
 * reader's place on the page away from them (#425).
 *
 * WHAT WENT WRONG. The stage control locked itself with the DOM's `disabled`
 * while the write was in flight. The browser blurs a FOCUSED element that
 * becomes disabled, to `<body>`, and never gives the focus back: measured on
 * the live board at t=3ms after the change, on four different rows, at t=0,
 * 100, 500 and 1200ms. For a keyboard user the next Tab restarts at the top of
 * the document — and at the owner's 1024px, with the detail pane docked open,
 * the pane's own select is the documented keyboard route to a stage change, so
 * both controls are fixed and both are driven here.
 *
 * WHY THE FIRST CASE IS THE LOAD-BEARING ONE. The obvious explanation — the
 * row is reparented into another stage group, so of course the focused node
 * goes away — is WRONG, and a test that only exercised a stage-CHANGING
 * correction would pass against a fix that merely handled reparenting. So the
 * first case is a SAME-SECTION correction: `rejected → ghosted`, both in the
 * `closed` bucket (`lib/dashboard/summary.ts`), where the row never moves and
 * the `<select>` node stays in the document the whole time. It loses focus
 * identically on the defect. The stage-changing case follows as a second case
 * and asserts what is honestly assertable there: focus is never lost while the
 * control is still ON the page. What happens after React unmounts it is a
 * different question from this one.
 *
 * WHY A SAMPLED TRACE AND NOT `await expect(select).toBeFocused()`. That
 * matcher auto-retries, so it goes green against a blur-then-restore
 * implementation — which is precisely the repair this fix is not: restoring
 * focus races the unmount and flickers. The instrument below is armed BEFORE
 * the change and samples every 8ms in the page, and the assertion is over the
 * whole trace: focus never visited `<body>` at all.
 *
 * AND IT ASSERTS THE LOCK IS STILL A LOCK. A control that keeps focus by
 * becoming operable mid-write would be a worse bug than the one it replaces,
 * so every busy sample must carry `aria-busy="true"`, `aria-disabled="true"`,
 * a dimmed computed opacity, and a DOM `disabled` property that is false; and
 * a second stage picked mid-flight must not take. That last assertion is
 * positive-controlled at the end of the first case — the same dispatch, with
 * no write in flight, must change the value — because "the value did not
 * change" is otherwise exactly what a dead instrument reports.
 *
 * /demo is the surface: it mounts the REAL `ApplicationRow` and
 * `ApplicationDetail` over an in-memory store (only the transport is
 * simulated), and it is the one board CI can reach without a Supabase session.
 */

/** One reading of the control and of where focus is, stamped in the page. */
interface FocusSample {
  /** ms since the probe was armed. */
  t: number;
  /** `document.activeElement`'s id, or its tag name when it has none — so a
   *  blur to the document body reads as the literal "BODY". */
  active: string;
  ariaBusy: string | null;
  ariaDisabled: string | null;
  /** The DOM property, not the attribute: the thing that blurs the element. */
  disabledProp: boolean;
  /** Computed, not the class list — the class is only a claim about the CSS. */
  opacity: string;
  /**
   * The drawn chevron beside the control, which dims WITH it.
   *
   * Sampled because it is the half of this fix that can fail silently: the
   * glyph used to key off `peer-disabled`, which reads the DOM property the
   * control no longer sets, so it would simply stop dimming and nothing else
   * would notice. `peer-aria-disabled` is the replacement and this is the
   * measurement that it emits.
   */
  chevronOpacity: string | null;
  value: string;
  /** False once React has unmounted the control (a reparented row). */
  inDocument: boolean;
}

interface FocusTrace {
  samples: FocusSample[];
  /** Did the probe ever see the write in flight? A trace that did not proves
   *  nothing about the in-flight state, however green its assertions read. */
  sawBusy: boolean;
  /** ms at which `aria-busy` went back to false, or null if it never did. */
  settledAt: number | null;
  /**
   * ms at which React took the control off the page, or null if it stayed.
   *
   * A correction that MOVES a row ends here rather than at a settle, and the
   * probe has to know the difference or it waits out its cap for an attribute
   * that can no longer change: the demo store commits the new status before
   * the write resolves, so the row is re-grouped — and this node detached —
   * while its last rendered frame still said `aria-busy="true"`. Measured:
   * detach at 459-462ms across runs, i.e. the instant the write returns.
   */
  detachedAt: number | null;
}

declare global {
  interface Window {
    __focusProbe?: { done: Promise<FocusTrace> };
  }
}

/**
 * Arm the in-page sampler on `selectId` and return a handle that resolves
 * once the write has settled (plus a tail, to catch a late blur) or the cap
 * runs out. Nothing here waits on a hardcoded latency: the probe follows
 * `aria-busy`, and the test asserts it actually saw both edges.
 */
async function armFocusProbe(page: Page, selectId: string): Promise<void> {
  await page.evaluate((id) => {
    const sel = document.getElementById(id) as HTMLSelectElement | null;
    if (!sel) throw new Error(`focus probe: no control with id ${id} on the page`);
    // The control and its glyph are siblings inside the select's wrapper, in
    // both components.
    const chevron = sel.parentElement?.querySelector("svg") ?? null;
    if (!chevron) throw new Error(`focus probe: no chevron beside ${id}`);
    const samples: FocusSample[] = [];
    const t0 = performance.now();
    let sawBusy = false;
    let settledAt: number | null = null;
    let detachedAt: number | null = null;

    const read = () => {
      const now = Math.round(performance.now() - t0);
      const active = document.activeElement;
      const mounted = document.contains(sel);
      if (!mounted && detachedAt === null) detachedAt = now;
      // Only a MOUNTED control's attributes are still being written to: a
      // detached node freezes on its last frame, and reading a settle off it
      // would be reading the past.
      const busy = mounted && sel.getAttribute("aria-busy") === "true";
      if (busy) sawBusy = true;
      else if (mounted && sawBusy && settledAt === null) settledAt = now;
      samples.push({
        t: now,
        active: active ? active.id || active.tagName : "none",
        ariaBusy: sel.getAttribute("aria-busy"),
        ariaDisabled: sel.getAttribute("aria-disabled"),
        disabledProp: sel.disabled,
        opacity: getComputedStyle(sel).opacity,
        chevronOpacity: chevron ? getComputedStyle(chevron).opacity : null,
        value: sel.value,
        inDocument: document.contains(sel),
      });
      return now;
    };

    read();
    const done = new Promise<FocusTrace>((resolve) => {
      const timer = window.setInterval(() => {
        const now = read();
        // 500ms of tail past the settle: on the live board the unmount landed
        // ~1.4s after the change, well after `aria-busy` cleared, and a blur
        // that happens THERE has to be inside the trace too.
        const finished =
          (settledAt !== null && now - settledAt >= 500) ||
          (detachedAt !== null && now - detachedAt >= 300) ||
          now >= 3000;
        if (!finished) return;
        window.clearInterval(timer);
        resolve({ samples, sawBusy, settledAt, detachedAt });
      }, 8);
    });
    window.__focusProbe = { done };
  }, selectId);
}

/** Where focus is right now, addressed the same way the probe addresses it. */
function activeElementId(page: Page): Promise<string> {
  return page.evaluate(() => {
    const a = document.activeElement;
    return a ? a.id || a.tagName : "none";
  });
}

/**
 * Pick a stage the way the page itself would, from inside the page.
 *
 * This is how the MID-FLIGHT attempt has to be made: `locator.selectOption`
 * would be answered by Playwright's own actionability layer (which reads
 * `aria-disabled`), so the refusal under test would be the runner's and not
 * the product's. Reports what it found and what the control read immediately
 * afterwards — React restores a controlled `<select>` synchronously at the end
 * of the event it ignored, so a snap-back is visible without waiting.
 */
function dispatchStage(
  page: Page,
  selectId: string,
  next: string,
): Promise<{ wasBusy: boolean; before: string; immediatelyAfter: string }> {
  return page.evaluate(
    ({ id, value }) => {
      const sel = document.getElementById(id) as HTMLSelectElement | null;
      if (!sel) throw new Error(`dispatchStage: no control with id ${id} on the page`);
      const wasBusy = sel.getAttribute("aria-busy") === "true";
      const before = sel.value;
      sel.value = value;
      sel.dispatchEvent(new Event("change", { bubbles: true }));
      return { wasBusy, before, immediatelyAfter: sel.value };
    },
    { id: selectId, value: next },
  );
}

/** The trace is only evidence if it caught the window it claims to describe. */
function expectUsableTrace(trace: FocusTrace, control: string): void {
  expect(
    trace.samples.length,
    `${control}: the focus probe took no readings at all`,
  ).toBeGreaterThan(2);
  expect(
    trace.sawBusy,
    `${control}: the probe never saw aria-busy="true", so it sampled no part of the in-flight window and every in-flight assertion below is vacuous`,
  ).toBe(true);
  // The correction has to have ENDED inside the trace, one way or the other:
  // the control settled back to idle, or React took it off the page. Neither
  // means the probe timed out on its cap with the window still open, and a
  // trace that did is not evidence about what happened after it.
  expect(
    trace.settledAt !== null || trace.detachedAt !== null,
    `${control}: the correction neither settled nor unmounted inside the probe's window — the trace does not cover the whole correction (settledAt=${trace.settledAt}, detachedAt=${trace.detachedAt})`,
  ).toBe(true);
}

/** The defect, stated over the whole trace rather than at any one instant. */
function expectNeverBlurredWhileMounted(trace: FocusTrace, selectId: string): void {
  const strayed = trace.samples.filter((s) => s.inDocument && s.active !== selectId);
  expect(
    strayed.map((s) => `t=${s.t} activeElement=${s.active} aria-disabled=${s.ariaDisabled}`),
    `the stage select must keep focus through an in-flight correction: focus left #${selectId} while the control was still in the document`,
  ).toEqual([]);
}

/** The lock has to still read as a lock — to the eye and to assistive tech. */
function expectBusyIsCommunicated(trace: FocusTrace, control: string): void {
  // Mounted only: a detached node freezes with its last attributes and
  // `getComputedStyle` on it returns nothing, so including one would compare
  // an empty string to "0.5" and red for a reason that is not the product's.
  const busy = trace.samples.filter((s) => s.inDocument && s.ariaBusy === "true");
  const notDimmed = busy.filter((s) => s.opacity !== "0.5");
  expect(
    notDimmed.map((s) => `t=${s.t} opacity=${s.opacity}`),
    `${control}: the control must still be visibly dimmed while the write is in flight (if this reads opacity=1, the aria-disabled: Tailwind variant did not emit)`,
  ).toEqual([]);
  const glyphNotDimmed = busy.filter((s) => s.chevronOpacity !== "0.5");
  expect(
    glyphNotDimmed.map((s) => `t=${s.t} chevron opacity=${s.chevronOpacity}`),
    `${control}: the chevron dims with the control (if this reads 1, peer-aria-disabled did not emit and the glyph is keying off a DOM property the control no longer sets)`,
  ).toEqual([]);
  const notStated = busy.filter((s) => s.ariaDisabled !== "true");
  expect(
    notStated.map((s) => `t=${s.t} aria-disabled=${s.ariaDisabled}`),
    `${control}: the in-flight lock must be stated to assistive tech with aria-disabled`,
  ).toEqual([]);
  const natively = busy.filter((s) => s.disabledProp);
  expect(
    natively.map((s) => `t=${s.t} disabled=${s.disabledProp}`),
    `${control}: the in-flight lock must NOT be the DOM disabled property — the browser blurs a focused element that becomes disabled, which is defect #425`,
  ).toEqual([]);
  // Only for a control that is still there to clear it. A correction that
  // moves its row replaces the node instead — its last frame legitimately
  // still reads busy, and the case that does this asserts the row arrived in
  // its new group instead.
  const last = trace.samples[trace.samples.length - 1];
  if (last.inDocument) {
    expect(last.ariaBusy, `${control}: aria-busy must clear when the write returns`).toBe("false");
    expect(last.opacity, `${control}: the control is undimmed once the write returns`).toBe("1");
    expect(
      last.chevronOpacity,
      `${control}: the chevron is undimmed once the write returns`,
    ).toBe("1");
  }
}


test.describe("a correction keeps the reader's place", () => {
  test("a same-section correction never blurs the stage control it was made on", async ({
    page,
  }) => {
    await page.goto("/demo");
    // Fernworks is a single-application employer at `rejected`, so the label
    // is unique and the row is not inside an employer set. `rejected` and
    // `ghosted` are both in the `closed` bucket: the correction below moves
    // the row NOWHERE, which is the whole point of this case.
    await expect(page.getByRole("region", { name: /closed — 3/i })).toBeVisible();
    const select = page.getByLabel("Change stage for Fernworks");
    const selectId = (await select.getAttribute("id"))!;
    expect(selectId, "the stage control carries the id the probe addresses it by").toBeTruthy();
    await expect(select).toHaveValue("rejected");

    await select.focus();
    const before = await activeElementId(page);
    expect(before, "the reader is standing on the control before they correct it").toBe(selectId);

    await armFocusProbe(page, selectId);
    await select.selectOption("ghosted");
    // Mid-flight, inside the same 300ms window the probe is sampling: a second
    // stage must not take. Asserted after the focus assertions below, so a red
    // here can never be mistaken for the defect this file is named for.
    const midFlight = await dispatchStage(page, selectId, "offered");
    const trace = await page.evaluate(() => window.__focusProbe!.done);

    // --- The defect ------------------------------------------------------
    expectUsableTrace(trace, "the row's stage select");
    expectNeverBlurredWhileMounted(trace, selectId);
    const detached = trace.samples.filter((s) => !s.inDocument);
    expect(
      detached.map((s) => `t=${s.t}`),
      "a same-section correction must not unmount the control — if it did, this case stopped being the one the defect needs",
    ).toEqual([]);
    const after = await activeElementId(page);
    expect(
      after,
      "focus is still on the control the correction was made with, after the write returned",
    ).toBe(selectId);
    await expect(select).toBeFocused();

    // --- The lock is still a lock ----------------------------------------
    expectBusyIsCommunicated(trace, "the row's stage select");
    expect(
      midFlight.wasBusy,
      "the mid-flight attempt has to land INSIDE the write window or it tests nothing",
    ).toBe(true);
    expect(
      midFlight.immediatelyAfter,
      "a stage picked while the write is in flight is ignored and the controlled value snaps back",
    ).toBe("ghosted");
    await expect(select).toHaveValue("ghosted");
    // …and the row is where a refused `offered` leaves it: still closed.
    await expect(page.getByRole("region", { name: /closed — 3/i })).toBeVisible();
    await expect(
      page.getByRole("region", { name: /closed/i }).getByText("Fernworks", { exact: true }),
    ).toBeVisible();

    // --- The instrument can change a value when it is allowed to ---------
    // Without this, "the mid-flight change was refused" is equally well
    // explained by a dispatch React never receives. `withdrawn` is closed too,
    // so the control stays put and this proves the mechanism, not the fix.
    const allowed = await dispatchStage(page, selectId, "withdrawn");
    expect(
      allowed.wasBusy,
      "the control case has to run with NO write in flight to say anything",
    ).toBe(false);
    expect(
      allowed.immediatelyAfter,
      "the same dispatch, un-refused, does change the control — so the refusal above was the product's and not the instrument's",
    ).toBe("withdrawn");
    await expect(select).toHaveValue("withdrawn");
  });

  test("a stage-changing correction keeps focus for as long as the control is on the page", async ({
    page,
  }) => {
    await page.goto("/demo");
    await expect(page.getByRole("region", { name: /interviewing — 4/i })).toBeVisible();
    const select = page.getByLabel("Change stage for Quarry Data");
    const selectId = (await select.getAttribute("id"))!;
    await expect(select).toHaveValue("applied");

    await select.focus();
    expect(
      await activeElementId(page),
      "the reader is standing on the control before they correct it",
    ).toBe(selectId);

    await armFocusProbe(page, selectId);
    await select.selectOption("interviewing");
    const trace = await page.evaluate(() => window.__focusProbe!.done);

    expectUsableTrace(trace, "the row's stage select (stage-changing)");
    // The premise of this case, checked rather than assumed: a correction that
    // moves the row across stage groups DOES take the control off the page.
    // Without this the case could quietly become a second copy of the
    // same-section one and stop covering the arrangement it is here for.
    expect(
      trace.detachedAt,
      "a stage-CHANGING correction is supposed to reparent the row — if the control is never unmounted, this case is no longer testing what it says it is",
    ).not.toBeNull();
    // And the honest limit of what it can then assert. Measured on this run:
    // the node detaches at ~460ms (the instant the write returns and the board
    // regroups) and focus goes to BODY WITH it. That is a reparent, it is
    // downstream, and it is not what #425 was: the defect blurred the control
    // at ~3ms, with the node still on the page and the write still in flight.
    // That is the thing asserted here — and it is exactly the assertion a
    // reparent-only "fix" could not pass.
    expectNeverBlurredWhileMounted(trace, selectId);
    expectBusyIsCommunicated(trace, "the row's stage select (stage-changing)");
    await expect(page.getByRole("region", { name: /interviewing — 5/i })).toBeVisible();
  });

  test("the detail pane's stage control keeps focus through its own write", async ({ page }) => {
    // The 1024px keyboard route (#425): with the pane docked, this is the
    // control a keyboard user reaches. Same correction as the first case —
    // same section, so nothing here moves either.
    await page.goto("/demo");
    await page.getByRole("button", { name: "Open Fernworks — Systems Engineer" }).click();
    const pane = page.getByTestId("application-detail");
    await expect(pane).toBeVisible();

    const select = page.locator("select[id^='detail-status-']");
    await expect(select).toHaveValue("rejected");
    const selectId = (await select.getAttribute("id"))!;

    await select.focus();
    expect(
      await activeElementId(page),
      "the reader is standing on the pane's control before they correct it",
    ).toBe(selectId);

    await armFocusProbe(page, selectId);
    await select.selectOption("ghosted");
    const midFlight = await dispatchStage(page, selectId, "offered");
    const trace = await page.evaluate(() => window.__focusProbe!.done);

    expectUsableTrace(trace, "the detail pane's stage select");
    expectNeverBlurredWhileMounted(trace, selectId);
    expect(
      await activeElementId(page),
      "focus is still on the pane's control after the write returned",
    ).toBe(selectId);
    expectBusyIsCommunicated(trace, "the detail pane's stage select");
    expect(
      midFlight.wasBusy,
      "the mid-flight attempt has to land INSIDE the write window or it tests nothing",
    ).toBe(true);
    expect(
      midFlight.immediatelyAfter,
      "a stage picked while the pane's write is in flight is ignored and the controlled value snaps back",
    ).toBe("ghosted");
    await expect(select).toHaveValue("ghosted");
  });
});
