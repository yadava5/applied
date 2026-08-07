import React from "react";
import { COLORS, FONTS, PAGE } from "../theme";
import { BRAND, MASTHEAD } from "../content";
import { CoverField } from "../visuals/CoverField";
import { AppliedLogoMark } from "../visuals/AppliedLogoMark";

/**
 * Front cover (page 01). A full-bleed near-black field of email envelopes
 * resolving into classified verdicts (CoverField) — the app's story told in
 * one image — with a legend that seeds the book's color language, a title
 * block lower-left over a soft scrim, and a vertical mono margin callout.
 */
export const CoverPage: React.FC = () => (
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
    <CoverField widthIn={8.75} heightIn={11.25} variant="front" />

    {/* Masthead — top-left. Same scrim-pill chrome as the legend opposite it:
        bare on the field, an envelope glyph ran straight through the text.
        Leads with the app's pipeline mark as a publisher's device — the field
        argues the mark's story at page scale, the masthead states it at seal
        scale. The pill stands in for the chip's dark tile. */}
    <div
      style={{
        position: "absolute",
        top: "0.62in",
        left: "0.62in",
        display: "flex",
        alignItems: "center",
        gap: 9,
        padding: "6px 12px",
        borderRadius: 999,
        background: "rgba(8, 13, 24, 0.66)",
        border: `0.5pt solid ${COLORS.ON_DARK_HAIRLINE}`,
        fontFamily: FONTS.MONO,
        fontSize: 9,
        fontWeight: 600,
        letterSpacing: "0.22em",
        textTransform: "uppercase",
        color: COLORS.ON_DARK_MUTED,
      }}
    >
      <AppliedLogoMark size={18} />
      {BRAND.name} · System Card
    </div>

    {/* Layer legend — top-right, establishes the color language up front. A
        subtle scrim lifts it off the busy resolved-envelope region. */}
    <div
      style={{
        position: "absolute",
        top: "0.6in",
        right: "0.62in",
        display: "flex",
        gap: 13,
        alignItems: "center",
        padding: "7px 12px",
        borderRadius: 999,
        background: "rgba(8, 13, 24, 0.66)",
        border: `0.5pt solid ${COLORS.ON_DARK_HAIRLINE}`,
      }}
    >
      {[
        { c: COLORS.RULES_CYAN, l: "rules" },
        { c: COLORS.E5_VIOLET, l: "e5" },
        { c: COLORS.SETFIT_GREEN, l: "SetFit" },
        { c: COLORS.GATE_AMBER, l: "gate" },
      ].map((x) => (
        <span
          key={x.l}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 5,
            fontFamily: FONTS.MONO,
            fontSize: 8,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: COLORS.ON_DARK,
          }}
        >
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: x.c }} />
          {x.l}
        </span>
      ))}
    </div>

    {/* Scrim behind the title block */}
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

    {/* Vertical margin callout — right edge. Painted AFTER the scrim: it sits
        in the scrim's fade band, and stacking it below cut it to
        near-invisible at print density. */}
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
      classify at the source
    </div>

    {/* Title block — lower-left */}
    <div
      style={{
        position: "absolute",
        left: "0.7in",
        bottom: "0.95in",
        right: "0.7in",
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <div
        style={{
          fontFamily: FONTS.SANS,
          fontSize: 78,
          fontWeight: 700,
          letterSpacing: "-0.035em",
          lineHeight: 0.92,
          color: COLORS.ON_DARK,
        }}
      >
        {BRAND.wordmarkHead}
        <span style={{ color: COLORS.RULES_CYAN }}>{BRAND.wordmarkTail}</span>
      </div>
      <div
        style={{
          fontFamily: FONTS.SERIF,
          fontStyle: "italic",
          fontSize: 23,
          lineHeight: 1.22,
          color: COLORS.ON_DARK_MUTED,
          maxWidth: "5.4in",
        }}
      >
        {BRAND.subtitle}
      </div>
      <div
        style={{
          marginTop: 6,
          display: "flex",
          alignItems: "center",
          gap: 14,
          fontFamily: FONTS.MONO,
          fontSize: 9,
          fontWeight: 500,
          letterSpacing: "0.16em",
          textTransform: "uppercase",
          color: COLORS.ON_DARK,
        }}
      >
        <span>
          {BRAND.author} · {BRAND.year}
        </span>
        <span style={{ width: 28, height: 1, background: COLORS.ON_DARK_HAIRLINE }} />
        <span style={{ color: COLORS.ON_DARK_SUBTLE }}>{MASTHEAD.volume}</span>
      </div>
    </div>
  </section>
);
