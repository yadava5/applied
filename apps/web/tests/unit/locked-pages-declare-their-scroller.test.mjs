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

/** Prose about the fix is not the fix. Every assertion here reads code only —
 *  see the control at the foot of this file for the mutation that proved it
 *  matters. */
function withoutComments(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .map((line) => line.replace(/(^|[^:'"`\\])\/\/.*$/, "$1"))
    .join("\n");
}

const DASHBOARD = "app/(app)/(protected)/dashboard/page.tsx";
const INBOX = "app/(app)/(protected)/inbox/page.tsx";
const EMPTY_BODY = "components/dashboard/EmptyBoardBody.tsx";

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

/**
 * Match the class ON AN ELEMENT, never the identifier anywhere in the file.
 *
 * THIS IS A REPAIR TO THIS FILE, and the hole it closes was found by mutation
 * rather than by reading. The first version of these assertions was a bare
 * file-wide `/LOCKED_BODY_CLASS/`. Strip the class from the root div and leave
 * the `import { LOCKED_BODY_CLASS }` line — the exact defect being asserted
 * against — and the import alone still satisfies the regex. Green, on the
 * broken build, for the one mutation the test is named after.
 *
 * Requiring a `className={...}` around it is what makes the match mean
 * "something renders with this" instead of "this word appears".
 */
function declaresOnAnElement(source, constant) {
  return new RegExp(`className=\\{[^}]*\\b${constant}\\b`).test(source);
}

test("the dashboard's non-board branches declare a scroll region", () => {
  // The populated branch's scroller is the worklist, inside PipelineBoard. The
  // other two have no worklist, so they must say where the scrolling happens.
  assert.ok(
    declaresOnAnElement(read(DASHBOARD), "LOCKED_BODY_CLASS"),
    "no dashboard branch RENDERS with LOCKED_BODY_CLASS — the empty and failed boards have " +
      "no worklist to do the scrolling, so a tall body (a held-mail queue, a short window) " +
      "overflows back out through <main> with the lock nominally on. An import of the " +
      "constant is not a use of it.",
  );
  assert.ok(
    declaresOnAnElement(read(EMPTY_BODY), "LOCKED_BODY_CLASS"),
    "EmptyBoardBody stopped declaring the scroll region it exists to own",
  );
});

/**
 * THE THIRD REQUIREMENT, and the one that actually shipped broken.
 *
 * A locked page needs a root that fills the pane, a body that scrolls — and a
 * body that is a POSITIONED ANCESTOR. `ReviewQueue` positions nothing of its
 * own and its per-row `sr-only` labels are `position: absolute`; unparented
 * they resolve against the initial containing block and plant a 1px box at
 * DOCUMENT scale, which no ancestor's `overflow` can clip. The document then
 * scrolls while the pane, <main> and the frame all still measure locked.
 *
 * MEASURED, not theorised. `EmptyBoardBody` shipped in this PR without
 * `relative`, and `/demo/shell?empty=1&review=4` read document scrollHeight
 * **1073** against clientHeights of 800, 768 and 720 — the same 1073 at every
 * viewport, because a box at document scale does not care how tall the window
 * is. One label, at top:1072. This is the #149 family, third occurrence.
 *
 * The two sites that already knew — `PipelineBoard`'s worklist pane and the
 * inbox page's roots — each carry an unprefixed `relative` with a comment
 * naming this exact escape. Neither was enforced, which is how a third site
 * was written without it.
 */
test("every container that can hold a ReviewQueue is a containing block", () => {
  for (const [file, what] of [
    [EMPTY_BODY, "EmptyBoardBody's scroll region"],
    [INBOX, "the inbox page's roots"],
  ]) {
    assert.match(
      read(file),
      /className=\{cn\("relative"/,
      `${what} does not establish a containing block. An absolutely-positioned ` +
        "descendant — ReviewQueue's sr-only labels are the ones that keep doing this — " +
        "resolves against the initial containing block instead, plants a box at document " +
        "scale, and the whole page scrolls while every lock still measures green (#149).",
    );
  }

  // THE CONTROL: the site that has carried this the longest still carries it.
  // Without it the two assertions above could both be satisfied by a repo-wide
  // convention that had quietly been abandoned.
  //
  // COMMENTS ARE STRIPPED FIRST, and that is not tidiness — the first version
  // of this control read the raw file and passed against a build where the
  // pane's `relative` had been deleted, because a twelve-line comment ABOVE
  // the element explains the #149 escape and contains both the testid and the
  // word `relative`. The control was matching the prose that describes the fix
  // instead of the fix. Anchor on the element, and read only code.
  const pane = withoutComments(read("components/dashboard/PipelineBoard.tsx"));
  const paneElement = pane.slice(
    pane.indexOf('data-testid="worklist-pane"'),
    pane.indexOf('data-testid="worklist-pane"') + 300,
  );
  assert.ok(
    paneElement.length > 0,
    "the worklist pane's testid is gone — this control is anchored on nothing",
  );
  assert.match(
    paneElement,
    /\brelative\b/,
    "PipelineBoard's worklist pane lost its `relative` — the original #149 fix is gone, " +
      "and the two assertions above are enforcing a convention nothing else follows",
  );
});

test("the inbox's not-connected and failed scan views declare a scroll region", () => {
  const source = read(INBOX);

  // The connected branch's scroller is InboxWorkbench's own. Every other branch
  // routes through ScanBody, which is the one place the region is declared —
  // so a fourth branch cannot be added without either using it or being seen.
  assert.match(
    source,
    /function ScanBody\([\s\S]*?className=\{cn\(LOCKED_BODY_CLASS/,
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
