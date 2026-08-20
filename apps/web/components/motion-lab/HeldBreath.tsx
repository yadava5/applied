"use client";

import { useMemo, useState } from "react";

import type { Director } from "./director";
import { TakeStage } from "./TakeStage";
import { trioVerdicts, type CastVerdict } from "./heldCast";
import { categoryWord } from "./traceEvidence";

/**
 * 08a — the held breath: two mails file fast (tick, tick), then the third
 * STOPS everything. The filed cards dim, an amber ring draws around the
 * ambiguous mail over a full second, and it settles as held — with NO top
 * guess shown, because under the bar the product's answer is the typed
 * null, and printing a guess would forge the decision it refuses to make.
 *
 * Staging a stop as the climactic beat is the point: 0.979 with no visible
 * hesitation reads as "too good". Every verdict below is computed live by
 * the shipped rules layer at render; nothing is hardcoded, and if the rules
 * change the cards re-verdict themselves.
 */

/** 0 none decided · 1,2 first/second filed · 3 the pause (dim + ring) ·
 *  4 the third held. At rest: 4. */
type Beat = 0 | 1 | 2 | 3 | 4;

function Card({ v, index, beat }: { v: CastVerdict; index: number; beat: Beat }) {
  const decided = v.held ? beat >= 4 : beat >= index + 1;
  const dimmed = beat === 3 && !v.held;
  const ringing = v.held && beat >= 3;
  return (
    <article
      className={`relative flex flex-col overflow-hidden rounded-xl border bg-surface transition-opacity duration-700 ${
        v.held && decided ? "border-review/40" : "border-line-soft"
      } ${dimmed ? "opacity-50" : "opacity-100"}`}
    >
      {/* The amber ring, drawn — not switched — around the mail that stops
          the room. Non-scaling stroke so the draw reads at any card size. */}
      {v.held && (
        <svg aria-hidden className="pointer-events-none absolute inset-0 z-10 h-full w-full">
          <rect
            x="1"
            y="1"
            width="calc(100% - 2px)"
            height="calc(100% - 2px)"
            rx="11"
            fill="none"
            stroke="var(--review)"
            strokeWidth="1.5"
            pathLength={100}
            strokeDasharray={100}
            strokeDashoffset={ringing ? 0 : 100}
            className="transition-[stroke-dashoffset] duration-1000 ease-out"
          />
        </svg>
      )}
      <div className="border-b border-line-soft px-4 py-3">
        <p className="text-sm font-medium text-strong">{v.mail.subject}</p>
        <p className="mt-0.5 font-mono text-xs text-dim">{v.mail.sender}</p>
      </div>
      <p className="flex-1 px-4 py-3 text-[0.8125rem] leading-relaxed text-muted">{v.mail.body}</p>
      <div className="min-h-[4.25rem] border-t border-line-soft px-4 py-3">
        <div
          className={`transition-all duration-500 ${
            decided ? "translate-y-0 opacity-100" : "translate-y-1 opacity-0"
          }`}
          aria-hidden={!decided}
        >
          {v.held ? (
            <>
              <p className="flex items-center gap-2">
                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-review" />
                <span className="text-sm font-medium text-review">Held for your review</span>
              </p>
              <p className="mt-1 text-xs text-dim">
                Applied wasn&apos;t sure — no verdict is written; your decision files it.
              </p>
            </>
          ) : (
            <>
              <p className="flex items-center gap-2">
                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-viz-rules" />
                <span className="text-sm font-medium text-strong">{categoryWord(v.category)}</span>
              </p>
              <p className="mt-1 text-xs text-dim">filed to your board</p>
            </>
          )}
        </div>
      </div>
    </article>
  );
}

export function HeldBreath() {
  const verdicts = useMemo(() => trioVerdicts(), []);
  const [beat, setBeat] = useState<Beat>(4);

  const take = async (d: Director) => {
    setBeat(0);
    d.say("Three mails land. Applied decides in the open.");
    await d.hold(1500);
    setBeat(1);
    d.say("The first files itself —");
    await d.hold(1000);
    setBeat(2);
    d.say("— the second too. Tick, tick.");
    await d.hold(1100);
    setBeat(3);
    d.say("The third stops everything. It is genuinely ambiguous…");
    await d.hold(2000);
    setBeat(4);
    d.say("…so nothing is written. Held for your review — the product refuses to guess.");
    await d.hold(800);
  };

  return (
    <TakeStage
      take={take}
      height={430}
      frameLabel="live verdicts — computed by the shipped engine at render, none hardcoded"
      opening="Two file fast; the third stops the room. The hesitation is the feature."
    >
      <div className="grid gap-4 lg:grid-cols-3">
        {verdicts.map((v, i) => (
          <Card key={v.mail.subject} v={v} index={i} beat={beat} />
        ))}
      </div>
      <p className="mt-4 max-w-2xl text-xs leading-relaxed text-dim">
        Synthetic mails; live verdicts. The held card commits no category — under the bar the
        answer is &ldquo;a human decides&rdquo;, which is what keeps the accuracy story believable.
      </p>
    </TakeStage>
  );
}
