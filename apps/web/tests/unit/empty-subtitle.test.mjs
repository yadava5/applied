/**
 * Unit tests for the EMPTY board's sync-row subtitle (`lib/dashboard/boardPrefs.ts`).
 *
 * THE DEFECT. This line was built inline in the dashboard Server Component,
 * which `node --test` cannot import — so nothing gated it, and the demo twin,
 * which could not see it either, fell back to calling `buildSubtitle` with the
 * FULL fixture summary. `/demo/shell?empty=1` therefore rendered
 *
 *     17 filed · 14 open · 0 offers
 *
 * directly above "nothing filed yet", in the one harness state that exists to
 * model an empty board — and which the viewport-lock specs measure. Found by a
 * browser pass, not by a test, which is the point.
 *
 * ===========================================================================
 * WHAT THIS FILE GATES, AND WHAT IT DOES NOT (#550). READ THIS BEFORE TRUSTING
 * A GREEN RUN HERE.
 * ===========================================================================
 *
 * GATED — the builder's BEHAVIOUR. The four tests below call `emptySubtitle`
 * and assert on the string it returns. Those are real executable tests.
 *
 * GATED — the STRUCTURE of both call sites. The four `STRUCTURE:` tests parse
 * `dashboard/page.tsx` and `components/demo/DemoDashboard.tsx` with the
 * TypeScript compiler API (`helpers/subtitleWiring.mjs`) and assert that each
 * surface imports THIS builder, passes exactly the board's three inputs, binds
 * the result, hands THAT binding to `<SyncBar subtitle=…>`, and does it inside
 * the branch an empty board actually takes.
 *
 * These replaced a source-text `grep` (`assert.match(page, /emptySubtitle\(\{/)`)
 * which was green if the page called the helper with the wrong arguments,
 * discarded the return, called it in a branch never taken, or rendered a
 * different string beside it. This is a much stronger source check. It is
 * still a source check, not a behavioural one: nothing here renders the page.
 *
 * NOT GATED — the real `/dashboard` rendering. NO test in this repo renders
 * that page, in any suite. The only executable empty-board surface is the twin,
 * `/demo/shell?empty=1`, driven by `EMPTY_STATES` in `tests/e2e/shell.spec.ts`
 * (line 252 at the time of writing — the name is the durable half). So if the
 * signed-in page and the twin ever diverge in a way the tree below cannot see,
 * every gate here stays green — which is the "verify the real surface, not the
 * twin" shape, and is why this section is written out rather than left to be
 * rediscovered.
 *
 * WHY NOT — the three blockers, named so the next person does not re-derive
 * them. Closing this properly means an e2e that reaches the REAL `/dashboard`
 * in its empty state, and that needs all three at once:
 *
 *   1. a fake Supabase auth server for the fixture user to sign in against;
 *   2. a valid `@supabase/ssr` session cookie, in the exact chunked format the
 *      server client reads, or the request never reaches a signed-in render;
 *   3. a JWT the e2e's own FastAPI will accept. Production AND the test backend
 *      verify **ES256** — a hand-made token is rejected, and the page then
 *      renders its LOAD FAILURE branch. That is the trap: such a fixture looks
 *      like it works, reaches the wrong branch entirely, and would assert the
 *      empty subtitle against a screen that never builds one.
 *
 * That is the content of #188 and it is its own project, not a line in this
 * file. Do not add a token-forging shortcut here to make the gap look closed.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  attributeIdentifier,
  bindingFor,
  callsTo,
  enclosingThenBranch,
  enclosingWhenTrue,
  importedLocalName,
  isFalseLiteral,
  isIdentifierNamed,
  isStringLiteral,
  jsxElements,
  objectArgument,
  parseTsx,
  properties,
  readsABinding,
  testsBoardIsEmpty,
  textOf,
} from "./helpers/subtitleWiring.mjs";

import { emptySubtitle } from "../../lib/dashboard/boardPrefs.ts";

const base = { gmailState: "disconnected", scanCompleted: false, needsReview: 0 };

test("an empty board never claims filed applications", () => {
  for (const gmailState of ["connected", "disconnected", "unknown"]) {
    for (const scanCompleted of [true, false]) {
      for (const needsReview of [0, 1, 4]) {
        const line = emptySubtitle({ gmailState, scanCompleted, needsReview });
        // The exact shape of the regression: a non-zero filed count.
        assert.doesNotMatch(
          line,
          /\b[1-9]\d*\s+filed\b/,
          `an empty board reported filed applications: ${line}`,
        );
        assert.doesNotMatch(line, /\bopen\b|\boffers?\b/, `populated wording leaked: ${line}`);
      }
    }
  }
});

test("a failed probe is not reported as disconnected", () => {
  assert.match(emptySubtitle({ ...base, gmailState: "unknown" }), /unknown/);
  assert.doesNotMatch(emptySubtitle({ ...base, gmailState: "unknown" }), /nothing tracked/);
});

test("a connected mailbox distinguishes 'not scanned' from 'scanned and empty'", () => {
  const scanned = emptySubtitle({ ...base, gmailState: "connected", scanCompleted: true });
  const unscanned = emptySubtitle({ ...base, gmailState: "connected", scanCompleted: false });
  assert.notEqual(scanned, unscanned);
  assert.match(scanned, /detected/);
  assert.match(unscanned, /filed/);
});

test("held mail is counted, pluralised, and silent at zero", () => {
  assert.match(emptySubtitle({ ...base, needsReview: 1 }), /1 needs review/);
  assert.match(emptySubtitle({ ...base, needsReview: 4 }), /4 need review/);
  assert.doesNotMatch(emptySubtitle({ ...base, needsReview: 0 }), /review/);
});

/**
 * WIRING, both ways. Everything above passes against a helper neither surface
 * calls — which is precisely the state this replaced. The four tests below are
 * the structural half described at the top of the file; they are split by
 * question rather than by file so a red names which property of the wiring
 * broke, not merely "the tripwire".
 */
