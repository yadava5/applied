/**
 * `app/api/profile/avatar/route.ts`, executed — the guards that decide what
 * may be parked in a public bucket, and the one refusal that has to stay
 * honest.
 *
 * WHY THIS FILE EXISTS. `tests/unit/profile-avatar.test.mjs` covers the rules
 * in `lib/profile/avatar.ts` thoroughly, and every one of them in isolation:
 * `sniffAvatarType` on bytes, `isBucketMissing` on an error object. None of it
 * touches the handler that CALLS them, and the handler is where the order and
 * the mapping live. An audit proved the gap by mutation — deleting the
 * server-side size guard, and making the route answer 502 unconditionally so
 * the `501 NOT_ENABLED` branch was gone — and the whole unit suite stayed
 * green through both. So these tests drive the real POST and DELETE
 * (`helpers/avatarRoute.mjs`), and each one below names the mutation that
 * turns it red.
 *
 * WHAT THE THREE GUARDS ARE FOR, in the route's own terms: the bytes come
 * through the server precisely so that the FILE decides what it is rather than
 * the `Content-Type` its sender declared, the ceiling is what makes reading the
 * whole body into memory to sniff it safe, and the 501 is the difference
 * between "this deployment has not had the bucket created yet" and "something
 * broke" — a distinction the user is told out loud, and the only thing making
 * "the feature degrades honestly without the bucket" a true sentence.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  AVATAR_BUCKET,
  AVATAR_METADATA_KEY,
  MAX_AVATAR_BYTES,
} from "../../lib/profile/avatar.ts";
import {
  BUCKET_MISSING,
  SIGNED_IN,
  STORAGE_REFUSED,
  UID,
  deleteAvatar,
  pngBytes,
  postAvatar,
  webpBytes,
} from "./helpers/avatarRoute.mjs";

/**
 * The ceiling, spelled out rather than imported into the fixtures below.
 * A body sized `MAX_AVATAR_BYTES + 1` would follow the constant wherever it
 * went, so raising the cap would move the fixture with it and the test would
 * stay green — the same reason `profile-avatar.test.mjs` writes the Supabase
 * origin out in full instead of reading it from the config it is checking.
 */
const CEILING = 512 * 1024;

/** A photo already on the account, in the shape `customAvatarPath` accepts. */
const STORED_PATH = `${UID}/f6a1b2c3-0000-4000-8000-abcdefabcdef.webp`;

test("the stored ceiling is 512 KB, and nothing may raise it quietly", () => {
  // The bucket's `file_size_limit` in `docs/avatars-bucket-2026-08-19.sql` is
  // this number. Raising one without the other means either an upload the
  // route accepts and Storage rejects, or a body larger than the route ever
  // meant to read into memory to sniff.
  //
  // Red when: MAX_AVATAR_BYTES is changed.
  assert.equal(MAX_AVATAR_BYTES, CEILING);
});

test("an image over the ceiling is refused, and no byte of it reaches storage", async () => {
  // A VALID PNG, deliberately: with garbage bytes the sniff would refuse it a
  // few lines later and a deleted size guard would still look like a refusal.
  // Valid bytes mean the only thing standing between this body and the bucket
  // is the guard itself.
  //
  // Red when: the `photo.size > MAX_AVATAR_BYTES` check is deleted (the body
  // is stored and the route answers 200), or the ceiling is raised past this
  // fixture, or the check is moved below the upload.
  const { status, body, calls } = await postAvatar({ photo: pngBytes(CEILING + 1) });

  assert.equal(status, 413);
  assert.match(body.detail, /too large/i);
  assert.deepEqual(calls.upload, [], "an oversize body must not be uploaded first and judged after");
  assert.deepEqual(calls.updateUser, []);
});

test("an image exactly at the ceiling is stored — the guard is a ceiling, not a fence", async () => {
  // The positive control. Without it every assertion above is satisfied by a
  // route that refuses everything, and `>=` would read as correct.
  //
  // Red when: the comparison becomes `>=`, or the ceiling is lowered.
  const { status, body, calls } = await postAvatar({ photo: pngBytes(CEILING) });

  assert.equal(status, 200);
  assert.equal(calls.upload.length, 1);
  assert.equal(calls.upload[0].bytes.length, CEILING);
  assert.equal(body.path, calls.upload[0].path);
});

test("a bucket that was never created answers 501, not a generic failure", async () => {
  // THE case. The bucket is applied by hand against the live project, so "no
  // bucket" is a real production state and the user is entitled to be told
  // that photo uploads are not enabled here rather than that something broke.
  //
  // Red when: the `isBucketMissing` branch is dropped, folded into the 502, or
  // the status is changed — which is the mutation the audit applied, and which
  // nothing caught.
  const { status, body, calls } = await postAvatar({ uploadError: BUCKET_MISSING });

  assert.equal(status, 501);
  assert.match(body.detail, /enabled/i);
  assert.deepEqual(calls.updateUser, [], "nothing was stored, so nothing may be pointed at");
});

