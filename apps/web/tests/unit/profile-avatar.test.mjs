/**
 * Profile photos: the precedence rule, the two guards around it, and the one
 * agreement that has no other way of being checked.
 *
 * WHY THESE ARE THE TESTS. Three of the four things that can go wrong here are
 * silent by construction:
 *
 *   1. An uploaded photo stored under a key GoTrue also writes would be
 *      overwritten by Google's on the next OAuth sign-in — a user's explicit
 *      choice reverting itself, days later, with nothing on screen to explain
 *      it. That the merge leaves other keys alone is already load-bearing in
 *      production: `display_name` lives in the same blob on an account that
 *      also holds a Google identity. So the property to pin is the KEY NAME,
 *      which is what the test below does.
 *   2. `user_metadata` is user-writable (`supabase.auth.updateUser`), so both
 *      values these rules read are attacker-influenced. The host check and the
 *      folder check are what stop that reaching the image optimizer.
 *   3. `next.config.ts` decides which hosts the optimizer will fetch. A URL
 *      this module ALLOWS and the config REFUSES does not throw — the image
 *      404s and the tile quietly falls back to the monogram, which looks
 *      exactly like "the account has no photo". Nothing else compares the two,
 *      so the last test does.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve as resolvePath } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import ts from "typescript";

import {
  AVATAR_METADATA_KEY,
  avatarObjectUrl,
  customAvatarPath,
  googleAvatarUrl,
  isBucketMissing,
  newAvatarPath,
  resolveAvatar,
  sniffAvatarType,
} from "../../lib/profile/avatar.ts";

const WEB_ROOT = resolvePath(dirname(fileURLToPath(import.meta.url)), "../..");

/** The live project's Supabase origin. Spelled out rather than derived so the
 *  last test can actually compare it with what `next.config.ts` allows — a
 *  value taken FROM the config could never disagree with the config. */
const SUPABASE_URL = "https://jbyvatoodyqqvkqbsrju.supabase.co";
const UID = "11111111-2222-4333-8444-555555555555";
const GOOGLE_PHOTO = "https://lh3.googleusercontent.com/a/ACg8ocKexample=s96-c";

/** The shape `getUser()` hands back for a Google sign-in. */
function googleUser(extra = {}) {
  return {
    id: UID,
    identities: [
      { provider: "google", identity_data: { avatar_url: GOOGLE_PHOTO, picture: GOOGLE_PHOTO } },
    ],
    user_metadata: { avatar_url: GOOGLE_PHOTO, picture: GOOGLE_PHOTO, full_name: "A Y" },
    ...extra,
  };
}

test("the metadata key can never collide with what an OAuth sign-in writes", () => {
  // The keys GoTrue merges into raw_user_meta_data from a Google identity,
  // read off the live account. If a future refactor renames the avatar key to
  // any of these, the user's uploaded photo silently reverts on their next
  // Google sign-in — the failure this whole naming decision exists to prevent.
  const PROVIDER_WRITTEN = [
    "avatar_url",
    "picture",
    "full_name",
    "name",
    "email",
    "provider_id",
    "sub",
    "iss",
    "email_verified",
    "phone_verified",
  ];
  assert.ok(
    !PROVIDER_WRITTEN.includes(AVATAR_METADATA_KEY),
    `${AVATAR_METADATA_KEY} is a key Google's identity data writes — an upload stored there would be overwritten at the next sign-in`,
  );
});

test("an upload wins over the Google photo, and knows Google is still there", () => {
  const path = `${UID}/f6a1b2c3-0000-4000-8000-abcdefabcdef.webp`;
  const resolved = resolveAvatar(googleUser({ user_metadata: { ...googleUser().user_metadata, [AVATAR_METADATA_KEY]: path } }), SUPABASE_URL);

  assert.equal(resolved.source, "custom");
  assert.equal(resolved.src, avatarObjectUrl(SUPABASE_URL, path));
  // What lets the Settings copy promise "remove it to go back to your Google
  // photo" before the removal has happened.
  assert.equal(resolved.googleAvailable, true);
});

test("no upload: Google's photo, from the identity rather than the metadata copy", () => {
  const resolved = resolveAvatar(googleUser(), SUPABASE_URL);
  assert.equal(resolved.source, "google");
  assert.equal(resolved.src, GOOGLE_PHOTO);
});

test("identities absent from the payload: the metadata copy still answers", () => {
  // Whether `identities` is populated is a property of the API RESPONSE, not of
  // the auth table. The fallback keeps a Google user's photo working either way.
  const resolved = resolveAvatar(
    { id: UID, user_metadata: { picture: GOOGLE_PHOTO } },
    SUPABASE_URL,
  );
  assert.equal(resolved.source, "google");
  assert.equal(resolved.src, GOOGLE_PHOTO);
});

test("email-only account: the monogram, which is a state and not a failure", () => {
  const resolved = resolveAvatar({ id: UID, user_metadata: {} }, SUPABASE_URL);
  assert.deepEqual(resolved, { source: "none", src: null, googleAvailable: false });
  assert.deepEqual(resolveAvatar(null, SUPABASE_URL).source, "none");
});

test("a photo URL off the Google host family is refused, however it arrived", () => {
  for (const hostile of [
    "https://evil.example/a/photo.png",
    "https://googleusercontent.com.evil.example/a.png",
    "http://lh3.googleusercontent.com/a/plain-http.png",
    "javascript:alert(1)",
    "/relative/path.png",
  ]) {
    assert.equal(
      googleAvatarUrl({ id: UID, user_metadata: { avatar_url: hostile } }),
      null,
      `${hostile} must not reach the image optimizer`,
    );
  }
  // The control: the real thing still passes, so the guard is not just "no".
  assert.equal(googleAvatarUrl(googleUser()), GOOGLE_PHOTO);
});

