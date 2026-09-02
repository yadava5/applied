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
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

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

// ===========================================================================
// THE CENSUS. The same rule, read as SOURCE, in all three ports.
// ===========================================================================
/**
 * TWO OF THREE HAND-WRITTEN PORTS IS WHAT A PER-FILE FIX PRODUCES.
 *
 * The engine was anchored first, in `dcbdc8f` ("match ATS relay domains as
 * domains, not substrings", #267, for issue #260). `lib/demo/rulesLayer.ts`
 * followed months later in `4fc748f`, which is what the behavioural tests
 * above pin. A THIRD port of the same predicate existed the whole time —
 * `ml/browser/site/app.js`, the in-browser demo classifier — and kept
 * `rules.ats.some((a) => dom.includes(a))` until the commit that added this
 * section. Nothing in the tree compared them, so nothing could say that one
 * had been left behind.
 *
 * WHAT IS IN `PORTS`: FOUR FILES, NOT FOUR PORTS. Three of them are
 * independent ports of `is_ats_sender` — the engine, the demo/`/import` layer,
 * the browser demo. The fourth, `ml/demo/space/jobtracker/classifier/rules.py`,
 * is not a port at all: it is a copy of the engine that `ml/demo/package_space
 * .py` generates for the Hugging Face Space. It is read here anyway, for the
 * reason `backend/tests/test_test_data_gate.py` records — that file has been
 * hand-edited out of step with its source before — and because
 * `backend/tests/test_a_reference_does_not_outrank_a_report.py`, the same kind
 * of census for the #451 fix, already lists it for the same reason. Where it
 * agrees with the engine this entry is redundant; the hand edit is the case
 * where it is not.
 *
 * WHY THIS IS A SOURCE CHECK AND NOT A BEHAVIOURAL ONE, said plainly.
 * `ml/browser/site/app.js` is a browser module. Its first statement is
 * `import { pipeline, env } from 'https://cdn.jsdelivr.net/npm/...'` — an
 * HTTPS specifier `node --test` will not resolve — it reads `document` at
 * module scope, and it exports nothing. There is no node-importable surface,
 * so there is no runtime to exercise under the unit runner and none of the
 * lookalike senders above can be sent through it here. This section reads a
 * regular expression over text. It proves the SHAPE of one line and it does
 * not prove what that line does. Do not present it as coverage of the browser
 * engine's behaviour, because it is not.
 *
 * WHERE THE BEHAVIOURAL COVERAGE ACTUALLY LIVES. For `rulesLayer.ts`, in the
 * tests ABOVE in this file — real lookalikes and real relays through
 * `classifyWithRules`, which is the evidence that the defect was real. For
 * `rules.py`, in `backend/tests/test_ingestion_hole_166.py`, the table those
 * tests were ported from. For `app.js` there is none, here or anywhere, and
 * saying so is the honest position: the browser demo's classification is
 * exercised by a person opening the page.
 *
 * WHAT THIS SECTION IS FOR. Catching a NEW port that lands unanchored, and
 * catching any of these quietly regressing. Its limit is explicit: `PORTS` is
 * a written list and cannot discover a file that is not in it. Another port or
 * another vendored copy of `is_ats_sender` means another entry here, and this
 * paragraph is the instruction to add one. The way to find them is a search
 * for `ATS_DOMAINS`/`ats_domains` across the tree, excluding
 * `.claude/worktrees/`; that is how this fourth entry was found.
 *
 * HOW THE PATHS ARE RESOLVED, and why it matters more than it looks. The repo
 * root comes from this file's own location with a FIXED four `..` segments,
 * and each port is a literal relative path joined to it. Never a glob, never a
 * search by basename, and never a walk upwards looking for `.git`:
 * `.claude/worktrees/` in this repository holds around fifty stale agent
 * checkouts, so a basename search for `app.js` or `rules.py` returns dozens of
 * copies that read perfectly and answer for the wrong tree.
 *
 * WHEN THIS RUNS. IT NOW COVERS WHAT IT READS, and the paragraph that stood
 * here said the opposite for as long as that was true. It read: "Three of the
 * four files read below sit outside that filter, so a pull request touching
 * only `ml/` or only `backend/` does not fire this census... left as a
 * decision rather than made here." The decision was taken with #667, which
 * added all three outside paths to BOTH trigger blocks of
 * `.github/workflows/frontend-ci.yml` — `ml/browser/site/app.js`,
 * `ml/demo/space/jobtracker/classifier/rules.py` and
 * `backend/jobtracker/classifier/rules.py`, at lines 33-35 and 56-58 — so a
 * pull request touching any file this census reads now fires it.
 *
 * The cost that paragraph weighed is real and was accepted: those three paths
 * pull the whole `Frontend CI` job — typecheck, lint, the unit suite and
 * `next build` — onto a backend-only or `ml/`-only pull request. That is the
 * price of a census that cannot be edited out of range of its own trigger.
 *
 * THE PROSE IS THE PART THAT ROTTED, which is the reason this correction is
 * worth more than two sentences of tidying. A census whose own docstring
 * understates its reach teaches the next reader that `ml/` edits go unchecked,
 * and the obvious response to that belief is to stop relying on the census —
 * which is how a gate that works becomes a gate nobody trusts. If the trigger
 * list and this paragraph disagree again, the trigger list is the truth.
 */

