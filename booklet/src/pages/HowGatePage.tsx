import React from "react";
import { BodyPage } from "../templates/BodyPage";
import { COLORS, FONTS, TYPE, SECTION_INK } from "../theme";
import { HOW } from "../content";
import { ConfidenceGate } from "../visuals/ConfidenceGate";
import { SourceNote } from "../primitives/SourceNote";

/** Page 13 — the 0.85 confidence gate + human handoff. */
export const HowGatePage: React.FC<{
  parity: "recto" | "verso";
  pageNumber: number;
  totalPages: number;
}> = ({ parity, pageNumber, totalPages }) => (
  <BodyPage
    parity={parity}
    pageNumber={pageNumber}
    totalPages={totalPages}
    sectionLabel="HOW"
    sectionColor={SECTION_INK["02_HOW"]}
    eyebrow={HOW.gate.eyebrow}
    headline={HOW.gate.headline}
  >
    <p
      style={{
        fontFamily: FONTS.SERIF,
        fontStyle: "italic",
        fontSize: 17,
        lineHeight: 1.35,
        color: COLORS.INK_MUTED,
        margin: "0 0 22px",
        maxWidth: "6.4in",
      }}
    >
      {HOW.gate.lede}
    </p>

    <ConfidenceGate />

    <p
      style={{
        fontFamily: FONTS.SANS,
        fontSize: TYPE.body.size,
        lineHeight: TYPE.body.lh,
        letterSpacing: TYPE.body.tracking,
        color: COLORS.INK,
        margin: "24px 0 0",
        maxWidth: "6.4in",
      }}
    >
      {HOW.gate.body}
    </p>

    {/* What a correction records — NOT a retrain loop; nothing consumes it. */}
    <div
      style={{
        marginTop: 22,
        border: `0.75pt dashed ${COLORS.GATE_DEEP}`,
        background: COLORS.GATE_TINT,
        borderRadius: 5,
        padding: "14px 18px",
        display: "flex",
        alignItems: "center",
        gap: 14,
      }}
    >
      <span
        style={{
          fontFamily: FONTS.MONO,
          fontSize: 22,
          color: COLORS.GATE_DEEP,
        }}
        aria-hidden
      >
        ✓
      </span>
      <div>
        <div
          style={{
            fontFamily: FONTS.MONO,
            fontSize: 8.5,
            fontWeight: 700,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            color: COLORS.GATE_DEEP,
            marginBottom: 4,
          }}
        >
          The correction sticks
        </div>
        <p
          style={{
            fontFamily: FONTS.SERIF,
            fontStyle: "italic",
            fontSize: 14.5,
            lineHeight: 1.35,
            color: COLORS.INK,
            margin: 0,
          }}
        >
          {HOW.gate.recordNote}
        </p>
      </div>
    </div>

    <div style={{ position: "absolute", left: "0.75in", bottom: "1.1in" }}>
      <SourceNote>{HOW.gate.source}</SourceNote>
    </div>
  </BodyPage>
);
