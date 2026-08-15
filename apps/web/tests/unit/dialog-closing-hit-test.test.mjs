/**
 * The dialog scrim must stop hit-testing the moment a close is initiated.
 *
 * THE INCIDENT (#263). The overlay is `fixed inset-0 z-[100]`, so while it is
 * mounted it covers the viewport and catches every click. `AnimatePresence`
 * keeps it mounted for the whole exit (~150 ms), so a click issued in that
 * window landed on the scrim and was swallowed — the control the user aimed at
 * never received it. It surfaced magnified during a signed-in browser pass in
 * a BACKGROUNDED tab, where `requestAnimationFrame` is frozen and the exit
 * therefore never advanced at all: three clicks were eaten before the cause was
 * understood. That part is Chrome working as designed and is not what this
 * guards; what it guards is that a closing overlay stops intercepting input.
 *
 * WHY THESE ASSERTIONS AND NOT A CLICK. A closing dialog is not a state this
 * runner can reach. `AnimatePresence` only produces an exiting child on a real
 * animation frame, and there is no DOM and no component-test framework here
 * (see `helpers/renderTsx.mjs` for the deliberate limits of the renderer). So
 * the contract is asserted STRUCTURALLY, against the exact object motion hands
 * the exiting element, plus a render that proves that object is the one the
 * overlay is built from. That is weaker than a real click and is stated as
 * such: what it cannot see is whether the browser honours the style, only that
 * the style is asked for. The Playwright suite covers the rendered page.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";

import { importTsx, markup, readSource } from "./helpers/renderTsx.mjs";

const { Dialog, overlayMotion } = await importTsx("components/ui/Dialog.tsx");

/** `useReducedMotion()` returns `null`, not `false`, when motion is allowed. */
const FULL_MOTION = null;
const REDUCED_MOTION = true;

// --- The closing window ------------------------------------------------------

test("a closing overlay stops catching clicks", () => {
  assert.equal(overlayMotion(FULL_MOTION).exit.pointerEvents, "none");
});

test("reduced motion closes the same window", () => {
  // Its exit is instant, but instant is still a frame of AnimatePresence
  // bookkeeping — and under a frozen rAF it is not a frame at all. Same hole.
  const { exit } = overlayMotion(REDUCED_MOTION);
  assert.equal(exit.pointerEvents, "none");
  assert.equal(exit.transition.duration, 0);
});

test("the exit still plays — this stops clicks, it does not skip the animation", () => {
  // If the fade were dropped the dialog would vanish instead of closing, which
  // is a visual regression this fix must not smuggle in.
  assert.equal(overlayMotion(FULL_MOTION).exit.opacity, 0);
  // Reduced motion never faded; it holds opacity and takes zero time.
  assert.equal(overlayMotion(REDUCED_MOTION).exit.opacity, 1);
});

// --- The open window, which must be unchanged --------------------------------

test("an OPEN overlay still blocks the page behind it", () => {
  // Motion never reverts a value it has set, and re-opening mid-exit reuses the
  // same DOM node. Without this pair the second open would come back with a
  // backdrop that no longer blocks anything — a worse bug than the one fixed.
  assert.equal(overlayMotion(FULL_MOTION).animate.pointerEvents, "auto");
  assert.equal(overlayMotion(REDUCED_MOTION).animate.pointerEvents, "auto");
});

test("the entrance is untouched by the extraction", () => {
  assert.deepEqual(overlayMotion(FULL_MOTION).initial, { opacity: 0 });
  // `false` = no entrance at all, the reduced-motion contract.
  assert.equal(overlayMotion(REDUCED_MOTION).initial, false);
});

test("an open dialog renders the full-viewport scrim, hit-testing, over its panel", () => {
  const html = markup(
    createElement(
      Dialog,
      { open: true, onClose() {}, title: "Delete account" },
      "Type DELETE to confirm.",
    ),
  );
  assert.match(html, /class="fixed inset-0 z-\[100\]/);
  assert.match(html, /role="dialog" aria-modal="true"/);
  // The repair belongs to the exit target alone. A `pointer-events-none` class
  // on the wrapper would read as the same fix while making the backdrop inert
  // for the whole time the dialog is open — clicks would fall through to the
  // page, and the backdrop-click close would never fire.
  assert.doesNotMatch(html, /pointer-events-none/);
});

// --- The wiring --------------------------------------------------------------

test("the overlay is built FROM that object, not from a copy of it", () => {
  // Server-rendered markup carries the `initial` target, so this is evidence
  // from the rendered output that `overlayMotion` reaches the overlay element
  // rather than sitting exported and unused next to a second set of inline
  // targets — the shape of gate that cannot fail.
  const html = markup(
    createElement(Dialog, { open: true, onClose() {}, title: "T" }, "b"),
  );
  assert.match(html, /class="fixed inset-0 z-\[100\][^"]*" style="opacity:0"/);

  const src = readSource("components/ui/Dialog.tsx");
  assert.match(src, /\{\.\.\.overlayMotion\(reduceMotion\)\}/);
  // The inline targets this replaced must be gone, or the spread could be
  // overridden by a later prop and every assertion above would still pass.
  assert.doesNotMatch(src, /exit=\{reduceMotion/);
});
