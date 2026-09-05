/**
 * Does each ROW actually call the neutraliser? (#424)
 *
 * `hostile-text.test.mjs` proves `MailText` cleans and flags. That is not the
 * same claim as "the filed ledger cleans and flags", and the gap between the
 * two is where this defect lives: a surface that never calls `MailText` looks
 * exactly like one that does, in source and on screen, until a stranger sends
 * the mail that tells them apart.
 *
 * TWO TIERS, AND THE DIFFERENCE IS STATED RATHER THAN BLURRED.
 *
 *   TIER 1 — the surface is RENDERED with hostile bytes and its visible text
 *   is read. `FiledMailList`, `ImportRow`, `VerdictRow`, both halves of
 *   `MailPreview`, and — with the board half of #424 — `ApplicationRow` and its
 *   `RowOutcome` tombstone. This is the honest form and it is what #424 asks
 *   for. Five of the eight files reach it.
 *
 *   TIER 2 — a census of the source. `ReviewQueue`, `ReclassifyControl` and
 *   `ApplicationDetail` are here, NOT by choice: `helpers/renderTsx.mjs`
 *   cannot load them without a stub map nobody has written. Two separate
 *   causes, both measured:
 *     - `ReviewQueue` and `ReclassifyControl` defeat the helper's specifier
 *       rewriter. It rewrites `/(\bfrom\s*|\bimport\s*\(\s*)["']([^"']+)["']/`
 *       over the TRANSPILED output, and both files contain the JSX text
 *       `from {sender}`, which compiles to `"…from ", sender, …` — a literal
 *       `from "` the rewriter reads as an import specifier. The import then
 *       fails with `Cannot find package ', sender, item.role ? …'`.
 *     - `ApplicationDetail` fails earlier and for an ordinary reason: only the
 *       ENTRY module's specifiers are rewritten, so its `.tsx` siblings
 *       (`Dialog`, `GateMeter`, `MailText`) are handed to Node as `.tsx` and it
 *       answers `Unknown file extension ".tsx"`. Measured on the current tree —
 *       an older note here blamed a truncated `@/lib` specifier, which is not
 *       what it does now. That one is a stub map away rather than a helper fix,
 *       and it is the first of these three worth doing.
 *   Fixing the rewriter is a change to a helper 77 test files share, which is
 *   not this fix's scope. It is the follow-up, and until it lands those three
 *   surfaces are covered by a scan and a scan cannot see everything.
 *
 * WHY THE TIER-2 GATE IS NOT `source.includes("MailText")`. That form is this
 * repo's recorded recurring defect: it stays green when an argument is swapped
 * for another of the same type, and it stays green when ONE of a row's four
 * fields loses its wrapper. This gate is inverted instead — it looks for what
 * must NOT be there. Any mail-supplied field interpolated as JSX text, or into
 * a template literal, without passing through `MailText` or `safeText` is a
 * failure. Deleting a single call site restores exactly that shape, so the
 * gate reds on the smallest possible regression rather than on a whole file.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { createElement } from "react";

import { importTsx, markup, stubModule } from "./helpers/renderTsx.mjs";
import { visibleText } from "./helpers/visibleText.mjs";

const WEB_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

/**
 * The REAL `MailText`, routed through the stub registry.
 *
 * NOT A STAND-IN, and the distinction is the whole reason these tests are
 * worth anything. `renderTsx` rewrites import specifiers in the ENTRY module
 * only, so a surface that imports `components/mail/MailText.tsx` hands Node a
 * `.tsx` it cannot parse. This maps that one specifier to the genuine module —
 * same file, same transpiler, same React, same sanitiser — so the row under
 * test really does call the real thing. A stub that faked the cleaning would
 * make every assertion below pass on the stub's behalf, which is why nothing
 * here fakes it.
 */
