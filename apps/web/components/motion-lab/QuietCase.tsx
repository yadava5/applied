"use client";

import { useMemo, useState } from "react";

import { VERDICT_EMAIL } from "@/components/marketing/verdictEmailData";

import type { Director } from "./director";
import { TakeStage } from "./TakeStage";
import { buildTraceView, categoryWord, filesTo, segments } from "./traceEvidence";

/**
 * 02c — the quiet case: no camera, no sweep. The deciding phrases light one
 * at a time and each is QUOTED beside the mail — the email's own words, cut
 * at the recorded offsets — then the verdict card closes the argument. The
 * restrained option of the family: evidence, then conclusion, at reading
 * pace.
 */

const { senderName, senderEmail, subject, body } = VERDICT_EMAIL;

export function QuietCase() {
  const view = useMemo(() => buildTraceView(), []);
  const word = categoryWord(view.category);
  const stage = filesTo(view.category);
  const total = view.evidence.length;

  // At rest (SSR / reduced motion): the full case, already made.
  const [lit, setLit] = useState(total);
  const [verdictShown, setVerdictShown] = useState(true);

  const take = async (d: Director) => {
    setLit(0);
    setVerdictShown(false);
    d.say("One mail, read in full.");
    await d.hold(1500);
    for (let i = 1; i <= total; i++) {
      setLit(i);
      d.say(
        i === 1
          ? "The first phrase that matters lights — and is quoted, verbatim."
          : "The next phrase joins the case…",
      );
      await d.hold(1250);
    }
    await d.hold(500);
    setVerdictShown(true);
    d.say("Then the conclusion — with its evidence standing beside it.");
    await d.hold(700);
  };

  const renderField = (text: string, field: "subject" | "body", offset: number) =>
    segments(text, field === "subject" ? view.subjectRanges : view.bodyRanges).map((part, i) =>
      part.mark ? (
        <mark
          key={i}
          className={`rounded-sm px-0.5 transition-all duration-500 ${
            offset + part.index < lit
              ? "bg-viz-rules/15 text-strong shadow-[inset_0_-1px_0_var(--viz-rules)]"
              : "bg-transparent text-inherit"
          }`}
        >
          {part.text}
        </mark>
      ) : (
        <span key={i}>{part.text}</span>
      ),
    );

  return (
    <TakeStage
      take={take}
      height={470}
      frameLabel="live verdict — quotes cut at the recorded offsets, in this tab"
      opening="The evidence, one phrase at a time; the verdict last."
    >
      <div className="grid gap-6 lg:grid-cols-[minmax(0,30rem)_minmax(0,1fr)] lg:items-start">
        <div className="overflow-hidden rounded-xl border border-line-soft bg-surface">
          <div className="border-b border-line-soft px-4 py-3">
            <p className="text-sm font-medium text-strong">{renderField(subject, "subject", 0)}</p>
            <p className="mt-0.5 text-xs text-dim">
              {senderName} · <span className="font-mono">{senderEmail}</span>
            </p>
          </div>
          <div className="px-4 py-3 text-[0.8125rem] leading-relaxed text-muted">
            {renderField(body, "body", view.subjectRanges.length)}
          </div>
          <p className="border-t border-line-soft px-4 py-2.5 text-[11px] leading-relaxed text-dim">
            A synthetic email. The lit phrases are the ones the decision turned on — recorded while
            it was made, never re-derived for display.
          </p>
        </div>

        <div>
          <p className="label-caps">The case</p>
          <ul className="mt-3 space-y-2">
            {view.evidence.map((ev, i) => (
              <li
                key={i}
                className={`rounded-lg border border-line-soft bg-surface px-3 py-2 transition-all duration-500 ${
                  i < lit ? "translate-y-0 opacity-100" : "translate-y-1 opacity-0"
                }`}
                aria-hidden={i >= lit}
              >
                <p className="text-sm leading-relaxed text-strong">&ldquo;{ev.quote}&rdquo;</p>
                <p className="mt-0.5 text-[11px] text-dim">
                  {ev.field === "subject" ? "in the subject line" : "in the body"}
                </p>
              </li>
            ))}
          </ul>
          <div
            className={`mt-4 rounded-lg border px-3 py-2.5 transition-all duration-500 ${
              verdictShown
                ? "translate-y-0 border-viz-rules/40 opacity-100"
                : "translate-y-1 border-transparent opacity-0"
            }`}
            aria-hidden={!verdictShown}
          >
            <p className="flex items-center gap-2">
              <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-viz-rules" />
              <span className="text-sm font-medium text-strong">{word}</span>
              {stage && <span className="text-xs text-dim">— filed to {stage}</span>}
            </p>
            <p className="mt-1 text-xs leading-relaxed text-dim">
              Every card on the board can answer &ldquo;why?&rdquo; like this — with the mail&apos;s
              own words, not a shrug.
            </p>
          </div>
        </div>
      </div>
    </TakeStage>
  );
}
