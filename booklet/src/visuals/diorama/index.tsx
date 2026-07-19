import React from "react";
import type { SectionKey } from "../../theme";
import { WhyManualDesk } from "./WhyManualDesk";
import { HowCascade } from "./HowCascade";
import { InsideEngine } from "./InsideEngine";
import { ProofPodium } from "./ProofPodium";
import { BuildScaffold } from "./BuildScaffold";

/**
 * Barrel + SectionKey → diorama component map. Each chapter divider pulls its
 * line-art from here: the lossy manual desk (WHY), the classifier cascade
 * (HOW), the in-browser engine (INSIDE), the verdict gauge (PROOF), and the
 * shipping scaffold (BUILD).
 */

export const DIORAMAS: Record<SectionKey, React.FC> = {
  "01_WHY": WhyManualDesk,
  "02_HOW": HowCascade,
  "03_INSIDE": InsideEngine,
  "04_PROOF": ProofPodium,
  "05_BUILD": BuildScaffold,
};

export { WhyManualDesk, HowCascade, InsideEngine, ProofPodium, BuildScaffold };
