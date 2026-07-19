import React from "react";
import { BodyPage } from "../templates/BodyPage";
import { COLORS, FONTS, TYPE, SECTION_INK } from "../theme";
import { INSIDE } from "../content";
import { SourceNote } from "../primitives/SourceNote";

const STAGE_ACCENT: Record<string, string> = {
  guard: COLORS.STEEL,
  rules: COLORS.RULES_CYAN,
  e5: COLORS.E5_VIOLET,
  setfit: COLORS.SETFIT_GREEN,
  gate: COLORS.GATE_AMBER,
  learn: COLORS.STEEL,
};

/** Page 15 — the layer architecture as one pipeline with a feedback loop. */
export const InsideArchPage: React.FC<{
  parity: "recto" | "verso";
  pageNumber: number;
  totalPages: number;
}> = ({ parity, pageNumber, totalPages }) => (
  <BodyPage
    parity={parity}
    pageNumber={pageNumber}
    totalPages={totalPages}
    sectionLabel="INSIDE"
    sectionColor={SECTION_INK["03_INSIDE"]}
    eyebrow={INSIDE.architecture.eyebrow}
    headline={INSIDE.architecture.headline}
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
      {INSIDE.architecture.body}
    </p>

    {/* Horizontal pipeline flow */}
    <div style={{ display: "flex", alignItems: "stretch", gap: 0, flexWrap: "nowrap" }}>
      {INSIDE.architecture.flow.map((s, i) => {
        const accent = STAGE_ACCENT[s.stage] ?? COLORS.STEEL;
        return (
          <React.Fragment key={s.stage}>
            <div
              style={{
                flex: 1,
                border: `0.5pt solid ${COLORS.HAIRLINE}`,
                borderTop: `2.5px solid ${accent}`,
                borderRadius: 4,
                background: COLORS.PAPER_ELEVATED,
                padding: "10px 8px",
                display: "flex",
                flexDirection: "column",
                gap: 5,
                minWidth: 0,
              }}
            >
              <span
                style={{
                  fontFamily: FONTS.MONO,
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: "0.02em",
                  color: COLORS.INK,
                }}
              >
                {s.stage}
              </span>
              <span
                style={{
                  fontFamily: FONTS.MONO,
                  fontSize: 7.5,
                  letterSpacing: "0.02em",
                  color: COLORS.INK_MUTED,
                  lineHeight: 1.3,
                }}
              >
                {s.detail}
              </span>
            </div>
            {i < INSIDE.architecture.flow.length - 1 && (
              <span
                style={{
                  alignSelf: "center",
                  color: COLORS.HAIRLINE_STRONG,
                  fontSize: 13,
                  padding: "0 4px",
                }}
                aria-hidden
              >
                ›
              </span>
            )}
          </React.Fragment>
        );
      })}
    </div>

    {/* The safe-fallback thesis */}
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: 26, marginTop: 30 }}>
      <div>
        <div
          style={{
            fontFamily: FONTS.MONO,
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: SECTION_INK["03_INSIDE"],
            marginBottom: 8,
          }}
        >
          The fallback is always safe
        </div>
        <p
          style={{
            fontFamily: FONTS.SERIF,
            fontStyle: "italic",
            fontSize: 15,
            lineHeight: 1.42,
            color: COLORS.INK,
            margin: 0,
          }}
        >
          If no layer clears its threshold, the pipeline does not pick a
          best-guess winner. It returns needs_review — a wrong-but-confident
          label is the one failure the architecture refuses to make.
        </p>
      </div>
      <div>
        <div
          style={{
            fontFamily: FONTS.MONO,
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: SECTION_INK["03_INSIDE"],
            marginBottom: 8,
          }}
        >
          The loop feeds the model
        </div>
        <p
          style={{
            fontFamily: FONTS.SERIF,
            fontStyle: "italic",
            fontSize: 15,
            lineHeight: 1.42,
            color: COLORS.INK,
            margin: 0,
          }}
        >
          Corrections write to training_data, embeddings persist in
          email_embeddings, and SetFit retrains once enough data accrues — the
          same email is decided unaided next time.
        </p>
      </div>
    </div>

    <div style={{ position: "absolute", left: "0.75in", bottom: "1.1in" }}>
      <SourceNote>{INSIDE.architecture.source}</SourceNote>
    </div>
  </BodyPage>
);
