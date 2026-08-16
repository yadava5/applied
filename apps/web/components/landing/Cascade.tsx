import type { CSSProperties } from "react";

/**
 * The cascade, drawn as a descent. One email enters the top; each layer tries
 * to decide and, if it clears its accept threshold, files and stops. Otherwise
 * it falls through to a smarter, costlier layer — and finally to the gate.
 *
 * Every figure here is verified against the repo:
 *   · 201 regex rules (rules.py: 106 strong + 26 weak + 69 negative), 14 ATS
 *     domains, accept ≥ 0.90.
 *   · pretrained intfloat/e5-small-v2, 384-dim, cosine 1-NN, accept ≥ 0.85
 *     (embeddings.py:36 — loaded off the shelf, not fine-tuned).
 *   · the one fine-tuned model: a SetFit head on a paraphrase-MiniLM-L6-v2
 *     body, few-shot, accept ≥ 0.70.
 *   · gate at 0.85 (DecisionTrace / hybrid.py).
 */

const LAYERS = [
  {
    n: "1",
    label: "Regex rules",
    model: "201 patterns · 14 ATS domains",
    note: "Instant, deterministic, fully auditable — the phrases a hiring pipeline actually uses.",
    accept: "accept ≥ 0.90",
    color: "var(--viz-rules)",
  },
  {
    n: "2",
    label: "e5 similarity",
    model: "pretrained e5-small-v2 · 384-d · cosine 1-NN",
    note: "No rule was sure. Embed the email, match the nearest labeled example — past the exact wording.",
    accept: "accept ≥ 0.85",
    color: "var(--viz-embeddings)",
  },
  {
    n: "3",
    label: "SetFit head",
    model: "fine-tuned · MiniLM-L6 body · few-shot",
    note: "The only trained model in the stack — the learned call for the genuinely ambiguous email.",
    accept: "accept ≥ 0.70",
    color: "var(--viz-setfit)",
  },
] as const;

function Connector() {
  return (
    <div className="flex items-center gap-2 py-1 pl-[1.375rem] font-mono text-[10px] text-dim" aria-hidden>
      <span className="h-4 w-px bg-line-strong" />
      <span>falls through ↓</span>
    </div>
  );
}

export function Cascade() {
  return (
    <div className="rounded-xl border border-line-soft bg-surface p-4 sm:p-6">
      {/* one email enters the top */}
      <div className="mb-3 flex items-center gap-3 rounded-lg border border-line-soft bg-background px-4 py-3">
        <span className="label-mono">in</span>
        <span className="min-w-0 flex-1 truncate text-sm text-foreground">one email · unknown outcome</span>
        <span className="font-mono text-[11px] text-dim">↓ enters the cascade</span>
      </div>

      {LAYERS.map((layer, i) => (
        <div key={layer.n}>
          <div
            className="flex flex-col gap-3 rounded-lg border bg-surface-2 p-4 sm:flex-row sm:items-center"
            style={{ borderColor: `color-mix(in oklab, ${layer.color} 30%, transparent)` }}
          >
            <div className="flex items-center gap-3">
              <span
                className="grid h-7 w-7 shrink-0 place-items-center rounded-full font-mono text-xs font-semibold"
                style={{ color: layer.color, border: `1px solid ${layer.color}`, boxShadow: `0 0 16px -6px ${layer.color}` }}
              >
                {layer.n}
              </span>
              <div className="sm:w-40">
                <p className="text-sm font-semibold text-strong">{layer.label}</p>
                <p className="font-mono text-[10.5px] leading-tight text-dim">{layer.model}</p>
              </div>
            </div>
            <p className="flex-1 text-[13px] leading-relaxed text-muted">{layer.note}</p>
            <span
              className="shrink-0 self-start rounded-full border px-2.5 py-1 font-mono text-[10px] uppercase tracking-wide sm:self-center"
              style={{ color: layer.color, borderColor: `color-mix(in oklab, ${layer.color} 45%, transparent)` }}
            >
              {layer.accept}
            </span>
          </div>
          {i < LAYERS.length - 1 && <Connector />}
        </div>
      ))}

      <Connector />

      {/* the gate */}
      <div
        className="rounded-lg border p-4"
        style={
          {
            borderColor: "color-mix(in oklab, var(--amber) 40%, transparent)",
            background: "color-mix(in oklab, var(--amber) 7%, transparent)",
            "--amber": "var(--amber)",
          } as CSSProperties
        }
      >
        <div className="flex items-center gap-3">
          <span
            className="grid h-7 w-7 shrink-0 place-items-center rounded-full font-mono text-xs font-semibold"
            style={{ color: "var(--amber)", border: "1px solid var(--amber)" }}
          >
            ◇
          </span>
          <p className="text-sm font-semibold text-strong">The 0.85 confidence gate</p>
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <p className="rounded-md border border-line-soft bg-surface px-3 py-2 text-[13px] text-muted">
            <span className="font-mono text-[11px] text-live">≥ 0.85 </span>
            clears the gate → filed under its category, automatically.
          </p>
          <p className="rounded-md border border-line-soft bg-surface px-3 py-2 text-[13px] text-muted">
            <span className="font-mono text-[11px] text-review">&lt; 0.85 </span>
            a human decides — the answer is saved as yours, and no model trains on it.
          </p>
        </div>
      </div>
    </div>
  );
}
