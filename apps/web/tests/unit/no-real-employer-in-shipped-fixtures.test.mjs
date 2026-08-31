/**
 * NO SHIPPED FIXTURE NAMES A REAL EMPLOYER (#638).
 *
 * THE RULE THIS ENFORCES, and it is not "no real domains".
 *
 *   Naming the CHANNEL is accurate and load-bearing. Naming the EMPLOYER is
 *   fabrication.
 *
 * A `no-reply` sender on `greenhouse.io` is CORRECT here: Greenhouse really is
 * the relay an ATS verdict arrives through, the row's subject names an invented
 * employer ("Northstar"), and depicting the relay is the entire point of the
 * scene. A `jobs@` sender on a real company's OWN domain, beside an invented
 * subject line and an invented classifier confidence, is not the same thing — it asserts, on a public
 * marketing page, that a named real company sent a specific verdict with a
 * specific score. Nobody at that company said any of it.
 *
 * WHAT SHIPPED. Two rows of `components/landing/InboxScene.tsx` and three rows
 * of `booklet/src/content.ts` (plus its built, publicly-served copy under
 * `apps/web/public/system-card/`) carried real employer domains with invented
 * subjects and invented confidences. Five of the seven landing rows already
 * used invented employers, so it was an inconsistency as much as a claim.
 *
 * WHY IT SURVIVED, and why the fix is here rather than there.
 * `scripts/check_test_data.py` is the repository's address gate and it is a
 * good one, but its `SCAN_ROOTS` are `backend/tests/`, `backend/jobtracker/`,
 * `apps/web/tests/` and `ml/`. NOTHING covers `apps/web/components/`,
 * `apps/web/app/`, `apps/web/lib/` or `booklet/`. The most public surface in
 * the product — the landing page a stranger sees first — was the one directory
 * tree with no scan over it at all. Widening those roots is issue #623 and
 * carries its own allowance design; this file covers the gap meanwhile, from
 * the suite that already runs on every PR (`npm run test:unit`).
 *
 * HOW IT DECIDES — three allowances, and everything else is a failure.
 *
 *   RESERVED   RFC 2606 §2/§3 and RFC 6761 §6.3. Citable, closed, and the only
 *              category that can honestly claim "cannot route anywhere".
 *   CHANNEL    The relay, the ATS, the assessment vendor, the mail provider.
 *              Real registrations belonging to real companies — and correct to
 *              name, because what is being depicted is the pipe, not a party to
 *              the correspondence.
 *   FIXTURE    Invented employers this repository's fixtures already use.
 *
 * FIXTURE is a JUDGEMENT, not a proof. `harbor.io`, `beacon.io` and
 * `cedarlabs.com` are names nobody here checked a WHOIS for; the list records
 * "reviewed and accepted as an invented fixture employer", which is weaker than
 * RESERVED's "un-routable by RFC" and is deliberately not dressed up as it. The
 * property that matters is that the list is CLOSED: a domain that is on none of
 * the three fails, so adding a company — any company, not just the two this
 * issue happened to find — reds this test until somebody writes down which
 * allowance it falls under and why. A gate that grepped for `stripe|datadog`
 * would pass forever the moment the next one was a different company.
 *
 * WHAT THIS DELIBERATELY DOES NOT CHECK.
 *
 *  · Bare company NAMES. `lib/demo/demoData.ts` seeds two unsynced rows as
 *    "Twitch" and "DoorDash" with no address attached, and this gate cannot see
 *    them. That is a real blind spot and it is named here rather than papered
 *    over. It is also already a DECIDED case, not an oversight:
 *    `scripts/footage/scenes.mjs` says of exactly those two rows — "real brand
 *    names, fine on a page labelled DEMO · FIXTURE DATA, not fine in unlabelled
 *    marketing footage" — and enforces it with `assertNoBrandRows` on every
 *    captured frame. Extending this gate to `company:` literals would red on
 *    that decision and need a hardcoded exception, which is a gate documenting
 *    an exception instead of enforcing a rule.
 *  · `backend/`. `jobtracker/tracking/extractor.py` maps `"stripe.com"` to
 *    `"Stripe"` — a real-domain-to-employer-name table is product logic that
 *    only works because the domains are real, the opposite of a fabricated
 *    fixture. It is also already under `check_test_data.py`'s roots.
 *
 * A NOTE ON THIS FILE'S OWN PROSE. It names domains, never addresses. This
 * file sits under `apps/web/tests/`, which IS one of `check_test_data.py`'s
 * scan roots, and writing the examples out in `local@domain` form would add
 * four non-reserved addresses to that gate's baseline — a gate about not
 * republishing material, moved in order to explain a gate about not
 * republishing material. The bare domains carry the whole argument anyway.
 *
 * Run:  cd apps/web && npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const WEB_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const REPO_ROOT = join(WEB_ROOT, "..", "..");

/**
 * The shipped, non-test surfaces this gate owns, with the floor each must
 * clear. The floors are TRIPWIRES against a walk that resolved nothing — a
 * renamed directory, a typo'd root, an extension filter that stopped matching —
 * not targets. Measured 2026-08-30 at 100 / 11 / 47 / 41 / 3 files.
 *
 * A per-root floor rather than one global count on purpose: with a single
 * total, a healthy `components/` would vouch for a `booklet/src/` that had
 * silently stopped being scanned, and the plant-a-domain proof in one root
 * would say nothing about the other four.
 *
 * `minAddresses` is the sharper half. A root can contain files and still be
 * invisible to the extractor if the regex or the decoding breaks; requiring
 * every root to yield at least one address means the scan is proven to be
 * READING, not merely listing.
 */
