"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { ApplicationRow } from "@/components/dashboard/ApplicationRow";
import { VERDICT_EMAIL } from "@/components/marketing/verdictEmailData";
import { todayISO } from "@/lib/dashboard/age";
import type { Application } from "@/lib/dashboard/summary";
import type { BoardTransport } from "@/lib/dashboard/transport";

import type { Director } from "./director";
import { TakeStage } from "./TakeStage";
import { buildTraceView, categoryWord, filesTo, segments } from "./traceEvidence";

/**
 * 02a — the highlighter: a reading light sweeps the mail once, at skim
 * speed; the phrases that decided catch light as it passes them — at the
 * offsets the scoring walk recorded, not at offsets chosen for the shot —
 * then the verdict stamps, and beside the mail the CONSEQUENCE plays: the
 * real board row flips its stage.
 *
 * The sweep is staging and says so in the caption: the verdict and the
 * spans are computed before the bar moves; the bar only reveals them. What
 * replaced the old mechanism column is the consequence surface — what
 * happened because of the reading, never how the reading is written.
 */

const { senderName, senderEmail, subject, body } = VERDICT_EMAIL;

/** In-memory no-ops so the real row cannot reach the live proxy from a lab
 *  page. The row renders and behaves; mutations land nowhere. */
const inertTransport: BoardTransport = {
  async changeStatus(_id, status) {
    return { ok: true, status };
  },
  async setDeadline() {
    return { ok: true };
  },
  async setRole() {
    return { ok: true };
  },
  async dismiss() {
    return { ok: true };
  },
  async deleteRow() {
    return { ok: true };
  },
  async detail() {
    return { ok: false, body: {} };
  },
};

