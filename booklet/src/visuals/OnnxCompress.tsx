import React from "react";
import { COLORS, FONTS } from "../theme";
import { INSIDE } from "../content";

/**
 * The int8 export, drawn to scale — as AREA, not bars. The outer square is the
 * 90.4 MB float32 graph; the nested square is the 22.8 MB int8 model, its SIDE
 * scaled by √(22.8 / 90.4) so its AREA is the true ~25 % of the original. The
 * ~4× compression is something you see at a glance, not just read.
 */
export const OnnxCompress: React.FC = () => {
  const { before, after, ratio, exact } = INSIDE.onnx;
  const fp32 = 90.4;
  const int8 = 22.8;

  // SVG geometry. Outer square side = OUTER; inner side scaled by √ratio so
  // AREA is proportional to file size.
  const PAD = 10;
  const OUTER = 150;
  const innerSide = OUTER * Math.sqrt(int8 / fp32);
  const innerX = PAD;
  const innerY = PAD + (OUTER - innerSide); // anchor bottom-left inside outer

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 30 }}>
      {/* Nested-area square */}
      <svg width={OUTER + PAD * 2} height={OUTER + PAD * 2} viewBox={`0 0 ${OUTER + PAD * 2} ${OUTER + PAD * 2}`} style={{ flexShrink: 0, overflow: "visible" }}>
        {/* outer = float32 */}
        <rect x={PAD} y={PAD} width={OUTER} height={OUTER} rx={4} fill={COLORS.STEEL} fillOpacity={0.08} stroke={COLORS.STEEL_DEEP} strokeWidth={1} />
        {/* inner = int8 */}
        <rect x={innerX} y={innerY} width={innerSide} height={innerSide} rx={3} fill={COLORS.E5_VIOLET} fillOpacity={0.9} stroke={COLORS.E5_DEEP} strokeWidth={1} />
        <text
          x={innerX + innerSide / 2}
          y={innerY + innerSide / 2 + 3}
          textAnchor="middle"
          fontFamily="ui-monospace, monospace"
          fontSize={9}
          fontWeight={700}
          fill={COLORS.PAPER}
        >
          int8
        </text>
        {/* float32 corner tag */}
        <text x={PAD + OUTER - 4} y={PAD + 12} textAnchor="end" fontFamily="ui-monospace, monospace" fontSize={8} fontWeight={600} fill={COLORS.STEEL_DEEP} letterSpacing="0.06em">
          float32
        </text>
      </svg>

      {/* Legend + ratio */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 12 }}>
        <LegendRow swatch={COLORS.STEEL} ink={COLORS.STEEL_DEEP} value={before.value} label={before.label} big={false} />
        <LegendRow swatch={COLORS.E5_VIOLET} ink={COLORS.E5_DEEP} value={after.value} label={after.label} big />
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            justifyContent: "space-between",
            gap: 12,
            paddingTop: 10,
            borderTop: `0.5pt solid ${COLORS.HAIRLINE}`,
          }}
        >
          <span style={{ fontFamily: FONTS.MONO, fontSize: 9, fontWeight: 700, letterSpacing: "0.06em", color: COLORS.E5_DEEP }}>
            {ratio} · dynamic int8 quantization
          </span>
          <span style={{ fontFamily: FONTS.MONO, fontSize: 8, color: COLORS.INK_SUBTLE, fontVariantNumeric: "tabular-nums" }}>{exact}</span>
        </div>
        <span style={{ fontFamily: FONTS.SERIF, fontStyle: "italic", fontSize: 10.5, color: COLORS.INK_SUBTLE }}>
          Area is drawn proportional to file size — the int8 square is a quarter of the float32 square.
        </span>
      </div>
    </div>
  );
};

const LegendRow: React.FC<{ swatch: string; ink: string; value: string; label: string; big: boolean }> = ({
  swatch,
  ink,
  value,
  label,
  big,
}) => (
  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
    <span style={{ width: 12, height: 12, borderRadius: 2, background: swatch, flexShrink: 0 }} />
    <span
      style={{
        fontFamily: FONTS.MONO,
        fontSize: big ? 22 : 17,
        fontWeight: 700,
        color: ink,
        fontVariantNumeric: "tabular-nums",
        minWidth: "1.5in",
      }}
    >
      {value}
    </span>
    <span
      style={{
        fontFamily: FONTS.MONO,
        fontSize: 9,
        fontWeight: 600,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        color: COLORS.INK_MUTED,
      }}
    >
      {label}
    </span>
  </div>
);
