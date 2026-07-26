import React from "react";
import { COLORS, FONTS, PAGE } from "../theme";
import { BACK_COVER } from "../content";
import { CoverField } from "../visuals/CoverField";

/**
 * Back cover (page 32) — a PURE CLOSING that mirrors the front cover. The same
 * wraparound envelope field (reseeded "back" variant), a colophon top-left, a
 * quiet closing line + coda lower-left over a soft scrim, and a vertical margin
 * callout on the right edge. No QR, no "scan me", no CTA — the Try-It page (31)
 * already sent the reader to the product; this page just closes the book.
 */
export const BackCoverPage: React.FC = () => (
  <section
    className="page"
    data-bleed="true"
    style={{
      background: COLORS.GROUND,
      color: COLORS.ON_DARK,
      position: "relative",
      overflow: "hidden",
    }}
  >
    <CoverField widthIn={8.75} heightIn={11.25} variant="back" />

    {/* Colophon — upper-left (mirrors the cover masthead) */}
    <div
      style={{
        position: "absolute",
        top: "0.7in",
        left: "0.7in",
        fontFamily: FONTS.MONO,
        fontSize: 8.5,
        fontWeight: 500,
        letterSpacing: "0.16em",
        textTransform: "uppercase",
        color: COLORS.ON_DARK_MUTED,
        lineHeight: 1.7,
      }}
    >
      {BACK_COVER.colophon.map((line, i) => (
        <React.Fragment key={i}>
          {line}
          <br />
        </React.Fragment>
      ))}
    </div>

    {/* Vertical margin callout — right edge (mirrors the cover) */}
    <div
      style={{
        position: "absolute",
        right: "0.4in",
        bottom: `${PAGE.margin.bottom}in`,
        writingMode: "vertical-rl",
        fontFamily: FONTS.MONO,
        fontSize: 8.5,
        fontWeight: 500,
        letterSpacing: "0.22em",
        textTransform: "uppercase",
        color: COLORS.ON_DARK_SUBTLE,
      }}
    >
      end · vol. 01
    </div>

    {/* Scrim behind the closing block */}
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 0,
        height: "4.2in",
        background: `linear-gradient(to top, ${COLORS.GROUND} 12%, rgba(11,18,32,0.86) 46%, rgba(11,18,32,0) 100%)`,
        pointerEvents: "none",
      }}
    />

    {/* Closing block — lower-left (mirrors the cover title block) */}
    <div
      style={{
        position: "absolute",
        left: "0.7in",
        bottom: "0.95in",
        right: "1.2in",
        display: "flex",
        flexDirection: "column",
        gap: 14,
      }}
    >
      <div
        style={{
          fontFamily: FONTS.SANS,
          fontSize: 34,
          fontWeight: 700,
          letterSpacing: "-0.03em",
          lineHeight: 1,
          color: COLORS.ON_DARK,
        }}
      >
        App<span style={{ color: COLORS.RULES_CYAN }}>lied</span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <div
          style={{
            fontFamily: FONTS.SERIF,
            fontStyle: "italic",
            fontSize: 24,
            lineHeight: 1.2,
            color: COLORS.ON_DARK,
            maxWidth: "5.2in",
          }}
        >
          {BACK_COVER.closingLine}
        </div>
        <div
          style={{
            fontFamily: FONTS.SERIF,
            fontStyle: "italic",
            fontSize: 17,
            lineHeight: 1.25,
            color: COLORS.ON_DARK_MUTED,
          }}
        >
          {BACK_COVER.coda}
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 2 }}>
        <span style={{ width: 34, height: 1, background: COLORS.ON_DARK_HAIRLINE }} />
        <span
          style={{
            fontFamily: FONTS.MONO,
            fontSize: 8.5,
            fontWeight: 500,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: COLORS.ON_DARK_SUBTLE,
          }}
        >
          System Card · Vol. 01
        </span>
      </div>
    </div>
  </section>
);
