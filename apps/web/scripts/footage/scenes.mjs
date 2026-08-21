/**
 * The scenes — the moments on the PUBLIC fixture surfaces that survived the
 * measurement pass. Never the signed-in app: that account holds the owner's
 * real employers and real rejections, and this footage goes on a marketing
 * page. `/demo` runs the same shipped components over fixture data, which is
 * what the landing should show anyway; `one-letter` is the one scene that
 * captures elsewhere, and its own header says why.
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

/**
 * The tracked scene's frame, in CSS px — derived twice over, never chosen.
 *
 * 704x528 since 2026-08-21, when the owner turned the row rail into the
 * page's second big box ("a big square and rectangle box that covers the
 * entire half of the left side" — his words, on a screenshot of the old
 * 478x129 strip). The strip's 576x155 was derived from a rail picture that
 * no longer exists, so both numbers re-derive from the new one:
 *
 * 704 because the row rail's ceiling is 44rem (`ClaimsDescent`'s
 * `--rail-row`), whose picture renders 702 CSS px wide — so a 704 CSS
 * frame, captured at 2x, encodes 1408 native px and the 2x screen the page
 * is designed on reads the clip at essentially 1:1, with `Clip.tsx`'s `k`
 * on exactly 2.0 and not one captured pixel scaled up. That is over the
 * shared 580 ceiling, which is a DEFAULT sized for the old 478px placement;
 * the scene raises its own (`maxCropW` below) for the 702px placement, the
 * knob MAX_CROP_W's docblock reserves for exactly this.
 * 528 because the box should read as a box, not a slot, and 4:3 is the
 * tallest shape the short viewport corner can seat: at 1024x600 the rail's
 * fold cap resolves the box to ~432px wide, whose 4:3 picture plus chrome
 * still clears the fold with the transport reachable (the `--rail-row`
 * derivation in ClaimsDescent carries the arithmetic). Squarer than 4:3
 * breaks that corner; wider stops being the box the owner asked for.
 * 1408x1056 divides evenly for H.264 and `k = 2.0` exactly.
 *
 * WHAT THE HEIGHT BUYS, in shot terms: the held opening now carries the
 * whole letter IN its pane with the board beside it, and the landing seats
 * the row inside its group with the neighbouring groups in frame — the row
 * seen in the board, which the 155px strip could only gesture at.
 */
const FRAME = { width: 704, height: 528 };

/** Padding around a derived crop, in CSS px. */
const PAD = 12;

/**
 * A camera path: one frame size, and where that frame sits over the page at a
 * few moments of the take. `at` is in CAPTURE seconds, read off `scene.json`
 * or a contact sheet exactly as the cut's `window` is; `x` / `y` are the
 * frame's top-left in CSS px. Two keyframes at the same position are a HOLD,
 * and a scene with one keyframe is a stationary window — which is what every
 * other scene here is, written the long way.
 *
 * The frame size is constant for the whole path ON PURPOSE, and it is the one
 * rule this abstraction enforces rather than documents. A frame that changed
 * size would be a zoom, and a zoom cannot be afforded honestly: the pipeline
 * never scales a captured pixel up (`Clip.tsx`), which pins the tightest
 * possible frame at half the encode's width — 576 CSS px — and the widest at
 * whatever stays legible in a 478px picture, which is about the same number.
 * The room to zoom is nil. The room to TRAVEL is the whole page.
 *
 * The keyframes are DERIVED from real elements, the same rule `boxOf` follows,
 * so a layout change moves the camera with it instead of quietly filming the
 * wrong rectangle.
 */
