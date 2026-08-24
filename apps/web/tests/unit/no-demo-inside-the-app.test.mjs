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
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { demoModulesReached, routeEntrypoints } from "./helpers/importGraph.mjs";

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
    "The REAL layer-1 rules engine plus its rules.json patterns — the shipped " +
      "classifier, not a fixture of one. It is what /import runs on a visitor's own " +
      "mail on-device. Misfiled under lib/demo/ by history; allowlisted rather than " +
      "moved because moving it is a rename with its own blast radius.",
  ],
]);

test("no signed-in route reaches a fixture module under lib/demo/", () => {
  const entrypoints = routeEntrypoints(join(WEB_ROOT, "app/(app)/(protected)"));
  entrypoints.push(join(WEB_ROOT, "app/(app)/layout.tsx"));

  const { hits, closure } = demoModulesReached(WEB_ROOT, entrypoints);

  // The walk actually walked. Without this, a resolver that quietly returned
  // null for every specifier would report zero fixture modules and read as a
  // pass — the failure mode every other census in this repo is guarded against.
  assert.ok(
    closure.size > 50,
    `the import closure is only ${closure.size} modules; the walk did not resolve. ` +
      "A zero-hit result from a walk that went nowhere is not a pass.",
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
