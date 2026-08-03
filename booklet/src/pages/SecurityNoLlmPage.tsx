import React from "react";
import { BodyPage } from "../templates/BodyPage";
import { COLORS, FONTS, TYPE, SECTION_INK } from "../theme";
import { SECURITY } from "../content";
import { SourceNote } from "../primitives/SourceNote";
import { DeviceCard } from "../primitives/DeviceCard";

/** Page 24 — no LLM reads the inbox; the classify path is in-repo code. */
export const SecurityNoLlmPage: React.FC<{
  parity: "recto" | "verso";
  pageNumber: number;
  totalPages: number;
}> = ({ parity, pageNumber, totalPages }) => {
  const { noLlm } = SECURITY;
  const ink = SECTION_INK["05_SECURITY"];
  return (
    <BodyPage
      parity={parity}
      pageNumber={pageNumber}
      totalPages={totalPages}
      sectionLabel="SECURITY"
      sectionColor={ink}
      eyebrow={noLlm.eyebrow}
      headline={noLlm.headline}
      align="top"
    >
      <p
        style={{
          fontFamily: FONTS.SERIF,
          fontStyle: "italic",
          fontSize: 17,
          lineHeight: 1.35,
          color: COLORS.INK_MUTED,
          margin: "0 0 10px",
          maxWidth: "6.4in",
        }}
      >
        {noLlm.lede}
      </p>
      <p
        style={{
          fontFamily: FONTS.SANS,
          fontSize: TYPE.body.size,
          lineHeight: TYPE.body.lh,
          letterSpacing: TYPE.body.tracking,
          color: COLORS.INK,
          margin: "0 0 20px",
          maxWidth: "6.4in",
        }}
      >
        {noLlm.body}
      </p>

      {/* Classify-path flow — in-repo layers vs the absent LLM */}
      <ClassifyPathFlow />

      {/* Honesty note — the only openai/anthropic strings */}
      <div
        style={{
          marginTop: 22,
          borderLeft: `2.5px solid ${ink}`,
          paddingLeft: 14,
          maxWidth: "6.4in",
        }}
      >
        <div
          style={{
            fontFamily: FONTS.MONO,
            fontSize: 8.5,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: ink,
            marginBottom: 4,
          }}
        >
          on the record
        </div>
        <div style={{ fontFamily: FONTS.SERIF, fontStyle: "italic", fontSize: 12.5, lineHeight: 1.42, color: COLORS.INK_MUTED }}>
          {noLlm.honest}
        </div>
      </div>

      {/* Facts grid */}
      <div
        style={{
          marginTop: 22,
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 0,
          border: `0.5pt solid ${COLORS.HAIRLINE}`,
          borderRadius: 5,
          overflow: "hidden",
        }}
      >
        {noLlm.facts.map((f, i) => (
          <div
            key={f.k}
            style={{
              padding: "11px 14px",
              borderTop: i >= 2 ? `0.5pt solid ${COLORS.HAIRLINE}` : "none",
              borderLeft: i % 2 === 1 ? `0.5pt solid ${COLORS.HAIRLINE}` : "none",
              display: "flex",
              flexDirection: "column",
              gap: 3,
            }}
          >
            <span
              style={{
                fontFamily: FONTS.MONO,
                fontSize: 8.5,
                fontWeight: 700,
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                color: ink,
              }}
            >
              {f.k}
            </span>
            <span style={{ fontFamily: FONTS.SANS, fontSize: 11, fontWeight: 500, color: COLORS.INK }}>{f.v}</span>
          </div>
        ))}
      </div>

      {/* What the classifier module actually imports */}
      <div style={{ marginTop: 22, display: "grid", gridTemplateColumns: "auto 1fr", columnGap: 20, alignItems: "center" }}>
        <DeviceCard chrome="backend/jobtracker/classifier/hybrid.py" accent={ink} style={{ width: "3.9in" }}>
          <div style={{ fontFamily: FONTS.MONO, fontSize: 9, lineHeight: 1.65, color: COLORS.ON_DARK_MUTED }}>
            <div>
              <span style={{ color: COLORS.RULES_CYAN }}>from</span> .rules <span style={{ color: COLORS.RULES_CYAN }}>import</span> RuleClassifier
            </div>
            <div>
              <span style={{ color: COLORS.E5_VIOLET }}>from</span> .embeddings <span style={{ color: COLORS.E5_VIOLET }}>import</span> EmbeddingClassifier
            </div>
            <div>
              <span style={{ color: COLORS.SETFIT_GREEN }}>from</span> .setfit_model <span style={{ color: COLORS.SETFIT_GREEN }}>import</span> SetFitClassifier
            </div>
            <div style={{ color: COLORS.ON_DARK_SUBTLE, marginTop: 4 }}>{"#  no openai · no anthropic · no gemini"}</div>
          </div>
        </DeviceCard>
        <div style={{ fontFamily: FONTS.SERIF, fontStyle: "italic", fontSize: 12.5, lineHeight: 1.45, color: COLORS.INK_MUTED }}>
          Three local classes, imported by name. The whole decision is code in this repository — nothing is delegated to a hosted model you cannot inspect.
        </div>
      </div>

      <div style={{ position: "absolute", left: "0.75in", bottom: "1.1in" }}>
        <SourceNote>{noLlm.source}</SourceNote>
      </div>
    </BodyPage>
  );
};

// ── The classify-path flow ─────────────────────────────────────────────────

const PATH_INK: Record<string, string> = {
  "02_HOW": COLORS.RULES_DEEP,
  "03_INSIDE": COLORS.E5_DEEP,
  "04_PROOF": COLORS.SETFIT_DEEP,
};

