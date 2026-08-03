import React from "react";
import { COLORS } from "../../theme";
import { SceneFrame, iso } from "./primitives";

/**
 * SECURITY — the trust story. A heater shield with a keyhole stands on a small
 * isometric plinth; the plinth carries five permission slots, only one of which
 * (read) is filled — the rest (send / delete / modify / compose) are struck,
 * the least-privilege grant drawn literally. Near-white linework on the dark
 * ground; indigo is the single trust accent.
 *
 * Deliberately sparse on labels (unlike a gauge) so nothing crowds or clips at
 * the frame edge — the shape carries the meaning.
 */

const LINE = COLORS.ON_DARK;
const INDIGO = COLORS.SECURITY_INDIGO;

const CX = 108;

// Iso plinth projection (centered under the shield point).
const PB = (x: number, y: number, z = 0) => {
  const p = iso(x, y, z);
  return { sx: p.sx * 1.6 + CX, sy: p.sy * 1.6 + 214 };
};
const poly = (pts: { sx: number; sy: number }[]) =>
  pts.map((p) => `${p.sx.toFixed(2)},${p.sy.toFixed(2)}`).join(" ");

export const SecurityShield: React.FC = () => {
  return (
    <SceneFrame
      lineColor={LINE}
      cornerLabels={{ topLeft: "LEAST PRIVILEGE", bottomRight: "READONLY" }}
    >
      {/* ---- Iso plinth ------------------------------------------------ */}
      {(() => {
        const o: [number, number] = [-26, -9];
        const w = 52;
        const d = 18;
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
            <polygon points={poly([bl, br, br0, bl0])} fill="currentColor" fillOpacity={0.16} stroke="currentColor" strokeWidth={1.0} strokeLinejoin="round" />
            <polygon points={poly([br, tr, tr0, br0])} fill="currentColor" fillOpacity={0.1} stroke="currentColor" strokeWidth={0.8} strokeLinejoin="round" />
            <polygon points={poly([tl, tr, br, bl])} fill="currentColor" fillOpacity={0.06} stroke="currentColor" strokeWidth={1.1} strokeLinejoin="round" />
          </g>
        );
      })()}

      {/* ---- Five permission slots on the plinth (only read is filled) - */}
      {(() => {
        const n = 5;
        const slotW = 6.5;
        const gap = 4.5;
        const total = n * slotW + (n - 1) * gap;
        const x0 = CX - total / 2;
        const y = 202;
        const labels = ["read", "send", "del", "mod", "cmp"];
        return (
          <g>
            {labels.map((lab, i) => {
              const x = x0 + i * (slotW + gap);
              const granted = i === 0;
              return (
                <g key={lab}>
                  <rect
                    x={x}
                    y={y - slotW}
                    width={slotW}
                    height={slotW}
                    rx={1}
                    fill={granted ? "currentColor" : "none"}
                    stroke="currentColor"
                    strokeWidth={granted ? 0 : 0.7}
                    strokeOpacity={granted ? 1 : 0.5}
                    {...(granted ? { style: { color: INDIGO } } : {})}
                  />
                  {granted && (
                    <path
                      d={`M ${x + 1.6} ${y - slotW / 2} l 1.6 1.7 l 2.8 -3.4`}
                      fill="none"
                      stroke={COLORS.GROUND}
                      strokeWidth={0.9}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  )}
                  {!granted && (
                    <line
                      x1={x + 1}
                      y1={y - 1}
                      x2={x + slotW - 1}
                      y2={y - slotW + 1}
                      stroke="currentColor"
                      strokeWidth={0.7}
                      strokeOpacity={0.45}
                    />
                  )}
                </g>
              );
            })}
            {/* caption below the plinth (at y+9 it was crossed by the
                plinth's front-top edge) */}
            <text x={CX} y={252} textAnchor="middle" fontFamily="ui-monospace, monospace" fontSize={4} letterSpacing="0.8" fill="currentColor" opacity={0.7}>
              1 GRANTED · 4 WITHHELD
            </text>
          </g>
        );
      })()}

      {/* ---- Shield silhouette ---------------------------------------- */}
      <path
        d="M 70 60 L 146 60 C 146 118, 138 156, 108 184 C 78 156, 70 118, 70 60 Z"
        fill="currentColor"
        fillOpacity={0.05}
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinejoin="round"
      />
      {/* inner keyline in indigo */}
      <g style={{ color: INDIGO }}>
        <path
          d="M 78 68 L 138 68 C 138 116, 131 150, 108 173 C 85 150, 78 116, 78 68 Z"
          fill="none"
          stroke="currentColor"
          strokeWidth={0.9}
          strokeOpacity={0.9}
          strokeLinejoin="round"
        />
        {/* keyhole */}
        <circle cx={CX} cy={104} r={9} fill="currentColor" fillOpacity={0.9} />
        <path d={`M ${CX - 3.4} 111 L ${CX + 3.4} 111 L ${CX + 5.4} 132 L ${CX - 5.4} 132 Z`} fill="currentColor" fillOpacity={0.9} />
      </g>

      {/* ---- Encrypted-at-rest annotation ----------------------------- */}
      <g opacity={0.55}>
        <line x1={148} y1={92} x2={176} y2={78} stroke="currentColor" strokeWidth={0.5} strokeDasharray="4 3" />
        <circle cx={148} cy={92} r={1.2} fill="currentColor" />
        <text x={178} y={80} fontFamily="ui-monospace, monospace" fontSize={4.4} letterSpacing="0.6" fill="currentColor">
          fernet
        </text>
      </g>
      <g opacity={0.55}>
        <line x1={68} y1={128} x2={40} y2={142} stroke="currentColor" strokeWidth={0.5} strokeDasharray="4 3" />
        <circle cx={68} cy={128} r={1.2} fill="currentColor" />
        <text x={38} y={144} textAnchor="end" fontFamily="ui-monospace, monospace" fontSize={4.4} letterSpacing="0.6" fill="currentColor">
          revocable
        </text>
      </g>
    </SceneFrame>
  );
};
