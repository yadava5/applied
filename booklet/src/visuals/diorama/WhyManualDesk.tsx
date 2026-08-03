import React from "react";
import { COLORS } from "../../theme";
import { SceneFrame, ConstructionLine, Marker, iso } from "./primitives";

/**
 * WHY — the lossy manual workflow. An isometric desk: a laptop showing an
 * inbox (a stack of envelope glyphs) on the left, a hand-kept spreadsheet
 * grid on the right. Envelopes march from inbox → tracker, but a few tumble
 * off the front edge of the desk into the void: dropped applications, a
 * dashed fall-line, and an amber LOST marker.
 *
 * Near-white linework on the dark ground; amber is the single accent — it
 * marks only what was lost.
 */

const LINE = COLORS.ON_DARK;
const AMBER = COLORS.GATE_AMBER;

const SCALE = 1.9;
const OFFSET_X = 108;
const OFFSET_Y = 112;
const P = (x: number, y: number, z = 0) => {
  const p = iso(x, y, z);
  return { sx: p.sx * SCALE + OFFSET_X, sy: p.sy * SCALE + OFFSET_Y };
};

const poly = (pts: { sx: number; sy: number }[]) =>
  pts.map((p) => `${p.sx.toFixed(2)},${p.sy.toFixed(2)}`).join(" ");

const lerp = (a: { sx: number; sy: number }, b: { sx: number; sy: number }, t: number) => ({
  sx: a.sx + (b.sx - a.sx) * t,
  sy: a.sy + (b.sy - a.sy) * t,
});

// Billboard envelope glyph — rounded body + a down-pointing flap V.
const Envelope: React.FC<{
  cx: number;
  cy: number;
  w: number;
  rot?: number;
  strokeWidth?: number;
  fillOpacity?: number;
  accent?: string;
}> = ({ cx, cy, w, rot = 0, strokeWidth = 0.9, fillOpacity = 0.14, accent }) => {
  const h = w * 0.66;
  const x0 = cx - w / 2;
  const y0 = cy - h / 2;
  return (
    <g transform={rot ? `rotate(${rot} ${cx} ${cy})` : undefined} strokeLinejoin="round" strokeLinecap="round">
      <rect x={x0} y={y0} width={w} height={h} rx={w * 0.1} fill="currentColor" fillOpacity={fillOpacity} stroke="currentColor" strokeWidth={strokeWidth} />
      <path
        d={`M ${x0.toFixed(2)} ${y0.toFixed(2)} L ${cx.toFixed(2)} ${(y0 + h * 0.5).toFixed(2)} L ${(x0 + w).toFixed(2)} ${y0.toFixed(2)}`}
        fill="none"
        stroke={accent ?? "currentColor"}
        strokeWidth={strokeWidth}
      />
    </g>
  );
};

