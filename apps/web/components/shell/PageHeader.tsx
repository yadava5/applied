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
