/**
 * Instant pending state for /settings — the same rail + capped-cards geometry
 * the loaded page renders (`page.tsx`), so the swap to real sections never
 * reflows. Before this existed, a cold navigation to Settings answered a
 * click with NOTHING for the whole origin wait (700–1150 ms measured, #203);
 * the dashboard has had its equivalent since #211. Warm navigations inside
 * the 30 s router-cache window never show this at all.
 */
export default function SettingsLoading() {
  return (
    <section aria-busy="true" aria-label="Loading settings" className="relative space-y-6">
      <div className="lg:grid lg:grid-cols-[10rem_minmax(0,48rem)] lg:gap-8">
        {/* The section rail's column — sized like `SettingsNav`, links elided. */}
        <div className="hidden lg:block">
          <div className="space-y-3 pt-1">
            {Array.from({ length: 7 }).map((_, i) => (
              <div key={i} className="h-3.5 w-20 animate-pulse rounded bg-surface-2" />
            ))}
          </div>
        </div>
        <div className="max-w-3xl space-y-6 lg:max-w-none">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="rounded-xl border border-line-soft bg-surface p-5">
              <div className="h-5 w-28 animate-pulse rounded bg-surface-2" />
              <div className="mt-4 h-4 w-full max-w-sm animate-pulse rounded bg-surface-2" />
              <div className="mt-2 h-4 w-48 animate-pulse rounded bg-surface-2" />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