const ROOTS = [
  { rel: "apps/web/components", minFiles: 60, minAddresses: 5 },
  { rel: "apps/web/lib/demo", minFiles: 6, minAddresses: 10 },
  { rel: "apps/web/app", minFiles: 25, minAddresses: 2 },
  { rel: "booklet/src", minFiles: 25, minAddresses: 3 },
  // The BUILT copy of `booklet/src`, committed and served publicly at
  // /system-card/. Source alone is not the surface: the bundle is what a
  // reader's browser downloads, so a fix to `content.ts` that is not rebuilt
  // leaves the fabrication live. Minified JS keeps its string literals, so the
  // same extractor works on it unchanged.
  { rel: "apps/web/public/system-card", minFiles: 2, minAddresses: 3 },
];

/** Text this gate can read. Everything else in these trees is a font or an
 *  image; scanning bytes for an address shape would only manufacture noise. */
const TEXT_EXTENSIONS = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".css", ".html", ".md"];

/** Never walked: build output and dependency trees are not this repo's
 *  material, and both are full of addresses that belong to somebody else. */
const SKIP_DIRS = new Set(["node_modules", ".next", ".git", "dist", "__pycache__", ".venv"]);

/**
 * RFC 2606 §2 reserves these TLDs; RFC 6761 §6.3 makes `.localhost`
 * un-routable by definition. Same citation `scripts/check_test_data.py` uses,
 * deliberately — one rule, stated once, applied in two places.
 */
const RESERVED_TLDS = [".test", ".example", ".invalid", ".localhost"];
/** RFC 2606 §3 reserves these second-level names AND everything under them, so
 *  `email.careers.example.com` is as un-routable as the bare name. */
const RESERVED_DOMAINS = ["example.com", "example.net", "example.org", "localhost"];

/**
 * Domains that name the CHANNEL — the relay, the applicant-tracking system, the
 * assessment vendor, the mail provider. Several are real registrations owned by
 * real companies, and naming them is CORRECT: the mail genuinely arrives
 * through them, and none of them is being cast as an employer somebody applied
 * to. Matched as a domain or as a suffix, so `us.greenhouse-mail.io` and
 * `hire.lever.co` need no entries of their own.
 */
