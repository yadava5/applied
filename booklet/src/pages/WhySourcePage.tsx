import React from "react";
import { BodyPage } from "../templates/BodyPage";
import { COLORS, FONTS, TYPE, SECTION, SECTION_INK } from "../theme";
import { WHY } from "../content";
import { PullQuote } from "../primitives/PullQuote";

/** Page 07 — the real problem is classification at the source. */
export const WhySourcePage: React.FC<{
  parity: "recto" | "verso";
  pageNumber: number;
  totalPages: number;
}> = ({ parity, pageNumber, totalPages }) => (
  <BodyPage
    parity={parity}
    pageNumber={pageNumber}
    totalPages={totalPages}
    sectionLabel="WHY"
    sectionColor={SECTION_INK["01_WHY"]}
    eyebrow={WHY.source.eyebrow}
    headline={WHY.source.headline}
  >
    <div style={{ maxWidth: "6.4in", marginTop: 4 }}>
      {WHY.source.body.map((p, i) => (
        <p
          key={i}
          style={{
            fontFamily: FONTS.SANS,
            fontSize: TYPE.body.size,
            lineHeight: TYPE.body.lh,
            letterSpacing: TYPE.body.tracking,
            color: COLORS.INK,
            margin: "0 0 10px",
          }}
        >
          {p}
        </p>
      ))}
    </div>

    {/* The reframe — three from → to rows */}
    <div style={{ marginTop: 26, display: "flex", flexDirection: "column", gap: 0 }}>
      <div
        style={{
          fontFamily: FONTS.MONO,
          fontSize: 9,
          fontWeight: 700,
          letterSpacing: "0.14em",
          textTransform: "uppercase",
          color: COLORS.INK_MUTED,
          marginBottom: 10,
        }}
      >
        The reframe
      </div>
      {WHY.source.reframe.map((r, i) => (
        <div
          key={i}
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 40px 1fr",
            alignItems: "center",
            gap: 12,
            padding: "11px 0",
            borderTop: `0.5pt solid ${COLORS.HAIRLINE}`,
          }}
        >
          <span
            style={{
              fontFamily: FONTS.SERIF,
              fontStyle: "italic",
              fontSize: 15,
              color: COLORS.INK_MUTED,
              textAlign: "right",
            }}
          >
            {r.from}
          </span>
          <span style={{ textAlign: "center", color: SECTION["01_WHY"], fontSize: 18, fontWeight: 700 }}>→</span>
          <span
            style={{
              fontFamily: FONTS.SANS,
              fontSize: 15,
              fontWeight: 700,
              letterSpacing: "-0.01em",
              color: COLORS.INK,
            }}
          >
            {r.to}
          </span>
        </div>
      ))}
    </div>

    {/* Thesis */}
    <div style={{ marginTop: 26 }}>
      <PullQuote color={SECTION_INK["01_WHY"]} style={{ maxWidth: "6.2in" }}>
        {WHY.source.thesis}
      </PullQuote>
    </div>

    {/* Handoff */}
    <div
      style={{
        position: "absolute",
        left: "0.75in",
        right: "0.75in",
        bottom: "1.15in",
        borderTop: `0.5pt solid ${COLORS.HAIRLINE_STRONG}`,
        paddingTop: 10,
        fontFamily: FONTS.MONO,
        fontSize: 9,
        fontWeight: 500,
        letterSpacing: "0.1em",
        textTransform: "uppercase",
        color: COLORS.INK_MUTED,
        textAlign: parity === "recto" ? "right" : "left",
      }}
    >
      {WHY.source.handoff}
    </div>
  </BodyPage>
);
