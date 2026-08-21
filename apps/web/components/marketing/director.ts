"use client";

/**
 * The window act's take engine, ported from the motion lab the owner chose
 * the treatment in (`demo/motion-lab`, 2026-08-19) and RECUT 2026-08-21 to a
 * scale-locked camera (the owner's direction, verbatim: the take should play
 * at "the browser zoom, of how people usually keep the zoom", and cinematic
 * zoom belongs to the descent's rail boxes, not the oner).
 *
 * A take is choreographed REAL DOM: the shipped components mount and run
 * their own state machines, and this class supplies the three instruments a
 * take needs around them — a camera (one transform on the stage wrapper), a
 * synthesized pointer (an overlay that travels, then dispatches real events
 * at whatever it points to, so the product answers with its own behaviour),
 * and a caption line. Nothing here redraws a surface: if a click files rows,
 * it is because the mounted component filed them.
 *
 * THE CAMERA IS A SCROLL, NOT A ZOOM. It renders the stage at scale 1 —
 * natural size, the zoom a visitor's own browser is at — for the whole take,
 * and its only move is a vertical pan, which is the move a person makes in a
 * real session: scrolling the page to what they are about to read or press.
 * The previous cut zoomed (an establishing fit, a brace ahead of the day
 * filter's collapse, computed close-ups, a cover floor riding stage
 * resizes), and the owner rejected the result three times over: the zoom
 * cropped the panel it was clicking inside, framed things nothing pressed,
 * and pressed things the frame had already left. All of that machinery —
 * `brace`, `punchTo`, `fitAll`, `COVER_MAX`, the cover floor — existed to
 * carry a zoomed camera across the board's own layout changes, and it
 * retired with the zoom. What replaced it is one rule with no arithmetic to
 * get wrong: THE CAMERA FRAMES WHAT THE POINTER PRESSES, BEFORE IT PRESSES
 * IT (`panTo`, scroll-into-view grammar), and otherwise it does not move.
 *
 * The clock is pausable — every tween, hold and wait advances only while
 * `paused` is false, so scrolling away (or pressing pause) freezes the take
 * mid-frame instead of letting it finish unwatched — and cancellable:
 * `cancel()` makes the next frame throw {@link TakeError}, which unwinds the
 * script through its own awaits. Concurrency is plain `Promise.all`: each
 * tween ticks its own rAF loop against the shared flags, so a camera move
 * and a pointer glide can share the same frames.
 *
 * Coordinate model: the camera element carries `translate3d(x,y) scale(1)`
 * with origin 0 0; the stage is its untransformed child. The pointer lives
 * in FRAME coordinates and re-measures its target every frame
 * (`getBoundingClientRect` against the frame), which is what lets it track
 * an element the camera is moving under it.
 */

export class TakeError extends Error {}

/** A live target: re-resolved whenever it is measured, so a take can point
 *  at an element that does not exist yet (a pane about to dock) or one the
 *  board is still gliding into place. */
export type Target = HTMLElement | (() => HTMLElement | null);

const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

function resolve(target: Target): HTMLElement | null {
  return typeof target === "function" ? target() : target;
}

/** The tracking thresholds: below these, a reframe delta is one frame of an
 *  ANIMATED resize and assignment is the correct motion; above them it is a
 *  single-layout-pass change — the day filter, a pane mounting — and there
 *  is no animation to track, so assignment would be the whole transition.
 *  That assignment was the owner's cut (measured: a 447px pan snap between
 *  two frames 8ms apart), so past the threshold the reframe ABSORBS
 *  instead: a real eased camera move to the re-derived shot (`absorb`).
 *  Sized to what one 60fps frame of the board's own glide can move a shot
 *  by, with slack; a snap under it is sub-perceptual. */
const TRACK_EPS_PAN = 6;

/** The absorb move's length. Short enough to read as the camera catching
 *  the board's change, long enough to be a move rather than a flick; any
 *  authored move the script starts supersedes it mid-flight (`motion`). */
const ABSORB_MS = 450;

/** The last rendered camera state, read back from the frame's own
 *  `data-cam-*` — the values `applyCam` writes, in this file's own decimal
 *  format. A takeover director must glide from where the last one left the
 *  shot rather than restate it, and the dataset is how a fresh instance
 *  adopts a predecessor's last frame without any hand-off protocol. NOT
 *  parsed from `style.transform`: the browser re-serializes what it stores
 *  (the unitless z becomes `0px`), and a parser of one's own writes is
 *  exactly the kind of gate that cannot fail — the first cut of this
 *  adoption did fail on that serialization, silently, and the takeover
 *  snapped home (measured Δscale 0.849 in one frame before the fix). */
