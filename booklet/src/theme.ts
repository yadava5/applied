/**
 * Applied System Card — design tokens (self-contained).
 *
 * Unlike the sibling AutoML booklet (which re-exported COLORS/FONTS from a
 * `../../poster/src/tokens` workspace file), this booklet ships standalone:
 * every token is inlined here so `jobtracker/booklet` builds with no external
 * package. The palette is Applied's OWN identity — a dark-monochrome ink
 * ground with the four semantic classifier accents surfaced from the app:
 *
 *   RULES_CYAN   #38BDF8   Layer 1 · 219 regex rules
 *   E5_VIOLET    #A78BFA   Layer 2 · pretrained e5 embeddings (cosine similarity)
 *   SETFIT_GREEN #34D399   Layer 3 · SetFit few-shot head
 *   GATE_AMBER   #F59E0B   the 0.85 confidence gate · a human decides
 *
 * Bright accents ride on dark surfaces (cover, dividers, device panels);
 * the *_DEEP variants are their legible-on-white counterparts, used for
 * eyebrows / footers / rules on the light editorial pages.
 */

// ---------------------------------------------------------------------------
// Palette
// ---------------------------------------------------------------------------

export const COLORS = {
  // Paper (light content pages)
  PAPER: "#FFFFFF",
  PAPER_WARM: "#FBFCFD",
  PAPER_ELEVATED: "#F5F7FA",
  SURFACE: "#EDF1F6",

  // Hairlines
  HAIRLINE: "#CBD3DE",
  HAIRLINE_STRONG: "#94A3B8",

  // Ink (primary text + the dark full-bleed ground)
  INK: "#0B1220",
  INK_SOFT: "#131C2E",
  INK_MUTED: "rgba(11, 18, 32, 0.62)",
  INK_SUBTLE: "rgba(11, 18, 32, 0.38)",

  // On-dark inks (text over the #0B1220 ground)
  ON_DARK: "#F4F7FB",
  ON_DARK_MUTED: "rgba(244, 247, 251, 0.66)",
  ON_DARK_SUBTLE: "rgba(244, 247, 251, 0.40)",
  ON_DARK_HAIRLINE: "rgba(244, 247, 251, 0.16)",

  // Dark grounds — cover / dividers / device panels
  GROUND: "#0B1220",
  GROUND_ELEVATED: "#111A2B",
  GROUND_PANEL: "#0E1626",

  // ── Semantic classifier accents (bright — for dark surfaces) ──
  RULES_CYAN: "#38BDF8",
  E5_VIOLET: "#A78BFA",
  SETFIT_GREEN: "#34D399",
  GATE_AMBER: "#F59E0B",
  STEEL: "#94A3B8",
  // Security & Privacy chapter accent — a royal indigo that reads "trust /
  // lock" while staying inside the app's cool (cyan → violet) half of the
  // wheel. Distinct from the lighter E5 lavender on both dark and light.
  SECURITY_INDIGO: "#6366F1",

  // ── Deep variants (legible on white — for editorial pages) ──
  RULES_DEEP: "#0284C7",
  E5_DEEP: "#7C3AED",
  SETFIT_DEEP: "#059669",
  GATE_DEEP: "#B45309",
  STEEL_DEEP: "#475569",
  SECURITY_DEEP: "#4338CA",

  // ── Accent tints (fills, bands) ──
  RULES_TINT: "rgba(56, 189, 248, 0.10)",
  E5_TINT: "rgba(167, 139, 250, 0.10)",
  SETFIT_TINT: "rgba(52, 211, 153, 0.12)",
  GATE_TINT: "rgba(245, 158, 11, 0.12)",
  SECURITY_TINT: "rgba(99, 102, 241, 0.10)",

  // Status
  SUCCESS: "#059669",
  DANGER: "#DC2626",
  DANGER_TINT: "rgba(220, 38, 38, 0.08)",

  // Neutral scale
  NEUTRAL_300: "#D4D4D4",
  NEUTRAL_400: "#9CA3AF",
  NEUTRAL_500: "#6B7280",
  NEUTRAL_600: "#4B5563",
  NEUTRAL_700: "#374151",
} as const;

// ---------------------------------------------------------------------------
// Fonts — Instrument Serif + Plus Jakarta Sans + Monaspace Neon (mono).
// ---------------------------------------------------------------------------

export const FONTS = {
  SANS: '"Plus Jakarta Sans", ui-sans-serif, system-ui, sans-serif',
  SERIF: '"Instrument Serif", Georgia, "Times New Roman", serif',
  MONO: '"Monaspace Neon", ui-monospace, SFMono-Regular, Menlo, monospace',
} as const;

// ---------------------------------------------------------------------------
// Section color map — one accent per chapter. Bright variant rides the dark
// dividers + accent dots/bars; the *_INK map is the legible-on-white variant
// for content-page eyebrows and page-number footers.
//
//   01 WHY       amber   · the manual/human cost — "a person is doing this by hand"
//   02 HOW       cyan    · the cascade of rules
//   03 INSIDE    violet  · the embedding engine room + ONNX
//   04 PROOF     green   · the verdict / macro-F1
//   05 SECURITY  indigo  · least-privilege, on-device, no LLM (the trust story)
//   06 BUILD     steel   · the workshop (deliberately neutral)
// ---------------------------------------------------------------------------

