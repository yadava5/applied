"use client";

import { useEffect, useMemo, useState } from "react";

import { ReviewQueue } from "@/components/dashboard/ReviewQueue";
import { todayISO } from "@/lib/dashboard/age";
import { cn } from "@/lib/utils";
import { showcaseApplications } from "./showcase";
import { cedarReviewItem, HELD_MAIL } from "./heldMail";

/**
 * The review rail's exhibit — the owner's 08c pick ("where it waits"),
 * running as the TAKE he picked it as: `ClaimsDescent` drives `settled` from
 * a `RailTake` script on a pausable clock — no director, no synthesized
 * pointer ("the object itself travels", the lab's own words), narrated
 * beat by beat, autoplaying once the rail is in view.
 *
 * Two beats. Cedar's ambiguous note starts full-size — the mail the rules
 * layer will not guess about — then settles into the REAL review queue
 * beneath it, as its first row. Nothing vanishes and nothing is guessed: the
 * mail keeps its place and its open question until a person answers it. The
 * queue is the shipped `ReviewQueue` over the showcase board's rows, so the
 * tray shown is exactly the tray the product mounts, stating the gate in the
 * product's own words ("held because Applied wasn't sure · your decision
 * files them") — no marketing copy restates it.
 *
 * INERT, deliberately. The queue's classify control POSTs to
 * /api/applications/review/*, and a marketing page must never wire a real
 * mutation path (the same boundary `landing-variants.test.mjs` holds against
 * `liveBoardTransport`). The board embed above earns its interactivity
 * through an in-memory transport; the queue has no transport seam, so it is
 * mounted as a specimen — real chrome, disarmed hand — rather than redrawn,
 * which the fabricated-design rule forbids.
 *
 * GEOMETRY. The exhibit CHANGES HEIGHT between beats — the card's body
 * collapses while the queue rises — which is why its rail rides the
 * viewport-tall self-centring box (the verdict rail's staging; see the rail
 * in `ClaimsDescent` for the measured argument) rather than a `--exhibit`
 * centring constant. The queue REGION is still height-reserved (`min-h`,
 * measured at 1024) through the client-only `today` mount, so the queue's
 * arrival is a fade into reserved ground, not a layout shift.
 *
 * Dates: the fixtures are dated relative to today, so the queue mounts
 * client-side only (`todayISO` in an effect — the house rule every fixture
 * mount follows; prerendering a relative date bakes the build day in).
 */
export function HeldExhibit({
  settled,
  queue = true,
}: {
  settled: boolean;
  /**
   * Whether the review queue renders beneath the card. `false` for the
   * below-`lg` inline snapshot, which shows the held mail alone: the shipped
   * `ReviewQueue` carries `id="needs-classification"`, and the rail copy
   * already holds that id — a second mount would ship a duplicate id in the
   * same document.
   */
  queue?: boolean;
}) {
  const [today, setToday] = useState<string | null>(null);
  useEffect(() => {
    const id = window.setTimeout(() => setToday(todayISO()), 0);
    return () => window.clearTimeout(id);
  }, []);
  const apps = useMemo(() => (today ? showcaseApplications(today) : []), [today]);
  const item = useMemo(() => (today ? cedarReviewItem(today) : null), [today]);

  return (
    <div>
      <article
        className={cn(
          "overflow-hidden rounded-xl border bg-surface motion-safe:transition-all motion-safe:duration-700",
          settled ? "scale-[0.985] border-line-soft opacity-90" : "border-review/40",
        )}
      >
        <div className="border-b border-line-soft px-4 py-3">
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm font-medium text-strong">{HELD_MAIL.subject}</p>
            <span className="label-caps inline-flex shrink-0 items-center gap-1.5 rounded-full border border-review/50 px-2.5 py-1 text-review">
              <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-review" />
              held
            </span>
          </div>
          <p className="mt-0.5 text-xs text-dim">
            {HELD_MAIL.company} · <span className="font-mono">{HELD_MAIL.sender}</span>
          </p>
        </div>
        <div
          className={cn(
            "grid motion-safe:transition-[grid-template-rows,opacity] motion-safe:duration-700",
            settled ? "grid-rows-[0fr] opacity-0" : "grid-rows-[1fr] opacity-100",
          )}
          aria-hidden={settled}
        >
          <div className="min-h-0 overflow-hidden">
            <p className="px-4 py-3 text-[0.8125rem] leading-relaxed text-muted">
              {HELD_MAIL.body}
            </p>
          </div>
        </div>
      </article>

      {/* The queue region is RESERVED whether or not the queue has mounted
          or the beat has arrived — the rail's centring constant is measured
          against this box and must not move under the reader. */}
      {queue && (
        <div
          className={cn(
            "mt-4 min-h-[14.25rem] motion-safe:transition-all motion-safe:duration-700",
            settled ? "translate-y-0 opacity-100" : "translate-y-2 opacity-0",
          )}
          aria-hidden={!settled}
          inert
        >
          {item && <ReviewQueue items={[item]} applications={apps} />}
        </div>
      )}
    </div>
  );
}
