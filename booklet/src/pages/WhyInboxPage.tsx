import React from "react";
import { BodyPage } from "../templates/BodyPage";
import { COLORS, FONTS, TYPE, SECTION, SECTION_INK } from "../theme";
import { WHY } from "../content";
import { PullQuote } from "../primitives/PullQuote";
import { EnvelopeMark } from "../visuals/LayerCascade";

const HUE: Record<string, string> = {
  danger: COLORS.DANGER,
  rules: COLORS.RULES_DEEP,
  setfit: COLORS.SETFIT_DEEP,
  e5: COLORS.E5_DEEP,
};

/** Page 05 — the inbox already holds the verdict. */
export const WhyInboxPage: React.FC<{
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
    eyebrow={WHY.inbox.eyebrow}
    headline={WHY.inbox.headline}
  >
    <div style={{ maxWidth: "6.4in", marginTop: 4 }}>
      <PullQuote color={COLORS.INK} style={{ marginBottom: 18 }}>
        {WHY.inbox.pullQuote}
      </PullQuote>

      {WHY.inbox.body.map((p, i) => (
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

    {/* The four verdicts, as envelope cards */}
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 12,
        marginTop: 24,
      }}
    >
      {WHY.inbox.signals.map((s) => {
        const c = HUE[s.hue] ?? COLORS.INK;
        return (
          <div
            key={s.label}
            style={{
              border: `0.5pt solid ${COLORS.HAIRLINE}`,
              borderLeft: `2.5px solid ${c}`,
              borderRadius: 5,
              background: COLORS.PAPER_ELEVATED,
              padding: "12px 14px",
              display: "flex",
              alignItems: "center",
              gap: 12,
            }}
          >
            <EnvelopeMark size={26} color={c} />
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <span
                style={{
                  fontFamily: FONTS.MONO,
                  fontSize: 9,
                  fontWeight: 700,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: c,
                }}
              >
                {s.label}
              </span>
              <span
                style={{
                  fontFamily: FONTS.SERIF,
                  fontStyle: "italic",
                  fontSize: 14,
                  color: COLORS.INK,
                  lineHeight: 1.2,
                }}
              >
                {s.quote}
              </span>
            </div>
          </div>
        );
      })}
    </div>

    {/* Coda */}
    <p
      style={{
        fontFamily: FONTS.SERIF,
        fontStyle: "italic",
        fontSize: 18,
        lineHeight: 1.35,
        color: COLORS.INK_MUTED,
        margin: "26px 0 0",
        maxWidth: "6in",
        borderTop: `1pt solid ${SECTION["01_WHY"]}`,
        paddingTop: 14,
      }}
    >
      {WHY.inbox.coda}
    </p>
  </BodyPage>
);
