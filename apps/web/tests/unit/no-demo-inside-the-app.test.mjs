/**
 * NOTHING WITHIN THE APP IS THE DEMO — enforced statically, today.
 *
 * The directive (#495): fixture content belongs to the landing page and the
 * public `/demo/*` routes. Inside the signed-in product a realistic invented
 * pipeline sitting where the reader's own board goes is not a demonstration,
 * it is a thing to be misread.
 *
 * WHY THIS FILE EXISTS RATHER THAN THE E2E THAT ALREADY ASSERTS IT.
 *
 * `tests/e2e/beta.spec.ts` carries "the signed-in inbox offers no route into
 * the demo", which is the better check — it reads what a browser actually
 * paints. It has never run and cannot run here: it is behind
 * `requireSession()`, no authenticated Supabase session exists locally or in
 * CI (`E2E_REQUIRE_SESSION` is unset there, so the guard skips rather than
 * fails), and it is one of 29 specs skipping for that reason. Shipping the
 * directive with its only enforcement being a test that cannot execute is the
 * exact defect shape this repo keeps finding: a check that cannot fail. That
 * e2e stays — it becomes real the day #188 lands a seeded account — and this
 * runs in `npm run test:unit` on every PR meanwhile.
 *
 * WHAT IS ASSERTED. Starting from the signed-in route entrypoints
 * (`app/(app)/(protected)/**` plus the `(app)` shell layout they nest in), the
 * transitive STATIC import closure must not reach any module under
 * `lib/demo/` except the allowlist below. See `helpers/importGraph.mjs` for
 * what the walk follows, and — importantly — for the `await import()` escape
 * hatch it deliberately does not follow.
 *
 * The two directions are each other's control, and both run every time: the
 * same walker over the `/demo` route tree MUST come back loaded with fixture
 * modules. A walk that silently resolved nothing would pass the first
 * assertion and fail the second.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

import {
  demoModulesReached,
  importClosure,
  routeEntrypoints,
} from "./helpers/importGraph.mjs";

const WEB_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

/**
 * Modules under `lib/demo/` a signed-in route MAY reach. Each entry states why
 * it carries no fixture data — an allowlist without reasons is a list of
 * things nobody has to justify again.
 *
 * These are paths, not prefixes: `lib/demo/asApplications.ts` cannot be
 * smuggled in by a rule written for `lib/demo/a…`.
 */
const ALLOWED = new Map([
  [
    "lib/demo/ambientPref.ts",
    "Cookie name + parse/write for the /demo-scoped ambient-mail preference. " +
      "Two functions over document.cookie and a string constant; it holds no mail, " +
      "no applications and no dates. Reached because lib/settings/transport.ts " +
      "shares one module between the live and demo transports.",
  ],
  [
    "lib/demo/notificationPrefs.ts",
    "Same shape, for the /demo-scoped notification preferences: a cookie name and " +
      "two codecs over the SAME readNotificationPrefs the signed-in page uses. " +
      "No fixture data.",
  ],
  [
    "lib/demo/rulesLayer.ts",
    "The REAL layer-1 rules engine — the shipped classifier, not a fixture of one. " +
      "Reached from a PRESENT import, not held in reserve: /import runs it on a " +
      "visitor's own mail, on-device, with no upload and no session. Misfiled under " +
      "lib/demo/ by history; allowlisted rather than moved because the rename has its " +
      "own blast radius (readme_facts.py, the marketing surfaces and two e2e specs all " +
      "name the path).",
  ],
  [
    "lib/demo/rules.json",
    "The engine's pattern table, and the inseparable other half of rulesLayer.ts — " +
      "15 real ATS domains and 261 regexes in strong/weak/veto/negative buckets across " +
      "7 categories. It surfaced only when the fence widened to /import, and it was " +
      "read before it was allowlisted: it holds no message, no company and no date. " +
      "Verified by a marker grep that returns 0 here while returning 6 in " +
      "sampleInbox.ts and 12 in demoData.ts, so the null is the file's and not the " +
      "grep's.",
  ],
]);