export const SECTION = {
  "01_WHY": COLORS.GATE_AMBER,
  "02_HOW": COLORS.RULES_CYAN,
  "03_INSIDE": COLORS.E5_VIOLET,
  "04_PROOF": COLORS.SETFIT_GREEN,
  "05_SECURITY": COLORS.SECURITY_INDIGO,
  "06_BUILD": COLORS.STEEL,
} as const;

export const SECTION_INK = {
  "01_WHY": COLORS.GATE_DEEP,
  "02_HOW": COLORS.RULES_DEEP,
  "03_INSIDE": COLORS.E5_DEEP,
  "04_PROOF": COLORS.SETFIT_DEEP,
  "05_SECURITY": COLORS.SECURITY_DEEP,
  "06_BUILD": COLORS.STEEL_DEEP,
} as const;

export type SectionKey = keyof typeof SECTION;

// ---------------------------------------------------------------------------
// Typography — sized for a held-in-hand 8.5"×11" page. Ported from the AutoML
// booklet's proven ladder (px at 96 CSS DPI; printed pt = px ÷ 1.333).
// ---------------------------------------------------------------------------

export const TYPE = {
  // Display — cover title, divider numerals
  display: { size: 220, weight: 700, tracking: "-0.03em", lh: 0.92 },
  displayMedium: { size: 112, weight: 700, tracking: "-0.025em", lh: 1 },

  // Section title on divider pages (italic serif)
  sectionTitle: { size: 80, weight: 400, tracking: "0", lh: 1, italic: true },

  // Page headlines and subheads
  h1: { size: 36, weight: 700, tracking: "-0.02em", lh: 1.08 },
  h2: { size: 22, weight: 600, tracking: "-0.015em", lh: 1.2 },

  // Italic serif subheads
  subheadLarge: { size: 20, weight: 400, italic: true, lh: 1.2 },
  subheadMedium: { size: 18, weight: 400, italic: true, lh: 1.25 },
  subheadSmall: { size: 14, weight: 400, italic: true, lh: 1.3 },

  // Body
  body: { size: 11, weight: 400, tracking: "-0.005em", lh: 1.46 },

  // Pull quotes (serif italic)
  pullQuote: { size: 28, weight: 400, tracking: "0", lh: 1.25, italic: true },
  pullQuoteSmall: { size: 24, weight: 400, tracking: "0", lh: 1.25, italic: true },

  // Supporting
  caption: { size: 10, weight: 500, tracking: "0.02em", lh: 1.25 },
  mono: { size: 10, weight: 500, tracking: "0.04em", lh: 1.2 },
  pageNum: { size: 9, weight: 500, tracking: "0.04em", lh: 1 },

  // Monaspace UPPERCASE eyebrow
  eyebrow: { size: 10, weight: 500, tracking: "0.12em", lh: 1 },
  eyebrowLarge: { size: 14, weight: 500, tracking: "0.12em", lh: 1 },

  // Subtitle under divider number
  dividerSubtitle: { size: 24, weight: 400, tracking: "-0.01em", lh: 1.2 },

  // Small caps on gate callout
  approvalLabel: { size: 10, weight: 600, tracking: "0.18em", lh: 1 },

  // Metric tiers — the numeric voice (mono 700, tabular)
  metricHero: { size: 92, weight: 700, tracking: "-0.03em", lh: 0.95 },
  metricLarge: { size: 60, weight: 700, tracking: "-0.02em", lh: 1 },
  metricMedium: { size: 44, weight: 700, tracking: "-0.03em", lh: 1 },
  metricSmall: { size: 30, weight: 700, tracking: "-0.02em", lh: 1 },
} as const;

// ---------------------------------------------------------------------------
// Page geometry — 8.5"×11" trim, 0.125" bleed, asymmetric margins.
// ---------------------------------------------------------------------------

export const PAGE = {
  trimW: 8.5,
  trimH: 11,
  bleedIn: 0.125,
  margin: {
    outer: 0.75,
    top: 0.875,
    bottom: 1.0,
    inner: 0.75,
  },
  grid: {
    cols: 4,
    gutterIn: 0.25,
  },
} as const;

// ---------------------------------------------------------------------------
// Card chrome
// ---------------------------------------------------------------------------

export const CARD = {
  bg: COLORS.PAPER_ELEVATED,
  border: `1px solid ${COLORS.HAIRLINE}`,
  radius: 6,
  padding: 10,
} as const;

// ---------------------------------------------------------------------------
// Color utility — hex → rgba().
// ---------------------------------------------------------------------------

export function hexWithAlpha(hex: string, alpha: number): string {
  const cleaned = hex.replace("#", "");
  const r = parseInt(cleaned.slice(0, 2), 16);
  const g = parseInt(cleaned.slice(2, 4), 16);
  const b = parseInt(cleaned.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

// probe: booklet-only diff, to observe which workflows trigger. Reverted.
