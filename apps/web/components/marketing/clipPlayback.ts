/**
 * Driving one `<video>`, and keeping it alive when the element under it dies.
 *
 * A PLAIN MODULE, like `footage.ts` beside it, and for a second reason on top
 * of that one: this is the part of `ProductClip` that can be proven. It takes
 * a structural element rather than an `HTMLVideoElement`, so `tests/unit/`
 * drives THIS code with a fake element under `node --test` — the same
 * function the page runs, not a re-implementation of it. `metrics.mjs` learned
 * that the hard way ("a control that exercises a duplicate of the gate can
 * pass while the gate itself is broken"), and a recovery path is exactly the
 * kind of code that is never exercised in a healthy run.
 *
 * WHY IT EXISTS AT ALL — `<source>` IS NOT A FALLBACK.
 *
 * Every clip on the landing shipped as a `<video>` with two `<source>`
 * children, `.webm` then `.mp4`, which reads like a ladder and is not one.
 * The resource selection algorithm walks that list ONCE, before the first
 * byte of media data is decoded, and picks the first entry the browser says
 * it might play. Everything after selection — a decode that fails on frame
 * 300, a decoder the browser could not allocate — happens to the ELEMENT, and
 * the element has no list any more. It sets `error` and stops. It does not
 * try the mp4 twin sitting next to it in `public/footage/`.
 *
 * That is how two clips ended up frozen on the live page carrying
 * `error.code === 3` (MEDIA_ERR_DECODE), `readyState === 1`, `currentTime === 0`
 * and — the part that makes the control useless — `paused === false`. The
 * element claimed to be playing while its clock never moved, so the transport
 * read "Pause", and pressing it called `play()` on a corpse: on an element in
 * that state the promise never settles, so nothing at all happened.
 *
 * The bytes were not the problem. ffmpeg decodes all three webm files
 * cleanly, the failure moved between files from run to run and never touched
 * the smallest one, which points at VP9 decoder exhaustion under software
 * decode rather than a bad file. The missing thing was a way back, and a way
 * back is worth having whatever causes the fall.
 *
 * SO: ONE `src`, NOT TWO `<source>`s. The ladder is walked here, in script,
 * where it can be walked AGAIN. `canPlayType` picks the first encode the
 * element admits to before anything is fetched (`preload="none"` means that
 * costs nothing), and two things push it down a rung:
 *
 *   · the element's own `error` event, and
 *   · a STALL — `paused === false` with `currentTime` not moving for
 *     `STALL_MS`. This is the case `error` misses: the freeze above was
 *     reached with the element insisting it was running, and an element that
 *     insists it is running fires no event to say otherwise. Only a clock can
 *     see it, and the caller's animation frame is already reading that clock
 *     for the transport rule, so it is the same loop.
 *
 * A rung down is `src = the mp4` plus `load()`, and `load()` is also what
 * REPAIRS THE PICTURE: it returns the element to its empty state, which is
 * the state in which the poster is shown. A reader who was staring at a
 * frozen frame gets the poster back on the way to the retry.
 *
 * AND THE REWIND NO LONGER DESTROYS THE POSTER. `start()` used to set
 * `currentTime = 0` unconditionally — and on a cold element, where the seek
 * cannot be honoured yet, it waited for `loadedmetadata` and did it then.
 * That seek forces frame 0 to decode and REPLACES the poster with it, so a
 * play that was then refused left the reader looking at the loop's own
 * "before": for `rules-read-the-body` that is an empty body under OTHER 50%
 * and a line about deferring to the neural layers, which is the product not
 * having done the thing — precisely the frame `POSTER_AT` exists to keep off
 * the page. The rewind is only meaningful on an element that has actually
 * moved, so it is guarded on that, and the cold path does nothing at all.
 *
 * THE PLAY/PAUSE RACE. The caller runs two IntersectionObservers, and at
 * 1024 — where the pinned rails resolve a viewport-dependent sticky offset,
 * so band crossings flap — a `pause()` lands on a `play()` that has not
 * settled and the console fills with `AbortError: The play() request was
 * interrupted by a call to pause()`. It self-heals, and it is not the freeze,
 * but it is real and it is width-specific: at 1440 every play resolved. A
 * pause therefore WAITS for the pending play, and a generation counter drops
 * it if a newer play has been issued in the meantime — awaiting alone would
 * only invert the race, landing a stale pause on a fresh play.
 */

/**
 * A `<video>`, reduced to what playback and recovery touch.
 *
 * Structural rather than `HTMLVideoElement` so the unit suite can hand this a
 * fake — `node --test` has no DOM. An `HTMLVideoElement` satisfies it.
 */
