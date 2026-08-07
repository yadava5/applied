import React from "react";
import { BodyPage } from "../templates/BodyPage";
import { COLORS, FONTS, TYPE, SECTION_INK } from "../theme";
import { PROOF } from "../content";
import { PullQuote } from "../primitives/PullQuote";

/** Page 22 — 305 tests, all passing + a merge-blocking CI gate. */
export const ProofTestsPage: React.FC<{
  parity: "recto" | "verso";
  pageNumber: number;
  totalPages: number;
}> = ({ parity, pageNumber, totalPages }) => (
  <BodyPage
    parity={parity}
    pageNumber={pageNumber}
    totalPages={totalPages}
    sectionLabel="PROOF"
    sectionColor={SECTION_INK["04_PROOF"]}
    eyebrow={PROOF.tests.eyebrow}
    headline={PROOF.tests.headline}
  >
    <p
      style={{
        fontFamily: FONTS.SANS,
        fontSize: TYPE.body.size,
        lineHeight: TYPE.body.lh,
        letterSpacing: TYPE.body.tracking,
        color: COLORS.INK,
        margin: "4px 0 26px",
        maxWidth: "6.4in",
      }}
    >
      {PROOF.tests.body}
    </p>

    {/* Three stats */}
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr 1fr",
        gap: 0,
        borderTop: `1pt solid ${COLORS.INK}`,
        borderBottom: `0.5pt solid ${COLORS.HAIRLINE}`,
      }}
    >
      {PROOF.tests.stats.map((s, i) => (
        <div
          key={s.label}
          style={{
            padding: "16px 16px",
            borderLeft: i === 0 ? "none" : `0.5pt solid ${COLORS.HAIRLINE}`,
            display: "flex",
            flexDirection: "column",
            gap: 5,
          }}
        >
          <span
            style={{
              fontFamily: FONTS.MONO,
              fontSize: TYPE.metricMedium.size,
              fontWeight: 700,
              letterSpacing: "-0.02em",
              color: COLORS.SETFIT_DEEP,
              lineHeight: 1,
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {s.value}
          </span>
          <span
            style={{
              fontFamily: FONTS.MONO,
              fontSize: 9,
              fontWeight: 600,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              color: COLORS.INK_MUTED,
            }}
          >
            {s.label}
          </span>
          <span
            style={{
              fontFamily: FONTS.MONO,
              fontSize: 7.5,
              color: COLORS.INK_SUBTLE,
            }}
          >
            {s.note}
          </span>
        </div>
      ))}
    </div>

    {/* Honesty note */}
    <div
      style={{
        marginTop: 20,
        background: COLORS.PAPER_ELEVATED,
        border: `0.5pt solid ${COLORS.HAIRLINE}`,
        borderLeft: `2.5px solid ${COLORS.STEEL}`,
        borderRadius: 4,
        padding: "12px 16px",
      }}
    >
      <div
        style={{
          fontFamily: FONTS.MONO,
          fontSize: 8.5,
          fontWeight: 700,
          letterSpacing: "0.14em",
          textTransform: "uppercase",
          color: COLORS.STEEL_DEEP,
          marginBottom: 5,
        }}
      >
        Honesty note
      </div>
      <p style={{ fontFamily: FONTS.SANS, fontSize: 10.5, lineHeight: 1.45, color: COLORS.INK, margin: 0 }}>
        {PROOF.tests.honest}
      </p>
    </div>

    {/* Closing quote */}
    <div style={{ marginTop: 28, maxWidth: "6.2in" }}>
      <PullQuote color={COLORS.INK}>{PROOF.tests.handoffQuote}</PullQuote>
    </div>
  </BodyPage>
);
