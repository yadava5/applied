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
  record: COLORS.STEEL,
};

/** Page 15 — the layer architecture as one pipeline, and what it records. */
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
          What a correction records
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
          Corrections write to training_data and flag the email user_corrected,
          so a later sync leaves the human&rsquo;s answer alone. Nothing
          retrains on them automatically.
        </p>
      </div>
    </div>

    {/* Where a correction persists — the two stores that make it stateful */}
    <div style={{ marginTop: 30 }}>
      <div
        style={{
          fontFamily: FONTS.MONO,
          fontSize: 9,
          fontWeight: 700,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: SECTION_INK["03_INSIDE"],
          marginBottom: 10,
        }}
      >
        What a correction writes to
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <PersistBox table="training_data" desc="every human correction, kept as a labeled example. No retrain consumes it automatically." />
        <PersistBox table="email_embeddings" desc="e5 vectors persisted for the similarity layer's lookups." />
      </div>
    </div>

    <div style={{ position: "absolute", left: "0.75in", bottom: "1.1in" }}>
      <SourceNote>{INSIDE.architecture.source}</SourceNote>
    </div>
  </BodyPage>
);

const PersistBox: React.FC<{ table: string; desc: string }> = ({ table, desc }) => (
  <div
    style={{
      border: `0.5pt solid ${COLORS.HAIRLINE}`,
      borderLeft: `2.5px solid ${COLORS.E5_VIOLET}`,
      borderRadius: 4,
      background: COLORS.PAPER_ELEVATED,
      padding: "11px 14px",
      display: "flex",
      flexDirection: "column",
      gap: 4,
    }}
  >
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <svg width={13} height={13} viewBox="0 0 14 14" aria-hidden style={{ flexShrink: 0 }}>
        <ellipse cx={7} cy={3.2} rx={5} ry={2} fill="none" stroke={COLORS.E5_DEEP} strokeWidth={1} />
        <path d="M2 3.2 V10.8 C2 11.9 4.2 12.8 7 12.8 C9.8 12.8 12 11.9 12 10.8 V3.2" fill="none" stroke={COLORS.E5_DEEP} strokeWidth={1} />
        <path d="M2 7 C2 8.1 4.2 9 7 9 C9.8 9 12 8.1 12 7" fill="none" stroke={COLORS.E5_DEEP} strokeWidth={0.8} strokeOpacity={0.6} />
      </svg>
      <span style={{ fontFamily: FONTS.MONO, fontSize: 11, fontWeight: 700, color: COLORS.INK }}>{table}</span>
    </div>
    <span style={{ fontFamily: FONTS.SERIF, fontStyle: "italic", fontSize: 11, lineHeight: 1.38, color: COLORS.INK_MUTED }}>{desc}</span>
  </div>
);