export type ClipElement = {
  readonly error: { readonly code: number } | null;
  readonly paused: boolean;
  readonly ended: boolean;
  /** `HTMLMediaElement.readyState`. Only the watchdog reads it, and only to
   *  tell a clip that is STUCK from one that has not been given anything to
   *  play yet. */
  readonly readyState: number;
  currentTime: number;
  muted: boolean;
  src: string;
  canPlayType(type: string): string;
  load(): void;
  play(): Promise<void>;
  pause(): void;
  addEventListener(type: string, listener: () => void): void;
  removeEventListener(type: string, listener: () => void): void;
};

/** One encode of one clip: what to fetch, and what to ask `canPlayType`. */
export type ClipSource = { readonly src: string; readonly type: string };

/**
 * What the caller renders from.
 *
 * Two booleans, not one, because the freeze this module exists for is exactly
 * the case where they disagree.
 */
export type ClipState = {
  /**
   * Told to run, and not yet told to stop. Drives the stall watchdog, which
   * has to keep looking at an element whose `play()` NEVER SETTLED — if the
   * watchdog ran on `playing` it would be switched off in the one state it is
   * needed in.
   */
  running: boolean;
  /**
   * `play()` came back and said yes. Drives the label, because it is the
   * element's own answer rather than our intent.
   */
  playing: boolean;
};

/**
 * How long a clip may claim to be running with its clock standing still,
 * once it has a frame to show.
 *
 * Two seconds, not one: the failure this catches is permanent, so waiting
 * costs it nothing, and a hair trigger costs a poster flash and a re-fetch on
 * a connection that was only slow.
 */
export const STALL_MS = 2000;

/**
 * `HAVE_CURRENT_DATA` — there is a frame for the current position.
 *
 * The stall watchdog is gated on this and the gate is load-bearing.
 * `play()` flips `paused` to false SYNCHRONOUSLY, before a byte has arrived,
 * and these clips ship `preload="none"`, so a first play on a slow connection
 * looks exactly like the freeze — running, clock at zero — for as long as the
 * fetch takes. Ungated, the watchdog would drop such a visitor to the mp4 at
 * two seconds, flash the poster, re-fetch a LARGER file and then give up: a
 * defect manufactured on clips that were fine. Below this readyState nothing
 * has decoded, so nothing can be stuck; above it, a clock that does not move
 * is a clip that is not playing.
 *
 * It costs no coverage of the measured freeze, because that one carried
 * `error.code === 3` and `sample()` checks the error FIRST, before it looks
 * at readyState — the live signature was `readyState 1` with an error set,
 * and it is the error that names it.
 */
const HAVE_CURRENT_DATA = 2;

export type ClipPlayback = {
  /** Wire up an element. Returns the detach. */
  attach(video: ClipElement): () => void;
  /** Start, or restart from the top. Safe on a dead element — it recovers. */
  start(): void;
  /** Stop, without racing a play that has not settled. */
  stop(): void;
  /** What the transport control does: recover first if there is nothing alive
   *  to play, otherwise toggle. */
  toggle(): void;
  /** The stall watchdog's only clock. Call once per animation frame while
   *  `running`; `now` is monotonic milliseconds. */
  sample(now: number): void;
  /** Which encode is on the element — index into `sources`. */
  sourceIndex(): number;
};

