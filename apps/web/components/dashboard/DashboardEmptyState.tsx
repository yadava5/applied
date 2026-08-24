import Link from "next/link";
import { Mail, Upload, type LucideIcon } from "lucide-react";

import { AddApplicationForm } from "@/components/applications/AddApplicationForm";

const ROUTES: {
  href: string;
  title: string;
  body: string;
  icon: LucideIcon;
}[] = [
  {
    href: "/settings",
    title: "Connect Gmail",
    body: "Read-only. The classifier reads job mail at the source and files it for you.",
    icon: Mail,
  },
  {
    href: "/import",
    title: "Import your mail",
    body: "No connection, no sign-in — drop a Takeout export and classify it in your browser.",
    icon: Upload,
  },
];

/** The two ways to start filling the board with real mail. Reused by the empty
 * state and by the honest offline/unauthorized states so every no-board view
 * routes forward.
 *
 * There used to be a third card here — "Try the sample inbox", pointing at
 * `/demo/inbox`. It left with #495: the demo belongs to the public marketing
 * surface, and inside the signed-in app a route whose payload is invented mail
 * is an invitation to read fixtures as your own pipeline. */
export function ForwardRoutes() {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {ROUTES.map((route) => {
        const Icon = route.icon;
        return (
          <Link
            key={route.href}
            href={route.href}
            className="group rounded-xl border border-line bg-surface-2 p-4 transition-colors hover:border-line-strong"
          >
            <div className="flex items-center justify-between">
              <Icon
                className="h-4 w-4 text-muted transition-colors group-hover:text-strong"
                aria-hidden="true"
              />
              <span className="font-mono text-muted transition-transform group-hover:translate-x-0.5">
                →
              </span>
            </div>
            <p className="mt-3 text-sm font-medium text-strong">
              {route.title}
            </p>
            <p className="mt-1 text-[12px] leading-snug text-muted">
              {route.body}
            </p>
          </Link>
        );
      })}
    </div>
  );
}

/**
 * What the dashboard shows before anything is filed. Never a blank page: a
 * clear headline, the fastest first action (file one, or connect a source),
 * and the routes forward.
 *
 * It used to end with a `SamplePreview` — a fixture board rendered under a
 * "sample data · not yours" pill, so the empty state could still demonstrate
 * the product. #495 removed it: nothing inside the signed-in app is the demo.
 * A disclaimer is not a defence when the thing it disclaims is a full,
 * realistic pipeline sitting where the reader's own board goes; the
 * demonstration belongs to the landing page and the public `/demo/*` routes,
 * which is where it still lives.
 */
export function DashboardEmptyState({
  mode = "live",
}: {
  /** Where "file an application" writes. `demo` is for the fixture twin, which
   *  mounts this component itself so its geometry cannot drift from the
   *  signed-in page's — see `EmptyBoardBody`. A live form on an auth-free
   *  route would offer a control whose only outcome is an API error. */
  mode?: "live" | "demo";
}) {
  return (
    <div className="rounded-2xl border border-line-soft bg-surface p-6 sm:p-8">
      <p className="label-caps">nothing filed yet</p>
      <h2 className="mt-3 text-balance text-2xl font-medium tracking-tight text-strong">
        Your board is empty — let&apos;s fill it.
      </h2>
      <p className="mt-2 max-w-xl text-sm text-muted">
        File an application by hand, or connect a mail source and let the
        classifier build the board for you. Either way, everything below fills
        in as applications arrive.
      </p>
      <div className="mt-5">
        <AddApplicationForm align="start" mode={mode} />
      </div>

      <div className="mt-6">
        <ForwardRoutes />
      </div>
    </div>
  );
}
