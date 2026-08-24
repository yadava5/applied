/**
 * Where a completed sign-in lands (`lib/auth/postSignIn.ts`), and the wiring
 * that makes the decision unavoidable.
 *
 * WHY THIS IS A UNIT TABLE AND NOT AN E2E. The flow this governs ends on
 * Google's own consent screen. It is not drivable in CI at any effort — there
 * is no session in CI (#188), and Google consent is not automatable even if
 * there were. The branching is therefore extracted into a pure function so the
 * part that actually holds the logic is executable, and the round trip is
 * verified by hand. The PR says which half is which; this file is the half
 * that runs.
 *
 * THE DEFECT SHAPE THIS GUARDS AGAINST. `GoogleSignInButton` ALWAYS sets
 * `?redirect=`, defaulted to `/dashboard`. A decision keyed on "was a redirect
 * requested" would be false on every real Google sign-in — the chain would
 * never fire, and a test suite covering only the non-chaining rows would be
 * fully green while the feature did nothing. So the chaining row is asserted
 * explicitly, the button's coupling is pinned in source, and there is a
 * tripwire below asserting the table is not uniformly `/dashboard`.
 *
 * Run:  node --test tests/unit/post-sign-in-destination.test.mjs
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve as resolvePath } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  CHAINED_GMAIL_AUTHORIZE,
  destinationAfterSignIn,
  isFirstSignInOfAccount,
  providerOfThisSignIn,
} from "../../lib/auth/postSignIn.ts";
import { DEFAULT_REDIRECT } from "../../lib/auth/redirect.ts";

/** `apps/web` — this file sits at `tests/unit/`. */
const WEB_ROOT = resolvePath(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
);
const read = (rel) => readFileSync(resolvePath(WEB_ROOT, rel), "utf8");

/**
 * Every combination that reaches the decision, with the reason each one lands
 * where it does. `provider` x `gmail` x `requestedRedirect`, exhaustive over
 * the first two and covering both classes of the third.
 */
const TABLE = [
  // The one row the feature exists for.
  {
    name: "google + not connected + no stated destination -> chains",
    input: {
      provider: "google",
      gmail: "not_connected",
      isFirstSignIn: true,
      requestedRedirect: DEFAULT_REDIRECT,
    },
    expected: CHAINED_GMAIL_AUTHORIZE,
  },

  // `unknown` must behave like `connected`, NOT like `not_connected`. This is
  // the phase-1 defect restated: a failed probe is not evidence of absence.
  {
    name: "google + unknown (probe failed) -> dashboard, never a consent screen",
    input: {
      provider: "google",
      gmail: "unknown",
      isFirstSignIn: true,
      requestedRedirect: DEFAULT_REDIRECT,
    },
    expected: DEFAULT_REDIRECT,
  },
  {
    name: "google + already connected -> dashboard, no pointless re-consent",
    input: {
      provider: "google",
      gmail: "connected",
      isFirstSignIn: true,
      requestedRedirect: DEFAULT_REDIRECT,
    },
    expected: DEFAULT_REDIRECT,
  },

  // A password sign-in has not consented to anything Google-shaped.
  {
    name: "password + not connected -> dashboard",
    input: {
      provider: "other",
      gmail: "not_connected",
      isFirstSignIn: true,
      requestedRedirect: DEFAULT_REDIRECT,
    },
    expected: DEFAULT_REDIRECT,
  },
  {
    name: "password + unknown -> dashboard",
    input: {
      provider: "other",
      gmail: "unknown",
      isFirstSignIn: true,
      requestedRedirect: DEFAULT_REDIRECT,
    },
    expected: DEFAULT_REDIRECT,
  },
  {
    name: "password + connected -> dashboard",
    input: {
      provider: "other",
      gmail: "connected",
      isFirstSignIn: true,
      requestedRedirect: DEFAULT_REDIRECT,
    },
    expected: DEFAULT_REDIRECT,
  },

  // #503. The row this rule was added for: everything the chain wants is true
  // EXCEPT that the person has been here before. Without the rule they are
  // sent to Google's consent screen on this login and on every login after it,
  // which is the complaint the whole feature was built to answer, arriving
  // from the other direction.
  {
    name: "google + not connected + RETURN VISIT -> dashboard, never nagged",
    input: {
      provider: "google",
      gmail: "not_connected",
      isFirstSignIn: false,
      requestedRedirect: DEFAULT_REDIRECT,
    },
    expected: DEFAULT_REDIRECT,
  },
  // Its control. Same account state, same provider, ONLY the visit differs —
  // so a fix that silently disabled the chain outright cannot pass both.
  {
    name: "google + not connected + FIRST sign-in -> still chains",
    input: {
      provider: "google",
      gmail: "not_connected",
      isFirstSignIn: true,
      requestedRedirect: DEFAULT_REDIRECT,
    },
    expected: CHAINED_GMAIL_AUTHORIZE,
  },

  // A stated destination is a stated intent, and outranks the chain even in
  // the exact state the chain exists for.
  {
    name: "stated destination outranks the chain",
    input: {
      provider: "google",
      gmail: "not_connected",
      isFirstSignIn: true,
      requestedRedirect: "/settings",
    },
    expected: "/settings",
  },
  {
    name: "stated destination is honoured for a password sign-in too",
    input: {
      provider: "other",
      gmail: "connected",
      isFirstSignIn: true,
      requestedRedirect: "/import",
    },
    expected: "/import",
  },
];

