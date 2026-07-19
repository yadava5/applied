import React from "react";
import { COLORS, FONTS } from "../theme";
import { CATEGORIES } from "../content";

/**
 * The 9-category taxonomy. Eight model-predicted outcomes in a grid, plus
 * needs_review set apart with an amber dashed border — because it is not a
 * trained label at all, but the confidence gate's output.
 */
export const ClassGrid: React.FC = () => {
  const predicted = CATEGORIES.filter((c) => c.predicted);
  const review = CATEGORIES.find((c) => !c.predicted)!;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 8,
        }}
      >
        {predicted.map((c) => (
          <div
            key={c.id}
            style={{
              border: `0.5pt solid ${COLORS.HAIRLINE}`,
              borderLeft: `2.5px solid ${COLORS.SETFIT_GREEN}`,
              borderRadius: 4,
              padding: "8px 10px",
              background: COLORS.PAPER_ELEVATED,
              display: "flex",
              flexDirection: "column",
              gap: 3,
            }}
          >
            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8 }}>
              <span
                style={{
                  fontFamily: FONTS.MONO,
                  fontSize: 11,
                  fontWeight: 700,
                  color: COLORS.INK,
                }}
              >
                {c.label}
              </span>
              <span
                style={{
                  fontFamily: FONTS.MONO,
                  fontSize: 8,
                  fontWeight: 600,
                  color: COLORS.INK_SUBTLE,
                  fontVariantNumeric: "tabular-nums",
                  whiteSpace: "nowrap",
                }}
              >
                {c.rules > 0 ? `${c.rules} rules` : "no rules"}
              </span>
            </div>
            <span
              style={{
                fontFamily: FONTS.SERIF,
                fontStyle: "italic",
                fontSize: 10,
                lineHeight: 1.3,
                color: COLORS.INK_MUTED,
              }}
            >
              {c.gloss}
            </span>
          </div>
        ))}
      </div>

      {/* needs_review — the gate's output, set apart */}
      <div
        style={{
          border: `0.75pt dashed ${COLORS.GATE_DEEP}`,
          borderRadius: 4,
          padding: "10px 12px",
          background: COLORS.GATE_TINT,
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}
      >
        <span
          style={{
            fontFamily: FONTS.MONO,
            fontSize: 12,
            fontWeight: 700,
            color: COLORS.GATE_DEEP,
          }}
        >
          {review.label}
        </span>
        <span
          style={{
            fontFamily: FONTS.SANS,
            fontSize: 10.5,
            fontWeight: 500,
            color: COLORS.INK,
            lineHeight: 1.35,
          }}
        >
          Not a trained label — it is where the 0.85 gate routes every email it
          is not sure about. The 9th category is the human handoff.
        </span>
      </div>
    </div>
  );
};
