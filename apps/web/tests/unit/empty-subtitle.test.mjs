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
 * On the page those inputs are pinned by EXPRESSION, not merely by shape:
 * `gmailState` and `scanCompleted` must be the board's own bindings of those
 * names and `needsReview` must be `state.needsReview`. "Each value reads a
 * binding" was not enough — `scanCompleted: scanFailed`, `needsReview:
 * state.total` and a literal laundered through a `const` all read bindings and
 * all ship a wrong subtitle. The page is also asserted to hold the ONLY
 * `state.total === 0` test in the file, so a second empty-board return added
 * above the gated one cannot take a slice of empty boards somewhere else, and
 * to build the line unconditionally rather than under a `?:`.
 *
 * These replaced a source-text `grep` (`assert.match(page, /emptySubtitle\(\{/)`)
 * which was green if the page called the helper with the wrong arguments,
 * discarded the return, called it in a branch never taken, or rendered a
 * different string beside it. This is a much stronger source check. It is
 * still a source check, not a behavioural one: nothing here renders the page.
 *
 * NOT GATED — the real `/dashboard` rendering. No test RUN has ever rendered
 * that page. It is not that no test would: the session-gated specs
 * (`dashboard.spec.ts` among them) navigate to `/dashboard` and would render it
 * the day a session exists, but both e2e jobs boot against a placeholder
 * Supabase project, so every one of them has skipped on every run the suite has
 * ever done — see `tests/e2e/session.ts`, which counts the hole and makes it
 * greppable. The only executable empty-board surface is the twin,
 * `/demo/shell?empty=1`, driven by `EMPTY_STATES` in `tests/e2e/shell.spec.ts`
 * (line 252 at the time of writing — the name is the durable half). So if the
 * signed-in page and the twin ever diverge in a way the tree below cannot see,
 * every gate here stays green — which is the "verify the real surface, not the
 * twin" shape, and is why this section is written out rather than left to be
 * rediscovered.
 *
 * NOT GATED — two residual source shapes, named rather than chased:
 *
 *   - REASSIGNMENT after the binding. `let subtitle = emptySubtitle({…});
 *     subtitle = "";` satisfies every assertion below, because what a binding
 *     is worth at render time is a dataflow question and this is a source
 *     check. Catching it honestly needs the page executed, which is the same
 *     gap as the one above.
 *   - SHADOWING the import — keeping it and adding a block-scoped
 *     `const emptySubtitle = …` over it. That is LINT's job, and it does it:
 *     the import goes unused, and `@typescript-eslint/no-unused-vars` under
 *     `--max-warnings 0` fails `npm run lint` on it (measured; `tsc` and this
 *     suite both stay green, so lint is the only gate that sees it).
 *
 * WHY NOT — the three blockers, named so the next person does not re-derive
 * them. Closing this properly means an e2e that reaches the REAL `/dashboard`
 * in its empty state, and that needs all three at once:
 *
 *   1. a fake Supabase auth server for the fixture user to sign in against;
 *   2. a session cookie the `@supabase/ssr` server client will read back, or
 *      the request never reaches a signed-in render. Chunking is NOT the
 *      requirement — read `node_modules/@supabase/ssr/dist/main/utils/chunker.js`:
 *      `createChunks` emits a single cookie named exactly the storage key
 *      (`sb-<ref>-auth-token`) unless the URI-encoded value exceeds
 *      `MAX_CHUNK_SIZE` (3180), and `combineChunks` looks the unchunked name up
 *      FIRST, falling back to `<key>.0`, `<key>.1`, … only when it is absent.
 *      What is actually required is the storage key, holding the session JSON —
 *      either plain or `base64-`-prefixed base64url, since
 *      `decodeChunkedCookieValue` returns anything without that prefix as-is.
 *   3. a JWT the e2e's own FastAPI will accept — and the honest blocker is not
 *      that one cannot be forged. `backend/jobtracker/auth/supabase_jwt.py`
 *      accepts BOTH algorithms, dispatching on the token header: ES256 against
 *      a configured JWKS, HS256 against `settings.supabase_jwt_secret`. The
 *      backend's own pytest suite mints HS256 tokens today and they verify. So
 *      forging works, and that is precisely why it must not be used here: a
 *      token we mint ourselves certifies the verifier path and the key the
 *      FIXTURE chose, not the one a real session travels — a deployment that
 *      signs ES256 (`JOBTRACKER_SUPABASE_JWKS_URL`, see DEPLOY.md) never runs
 *      the shared-secret branch at all — so the test would prove something
 *      about a code path no user reaches.
 *      The half that IS an obstacle, and is verified against the page: a token
 *      the backend REJECTS lands in `state.kind === "auth"`, and the page
 *      returns its LOAD FAILURE branch at `state.kind !== "ok"` BEFORE
 *      `state.total === 0` is ever tested. Such a fixture looks like it works,
 *      reaches the wrong branch entirely, and asserts the empty subtitle
 *      against a screen that never builds one.
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
  emptyBoardTests,
  enclosingConditional,
  enclosingThenBranch,
  enclosingWhenTrue,
  importedLocalName,
  isFalseLiteral,
  isIdentifierNamed,
  isPropertyAccessOf,
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

  // RIGHT KEYS, WRONG VALUES. "Passes exactly the three inputs" and even
  // "each value reads a binding" are both satisfied by a call that reads the
  // WRONG three bindings, which is why each value is pinned to the one
  // expression the board actually holds:
  //
  //   scanCompleted: scanFailed   — reads a binding, typechecks, and inverts
  //     the fix the page's own comment above `scanFailed` exists to record: a
  //     connected user whose first sync errored reads "connected · no
  //     applications detected yet" directly above the SyncBar's failure alert.
  //   needsReview: state.total    — reads a binding, and is 0 by construction
  //     everywhere this branch runs, so the held-mail note the four tests
  //     above prove can never appear.
  //   needsReview: NONE           — a literal laundered through a `const`.
  //
  // Pinning identifiers makes a RENAME a red. That price is already paid in
  // this file — `testsBoardIsEmpty` hardcodes `state` and `total` — and a
  // rename that reds here is a two-word edit, while every mutation above ships
  // a wrong subtitle to the first screen a new account sees.
  assert.ok(
    isIdentifierNamed(props.get("gmailState"), "gmailState"),
    `the real dashboard's gmailState is not the board's own \`gmailState\`: ${textOf(props.get("gmailState"))}`,
  );
  assert.ok(
    isIdentifierNamed(props.get("scanCompleted"), "scanCompleted"),
    `the real dashboard's scanCompleted is not the board's own \`scanCompleted\`: ${textOf(props.get("scanCompleted"))}`,
  );
  assert.ok(
    isPropertyAccessOf(props.get("needsReview"), "state", "needsReview"),
    `the real dashboard's needsReview is not \`state.needsReview\`: ${textOf(props.get("needsReview"))}`,
  );
});

