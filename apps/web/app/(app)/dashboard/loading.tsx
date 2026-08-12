export default function DashboardLoading() {
  return (
    <section
      className="flex flex-col gap-4 lg:min-h-0 lg:flex-1"
      aria-busy="true"
      aria-label="Loading dashboard"
    >
      {/* Header: title + subtitle line, sync cluster */}
      <div className="flex items-end justify-between gap-3">
        <div className="space-y-2">
          <div className="h-7 w-32 animate-pulse rounded-lg bg-surface-2" />
          <div className="h-3 w-56 animate-pulse rounded bg-surface-2" />
        </div>
        <div className="h-9 w-40 animate-pulse rounded-lg bg-surface-2" />
      </div>

      {/* Spine + worklist — the same geometry the loaded board renders into,
          so the swap from skeleton to rows never reflows the page. */}
      <div className="flex min-h-0 flex-1 gap-5">
        <div className="hidden w-52 shrink-0 flex-col gap-2 lg:flex">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-10 animate-pulse rounded-lg bg-surface-2" />
          ))}
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-2 overflow-hidden">
          {Array.from({ length: 9 }).map((_, i) => (
            <div key={i} className="h-10 animate-pulse rounded-lg border border-line-soft bg-surface" />
          ))}
        </div>
      </div>
    </section>
  );
}
