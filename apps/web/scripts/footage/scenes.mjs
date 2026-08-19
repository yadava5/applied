/**
 * The scenes — the two moments on the PUBLIC /demo family that survived the
 * measurement pass. Never the signed-in app: that account holds the owner's
 * real employers and real rejections, and this footage goes on a marketing
 * page. `/demo` runs the same shipped components over fixture data, which is
 * what the landing should show anyway.
 *
 * WHAT WAS REJECTED, AND WHY — kept here because the next person will have the
 * same four ideas, and re-deriving these takes a production build and an hour:
 *
 *   · the detail pane docking open on "the mail behind this card". Measured
 *     `transition: all 0s; animation: none 0s` (scripts/footage/geom.mjs). It
 *     is a hard mount plus a 250ms transport delay on the mail trail — two
 *     states, which is a diagram, not a clip. The only framing with real motion
 *     is the one where the whole board re-lays out around it, and that crop is
 *     ~1400 CSS px: illegible at the 26rem the card gives it.
 *   · a row travelling between stages via its select. It animates (PipelineBoard
 *     wraps every row in a `motion.li` with a shared `layoutId`), but a USER
 *     picking a new stage is the exact opposite of "never update a job tracker
 *     again". Filming it to sell that sentence would be dishonest.
 *   · the sample inbox's three-layer trace expanding. Source-verified hard cut:
 *     `{open && <ExpandedTrace/>}`, and the confidence meter's width is an
 *     inline style with no transition. The 79-frame capture that looked
 *     promising was the DEFAULT-OPEN first row closing.
 *   · correcting a wrong verdict on /demo/scan. Honest and legible, but the row
 *     is 822 CSS px and its payload (the row's chip, and the filter chips
 *     recounting 220px above it) does not fit one crop — and "the classifier
 *     gets it wrong" is not one of the three claims the column argues.
 *
 * And the one that cannot exist: PRIVACY.headline, "Read in flight. Never
 * kept." Absence is not filmable. Any clip of it would be a caption with a
 * screenshot behind it, which is the thing the brief rules out.
 */

/** Crop width ceiling, in CSS px — the DEFAULT; a scene may raise its own.
 *
 *  The artifact column was `minmax(0,26rem)` — 416 px. A crop wider than that
 *  gets downscaled past the point where 11–14px product type survives: the
 *  first pass cropped the board at 1180 CSS px, which is 2.8x down, and every
 *  label in it turned to grey mush. At 580 the downscale is 1.4x, and captured
 *  at 2x that still leaves 1.43 device px per display px.
 *
 *  The ceiling is a function of WHERE A CLIP IS SHOWN, which is why it is a
 *  default now rather than a law: the placements this footage actually has are
 *  wider than the column it was sized for (768 CSS px in `ClaimsDescent`), and
 *  a scene placed there can carry a wider crop without losing a pixel of
 *  legibility — at 720 into 768 the product type renders very near its
 *  authored size. A scene that raises it has to say what display width it is
 *  raising it FOR. Enforced in `capture.mjs`, not remembered. */
export const MAX_CROP_W = 580;

/** Padding around a derived crop, in CSS px. */
const PAD = 12;

/** Union of several element boxes, padded, clamped to the viewport. Crops are
 *  DERIVED from real elements rather than typed in as numbers, so a layout
 *  change moves the frame with it instead of silently filming the wrong thing.
 *  Only the trims are literal, and each one says what it is dropping. */
export async function boxOf(page, locators, { pad = PAD, trim = {} } = {}) {
  const boxes = [];
  for (const l of locators) {
    const b = await l.boundingBox();
    if (b) boxes.push(b);
  }
  if (!boxes.length) throw new Error("crop anchor matched nothing");
  const vp = page.viewportSize();
  const x0 = Math.min(...boxes.map((b) => b.x)) - pad + (trim.left ?? 0);
  const y0 = Math.min(...boxes.map((b) => b.y)) - pad + (trim.top ?? 0);
  const x1 = Math.max(...boxes.map((b) => b.x + b.width)) + pad - (trim.right ?? 0);
  const y1 = Math.max(...boxes.map((b) => b.y + b.height)) + pad - (trim.bottom ?? 0);
  const x = Math.max(0, Math.round(x0));
  const y = Math.max(0, Math.round(y0));
  return {
    x,
    y,
    width: Math.min(vp.width - x, Math.round(x1 - x0)),
    height: Math.min(vp.height - y, Math.round(y1 - y0)),
  };
}

