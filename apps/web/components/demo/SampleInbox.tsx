"use client";

import { useMemo, useState } from "react";

import {
  GATE,
  SAMPLE_EMAILS,
  sampleInboxStats,
  type LayerId,
  type SampleEmail,
  type TraceStep,
} from "@/lib/demo/sampleInbox";
import { classifyWithRules } from "@/lib/demo/rulesLayer";

/**
 * The sample-inbox experience: eleven synthetic job-search emails, each shown
 * with the REAL verdict the shipped classifier produced (precomputed offline —
 * see `sampleInbox.ts`), an expandable three-layer decision trace, and the
 * 0.85 confidence gate. Layer 1 is additionally recomputed LIVE in the browser
 * so the trace is verifiably real, and a small playground lets a visitor run
 * layer 1 on their own text. No inbox is read; no network call is made.
 */

const LAYER_META: Record<LayerId, { n: number; label: string; color: string; blurb: string }> = {
  rules: { n: 1, label: "rules", color: "var(--viz-rules)", blurb: "201 regex rules — instant, deterministic" },
  embeddings: { n: 2, label: "e5", color: "var(--viz-embeddings)", blurb: "e5 embedding similarity — semantic match" },
  setfit: { n: 3, label: "SetFit", color: "var(--viz-setfit)", blurb: "SetFit few-shot head — the learned call" },
};

const CATEGORY_DOT: Record<string, string> = {
  offer: "var(--green)",
  interview: "var(--viz-rules)",
  assessment: "var(--viz-embeddings)",
  applied: "var(--text-muted)",
  pending_application: "var(--viz-embeddings)",
  follow_up: "var(--viz-setfit)",
  rejection: "var(--red)",
  needs_review: "var(--amber)",
  other: "var(--text-dim)",
};

function pct(n: number) {
  return `${Math.round(n * 100)}%`;
}

function pretty(category: string) {
  return category.replace(/_/g, " ");
}

function LayerTrack({ trace }: { trace: TraceStep[] }) {
  const firedIndex = trace.findIndex((t) => t.state === "answered");
  return (
    <div className="flex items-center gap-1" aria-hidden>
      {trace.map((step, i) => {
        const meta = LAYER_META[step.layer];
        const isFired = step.state === "answered";
        const passed = step.state === "passed";
        return (
          <span key={step.layer} className="flex items-center">
            <span
              className="grid h-6 w-6 place-items-center rounded-md border font-mono text-[10px]"
              style={
                isFired
                  ? {
                      borderColor: meta.color,
                      color: meta.color,
                      background: `color-mix(in oklab, ${meta.color} 16%, transparent)`,
                      boxShadow: `0 0 14px -4px ${meta.color}`,
                    }
                  : { borderColor: "var(--line)", color: "var(--text-dim)", opacity: passed ? 0.7 : 0.35 }
              }
            >
              {passed ? "→" : isFired ? meta.n : meta.n}
            </span>
            {i < trace.length - 1 && (
              <span
                className="h-px w-3"
                style={{ background: i < firedIndex ? "var(--line-strong)" : "var(--line-soft)" }}
              />
            )}
          </span>
        );
      })}
    </div>
  );
}

