export default function DashboardLoading() {
  return (
    <section
      className="flex flex-col gap-3 lg:min-h-0 lg:flex-1"
      aria-busy="true"
      aria-label="Loading dashboard"
    >
      {/* Header: title + inline subtitle on one baseline, sync cluster right —
          the same single-line band the loaded SyncBar renders. */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-baseline gap-3">
          <div className="h-7 w-32 animate-pulse rounded-lg bg-surface-2" />
          <div className="h-3 w-56 animate-pulse rounded bg-surface-2" />
        </div>
        <div className="h-9 w-40 animate-pulse rounded-lg bg-surface-2" />
      </div>

      {/* No stand-in for the notification chip (#212): at `lg`+ it overlays
          the header row and costs no height, so the skeleton's geometry is
          already the loaded one's. */}

      {/* Spine (stages + pulse column) + worklist — the same geometry the
          loaded board renders into, so the swap from skeleton to rows never
          reflows the page. */}
      <div className="flex min-h-0 flex-1 gap-5">
        <div className="hidden w-52 shrink-0 flex-col gap-2 lg:flex">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-8 animate-pulse rounded-lg bg-surface-2" />
          ))}
          {/* The pulse's instrument column under the stage buttons. */}
          <div className="mt-2 h-64 animate-pulse rounded-lg bg-surface-2" />
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
