import Link from "next/link";
import { Inbox, Mail, Upload, type LucideIcon } from "lucide-react";

import { AddApplicationForm } from "@/components/applications/AddApplicationForm";
import { PipelineBoard } from "@/components/dashboard/PipelineBoard";
import { DEMO_APPLICATIONS_AS_API } from "@/lib/demo/asApplications";
import { summarize } from "@/lib/dashboard/summary";

const ROUTES: { href: string; title: string; body: string; icon: LucideIcon }[] = [
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
  {
    href: "/demo/inbox",
    title: "Try the sample inbox",
    body: "Watch the real classifier label a set of job emails, gate and trace included.",
    icon: Inbox,
  },
];

/** The three ways to start filling the board. Reused by the empty state and by
 * the honest offline/unauthorized states so every no-board view routes forward. */
export function ForwardRoutes() {
  return (
    <div className="grid gap-3 sm:grid-cols-3">
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
            <p className="mt-3 text-sm font-medium text-strong">{route.title}</p>
            <p className="mt-1 text-[12px] leading-snug text-muted">{route.body}</p>
          </Link>
        );
      })}
    </div>
  );
}

/**
 * A labelled preview built from sample data. Clearly tagged "not yours" and
 * inert, it lets any no-board state still demonstrate exactly what a populated
 * dashboard looks like.
 */
export function SamplePreview() {
  const summary = summarize(DEMO_APPLICATIONS_AS_API);

  return (
    <section aria-label="Sample dashboard preview" className="space-y-4">
      {/* The "not yours" disclaimer is the only thing standing between a
          fixture board and a user reading it as their own pipeline, so it is
          sized and contrasted to be READ: text-strong on a raised surface with
          a strong border, not a 10px dim whisper. Same mono/uppercase language
          as the rest of the labels. */}
      <div className="flex items-center gap-3">
        <span className="label-mono">preview</span>
        <span className="rounded-full border border-line-strong bg-surface-2 px-2.5 py-1 font-mono text-[11px] font-medium uppercase tracking-wider text-strong">
          sample data · not yours
        </span>
        <span className="h-px flex-1 bg-line-soft" aria-hidden="true" />
      </div>
      {/* The board IS the preview — the same subtitle-plus-board hierarchy the
          real dashboard has, so the sample demonstrates the product it mirrors
          (no tiles, no funnel: those left the dashboard too). */}
      <div className="pointer-events-none select-none space-y-4 opacity-70">
        <p className="font-mono text-xs text-dim">
          {summary.total} filed · {summary.inMotion} in motion · {summary.offers} offer
          {summary.offers === 1 ? "" : "s"}
        </p>
        <PipelineBoard applications={DEMO_APPLICATIONS_AS_API} interactive={false} />
      </div>
    </section>
  );
}

/**
 * What the dashboard shows before anything is filed. Never a blank page: a
 * clear headline, the fastest first action (file one, or connect a source),
 * three routes forward, and a labelled sample preview so the empty state still
 * demonstrates the product.
 */
export function DashboardEmptyState() {
  return (
    <div className="space-y-8">
      <div className="rounded-2xl border border-line-soft bg-surface p-6 sm:p-8">
        <p className="label-mono">nothing filed yet</p>
        <h2 className="mt-3 text-balance text-2xl font-medium tracking-tight text-strong">
          Your pipeline is empty — let&apos;s fill it.
        </h2>
        <p className="mt-2 max-w-xl text-sm text-muted">
          File an application by hand, or connect a mail source and let the classifier build the
          board for you. Either way, everything below fills in as applications arrive.
        </p>
        <div className="mt-5">
          <AddApplicationForm align="start" />
        </div>

        <div className="mt-6">
          <ForwardRoutes />
        </div>
      </div>

      <SamplePreview />
    </div>
  );
}