export function Highlighter() {
  const view = useMemo(() => buildTraceView(), []);
  const word = categoryWord(view.category);
  const stage = filesTo(view.category) ?? "its stage";

  // null = at rest: everything lit (the SSR / reduced-motion state). The
  // set itself is only ever written from the take's own tween, never during
  // render — mark offsets live in a ref the ref-callbacks fill.
  const [litKeys, setLitKeys] = useState<ReadonlySet<string> | null>(null);
  const [scanY, setScanY] = useState<number | null>(null);
  const [stamped, setStamped] = useState(true);
  const [flipped, setFlipped] = useState(true);
  // The row renders client-side only: its age tag reads the calendar.
  // Deferred off the effect body — the house rule every fixture mount follows.
  const [today, setToday] = useState<string | null>(null);
  useEffect(() => {
    const id = window.setTimeout(() => setToday(todayISO()), 0);
    return () => window.clearTimeout(id);
  }, []);

  const cardRef = useRef<HTMLDivElement>(null);
  const markTops = useRef(new Map<string, number>());
  const registerMark = (key: string) => (el: HTMLElement | null) => {
    if (el) markTops.current.set(key, el.offsetTop);
  };

  const take = async (d: Director) => {
    setLitKeys(new Set());
    setScanY(0);
    setStamped(false);
    setFlipped(false);
    d.say("Applied reads the whole mail, not the first two lines — watch the pass.");
    await d.hold(900);
    const h = (cardRef.current?.scrollHeight ?? 420) + 40;
    const entries = Array.from(markTops.current.entries());
    let litCount = 0;
    await d.tween(3400, (t) => {
      const y = t * h;
      setScanY(y);
      const on = entries.filter(([, top]) => top <= y).map(([key]) => key);
      if (on.length !== litCount) {
        litCount = on.length;
        setLitKeys(new Set(on));
      }
    });
    setScanY(null);
    d.say("The phrases that decided stay lit — the mail's own words, recorded while it was scored.");
    await d.hold(1400);
    setStamped(true);
    d.say(`Verdict: ${word.toLowerCase()} — stamped on the mail…`);
    await d.hold(1300);
    setFlipped(true);
    d.say(`…and enacted on the board: the row moves to ${stage}, with this mail behind it.`);
    await d.hold(600);
  };

  const renderField = (text: string, field: "subject" | "body") =>
    segments(text, field === "subject" ? view.subjectRanges : view.bodyRanges).map((seg, i) => {
      if (!seg.mark) return <span key={i}>{seg.text}</span>;
      const key = `${field}-${seg.index}`;
      const lit = litKeys === null || litKeys.has(key);
      return (
        <mark
          key={i}
          ref={registerMark(key)}
          className={`rounded-sm px-0.5 transition-all duration-500 ${
            lit
              ? "bg-viz-rules/15 text-strong shadow-[inset_0_-1px_0_var(--viz-rules)]"
              : "bg-transparent text-inherit"
          }`}
        >
          {seg.text}
        </mark>
      );
    });

  const rowApp: Application | null = today
    ? {
        id: 9001,
        user_id: "demo",
        company: VERDICT_EMAIL.company,
        position: VERDICT_EMAIL.role,
        status: flipped ? "interviewing" : "applied",
        notes: flipped ? subject : "We received your application",
        created_at: `${today}T12:00:00.000Z`,
        source: "gmail",
        due_at: null,
        due_source: null,
      }
    : null;

  return (
    <TakeStage
      take={take}
      height={470}
      frameLabel="live verdict — spans recorded during scoring; the sweep only reveals them"
      opening="A reading light sweeps the mail; the deciding phrases hold; the board answers."
    >
      <div className="grid gap-6 lg:grid-cols-[minmax(0,30rem)_minmax(0,1fr)] lg:items-start">
        <div
          ref={cardRef}
          className="relative overflow-hidden rounded-xl border border-line-soft bg-surface"
        >
          {/* The reading light — staging, not measurement; see the header. */}
          {scanY !== null && (
            <div
              aria-hidden
              className="pointer-events-none absolute inset-x-0 top-0 z-10"
              style={{ transform: `translateY(${scanY}px)` }}
            >
              <div className="h-px bg-viz-rules/70" />
              <div className="h-10 bg-gradient-to-b from-viz-rules/10 to-transparent" />
            </div>
          )}
          <div className="border-b border-line-soft px-4 py-3">
            <div className="flex items-start justify-between gap-3">
              <p className="min-w-0 text-sm font-medium text-strong">
                {renderField(subject, "subject")}
              </p>
              <span
                className={`label-caps inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 transition-all duration-500 ${
                  stamped
                    ? "scale-100 border-viz-rules/40 text-viz-rules opacity-100"
                    : "scale-90 border-transparent text-transparent opacity-0"
                }`}
              >
                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-viz-rules" />
                {word}
              </span>
            </div>
            <p className="mt-0.5 text-xs text-dim">
              {senderName} · <span className="font-mono">{senderEmail}</span>
            </p>
          </div>
          <div className="px-4 py-3 text-[0.8125rem] leading-relaxed text-muted">
            {renderField(body, "body")}
          </div>
          <p className="border-t border-line-soft px-4 py-2.5 text-[11px] leading-relaxed text-dim">
            A synthetic email. The lit phrases are the ones the decision actually turned on —
            recorded while it was made, in this tab. The sweep is presentation; the verdict was
            computed before the bar moved.
          </p>
        </div>

        <div>
          <p className="label-caps">What happened because of it</p>
          <ul className="mt-3">
            {rowApp && (
              <li className="list-none">
                <ApplicationRow app={rowApp} today={today ?? undefined} transport={inertTransport} />
              </li>
            )}
          </ul>
          <p
            className={`mt-3 max-w-sm text-xs leading-relaxed transition-opacity duration-700 ${
              flipped ? "opacity-100" : "opacity-40"
            } text-dim`}
          >
            {flipped
              ? `The row moved to ${stage} and this mail joined its trail — the reading, enacted.`
              : "The row waits in Applied — the reading has not reached the board yet."}
          </p>
        </div>
      </div>
    </TakeStage>
  );
}
