import { Search } from "lucide-react";
import Link from "next/link";

import { MailSnippet, OpenInGmail } from "@/components/mail/MailPreview";
import { ReclassifyControl } from "@/components/mail/ReclassifyControl";
import { GateMeter } from "@/components/viz/GateMeter";
import { shortDate } from "@/lib/dashboard/dates";
import { categoryChips, CATEGORY_META, chipTotal } from "@/lib/gmail/types";
import { filedMailHref, filedPageCount, type FiledMailPage } from "@/lib/mail/filed";
import { cn } from "@/lib/utils";

/**
 * The filed-mail ledger — every message Applied has stored, whatever the
 * verdict, wherever it went. Server-rendered from `GET /applications/mail`
 * and driven entirely by the URL (category chips are links, search is a GET
 * form, the pager is links), so a filter state is shareable and the back
 * button works; the only client islands are the per-row corrections.
 *
 * This is the surface the review queue could never be: the queue filters to
 * `needs_review AND unlinked AND unreviewed`, so a verdict left it forever the
 * moment it was touched — the product could display a wrong verdict it would
 * never let you fix (messages 58/59 in production are exactly that state).
 * Here every row carries `ReclassifyControl`, and the backend accepts a
 * correction for any owned message, so a verdict stays correctable for as
 * long as it exists.
 *
 * GEOMETRY (#197). The page root declares `LOCKED_PAGE_CLASS`, so at `lg`+
 * this component is a flex column inside a fixed-height pane: the filter
 * plate and the pager hold still (`lg:shrink-0`) and the <ul> is the ONE
 * scroll region. The chain is deliberate — `lg:min-h-0` on this root AND on
 * the <ul>, because a flex column's content-based automatic minimum defeats
 * the lock silently (the 993px-in-a-744px-pane war story in
 * `components/shell/geometry.ts`); every class here is load-bearing. Below
 * `lg` none of it applies and the list flows in <main>, by the contract's
 * own design. `tests/e2e/inbox-geometry.spec.ts` holds all of this.
 */

const pct = (n: number) => `${Math.round(n * 100)}%`;

