/**
 * The settings publish contract: any section that writes user metadata must
 * also publish the write to the router cache.
 *
 * WHY THIS GATE EXISTS. `/settings` used to pin itself out of the router
 * cache (`unstable_dynamicStaleTime = 0`) as a backstop against exactly one
 * future defect: a NEW section calling `saveMetadata` without a
 * `router.refresh()`, whose saved value would then visibly revert for up to
 * 30 s on the next visit — a control lying about its own state (#216). That
 * backstop cost 700–1150 ms of re-paid origin time on EVERY dashboard→
 * settings navigation (#203) to guard against a defect that can be caught
 * here instead, at zero runtime cost. Removing the pin (perf/nav-latency) is
 * only sound while this gate stands: if this test is deleted, the pin's
 * argument comes back.
 *
 * WHAT IT ASSERTS. Every source under `components/settings/` that writes
 * account state also contains `router.refresh()`. Source-level and crude on
 * purpose — the alternative (executing each section) needs a DOM none of
 * these unit tests have. A false positive (refresh present but unreachable)
 * is possible; a false NEGATIVE — a write with no refresh anywhere in the
 * file — is not, and the paragraph below is what makes that second half true.
 *
 * A COMMENT USED TO BE ENOUGH — this gate had joined the family it exists to
 * police. The predicate ran `includes("router.refresh()")` over raw file text,
 * and `ProfilePhotoField.tsx`'s docblock says "Both writes end in
 * `router.refresh()`". Deleting BOTH real calls left this test green; only
 * deleting the sentence describing them turned it red. The shape was already
 * here before the photo field: `NotificationsSection.tsx` explains what
 * `router.refresh()` does to the segment cache in a comment, and
 * `AppearanceSection.tsx` mentions it in one too — three of the five writers
 * carried their own alibi. So every file is stripped of its comments before
 * the predicate reads it, by the TypeScript compiler rather than a regex,
 * because `//` inside a URL, an apostrophe in JSX text and a comment written
 * inside a JSX expression container are three things a hand-rolled stripper
 * gets wrong (all three are fixtures below). What remains reachable is a
 * string literal holding the call — a far stranger thing to write by accident
 * than a sentence describing what the code does.
 *
 * THE WRITE LIST GREW. It was `saveMetadata(` alone. The profile photo
 * (`ProfilePhotoField`) writes through its own transport calls — the bytes go
 * to a route handler, not to `updateUser` in the browser — so the original
 * predicate would have waved it straight through while it fed exactly the same
 * defect: the tile is server-rendered into the shell's rail, so a photo saved
 * without publishing sits behind the 300 s router cache and the sidebar keeps
 * showing the old one. Any future transport call that changes what a server
 * render prints belongs in this list.
 *
 * The predicate itself is exercised against a synthetic offender below, so
 * the gate is proven able to fail before it is trusted on the real tree
 * (the checks-that-cannot-fail rule).
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import ts from "typescript";

const SETTINGS_DIR = join(
  dirname(fileURLToPath(import.meta.url)),
  "../../components/settings",
);

/** The transport calls that change what a server render of the shell or the
 *  settings page will print. */
const WRITE_CALL = /\b(saveMetadata|uploadAvatar|removeAvatar)\(/;

/**
 * The CODE of a settings section — everything its comments say, removed.
 *
 * `ts.transpileModule` rather than a hand-written stripper: knowing that `//`
 * inside `https://…` is not a comment, that the apostrophe in JSX text is not
 * a string, and that a comment can be written inside a JSX expression
 * container where no plain block-comment scanner would look, is the compiler's
 * job and it already does it. `typescript` is already a devDependency and
 * already how three other tests here read TypeScript (`helpers/renderTsx.mjs`,
 * `api-no-store-headers`, `profile-avatar`). `JsxEmit.React` is deliberate: it
 * turns JSX text into string literals and drops comment-only expression
 * containers outright.
 */
function withoutComments(source, fileName = "/Synthetic.tsx") {
  return ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.React,
      removeComments: true,
    },
    fileName,
  }).outputText;
}

/** Does this comment-free code write account state without publishing the
 *  write? Takes what `withoutComments` returns, never raw file text. */
function violatesPublishContract(code) {
  return WRITE_CALL.test(code) && !code.includes("router.refresh()");
}