/** `apps/web/tests/unit/` → the repository root. Four segments, fixed. */
const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..");

/**
 * The JavaScript ports share a predicate shape, so they share its patterns.
 *
 * The back-references are the point. `\1` ties the compared value to the
 * `some` callback's own parameter and `\2` ties both sides of the `||` to the
 * same domain variable, so a line that compares one name and suffixes another
 * cannot pass by looking approximately right. Neither pattern names `a` or
 * `domain`: `rulesLayer.ts` calls the host `domain` and `app.js` calls it
 * `dom`, and one regex has to read both.
 */
const ANCHORED_JS = /\((\w+)\) => (\w+) === \1 \|\| \2\.endsWith\(`\.\$\{\1\}`\)/;
const UNANCHORED_JS = /\((\w+)\) => (\w+)\.includes\(\1\)/;

/** The Python copies share a predicate shape too, so they share its patterns. */
const LOCATOR_PY = /for \w+ in ATS_DOMAINS/;
const ANCHORED_PY = /\b(\w+) == (\w+) or \1\.endswith\(f"\.\{\2\}"\)/;
const UNANCHORED_PY = /\b(\w+) in (\w+) for \1 in ATS_DOMAINS/;

/** What both Python copies carried before anchoring, byte for byte. */
const CONTAINMENT_PY = "    return any(ats in domain for ats in ATS_DOMAINS)";

/**
 * The four files, and for each one the line it carried BEFORE it was anchored.
 *
 * Those `before` lines are quoted from git, not reconstructed: the engine's is
 * the `-` side of `dcbdc8f`; the vendored copy's is the `+` side of `8afd5b1`,
 * which is the commit that first vendored it and shows the identical text; the
 * `rulesLayer.ts` one is the `-` side of `4fc748f`; and the `app.js` one is
 * what stood at line 54 of that file until the commit adding this section
 * removed it. They are the directional control — see the second loop below —
 * and a census whose "absent" pattern matches nothing is indistinguishable
 * from one whose pattern is simply wrong.
 */
