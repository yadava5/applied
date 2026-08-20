"use client";

// ClassF1Bars is a client module; importing its CLASSES from a server
// component would hand over a reference, not the array (footage.ts scar).
import { ClassF1Bars, CLASSES } from "@/components/landing/ClassF1Bars";

/**
 * Candidate 10 — ClassF1Bars sourced from the artifact instead of hand-typed.
 *
 * The server side of this plate (app/motion-lab/page.tsx) reads
 * `backend/data/evaluation/baseline_hybrid_v3.json` — the file the 0.979
 * headline is transcribed from — at render and passes the per-class F1 down
 * as props. This component then diffs those derived numbers against the
 * hand-typed literals the live landing ships, and prints the verdict it
 * COMPUTED: the equality below is measured at render, not asserted in copy.
 *
 * The production shape would not be a runtime fs read (the artifact lives
 * outside the deploy): it is a build-time sync gate in the readme-facts
 * idiom — a script derives the literals from the artifact and CI fails when
 * they drift. This plate demonstrates the derivation and the diff; the gate
 * is the follow-up it argues for.
 */

export interface DerivedF1 {
  label: string;
  f1: number;
}

export function ArtifactF1({
  derived,
  macroF1,
  generatedAt,
}: {
  derived: DerivedF1[];
  macroF1: number;
  generatedAt: string;
}) {
  const rows = CLASSES.map((typed) => {
    const artifact = derived.find((d) => d.label === typed.label);
    return {
      label: typed.label,
      typed: typed.f1,
      derived: artifact?.f1 ?? null,
      match: artifact !== undefined && Math.abs(artifact.f1 - typed.f1) < 5e-5,
    };
  });
  const matches = rows.filter((r) => r.match).length;

  return (
    <div className="grid gap-8 lg:grid-cols-2 lg:items-start">
      <div>
        <p className="label-caps">Derived at render vs hand-typed on the live page</p>
        <div className="mt-3 grid grid-cols-[8.5rem_1fr_1fr_2rem] gap-x-3 gap-y-1 font-mono text-xs">
          <span className="text-dim">class</span>
          <span className="text-dim">artifact</span>
          <span className="text-dim">typed</span>
          <span className="text-dim">Δ</span>
          {rows.map((r) => (
            <div key={r.label} className="contents">
              <span className="truncate text-muted">{r.label}</span>
              <span className="tabular text-strong">{r.derived?.toFixed(4) ?? "—"}</span>
              <span className="tabular text-muted">{r.typed.toFixed(4)}</span>
              <span className={r.match ? "text-viz-rules" : "text-review"}>
                {r.match ? "=" : "≠"}
              </span>
            </div>
          ))}
        </div>
        <p className="mt-3 font-mono text-xs text-dim">
          {matches}/{rows.length} match to 4 dp · artifact macro-F1 {macroF1.toFixed(4)} ·
          generated {generatedAt.slice(0, 10)}
        </p>
        <p className="mt-3 max-w-sm text-xs leading-relaxed text-dim">
          Equal today — but nothing fails if the benchmark moves. The production fix is a
          build-time gate deriving these literals from the artifact, not a runtime read; this
          plate is the derivation working.
        </p>
      </div>
      <div>
        <p className="label-caps mb-3">The shipped component, unchanged</p>
        <ClassF1Bars />
      </div>
    </div>
  );
}
