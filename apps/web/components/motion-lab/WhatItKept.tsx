"use client";

import { useMemo, useState } from "react";

import { PREVIEW_CHARS, VERDICT_EMAIL } from "@/components/marketing/verdictEmailData";

import type { Director } from "./director";
import { TakeStage } from "./TakeStage";
import { buildTraceView, categoryWord, segments } from "./traceEvidence";

/**
 * 02b — what it kept: the retention policy, enacted. The mail sits fully
 * read, deciding phrases lit; then the prose dissolves — the unlit
 * sentences first, and a beat later the lit ones too, because Applied keeps
 * the DECISION, not the correspondence — and what remains is the record the
 * database actually holds, in the same kept-record grammar the landing's
 * retention exhibit uses.
 *
 * Two honesty rails, stated because a dissolve can lie in two directions:
 * this visibly happens to APPLIED'S COPY, inside Applied's frame — Gmail
 * keeps the original untouched — and the record shown is the real shape
 * (subject, sender, an 80-character snippet, the verdict; body columns
 * never written). The sentence that decided the verdict is NOT in it,
 * which is the exhibit's closing beat: even the deciding phrase isn't
 * kept — only the decision is.
 */

const { senderName, senderEmail, subject, body } = VERDICT_EMAIL;

/** 0 mail lit · 1 prose dissolves, lit phrases hold · 2 phrases go too and
 *  the kept record rises · 3 settle, gentle push-in on the record. */
type Phase = 0 | 1 | 2 | 3;

export function WhatItKept() {
  const view = useMemo(() => buildTraceView(), []);
  const word = categoryWord(view.category);
  const [phase, setPhase] = useState<Phase>(3);

  const take = async (d: Director) => {
    setPhase(0);
    d.say(`The ${word.toLowerCase()} is found — every deciding phrase lit.`);
    await d.hold(2300);
    setPhase(1);
    d.say("Now the mail dissolves. This is Applied's copy — your Gmail keeps the original.");
    await d.hold(2100);
    setPhase(2);
    d.say("Even the lit phrases go: they were read and used, never stored.");
    await d.hold(1900);
    setPhase(3);
    d.say("What remains is the record: enough to explain the verdict, nothing to leak.");
    await d.hold(800);
  };

  const dim = (mark: boolean) => {
    if (phase === 0) return mark ? "lit" : "plain";
    if (phase === 1) return mark ? "lit" : "gone";
    return "gone";
  };

  const seg = (cls: string) =>
    cls === "lit"
      ? "rounded-sm bg-viz-rules/15 px-0.5 text-strong shadow-[inset_0_-1px_0_var(--viz-rules)]"
      : cls === "gone"
        ? "opacity-[0.14] blur-[1.5px] grayscale"
        : "";

  const renderField = (text: string, field: "subject" | "body") =>
    segments(text, field === "subject" ? view.subjectRanges : view.bodyRanges).map((part, i) => (
      <span
        key={i}
        className={`transition-all duration-700 ${seg(dim(part.mark))}`}
      >
        {part.text}
      </span>
    ));

  const kept = [
    { k: "subject", v: subject },
    { k: "sender_email", v: senderEmail },
    { k: "body_snippet", v: `${body.slice(0, 80)}…` },
    { k: "classified_as", v: view.category },
  ];

  return (
    <TakeStage
      take={take}
      height={500}
      frameLabel="live verdict — the kept record is the real retained shape, nothing more"
      opening="The mail dissolves; the record remains. Retention as a scene, not a paragraph."
    >
      <div className="mx-auto max-w-[34rem]">
        <div
          className={`overflow-hidden rounded-xl border border-line-soft bg-surface transition-transform duration-1000 ${
            phase === 3 ? "scale-[1.02]" : "scale-100"
          }`}
        >
          <div className="border-b border-line-soft px-4 py-3">
            <div className="flex items-start justify-between gap-3">
              <p className="min-w-0 text-sm font-medium text-strong">
                {renderField(subject, "subject")}
              </p>
              <span className="label-caps inline-flex shrink-0 items-center gap-1.5 rounded-full border border-viz-rules/40 px-2.5 py-1 text-viz-rules">
                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-viz-rules" />
                {word}
              </span>
            </div>
            <p className="mt-0.5 text-xs text-dim">
              {senderName} · <span className="font-mono">{senderEmail}</span>
            </p>
          </div>

          <div
            className={`grid transition-[grid-template-rows] duration-1000 ${
              phase >= 2 ? "grid-rows-[0.4fr]" : "grid-rows-[1fr]"
            }`}
          >
            <div className="min-h-0 overflow-hidden">
              <div className="px-4 py-3 text-[0.8125rem] leading-relaxed text-muted">
                {renderField(body, "body")}
              </div>
            </div>
          </div>

          {/* The kept record — the same shape the landing's retention exhibit
              states, because it is the same fact. */}
          <div
            className={`grid transition-[grid-template-rows,opacity] duration-1000 ${
              phase >= 2 ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"
            }`}
            aria-hidden={phase < 2}
          >
            <div className="min-h-0 overflow-hidden">
              <dl className="divide-y divide-line-soft border-t border-line-soft text-[0.8125rem]">
                {kept.map((row) => (
                  <div
                    key={row.k}
                    className="grid grid-cols-[8.5rem_minmax(0,1fr)] gap-2 px-4 py-2"
                  >
                    <dt className="font-mono text-xs leading-5 text-strong">{row.k}</dt>
                    <dd className="truncate leading-5 text-muted">{row.v}</dd>
                  </div>
                ))}
                {["body_text", "body_html"].map((k) => (
                  <div key={k} className="grid grid-cols-[8.5rem_minmax(0,1fr)] gap-2 px-4 py-2">
                    <dt className="font-mono text-xs leading-5 text-dim line-through decoration-line-strong">
                      {k}
                    </dt>
                    <dd className="leading-5 text-dim">never written</dd>
                  </div>
                ))}
              </dl>
            </div>
          </div>

          <p className="border-t border-line-soft px-4 py-2.5 text-[11px] leading-relaxed text-dim">
            A synthetic email, verdict computed live in this tab. The snippet the record keeps ends
            at character 80 — the sentence that decided the verdict starts at character{" "}
            {PREVIEW_CHARS + 1}, and is not kept.
          </p>
        </div>
      </div>
    </TakeStage>
  );
}