test("a stored path outside the caller's own folder is not a photo", () => {
  const other = "99999999-8888-4777-8666-555555555555";
  for (const hostile of [
    `${other}/f6a1b2c3-0000-4000-8000-abcdefabcdef.webp`,
    `${UID}/../${other}/x.webp`,
    `${UID}/x.svg`,
    `${UID}/x.webp/../../y.webp`,
    "x.webp",
  ]) {
    assert.equal(
      customAvatarPath({ id: UID, user_metadata: { [AVATAR_METADATA_KEY]: hostile } }),
      null,
      `${hostile} must not be rendered`,
    );
  }
  const own = newAvatarPath(UID, "image/webp", "f6a1b2c3-0000-4000-8000-abcdefabcdef");
  assert.equal(customAvatarPath({ id: UID, user_metadata: { [AVATAR_METADATA_KEY]: own } }), own);
});

test("stored bytes are identified by their signature, not by what was claimed", () => {
  const png = Uint8Array.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0]);
  const webp = Uint8Array.from([
    0x52, 0x49, 0x46, 0x46, 0x24, 0, 0, 0, 0x57, 0x45, 0x42, 0x50,
  ]);
  assert.equal(sniffAvatarType(png), "image/png");
  assert.equal(sniffAvatarType(webp), "image/webp");
  // A JPEG, an SVG and an HTML document: all things a `Content-Type: image/webp`
  // header would happily claim to be, and none of them storable.
  assert.equal(sniffAvatarType(Uint8Array.from([0xff, 0xd8, 0xff, 0xe0, 0, 0, 0, 0, 0, 0, 0, 0])), null);
  assert.equal(sniffAvatarType(new TextEncoder().encode("<svg xmlns=…>")), null);
  assert.equal(sniffAvatarType(new TextEncoder().encode("<!doctype html>")), null);
  assert.equal(sniffAvatarType(new Uint8Array()), null);
});

test("a missing bucket is recognised, so it can be told apart from a failure", () => {
  assert.equal(isBucketMissing({ message: "Bucket not found" }), true);
  assert.equal(isBucketMissing({ message: "new row violates row-level security policy" }), false);
  assert.equal(isBucketMissing(null), false);
});

/**
 * `next.config.ts`, executed — the same transpile-and-import trick
 * `api-no-store-headers.test.mjs` uses, and for the same reason: the file is
 * TypeScript and its only import is a type.
 */
async function loadConfig() {
  const absolute = resolvePath(WEB_ROOT, "next.config.ts");
  const { outputText } = ts.transpileModule(readFileSync(absolute, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
    fileName: absolute,
  });
  const url = `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`;
  return import(url);
}

/** Next's own hostname wildcard rules: `*` is one label, `**` is any number.
 *  Reimplemented rather than imported because Next does not export it; the
 *  synthetic cases in the test below are what keep the reimplementation honest. */
function hostMatches(pattern, hostname) {
  if (pattern.startsWith("**.")) return hostname.endsWith(pattern.slice(2));
  if (pattern.startsWith("*.")) {
    const suffix = pattern.slice(1);
    return hostname.endsWith(suffix) && !hostname.slice(0, -suffix.length).includes(".");
  }
  return pattern === hostname;
}

function covers(patterns, url) {
  const { protocol, hostname, pathname } = new URL(url);
  return patterns.some(
    (pattern) =>
      `${pattern.protocol}:` === protocol &&
      hostMatches(pattern.hostname, hostname) &&
      (!pattern.pathname || pathname.startsWith(pattern.pathname.replace(/\*+$/, ""))),
  );
}

test("the matcher can fail: a host outside the pattern is not covered", () => {
  const patterns = [{ protocol: "https", hostname: "*.googleusercontent.com" }];
  assert.equal(covers(patterns, "https://lh3.googleusercontent.com/a/x"), true);
  assert.equal(covers(patterns, "https://evil.example/a/x"), false);
  // `*` is ONE label: a nested host must not slip through.
  assert.equal(covers(patterns, "https://a.b.googleusercontent.com/x"), false);
  assert.equal(covers([], "https://lh3.googleusercontent.com/a/x"), false);
});

test("every URL this module permits, next/image's optimizer will actually fetch", async () => {
  const { default: config } = await loadConfig();
  const patterns = config.images?.remotePatterns ?? [];
  assert.ok(patterns.length > 0, "next.config.ts declares no images.remotePatterns");

  // The Google branch: what `googleAvatarUrl` returns is what the tile renders.
  assert.equal(
    covers(patterns, googleAvatarUrl(googleUser())),
    true,
    "the config refuses a Google avatar this module allows — the tile would silently fall back to the monogram",
  );

  // The upload branch: the public object URL, built the way the app builds it.
  const path = newAvatarPath(UID, "image/webp", "f6a1b2c3-0000-4000-8000-abcdefabcdef");
  assert.equal(
    covers(patterns, avatarObjectUrl(SUPABASE_URL, path)),
    true,
    `the config refuses ${SUPABASE_URL}'s avatars — uploaded photos would not render`,
  );

  // And the optimizer must not be usable as a general proxy.
  assert.equal(covers(patterns, "https://example.com/anything.png"), false);
  assert.equal(
    covers(patterns, `${SUPABASE_URL}/storage/v1/object/public/some-other-bucket/x.png`),
    false,
  );
});
