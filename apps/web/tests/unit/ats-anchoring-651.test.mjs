/**
 * A LOOKALIKE DOMAIN IS NOT AN ATS RELAY — IN THE BROWSER ENGINE TOO (#651).
 *
 * `backend/jobtracker/classifier/rules.py` matches an ATS sender ANCHORED: the
 * domain must BE a listed domain or a PROPER subdomain of one. That is #260,
 * and `is_ats_sender`'s docstring says why at length — unanchored containment
 * matched an ATS name anywhere in the host, so `greenhouse.io.mailgun.net` and
 * `notlever.co.example.com` read as ATS relays, and anyone with a registrar
 * could put themselves on a closed list.
 *
 * `lib/demo/rulesLayer.ts` never got that fix. It ran
 * `ATS_DOMAINS.some((a) => domain.includes(a))` until #651, four months after
 * the Python side was anchored. That matters here rather than only there
 * because `/import` is PUBLIC and unauthenticated (`components/import/
 * ImportMail.tsx` calls `classifyWithRules` with the parsed sender), so the
 * string is a stranger's, and on the 0.80 rung the +0.05 ATS bonus lands
 * exactly on 0.85 — `AUTO_FILE_GATE`, the value at which the server-side
 * pipeline MAY assert a hard status.
 *
 * WHAT THIS FILE IS. A divergence check, not a unit test: the case tables are
 * `LOOKALIKE_SENDERS` and `REAL_RELAY_SENDERS` from
 * `backend/tests/test_ingestion_hole_166.py`, ported host-for-host, so the
 * oracle is the Python engine's own table and not a reconstruction of it. It
 * is modelled on `rescission-divergence-417.test.mjs` and means the OPPOSITE:
 * 417 pins a divergence that is still open and asks to be deleted when it is
 * ported; this one pins a divergence that has been CLOSED. If it goes red, the
 * two engines have come apart again — fix the port, do not delete the file.
 *
 * WHAT IS EVIDENCE HERE AND WHAT IS NOT, kept apart the way the Python file
 * keeps it. The lookalike cases FAIL on the pre-#651 line (swap the operand
 * back to `domain.includes(a)` and they go red) and are the proof the defect
 * was real — with one exception, called out at its case: `sohire.comcast.net`
 * passes either way today, because the entry it worked through (`hire.com`)
 * was removed from the list in #348. It is here because the docstring names
 * it, as documentation. `myworkday.company.net` is its live equivalent.
 * The relay cases pass on the old line too. They are the anti-vacuity control
 * — a fix that anchors too hard and drops real relays is the same defect
 * pointing the other way.
 *
 * ADDRESSES AND `docs/TEST_DATA_POLICY.md`. Every case that can sit on a
 * domain that cannot route does. A lookalike is about a SUBSTRING, so the
 * labels around the ATS name are free: `greenhouse.io.mailhost.test` still
 * contains `greenhouse.io`, still is not it and still does not end in
 * `.greenhouse.io`, which is the whole discrimination. Two kinds of case
 * cannot be moved, and the reason is structural rather than lazy:
 *
 *   - a genuine-relay control has to MATCH a listed ATS domain, and no
 *     reserved name is one or is a subdomain of one;
 *   - `jobs@xgreenhouse.io` has to END with a listed name, which forces that
 *     name's real TLD.
 *
 * Every address in this file that is on a routable domain already appears
 * verbatim elsewhere in the tracked tree — most of them in
 * `backend/tests/test_ingestion_hole_166.py`, the table this one ports — so
 * nothing here is a string the repository had not already published. The
 * baseline was re-recorded deliberately in the commit that added this file.
 *
 * Run:  pnpm test:unit
 */

import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

import { importApp } from "./helpers/appModule.mjs";

const { classifyWithRules } = await importApp("lib/demo/rulesLayer.ts");

/** The list both engines read. `rules.json` is the browser port's copy of it. */
const ATS_DOMAINS = JSON.parse(
  readFileSync(new URL("../../lib/demo/rules.json", import.meta.url), "utf8"),
).ats_domains;

/**
 * The same list as a Set, and the reason is a static-analysis one.
 *
 * Every membership assertion below asks whether a string IS one of the listed
 * domains. That is exact membership and never substring containment — the
 * distinction this whole file exists to hold. Written as
 * `ATS_DOMAINS.includes("rippling.com")` it is `Array.prototype.includes`, but
 * the list arrives from `JSON.parse` with no type attached, and CodeQL's
 * `js/incomplete-url-substring-sanitization` cannot tell that call from
 * `String.prototype.includes`. It read the assertion as the very defect the
 * fix removed and raised a high-severity alert on it.
 *
 * `Set.prototype.has` cannot be misread, so the assertion keeps its meaning
 * with nothing suppressed. That choice is deliberate: an inline dismissal on
 * THIS file is what a future reader would most reasonably trust, and it would
 * also hide a real reintroduction of the substring bug behind a comment that
 * says the alert was already considered. Do not "simplify" this back to
 * `.includes(...)`.
 *
 * `backend/tests/test_ingestion_hole_166.py` resolves the identical Python
 * false positive the same way — a set-subset assertion rather than `in` — and
 * for the same reason. The two are worth reading together.
 */