const CHANNEL = new Map([
  ["greenhouse.io", "Greenhouse — the ATS relay an application receipt or verdict actually arrives through. The landing scene's whole argument is that the relay is visible and the verdict is not; its row's subject names the invented employer 'Northstar'."],
  ["greenhouse-mail.io", "Greenhouse's own sending domain, the one real ATS mail is stamped with (`us.greenhouse-mail.io`)."],
  ["lever.co", "Lever — same category, including its `hire.lever.co` sending subdomain."],
  // Only relays that ACTUALLY appear in the scanned roots are listed. `ashbyhq.com`,
  // `workday.com`, `hackerrank.com` and `codesignal.com` are the same category and
  // would belong here the moment a fixture used one — they are absent because the
  // last test in this file refuses an allowance that matches nothing, and a standing
  // excuse for a domain nothing uses is a hole waiting for the wrong thing to fill it.
  ["myworkday.com", "Workday's per-tenant sending domain. A Workday confirmation really does come from here; the tenant slug in front of it, not the domain, is what would name an employer."],
  ["gmail.com", "A mail PROVIDER, which is the channel by definition. Covers a recruiter writing from a personal mailbox in the /demo scan fixture, and the owner's own beta-access address in `components/beta/constants.ts` — a deliberate contact surface, not a fixture."],
  ["applicant-mail.net", "A generic invented relay used by the review-queue fixture for the case that matters there: mail that names NO employer at all. Naming nobody is the point of the row."],
  ["jobboard.com", "A job-board digest — the aggregator that sent it, not an employer. Noted as the estate's one inconsistency here: `lib/demo/scanMine.ts` writes the same idea as `digest@jobboard.test`, i.e. reserved. Converging the two is the owner's call, not this gate's."],
  ["corp.com", "Prose, not a fixture: `components/shell/RailFooter.tsx`'s docstring uses a `billing@` address on `corp.com` to illustrate a connected Gmail that differs from the signed-in account. No employer is being named — the example is about two mailboxes."],
]);

/**
 * Invented employers this repository's fixtures use. Matched as a domain or a
 * suffix, so `hackerrank.harboranalytics.com` (a fixture employer's own
 * assessment subdomain) needs no entry.
 *
 * READ THE HEADER BEFORE ADDING ONE. This list records "reviewed on 2026-08-30
 * and accepted as invented", not "provably unregistered" — nobody ran a WHOIS,
 * and `.io` / `.dev` / `.com` names of this shape frequently are registered by
 * somebody. What it buys is that the list is closed: the next real company to
 * appear in these trees fails this test, whatever its name is.
 */
const FIXTURE_EMPLOYERS = new Map([
  ["harbor.io", "Harbor — the landing scene's assessment row."],
  ["harboranalytics.com", "Harbor Analytics — the board fixture's interviewing employer, and the booklet's follow-up trace."],
  ["beacon.io", "Beacon — the landing scene's offer row."],
  ["beaconhealth.io", "Beacon Health — the board fixture's offer employer."],
  ["earlystage.xyz", "An unnamed early-stage startup writing from a personal-looking address; the low-confidence row that the gate holds for a human."],
  ["cedarlabs.com", "Cedar Labs — the board fixture's follow-up employer."],
  ["cedarlabs.io", "Cedar Labs, the marketing surface's spelling of the same invented employer."],
  ["northstar.dev", "Northstar — the board fixture's interviewing employer."],
  ["northstarsystems.dev", "Northstar Systems, the marketing surface's spelling of the same invented employer."],
  ["larkspur.dev", "Larkspur Systems — the marketing surface's rejection."],
  ["summit.dev", "Summit — the needs-review row's employer."],
  ["junipercloud.io", "Juniper Cloud — an invented employer already used by `lib/demo/sampleInbox.ts` and seeded in `demoData.ts`. It replaced `stripe.com` on the landing scene and in the booklet's trace (#638)."],
  ["kestreldynamics.com", "Kestrel Dynamics — an invented employer already seeded in `demoData.ts`, `showcase.ts` and `BoardStill.tsx`; this is the first use of its DOMAIN. It replaced `datadog.com` (#638)."],
  ["atlasfreight.com", "Atlas Freight — the board fixture's rejection."],
  ["meridianrobotics.com", "Meridian Robotics — the sample inbox's coordinator."],
]);