export function createClipPlayback(
  sources: readonly ClipSource[],
  onChange: (state: ClipState) => void,
): ClipPlayback {
  let video: ClipElement | null = null;
  let index = 0;
  /** Bumped by every start and every stop, so a settled promise can tell
   *  whether the intent that issued it is still the current one. */
  let generation = 0;
  /** The play whose promise has not settled, or null. */
  let pending: Promise<void> | null = null;
  let running = false;
  let playing = false;
  /** No rung left: the ladder was walked to the end and the last one failed
   *  too. The control can still ask for a fresh walk. */
  let exhausted = false;
  let lastTime = -1;
  let lastAdvance = 0;

  const emit = () => onChange({ running, playing });

  const set = (nextRunning: boolean, nextPlaying: boolean) => {
    if (running === nextRunning && playing === nextPlaying) return;
    running = nextRunning;
    playing = nextPlaying;
    emit();
  };

  /** The first encode at or after `from` that the element does not refuse
   *  outright. `canPlayType` answers "", "maybe" or "probably"; only "" is a
   *  refusal, and a "maybe" that turns out to be a lie is what the error and
   *  stall paths are for. */
  const rungAt = (v: ClipElement, from: number): number | null => {
    for (let i = from; i < sources.length; i += 1) {
      if (v.canPlayType(sources[i].type) !== "") return i;
    }
    return null;
  };

  /** Put an encode on the element. `load()` resets it to the empty state,
   *  which is the state that shows the poster. */
  const mount = (v: ClipElement, i: number) => {
    index = i;
    exhausted = false;
    lastTime = -1;
    lastAdvance = 0;
    v.src = sources[i].src;
    v.load();
  };

  /** A rung down, then try again — or, if there is no rung left, give the
   *  reader the poster and the control back rather than a frozen frame. */
  const recover = () => {
    const v = video;
    if (!v) return;
    // Orphan whatever was in flight: its promise, if it ever settles, is
    // answering about an element state that no longer exists.
    generation += 1;
    pending = null;

    const next = rungAt(v, index + 1);
    if (next === null) {
      mount(v, index);
      exhausted = true;
      set(false, false);
      return;
    }
    mount(v, next);
    start();
  };

  const start = () => {
    const v = video;
    if (!v) return;
    // `play()` on an element that has already errored never settles, so this
    // has to come first — it is what made the transport control useless.
    if (v.error || exhausted) {
      recover();
      return;
    }
    v.muted = true; // belt and braces: an audible clip is refused autoplay
    // Only an element that has moved needs rewinding, and only that guard
    // keeps the poster alive on a play that is about to be refused.
    if (v.currentTime > 0) v.currentTime = 0;

    const gen = (generation += 1);
    lastTime = -1;
    lastAdvance = 0;
    set(true, playing);

    const settled = v.play().then(
      () => {
        if (gen === generation) set(true, true);
      },
      // Refused: by the autoplay policy, by a backgrounded tab, or because
      // the reader asked for reduced motion. Nothing decoded, so the poster
      // is still the picture, and the control is still the offer. `running`
      // goes false too — a refused element is not one the watchdog should
      // keep waking for.
      () => {
        if (gen === generation) set(false, false);
      },
    );
    pending = settled;
    void settled.then(() => {
      if (pending === settled) pending = null;
    });
  };

  const stop = () => {
    const gen = (generation += 1);
    const v = video;
    if (!v) {
      set(false, false);
      return;
    }
    if (!pending) {
      v.pause();
      set(false, false);
      return;
    }
    // The AbortError. Wait for the play to settle before pausing it — and
    // then drop this pause if a newer start has been issued since, because
    // awaiting alone would only turn the race around.
    set(false, playing);
    void pending.then(() => {
      if (generation !== gen) return;
      v.pause();
      set(false, false);
    });
  };

  const toggle = () => {
    const v = video;
    if (!v) return;
    // A press is a fresh intent, so an exhausted ladder is walked again FROM
    // THE TOP rather than nudged one more time at the rung that just failed.
    // The failure this recovers from migrated between files between runs and
    // is not a property of any one encode, so the rung that died a minute ago
    // is as good a bet as any — and better than refusing the reader outright.
    if (exhausted) {
      mount(v, rungAt(v, 0) ?? 0);
      start();
      return;
    }
    if (v.error) {
      recover();
      return;
    }
    if (running) stop();
    else start();
  };

  const sample = (now: number) => {
    const v = video;
    if (!v || !running) return;
    // THE ERROR COMES FIRST, and not for tidiness. The freeze measured on the
    // live page was `error.code === 3` at `readyState 1` — a decode that died
    // before a single frame was available — so both of the checks below would
    // wave it through, and it is not guaranteed that the `error` EVENT was
    // ever seen (an element can be errored before this is attached, and a
    // missed event is unrecoverable by definition). Reading the property each
    // frame costs nothing and cannot false-positive: an error is an error.
    if (v.error) {
      recover();
      return;
    }
    // A paused or ended element is not stalled, it is stopped.
    if (v.paused || v.ended) {
      lastTime = -1;
      return;
    }
    // Nothing has decoded yet, so nothing is stuck — it is loading. See
    // `HAVE_CURRENT_DATA`.
    if (v.readyState < HAVE_CURRENT_DATA) {
      lastTime = -1;
      return;
    }
    if (v.currentTime !== lastTime) {
      lastTime = v.currentTime;
      lastAdvance = now;
      return;
    }
    if (now - lastAdvance >= STALL_MS) recover();
  };

  const attach = (v: ClipElement) => {
    video = v;
    const first = rungAt(v, 0) ?? 0;
    // Only touch `src` if the choice differs from what was rendered: the
    // markup ships the webm, so the common path costs no `load()` at all.
    // Compared by suffix because a DOM element resolves `src` to an absolute
    // URL, and the ladder is written in page-relative paths.
    if (v.src.endsWith(sources[first].src)) index = first;
    else mount(v, first);

    const onError = () => recover();
    v.addEventListener("error", onError);
    return () => {
      v.removeEventListener("error", onError);
      video = null;
      pending = null;
      generation += 1;
    };
  };

  return { attach, start, stop, toggle, sample, sourceIndex: () => index };
}
