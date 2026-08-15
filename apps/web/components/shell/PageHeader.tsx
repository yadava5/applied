"use client";

import { MoreHorizontal } from "lucide-react";
import type { ReactNode } from "react";

import { RowActionsMenu } from "@/components/dashboard/RowActionsMenu";
import { cn } from "@/lib/utils";
import { useSignOut } from "./SessionControls";

/**
 * The header line for a non-board route, in the BOARD'S idiom.
 *
 * WHAT THIS REPLACES. At `lg`+ the dashboard's top line is the board's own row
 * (`SyncBar`): the page's state on the left, its controls on the right, and
 * sign-out folded into a `⋯` menu — never a row-level button, which is what
 * wrapped that row at 1024 (#172). /inbox, /settings and /import instead got
 * `TopBar`: a 48px strip whose left end printed the route's NAME and whose
 * right end held a `Sign out` button. Two different header languages in one
 * app, and the strip's content was a restatement — the rail is lit, the reader
 * can see where they are. This component is the one pattern, so the four
 * destinations now read the same at the top of the screen.
 *
 * WHAT GOES IN IT. `children` — the page's own controls, and only controls or
 * genuine state. A header that restates the rail is worse than no header, and
 * this repo has removed that restatement by number three times already (#196,
 * #197, #199, and #198 for the /import mode pill). So /inbox promotes its
 * Filed/Live-scan switch (navigation WITHIN the page, which is exactly what a
 * page header is for) and /settings and /import pass nothing: their state is
 * already stated once, elsewhere, by something that is also a control.
 *
 * THE SESSION EDGE IS WHY IT EXISTS AT ALL. `TopBar` yields at `lg`+ on every
 * route that renders this (see `ownsPageHeader` in `./nav`), and it carried the
 * only sign-out. So the `⋯` here is not decoration: it is the route's sign-out
 * above `lg`, in the same menu, with the same label and the same trigger
 * geometry the board uses. Below `lg` it is hidden and `TopBar` is back with
 * its button — one control visible at a time, never two.
 *
 * GEOMETRY. `flex`, not `flex-wrap`: the children slot is `min-w-0 flex-1` and
 * shrinks, so a long child can never push the menu onto a second line. That is
 * the #172 failure shape, and it is designed out rather than watched for. With
 * no children the whole row is `hidden lg:flex`, because below `lg` an empty
 * row is 36px of nothing — and the board's own comment is that it refuses to
 * spend 48px on a strip with an empty middle.
 *
 * PINNED. The row it replaced (`TopBar`) lived OUTSIDE `<main>` and therefore
 * never moved. This one is inside the scroll pane, and in flow that was a real
 * regression: measured at 1024, the `⋯` reached top `-176` on /import and
 * `-1534` on /settings — sign-out below the fold on exactly the two routes the
 * complaint named. So the row is `sticky` at `lg`.
 *
 * `top-0`, AND THAT IS NOT THE ZERO IT LOOKS LIKE. It resolves to y=16 here,
 * not y=0 — measured on all four routes, at 1024 and 1383: the row's box comes
 * out `top: 16, height: 36`, byte-for-byte the board's `data-sync-header-row`.
 * The offset behaves as an inset from the SCROLLPORT'S CONTENT box, and
 * `<main>`'s `py-4` is already 16 of it, so `top-0` parks the row exactly where
 * normal flow had put it. It therefore never moves at all — there is no
 * transition into "stuck", which is the nicest possible version of this.
 *
 * The plausible-sounding alternatives were both tried and both measured wrong,
 * which is why this comment is long:
 *
 *   - `top-4`, reasoning that the offset is measured from the PADDING box and
 *     the row must park where `py-4` put it: that stacks the two, and the row
 *     lands at y=32 — 16px below the board's line, breaking the one geometry
 *     this component exists to match.
 *   - `top-0` with `-mt-4 pt-4`, to move the pane's padding inside the row so
 *     its background covers it: the negative margin cannot lift a sticky box
 *     out of its containing block, so the row stayed at 16 regardless and the
 *     only lasting effect was a 52px box whose CONTENT sat at 32 — the same
 *     16px break, hidden one level down.
 *
 * `before:` IS THE 16px. Parking at 16 leaves the pane's own top padding
 * uncovered, and content scrolls through it — measured on /settings at scroll
 * 800, `elementFromPoint` at y=4 returned the sections grid, and a card's top
 * edge was visibly sliced above the row. The pseudo-element extends the row's
 * background upward over exactly that band. It is out of flow, so the row's box
 * stays 36px, and it inherits the row's `z-30` stacking context so it covers
 * what passes under it.
 *
 * On a LOCKED page (/inbox) `<main>` does not scroll at `lg`, so `sticky` never
 * engages and all of this is inert — no prop, nothing for a caller to forget.
 * The clearance an anchor jump needs underneath a parked row is the
 * SCROLLPORT's business, not each target's: `AppShellFrame` declares it once
 * with `lg:has-[[data-page-header]]:scroll-pt-14`, so pages that render no
 * header (the /privacy document) are untouched.
 *
 * No hairline. The board's row has none, matching it is the brief, and the row
 * is parked from the first pixel — there is no unstuck state for a border to
 * distinguish it from.
 *
 * `data-page-header` names the row for geometry assertions, the same reason
 * `data-sync-header-row` exists on the board's: a check that had to find this
 * box by its class list goes quietly vacuous the first time the utilities are
 * touched.
 */
export function PageHeader({ children }: { children?: ReactNode }) {
  const { signOut } = useSignOut();

  return (
    <div
      data-page-header=""
      className={cn(
        "flex items-center gap-3",
        // Parked at the top of the scroll pane, so the session edge cannot go
        // below the fold. `lg` only: beneath it TopBar is back, outside the
        // pane, carrying its own sign-out. `top-0` resolves to y=16 — the
        // board's own line — so the row never moves at all; `before:` covers
        // the 16px above it, the only place content could otherwise scroll
        // past. Both are measured, and both alternatives failed. See above.
        "lg:sticky lg:top-0 lg:z-30 lg:bg-background",
        "lg:before:absolute lg:before:inset-x-0 lg:before:bottom-full lg:before:h-4 lg:before:bg-background lg:before:content-['']",
        // No children means nothing to show below `lg`, where the menu is
        // hidden and TopBar owns the session edge.
        children == null && "hidden lg:flex",
      )}
    >
      <div className="min-w-0 flex-1">{children}</div>
      <div className="hidden shrink-0 items-center lg:flex">
        <RowActionsMenu
          label="More actions"
          triggerClassName="grid h-9 w-9 place-items-center rounded-lg border border-line text-muted transition-colors hover:border-line-strong hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong"
          triggerContent={<MoreHorizontal className="h-4 w-4" aria-hidden />}
          items={[
            {
              key: "sign-out",
              // Same label, same menu chrome, same position (last) as the
              // board's. `session-edge.spec.ts` measures that arrangement on
              // the board; the point of this component is that there is only
              // one arrangement to measure.
              label: "Sign out",
              onSelect: () => void signOut(),
            },
          ]}
        />
      </div>
    </div>
  );
}
