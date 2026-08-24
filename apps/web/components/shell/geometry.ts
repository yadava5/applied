/**
 * The LOCKED-page contract, as code instead of a convention.
 *
 * The shell (`AppShellFrame`) is one screen tall and its <main> is the app's
 * single fallback scroll pane. A page that wants the locked geometry — fill
 * the pane exactly, hold its own chrome still, scroll a region of its own —
 * declares this class string on its root. It lived as a hand-copied literal
 * in the signed-in dashboard and would have drifted the moment the /demo
 * shell twin repeated it; the twin is only honest evidence for the signed-in
 * page while the two roots are byte-identical, so the string lives once.
 *
 * `page-locked` is a marker, not a style: the frame's centred wrapper reads
 * it with `:has()` to collapse its own `min-height` exactly when a locked
 * page is inside (`lg:has-[.page-locked]:min-h-0`). That conditional is the
 * lock's load-bearing half, and it exists because the measured alternative
 * failed: a flex column's content-based automatic minimum is computed from
 * its child's CONTENT size, which the child's own `min-h-0` does not reduce
 * — so without it the wrapper ballooned past the pane (measured 993px in a
 * 744px pane on /demo/shell) and the whole dashboard scrolled inside <main>,
 * SyncBar and all, while the document-level lock still "passed". Flow pages
 * contain no marker, keep the auto minimum, and grow the wrapper exactly as
 * before.
 *
 * `lg:` on purpose: below the desktop breakpoint the lock releases and the
 * page flows inside <main> — pinning a phone's only content pane behind a
 * nested scroller helps nobody. The document itself stays locked at every
 * width by the frame's `h-dvh overflow-hidden`.
 */
export const LOCKED_PAGE_CLASS =
  "page-locked flex flex-col gap-3 lg:min-h-0 lg:flex-1";

/**
 * The scroll region a locked page's ORDINARY body needs.
 *
 * `LOCKED_PAGE_CLASS` only makes the root fill the pane; something inside it
 * still has to be the thing that moves, or over-tall content pushes back out
 * through <main> and the whole page scrolls again — the lock passes and the
 * symptom survives. The populated dashboard satisfies that with its worklist,
 * which owns its own scroller. Its EMPTY and FAILED branches have no worklist,
 * so they declare it here instead: header parked, body scrolls, one geometry
 * either way.
 *
 * This existed as a gap rather than a decision. Only the populated board ever
 * declared the lock (#495 verified it there), so a signed-in user with nothing
 * filed — every brand-new account, and every account whose mail is not
 * connected — got the flow geometry: chrome and all scrolling as one block,
 * which is exactly the "the dashboard doesn't scroll, but the preview does"
 * report. The empty board is the FIRST screen a new user sees, so it was the
 * one branch that most needed to look like the product.
 *
 * `lg:` to match `LOCKED_PAGE_CLASS` — the lock releases below the desktop
 * breakpoint, and a nested scroller under a released lock would be a pane
 * inside a pane.
 */
export const LOCKED_BODY_CLASS = "lg:min-h-0 lg:flex-1 lg:overflow-y-auto";
