import React from "react";
import { COLORS } from "../../theme";
import { SceneFrame, iso } from "./primitives";

/**
 * PROOF — the verdict. A vertical instrument gauge reads the held-out
 * macro-F1 (0.979): a green needle pegged near the top, a ring of ticks,
 * and one amber tick pinning the 0.95 confidence-interval floor below it.
 * The gauge stands on a small isometric plinth carrying nine short bars —
 * the nine classes, every one clearing the amber floor.
 *
 * Near-white linework on the dark ground; green is the verdict, amber the
 * single floor it must clear.
 */

const LINE = COLORS.ON_DARK;
const GREEN = COLORS.SETFIT_GREEN;
const AMBER = COLORS.GATE_AMBER;

// Gauge geometry (billboard).
const GX = 124;
const GY = 112;
const R = 62;

// value 0.90..1.00 → fraction 0..1
const fOf = (v: number) => (v - 0.9) / 0.1;
// fraction → point on the right-half arc (bottom → right → top)
const arcPt = (f: number, radius = R) => {
  const phi = -Math.PI / 2 + f * Math.PI;
  return { sx: GX + radius * Math.cos(phi), sy: GY - radius * Math.sin(phi) };
};

// Iso plinth projection.
const PB = (x: number, y: number, z = 0) => {
  const p = iso(x, y, z);
  return { sx: p.sx * 1.5 + GX, sy: p.sy * 1.5 + 214 };
};
const poly = (pts: { sx: number; sy: number }[]) =>
  pts.map((p) => `${p.sx.toFixed(2)},${p.sy.toFixed(2)}`).join(" ");