test("any other storage refusal is a 502, and says so differently", async () => {
  // The inverse, driven off the same stub: a route hard-wired to 501 would
  // pass the test above while telling every user of a healthy deployment that
  // the feature is switched off.
  //
  // Red when: the missing-bucket branch is widened to catch every error.
  const refused = await postAvatar({ uploadError: STORAGE_REFUSED });
  const missing = await postAvatar({ uploadError: BUCKET_MISSING });

  assert.equal(refused.status, 502);
  assert.notEqual(refused.body.detail, missing.body.detail);
  assert.deepEqual(refused.calls.updateUser, []);
});

test("what the bytes ARE decides, not what the request claimed they were", async () => {
  // `Content-Type` on a multipart part is a claim by the sender, and the
  // bucket is public-read. An SVG stored under an image's name is a script
  // served from the project's own origin.
  //
  // Red when: the `sniffAvatarType` result is not checked, or the upload is
  // moved above it — either way one of these bodies lands in the bucket.
  for (const [what, bytes] of [
    ["a JPEG", Uint8Array.from([0xff, 0xd8, 0xff, 0xe0, 0, 0, 0, 0, 0, 0, 0, 0])],
    ["an SVG", new TextEncoder().encode("<svg xmlns=…><script/></svg>")],
    ["an HTML document", new TextEncoder().encode("<!doctype html><script>…</script>")],
  ]) {
    const { status, calls } = await postAvatar({ photo: bytes, declaredType: "image/png" });

    assert.equal(status, 415, `${what} declared as a PNG was not refused`);
    assert.deepEqual(calls.upload, [], `${what} reached the bucket`);
    assert.deepEqual(calls.updateUser, []);
  }
});

test("the stored object carries the sniffed type, not the declared one", async () => {
  // The other half of the same guard, and the reason the bytes come through
  // the server at all: a WebP announced as a PNG is stored as what it is, so
  // the object's extension, its `contentType` and its content agree.
  //
  // Red when: `photo.type` (or the form's declared type) is passed to Storage
  // in place of the sniffed one.
  const { status, body, calls } = await postAvatar({
    photo: webpBytes(),
    declaredType: "image/png",
    filename: "claims-to-be.png",
  });

  assert.equal(status, 200);
  assert.equal(calls.upload.length, 1);
  const stored = calls.upload[0];
  assert.equal(stored.bucket, AVATAR_BUCKET);
  assert.equal(stored.options.contentType, "image/webp");
  assert.match(stored.path, new RegExp(`^${UID}/[0-9a-f-]{36}\\.webp$`));
  // And the metadata points at exactly what was stored — an upload nothing
  // references is an orphaned photograph of the user's face.
  assert.deepEqual(calls.updateUser, [{ data: { [AVATAR_METADATA_KEY]: stored.path } }]);
  assert.equal(body.path, stored.path);
});

test("removal survives a deployment with no bucket at all", async () => {
  // The mirror of the 501: on the way OUT, "the bucket does not exist" means
  // there is nothing to remove, so it must not stop the metadata being
  // cleared. A user whose deployment lost its bucket can still take their
  // photo off their account.
  //
  // Red when: `isBucketMissing` is dropped from the DELETE branch, so a
  // missing bucket answers 502 and the photo can never be removed.
  const missing = await deleteAvatar({
    user: { id: UID, user_metadata: { [AVATAR_METADATA_KEY]: STORED_PATH } },
    removeError: BUCKET_MISSING,
  });
  // The removal has to have been ATTEMPTED, or the 200 below says nothing
  // about the missing bucket: a path `customAvatarPath` refused would skip the
  // whole Storage block and still clear the metadata.
  assert.equal(missing.calls.remove.length, 1, "the stored object was never asked for");
  assert.deepEqual(missing.calls.remove[0].paths, [STORED_PATH]);
  assert.equal(missing.status, 200);
  assert.equal(missing.body.removed, true);
  assert.deepEqual(missing.calls.updateUser, [{ data: { [AVATAR_METADATA_KEY]: null } }]);

  // The control: a real Storage failure still refuses, and leaves the metadata
  // pointing at an object that is still there.
  const refused = await deleteAvatar({
    user: { id: UID, user_metadata: { [AVATAR_METADATA_KEY]: STORED_PATH } },
    removeError: STORAGE_REFUSED,
  });
  assert.equal(refused.calls.remove.length, 1);
  assert.equal(refused.status, 502);
  assert.deepEqual(refused.calls.updateUser, []);
});

test("no session, and no file, are refused before anything is read", async () => {
  // Controls for every test above: they all run as `SIGNED_IN` with a file, so
  // without these the handler could be answering 200 for reasons that have
  // nothing to do with the caller.
  //
  // Red when: the `getUser()` gate or the `instanceof Blob` check is removed.
  const anonymous = await postAvatar({ user: null });
  assert.equal(anonymous.status, 401);
  assert.deepEqual(anonymous.calls.upload, []);

  const empty = await postAvatar({ photo: null });
  assert.equal(empty.status, 400);
  assert.deepEqual(empty.calls.upload, []);

  // And the account these tests actually run as is the one the paths are
  // built under.
  assert.equal(SIGNED_IN.id, UID);
});