function ExpandedTrace({ email }: { email: SampleEmail }) {
  const { trace, needsReview, category } = email.verdict;
  const fired = trace.find((t) => t.state === "answered");
  const firedMeta = fired ? LAYER_META[fired.layer] : LAYER_META.setfit;
  const meterPct = Math.round(email.verdict.confidence * 100);

  // LIVE: recompute layer 1 in the browser, right now, from the raw text.
  const live = classifyWithRules(email.subject, email.body);
  const storedLayer1 = trace.find((t) => t.layer === "rules");
  // Did layer 1 render the FINAL call (answered ≥0.90), or pass it on?
  const rulesAnswered = storedLayer1?.state === "answered";
  // Sanity check: the live recompute reproduces the stored layer-1 confidence
  // exactly (same code, same rules) — proof the trace is genuine, not canned.
  const reproducesStored =
    storedLayer1?.confidence != null &&
    Math.abs(live.confidence - storedLayer1.confidence) < 0.001;

  return (
    <div className="border-t border-line-soft bg-surface-2/50 px-4 py-4">
      {/* per-layer rows */}
      <ol className="space-y-2">
        {trace.map((step) => {
          const meta = LAYER_META[step.layer];
          const dim = step.state === "skipped";
          return (
            <li key={step.layer} className="flex items-start gap-3 font-mono text-[11px]">
              <span
                className="mt-0.5 inline-block h-2 w-2 shrink-0 rounded-full"
                style={{ background: meta.color, opacity: dim ? 0.3 : 1 }}
                aria-hidden
              />
              <span className="w-16 shrink-0 text-dim">
                {meta.n} · {meta.label}
              </span>
              {/* The note is the payload of the trace — `never ran` is what says
                  layers 2 and 3 were skipped because layer 1 already cleared the
                  gate — so it does NOT drop a rank when the layer is skipped.
                  Measured on a production build at 1024, composited over the real
                  painted backdrop: `muted` is 10.7:1 / APCA Lc 70.2 at 11px here,
                  where `dim` was 8.98:1 / Lc 60.9 — passing AA but a hair over the
                  Lc 60 floor for secondary text, and the quietest thing in its own
                  row. (Older still was `text-dim/70`, 2.88:1 on the pre-raise
                  palette; that alpha is gone. See applied#79.) The skipped state
                  is carried by the dot's 0.3 opacity above and by the dim layer
                  name beside it, so the sentence itself never has to whisper. */}
              <span className="text-muted">
                {step.state === "answered" ? "answered — " : step.state === "passed" ? "passed — " : ""}
                {step.note}
              </span>
            </li>
          );
        })}
      </ol>

      {/* confidence meter vs the 0.85 gate */}
      <div className="mt-4">
        <div className="relative h-2 rounded-full bg-surface">
          <div
            className="absolute inset-y-0 left-0 rounded-full"
            style={{ width: `${meterPct}%`, background: needsReview ? "var(--amber)" : firedMeta.color }}
          />
          <div className="absolute inset-y-[-4px] w-px bg-line-strong" style={{ left: `${GATE * 100}%` }} />
        </div>
        <div className="mt-1.5 flex justify-between font-mono text-[10px] text-dim">
          <span>0%</span>
          <span style={{ marginLeft: `${GATE * 100 - 10}%` }}>gate {GATE}</span>
          <span>100%</span>
        </div>
      </div>

      <p className="mt-3 text-xs leading-relaxed text-dim">
        {needsReview
          ? "Confidence sits below the 0.85 gate, so nothing is auto-filed — the email waits for a human, and the correction becomes new SetFit training data."
          : `Confidence clears the 0.85 gate, so Applied files this as “${pretty(category)}” automatically.`}
      </p>

      {/* LIVE proof: layer 1 recomputed in-browser just now */}
      <p
        data-testid="live-rules"
        data-live-category={live.category}
        data-live-answered={rulesAnswered ? "yes" : "no"}
        data-live-reproduces={reproducesStored ? "yes" : "no"}
        className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-line-soft pt-3 font-mono text-[11px] text-dim"
      >
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: "var(--viz-rules)" }} aria-hidden />
          layer 1 recomputed live in your browser:
        </span>
        <span className="text-muted">
          {pretty(live.category)} @ {pct(live.confidence)}
        </span>
        <span style={{ color: rulesAnswered ? "var(--green)" : "var(--amber)" }}>
          {rulesAnswered ? "✓ this is the final verdict" : "→ layer 1 passed to a deeper layer"}
        </span>
      </p>
    </div>
  );
}

function InboxRow({
  email,
  open,
  onToggle,
}: {
  email: SampleEmail;
  open: boolean;
  onToggle: () => void;
}) {
  const { verdict } = email;
  const dot = CATEGORY_DOT[verdict.category] ?? "var(--text-dim)";
  return (
    <li>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        data-testid="sample-row"
        className="trace-row focus-inset flex w-full flex-wrap items-center gap-3 px-4 py-3 text-left hover:bg-surface-2"
      >
        <div className="min-w-0 basis-full sm:basis-0 sm:flex-1">
          <p className="truncate text-sm font-medium text-strong">{email.subject}</p>
          <p className="truncate text-xs text-dim">
            {email.senderName} · {email.senderEmail}
          </p>
        </div>

        <LayerTrack trace={verdict.trace} />

        <span className="inline-flex items-center gap-1.5 text-xs text-muted">
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: dot }} aria-hidden />
          {pretty(verdict.category)}
        </span>

        {verdict.needsReview ? (
          <span className="rounded-full border border-review/40 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-review">
            review
          </span>
        ) : (
          <span className="hidden w-14 font-mono text-[10px] text-dim sm:inline">via {verdict.method}</span>
        )}

        <span
          className="tabular w-12 shrink-0 text-right font-mono text-xs"
          style={{ color: verdict.needsReview ? "var(--amber)" : "var(--green)" }}
        >
          {pct(verdict.confidence)}
        </span>
      </button>

      {open && <ExpandedTrace email={email} />}
    </li>
  );
}

