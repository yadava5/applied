import facts from "@/lib/benchmark/baseline-v3.generated.json";

import { MotionLab } from "@/components/motion-lab/MotionLab";

/** Plate 10 derives the per-class figures instead of trusting the hand-typed
 *  literal in `ClassF1Bars`. It reads a GENERATED file that lives inside this
 *  app, not the backend artifact directly.
 *
 *  That distinction is load-bearing and was learned the hard way: the first
 *  version did `readFileSync(process.cwd() + "/../../backend/...")`, which
 *  resolves in a local checkout and threw a 500 on every request in
 *  production, because Vercel's root directory for this project is `apps/web`
 *  and `backend/` is not in the deployment bundle. A serverless function
 *  cannot reach the repo root.
 *
 *  `scripts/gen-benchmark-facts.mjs` writes the file; `--check` fails if it
 *  drifts from the artifact, so the numbers stay derived rather than typed.
 *  Proven able to fail: mutating one f1 exits 1. */

export default function MotionLabPage() {
  const derivedF1 = Object.entries(facts.perLabel).map(([label, m]) => ({
    label,
    f1: m.f1,
  }));

  return (
    <MotionLab
      derivedF1={derivedF1}
      macroF1={facts.macroF1}
      generatedAt={facts.generatedAt}
    />
  );
}
