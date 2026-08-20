"use client";

import { useEffect, useRef, useState } from "react";

import { DECISION, PRIVACY } from "@/components/marketing/copy";
import { PREVIEW_CHARS } from "@/components/marketing/verdictEmailData";
import { trackProgress } from "@/components/marketing/scrub";

/**
 * Candidate 09 — the travelling spine, at miniature scale.
 *
 * One element that never resets: a rule in the gutter that fills with the
 * reader's progress, and a bead riding it that jogs LEFT or RIGHT at each
 * phase handoff — the side the bead sits on is the side the landing's
 * pinned rail would sit on, so the page's alternation becomes something you
 * can watch instead of something you infer. At each handoff the bead's tick
 * shows that phase's machine value, single-sourced from copy.ts /
 * verdictEmailData.ts — the spine never states a number of its own.
 *
 * Reduced motion (and no-JS, and pre-hydration): the spine renders fully
 * drawn with all four ticks placed — a composed diagram of the same truth,
 * nothing gated behind the scrub.
 */

const PHASES = [
  { name: "window act", side: "left", value: DECISION.rulesF1, what: "rules stage macro-F1" },
  { name: "verdict", side: "right", value: String(PREVIEW_CHARS), what: "Gmail's snippet budget, chars" },
  { name: "decision", side: "left", value: DECISION.cascadeF1, what: "full cascade macro-F1" },
  { name: "retention", side: "right", value: PRIVACY.testPath, what: "the enforcement test" },
] as const;

export function SpineDemo() {
  const runwayRef = useRef<HTMLDivElement>(null);
  const fillRef = useRef<HTMLDivElement>(null);
  const beadRef = useRef<HTMLDivElement>(null);
  const [phase, setPhase] = useState<number | null>(null);

  useEffect(() => {
    const runway = runwayRef.current;
    if (!runway) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    return trackProgress(runway, { from: 0.6, to: 0.4 }, (p) => {
      if (fillRef.current) fillRef.current.style.transform = `scaleY(${p})`;
      if (beadRef.current) beadRef.current.style.top = `${p * 100}%`;
      setPhase(Math.min(PHASES.length - 1, Math.floor(p * PHASES.length)));
    });
  }, []);

  // Pre-hydration / reduced-motion: the composed diagram — spine full, every
  // tick placed. `phase === null` is that state; a scrub frame replaces it.
  const composed = phase === null;
  const current = PHASES[phase ?? 0];

  return (
    <div ref={runwayRef} className="relative mx-auto h-[160vh] max-w-3xl">
      {/* the spine */}
      <div aria-hidden className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-line-strong">
        <div
          ref={fillRef}
          className="h-full w-full origin-top bg-viz-rules"
          style={{ transform: composed ? "scaleY(1)" : "scaleY(0)" }}
        />
      </div>

      {/* the travelling bead — hidden in the composed state, where the ticks carry it */}
      {!composed && (
        <div
          ref={beadRef}
          aria-hidden
          className={`absolute left-1/2 z-10 flex -translate-y-1/2 items-center gap-2 transition-transform duration-300 ${
            current.side === "left" ? "-translate-x-[calc(100%+0.75rem)]" : "translate-x-3"
          }`}
          style={{ top: "0%" }}
        >
          {current.side === "right" && <span className="h-2 w-2 rounded-full bg-viz-rules" />}
          <span className="whitespace-nowrap font-mono text-xs text-strong">{current.value}</span>
          {current.side === "left" && <span className="h-2 w-2 rounded-full bg-viz-rules" />}
        </div>
      )}

      {/* the phases: blocks alternating sides, each with its handoff tick */}
      {PHASES.map((p, i) => (
        <div
          key={p.name}
          className={`absolute w-[44%] ${p.side === "left" ? "left-0 text-right" : "right-0"}`}
          style={{ top: `${(i / PHASES.length) * 100 + 4}%` }}
        >
          <p className="label-caps">{p.name}</p>
          <p className="mt-1 text-xs text-dim">
            rail {p.side === "left" ? "on the left" : "on the right"} — the bead jogs here
          </p>
          <p className="mt-2 break-all font-mono text-xs text-muted">
            {p.value} <span className="text-dim">· {p.what}</span>
          </p>
        </div>
      ))}
    </div>
  );
}
