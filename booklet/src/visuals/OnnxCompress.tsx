import React from "react";
import { COLORS, FONTS } from "../theme";
import { INSIDE } from "../content";

/**
 * The int8 export, drawn to scale. Two proportional bars — float32 (90.4 MB)
 * and int8 (22.8 MB) — so the ~4× compression is visible, not just stated.
 */
export const OnnxCompress: React.FC = () => {
  const { before, after, ratio, exact } = INSIDE.onnx;
  // 90.4 MB is full width; 22.8 MB is scaled to its true proportion.
  const fp32 = 90.4;
  const int8 = 22.8;
  const afterPct = (int8 / fp32) * 100;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <Bar
        pct={100}
        fill={COLORS.STEEL}
        value={before.value}
        label={before.label}
        ink={COLORS.STEEL_DEEP}
      />
      <Bar
        pct={afterPct}
        fill={COLORS.E5_VIOLET}
        value={after.value}
        label={after.label}
        ink={COLORS.E5_DEEP}
        highlight
      />
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 12,
          paddingTop: 4,
          borderTop: `0.5pt solid ${COLORS.HAIRLINE}`,
        }}
      >
        <span
          style={{
            fontFamily: FONTS.MONO,
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: "0.06em",
            color: COLORS.E5_DEEP,
          }}
        >
          {ratio} · dynamic int8 quantization
        </span>
        <span
          style={{
            fontFamily: FONTS.MONO,
            fontSize: 8,
            color: COLORS.INK_SUBTLE,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {exact}
        </span>
      </div>
    </div>
  );
};

const Bar: React.FC<{
  pct: number;
  fill: string;
  value: string;
  label: string;
  ink: string;
  highlight?: boolean;
}> = ({ pct, fill, value, label, ink, highlight = false }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
    <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
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
      <span
        style={{
          fontFamily: FONTS.MONO,
          fontSize: highlight ? 20 : 15,
          fontWeight: 700,
          color: ink,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </span>
    </div>
    <div
      style={{
        height: highlight ? 18 : 14,
        width: "100%",
        background: COLORS.SURFACE,
        borderRadius: 3,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          height: "100%",
          width: `${pct}%`,
          background: fill,
          borderRadius: 3,
        }}
      />
    </div>
  </div>
);
