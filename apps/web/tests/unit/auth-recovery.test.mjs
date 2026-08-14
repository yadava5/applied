/**
 * The password-reset request must answer identically for an address that has
 * an account and one that does not — and the new password must be judged by
 * the rules `/signup` already enforces, not by a second standard.
 *
 * The first property is the one this feature is usually built wrong on, and it
 * is not observable from the outside: both cases render "check your inbox", so
 * a test that only asserts the happy path passes whether or not the leak is
 * there. What distinguishes them is what Supabase hands back —
 *
 *   - an unknown address: `{ data: {}, error: null }`, a plain 200;
 *   - a known address asked twice: `{ error: { status: 429, message:
 *     "For security purposes, you can only request this after 51 seconds" } }`,
 *     because the 60-second window on `/auth/v1/recover` is per USER and can
 *     only fire for an address that has one;
 *   - a blocked or failed fetch: a thrown `TypeError`.
 *
 * — so the test drives the real code path with a fake sender that produces
 * each of those, and asserts the three outcomes are byte-identical. Flip
 * `requestPasswordReset` to pass the provider's answer through and every one
 * of these goes red; that was checked by hand, not assumed.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  RESET_EMAIL_SENT_NOTICE,
  RESEND_COOLDOWN_SECONDS,
  remainingCooldown,
  requestPasswordReset,
} from "../../lib/auth/recovery.ts";
import {
  SIGNUP_MIN_PASSWORD,
  credentialProblem,
  emailProblem,
  newPasswordProblem,
  passwordProblem,
} from "../../lib/auth/credentials.ts";
import {
  RECOVERY_MARKER_PATH,
  RECOVERY_MARKER_VALUE,
  expiredRecoveryMarkerCookieOptions,
  hasRecoveryMarker,
  recoveryMarkerCookieOptions,
} from "../../lib/auth/recoverySession.ts";

/** What Supabase answers for an address with no account behind it. */
const unknownAddress = async () => ({ data: {}, error: null });

/**
 * What it answers the second time for an address that DOES have one. The
 * 60-second window is documented as "before a new request is allowed to the
 * same user" (supabase.com/docs/guides/auth/rate-limits), so this response is
 * itself proof the account exists.
 */
const knownAddressRateLimited = async () => ({
  data: null,
  error: {
    status: 429,
    code: "over_email_send_rate_limit",
    message: "For security purposes, you can only request this after 51 seconds",
  },
});

/** What a CSP block or an offline browser produces: a rejection, not a value. */
const fetchFailed = async () => {
  throw new TypeError("Failed to fetch");
};

test("the same answer for an unknown address, a known one, and a failure", async () => {
  const unknown = await requestPasswordReset("nobody@example.invalid", unknownAddress);
  const known = await requestPasswordReset("real@example.invalid", knownAddressRateLimited);
  const failed = await requestPasswordReset("real@example.invalid", fetchFailed);

  assert.deepEqual(unknown, known);
  assert.deepEqual(known, failed);
  assert.equal(unknown.notice, RESET_EMAIL_SENT_NOTICE);
});

test("the outcome has nowhere to put the provider's answer", () => {
  // A property of the SHAPE, not of one code path: with a single field that is
  // a constant, a component cannot leak what it never receives. If a field is
  // ever added here, this fails and the leak gets argued about on purpose.
  return requestPasswordReset("real@example.invalid", knownAddressRateLimited).then(
    (outcome) => {
      assert.deepEqual(Object.keys(outcome), ["notice"]);
      const serialised = JSON.stringify(outcome);
      for (const leak of ["429", "51 seconds", "rate_limit", "security purposes"]) {
        assert.equal(
          serialised.includes(leak),
          false,
          `the outcome carries ${JSON.stringify(leak)} from the provider`,
        );
      }
    },
  );
});

test("the notice describes no particular account", () => {
  // "we sent you a link" vs "no account found" is the leak with good manners.
  assert.match(RESET_EMAIL_SENT_NOTICE, /if an account exists/i);
  for (const forbidden of [/no account/i, /not found/i, /doesn.t exist/i, /we sent you/i]) {
    assert.equal(
      forbidden.test(RESET_EMAIL_SENT_NOTICE),
      false,
      `the notice asserts something about the address: ${forbidden}`,
    );
  }
});

test("the address reaches the sender trimmed, exactly once", async () => {
  const seen = [];
  await requestPasswordReset("  padded@example.invalid  ", async (address) => {
    seen.push(address);
    return { data: {}, error: null };
  });
  assert.deepEqual(seen, ["padded@example.invalid"]);
});

test("a malformed address is caught by the same check the other two forms run", () => {
  // The page runs `emailProblem` before it calls `requestPasswordReset`, so a
  // typo costs nothing. It is identical for every address and therefore leaks
  // nothing — and it is the SAME predicate, so its wording cannot drift from
  // /login's.
  assert.deepEqual(emailProblem(""), {
    field: "email",
    message: "Enter your email address.",
  });
  assert.deepEqual(emailProblem("not-an-email"), {
    field: "email",
    message: "That doesn’t look like an email address.",
  });
  assert.equal(emailProblem("  ayush@example.com  "), null);
  assert.deepEqual(
    emailProblem("not-an-email"),
    credentialProblem("not-an-email", "longenoughpassword", SIGNUP_MIN_PASSWORD),
  );
});

