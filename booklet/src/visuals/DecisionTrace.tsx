import React from "react";
import { COLORS, FONTS, SECTION, type SectionKey } from "../theme";
import { PROOF, LAYERS } from "../content";

/**
 * The signature Applied visual, printed. A faithful still of the app's
 * DecisionTrace (apps/web/components/viz/DecisionTrace.tsx): every email's
 * verdict traced through the three layers, the firing layer lit in its hue,
 * a confidence meter drawn against the 0.85 gate. Rendered on the dark ground
 * so it reads as the live product. Rows are illustrative of the mechanism.
 */

const LAYER_ACCENTS = LAYERS.map((l) => SECTION[l.accentKey as SectionKey]);
const GATE = 0.85;

export const DecisionTrace: React.FC = () => {
  const rows = PROOF.trace.rows;
  const expanded = rows[3]; // the first needs-review row — shows the gate meter

  return (
    <div style={{ fontFamily: FONTS.SANS }}>
      {/* Legend */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: "6px 16px",
          paddingBottom: 10,
          borderBottom: `1px solid ${COLORS.ON_DARK_HAIRLINE}`,
        }}
      >
        {LAYERS.map((l, i) => (
          <span
            key={l.id}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              fontFamily: FONTS.MONO,
              fontSize: 9.5,
              color: COLORS.ON_DARK_MUTED,
            }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: LAYER_ACCENTS[i],
              }}
            />
            <span style={{ color: COLORS.ON_DARK_SUBTLE }}>{i + 1}</span>{" "}
            <span style={{ color: COLORS.ON_DARK }}>{l.label}</span>
          </span>
        ))}
        <span
          style={{
            marginLeft: "auto",
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            fontFamily: FONTS.MONO,
            fontSize: 9.5,
            color: COLORS.GATE_AMBER,
          }}
        >
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: COLORS.GATE_AMBER }} />
          {PROOF.trace.legendGate}
        </span>
      </div>

      {/* Rows */}
      <div style={{ display: "flex", flexDirection: "column" }}>
        {rows.map((item, ri) => {
          const pct = Math.round(item.confidence * 100);
          return (
            <div
              key={item.subject}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "9px 0",
                borderTop: ri === 0 ? "none" : `1px solid ${COLORS.ON_DARK_HAIRLINE}`,
              }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    fontFamily: FONTS.SANS,
                    fontSize: 11,
                    fontWeight: 500,
                    color: COLORS.ON_DARK,
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                >
                  {item.subject}
                </div>
                <div
                  style={{
                    fontFamily: FONTS.MONO,
                    fontSize: 8.5,
                    color: COLORS.ON_DARK_SUBTLE,
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                >
                  {item.from}
                </div>
              </div>

              <LayerTrack fired={item.fired} />

              <Verdict item={item} />

              <span
                style={{
                  width: 34,
                  textAlign: "right",
                  fontFamily: FONTS.MONO,
                  fontSize: 11,
                  fontWeight: 600,
                  fontVariantNumeric: "tabular-nums",
                  color: item.needsReview ? COLORS.GATE_AMBER : COLORS.SETFIT_GREEN,
                }}
              >
                {pct}%
              </span>
            </div>
          );
        })}
      </div>

      {/* Expanded trace — the gate meter */}
      {expanded && <GateMeter item={expanded} />}
    </div>
  );
};

type Row = (typeof PROOF.trace.rows)[number];

const LayerTrack: React.FC<{ fired: number }> = ({ fired }) => (
  <div style={{ display: "flex", alignItems: "center" }} aria-hidden>
    {LAYERS.map((l, i) => {
      const isFired = i === fired;
      const passed = i < fired;
      const accent = LAYER_ACCENTS[i]!;
      return (
        <span key={l.id} style={{ display: "flex", alignItems: "center" }}>
          <span
            style={{
              width: 22,
              height: 22,
              display: "grid",
              placeItems: "center",
              borderRadius: 5,
              border: `1px solid ${isFired ? accent : COLORS.ON_DARK_HAIRLINE}`,
              fontFamily: FONTS.MONO,
              fontSize: 9.5,
              fontWeight: 700,
              color: isFired ? accent : COLORS.ON_DARK_SUBTLE,
              background: isFired ? `${accent}22` : "transparent",
              boxShadow: isFired ? `0 0 12px -3px ${accent}` : "none",
              opacity: isFired ? 1 : passed ? 0.7 : 0.4,
            }}
          >
            {passed ? "✓" : i + 1}
          </span>
          {i < LAYERS.length - 1 && (
            <span
              style={{
                width: 10,
                height: 1,
                background: i < fired ? COLORS.ON_DARK_MUTED : COLORS.ON_DARK_HAIRLINE,
              }}
            />
          )}
        </span>
      );
    })}
  </div>
);