test("the predicate can fail: a write without a refresh is flagged", () => {
  for (const call of [
    'transport.saveMetadata({ theme_accent: accent })',
    "transport.uploadAvatar(prepared.blob)",
    "transport.removeAvatar()",
  ]) {
    const offender = `
      const { ok } = await ${call};
      setState(ok ? "saved" : "error");
    `;
    assert.equal(
      violatesPublishContract(withoutComments(offender)),
      true,
      `${call} was not seen as a write`,
    );
    const publisher = `${offender}\n      if (ok) router.refresh();`;
    assert.equal(violatesPublishContract(withoutComments(publisher)), false);
  }
});

test("a comment describing the call does not stand in for the call", () => {
  // The hole itself, as three fixtures. Each of these writes and never
  // publishes, and each mentions `router.refresh()` somewhere the compiler
  // treats as prose — which is precisely what shipped: both real calls were
  // deleted from ProfilePhotoField.tsx and this file stayed green.
  const write = "const { ok } = await transport.uploadAvatar(blob);";
  for (const [where, alibi] of [
    ["a docblock", "/**\n * Both writes end in `router.refresh()`: the photo is\n */"],
    ["a line comment", "// then router.refresh(), because the rail is server-rendered"],
    ["a JSX comment", "const tile = <p>{/* router.refresh() runs above */}saved</p>;"],
  ]) {
    assert.equal(
      violatesPublishContract(withoutComments(`${alibi}\n${write}`)),
      true,
      `${where} stood in for the call it describes`,
    );
  }

  // And the other direction, which is what makes stripping with a compiler
  // worth the import: the three constructs a regex stripper eats. The call is
  // real in this one, so any of them being swallowed shows up as a false alarm.
  const awkward = [
    'const doc = "https://nextjs.org/docs/app/api-reference/functions/use-router";',
    "const hint = <p>Don't lose this</p>;",
    "const re = /[\"']\\/\\//;",
  ].join("\n");
  assert.equal(
    violatesPublishContract(withoutComments(`${awkward}\n${write}\nif (ok) router.refresh();`)),
    false,
    "stripping ate real code — a URL, JSX text or a regex was read as a comment",
  );
});

test("every settings section that calls saveMetadata also calls router.refresh", () => {
  const files = readdirSync(SETTINGS_DIR).filter((f) => /\.tsx?$/.test(f));
  // Stripped once per file, and the vacuity check and the predicate both read
  // that same text: otherwise the two disagree about what "the source" is, and
  // a comment naming a write would make a non-writer register as a writer.
  const code = new Map(
    files.map((f) => {
      const path = join(SETTINGS_DIR, f);
      return [f, withoutComments(readFileSync(path, "utf8"), path)];
    }),
  );

  // The stripper has to have worked. A `transpileModule` that returned nothing
  // — a swallowed throw, a fileName it would not parse — leaves every file
  // both comment-free AND write-free, and the scan below passes having read
  // air. This is the same defect one level up, so it is checked rather than
  // assumed.
  assert.ok(
    code.get("ProfilePhotoField.tsx")?.includes("router.refresh()"),
    "stripping removed ProfilePhotoField.tsx's real router.refresh() calls — every assertion below would be vacuous",
  );
  // And per file, because the failure direction is silent: a section whose
  // stripped output came back empty holds no write call either, so it drops
  // out of `writers` and out of `offenders` at once — a writer going dark
  // without a single assertion noticing.
  for (const [file, stripped] of code) {
    assert.ok(
      stripped.trim().length > 0,
      `stripping produced no code for ${file} — the scan cannot see it at all`,
    );
  }

  // The contract must actually be examining the known writers — an empty or
  // wrongly-pointed scan would pass vacuously (zero-match = failure).
  const writers = files.filter((f) => WRITE_CALL.test(code.get(f)));
  assert.ok(
    writers.includes("ProfileSection.tsx") &&
      writers.includes("NotificationsSection.tsx") &&
      writers.includes("ProfilePhotoField.tsx"),
    `scan is not seeing the known metadata writers — found: ${writers.join(", ") || "none"}`,
  );

  const offenders = files.filter((f) => violatesPublishContract(code.get(f)));
  assert.deepEqual(
    offenders,
    [],
    `these settings sections write metadata without router.refresh(), which shows ` +
      `stale controls for 30 s under the router cache (see app/(app)/(protected)/settings/page.tsx): ` +
      offenders.join(", "),
  );
});