const PORTS = [
  {
    path: "backend/jobtracker/classifier/rules.py",
    what: "the engine, `is_ats_sender`",
    locator: LOCATOR_PY,
    anchored: ANCHORED_PY,
    unanchored: UNANCHORED_PY,
    before: CONTAINMENT_PY,
  },
  {
    // Generated from the file above by `ml/demo/package_space.py`, so this
    // entry is normally redundant with it. It is not redundant when the copy
    // is edited by hand, which is the case it is here to catch.
    path: "ml/demo/space/jobtracker/classifier/rules.py",
    what: "the vendored Hugging Face Space copy of the engine",
    locator: LOCATOR_PY,
    anchored: ANCHORED_PY,
    unanchored: UNANCHORED_PY,
    before: CONTAINMENT_PY,
  },
  {
    path: "apps/web/lib/demo/rulesLayer.ts",
    what: "the demo and the public `/import` page",
    locator: /ATS_DOMAINS\.some\(/,
    anchored: ANCHORED_JS,
    unanchored: UNANCHORED_JS,
    before: "    isAts = ATS_DOMAINS.some((a) => domain.includes(a));",
  },
  {
    path: "ml/browser/site/app.js",
    what: "the in-browser demo classifier",
    locator: /rules\.ats\.some\(/,
    anchored: ANCHORED_JS,
    unanchored: UNANCHORED_JS,
    before: "    isAts = rules.ats.some((a) => dom.includes(a));",
  },
];

/**
 * Read a port, and fail with a sentence rather than an `ENOENT` stack.
 *
 * A deleted port must not turn into an unreadable red. Same reasoning as the
 * `MIN_TESTS` note in `scripts/assert-unit-suite-ran.mjs`: removing something
 * on purpose is fine, and the diff has to say so out loud.
 */
const readPort = ({ path }) => {
  const absolute = join(REPO_ROOT, path);
  try {
    return readFileSync(absolute, "utf8");
  } catch (err) {
    assert.fail(
      `${path} was not at ${absolute} (${err.code ?? err.message}). If that port was ` +
        "moved or deleted, update or remove its entry in PORTS in the same commit, so " +
        "the diff records that a port stopped being checked.",
    );
  }
};

for (const port of PORTS) {
  test(`census: ${port.path} matches ATS senders anchored (${port.what})`, () => {
    const lines = readPort(port)
      .split("\n")
      .filter((line) => port.locator.test(line));

    // Exactly one line decides this in every port. Two would mean the census
    // is reading one of them and ignoring the other; zero means the predicate
    // moved and this file is now measuring nothing at all.
    assert.equal(
      lines.length,
      1,
      `expected exactly one ATS-matching line in ${port.path}, found ${lines.length} — ` +
        "the predicate moved or was duplicated, and the assertions below would read the " +
        "wrong one. Fix the locator, do not delete the entry.",
    );

    const line = lines[0].trim();
    assert.match(
      line,
      port.anchored,
      `${port.path} no longer matches ATS senders anchored. The line is:\n    ${line}\n` +
        "It must accept a listed domain or a PROPER subdomain of one, and nothing else — " +
        "`domain.endsWith(a)` is the repair that looks right and still accepts " +
        "`xgreenhouse.io`.",
    );
    assert.doesNotMatch(
      line,
      port.unanchored,
      `${port.path} matches ATS senders by unanchored containment. The line is:\n    ${line}\n` +
        "A host that merely CONTAINS a listed name is not that ATS, and anyone with a " +
        "registrar can put themselves on a closed list that way (#651, and #260 before it).",
    );
  });
}

for (const port of PORTS) {
  test(`census control: the patterns tell the two forms apart (${port.path})`, () => {
    // Anti-vacuity, in all three directions. Without this, a typo in
    // `unanchored` would let the census pass on a port that had regressed, and
    // it would look exactly like a port that was fine.
    assert.match(
      port.before,
      port.unanchored,
      `the \`unanchored\` pattern for ${port.path} does not match the containment line ` +
        "that port really carried, so it can never catch a regression",
    );
    assert.doesNotMatch(
      port.before,
      port.anchored,
      `the \`anchored\` pattern for ${port.path} matches the pre-fix containment line, ` +
        "so it cannot tell the fix from the defect",
    );
    // The locator has to find the line when the line is WRONG, not only when
    // it is right. If it were written against the anchored form, a real
    // regression would surface as "found 0 candidate lines" — a red that
    // blames the census instead of naming the defect.
    assert.match(
      port.before,
      port.locator,
      `the locator for ${port.path} only finds the ATS line once it is already fixed`,
    );
  });
}

/**
 * THE CENSUS RUNS ON EVERY FILE IT READS — asserted, not described.
 *
 * The paragraph in this file's header used to say the opposite, correctly, and
 * then went on saying it after #667 widened the trigger. That is the failure
 * mode this whole file exists to catch, occurring in the file itself: a claim
 * about coverage that nobody re-derived. So the correspondence between `PORTS`
 * and `frontend-ci.yml`'s trigger is read out of both, rather than asserted in
 * prose that the next reader has to take on trust.
 *
 * A path is covered when it is under `apps/web/**` — already in both blocks —
 * or named explicitly in BOTH the `pull_request` and the `push` block. Both,
 * because a census that fires on the PR and not on the merge cannot see a port
 * that regresses in a direct push to `main`, and one that fires on the merge
 * and not the PR reports the regression after it has landed.
 *
 * MUTATION: delete any one of the three explicit lines from either block and
 * this reds, naming the path and the block.
 */
test("census: every port this file reads is in frontend-ci.yml's trigger", () => {
  const workflow = readFileSync(
    join(REPO_ROOT, ".github", "workflows", "frontend-ci.yml"),
    "utf8",
  );

  // The two `paths:` blocks, split on the `push:` key at the `on:` mapping's
  // own indentation. Deliberately not a YAML parse: a dependency here would be
  // one more thing that can silently start answering about a different file.
  const split = workflow.indexOf("\n  push:\n");
  assert.ok(split > 0, "frontend-ci.yml has no `push:` trigger block any more");
  const blocks = {
    pull_request: workflow.slice(0, split),
    push: workflow.slice(split),
  };
  // The control: the split really did separate them, rather than putting
  // everything on one side where every assertion below would pass twice.
  assert.ok(
    blocks.pull_request.includes("pull_request:"),
    "the split put `pull_request:` on the wrong side",
  );
  assert.ok(
    !blocks.push.includes("pull_request:"),
    "the split did not separate the two trigger blocks",
  );

  for (const port of PORTS) {
    if (port.path.startsWith("apps/web/")) continue; // covered by `apps/web/**`
    for (const [name, block] of Object.entries(blocks)) {
      assert.ok(
        block.includes(`- "${port.path}"`),
        `${port.path} is read by this census but is not in frontend-ci.yml's ` +
          `${name} trigger, so the pull request most likely to regress it is ` +
          `the one that would not run this file`,
      );
    }
  }
});
