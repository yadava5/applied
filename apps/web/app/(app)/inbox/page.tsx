import Link from "next/link";
import type { Metadata } from "next";

import { BetaCard } from "@/components/beta/BetaCard";
import { ConnectGmailButton } from "@/components/gmail/ConnectGmailButton";
import { InboxWorkbench } from "@/components/gmail/InboxWorkbench";
import { FiledMailList } from "@/components/mail/FiledMailList";
import { getMail } from "@/lib/applications/server";
import { getGmailStatus } from "@/lib/gmail/server";
import { FILED_PAGE_SIZE, readFiledMailPage } from "@/lib/mail/filed";
import { cn } from "@/lib/utils";

export const metadata: Metadata = {
  title: "Inbox",
  description:
    "Everything Applied has read and how it judged it — plus a live, read-only mine of your Gmail.",
};

/**
 * The mail section, in two views. This is where "where do I review the filed
 * mail?" is answered — with a PLACE, not a transient interrupt:
 *
 *   - **Filed** (default) — every message the sync has stored, whatever the
 *     classifier decided and wherever the message went: linked to a board
 *     row, resolved as noise, held for review, already reviewed. Each row
 *     shows the verdict (category, confidence against the gate) and carries a
 *     correction control, because the backend accepts a re-classification for
 *     any owned message — the needs-review queue was the only correction
 *     surface before, and it hides a verdict forever the moment it is
 *     touched.
 *   - **Live scan** — the existing workbench: a read-only, on-demand mine of
 *     the connected Gmail that can file what it finds. It reads Google, not
 *     the store, so it stays its own view rather than pretending to be a
 *     record.
 *
 * The Filed view is driven entirely by the URL (`category`, `q`, `page`), so
 * the chips and pager are links, a filter state is shareable, and the server
 * renders the truth on every visit — no client cache to go stale.
 */

type SearchParams = Promise<{
  view?: string;
  category?: string;
  q?: string;
  page?: string;
}>;

function ViewSwitch({ scan }: { scan: boolean }) {
  const tab = (active: boolean) =>
    cn(
      "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
      active ? "bg-strong text-background" : "text-muted hover:text-strong",
    );
  return (
    // The privacy link is STANDING on both views, not folded: Google's API
    // Services User Data Policy wants the policy "prominently displayed",
    // and this is the surface that displays what was read from Gmail. The
    // Gmail card carries the other standing copy, at the consent moment.
    // Nothing equivalent goes on the dashboard (decided).
    <div className="flex flex-wrap items-center justify-between gap-3">
      {/* `aria-current="true"`, not `"page"`. These tabs pick a VIEW within
          one page; the rail's Inbox item is the thing that names where you
          are in the site, and `"page"` may identify exactly one element in a
          document. Both said `"page"` until #163, so a screen reader on
          /inbox announced two current-page landmarks. `"true"` is what the
          filed-mail category chips below have used all along. */}
      <nav aria-label="Inbox views" className="inline-flex rounded-lg border border-line-soft bg-surface p-0.5">
        <Link href="/inbox" aria-current={!scan ? "true" : undefined} className={tab(!scan)}>
          Filed
        </Link>
        <Link
          href="/inbox?view=scan"
          aria-current={scan ? "true" : undefined}
          className={tab(scan)}
        >
          Live scan
        </Link>
      </nav>
      <Link
        href="/privacy"
        className="text-xs text-dim underline-offset-4 transition-colors hover:text-strong hover:underline"
      >
        how your mail is handled · privacy policy →
      </Link>
    </div>
  );
}

function ImportFallback() {
  return (
    <div className="rounded-xl border border-line-soft bg-surface p-5">
      <h2 className="text-base font-medium text-strong">See it on your own mail — right now</h2>
      <p className="mt-1.5 text-sm text-muted">
        No beta seat needed: export from Google Takeout (or one{" "}
        <span className="font-mono text-dim">.eml</span>) and classify it{" "}
        <span className="text-strong">entirely in your browser</span> — no upload, no OAuth.
      </p>
      <Link
        href="/import"
        className="mt-3 inline-flex items-center gap-2 rounded-lg border border-line px-4 py-2 text-sm text-foreground transition-colors hover:border-line-strong hover:text-strong"
      >
        Import your mail <span aria-hidden>→</span>
      </Link>
    </div>
  );
}

/** The scan view's non-connected states — connect, the beta seat, or the
 *  no-OAuth import path. Every branch routes forward; none is a dead end. */
