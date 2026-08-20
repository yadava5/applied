import type { Metadata } from "next";

import { MotionLab } from "@/components/motion-lab/MotionLab";

/** A private selection surface: never linked, never indexed. Round two
 *  dropped the benchmark plate (10), so this route no longer reads
 *  `lib/benchmark/baseline-v3.generated.json`; `scripts/gen-benchmark-facts.mjs`
 *  stays — a working, proven-able-to-fail derivation gate is worth keeping
 *  for the next surface that quotes the benchmark. */
export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function MotionLabPage() {
  return <MotionLab />;
}