const ClassifyPathFlow: React.FC = () => {
  const { noLlm } = SECURITY;
  return (
    <div
      style={{
        border: `0.5pt solid ${COLORS.HAIRLINE}`,
        borderRadius: 6,
        background: COLORS.PAPER_ELEVATED,
        padding: "14px 16px",
      }}
    >
      <div
        style={{
          fontFamily: FONTS.MONO,
          fontSize: 8.5,
          fontWeight: 700,
          letterSpacing: "0.14em",
          textTransform: "uppercase",
          color: COLORS.INK_MUTED,
          marginBottom: 12,
        }}
      >
        the classify path — end to end, in this repo
      </div>
      <div style={{ display: "flex", alignItems: "stretch", gap: 8 }}>
        <EnvChip />
        <Arrow />
        {noLlm.path.map((s, i) => (
          <React.Fragment key={s.label}>
            <PathChip n={s.n} label={s.label} note={s.note} color={PATH_INK[s.accentKey] ?? COLORS.INK} />
            {i < noLlm.path.length - 1 && <Arrow />}
          </React.Fragment>
        ))}
        <Arrow />
        <VerdictChip />
      </div>

      {/* Absent LLM rail */}
      <div
        style={{
          marginTop: 14,
          display: "flex",
          alignItems: "center",
          gap: 10,
          borderTop: `0.5pt solid ${COLORS.HAIRLINE}`,
          paddingTop: 12,
        }}
      >
        <div
          style={{
            position: "relative",
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            padding: "6px 12px",
            borderRadius: 5,
            border: `1px dashed ${COLORS.DANGER}`,
            background: COLORS.DANGER_TINT,
          }}
        >
          <span
            style={{
              fontFamily: FONTS.MONO,
              fontSize: 10,
              fontWeight: 600,
              color: COLORS.DANGER,
              textDecoration: "line-through",
              textDecorationThickness: "1.5px",
            }}
          >
            {noLlm.absent}
          </span>
        </div>
        <span style={{ fontFamily: FONTS.SANS, fontSize: 10.5, fontWeight: 500, color: COLORS.INK }}>
          {noLlm.absentNote} — the classifier module imports no LLM SDK.
        </span>
      </div>
    </div>
  );
};

const EnvChip: React.FC = () => (
  <div
    style={{
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      gap: 3,
      padding: "8px 10px",
      borderRadius: 5,
      border: `0.5pt solid ${COLORS.HAIRLINE}`,
      background: COLORS.PAPER,
      minWidth: 52,
    }}
  >
    <svg width={18} height={13} viewBox="0 0 25 18" aria-hidden>
      <rect x={1} y={1} width={23} height={16} rx={2} fill="none" stroke={COLORS.INK} strokeWidth={1.4} />
      <path d="M1.5 2 L12.5 10 L23.5 2" fill="none" stroke={COLORS.INK} strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
    <span style={{ fontFamily: FONTS.MONO, fontSize: 7, letterSpacing: "0.08em", textTransform: "uppercase", color: COLORS.INK_SUBTLE }}>
      email
    </span>
  </div>
);

const PathChip: React.FC<{ n: string; label: string; note: string; color: string }> = ({ n, label, note, color }) => (
  <div
    style={{
      flex: 1,
      display: "flex",
      flexDirection: "column",
      gap: 3,
      padding: "8px 10px",
      borderRadius: 5,
      borderLeft: `3px solid ${color}`,
      border: `0.5pt solid ${COLORS.HAIRLINE}`,
      borderLeftWidth: 3,
      borderLeftColor: color,
      background: COLORS.PAPER,
      minWidth: 0,
    }}
  >
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span
        style={{
          width: 15,
          height: 15,
          borderRadius: "50%",
          background: color,
          color: COLORS.PAPER,
          display: "grid",
          placeItems: "center",
          fontFamily: FONTS.MONO,
          fontSize: 9,
          fontWeight: 700,
          flexShrink: 0,
        }}
      >
        {n}
      </span>
      <span style={{ fontFamily: FONTS.SANS, fontSize: 11, fontWeight: 700, letterSpacing: "-0.01em", color: COLORS.INK, whiteSpace: "nowrap" }}>
        {label}
      </span>
    </div>
    <span style={{ fontFamily: FONTS.MONO, fontSize: 7.5, letterSpacing: "0.02em", color: COLORS.INK_MUTED }}>{note}</span>
  </div>
);

const VerdictChip: React.FC = () => (
  <div
    style={{
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      gap: 3,
      padding: "8px 10px",
      borderRadius: 5,
      border: `0.5pt solid ${COLORS.SETFIT_GREEN}`,
      background: COLORS.SETFIT_TINT,
      minWidth: 54,
    }}
  >
    <svg width={16} height={16} viewBox="0 0 18 18" aria-hidden>
      <circle cx={9} cy={9} r={8} fill={COLORS.SETFIT_GREEN} />
      <path d="M5 9 L8 12 L13 6" fill="none" stroke={COLORS.PAPER} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
    <span style={{ fontFamily: FONTS.MONO, fontSize: 7, letterSpacing: "0.08em", textTransform: "uppercase", color: COLORS.SETFIT_DEEP }}>
      verdict
    </span>
  </div>
);

const Arrow: React.FC = () => (
  <div style={{ display: "flex", alignItems: "center" }} aria-hidden>
    <svg width={16} height={10} viewBox="0 0 16 10">
      <line x1={1} y1={5} x2={12} y2={5} stroke={COLORS.HAIRLINE_STRONG} strokeWidth={1.2} strokeLinecap="round" />
      <path d="M9 2 L13 5 L9 8" fill="none" stroke={COLORS.HAIRLINE_STRONG} strokeWidth={1.2} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  </div>
);