/**
 * Set a controlled input's value the way a keystroke does, without Playwright's
 * actionability pass. `locator.fill()` scrolls its target into view before
 * every call, and the playground's card grows by a row the moment the score
 * chips appear — so filling it 60 times walked the page under a fixed crop and
 * the take drifted. Going through React's own value setter and dispatching one
 * `input` event produces the same recompute the component sees from a real
 * keypress, and moves nothing.
 */
async function typeInto(page, testId, value) {
  await page.evaluate(
    ({ testId, value }) => {
      const el = document.querySelector(`[data-testid="${testId}"]`);
      const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement : HTMLInputElement;
      Object.getOwnPropertyDescriptor(proto.prototype, "value").set.call(el, value);
      el.dispatchEvent(new Event("input", { bubbles: true }));
    },
    { testId, value },
  );
}

export const SCENES = [
  {
    id: "board-syncs",
    title: "The board files new mail by itself",
    /** Applied's own promise, and the consequence half of the descent's first
     *  claim: a verdict arrived and the board moved. Nothing is dragged and no
     *  stage is picked — the only input is one press of Sync. */
    url: "/demo",
    /**
     * 1040, not 1440. The strip's live sync status is CENTRED in the content
     * column, so the wider the viewport the further it drifts from the counters
     * on the left — at 1440 no crop under the legibility ceiling holds both
     * "19 filed · 16 open" and "2 filed, 3 already known", and the sentence that
     * says what just happened is the half a stranger needs. At 1040 the whole
     * strip is 812px and one 576px crop carries the counters, the status and
     * three full pulse cells.
     *
     * What this costs, stated plainly: the momentum sparkline is `xl:flex`
     * (PipelinePulse.tsx) and does not render below 1280, so its bars are not
     * in the clip. Its caption — "6 this wk · up from 5" → "8 this wk" — is,
     * and the bars are 96x16 CSS px, which is illegible at a 26rem card anyway.
     * 1040 is also a width the product genuinely serves and is used at.
     */
    viewport: { width: 1040, height: 900 },
    /** The board's top-left corner: the counters, the sync line, the momentum
     *  and open-age cells, and the head of the APPLIED group. Everything in it
     *  changes when the sync lands, and the crop deliberately STOPS above the
     *  rows: the two fixture rows that file are seeded "Twitch" and "DoorDash"
     *  (lib/demo/demoData.ts) — real brand names, fine on a page labelled
     *  DEMO · FIXTURE DATA, not fine in unlabelled marketing footage.
     *  `assertNoBrandRows` in capture.mjs holds that line on every frame. */
    async crop(page) {
      const box = await boxOf(page, [
        page.locator("[data-sync-surface]"),
        // The pulse is a 4-column grid; the crop ends on the third column's
        // boundary rather than slicing the fourth in half. Derived from the
        // grid's own geometry so it survives the columns changing width.
        page.getByTestId("pipeline-pulse").locator("> *").nth(2),
      ]);
      // The bottom edge is the top of the first CARD, derived rather than typed:
      // everything above it is counters and group headers, everything below it
      // is rows. That is the line that keeps the branded fixture rows out of
      // frame, and deriving it means a layout change moves the line too.
      const firstRow = await page
        .getByRole("region", { name: /applied —/i })
        .locator("li")
        .first()
        .boundingBox();
      const bottom = firstRow ? Math.round(firstRow.y - 6) : box.y + box.height;
      return { ...box, height: Math.max(80, bottom - box.y) };
    },
    /** Text that must never appear inside the crop on any frame. The two
     *  fixture rows an additive sync files are seeded with real company names,
     *  and this footage carries no DEMO · FIXTURE DATA pill with it. */
    forbid: ["Twitch", "DoorDash"],
    async run(page) {
      await page.getByRole("button", { name: "Sync new mail from Gmail" }).click();
      await page.waitForTimeout(7000);
    },
  },

  {
    id: "rules-read-the-body",
    title: "The rules layer reads past the preview",
    /**
     * The descent's first claim, demonstrated rather than asserted: a rejection
     * spends its opening being polite, and the verdict only arrives once the
     * body does. This is the SHIPPED layer-1 classifier (`lib/demo/rulesLayer.ts`,
     * the same module the landing's own `VerdictEmail` calls) recomputing in the
     * tab on every keystroke — no network, no model download, nothing precomputed.
     *
     * The arc is real and was measured, not staged (`scripts/footage/geom2.mjs`):
     * the verdict holds at OTHER for the first 174 characters and flips to
     * REJECTION at 175, on "…consideration we have decided…", landing at 90% —
     * over the 0.90 bar at which layer 1 answers on its own. Gmail's preview is
     * about 200 characters. The flip lands inside that window, which is the
     * whole point of the claim beside it.
     *
     * Captured at a 620px viewport: `/demo/inbox` is `max-w-3xl px-6`, so a
     * desktop capture makes the playground card 720 CSS px — 1.7x down in a
     * 26rem slot. At 620 the SAME component lays out at ~572, inside the crop
     * ceiling. This is the shipped responsive layout at a width the product
     * genuinely serves, not a style written for the camera.
     */
    url: "/demo/inbox",
    viewport: { width: 600, height: 900 },
    subject: "Update on your application",
    body:
      "Thank you so much for taking the time to speak with our team about the Backend Engineer role. " +
      "We were impressed by your background. After careful consideration we have decided to move " +
      "forward with other candidates.",
    async prepare(page) {
      await page.getByTestId("playground-subject").fill(this.subject);
      await typeInto(page, "playground-body", "");
      // Move focus off the subject and onto the field being typed into. Left
      // on the subject, its `focus:border-line-strong` painted a bright rule
      // across the top of every frame, drawing the eye to the one control
      // nothing happens in.
      await page.getByTestId("playground-body").focus();
      // Park the card so the crop is a stationary window: the page must not
      // move under the frame once recording starts. `scrollIntoView` on the
      // card, then a settle — and from here on nothing calls a Playwright
      // action on the textarea, which is what was scrolling the page mid-take
      // (`locator.fill` scrolls its target into view before every call, and
      // the card grows by a row when the score chips appear).
      await page.getByTestId("playground-verdict").evaluate((el) =>
        el.closest("div.rounded-xl")?.scrollIntoView({ block: "center" }),
      );
      await page.waitForTimeout(500);
    },
    async crop(page) {
      // Body field down to the verdict row. It deliberately stops ABOVE the
      // score chips: those appear only once something scores, so including them
      // would make the card's bottom edge move during the take and the frame
      // would breathe. The verdict row itself never moves.
      return boxOf(page, [
        page.getByTestId("playground-subject").locator("xpath=.."),
        page.getByTestId("playground-verdict").locator("xpath=.."),
      ]);
    },
    async run(page) {
      const text = this.body;
      // Typed in small irregular bursts rather than at a fixed metronome: a
      // constant delay reads as a machine filling a form. The burst sizes are a
      // fixed cycle, not random, so a re-render produces the same take.
      const BURSTS = [3, 5, 2, 7, 4, 3, 6, 2, 5, 4];
      let i = 0, b = 0;
      while (i < text.length) {
        i = Math.min(text.length, i + BURSTS[b++ % BURSTS.length]);
        await typeInto(page, "playground-body", text.slice(0, i));
        await page.waitForTimeout(26);
      }
      // Hold on the landed verdict — the frame the clip ends on, and the state
      // it loops back out of.
      await page.waitForTimeout(2000);
    },
  },

  {
    id: "import-classifies",
    title: "A mail export, classified in the tab",
    /**
     * The page's second CTA, which had no evidence anywhere on it. `ACCESS`
     * says "drop it in: it is parsed and classified in your browser. Nothing
     * uploads", and `DECISION` says the neural layers "run where they cost you
     * nothing — in your own browser, on the demo and the import page". Both
     * sentences describe something a visitor can watch happen, and neither had
     * ever been shown.
     *
     * WHY A HARD CUT IS THE HONEST SHAPE HERE, and why that does not make it
     * the rejected "trace expanding" clip above. `ingest()` is synchronous —
     * `parseMailFile` then `classify`, both pure, both in the tab — so the
     * counters land in ONE paint. That is not a limitation being papered over;
     * it is the claim. There is no request, no spinner and no round trip
     * because nothing leaves the device, and a clip that showed a progress bar
     * here would be inventing latency to look busy. The rejected trace clip had
     * nothing to read in either of its two states; this frame carries the
     * on-device promise the whole time and the arithmetic arrives beneath it.
     *
     * The results LIST is deliberately out of frame — see `forbid`.
     */
    url: "/import",
    /**
     * 780, not 600 and not 1440. `/import` signed out is `max-w-3xl px-6`, so
     * the column is 720 CSS px at any viewport at or above 768 — and 720 is
     * what the stats row needs to lay out as one row of four cells rather than
     * two rows of two (`sm:grid-cols-4`, and the grid's own width is what
     * decides). Below 768 the column shrinks with the viewport and the four
     * counters stack; that is the mobile layout, and it is not the one this
     * clip is placed in.
     */
    viewport: { width: 780, height: 900 },
    /** Raised from 580 for THIS scene: it is placed at 768 CSS px in the
     *  access claim, not in the 416px artifact column the shared ceiling was
     *  derived for. At 744 into 768 the product's own type renders at 1.03x —
     *  nearer its authored size than any other clip on the page.
     *
     *  744 and not 720: the column is 720 CSS px and `boxOf` pads it by 12 a
     *  side, so a 720 ceiling trimmed the pad off ONE side and sliced the
     *  fourth stats cell — the one that names the format — in half. A ceiling
     *  that cuts the frame it is supposed to protect is worse than no ceiling. */
    maxCropW: 744,
    /**
     * The sample export's four senders. They are synthetic (`SAMPLE_MBOX` in
     * components/import/ImportMail.tsx) so nothing here is protecting a real
     * company — this is a FRAMING gate: the crop must stop above the message
     * list, because the per-message verdicts are not this clip's claim and one
     * of the four is a rejection. The landing carries exactly one rejection,
     * deliberately, and it is not this one.
     */
    forbid: ["Cedar Labs", "Juniper Cloud", "Atlas Freight", "Maya Chen"],
    /**
     * The results block does not exist until the sample has been ingested, so
     * its geometry is measured by ingesting once and then reloading — the crop
     * stays DERIVED from real elements rather than typed in, which is the rule
     * the rest of this file follows. Two numbers survive the reload: how tall
     * the stats row is, and how far it sits below the note. The crop is then
     * built from the live note plus those, so a layout change moves the frame
     * with it.
     */
    async prepare(page) {
      await page.getByTestId("import-sample").click();
      await page.getByTestId("import-results").waitFor();
      this.measured = await page.evaluate(() => {
        const noteEl = document.querySelector('[role="note"]');
        const dl = document.querySelector('[data-testid="import-results"] dl');
        const found = document.querySelector('[data-testid="import-results"] p');
        if (!noteEl || !dl) throw new Error("import: nothing to measure the crop from");
        // Down to the file line ("sample.mbox · 4 messages found"), which names
        // what was read; the message list below it is out of frame by design.
        const bottom = (found ?? dl).getBoundingClientRect().bottom;
        return { run: bottom - noteEl.getBoundingClientRect().bottom };
      });
      // Back to the un-ingested page: the take has to OPEN on an empty result
      // with nothing computed yet, or there is no arrival to record. The whole
      // crop fits the viewport at scroll 0, so nothing is scrolled and the
      // frame is a stationary window by construction.
      await page.reload({ waitUntil: "networkidle" });
      await page.evaluate(() => document.fonts.ready);
      await page.waitForTimeout(600);
    },
    async crop(page) {
      // The whole action, top to bottom: the drop target and its two buttons
      // (so the counters below have a visible cause — the take's one event is
      // a press of "Try a sample export"), then the on-device promise, then the
      // ground the counters land on. The bottom edge is the only derived-then-
      // remembered number on the page, because the thing it measures does not
      // exist yet when the frame is chosen.
      const dropZone = page.getByTestId("import-sample").locator("xpath=../..");
      // The drop target carries ~110px of its own top padding above the
      // envelope glyph, which is right on a page and is dead frame in a clip.
      // Trimmed, not re-styled: the recording shows the shipped layout, and
      // the crop is where a frame gets chosen.
      const box = await boxOf(page, [dropZone, page.getByRole("note").first()], {
        trim: { top: 56 },
      });
      return { ...box, height: Math.round(box.height + this.measured.run) };
    },
    async run(page) {
      await page.getByTestId("import-sample").click();
      await page.getByTestId("import-results").waitFor();
      // Hold on the landed counters — the frame the clip ends on, and the one
      // the poster is taken from.
      await page.waitForTimeout(2200);
    },
  },
];
