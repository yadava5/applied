/**
 * THE LOCK IS TWO HALVES, AND ONLY ONE OF THEM IS GREPPABLE.
 *
 * `LOCKED_PAGE_CLASS` makes a page root FILL the shell pane. That is half. The
 * other half is that something INSIDE it has to be the thing that scrolls — or
 * a body taller than the pane pushes back out through <main>, and the whole
 * page scrolls with its chrome while the root still carries the marker and
 * every "is it locked" grep still says yes.
 *
 * BOTH HALVES HAVE NOW FAILED IN PRODUCTION, one per page:
 *
 *   - the dashboard's EMPTY and FAILED branches never declared the root at all
 *     (#505). #495 locked the populated branch, which was the only one it
 *     touched, so the first screen of every new account kept the flow geometry.
 *   - the inbox's not-connected SCAN view declared the root and then hung three
 *     ordinary stacked cards under it with no scroll region anywhere.
 *
 * WHY THIS IS A SOURCE TEST AND NOT A BROWSER ONE. Both surfaces need a
 * Supabase session, which no CI environment here has (#188), so the executing
 * geometry lives on `/demo/shell` — a twin that could only ever mount the
 * POPULATED board until `?empty=1` was added, and that has no counterpart at
 * all for the inbox's scan fallback. The measurement is worth more and it now
 * exists where it can; this file is what covers the branches it cannot reach,
 * and what makes the invariant a rule instead of a sentence in a comment.
 *
 * `components/shell/geometry.ts` states the contract in prose. An unenforced
 * invariant in a doc comment is exactly how both of these shipped.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const WEB_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const read = (rel) => readFileSync(join(WEB_ROOT, rel), "utf8");

const DASHBOARD = "app/(app)/(protected)/dashboard/page.tsx";
const INBOX = "app/(app)/(protected)/inbox/page.tsx";

test("every dashboard branch locks its root — not just the populated one", () => {
  const source = read(DASHBOARD);

  // Each `return (` from the page component opens a branch, and each renders a
  // <section> root. Count the roots rather than the returns: a helper's return
  // is not a page branch, and a <section> is what the shell's `:has()` reads.
  const roots = [
    ...source.matchAll(/<section\s+className=\{?([^>]*?)\}?>/g),
  ].map((m) => m[1]);

  assert.ok(
    roots.length >= 3,
    `expected the dashboard's three branches (failed / empty / populated), found ${roots.length} ` +
      "<section> roots — if a branch was added or removed, this count is the thing to update, " +
      "but check first that the new one locks",
  );

  const unlocked = roots.filter((cls) => !cls.includes("LOCKED_PAGE_CLASS"));
  assert.deepEqual(
    unlocked,
    [],
    "a dashboard branch renders a root without LOCKED_PAGE_CLASS:\n" +
      unlocked.map((c) => `  <section className=${c}>`).join("\n") +
      "\n\nThat branch keeps the flow geometry: AppShellFrame's wrapper keeps its " +
      "content-based minimum (`lg:has-[.page-locked]:min-h-0` never fires) and <main> " +
      "scrolls the whole page, sync row and all. This is #505 — the branch it hit was " +
      "the empty board, which is the first screen of every new account.",
  );
});

test("the dashboard's non-board branches declare a scroll region", () => {
  const source = read(DASHBOARD);

  // The populated branch's scroller is the worklist, inside PipelineBoard. The
  // other two have no worklist, so they must say where the scrolling happens.
  assert.match(
    source,
    /LOCKED_BODY_CLASS/,
    "no dashboard branch declares LOCKED_BODY_CLASS — the empty and failed boards have no " +
      "worklist to do the scrolling, so a tall body (a held-mail queue, a short window) " +
      "overflows back out through <main> with the lock nominally on",
  );
  assert.match(
    read("components/dashboard/EmptyBoardBody.tsx"),
    /LOCKED_BODY_CLASS/,
    "EmptyBoardBody stopped declaring the scroll region it exists to own",
  );
});

test("the inbox's not-connected and failed scan views declare a scroll region", () => {
  const source = read(INBOX);

  // The connected branch's scroller is InboxWorkbench's own. Every other branch
  // routes through ScanBody, which is the one place the region is declared —
  // so a fourth branch cannot be added without either using it or being seen.
  assert.match(
    source,
    /function ScanBody\([\s\S]*?LOCKED_BODY_CLASS/,
    "ScanBody no longer declares LOCKED_BODY_CLASS — the not-connected scan view is back to " +
      "three stacked cards under a root that has stopped growing",
  );

  const scanView = source.slice(
    source.indexOf("if (scan) {"),
    source.indexOf("// --- Filed"),
  );
  const branches = [
    ...scanView.matchAll(/\) : (?:result\.kind === "\w+" \? )?\(\s*(<\w+)/g),
  ].map((m) => m[1]);
  assert.ok(
    branches.length >= 3,
    `expected the scan view's auth / backend / fallback branches, matched ${branches.length}`,
  );
  const bare = branches.filter((tag) => tag !== "<ScanBody");
  assert.deepEqual(
    bare,
    [],
    `a scan-view branch renders ${bare.join(", ")} directly instead of wrapping it in ` +
      "<ScanBody>, so that branch has no scroll region and the page scrolls as one block",
  );
});

test("CONTROL: the marker and the region are different strings, and both are findable", () => {
  // Without this the three tests above could all be passing on a typo — a
  // constant that no longer exists still "matches" nothing consistently.
  const geometry = read("components/shell/geometry.ts");
  assert.match(geometry, /export const LOCKED_PAGE_CLASS =\s*"page-locked/);
  assert.match(geometry, /export const LOCKED_BODY_CLASS =\s*"lg:min-h-0/);
  // The root marker must NOT itself carry overflow: if it did, the second half
  // would be free and these tests would be asserting a redundancy.
  assert.doesNotMatch(
    geometry.slice(geometry.indexOf("export const LOCKED_PAGE_CLASS")),
    /LOCKED_PAGE_CLASS =\s*"[^"]*overflow/,
    "LOCKED_PAGE_CLASS grew an overflow of its own — if the root scrolls, it scrolls its " +
      "own chrome too, which is the symptom, not the fix",
  );
});
