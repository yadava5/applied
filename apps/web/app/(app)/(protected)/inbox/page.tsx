import Link from "next/link";
import type { Metadata } from "next";

import { BetaCard } from "@/components/beta/BetaCard";
import { ConnectGmailButton } from "@/components/gmail/ConnectGmailButton";
import { InboxWorkbench } from "@/components/gmail/InboxWorkbench";
import { FiledMailList } from "@/components/mail/FiledMailList";
import {
  LOCKED_BODY_CLASS,
  LOCKED_PAGE_CLASS,
} from "@/components/shell/geometry";
import { PageHeader } from "@/components/shell/PageHeader";
import { getBoardPage, getMail } from "@/lib/applications/server";
import { BOARD_PAGE_SIZE } from "@/lib/dashboard/boardPage";
import type { CandidateApplication } from "@/lib/dashboard/review";
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
 *
 * GEOMETRY (#197). Both views opt into the shell's locked-page contract
 * (`LOCKED_PAGE_CLASS`, see `components/shell/geometry.ts`): the page fills
 * the pane, the view switch and the filter plates hold still, and ONLY the
 * message list scrolls. Below `lg` the lock releases by the contract's own
 * design — a phone's one content pane should not hide behind a nested
 * scroller — and the page flows in <main> as before.
 *
 * HEADING (#197). The rail names this place, so the page renders no visible
 * title of its own — the third copy, plus its subtitle, was the complaint. One
 * `sr-only` <h1> keeps the document outline for assistive tech; the stored-
 * message count survives as the filter row's "all N" chip, where it is a
 * control rather than prose. The top bar used to print "Inbox" beside the menu
 * at every width; above `lg` it yields entirely now (see `PageHeader`), so the
 * lit rail item is the only thing that names the place there. Below `lg`, where
 * the rail is hidden, the bar and its label are still what say where you are.
 */

type SearchParams = Promise<{
  view?: string;
  category?: string;
  q?: string;
  page?: string;
}>;

/**
 * The page's header line — the view switch, the standing privacy link, and (at
 * `lg`+, via `PageHeader`) the session edge.
 *
 * These are the inbox's own CONTROLS, which is the whole test for what may sit
 * on a header row here: the counts a header could otherwise print already exist
 * one plate down as `FiledMailList`'s category chips, where they are filters
 * rather than prose, and the route's name already exists in the lit rail item.
 * Promoting either would be the restatement #196/#197/#199 removed. The switch
 * is navigation WITHIN the page, so this is where it belongs.
 */
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
    //
    // `justify-between` inside `PageHeader`'s `flex-1` slot puts the switch on
    // the left and the privacy link against the `⋯` menu on the right — the
    // board's own arrangement (state left, controls right, session edge last).
    <div className="flex flex-wrap items-center justify-between gap-3">
      {/* `aria-current="true"`, not `"page"`. These tabs pick a VIEW within
          one page; the rail's Inbox item is the thing that names where you
          are in the site, and `"page"` may identify exactly one element in a
          document. Both said `"page"` until #163, so a screen reader on
          /inbox announced two current-page landmarks. `"true"` is what the
          filed-mail category chips below have used all along. */}
      <nav
        aria-label="Inbox views"
        className="inline-flex rounded-lg border border-line-soft bg-surface p-0.5"
      >
        <Link
          href="/inbox"
          aria-current={!scan ? "true" : undefined}
          className={tab(!scan)}
        >
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
      <h2 className="text-base font-medium text-strong">
        See it on your own mail — right now
      </h2>
      {/* How-to only — the no-upload reassurance prose moved to the policy the
          standing /privacy link reaches (#200/#201). */}
      <p className="mt-1.5 text-sm text-muted">
        No beta seat needed: export from Google Takeout (or one{" "}
        <span className="font-mono text-dim">.eml</span>) and classify it here.
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

/**
 * THE SCROLL REGION IS PART OF THE LOCK, not decoration on it.
 *
 * This page's root declares `LOCKED_PAGE_CLASS`, which makes the root FILL the
 * shell pane — and that is only half of it. Something inside still has to be
 * the thing that moves, or a body taller than the pane pushes back out through
 * <main> and the whole page scrolls, sync chrome and all, with the lock
 * nominally on. The connected branch satisfies that with `InboxWorkbench`,
 * which owns its own scroller. THESE branches did not: three stacked cards and
 * two error cards, all of them ordinary flow content under a root that had
 * stopped growing.
 *
 * Which made this the not-connected scan view — the first place someone on a
 * fresh account goes looking for their mail — and it was carrying the same
 * half-lock the empty dashboard was carrying (#505). Found while fixing that
 * one, and it is the same one-line shape: give the body the region.
 */
function ScanBody({ children }: { children: React.ReactNode }) {
  return (
    <div className={cn(LOCKED_BODY_CLASS, "flex flex-col gap-3")}>
      {children}
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
        {/* The scopes/read-only reassurance paragraph is gone (#200): the
            consent moment carries it (Gmail card + Google's own screen), and
            the standing /privacy link above is the durable copy. */}
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h2 className="text-base font-medium text-strong">
            Connect Gmail to scan live
          </h2>
          <ConnectGmailButton className="shrink-0" />
        </div>
        <p className="mt-4 border-t border-line-soft pt-4 text-sm text-muted">
          The full scopes-and-safeguards breakdown lives in{" "}
          <Link
            href="/settings"
            className="text-strong underline-offset-4 hover:underline"
          >
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

/**
 * The board slice the row corrections' picker needs, read defensively.
 *
 * Only four fields, and any row missing one of them is dropped rather than
 * rendered as a blank option: an option a reader cannot tell apart from
 * another is not an answer to "which application is this about?".
 */
function readBoardCandidates(data: unknown): CandidateApplication[] {
  const rows = (data as { applications?: unknown })?.applications;
  if (!Array.isArray(rows)) return [];
  const out: CandidateApplication[] = [];
  for (const raw of rows) {
    const row = raw as Record<string, unknown>;
    if (typeof row?.id !== "number" || typeof row?.company !== "string") continue;
    out.push({
      id: row.id,
      company: row.company,
      position: typeof row.position === "string" ? row.position : "",
      status: typeof row.status === "string" ? row.status : "",
    });
  }
  return out;
}

export default async function InboxPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const scan = params.view === "scan";

  // --- Live scan ------------------------------------------------------------
  if (scan) {
    const result = await getGmailStatus();
    const connected =
      result.kind === "ok" &&
      result.status.configured &&
      result.status.connected;
    return (
      <section className={cn("relative", LOCKED_PAGE_CLASS)}>
        {/* The page's ONE heading, for the document outline only — the rail
            and the top bar already name this place (#197). `sr-only` is
            `position: absolute`, so the root is `relative`: the containing
            block that keeps the 1×1 box inside the pane's own scroll math
            (the escaped-`sr-only` document-scroll family, #149). */}
        <h1 className="sr-only">Inbox</h1>
        <PageHeader>
          <ViewSwitch scan />
        </PageHeader>
        {connected ? (
          <InboxWorkbench email={result.status.email} />
        ) : result.kind === "auth" ? (
          <ScanBody>
            <div className="rounded-xl border border-line-soft bg-surface p-5">
              <p className="text-sm text-muted">
                Your session couldn&apos;t be verified for the mail backend (
                <span className="font-mono text-dim">{result.status}</span>).
              </p>
              <Link
                href="/login?redirect=/inbox"
                className="mt-3 inline-flex items-center gap-2 rounded-lg bg-strong px-4 py-2 text-sm font-medium text-background hover:opacity-90"
              >
                Sign in again <span aria-hidden>→</span>
              </Link>
            </div>
          </ScanBody>
        ) : result.kind === "backend" ? (
          <ScanBody>
            <div className="rounded-xl border border-line-soft bg-surface p-5 text-sm text-muted">
              The mail backend is temporarily unavailable — this view fills in
              the moment it answers.
            </div>
          </ScanBody>
        ) : (
          <ScanBody>
            <ScanFallback
              configured={result.kind === "ok" && result.status.configured}
            />
          </ScanBody>
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
  // IN PARALLEL, not in series. The board is only needed to ask each row's
  // correction "which application is this about?" (#560), and a question the
  // reader may never open must not add a second ~850 ms backend wait to the
  // page they did open. Issue #203 measured concurrency, not idleness, as what
  // triggers a cold start; this takes /inbox's fan-out from 1 to 2.
  //
  // THE CANDIDATE POOL IS ONE PAGE — `BOARD_PAGE_SIZE` (200) ROWS — AND THAT
  // IS A STATED LIMIT, not an oversight. Past 200 applications the newest rows
  // fall off this page, so an employer whose siblings sit beyond it can show
  // fewer than two candidates here; the question is then not asked and the
  // backend's tie-break files the correction on that employer's oldest live
  // row — #560's behaviour, with no signal on screen.
  //
  // It is not fixed by raising the number, which only moves the cliff, and the
  // honest fix is server-side: the endpoint knows the employer token already
  // (`employer_token` below) and could return that employer's rows instead of
  // a page of the board. That is a bigger change than this one and is not
  // smuggled in here. The number is deliberately the SAME constant the
  // dashboard reads, so the question can only ever offer rows the reader can
  // also see on their board.
  const [result, boardResult] = await Promise.all([
    getMail(search),
    getBoardPage(BOARD_PAGE_SIZE),
  ]);
  const page = result.ok ? readFiledMailPage(result.data) : null;
  // A board that did not load costs the QUESTION, never the ledger: the rows
  // still render and still correct, they just cannot be asked which
  // application they are about — which is exactly how this page behaved before
  // #560. Read structurally rather than through the generated schema, for the
  // same reason `readFiledMailPage` does: a shape the backend changes should
  // degrade to "no candidates", not throw on a page of mail.
  const board: CandidateApplication[] = boardResult.ok
    ? readBoardCandidates(boardResult.data)
    : [];

  return (
    <section className={cn("relative", LOCKED_PAGE_CLASS)}>
      {/* Same one-heading + containment arrangement as the scan view above. */}
      <h1 className="sr-only">Inbox</h1>
      <PageHeader>
        <ViewSwitch scan={false} />
      </PageHeader>
      {page ? (
        <FiledMailList page={page} activeCategory={category} q={q} board={board} />
      ) : (
        // Honest failure — never an empty inbox that reads as "no mail". The
        // distinct next step per status mirrors the dashboard's rule.
        <div
          role="alert"
          className="rounded-xl border border-reject/40 bg-surface p-6"
        >
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
