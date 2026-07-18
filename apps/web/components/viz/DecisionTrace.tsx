"use client";

import { useState } from "react";
import { DEMO_REVIEW_QUEUE, type DemoReviewItem } from "@/lib/demo/demoData";

const LAYERS = [
  { id: "rules", label: "rules", note: "201 regex rules — instant, deterministic", color: "var(--viz-rules)" },
  { id: "embeddings", label: "e5", note: "e5 embedding similarity — semantic match", color: "var(--viz-embeddings)" },
  { id: "setfit", label: "SetFit", note: "SetFit few-shot head — the learned call", color: "var(--viz-setfit)" },
] as const;

const GATE = 0.85;

function layerIndex(method: DemoReviewItem["method"]) {
  return LAYERS.findIndex((l) => l.id === method);
}

/**
 * The signature JobTracker visual: every email's verdict traced through the
 * three-layer pipeline. The layer that *fired* lights in its own hue; layers
 * before it passed the email on, layers after weren't needed. A confidence
 * meter is drawn against the 0.85 auto-file gate — below it, a human presides.
 */
export function DecisionTrace() {
  const [open, setOpen] = useState<string | null>(DEMO_REVIEW_QUEUE[0]?.subject ?? null);

  return (
    <div className="overflow-hidden rounded-xl border border-line-soft bg-surface">
      {/* Legend */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-line-soft px-4 py-3">
        {LAYERS.map((l, i) => (
          <span key={l.id} className="flex items-center gap-2 font-mono text-[11px] text-muted">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: l.color }}
            />
            <span className="text-dim">{i + 1}</span> {l.label}
          </span>
        ))}
        <span className="ml-auto flex items-center gap-2 font-mono text-[11px] text-review">
          <span className="inline-block h-2 w-2 rounded-full bg-review" /> below {GATE} → human
        </span>
      </div>

      <ul className="divide-y divide-line-soft">
        {DEMO_REVIEW_QUEUE.map((item) => {
          const fired = layerIndex(item.method);
          const isOpen = open === item.subject;
          const pct = Math.round(item.confidence * 100);
          return (
            <li key={item.subject}>
              <button
                type="button"
                onClick={() => setOpen(isOpen ? null : item.subject)}
                className="flex w-full flex-wrap items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-2"
              >
                {/* basis-full on mobile gives the subject its own line so the
                    layer track / verdict / % wrap below instead of squeezing it
                    to a few characters; sm+ restores the single-row layout. */}
                <div className="min-w-0 basis-full sm:basis-0 sm:flex-1">
                  <p className="truncate text-sm text-strong">{item.subject}</p>
                  <p className="truncate font-mono text-[11px] text-dim">{item.from}</p>
                </div>

                {/* Layer track */}
                <div className="flex items-center gap-1" aria-hidden>
                  {LAYERS.map((l, i) => {
                    const isFired = i === fired;
                    const passed = i < fired;
                    return (
                      <span key={l.id} className="flex items-center">
                        <span
                          className="grid h-6 w-6 place-items-center rounded-md border font-mono text-[10px] transition"
                          style={
                            isFired
                              ? { borderColor: l.color, color: l.color, background: `color-mix(in oklab, ${l.color} 16%, transparent)`, boxShadow: `0 0 14px -4px ${l.color}` }
                              : { borderColor: "var(--line)", color: passed ? "var(--text-dim)" : "var(--text-dim)", opacity: passed ? 0.7 : 0.35 }
                          }
                        >
                          {passed ? "✓" : i + 1}
                        </span>
                        {i < LAYERS.length - 1 && (
                          <span
                            className="h-px w-3"
                            style={{ background: i < fired ? "var(--line-strong)" : "var(--line-soft)" }}
                          />
                        )}
                      </span>
                    );
                  })}
                </div>

                {/* Verdict */}
                {item.needsReview ? (
                  <span className="rounded-full border border-review/40 px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-review">
                    human review
                  </span>
                ) : (
                  <span className="rounded-full border border-line px-2.5 py-0.5 font-mono text-[11px] uppercase tracking-wide text-foreground">
                    {item.category.replace("_", " ")}
                  </span>
                )}
                <span
                  className="tabular w-12 text-right font-mono text-xs"
                  style={{ color: item.needsReview ? "var(--amber)" : "var(--green)" }}
                >
                  {pct}%
                </span>
              </button>

              {/* Expanded trace */}
              {isOpen && (
                <div className="border-t border-line-soft bg-surface-2/50 px-4 py-4">
                  <p className="mb-3 font-mono text-[11px] text-muted">
                    Fired at layer {fired + 1} · <span style={{ color: LAYERS[fired].color }}>{LAYERS[fired].note}</span>
                  </p>
                  {/* Confidence meter vs gate */}
                  <div className="relative h-2 rounded-full bg-surface">
                    <div
                      className="absolute inset-y-0 left-0 rounded-full"
                      style={{
                        width: `${pct}%`,
                        background: item.needsReview ? "var(--amber)" : LAYERS[fired].color,
                      }}
                    />
                    {/* gate line */}
                    <div
                      className="absolute inset-y-[-4px] w-px bg-line-strong"
                      style={{ left: `${GATE * 100}%` }}
                    />
                  </div>
                  <div className="mt-1.5 flex justify-between font-mono text-[10px] text-dim">
                    <span>0%</span>
                    <span style={{ marginLeft: `${GATE * 100 - 8}%` }}>gate {GATE}</span>
                    <span>100%</span>
                  </div>
                  <p className="mt-3 font-mono text-[11px] leading-relaxed text-dim">
                    {item.needsReview
                      ? "Confidence sits below the 0.85 gate, so nothing is auto-filed — the email waits for a human, and the correction becomes new SetFit training data."
                      : `Confidence clears the 0.85 gate, so JobTracker files this as “${item.category.replace("_", " ")}” automatically.`}
                  </p>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
