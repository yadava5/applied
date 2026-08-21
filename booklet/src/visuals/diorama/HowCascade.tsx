import React from "react";
import { COLORS } from "../../theme";
import { SceneFrame, FlowChannel, Marker, iso } from "./primitives";

/**
 * HOW — the 3-layer classifier cascade (the hero diorama). One envelope
 * enters at the top and threads down through three stacked isometric slabs:
 *
 *   L1 · RULES    219 regex rules      (cyan edge)
 *   L2 · e5       pretrained e5 embeddings · cosine similarity (violet edge)
 *   L3 · SetFit   few-shot head        (green edge)
 *
 * Below the stack sits the 0.85 CONFIDENCE GATE (amber): the flow branches —
 * one arm carries an accepted verdict, the other drops to a human figure.
 *
 * Near-white linework on the dark divider ground; each layer wears its own
 * accent as a thin top-edge highlight, amber owns the gate + the human path.
 */

const LINE = COLORS.ON_DARK;

const SCALE = 1.5;
const OFFSET_X = 104;
const OFFSET_Y = 150;
const P = (x: number, y: number, z = 0) => {
  const p = iso(x, y, z);
  return { sx: p.sx * SCALE + OFFSET_X, sy: p.sy * SCALE + OFFSET_Y };
};

const poly = (pts: { sx: number; sy: number }[]) =>
  pts.map((p) => `${p.sx.toFixed(2)},${p.sy.toFixed(2)}`).join(" ");

// Footprint shared by all three slabs.
const FW = 44;
const FD = 28;
const OX = -FW / 2;
const OY = -FD / 2;
const HH = 5; // slab thickness

const L1Z = 46;
const L2Z = 26;
const L3Z = 6;
const GATE_Z = -7;

type Layer = {
  z: number;
  accent: string;
  tag: string;
  name: string;
  motif: "rules" | "embed" | "setfit";
};

const LAYERS: readonly Layer[] = [
  { z: L1Z, accent: COLORS.RULES_CYAN, tag: "L1", name: "RULES", motif: "rules" },
  { z: L2Z, accent: COLORS.E5_VIOLET, tag: "L2", name: "e5", motif: "embed" },
  { z: L3Z, accent: COLORS.SETFIT_GREEN, tag: "L3", name: "SetFit", motif: "setfit" },
];

// Billboard envelope glyph — rounded body + a down-pointing flap V.
const Envelope: React.FC<{
  cx: number;
  cy: number;
  w: number;
  strokeWidth?: number;
  fillOpacity?: number;
  accent?: string;
}> = ({ cx, cy, w, strokeWidth = 1.1, fillOpacity = 0.16, accent }) => {
  const h = w * 0.66;
  const x0 = cx - w / 2;
  const y0 = cy - h / 2;
  return (
    <g strokeLinejoin="round" strokeLinecap="round">
      <rect
        x={x0}
        y={y0}
        width={w}
        height={h}
        rx={w * 0.09}
        fill="currentColor"
        fillOpacity={fillOpacity}
        stroke="currentColor"
        strokeWidth={strokeWidth}
      />
      <path
        d={`M ${x0.toFixed(2)} ${y0.toFixed(2)} L ${cx.toFixed(2)} ${(y0 + h * 0.5).toFixed(2)} L ${(x0 + w).toFixed(2)} ${y0.toFixed(2)}`}
        fill="none"
        stroke={accent ?? "currentColor"}
        strokeWidth={strokeWidth}
      />
    </g>
  );
};