test("the new password is judged by signup's floor, with signup's sentence", () => {
  // One implementation, one message. Derived from the shared predicate rather
  // than restated, so a change to either has to change both.
  assert.deepEqual(newPasswordProblem("1234567", "1234567"), {
    field: "password",
    message: passwordProblem("1234567", SIGNUP_MIN_PASSWORD).message,
  });
  assert.match(newPasswordProblem("1234567", "1234567").message, /at least 8 characters/);
  // The login floor of 6 must NOT be what applies to a password being chosen.
  assert.notEqual(newPasswordProblem("123456", "123456"), null);
  assert.equal(newPasswordProblem("12345678", "12345678"), null);
});

test("the confirmation is an additional rule, not part of the floor", () => {
  // An empty form names the password, not the confirmation.
  assert.deepEqual(newPasswordProblem("", ""), {
    field: "password",
    message: "Enter your password.",
  });
  // Too short AND mismatched: still the password, because focus goes there.
  assert.equal(newPasswordProblem("abc", "xyz")?.field, "password");
  // Long enough but mistyped: now the confirmation.
  assert.deepEqual(newPasswordProblem("correct horse", "correct hoarse"), {
    field: "confirmation",
    message: "Those passwords don’t match.",
  });
  // Whitespace is a legitimate password character and is never trimmed away.
  assert.equal(newPasswordProblem("        ", "        "), null);
  assert.equal(newPasswordProblem("password ", "password")?.field, "confirmation");
});

test("the resend cooldown counts down whole seconds and floors at zero", () => {
  const sentAt = 1_000_000;
  assert.equal(remainingCooldown(sentAt, sentAt), RESEND_COOLDOWN_SECONDS);
  assert.equal(remainingCooldown(sentAt, sentAt + 1_000), RESEND_COOLDOWN_SECONDS - 1);
  // A part-second remaining still reads as a second, never as 0.
  assert.equal(remainingCooldown(sentAt, sentAt + 59_500), 1);
  assert.equal(remainingCooldown(sentAt, sentAt + 60_000), 0);
  // Past the window, and a clock that jumped backwards, both clamp.
  assert.equal(remainingCooldown(sentAt, sentAt + 600_000), 0);
  assert.equal(remainingCooldown(sentAt, sentAt - 5_000, 1), 6);
});

test("the cooldown is no longer than the window Supabase enforces per user", () => {
  // Waiting longer than GoTrue does would look like the product is broken;
  // waiting less would let the form spend a request that is going to 429.
  assert.equal(RESEND_COOLDOWN_SECONDS, 60);
});

/**
 * The gate on `/reset-password`: a session is not enough, the browser must
 * also hold the marker that only a completed recovery exchange writes.
 */
test("only the exact marker value counts as proof", () => {
  assert.equal(hasRecoveryMarker(RECOVERY_MARKER_VALUE), true);
  // Truthiness would accept every one of these. A cookie left under this name
  // by anything other than the callback route is not proof of a recovery.
  for (const notProof of [undefined, null, "", "0", "false", "true", "yes", "11", " 1"]) {
    assert.equal(
      hasRecoveryMarker(notProof),
      false,
      `${JSON.stringify(notProof)} must not read as a completed recovery`,
    );
  }
});

test("the marker is unreadable by script, scoped, and short-lived", () => {
  const inProduction = recoveryMarkerCookieOptions(true);
  // httpOnly is what stops an injected script forging or reading the proof.
  assert.equal(inProduction.httpOnly, true);
  assert.equal(inProduction.secure, true);
  // Lax, not Strict: the browser arrives from Supabase's domain, a cross-site
  // top-level navigation. Strict would drop the cookie on exactly the request
  // that sets it — the flow would be dead and look like an expired link.
  assert.equal(inProduction.sameSite, "lax");
  // Sent to the one page that consults it, and nowhere else in the app.
  assert.equal(inProduction.path, RECOVERY_MARKER_PATH);
  assert.equal(inProduction.path, "/reset-password");
  assert.ok(inProduction.maxAge > 0 && inProduction.maxAge <= 15 * 60);

  // `secure` is the only thing that may differ outside production, and only
  // because a local `next start` serves plain HTTP.
  const local = recoveryMarkerCookieOptions(false);
  assert.equal(local.secure, false);
  assert.deepEqual({ ...local, secure: true }, inProduction);
});

test("expiring the marker keeps every attribute except its lifetime", () => {
  // A Set-Cookie that clears one must match name, path and domain or the
  // browser keeps the original and the proof outlives its single use.
  for (const isProduction of [true, false]) {
    const expired = expiredRecoveryMarkerCookieOptions(isProduction);
    assert.equal(expired.maxAge, 0);
    assert.deepEqual(
      { ...expired, maxAge: recoveryMarkerCookieOptions(isProduction).maxAge },
      recoveryMarkerCookieOptions(isProduction),
    );
  }
});