function adoptCam(frame: HTMLElement): { x: number; y: number } | null {
  const x = Number(frame.dataset.camX);
  const y = Number(frame.dataset.camY);
  return Number.isFinite(x) && Number.isFinite(y) ? { x, y } : null;
}

/** The breathing room a framed target keeps from the frame's edges, in frame
 *  px — one breath, so a control the pointer is about to press reads as
 *  inside the shot rather than kissing its crop. Also where a top-aligned
 *  pan seats its target's head below the frame's top edge. */
const PAN_PAD = 24;

/**
 * The take's CLOCK, on its own — pausable, cancellable, and able to narrate.
 * Split out of {@link Director} for the rail takes (`RailTake`): the 02b and
 * 08c exhibits run on this clock exactly as they did in the lab — timed
 * beats, a narration line, pause/replay — but neither moves a camera nor
 * synthesizes a pointer ("no camera, no pointer — the object itself
 * travels", the lab's own words), so the clock is all they may hold. A rail
 * that wants the full instrument set upgrades to the Director and says why.
 */
export class TakeClock {
  paused = false;
  /**
   * Take-time per wall-second — the rail governor's one knob (see
   * `RailTake`). A rail's band is a scroll DISTANCE and this clock is a
   * TIME, and the owner's dissolve-at-departure screenshot is what their
   * mismatch looks like: where a beat lands was purely a function of the
   * visitor's scroll speed. The governor raises this above 1 when the
   * visitor is outrunning the story, so the take compresses instead of
   * overflowing its band. Floor 1 by contract: a parked visitor always
   * gets the authored tempo. The oner never touches it.
   */
  rate = 1;
  /** Take-time elapsed since construction, ms — what the governor steers
   *  by. Advances by rate-scaled wall time, freezes with `paused`. */
  elapsed = 0;
  private cancelled = false;

  constructor(protected onCaption: (line: string) => void) {}

  cancel() {
    this.cancelled = true;
  }

  say(line: string) {
    this.onCaption(line);
  }

  // ---- the clock -----------------------------------------------------------

  /** One animation frame's worth of take-time: 0 while paused, wall-clock dt
   *  otherwise. Rejects once cancelled, which is how a script unwinds. */
  protected step(): Promise<number> {
    return new Promise((res, rej) => {
      const prev = performance.now();
      requestAnimationFrame(() => {
        if (this.cancelled) {
          rej(new TakeError("cancelled"));
          return;
        }
        const dt = this.paused ? 0 : (performance.now() - prev) * this.rate;
        this.elapsed += dt;
        res(dt);
      });
    });
  }

  async hold(ms: number) {
    let t = 0;
    while (t < ms) t += await this.step();
  }

  /** Eased 0→1 over `ms`, one call per frame; guaranteed to end on exactly 1. */
  async tween(ms: number, frame: (t: number) => void) {
    if (ms <= 0) {
      frame(1);
      return;
    }
    let t = 0;
    while (t < ms) {
      t += await this.step();
      frame(easeInOut(clamp(t / ms, 0, 1)));
    }
  }

  async waitFor(pred: () => unknown, timeoutMs = 10000, what = "condition") {
    let t = 0;
    while (!pred()) {
      t += await this.step();
      if (t > timeoutMs) throw new TakeError(`timed out waiting for ${what}`);
    }
  }
}

/** A shot the camera can HOLD, not just arrive at: the subject and how it is
 *  seated. Recording the shot (rather than the pan it resolved to once) is
 *  what lets `reframe` keep the composition true when the stage changes size
 *  under a parked camera — the day filter collapsing the board, a pane
 *  docking into it.
 *
 *  `into` is scroll-into-view: pan only as far as it takes for the target to
 *  sit whole inside the frame with `PAN_PAD` of breath, and not at all if it
 *  already does — the minimal move, which is the honest camera at scale 1.
 *  `top` seats the target's head just under the frame's top edge: the shot
 *  for a pane taller than the frame, whose head — not its middle — is what
 *  the narration is pointing at. */
type Shot = {
  target: Target | null;
  align: "into" | "top";
};

