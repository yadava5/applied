export default function DashboardLoading() {
  return (
    <section className="space-y-6" aria-busy="true">
      <div className="h-8 w-40 animate-pulse rounded-lg bg-surface-2" />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-48 animate-pulse rounded-xl border border-line-soft bg-surface" />
        ))}
      </div>
    </section>
  );
}