const { MailText } = await importTsx("components/mail/MailText.tsx");
const REAL_MAIL_TEXT = { "@/components/mail/MailText": stubModule({ MailText }) };
const { MailSnippet, OpenInGmail } = await importTsx("components/mail/MailPreview.tsx", {
  stubs: REAL_MAIL_TEXT,
});

const cp = (n) => String.fromCodePoint(n);
const RLO = cp(0x202e); // RIGHT-TO-LEFT OVERRIDE
const PDF = cp(0x202c); // POP DIRECTIONAL FORMATTING
const ZWSP = cp(0x200b); // ZERO WIDTH SPACE
const SENTINEL = cp(0xfffd);

/** The subject #424 measured: the bytes say `.exe`, the screen said `.jpg`. */
const HOSTILE_SUBJECT = `Payroll ${RLO}gpj.exe${PDF}`;
/**
 * The forged/genuine sender pair, and the invariant that makes it mean
 * something.
 *
 * PROVENANCE. #424 measured this against a real applicant-tracking system's
 * no-reply address. The SHAPE is the measured one — a `no-reply` local part on
 * an employer-facing ATS domain — and the particulars are invented on a domain
 * reserved by RFC 2606, per `docs/TEST_DATA_POLICY.md`. Nothing here can reach
 * a mailbox, and the property under test does not need a routable domain: a
 * forgery rendering identically to a genuine address is just as true of an
 * invented one.
 *
 * GENUINE IS A LITERAL ON PURPOSE. `scripts/check_test_data.py` cannot see an
 * address that is interpolated or assembled — an `@` followed by `{` or a
 * concatenation is invisible to its regex (#647) — so a pair built out of
 * fragments would sail past that gate without it ever having read the domain.
 *
 * FORGED IS DERIVED FROM IT, not written a second time. That is what
 * guarantees the two differ by exactly one invisible character, which is the
 * whole property the strip-versus-sentinel assertion rests on. Two
 * hand-written literals could lose it to a typo and the test would then pass
 * for the wrong reason.
 */
const GENUINE_SENDER = "no-reply@harbourgate.test";
const HOSTILE_SENDER = GENUINE_SENDER.replace("@", `${ZWSP}@`);

/**
 * Every assertion a hostile row must satisfy, in one place so a surface cannot
 * be "covered" by a weaker set than its neighbour.
 */
function assertRowIsHonest(html, where) {
  assert.equal(html.includes(RLO), false, `${where}: U+202E reached the markup`);
  assert.equal(html.includes(PDF), false, `${where}: U+202C reached the markup`);
  assert.equal(html.includes(ZWSP), false, `${where}: U+200B reached the markup`);
  const text = visibleText(html);
  assert.equal(text.includes("exe.jpg"), false, `${where}: the override survived`);
  assert.match(text, /gpj\.exe/, `${where}: the subject's real bytes are not on the row`);
  assert.equal(
    text.includes(GENUINE_SENDER),
    false,
    `${where}: the forged sender rendered as the GENUINE address — stripped, not substituted`,
  );
  assert.match(html, /data-testid="hidden-character-flag"/, `${where}: cleaned in silence, no flag`);
}

// ---------------------------------------------------------------------------
// TIER 1 — rendered.
// ---------------------------------------------------------------------------

/**
 * Sibling components this row merely mounts, replaced so the entry can load.
 *
 * Each is an INPUT to the code under test, never a stand-in for it: the row's
 * own markup is the real thing and real `react-dom/server` renders it. That is
 * the line `helpers/renderTsx.mjs` draws and this stays on the right side of
 * it — nothing here renders a subject or a sender, so nothing here can make
 * the assertions pass on the stub's behalf.
 */
function stubLeaf(name) {
  function Stub(props) {
    return createElement("span", { "data-stub": name }, props?.children ?? null);
  }
  Stub.displayName = `Stub(${name})`;
  return Stub;
}

