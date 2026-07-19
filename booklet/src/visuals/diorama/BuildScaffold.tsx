import React from "react";
import { COLORS } from "../../theme";
import { SceneFrame, FlowChannel, Marker, iso } from "./primitives";

/**
 * BUILD — the shipping pipeline as scaffolding. Five stacked isometric
 * platforms name the stages the model passes through on its way out:
 *
 *   TRAIN → MLflow → ONNX → HF·SPACE → WEB
 *
 * A steel flow thread climbs the left face through every tier; a gantry
 * straddles the tower and lowers the shipped artifact onto the top (WEB)
 * platform. Near-white linework on the dark ground; steel is the single
 * accent — the moving pipeline and its shipped output.
 */

const LINE = COLORS.ON_DARK;
const STEEL = COLORS.STEEL;

const SCALE = 1.55;
const OFFSET_X = 96;
const OFFSET_Y = 250;
const P = (x: number, y: number, z = 0) => {
  const p = iso(x, y, z);
  return { sx: p.sx * SCALE + OFFSET_X, sy: p.sy * SCALE + OFFSET_Y };
};

const poly = (pts: { sx: number; sy: number }[]) =>
  pts.map((p) => `${p.sx.toFixed(2)},${p.sy.toFixed(2)}`).join(" ");

const FW = 40;
const FD = 26;
const OX = -FW / 2;
const OY = -FD / 2;
const HH = 4;
const STEP = 13;

type Tier = { z: number; name: string; idx: string };
const TIERS: readonly Tier[] = [
  { z: 0, name: "TRAIN", idx: "1" },
  { z: STEP, name: "MLflow", idx: "2" },
  { z: STEP * 2, name: "ONNX", idx: "3" },
  { z: STEP * 3, name: "HF·SPACE", idx: "4" },
  { z: STEP * 4, name: "WEB", idx: "5" },
];

