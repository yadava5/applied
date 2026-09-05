/**
 * What the dashboard says when a sync or scan FAILED, and the retry beside it.
 *
 * A LEAF ON PURPOSE (#848). This lived inline in `SyncBar.tsx`, which imports
 * `next/link`, `next/navigation` and `motion` and therefore cannot be rendered
 * under `node --test` at all — so the copy on the one path that carries the
 * backend's own words was asserted by reading the file. Pulled out here it is
 * a leaf presentational component: no router, no link, no hook, so
 * `helpers/renderTsx.mjs` renders it for real and
 * `tests/unit/sync-failure-note.test.mjs` asserts what a reader sees.
 *
 * THE STANDING CLAUSE IS NOT REPLACEABLE. `detail` is precision WITHIN the
 * failure, never a substitute for it. #643 warned in as many words that
 * relaying the backend's sentence "collapses back into the rejected fix" if
 * the frontend renders a typed 500 as a success; #604 is where that reasoning
 * was settled. So this component always renders three things together — the
 * operation that failed, the clause that is true at every failure point, and
 * the retry — and `detail` is appended to them. A future edit that drops the
 * clause or the retry to make room for the backend's sentence reds the test.
 *
 * `detail` is `null` on every response that carried no usable body: a 502 from
 * the edge, a timeout, an HTML error page, a function killed on its ceiling.
 * That case renders exactly the sentence this surface shipped before #848 —
 * never the word "null", and never an empty separator dangling off the clause.
 */

/** Which run failed — the word the reader saw on the button they pressed. */
export type SyncFailureOp = string;

/** The clause that is true at every point either run can stop.
 *
 *  Exported so the test names it once rather than retyping a sentence, and so
 *  a reword changes the assertion and the UI in the same commit. */
export const STANDING_CLAUSE =
  "anything it filed or removed before stopping stays that way";

export function SyncFailureNote({
  op,
  detail,
  onRetry,
}: {
  op: SyncFailureOp;
  /** The backend's own sentence, or `null` when it sent none. */
  detail: string | null;
  onRetry: () => void;
}) {
  return (
    <>
      {op} failed · {STANDING_CLAUSE}
      {detail ? ` · ${detail}` : ""}{" "}
      <button
        type="button"
        onClick={onRetry}
        className="text-muted underline-offset-2 hover:text-strong hover:underline"
      >
        try again
      </button>
    </>
  );
}
