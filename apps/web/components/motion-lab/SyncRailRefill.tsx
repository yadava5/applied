"use client";

import { FOOTAGE, PRIVACY } from "@/components/marketing/copy";
import { CLIPS } from "@/components/marketing/footage";
import { ProductClip } from "@/components/marketing/ProductClip";
import { VerdictEmail } from "@/components/marketing/VerdictEmail";

/**
 * Candidate 03 — refilling the sync rail.
 *
 * The measured defect: the landing's retention rail pins for 1114px of
 * scroll — three to four times any other rail — carrying one 129px-tall
 * clip. This restage keeps the pin but gives the rail the WHOLE retention
 * sentence: the sync clip (the reading — mail going in) stacked over the
 * kept record (what comes out), so the rail's content is a fold's worth of
 * exhibit instead of a strip of it. The flowing column is the real
 * retention copy, spaced to a runway roughly half the current one.
 *
 * Honesty constraint carried over unchanged: the demo's Sync classifies
 * nothing — it commits pre-labelled fixture rows — so the clip's caption
 * stays scoped to the pass ("what it filed") and no words here may say the
 * classifier is deciding in that frame.
 */
export function SyncRailRefill() {
  return (
    <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,30rem)]">
      <div className="space-y-[30vh] py-[8vh]">
        <div>
          <p className="label-caps mb-3">{PRIVACY.eyebrow}</p>
          <h3 className="text-2xl font-medium tracking-tight text-strong">{PRIVACY.headline}</h3>
          <p className="mt-4 text-muted">{PRIVACY.scope}</p>
        </div>
        <p className="text-muted">{PRIVACY.retention}</p>
        <p className="text-muted">
          {PRIVACY.mechanism}{" "}
          <span className="break-all font-mono text-[0.8125rem] text-strong">
            {PRIVACY.testPath}
          </span>
        </p>
      </div>
      <div className="self-start lg:sticky lg:top-14">
        <ProductClip
          clip={CLIPS.boardSyncs}
          name={FOOTAGE.sync.name}
          caption={FOOTAGE.sync.caption}
          stack
        />
        <div className="mt-4">
          <VerdictEmail stage="retained" />
        </div>
      </div>
    </div>
  );
}