export class Director extends TakeClock {
  /** The camera's pan. Scale is 1 by construction and has no field: the take
   *  plays at the visitor's own browser zoom, full stop. */
  private cam = { x: 0, y: 0 };
  private cur = { x: 0, y: 0 };
  /** The current shot, kept live by `reframe` whenever the stage resizes. */
  private shot: Shot | null = null;
  /** True while a camera tween is in flight — the tween re-derives its own
   *  destination every frame, so `reframe` must not fight it. */
  private moving = false;
  /** Which camera move owns the transform. Every `moveCam` takes a fresh
   *  token and each of its frames checks it still holds it, so an authored
   *  move STARTED DURING an absorb simply takes over mid-flight — the
   *  superseded tween's remaining frames become no-ops and drain out. One
   *  camera, one hand on it, no hand-off seam. */
  private motion = 0;
  private ro: ResizeObserver | null = null;

  constructor(
    private frame: HTMLElement,
    private camera: HTMLElement,
    private stage: HTMLElement,
    private cursor: HTMLElement,
    onCaption: (line: string) => void,
  ) {
    super(onCaption);
    // The stage's size is part of every shot's arithmetic, and it CHANGES
    // mid-take — the day filter collapses the board, the detail pane grows
    // it — so the director watches it and re-derives the current shot when
    // it moves. Transforms are not layout, so applying the camera cannot
    // re-fire this.
    if (typeof ResizeObserver !== "undefined") {
      this.ro = new ResizeObserver(() => this.reframe());
      this.ro.observe(stage);
    }
    // THE CAMERA IS NEVER ALLOWED AN UNTRANSFORMED FRAME. Production opened
    // on ~500ms of the mounting board and then a hard cut when the take's
    // first write landed, because the camera element rendered with no
    // transform at all until the script's first beat. So construction
    // composes the frame on the spot:
    //   · a virgin camera is seeded at the resting shot — the board's own
    //     top, at natural size, which is exactly what the frame shows a
    //     no-JS or pre-take visitor;
    //   · a camera with a predecessor's rendered state on it is ADOPTED
    //     as-is, so a takeover director glides home from the live shot
    //     instead of restating it (`adoptCam`).
    // Constructed in a layout effect, so the seed is applied before the
    // stage's first paint — there is no frame for the defect to show on.
    this.shot = { target: null, align: "top" };
    this.cam = adoptCam(frame) ?? this.camTargetFor(null, "top", { x: 0, y: 0 });
    this.applyCam();
  }

  cancel() {
    super.cancel();
    this.ro?.disconnect();
  }

  // ---- finding things on the stage ----------------------------------------

  query(selector: string): HTMLElement | null {
    return this.stage.querySelector<HTMLElement>(selector);
  }

  queryAll(selector: string): HTMLElement[] {
    return Array.from(this.stage.querySelectorAll<HTMLElement>(selector));
  }

  find(selector: string): HTMLElement {
    const el = this.query(selector);
    if (!el) throw new TakeError(`nothing on stage matches ${selector}`);
    return el;
  }

  /** The visible button whose accessible name starts with `prefix` — the
   *  board renders some controls twice (spine + chip strip) and hides one
   *  per breakpoint, so visibility is part of the address. */
  byLabelPrefix(prefix: string): HTMLElement | null {
    const all = this.stage.querySelectorAll<HTMLElement>(`[aria-label^="${prefix}"]`);
    for (const el of all) if (el.offsetParent !== null) return el;
    return null;
  }

  buttonByText(text: string): HTMLElement | null {
    const all = this.stage.querySelectorAll<HTMLElement>("button");
    for (const el of all) {
      if (el.textContent?.trim() === text && el.offsetParent !== null) return el;
    }
    return null;
  }

  // ---- the camera ----------------------------------------------------------

  private applyCam() {
    const { x, y } = this.cam;
    this.camera.style.transform = `translate3d(${x}px, ${y}px, 0) scale(1)`;
    // The camera's position, written where a test can read it. The take's own
    // suite is green when the LOGIC runs — the pointer really pressed the day
    // bar, the board really narrowed — and none of it could see how the shot
    // travelled. `data-cam-*` on the frame is the truth of where the camera
    // is, per applied frame: the scale is a constant `1.000` by this recut's
    // contract (a gate that reads anything else has found a zoom that must
    // not exist), and the pan is what the continuity gate holds the line on
    // (the owner's cuts were pan snaps — 447px in one 8ms frame).
    this.frame.dataset.camScale = "1.000";
    this.frame.dataset.camX = x.toFixed(1);
    this.frame.dataset.camY = y.toFixed(1);
  }

