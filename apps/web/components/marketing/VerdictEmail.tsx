"use client";

import { classifyWithRules } from "@/lib/demo/rulesLayer";

/**
 * Variant C's travelling artifact: one synthetic rejection, classified LIVE.
 *
 * The email is invented (no real person's mail is ever read) but nothing else
 * is: both verdicts below are computed in the visitor's tab by
 * `classifyWithRules` — the browser port of the shipped rules engine — once
 * on the first ~200 characters (what Gmail's `snippet` gives) and once on the
 * whole body. The text was tuned so the two calls disagree the way the
 * production mailbox actually did (the memory behind #320): a rejection's
 * polite opening reads as a confirmation, and the sentence that matters falls
 * past the preview. If `rules.json` ever changes, this page changes with it —
 * the verdicts are read from the engine, never hardcoded.
 *
 * Pure and date-free, so it is prerender-safe: same inputs on the server pass
 * and in the browser, no hydration risk. Transitions between stages are CSS
 * under `motion-safe:` — with reduced motion the states still change, they
 * just stop animating.
 */

export type VerdictStage = "raw" | "split" | "retained";

const SENDER_NAME = "Larkspur Systems Recruiting";
const SENDER_EMAIL = "no-reply@larkspur.dev";
const SUBJECT = "Your application to Larkspur Systems";
const BODY =
  "Hi Ayush, thank you for the time and care you put into your application for the Staff Software Engineer role at Larkspur Systems, and for walking us through your work. We know how much effort a search takes, and we genuinely appreciate your interest in the team. After careful review, we have decided to move forward with other candidates whose experience more closely matches the role. We'd be glad to see you apply again as new positions open.";

/** Gmail's snippet budget — the honest reason the preview verdict is wrong. */
const PREVIEW_CHARS = 200;

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
    <div
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

export function VerdictEmail({ stage }: { stage: VerdictStage }) {
  // Live, both of them — the whole point of the artifact.
  const fromPreview = classifyWithRules(SUBJECT, PREVIEW, SENDER_EMAIL);
  const fromBody = classifyWithRules(SUBJECT, BODY, SENDER_EMAIL);
  const retained = stage === "retained";

  return (
    <div className="overflow-hidden rounded-xl border border-line-soft bg-surface">
      {/* ---- header: what is always visible ------------------------------ */}
      <div className="border-b border-line-soft px-4 py-3">
        <p className="text-sm font-medium text-strong">{SUBJECT}</p>
        <p className="mt-0.5 text-xs text-dim">
          {SENDER_NAME} · <span className="font-mono">{SENDER_EMAIL}</span>
        </p>
      </div>

      {/* ---- body: collapses when the claim is retention ------------------ */}
      <div
        className={`grid motion-safe:transition-[grid-template-rows,opacity] motion-safe:duration-500 ${
          retained ? "grid-rows-[0fr] opacity-0" : "grid-rows-[1fr] opacity-100"
        }`}
        aria-hidden={retained}
      >
        <div className="min-h-0 overflow-hidden">
          <div className="px-4 py-3 text-[0.8125rem] leading-relaxed text-muted">
            <p>{PREVIEW}</p>
            <p
              className={`label-caps my-2 flex items-center gap-3 motion-safe:transition-opacity motion-safe:duration-500 ${
                stage === "raw" ? "opacity-40" : "opacity-100"
              }`}
              aria-hidden
            >
              <span className="h-px flex-1 bg-line-strong" />
              Gmail&apos;s preview ends here
              <span className="h-px flex-1 bg-line-strong" />
            </p>
            <p>{REST}</p>
          </div>
        </div>
      </div>

      {/* ---- the two live verdicts --------------------------------------- */}
      <div
        className={`grid motion-safe:transition-[grid-template-rows,opacity] motion-safe:duration-500 ${
          stage === "split" ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"
        }`}
        aria-hidden={stage !== "split"}
      >
        <div className="min-h-0 overflow-hidden">
          <div className="grid gap-2 border-t border-line-soft px-4 py-3 sm:grid-cols-2">
            <Chip
              source="preview only"
              category={fromPreview.category}
              confidence={fromPreview.confidence}
              note="reads as a confirmation — wrong"
            />
            <Chip
              source="whole body"
              category={fromBody.category}
              confidence={fromBody.confidence}
              note="the real outcome"
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
        A synthetic email — the verdicts are computed live in this tab by the shipped rules layer.
      </p>
    </div>
  );
}
