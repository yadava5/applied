import { Activity, CalendarPlus, Layers, Trophy, type LucideIcon } from "lucide-react";

import { AUTO_FILE_GATE, CI_FLOOR, MACRO_F1 } from "@/lib/dashboard/model";
import type { PipelineSummary } from "@/lib/dashboard/summary";

type Tile = {
  key: string;
  label: string;
  value: number;
  sub: string;
  icon: LucideIcon;
  /** CSS colour for the number; defaults to strong text. */
  accent?: string;
};

/**
 * The headline metric row. Presentational and prop-driven — the same tiles
 * render for real API rows and for the demo's fixture rows, so what a visitor
 * sees on `/demo` is exactly what a signed-in user sees on their dashboard.
 */
export function StatTiles({ summary }: { summary: PipelineSummary }) {
  const tiles: Tile[] = [
    {
      key: "total",
      label: "applications",
      value: summary.total,
      sub: "in your pipeline",
      icon: Layers,
    },
    {
      key: "week",
      label: "this week",
      value: summary.thisWeek,
      sub: "filed in the last 7 days",
      icon: CalendarPlus,
    },
    {
      key: "motion",
      label: "in motion",
      value: summary.inMotion,
      sub: "applied + interviewing",
      icon: Activity,
      accent: "var(--viz-embeddings)",
    },
    {
      key: "offers",
      label: "offers",
      value: summary.offers,
      sub: "offered + accepted",
      icon: Trophy,
      accent: "var(--green)",
    },
  ];

  return (
    <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {tiles.map((tile) => {
        const Icon = tile.icon;
        return (
          <div
            key={tile.key}
            className="rounded-xl border border-line-soft bg-surface p-4 transition-colors hover:border-line"
          >
            <div className="flex items-center justify-between">
              <dt className="label-mono">{tile.label}</dt>
              <Icon className="h-4 w-4 text-dim" aria-hidden="true" />
            </div>
            <dd
              className="tabular mt-2 font-mono text-3xl font-semibold leading-none"
              style={{ color: tile.accent ?? "var(--text-strong)" }}
            >
              {tile.value}
            </dd>
            <p className="mt-1.5 text-[11px] leading-tight text-dim">{tile.sub}</p>
          </div>
        );
      })}
    </dl>
  );
}

/**
 * The classifier-context strip — the honest, code-verified numbers that govern
 * how mail becomes pipeline: the 0.85 auto-file gate, the measured macro-F1,
 * and the CI floor that blocks a regression from ever shipping.
 */
export function ClassifierContext({ gate = AUTO_FILE_GATE }: { gate?: number }) {
  const items: { k: string; v: string; hint: string }[] = [
    { k: "auto-file gate", v: gate.toFixed(2), hint: "below this, a human decides" },
    { k: "macro-F1", v: MACRO_F1.toFixed(3), hint: "measured · hybrid v3" },
    { k: "CI floor", v: `≥ ${CI_FLOOR.toFixed(2)}`, hint: "merges fail below it" },
  ];
  return (
    <div className="grid grid-cols-3 overflow-hidden rounded-xl border border-line-soft bg-surface">
      {items.map((item, i) => (
        <div
          key={item.k}
          className={`p-4 ${i < items.length - 1 ? "border-r border-line-soft" : ""}`}
        >
          <p className="label-mono">{item.k}</p>
          <p className="tabular mt-1 font-mono text-lg font-semibold text-strong">{item.v}</p>
          <p className="mt-0.5 hidden text-[11px] leading-tight text-dim sm:block">{item.hint}</p>
        </div>
      ))}
    </div>
  );
}