test("the forged sender is the genuine one plus one invisible character", () => {
  // Guards `assertRowIsHonest`. If the pair differed in any other byte, "the
  // forged sender did not render as the GENUINE address" would pass for the
  // wrong reason on every surface at once.
  assert.equal(HOSTILE_SENDER.replaceAll(ZWSP, ""), GENUINE_SENDER);
  assert.equal(HOSTILE_SENDER.length, GENUINE_SENDER.length + 1);
  assert.notEqual(HOSTILE_SENDER, GENUINE_SENDER);
});

test("the filed ledger neutralises and flags a hostile row", async () => {
  const { FiledMailList } = await importTsx("components/mail/FiledMailList.tsx", {
    stubs: {
      "next/link": stubModule({ default: stubLeaf("link") }),
      "@/components/mail/MailPreview": stubModule({
        MailSnippet: stubLeaf("snippet"),
        OpenInGmail: stubLeaf("open"),
      }),
      "@/components/mail/ReclassifyControl": stubModule({ ReclassifyControl: stubLeaf("reclass") }),
      "@/components/viz/GateMeter": stubModule({ GateMeter: stubLeaf("meter") }),
      ...REAL_MAIL_TEXT,
    },
  });

  const page = {
    messages: [
      {
        message_id: "m1",
        thread_id: null,
        subject: HOSTILE_SUBJECT,
        sender_name: null,
        sender_email: HOSTILE_SENDER,
        received_at: "2026-08-01T00:00:00Z",
        snippet: null,
        category: "rejection",
        confidence: 0.94,
        method: "rules",
        user_corrected: false,
        disposition: null,
        company: `Harbour${ZWSP}gate`,
        application_id: null,
        on_board: false,
        gmail_link: null,
        employer_token: null,
        dismissed_reason: null,
      },
    ],
    total: 1,
    page: 1,
    pageSize: 50,
    categoryCounts: { rejection: 1 },
  };

  const html = markup(
    createElement(FiledMailList, { page, activeCategory: null, q: null, board: [] }),
  );
  assertRowIsHonest(html, "FiledMailList");
  // The employer beside the sender is mail-derived too, and an unterminated
  // override there would reverse the rest of the line, not just the name.
  assert.equal(visibleText(html).includes("Harbourgate"), false);
  assert.match(visibleText(html), new RegExp(`Harbour${SENTINEL}gate`));
});

test("the public /import row neutralises and flags a hostile row", async () => {
  // The surface #424 was found on: unauthenticated, so every string on it came
  // from a stranger by construction.
  const { ImportRow } = await importTsx("components/import/ImportMail.tsx", {
    stubs: {
      "@/lib/demo/rulesLayer": stubModule({
        classifyWithRules: () => ({ category: "rejection", confidence: 0.94, scores: {} }),
      }),
      ...REAL_MAIL_TEXT,
    },
  });

  const html = markup(
    createElement(ImportRow, {
      item: {
        id: "1",
        subject: HOSTILE_SUBJECT,
        senderName: `Harbour${ZWSP}gate`,
        senderEmail: HOSTILE_SENDER,
        body: "",
        category: "rejection",
        confidence: 0.94,
        answeredByRules: true,
        clearsGate: true,
        topScores: [],
      },
    }),
  );
  assertRowIsHonest(html, "ImportRow");
});

