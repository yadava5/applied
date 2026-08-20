/**
 * The 02 family's shared evidence: the spans the shipped scoring walk
 * actually matched on the verdict email, merged into lit ranges and sliced
 * into quotable phrases.
 *
 * What this module deliberately does NOT export — the trade line the owner
 * drew: pattern sources, tier weights, per-hit points, confidence decimals.
 * The exhibits show WHAT decided (the mail's own phrases) and WHAT HAPPENED
 * because of it (the filing), never how the deciding is written. The offsets
 * still come from `traceRules` — recorded during the scoring walk, in the
 * same tab — so the display cannot drift from the verdict: if the rules
 * move, the category, the lit spans and the quotes all move with them in the
 * same render.
 *
 * Pure and date-free → prerender-safe, same result on server and client.
 */
import { VERDICT_EMAIL } from "@/components/marketing/verdictEmailData";
import { traceRules, type RuleHit } from "@/lib/demo/rulesLayer";

export interface LitRange {
  start: number;
  end: number;
}

export interface EvidenceQuote {
  field: "subject" | "body";
  quote: string;
}

export interface TraceView {
  /** The engine's category token — machine value; display via categoryWord. */
  category: string;
  subjectRanges: LitRange[];
  bodyRanges: LitRange[];
  /** Reading order: subject phrases first, then body. */
  evidence: EvidenceQuote[];
}

/** The user-facing word for a mail category — the product's vocabulary, not
 *  the engine's token (`follow_up` is a key, "Follow-up" is a label). */
const CATEGORY_WORDS: Record<string, string> = {
  applied: "Application received",
  rejection: "Rejection",
  interview: "Interview",
  offer: "Offer",
  assessment: "Assessment",
  follow_up: "Follow-up",
  other: "Not job mail",
};

export function categoryWord(category: string): string {
  return CATEGORY_WORDS[category] ?? category;
}

/** Where a mail of this category files on the board — stage words, the same
 *  vocabulary the board's group headings use. */
const FILES_TO: Record<string, string> = {
  interview: "Interviewing",
  offer: "Offered",
  rejection: "Closed",
  assessment: "Assessment",
  applied: "Applied",
};

export function filesTo(category: string): string | null {
  return FILES_TO[category] ?? null;
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
  const subjectRanges = litRanges(winner, "subject");
  const bodyRanges = litRanges(winner, "body");
  const quote = (text: string, r: LitRange) => text.slice(r.start, r.end).replace(/\s+/g, " ").trim();
  return {
    category: verdict.category,
    subjectRanges,
    bodyRanges,
    evidence: [
      ...subjectRanges.map((r) => ({ field: "subject" as const, quote: quote(subject, r) })),
      ...bodyRanges.map((r) => ({ field: "body" as const, quote: quote(body, r) })),
    ],
  };
}

/** The text with its lit ranges wrapped, the first `lit` of them switched on.
 *  Shared by the 02 exhibits so the highlight grammar stays one grammar. */
export function segments(
  text: string,
  ranges: LitRange[],
): { text: string; mark: boolean; index: number }[] {
  const parts: { text: string; mark: boolean; index: number }[] = [];
  let cursor = 0;
  ranges.forEach((r, index) => {
    if (r.start > cursor) parts.push({ text: text.slice(cursor, r.start), mark: false, index: -1 });
    parts.push({ text: text.slice(r.start, r.end), mark: true, index });
    cursor = r.end;
  });
  if (cursor < text.length) parts.push({ text: text.slice(cursor), mark: false, index: -1 });
  return parts;
}
