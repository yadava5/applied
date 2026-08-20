/**
 * The landing recordings' recovery path, driven directly.
 *
 * WHY THIS SUITE EXISTS AND WHY IT LOOKS LIKE THIS. Two clips shipped to the
 * live page frozen on a frame, with a transport control that could not undo
 * it, and the reason was structural: `<video>`'s `<source>` list is walked
 * once at SELECTION time, so an element that dies after selection has no
 * fallback left and `play()` on it never settles. The fix is a script-side
 * ladder (`components/marketing/clipPlayback.ts`), and a recovery path is by
 * definition code that a healthy run never touches — so it gets no coverage
 * from anything else on the page, and it is exactly the kind of code that can
 * rot to a no-op without a single gate noticing.
 *
 * IT DRIVES THE REAL MODULE, not a description of it. `metrics.mjs` records
 * what the alternative buys: its negative control first shipped with its own
 * copy of the arithmetic, "which proves nothing — a control that exercises a
 * duplicate of the gate can pass while the gate itself is broken". So
 * `createClipPlayback` is imported and run here; only the `<video>` is a
 * stand-in, because `node --test` has no DOM and because a real element would
 * decide for itself when to settle a play, which is the one thing these cases
 * need to hold still.
 *
 * The stand-in keeps an ORDERED LOG of what was done to it. Several of these
 * defects are ordering defects — a `play()` before the element was reloaded,
 * a `pause()` before the play it interrupts has settled — and a log is the
 * only assertion that can see them; counters cannot.
 */
import assert from "node:assert/strict";
import test from "node:test";

import { STALL_MS, createClipPlayback } from "../../components/marketing/clipPlayback.ts";

const SOURCES = [
  { src: "/footage/x.webm", type: 'video/webm; codecs="vp9"' },
  { src: "/footage/x.mp4", type: 'video/mp4; codecs="avc1.42E01E"' },
];

/**
 * A `<video>` that does only what the module touches, and says so out loud.
 *
 * `play()` hands back a promise this test settles by hand: a browser decides
 * that on its own schedule, and both the AbortError race and the corpse (a
 * promise that never settles at all) live entirely in that schedule.
 */
function makeVideo({ refuses = () => false, src = "/footage/x.webm" } = {}) {
  const ops = [];
  const listeners = new Map();
  /** Every play still in flight, oldest first. A queue rather than a single
   *  slot because the race this suite exists for is TWO plays overlapping: a
   *  fake that can only hold the newest silently drops the older promise, and
   *  a promise that never settles cannot land a stale pause on anything. */
  const inFlight = [];
  let href = src;
  /** The playback clock. Kept out here because `load()` resets it the way a
   *  real element does — internally, without that counting as a seek. */
  let clock = 0;

  const video = {
    error: null,
    paused: true,
    ended: false,
    /** `HAVE_NOTHING` until something is played into it, the way a
     *  `preload="none"` element starts. */
    readyState: 0,
    muted: false,
    get src() {
      return `https://applied.test${href}`;
    },
    set src(next) {
      href = next;
      ops.push(`src=${next}`);
    },
    canPlayType(type) {
      return refuses(type) ? "" : "probably";
    },
    load() {
      ops.push("load");
      this.error = null;
      this.paused = true;
      this.readyState = 0;
      clock = 0;
    },
    play() {
      ops.push("play");
      return new Promise((resolve, reject) => {
        inFlight.push({ resolve, reject });
      });
    },
    pause() {
      ops.push("pause");
      this.paused = true;
    },
    addEventListener(type, fn) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(fn);
    },
    removeEventListener(type, fn) {
      listeners.set(type, (listeners.get(type) ?? []).filter((f) => f !== fn));
    },
  };

  // `currentTime` is watched rather than merely stored: an unguarded rewind is
  // what destroyed the poster, and only a write can show that.
  Object.defineProperty(video, "currentTime", {
    get: () => clock,
    set: (next) => {
      clock = next;
      ops.push(`seek=${next}`);
    },
    configurable: true,
  });
  /** Move the clock the way playback does — without logging a seek. */
  const advance = (to) => {
    clock = to;
  };

  return {
    video,
    ops,
    /**
     * The browser said yes to the OLDEST outstanding play: the element is now
     * running.
     *
     * `readyState` defaults to HAVE_ENOUGH_DATA because that is the ordinary
     * case, but it is a PARAMETER, because the interesting one is not: a
     * `play()` resolves before any media data arrives, so a cold element on a
     * slow connection sits at `paused === false` with `readyState 1` and a
     * clock that has never moved — indistinguishable from the freeze except
     * by this number.
     */
    accept(readyState = 4) {
      video.paused = false;
      video.readyState = readyState;
      inFlight.shift().resolve();
      return Promise.resolve();
    },
    /** The browser said no — autoplay policy, backgrounded tab, reduced motion. */
    refuse() {
      inFlight.shift().reject(new Error("NotAllowedError"));
      return Promise.resolve();
    },
    /** How many plays the element has not answered yet. */
    inFlight: () => inFlight.length,
    advance,
    /** The decode failed under the element, the way a live one reports it. */
    breakDecode() {
      video.error = { code: 3 }; // MEDIA_ERR_DECODE
      for (const fn of listeners.get("error") ?? []) fn();
    },
  };
}