export function cameraPath(frame, path) {
  if (!path.length) throw new Error("a camera path needs at least one keyframe");
  return {
    width: Math.round(frame.width),
    height: Math.round(frame.height),
    path: path.map((k) => ({ at: k.at, x: Math.round(k.x), y: Math.round(k.y) })),
  };
}

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
    id: "one-letter",
    title: "One letter, and the row it left behind",
    /**
     * The retention claim's exhibit, and the first scene here shot with a
     * camera that moves. `PRIVACY.retention` says the classifier reads a
     * message's body to decide and then discards it; the sync recording showed
     * the counting half of that, and this shows the OTHER half — one message,
     * read, and the row it left on the board.
     *
     * THE SHOT. One continuous take, one frame size, no cut. It opens held on
     * the letter — Kestrel Dynamics' assessment invitation, in the detail
     * pane's own mail trail, carrying the verdict the classifier already
     * reached (`assessment`, 97%, drawn against the 0.85 gate) and the
     * sentence that named the deadline. The pane is then closed by a real
     * press of its own × and the board answers in frame: every row expands
     * into the space the pane held, by `PipelineBoard`'s own layout animation
     * (measured on this surface at this viewport: the tracked row goes 632 →
     * 1036 px wide and un-wraps 68 → 42 px tall, settled in 202 ms). The
     * camera rides that expansion up and to the left and comes to rest on the
     * ASSESSMENT group, with the row the letter produced sitting in it.
     *
     * WHY /landing-a AND NOT /demo, which every other scene captures from.
     * The subject has to be an assessment, and it has to be filed AT
     * assessment — `assessment` has been a stage of its own since 2026-08-12.
     * /demo cannot show that: it has no `assessment`-status row at all, and
     * its own Kestrel row is filed at `interviewing` with an assessment mail
     * behind it, which `lib/demo/demoData.ts` documents as stale rather than
     * principled. Filming it would publish a fixture this repo already knows
     * is wrong. /landing-a mounts the SAME shipped components — the real
     * `PipelineBoard`, the real `ApplicationRow`, the real
     * `ApplicationDetail` — over `components/marketing/showcase.ts`, where
     * Kestrel is filed at `assessment` with the deadline its mail stated. The
     * rule /demo exists to hold is that no marketing frame shows the owner's
     * real mail; that rule is kept here in full. Every employer in this
     * fixture is invented.
     *
     * TWO REFUSALS, from the storyboard, structural rather than captioned:
     *  · nothing is classified on camera. The pane is opened, and its trail
     *    resolved, in `prepare` — before a frame is recorded — so the verdict
     *    is already a fact when the take begins. There is no moment a viewer
     *    could read as the frame deciding anything.
     *  · the letter is never a rejection. Production has never auto-detected
     *    one; every rejection on a real board came through the human review
     *    gate, so a shot that filed one on its own would fabricate a
     *    capability. `forbid` below keeps the board's one closed row out of
     *    the camera's whole travel, and fails the capture if the path ever
     *    wanders onto it.
     *
     * WHAT WAS CUT FROM THE STORYBOARD, AND WHY. The plate opened on three
     * mail arrivals drifting toward the board and folded one of them into a
     * row mid-flight. Neither is filmable: mail does not travel across
     * Applied's screen, and making it do so means compositing a mail layer
     * over a board layer — motion graphics, which the covenant bans and the
     * camera clause does not reach. What survives is the true residue: the
     * trail really does hold two messages, and the camera really does lock
     * onto the one that decided.
     */
    url: "/landing-a",
    /**
     * 1280, and both numbers are load-bearing.
     *
     * WIDTH. `ApplicationDetail`'s docked pane grows to 384 CSS px and stops,
     * and the whole shot depends on the letter being READ: at 1152 the pane
     * is 346 and the subject line truncates to "Next step: online assessment
     * (90 m…" — the four words the clip exists for. 1280 is the narrowest
     * viewport that gives the pane its full width. Above it nothing improves;
     * the pane is right-anchored, so a frame pushed as far right as the
     * viewport allows sits 168 px into the worklist at EVERY width.
     *
     * HEIGHT. 1000, not 900. The board's stage is
     * `clamp(480px, calc(100dvh - 16.5rem), 900px)` (app/landing-a/page.tsx),
     * so the viewport's height decides how much board there is; at 900 the
     * docked pane's foot falls below the fold and the trail's second message
     * is cut in half at the exact moment the camera is holding on the first.
     */
    viewport: { width: 1280, height: 1000 },
    /**
     * Raised for the big-box placement: the row rail shows this clip at up
     * to 702 CSS px (`--rail-row`'s 44rem ceiling), so a 704 frame is a
     * 1.0x read there — the shared 580 default is sized for a placement
     * this clip no longer has. FRAME's docblock carries the derivation.
     */
    maxCropW: FRAME.width,
    /**
     * The board's one closed row, and the phrase it files under. This is a
     * FRAMING gate on the camera's whole travel: the showcase fixture carries
     * a rejection deliberately (a board with no verdict it did not want is a
     * brochure — see showcase.ts), and it is exactly what this clip must not
     * be seen filing. `assertNothingForbidden` measures every matching element
     * against the path's bounding box, so a camera that drifts far enough down
     * the worklist to catch the closed group fails the capture rather than
     * shipping.
     */
    forbid: ["Atlas Freight", "Moving forward with other candidates"],
    /**
     * Two things happen here, and both have to happen BEFORE the first frame.
     *
     * The ASSESSMENT group's resting geometry is measured first, because the
     * camera's landing is a rectangle over a state that does not exist while
     * the pane is open — the same derived-then-remembered idiom the import
     * scene uses for its counters, and for the same reason: a crop typed in as
     * a number stops following the layout.
     *
     * Then the row is opened, through its own shipped opener, and the trail is
     * waited for. That is what puts the verdict on screen before the camera
     * rolls.
     */
    async prepare(page) {
      await page.waitForSelector('[data-testid="pipeline-board"]');
      await page.evaluate(() => document.fonts.ready);
      await page.waitForTimeout(600);
      this.seated = await page.evaluate(() => {
        const section = [...document.querySelectorAll("section[aria-label]")].find((el) =>
          /^assessment —/i.test(el.getAttribute("aria-label") ?? ""),
        );
        if (!section) throw new Error("one-letter: no assessment group on the board");
        const row = section.querySelector("li");
        if (!row) throw new Error("one-letter: the assessment group is empty");
        const closed = [...document.querySelectorAll("section[aria-label]")].find((el) =>
          /^closed —/i.test(el.getAttribute("aria-label") ?? ""),
        );
        if (!closed) throw new Error("one-letter: no closed group to keep out of frame");
        const board = document.querySelector('[data-testid="pipeline-board"]');
        if (!board) throw new Error("one-letter: no board");
        const g = section.getBoundingClientRect();
        const r = row.getBoundingClientRect();
        // `boardLeft` is the whole board's edge — spine included — because
        // that is where the seat's frame now rests (see `camera`). The
        // closed group's top is measured in the SAME resting state the
        // landing films in: the 4:3 frame reaches far enough down the board
        // that the seat must be derived against it, not just trusted to the
        // forbid gate's failure.
        return {
          left: g.x,
          boardLeft: board.getBoundingClientRect().x,
          rowMid: r.y + r.height / 2,
          closedTop: closed.getBoundingClientRect().y,
        };
      });
      await page.getByRole("button", { name: /^Open Kestrel Dynamics/ }).click();
      // The trail is a real transport call, and the pane mounts on "loading
      // the mail trail…" while it runs. Waiting for the message itself — not
      // for the pane — is what guarantees the take opens on a resolved
      // verdict rather than on a spinner.
      await page
        .locator('[data-testid="application-detail"] li', { hasText: "online assessment" })
        .first()
        .waitFor();
      await page.waitForTimeout(700);
    },
    /**
     * The camera. 704 x 528 CSS px (FRAME's docblock derives both), held,
     * tracked, held — half the 1408 the clip encodes at, captured at 2x, so
     * `Clip.tsx`'s `k` lands on exactly 2.0 and not one pixel is scaled up.
     *
     * The keyframes are the beats. The hold either side of the move is what
     * makes it a tracking shot rather than a drift — a camera that is
     * always moving has no beginning and no end. The 4:3 frame keeps the
     * same path shape as the 155px strip did (hold on the letter, tilt to
     * the row's line, track into its group): the taller window changes what
     * each position CONTAINS — the whole pane, the row among its
     * neighbours — not where the camera goes.
     */
    async camera(page) {
      const vp = page.viewportSize();
      const letter = await page
        .locator('[data-testid="application-detail"] li', { hasText: "online assessment" })
        .first()
        .boundingBox();
      if (!letter) throw new Error("one-letter: the letter is not on screen");
      // As far right as the frame can sit and still be a window on the page.
      // The pane is right-anchored, so this is what puts the letter in frame
      // with the board's own edge beside it — the shot's whole subject, both
      // halves, without a composite. Vertically the frame ENDS just under the
      // letter (12px into the gap before the trail's second message, which is
      // excluded whole rather than cut mid-card): the 4:3 window read upward
      // from there holds the pane's chips, the deadline, the next-step line
      // and the letter, with the worklist's own rows beside them — measured
      // at 1280x1000, frame y 263..791 against a pane at 300..936.
      const held = {
        x: Math.min(letter.x - 18, vp.width - FRAME.width),
        y: letter.y + letter.height + 12 - FRAME.height,
      };
      // The landing: the board's whole left flank — the stages spine (with
      // ASSESSMENT counted on it), the group heading, and the row's identity,
      // every one of them WHOLE. Measured post-close at 1280x1000: heading
      // 224 to deadline-chip end 997 spans 773 CSS px, so no 704 frame can
      // rest on both ends without slicing one — and a sliced chip in the
      // landed poster was exactly what the first 4:3 cut produced. The chip
      // is not lost: the track carries it through the frame at 1:1 on the
      // way to this seat ("past the same deadline drawn on the row" —
      // FOOTAGE.letter.name has always said the camera goes PAST it). What
      // the shot rests on is the row seen IN the board, spine and all.
      //
      // Same y as the held frame — a PURE lateral track, no drift — with the
      // closed group's line as the one override: the frame must never reach
      // the group this clip refuses to film (`forbid`), so the seat rises
      // off the shared line before it lets that happen.
      const seat = {
        x: this.seated.boardLeft - 12,
        y: Math.min(held.y, this.seated.closedTop - 12 - FRAME.height),
      };
      // ONE TRACK, NOT THE OLD TILT-THEN-TRACK. The 155px strip needed two
      // segments because its letterbox could only hold one line of the page
      // at a time — it had to climb the pane's column before it could travel.
      // The 4:3 frame holds the letter AND the row's own line at once, so the
      // move that remains is the honest one: after the press is answered, the
      // camera tracks LEFT along the row it never lets go of, from the pane's
      // side of the board into the ASSESSMENT group, and rests.
      return cameraPath(FRAME, [
        { at: 0, ...held },
        // The press lands at ~2.2s and the board's answer is done by ~2.45s;
        // the camera stays put through both, so the expansion is watched
        // rather than chased — camera motion is spent only on what the press
        // did, never on arriving somewhere nothing happened.
        { at: 2.9, ...held },
        { at: 4.4, ...seat },
        { at: 7.05, ...seat },
      ]);
    },
    /** The path's bounding box, for the `forbid` gate. */
    async crop(page) {
      const cam = await this.camera(page);
      const xs = cam.path.map((k) => k.x);
      const ys = cam.path.map((k) => k.y);
      return {
        x: Math.min(...xs),
        y: Math.min(...ys),
        width: Math.max(...xs) - Math.min(...xs) + cam.width,
        height: Math.max(...ys) - Math.min(...ys) + cam.height,
      };
    },
    async run(page) {
      // Held on the letter, long enough to read the subject, the sender and
      // the verdict under it.
      await page.waitForTimeout(1500);
      // The take's one input: a press of the pane's own close control. It is
      // dispatched at the shipped button exactly as every other scene's is,
      // and nothing draws a pointer for it.
      await page.getByRole("button", { name: "Close detail" }).click();
      // The expansion, the tilt, the beat on the match, the track, and the
      // hold on the seated row — the camera's last keyframe is at 7.05s of
      // capture time and the take has to outlive it.
      await page.waitForTimeout(5100);
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
     * The arc is real and was measured, not staged: the verdict holds at
     * OTHER for the first 174 characters and flips to REJECTION at 175, on
     * "…consideration we have decided…". Gmail's preview is about 200
     * characters. The flip lands inside that window, which is the whole point
     * of the claim beside it.
     *
     * `scripts/footage/geom2.mjs` was cited here as the instrument that
     * measured it and DOES NOT EXIST in the tree. Re-measured on the shipped
     * mp4 on 2026-08-21 by extracting all 654 frames: the chip flips at frame
     * 426 (7.083s), which is ~char 176, so the documented 175 is right to
     * within one frame of capture granularity.
     *
     * WHAT THAT RE-MEASUREMENT ALSO FOUND, and it is NOT new: the confidence
     * steps 50% → 70% at the flip and 70% → 90% at frame 502, 1.267s later,
     * and the status line under the verdict changes on the SECOND step, not
     * the first. That split is a property of the arc rather than of any
     * threshold: 0.90 and 0.85 both sit inside (0.70, 0.90], so the old
     * status line and the current one change on exactly the same frame. The
     * clip has always read as two events. Worth knowing before anyone
     * "fixes" a threshold to close a gap a threshold did not open.
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
      // ONE CHARACTER PER STEP, at an irregular cadence. The previous take
      // typed in bursts of 2-7 characters every 26ms — the whole body landed
      // in about a second, and the owner read it as pasting, which it
      // visually was. A keystroke is the unit a reader's eye knows, so the
      // take types like a fast, fluent typist: ~25 characters a second,
      // small tempo wobble on a fixed cycle (not random, so a re-render
      // produces the same take). The evaluate round-trip adds a few ms per
      // step; the cadence below was tuned WITH that overhead against the
      // recorded scene.json timestamps, not against arithmetic alone.
      const DELAYS = [24, 38, 18, 46, 28, 22, 52, 30, 20, 36, 26, 44];
      for (let i = 1; i <= text.length; i += 1) {
        await typeInto(page, "playground-body", text.slice(0, i));
        await page.waitForTimeout(DELAYS[i % DELAYS.length]);
      }
      // Hold on the landed verdict — the frame the clip ends on, and the state
      // it loops back out of.
      await page.waitForTimeout(2000);
    },
  },
];