const LISTED = new Set(ATS_DOMAINS);

/**
 * `pipeline.AUTO_FILE_GATE`. The threshold the bonus is measured against.
 *
 * Compared with `>=` and `<` rather than `===`, because the sum really is
 * `0.8 + 0.05 === 0.8500000000000001` in IEEE 754 — in Python too, which is
 * the point: the port reproduces the arithmetic, wart included.
 */
const AUTO_FILE_GATE = 0.85;

/**
 * A message that scores the 0.80 rung: `applied` at 4 points, margin 4.
 *
 * The rung is chosen and not incidental. 0.80 is the only tier where +0.05
 * crosses `AUTO_FILE_GATE`, so it is the case that sits ON the threshold —
 * anywhere else the bonus moves a number nobody acts on.
 */
const SUBJECT = "Update from Cedarhollow Systems";
const BODY = "We have received your application. Thank you for your interest.";

/** An ordinary employer domain: on no list, by either matching rule. */
const PLAIN_SENDER = "recruiting@cedarhollow.example";

const confidenceFrom = (sender) => classifyWithRules(SUBJECT, BODY, sender).confidence;

test("the fixture sits on the 0.80 rung, so the bonus is observable at all", () => {
  // `classifyWithRules` does not return `isAts`; the ONLY way this file can
  // see the match is the 0.05 it is worth. Without this control, every
  // "lookalike stays at 0.80" assertion below would pass just as happily if
  // the flag were hardwired false and the bonus never applied to anyone.
  const verdict = classifyWithRules(SUBJECT, BODY, PLAIN_SENDER);
  assert.equal(verdict.category, "applied");
  assert.equal(verdict.scores.applied, 4, "the fixture stopped scoring 4 — re-pick the rung");
  assert.equal(verdict.confidence, 0.8, "the fixture left the 0.80 rung and measures nothing");
  assert.ok(0.8 + 0.05 >= AUTO_FILE_GATE, "the rung no longer reaches the gate");
});

// ---------------------------------------------------------------------------
// Hosts that CONTAIN a listed ATS name but are not that ATS. Every one is
// registrable by a stranger. Ported from `LOOKALIKE_SENDERS` in
// `backend/tests/test_ingestion_hole_166.py`.
// ---------------------------------------------------------------------------

const LOOKALIKE_SENDERS = [
  // The three the `is_ats_sender` docstring names as the reason for #260. Two
  // of them carry a reserved host here instead of the routable one the Python
  // table uses: a lookalike is about the SUBSTRING, so the labels AROUND the
  // ATS name are free and `.test` cannot route. `notlever.co.example.com` is
  // already under `example.com` and is quoted verbatim.
  ["no-reply@greenhouse.io.mailhost.test", "the ATS name as the LEFT label"],
  ["careers@notlever.co.example.com", "the ATS name in the MIDDLE, glued left"],
  [
    "hr@sohire.company.test",
    "the docstring's third example — DOCUMENTATION, NOT EVIDENCE: it worked " +
      "through `hire.com`, which #348 removed from the list, so it is refused " +
      "twice over and cannot go red on the old line",
  ],
  // The rest of the Python table. `xgreenhouse.io` is the one lookalike that
  // CANNOT move to a reserved domain: its whole property is that the host ENDS
  // with a listed name, which forces the real TLD. It is also the case that
  // catches `domain.endsWith(a)` — the repair that looks right and is not.
  ["jobs@xgreenhouse.io", "one character short of the real relay — ENDS with it, is not a subdomain"],
  ["noreply@workday.com.phish.example", "the classic suffix-looking prefix"],
  // Added here: the live equivalent of the `sohire` shape, built on an entry
  // the list still carries. It contains `myworkday.com` AND `workday.com`
  // strictly inside the host, straddling a label boundary, and is a subdomain
  // of neither.
  ["careers@myworkday.company.test", "a listed domain straddling a label boundary, mid-host"],
];

for (const [sender, why] of LOOKALIKE_SENDERS) {
  test(`a lookalike earns no ATS bonus: ${sender} (${why})`, () => {
    const confidence = confidenceFrom(sender);
    assert.equal(
      confidence,
      0.8,
      `${sender} moved off the 0.80 rung, so the browser port counted it as an ATS relay`,
    );
    assert.ok(
      confidence < AUTO_FILE_GATE,
      `${sender} reached ${confidence}, at or over the auto-file gate — a domain ` +
        "a stranger can register must not get a message filed",
    );
  });
}

// ---------------------------------------------------------------------------
// The forms that legitimately match and MUST keep matching. Ported from
// `REAL_RELAY_SENDERS`. These pass on the pre-#651 line too: they are the
// directional control, not proof of the bug.
// ---------------------------------------------------------------------------

