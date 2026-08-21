"use client";

/**
 * The window act's take engine, ported from the motion lab the owner chose
 * the treatment in (`demo/motion-lab`, 2026-08-19).
 *
 * A take is choreographed REAL DOM: the shipped components mount and run
 * their own state machines, and this class supplies the three instruments a
 * take needs around them — a camera (one transform on the stage wrapper), a
 * synthesized pointer (an overlay that travels, then dispatches real events
 * at whatever it points to, so the product answers with its own behaviour),
 * and a caption line. Nothing here redraws a surface: if a click files rows,
 * it is because the mounted component filed them.
 *
 * The clock is pausable — every tween, hold and wait advances only while
 * `paused` is false, so scrolling away (or pressing pause) freezes the take
 * mid-frame instead of letting it finish unwatched — and cancellable:
 * `cancel()` makes the next frame throw {@link TakeError}, which unwinds the
 * script through its own awaits. Concurrency is plain `Promise.all`: each
 * tween ticks its own rAF loop against the shared flags, so a camera move
 * and a pointer glide can share the same frames.
 *
 * Coordinate model: the camera element carries `translate3d(x,y) scale(s)`
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

/** The close-up's fit ceiling. 1.9 keeps a punched control inside "detail
 *  shot" — at 2× and beyond the product's 13px type renders 26px+ and reads
 *  as a magnifier, not a camera. */
const PUNCH_MAX = 1.9;

/** How far the cover rule may push past `PUNCH_MAX` before a letterbox is
 *  accepted after all. 2.75 covers the measured worst case on this page — the
 *  day-filtered board (three rows) inside a tall viewport's frame — with the
 *  type still legible; past it a void is the lesser evil. Exported for the
 *  script's own scale resolvers (`OnerStage.filteredCover`), which must cap
 *  where the camera caps. */
export const COVER_MAX = 2.75;

/** The tracking thresholds: below these, a reframe delta is one frame of an
 *  ANIMATED resize and assignment is the correct motion; above them it is a
 *  single-layout-pass change — the day filter, a pane mounting — and there
 *  is no animation to track, so assignment would be the whole transition.
 *  That assignment was the owner's cut (measured: scale +88% and a 447px
 *  pan snap between two frames 8ms apart), so past the threshold the
 *  reframe ABSORBS instead: a real eased camera move to the re-derived
 *  shot (`absorb`). Sized to what one 60fps frame of the board's own glide
 *  can move a shot by, with slack; a snap under them is sub-perceptual. */
const TRACK_EPS_SCALE = 0.01;
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
function adoptCam(frame: HTMLElement): { scale: number; x: number; y: number } | null {
  const scale = Number(frame.dataset.camScale);
  const x = Number(frame.dataset.camX);
  const y = Number(frame.dataset.camY);
  return Number.isFinite(scale) && Number.isFinite(x) && Number.isFinite(y)
    ? { scale, x, y }
    : null;
}

/** Where a top-aligned close-up seats its target below the frame's top edge,
 *  in frame px — one breath, so the pane's own border reads as inside the
 *  shot rather than cropped by it. */
const CLOSEUP_HEADROOM = 24;

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

/** A shot the camera can HOLD, not just arrive at: the subject, a scale
 *  resolver re-evaluated against live geometry, and whether the cover floor
 *  is armed while it plays. Recording the shot (rather than the number it
 *  resolved to once) is what lets `reframe` keep the composition true when
 *  the stage changes size under a parked camera. */
type Shot = {
  target: Target | null;
  scale: () => number;
  align: "centre" | "top";
  cover: boolean;
};

