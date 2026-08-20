"use client";

import { useEffect, useMemo, useState } from "react";

import { ReviewQueue } from "@/components/dashboard/ReviewQueue";
import { showcaseApplications } from "@/components/marketing/showcase";
import { todayISO } from "@/lib/dashboard/age";

import type { Director } from "./director";
import { TakeStage } from "./TakeStage";
import { cedarReviewItem, TRIO } from "./heldCast";

/**
 * 08c — where it waits: the held mail's journey, not the human's. Cedar's
 * ambiguous note starts full-size — the mail 08a just refused to guess
 * about — then settles into the REAL review queue beneath it, as its first
 * row, on the board it will wait on. Nothing vanishes and nothing is
 * guessed: the mail keeps its place and its open question until a person
 * answers it.
 *
 * No camera, no pointer — the object itself travels. The queue is the
 * shipped component over the showcase board's rows, so the tray shown is
 * exactly the tray the product mounts.
 */
export function WhereItWaits() {
  const cedar = TRIO[2]!;
  // Deferred off the effect body — the house rule every fixture mount follows.
  const [today, setToday] = useState<string | null>(null);
  useEffect(() => {
    const id = window.setTimeout(() => setToday(todayISO()), 0);
    return () => window.clearTimeout(id);
  }, []);
  const apps = useMemo(() => (today ? showcaseApplications(today) : []), [today]);

  /** 0 the mail alone · 1 it compresses and the queue opens beneath. */
  const [phase, setPhase] = useState<0 | 1>(1);

  const take = async (d: Director) => {
    setPhase(0);
    d.say("The mail Applied wouldn't guess about.");
    await d.hold(2200);
    setPhase(1);
    d.say("It doesn't vanish and it isn't filed — it takes its place in the review queue, on your board, question still open.");
    await d.hold(2400);
    d.say("Nothing is lost while you decide: the mail keeps its place, the board keeps its truth.");
    await d.hold(800);
  };

  return (
    <TakeStage
      take={take}
      height={470}
      frameLabel="the real review queue — the held mail lands where the product actually puts it"
      opening="A held mail doesn't disappear; watch where it goes."
    >
      <div className="mx-auto max-w-3xl">
        <article
          className={`overflow-hidden rounded-xl border bg-surface transition-all duration-700 ${
            phase === 0 ? "border-review/40" : "scale-[0.985] border-line-soft opacity-90"
          }`}
        >
          <div className="border-b border-line-soft px-4 py-3">
            <div className="flex items-start justify-between gap-3">
              <p className="text-sm font-medium text-strong">{cedar.subject}</p>
              <span className="label-caps inline-flex shrink-0 items-center gap-1.5 rounded-full border border-review/50 px-2.5 py-1 text-review">
                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-review" />
                held
              </span>
            </div>
            <p className="mt-0.5 font-mono text-xs text-dim">{cedar.sender}</p>
          </div>
          <div
            className={`grid transition-[grid-template-rows,opacity] duration-700 ${
              phase === 0 ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"
            }`}
            aria-hidden={phase === 1}
          >
            <div className="min-h-0 overflow-hidden">
              <p className="px-4 py-3 text-[0.8125rem] leading-relaxed text-muted">{cedar.body}</p>
            </div>
          </div>
        </article>

        <div
          className={`mt-4 transition-all duration-700 ${
            phase === 1 ? "translate-y-0 opacity-100" : "translate-y-2 opacity-0"
          }`}
          aria-hidden={phase === 0}
        >
          {today && <ReviewQueue items={[cedarReviewItem(today)]} applications={apps} />}
        </div>
      </div>
    </TakeStage>
  );
}