export const WhyManualDesk: React.FC = () => {
  // Desk top rhombus.
  const desk = { o: [-32, -22] as [number, number], w: 64, d: 44 };
  const deskTL = P(desk.o[0], desk.o[1]);
  const deskTR = P(desk.o[0] + desk.w, desk.o[1]);
  const deskBR = P(desk.o[0] + desk.w, desk.o[1] + desk.d);
  const deskBL = P(desk.o[0], desk.o[1] + desk.d);
  const deskThickness = 6;

  // Laptop (back-left) — base + screen tilted back.
  const lo: [number, number, number] = [-26, -14, 0];
  const lw = 24;
  const ld = 16;
  const baseH = 1.4;
  const screenH = 15;
  const tip = 3;
  const backLeft = P(lo[0], lo[1], baseH);
  const backRight = P(lo[0] + lw, lo[1], baseH);
  const scrTL = P(lo[0] - tip, lo[1] - tip, baseH + screenH);
  const scrTR = P(lo[0] + lw - tip, lo[1] - tip, baseH + screenH);
  // bilinear sample inside the screen quad (u across, v down from top edge)
  const screenPt = (u: number, v: number) => {
    const top = lerp(scrTL, scrTR, u);
    const bot = lerp(backLeft, backRight, u);
    return lerp(top, bot, v);
  };

  // Spreadsheet tracker grid (right side of desk).
  const sp = { o: [2, -16] as [number, number], w: 26, d: 30, z: 0.5, rows: 5, cols: 4 };
  const spTL = P(sp.o[0], sp.o[1], sp.z);
  const spTR = P(sp.o[0] + sp.w, sp.o[1], sp.z);
  const spBR = P(sp.o[0] + sp.w, sp.o[1] + sp.d, sp.z);
  const spBL = P(sp.o[0], sp.o[1] + sp.d, sp.z);

  // Envelopes marching inbox → tracker (on the desk surface).
  const flowPts = [P(-6, -6, 1), P(4, -8, 1), P(12, -10, 1)];

  // The fall — off the front edge into the void.
  const dropTop = { sx: 74, sy: 150 };
  const dropBot = { sx: 56, sy: 250 };
  const fallEnv = [0.24, 0.54, 0.84].map((t, i) => ({
    at: lerp(dropTop, dropBot, t),
    rot: 18 + i * 26,
    w: 13 - i * 1.2,
  }));

  return (
    <SceneFrame
      lineColor={LINE}
      cornerLabels={{ topLeft: "MANUAL · BY HAND", bottomRight: "LOSSY" }}
    >
      {/* Desk top */}
      <polygon points={poly([deskTL, deskTR, deskBR, deskBL])} fill="currentColor" fillOpacity={0.09} stroke="currentColor" strokeWidth={1.4} strokeLinejoin="round" />
      {/* Desk front edge thickness */}
      <polygon
        points={poly([deskBL, deskBR, { sx: deskBR.sx, sy: deskBR.sy + deskThickness }, { sx: deskBL.sx, sy: deskBL.sy + deskThickness }])}
        fill="currentColor"
        fillOpacity={0.2}
        stroke="currentColor"
        strokeWidth={1.0}
      />
      <polygon
        points={poly([deskBR, deskTR, { sx: deskTR.sx, sy: deskTR.sy + deskThickness }, { sx: deskBR.sx, sy: deskBR.sy + deskThickness }])}
        fill="currentColor"
        fillOpacity={0.12}
        stroke="currentColor"
        strokeWidth={0.8}
      />

      {/* ---- Laptop ------------------------------------------------- */}
      {(() => {
        const b000 = P(lo[0], lo[1], 0);
        const b100 = P(lo[0] + lw, lo[1], 0);
        const b110 = P(lo[0] + lw, lo[1] + ld, 0);
        const b010 = P(lo[0], lo[1] + ld, 0);
        const b001 = P(lo[0], lo[1], baseH);
        const b101 = P(lo[0] + lw, lo[1], baseH);
        const b111 = P(lo[0] + lw, lo[1] + ld, baseH);
        const b011 = P(lo[0], lo[1] + ld, baseH);
        return (
          <g>
            {/* base */}
            <polygon points={poly([b100, b101, b111, b110])} fill="currentColor" fillOpacity={0.08} stroke="currentColor" strokeWidth={1.0} strokeLinejoin="round" />
            <polygon points={poly([b000, b001, b011, b010])} fill="currentColor" fillOpacity={0.14} stroke="currentColor" strokeWidth={1.0} strokeLinejoin="round" />
            <polygon points={poly([b001, b101, b111, b011])} fill="currentColor" fillOpacity={0.12} stroke="currentColor" strokeWidth={1.0} strokeLinejoin="round" />
            {/* screen */}
            <polygon points={poly([backLeft, backRight, scrTR, scrTL])} fill="currentColor" fillOpacity={0.22} stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round" />
          </g>
        );
      })()}

      {/* Inbox on the screen — header + a stack of envelope rows */}
      {(() => {
        const rows = [0, 1, 2, 3];
        return (
          <g>
            {/* window chrome dots */}
            {[0.12, 0.19, 0.26].map((u, i) => {
              const d = screenPt(u, 0.12);
              return <circle key={i} cx={d.sx} cy={d.sy} r={0.7} fill="currentColor" opacity={0.6} />;
            })}
            {/* header rule */}
            {(() => {
              const a = screenPt(0.1, 0.24);
              const b = screenPt(0.9, 0.24);
              return <line x1={a.sx} y1={a.sy} x2={b.sx} y2={b.sy} stroke="currentColor" strokeWidth={0.5} opacity={0.5} />;
            })()}
            {rows.map((r) => {
              const v = 0.4 + r * 0.16;
              const icon = screenPt(0.2, v);
              const lineA = screenPt(0.34, v);
              const lineB = screenPt(0.86, v);
              return (
                <g key={r}>
                  <Envelope cx={icon.sx} cy={icon.sy} w={5.6} strokeWidth={0.55} fillOpacity={0.18} />
                  <line x1={lineA.sx} y1={lineA.sy} x2={lineB.sx} y2={lineB.sy} stroke="currentColor" strokeWidth={0.6} opacity={0.72} />
                </g>
              );
            })}
          </g>
        );
      })()}

      {/* ---- Spreadsheet tracker grid ------------------------------- */}
      <g>
        <polygon points={poly([spTL, spTR, spBR, spBL])} fill="currentColor" fillOpacity={0.05} stroke="currentColor" strokeWidth={1.1} strokeLinejoin="round" />
        {Array.from({ length: sp.cols - 1 }).map((_, i) => {
          const t = (i + 1) / sp.cols;
          const a = P(sp.o[0] + sp.w * t, sp.o[1], sp.z);
          const b = P(sp.o[0] + sp.w * t, sp.o[1] + sp.d, sp.z);
          return <line key={`c${i}`} x1={a.sx} y1={a.sy} x2={b.sx} y2={b.sy} stroke="currentColor" strokeWidth={0.5} opacity={0.4} />;
        })}
        {Array.from({ length: sp.rows - 1 }).map((_, j) => {
          const t = (j + 1) / sp.rows;
          const a = P(sp.o[0], sp.o[1] + sp.d * t, sp.z);
          const b = P(sp.o[0] + sp.w, sp.o[1] + sp.d * t, sp.z);
          return <line key={`r${j}`} x1={a.sx} y1={a.sy} x2={b.sx} y2={b.sy} stroke="currentColor" strokeWidth={0.5} opacity={0.4} />;
        })}
        {/* header band filled */}
        {(() => {
          const t = 1 / sp.rows;
          const a = P(sp.o[0], sp.o[1] + sp.d * t, sp.z);
          const b = P(sp.o[0] + sp.w, sp.o[1] + sp.d * t, sp.z);
          return <polygon points={poly([spTL, spTR, b, a])} fill="currentColor" fillOpacity={0.14} />;
        })()}
        {/* label */}
        {(() => {
          const p = P(sp.o[0], sp.o[1] - 2, sp.z);
          return (
            <text x={p.sx} y={p.sy} fontFamily="ui-monospace, monospace" fontSize={4} letterSpacing="0.8" fontWeight={600} fill="currentColor" opacity={0.8}>
              TRACKER.XLSX
            </text>
          );
        })()}
      </g>

      {/* ---- Envelopes marching inbox → tracker --------------------- */}
      {flowPts.map((p, i) => (
        <Envelope key={i} cx={p.sx} cy={p.sy} w={9 - i * 0.6} rot={-6 + i * 4} strokeWidth={0.8} />
      ))}
      <ConstructionLine from={[flowPts[0]?.sx ?? 0, (flowPts[0]?.sy ?? 0) - 6]} to={[spTL.sx + 6, spTL.sy - 4]} tick="end" strokeWidth={0.5} dashPattern="3 2" opacity={0.5} />

      {/* ---- The fall (amber) — dropped applications ---------------- */}
      <g style={{ color: AMBER }}>
        {/* dashed fall-line */}
        <path
          d={`M ${dropTop.sx} ${dropTop.sy} Q ${dropTop.sx - 14} ${(dropTop.sy + dropBot.sy) / 2} ${dropBot.sx} ${dropBot.sy}`}
          fill="none"
          stroke="currentColor"
          strokeWidth={0.7}
          strokeDasharray="3 3"
          opacity={0.7}
        />
        {/* the edge from which they fall */}
        <circle cx={dropTop.sx} cy={dropTop.sy} r={1.3} fill="currentColor" opacity={0.85} />
        {fallEnv.map((e, i) => (
          <Envelope key={i} cx={e.at.sx} cy={e.at.sy} w={e.w} rot={e.rot} strokeWidth={0.9} fillOpacity={0.12} accent={AMBER} />
        ))}
        {/* LOST marker at the bottom of the void */}
        <Marker at={[dropBot.sx - 4, dropBot.sy + 8]} kind="target" size={1.7} />
        <text x={dropBot.sx + 10} y={dropBot.sy + 12} fontFamily="ui-monospace, monospace" fontSize={5} letterSpacing="1.2" fontWeight={600} fill="currentColor">
          LOST
        </text>
        <text x={dropBot.sx + 10} y={dropBot.sy + 18} fontFamily="ui-monospace, monospace" fontSize={3.4} letterSpacing="0.8" fill="currentColor" opacity={0.8}>
          dropped by hand
        </text>
      </g>
    </SceneFrame>
  );
};