export const ProofPodium: React.FC = () => {
  const needleF = fOf(0.979);
  const floorF = fOf(0.95);
  const needleTip = arcPt(needleF, R * 0.9);
  const floorOuter = arcPt(floorF, R);
  const floorInner = arcPt(floorF, R - 9);

  return (
    <SceneFrame
      lineColor={LINE}
      cornerLabels={{ topLeft: "HELD-OUT EVAL", bottomRight: "CI FLOOR 0.95" }}
    >
      {/* ---- Iso plinth --------------------------------------------- */}
      {(() => {
        const o: [number, number] = [-28, -10];
        const w = 56;
        const d = 20;
        const h = 5;
        const tl = PB(o[0], o[1], h);
        const tr = PB(o[0] + w, o[1], h);
        const br = PB(o[0] + w, o[1] + d, h);
        const bl = PB(o[0], o[1] + d, h);
        const bl0 = PB(o[0], o[1] + d, 0);
        const br0 = PB(o[0] + w, o[1] + d, 0);
        const tr0 = PB(o[0] + w, o[1], 0);
        return (
          <g>
            {/* front + right thickness */}
            <polygon points={poly([bl, br, br0, bl0])} fill="currentColor" fillOpacity={0.16} stroke="currentColor" strokeWidth={1.0} strokeLinejoin="round" />
            <polygon points={poly([br, tr, tr0, br0])} fill="currentColor" fillOpacity={0.1} stroke="currentColor" strokeWidth={0.8} strokeLinejoin="round" />
            {/* top */}
            <polygon points={poly([tl, tr, br, bl])} fill="currentColor" fillOpacity={0.06} stroke="currentColor" strokeWidth={1.1} strokeLinejoin="round" />
          </g>
        );
      })()}

      {/* ---- Nine class bars on the plinth (all clear the floor) ----- */}
      {(() => {
        const n = 9;
        const bw = 3.4;
        const gap = 2.2;
        const total = n * bw + (n - 1) * gap;
        const x0 = GX - total / 2;
        const baseY = 210;
        const floorY = baseY - 9;
        const heights = [13, 15, 12, 14, 13, 15, 12, 14, 13];
        return (
          <g>
            {heights.map((hv, i) => {
              const x = x0 + i * (bw + gap);
              return <rect key={i} x={x} y={baseY - hv} width={bw} height={hv} fill="currentColor" fillOpacity={0.9} stroke="currentColor" strokeWidth={0.5} />;
            })}
            {/* amber floor line under the bar tops */}
            <g style={{ color: AMBER }}>
              <line x1={x0 - 4} y1={floorY} x2={x0 + total + 4} y2={floorY} stroke="currentColor" strokeWidth={0.8} strokeDasharray="3 2" />
              <circle cx={x0 - 4} cy={floorY} r={1.2} fill="currentColor" />
              <text x={x0 + total + 7} y={floorY + 1.6} fontFamily="ui-monospace, monospace" fontSize={3.6} letterSpacing="0.6" fill="currentColor">
                0.95
              </text>
            </g>
            {/* caption below the plinth (was y 218 — crossed by the plinth's
                front-top edge) */}
            <text x={GX} y={252} textAnchor="middle" fontFamily="ui-monospace, monospace" fontSize={3.8} letterSpacing="1" fill="currentColor" opacity={0.7}>
              9 CLASSES · ALL PASS
            </text>
          </g>
        );
      })()}

      {/* ---- Gauge arc + ticks (sweep 0 = the RIGHT half, matching the
              ticks/needle — sweep 1 drew the arc through the score plate) -- */}
      <path d={`M ${GX} ${GY + R} A ${R} ${R} 0 0 0 ${GX} ${GY - R}`} fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" />
      {/* faint inner arc */}
      <path d={`M ${GX} ${GY + (R - 9)} A ${R - 9} ${R - 9} 0 0 0 ${GX} ${GY - (R - 9)}`} fill="none" stroke="currentColor" strokeWidth={0.5} opacity={0.35} />
      {Array.from({ length: 41 }).map((_, i) => {
        const f = i / 40;
        const major = i % 10 === 0;
        const outer = arcPt(f, R);
        const inner = arcPt(f, R - (major ? 7 : 4));
        return <line key={i} x1={outer.sx} y1={outer.sy} x2={inner.sx} y2={inner.sy} stroke="currentColor" strokeWidth={major ? 0.9 : 0.5} opacity={major ? 0.9 : 0.5} />;
      })}
      {/* end labels */}
      {(() => {
        const lo = arcPt(0, R + 7);
        const hi = arcPt(1, R + 7);
        return (
          <g fontFamily="ui-monospace, monospace" fontSize={3.8} letterSpacing="0.5" fill="currentColor" opacity={0.75}>
            <text x={lo.sx + 4} y={lo.sy + 1.5}>0.90</text>
            <text x={hi.sx + 4} y={hi.sy + 1.5}>1.00</text>
          </g>
        );
      })()}

      {/* ---- Amber floor tick at 0.95 (label lives on the left plate, so
              nothing runs off the right frame edge) --------------------- */}
      <g style={{ color: AMBER }}>
        <line x1={floorOuter.sx} y1={floorOuter.sy} x2={floorInner.sx} y2={floorInner.sy} stroke="currentColor" strokeWidth={2} strokeLinecap="round" />
        <circle cx={floorOuter.sx} cy={floorOuter.sy} r={1.6} fill="currentColor" />
      </g>

      {/* ---- Green needle + hub ------------------------------------- */}
      <g style={{ color: GREEN }}>
        <line x1={GX} y1={GY} x2={needleTip.sx} y2={needleTip.sy} stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" />
        <circle cx={GX} cy={GY} r={3.4} fill="currentColor" fillOpacity={0.25} stroke="currentColor" strokeWidth={1.2} />
        <circle cx={GX} cy={GY} r={1.3} fill="currentColor" />
        <circle cx={needleTip.sx} cy={needleTip.sy} r={1.6} fill="currentColor" />
      </g>

      {/* ---- Score plate (left, in the open half) ------------------- */}
      {(() => {
        const cx = 52;
        return (
          <g textAnchor="middle">
            <text x={cx} y={88} fontFamily="ui-monospace, monospace" fontSize={5.6} letterSpacing="1.4" fill="currentColor" opacity={0.7}>
              MACRO-F1
            </text>
            <text x={cx} y={122} fontFamily="ui-monospace, monospace" fontSize={30} fontWeight={700} letterSpacing="-0.5" fill="currentColor" stroke="currentColor" strokeWidth={0.3}>
              0.979
            </text>
            <g style={{ color: GREEN }}>
              <text x={cx} y={138} fontFamily="ui-monospace, monospace" fontSize={4.4} letterSpacing="0.6" fill="currentColor">
                held-out · passing
              </text>
            </g>
            {/* CI-floor legend, kept on the open left half (no edge clip) */}
            <g style={{ color: AMBER }}>
              <line x1={cx - 20} y1={150} x2={cx - 12} y2={150} stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" />
              <text x={cx - 8} y={152} textAnchor="start" fontFamily="ui-monospace, monospace" fontSize={4.2} letterSpacing="0.4" fill="currentColor">
                0.95 CI floor
              </text>
            </g>
          </g>
        );
      })()}
    </SceneFrame>
  );
};
