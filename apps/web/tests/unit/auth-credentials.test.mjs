/**
 * The credential checks both auth forms run before the network
 * (`lib/auth/credentials.ts`).
 *
 * What is asserted here is asserted for /login and /signup at once, because
 * both pages call the same predicate. The properties that matter:
 *  - nothing empty, nothing malformed, ever reaches Supabase — the defect was
 *    that `noValidate` made `required` / `type="email"` / `minLength` inert
 *    and NOTHING replaced them, so an empty submit fired a real
 *    POST /auth/v1/token;
 *  - the two password floors stay different on purpose (6 on login so an old
 *    account can still sign in, 8 on signup because the hint promises 8);
 *  - the email check rejects the typos a person actually makes without
 *    rejecting an address they actually own;
 *  - a password is never trimmed, an email always is.
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  LOGIN_MIN_PASSWORD,
  SIGNUP_MIN_PASSWORD,
  credentialProblem,
  isValidEmail,
} from "../../lib/auth/credentials.ts";

test("the two floors are deliberately different, and in the right order", () => {
  assert.equal(LOGIN_MIN_PASSWORD, 6);
  assert.equal(SIGNUP_MIN_PASSWORD, 8);
  assert.ok(LOGIN_MIN_PASSWORD < SIGNUP_MIN_PASSWORD);
});

test("isValidEmail: the shapes a real address has", () => {
  for (const good of [
    "a@b.co",
    "ayush@example.com",
    "first.last@sub.domain.example.org",
    "user+tag@example.co.uk",
    "UPPER@EXAMPLE.COM",
    "  padded@example.com  ",
  ]) {
    assert.equal(isValidEmail(good), true, `should accept ${JSON.stringify(good)}`);
  }
});

test("isValidEmail: the typos that used to cost a request", () => {
  for (const bad of [
    "",
    "   ",
    "not-an-email",
    "@example.com",
    "user@",
    "user@example",
    "user@.com",
    "user@example.",
    "user@@example.com",
    "user name@example.com",
    "user@exa mple.com",
    "user@example..com",
  ]) {
    assert.equal(isValidEmail(bad), false, `should reject ${JSON.stringify(bad)}`);
  }
});

test("isValidEmail: an address longer than RFC 5321 allows is refused", () => {
  // 254 is the ceiling on the whole address, so the boundary is exercised on
  // both sides rather than asserted from one wildly long string.
  const domain = "@example.com"; // 12 characters
  assert.equal(isValidEmail(`${"a".repeat(254 - domain.length)}${domain}`), true);
  assert.equal(isValidEmail(`${"a".repeat(255 - domain.length)}${domain}`), false);
});

test("credentialProblem: the exact submits measured against the live deployment", () => {
  // Empty form — fired POST /auth/v1/token, showed nothing.
  assert.deepEqual(credentialProblem("", "", LOGIN_MIN_PASSWORD), {
    field: "email",
    message: "Enter your email address.",
  });
  // not-an-email / notarealpassword — fired the same POST.
  assert.deepEqual(credentialProblem("not-an-email", "notarealpassword", LOGIN_MIN_PASSWORD), {
    field: "email",
    message: "That doesn’t look like an email address.",
  });
  // A well-formed address with a 3-character password — fired it too.
  assert.deepEqual(credentialProblem("test@example.invalid", "ab1", LOGIN_MIN_PASSWORD), {
    field: "password",
    message: "Password must be at least 6 characters.",
  });
  // /signup accepted a malformed email as long as the password was long enough.
  assert.deepEqual(credentialProblem("not-an-email", "longenoughpassword", SIGNUP_MIN_PASSWORD), {
    field: "email",
    message: "That doesn’t look like an email address.",
  });
});

test("credentialProblem: one problem at a time, in reading order", () => {
  // Both fields wrong: the email is named first, because that is the field
  // focus moves to and the form has a single alert region.
  assert.equal(credentialProblem("nope", "ab", SIGNUP_MIN_PASSWORD)?.field, "email");
  // Email fixed, password still short: now the password is named.
  assert.equal(credentialProblem("a@b.co", "ab", SIGNUP_MIN_PASSWORD)?.field, "password");
  // A missing password is not "too short" — it says what to do.
  assert.deepEqual(credentialProblem("a@b.co", "", LOGIN_MIN_PASSWORD), {
    field: "password",
    message: "Enter your password.",
  });
});

test("credentialProblem: the floors are enforced exactly, not approximately", () => {
  assert.equal(credentialProblem("a@b.co", "12345", LOGIN_MIN_PASSWORD)?.field, "password");
  assert.equal(credentialProblem("a@b.co", "123456", LOGIN_MIN_PASSWORD), null);
  assert.equal(credentialProblem("a@b.co", "1234567", SIGNUP_MIN_PASSWORD)?.field, "password");
  assert.equal(credentialProblem("a@b.co", "12345678", SIGNUP_MIN_PASSWORD), null);
  assert.match(
    credentialProblem("a@b.co", "short", SIGNUP_MIN_PASSWORD).message,
    /at least 8 characters/,
  );
});

test("credentialProblem: a password is never trimmed", () => {
  // Whitespace is a legitimate password character. Both of these are exactly
  // six characters long and clear the login floor; trimming would measure them
  // as zero and two and refuse a password the account really has.
  assert.equal(credentialProblem("a@b.co", "      ", LOGIN_MIN_PASSWORD), null);
  assert.equal(credentialProblem("a@b.co", "  ab  ", LOGIN_MIN_PASSWORD), null);
  // …and the same six characters are still short of the signup floor.
  assert.equal(credentialProblem("a@b.co", "  ab  ", SIGNUP_MIN_PASSWORD)?.field, "password");
});

test("credentialProblem: valid credentials produce no problem at all", () => {
  assert.equal(credentialProblem("ayush@example.com", "correct horse", LOGIN_MIN_PASSWORD), null);
  assert.equal(credentialProblem("  ayush@example.com  ", "correct horse", SIGNUP_MIN_PASSWORD), null);
});