/** Let every already-settled promise chain run. Two turns, because the module
 *  chains a `.then` onto the play's own handlers. */
const drain = async () => {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
};

function harness(options) {
  const fake = makeVideo(options);
  const states = [];
  const player = createClipPlayback(SOURCES, (state) => states.push(state));
  const detach = player.attach(fake.video);
  return { ...fake, player, states, detach, last: () => states.at(-1) };
}

test("the ladder is walked before a byte is fetched, and skips an encode the element refuses", () => {
  const plain = harness();
  assert.equal(plain.player.sourceIndex(), 0, "a browser that takes webm should be left on the webm");
  assert.deepEqual(plain.ops, [], "nothing was refused, so nothing needed reloading");

  const noVp9 = harness({ refuses: (type) => type.includes("webm") });
  assert.equal(noVp9.player.sourceIndex(), 1, "an element that refuses webm was left on it anyway");
  assert.deepEqual(
    noVp9.ops,
    ["src=/footage/x.mp4", "load"],
    "the mp4 was chosen but never actually mounted",
  );
});

test("a decode failure mid-playback drops to the mp4 and retries — what <source> cannot do", async () => {
  const h = harness();
  h.player.start();
  await h.accept();
  h.advance(1.2);
  h.ops.length = 0;

  h.breakDecode();

  assert.deepEqual(
    h.ops,
    ["src=/footage/x.mp4", "load", "play"],
    "a dead element was not carried down to the mp4 twin and restarted",
  );
  assert.equal(h.player.sourceIndex(), 1);
});

test("a SILENT stall — frames available, insisting it is playing, clock frozen — falls back too", async () => {
  const h = harness();
  h.player.start();
  await h.accept();
  // The case no event and no property can name: data is there (`readyState 4`)
  // and the element says it is running, but the clock does not move and
  // nothing is ever reported. A clock is the only witness.
  assert.equal(h.video.paused, false);
  assert.equal(h.video.error, null);
  h.ops.length = 0;

  h.player.sample(0);
  h.player.sample(STALL_MS - 1);
  assert.deepEqual(h.ops, [], `recovered after ${STALL_MS - 1}ms — that is a buffering clip, not a dead one`);

  h.player.sample(STALL_MS);
  assert.deepEqual(
    h.ops,
    ["src=/footage/x.mp4", "load", "play"],
    "a clip frozen for the whole stall window was left frozen",
  );
});

test("a clip that is merely slow is not dragged down the ladder", async () => {
  const h = harness();
  h.player.start();
  await h.accept();
  h.ops.length = 0;

  h.player.sample(0);
  h.player.sample(1500);
  h.advance(0.4); // the buffer arrived
  h.player.sample(3000);
  h.player.sample(4000);

  assert.deepEqual(h.ops, [], "a clip whose clock moved was treated as stalled");
  assert.equal(h.player.sourceIndex(), 0);
});

test("a clip that has not been given a frame yet is left to load, however long it takes", async () => {
  const h = harness();
  h.player.start();
  // `play()` resolved and `paused` is already false — that happens before a
  // byte of media arrives. Nothing has decoded, so the clock cannot move.
  await h.accept(1); // HAVE_METADATA
  h.ops.length = 0;

  h.player.sample(0);
  h.player.sample(STALL_MS);
  h.player.sample(STALL_MS * 2);
  h.player.sample(STALL_MS * 4);

  assert.deepEqual(
    h.ops,
    [],
    "a buffering clip was dropped to the mp4 and re-fetched — a poster flash, a LARGER file and eventually a dead transport, manufactured on a clip that was only slow",
  );
  assert.equal(h.player.sourceIndex(), 0);

  // And the moment a frame lands, the watchdog is watching again.
  h.video.readyState = 4;
  h.player.sample(STALL_MS * 5);
  h.player.sample(STALL_MS * 7);
  assert.deepEqual(h.ops, ["src=/footage/x.mp4", "load", "play"], "the watchdog never came back on");
});

test("the live freeze signature — errored at readyState 1 — is caught without an error event", async () => {
  const h = harness();
  h.player.start();
  await h.accept(1);
  // Exactly what was measured on the page: error.code 3, readyState 1,
  // currentTime 0, paused false. The `error` event is deliberately NOT fired
  // — an element can already be errored when this attaches, and a missed
  // event is unrecoverable by definition, so the watchdog has to read the
  // property rather than wait to be told.
  h.video.error = { code: 3 };
  h.ops.length = 0;

  h.player.sample(0);

  assert.deepEqual(
    h.ops,
    ["src=/footage/x.mp4", "load", "play"],
    "the exact state two clips shipped frozen in was waved through — the readyState gate must not sit in front of the error check",
  );
});

