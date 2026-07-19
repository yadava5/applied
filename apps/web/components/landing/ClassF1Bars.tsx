"use client";

import { useState, type CSSProperties } from "react";
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
 *
 * Motion is enhancement only: each bar draws in from zero (`.bar-grow`, keyed to
 * the Reveal wrapper) with a one-shot sheen sweep, and hovering a row lifts it
 * out while the others dim — the exact F1 is always printed, so nothing is
 * gated behind the interaction. All of it flattens under reduced-motion.
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
  const [hovered, setHovered] = useState<number | null>(null);

  return (
    <Reveal className="rounded-xl border border-line-soft bg-surface p-4 sm:p-5">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <span className="label-mono">per-class F1 · held-out eval · v3</span>
        <span className="font-mono text-[11px] text-dim">8 learned classes · all clear 0.95</span>
      </div>

      <div className="grid grid-cols-[6.5rem_1fr_2.9rem] items-center gap-x-3 gap-y-1.5 sm:grid-cols-[8.5rem_1fr_2.9rem]">
        {CLASSES.map((c, i) => {
          const dim = hovered !== null && hovered !== i;
          const active = hovered === i;
          return (
            <div
              key={c.label}
              className="contents"
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered(null)}
            >
              <span
                className="truncate font-mono text-[11px] transition-colors"
                style={{ color: active ? "var(--text-strong)" : "var(--text-muted)", opacity: dim ? 0.5 : 1 }}
              >
                {c.label}
              </span>
              <div
                className="relative h-3.5 overflow-hidden rounded bg-surface-2 transition-opacity"
                style={{ opacity: dim ? 0.5 : 1 }}
              >
                <div
                  className="bar-grow relative h-full rounded"
                  style={
                    {
                      "--bar-w": pct(c.f1),
                      "--i": i,
                      background:
                        "linear-gradient(90deg, color-mix(in oklab, var(--viz-setfit) 55%, transparent), var(--viz-setfit))",
                      boxShadow: active
                        ? "0 0 16px -3px var(--viz-setfit)"
                        : "0 0 10px -5px var(--viz-setfit)",
                      transition: "box-shadow 0.25s ease, width 1.1s cubic-bezier(0.22,1,0.36,1)",
                    } as CSSProperties
                  }
                >
                  {/* bright tip at the bar head */}
                  <span
                    className="absolute right-0 top-1/2 h-2 w-2 -translate-y-1/2 translate-x-1/2 rounded-full"
                    style={{ background: "var(--viz-setfit)", boxShadow: "0 0 8px 0 var(--viz-setfit)" }}
                    aria-hidden
                  />
                  {/* one-shot sheen sweep on draw-in */}
                  <span
                    className="f1-sheen absolute inset-y-0 left-0 w-8 -skew-x-12"
                    style={
                      {
                        "--i": i,
                        background:
                          "linear-gradient(90deg, transparent, rgb(255 255 255 / 0.55), transparent)",
                      } as CSSProperties
                    }
                    aria-hidden
                  />
                </div>
                {/* 0.95 CI-floor marker */}
                <div
                  className="absolute inset-y-0 z-10 w-px"
                  style={{ left: pct(GATE), background: "var(--amber)", opacity: 0.85 }}
                  aria-hidden
                />
              </div>
              <span
                className="tabular text-right font-mono text-[11px] transition-all"
                style={{
                  color: active ? "var(--viz-setfit)" : "var(--text-strong)",
                  opacity: dim ? 0.5 : 1,
                }}
              >
                {c.f1.toFixed(3)}
              </span>
            </div>
          );
        })}
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
