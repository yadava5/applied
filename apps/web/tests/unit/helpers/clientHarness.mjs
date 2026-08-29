/**
 * Run a leaf Client Component's `useState` + `useEffect` cycle under plain
 * `node --test`, so a client delivery path can be ASSERTED BY EXECUTION.
 *
 * WHY THIS EXISTS. `renderTsx` renders with `react-dom/server`, which never
 * runs an effect — so a component whose entire job happens after hydration
 * (fetch, then correct the number on screen) had no executable coverage at all,
 * and was gated by `source.includes(...)` scans instead. A scan cannot see an
 * argument swapped for another of the same type, which is this repo's recorded
 * recurring defect: `summaryWeekCorrection(readerToday, servedWeekStart)` ->
 * `(servedWeekStart, servedWeekStart)` restores #518 in full and leaves every
 * scanned substring in place.
 *
 * WHAT IT IS. A hook dispatcher, roughly 60 lines, substituted for `react`'s
 * `useState`/`useEffect` in the ENTRY module only (`renderTsx`'s `stubs`). The
 * component function is the real one and its body really runs; the element it
 * returns is built by real React and rendered by real `react-dom/server`.
 *
 * WHAT IT IS NOT, SAID PLAINLY. It is not React. There is no fibre tree, no
 * batching, no concurrent rendering, no children — a parent's effects and a
 * child's do not interleave the way React orders them, because this only ever
 * calls ONE component function. Anything whose correctness depends on React's
 * scheduling, or on a DOM, belongs to Playwright and not here. The rule that
 * keeps this from growing into a second, worse renderer: it may drive a leaf
 * client component that uses `useState` and `useEffect`, and nothing else.
 *
 * HOW A PASS WORKS. Call the component, run whichever effects have changed
 * deps, drain the microtask queue (the effect under test is an async IIFE
 * around `fetch`), and if a `setState` landed, render again. Repeat until the
 * output stops moving — which is what "settled" means here, and it throws
 * rather than looping if it never does.
 *
 * AND THE HARNESS ITSELF CANNOT PASS DEAD. A harness that never ran an effect
 * would make a "the number is corrected" test red, which announces itself, but
 * it would also make a "no request is made outside the window" test green for
 * the wrong reason. Tests using this must therefore assert the call count on
 * BOTH sides — exactly once when it should fire, exactly zero when it should
 * not. `settle()` returns the number of render passes so a test can also state
 * that a second pass happened at all.
 */
import { renderToStaticMarkup } from "react-dom/server";

/** Same comparison React uses for a dependency array. */
function sameDeps(a, b) {
  if (a === undefined || b === undefined) return false;
  if (a.length !== b.length) return false;
  return a.every((value, i) => Object.is(value, b[i]));
}

/**
 * Let every already-queued promise callback run.
 *
 * `await Promise.resolve()` alone advances one microtask tick, and the effect
 * under test is an async function that awaits `fetch` and then `res.json()` —
 * several ticks deep. A macrotask turn (`setImmediate`) drains the whole
 * microtask queue that preceded it, and a handful of them covers any realistic
 * chain without pinning a number of awaits the component is free to change.
 */
async function drain(turns = 5) {
  for (let i = 0; i < turns; i++) await new Promise((resolve) => setImmediate(resolve));
}

/**
 * A dispatcher plus a driver for one component function.
 *
 * ```js
 * const harness = createClientHarness();
 * const { BoardSubtitle } = await importTsx("components/dashboard/BoardSubtitle.tsx", {
 *   stubs: { react: stubModule(harness.reactStub) },
 * });
 * const { text, passes } = await harness.settle(BoardSubtitle, props);
 * ```
 */
export function createClientHarness({ maxPasses = 20 } = {}) {
  const states = [];
  const effectSlots = [];
  let stateCursor = 0;
  let effectCursor = 0;
  let pending = [];
  let dirty = false;

  function useState(initial) {
    const slot = stateCursor++;
    if (slot >= states.length) {
      states.push(typeof initial === "function" ? initial() : initial);
    }
    const setState = (next) => {
      const value = typeof next === "function" ? next(states[slot]) : next;
      if (Object.is(value, states[slot])) return;
      states[slot] = value;
      dirty = true;
    };
    return [states[slot], setState];
  }

  function useEffect(effect, deps) {
    const slot = effectCursor++;
    const previous = effectSlots[slot];
    if (previous !== undefined && sameDeps(previous.deps, deps)) return;
    pending.push({ slot, effect, deps, previous });
  }

  async function settle(Component, props) {
    let element = null;
    for (let pass = 1; pass <= maxPasses; pass++) {
      stateCursor = 0;
      effectCursor = 0;
      pending = [];
      dirty = false;

      element = Component(props);

      for (const { slot, effect, deps, previous } of pending) {
        if (typeof previous?.cleanup === "function") previous.cleanup();
        const cleanup = effect();
        effectSlots[slot] = { deps, cleanup: typeof cleanup === "function" ? cleanup : null };
      }

      await drain();
      if (!dirty) return { element, text: renderToStaticMarkup(element), passes: pass };
    }
    throw new Error(
      `clientHarness: the component never settled in ${maxPasses} passes — a setState is ` +
        "running on every render, which is a real defect and not a harness limit.",
    );
  }

  /** Run every registered cleanup, as an unmount would. */
  function unmount() {
    for (const slot of effectSlots) if (typeof slot?.cleanup === "function") slot.cleanup();
  }

  return { reactStub: { useState, useEffect }, settle, unmount };
}

/**
 * A `fetch` that answers from a table and records every call.
 *
 * `routes` maps a URL (exactly as the component builds it) to the JSON body to
 * answer with. A URL that is not in the table answers 404, which is a real
 * behaviour worth being able to assert rather than a crash.
 */
export function recordingFetch(routes) {
  const calls = [];
  const impl = async (url, init) => {
    calls.push({ url: String(url), init });
    const body = routes[String(url)];
    if (body === undefined) return new Response("{}", { status: 404 });
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  return { calls, impl };
}