test("STRUCTURE: the real page's empty branch renders exactly what it built", () => {
  const { sourceFile, call } = soleCall(PAGE);

  // Built, not discarded.
  const binding = bindingFor(call);
  assert.ok(
    binding !== null,
    "the real dashboard calls emptySubtitle and throws the result away",
  );

  // Built UNCONDITIONALLY inside that branch. `bindingFor` walks out through a
  // ConditionalExpression because the twin genuinely needs that — it chooses
  // between the two builders with one — and the page inherits the allowance it
  // does not need: `const subtitle = state.needsReview > 0 ? emptySubtitle({…})
  // : ""` binds, reaches the SyncBar and sits in the empty branch, while every
  // empty board with nothing held renders no subtitle at all.
  const conditional = enclosingConditional(call);
  assert.equal(
    conditional,
    null,
    `the real dashboard builds its empty subtitle conditionally: ${conditional === null ? "" : textOf(conditional)}`,
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

  // …and that is the ONLY branch an empty board can take. Everything above is
  // about the branch the call is in and says nothing about a second one added
  // ABOVE it — `if (state.total === 0 && gmailState === "unknown") return
  // <SyncBar subtitle="0 filed" …>` returns a slice of empty boards to a
  // literal subtitle with every other assertion here green. The page's comment
  // at this branch records that this split shipped once and what it cost.
  // One test, one branch, one subtitle.
  const emptyTests = emptyBoardTests(sourceFile);
  assert.equal(
    emptyTests.length,
    1,
    `the real dashboard tests \`state.total === 0\` in ${emptyTests.length} places, so an empty board has more than one way out: ${emptyTests.map((node) => textOf(node.parent)).join(" | ")}`,
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