test("no signed-in route reaches a fixture module under lib/demo/", () => {
  // EVERY route in the `(app)` group, not just `(protected)`. "Within the app"
  // means what renders in the app shell, and `/import` and `/privacy` do —
  // they sit outside `(protected)` only because they need no session, not
  // because they are somewhere else. Narrowing this to `(protected)` was a
  // real hole: the one fixture leak #495 caught by MEASURING a production
  // build was `components/import/ImportMail.tsx` importing GATE from
  // `lib/demo/sampleInbox`, which dragged eleven invented emails into the
  // /import chunk. A gate blind to the defect it shipped alongside is the
  // shape this file exists to retire.
  const entrypoints = routeEntrypoints(join(WEB_ROOT, "app/(app)"));

  const { hits, closure } = demoModulesReached(WEB_ROOT, entrypoints);

  // The walk actually walked. Without this, a resolver that quietly returned
  // null for every specifier would report zero fixture modules and read as a
  // pass — the failure mode every other census in this repo is guarded against.
  assert.ok(
    closure.size > 50,
    `the import closure is only ${closure.size} modules; the walk did not resolve. ` +
      "A zero-hit result from a walk that went nowhere is not a pass. " +
      "50 is a TRIPWIRE, not a target: the closure measured 122 across the 7 `(app)` " +
      "entrypoints on the commit that widened this fence (115 when it walked only " +
      "`(protected)`; 124 on origin/main, which still carries SamplePreview). Set " +
      "far enough below that ordinary churn never touches it, and high enough that a " +
      "resolver returning null for every specifier cannot slip through — same rule as " +
      "MIN_TESTS in scripts/assert-unit-suite-ran.mjs.",
  );
  for (const anchor of [
    "components/dashboard/DashboardEmptyState.tsx",
    "components/dashboard/PipelineBoard.tsx",
    "lib/settings/transport.ts",
  ]) {
    assert.ok(
      [...closure.keys()].some((f) => f.endsWith(anchor.split("/").join("/"))),
      `${anchor} is not in the signed-in closure, so this gate is not looking at the app.`,
    );
  }

  const offenders = hits.filter((h) => !ALLOWED.has(h.module));
  assert.deepEqual(
    offenders.map((h) => h.module),
    [],
    offenders.length === 0
      ? ""
      : "A signed-in route reaches fixture data (#495 — nothing within the app is the demo):\n" +
        offenders.map((h) => "  " + h.chain.join("\n    -> ")).join("\n\n") +
        "\n\nEither drop the import, or — if the module genuinely carries no fixtures — " +
        "add it to ALLOWED in this file WITH the reason. If it does carry fixtures and " +
        "is genuinely needed, load it behind `await import()` and prove the chunk is " +
        "clean in a production build, the way #495 did.",
  );
});

test("the allowlist names files that exist", () => {
  // A renamed or deleted module must not leave a permanent hole behind.
  for (const [rel] of ALLOWED) {
    assert.ok(existsSync(join(WEB_ROOT, rel)), `ALLOWED names ${rel}, which does not exist`);
  }
});

test("the same walk over /demo IS loaded with fixture modules", () => {
  // The control for the assertion above. If the walker cannot see a demo
  // import when one is right in front of it, its silence about the signed-in
  // tree means nothing at all.
  const { hits } = demoModulesReached(WEB_ROOT, routeEntrypoints(join(WEB_ROOT, "app/demo")));
  const modules = hits.map((h) => h.module);

  assert.ok(
    modules.includes("lib/demo/asApplications.ts"),
    `the /demo routes must reach the fixture board; walker saw: ${modules.join(", ") || "nothing"}`,
  );
  assert.ok(
    modules.filter((m) => !ALLOWED.has(m)).length >= 3,
    `expected the /demo tree to reach several fixture modules, saw: ${modules.join(", ")}`,
  );
});

