/**
 * Instant pending state for /import. This route is dual-mode (shell-wrapped
 * when signed in, standalone public page when not) and the pending UI cannot
 * know which branch is coming, so it renders the one thing both share: the
 * centred drop-zone measure, as a neutral plate. What it buys is an answer to
 * the click — before this, a signed-in navigation here held the previous page
 * on screen for the whole origin wait (the page's Gmail probe + auth read,
 * 700–1150 ms measured on the signed-in surface, #203).
 */
export default function ImportLoading() {
  return (
    <div
      aria-busy="true"
      aria-label="Loading mail import"
      className="mx-auto my-auto w-full max-w-3xl px-6 py-10"
    >
      <div className="h-44 animate-pulse rounded-2xl border border-line-soft bg-surface" />
      <div className="mx-auto mt-6 h-4 w-64 animate-pulse rounded bg-surface-2" />
    </div>
  );
}