export const BuildScaffold: React.FC = () => {
  // Left-face flow anchor points, one per tier.
  const flowPts = TIERS.map((t) => P(OX - 2, OY + FD + 2, t.z + HH * 0.5));
  const webTopCenter = P(0, 0, TIERS[4]!.z + HH);

  // Gantry frame geometry (screen space).
  const beamY = 122;
  const postL = 48;
  const postR = 146;
  const baseY = 268;

  return (
    <SceneFrame
      lineColor={LINE}
      cornerLabels={{ topLeft: "BUILD · PIPELINE", bottomRight: "SHIPPED" }}
    >
      {/* Ground plane */}
      {(() => {
        const a = P(-36, -28, 0);
        const b = P(36, -28, 0);
        const c = P(36, 30, 0);
        const d = P(-36, 30, 0);
        return <polygon points={poly([a, b, c, d])} fill="currentColor" fillOpacity={0.04} stroke="currentColor" strokeWidth={0.5} strokeOpacity={0.3} strokeLinejoin="round" />;
      })()}

      {/* Foundation slab */}
      {(() => {
        const s = 2.5;
        const a = P(OX - s, OY - s, 0);
        const b = P(OX + FW + s, OY - s, 0);
        const c = P(OX + FW + s, OY + FD + s, 0);
        const d = P(OX - s, OY + FD + s, 0);
        return <polygon points={poly([a, b, c, d])} fill="currentColor" fillOpacity={0.2} stroke="currentColor" strokeWidth={1.0} strokeLinejoin="round" />;
      })()}

      {/* Gantry posts + beam (behind the tower) */}
      <g stroke="currentColor" strokeWidth={1.2} strokeLinecap="round" opacity={0.85}>
        <line x1={postL} y1={baseY} x2={postL} y2={beamY} />
        <line x1={postR} y1={baseY} x2={postR} y2={beamY} />
        <line x1={postL - 3} y1={beamY} x2={postR + 3} y2={beamY} />
        {/* post feet */}
        <line x1={postL - 4} y1={baseY} x2={postL + 4} y2={baseY} strokeWidth={1.4} />
        <line x1={postR - 4} y1={baseY} x2={postR + 4} y2={baseY} strokeWidth={1.4} />
        {/* diagonal braces */}
        <line x1={postL} y1={beamY + 14} x2={postL + 12} y2={beamY} strokeWidth={0.6} strokeDasharray="2 2" opacity={0.6} />
        <line x1={postR} y1={beamY + 14} x2={postR - 12} y2={beamY} strokeWidth={0.6} strokeDasharray="2 2" opacity={0.6} />
      </g>

      {/* ---- Five stacked platforms (back-to-front by z) ------------ */}
      {TIERS.map((t) => {
        const zt = t.z + HH;
        const p000 = P(OX, OY, t.z);
        const p100 = P(OX + FW, OY, t.z);
        const p110 = P(OX + FW, OY + FD, t.z);
        const p010 = P(OX, OY + FD, t.z);
        const p001 = P(OX, OY, zt);
        const p101 = P(OX + FW, OY, zt);
        const p111 = P(OX + FW, OY + FD, zt);
        const p011 = P(OX, OY + FD, zt);
        const isWeb = t.name === "WEB";
        return (
          <g key={t.name}>
            <polygon points={poly([p000, p001, p011, p010])} fill="currentColor" fillOpacity={0.15} stroke="currentColor" strokeWidth={0.9} strokeLinejoin="round" />
            <polygon points={poly([p100, p101, p111, p110])} fill="currentColor" fillOpacity={0.08} stroke="currentColor" strokeWidth={0.9} strokeLinejoin="round" />
            <polygon
              points={poly([p001, p101, p111, p011])}
              fill="currentColor"
              fillOpacity={isWeb ? 0.1 : 0.05}
              stroke={isWeb ? STEEL : "currentColor"}
              strokeWidth={isWeb ? 1.5 : 1.1}
              strokeLinejoin="round"
            />
          </g>
        );
      })}

      {/* ---- Steel flow thread climbing the left face --------------- */}
      <g style={{ color: STEEL }}>
        {flowPts.slice(0, -1).map((p, i) => {
          const next = flowPts[i + 1]!;
          return <FlowChannel key={i} from={[p.sx, p.sy]} to={[next.sx, next.sy]} curvature={i % 2 === 0 ? 0.2 : -0.2} dashed dashPattern="3 3" strokeWidth={1.1} tracer={i === flowPts.length - 2} />;
        })}
        {flowPts.map((p, i) => (
          <Marker key={i} at={[p.sx, p.sy]} kind={i === flowPts.length - 1 ? "ring" : "dot"} size={1.5} />
        ))}
      </g>

      {/* ---- Gantry trolley + cable + shipped artifact (steel) ------ */}
      <g style={{ color: STEEL }}>
        <rect x={webTopCenter.sx - 5} y={beamY - 2.5} width={10} height={4} rx={0.8} fill="currentColor" fillOpacity={0.3} stroke="currentColor" strokeWidth={1.0} />
        <line x1={webTopCenter.sx} y1={beamY + 1.5} x2={webTopCenter.sx} y2={webTopCenter.sy - 16} stroke="currentColor" strokeWidth={0.6} strokeDasharray="1.5 2" />
        {/* shipped box being lowered onto WEB */}
        {(() => {
          const bx = webTopCenter.sx;
          const by = webTopCenter.sy - 11;
          return (
            <g>
              <rect x={bx - 6} y={by - 6} width={12} height={12} rx={1.2} fill="currentColor" fillOpacity={0.22} stroke="currentColor" strokeWidth={1.3} strokeLinejoin="round" />
              <path d={`M ${bx - 3} ${by} l 2.2 2.4 l 4.4 -5`} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
            </g>
          );
        })()}
      </g>

      {/* ---- Right-edge stage labels -------------------------------- */}
      {TIERS.map((t) => {
        const edge = P(OX + FW, OY, t.z + HH * 0.5);
        const lx = 152;
        const isWeb = t.name === "WEB";
        return (
          <g key={`lab-${t.name}`}>
            <line x1={edge.sx + 2} y1={edge.sy} x2={lx - 3} y2={edge.sy} stroke="currentColor" strokeWidth={0.4} opacity={0.4} />
            <circle cx={edge.sx + 2} cy={edge.sy} r={1} fill={isWeb ? STEEL : "currentColor"} opacity={isWeb ? 1 : 0.6} />
            <text x={lx} y={edge.sy - 0.5} fontFamily="ui-monospace, monospace" fontSize={3.4} letterSpacing="0.6" fill="currentColor" opacity={0.55}>
              {`S${t.idx}`}
            </text>
            <text x={lx} y={edge.sy + 4.6} fontFamily="ui-monospace, monospace" fontSize={5} fontWeight={isWeb ? 700 : 600} letterSpacing="0.6" fill={isWeb ? STEEL : "currentColor"} opacity={isWeb ? 1 : 0.9}>
              {t.name}
            </text>
          </g>
        );
      })}

      {/* SHIPPED flag on top */}
      {(() => {
        const p = P(0, 0, TIERS[4]!.z + HH);
        return (
          <text x={p.sx} y={p.sy + 6} textAnchor="middle" fontFamily="ui-monospace, monospace" fontSize={3.6} letterSpacing="1" fill="currentColor" opacity={0.7}>
            v1.0 · LIVE
          </text>
        );
      })()}
    </SceneFrame>
  );
};
