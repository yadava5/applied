/**
 * DISPLAY grouping of worklist rows by employer — and only display.
 *
 * One employer can hold several applications (four Amazon requisitions in one
 * evening is the proven case), and rendering each as its own row headed by the
 * same company name read as duplication — four near-identical lines all saying
 * "Amazon". So the board folds same-employer rows *within one stage group*
 * into a single employer card that opens inline.
 *
 * What this module must never become: a merge. Collapsing applications into
 * one *record* per company was a real correctness bug fixed at real cost — a
 * merged row took the furthest stage any of the employer's mail reached, a
 * per-requisition rejection froze it terminal, and every later interview and
 * offer for the other requisitions went invisible. Each application keeps its
 * own id, its own status, its own mail and its own controls; a group here is
 * a list of the same rows the flat board would render, in the same order.
 *
 * Grouping is scoped to a stage on purpose. An employer whose applications sit
 * in different stages appears once per stage it occupies — Amazon under
 * `applied` holding 3 AND under `interviewing` holding 1 — because any
 * cross-stage summary row would have to pick one stage to live in, which is
 * exactly the furthest-stage-wins display the merge bug taught us not to
 * draw. Stage counts stay honest application counts by construction, and no
 * row's true stage is ever behind an employer summary.
 *
 * Import-free so `node --test` loads it under type stripping, like `board.ts`.
 */

/** The one field grouping reads. Structural, so this stays schema-free. */
interface CompanyRow {
  company: string;
}

/**
 * One rendered position in a stage group's list: a plain application row, or
 * an employer set holding every application that employer has in this stage.
 */
export type WorklistEntry<T extends CompanyRow> =
  | { kind: "single"; app: T }
  | { kind: "set"; company: string; items: T[] };

/**
 * Fold a stage group's rows into worklist entries. A set forms only when two
 * or more rows share an employer — the singleton (most rows) renders exactly
 * as before. A set anchors at its first member's position and keeps its
 * members in list order, so grouping never reorders what the flat list showed.
 */
export function groupByEmployer<T extends CompanyRow>(rows: T[]): WorklistEntry<T>[] {
  const byCompany = new Map<string, T[]>();
  for (const row of rows) {
    const members = byCompany.get(row.company);
    if (members) members.push(row);
    else byCompany.set(row.company, [row]);
  }

  const entries: WorklistEntry<T>[] = [];
  const emitted = new Set<string>();
  for (const row of rows) {
    const members = byCompany.get(row.company)!;
    if (members.length === 1) {
      entries.push({ kind: "single", app: row });
      continue;
    }
    if (emitted.has(row.company)) continue;
    emitted.add(row.company);
    entries.push({ kind: "set", company: row.company, items: members });
  }
  return entries;
}

/**
 * The visible text of the cross-stage chip: what an employer holds OUTSIDE the
 * stage the reader is looking at. `"+1 in interviewing"` when the rest sits in
 * one stage, `"+3 in other stages"` when it is spread. The old text repeated
 * the employer's name ("+3 at Amazon") one word away from the row already
 * saying "Amazon" — the same duplication grouping exists to remove — and was
 * the widest thing on a phone row. The accessible name is NOT built here: it
 * stays `Show all applications at {company}`, the contract the specs and
 * muscle memory hold (see `SameCompanyChip`).
 */
export function elsewhereLabel(count: number, stageLabels: readonly string[]): string | null {
  if (count <= 0 || stageLabels.length === 0) return null;
  const distinct = [...new Set(stageLabels)];
  return distinct.length === 1 ? `+${count} in ${distinct[0]}` : `+${count} in other stages`;
}
