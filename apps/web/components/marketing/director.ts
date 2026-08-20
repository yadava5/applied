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
 *  type still legible; past it a void is the lesser evil. */
const COVER_MAX = 2.75;

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
        res(this.paused ? 0 : performance.now() - prev);
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

export class Director extends TakeClock {
  private cam = { scale: 1, x: 0, y: 0 };
  private cur = { x: 0, y: 0 };

  constructor(
    private frame: HTMLElement,
    private camera: HTMLElement,
    private stage: HTMLElement,
    private cursor: HTMLElement,
    onCaption: (line: string) => void,
  ) {
    super(onCaption);
  }

  // ---- finding things on the stage ----------------------------------------

  query(selector: string): HTMLElement | null {
    return this.stage.querySelector<HTMLElement>(selector);
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
    this.camera.style.transform = `translate3d(${this.cam.x}px, ${this.cam.y}px, 0) scale(${this.cam.scale})`;
    // The camera's position, written where a test can read it. The take's own
    // suite is green when the LOGIC runs — the pointer really pressed the day
    // bar, the board really narrowed — and none of it could see that the shot
    // was not a shot: production played a whole take with the camera parked
    // at scale 1 and nobody's gate went red. A shot is assertable now:
    // `data-cam-scale` on the frame is the truth of where the camera is, per
    // frame, and the e2e can require it to actually arrive somewhere.
    this.frame.dataset.camScale = this.cam.scale.toFixed(3);
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
      const cx = (r.left + r.width / 2 - sr.left) / this.cam.scale;
      const ty = (r.top - sr.top) / this.cam.scale;
      const cy = ty + r.height / 2 / this.cam.scale;
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
    const from = { ...this.cam };
    const to = this.camTargetFor(target, scale, align);
    await this.tween(ms, (t) => {
      this.cam.scale = from.scale + (to.scale - from.scale) * t;
      this.cam.x = from.x + (to.x - from.x) * t;
      this.cam.y = from.y + (to.y - from.y) * t;
      this.applyCam();
    });
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
   */
  async punchTo(target: Target, ms = 1500, fill = 0.85, align: "centre" | "top" = "centre") {
    const el = resolve(target);
    if (!el) throw new TakeError("punch target vanished");
    const f = this.frame.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    const rw = r.width / this.cam.scale;
    const rh = r.height / this.cam.scale;
    let s = clamp(Math.min((f.width * fill) / rw, (f.height * fill) / rh), 1, PUNCH_MAX);
    const cover = f.height / this.stage.offsetHeight;
    if (s < cover) s = Math.min(cover, COVER_MAX);
    await this.zoomTo(target, s, ms, align);
  }

  /** The establishing shot: the whole mounted surface in one frame, centred,
   *  floored at 0.3× so a very tall dashboard stays an image, not a speck. */
  async fitAll(ms = 1400) {
    const f = this.frame.getBoundingClientRect();
    const s = clamp(
      Math.min(f.width / this.stage.offsetWidth, f.height / this.stage.offsetHeight),
      0.3,
      1,
    );
    await this.zoomTo(null, s, ms);
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
