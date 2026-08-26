/**
 * Unit tests for the Gmail connect outcome notice (`lib/gmail/notices.ts`).
 *
 * WHY THIS MAP MOVED (#510). It lived inside the Settings route, which was
 * right while Settings was the only page a Gmail callback could land on. A
 * consent chained off a first Google sign-in now returns to `/dashboard`
 * instead, so a second copy would be two copies of the sentence a user reads
 * at the most consequential moment in the product — free to drift, with
 * nothing to notice when they did.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { GMAIL_NOTICES, NOTICE_TONE_CLASS, gmailNoticeFor } from "../../lib/gmail/notices.ts";

/** Every outcome token the backend's `_web_redirect` can emit. */
const BACKEND_OUTCOMES = ["connected", "disconnected", "error", "auth", "unavailable", "capacity"];

test("every outcome the backend can send has something to say", () => {
  for (const flag of BACKEND_OUTCOMES) {
    const notice = gmailNoticeFor(flag);
    assert.ok(notice, `no notice for the backend outcome "${flag}"`);
    assert.ok(notice.text.length > 0);
    assert.ok(notice.tone in NOTICE_TONE_CLASS, `tone "${notice.tone}" has no class`);
  }
});

/**
 * The flag is a URL parameter and anyone can type one. Inventing an outcome
 * for a value the backend never emits would put words in the product's mouth
 * about something that did not happen.
 */
test("an unknown or absent flag says nothing at all", () => {
  for (const junk of [undefined, null, "", "connected!", "CONNECTED", "<script>", "0", "true"]) {
    assert.equal(
      gmailNoticeFor(junk),
      null,
      `${JSON.stringify(junk)} produced a notice it should not have`,
    );
  }
});

test("a failure never reads as a success", () => {
  for (const flag of ["error", "auth"]) {
    assert.equal(gmailNoticeFor(flag).tone, "error");
  }
  assert.equal(gmailNoticeFor("connected").tone, "ok");
});

/**
 * The capacity notice is the only one asking the reader to do something
 * outside the product, and it has to: Google caps how many people this app may
 * ever connect and that number cannot be raised on request, so "try again
 * later" would be false. Losing the address turns a refusal into a dead end.
 */
test("the beta-capacity notice keeps its contact address and its alternative", () => {
  const text = gmailNoticeFor("capacity").text;
  assert.match(text, /@/, "the capacity notice lost the address to appeal to");
  assert.match(text, /import/i, "the capacity notice lost the route that needs no Google account");
});

/**
 * WIRING. Everything above passes against a map nothing imports. These assert
 * that both landing pages actually render the shared component — which is the
 * whole point of extracting it.
 */
test("TRIPWIRE: both pages a callback can land on render the shared notice", () => {
  const read = (p) => readFileSync(new URL(`../../${p}`, import.meta.url), "utf8");

  for (const page of [
    "app/(app)/(protected)/settings/page.tsx",
    "app/(app)/(protected)/dashboard/page.tsx",
  ]) {
    const source = read(page);
    assert.match(source, /<GmailNotice\s+flag=/, `${page} does not render GmailNotice`);
  }

  // The dashboard has TWO branches a chained user can land in, and the EMPTY
  // one is the branch that actually matters: someone who just signed up and
  // connected has nothing filed yet. Shipping the notice on the populated
  // branch alone would leave it invisible to every new account — which is the
  // only population this feature exists for.
  const dashboard = read("app/(app)/(protected)/dashboard/page.tsx");
  assert.equal(
    dashboard.match(/<GmailNotice\s+flag=/g)?.length,
    2,
    "the dashboard renders the notice in only one of its two branches",
  );

  // ...and the map must not have been copied back into a page.
  for (const page of [
    "app/(app)/(protected)/settings/page.tsx",
    "app/(app)/(protected)/dashboard/page.tsx",
  ]) {
    assert.doesNotMatch(
      read(page),
      /Gmail connected\. Applied can now read/,
      `${page} holds its own copy of the notice text again`,
    );
  }
});

test("the map is not empty, which every assertion above would tolerate", () => {
  assert.ok(Object.keys(GMAIL_NOTICES).length >= BACKEND_OUTCOMES.length);
});
