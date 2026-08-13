/**
 * `aria-current="page"` may name exactly ONE element in a document — the place
 * you are in the site's navigation. Only the primary nav gets to claim it.
 *
 * The defect this exists for (#163): the inbox's Filed/Live-scan view switch
 * set `aria-current="page"` on the selected tab, so /inbox served TWO of them
 * — the rail's Inbox item and the Filed tab — and a screen reader announced
 * two current-page landmarks with no way to tell which was the location.
 *
 * There WAS an assertion for this, and it is correct:
 * `tests/e2e/shell.spec.ts`, "the sidebar marks 'Inbox' as the current page",
 * asserts `toHaveCount(1)` on `a[aria-current="page"]`. It has never executed.
 * Its whole describe block goes through `requireSession()`, which `test.skip`s
 * the moment /dashboard bounces to /login — and both e2e jobs boot the app
 * against a placeholder Supabase project (`https://example.supabase.co`), so
 * that bounce is unconditional in CI. A correct gate pointed at something it
 * cannot reach: the same shape as the Node-20 unit job and the review-queue
 * gap (#151). That test stays exactly as it is — it is the stronger check the
 * day a seeded session exists. This file is the one that runs TODAY, on every
 * PR touching apps/web, in `pnpm test:unit` under Frontend CI.
 *
 * It reads source rather than rendered markup: the components involved import
 * `next/link` and `next/navigation`, which is the boundary
 * `helpers/renderTsx.mjs` documents. Weaker than a render — it cannot count
 * what a given URL actually paints — but it is what makes the invariant
 * enforceable across every file in the tree, including ones not written yet.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

/** Every tree that can render markup. `readdirSync` THROWS on a missing
 *  directory and that is the point — an `existsSync` skip here is how three
 *  gates in this repo ended up measuring half their inputs and printing
 *  PASSED. If a root is renamed, this file goes red instead of quiet. */
const ROOTS = ["app", "components"];

/**
 * The files allowed to set `aria-current="page"`: the authed app's primary
 * navigation, and only it. TWO files, because the desktop rail and the mobile
 * menu are two renderings of the SAME `navItems` source (`components/shell/
 * nav.ts`) at opposite sides of the `md` breakpoint — one nav, not two sets.
 * Anything else on a page — a view switch, a filter chip, a pager — is
 * navigation WITHIN the page and takes `aria-current="true"`.
 */
const PRIMARY_NAV = ["components/shell/Sidebar.tsx", "components/shell/TopBar.tsx"];

function sourceFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return /\.tsx?$/.test(entry.name) ? [full] : [];
  });
}

/**
 * Comments out, markup only. This repo comments densely and those comments
 * quote the attribute they are about — including, one file down, the note
 * explaining why the view switch is `"true"` and not `"page"`. Scanning raw
 * text made this file's own first run red against prose, and the same mistake
 * in the other direction would flag a violation nothing renders. `//` is left
 * alone after a colon so `https://…` in an href survives.
 */
function code(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/[^\n]*/g, "$1");
}

/** Every scannable source file, keyed by its path relative to `apps/web`. */
const sources = ROOTS.flatMap((root) =>
  sourceFiles(join(webRoot, root)).map((file) => ({
    path: relative(webRoot, file).split(sep).join("/"),
    code: code(readFileSync(file, "utf8")),
  })),
);

/**
 * One whole `aria-current` attribute, in either form JSX writes it: a string
 * literal (`aria-current="page"`) or an expression
 * (`aria-current={active ? "page" : undefined}`). The brace alternative
 * tolerates one level of nesting, which is all a ternary needs.
 */
const ARIA_CURRENT = /aria-current\s*=\s*(?:"[^"]*"|\{(?:[^{}]|\{[^{}]*\})*\})/g;

/** Every `aria-current` attribute written in one file's markup. */
function attrsIn(relativePath) {
  return code(readFileSync(join(webRoot, ...relativePath.split("/")), "utf8")).match(ARIA_CURRENT) ?? [];
}

/** Files whose `aria-current` can evaluate to `"page"`. */
function filesClaimingPage() {
  return sources
    .filter(({ code }) => (code.match(ARIA_CURRENT) ?? []).some((attr) => /"page"/.test(attr)))
    .map(({ path }) => path)
    .sort();
}

// --- Guarding the guard ------------------------------------------------------

test("the scan reaches the app's markup — otherwise every check below is vacuous", () => {
  for (const root of ROOTS) {
    const found = sources.filter(({ path }) => path.startsWith(`${root}/`));
    assert.ok(found.length > 0, `no .ts/.tsx files found under ${root}/ — the walk is broken`);
  }
  // A floor well under the ~98 files present, so it survives ordinary churn
  // but not a walk that silently stops at the first directory.
  assert.ok(sources.length >= 50, `only ${sources.length} source files scanned`);
});

test("the scanner sees the attribute at all — the primary nav still claims the page", () => {
  // The positive control. Without it, a regex that matched nothing would
  // report "no violations" forever, and so would a rail that lost its active
  // state entirely. Both must be red, not green.
  const claiming = filesClaimingPage();
  for (const file of PRIMARY_NAV) {
    assert.ok(
      claiming.includes(file),
      `${file} no longer sets aria-current="page" — either the primary nav lost ` +
        `its active state, or this file's matcher stopped working. Both make the ` +
        `check below unfalsifiable: ${JSON.stringify(claiming)}`,
    );
  }
});

// --- The invariant -----------------------------------------------------------

test('only the primary navigation claims aria-current="page"', () => {
  const strays = filesClaimingPage().filter((file) => !PRIMARY_NAV.includes(file));
  assert.deepEqual(
    strays,
    [],
    `aria-current="page" identifies ONE location in the site nav, so a second ` +
      `element claiming it makes both meaningless to assistive tech. These are ` +
      `in-page switchers and want aria-current="true": ${strays.join(", ")}`,
  );
});

test("the inbox view switch still SAYS which view is selected", () => {
  // The half a careless fix defeats: deleting the attribute also empties the
  // list above. Both tabs must still announce their selected state, by the
  // value the filed-mail category chips already use.
  assert.deepEqual(
    attrsIn("app/(app)/inbox/page.tsx").sort(),
    ['aria-current={!scan ? "true" : undefined}', 'aria-current={scan ? "true" : undefined}'],
    "both inbox view tabs must carry aria-current, and it must be \"true\"",
  );
});

test("the in-page switchers agree on one value", () => {
  // Filed-mail chips got this right from the start; the view switch was the
  // outlier. Stated here so the two cannot drift back apart.
  const attrs = attrsIn("components/mail/FiledMailList.tsx");
  assert.ok(attrs.length >= 2, `expected the category chips' aria-current, found ${attrs.length}`);
  for (const attr of attrs) assert.match(attr, /"true"/);
});
