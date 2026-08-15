import type { CSSProperties } from "react";

/**
 * Instant pending state for /settings — the Triage boot's quiet form at the
 * same rail + capped-cards geometry the loaded page renders (`page.tsx`), so
 * the swap to real sections never reflows. Settings holds no mail rows, so
 * the classify signal is abstracted here: attention travels the cards as a
 * staggered hairline border lift (`boot-quiet-card`) rather than inventing
 * envelopes the content will never show. Before this surface existed, a cold
 * navigation answered a click with NOTHING for the whole origin wait
 * (700–1150 ms measured, #203).
 */
export default function SettingsLoading() {
  return (
    <section
      aria-busy="true"
      aria-label="Loading settings"
      className="boot-quiet relative space-y-6"
    >
      {/* The PageHeader band (#297): childless here, so it is lg-only — just
          the ⋯ session menu's square on the right, at the loaded row's 36px. */}
      <div className="hidden justify-end lg:flex">
        <div className="h-9 w-9 rounded-lg border border-line" />
      </div>
      <div className="lg:grid lg:grid-cols-[10rem_minmax(0,48rem)] lg:gap-8">
        {/* The section rail's column — sized like `SettingsNav`, links elided. */}
        <div className="hidden lg:block">
          <div className="space-y-3 pt-1">
            {Array.from({ length: 7 }).map((_, i) => (
              <div key={i} className="h-3.5 w-20 rounded border border-line" />
            ))}
          </div>
        </div>
        <div className="max-w-3xl space-y-6 lg:max-w-none">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="boot-quiet-card rounded-xl border border-line-soft p-5"
              style={{ "--i": i } as CSSProperties}
            >
              <div className="h-5 w-28 rounded border border-line-strong" />
              <div className="mt-4 h-4 w-full max-w-sm rounded border border-line" />
              <div className="mt-2 h-4 w-48 rounded border border-line" />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