/** Loose on the left of the `@`, strict on the right: the job is to notice an
 *  address, not to validate one. Two-or-more letters in the TLD keeps
 *  `@pytest.fixture` and `@playwright/test` out. Same shape as the Python
 *  gate's, on purpose. */
const EMAIL = /[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}/g;

function isReserved(domain) {
  if (RESERVED_DOMAINS.includes(domain)) return true;
  if (RESERVED_TLDS.some((tld) => domain.endsWith(tld))) return true;
  return RESERVED_DOMAINS.some((d) => domain.endsWith("." + d));
}

/** A domain or any subdomain of it. `x.greenhouse-mail.io` matches
 *  `greenhouse-mail.io`; `evil-greenhouse.io` does NOT — the dot is required,
 *  so a lookalike registration cannot inherit the allowance. */
function matchesEntry(domain, table) {
  for (const key of table.keys()) {
    if (domain === key || domain.endsWith("." + key)) return key;
  }
  return null;
}

/** Which allowance covers this domain, or null when none does. */
function allowanceFor(domain) {
  if (isReserved(domain)) return { kind: "RESERVED", reason: "RFC 2606 / RFC 6761 — cannot route." };
  const channel = matchesEntry(domain, CHANNEL);
  if (channel) return { kind: "CHANNEL", reason: CHANNEL.get(channel) };
  const fixture = matchesEntry(domain, FIXTURE_EMPLOYERS);
  if (fixture) return { kind: "FIXTURE", reason: FIXTURE_EMPLOYERS.get(fixture) };
  return null;
}

function filesUnder(absRoot) {
  const out = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir)) {
      if (SKIP_DIRS.has(entry)) continue;
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) walk(full);
      else if (TEXT_EXTENSIONS.some((ext) => entry.endsWith(ext))) out.push(full);
    }
  };
  walk(absRoot);
  return out;
}

/** Every address in one root, with the file it came from. */
function scanRoot(rel) {
  const files = filesUnder(join(REPO_ROOT, rel));
  const addresses = [];
  for (const file of files) {
    const text = readFileSync(file, "utf8");
    for (const match of text.matchAll(EMAIL)) {
      addresses.push({
        address: match[0],
        domain: match[0].split("@").pop().toLowerCase().replace(/\.$/, ""),
        file: relative(REPO_ROOT, file).split("\\").join("/"),
      });
    }
  }
  return { files, addresses };
}

