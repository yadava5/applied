import React from "react";
import { COLORS, FONTS } from "../theme";
import { HOW } from "../content";

/**
 * The 0.85 confidence gate drawn as a probability axis. Three zones — fall
 * back (< 0.70), flag (0.70–0.84), auto-file (≥ 0.85) — with a bold gate line
 * at 0.85. Below, the three bands as a legend keyed to the app's thresholds.
 */

const TONE: Record<string, { fill: string; ink: string }> = {
  setfit: { fill: COLORS.SETFIT_TINT, ink: COLORS.SETFIT_DEEP },
  gate: { fill: COLORS.GATE_TINT, ink: COLORS.GATE_DEEP },
  danger: { fill: COLORS.DANGER_TINT, ink: COLORS.DANGER },
};

export const ConfidenceGate: React.FC = () => (
  <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
    {/* Axis */}
    <div>
      <div
        style={{
          position: "relative",
          height: 34,
          borderRadius: 5,
          overflow: "hidden",
          border: `0.5pt solid ${COLORS.HAIRLINE}`,
          display: "flex",
        }}
      >
        <Zone width={70} fill={COLORS.DANGER_TINT} label="fall back" ink={COLORS.DANGER} />
        <Zone width={15} fill={COLORS.GATE_TINT} label="flag" ink={COLORS.GATE_DEEP} />
        <Zone width={15} fill={COLORS.SETFIT_TINT} label="auto-file" ink={COLORS.SETFIT_DEEP} />
        {/* gate line at 85% */}
        <div
          style={{
            position: "absolute",
            top: -3,
            bottom: -3,
            left: "85%",
            width: 2,
            background: COLORS.GATE_AMBER,
          }}
        />
      </div>
      {/* ticks */}
      <div style={{ position: "relative", height: 16, marginTop: 3 }}>
        {[
          { at: 0, label: "0.00" },
          { at: 70, label: "0.70" },
          { at: 100, label: "1.00" },
        ].map((t) => (
          <div
            key={t.at}
            style={{
              position: "absolute",
              left: `${t.at}%`,
              transform:
                t.at === 0 ? "translateX(0)" : t.at === 100 ? "translateX(-100%)" : "translateX(-50%)",
              fontFamily: FONTS.MONO,
              fontSize: 8,
              fontWeight: 500,
              color: COLORS.INK_MUTED,
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {t.label}
          </div>
        ))}
        {/* gate tick — the ▲ itself is centered under the 0.85 line, and the
            text hangs to its right, so the pointer points at the marker */}
        <div
          style={{
            position: "absolute",
            left: "85%",
            transform: "translateX(-50%)",
            fontFamily: FONTS.MONO,
            fontSize: 8,
            fontWeight: 700,
            color: COLORS.GATE_DEEP,
          }}
        >
          ▲
        </div>
        <div
          style={{
            position: "absolute",
            left: "85%",
            marginLeft: 7,
            fontFamily: FONTS.MONO,
            fontSize: 8,
            fontWeight: 700,
            color: COLORS.GATE_DEEP,
            fontVariantNumeric: "tabular-nums",
            whiteSpace: "nowrap",
          }}
        >
          0.85 gate
        </div>
      </div>
    </div>

    {/* Bands */}
    <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
      {HOW.gate.bands.map((b) => {
        const tone = TONE[b.tone] ?? TONE.gate!;
        return (
          <div
            key={b.range}
            style={{
              display: "grid",
              gridTemplateColumns: "84px 92px 1fr",
              alignItems: "center",
              gap: 12,
              background: tone.fill,
              borderRadius: 4,
              padding: "7px 10px",
            }}
          >
            <span
              style={{
                fontFamily: FONTS.MONO,
                fontSize: 11,
                fontWeight: 700,
                color: tone.ink,
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {b.range}
            </span>
            <span
              style={{
                fontFamily: FONTS.MONO,
                fontSize: 8.5,
                fontWeight: 700,
                letterSpacing: "0.1em",
                textTransform: "uppercase",
                color: tone.ink,
              }}
            >
              {b.verb}
            </span>
            <span
              style={{
                fontFamily: FONTS.SANS,
                fontSize: 10.5,
                fontWeight: 500,
                color: COLORS.INK,
              }}
            >
              {b.detail}
            </span>
          </div>
        );
      })}
    </div>
  </div>
);

const Zone: React.FC<{ width: number; fill: string; label: string; ink: string }> = ({
  width,
  fill,
  label,
  ink,
}) => (
  <div
    style={{
      width: `${width}%`,
      background: fill,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontFamily: FONTS.MONO,
      fontSize: 8,
      fontWeight: 700,
      letterSpacing: "0.08em",
      textTransform: "uppercase",
      color: ink,
      borderRight: width < 100 ? `0.5pt solid ${COLORS.HAIRLINE}` : "none",
    }}
  >
    {width >= 15 ? label : ""}
  </div>
);
