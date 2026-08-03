/**
 * The booklet's page registry — single source of truth for ordering, parity,
 * and page-kind dispatch. Pure data: the validator script and the runtime
 * `Booklet.tsx` both consume this file, so it must stay JSX-free.
 *
 * Saddle-stitch parity (28-page book = 7 folded sheets): page 01 is a recto
 * (odd index), pages alternate recto/verso, and the page count is a multiple
 * of 4. `scripts/validate-parity.mjs` enforces this at PDF-export time.
 *
 * Two-page spreads (kind: "spread") MUST be a verso+recto pair on adjacent
 * indices so they face each other once bound.
 */

import type { SectionKey } from "./theme";

export type PageKind =
  | "cover"
  | "back-cover"
  | "endpaper"
  | "toc"
  | "divider"
  | "body"
  | "spread";

/** Body-page kinds — one per unique body content module. */
export type BodyKey =
  | "why-inbox"
  | "why-lossy"
  | "why-source"
  | "how-cascade"
  | "how-rules"
  | "how-embeddings"
  | "how-setfit"
  | "how-gate"
  | "inside-architecture"
  | "inside-onnx"
  | "inside-browser"
  | "proof-f1"
  | "proof-classes"
  | "proof-trace"
  | "proof-tests"
  | "sec-no-llm"
  | "sec-on-device"
  | "sec-gmail"
  | "build-stack"
  | "build-closing";

export type PageSpec =
  | { num: 1; kind: "cover"; parity: "recto"; sectionKey: null }
  | { num: 2; kind: "endpaper"; parity: "verso"; sectionKey: null }
  | { num: 3; kind: "toc"; parity: "recto"; sectionKey: null }
  | {
      num: number;
      kind: "divider";
      parity: "recto" | "verso";
      sectionKey: SectionKey;
      chapterNum: string;
      chapterTitle: string;
      subtitle: string;
      artSlot: string;
      chapterIndex: number;
      chapterTotal: number;
    }
  | {
      num: number;
      kind: "body";
      parity: "recto" | "verso";
      sectionKey: SectionKey;
      body: BodyKey;
    }
  | {
      num: number;
      kind: "spread";
      parity: "recto" | "verso";
      sectionKey: SectionKey;
      half: "left" | "right";
    }
  | { num: 32; kind: "back-cover"; parity: "verso"; sectionKey: null };

// ---------------------------------------------------------------------------
// Manifest — the 28 pages, in order.
// ---------------------------------------------------------------------------

