import React from "react";
import { COLORS, FONTS } from "../theme";
import { CATEGORIES } from "../content";

/**
 * Per-layer "signature" visuals — one distinct diagram per cascade rung so the
 * three layer-detail pages don't read as one template. Each shows how that
 * layer actually decides:
 *
 *   RulesSignature  — real regex patterns from ml/browser/site/rules.json,
 *                     mapped to the category they fire.
 *   E5Signature     — a cosine nearest-neighbor sketch: a query embedding
 *                     matched to its closest labeled example.
 *   SetfitSignature — a few-shot cluster: 5–10 contrastive examples per class
 *                     shaping a boundary.
 */

const CARD: React.CSSProperties = {
  border: `0.5pt solid ${COLORS.HAIRLINE}`,
  borderRadius: 6,
  background: COLORS.PAPER_ELEVATED,
  padding: 14,
  display: "flex",
  flexDirection: "column",
  gap: 10,
};

const CardHead: React.FC<{ label: string; accent: string; source: string }> = ({
  label,
  accent,
  source,
}) => (
  <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8 }}>
    <span
      style={{
        fontFamily: FONTS.MONO,
        fontSize: 8.5,
        fontWeight: 700,
        letterSpacing: "0.14em",
        textTransform: "uppercase",
        color: accent,
      }}
    >
      {label}
    </span>
    <span style={{ fontFamily: FONTS.MONO, fontSize: 7, color: COLORS.INK_SUBTLE }}>{source}</span>
  </div>
);

// ── Layer 1 · Rules — real regex → category ────────────────────────────────

const RULES: ReadonlyArray<{ pattern: string; cat: string; color: string }> = [
  { pattern: "regret to inform", cat: "rejection", color: COLORS.DANGER },
  { pattern: "schedule.{0,20}interview", cat: "interview", color: COLORS.RULES_DEEP },
  { pattern: "pleased to (offer|extend)", cat: "offer", color: COLORS.SETFIT_DEEP },
];

