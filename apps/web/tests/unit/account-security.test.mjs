/**
 * The Profile card's derived account-security facts
 * (`components/settings/accountSecurity.ts`).
 *
 * The defect being pinned (#199): "sign-in method: Email & password" was a
 * hardcoded literal, false-reading for anyone who signs in with Google and
 * silent about a linked second identity. The production auth table holds all
 * three shapes — email-only (the demo account), and email+google (the owner's
 * account) — so every one of them is asserted here, plus the gate #202 hangs
 * off the same derivation: no `email` identity, no change-password control.
 */
import assert from "node:assert/strict";
import test from "node:test";

import { SIGNUP_MIN_PASSWORD } from "../../lib/auth/credentials.ts";
import { newPasswordProblem, summarizeSignIn } from "../../components/settings/accountSecurity.ts";

test("email-only identity: Email & password, singular label, password changeable", () => {
  const summary = summarizeSignIn({ identities: [{ provider: "email" }] });
  assert.equal(summary.value, "Email & password");
  assert.equal(summary.label, "sign-in method");
  assert.equal(summary.hasEmailIdentity, true);
});

test("google-only identity: Google, and NO password to change", () => {
  const summary = summarizeSignIn({ identities: [{ provider: "google" }] });
  assert.equal(summary.value, "Google");
  assert.equal(summary.label, "sign-in method");
  // The gate for #202 — offering change-password here would be a dead control.
  assert.equal(summary.hasEmailIdentity, false);
});

test("both linked (the measured production shape): both named, email first, plural label", () => {
  // auth.identities order is link order; google-first input proves the
  // summary sorts the password identity to the front rather than echoing.
  const summary = summarizeSignIn({
    identities: [{ provider: "google" }, { provider: "email" }],
  });
  assert.equal(summary.value, "Email & password, or Google");
  assert.equal(summary.label, "sign-in methods");
  assert.equal(summary.hasEmailIdentity, true);
});

test("no identities array: falls back to app_metadata.providers, never to a guess", () => {
  const summary = summarizeSignIn({
    identities: null,
    app_metadata: { providers: ["email", "google"] },
  });
  assert.equal(summary.value, "Email & password, or Google");
  assert.equal(summary.hasEmailIdentity, true);
});

test("nothing known: says Unknown and offers no password control — never the old literal", () => {
  for (const user of [null, {}, { identities: [], app_metadata: {} }]) {
    const summary = summarizeSignIn(user);
    assert.equal(summary.value, "Unknown");
    assert.equal(summary.hasEmailIdentity, false);
  }
});

test("an unmapped future provider is capitalised, not dropped", () => {
  const summary = summarizeSignIn({ identities: [{ provider: "github" }] });
  assert.equal(summary.value, "Github");
  assert.equal(summary.hasEmailIdentity, false);
});

test("newPasswordProblem enforces the signup floor it is handed, in reading order", () => {
  assert.equal(newPasswordProblem("", "", SIGNUP_MIN_PASSWORD)?.field, "password");
  const short = newPasswordProblem("a".repeat(SIGNUP_MIN_PASSWORD - 1), "", SIGNUP_MIN_PASSWORD);
  assert.equal(short?.field, "password");
  assert.match(short?.message ?? "", new RegExp(`${SIGNUP_MIN_PASSWORD}`));
  // Long enough but unconfirmed → the problem moves to the confirm field.
  const mismatch = newPasswordProblem("a".repeat(SIGNUP_MIN_PASSWORD), "b", SIGNUP_MIN_PASSWORD);
  assert.equal(mismatch?.field, "confirm");
  // Matching pair at the floor → no problem.
  const ok = "a".repeat(SIGNUP_MIN_PASSWORD);
  assert.equal(newPasswordProblem(ok, ok, SIGNUP_MIN_PASSWORD), null);
});

test("a password is never trimmed — whitespace counts toward the floor and the match", () => {
  const padded = "  pass word  "; // 13 chars with the spaces
  assert.equal(newPasswordProblem(padded, padded, SIGNUP_MIN_PASSWORD), null);
  assert.equal(
    newPasswordProblem(padded, padded.trim(), SIGNUP_MIN_PASSWORD)?.field,
    "confirm",
  );
});
