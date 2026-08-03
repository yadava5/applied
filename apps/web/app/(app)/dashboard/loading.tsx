export default function DashboardLoading() {
  return (
    <section className="space-y-6" aria-busy="true" aria-label="Loading dashboard">
      <div className="flex items-end justify-between gap-3">
        <div className="space-y-2">
          <div className="h-7 w-32 animate-pulse rounded-lg bg-surface-2" />
          <div className="h-3 w-48 animate-pulse rounded bg-surface-2" />
        </div>
        <div className="h-9 w-40 animate-pulse rounded-lg bg-surface-2" />
      </div>

      {/* Stat tiles */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-24 animate-pulse rounded-xl border border-line-soft bg-surface" />
        ))}
      </div>

      {/* Funnel */}
      <div className="h-40 animate-pulse rounded-xl border border-line-soft bg-surface" />

      {/* Board */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-48 animate-pulse rounded-xl border border-line-soft bg-surface" />
        ))}
      </div>
    </section>
  );
}
