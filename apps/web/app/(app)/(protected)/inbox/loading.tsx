/**
 * Instant pending state for /inbox — the view-switch strip and a run of
 * message-row plates, the same top-line geometry both loaded views render
 * (`page.tsx`), so the swap never reflows. A cold navigation here previously
 * answered the click with nothing until `GET /applications/mail` came back
 * (700–1150 ms of origin time, #203); the dashboard has had its skeleton
 * since #211. Warm navigations inside the 30 s router-cache window skip this.
 */
export default function InboxLoading() {
  return (
    <section aria-busy="true" aria-label="Loading inbox" className="relative space-y-4">
      {/* View switch left, privacy link right — the ViewSwitch row's shape. */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="h-8 w-40 animate-pulse rounded-lg bg-surface-2" />
        <div className="h-3 w-56 animate-pulse rounded bg-surface-2" />
      </div>
      {/* The filter chips row, then the list. */}
      <div className="flex gap-1.5">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-6 w-16 animate-pulse rounded-full bg-surface-2" />
        ))}
      </div>
      <div className="space-y-2">
        {Array.from({ length: 8 }).map((_, i) => (
          <div
            key={i}
            className="h-12 animate-pulse rounded-lg border border-line-soft bg-surface"
          />
        ))}
      </div>
    </section>
  );
}