const PAGE = "app/(app)/(protected)/dashboard/page.tsx";
const TWIN = "components/demo/DemoDashboard.tsx";

/** The builder's whole input contract — no more, no fewer. */
const INPUTS = ["gmailState", "needsReview", "scanCompleted"];

/** The one definition both surfaces must be calling. */
const BUILDER_MODULE = "@/lib/dashboard/boardPrefs";

/**
 * The one `emptySubtitle(…)` call in a file, with its object argument read.
 *
 * The call is resolved THROUGH the import, not by name: every other assertion
 * below is satisfied by any identifier spelled `emptySubtitle`, so a file that
 * dropped the import and defined its own inline copy would pass all of them —
 * which is #513's defect exactly, one layer up.
 */
function soleCall(relativePath) {
  const sourceFile = parseTsx(relativePath);
  const local = importedLocalName(sourceFile, BUILDER_MODULE, "emptySubtitle");
  assert.ok(
    local !== null,
    `${relativePath} no longer imports emptySubtitle from ${BUILDER_MODULE} as a value — whatever it calls is not the shared builder`,
  );
  const calls = callsTo(sourceFile, local);
  assert.equal(
    calls.length,
    1,
    `${relativePath} should contain exactly one ${local}(…) call, found ${calls.length}`,
  );
  const [call] = calls;
  const object = objectArgument(call);
  assert.ok(
    object !== null,
    `${relativePath} calls emptySubtitle with something other than a single object literal: ${textOf(call)}`,
  );
  const props = properties(object);
  assert.ok(
    props !== null,
    `${relativePath}'s emptySubtitle argument uses a spread or a computed key, so its inputs cannot be read: ${textOf(object)}`,
  );
  return { sourceFile, call, props };
}

test("STRUCTURE: the real page passes the board's own three inputs to emptySubtitle", () => {
  const { props } = soleCall(PAGE);

  assert.deepEqual(
    [...props.keys()].sort(),
    INPUTS,
    "the real dashboard no longer passes exactly the empty builder's three inputs",
  );

  // A LITERAL here is the mutation the old grep could never see: `needsReview: 0`
  // keeps the characters `emptySubtitle({` intact while permanently silencing
  // the held-mail note the four tests above exist to prove.
  for (const name of INPUTS) {
    assert.ok(
      readsABinding(props.get(name)),
      `the real dashboard hard-codes \`${name}\` instead of reading it from the board: ${textOf(props.get(name))}`,
    );
  }
});

