/**
 * A route that takes the top line must actually render one — with a sign-out in
 * it.
 *
 * WHAT THE CONTRACT IS. `components/shell/nav.ts` names the destinations whose
 * PAGE owns the screen's top line at `lg`+ (`PAGE_HEADER_HREFS`). `TopBar` reads
 * that list and hides itself at `lg` on those routes — and `TopBar` is where the
 * `Sign out` button lives. So every href on the list is a promise: this page
 * renders a header row of its own, and that row carries the session edge. Break
 * the promise on one route and that route simply has no way to sign out above
 * 1024px, which is the width the app is used at.
 *
 * WHY IT IS NOT SELF-EVIDENT. The board kept this promise for a long time as
 * the ONLY route that hid the bar, through `SyncBar`'s `⋯` menu, and nothing
 * checked it — the arrangement was one route wide, so it was held in place by
 * being remembered. Generalising the hide to four routes is exactly the moment
 * that stops working: the list and the pages that satisfy it are now in
 * different files, and adding an href is one line.
 *
 * WHY A SOURCE SCAN. These are Server Components importing `next/link` and
 * `next/navigation`, the boundary `helpers/renderTsx.mjs` documents; they cannot
 * be rendered here. Weaker than a render — it cannot prove the row is VISIBLE at
 * 1024, which is `tests/e2e/session-edge.spec.ts`'s job on the board and a
 * browser pass everywhere else — but it is what runs on every PR, and it catches
 * the failure that actually happens: a route joins the list and nobody gives it
 * a header.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";
import { readdirSync, readFileSync, existsSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const appRoot = join(webRoot, "app");

const read = (...parts) => readFileSync(join(webRoot, ...parts), "utf8");

/** Comments out, code only — this repo's comments quote the identifiers they
 *  are about, and two of them discuss this very list. Same stripper the
 *  `aria-current` gate uses, and for the same reason. */
function code(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/[^\n]*/g, "$1");
}

const navSource = code(read("components", "shell", "nav.ts"));

/** The hrefs inside `PAGE_HEADER_HREFS`'s initialiser, in source order. */
function headerHrefs() {
  const block = navSource.match(/PAGE_HEADER_HREFS[^=]*=\s*new Set\(\[([^\]]*)\]/);
  if (!block) return [];
  return [...block[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
}

/**
 * Every `page.tsx` under `app/`, keyed by the URL it actually serves.
 *
 * Built by walking rather than by guessing a path: route groups contribute no
 * URL segment, so the file for `/settings` is not at `app/settings/` and a
 * hard-coded path is one folder move away from reading nothing (this exact
 * change moved four of them). Resolving the full URL is also what keeps the
 * fixture twins out — `app/demo/settings/page.tsx` serves `/demo/settings`, and
 * a name-only match would have found two files for `/settings` and no honest
 * way to pick.
 */
function routePages() {
  const byUrl = new Map();
  (function walk(dir, url) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (!entry.isDirectory() || entry.name.startsWith("_")) continue;
      const full = join(dir, entry.name);
      const isGroup = entry.name.startsWith("(") && entry.name.endsWith(")");
      const nextUrl = isGroup ? url : `${url}/${entry.name}`;
      const page = join(full, "page.tsx");
      if (existsSync(page)) {
        const file = relative(webRoot, page).split(sep).join("/");
        byUrl.set(nextUrl, [...(byUrl.get(nextUrl) ?? []), file]);
      }
      walk(full, nextUrl);
    }
  })(appRoot, "");
  return byUrl;
}

const PAGES = routePages();

/**
 * The two shapes that satisfy the promise. `PageHeader` carries the `⋯` with
 * `Sign out` itself; the board's `SyncBar` does the same thing in its own row,
 * but only when told there is a session to end — `signedIn` is what mounts the
 * menu item (see that prop's contract), so the bare element is NOT enough.
 */
const HEADER_MARKERS = [/<PageHeader[\s/>]/, /<SyncBar[\s\S]*?\bsignedIn\b/];

// --- Guarding the guard ------------------------------------------------------

test("the list is readable and non-empty — otherwise every check below is vacuous", () => {
  const hrefs = headerHrefs();
  assert.ok(
    hrefs.length >= 4,
    `PAGE_HEADER_HREFS parsed as ${JSON.stringify(hrefs)} — either the list ` +
      `shrank or this file's matcher stopped working, and a broken matcher ` +
      `makes the contract below unfalsifiable`,
  );
  assert.ok(hrefs.includes("/dashboard"), `the board must be on the list: ${JSON.stringify(hrefs)}`);
  // And the walk really reaches the app's routes — an empty map would make the
  // contract below fail loudly rather than quietly, but a map missing only the
  // fixture twins would let a name collision go unnoticed.
  assert.ok(PAGES.has("/demo/settings"), "the route walk is not reaching app/demo/");
  assert.ok(PAGES.size >= 8, `only ${PAGES.size} routes found by the walk`);
});

