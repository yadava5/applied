import type { CSSProperties } from "react";
import { Reveal } from "./Reveal";

/**
 * Per-class F1 for the hybrid classifier v3, measured on the held-out eval and
 * read verbatim from backend/data/evaluation/baseline_hybrid_v3.json. Their
 * average is the 0.9791 macro-F1 headline — shown here so the weakest class is
 * visible rather than hidden behind an accuracy number.
 *
 * The bars are scaled to a 0.90–1.00 window (labeled as such) so the spread is
 * legible; the ┊ marker sits on the 0.95 CI floor that blocks merges. Every one
 * clears it.
 */

const AXIS_MIN = 0.9;
const GATE = 0.95;

const CLASSES: { label: string; f1: number }[] = [
  { label: "applied", f1: 1.0 },
  { label: "pending_application", f1: 1.0 },
  { label: "interview", f1: 1.0 },
  { label: "offer", f1: 1.0 },
  { label: "other", f1: 0.96 },
  { label: "assessment", f1: 0.96 },
  { label: "rejection", f1: 0.9565 },
  { label: "follow_up", f1: 0.9565 },
];

const pct = (v: number) => `${((v - AXIS_MIN) / (1 - AXIS_MIN)) * 100}%`;

export function ClassF1Bars() {
  return (
    <Reveal className="rounded-xl border border-line-soft bg-surface p-4 sm:p-5">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <span className="label-mono">per-class F1 · held-out eval · v3</span>
        <span className="font-mono text-[11px] text-dim">8 learned classes · all clear 0.95</span>
      </div>

      <div className="grid grid-cols-[6.5rem_1fr_2.9rem] items-center gap-x-3 gap-y-1.5 sm:grid-cols-[8.5rem_1fr_2.9rem]">
        {CLASSES.map((c, i) => (
          <div key={c.label} className="contents">
            <span className="truncate font-mono text-[11px] text-muted">{c.label}</span>
            <div className="relative h-3.5 overflow-hidden rounded bg-surface-2">
              <div
                className="bar-grow h-full rounded"
                style={
                  {
                    "--bar-w": pct(c.f1),
                    "--i": i,
                    background: "color-mix(in oklab, var(--viz-setfit) 85%, white 0%)",
                  } as CSSProperties
                }
              />
              {/* 0.95 CI-floor marker */}
              <div
                className="absolute inset-y-0 w-px"
                style={{ left: pct(GATE), background: "var(--amber)", opacity: 0.85 }}
                aria-hidden
              />
            </div>
            <span className="tabular text-right font-mono text-[11px] text-strong">{c.f1.toFixed(3)}</span>
          </div>
        ))}
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-line-soft pt-3 font-mono text-[10.5px] text-dim">
        <span>axis 0.90 —— 1.00</span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-3 w-px bg-review" aria-hidden />
          0.95 CI floor — merges fail below it
        </span>
      </div>
    </Reveal>
  );
}