function CategoryChips({
  page,
  activeCategory,
  q,
}: {
  page: FiledMailPage;
  activeCategory: string | null;
  q: string | null;
}) {
  // Canonical order first, then anything the backend adds later — a category
  // this file doesn't know is still shown, never silently dropped. Built by
  // `categoryChips` so the live-scan view offers the identical vocabulary
  // rather than a second list that drifts from this one.
  const chips = categoryChips(page.categoryCounts);
  const all = chipTotal(page.categoryCounts);

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Link
        href={filedMailHref({ q })}
        aria-current={activeCategory === null ? "true" : undefined}
        className={cn(
          "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
          activeCategory === null
            ? "border-line-strong text-strong"
            : "border-line-soft text-dim hover:text-muted",
        )}
      >
        all {all}
      </Link>
      {chips.map((chip) => {
        const active = activeCategory === chip.value;
        return (
          <Link
            key={chip.value}
            href={active ? filedMailHref({ q }) : filedMailHref({ category: chip.value, q })}
            aria-current={active ? "true" : undefined}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors",
              active
                ? "border-line-strong text-strong"
                : "border-line-soft text-muted hover:text-strong",
            )}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${chip.dot}`} aria-hidden />
            {chip.label} {chip.count}
          </Link>
        );
      })}
    </div>
  );
}

export function FiledMailList({
  page,
  activeCategory,
  q,
}: {
  page: FiledMailPage;
  activeCategory: string | null;
  q: string | null;
}) {
  const pages = filedPageCount(page.total, page.pageSize);

  return (
    <div className="flex flex-col gap-4 lg:min-h-0 lg:flex-1">
      {/* --- Filters: category chips + search ------------------------------ */}
      <div className="space-y-3 rounded-xl border border-line-soft bg-surface p-4 lg:shrink-0">
        <CategoryChips page={page} activeCategory={activeCategory} q={q} />
        <form
          method="get"
          action="/inbox"
          className="flex flex-wrap items-center gap-3 border-t border-line-soft pt-3"
        >
          {activeCategory ? <input type="hidden" name="category" value={activeCategory} /> : null}
          <div className="relative min-w-0 flex-1 basis-48">
            <Search
              className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-dim"
              aria-hidden
            />
            <input
              type="search"
              name="q"
              defaultValue={q ?? ""}
              placeholder="search subject, sender, company…"
              aria-label="Search stored mail"
              className="w-full rounded-lg border border-line bg-surface-2 py-1.5 pl-8 pr-3 text-sm text-strong outline-none placeholder:text-dim focus:border-line-strong"
            />
          </div>
          <button
            type="submit"
            className="rounded-lg border border-line px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-line-strong hover:text-strong"
          >
            search
          </button>
          {q ? (
            <Link
              href={filedMailHref({ category: activeCategory })}
              className="text-xs text-dim underline-offset-2 hover:text-strong hover:underline"
            >
              clear
            </Link>
          ) : null}
        </form>
      </div>

      {/* --- The messages --------------------------------------------------- */}
      {page.messages.length === 0 ? (
        <div className="rounded-xl border border-dashed border-line-soft bg-surface p-8 text-center">
          <p className="text-sm text-muted">
            {q || activeCategory
              ? "Nothing stored matches this view."
              : "Nothing stored yet — mail lands here as Applied reads your inbox."}
          </p>
          <p className="mt-2 text-xs text-dim">
            {q || activeCategory ? (
              <Link href="/inbox" className="underline-offset-2 hover:text-strong hover:underline">
                clear the filters →
              </Link>
            ) : (
              <>
                sync from the dashboard, or{" "}
                <Link
                  href="/inbox?view=scan"
                  className="underline-offset-2 hover:text-strong hover:underline"
                >
                  run a live scan →
                </Link>
              </>
            )}
          </p>
        </div>
      ) : (
        // `lg:min-h-0` WITHOUT `flex-1`: a short page keeps its border hugging
        // the last row; a long one shrinks to the pane's remaining measure and
        // scrolls itself. The testid is the sanctioned-scroller name the
        // geometry spec's rogue-scroller sweep excludes, same arrangement as
        // the dashboard's `worklist-pane`.
        <ul
          data-testid="filed-mail-pane"
          className="rounded-xl border border-line-soft bg-surface px-3 lg:min-h-0 lg:overflow-y-auto"
        >
          {page.messages.map((m) => {
            const meta = m.category
              ? (CATEGORY_META[m.category] ?? {
                  label: m.category.replaceAll("_", " "),
                  dot: "bg-dim",
                })
              : { label: "unclassified", dot: "bg-dim" };
            const sender = m.sender_name || m.sender_email || "unknown sender";
            const subject = m.subject || "(no subject)";
            return (
              <li
                key={m.message_id}
                className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line-soft px-1 py-3 last:border-b-0"
              >
                <div className="min-w-0 basis-full sm:basis-0 sm:flex-1">
                  <p className="truncate text-sm font-medium text-strong">{subject}</p>
                  <p className="truncate text-xs text-dim">
                    {sender}
                    {m.company ? <span className="text-muted"> · {m.company}</span> : null}
                  </p>
                  <MailSnippet snippet={m.snippet} />
                </div>
                <span className="inline-flex w-24 items-center gap-1.5 text-xs text-muted">
                  <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${meta.dot}`} aria-hidden />
                  <span className="truncate">{meta.label}</span>
                </span>
                {/* Null since the review endpoint stopped leaving the machine's
                    number on a row the human relabelled. The slots hold their
                    widths so the meters stay a column; "corrected by you" below
                    is what the row says instead. */}
                {typeof m.confidence === "number" ? (
                  <>
                    <GateMeter confidence={m.confidence} className="hidden sm:inline-block" />
                    <span
                      className="tabular w-10 text-right font-mono text-[11px]"
                      style={{
                        color: m.category === "needs_review" ? "var(--amber)" : "var(--green)",
                      }}
                    >
                      {pct(m.confidence)}
                    </span>
                  </>
                ) : (
                  <>
                    <span className="hidden h-1 w-14 shrink-0 sm:inline-block" aria-hidden />
                    <span className="tabular w-10 text-right font-mono text-[11px] text-dim">—</span>
                  </>
                )}
                <span className="tabular hidden w-12 shrink-0 text-right font-mono text-[10px] text-dim md:inline">
                  {m.received_at ? shortDate(m.received_at) : ""}
                </span>
                <OpenInGmail href={m.gmail_link} subject={subject} />
                {/* The row's standing facts: whose verdict it is, and whether it
                    built a board row. Quiet — they qualify, they don't shout. */}
                <span className="flex basis-full flex-wrap items-center gap-x-3 gap-y-1">
                  {m.user_corrected ? (
                    <span className="text-[11px] text-dim">corrected by you</span>
                  ) : null}
                  {m.application_id !== null ? (
                    <span className="text-[11px] text-dim">on your board</span>
                  ) : null}
                  <ReclassifyControl
                    messageId={m.message_id}
                    subject={subject}
                    company={m.company}
                  />
                </span>
              </li>
            );
          })}
        </ul>
      )}

      {/* --- Pager ----------------------------------------------------------- */}
      {pages > 1 ? (
        // Below the scrollport, not inside it: page controls belong with the
        // filters, always reachable without scrolling back.
        <nav aria-label="Mail pages" className="flex items-center justify-between lg:shrink-0">
          {page.page > 1 ? (
            <Link
              href={filedMailHref({
                category: activeCategory,
                q,
                page: page.page - 1,
              })}
              className="text-xs text-muted underline-offset-2 hover:text-strong hover:underline"
            >
              ← newer
            </Link>
          ) : (
            <span aria-hidden />
          )}
          <span className="tabular font-mono text-[11px] text-dim">
            page {page.page} of {pages}
          </span>
          {page.page < pages ? (
            <Link
              href={filedMailHref({
                category: activeCategory,
                q,
                page: page.page + 1,
              })}
              className="text-xs text-muted underline-offset-2 hover:text-strong hover:underline"
            >
              older →
            </Link>
          ) : (
            <span aria-hidden />
          )}
        </nav>
      ) : null}
    </div>
  );
}