test("TopBar's `lg` yield is driven by that list, not by a second copy of it", () => {
  // The contract only means anything if the bar really steps aside for exactly
  // these routes. A hardcoded pathname check in TopBar would satisfy every
  // other assertion here while drifting from `nav.ts` on the next edit.
  const topBar = code(read("components", "shell", "TopBar.tsx"));
  assert.match(
    topBar,
    /ownsPageHeader\(/,
    "TopBar no longer asks nav.ts which routes own their header, so hiding the " +
      "bar and rendering a replacement are no longer the same decision",
  );
  assert.match(
    topBar,
    /ownsHeader\s*&&\s*"lg:hidden"/,
    "TopBar's `lg` yield is no longer conditioned on ownsPageHeader's answer",
  );
});

test("PageHeader is the sign-out it promises to be", () => {
  // The positive control for the marker above: `<PageHeader />` counts as a
  // header only because that component mounts the menu item. If it stops, every
  // route relying on it loses sign-out with this file green.
  const source = code(read("components", "shell", "PageHeader.tsx"));
  assert.match(source, /label:\s*"Sign out"/, "PageHeader no longer offers Sign out");
  assert.match(source, /useSignOut\(\)/, "PageHeader's Sign out no longer ends the session");
});

test("the header is PARKED, so sign-out cannot go below the fold", () => {
  // "Reachable" is not "present". The bar this component replaced (`TopBar`)
  // sat outside `<main>` and never moved; this one lives inside the scroll
  // pane, and in flow it reached top -176 on /import and -1534 on /settings at
  // 1024 — sign-out unreachable without scrolling back up, on the two routes
  // the complaint named. These are one mechanism, not a set of preferences:
  // `sticky` + `top-0` parks the row at y=16 — the board's own line, because
  // the offset insets from the scrollport's CONTENT box and `<main>`'s `py-4`
  // is already that 16 — so it never jumps; the background is what stops
  // content showing through it; and `before:bottom-full` covers the 16px above
  // it, measured leaking a card's sliced top edge without it. `top-4` is the
  // tempting wrong value and puts the row 16px below the board's line. Drop any
  // one of these and the fix is cosmetic.
  const source = code(read("components", "shell", "PageHeader.tsx"));
  for (const utility of [
    "lg:sticky",
    "lg:top-0",
    "lg:bg-background",
    "lg:before:bottom-full",
    "lg:before:bg-background",
  ]) {
    assert.ok(
      source.includes(utility),
      `PageHeader lost \`${utility}\` — the session edge scrolls out of reach on ` +
        `the flow pages (/settings, /import) without it`,
    );
  }
});

test("the scroll pane clears the parked row for anchor jumps", () => {
  // The other half, and the reason Settings' six sections need no `scroll-mt`
  // edit: the SCROLLPORT declares how much of itself is covered. Scoped by
  // `:has()` so /privacy — in the shell, no header row — keeps its own jumps.
  const frame = code(read("components", "shell", "AppShellFrame.tsx"));
  assert.match(
    frame,
    /lg:has-\[\[data-page-header\]\]:scroll-pt-14/,
    "<main> no longer reserves room under a parked PageHeader, so a jump to a " +
      "Settings section lands with its heading underneath the row",
  );
  // And the rail that parks in the same scrollport has to clear it too.
  const nav = code(read("components", "settings", "SettingsNav.tsx"));
  assert.match(
    nav,
    /inShell \? "lg:top-14" : "lg:top-1"/,
    "SettingsNav's sticky offset no longer distinguishes the shell's scrollport " +
      "from the standalone twin's — in the shell its first links park under the header",
  );
});

// --- The contract ------------------------------------------------------------

test("every route that hides the top bar renders its own header with a sign-out", () => {
  const failures = [];
  for (const href of headerHrefs()) {
    const files = PAGES.get(href) ?? [];
    if (files.length !== 1) {
      failures.push(`${href}: expected exactly one page.tsx, found ${JSON.stringify(files)}`);
      continue;
    }
    const source = code(read(...files[0].split("/")));
    if (!HEADER_MARKERS.some((re) => re.test(source))) {
      failures.push(
        `${href} (${files[0]}): TopBar hides at lg on this route but the page ` +
          `renders neither <PageHeader> nor a <SyncBar signedIn>, so there is ` +
          `no sign-out above 1024px`,
      );
    }
  }
  assert.deepEqual(failures, [], failures.join("\n"));
});
