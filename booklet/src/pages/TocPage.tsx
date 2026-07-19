import React from "react";
import { Page } from "../primitives/Page";
import { COLORS, FONTS, TYPE, SECTION } from "../theme";
import { BRAND, CHAPTERS, TOC } from "../content";

/**
 * Contents (page 03). Upper band: title block + colored TOC. Lower band: the
 * reading apparatus — who this is for, how to read it, at a glance, a
 * micro-glossary, and a five-waypoint reading path.
 */
export const TocPage: React.FC<{
  parity: "recto" | "verso";
  pageNumber: number;
  totalPages: number;
}> = ({ parity, pageNumber, totalPages }) => (
  <Page
    parity={parity}
    pageNumber={pageNumber}
    totalPages={totalPages}
    sectionLabel="FRONTMATTER"
    sectionColor={COLORS.INK_MUTED}
    hideFooter
  >
    <div style={{ display: "flex", flexDirection: "column", height: "100%", gap: 16 }}>
      {/* Upper band */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1.1fr", columnGap: "0.5in" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <SmallLabel>Vol. 01 · System Card</SmallLabel>
          <h1
            style={{
              fontFamily: FONTS.SANS,
              fontSize: 46,
              fontWeight: 700,
              letterSpacing: "-0.03em",
              lineHeight: 1,
              color: COLORS.INK,
              margin: 0,
            }}
          >
            {BRAND.name}
          </h1>
          <p
            style={{
              fontFamily: FONTS.SERIF,
              fontStyle: "italic",
              fontSize: 18,
              lineHeight: 1.25,
              color: COLORS.INK_MUTED,
              margin: 0,
            }}
          >
            {BRAND.subtitle}
          </p>
          <div style={{ marginTop: 14 }}>
            <LabelValue label="Author" value={`${BRAND.author} · ${BRAND.year}`} />
            <LabelValue label="Live" value={BRAND.liveUrl} />
            <LabelValue label="Model" value="int8 ONNX · runs in-browser · MIT" />
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
          <SmallLabel>Contents</SmallLabel>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 2 }}>
            {CHAPTERS.map((ch) => (
              <TocRow
                key={ch.num}
                num={ch.num}
                name={ch.name}
                tagline={TOC.chapterTaglines[ch.name] ?? ""}
                pages={ch.pages}
                color={SECTION[ch.sectionKey]}
                glyph={TOC.chapterGlyphs[ch.name] ?? ""}
              />
            ))}
          </div>
        </div>
      </div>

      <div style={{ borderTop: `0.5pt solid ${COLORS.HAIRLINE}` }} />

      {/* Editorial grid */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", columnGap: "0.4in", rowGap: 18 }}>
        <EditorialBlock eyebrow="WHO THIS IS FOR" rows={TOC.audience} />
        <EditorialBlock eyebrow="HOW TO READ IT" rows={TOC.readingPaths} />
        <EditorialBlock eyebrow="AT A GLANCE" rows={TOC.atAGlance} />
      </div>

      {/* Glossary strip */}
      <div>
        <SmallLabel style={{ marginBottom: 8 }}>Glossary at a glance</SmallLabel>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(6, 1fr)",
            columnGap: 12,
            borderTop: `0.5pt solid ${COLORS.HAIRLINE}`,
            borderBottom: `0.5pt solid ${COLORS.HAIRLINE}`,
            padding: "10px 0",
          }}
        >
          {TOC.glossary.map((g) => (
            <div key={g.term} style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <div
                style={{
                  fontFamily: FONTS.MONO,
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: "0.04em",
                  color: COLORS.INK,
                }}
              >
                {g.term}
              </div>
              <div
                style={{
                  fontFamily: FONTS.SANS,
                  fontSize: 8.5,
                  lineHeight: 1.32,
                  color: COLORS.INK_MUTED,
                }}
              >
                {g.def}
              </div>
            </div>
          ))}
        </div>
      </div>

      <ReadingPath />

      <div style={{ flex: 1 }} />

      {/* Teaser + colophon */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1.6fr 1fr",
          columnGap: "0.4in",
          alignItems: "center",
          borderTop: `0.5pt solid ${COLORS.HAIRLINE}`,
          paddingTop: 14,
        }}
      >
        <p
          style={{
            fontFamily: FONTS.SERIF,
            fontStyle: "italic",
            fontSize: 16,
            lineHeight: 1.3,
            color: COLORS.INK,
            margin: 0,
            maxWidth: "4.4in",
            borderLeft: `2px solid ${COLORS.RULES_DEEP}`,
            paddingLeft: 14,
          }}
        >
          {TOC.teaser}
        </p>
        <div
          style={{
            fontFamily: FONTS.MONO,
            fontSize: 8.5,
            fontWeight: 500,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: COLORS.INK_SUBTLE,
            lineHeight: 1.55,
            textAlign: "right",
          }}
        >
          {TOC.colophon.map((l, i) => (
            <React.Fragment key={i}>
              {l}
              <br />
            </React.Fragment>
          ))}
        </div>
      </div>
    </div>
  </Page>
);

// ── sub-components ─────────────────────────────────────────────────────────