for (const root of ROOTS) {
  test(`${root.rel} — every sender domain falls under a stated allowance`, () => {
    const { files, addresses } = scanRoot(root.rel);

    // The scan reached the tree. Without this, a moved directory or a stale
    // extension filter turns the whole gate green by looking at nothing — the
    // "check that cannot fail" this repository keeps re-finding.
    assert.ok(
      files.length >= root.minFiles,
      `${root.rel}: scanned only ${files.length} files, floor is ${root.minFiles}. ` +
        "The walk did not resolve — a renamed directory, or TEXT_EXTENSIONS no longer matching. " +
        "A zero-hit result from a scan that went nowhere is not a pass.",
    );
    // And it is READING them, not just listing them.
    assert.ok(
      addresses.length >= root.minAddresses,
      `${root.rel}: found only ${addresses.length} addresses in ${files.length} files, ` +
        `floor is ${root.minAddresses}. The extractor is not matching — if these fixtures ` +
        "genuinely lost their senders, lower the floor in the same commit so the diff says so.",
    );

    const offenders = addresses.filter((hit) => allowanceFor(hit.domain) === null);
    const unique = [...new Set(offenders.map((hit) => `${hit.domain}  (${hit.file})`))];
    assert.deepEqual(
      unique,
      [],
      unique.length === 0
        ? ""
        : `A shipped fixture in ${root.rel} names a domain no allowance covers (#638):\n` +
          unique.map((line) => "  " + line).join("\n") +
          "\n\nDecide which it is, then act:\n" +
          "  · It names an EMPLOYER a person applied to → it is a fabrication on a public\n" +
          "    surface. Swap it for an invented one, matching the style already in the file\n" +
          "    (harbor.io, beacon.io, cedarlabs.com, northstar.dev, junipercloud.io), and keep\n" +
          "    the row's meaning: a rejection stays a rejection, a 0.95 stays 0.95.\n" +
          "  · It names the CHANNEL — an ATS relay, an assessment vendor, a mail provider →\n" +
          "    add it to CHANNEL with the reason. Depicting the pipe is the point.\n" +
          "  · It is a NEW invented employer → add it to FIXTURE_EMPLOYERS with the reason,\n" +
          "    and read that list's header first: it records a judgement, not a proof.\n" +
          "\nIf you edited booklet/src/, rebuild the served copy too:\n" +
          "    cd booklet && npm run build:system-card\n" +
          "Source and bundle are separate surfaces and this gate scans both.",
    );
  });
}

test("the classifier is directional — a real employer domain is NOT allowed", () => {
  // The control for every assertion above. Each of these is shaped exactly like
  // a domain the gate must reject: a real company standing in as the employer.
  // If `allowanceFor` ever went permissive — a suffix rule that swallowed too
  // much, an allowlist entry pasted at the wrong nesting — the five tests above
  // would go green by accepting everything, and only this notices.
  for (const domain of ["stripe.com", "datadog.com", "notion.so", "acme-hiring.com"]) {
    assert.equal(
      allowanceFor(domain),
      null,
      `${domain} is covered by an allowance; the allowlists have gone permissive`,
    );
  }
  // …and directional the other way, or a gate that rejected everything would
  // also look like it worked.
  assert.equal(allowanceFor("greenhouse.io")?.kind, "CHANNEL");
  assert.equal(allowanceFor("us.greenhouse-mail.io")?.kind, "CHANNEL");
  assert.equal(allowanceFor("harbor.io")?.kind, "FIXTURE");
  assert.equal(allowanceFor("careers.example.com")?.kind, "RESERVED");
  // A lookalike registration must not inherit a relay's allowance. The suffix
  // match requires the dot; `evil-greenhouse.io` is a different company.
  assert.equal(allowanceFor("evil-greenhouse.io"), null);
});

test("every allowance entry is still used by something", () => {
  // An entry nobody matches is a permanent hole: the tree could later grow a
  // real employer on that exact domain and inherit an excuse written for
  // something else. Removing a fixture is fine — remove its allowance in the
  // same commit, and the diff then says out loud that the excuse went with it.
  // This is also what keeps the allowlists from becoming a wishlist of every
  // ATS anyone could think of, which is how an allowlist stops being a gate.
  const seen = new Set();
  for (const root of ROOTS) {
    for (const hit of scanRoot(root.rel).addresses) {
      const channel = matchesEntry(hit.domain, CHANNEL);
      if (channel) seen.add(channel);
      const fixture = matchesEntry(hit.domain, FIXTURE_EMPLOYERS);
      if (fixture) seen.add(fixture);
    }
  }
  const unused = [...CHANNEL.keys(), ...FIXTURE_EMPLOYERS.keys()].filter((k) => !seen.has(k));
  assert.deepEqual(
    unused,
    [],
    `These allowances match nothing in the scanned roots any more: ${unused.join(", ")}. ` +
      "Delete the entries in the same commit that removed their fixtures — a standing " +
      "excuse for a domain nothing uses is a hole waiting for the wrong thing to fill it.",
  );
});
