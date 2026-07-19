import React from "react";
import { BodyPage } from "../templates/BodyPage";
import { COLORS, FONTS, TYPE, SECTION, SECTION_INK } from "../theme";
import { HOW, LAYERS } from "../content";
import { StatBig } from "../primitives/StatBig";

/**
 * Shared template for the three Layer pages (10–12). Each is one rung of the
 * cascade: a rail placing it in the 1-2-3 sequence, the layer's prose, its two
 * headline numbers, and an honesty note. The layer's own accent colors the
 * page so the reader feels which rung they are on.
 */

type LayerContent = {
  eyebrow: string;
  headline: string;
  body: readonly string[];
  stat: { value: string; label: string };
  stat2: { value: string; label: string };
  note: string;
};

const LayerDetail: React.FC<{
  parity: "recto" | "verso";
  pageNumber: number;
  totalPages: number;
  activeIndex: number;
  data: LayerContent;
}> = ({ parity, pageNumber, totalPages, activeIndex, data }) => {
  const layer = LAYERS[activeIndex]!;
  const accent = SECTION[layer.accentKey];
  const accentInk = SECTION_INK[layer.accentKey];
  return (
    <BodyPage
      parity={parity}
      pageNumber={pageNumber}
      totalPages={totalPages}
      sectionLabel="HOW"
      sectionColor={accentInk}
      eyebrow={data.eyebrow}
      headline={data.headline}
    >
      <LayerRail activeIndex={activeIndex} />

      <div style={{ maxWidth: "6.3in", marginTop: 20 }}>
        {data.body.map((p, i) => (
          <p
            key={i}
            style={{
              fontFamily: FONTS.SANS,
              fontSize: TYPE.body.size,
              lineHeight: TYPE.body.lh,
              letterSpacing: TYPE.body.tracking,
              color: COLORS.INK,
              margin: "0 0 10px",
            }}
          >
            {p}
          </p>
        ))}
      </div>

      {/* Two headline numbers */}
      <div
        style={{
          display: "flex",
          gap: 40,
          marginTop: 26,
          paddingTop: 18,
          borderTop: `1pt solid ${accent}`,
        }}
      >
        <StatBig value={data.stat.value} label={data.stat.label} tier="metricMedium" color={accentInk} />
        <StatBig value={data.stat2.value} label={data.stat2.label} tier="metricMedium" color={COLORS.INK} />
        <div style={{ flex: 1 }} />
      </div>

      {/* Honesty note */}
      <div
        style={{
          marginTop: 24,
          borderLeft: `2.5px solid ${accent}`,
          paddingLeft: 14,
          maxWidth: "6in",
        }}
      >
        <div
          style={{
            fontFamily: FONTS.MONO,
            fontSize: 8.5,
            fontWeight: 700,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            color: accentInk,
            marginBottom: 5,
          }}
        >
          On the record
        </div>
        <p
          style={{
            fontFamily: FONTS.SERIF,
            fontStyle: "italic",
            fontSize: 15,
            lineHeight: 1.4,
            color: COLORS.INK,
            margin: 0,
          }}
        >
          {data.note}
        </p>
      </div>
    </BodyPage>
  );
};

/** The 1-2-3 rail with the current layer lit. */
const LayerRail: React.FC<{ activeIndex: number }> = ({ activeIndex }) => (
  <div style={{ display: "flex", alignItems: "center", gap: 0, marginTop: 2 }}>
    {LAYERS.map((l, i) => {
      const accent = SECTION[l.accentKey];
      const active = i === activeIndex;
      return (
        <React.Fragment key={l.id}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              opacity: active ? 1 : 0.4,
            }}
          >
            <span
              style={{
                width: 26,
                height: 26,
                borderRadius: "50%",
                background: active ? accent : "transparent",
                border: `1.5px solid ${accent}`,
                color: active ? COLORS.GROUND : accent,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontFamily: FONTS.MONO,
                fontSize: 11,
                fontWeight: 700,
                boxShadow: active ? `0 0 12px -3px ${accent}` : "none",
              }}
            >
              {l.n}
            </span>
            <span
              style={{
                fontFamily: FONTS.MONO,
                fontSize: 10,
                fontWeight: active ? 700 : 500,
                letterSpacing: "0.04em",
                color: active ? COLORS.INK : COLORS.INK_MUTED,
              }}
            >
              {l.label}
            </span>
          </div>
          {i < LAYERS.length - 1 && (
            <span
              style={{
                width: 26,
                height: 1.5,
                background: COLORS.HAIRLINE_STRONG,
                margin: "0 12px",
              }}
            />
          )}
        </React.Fragment>
      );
    })}
  </div>
);

// ── The three concrete pages ───────────────────────────────────────────────

type PageProps = { parity: "recto" | "verso"; pageNumber: number; totalPages: number };

export const HowRulesPage: React.FC<PageProps> = (p) => (
  <LayerDetail {...p} activeIndex={0} data={HOW.rules} />
);
export const HowEmbeddingsPage: React.FC<PageProps> = (p) => (
  <LayerDetail {...p} activeIndex={1} data={HOW.embeddings} />
);
export const HowSetfitPage: React.FC<PageProps> = (p) => (
  <LayerDetail {...p} activeIndex={2} data={HOW.setfit} />
);