test("a refused play leaves the poster alone — no rewind, no decode", async () => {
  const h = harness();
  h.player.start();
  await h.refuse();
  await drain();

  assert.deepEqual(
    h.ops,
    ["play"],
    "a cold element was seeked. That seek decodes frame 0 and REPLACES the poster, which for rules-read-the-body is an empty body under OTHER 50% — the clip's own 'before'",
  );
  assert.deepEqual(
    h.last(),
    { running: false, playing: false },
    "a refused clip still reported itself running — the watchdog would spin on it and the label would lie",
  );
});

test("re-entry does rewind, because an element that has moved has somewhere to come back from", async () => {
  const h = harness();
  h.player.start();
  await h.accept();
  h.advance(3.4);
  h.player.stop();
  await drain();
  h.ops.length = 0;

  h.player.start();
  assert.deepEqual(h.ops, ["seek=0", "play"], "a returning reader was dropped into the middle of the loop");
});

test("the transport recovers a dead element instead of calling play() on a corpse", async () => {
  const h = harness();
  h.player.start();
  await h.accept();
  h.video.error = { code: 3 }; // errored without the event being seen — a hard reload, a lost decoder
  h.ops.length = 0;

  h.player.toggle();

  assert.deepEqual(
    h.ops,
    ["src=/footage/x.mp4", "load", "play"],
    "the control called play() on an errored element. That promise never settles, which is why pressing PLAY did nothing",
  );
});

test("re-entering the band on a dead element recovers it rather than playing it", async () => {
  const h = harness();
  h.player.start();
  await h.accept();
  // The element died while the reader was elsewhere — no listener saw it,
  // because the observer had already scrolled the clip out of band. The
  // observer's next crossing IN calls start(), not toggle(), so the corpse
  // check has to live there too or the rail silently re-plays a dead element
  // every time the reader scrolls back.
  h.player.stop();
  await drain();
  h.video.error = { code: 3 };
  h.ops.length = 0;

  h.player.start();

  assert.deepEqual(
    h.ops,
    ["src=/footage/x.mp4", "load", "play"],
    "the band observer called play() on an errored element — a promise that never settles, and a clip that never moves again",
  );
});

test("a pause never interrupts a play that has not settled — the AbortError at 1024", async () => {
  const h = harness();
  h.player.start();
  h.ops.length = 0;

  h.player.stop(); // the band flapped: a crossing out, before the play came back
  assert.deepEqual(h.ops, [], "pause() was issued against an in-flight play — that is the AbortError verbatim");
  assert.equal(h.last().running, false, "the intent should drop immediately even though the pause waits");

  await h.accept();
  await drain();
  assert.deepEqual(h.ops, ["pause"], "the deferred pause never landed, so the clip ran on out of band");
});

test("a deferred pause is dropped when a newer play has overtaken it", async () => {
  const h = harness();
  h.player.start();
  h.player.stop(); // out of band
  h.player.start(); // and back in, before the first play settled
  h.ops.length = 0;
  assert.equal(h.inFlight(), 2, "the band flapped, so two plays are outstanding — that is the whole case");

  // The FIRST play answers, and the pause waiting on it is now stale: simply
  // awaiting the pending play would land it on the second one and stop a clip
  // that is back in band. Inverting the race is not fixing it.
  await h.accept();
  await drain();
  assert.deepEqual(h.ops, [], "a stale pause landed on a fresh play — the race turned around rather than fixed");

  await h.accept();
  await drain();
  assert.deepEqual(h.ops, [], "the second play was interrupted after it had already been answered");
  assert.deepEqual(h.last(), { running: true, playing: true });
});

test("with no rung left the reader gets the poster and the offer back, not a frozen frame", async () => {
  const h = harness();
  h.player.start();
  await h.accept();
  h.breakDecode(); // webm -> mp4
  await h.accept();
  h.ops.length = 0;

  h.breakDecode(); // and the mp4 dies too

  assert.deepEqual(
    h.ops,
    ["src=/footage/x.mp4", "load"],
    "the last rung was not reloaded — load() is what returns the element to the empty state where the poster shows",
  );
  assert.deepEqual(h.last(), { running: false, playing: false }, "the transport was left reading Pause over a dead clip");

  // And the control can still ask for a fresh walk from the top.
  h.ops.length = 0;
  h.player.toggle();
  assert.deepEqual(h.ops, ["src=/footage/x.webm", "load", "play"], "a second press could not restart the ladder");
});