  /** Re-derive the current shot after the stage changed size outside a
   *  camera tween — a held subject is re-seated, a vanished one releases the
   *  pan toward home, and either way the clamp keeps the frame on the stage
   *  the board now actually has.
   *
   *  A first cut snapped here unconditionally, on the premise that "the
   *  observer fires on each frame of an animated resize, so tracking IS
   *  the motion". The premise was FALSE for the two changes that matter:
   *  the day filter and the detail pane's mount are single layout passes
   *  (measured 2026-08-20: `offsetHeight` 783 → 417, then 417 → 806,
   *  between consecutive frames 8ms apart), so there was no animation to
   *  track and the snap was the entire transition — both of the owner's
   *  cuts. So the reframe now discriminates by DELTA: within the tracking
   *  threshold it assigns (one frame of a real animated resize, or
   *  jitter); past it it absorbs — a genuine eased camera move whose
   *  destination is re-derived every frame, so it also tracks a resize
   *  that is still animating underneath it. */
  private reframe() {
    if (!this.shot) return;
    if (this.moving) return; // the active tween re-derives its own destination
    const to = this.camTargetFor(this.shot.target, this.shot.align, this.cam);
    if (Math.abs(to.x - this.cam.x) <= TRACK_EPS_PAN && Math.abs(to.y - this.cam.y) <= TRACK_EPS_PAN) {
      this.cam = to;
      this.applyCam();
      return;
    }
    // Fire-and-forget on purpose: nothing is awaiting a resize. A newer
    // discontinuity, or the script's next authored move, supersedes this
    // one via `motion` and the drained tween's frames no-op. Cancellation
    // lands here as TakeError, which is the take unwinding — not an error.
    void this.moveCam(this.shot, ABSORB_MS).catch((err: unknown) => {
      if (!(err instanceof TakeError)) throw err;
    });
  }

  /**
   * Where the camera must sit for `target` to be inside the frame, derived
   * from `base` — the pan the move is judged FROM (a tween's start, or the
   * live camera for a reframe), which is what makes `into` a minimal move
   * rather than a recentring: a target already whole in frame resolves to
   * `base` itself and the camera does not stir.
   *
   * The pan is clamped so the frame never runs past the stage's edges it
   * could show: `y` rests at 0 (the board's own top — a page is read from
   * the top, so a stage shorter than the frame sits where a browser would
   * put it, never letterbox-centred) and reaches at most `fh − sh` (the
   * stage's foot on the frame's foot). `x` is centred; the stage fills the
   * frame's width at scale 1, so in practice it is 0.
   */
  private camTargetFor(target: Target | null, align: "into" | "top", base: { x: number; y: number }) {
    const f = this.frame.getBoundingClientRect();
    const sw = this.stage.offsetWidth;
    const sh = this.stage.offsetHeight;
    const x = sw > f.width ? clamp(base.x, f.width - sw, 0) : (f.width - sw) / 2;
    let y = 0;
    const el = target ? resolve(target) : null;
    if (el) {
      const r = el.getBoundingClientRect();
      const sr = this.stage.getBoundingClientRect();
      // Stage coordinates — the transform is a pure translate, so the rect
      // needs shifting, never unscaling.
      const ty = r.top - sr.top;
      const tb = ty + r.height;
      if (align === "top" || r.height > f.height - 2 * PAN_PAD) {
        // The head is the shot: a pane taller than the frame is read from
        // its top, and `into` degrades to the same seat for the same reason.
        y = PAN_PAD - ty;
      } else {
        y = base.y;
        if (ty + y < PAN_PAD) y = PAN_PAD - ty;
        else if (tb + y > f.height - PAN_PAD) y = f.height - PAN_PAD - tb;
      }
    }
    y = sh > f.height ? clamp(y, f.height - sh, 0) : 0;
    return { x, y };
  }

  /**
   * The one authored camera move: pan the stage so `target` sits in frame —
   * BEFORE the pointer presses it, which is the recut's whole covenant. The
   * destination is re-derived every frame from the move's own start (target
   * rect, clamps — the same rule the pointer lives by), so a board still
   * gliding under the move cannot leave the shot stale; and the duration is
   * a function of the distance actually travelled, because a fixed-length
   * tween makes a 12px adjustment take as long as a 300px scroll and both
   * read wrong.
   */
  async panTo(target: Target, align: "into" | "top" = "into", ms?: number) {
    const to = this.camTargetFor(target, align, this.cam);
    const dist = Math.hypot(to.x - this.cam.x, to.y - this.cam.y);
    const dur = ms ?? (dist < 2 ? 0 : clamp(dist * 2.2, 450, 1100));
    await this.moveCam({ target, align }, dur);
  }