test("STRUCTURE: the real page's empty branch renders exactly what it built", () => {
  const { call } = soleCall(PAGE);

  // Built, not discarded.
  const binding = bindingFor(call);
  assert.ok(
    binding !== null,
    "the real dashboard calls emptySubtitle and throws the result away",
  );

  // Inside the branch an empty board actually takes — hoisting the call above
  // the `if` leaves every other assertion here green.
  const branch = enclosingThenBranch(call);
  assert.ok(
    branch !== null,
    "the real dashboard's emptySubtitle call is no longer inside an `if` branch at all",
  );
  assert.ok(
    testsBoardIsEmpty(branch.expression),
    `the real dashboard builds its empty subtitle under \`${textOf(branch.expression)}\`, not under \`state.total === 0\``,
  );

  // …and the SAME binding reaches the SyncBar IN THAT BRANCH. Scoping to the
  // branch is load-bearing: the page has three SyncBars and the populated one
  // also reads a local called `subtitle`, so a file-wide search would pass on
  // the wrong element.
  const bars = jsxElements(branch.thenStatement, "SyncBar");
  assert.equal(
    bars.length,
    1,
    `the empty branch should render exactly one SyncBar, found ${bars.length}`,
  );
  assert.equal(
    attributeIdentifier(bars[0], "subtitle"),
    binding,
    `the empty branch's SyncBar does not render \`${binding}\` — it is given a literal, or some other value`,
  );
});

test("STRUCTURE: the twin passes the same three inputs, pinned to the empty rail", () => {
  const { props } = soleCall(TWIN);

  assert.deepEqual(
    [...props.keys()].sort(),
    INPUTS,
    "the demo twin no longer passes exactly the empty builder's three inputs",
  );

  // The twin's first two ARE literals on purpose, and pinning them is stronger
  // than "not a literal": they mirror `EMPTY_RAIL`'s `connected: false` in
  // `DemoShell`, so header, rail and body describe ONE account rather than
  // three. If the rail's fixture ever changes, change these together — this
  // assertion is the reminder, not an obstacle.
  assert.ok(
    isStringLiteral(props.get("gmailState"), "disconnected"),
    `the twin's gmailState no longer matches EMPTY_RAIL's disconnected mailbox: ${textOf(props.get("gmailState"))}`,
  );
  assert.ok(
    isFalseLiteral(props.get("scanCompleted")),
    `the twin claims a completed scan on a board that has never synced: ${textOf(props.get("scanCompleted"))}`,
  );
  assert.ok(
    readsABinding(props.get("needsReview")),
    `the twin hard-codes needsReview, so \`?review=N\` stops reaching the subtitle: ${textOf(props.get("needsReview"))}`,
  );
});

test("STRUCTURE: the twin branches on `empty` and renders what that branch built", () => {
  const { sourceFile, call } = soleCall(TWIN);

  const binding = bindingFor(call);
  assert.ok(binding !== null, "the demo twin calls emptySubtitle and throws the result away");

  // The twin uses a conditional rather than an `if`; the call must sit on the
  // TRUE arm. #513 was exactly this branch missing — `buildSubtitle` ran
  // regardless of `empty`, so `?empty=1` printed "17 filed · 14 open · 0 offers"
  // above "nothing filed yet".
  const conditional = enclosingWhenTrue(call);
  assert.ok(
    conditional !== null,
    "the twin no longer chooses emptySubtitle on the true arm of a conditional",
  );
  assert.ok(
    isIdentifierNamed(conditional.condition, "empty"),
    `the twin's subtitle branch is guarded by \`${textOf(conditional.condition)}\`, not by \`empty\``,
  );
  const populated = importedLocalName(sourceFile, BUILDER_MODULE, "buildSubtitle");
  assert.ok(populated !== null, `the twin no longer imports buildSubtitle from ${BUILDER_MODULE}`);
  assert.equal(
    callsTo(conditional.whenFalse, populated).length,
    1,
    "the twin's populated arm no longer calls the signed-in page's own buildSubtitle",
  );

  const bars = jsxElements(sourceFile, "SyncBar");
  assert.equal(bars.length, 1, `the twin should render exactly one SyncBar, found ${bars.length}`);
  assert.equal(
    attributeIdentifier(bars[0], "subtitle"),
    binding,
    `the twin's SyncBar does not render \`${binding}\` — it is given a literal, or some other value`,
  );
});
