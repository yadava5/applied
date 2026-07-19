import React from "react";
import { COLORS, FONTS, PAGE } from "../theme";
import { BRAND, MASTHEAD } from "../content";
import { CoverField } from "../visuals/CoverField";

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

    {/* Masthead — top-left */}
    <div
      style={{
        position: "absolute",
        top: "0.7in",
        left: "0.7in",
        fontFamily: FONTS.MONO,
        fontSize: 9,
        fontWeight: 600,
        letterSpacing: "0.22em",
        textTransform: "uppercase",
        color: COLORS.ON_DARK_MUTED,
      }}
    >
      JobTracker · System Card
    </div>

    {/* Layer legend — top-right, establishes the color language up front */}
    <div
      style={{
        position: "absolute",
        top: "0.66in",
        right: "0.7in",
        display: "flex",
        gap: 12,
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
            color: COLORS.ON_DARK_MUTED,
          }}
        >
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: x.c }} />
          {x.l}
        </span>
      ))}
    </div>

    {/* Vertical margin callout — right edge */}
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
        Job<span style={{ color: COLORS.RULES_CYAN }}>Tracker</span>
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
