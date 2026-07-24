import React from "react";
import { QRCodeSVG } from "qrcode.react";
import { BodyPage } from "../templates/BodyPage";
import { COLORS, FONTS, TYPE, SECTION_INK } from "../theme";
import { BUILD } from "../content";

/**
 * Page 31 — Try it. The reader's exit into the live product. The QR lives HERE
 * now (moved off the back cover, which is a quiet closing): scan to open the
 * app, plus the two destinations and the in-browser classifier Space.
 */
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
      sectionColor={SECTION_INK["06_BUILD"]}
      eyebrow={closing.eyebrow}
      headline={closing.headline}
      align="top"
    >
      <p
        style={{
          fontFamily: FONTS.SERIF,
          fontStyle: "italic",
          fontSize: 20,
          lineHeight: 1.3,
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
          marginBottom: 30,
        }}
      >
        {closing.microNote}
      </div>

      {/* QR card + destinations */}
      <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", columnGap: 30, alignItems: "center" }}>
        {/* QR on a paper card */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
          <div
            style={{
              background: COLORS.PAPER,
              borderRadius: 10,
              padding: 14,
              border: `1px solid ${COLORS.HAIRLINE}`,
              boxShadow: "0 1px 8px rgba(11,18,32,0.06)",
            }}
          >
            <QRCodeSVG value={closing.qrTarget} size={132} level="M" marginSize={0} fgColor={COLORS.INK} />
          </div>
          <div
            style={{
              fontFamily: FONTS.MONO,
              fontSize: 8,
              fontWeight: 600,
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              color: COLORS.INK_MUTED,
            }}
          >
            {closing.qrCaption}
          </div>
        </div>

        {/* Destinations */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <UrlBlock label={closing.liveLabel} url={closing.liveUrl} arrow={closing.leftArrowLabel} color={COLORS.RULES_DEEP} />
          <div style={{ borderTop: `0.5pt solid ${COLORS.HAIRLINE}` }} />
          <UrlBlock label={closing.spaceLabel} url={closing.spaceUrl} arrow={closing.rightArrowLabel} color={COLORS.E5_DEEP} note={closing.spaceNote} />
        </div>
      </div>

      {/* What to try once you're in */}
      <div style={{ marginTop: 34 }}>
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
          three things to try
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 0, borderTop: `1pt solid ${COLORS.INK}` }}>
          <TryItem n="01" title="Paste a real email" body="watch it fall through rules → e5 → SetFit." accent={COLORS.RULES_DEEP} first />
          <TryItem n="02" title="Read the decision trace" body="see which layer fired, and how sure it was." accent={COLORS.E5_DEEP} />
          <TryItem n="03" title="Cross the gate" body="drop below 0.85 and land in needs_review." accent={COLORS.GATE_DEEP} />
        </div>
      </div>

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
        Applied · System Card Vol. 01
        <br />
        Ayush Yadav · 2026
      </div>

      {/* envelope→verdict resolve mark, lower-right */}
      <div style={{ position: "absolute", right: "0.9in", bottom: "1.4in", display: "flex", alignItems: "center", gap: 12 }} aria-hidden>
        <svg width={56} height={42} viewBox="0 0 62 46">
          <rect x={2} y={4} width={44} height={30} rx={3} fill="none" stroke={COLORS.INK} strokeOpacity={0.28} strokeWidth={1.6} />
          <path d="M3 6 L24 22 L45 6" fill="none" stroke={COLORS.INK} strokeOpacity={0.28} strokeWidth={1.6} strokeLinejoin="round" />
          <circle cx={50} cy={30} r={9} fill={COLORS.SETFIT_GREEN} />
          <path d="M46 30 L49 33 L54 27" fill="none" stroke={COLORS.PAPER} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span style={{ fontFamily: FONTS.MONO, fontSize: 8, letterSpacing: "0.16em", textTransform: "uppercase", color: COLORS.INK_SUBTLE }}>
          inbox → verdict
        </span>
      </div>

      {/* end fleuron */}
      <div style={{ position: "absolute", left: 0, right: 0, bottom: "0.85in", display: "flex", justifyContent: "center" }} aria-hidden>
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

const TryItem: React.FC<{ n: string; title: string; body: string; accent: string; first?: boolean }> = ({
  n,
  title,
  body,
  accent,
  first = false,
}) => (
  <div style={{ padding: "12px 16px 0", borderLeft: first ? "none" : `0.5pt solid ${COLORS.HAIRLINE}` }}>
    <div style={{ fontFamily: FONTS.MONO, fontSize: 10, fontWeight: 700, color: accent, letterSpacing: "0.04em", marginBottom: 5 }}>{n}</div>
    <div style={{ fontFamily: FONTS.SANS, fontSize: 12, fontWeight: 700, color: COLORS.INK, letterSpacing: "-0.01em", marginBottom: 3 }}>{title}</div>
    <div style={{ fontFamily: FONTS.SERIF, fontStyle: "italic", fontSize: 11, lineHeight: 1.35, color: COLORS.INK_MUTED }}>{body}</div>
  </div>
);

const UrlBlock: React.FC<{ label: string; url: string; arrow: string; color: string; note?: string }> = ({
  label,
  url,
  arrow,
  color,
  note,
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
        overflowWrap: "anywhere",
      }}
    >
      {url}
    </div>
    {note && (
      <div style={{ fontFamily: FONTS.MONO, fontSize: 8.5, color: COLORS.INK_MUTED, marginTop: 3, letterSpacing: "0.02em" }}>
        {note}
      </div>
    )}
    <div style={{ marginTop: 7, display: "flex", alignItems: "center", gap: 8 }}>
      <svg width={40} height={12} viewBox="0 0 40 12" aria-hidden>
        <line x1={2} y1={6} x2={34} y2={6} stroke={color} strokeWidth={1.4} strokeLinecap="round" />
        <path d="M30 2 L36 6 L30 10" fill="none" stroke={color} strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span style={{ fontFamily: FONTS.SERIF, fontStyle: "italic", fontSize: 13, color }}>{arrow}</span>
    </div>
  </div>
);
