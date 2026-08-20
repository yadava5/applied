import { readFileSync } from "node:fs";
import path from "node:path";

import type { Metadata } from "next";

import { MotionLab } from "@/components/motion-lab/MotionLab";

/**
 * /motion-lab — a private selection surface for the landing's candidate
 * motion treatments. Deliberately unreachable except by URL: no nav link
 * anywhere, and robots below refuses indexing. Nothing on this route ships
 * to `/`; it exists so the owner can pick treatments by ID instead of
 * commissioning builds sight-unseen.
 */
export const metadata: Metadata = {
  title: "Motion lab",
  robots: { index: false, follow: false },
};

/** The artifact the 0.979 headline is transcribed from (see ClassF1Bars).
 *  Read at render for plate 10's derive-and-diff; resolved from the repo
 *  root because the file lives with the backend, outside this app. */
const ARTIFACT = path.join(
  process.cwd(),
  "..",
  "..",
  "backend",
  "data",
  "evaluation",
  "baseline_hybrid_v3.json",
);

interface EvalArtifact {
  per_label: Record<string, { f1: number }>;
  overall: { macro_f1: number };
  meta: { generated_at: string };
}

export default function MotionLabPage() {
  const artifact = JSON.parse(readFileSync(ARTIFACT, "utf8")) as EvalArtifact;
  const derivedF1 = Object.entries(artifact.per_label).map(([label, m]) => ({
    label,
    f1: m.f1,
  }));

  return (
    <MotionLab
      derivedF1={derivedF1}
      macroF1={artifact.overall.macro_f1}
      generatedAt={artifact.meta.generated_at}
    />
  );
}