test("the signed-in live scan neutralises and flags a hostile row", async () => {
  const { VerdictRow } = await importTsx("components/gmail/InboxWorkbench.tsx", {
    stubs: {
      "next/link": stubModule({ default: stubLeaf("link") }),
      "next/navigation": stubModule({ useRouter: () => ({ refresh() {} }) }),
      "@/components/gmail/ConnectGmailButton": stubModule({ ConnectGmailButton: stubLeaf("gmail") }),
      "@/components/mail/MailPreview": stubModule({
        MailSnippet: stubLeaf("snippet"),
        OpenInGmail: stubLeaf("open"),
      }),
      "@/components/mail/ReclassifyControl": stubModule({ ReclassifyControl: stubLeaf("reclass") }),
      "@/components/viz/GateMeter": stubModule({ GateMeter: stubLeaf("meter") }),
      "@/components/ui/Segmented": stubModule({ Segmented: stubLeaf("segmented") }),
      ...REAL_MAIL_TEXT,
    },
  });

  const html = markup(
    createElement(VerdictRow, {
      v: {
        message_id: "m1",
        subject: HOSTILE_SUBJECT,
        sender_name: null,
        sender_email: HOSTILE_SENDER,
        company: `Harbour${ZWSP}gate`,
        category: "rejection",
        confidence: 0.94,
        needs_review: false,
        received_at: "2026-08-01T00:00:00Z",
        snippet: null,
        gmail_link: null,
        user_corrected: false,
      },
      onCorrected: () => {},
      classify: async () => ({ ok: true }),
    }),
  );
  assertRowIsHonest(html, "VerdictRow");
});

test("the shared snippet neutralises and flags — a body is attacker-written too", () => {
  const html = markup(MailSnippet({ snippet: `We regret ${RLO}gpj.exe${PDF}` }));
  assert.equal(html.includes(RLO), false);
  assert.equal(visibleText(html).includes("exe.jpg"), false);
  assert.match(html, /data-testid="hidden-character-flag"/);
});

test("the Gmail link's accessible name cannot be reversed by the subject it names", () => {
  // An UNTERMINATED override is not scoped to its own substring: it reverses
  // everything after it. In `Open “${subject}” in Gmail` that is the REST of
  // the control's announced name, so the label needs the neutralised form even
  // though nothing about it is visible.
  const html = markup(
    OpenInGmail({ href: "https://mail.google.com/mail/#all/t1", subject: `Payroll ${RLO}gpj.exe` }),
  );
  const label = /aria-label="([^"]*)"/.exec(html);
  assert.notEqual(label, null, "the link lost its accessible name");
  assert.equal(label[1].includes(RLO), false, "U+202E reached the accessible name");
  assert.match(label[1], /Payroll .gpj\.exe. in Gmail/);
});

/**
 * The BOARD row — the other half of #424, and the half that is not about a
 * message at all.
 *
 * A card's `company` and `role` are read out of mail by the sync, so they carry
 * whatever an applicant-tracking system put in a display name. This renders the
 * real component and reads both, because the two are drawn by different code
 * paths (an element for the company, an element plus a `title` for the role)
 * and a fix that wrapped one is indistinguishable from a fix that wrapped both
 * until you look.
 */