test("destinationAfterSignIn: the whole decision table", () => {
  for (const row of TABLE) {
    assert.equal(destinationAfterSignIn(row.input), row.expected, row.name);
  }
});

test("TRIPWIRE: the table is not uniformly the default", () => {
  // Without this, deleting the chain entirely (`return DEFAULT_REDIRECT` as
  // the whole function body) would still pass six of eight rows, and a future
  // reader skimming green checkmarks would not notice the feature was gone.
  const outcomes = new Set(
    TABLE.map((row) => destinationAfterSignIn(row.input)),
  );
  assert.ok(
    outcomes.has(CHAINED_GMAIL_AUTHORIZE),
    "no row produces the chained destination — the feature is inert",
  );
  assert.ok(outcomes.size >= 3, "the decision collapsed to too few outcomes");
});

test("TRIPWIRE: the first-sign-in rule is load-bearing, not decoration", () => {
  // Deleting `if (!isFirstSignIn)` from the decision would leave every row of
  // the table above passing except one — and that one is easy to "fix" by
  // flipping its expectation. This states the property directly: the visit is
  // the ONLY thing that differs between these two, so they must not agree.
  const base = {
    provider: "google",
    gmail: "not_connected",
    requestedRedirect: DEFAULT_REDIRECT,
  };
  assert.notEqual(
    destinationAfterSignIn({ ...base, isFirstSignIn: true }),
    destinationAfterSignIn({ ...base, isFirstSignIn: false }),
    "a first sign-in and a return visit reach the same destination — " +
      "the rule that separates them is gone",
  );
});

/**
 * `isFirstSignInOfAccount`, pinned to REAL magnitudes rather than to numbers
 * chosen to agree with the threshold.
 *
 * The trap this avoids: seed `created_at` and `last_sign_in_at` a millisecond
 * apart for "signup" and a year apart for "return", and the test passes for
 * ANY window between them — including one so wide it says yes to everybody.
 * The two anchors below are the pair actually observed in this project's
 * `auth.users`: a Google account created by signing up (0.47s) and an account
 * that came back later (4h37m). The window has to sit between those two to be
 * worth anything, and the boundary rows below say where it sits.
 */
test("isFirstSignInOfAccount: the observed pair, and the boundary", () => {
  const created = "2026-08-24T06:02:58.561Z";

  assert.equal(
    isFirstSignInOfAccount({
      createdAt: created,
      lastSignInAt: "2026-08-24T06:02:59.030Z",
    }),
    true,
    "the real signup pair, 0.47s apart, must read as a first sign-in",
  );

  assert.equal(
    isFirstSignInOfAccount({
      createdAt: "2026-07-17T20:27:38.538Z",
      lastSignInAt: "2026-07-18T01:04:36.625Z",
    }),
    false,
    "the real return pair, 4h37m apart, must not",
  );

  // Where the line actually is. Without these two the window could be a day
  // wide and every assertion above would still hold.
  assert.equal(
    isFirstSignInOfAccount({
      createdAt: created,
      lastSignInAt: "2026-08-24T06:03:28.000Z",
    }),
    true,
    "29.4s is inside the window",
  );
  assert.equal(
    isFirstSignInOfAccount({
      createdAt: created,
      lastSignInAt: "2026-08-24T06:03:29.000Z",
    }),
    false,
    "30.4s is outside it — if this passes as `true` the window has been widened",
  );

  // A null last-sign-in is a first sign-in: see the note in the source about
  // GoTrue possibly returning the user as it stood before the write.
  assert.equal(
    isFirstSignInOfAccount({ createdAt: created, lastSignInAt: null }),
    true,
    "no recorded previous sign-in means this is the first",
  );

  // Unreadable input fails CLOSED — no chain — rather than sending someone who
  // did not just sign up to a consent screen.
  assert.equal(
    isFirstSignInOfAccount({ createdAt: undefined, lastSignInAt: created }),
    false,
    "a missing created_at must not read as a signup",
  );
  assert.equal(
    isFirstSignInOfAccount({ createdAt: created, lastSignInAt: "not a date" }),
    false,
    "an unparseable last_sign_in_at must not read as a signup",
  );
});