export const HowCascade: React.FC = () => {
  // Slab centre points (top face) — the flow threads through these.
  const cEnv = { sx: OFFSET_X, sy: 33 };
  const c1 = P(0, 0, L1Z + HH);
  const c2 = P(0, 0, L2Z + HH);
  const c3 = P(0, 0, L3Z + HH);
  const cGate = P(0, 0, GATE_Z + 1);

  // Branch endpoints below the gate.
  const branchRoot = { sx: OFFSET_X, sy: cGate.sy + 12 };
  const acceptAt = { sx: 150, sy: 214 };
  const humanAt = { sx: 62, sy: 214 };

  return (
    <SceneFrame
      lineColor={LINE}
      cornerLabels={{ topLeft: "CLASSIFIER · CASCADE", bottomRight: "GATE 0.85" }}
    >
      {/* ---- Three stacked slabs, back-to-front by z ---------------- */}
      {LAYERS.map((L) => {
        const zt = L.z + HH;
        const p000 = P(OX, OY, L.z);
        const p100 = P(OX + FW, OY, L.z);
        const p110 = P(OX + FW, OY + FD, L.z);
        const p010 = P(OX, OY + FD, L.z);
        const p001 = P(OX, OY, zt);
        const p101 = P(OX + FW, OY, zt);
        const p111 = P(OX + FW, OY + FD, zt);
        const p011 = P(OX, OY + FD, zt);
        const cx = (p001.sx + p111.sx) / 2;
        const cy = (p001.sy + p111.sy) / 2;
        return (
          <g key={L.tag}>
            {/* left + right faces — neutral linework */}
            <polygon
              points={poly([p000, p001, p011, p010])}
              fill="currentColor"
              fillOpacity={0.16}
              stroke="currentColor"
              strokeWidth={0.9}
              strokeLinejoin="round"
            />
            <polygon
              points={poly([p100, p101, p111, p110])}
              fill="currentColor"
              fillOpacity={0.09}
              stroke="currentColor"
              strokeWidth={0.9}
              strokeLinejoin="round"
            />
            {/* top rhombus — faint neutral fill, accent-coloured lip */}
            <polygon
              points={poly([p001, p101, p111, p011])}
              fill="currentColor"
              fillOpacity={0.06}
              stroke={L.accent}
              strokeWidth={1.4}
              strokeLinejoin="round"
            />
            {/* per-layer micro-motif on the top face (what this layer does) */}
            {L.motif === "rules" && (
              <g stroke="currentColor" strokeWidth={0.5} opacity={0.5}>
                {[-9, -3, 3, 9].map((dx, i) => (
                  <g key={i}>
                    <line x1={cx + dx} y1={cy - 4} x2={cx + dx} y2={cy - 1} />
                    <line x1={cx + dx - 1.4} y1={cy - 2.5} x2={cx + dx + 1.4} y2={cy - 2.5} />
                  </g>
                ))}
              </g>
            )}
            {L.motif === "embed" && (
              <g fill="currentColor" opacity={0.5}>
                {Array.from({ length: 12 }).map((_, k) => {
                  const r = Math.floor(k / 4);
                  const cc = k % 4;
                  return <circle key={k} cx={cx - 9 + cc * 6} cy={cy - 4.5 + r * 3} r={0.7} />;
                })}
              </g>
            )}
            {L.motif === "setfit" && (
              <g opacity={0.55}>
                <line
                  x1={cx - 8}
                  y1={cy + 1}
                  x2={cx + 9}
                  y2={cy - 6}
                  stroke="currentColor"
                  strokeWidth={0.5}
                  strokeDasharray="2 1.5"
                />
                {[
                  [-6, -3],
                  [-3, 1],
                  [-7, 2],
                  [5, -5],
                  [8, -1],
                  [3, -6],
                ].map(([dx, dy], i) => (
                  <circle
                    key={i}
                    cx={cx + (dx ?? 0)}
                    cy={cy + (dy ?? 0)}
                    r={1}
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={0.6}
                  />
                ))}
              </g>
            )}
          </g>
        );
      })}

      {/* ---- The descending flow thread (drawn over the slabs) ------- */}
      <FlowChannel from={[cEnv.sx, cEnv.sy + 6]} to={[c1.sx, c1.sy]} curvature={0.12} dashed dashPattern="3 3" strokeWidth={1.1} />
      <FlowChannel from={[c1.sx, c1.sy]} to={[c2.sx, c2.sy]} curvature={-0.16} dashed dashPattern="3 3" strokeWidth={1.1} />
      <FlowChannel from={[c2.sx, c2.sy]} to={[c3.sx, c3.sy]} curvature={0.16} dashed dashPattern="3 3" strokeWidth={1.1} />
      <FlowChannel from={[c3.sx, c3.sy]} to={[cGate.sx, cGate.sy]} curvature={-0.12} strokeWidth={1.2} tracer />
      <Marker at={[c1.sx, c1.sy]} kind="ring" size={1.7} />
      <Marker at={[c2.sx, c2.sy]} kind="ring" size={1.7} />
      <Marker at={[c3.sx, c3.sy]} kind="ring" size={1.7} />

      {/* ---- The envelope entering at the top ----------------------- */}
      <Envelope cx={cEnv.sx} cy={cEnv.sy} w={17} />
      {(() => {
        const p = { sx: cEnv.sx + 13, sy: cEnv.sy - 6 };
        return (
          <text
            x={p.sx}
            y={p.sy}
            fontFamily="ui-monospace, monospace"
            fontSize={4.2}
            letterSpacing="0.8"
            fill="currentColor"
            opacity={0.7}
          >
            INBOX MSG
          </text>
        );
      })()}

      {/* ---- Right-edge layer labels with leader ticks -------------- */}
      {LAYERS.map((L) => {
        const edge = P(OX + FW, OY, L.z + HH * 0.5);
        const lx = 158;
        return (
          <g key={`lab-${L.tag}`}>
            <line x1={edge.sx + 2} y1={edge.sy} x2={lx - 3} y2={edge.sy} stroke="currentColor" strokeWidth={0.4} opacity={0.4} />
            <circle cx={edge.sx + 2} cy={edge.sy} r={1.1} fill={L.accent} />
            <text x={lx} y={edge.sy - 1} fontFamily="ui-monospace, monospace" fontSize={5.4} fontWeight={700} letterSpacing="0.8" fill="currentColor" opacity={0.95}>
              {L.tag}
            </text>
            <text x={lx} y={edge.sy + 5} fontFamily="ui-monospace, monospace" fontSize={3.8} letterSpacing="0.6" fill="currentColor" opacity={0.62}>
              {L.name}
            </text>
          </g>
        );
      })}

      {/* ---- The 0.85 confidence gate (amber) ----------------------- */}
      <g style={{ color: COLORS.GATE_AMBER }}>
        {(() => {
          const gw = 50;
          const gd = 32;
          const gx = -gw / 2;
          const gy = -gd / 2;
          const zt = GATE_Z + 1.6;
          const p000 = P(gx, gy, GATE_Z);
          const p100 = P(gx + gw, gy, GATE_Z);
          const p110 = P(gx + gw, gy + gd, GATE_Z);
          const p010 = P(gx, gy + gd, GATE_Z);
          const p001 = P(gx, gy, zt);
          const p101 = P(gx + gw, gy, zt);
          const p111 = P(gx + gw, gy + gd, zt);
          const p011 = P(gx, gy + gd, zt);
          return (
            <g>
              <polygon points={poly([p000, p001, p011, p010])} fill="currentColor" fillOpacity={0.14} stroke="currentColor" strokeWidth={1.0} strokeLinejoin="round" />
              <polygon points={poly([p100, p101, p111, p110])} fill="currentColor" fillOpacity={0.08} stroke="currentColor" strokeWidth={1.0} strokeLinejoin="round" />
              <polygon points={poly([p001, p101, p111, p011])} fill="currentColor" fillOpacity={0.12} stroke="currentColor" strokeWidth={1.4} strokeLinejoin="round" />
              {/* threshold dashes running along the gate top */}
              <line
                x1={(p001.sx + p011.sx) / 2}
                y1={(p001.sy + p011.sy) / 2}
                x2={(p101.sx + p111.sx) / 2}
                y2={(p101.sy + p111.sy) / 2}
                stroke="currentColor"
                strokeWidth={0.6}
                strokeDasharray="3 2"
                opacity={0.9}
              />
            </g>
          );
        })()}
        {/* gate value + caption */}
        {(() => {
          const lab = P(FW / 2 + 2, -FD / 2, GATE_Z + 2);
          return (
            <g>
              <text x={lab.sx + 4} y={lab.sy - 2} fontFamily="ui-monospace, monospace" fontSize={7} fontWeight={700} letterSpacing="0.5" fill="currentColor">
                0.85
              </text>
              <text x={lab.sx + 4} y={lab.sy + 3.5} fontFamily="ui-monospace, monospace" fontSize={3.4} letterSpacing="0.8" fill="currentColor" opacity={0.85}>
                CONFIDENCE
              </text>
            </g>
          );
        })()}
      </g>

      {/* ---- Branch: accepted verdict vs. a human decides ----------- */}
      <FlowChannel from={[branchRoot.sx, branchRoot.sy - 4]} to={[acceptAt.sx - 4, acceptAt.sy - 6]} curvature={0.28} strokeWidth={1.1} />
      <FlowChannel from={[branchRoot.sx, branchRoot.sy - 4]} to={[humanAt.sx + 6, humanAt.sy - 8]} curvature={-0.28} dashed dashPattern="3 3" strokeWidth={1.1} />

      {/* accepted tag (neutral) with a check */}
      {(() => {
        const w = 30;
        const h = 13;
        const x0 = acceptAt.sx - w / 2;
        const y0 = acceptAt.sy - h / 2;
        return (
          <g>
            <rect x={x0} y={y0} width={w} height={h} rx={2.2} fill="currentColor" fillOpacity={0.12} stroke="currentColor" strokeWidth={1.1} />
            <path d={`M ${x0 + 4} ${acceptAt.sy} l 2.4 2.6 l 5 -5.6`} fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" />
            <text x={x0 + 12} y={acceptAt.sy + 2} fontFamily="ui-monospace, monospace" fontSize={3.8} letterSpacing="0.6" fontWeight={600} fill="currentColor">
              ACCEPT
            </text>
            <text x={acceptAt.sx} y={y0 - 3} textAnchor="middle" fontFamily="ui-monospace, monospace" fontSize={3.6} letterSpacing="0.6" fill="currentColor" opacity={0.7}>
              ≥ 0.85
            </text>
          </g>
        );
      })()}

      {/* human path (amber) */}
      <g style={{ color: COLORS.GATE_AMBER }}>
        {(() => {
          const shoulders = { sx: humanAt.sx, sy: humanAt.sy + 2 };
          const head = { sx: humanAt.sx, sy: humanAt.sy - 4 };
          const feet = { sx: humanAt.sx, sy: humanAt.sy + 9 };
          return (
            <g>
              <ellipse cx={shoulders.sx} cy={shoulders.sy} rx={3} ry={4} fill="currentColor" fillOpacity={0.3} stroke="currentColor" strokeWidth={1.0} />
              <circle cx={head.sx} cy={head.sy} r={2.4} fill="currentColor" fillOpacity={0.35} stroke="currentColor" strokeWidth={1.0} />
              <line x1={shoulders.sx - 2} y1={shoulders.sy + 3.5} x2={feet.sx - 2} y2={feet.sy} stroke="currentColor" strokeWidth={1.0} strokeLinecap="round" />
              <line x1={shoulders.sx + 2} y1={shoulders.sy + 3.5} x2={feet.sx + 2} y2={feet.sy} stroke="currentColor" strokeWidth={1.0} strokeLinecap="round" />
              <text x={humanAt.sx} y={head.sy - 6} textAnchor="middle" fontFamily="ui-monospace, monospace" fontSize={3.6} letterSpacing="0.6" fill="currentColor" opacity={0.85}>
                &lt; 0.85
              </text>
              <text x={humanAt.sx} y={feet.sy + 6} textAnchor="middle" fontFamily="ui-monospace, monospace" fontSize={3.8} letterSpacing="0.4" fill="currentColor">
                a human decides
              </text>
            </g>
          );
        })()}
      </g>
    </SceneFrame>
  );
};
