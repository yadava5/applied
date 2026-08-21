"use client";

import { classifyWithRules } from "@/lib/demo/rulesLayer";

import { cn } from "@/lib/utils";
import { buildTraceView, segments, segmentsBetween, type TraceView } from "./traceEvidence";
import { PREVIEW_CHARS, VERDICT_EMAIL } from "./verdictEmailData";

/**
 * The descent's travelling artifact: one synthetic interview invitation,
 * classified LIVE.
 *
 * The email is invented (no real person's mail is ever read) but nothing else
 * is: both verdicts below are computed in the visitor's tab by
 * `classifyWithRules` — the browser port of the shipped rules engine — once
 * on the first ~200 characters (what Gmail's `snippet` gives) and once on the
 * whole body. The text was tuned so the two calls disagree the way production
 * truncation actually bites (see verdictEmailData.ts): the invitation's
 * polite opening reads as a routine acknowledgment, and the sentence that
 * invites you falls past the preview. If `rules.json` ever changes, this page
 * changes with it — the verdicts are read from the engine, never hardcoded.
 *
 * Pure and date-free, so it is prerender-safe: same inputs on the server pass
 * and in the browser, no hydration risk. Transitions between stages are CSS
 * under `motion-safe:` — with reduced motion the states still change, they
 * just stop animating.
 */

/**
 * `dissolve` is the escalated exhibit's third beat (see the `evidence` prop):
 * the mail is still at full height, but every phrase the scoring walk did NOT
 * match fades to a residue while the lit phrases hold. Without `evidence` it
 * renders as `split`, so no legacy caller can reach a state it never staged.
 */
export type VerdictStage = "raw" | "split" | "dissolve" | "retained";

// The email itself lives in verdictEmailData.ts (plain data, no directive) so
// variant C's server-rendered hero row can derive its stage chip from the
// same live classification this component shows.
const { senderName: SENDER_NAME, senderEmail: SENDER_EMAIL, subject: SUBJECT, body: BODY } =
  VERDICT_EMAIL;

const PREVIEW = BODY.slice(0, PREVIEW_CHARS);
const REST = BODY.slice(PREVIEW_CHARS);

function Chip({
  source,
  category,
  confidence,
  note,
  fired,
}: {
  source: string;
  category: string;
  confidence: number;
  note: string;
  fired?: boolean;
}) {
  return (
    // `data-verdict-chip` is the chip's ADDRESS, for the fold gate that has to
    // find it (landing.spec.ts). Its words are quoted in the take's narration,
    // so a text match resolves the narration line too — an addressable handle
    // is what stops that gate losing itself to a strict-mode violation.
    <div
      data-verdict-chip={source}
      className={`rounded-lg border px-3 py-2 ${
        fired ? "border-viz-rules/50 bg-surface" : "border-line-soft bg-surface"
      }`}
    >
      <p className="label-caps flex items-center gap-2">
        {fired && <span className="h-1.5 w-1.5 rounded-full bg-viz-rules" aria-hidden />}
        {source}
      </p>
      <p className="mt-1.5 flex items-baseline gap-2">
        <span className={`text-sm font-medium ${fired ? "text-strong" : "text-muted"}`}>
          {category}
        </span>
        <span className="tabular font-mono text-xs text-dim">{confidence.toFixed(2)}</span>
      </p>
      <p className="mt-1 text-xs text-dim">{note}</p>
    </div>
  );
}

/** Lazily built and memoised at module scope: pure and date-free, so it is
 *  the same on the server pass and in the browser — and consumers that never
 *  pass `evidence` never pay for the trace walk. */
let traceMemo: TraceView | null = null;
function trace(): TraceView {
  return (traceMemo ??= buildTraceView());
}

/** The highlight grammar, shared with the take that introduced it (02b):
 *  matched phrases carry the rules-layer colour; dissolved prose is a
 *  residue, deliberately below legibility — the state is "going", and the
 *  wall label beside the exhibit names it. */
const LIT = "rounded-sm bg-viz-rules/15 px-0.5 text-strong shadow-[inset_0_-1px_0_var(--viz-rules)]";
const GONE = "opacity-[0.14] blur-[1.5px] grayscale";

function EvidenceText({
  parts,
  stage,
}: {
  parts: { text: string; mark: boolean }[];
  stage: VerdictStage;
}) {
  return (
    <>
      {parts.map((part, i) => (
        <span
          key={i}
          className={cn(
            "motion-safe:transition-[opacity,filter,color,background-color] motion-safe:duration-700",
            part.mark && stage !== "raw" && LIT,
            !part.mark && stage === "dissolve" && GONE,
          )}
        >
          {part.text}
        </span>
      ))}
    </>
  );
}

