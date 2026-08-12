"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { Logo } from "@/components/brand/Logo";
import { PipelinePulse } from "@/components/dashboard/PipelinePulse";
import { cn } from "@/lib/utils";
import type { RailData } from "@/lib/shell/rail";
import { isNavItemActive, navItems } from "./nav";
import { RailFooter } from "./RailFooter";
import { RailPipeline } from "./RailPipeline";

/**
 * Desktop primary navigation, redesigned as a full-height data rail (hidden
 * below `md`; the mobile menu in `TopBar` takes over there).
 *
 * Top to bottom: the Applied lockup, the four nav items, the instrument
 * column — a live pipeline snapshot (`RailPipeline`: total + stage
 * distribution) with the pulse's four derived signals stacked beneath it
 * (`PipelinePulse layout="rail"`: momentum, ageing, deadlines, classifier) —
 * then, anchored to the viewport bottom via the sticky full-height column,
 * one identity block: who is signed in, with the Gmail connection state as a
 * subordinate line beneath it (`RailFooter`, which explains why those two
 * chips became one). The rail is `sticky top-0 h-dvh`, so it stays in view
 * while long pages scroll and the footer genuinely anchors; the middle
 * section scrolls internally on short viewports so the footer is never
 * pushed out of reach.
 *
 * The pulse moved here FROM the dashboard (it used to render inside the
 * board's stage spine, plus a display-none twin under the list below `lg`):
 * the rail had the empty vertical run, the dashboard needed the room for the
 * worklist, and ambient instrumentation belongs to the chrome that renders
 * on every tab. One copy now exists in the tree, full stop — below `md` the
 * rail collapses and the pulse goes with it, deliberately (see the pulse's
 * own doc block for the phone reasoning).
 *
 * The item matching the current route keeps its clear active treatment — a
 * cyan accent bar, a lit icon, a raised surface, and `aria-current="page"`.
 * Micro-interactions: icons nudge right on hover (motion-safe only) and every
 * interactive element carries a visible cyan focus ring for keyboard users.
 *
 * `rail` is assembled server-side by `lib/shell/rail` (type-only import here,
 * erased at compile time) — this component just renders what it is handed.
 */

type SidebarProps = {
  rail: RailData;
  userEmail: string | null;
};

export function Sidebar({ rail, userEmail }: SidebarProps) {
  const pathname = usePathname();

  return (
    <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-line-soft bg-surface md:flex">
      <div className="px-4 py-4">
        <Link
          href="/dashboard"
          aria-label="Applied — go to dashboard"
          className="brand-logo-link rounded-md text-strong focus-accent"
        >
          <Logo className="h-7 w-auto" />
        </Link>
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto pb-4">
        <nav className="px-2" aria-label="Primary">
          <ul className="space-y-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const active = isNavItemActive(pathname, item.href);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "group relative flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors focus-accent",
                      active
                        ? "bg-surface-2 text-strong"
                        : "text-muted hover:bg-surface-2 hover:text-strong",
                    )}
                  >
                    {active ? (
                      <span
                        aria-hidden="true"
                        className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-viz-rules"
                      />
                    ) : null}
                    <Icon
                      className={cn(
                        "h-4 w-4 transition-transform motion-safe:group-hover:translate-x-0.5",
                        active && "text-viz-rules",
                      )}
                      aria-hidden="true"
                    />
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        {/* The instrument column renders on EVERY tab, including /dashboard.
            It briefly yielded there (a miniature of the board beside itself),
            but the cost was a rail that changed shape as you navigated —
            chrome must be constant, and the instruments are the rail's
            identity, not page content. The overlap with the board's spine is
            accepted, on purpose.

            `px-5` puts the column's text on the nav labels' own left edge
            (nav px-2 + item px-3). The pulse only mounts when its rows
            loaded AND there is something to say — a fresh account's rail
            stays quiet (four signals of zero would be onboarding noise), but
            held mail alone is enough, because the classifier signal owns the
            "N held under the gate" link and zero *filed* can still mean work
            waiting. */}
        <div className="mt-5 flex flex-col gap-3 px-5">
          <RailPipeline pipeline={rail.pipeline} />
          {rail.pipeline?.pulseRows &&
          (rail.pipeline.summary.total > 0 || rail.pipeline.needsReview > 0) ? (
            <PipelinePulse
              layout="rail"
              applications={rail.pipeline.pulseRows}
              total={rail.pipeline.summary.total}
              needsReview={rail.pipeline.needsReview}
            />
          ) : null}
        </div>
      </div>

      <div className="shrink-0 border-t border-line-soft px-3 py-3">
        <RailFooter gmail={rail.gmail} userEmail={userEmail} />
      </div>
    </aside>
  );
}
