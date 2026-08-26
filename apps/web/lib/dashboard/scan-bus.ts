/**
 * One-slot signal for "open the windowed-scan dialog".
 *
 * The dialog lives inside `SyncBar` (the single owner of sync state, so a
 * windowed scan started from anywhere reports through the one status line), but
 * the empty state's "Choose a window" button renders in a different subtree.
 * Rather than threading a context through the server page, the button raises
 * this signal and the mounted SyncBar answers it.
 *
 * Module-level state is safe here for the same reason as `rowMenuRegistry`:
 * only client components touch it, and only from effects and event handlers —
 * never during a server render. Dependency-free so `node --test` can load it.
 */

type Listener = () => void;

let listener: Listener | null = null;

/** SyncBar subscribes on mount; returns the unsubscribe. */
export function onScanRequest(fn: Listener): () => void {
  listener = fn;
  return () => {
    if (listener === fn) listener = null;
  };
}

/**
 * Ask the mounted SyncBar to open the scan dialog. Returns whether anything
 * was listening, so a caller can fall back honestly instead of doing nothing.
 */
export function requestScan(): boolean {
  if (listener === null) return false;
  listener();
  return true;
}