/**
 * THE OTHER AXIS, and the one that was missing.
 *
 * Everything above asks what a signed-in route IMPORTS. That is not the only
 * way the demo gets inside the app, and the way it actually did is invisible
 * to an import walk: a `<Link href="/demo/inbox">` imports nothing.
 *
 * WHAT SHIPPED. `BetaBanner` — the dismissible "Beta · limited access" pill —
 * is mounted by the ROOT layout, so it renders on every route its own
 * `HIDE_ON` list does not name. Its popover carried "Try the sample inbox" →
 * `/demo/inbox`, justified in `components/beta/constants.ts` by the claim that
 * `HIDE_ON` left only signed-out edges. `HIDE_ON` is a list of ROUTES, and a
 * route is not a session. `/privacy` is not on it and is signed-in-reachable
 * by design — the protected Inbox page links to it, the Gmail card in Settings
 * links to it, and `app/(app)/layout.tsx` wraps it in the full app shell for a
 * signed-in reader. `not-found.tsx` is not on it and cannot be. So a user
 * inside the product was one click from invented mail, which is the exact
 * thing #495 was about.
 *
 * WHY BOTH EXISTING GATES WERE BLIND, stated so neither is trusted for this
 * again. The import walk above starts at `app/(app)` — the ROOT layout is not
 * in that closure at all, and it never inspects an href. The e2e that DOES
 * read hrefs (`tests/e2e/beta.spec.ts`) checks `/inbox` only and skips behind
 * `requireSession()`, so it has never executed.
 *
 * WHAT THIS ASSERTS. Walk from the root layout — plus `not-found` and the
 * whole `(app)` group — and refuse any `/demo…` path literal that is not on
 * the allowlist below with a reason. It is deliberately a literal scan and not
 * a render: an href-shaped string in a module the root layout can reach is
 * close enough to a link that the burden should be on justifying it.
 */
