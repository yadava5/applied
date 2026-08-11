/**
 * How the pipeline board LABELS what `summary.ts` groups. Presentation only —
 * membership (which status belongs in which column) is still decided by
 * `stageOf`, so the board can never disagree with the tiles or the funnel about
 * how many rows are where.
 *
 * The bug this fixes: a `withdrawn` application landed in a column whose
 * `aria-label` read `rejected — 1`. The user withdrew; the board told them (and
 * a screen reader) they were rejected. The membership is not wrong — withdrawn
 * IS resolved, and `summary.ts` already calls that bucket `closed`
 * ("rejected + withdrawn") — only the column's word was, so only the word moves
 * here. The count under `closed` is byte-for-byte the count that was under
 * `rejected`, and it now matches the vocabulary the summary type already uses.
 *
 * What this does NOT do, deliberately: give `withdrawn` a column of its own.
 * That is a membership change, and membership lives in `STAGES` /
 * `summarizeCounts` in `summary.ts` — the single implementation of stage
 * semantics that the board, the funnel and the stat tiles all read. Splitting
 * it only on the board would put a five-column board next to a four-stage
 * funnel that still counts withdrawn inside "rejected": two numbers for one
 * thing, which is worse than one imprecise label. The heading and the cards
 * under it now agree either way — nothing in `closed` claims to be a rejection.
 *
 * The membership change is still worth making, and it is one file: `STAGES`
 * grows a fifth stage owning `withdrawn` (and `ghosted`, which today has no
 * stage at all and so falls through `stageOf`'s `?? "applied"` into the applied
 * column and into `inMotion`), `counts`/`PipelineSummary` gain that key, and
 * the board's `lg:grid-cols-4` becomes 5. Doing it there fixes the funnel and
 * the tiles in the same stroke; doing it here would fix only the board.
 *
 * `stages` is a parameter rather than an import so this module stays
 * import-free and `node --test` can load it under type stripping (`summary.ts`
 * value-imports through the `@/` alias, which Node cannot resolve).
 */
import type { StageDef, StageKey } from "./summary";

/**
 * Column headings that differ from the stage's own name. Only the resolved
 * bucket does: it holds rejections AND withdrawals, so it is "closed".
 */
export const COLUMN_LABELS: Partial<Record<StageKey, string>> = {
  rejected: "closed",
};

export interface BoardColumn {
  key: StageKey;
  /** The heading, and the `${label} — ${count}` region name. */
  label: string;
  color: string;
}

/** The board's columns: the stages, in order, under their board headings. */
export function boardColumns(stages: readonly StageDef[]): BoardColumn[] {
  return stages.map((stage) => ({
    key: stage.key,
    label: COLUMN_LABELS[stage.key] ?? stage.label,
    color: stage.color,
  }));
}

/**
 * The word a card must carry so its column's heading is never read as a claim
 * about that row: its own status, whenever the heading does not already say it.
 *
 * In `closed` that tags every card `rejected` or `withdrawn`; in `offered` it
 * tags `accepted`; in `applied` it tags a `ghosted` row (which has no column of
 * its own — see the report/`stageOf`'s fallback) instead of letting it pass for
 * a live application. A row whose status IS the heading gets nothing, because
 * the heading already said it.
 */
export function cardQualifier(status: string | null | undefined, columnLabel: string): string | null {
  const s = typeof status === "string" ? status.trim().toLowerCase() : "";
  if (!s) return null;
  return s === columnLabel.trim().toLowerCase() ? null : s;
}