test("the board row neutralises and flags a hostile company AND role", async () => {
  const { ApplicationRow } = await importTsx("components/dashboard/ApplicationRow.tsx", {
    stubs: {
      "next/navigation": stubModule({ useRouter: () => ({ refresh() {} }) }),
      "@/components/dashboard/CardMeta": stubModule({
        DeadlineTag: stubLeaf("deadline"),
        FiledStamp: stubLeaf("filed"),
        SameCompanyChip: stubLeaf("chip"),
      }),
      "@/components/dashboard/RowActionsMenu": stubModule({ RowActionsMenu: stubLeaf("menu") }),
      "@/components/feedback/notify": stubModule({ notifySuccess: () => {} }),
      "@/lib/dashboard/transport": stubModule({ liveBoardTransport: {} }),
      ...REAL_MAIL_TEXT,
    },
  });

  const html = markup(
    createElement(ApplicationRow, {
      app: {
        id: 1,
        company: `Harbour${ZWSP}gate`,
        position: HOSTILE_SUBJECT,
        position_source: null,
        status: "applied",
        source: "gmail",
        due_at: null,
        applied_date: "2026-08-01",
        created_at: "2026-08-01T00:00:00Z",
        url: "https://mail.google.com/mail/#all/t1",
      },
      today: "2026-08-04",
      onOpenDetail: () => {},
    }),
  );

  assert.equal(html.includes(RLO), false, "ApplicationRow: U+202E reached the markup");
  assert.equal(html.includes(PDF), false, "ApplicationRow: U+202C reached the markup");
  assert.equal(html.includes(ZWSP), false, "ApplicationRow: U+200B reached the markup");

  const text = visibleText(html);
  // The role: the bytes say `.exe` and the screen must not say `.jpg`.
  assert.equal(text.includes("exe.jpg"), false, "the override survived in the role");
  assert.match(text, /gpj\.exe/, "the role's real bytes are not on the row");
  // The company: substituted, not stripped — a strip would render the clean
  // employer name and make a false claim look checked.
  assert.equal(text.includes("Harbourgate"), false, "the company was stripped, not substituted");
  assert.match(text, new RegExp(`Harbour${SENTINEL}gate`));
  // Two flags, because two different fields were hostile. One would mean the
  // row cleaned a field in silence, which is the half of #424 that gets skipped.
  assert.equal(
    html.split('data-testid="hidden-character-flag"').length - 1,
    2,
    "the row drew a flag for only one of its two hostile fields",
  );

  // The attribute half, by execution rather than by the source census: a
  // `title` and an accessible name are strings and cannot hold an element, so
  // they take `safeText` — and an unterminated override in one of them rewrites
  // the rest of the announced name, not just its own part.
  for (const attribute of ["title", "aria-label"]) {
    const values = [...html.matchAll(new RegExp(`${attribute}="([^"]*)"`, "g"))].map((m) => m[1]);
    assert.ok(values.length > 0, `the row rendered no ${attribute} at all`);
    for (const value of values) {
      assert.equal(value.includes(RLO), false, `U+202E reached a ${attribute}`);
      assert.equal(value.includes(ZWSP), false, `U+200B reached a ${attribute}`);
    }
  }
});

/**
 * The tombstone, which no static render can reach.
 *
 * Both outcome lines live behind `useState` (`removalPending`, `removed`), so
 * `renderToStaticMarkup` only ever sees the row's initial state and neither
 * branch is on any rendered path here. They are also the sites the source
 * census cannot see — the row used to draw `{removalPendingMessage(app.company,
 * …)}`, a call expression the scanner reads straight past. `RowOutcome` is the
 * component that composition became, and calling it directly is what puts the
 * line under execution instead of under a scan.
 */
test("the removal tombstone neutralises and flags the employer it names", async () => {
  const { RowOutcome } = await importTsx("components/dashboard/ApplicationRow.tsx", {
    stubs: {
      "next/navigation": stubModule({ useRouter: () => ({ refresh() {} }) }),
      "@/components/dashboard/CardMeta": stubModule({
        DeadlineTag: stubLeaf("deadline"),
        FiledStamp: stubLeaf("filed"),
        SameCompanyChip: stubLeaf("chip"),
      }),
      "@/components/dashboard/RowActionsMenu": stubModule({ RowActionsMenu: stubLeaf("menu") }),
      "@/components/feedback/notify": stubModule({ notifySuccess: () => {} }),
      "@/lib/dashboard/transport": stubModule({ liveBoardTransport: {} }),
      ...REAL_MAIL_TEXT,
    },
  });

  const html = markup(
    RowOutcome({ company: `Harbour${ZWSP}gate${RLO}`, tail: " removed from the board · not deleted" }),
  );

  assert.equal(html.includes(RLO), false, "RowOutcome: U+202E reached the markup");
  assert.equal(html.includes(ZWSP), false, "RowOutcome: U+200B reached the markup");
  assert.match(html, /data-testid="hidden-character-flag"/, "cleaned in silence, no flag");
  // The tail is what the override used to reverse: it follows the name inside
  // one paragraph, and the name had no element of its own to be isolated in.
  assert.match(visibleText(html), /removed from the board · not deleted$/);
  assert.equal(visibleText(html).includes("Harbourgate"), false);
});