const SmallLabel: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({
  children,
  style,
}) => (
  <div
    style={{
      fontFamily: FONTS.MONO,
      fontSize: TYPE.eyebrow.size,
      fontWeight: 600,
      letterSpacing: TYPE.eyebrow.tracking,
      textTransform: "uppercase",
      color: COLORS.INK_MUTED,
      ...style,
    }}
  >
    {children}
  </div>
);

const LabelValue: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div style={{ display: "grid", gridTemplateColumns: "58px 1fr", alignItems: "baseline", marginBottom: 5 }}>
    <div
      style={{
        fontFamily: FONTS.MONO,
        fontSize: TYPE.eyebrow.size,
        fontWeight: 600,
        letterSpacing: "0.12em",
        textTransform: "uppercase",
        color: COLORS.INK_MUTED,
      }}
    >
      {label}
    </div>
    <div style={{ fontFamily: FONTS.SANS, fontSize: 12, fontWeight: 500, color: COLORS.INK }}>
      {value}
    </div>
  </div>
);

const TocRow: React.FC<{
  num: string;
  name: string;
  tagline: string;
  pages: string;
  color: string;
  glyph: string;
}> = ({ num, name, tagline, pages, color, glyph }) => (
  <div
    style={{
      display: "grid",
      gridTemplateColumns: "0.45in 30px 1fr auto",
      alignItems: "center",
      columnGap: 10,
      borderBottom: `0.5pt solid ${COLORS.HAIRLINE}`,
      paddingBottom: 7,
    }}
  >
    <div
      style={{
        width: "0.45in",
        height: 32,
        background: color,
        borderRadius: 3,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: COLORS.GROUND,
        fontFamily: FONTS.MONO,
        fontSize: 15,
        fontWeight: 700,
      }}
    >
      {glyph}
    </div>
    <div
      style={{
        fontFamily: FONTS.MONO,
        fontSize: 15,
        fontWeight: 700,
        color: COLORS.INK,
        fontVariantNumeric: "tabular-nums",
      }}
    >
      {num}
    </div>
    <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
      <div style={{ fontFamily: FONTS.SERIF, fontStyle: "italic", fontSize: 19, color: COLORS.INK, lineHeight: 1 }}>
        {name}
      </div>
      <div
        style={{
          fontFamily: FONTS.SERIF,
          fontStyle: "italic",
          fontSize: 12.5,
          lineHeight: 1.25,
          color: COLORS.INK_SUBTLE,
        }}
      >
        {tagline}
      </div>
    </div>
    <div
      style={{
        fontFamily: FONTS.MONO,
        fontSize: 10,
        fontWeight: 600,
        color: COLORS.INK_MUTED,
        fontVariantNumeric: "tabular-nums",
      }}
    >
      {pages}
    </div>
  </div>
);

const EditorialBlock: React.FC<{
  eyebrow: string;
  rows: ReadonlyArray<{ key: string; val: string }>;
}> = ({ eyebrow, rows }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
    <SmallLabel>{eyebrow}</SmallLabel>
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {rows.map((r) => (
        <div key={r.key} style={{ display: "flex", flexDirection: "column", gap: 1 }}>
          <div
            style={{
              fontFamily: FONTS.MONO,
              fontSize: 9.5,
              fontWeight: 700,
              letterSpacing: "0.04em",
              textTransform: "uppercase",
              color: COLORS.INK,
            }}
          >
            {r.key}
          </div>
          <div
            style={{
              fontFamily: FONTS.SERIF,
              fontStyle: "italic",
              fontSize: 12,
              lineHeight: 1.3,
              color: COLORS.INK_MUTED,
            }}
          >
            {r.val}
          </div>
        </div>
      ))}
    </div>
  </div>
);

const ReadingPath: React.FC = () => (
  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
      <SmallLabel>Reading path</SmallLabel>
      <div style={{ fontFamily: FONTS.SERIF, fontStyle: "italic", fontSize: 11, color: COLORS.INK_SUBTLE }}>
        five chapters · one sitting
      </div>
    </div>
    <div style={{ position: "relative", padding: "8px 0 4px" }}>
      <div
        style={{
          position: "absolute",
          top: 15,
          left: "4%",
          right: "4%",
          borderTop: `0.5pt solid ${COLORS.HAIRLINE}`,
        }}
      />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", position: "relative" }}>
        {CHAPTERS.map((ch) => (
          <div key={ch.num} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
            <div
              style={{
                width: 13,
                height: 13,
                borderRadius: "50%",
                background: SECTION[ch.sectionKey],
                border: `2px solid ${COLORS.PAPER}`,
                boxShadow: `0 0 0 1pt ${SECTION[ch.sectionKey]}`,
              }}
            />
            <div
              style={{
                fontFamily: FONTS.MONO,
                fontSize: 8.5,
                fontWeight: 700,
                letterSpacing: "0.1em",
                textTransform: "uppercase",
                color: COLORS.INK,
                marginTop: 2,
              }}
            >
              {ch.num} · {ch.name}
            </div>
            <div
              style={{
                fontFamily: FONTS.MONO,
                fontSize: 8.5,
                color: COLORS.INK_SUBTLE,
                fontVariantNumeric: "tabular-nums",
              }}
            >
              pp. {ch.pages}
            </div>
          </div>
        ))}
      </div>
    </div>
  </div>
);
