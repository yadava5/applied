import React from "react";
import { COLORS } from "../../theme";
import { SceneFrame, Marker, iso } from "./primitives";

/**
 * INSIDE — the model runs in the browser, no server. An isometric browser
 * window (chrome bar + 3 dots + a URL line) is the container; inside it a
 * quantized ONNX chip (package + pin-legs + a violet die) does the work.
 * Behind it, a server rack silhouette is crossed out: NO SERVER. A small
 * caption plate reads 22.8 MB · WASM.
 *
 * Near-white linework on the dark ground; violet is the single accent — the
 * silicon that actually runs.
 */

const LINE = COLORS.ON_DARK;
const VIOLET = COLORS.E5_VIOLET;

const SCALE = 1.7;
const OFFSET_X = 100;
const OFFSET_Y = 158;
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

// Manually-projected iso cube (top + two visible faces).
const SCube: React.FC<{
  origin: [number, number, number];
  size: [number, number, number];
  face?: { top: number; left: number; right: number };
  strokeWidth?: number;
  dashed?: boolean;
  opacity?: number;
}> = ({ origin: [ox, oy, oz], size: [w, d, h], face = { top: 0.2, left: 0.13, right: 0.07 }, strokeWidth = 1.0, dashed = false, opacity = 1 }) => {
  const p000 = P(ox, oy, oz);
  const p100 = P(ox + w, oy, oz);
  const p110 = P(ox + w, oy + d, oz);
  const p010 = P(ox, oy + d, oz);
  const p001 = P(ox, oy, oz + h);
  const p101 = P(ox + w, oy, oz + h);
  const p111 = P(ox + w, oy + d, oz + h);
  const p011 = P(ox, oy + d, oz + h);
  const ext = dashed ? { strokeDasharray: "3 2.5" } : {};
  return (
    <g stroke="currentColor" strokeWidth={strokeWidth} strokeLinejoin="round" opacity={opacity} {...ext}>
      <polygon points={poly([p000, p001, p011, p010])} fill="currentColor" fillOpacity={face.left} />
      <polygon points={poly([p100, p101, p111, p110])} fill="currentColor" fillOpacity={face.right} />
      <polygon points={poly([p001, p101, p111, p011])} fill="currentColor" fillOpacity={face.top} />
    </g>
  );
};

