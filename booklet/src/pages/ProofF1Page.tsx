import React from "react";
import { BodyPage } from "../templates/BodyPage";
import { COLORS, FONTS, TYPE, SECTION_INK } from "../theme";
import { PROOF } from "../content";
import { SourceNote } from "../primitives/SourceNote";

/** Page 19 — 0.979 macro-F1, CI-gated. */
export const ProofF1Page: React.FC<{
  parity: "recto" | "verso";
  pageNumber: number;
  totalPages: number;
}> = ({ parity, pageNumber, totalPages }) => {
  const { f1 } = PROOF;
  return (
    <BodyPage
      parity={parity}
      pageNumber={pageNumber}
      totalPages={totalPages}
      sectionLabel="PROOF"
      sectionColor={SECTION_INK["04_PROOF"]}
      eyebrow={f1.eyebrow}
      headline={f1.headline}
    >
      {/* Hero number */}
      <div style={{ display: "flex", alignItems: "flex-end", gap: 24, marginTop: 6 }}>
        <div
          style={{
            fontFamily: FONTS.MONO,
            fontSize: TYPE.metricHero.size,
            fontWeight: 700,
            letterSpacing: TYPE.metricHero.tracking,
            lineHeight: 0.9,
            color: COLORS.SETFIT_DEEP,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {f1.hero}
        </div>
        <div style={{ paddingBottom: 8 }}>
          <div
            style={{
              fontFamily: FONTS.MONO,
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              color: COLORS.INK_MUTED,
              maxWidth: "2.4in",
              lineHeight: 1.35,
            }}
          >
            {f1.heroLabel}
          </div>
        </div>
      </div>

      {/* Floor bar — 0.979 clears the 0.95 gate */}
      <div style={{ marginTop: 24, maxWidth: "6.4in" }}>
        <div
          style={{
            position: "relative",
            height: 26,
            borderRadius: 5,
            background: COLORS.SURFACE,
            overflow: "hidden",
          }}
        >
          {/* fill to 0.979 on a 0.90–1.00 scale */}
          <div
            style={{
              position: "absolute",
              inset: "0 auto 0 0",
              width: `${((0.9791 - 0.9) / 0.1) * 100}%`,
              background: COLORS.SETFIT_GREEN,
              opacity: 0.85,
            }}
          />
          {/* floor line at 0.95 */}
          <div style={{ position: "absolute", top: -3, bottom: -3, left: `${((0.95 - 0.9) / 0.1) * 100}%`, width: 2, background: COLORS.DANGER }} />
        </div>
        <div style={{ position: "relative", height: 14, marginTop: 4 }}>
          <Tick at={0} label="0.90" />
          <Tick at={50} label="0.95 floor" danger />
          <Tick at={100} label="1.00" />
        </div>
      </div>

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
        {f1.body}
      </p>

      {/* CI gate block */}
      <div
        style={{
          marginTop: 24,
          display: "grid",
          gridTemplateColumns: "auto 1fr",
          columnGap: 20,
          alignItems: "center",
          borderTop: `1pt solid ${COLORS.INK}`,
          paddingTop: 18,
        }}
      >
        <div
          style={{
            fontFamily: FONTS.MONO,
            fontSize: TYPE.metricMedium.size,
            fontWeight: 700,
            color: COLORS.DANGER,
            fontVariantNumeric: "tabular-nums",
            lineHeight: 1,
          }}
        >
          ≥ {f1.ciValue}
        </div>
        <div>
          <div
            style={{
              fontFamily: FONTS.MONO,
              fontSize: 9,
              fontWeight: 700,
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              color: COLORS.INK_MUTED,
              marginBottom: 4,
            }}
          >
            {f1.ciLabel}
          </div>
          <p style={{ fontFamily: FONTS.SANS, fontSize: 11, lineHeight: 1.42, color: COLORS.INK, margin: 0 }}>
            {f1.ciBody}
          </p>
        </div>
      </div>

      <div style={{ position: "absolute", left: "0.75in", bottom: "1.1in", display: "flex", flexDirection: "column", gap: 6 }}>
        <div
          style={{
            fontFamily: FONTS.MONO,
            fontSize: 8.5,
            color: COLORS.INK_MUTED,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {f1.exact}
        </div>
        <SourceNote>{f1.source}</SourceNote>
      </div>
    </BodyPage>
  );
};

const Tick: React.FC<{ at: number; label: string; danger?: boolean }> = ({ at, label, danger = false }) => (
  <div
    style={{
      position: "absolute",
      left: `${at}%`,
      transform: at === 0 ? "none" : at === 100 ? "translateX(-100%)" : "translateX(-50%)",
      fontFamily: FONTS.MONO,
      fontSize: 8,
      fontWeight: danger ? 700 : 500,
      color: danger ? COLORS.DANGER : COLORS.INK_MUTED,
      fontVariantNumeric: "tabular-nums",
      whiteSpace: "nowrap",
    }}
  >
    {label}
  </div>
);