export const RulesSignature: React.FC = () => (
  <div style={CARD}>
    <CardHead label="Pattern sample" accent={COLORS.RULES_DEEP} source="rules.json" />
    <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
      {RULES.map((r) => (
        <div key={r.pattern} style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <code
            style={{
              flex: 1,
              minWidth: 0,
              fontFamily: FONTS.MONO,
              fontSize: 9.5,
              color: COLORS.INK,
              background: COLORS.SURFACE,
              border: `0.5pt solid ${COLORS.HAIRLINE}`,
              borderRadius: 3,
              padding: "4px 7px",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            /{r.pattern}/
          </code>
          <span aria-hidden style={{ color: COLORS.INK_SUBTLE, fontSize: 12 }}>
            →
          </span>
          <span
            style={{
              fontFamily: FONTS.MONO,
              fontSize: 8.5,
              fontWeight: 700,
              color: r.color,
              minWidth: 58,
            }}
          >
            {r.cat}
          </span>
        </div>
      ))}
    </div>
    <div style={{ fontFamily: FONTS.SERIF, fontStyle: "italic", fontSize: 10.5, color: COLORS.INK_MUTED }}>
      Each category carries <b>strong</b>, <b>weak</b>, and <b>negative</b> guards — so
      “schedule an interview” inside a rejection can’t misfire.
    </div>
  </div>
);

// ── Layer 1 · Rules — how the 201 patterns split across categories ─────────
// A lollipop (dot) chart, not a bar — the real per-category rule counts from
// content.CATEGORIES (sum = 201). Distinct chart form; honest data.

export const RulesDistribution: React.FC = () => {
  const rows = CATEGORIES.filter((c) => c.rules > 0)
    .slice()
    .sort((a, b) => b.rules - a.rules);
  const max = Math.max(...rows.map((r) => r.rules));
  const total = rows.reduce((s, r) => s + r.rules, 0);
  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 10 }}>
        <span
          style={{
            fontFamily: FONTS.MONO,
            fontSize: 8.5,
            fontWeight: 700,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            color: COLORS.RULES_DEEP,
          }}
        >
          rules per category
        </span>
        <span style={{ fontFamily: FONTS.MONO, fontSize: 8, color: COLORS.INK_SUBTLE, fontVariantNumeric: "tabular-nums" }}>
          {total} patterns · 7 categories
        </span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {rows.map((r) => {
          const pct = (r.rules / max) * 100;
          return (
            <div key={r.id} style={{ display: "grid", gridTemplateColumns: "1.35in 1fr 22px", alignItems: "center", columnGap: 10 }}>
              <span
                style={{
                  fontFamily: FONTS.MONO,
                  fontSize: 9.5,
                  fontWeight: 600,
                  color: COLORS.INK,
                  textAlign: "right",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {r.label}
              </span>
              <div style={{ position: "relative", height: 12, display: "flex", alignItems: "center" }}>
                {/* baseline track */}
                <span style={{ position: "absolute", left: 0, right: 0, height: 1, background: COLORS.HAIRLINE }} />
                {/* stem */}
                <span style={{ position: "absolute", left: 0, width: `${pct}%`, height: 2, background: COLORS.RULES_CYAN, borderRadius: 2 }} />
                {/* dot */}
                <span
                  style={{
                    position: "absolute",
                    left: `${pct}%`,
                    transform: "translateX(-50%)",
                    width: 9,
                    height: 9,
                    borderRadius: "50%",
                    background: COLORS.RULES_CYAN,
                    border: `1.5px solid ${COLORS.RULES_DEEP}`,
                  }}
                />
              </div>
              <span style={{ fontFamily: FONTS.MONO, fontSize: 10, fontWeight: 700, color: COLORS.RULES_DEEP, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                {r.rules}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

// ── Layer 2 · e5 — cosine nearest-neighbor ─────────────────────────────────

type Pt = { x: number; y: number; c: string };
const NEIGHBORS: Pt[] = [
  { x: 30, y: 40, c: COLORS.DANGER },
  { x: 52, y: 30, c: COLORS.DANGER },
  { x: 120, y: 52, c: COLORS.RULES_CYAN },
  { x: 150, y: 40, c: COLORS.RULES_CYAN },
  { x: 60, y: 96, c: COLORS.SETFIT_GREEN },
  { x: 40, y: 118, c: COLORS.SETFIT_GREEN },
  { x: 150, y: 112, c: COLORS.GATE_AMBER },
  { x: 168, y: 92, c: COLORS.GATE_AMBER },
];
const QUERY: Pt = { x: 104, y: 96, c: COLORS.E5_VIOLET };
// nearest neighbor = the closest labeled point (the lower-left green pair)
const NEAREST = NEIGHBORS[4]!;

export const E5Signature: React.FC = () => (
  <div style={CARD}>
    <CardHead label="cosine nearest-neighbor" accent={COLORS.E5_DEEP} source="e5-small-v2" />
    <svg viewBox="0 0 200 150" width="100%" style={{ display: "block" }}>
      {/* faint lattice */}
      {[0, 1, 2, 3].map((i) => (
        <line key={`h${i}`} x1={8} x2={192} y1={20 + i * 36} y2={20 + i * 36} stroke={COLORS.HAIRLINE} strokeWidth={0.4} strokeOpacity={0.5} />
      ))}
      {[0, 1, 2, 3, 4].map((i) => (
        <line key={`v${i}`} x1={16 + i * 42} x2={16 + i * 42} y1={12} y2={140} stroke={COLORS.HAIRLINE} strokeWidth={0.4} strokeOpacity={0.5} />
      ))}
      {/* the match line query → nearest */}
      <line x1={QUERY.x} y1={QUERY.y} x2={NEAREST.x} y2={NEAREST.y} stroke={COLORS.E5_VIOLET} strokeWidth={1.4} strokeDasharray="4 3" />
      {/* labeled neighbors */}
      {NEIGHBORS.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r={4} fill={p.c} fillOpacity={0.85} />
      ))}
      {/* halo on nearest */}
      <circle cx={NEAREST.x} cy={NEAREST.y} r={8} fill="none" stroke={COLORS.SETFIT_GREEN} strokeWidth={1} strokeOpacity={0.7} />
      {/* query — hollow violet */}
      <circle cx={QUERY.x} cy={QUERY.y} r={5.5} fill={COLORS.PAPER} stroke={COLORS.E5_VIOLET} strokeWidth={2} />
      <text x={QUERY.x + 8} y={QUERY.y - 6} fontFamily="ui-monospace, monospace" fontSize={7} fill={COLORS.E5_DEEP}>
        this email
      </text>
      <text x={NEAREST.x - 8} y={NEAREST.y + 16} fontFamily="ui-monospace, monospace" fontSize={7} fill={COLORS.SETFIT_DEEP} textAnchor="middle">
        nearest label
      </text>
    </svg>
    <div style={{ fontFamily: FONTS.SERIF, fontStyle: "italic", fontSize: 10.5, color: COLORS.INK_MUTED }}>
      The query embedding takes the category of its closest labeled neighbor,
      drawn from the labeled corpus as shipped.
    </div>
  </div>
);

// ── Layer 3 · SetFit — few-shot clusters ───────────────────────────────────

const CLUSTERS: ReadonlyArray<{ cx: number; cy: number; c: string; label: string }> = [
  { cx: 46, cy: 52, c: COLORS.RULES_CYAN, label: "interview" },
  { cx: 150, cy: 44, c: COLORS.SETFIT_GREEN, label: "offer" },
  { cx: 100, cy: 108, c: COLORS.DANGER, label: "rejection" },
];
// deterministic jitter for the 6 few-shot points around each centroid
const JITTER: ReadonlyArray<[number, number]> = [
  [-14, -8], [12, -12], [16, 8], [-10, 12], [2, -18], [-2, 16],
];

export const SetfitSignature: React.FC = () => (
  <div style={CARD}>
    <CardHead label="few-shot clusters" accent={COLORS.SETFIT_DEEP} source="SetFit · MiniLM-L6" />
    <svg viewBox="0 0 200 150" width="100%" style={{ display: "block" }}>
      {/* contrastive boundaries — dashed arcs between clusters */}
      <path d="M 98 12 Q 70 75 118 138" fill="none" stroke={COLORS.HAIRLINE_STRONG} strokeWidth={0.8} strokeDasharray="3 3" />
      <path d="M 8 96 Q 100 72 192 96" fill="none" stroke={COLORS.HAIRLINE_STRONG} strokeWidth={0.8} strokeDasharray="3 3" />
      {CLUSTERS.map((cl) => (
        <g key={cl.label}>
          {JITTER.map(([dx, dy], i) => (
            <circle key={i} cx={cl.cx + dx} cy={cl.cy + dy} r={3.2} fill={cl.c} fillOpacity={0.8} />
          ))}
          {/* centroid */}
          <circle cx={cl.cx} cy={cl.cy} r={5} fill="none" stroke={cl.c} strokeWidth={1.6} />
          <text
            x={cl.cx}
            y={cl.cy - 20}
            fontFamily="ui-monospace, monospace"
            fontSize={7}
            fontWeight={700}
            fill={cl.c}
            textAnchor="middle"
          >
            {cl.label}
          </text>
        </g>
      ))}
    </svg>
    <div style={{ fontFamily: FONTS.SERIF, fontStyle: "italic", fontSize: 10.5, color: COLORS.INK_MUTED }}>
      Contrastive training pulls each class’s handful of examples together and
      pushes the classes apart — no giant labeled set required.
    </div>
  </div>
);
