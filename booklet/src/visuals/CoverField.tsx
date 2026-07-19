import React from "react";
import { COLORS } from "../theme";

/**
 * CoverField — the cover motif: a field of email envelopes resolving into
 * classified verdicts. Deterministic (a seeded mulberry32 PRNG, no deps): a
 * jittered grid of envelope glyphs on the dark ground. Upper-left envelopes
 * are dim and unclassified; moving down-right they brighten and gain a
 * verdict tint — RULES cyan / e5 violet / SetFit green. A faint amber
 * CONFIDENCE · 0.85 gate crosses ~70% down; a handful of envelopes below it
 * are flagged amber — a human decides.
 *
 *   front    — the resolving field.
 *   back     — reseeded + x-shifted so the spread reads as one wraparound.
 *   endpaper — sparse and faint.
 *
 * All vector: envelope strokes on a #0B1220 ground with a low-alpha
 * feTurbulence grain. No blend-modes, masks, or external images (PDF-safe).
 */

export type CoverFieldProps = {
  widthIn: number;
  heightIn: number;
  variant: "front" | "back" | "endpaper";
  seed?: string;
};

const VB_W = 875;
const VB_H = 1125;

const VERDICTS = [COLORS.RULES_CYAN, COLORS.E5_VIOLET, COLORS.SETFIT_GREEN] as const;

const GRAIN_ID: Record<CoverFieldProps["variant"], string> = {
  front: "field-grain-front",
  back: "field-grain-back",
  endpaper: "field-grain-endpaper",
};
const GRAIN_SEED: Record<CoverFieldProps["variant"], number> = {
  front: 7,
  back: 13,
  endpaper: 21,
};