export const InsideEngine: React.FC = () => {
  // Browser window — a shallow slab whose top face is the viewport.
  const bo: [number, number, number] = [-30, -18, 0];
  const bw = 44;
  const bd = 30;
  const bh = 3;
  const vTL = P(bo[0], bo[1], bh); // back
  const vTR = P(bo[0] + bw, bo[1], bh); // right
  const vBR = P(bo[0] + bw, bo[1] + bd, bh); // front
  const vBL = P(bo[0], bo[1] + bd, bh); // left
  const vpt = (u: number, v: number) => lerp(lerp(vTL, vTR, u), lerp(vBL, vBR, u), v);

  // Chip package on the viewport.
  const co: [number, number, number] = [-8, -8, bh];
  const cw = 16;
  const cd = 14;
  const ch = 4;

  return (
    <SceneFrame
      lineColor={LINE}
      cornerLabels={{ topLeft: "IN-BROWSER", bottomRight: "ZERO SERVERS" }}
    >
      {/* ---- Server rack, crossed out (drawn first, behind) --------- */}
      {(() => {
        const so: [number, number, number] = [10, -40, 16];
        const sw = 10;
        const sd = 8;
        const sh = 22;
        const fTL = P(so[0], so[1] + sd, so[2] + sh); // front-top-left
        const fTR = P(so[0] + sw, so[1] + sd, so[2] + sh);
        const fBR = P(so[0] + sw, so[1] + sd, so[2]);
        const fBL = P(so[0], so[1] + sd, so[2]);
        return (
          <g opacity={0.55}>
            <SCube origin={so} size={[sw, sd, sh]} face={{ top: 0.06, left: 0.05, right: 0.03 }} strokeWidth={0.9} dashed />
            {/* rack-unit slots on the front face */}
            {[0.16, 0.32, 0.48, 0.64, 0.8].map((t, i) => {
              const a = lerp(fBL, fTL, t);
              const b = lerp(fBR, fTR, t);
              return <line key={i} x1={a.sx} y1={a.sy} x2={b.sx} y2={b.sy} stroke="currentColor" strokeWidth={0.5} opacity={0.7} />;
            })}
            {/* crossed out */}
            <g stroke="currentColor" strokeWidth={1.3} strokeLinecap="round">
              <line x1={fTL.sx} y1={fTL.sy} x2={fBR.sx} y2={fBR.sy} />
              <line x1={fTR.sx} y1={fTR.sy} x2={fBL.sx} y2={fBL.sy} />
            </g>
            <text x={fBL.sx - 2} y={fBR.sy + 8} textAnchor="middle" fontFamily="ui-monospace, monospace" fontSize={4.4} letterSpacing="1" fontWeight={600} fill="currentColor" opacity={1}>
              NO SERVER
            </text>
          </g>
        );
      })()}

      {/* ---- Browser window ----------------------------------------- */}
      <SCube origin={bo} size={[bw, bd, bh]} face={{ top: 0.05, left: 0.16, right: 0.1 }} strokeWidth={1.3} />
      {/* chrome bar along the back edge + traffic dots + url line */}
      {(() => {
        const cTL = vpt(0.0, 0.0);
        const cTR = vpt(1.0, 0.0);
        const cbl = vpt(0.0, 0.14);
        const cbr = vpt(1.0, 0.14);
        return (
          <g>
            <polygon points={poly([cTL, cTR, cbr, cbl])} fill="currentColor" fillOpacity={0.16} stroke="currentColor" strokeWidth={0.6} />
            {[0.06, 0.11, 0.16].map((u, i) => {
              const p = vpt(u, 0.07);
              return <circle key={i} cx={p.sx} cy={p.sy} r={0.9} fill="currentColor" opacity={0.7} />;
            })}
            {(() => {
              const a = vpt(0.24, 0.07);
              const b = vpt(0.9, 0.07);
              return <line x1={a.sx} y1={a.sy} x2={b.sx} y2={b.sy} stroke="currentColor" strokeWidth={0.6} opacity={0.55} />;
            })()}
          </g>
        );
      })()}

      {/* ---- ONNX chip on the viewport ------------------------------ */}
      {/* pin-legs along the two front base edges */}
      {(() => {
        const blf = P(co[0], co[1] + cd, co[2]); // front-left base
        const bff = P(co[0] + cw, co[1] + cd, co[2]); // front base corner
        const brf = P(co[0] + cw, co[1], co[2]); // right base
        const legs: React.ReactElement[] = [];
        for (let i = 1; i <= 4; i++) {
          const t = i / 5;
          const a = lerp(blf, bff, t);
          legs.push(<line key={`l${i}`} x1={a.sx} y1={a.sy} x2={a.sx - 1} y2={a.sy + 3} stroke="currentColor" strokeWidth={0.8} strokeLinecap="round" />);
          const b = lerp(bff, brf, t);
          legs.push(<line key={`r${i}`} x1={b.sx} y1={b.sy} x2={b.sx + 1} y2={b.sy + 3} stroke="currentColor" strokeWidth={0.8} strokeLinecap="round" />);
        }
        return <g opacity={0.85}>{legs}</g>;
      })()}
      <SCube origin={co} size={[cw, cd, ch]} face={{ top: 0.14, left: 0.2, right: 0.12 }} strokeWidth={1.4} />
      {/* violet die on top + halo */}
      <g style={{ color: VIOLET }}>
        {(() => {
          const inset = 3;
          const dTL = P(co[0] + inset, co[1] + inset, co[2] + ch);
          const dTR = P(co[0] + cw - inset, co[1] + inset, co[2] + ch);
          const dBR = P(co[0] + cw - inset, co[1] + cd - inset, co[2] + ch);
          const dBL = P(co[0] + inset, co[1] + cd - inset, co[2] + ch);
          const cx = (dTL.sx + dBR.sx) / 2;
          const cy = (dTL.sy + dBR.sy) / 2;
          return (
            <g>
              <polygon points={poly([dTL, dTR, dBR, dBL])} fill="currentColor" fillOpacity={0.4} stroke="currentColor" strokeWidth={1.1} strokeLinejoin="round" />
              {/* die traces */}
              {[0.3, 0.5, 0.7].map((t, i) => {
                const a = lerp(dTL, dBL, t);
                const b = lerp(dTR, dBR, t);
                return <line key={i} x1={a.sx} y1={a.sy} x2={b.sx} y2={b.sy} stroke="currentColor" strokeWidth={0.4} opacity={0.7} />;
              })}
              <Marker at={[cx, cy]} kind="halo" size={2.4} />
            </g>
          );
        })()}
      </g>
      {/* chip label — below the browser slab with a leader to the chip's base
          (was printed across the viewport's front edge lines) */}
      {(() => {
        const chipBase = P(4, 6, co[2]); // near the chip's front-left leg
        return (
          <g>
            <circle cx={chipBase.sx} cy={chipBase.sy + 3} r={1} fill="currentColor" opacity={0.8} />
            <line x1={chipBase.sx} y1={chipBase.sy + 3} x2={84} y2={186} stroke="currentColor" strokeWidth={0.5} strokeDasharray="3 2" opacity={0.6} />
            <text x={80} y={193} textAnchor="middle" fontFamily="ui-monospace, monospace" fontSize={4.6} letterSpacing="0.8" fontWeight={600} fill="currentColor">
              ONNX · int8
            </text>
          </g>
        );
      })()}

      {/* ---- Caption plate ------------------------------------------ */}
      {(() => {
        const cx = 100;
        const cy = 250;
        const w = 74;
        const h = 15;
        return (
          <g>
            <rect x={cx - w / 2} y={cy - h / 2} width={w} height={h} rx={2.4} fill="currentColor" fillOpacity={0.06} stroke="currentColor" strokeWidth={0.9} />
            <circle cx={cx - w / 2 + 8} cy={cy} r={2} fill={VIOLET} />
            <text x={cx - w / 2 + 15} y={cy + 2.6} fontFamily="ui-monospace, monospace" fontSize={7} fontWeight={700} letterSpacing="0.4" fill="currentColor">
              22.8 MB
            </text>
            <text x={cx + w / 2 - 4} y={cy + 2.4} textAnchor="end" fontFamily="ui-monospace, monospace" fontSize={4.4} letterSpacing="1.4" fill="currentColor" opacity={0.75}>
              WASM
            </text>
          </g>
        );
      })()}
    </SceneFrame>
  );
};
