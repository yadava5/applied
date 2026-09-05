/**
 * The MOUNT — the hop between the proxy and the copy, which nothing executed.
 *
 * WHY THIS FILE EXISTS. `sync-failure-detail`, `sync-failure-note` and
 * `sync-proxy-relays-detail` cover three of the four hops in #848 and every
 * one of them was proven to red under a mutation. They cover every file
 * except the one that wires them together, and the survivor is embarrassing:
 * replacing BOTH call sites with
 *
 *     detail: null,
 *
 * typechecks, passes all 18 of those tests, passes the whole 905-test suite,
 * and puts the product back exactly where #848 found it — one hop later.
 * Measured, not imagined.
 *
 * `SyncBar.tsx` imports `next/link` and `next/navigation`, so it cannot be
 * rendered here at all; this reads its AST instead. That is a weaker
 * instrument than execution and it is named as such — the durable version is
 * a Playwright pass against a demo transport that can fail, which no e2e does
 * today. Until that exists, this is what stands between the mount and silence.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import { readSource } from "./helpers/renderTsx.mjs";
import {
  callsTo,
  enclosingThenBranch,
  jsxElements,
  objectArgument,
  parseTsx,
  properties,
  textOf,
} from "./helpers/subtitleWiring.mjs";

const SYNC_BAR = "components/dashboard/SyncBar.tsx";

/** Every `setPhase({ kind: "failed", … })` in the file, as its property map. */
function failedPhases(sourceFile) {
  const phases = [];
  for (const call of callsTo(sourceFile, "setPhase")) {
    const object = objectArgument(call);
    if (object === null) continue;
    const props = properties(object);
    if (props === null) continue;
    const kind = props.get("kind");
    if (kind !== undefined && textOf(kind) === '"failed"') phases.push(props);
  }
  return phases;
}

test("both failure paths ask what the reader may be shown, and pass the status", () => {
  // THE SURVIVOR THIS FILE EXISTS FOR. `detail: null` at both sites is green
  // everywhere else. MUTATION: either site back to `null`, or to
  // `backendSyncDetail(res.body)` without the status -> red here.
  //
  // The status argument is not decoration: the proxy route flattens EVERY
  // failure kind into the same `detail` key, so a 429 arrives as
  // `{detail:"rate_limited"}` and status is the only discriminator left.
  const sourceFile = parseTsx(SYNC_BAR);
  const phases = failedPhases(sourceFile);

  assert.equal(
    phases.length,
    2,
    `expected the plain sync and the windowed scan to be the two failure paths, found ${phases.length}`,
  );

  for (const props of phases) {
    const detail = props.get("detail");
    assert.ok(detail !== undefined, "a failed phase is set without a `detail` at all");
    const rendered = textOf(detail);
    assert.match(
      rendered,
      /^dashboardSyncDetail\(/,
      `a failed phase builds its detail as \`${rendered}\` — the status guard is bypassed`,
    );
    assert.match(
      rendered,
      /res\.status/,
      `\`${rendered}\` does not pass the status, so a 429's machine token renders as prose`,
    );
    assert.match(rendered, /res\.body/, `\`${rendered}\` does not read the response body`);
  }
});

test("the note is mounted inside the failed branch, reading the phase's own detail", () => {
  // MUTATION: move the element into the `receipt` branch, or give it a literal
  // -> red. A detail rendered from a success phase IS the collapse #643 named.
  const sourceFile = parseTsx(SYNC_BAR);
  const mounted = jsxElements(sourceFile, "SyncFailureNote");

  assert.equal(mounted.length, 1, `expected exactly one SyncFailureNote, found ${mounted.length}`);

  const branch = enclosingThenBranch(mounted[0]);
  assert.ok(branch !== null, "SyncFailureNote is no longer inside an `if` at all");
  // EQUALITY, not a match. A substring assertion passes a WIDENED condition —
  // `phase.kind === "receipt" || phase.kind === "failed"` contains the needle
  // and mounts the failure copy on a success phase, which is the collapse.
  // Measured: that mutation survived the `match` form of this assertion.
  //
  // The discriminated union is the stronger guard and catches it first — the
  // widened branch fails `tsc` with two TS2339s, because `detail` and
  // `notConnected` do not exist on the receipt phase. This assertion is the
  // one that names WHY when it happens, and it holds if the union is ever
  // loosened.
  assert.equal(
    textOf(branch.expression),
    'phase.kind === "failed"',
    `SyncFailureNote is mounted under \`${textOf(branch.expression)}\`, not on the failed phase alone`,
  );

  const attributes = new Map(
    mounted[0].attributes.properties
      .filter((p) => p.name !== undefined && p.initializer !== undefined)
      .map((p) => [textOf(p.name), textOf(p.initializer)]),
  );
  assert.equal(
    attributes.get("detail"),
    "{phase.detail}",
    `the note is given \`${attributes.get("detail")}\` rather than the phase's own detail`,
  );
  assert.equal(attributes.get("op"), "{phase.op}");
});

test("the failure still speaks as a failure: an alert region, in the reject colour", () => {
  // The valence dimension unit markup cannot see (#848's "under a green tick").
  // MUTATION: role="status", or the colour token swapped for a success one ->
  // red. This is a source pin because the element lives in a file no harness
  // here can render; the executable version is the e2e that does not exist yet.
  const source = readSource(SYNC_BAR);
  const region = source.match(/<p\s+role="alert"\s+className=\{`([^`]*)`\}/);

  assert.ok(region !== null, "the persistent alert region is gone or no longer a <p role=alert>");
  assert.match(
    region[1],
    /text-reject-ink/,
    `the alert renders in \`${region[1]}\` — a failure must not be announced in a success colour`,
  );
  assert.match(
    source,
    /role="alert"[\s\S]{0,200}\{alertContent\}/,
    "the alert region no longer renders alertContent, so the failure copy has no announced home",
  );
});