// --- deterministic PRNG ----------------------------------------------------
function xmur3(str: string): () => number {
  let h = 1779033703 ^ str.length;
  for (let i = 0; i < str.length; i++) {
    h = Math.imul(h ^ str.charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  return () => {
    h = Math.imul(h ^ (h >>> 16), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    h ^= h >>> 16;
    return h >>> 0;
  };
}
function mulberry32(a: number): () => number {
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const clamp = (v: number, lo: number, hi: number) => (v < lo ? lo : v > hi ? hi : v);

type Glyph = {
  id: string;
  cx: number;
  cy: number;
  w: number;
  rot: number;
  stroke: string;
  strokeOpacity: number;
  strokeWidth: number;
  verdict: string | null;
  flagged: boolean;
};

function buildField(seed: string, variant: CoverFieldProps["variant"]) {
  const rand = mulberry32(xmur3(`${seed}::${variant}`)());
  const endpaper = variant === "endpaper";

  const cols = endpaper ? 7 : 8;
  const rows = endpaper ? 9 : 11;
  const cellW = VB_W / cols;
  const cellH = VB_H / rows;
  const xShift = variant === "back" ? cellW * 0.5 : 0;
  const bias = variant === "back" ? 0.26 : endpaper ? -0.12 : 0.0;
  const gateY = VB_H * (variant === "back" ? 0.6 : endpaper ? 0.82 : 0.7);

  const glyphs: Glyph[] = [];

  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < cols; col++) {
      // Sparse endpaper: drop roughly half the cells.
      if (endpaper && rand() < 0.5) {
        // still burn a few draws so the sequence stays varied
        rand();
        rand();
        continue;
      }

      const jx = (rand() - 0.5) * cellW * 0.42;
      const jy = (rand() - 0.5) * cellH * 0.42;
      const cx = (col + 0.5) * cellW + jx + xShift;
      const cy = (row + 0.5) * cellH + jy;
      const rot = (rand() - 0.5) * 11;
      const w = cellW * (0.4 + rand() * 0.13);

      const tx = cols > 1 ? col / (cols - 1) : 0;
      const ty = rows > 1 ? row / (rows - 1) : 0;
      const t = clamp(tx * 0.5 + ty * 0.5 + bias + (rand() - 0.5) * 0.14, 0, 1);

      const resolved = endpaper ? rand() < 0.16 : t + (rand() - 0.5) * 0.12 > 0.45;

      let verdict: string | null = null;
      let flagged = false;
      if (resolved) {
        verdict = VERDICTS[Math.floor(rand() * VERDICTS.length)] ?? COLORS.RULES_CYAN;
        // A handful below the gate get flagged for a human.
        if (!endpaper && cy > gateY && rand() < 0.42) {
          verdict = COLORS.GATE_AMBER;
          flagged = true;
        }
      }

      const baseOpacity = endpaper ? 0.1 + t * 0.16 : 0.12 + t * 0.6;
      const strokeOpacity = clamp(resolved ? baseOpacity + 0.16 : baseOpacity, 0.08, 0.92);
      const strokeWidth = resolved ? 2.1 : 1.5;

      glyphs.push({
        id: `${row}-${col}`,
        cx,
        cy,
        w,
        rot,
        stroke: COLORS.ON_DARK,
        strokeOpacity,
        strokeWidth,
        verdict,
        flagged,
      });
    }
  }

  return { glyphs, gateY, endpaper };
}

const CoverEnvelope: React.FC<Glyph> = ({ cx, cy, w, rot, stroke, strokeOpacity, strokeWidth, verdict, flagged }) => {
  const h = w * 0.64;
  const x0 = cx - w / 2;
  const y0 = cy - h / 2;
  const vColor = verdict ?? stroke;
  const vOpacity = verdict ? Math.min(strokeOpacity + 0.15, 0.95) : strokeOpacity;
  return (
    <g transform={`rotate(${rot.toFixed(2)} ${cx.toFixed(2)} ${cy.toFixed(2)})`} strokeLinejoin="round" strokeLinecap="round">
      {flagged && <circle cx={cx} cy={cy} r={w * 0.62} fill="none" stroke={COLORS.GATE_AMBER} strokeWidth={1.1} strokeOpacity={0.6} strokeDasharray="3 3" />}
      <rect x={x0} y={y0} width={w} height={h} rx={w * 0.08} fill="none" stroke={stroke} strokeOpacity={strokeOpacity} strokeWidth={strokeWidth} />
      <path
        d={`M ${x0.toFixed(2)} ${y0.toFixed(2)} L ${cx.toFixed(2)} ${(y0 + h * 0.5).toFixed(2)} L ${(x0 + w).toFixed(2)} ${y0.toFixed(2)}`}
        fill="none"
        stroke={vColor}
        strokeOpacity={vOpacity}
        strokeWidth={strokeWidth}
      />
      {verdict && <circle cx={cx} cy={y0 + h * 0.72} r={w * 0.07} fill={vColor} fillOpacity={Math.min(vOpacity + 0.05, 1)} />}
    </g>
  );
};

export const CoverField: React.FC<CoverFieldProps> = ({ widthIn, heightIn, variant, seed = "jobtracker-2026" }) => {
  // viewBox is locked to the internal canvas; the *In props are reserved API
  // knobs for future trim-size changes.
  void widthIn;
  void heightIn;

  const { glyphs, gateY, endpaper } = React.useMemo(() => buildField(seed, variant), [seed, variant]);
  const grainId = GRAIN_ID[variant];

  return (
    <svg
      viewBox={`0 0 ${VB_W} ${VB_H}`}
      preserveAspectRatio="xMidYMid slice"
      style={{ position: "absolute", inset: 0, width: "100%", height: "100%", display: "block" }}
      aria-hidden="true"
    >
      <defs>
        <filter id={grainId} x="-2%" y="-2%" width="104%" height="104%" primitiveUnits="userSpaceOnUse">
          <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves={2} stitchTiles="stitch" seed={GRAIN_SEED[variant]} />
          {/* flatten to a soft light speckle; alpha carries the grain at ~6% */}
          <feColorMatrix
            values="0 0 0 0 0.55
                    0 0 0 0 0.58
                    0 0 0 0 0.62
                    0 0 0 0.06 0"
          />
        </filter>
        <radialGradient id={`field-vignette-${variant}`} cx="50%" cy={variant === "front" ? "34%" : "66%"} r="78%">
          <stop offset="0%" stopColor={COLORS.GROUND} stopOpacity="0" />
          <stop offset="100%" stopColor="#000000" stopOpacity="0.35" />
        </radialGradient>
      </defs>

      {/* Ground */}
      <rect x={0} y={0} width={VB_W} height={VB_H} fill={COLORS.GROUND} />

      {/* Envelope field. opacity 0.99 dodges a Chromium PDF bug that can drop
          opacity:1 subtrees. */}
      <g opacity={0.99}>
        {glyphs.map((g) => (
          <CoverEnvelope key={g.id} {...g} />
        ))}
      </g>

      {/* Confidence gate */}
      <g opacity={endpaper ? 0.3 : 0.92}>
        <line x1={0} y1={gateY} x2={VB_W} y2={gateY} stroke={COLORS.GATE_AMBER} strokeWidth={2} strokeOpacity={0.5} strokeDasharray="10 8" />
        {!endpaper && (
          <>
            <text x={44} y={gateY - 12} fontFamily="ui-monospace, monospace" fontSize={16} letterSpacing="3" fill={COLORS.GATE_AMBER} fillOpacity={0.62}>
              CONFIDENCE · 0.85
            </text>
            <text x={VB_W - 44} y={gateY + 26} textAnchor="end" fontFamily="ui-monospace, monospace" fontSize={12} letterSpacing="2" fill={COLORS.GATE_AMBER} fillOpacity={0.45}>
              a human decides ↓
            </text>
          </>
        )}
      </g>

      {/* Vignette + grain (last, over everything) */}
      <rect x={0} y={0} width={VB_W} height={VB_H} fill={`url(#field-vignette-${variant})`} pointerEvents="none" />
      <rect x={0} y={0} width={VB_W} height={VB_H} filter={`url(#${grainId})`} pointerEvents="none" opacity={0.9} />
    </svg>
  );
};
