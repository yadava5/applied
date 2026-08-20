"use client";

import { FOOTAGE } from "@/components/marketing/copy";
import { CLIPS } from "@/components/marketing/footage";
import { ProductClip } from "@/components/marketing/ProductClip";
import { FidelityStamp } from "./Plate";

/**
 * Candidate 04 — fixing the import clip's scale, shown at real size.
 *
 * The measured defect: every clip displays at 478 CSS px whatever the
 * viewport, and the import clip's authored crop is 744 CSS px of product —
 * so its 11–14px product type renders at 0.64×, the worst-read exhibit on
 * the page. The encode is 1152 device px, so the honest display ceiling is
 * 576 CSS (1152 ÷ 2× screens): past that the encode undersamples and
 * "bigger" starts showing mush.
 *
 * Two fixes, one live and one storyboarded:
 *
 *   A (live)  — widen the display box to the 576 ceiling. Product type
 *               reaches 0.77×. Free, honest, and the most this footage can
 *               give.
 *   B (story) — re-CAPTURE at a ~600px viewport, the way the rules clip was
 *               (534px crop → 0.89× displayed). /import is responsive, so
 *               the layout reflows into a crop that fits the ceiling at 2×
 *               and product type displays at ~1×. Needs a footage run; no
 *               CSS preview is shown because cropping the current wide
 *               layout cuts through its own copy — the fix is a reflow, not
 *               a crop.
 */

/** Authored crop widths, CSS px — from scripts/footage/scenes.mjs. */
const IMPORT_CROP = 744;
const RULES_CROP = 534;

/** The landing's current display width for every rail clip, measured. */
const CURRENT = 478;

/** The honest ceiling: encode width ÷ 2 (device px per CSS px). */
const CEILING = CLIPS.importClassifies.width / 2;

const scaleAt = (shown: number, crop: number) => (shown / crop).toFixed(2);

export function ClipScaleFix() {
  return (
    <div className="space-y-10">
      <div>
        <p className="label-caps mb-3">A — today&apos;s 478px box (the defect, at real size)</p>
        <div className="max-w-full" style={{ width: CURRENT }}>
          <ProductClip
            clip={CLIPS.importClassifies}
            name={FOOTAGE.import.name}
            caption={FOOTAGE.import.caption}
            stack
          />
        </div>
        <p className="mt-2 font-mono text-xs text-dim">
          {IMPORT_CROP} CSS authored → {CURRENT} shown = {scaleAt(CURRENT, IMPORT_CROP)}× product
          scale
        </p>
      </div>

      <div>
        <p className="label-caps mb-3">A — the same encode at the 576px ceiling</p>
        <div className="max-w-full" style={{ width: CEILING }}>
          <ProductClip
            clip={CLIPS.importClassifies}
            name={FOOTAGE.import.name}
            caption={FOOTAGE.import.caption}
            stack
          />
        </div>
        <p className="mt-2 font-mono text-xs text-dim">
          {IMPORT_CROP} CSS authored → {CEILING} shown = {scaleAt(CEILING, IMPORT_CROP)}× ·
          exactly 2× sampled ({CLIPS.importClassifies.width} ÷ {CEILING * 2} device px)
        </p>
      </div>

      <div className="rounded-xl border border-dashed border-review/40 p-5">
        <div className="flex flex-wrap items-center gap-3">
          <FidelityStamp fidelity="storyboard" />
          <p className="label-caps">B — re-capture /import at a ~600px viewport</p>
        </div>
        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-dim">
          The page is responsive: at ~600px the drop zone&apos;s copy wraps and the counters stack, so
          the whole take fits a crop near the 576 ceiling and product type displays at ~1× — the
          same staging that makes the rules clip the best-read recording on the page. For the
          pattern at real size, here is that clip in the same 478px box:
        </p>
        <div className="mt-4 max-w-full" style={{ width: CURRENT }}>
          <ProductClip
            clip={CLIPS.rulesReadTheBody}
            name={FOOTAGE.rules.name}
            caption={FOOTAGE.rules.caption}
            stack
          />
        </div>
        <p className="mt-2 font-mono text-xs text-dim">
          {RULES_CROP} CSS authored → {CURRENT} shown = {scaleAt(CURRENT, RULES_CROP)}× product
          scale
        </p>
      </div>
    </div>
  );
}