test("a row with ordinary non-ASCII is untouched and unflagged", () => {
  // The regression this fix must not be: a French name is not an attack.
  const snippet = "Bonjour Zoë Lefèvre — nous avons bien reçu votre candidature. 株式会社";
  const html = markup(MailSnippet({ snippet }));
  assert.equal(visibleText(html), snippet);
  assert.doesNotMatch(html, /hidden-character-flag/);
});

// ---------------------------------------------------------------------------
// TIER 2 — the census.
// ---------------------------------------------------------------------------

/**
 * The message's own fields — exactly what #424 names, and what this fix is
 * accountable for on every surface in the list below.
 */
const MESSAGE_FIELDS = [
  "subject",
  "sender",
  "senderName",
  "senderEmail",
  "sender_name",
  "sender_email",
  "snippet",
];

/**
 * The message's fields PLUS the two the backend reads out of them.
 *
 * A control character in a header survives into `company` and `role`, so on a
 * mail row — where they are drawn beside the sender and are read as part of
 * the same claim — they are held to the same bar.
 */
const MAIL_ROW_FIELDS = [...MESSAGE_FIELDS, "company", "role", "suggested_employer"];

/**
 * Every surface that draws a string a stranger chose, and which fields each is
 * held to.
 *
 * Deliberately NOT a glob over `components/`. `demo/SampleInbox.tsx`,
 * `landing/InboxScene.tsx`, `viz/DecisionTrace.tsx` and `marketing/*` all draw
 * subjects and senders too, and every one of them is a hardcoded fixture
 * checked into this repo — no attacker reaches them, and wrapping them would
 * spend the reader's attention on a warning that can never fire.
 *
 * THE BOARD IS IN SCOPE NOW, AND WHAT IS STILL OUT. An APPLICATION's `company`
 * and `role` — the board's own identity for a card — are mail-derived too, and
 * this note used to say they were not covered and that closing them was a
 * second issue. That is the remaining half of #424 and it is closed here for
 * the two surfaces that draw a whole card: `ApplicationRow` and
 * `ApplicationDetail`, both now held to `MAIL_ROW_FIELDS`. The value is
 * attacker-chosen end to end — an ATS display name reaches `company` through
 * `_clean_sender_display_name` / `_valid_company_token`
 * (`backend/jobtracker/cloud/pipeline.py`), which reject stopwords, requisition
 * codes and digits and cap length, and apply no character class at any point.
 *
 * `role` is `app.position`, whose `position_source` is `"user"` for a typed
 * title and NULL when the sync extracted it. Only the NULL rows are
 * mail-derived, and the components neutralise BOTH — see `ApplicationRow`'s
 * note on `role`. A provenance branch would leave a raw render path gated on a
 * flag that is not a trust boundary, which is the shape this gate exists to
 * remove.
 *
 * STILL OUT, AND STILL A SECOND ISSUE: the six other components that draw a
 * card's identity — `PipelineBoard`, `CompanyBand`, `EmployerSetRow`,
 * `CardMeta`, `PulseDetail`, `SyncBar`. They take `company` as a PROP from the
 * two surfaces above, so this gate's `=` exclusion lets it through and their
 * own renders are unscanned. That is a real gap, not a decision that they are
 * safe.
 */
const ATTACKER_FACING = [
  { file: "components/import/ImportMail.tsx", fields: MAIL_ROW_FIELDS },
  { file: "components/mail/FiledMailList.tsx", fields: MAIL_ROW_FIELDS },
  { file: "components/mail/MailPreview.tsx", fields: MAIL_ROW_FIELDS },
  { file: "components/mail/ReclassifyControl.tsx", fields: MAIL_ROW_FIELDS },
  { file: "components/gmail/InboxWorkbench.tsx", fields: MAIL_ROW_FIELDS },
  { file: "components/dashboard/ReviewQueue.tsx", fields: MAIL_ROW_FIELDS },
  { file: "components/dashboard/ApplicationRow.tsx", fields: MAIL_ROW_FIELDS },
  { file: "components/dashboard/ApplicationDetail.tsx", fields: MAIL_ROW_FIELDS },
];