const REAL_RELAY_SENDERS = [
  ["no-reply@greenhouse.io", "the listed domain itself"],
  ["no-reply@mail.greenhouse.io", "a proper subdomain"],
  ["no-reply@us.greenhouse-mail.io", "the relay Greenhouse actually sends from"],
  ["no-reply@us-east.smartrecruiters.com", "a regional subdomain"],
  ["no-reply@ats.rippling.com", "the full host the list carries on purpose"],
  ["no-reply@mail.ats.rippling.com", "a subdomain of a multi-label entry"],
  ["no-reply@lever.co", "the listed domain itself"],
  ["no-reply@hire.lever.co", "what `hire.com` was reaching for; covered by `lever.co` either way"],
  ["no-reply@myworkday.com", "the entry anchoring made load-bearing"],
];

for (const [sender, why] of REAL_RELAY_SENDERS) {
  test(`a real relay still earns the ATS bonus: ${sender} (${why})`, () => {
    const confidence = confidenceFrom(sender);
    assert.ok(
      confidence >= AUTO_FILE_GATE,
      `${sender} scored ${confidence}: anchoring dropped a relay that legitimately ` +
        "matched, which is the same defect pointing the other way",
    );
  });
}

test("the two entries anchoring makes load-bearing are both still in rules.json", () => {
  // Under containment `myworkday.com` was redundant with `workday.com` and
  // `greenhouse-mail.io` looked like a variant of `greenhouse.io`; a tidying
  // pass could delete either and no gate here would notice. Under anchoring
  // neither is redundant — `myworkday.com` does not end in `.workday.com` —
  // and deleting one silently stops recognising a relay production really uses.
  // The Python side pins the same pair in
  // `test_two_list_entries_became_load_bearing_under_anchoring`.
  for (const entry of ["myworkday.com", "workday.com", "greenhouse-mail.io", "greenhouse.io"]) {
    assert.ok(LISTED.has(entry), `rules.json lost the \`${entry}\` entry`);
  }
});

test("bare rippling.com is still not an ATS sender — it is payroll mail", () => {
  // Passes on the old line too (`"ats.rippling.com"` is not a substring of
  // `"rippling.com"`), so it is a regression guard and not evidence. It is here
  // because the docstring calls the narrow entry deliberate: a bare
  // `rippling.com` would sweep in payroll mail that is not about an application.
  assert.equal(confidenceFrom("payroll@rippling.com"), 0.8);
  assert.ok(!LISTED.has("rippling.com"));
});

test("a sender with no domain does not throw and is not an ATS relay", () => {
  // `is_ats_sender` returns False for a falsy address or one with no `@`, and
  // reads a missing domain as "no match" rather than as a wildcard. Three of
  // these are reachable from `/import`: `parseFrom`'s fallback returns whatever
  // it was given when the header holds no address at all.
  for (const sender of ["", undefined, "no-at-sign-here", "@", "user@"]) {
    let confidence;
    assert.doesNotThrow(() => {
      confidence = confidenceFrom(sender);
    }, `classifyWithRules threw on ${JSON.stringify(sender)}`);
    assert.equal(
      confidence,
      0.8,
      `${JSON.stringify(sender)} earned the ATS bonus with no domain to earn it with`,
    );
  }

  // The empty-domain case deserves its own sentence: `"@"` and `"user@"` split
  // to `""`, and `"".endsWith(".greenhouse.io")` is false — but `ATS_DOMAINS`
  // must never gain an empty entry, because `"" === ""` would then match every
  // sender that has an `@` in it.
  assert.ok(!LISTED.has(""), "an empty list entry would match every sender");
});

test("an address with an empty local part still HAS a domain, and both engines match it", () => {
  // `"@greenhouse.io"` is not degenerate the way `"user@"` is: it splits to the
  // listed domain, and `is_ats_sender("@greenhouse.io")` is True — measured
  // against the shipped `rules.py`, not inferred. Written down because it looks
  // like a case for the "no domain" list above and is not one; moving it there
  // would make the browser port stricter than the engine it mirrors.
  assert.ok(confidenceFrom("@greenhouse.io") >= AUTO_FILE_GATE);
});

test("a raw From header is refused by both engines, and neither /import nor the demo sends one", () => {
  // The docstring is explicit that the argument is a bare address, never a raw
  // `From`: "containment tolerated the trailing `>` of
  // `… <no-reply@us.greenhouse-mail.io>` and anchoring does not." Pinned so the
  // agreement is deliberate rather than accidental —
  // `lib/import/parseMail.ts:parseFrom` returns a trimmed, lowercased bare
  // address exactly as `email.utils.parseaddr` does, which is what makes
  // refusing this safe rather than a regression on the public import page.
  assert.equal(confidenceFrom("Cedarhollow Talent <no-reply@greenhouse.io>"), 0.8);

  // Same reasoning for trailing whitespace: `is_ats_sender` does not `.strip()`
  // (only `sender_domain` does), so a `.trim()` added here would re-diverge the
  // two engines while looking like a tidy-up.
  assert.equal(confidenceFrom("no-reply@greenhouse.io "), 0.8);
});