function ScanFallback({ configured }: { configured: boolean }) {
  if (!configured) return <ImportFallback />;
  return (
    <>
      <div className="rounded-xl border border-line-soft bg-surface p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 className="text-base font-medium text-strong">Connect Gmail to scan live</h2>
            <p className="mt-1.5 text-sm text-muted">
              Read-only, on Google&apos;s own consent screen. The classifier labels your job-search
              mail — it <span className="text-strong">cannot</span> send, delete, or modify anything.
            </p>
          </div>
          <ConnectGmailButton className="shrink-0" />
        </div>
        <p className="mt-4 border-t border-line-soft pt-4 text-sm text-muted">
          The full scopes-and-safeguards breakdown lives in{" "}
          <Link href="/settings" className="text-strong underline-offset-4 hover:underline">
            Settings
          </Link>
          .
        </p>
      </div>
      <BetaCard />
      <ImportFallback />
    </>
  );
}

export default async function InboxPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const scan = params.view === "scan";

  // --- Live scan ------------------------------------------------------------
  if (scan) {
    const result = await getGmailStatus();
    const connected = result.kind === "ok" && result.status.configured && result.status.connected;
    return (
      <section className="space-y-5">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight text-strong">Inbox</h1>
          <p className="mt-1 text-[13px] text-muted">
            live scan · read-only mine of your Gmail · one verdict per message
          </p>
        </header>
        <ViewSwitch scan />
        {connected ? (
          <InboxWorkbench email={result.status.email} />
        ) : result.kind === "auth" ? (
          <div className="rounded-xl border border-line-soft bg-surface p-5">
            <p className="text-sm text-muted">
              Your session couldn&apos;t be verified for the mail backend
              {" "}(<span className="font-mono text-dim">{result.status}</span>).
            </p>
            <Link
              href="/login?redirect=/inbox"
              className="mt-3 inline-flex items-center gap-2 rounded-lg bg-strong px-4 py-2 text-sm font-medium text-background hover:opacity-90"
            >
              Sign in again <span aria-hidden>→</span>
            </Link>
          </div>
        ) : result.kind === "backend" ? (
          <div className="rounded-xl border border-line-soft bg-surface p-5 text-sm text-muted">
            The mail backend is temporarily unavailable — this view fills in the moment it answers.
          </div>
        ) : (
          <ScanFallback configured={result.kind === "ok" && result.status.configured} />
        )}
      </section>
    );
  }

  // --- Filed (default) --------------------------------------------------------
  const category = params.category?.trim() || null;
  const q = params.q?.trim() || null;
  const requested = Number(params.page);
  const pageNum = Number.isInteger(requested) && requested > 1 ? requested : 1;

  const search = new URLSearchParams();
  search.set("page", String(pageNum));
  search.set("page_size", String(FILED_PAGE_SIZE));
  if (category) search.set("category", category);
  if (q) search.set("q", q);
  const result = await getMail(search);
  const page = result.ok ? readFiledMailPage(result.data) : null;

  return (
    <section className="space-y-5">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-strong">Inbox</h1>
        <p className="mt-1 text-[13px] text-muted">
          {page
            ? `everything Applied has read · ${page.total} message${page.total === 1 ? "" : "s"}${
                category || q ? " in this view" : " stored"
              } · every verdict correctable`
            : "everything Applied has read, and how it judged it"}
        </p>
      </header>
      <ViewSwitch scan={false} />
      {page ? (
        <FiledMailList page={page} activeCategory={category} q={q} />
      ) : (
        // Honest failure — never an empty inbox that reads as "no mail". The
        // distinct next step per status mirrors the dashboard's rule.
        <div role="alert" className="rounded-xl border border-reject/40 bg-surface p-6">
          <p className="label-caps text-reject-ink">couldn&apos;t load</p>
          <h2 className="mt-2 text-base font-medium text-strong">
            Your stored mail didn&apos;t load.
          </h2>
          <p className="mt-1.5 text-sm text-muted">
            {result.status === 401 || result.status === 403
              ? "The backend rejected this session — signing in again usually clears it."
              : `The backend answered ${result.status}. Nothing is lost — the list renders the moment it responds.`}
          </p>
          {result.status === 401 || result.status === 403 ? (
            <Link
              href="/login?redirect=/inbox"
              className="mt-3 inline-block text-xs text-dim underline-offset-4 hover:text-strong hover:underline"
            >
              sign in again →
            </Link>
          ) : null}
        </div>
      )}
    </section>
  );
}