export const PAGES: readonly PageSpec[] = [
  { num: 1, kind: "cover", parity: "recto", sectionKey: null },
  { num: 2, kind: "endpaper", parity: "verso", sectionKey: null },
  { num: 3, kind: "toc", parity: "recto", sectionKey: null },

  {
    num: 4, kind: "divider", parity: "verso", sectionKey: "01_WHY",
    chapterNum: "01", chapterTitle: "WHY",
    subtitle: "the verdict is already sitting in your inbox",
    artSlot: "/art/div-01-why.svg",
    chapterIndex: 1, chapterTotal: 6,
  },
  { num: 5, kind: "body", parity: "recto", sectionKey: "01_WHY", body: "why-inbox" },
  { num: 6, kind: "body", parity: "verso", sectionKey: "01_WHY", body: "why-lossy" },
  { num: 7, kind: "body", parity: "recto", sectionKey: "01_WHY", body: "why-source" },

  {
    num: 8, kind: "divider", parity: "verso", sectionKey: "02_HOW",
    chapterNum: "02", chapterTitle: "HOW",
    subtitle: "rules first · then similarity · then the learned head",
    artSlot: "/art/div-02-how.svg",
    chapterIndex: 2, chapterTotal: 6,
  },
  { num: 9, kind: "body", parity: "recto", sectionKey: "02_HOW", body: "how-cascade" },
  { num: 10, kind: "body", parity: "verso", sectionKey: "02_HOW", body: "how-rules" },
  { num: 11, kind: "body", parity: "recto", sectionKey: "02_HOW", body: "how-embeddings" },
  { num: 12, kind: "body", parity: "verso", sectionKey: "02_HOW", body: "how-setfit" },
  { num: 13, kind: "body", parity: "recto", sectionKey: "02_HOW", body: "how-gate" },

  {
    num: 14, kind: "divider", parity: "verso", sectionKey: "03_INSIDE",
    chapterNum: "03", chapterTitle: "INSIDE",
    subtitle: "the engine room — and the model that fits in a browser tab",
    artSlot: "/art/div-03-inside.svg",
    chapterIndex: 3, chapterTotal: 6,
  },
  { num: 15, kind: "body", parity: "recto", sectionKey: "03_INSIDE", body: "inside-architecture" },
  { num: 16, kind: "body", parity: "verso", sectionKey: "03_INSIDE", body: "inside-onnx" },
  { num: 17, kind: "body", parity: "recto", sectionKey: "03_INSIDE", body: "inside-browser" },

  {
    num: 18, kind: "divider", parity: "verso", sectionKey: "04_PROOF",
    chapterNum: "04", chapterTitle: "PROOF",
    subtitle: "what we measured — and the gate that guards it",
    artSlot: "/art/div-04-proof.svg",
    chapterIndex: 4, chapterTotal: 6,
  },
  { num: 19, kind: "body", parity: "recto", sectionKey: "04_PROOF", body: "proof-f1" },
  { num: 20, kind: "body", parity: "verso", sectionKey: "04_PROOF", body: "proof-classes" },
  { num: 21, kind: "body", parity: "recto", sectionKey: "04_PROOF", body: "proof-trace" },
  { num: 22, kind: "body", parity: "verso", sectionKey: "04_PROOF", body: "proof-tests" },

  {
    num: 23, kind: "divider", parity: "recto", sectionKey: "05_SECURITY",
    chapterNum: "05", chapterTitle: "SECURITY",
    subtitle: "no LLM reads the inbox · it can run on-device · Gmail is read-only",
    artSlot: "/art/div-05-security.svg",
    chapterIndex: 5, chapterTotal: 6,
  },
  { num: 24, kind: "body", parity: "verso", sectionKey: "05_SECURITY", body: "sec-no-llm" },
  { num: 25, kind: "body", parity: "recto", sectionKey: "05_SECURITY", body: "sec-on-device" },
  { num: 26, kind: "body", parity: "verso", sectionKey: "05_SECURITY", body: "sec-gmail" },

  {
    num: 27, kind: "divider", parity: "recto", sectionKey: "06_BUILD",
    chapterNum: "06", chapterTitle: "BUILD",
    subtitle: "train · register · export · ship",
    artSlot: "/art/div-06-build.svg",
    chapterIndex: 6, chapterTotal: 6,
  },
  { num: 28, kind: "spread", parity: "verso", sectionKey: "06_BUILD", half: "left" },
  { num: 29, kind: "spread", parity: "recto", sectionKey: "06_BUILD", half: "right" },
  { num: 30, kind: "body", parity: "verso", sectionKey: "06_BUILD", body: "build-stack" },
  { num: 31, kind: "body", parity: "recto", sectionKey: "06_BUILD", body: "build-closing" },

  { num: 32, kind: "back-cover", parity: "verso", sectionKey: null },
] as const;

// ---------------------------------------------------------------------------
// Invariants — enforced at validate-parity.mjs time.
// ---------------------------------------------------------------------------

/** Expected parity for a given 1-based page index: recto on odd, verso on even. */
export function expectedParity(num: number): "recto" | "verso" {
  return num % 2 === 1 ? "recto" : "verso";
}

/** Assert manifest invariants. Throws the first failure it encounters. */
export function assertManifestInvariants(): void {
  if (PAGES.length % 4 !== 0) {
    throw new Error(`saddle-stitch needs a multiple of 4 pages, got ${PAGES.length}`);
  }
  for (const p of PAGES) {
    if (p.parity !== expectedParity(p.num)) {
      throw new Error(
        `page ${p.num}: expected ${expectedParity(p.num)}, manifest says ${p.parity}`,
      );
    }
  }
  const spreads = PAGES.filter((p) => p.kind === "spread");
  if (spreads.length !== 2) {
    throw new Error(`expected exactly 2 spread pages, got ${spreads.length}`);
  }
  const [l, r] = spreads;
  if (!l || !r) throw new Error("spread pages missing");
  if (l.num + 1 !== r.num) {
    throw new Error(`spread pages must be adjacent: got num=${l.num} and num=${r.num}`);
  }
  if (l.parity !== "verso" || r.parity !== "recto") {
    throw new Error(`spread pages must be verso+recto; got ${l.parity}+${r.parity}`);
  }
}
