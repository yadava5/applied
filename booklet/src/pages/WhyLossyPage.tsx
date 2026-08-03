import React from "react";
import { BodyPage } from "../templates/BodyPage";
import { COLORS, FONTS, TYPE, SECTION, SECTION_INK } from "../theme";
import { WHY } from "../content";

/** Page 06 — manual tracking is lossy. A BEFORE / WITH comparison. */
export const WhyLossyPage: React.FC<{
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
    eyebrow={WHY.lossy.eyebrow}
    headline={WHY.lossy.headline}
  >
    <p
      style={{
        fontFamily: FONTS.SERIF,
        fontStyle: "italic",
        fontSize: 17,
        lineHeight: 1.35,
        color: COLORS.INK_MUTED,
        margin: "0 0 22px",
        maxWidth: "6.2in",
      }}
    >
      {WHY.lossy.lede}
    </p>

    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: 24 }}>
      {/* BEFORE */}
      <div>
        <ColumnHead label={WHY.lossy.beforeTitle} color={COLORS.INK_MUTED} />
        <ul style={listStyle}>
          {WHY.lossy.before.map((item, i) => (
            <Item key={i} n={i} color={COLORS.INK_MUTED}>
              {item}
            </Item>
          ))}
        </ul>
      </div>
      {/* WITH */}
      <div>
        <ColumnHead label={WHY.lossy.withTitle} color={SECTION_INK["01_WHY"]} />
        <ul style={listStyle}>
          {WHY.lossy.with.map((item, i) => (
            <Item key={i} n={i} color={SECTION_INK["01_WHY"]}>
              {item}
            </Item>
          ))}
        </ul>
      </div>
    </div>

    {/* Closing line */}
    <div
      style={{
        marginTop: 28,
        borderLeft: `2.5px solid ${SECTION["01_WHY"]}`,
        background: COLORS.GATE_TINT,
        borderRadius: 4,
        padding: "14px 18px",
      }}
    >
      <p
        style={{
          fontFamily: FONTS.SERIF,
          fontStyle: "italic",
          fontSize: 18,
          lineHeight: 1.35,
          color: COLORS.INK,
          margin: 0,
        }}
      >
        {WHY.lossy.gate}
      </p>
    </div>
  </BodyPage>
);

const ColumnHead: React.FC<{ label: string; color: string }> = ({ label, color }) => (
  <div
    style={{
      fontFamily: FONTS.MONO,
      fontSize: TYPE.eyebrow.size,
      fontWeight: 700,
      letterSpacing: "0.12em",
      textTransform: "uppercase",
      color,
      marginBottom: 10,
      paddingBottom: 5,
      borderBottom: `1pt solid ${color}`,
    }}
  >
    {label}
  </div>
);

const Item: React.FC<{ n: number; color: string; children: React.ReactNode }> = ({
  n,
  color,
  children,
}) => (
  <li style={itemStyle}>
    <span
      style={{
        fontFamily: FONTS.MONO,
        fontSize: 9,
        fontWeight: 700,
        color,
        letterSpacing: "0.06em",
        paddingTop: 2,
      }}
    >
      {String(n + 1).padStart(2, "0")}
    </span>
    <span>{children}</span>
  </li>
);

const listStyle: React.CSSProperties = {
  listStyle: "none",
  padding: 0,
  margin: 0,
  display: "flex",
  flexDirection: "column",
  gap: 12,
};

const itemStyle: React.CSSProperties = {
  fontFamily: FONTS.SANS,
  fontSize: TYPE.body.size,
  letterSpacing: TYPE.body.tracking,
  lineHeight: 1.4,
  color: COLORS.INK,
  fontWeight: 500,
  display: "grid",
  gridTemplateColumns: "22px 1fr",
  columnGap: 6,
};