const Verdict: React.FC<{ item: Row }> = ({ item }) =>
  item.needsReview ? (
    <span
      style={{
        borderRadius: 999,
        border: `1px solid ${COLORS.GATE_AMBER}`,
        padding: "2px 9px",
        fontFamily: FONTS.MONO,
        fontSize: 8.5,
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.06em",
        color: COLORS.GATE_AMBER,
        whiteSpace: "nowrap",
      }}
    >
      human review
    </span>
  ) : (
    <span
      style={{
        borderRadius: 999,
        border: `1px solid ${COLORS.ON_DARK_HAIRLINE}`,
        padding: "2px 9px",
        fontFamily: FONTS.MONO,
        fontSize: 8.5,
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.06em",
        color: COLORS.ON_DARK,
        whiteSpace: "nowrap",
      }}
    >
      {item.category.replace("_", " ")}
    </span>
  );

const GateMeter: React.FC<{ item: Row }> = ({ item }) => {
  const pct = Math.round(item.confidence * 100);
  const accent = item.needsReview ? COLORS.GATE_AMBER : LAYER_ACCENTS[item.fired]!;
  return (
    <div
      style={{
        marginTop: 10,
        paddingTop: 12,
        borderTop: `1px solid ${COLORS.ON_DARK_HAIRLINE}`,
      }}
    >
      <div
        style={{
          fontFamily: FONTS.MONO,
          fontSize: 9,
          color: COLORS.ON_DARK_MUTED,
          marginBottom: 8,
        }}
      >
        fired at layer {item.fired + 1} ·{" "}
        <span style={{ color: LAYER_ACCENTS[item.fired] }}>{LAYERS[item.fired]!.note}</span>
      </div>
      {/* meter */}
      <div
        style={{
          position: "relative",
          height: 8,
          borderRadius: 999,
          background: COLORS.GROUND_ELEVATED,
        }}
      >
        <div
          style={{
            position: "absolute",
            inset: "0 auto 0 0",
            width: `${pct}%`,
            borderRadius: 999,
            background: accent,
          }}
        />
        <div
          style={{
            position: "absolute",
            top: -4,
            bottom: -4,
            left: `${GATE * 100}%`,
            width: 1.5,
            background: COLORS.ON_DARK,
          }}
        />
      </div>
      {/* scale row — the gate label sits under the gate line itself, not at
          the row's centre */}
      <div
        style={{
          position: "relative",
          height: 12,
          fontFamily: FONTS.MONO,
          fontSize: 8,
          color: COLORS.ON_DARK_SUBTLE,
          marginTop: 4,
        }}
      >
        <span style={{ position: "absolute", left: 0 }}>0%</span>
        <span
          style={{
            position: "absolute",
            left: `${GATE * 100}%`,
            transform: "translateX(-50%)",
            color: COLORS.ON_DARK_MUTED,
            whiteSpace: "nowrap",
          }}
        >
          gate {GATE}
        </span>
        <span style={{ position: "absolute", right: 0 }}>100%</span>
      </div>
      <div
        style={{
          fontFamily: FONTS.MONO,
          fontSize: 8.5,
          lineHeight: 1.5,
          color: COLORS.ON_DARK_SUBTLE,
          marginTop: 8,
        }}
      >
        confidence sits below the 0.85 gate — nothing is auto-filed. the email
        waits for a human, and the correction becomes new SetFit training data.
      </div>
    </div>
  );
};
