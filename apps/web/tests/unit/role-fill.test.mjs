/**
 * Unit tests for filling in a role by hand — issue #72.
 *
 * Every application filed from Gmail lands with `position: ""` and always will:
 * the Gmail path fetches `format=metadata` so no body is ever read, and the ATS
 * acknowledgement subjects it does read name the employer rather than the role
 * ("Thanks for applying to Supabase"). The product's answer is to let the user
 * type it, which makes two things testable at this level and worth pinning:
 *
 *  1. WHICH endpoint the control hits. The role write is its own PUT, not a
 *     field smuggled into the status PATCH — the backend's `ApplicationStatusUpdate`
 *     has no `extra="forbid"`, so an unknown key there would be silently dropped
 *     and the UI would report a save that never happened.
 *  2. That a blank draft CLEARS rather than storing whitespace. #72 exists to
 *     stop invented data reaching this field, and a row that renders as filled
 *     because it holds three spaces is the same lie in a quieter font.
 *
 * The control's markup is not asserted here — `ApplicationDetail.tsx` needs
 * `next/navigation` and browser hooks, which `renderTsx` deliberately does not
 * provide. That surface is verified in a real browser.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import { roleChangeRequest } from "../../lib/dashboard/rowActions.ts";
import {
  MAX_ROLE_LENGTH,
  ROLE_ABSENT_FROM_MAIL_HINT,
  ROLE_ABSENT_HINT,
  ROLE_ADD_LABEL,
  ROLE_CLEAR_HINT,
  ROLE_SAVE_FAILED,
  ROLE_TOO_LONG,
  normalizeRoleDraft,
  roleAbsentHint,
  roleDraftError,
  roleSourceLabel,
} from "../../lib/dashboard/role.ts";

// --- the request ------------------------------------------------------------

test("a role write is its own PUT, never a field on the status PATCH", () => {
  const req = roleChangeRequest(42, "Backend Engineer");
  assert.equal(req.path, "/api/applications/42/role");
  assert.equal(req.method, "PUT");
  assert.deepEqual(req.body, { role: "Backend Engineer" });
});

test("clearing sends an explicit null, not an omitted key", () => {
  const req = roleChangeRequest(42, null);
  assert.deepEqual(req.body, { role: null });
  assert.ok("role" in req.body, "the key must be present or the backend clears nothing");
});

// --- the draft --------------------------------------------------------------

test("a typed role is trimmed", () => {
  assert.equal(normalizeRoleDraft("  Backend Engineer  "), "Backend Engineer");
});

test("a blank draft normalizes to null — a clear, never stored whitespace", () => {
  for (const blank of ["", "   ", "\t", "\n  \t"]) {
    assert.equal(normalizeRoleDraft(blank), null, JSON.stringify(blank));
  }
});

test("interior spacing is left alone — job titles contain them", () => {
  assert.equal(
    normalizeRoleDraft("Software Development Engineer, AWS Data Services"),
    "Software Development Engineer, AWS Data Services",
  );
});

// --- refusals ---------------------------------------------------------------

test("a title past the backend's ceiling is refused before it is sent", () => {
  assert.equal(roleDraftError("x".repeat(MAX_ROLE_LENGTH)), null);
  assert.equal(roleDraftError("x".repeat(MAX_ROLE_LENGTH + 1)), ROLE_TOO_LONG);
});

test("the client ceiling is the one the backend actually enforces", () => {
  // `_MAX_ROLE_LEN` in backend/jobtracker/cloud/applications.py. A client limit
  // looser than the server's turns a 422 into an unexplained failure; tighter,
  // and the UI refuses something the API would have taken.
  assert.equal(MAX_ROLE_LENGTH, 200);
});

test("a blank draft is not an error — it is the clear", () => {
  assert.equal(roleDraftError("   "), null);
});

// --- provenance -------------------------------------------------------------

test("only a role the user actually typed is labelled as theirs", () => {
  assert.equal(roleSourceLabel("user"), "set by you");
  // Everything else came off the mail or from nowhere in particular, and
  // neither may be dressed up as the reader's own word.
  assert.equal(roleSourceLabel(null), null);
  assert.equal(roleSourceLabel(undefined), null);
  assert.equal(roleSourceLabel("mail"), null);
  assert.equal(roleSourceLabel("gmail"), null);
});

// --- the absence is explained only as far as the row supports ---------------

test("a mail-derived row may be told its mail named no role", () => {
  assert.equal(roleAbsentHint("gmail"), ROLE_ABSENT_FROM_MAIL_HINT);
  assert.equal(roleAbsentHint("gmail_user"), ROLE_ABSENT_FROM_MAIL_HINT);
});

test("a row with no mail behind it is told nothing about mail", () => {
  // `AddApplicationForm` files these by hand. Saying "your mail never named
  // one" here describes a message that does not exist — the same invention,
  // one layer over, that #72 exists to prevent.
  assert.equal(roleAbsentHint("manual"), ROLE_ABSENT_HINT);
  assert.notEqual(ROLE_ABSENT_HINT, ROLE_ABSENT_FROM_MAIL_HINT);
  assert.doesNotMatch(ROLE_ABSENT_HINT, /mail/i);
});

test("an unrecognised source is not evidence of mail", () => {
  for (const source of [null, undefined, "", "imap", "icloud"]) {
    assert.equal(roleAbsentHint(source), ROLE_ABSENT_HINT, String(source));
  }
});

// --- copy -------------------------------------------------------------------

test("nothing in the copy invents or implies a role", () => {
  for (const line of [ROLE_ADD_LABEL, ROLE_CLEAR_HINT, ROLE_SAVE_FAILED, ROLE_TOO_LONG, ROLE_ABSENT_HINT, ROLE_ABSENT_FROM_MAIL_HINT]) {
    assert.equal(typeof line, "string");
    assert.ok(line.length > 0);
    // The whole point of #72: no example title anywhere near this control can
    // be mistaken for a suggestion the product is making.
    assert.doesNotMatch(line, /software engineer/i, line);
  }
});

test("clearing does not read like a delete", () => {
  assert.doesNotMatch(ROLE_CLEAR_HINT, /delete|remove|erase/i);
});
