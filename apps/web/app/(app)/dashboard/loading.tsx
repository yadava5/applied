export default function DashboardLoading() {
  return (
    <section className="space-y-6" aria-busy="true" aria-label="Loading dashboard">
      {/* Header: title + subtitle line, sync cluster */}
      <div className="flex items-end justify-between gap-3">
        <div className="space-y-2">
          <div className="h-7 w-32 animate-pulse rounded-lg bg-surface-2" />
          <div className="h-3 w-56 animate-pulse rounded bg-surface-2" />
        </div>
        <div className="h-9 w-40 animate-pulse rounded-lg bg-surface-2" />
      </div>

      {/* Board columns — the page's one big block now (no tiles, no funnel) */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-64 animate-pulse rounded-xl border border-line-soft bg-surface" />
        ))}
      </div>
    </section>
  );
}
