/**
 * The verdict exhibit's evidence: the spans the shipped scoring walk actually
 * matched on the verdict email, merged into lit ranges and sliceable into
 * segments.
 *
 * What this module deliberately does NOT export — the trade line the owner
 * drew: pattern sources, tier weights, per-hit points, confidence decimals.
 * The exhibit shows WHAT decided (the mail's own phrases), never how the
 * deciding is written. The offsets come from `traceRules` — recorded during
 * the scoring walk, in the same tab — so the display cannot drift from the
 * verdict: if the rules move, the category and the lit spans move with them
 * in the same render.
 *
 * Pure and date-free → prerender-safe, same result on server and client.
 */
import { VERDICT_EMAIL } from "@/components/marketing/verdictEmailData";
import { traceRules, type RuleHit } from "@/lib/demo/rulesLayer";

export interface LitRange {
  start: number;
  end: number;
}

export interface TraceView {
  /** The engine's category token — a machine value, never rendered raw. */
  category: string;
  subjectRanges: LitRange[];
  bodyRanges: LitRange[];
}

/** Merge one field's positive hits into non-overlapping lit ranges. */
function litRanges(hits: RuleHit[], field: "subject" | "body"): LitRange[] {
  const sorted = hits
    .filter((h) => h.field === field && h.points > 0)
    .sort((a, b) => a.start - b.start);
  const merged: LitRange[] = [];
  for (const h of sorted) {
    const last = merged[merged.length - 1];
    if (last && h.start <= last.end) last.end = Math.max(last.end, h.end);
    else merged.push({ start: h.start, end: h.end });
  }
  return merged;
}

export function buildTraceView(): TraceView {
  const { subject, body, senderEmail } = VERDICT_EMAIL;
  const { verdict, hits } = traceRules(subject, body, senderEmail);
  const winner = hits.filter((h) => h.category === verdict.category);
  return {
    category: verdict.category,
    subjectRanges: litRanges(winner, "subject"),
    bodyRanges: litRanges(winner, "body"),
  };
}

/** The text with its lit ranges wrapped — the exhibit's one highlight
 *  grammar, so preview and rest can be segmented against the same offsets. */
export function segments(
  text: string,
  ranges: LitRange[],
): { text: string; mark: boolean }[] {
  const parts: { text: string; mark: boolean }[] = [];
  let cursor = 0;
  for (const r of ranges) {
    if (r.start > cursor) parts.push({ text: text.slice(cursor, r.start), mark: false });
    parts.push({ text: text.slice(r.start, r.end), mark: true });
    cursor = r.end;
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor), mark: false });
  return parts;
}

/** `segments` over a window of the text — offsets stay in the FULL text's
 *  coordinates, so the preview/rest split cannot shear a lit range. */
export function segmentsBetween(
  text: string,
  ranges: LitRange[],
  from: number,
  to: number,
): { text: string; mark: boolean }[] {
  const clipped = ranges
    .filter((r) => r.end > from && r.start < to)
    .map((r) => ({ start: Math.max(r.start, from) - from, end: Math.min(r.end, to) - from }));
  return segments(text.slice(from, to), clipped);
}
