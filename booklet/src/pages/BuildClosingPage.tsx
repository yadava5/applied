import React from "react";
import { BodyPage } from "../templates/BodyPage";
import { COLORS, FONTS, TYPE, SECTION_INK } from "../theme";
import { BUILD } from "../content";

/** Page 27 — Try it. Print-native book-end that hands the reader to the app. */
export const BuildClosingPage: React.FC<{
  parity: "recto" | "verso";
  pageNumber: number;
  totalPages: number;
}> = ({ parity, pageNumber, totalPages }) => {
  const { closing } = BUILD;
  return (
    <BodyPage
      parity={parity}
      pageNumber={pageNumber}
      totalPages={totalPages}
      sectionLabel="BUILD"
      sectionColor={SECTION_INK["05_BUILD"]}
      eyebrow={closing.eyebrow}
      headline={closing.headline}
    >
      <p
        style={{
          fontFamily: FONTS.SERIF,
          fontStyle: "italic",
          fontSize: 22,
          lineHeight: 1.28,
          color: COLORS.INK,
          margin: "2px 0 8px",
          maxWidth: "6in",
        }}
      >
        {closing.tagline}
      </p>
      <div
        style={{
          fontFamily: FONTS.MONO,
          fontSize: 9,
          fontWeight: 500,
          letterSpacing: "0.2em",
          textTransform: "uppercase",
          color: COLORS.INK_SUBTLE,
          marginBottom: 40,
        }}
      >
        {closing.microNote}
      </div>

      {/* Two destinations */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: 24 }}>
        <UrlBlock
          label={closing.liveLabel}
          url={closing.liveUrl}
          arrow={closing.leftArrowLabel}
          color={COLORS.RULES_DEEP}
        />
        <UrlBlock
          label={closing.spaceLabel}
          url={closing.spaceUrl}
          arrow={closing.rightArrowLabel}
          color={COLORS.E5_DEEP}
        />
      </div>

      {/* Big envelope→verdict resolve mark */}
      <ResolveMark />

      {/* colophon */}
      <div
        style={{
          position: "absolute",
          left: "0.75in",
          bottom: "1.35in",
          fontFamily: FONTS.MONO,
          fontSize: TYPE.eyebrow.size,
          fontWeight: 500,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: COLORS.INK_SUBTLE,
          lineHeight: 1.5,
        }}
      >
        JobTracker · System Card Vol. 01
        <br />
        Ayush Yadav · 2026
      </div>

      {/* end fleuron */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: "0.85in",
          display: "flex",
          justifyContent: "center",
        }}
        aria-hidden
      >
        <svg width={72} height={14} viewBox="0 0 72 14">
          <circle cx={8} cy={7} r={1.6} fill={COLORS.INK} opacity={0.3} />
          <line x1={16} y1={7} x2={26} y2={7} stroke={COLORS.INK} strokeOpacity={0.3} strokeWidth={0.8} />
          <rect x={32} y={3} width={8} height={8} transform="rotate(45 36 7)" fill={COLORS.RULES_DEEP} opacity={0.85} />
          <line x1={46} y1={7} x2={56} y2={7} stroke={COLORS.INK} strokeOpacity={0.3} strokeWidth={0.8} />
          <circle cx={64} cy={7} r={1.6} fill={COLORS.INK} opacity={0.3} />
        </svg>
      </div>
    </BodyPage>
  );
};

const UrlBlock: React.FC<{ label: string; url: string; arrow: string; color: string }> = ({
  label,
  url,
  arrow,
  color,
}) => (
  <div>
    <div
      style={{
        fontFamily: FONTS.MONO,
        fontSize: TYPE.eyebrow.size,
        fontWeight: 700,
        letterSpacing: "0.12em",
        textTransform: "uppercase",
        color: COLORS.INK_MUTED,
      }}
    >
      {label}
    </div>
    <div
      style={{
        fontFamily: FONTS.SANS,
        fontSize: 16,
        fontWeight: 600,
        color: COLORS.INK,
        marginTop: 3,
        letterSpacing: "-0.01em",
        wordBreak: "break-all",
      }}
    >
      {url}
    </div>
    <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 8 }}>
      <svg width={40} height={12} viewBox="0 0 40 12" aria-hidden>
        <line x1={2} y1={6} x2={34} y2={6} stroke={color} strokeWidth={1.4} strokeLinecap="round" />
        <path d="M30 2 L36 6 L30 10" fill="none" stroke={color} strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span style={{ fontFamily: FONTS.SERIF, fontStyle: "italic", fontSize: 13, color }}>{arrow}</span>
    </div>
  </div>
);

/** An envelope resolving into a green verdict tag — the book's motif, once more. */
const ResolveMark: React.FC = () => (
  <div
    style={{
      position: "absolute",
      right: "0.9in",
      bottom: "1.5in",
      display: "flex",
      alignItems: "center",
      gap: 14,
    }}
    aria-hidden
  >
    <svg width={62} height={46} viewBox="0 0 62 46">
      <rect x={2} y={4} width={44} height={30} rx={3} fill="none" stroke={COLORS.INK} strokeOpacity={0.28} strokeWidth={1.6} />
      <path d="M3 6 L24 22 L45 6" fill="none" stroke={COLORS.INK} strokeOpacity={0.28} strokeWidth={1.6} strokeLinejoin="round" />
      <circle cx={50} cy={30} r={9} fill={COLORS.SETFIT_GREEN} />
      <path d="M46 30 L49 33 L54 27" fill="none" stroke={COLORS.PAPER} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
    <span
      style={{
        fontFamily: FONTS.MONO,
        fontSize: 8,
        letterSpacing: "0.16em",
        textTransform: "uppercase",
        color: COLORS.INK_SUBTLE,
      }}
    >
      inbox → verdict
    </span>
  </div>
);