/** Comments say `{company}` all over this repo and mean nothing by it. */
function stripComments(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/[^\n]*/g, "$1");
}

/**
 * Attributes and props whose value is DRAWN or ANNOUNCED on its own.
 *
 * The `=` exclusion below used to be unconditional, and this set is the hole it
 * left. `title={role}` is not a prop handed to a sanitising component — it is a
 * string the browser paints in a tooltip and a screen reader reads out, and a
 * bare identifier there was invisible to this gate. It is not a hypothetical:
 * `ApplicationRow` carried `title={role}` twice and `ApplicationDetail` carried
 * `title={active.company}`, and a fix that wrapped only the JSX text would have
 * left all three raw and this file green.
 *
 * `description` and `label` are React PROPS rather than HTML attributes, which
 * is why this is not called an attribute list: `Dialog` renders `description`
 * as visible text (`components/ui/Dialog.tsx`) and `RowActionsMenu` announces
 * `label`. What decides membership is whether the STRING reaches a person, not
 * whether the DOM has an attribute by that name.
 */
const RENDERED_ATTRIBUTES = new Set([
  "title",
  "alt",
  "placeholder",
  "label",
  "description",
  "aria-label",
  "aria-description",
  "aria-placeholder",
  "aria-roledescription",
  "aria-valuetext",
]);

/** The attribute or prop name an interpolation at `index` is the value of. */
function attributeAt(source, index) {
  const before = source.slice(Math.max(0, index - 48), index);
  const m = /([A-Za-z_$][\w$-]*)=$/.exec(before);
  return m === null ? null : m[1];
}

/**
 * Mail-supplied fields interpolated raw — as JSX text, into a template literal,
 * or into an attribute that renders — rather than through `MailText` /
 * `safeText`.
 *
 * An interpolation preceded by `=` is an ATTRIBUTE (`value={subject}`,
 * `subject={subject}`). Those are allowed: the first IS the sanitiser's call
 * site, and the second hands the string to a component that sanitises it, and
 * that component is itself in this list. `RENDERED_ATTRIBUTES` is the carve-out
 * from that carve-out — an attribute whose value goes straight to a person is
 * held to the same bar as JSX text.
 *
 * `||` and `??` both end the expression being read, so `{role || "not set"}`
 * and `{c.role ?? "none"}` are the same claim about `role` and are treated
 * alike. Handling only `||` made the nullish form a one-character bypass.
 *
 * WHAT THIS STILL CANNOT SEE, so it is written down rather than discovered.
 * A mail field passed to a FUNCTION and rendered — `{someMessage(app.company)}`
 * — parses as a call, fails the identifier test and is invisible here. That
 * shape was real: the row's two tombstones drew
 * `{removalPendingMessage(app.company, …)}`, one composed string with the
 * employer name already inside it and no element able to hold a sanitiser. It
 * is fixed by giving the name its own element (`RowOutcome`), and it is covered
 * by RENDERING that component in tier 1 above, not by this scan. A scan cannot
 * see everything, which is why the tier-1 list exists.
 */
function rawMailInterpolations(source, fields) {
  const wanted = new Set(fields);
  const hits = [];
  const re = /\{([^{}]+)\}/g;
  for (let m = re.exec(source); m !== null; m = re.exec(source)) {
    if (source[m.index - 1] === "=" && !RENDERED_ATTRIBUTES.has(attributeAt(source, m.index))) {
      continue;
    }
    const head = m[1].replace(/(?:\|\||\?\?)[\s\S]*$/, "").trim();
    if (!/^[A-Za-z_$][\w$]*(?:(?:\?\.|\.)[\w$]+)*$/.test(head)) continue;
    if (!wanted.has(head.split(".").pop())) continue;
    hits.push(m[1].trim());
  }
  return hits;
}