export class Director extends TakeClock {
  private cam = { scale: 1, x: 0, y: 0 };
  /** What the camera element actually renders — `cam` raised to the cover
   *  floor and re-clamped. Kept separate so tweens interpolate the AUTHORED
   *  path while the floor rides over it, and so stage-rect measurements can
   *  unscale by the transform that is really applied. */
  private rendered = { scale: 1, x: 0, y: 0 };
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
  /** The cover floor's switch — see `followCover` and `applyCam`. */
  private covering = false;
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
    // mid-take — the day filter collapses the board, the pulse panel grows
    // it — so the director watches it and re-derives the current shot when
    // it moves. Transforms are not layout, so applying the camera cannot
    // re-fire this.
    if (typeof ResizeObserver !== "undefined") {
      this.ro = new ResizeObserver(() => this.reframe());
      this.ro.observe(stage);
    }
    // THE CAMERA IS NEVER ALLOWED AN UNTRANSFORMED FRAME. Production opened
    // on ~500ms of the mounting board at natural scale and then cut to the
    // establishing fit (measured 2026-08-20: 56 frames at 1.0, then a hard
    // snap to 0.925 at 1440x900 — a 32% mismatch at 1024x768), because the
    // camera element renders with no transform and `fitAll(0)` was the
    // first write. So construction composes the frame on the spot:
    //   · a virgin camera is seeded with the establishing fit of whatever
    //     the stage holds right now (the skeleton fits too — when the real
    //     board lands, the resize is absorbed as a move like any other);
    //   · a camera with a predecessor's rendered state on it is ADOPTED
    //     as-is, so a takeover director glides home from the live shot
    //     instead of restating it (`adoptCam`).
    // Constructed in a layout effect, so the seed is applied before the
    // stage's first paint — there is no frame for the defect to show on.
    this.shot = { target: null, scale: this.fitScale, align: "centre", cover: false };
    this.cam = adoptCam(frame) ?? this.camTargetFor(null, this.fitScale(), "centre");
    this.rendered = { ...this.cam };
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

  /** Stage geometry for script-side scale resolvers (`filteredCover`) —
   *  layout truth (`offsetHeight`) and rendered truth (the rect), so a
   *  resolver can unscale what it measures the way internal ones do. */
  stageHeight(): number {
    return this.stage.offsetHeight;
  }

  stageRect(): DOMRect {
    return this.stage.getBoundingClientRect();
  }