function LivePlayground() {
  const [subject, setSubject] = useState("We'd like to schedule a call to discuss the role");
  const [body, setBody] = useState(
    "Thanks for your interest. Are you available for a 30-minute interview next week to meet the team?",
  );

  const result = useMemo(() => classifyWithRules(subject, body), [subject, body]);
  const topScores = useMemo(
    () =>
      Object.entries(result.scores)
        .filter(([, s]) => s > 0)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 4),
    [result.scores],
  );

  return (
    <div className="rounded-xl border border-line-soft bg-surface p-5">
      <h3 className="label-mono mb-1">run layer 1 live · your own text</h3>
      <p className="mb-4 text-sm text-muted">
        Layer 1 (the regex rules) runs entirely in your browser — no model download, no network. Type
        anything and watch it score. Layers 2–3 (the 23 MB ONNX model) are the precomputed part above.
      </p>

      <div className="space-y-2">
        <label className="block">
          <span className="label-mono">subject</span>
          <input
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            data-testid="playground-subject"
            className="mt-1 block w-full rounded-md border border-line bg-surface-2 px-3 py-2 text-sm text-strong outline-none placeholder:text-dim focus:border-line-strong"
          />
        </label>
        <label className="block">
          <span className="label-mono">body</span>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={3}
            data-testid="playground-body"
            className="mt-1 block w-full resize-y rounded-md border border-line bg-surface-2 px-3 py-2 text-sm text-strong outline-none placeholder:text-dim focus:border-line-strong"
          />
        </label>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line-soft pt-4">
        <span className="label-mono">verdict</span>
        <span
          data-testid="playground-verdict"
          className="rounded-full border px-3 py-1 font-mono text-xs uppercase tracking-wide"
          style={{
            color: result.category === "other" ? "var(--text-dim)" : "var(--text-strong)",
            borderColor: "var(--line)",
          }}
        >
          {pretty(result.category)}
        </span>
        <span
          className="tabular font-mono text-sm"
          style={{ color: result.confidence >= GATE ? "var(--green)" : "var(--amber)" }}
        >
          {pct(result.confidence)}
        </span>
        <span className="font-mono text-[11px] text-dim">
          {result.confidence >= 0.9
            ? "clears the layer-1 accept bar (≥0.90) — rules would answer"
            : "below 0.90 — the full pipeline would defer to e5 / SetFit"}
        </span>
      </div>

      {topScores.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {topScores.map(([cat, score]) => (
            <span key={cat} className="rounded border border-line-soft px-2 py-0.5 font-mono text-[10px] text-dim">
              {pretty(cat)} +{score}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function SampleInbox() {
  const [openId, setOpenId] = useState<string | null>(SAMPLE_EMAILS[0]?.id ?? null);
  const stats = sampleInboxStats();

  const statCells: [string, string][] = [
    ["scanned", String(stats.scanned)],
    ["auto-classified", `${stats.autoClassified} · ${stats.autoPct}%`],
    ["held for review", String(stats.heldForReview)],
    ["layers", "rules · e5 · SetFit"],
  ];

  return (
    <div className="space-y-6">
      <dl className="grid grid-cols-2 overflow-hidden rounded-xl border border-line-soft bg-surface sm:grid-cols-4">
        {statCells.map(([k, v]) => (
          <div key={k} className="border-b border-r border-line-soft p-4 last:border-r-0 sm:border-b-0">
            <dt className="label-mono">{k}</dt>
            <dd
              data-testid={`stat-${k.replace(/\s+/g, "-")}`}
              className="tabular mt-1 font-mono text-sm font-semibold text-strong"
            >
              {v}
            </dd>
          </div>
        ))}
      </dl>

      <div className="trace-card overflow-hidden rounded-xl border border-line-soft bg-surface">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-line-soft px-4 py-3">
          {(["rules", "embeddings", "setfit"] as LayerId[]).map((id) => {
            const m = LAYER_META[id];
            return (
              <span key={id} className="flex items-center gap-2 font-mono text-[11px] text-muted">
                <span className="inline-block h-2 w-2 rounded-full" style={{ background: m.color }} />
                <span className="text-dim">{m.n}</span> {m.label}
              </span>
            );
          })}
          <span className="ml-auto flex items-center gap-2 font-mono text-[11px] text-review">
            <span className="inline-block h-2 w-2 rounded-full bg-review" /> below {GATE} → human
          </span>
        </div>

        <ul className="divide-y divide-line-soft">
          {SAMPLE_EMAILS.map((email) => (
            <InboxRow
              key={email.id}
              email={email}
              open={openId === email.id}
              onToggle={() => setOpenId(openId === email.id ? null : email.id)}
            />
          ))}
        </ul>
      </div>

      <LivePlayground />
    </div>
  );
}