  /** The resting shot: the board's own top, at natural size — where a real
   *  session starts and where the take leaves the visitor. */
  async panHome(ms = 900) {
    await this.moveCam({ target: null, align: "top" }, ms);
  }

  /**
   * The one camera tween. The destination is re-derived EVERY FRAME — target
   * rect, clamps — against the move's own start, and the tween eases from
   * where the authored camera was, landing exactly on the live destination
   * at t=1. Superseded frames (a newer `motion` token) drain as no-ops.
   */
  private async moveCam(shot: Shot, ms: number) {
    const token = ++this.motion;
    this.shot = shot;
    this.moving = true;
    try {
      const from = { ...this.cam };
      await this.tween(ms, (t) => {
        // Superseded — a newer move owns the camera; drain silently.
        if (this.motion !== token) return;
        const to = this.camTargetFor(shot.target, shot.align, from);
        this.cam = {
          x: from.x + (to.x - from.x) * t,
          y: from.y + (to.y - from.y) * t,
        };
        this.applyCam();
      });
    } finally {
      if (this.motion === token) this.moving = false;
    }
  }

  // ---- the pointer ---------------------------------------------------------

  /** Where the pointer's hotspot should sit for `target`, in frame coords —
   *  slightly below centre, the way a hand actually lands on a control. */
  private pointFor(target: Target): { x: number; y: number } | null {
    const el = resolve(target);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const f = this.frame.getBoundingClientRect();
    return { x: r.left - f.left + r.width / 2, y: r.top - f.top + r.height * 0.6 };
  }

  private applyCursor() {
    this.cursor.style.transform = `translate3d(${this.cur.x}px, ${this.cur.y}px, 0)`;
  }

  /** The pointer arrives from just off the frame's lower-right — it never
   *  teleports into shot. */
  enterCursor() {
    const f = this.frame.getBoundingClientRect();
    this.cur = { x: f.width * 0.86, y: f.height + 24 };
    this.applyCursor();
    this.cursor.style.opacity = "1";
  }

  hideCursor() {
    this.cursor.style.opacity = "0";
  }

  async moveTo(target: Target, ms?: number) {
    const start = { ...this.cur };
    const first = this.pointFor(target) ?? start;
    const dist = Math.hypot(first.x - start.x, first.y - start.y);
    const dur = ms ?? clamp(dist * 1.4, 420, 1300);
    this.cursor.style.opacity = "1";
    await this.tween(dur, (t) => {
      // Re-measured every frame, so the pointer tracks a target the camera
      // (or the board's own layout animation) is moving under it.
      const p = this.pointFor(target) ?? first;
      this.cur.x = start.x + (p.x - start.x) * t;
      this.cur.y = start.y + (p.y - start.y) * t;
      this.applyCursor();
    });
  }

  private ripple() {
    const r = document.createElement("span");
    r.style.cssText =
      `position:absolute;left:${this.cur.x - 14}px;top:${this.cur.y - 14}px;` +
      "width:28px;height:28px;border:1.5px solid var(--viz-rules);" +
      "border-radius:9999px;pointer-events:none;z-index:30;";
    this.frame.appendChild(r);
    r.animate(
      [
        { transform: "scale(0.35)", opacity: 0.9 },
        { transform: "scale(1.7)", opacity: 0 },
      ],
      { duration: 480, easing: "ease-out" },
    ).finished.finally(() => r.remove());
  }

  /**
   * Travel to the target, then press it FOR REAL: pointer/mouse events
   * dispatched at the element plus its own `click()`, so whatever the
   * product does with a click — open a pane, run a sync, filter the list —
   * is the product doing it. The take cannot make the surface do anything a
   * visitor's hand could not.
   */
  async click(target: Target) {
    await this.moveTo(target);
    const el = resolve(target);
    if (!el) throw new TakeError("click target vanished");
    this.ripple();
    this.cursor.animate(
      [{ transform: "scale(1)" }, { transform: "scale(0.82)" }, { transform: "scale(1)" }],
      { duration: 220, easing: "ease-out", pseudoElement: undefined, composite: "add" },
    );
    const opts = { bubbles: true, cancelable: true, view: window } as const;
    el.dispatchEvent(new PointerEvent("pointerdown", opts));
    el.dispatchEvent(new MouseEvent("mousedown", opts));
    await this.hold(90);
    el.dispatchEvent(new PointerEvent("pointerup", opts));
    el.dispatchEvent(new MouseEvent("mouseup", opts));
    el.click();
    await this.hold(140);
  }
}
