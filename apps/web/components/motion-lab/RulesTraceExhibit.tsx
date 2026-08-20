import { VERDICT_EMAIL } from "@/components/marketing/verdictEmailData";
import { traceRules, type RuleHit } from "@/lib/demo/rulesLayer";

/**
 * Candidate 02 — the rules trace: the verdict email with the spans that
 * decided it lit, straight from the engine.
 *
 * `traceRules` is the shipped rules walk with a recorder attached (see
 * lib/demo/rulesLayer.ts) — the highlights below are the offsets the scoring
 * regexes themselves matched at, so this exhibit cannot drift from the
 * verdict: if rules.json changes, both the category and the lit spans change
 * with it in the same render.
 *
 * Only the WINNING category's hits are lit. Lighting all eight categories'
 * matches turns evidence into noise; the claim is "here is why it decided",
 * and why-it-decided is the winner's spans plus the winner's arithmetic.
 *
 * Pure and date-free — same inputs on the server pass and in the browser, so
 * it prerenders and carries no hydration risk. No motion is needed: the
 * treatment IS the highlight, and it works frozen.
 */

const { senderName, senderEmail, subject, body } = VERDICT_EMAIL;

/** Merge the winner's hits in one field into non-overlapping lit ranges. */
function litRanges(hits: RuleHit[], field: "subject" | "body"): { start: number; end: number }[] {
  const sorted = hits
    .filter((h) => h.field === field && h.points > 0)
    .sort((a, b) => a.start - b.start);
  const merged: { start: number; end: number }[] = [];
  for (const h of sorted) {
    const last = merged[merged.length - 1];
    if (last && h.start <= last.end) last.end = Math.max(last.end, h.end);
    else merged.push({ start: h.start, end: h.end });
  }
  return merged;
}

/** The text with its lit ranges wrapped — plain spans, no re-derivation. */
function Lit({ text, ranges }: { text: string; ranges: { start: number; end: number }[] }) {
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  for (const r of ranges) {
    if (r.start > cursor) parts.push(text.slice(cursor, r.start));
    parts.push(
      <mark
        key={r.start}
        className="rounded-sm bg-viz-rules/15 px-0.5 text-strong shadow-[inset_0_-1px_0_var(--viz-rules)]"
      >
        {text.slice(r.start, r.end)}
      </mark>,
    );
    cursor = r.end;
  }
  if (cursor < text.length) parts.push(text.slice(cursor));
  return <>{parts}</>;
}

export function RulesTraceExhibit() {
  const { verdict, hits } = traceRules(subject, body, senderEmail);
  const winnerHits = hits.filter((h) => h.category === verdict.category);

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,30rem)_minmax(0,1fr)] lg:items-start">
      <div className="overflow-hidden rounded-xl border border-line-soft bg-surface">
        <div className="border-b border-line-soft px-4 py-3">
          <p className="text-sm font-medium text-strong">
            <Lit text={subject} ranges={litRanges(winnerHits, "subject")} />
          </p>
          <p className="mt-0.5 text-xs text-dim">
            {senderName} · <span className="font-mono">{senderEmail}</span>
          </p>
        </div>
        <div className="px-4 py-3 text-[0.8125rem] leading-relaxed text-muted">
          <Lit text={body} ranges={litRanges(winnerHits, "body")} />
        </div>
        <p className="border-t border-line-soft px-4 py-2.5 text-[11px] leading-relaxed text-dim">
          A synthetic email. The lit spans are the offsets the shipped rules layer matched while
          scoring it — recorded during the walk, in this tab, not re-derived for display.
        </p>
      </div>

      <div>
        <p className="label-caps">The verdict, and its evidence</p>
        <p className="mt-2 flex items-baseline gap-2">
          <span className="text-sm font-medium text-strong">{verdict.category}</span>
          <span className="tabular font-mono text-xs text-dim">
            {verdict.confidence.toFixed(2)}
          </span>
        </p>
        <ul className="mt-3 space-y-1.5">
          {winnerHits.map((h) => (
            <li key={h.source + h.field} className="flex items-baseline gap-2 font-mono text-xs">
              <span className="tabular shrink-0 text-viz-rules">
                {h.points > 0 ? `+${h.points}` : h.points}
              </span>
              <span className="shrink-0 text-dim">{h.field}</span>
              <span className="truncate text-muted" title={h.source}>
                /{h.source}/i
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-4 max-w-sm text-xs leading-relaxed text-dim">
          Each row is one pattern the winning category scored on: its points, the field it scored
          in, and the pattern itself. This is the differentiator rendered — the product can show
          this for any mail because the classifier is rules, not weights.
        </p>
      </div>
    </div>
  );
}
