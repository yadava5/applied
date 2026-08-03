import React from "react";
import { BodyPage } from "../templates/BodyPage";
import { COLORS, FONTS, TYPE, SECTION_INK } from "../theme";
import { PROOF, CATEGORIES_META } from "../content";
import { ClassGrid } from "../visuals/ClassGrid";
import { SourceNote } from "../primitives/SourceNote";

/** Page 20 — the nine categories, eight learned. */
export const ProofClassesPage: React.FC<{
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
    eyebrow={PROOF.classes.eyebrow}
    headline={PROOF.classes.headline}
  >
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1.15fr", columnGap: 26, alignItems: "start" }}>
      <div>
        <p
          style={{
            fontFamily: FONTS.SERIF,
            fontStyle: "italic",
            fontSize: 16,
            lineHeight: 1.4,
            color: COLORS.INK_MUTED,
            margin: "0 0 18px",
          }}
        >
          {PROOF.classes.lede}
        </p>

        {/* count callout */}
        <div style={{ display: "flex", gap: 22, marginBottom: 18 }}>
          <Count value={String(CATEGORIES_META.total)} label="categories" color={COLORS.INK} />
          <Count value={String(CATEGORIES_META.predicted)} label="model-predicted" color={COLORS.SETFIT_DEEP} />
          <Count value={String(CATEGORIES_META.ruleTotal)} label="regex rules" color={COLORS.RULES_DEEP} />
        </div>

        <div
          style={{
            borderLeft: `2.5px solid ${COLORS.GATE_AMBER}`,
            paddingLeft: 14,
          }}
        >
          <p style={{ fontFamily: FONTS.SERIF, fontStyle: "italic", fontSize: 14, lineHeight: 1.4, color: COLORS.INK, margin: 0 }}>
            {PROOF.classes.note}
          </p>
        </div>
      </div>

      <ClassGrid />
    </div>

    <div style={{ position: "absolute", left: "0.75in", bottom: "1.1in" }}>
      <SourceNote>{PROOF.classes.source}</SourceNote>
    </div>
  </BodyPage>
);

const Count: React.FC<{ value: string; label: string; color: string }> = ({ value, label, color }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
    <span
      style={{
        fontFamily: FONTS.MONO,
        fontSize: TYPE.metricMedium.size,
        fontWeight: 700,
        letterSpacing: "-0.02em",
        color,
        lineHeight: 1,
        fontVariantNumeric: "tabular-nums",
      }}
    >
      {value}
    </span>
    <span
      style={{
        fontFamily: FONTS.MONO,
        fontSize: 8.5,
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
