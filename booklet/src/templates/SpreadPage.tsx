import React from "react";
import { Page } from "../primitives/Page";
import { Eyebrow } from "../primitives/Eyebrow";
import { COLORS, FONTS, SECTION, SECTION_INK, type SectionKey } from "../theme";
import { BUILD } from "../content";

/**
 * BUILD spread (pages 24 / 25) — the end-to-end pipeline read across the
 * gutter. Left half: train → register → export. Right half: export → publish
 * → ship. The ONNX "export" stage is repeated as the hinge so the two halves
 * read as one continuous ribbon once bound.
 */
export type SpreadPageProps = {
  half: "left" | "right";
  parity: "recto" | "verso";
  pageNumber: number;
  totalPages: number;
  sectionLabel: string;
  sectionColor: string;
};

export const SpreadPage: React.FC<SpreadPageProps> = ({
  half,
  parity,
  pageNumber,
  totalPages,
  sectionLabel,
  sectionColor,
}) => {
  const { pipeline } = BUILD;
  const stages = half === "left" ? pipeline.stages.slice(0, 3) : pipeline.stages.slice(2, 5);
  const headline = half === "left" ? pipeline.headlineLeft : pipeline.headlineRight;
  const sub = half === "left" ? pipeline.subLeft : pipeline.subRight;

  return (
    <Page
      parity={parity}
      pageNumber={pageNumber}
      totalPages={totalPages}
      sectionLabel={sectionLabel}
      sectionColor={sectionColor}
    >
      <Eyebrow color={SECTION_INK["05_BUILD"]} style={{ marginBottom: 6 }}>
        {half === "left" ? pipeline.eyebrowLeft : pipeline.eyebrowRight}
      </Eyebrow>

      <div style={{ textAlign: half === "right" ? "right" : "left" }}>
        <h1
          style={{
            fontFamily: FONTS.SANS,
            fontSize: 30,
            fontWeight: 700,
            letterSpacing: "-0.02em",
            lineHeight: 1.05,
            color: COLORS.INK,
            margin: 0,
          }}
        >
          {headline}
        </h1>
        <p
          style={{
            fontFamily: FONTS.SERIF,
            fontStyle: "italic",
            fontSize: 14,
            lineHeight: 1.4,
            color: COLORS.INK_MUTED,
            margin: "6px 0 0",
            maxWidth: "5.4in",
            marginLeft: half === "right" ? "auto" : 0,
          }}
        >
          {sub}
        </p>
      </div>

      {/* Vertical pipeline ribbon */}
      <div style={{ marginTop: 34, display: "flex", flexDirection: "column", gap: 0 }}>
        {stages.map((s, i) => {
          const accent = SECTION[s.accentKey as SectionKey];
          const bridge = s.label === "ONNX";
          return (
            <React.Fragment key={s.label}>
              <StageCard n={s.n} label={s.label} detail={s.detail} accent={accent} bridge={bridge} />
              {i < stages.length - 1 && <Connector />}
            </React.Fragment>
          );
        })}
      </div>

      {/* Foot — registry line (left) or ship targets (right) */}
      <div style={{ position: "absolute", left: "0.75in", right: "0.75in", bottom: "1.2in" }}>
        {half === "left" ? (
          <div
            style={{
              borderTop: `1pt solid ${COLORS.INK}`,
              paddingTop: 12,
              display: "flex",
              alignItems: "center",
              gap: 12,
            }}
          >
            <span
              style={{
                fontFamily: FONTS.MONO,
                fontSize: 8.5,
                fontWeight: 700,
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                color: SECTION_INK["05_BUILD"],
                whiteSpace: "nowrap",
              }}
            >
              MLflow registry
            </span>
            <span style={{ fontFamily: FONTS.SERIF, fontStyle: "italic", fontSize: 13, color: COLORS.INK, lineHeight: 1.35 }}>
              {BUILD.pipeline.registry}
            </span>
          </div>
        ) : (
          <div
            style={{
              borderTop: `1pt solid ${COLORS.INK}`,
              paddingTop: 12,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "baseline",
              gap: 16,
              fontFamily: FONTS.MONO,
              fontSize: 8.5,
              fontWeight: 600,
              letterSpacing: "0.06em",
              color: COLORS.INK_MUTED,
            }}
          >
            <span style={{ color: COLORS.RULES_DEEP }}>{BUILD.closing.liveUrl}</span>
            <span>·</span>
            <span style={{ color: COLORS.E5_DEEP }}>{BUILD.closing.spaceUrl}</span>
          </div>
        )}
      </div>

      {/* gutter continuity marker */}
      <div
        style={{
          position: "absolute",
          bottom: "0.55in",
          [half === "left" ? "right" : "left"]: "0.75in",
          fontFamily: FONTS.MONO,
          fontSize: 8,
          fontWeight: 600,
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          color: SECTION_INK["05_BUILD"],
        }}
      >
        {half === "left" ? "pipeline continues →" : "← the export bridges the fold"}
      </div>
    </Page>
  );
};

const StageCard: React.FC<{
  n: string;
  label: string;
  detail: string;
  accent: string;
  bridge: boolean;
}> = ({ n, label, detail, accent, bridge }) => (
  <div
    style={{
      display: "flex",
      alignItems: "center",
      gap: 14,
      border: `0.5pt solid ${bridge ? accent : COLORS.HAIRLINE}`,
      borderLeft: `3px solid ${accent}`,
      borderRadius: 5,
      background: bridge ? `${accent}12` : COLORS.PAPER_ELEVATED,
      padding: "14px 16px",
    }}
  >
    <div
      style={{
        width: 34,
        height: 34,
        borderRadius: "50%",
        background: accent,
        color: COLORS.GROUND,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: FONTS.MONO,
        fontSize: 15,
        fontWeight: 700,
        flexShrink: 0,
      }}
    >
      {n}
    </div>
    <div style={{ flex: 1 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span style={{ fontFamily: FONTS.SANS, fontSize: 17, fontWeight: 700, letterSpacing: "-0.01em", color: COLORS.INK }}>
          {label}
        </span>
        {bridge && (
          <span
            style={{
              fontFamily: FONTS.MONO,
              fontSize: 7.5,
              fontWeight: 700,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: accent,
            }}
          >
            the hinge
          </span>
        )}
      </div>
      <div style={{ fontFamily: FONTS.MONO, fontSize: 9, color: COLORS.INK_MUTED, marginTop: 2 }}>{detail}</div>
    </div>
  </div>
);

const Connector: React.FC = () => (
  <div style={{ display: "flex", justifyContent: "center", padding: "3px 0" }}>
    <span style={{ color: COLORS.HAIRLINE_STRONG, fontSize: 14 }} aria-hidden>
      ↓
    </span>
  </div>
);
