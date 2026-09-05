/**
 * What a reader actually SEES when a sync fails, rendered (#848).
 *
 * THE GUARD THIS FILE IS. #643 relayed the backend's own sentence and warned,
 * in as many words, that the fix "collapses back into the rejected fix" if the
 * frontend renders the typed 500 as a success. Before #848 that collapse was
 * structurally impossible — nothing rendered the sentence at all. The moment
 * the proxy relays it, the copy becomes load-bearing, and asserting only that
 * the text APPEARS would pass a UI that printed "3 filed and 1 queued of 4
 * scanned" under a green tick with no retry beside it.
 *
 * So every assertion here is about the sentence's COMPANY and its ORDER:
 *   - the operation that failed leads,
 *   - the clause true at every failure point comes next and is never replaced,
 *   - the backend's precision is appended to them, not substituted for them,
 *   - and the retry is present in both branches.
 *
 * The order assertion is the valence guard proper. Rendered detail-first the
 * line opens "3 filed and 1 queued of 4 scanned…", which reads as a receipt
 * for a run that worked.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import { importTsx, markup } from "./helpers/renderTsx.mjs";
import { visibleText } from "./helpers/visibleText.mjs";

const TYPED_500 =
  "Could not record this sync. 3 filed and 1 queued of 4 scanned before it failed; sync again to finish.";

async function render(props) {
  const { SyncFailureNote, STANDING_CLAUSE } = await importTsx(
    "components/dashboard/SyncFailureNote.tsx",
  );
  const html = markup(SyncFailureNote({ op: "sync", detail: null, onRetry: () => {}, ...props }));
  return { html, text: visibleText(html), STANDING_CLAUSE };
}

test("the harness renders this component at all", async () => {
  // A control, and not a formality: `renderTsx` cannot load a component that
  // reaches for next/link or a router, and it fails by THROWING — but a future
  // edit that made every assertion below vacuous by returning an empty
  // fragment would not. Pin something non-empty first.
  const { html, text } = await render({});
  assert.ok(html.length > 0, "no markup at all");
  assert.match(text, /sync failed/, "the failure never named the operation");
});

test("the backend's sentence reaches the reader", async () => {
  // MUTATION: drop `detail` from the component's output -> red. This is #848.
  const { text } = await render({ detail: TYPED_500 });
  assert.ok(text.includes(TYPED_500), `the backend's sentence is not on screen:\n${text}`);
});

test("VALENCE: the failure leads, the standing clause holds, the detail follows", async () => {
  // MUTATION: render `{detail}` before the clause, or in place of it -> red.
  // Detail-first the line opens with "3 filed and 1 queued of 4 scanned",
  // which is a success receipt, not a failure.
  const { text, STANDING_CLAUSE } = await render({ detail: TYPED_500 });

  const failedAt = text.indexOf("sync failed");
  const clauseAt = text.indexOf(STANDING_CLAUSE);
  const detailAt = text.indexOf(TYPED_500);

  assert.ok(failedAt >= 0, "the word `failed` left the failure copy");
  assert.ok(clauseAt >= 0, "the standing clause was replaced by the backend's sentence");
  assert.ok(detailAt >= 0, "the backend's sentence is missing");
  assert.ok(
    failedAt < clauseAt && clauseAt < detailAt,
    `order is failure -> clause -> detail; got ${failedAt}, ${clauseAt}, ${detailAt}:\n${text}`,
  );
});

test("VALENCE: the retry survives the detail, on both branches", async () => {
  // MUTATION: render the retry only when `detail` is null (a plausible
  // "the backend already told them what to do" edit) -> red on the first case.
  for (const detail of [TYPED_500, null]) {
    const { html, text } = await render({ detail });
    assert.match(html, /<button[^>]*type="button"/, `no retry control (detail=${detail})`);
    assert.ok(text.includes("try again"), `the retry lost its label (detail=${detail})`);
  }
});

test("no body to quote renders the sentence this surface already shipped", async () => {
  // MUTATION: `{` · ${detail}`}` without the guard -> red. `null` and
  // `undefined` render as the literal words in JSX string interpolation, and a
  // failure alert reading "… stays that way · null" is worse than no detail.
  const { text } = await render({ detail: null });
  const { STANDING_CLAUSE } = await render({});

  assert.ok(text.includes(STANDING_CLAUSE), "the standing clause is the fallback and it is gone");
  assert.doesNotMatch(text, /null|undefined|NaN|\[object/, `a placeholder leaked:\n${text}`);
  // And no separator dangling off the clause with nothing after it.
  assert.doesNotMatch(
    text,
    new RegExp(`${STANDING_CLAUSE} ·\\s`),
    "an empty detail left its separator behind",
  );
});

test("the operation is the reader's own word, not a fixed one", async () => {
  // MUTATION: hard-code "sync" -> red. A windowed re-scan that failed must not
  // report itself as a sync; the retry re-issues whichever one it was.
  const { text } = await render({ op: "re-scan", detail: TYPED_500 });
  assert.ok(text.includes("re-scan failed"), `the operation was renamed:\n${text}`);
});