  frameRect(): DOMRect {
    return this.frame.getBoundingClientRect();
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

  /** The scale at which the stage covers the frame's height, capped at
   *  `COVER_MAX` — past the cap a letterbox is the lesser evil (see the
   *  constant). Live: re-read every time, because the stage resizing is
   *  exactly when this number matters. */
  private coverScale(): number {
    return Math.min(this.frame.getBoundingClientRect().height / this.stage.offsetHeight, COVER_MAX);
  }

  /** Clamp a pan so the stage never tears off an edge it covers, and centre
   *  it on any axis it does not — the same rule `camTargetFor` applies at
   *  target time, applied continuously so no rendered frame can violate it. */
  private clampPan(scale: number, x: number, y: number) {
    const f = this.frame.getBoundingClientRect();
    const sw = this.stage.offsetWidth;
    const sh = this.stage.offsetHeight;
    x = scale * sw > f.width ? clamp(x, f.width - scale * sw, 0) : (f.width - scale * sw) / 2;
    y = scale * sh > f.height ? clamp(y, f.height - scale * sh, 0) : Math.max(0, (f.height - scale * sh) / 2);
    return { x, y };
  }

  private applyCam() {
    let { scale, x, y } = this.cam;
    // THE COVER FLOOR, enforced on every rendered frame rather than once at
    // punch time. The owner's void, in its second form (measured 2026-08-20,
    // production build): the day filter SHRINKS the board while the camera is
    // still parked at the establishing scale, and a cover bound evaluated
    // only when `punchTo` was called left the frame 47% empty for the ~1.4s
    // it took the push-in to catch up — at 1024x600 and 1024x768 alike, on
    // the beat where the product does the thing. While `covering` is armed
    // (a punch, or `followCover` ahead of a click the script knows will
    // collapse the stage), the rendered scale never drops below the live
    // cover bound: as the board's own glide shrinks the stage, the floor
    // rises with it and the camera RIDES the collapse, frame for frame. The
    // raise keeps the frame's centre on its subject; `clampPan` then keeps
    // every edge honest. `fitAll` disarms it — the establishing shot's
    // letterbox is composition, not void (see `fitAll`).
    if (this.covering) {
      const floor = this.coverScale();
      if (scale < floor) {
        const f = this.frame.getBoundingClientRect();
        x = f.width / 2 - (floor / scale) * (f.width / 2 - x);
        y = f.height / 2 - (floor / scale) * (f.height / 2 - y);
        scale = floor;
      }
    }
    ({ x, y } = this.clampPan(scale, x, y));
    this.rendered = { scale, x, y };
    this.camera.style.transform = `translate3d(${x}px, ${y}px, 0) scale(${scale})`;
    // The camera's position, written where a test can read it. The take's own
    // suite is green when the LOGIC runs — the pointer really pressed the day
    // bar, the board really narrowed — and none of it could see that the shot
    // was not a shot: production played a whole take with the camera parked
    // at scale 1 and nobody's gate went red. A shot is assertable now:
    // `data-cam-scale` on the frame is the truth of where the camera is, per
    // frame — the RENDERED truth, floor included — and the e2e can require it
    // to actually arrive somewhere. The pan joined it (2026-08-20): the
    // owner's cuts were pan snaps as much as scale snaps (447px in one 8ms
    // frame), and the continuity gate needs all three axes to hold the line.
    this.frame.dataset.camScale = scale.toFixed(3);
    this.frame.dataset.camX = x.toFixed(1);
    this.frame.dataset.camY = y.toFixed(1);
  }

  /**
   * Arm the cover floor without moving the camera — for a script that knows
   * a stage change is coming but has no shot to author against it. The oner
   * no longer needs this on the filter beat (`brace` arms the floor through
   * its own shot, and arrives BEFORE the collapse instead of letting the
   * floor snap through it), but the switch stays: it is the director's only
   * way to hold the void guarantee across a change no move anticipates.
   * Every `punchTo` arms it too; `fitAll` stands it down.
   */
  followCover() {
    this.covering = true;
  }

  /** Re-derive the current shot after the stage changed size outside a
   *  camera tween — a fit re-fits (letterbox intact), a punch re-frames its
   *  subject at its re-resolved scale, and the cover floor (when armed) is
   *  re-applied by `applyCam` either way.
   *
   *  A first cut snapped here unconditionally, on the premise that "the
   *  observer fires on each frame of an animated resize, so tracking IS
   *  the motion". The premise was FALSE for the two changes that matter:
   *  the day filter and the detail pane's mount are single layout passes
   *  (measured 2026-08-20: `offsetHeight` 783 → 417, then 417 → 806,
   *  between consecutive frames 8ms apart), so there was no animation to
   *  track and the snap was the entire transition — both of the owner's
   *  cuts. So the reframe now discriminates by DELTA: within the tracking
   *  thresholds it assigns (one frame of a real animated resize, or
   *  jitter); past them it absorbs — a genuine eased camera move whose
   *  destination is re-derived every frame, so it also tracks a resize
   *  that is still animating underneath it. */
  private reframe() {
    if (!this.shot) return;
    if (this.moving) {
      // The active tween re-derives its own destination; just keep the
      // rendered frame honest (floor + clamp) — this is what covers a take
      // PAUSED mid-tween while the board's own animation finishes.
      this.applyCam();
      return;
    }
    const to = this.camTargetFor(this.shot.target, this.shot.scale(), this.shot.align);
    if (
      Math.abs(to.scale - this.cam.scale) <= TRACK_EPS_SCALE &&
      Math.abs(to.x - this.cam.x) <= TRACK_EPS_PAN &&
      Math.abs(to.y - this.cam.y) <= TRACK_EPS_PAN
    ) {
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

  /** Where the camera must sit for `target`'s centre to hold frame-centre at
   *  `scale` — clamped so the stage never tears off an edge it covers.
   *  `align: "top"` seats the target's top edge just under the frame's
   *  instead: the shot for a pane taller than the frame, whose head — not
   *  its middle — is what the narration is pointing at. */
  private camTargetFor(target: Target | null, scale: number, align: "centre" | "top" = "centre") {
    const f = this.frame.getBoundingClientRect();
    const sw = this.stage.offsetWidth;
    const sh = this.stage.offsetHeight;
    let x: number;
    let y: number;
    const el = target ? resolve(target) : null;
    if (el) {
      const r = el.getBoundingClientRect();
      const sr = this.stage.getBoundingClientRect();
      // Unscale by the RENDERED transform — the one the rects were measured
      // under — not the authored one, which the cover floor may sit above.
      const cx = (r.left + r.width / 2 - sr.left) / this.rendered.scale;
      const ty = (r.top - sr.top) / this.rendered.scale;
      const cy = ty + r.height / 2 / this.rendered.scale;
      x = f.width / 2 - scale * cx;
      y = align === "top" ? CLOSEUP_HEADROOM - scale * ty : f.height / 2 - scale * cy;
    } else {
      x = (f.width - scale * sw) / 2;
      y = 0;
    }
    x = scale * sw > f.width ? clamp(x, f.width - scale * sw, 0) : (f.width - scale * sw) / 2;
    y = scale * sh > f.height ? clamp(y, f.height - scale * sh, 0) : Math.max(0, (f.height - scale * sh) / 2);
    return { scale, x, y };
  }

  async zoomTo(target: Target | null, scale: number, ms = 1400, align: "centre" | "top" = "centre") {
    await this.moveCam({ target, scale: () => scale, align, cover: false }, ms);
  }

  /** The rendered scale, for script-side resolvers that must unscale rects
   *  they measured under the live transform (`OnerStage.filteredCover`) —
   *  the same division every internal resolver already performs. */
  get renderedScale(): number {
    return this.rendered.scale;
  }

  /**
   * The anticipation shot: push in to the composition a coming collapse
   * will demand, BEFORE the press that causes it.
   *
   * This exists because the one stage change the camera cannot ride is the
   * day filter's: React removes the filtered rows in a single layout pass,
   * so there is no animation for the reframe to track and no tween that
   * could cross the change without either a cut or a void — at the collapse
   * instant, a full frame requires `frame.height / postHeight` of scale,
   * period. The only continuous answer is to be there already: the camera
   * tightens onto the stage's head (null target — top-anchored, and the
   * head is exactly what survives a worklist collapse: bands, filter, the
   * surviving rows) at the caller's predicted post-collapse cover, while
   * the pointer makes its own travel to the control. Then the press lands
   * inside a frame every pixel of which survives it: the rows file out as
   * product behaviour under a camera that does not move at all.
   *
   * Cover-armed, so a prediction that lands slightly UNDER the true bound
   * is caught by the floor as a small rise instead of a void — but the
   * caller's contract is to underestimate the filtered stage's height, so
   * the shot over-covers and the punch that follows relaxes onto the
   * survivors as a pull-back reveal. See `filteredCover` in OnerStage for
   * the prediction's terms.
   */
  async brace(scale: () => number, ms = 1100) {
    await this.moveCam({ target: null, scale, align: "centre", cover: false }, ms);
    // Armed on ARRIVAL, not at the first frame of the move: on tall frames
    // the establishing shot letterboxes (fit capped at 1) and sits under
    // the live cover, so arming at the start raised the rendered frame in
    // one step — measured 1.000 → 1.206 at 1024x1120, a cut of this file's
    // own making. By the time the push has landed, the authored scale is at
    // the predicted cover and arming is a no-op; the floor exists from here
    // purely to catch the collapse the press is about to cause.
    this.covering = true;
  }

  /**
   * The one camera move. The destination is re-derived EVERY FRAME — target
   * rect, resolved scale, clamps — the same rule the pointer already lives
   * by, because a shot authored against the stage as it was at call time is
   * a stale composition the moment the board moves (the punch-time cover
   * bound was exactly that bug). The tween still eases from where the
   * AUTHORED camera was, and lands exactly on the live destination at t=1.
   */
  private async moveCam(shot: Shot, ms: number) {
    const token = ++this.motion;
    this.shot = shot;
    this.covering = shot.cover;
    this.moving = true;
    try {
      const from = { ...this.cam };
      await this.tween(ms, (t) => {
        // Superseded — a newer move owns the camera; drain silently.
        if (this.motion !== token) return;
        const to = this.camTargetFor(shot.target, shot.scale(), shot.align);
        this.cam = {
          scale: from.scale + (to.scale - from.scale) * t,
          x: from.x + (to.x - from.x) * t,
          y: from.y + (to.y - from.y) * t,
        };
        this.applyCam();
      });
    } finally {
      if (this.motion === token) this.moving = false;
    }
  }

  /**
   * The close-up: travel to `target` at a scale COMPUTED FROM THE TARGET, so
   * the thing the narration names is what fills the frame.
   *
   * This replaces the lab's authored `zoomTo(target, 1)` calls, which were a
   * frame-size assumption wearing a constant's clothes: in the lab's 560px
   * plate the establishing fit sat near 0.5×, so absolute 1 WAS a push-in.
   * This frame is `100dvh - 11rem` tall, the establishing fit already rides
   * the 0.3 floor, and the board SHRINKS when the day filter lands — so the
   * same authored 1 produced the owner's production screenshot: the filtered
   * board at natural scale, centred in a frame it half fills, void above and
   * void below, "it scrolls the window down but no zoomed in". The authored
   * number was never the shot; the target's own size against the frame's is.
   *
   * Two bounds, and they do different jobs:
   *   · `PUNCH_MAX` caps the fit — a small control must not become a blur-up
   *     poster of itself. Above 1 is deliberate: the camera scales live DOM,
   *     which the browser re-rasterises at rest, so a close-up is crisp where
   *     upscaled video could not be. The push may soften WHILE moving; it
   *     lands sharp.
   *   · the COVER bound rides over it: if the whole stage at the fitted scale
   *     is shorter than the frame, the scale rises until the stage covers it
   *     (up to `COVER_MAX`) — the frame must not be able to show a void, and
   *     a tighter close-up is the honest way out where a letterbox is not.
   *
   * Both are LIVE. A first cut evaluated the cover bound once, at punch
   * time, and the void it existed to kill simply moved one beat earlier:
   * the board shrinks when the filter lands, the punch's arithmetic was
   * already frozen against the pre-shrink stage, and the frame sat 47%
   * empty for the ~1.4s the push-in took to catch up (measured 2026-08-20
   * at 1024x600 and 1024x768, production build). The resolver below and
   * the armed cover floor in `applyCam` are the fix: the bound holds
   * continuously across a stage resize, not only at punch time.
   */
  async punchTo(target: Target, ms = 1500, fill = 0.85, align: "centre" | "top" = "centre") {
    if (!resolve(target)) throw new TakeError("punch target vanished");
    // The fill and the cover bound are RESOLVERS now, not numbers: both are
    // re-evaluated on every frame of the move (and by `reframe` on every
    // stage resize after it), so a board that shrinks under the punch raises
    // the shot with it instead of leaving the frame to a stale arithmetic.
    // Falls back to the last resolved scale if the target vanishes mid-move —
    // the shot ends where it was pointed, and the script's own waits decide
    // what happens next.
    let last = Math.max(1, this.rendered.scale);
    const scale = () => {
      const el = resolve(target);
      if (!el) return last;
      const f = this.frame.getBoundingClientRect();
      const r = el.getBoundingClientRect();
      const rw = r.width / this.rendered.scale;
      const rh = r.height / this.rendered.scale;
      let s = clamp(Math.min((f.width * fill) / rw, (f.height * fill) / rh), 1, PUNCH_MAX);
      const cover = f.height / this.stage.offsetHeight;
      if (s < cover) s = Math.min(cover, COVER_MAX);
      last = s;
      return s;
    };
    await this.moveCam({ target, scale, align, cover: true }, ms);
  }

  /** The establishing shot: the whole mounted surface in one frame, centred,
   *  floored at 0.3× so a very tall dashboard stays an image, not a speck —
   *  and CAPPED AT 1×, deliberately, bands and all. At 1024x1120 the cap
   *  letterboxes the establishing shot (~81px top and bottom, ~63px at
   *  rest, measured 2026-08-20): the whole-surface shot cannot fill a frame
   *  taller than the board's own aspect without either cropping columns off
   *  a surface whose point is its wholeness, or blowing the product's 13px
   *  type past its own size for band-hygiene. Symmetric letterbox is the
   *  honest composition; the VOID this file guards against is the
   *  asymmetric, resize-born kind, and that is the cover floor's job
   *  (`applyCam`), which this shot stands down. */
  /** The establishing fit's scale — a field, not a method, so the
   *  constructor's seed and `fitAll` share one arithmetic by construction. */
  private fitScale = () => {
    const f = this.frame.getBoundingClientRect();
    return clamp(
      Math.min(f.width / this.stage.offsetWidth, f.height / this.stage.offsetHeight),
      0.3,
      1,
    );
  };

  async fitAll(ms = 1400) {
    await this.moveCam({ target: null, scale: this.fitScale, align: "centre", cover: false }, ms);
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