test("the census can see a raw render — positive control", () => {
  // A scanner that matches nothing reports "clean" and "never ran" with the
  // same output. Eight shapes it must catch, and five it must not.
  const scan = (s) => rawMailInterpolations(s, MAIL_ROW_FIELDS);

  assert.deepEqual(scan(`<p>{item.subject}</p>`), ["item.subject"]);
  assert.deepEqual(scan(`<p>\n  {sender}\n</p>`), ["sender"]);
  assert.deepEqual(scan('aria-label={`Open “${subject}”`}'), ["subject"]);
  assert.deepEqual(scan(`<p>{m.subject || "(no subject)"}</p>`), ['m.subject || "(no subject)"']);
  assert.deepEqual(scan("{item.role ? `, ${item.role}` : ''}"), ["item.role"]);
  // The attribute hole. A bare identifier in a slot that renders was invisible
  // until `RENDERED_ATTRIBUTES`, and these three were all occupied in the tree.
  assert.deepEqual(scan(`title={role}`), ["role"]);
  assert.deepEqual(scan(`title={active.company}`), ["active.company"]);
  assert.deepEqual(scan(`description={role || "role not captured yet"}`), [
    'role || "role not captured yet"',
  ]);
  // `??` is `||`'s twin and was a one-character bypass.
  assert.deepEqual(scan(`<li>{c.role ?? "no role named in this mail"}</li>`), [
    'c.role ?? "no role named in this mail"',
  ]);

  assert.deepEqual(scan(`<MailText value={item.subject} />`), []);
  assert.deepEqual(scan(`<Control subject={subject} />`), []);
  assert.deepEqual(scan(`<p>{safeText(sender)}</p>`), []);
  // The allowed-attribute exclusion has to SURVIVE the tightening, or every
  // sanitiser call site in the tree becomes a false positive and the gate is
  // red for a reason that has nothing to do with a raw render.
  assert.deepEqual(scan(`<MailText value={company} />`), []);
  assert.deepEqual(scan(`title={safeText(role)}`), []);

  // And the per-file narrowing has to stay real, because it is what lets a
  // surface be held to the message set alone: a board field must be invisible
  // to `MESSAGE_FIELDS` and visible to `MAIL_ROW_FIELDS`. No entry uses the
  // narrow set today; the mechanism is asserted anyway, so the next one that
  // needs it is not adopting an untested narrowing.
  assert.deepEqual(rawMailInterpolations(`<h1>{active.company}</h1>`, MESSAGE_FIELDS), []);
  assert.deepEqual(rawMailInterpolations(`<h1>{active.company}</h1>`, MAIL_ROW_FIELDS), [
    "active.company",
  ]);
});

test("every attacker-facing surface is in the tree and non-empty", () => {
  // A renamed or moved file would otherwise make the sweep below pass by
  // measuring nothing at all.
  assert.ok(ATTACKER_FACING.length >= 8);
  for (const { file } of ATTACKER_FACING) {
    const source = readFileSync(resolve(WEB_ROOT, file), "utf8");
    assert.ok(source.length > 500, `${file} is suspiciously small`);
    assert.match(source, /MailText|safeText/, `${file} does not reference the neutraliser at all`);
  }
});

for (const { file, fields } of ATTACKER_FACING) {
  test(`${file} renders no mail-supplied field raw`, () => {
    const source = stripComments(readFileSync(resolve(WEB_ROOT, file), "utf8"));
    assert.deepEqual(
      rawMailInterpolations(source, fields),
      [],
      `${file} interpolates a mail-supplied field without MailText or safeText`,
    );
  });
}