const DEMO_PATH_LITERAL = /["'`](\/demo(?:\/[a-z-]+)*)["'`]/g;

/**
 * `/demo…` literals a root-mounted module MAY hold, each with the reason it is
 * not a link. Keyed `file::literal`, so allowing one string in one file cannot
 * quietly allow a different one somewhere else.
 */
const ALLOWED_DEMO_LITERALS = new Map([
  [
    "components/beta/BetaBanner.tsx::/demo",
    "An entry in the pill's own HIDE_ON list — a route where the banner must " +
      "NOT render. The opposite of a link to it.",
  ],
  [
    "components/shell/nav.ts::/demo",
    "The demo-mode nav map. Applied only through `demoHrefFor()`, which " +
      "`NavLink` calls only when `useDemoMode()` is true — and the one " +
      "signed-in mount, `components/shell/AppShell.tsx`, passes no `demo` " +
      "prop, so `AppShellFrame` supplies `false`. See the sibling test.",
  ],
  ["components/shell/nav.ts::/demo/inbox", "Same map, same gate."],
  ["components/shell/nav.ts::/demo/settings", "Same map, same gate."],
  ["components/shell/nav.ts::/demo/shell", "Same map, same gate."],
  [
    "components/shell/Sidebar.tsx::/demo",
    "The rail logo's destination in demo dress, behind the same `demo` flag.",
  ],
  [
    "components/shell/TopBar.tsx::/demo",
    "The top bar's demo-dress destination, behind the same `demo` flag.",
  ],
  [
    "components/dashboard/SyncBar.tsx::/demo",
    "Where the twin's `⋯` menu sends a fixture 'sign out'. Reachable only on " +
      "the simulated transport; the dashboard passes none, so `simulated` is " +
      "false on every signed-in render.",
  ],
  [
    "lib/demo/ambientPref.ts::/demo",
    "A cookie PATH scope, not a URL — it is what confines the demo's toggle " +
      "cookie to the demo routes.",
  ],
  [
    "lib/demo/notificationPrefs.ts::/demo",
    "Same: the cookie path scope for the demo notification prefs.",
  ],
]);

/** Comments are prose about the demo, not routes into it. Strip them first, or
 *  the gate fires on its own explanation. */
function withoutComments(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .map((line) => line.replace(/(^|[^:'"`\\])\/\/.*$/, "$1"))
    .join("\n");
}

function demoLiteralsUnder(webRoot, entrypoints) {
  const { closure, chainTo } = importClosure(webRoot, entrypoints);
  const found = [];
  for (const file of closure.keys()) {
    const rel = relative(webRoot, file).split("\\").join("/");
    const source = withoutComments(readFileSync(file, "utf8"));
    for (const match of source.matchAll(DEMO_PATH_LITERAL)) {
      found.push({ key: `${rel}::${match[1]}`, rel, literal: match[1], chain: chainTo(file) });
    }
  }
  return { found, closure };
}

test("nothing the ROOT layout can render links into the demo", () => {
  const entrypoints = [
    join(WEB_ROOT, "app/layout.tsx"),
    join(WEB_ROOT, "app/not-found.tsx"),
    ...routeEntrypoints(join(WEB_ROOT, "app/(app)")),
  ];
  const { found, closure } = demoLiteralsUnder(WEB_ROOT, entrypoints);

  // The walk actually walked — same tripwire discipline as above. Measured 132
  // modules when this gate was written.
  assert.ok(
    closure.size > 60,
    `the root closure is only ${closure.size} modules; the walk did not resolve`,
  );
  // And it is looking at the module the defect was in. Without this the gate
  // passes just as well if BetaBanner stops being reachable for some unrelated
  // reason — green because it looked nowhere.
  assert.ok(
    [...closure.keys()].some((f) => f.endsWith("components/beta/BetaBanner.tsx")),
    "BetaBanner is not in the root closure — this gate is not looking at the pill",
  );

  const offenders = found.filter((hit) => !ALLOWED_DEMO_LITERALS.has(hit.key));
  assert.deepEqual(
    offenders.map((hit) => hit.key),
    [],
    offenders.length === 0
      ? ""
      : "A module the root layout can render holds a /demo path (#495 — nothing " +
        "within the app is the demo):\n" +
        offenders.map((hit) => "  " + hit.chain.join("\n    -> ")).join("\n\n") +
        "\n\nIf it is genuinely not a link — a HIDE_ON entry, a cookie scope, a " +
        "destination behind the `demo` flag — add it to ALLOWED_DEMO_LITERALS " +
        "WITH the reason.",
  );
});

test("the allowlisted demo literals still exist where they were allowed", () => {
  // An allowlist entry that no longer matches anything is a permanent hole:
  // the file could grow a REAL link at that same literal and inherit the
  // excuse. Every entry must still be found in the file it names.
  for (const [key] of ALLOWED_DEMO_LITERALS) {
    const [rel, literal] = key.split("::");
    const source = withoutComments(readFileSync(join(WEB_ROOT, rel), "utf8"));
    const literals = [...source.matchAll(DEMO_PATH_LITERAL)].map((m) => m[1]);
    assert.ok(
      literals.includes(literal),
      `ALLOWED_DEMO_LITERALS excuses "${literal}" in ${rel}, which no longer holds it`,
    );
  }
});

test("the signed-in shell mount does not turn demo mode on", () => {
  // The load-bearing half of four allowlist entries above. Every `/demo`
  // destination in the shell chrome is gated on `useDemoMode()`, which is fed
  // by `AppShellFrame`'s `demo` prop. If the signed-in mount ever passes it,
  // those four excuses become false all at once and the rail, the top bar and
  // the sync row all start pointing at the demo.
  const source = readFileSync(join(WEB_ROOT, "components/shell/AppShell.tsx"), "utf8");
  const mount = source.slice(source.indexOf("<AppShellFrame"));
  assert.doesNotMatch(
    mount.slice(0, mount.indexOf(">")),
    /\bdemo\b/,
    "AppShell now passes a `demo` prop — the shell's demo-mode destinations are live " +
      "on the signed-in tree, and four ALLOWED_DEMO_LITERALS entries no longer hold",
  );
});

test("the same scan over the /demo routes DOES find demo links", () => {
  // The control. A scanner that matched nothing anywhere would pass the gate
  // above by being broken.
  const { found } = demoLiteralsUnder(WEB_ROOT, routeEntrypoints(join(WEB_ROOT, "app/demo")));
  assert.ok(
    found.length >= 3,
    `the /demo tree must hold demo links; the scan found ${found.length}`,
  );
});