export function VerdictEmail({
  stage,
  evidence = false,
}: {
  stage: VerdictStage;
  /**
   * The escalated staging (the owner's 02b pick, 2026-08-19): the phrases the
   * scoring walk matched are lit from `split` on, `dissolve` fades the prose
   * that never scored, and `retained` then takes the lit phrases too — the
   * record is all that outlives the mail, deciding phrase included. Off by
   * default: every other mount (the candidates, the inline snapshots, the
   * retention record) keeps its approved rendering untouched.
   */
  evidence?: boolean;
}) {
  // Live, both of them — the whole point of the artifact.
  const fromPreview = classifyWithRules(SUBJECT, PREVIEW, SENDER_EMAIL);
  const fromBody = classifyWithRules(SUBJECT, BODY, SENDER_EMAIL);
  if (stage === "dissolve" && !evidence) stage = "split";
  const retained = stage === "retained";
  const view = evidence ? trace() : null;

  return (
    <div className="overflow-hidden rounded-xl border border-line-soft bg-surface">
      {/* ---- header: what is always visible ------------------------------ */}
      <div className="border-b border-line-soft px-4 py-3">
        <p className="text-sm font-medium text-strong">
          {view ? <EvidenceText parts={segments(SUBJECT, view.subjectRanges)} stage={stage} /> : SUBJECT}
        </p>
        <p className="mt-0.5 text-xs text-dim">
          {SENDER_NAME} · <span className="font-mono">{SENDER_EMAIL}</span>
        </p>
      </div>

      {/* ---- body: dissolves under the escalated staging, collapses when
              the claim is retention ------------------------------------- */}
      <div
        className={`grid motion-safe:transition-[grid-template-rows,opacity] motion-safe:duration-500 ${
          retained ? "grid-rows-[0fr] opacity-0" : "grid-rows-[1fr] opacity-100"
        }`}
        aria-hidden={retained || stage === "dissolve"}
      >
        <div className="min-h-0 overflow-hidden">
          <div className="px-4 py-3 text-[0.8125rem] leading-relaxed text-muted">
            <p>
              {view ? (
                <EvidenceText
                  parts={segmentsBetween(BODY, view.bodyRanges, 0, PREVIEW_CHARS)}
                  stage={stage}
                />
              ) : (
                PREVIEW
              )}
            </p>
            <p
              className={`label-caps my-2 flex items-center gap-3 motion-safe:transition-opacity motion-safe:duration-500 ${
                stage === "raw" ? "opacity-40" : stage === "dissolve" ? "opacity-0" : "opacity-100"
              }`}
              aria-hidden
            >
              <span className="h-px flex-1 bg-line-strong" />
              Gmail&apos;s preview ends here
              <span className="h-px flex-1 bg-line-strong" />
            </p>
            <p>
              {view ? (
                <EvidenceText
                  parts={segmentsBetween(BODY, view.bodyRanges, PREVIEW_CHARS, BODY.length)}
                  stage={stage}
                />
              ) : (
                REST
              )}
            </p>
          </div>
        </div>
      </div>

      {/* ---- the two live verdicts. They hold through the dissolve — the
              verdicts are the part that survives the prose — and leave only
              for the record. ---------------------------------------------- */}
      <div
        className={`grid motion-safe:transition-[grid-template-rows,opacity] motion-safe:duration-500 ${
          stage === "split" || stage === "dissolve"
            ? "grid-rows-[1fr] opacity-100"
            : "grid-rows-[0fr] opacity-0"
        }`}
        aria-hidden={stage !== "split" && stage !== "dissolve"}
      >
        {/* `data-verdict-chips` names the element the collapse ZEROES: the grid
            item is what `grid-rows-[0fr]` gives height 0, while the chips
            inside keep their own boxes under the clip. It is the one handle
            on this exhibit that reads "the verdicts are open". */}
        <div data-verdict-chips className="min-h-0 overflow-hidden">
          <div className="grid gap-2 border-t border-line-soft px-4 py-3 sm:grid-cols-2">
            <Chip
              source="preview only"
              category={fromPreview.category}
              confidence={fromPreview.confidence}
              note="reads as a routine acknowledgment. Wrong."
            />
            <Chip
              source="whole body"
              category={fromBody.category}
              confidence={fromBody.confidence}
              note="the invitation, found"
              fired
            />
          </div>
        </div>
      </div>

      {/* ---- what the database keeps ------------------------------------- */}
      <div
        className={`grid motion-safe:transition-[grid-template-rows,opacity] motion-safe:duration-500 ${
          retained ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"
        }`}
        aria-hidden={!retained}
      >
        <div className="min-h-0 overflow-hidden">
          <dl className="divide-y divide-line-soft border-t border-line-soft text-[0.8125rem]">
            {[
              { k: "subject", v: SUBJECT },
              { k: "sender_email", v: SENDER_EMAIL },
              { k: "body_snippet", v: `${PREVIEW.slice(0, 80)}…` },
              { k: "classified_as", v: fromBody.category },
            ].map((row) => (
              <div key={row.k} className="grid grid-cols-[8.5rem_minmax(0,1fr)] gap-2 px-4 py-2">
                <dt className="font-mono text-xs leading-5 text-strong">{row.k}</dt>
                <dd className="truncate leading-5 text-muted">{row.v}</dd>
              </div>
            ))}
            {["body_text", "body_html"].map((k) => (
              <div key={k} className="grid grid-cols-[8.5rem_minmax(0,1fr)] gap-2 px-4 py-2">
                <dt className="font-mono text-xs leading-5 text-dim line-through decoration-line-strong">
                  {k}
                </dt>
                <dd className="leading-5 text-dim">never written</dd>
              </div>
            ))}
          </dl>
        </div>
      </div>

      <p className="border-t border-line-soft px-4 py-2.5 text-[11px] leading-relaxed text-dim">
        A synthetic email. The verdicts are computed live in this tab.
      </p>
    </div>
  );
}
