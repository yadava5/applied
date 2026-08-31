/**
 * What a person actually reads, taken from markup by PARSING it.
 *
 * WHY THIS EXISTS, AND WHY IT IS NOT A REGEX (#424, CodeQL).
 *
 * Two test files each grew their own `visibleText(html)` that stripped tags
 * with `/<[^>]*>/g` and then put a handful of entities back by hand. CodeQL
 * flagged both as `js/incomplete-multi-character-sanitization`, and one of them
 * as `js/double-escaping`. The severity label is wrong — neither helper ever
 * runs in the product and there is no injection path from a test — but the
 * double-escaping finding was a REAL correctness bug, and the kind that makes
 * an assertion pass for the wrong reason:
 *
 *     .replaceAll("&amp;", "&")   // runs first
 *     .replaceAll("&lt;", "<")    // then this
 *
 * React renders the literal text `&lt;script&gt;` as `&amp;lt;script&amp;gt;`,
 * so a reader sees `&lt;script&gt;` — punctuation and the letters `lt`, not a
 * tag. The chain above turned `&amp;lt;` into `&lt;` into `<` and reported
 * `<script>`, a string that was never on screen. Measured, both helpers, same
 * input `<p>&amp;lt;script&amp;gt; hi</p>`:
 *
 *     hand-rolled ->  "<script> hi"          <- never visible to anyone
 *     parsed      ->  "&lt;script&gt; hi"    <- what is actually on the line
 *
 * The tag strip is wrong in the same direction. A `>` inside a QUOTED
 * attribute value does not close the tag — the HTML tokenizer stays in the
 * attribute-value state — but `<[^>]*>` cuts at it anyway and spills the rest
 * of the attribute into what it calls visible text:
 *
 *     <p title="1 hidden character (U+202E) > see">Payroll</p>
 *     regex  ->  " see\">Payroll"
 *     parsed ->  "Payroll"
 *
 * That second one is NOT reachable from a component today: React escapes `>`
 * to `&gt;` inside attribute values, so `renderToStaticMarkup` never emits it.
 * It is fixed anyway because the correctness of the instrument should not rest
 * on a guarantee made by the thing it is measuring, and because this helper is
 * exported now and the next caller may not be React.
 *
 * WHAT THIS IS. `<template>`, then `.textContent`. The template's content is a
 * DocumentFragment parsed with no element-nesting restrictions, so a bare
 * `<li>` — which is what every row component here renders — survives instead
 * of being relocated the way `body.innerHTML` can relocate it. `textContent`
 * is then the definition of the thing being asserted: the concatenated text of
 * every descendant, entities resolved by the same parser a browser uses, and
 * attributes excluded because an attribute is not on the line. A code point
 * hiding in a `title` is not something a reader sees, and that exclusion is now
 * a property of the parser rather than of a regex that has to remember it.
 *
 * jsdom is already a devDependency and already loaded by `helpers/mountApp.mjs`,
 * so this adds nothing to install. One document and one template are built at
 * import time and reused; assigning `innerHTML` replaces the content each call,
 * so there is no state to leak between tests.
 */
import { JSDOM } from "jsdom";

const { document } = new JSDOM("<!doctype html><html><body></body></html>").window;
const template = document.createElement("template");

/** The text a reader would see, given a fragment of rendered markup. */
export function visibleText(html) {
  template.innerHTML = html;
  return template.content.textContent;
}
