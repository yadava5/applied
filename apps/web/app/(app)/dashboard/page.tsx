import { createServerApiClient } from "@/lib/api/server";
import type { components } from "@/lib/api/schema";
import { ApplicationsBoard } from "@/components/applications/ApplicationsBoard";
import { AddApplicationForm } from "@/components/applications/AddApplicationForm";

type Application = components["schemas"]["Application"];

/**
 * The signed-in product: the pipeline board driven by GET /applications,
 * with a filing form posting through the server-side proxy. Failure
 * modes stay first-class — an unreachable backend degrades to a labeled
 * state, never a crash (the shell above already guarantees auth).
 */
type LoadState =
  | { kind: "ok"; applications: Application[]; total: number }
  | { kind: "unauthorized"; message: string }
  | { kind: "offline"; message: string };

async function loadApplications(): Promise<LoadState> {
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.GET("/applications");
    if (error || !data) {
      return {
        kind: "unauthorized",
        message:
          typeof error === "object" && error && "detail" in error
            ? String((error as { detail: unknown }).detail)
            : `Backend responded ${response.status}`,
      };
    }
    return { kind: "ok", applications: data.applications, total: data.total };
  } catch (err) {
    return {
      kind: "offline",
      message: err instanceof Error ? err.message : "Unknown fetch error",
    };
  }
}

export default async function DashboardPage() {
  const state = await loadApplications();

  if (state.kind !== "ok") {
    return (
      <section className="space-y-4">
        <h1 className="text-2xl font-semibold tracking-tight text-strong">Pipeline</h1>
        <div
          className="rounded-xl border border-line-soft bg-surface p-4 font-mono text-sm text-muted"
          role="status"
        >
          {state.kind === "unauthorized"
            ? `The backend rejected the session: ${state.message}`
            : `The backend is unreachable — the board renders the moment it answers. (${state.message})`}
        </div>
      </section>
    );
  }

  const active = state.applications.filter((a) =>
    ["applied", "interviewing"].includes(a.status),
  ).length;
  const offers = state.applications.filter((a) =>
    ["offered", "accepted"].includes(a.status),
  ).length;

  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-strong">Pipeline</h1>
          <p className="mt-1 font-mono text-xs text-dim">
            {state.total} filed · {active} in motion · {offers} offer{offers === 1 ? "" : "s"}
          </p>
        </div>
        <AddApplicationForm />
      </header>

      {state.total === 0 ? (
        <div className="rounded-xl border border-dashed border-line-soft bg-surface p-8 text-center">
          <p className="text-strong">Nothing filed yet.</p>
          <p className="mt-1 text-sm text-muted">
            File your first application above — the board takes it from there.
          </p>
        </div>
      ) : (
        <ApplicationsBoard applications={state.applications} />
      )}
    </section>
  );
}
