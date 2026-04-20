import { createServerApiClient } from "@/lib/api/server";

/**
 * Dashboard smoke screen.
 *
 * Intentionally minimal for C10: we make one server-side, typed fetch to
 * `GET /auth/me` to prove the API client is wired up. Real dashboard
 * widgets (pipeline totals, recent emails, follow-up reminders) land in
 * C13 once the backend endpoints for them exist.
 *
 * The fetch is wrapped in try/catch so a backend outage renders a
 * "Backend offline" placeholder rather than crashing the RSC — the
 * protected shell above us has already confirmed the user is signed in,
 * so the UX shouldn't degrade into a redirect loop if the backend is
 * momentarily unreachable.
 */
type AuthMeState =
  | { kind: "ok"; userId: string }
  | { kind: "unauthorized"; message: string }
  | { kind: "offline"; message: string };

async function loadAuthMe(): Promise<AuthMeState> {
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.GET("/auth/me");

    if (error || !data) {
      return {
        kind: "unauthorized",
        message:
          typeof error === "object" && error && "detail" in error
            ? String((error as { detail: unknown }).detail)
            : `Backend responded ${response.status}`,
      };
    }

    return { kind: "ok", userId: data.user_id };
  } catch (err) {
    return {
      kind: "offline",
      message: err instanceof Error ? err.message : "Unknown fetch error",
    };
  }
}

export default async function DashboardPage() {
  const authMe = await loadAuthMe();

  return (
    <section className="space-y-4">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          Your JobTracker pipeline will show up here once the backend API
          integration lands. For now this is an empty placeholder served by
          the authenticated shell.
        </p>
      </header>

      <div
        className="rounded-md border border-neutral-200 p-3 text-sm dark:border-neutral-800"
        data-testid="auth-me-smoke"
      >
        {authMe.kind === "ok" ? (
          <p>
            <span className="font-medium">Backend reachable.</span>{" "}
            <code className="font-mono text-xs">user_id={authMe.userId}</code>
          </p>
        ) : authMe.kind === "unauthorized" ? (
          <p className="text-amber-700 dark:text-amber-400">
            Backend reachable, but the session token was rejected:{" "}
            {authMe.message}
          </p>
        ) : (
          <p className="text-neutral-500 dark:text-neutral-400">
            Backend offline — dashboard will populate once{" "}
            <code className="font-mono text-xs">BACKEND_API_URL</code> is
            reachable. ({authMe.message})
          </p>
        )}
      </div>
    </section>
  );
}