test("providerOfThisSignIn: either signal suffices, neither is required", () => {
  const google = { providerToken: "ya29.token", appMetadataProvider: "email" };
  assert.equal(
    providerOfThisSignIn(google),
    "google",
    "a fresh provider_token is the most direct evidence of an OAuth sign-in",
  );

  assert.equal(
    providerOfThisSignIn({
      providerToken: null,
      appMetadataProvider: "google",
    }),
    "google",
    "app_metadata alone must still chain — see the OR-not-AND note",
  );

  assert.equal(
    providerOfThisSignIn({
      providerToken: undefined,
      appMetadataProvider: "email",
      appMetadataProviders: ["email", "google"],
    }),
    "google",
    "a linked google identity counts",
  );

  assert.equal(
    providerOfThisSignIn({
      providerToken: null,
      appMetadataProvider: "email",
      appMetadataProviders: ["email"],
    }),
    "other",
    "a plain password account is not google",
  );

  assert.equal(
    providerOfThisSignIn({
      providerToken: null,
      appMetadataProvider: undefined,
      appMetadataProviders: null,
    }),
    "other",
    "absent metadata must not read as google",
  );
});

/**
 * The wiring half. `/callback` is a Route Handler and cannot be loaded under
 * `node --test`, so what is provable here is narrow but real: the sink still
 * routes through the decision, and the coupling that dictated the decision's
 * contract still exists.
 */
test("WIRING: the callback routes its destination through the decision", () => {
  const source = read("app/(auth)/callback/route.ts");

  assert.match(
    source,
    /destinationAfterSignIn\(/,
    "the callback no longer asks postSignIn where to go",
  );
  assert.match(
    source,
    /providerOfThisSignIn\(/,
    "the callback no longer derives the provider from the exchange",
  );
  assert.doesNotMatch(
    source,
    /return finish\(NextResponse\.redirect\(new URL\(nextPath, origin\)\)\)/,
    "the success exit went back to redirecting straight to nextPath, " +
      "which bypasses the decision entirely",
  );
});

test("WIRING: the callback derives the visit and gates the probe on it", () => {
  const source = read("app/(auth)/callback/route.ts");

  assert.match(
    source,
    /isFirstSignInOfAccount\(/,
    "the callback no longer asks whether this is a first sign-in",
  );
  assert.match(
    source,
    /isFirstSignIn,/,
    "the callback computes the visit but does not pass it to the decision",
  );
  // The probe is a network round trip to the backend on the auth hot path.
  // Gating it on the same condition as the chain is what makes a return visit
  // cost nothing at all rather than cost a call whose answer is discarded.
  assert.match(
    source,
    /provider === "google" && isFirstSignIn &&/,
    "the gmail status probe is no longer skipped on a return visit",
  );
});

test("WIRING: the probe cannot be read as a connection when it fails", () => {
  const source = read("app/(auth)/callback/route.ts");

  // The failure mode this forbids: `gmail = status.kind === "ok" && ...` style
  // collapsing, or defaulting the variable to "not_connected".
  assert.match(
    source,
    /GmailLinkState\s*=\s*"unknown"/,
    "the gmail state must START as unknown so every non-ok probe stays unknown",
  );
  assert.doesNotMatch(
    source,
    /GmailLinkState\s*=\s*"not_connected"/,
    "defaulting the probe to not_connected would chain on a backend hiccup",
  );
});

test("WIRING: a chained entry does not land a new user on a settings error", () => {
  const source = read("app/api/gmail/authorize/route.ts");

  assert.match(
    source,
    /from.*===\s*"signin"/,
    "the authorize route no longer distinguishes a chained entry",
  );
  assert.match(
    source,
    /new URL\("\/dashboard", origin\)/,
    "a chained failure must land on the dashboard, not /settings?gmail=",
  );
});

test("WIRING: the coupling that dictates the DEFAULT_REDIRECT contract", () => {
  const source = read("components/auth/GoogleSignInButton.tsx");

  // If this ever stops being true, `requestedRedirect` can become a nullable
  // "was it asked for" and the conflation in postSignIn.ts can be dropped.
  // Until then, a decision keyed on absence is a decision that never fires.
  assert.match(
    source,
    /callbackUrl\.searchParams\.set\("redirect",/,
    "GoogleSignInButton stopped always setting ?redirect= — revisit " +
      "PostSignInInput.requestedRedirect, which is shaped around it",
  );
});
