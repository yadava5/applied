/**
 * Profile photos: where one comes from, and whether Applied may render it.
 *
 * WHAT WAS THERE BEFORE. Nothing — the rail's identity row drew the first
 * letter of the display name in a 32px tile and there was no photo affordance
 * anywhere in the product. Meanwhile Google has been handing us a photo on
 * every OAuth sign-in (`identity_data.avatar_url` / `.picture` on the `google`
 * identity, both populated on the live account) and the app read neither key.
 *
 * THE DECISION THIS MODULE ENCODES, AND WHY IT IS NOT THE OBVIOUS ONE.
 * Rendering `<img src="https://lh3.googleusercontent.com/…">` in the shell
 * means the READER'S BROWSER asks Google for a picture every time they open
 * their signed-in dashboard. That is a per-pageview beacon carrying their IP,
 * their user-agent and the timing of their job search, to a third party, on a
 * product whose entire pitch is that no model reads your mail and no message
 * body is stored. A privacy claim undone by an `<img>` tag is exactly the kind
 * of thing a careful reader finds.
 *
 * So no avatar URL is ever handed to a browser. Both sources are rendered
 * through `next/image`, whose optimizer runs SERVER-SIDE: the browser requests
 * `/_next/image?url=…` from Applied's own origin and Applied's server fetches
 * the bytes, once per `images.minimumCacheTTL` (`next.config.ts`). Google sees
 * one request from the deployment's infrastructure every thirty days; it never
 * sees the reader's address and never learns that they opened the app.
 *
 * Two consequences worth stating out loud, because both look like omissions:
 *
 *   - `img-src 'self' data:` in `lib/security/csp.ts` is UNCHANGED. There is
 *     no remote image origin to allow, because the browser never contacts one.
 *     The upload preview uses a `data:` URL for the same reason (a `blob:`
 *     would have needed the policy widened for a thumbnail).
 *   - Nothing is copied into storage at sign-in. Copying the Google photo into
 *     a bucket buys the same privacy property this already has, and costs a
 *     fetch on the auth path, a staleness window, and a bucket the Google
 *     branch would then depend on. This way a Google user's photo works even
 *     if the bucket in `docs/avatars-bucket-2026-08-19.sql` is never applied.
 *
 * Pure and dependency-free — no React, no `@/` alias, no `next/*` — in the same
 * spirit as `components/settings/accountSecurity.ts` and `lib/account/
 * deletion.ts`, so `tests/unit/profile-avatar.test.mjs` can execute every rule
 * below under Node's type stripping with no browser and no session.
 */

/** The Supabase Storage bucket holding uploaded photos. Created by hand — see
 *  `docs/avatars-bucket-2026-08-19.sql`; it does not exist until that is run. */
export const AVATAR_BUCKET = "avatars";

/**
 * The user-metadata key holding an uploaded photo's object path.
 *
 * DELIBERATELY NOT `avatar_url`. GoTrue merges the OAuth provider's identity
 * data into `raw_user_meta_data` on every sign-in, and the keys it writes are
 * the provider's own — `full_name`, `name`, `email`, `avatar_url`, `picture`,
 * `provider_id`, `sub`. A photo stored under one of those names would be
 * silently overwritten by Google's the next time the user signed in with
 * Google, which is precisely the "their choice must survive" requirement.
 *
 * That the merge leaves OTHER keys alone is not a hope: `display_name` is
 * written into this same blob by Settings → Profile today and persists on the
 * account that also holds a Google identity. Same mechanism, same blob, and it
 * is already in production.
 */
export const AVATAR_METADATA_KEY = "custom_avatar_path";

/**
 * Stored edge, in CSS pixels. The photo is drawn at 32px in the rail and 64px
 * in Settings, so 256 covers both at 2× with room for a future larger use, and
 * a 256px square re-encode is a few tens of kilobytes rather than the several
 * megabytes a phone camera hands over.
 */
export const AVATAR_EDGE = 256;

/**
 * Server-side ceiling on what may be stored, and the bucket's `file_size_limit`
 * in the SQL. Generous against a 256×256 re-encode (a photographic WebP lands
 * near 20 KB, the PNG fallback near 140 KB) and small enough that the whole
 * body is read into memory to be sniffed without a second thought.
 */
export const MAX_AVATAR_BYTES = 512 * 1024;

/**
 * Ceiling on the file a user may CHOOSE, checked in the browser before the
 * image is decoded. A 50 MP photo decodes to ~200 MB of bitmap; refusing early
 * with a sentence beats a tab that freezes and then fails.
 */
export const MAX_SOURCE_BYTES = 12 * 1024 * 1024;

/**
 * What the file picker offers, and what `prepareAvatarFile` will decode. The
 * stored object is always re-encoded from a canvas, so this list constrains
 * the DECODER, not the storage format.
 */
export const ACCEPTED_SOURCE_TYPES = ["image/png", "image/jpeg", "image/webp"] as const;

/**
 * The two formats a re-encoded avatar can arrive in. WebP is what the canvas is
 * asked for; PNG is the fallback the HTML spec prescribes when a browser cannot
 * encode the requested type (older Safari), and it is accepted rather than
 * refused so a Safari user is not simply told no.
 */
export const STORED_AVATAR_TYPES = ["image/webp", "image/png"] as const;
export type StoredAvatarType = (typeof STORED_AVATAR_TYPES)[number];

/**
 * The host family Google serves profile photos from. `lh1` … `lh7` all resolve
 * to the same `googlehosted.l.googleusercontent.com` and serve byte-identical
 * responses, so the numeric prefix is an interchangeable load-balancer label
 * rather than a distinct service — pinning `lh3` alone would be a silent
 * monogram the day Google hands out `lh4`.
 *
 * This is defence in depth, not the primary control. Since the candidate is
 * read from `identity_data` only, the string already comes from Google's
 * verified ID token; this predicate is what keeps that true if the source is
 * ever widened again.
 *
 * `next.config.ts` must allow the same family in `images.remotePatterns` or the
 * optimizer refuses what this permits and the tile silently falls back to the
 * monogram. The two are restated rather than shared — the config is loaded
 * standalone by `tests/unit/api-no-store-headers.test.mjs`, where a relative
 * import could not resolve — and `tests/unit/profile-avatar.test.mjs` asserts
 * they agree.
 */
export const GOOGLE_AVATAR_HOST_SUFFIX = ".googleusercontent.com";

/** Where a rendered photo came from. `none` is the monogram, which is a real
 *  state and not a failure — most accounts here have never had a photo. */
export type AvatarSource = "custom" | "google" | "none";

/** The slice of a Supabase `User` these rules read. The real `User` satisfies
 *  it structurally, so nothing has to import `@supabase/supabase-js`. */
export interface AvatarBearer {
  id?: string;
  identities?: { provider: string; identity_data?: Record<string, unknown> | null }[] | null;
  user_metadata?: Record<string, unknown> | null;
}

export interface ResolvedAvatar {
  source: AvatarSource;
  /** Absolute URL, already host-checked, safe to hand to `next/image`. */
  src: string | null;
  /** Is there a Google photo to fall back to if the upload is removed? This is
   *  what lets the Settings copy promise the right thing before it happens. */
  googleAvailable: boolean;
}

/**
 * `identity_data` on the `google` identity, and NOTHING ELSE.
 *
 * This value is handed to `next/image`, whose optimizer makes the fetch
 * server-side, so where it comes from is a security question rather than a
 * convenience one. `identity_data` is written by GoTrue from the verified ID
 * token and is unreachable from any client-facing parameter: `updateUser`
 * routes `data` to `UpdateUserMetaData`, which writes only
 * `raw_user_meta_data`, and neither the user nor the admin API exposes a field
 * that reaches `identity_data`.
 *
 * THERE IS DELIBERATELY NO `user_metadata` FALLBACK. An earlier revision had
 * one, reasoning that whether `identities` is populated is a property of the
 * API response rather than the table. It is not: `GET /auth/v1/user` resolves
 * the user through `findUser`, which eager-loads the `has_many:"identities"`
 * association, and the struct field carries no `omitempty`, so the key is
 * always present. `getUser()` in auth-js always makes that request -- there is
 * no local-JWT-decode path -- so a server component and the browser see the
 * same object.
 *
 * The fallback was therefore never load-bearing, and it was the whole attack
 * surface: `user_metadata` IS user-writable, directly through the anon key,
 * with or without this app's Settings screen. GoTrue does overwrite
 * `avatar_url` from the provider on each interactive OAuth sign-in, but that
 * merges rather than clears, does not fire on refresh-token rotation, and is
 * skipped entirely when Google omits the `picture` claim -- so an injected
 * value could outlive the session that set it.
 *
 * Select by provider, never `identities[0]`: the array is in link order, and
 * an account can carry more than one identity.
 */
function googleAvatarCandidate(user: AvatarBearer | null): unknown {
  for (const identity of user?.identities ?? []) {
    if (identity.provider !== "google") continue;
    const data = identity.identity_data ?? {};
    if (data.picture != null) return data.picture;
    if (data.avatar_url != null) return data.avatar_url;
  }
  return null;
}

/**
 * The Google photo for this account, or `null`. HTTPS and the Google host
 * family are both required: this string ends up as the `url` parameter of the
 * image optimizer, and the optimizer is a fetch made by Applied's server.
 */
export function googleAvatarUrl(user: AvatarBearer | null): string | null {
  const candidate = googleAvatarCandidate(user);
  if (typeof candidate !== "string" || candidate.length === 0) return null;
  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    return null;
  }
  if (parsed.protocol !== "https:") return null;
  return parsed.hostname.endsWith(GOOGLE_AVATAR_HOST_SUFFIX) ? candidate : null;
}

/**
 * The uploaded photo's object path (`<user id>/<random>.webp`), or `null`.
 *
 * The shape is enforced, not trusted. This value lives in user-writable
 * metadata, and the first path segment is what the bucket's RLS policies key
 * ownership off — so a path naming somebody else's folder, or one carrying
 * `..`, is treated as no photo at all rather than rendered.
 */
export function customAvatarPath(user: AvatarBearer | null): string | null {
  const value = (user?.user_metadata ?? {})[AVATAR_METADATA_KEY];
  if (typeof value !== "string") return null;
  const match = /^([0-9a-fA-F-]{36})\/([A-Za-z0-9_-]+)\.(webp|png)$/.exec(value);
  if (!match) return null;
  // When the caller knows who the user is, the folder must be theirs.
  if (user?.id && match[1] !== user.id) return null;
  return value;
}

/** The public URL of a stored object. Public-read by design (the bucket SQL
 *  says why); the path segment is a UUID, so it is unguessable. */
export function avatarObjectUrl(supabaseUrl: string, path: string): string {
  return `${supabaseUrl.replace(/\/+$/, "")}/storage/v1/object/public/${AVATAR_BUCKET}/${path}`;
}

/**
 * The photo to draw, by precedence: the user's own upload, then Google's, then
 * the monogram.
 *
 * The upload wins unconditionally — that IS the setting. There is no separate
 * "prefer my upload" flag to keep in sync, because the presence of the object
 * is the preference: removing it is how you go back to Google's, and Google's
 * own key can never collide with it (see `AVATAR_METADATA_KEY`).
 */
export function resolveAvatar(
  user: AvatarBearer | null,
  supabaseUrl: string,
): ResolvedAvatar {
  const google = googleAvatarUrl(user);
  const custom = customAvatarPath(user);
  if (custom) {
    return { source: "custom", src: avatarObjectUrl(supabaseUrl, custom), googleAvailable: !!google };
  }
  if (google) return { source: "google", src: google, googleAvailable: true };
  return { source: "none", src: null, googleAvailable: false };
}

/**
 * What these bytes actually are, read from the file's own signature.
 *
 * The browser re-encodes every upload through a canvas, so a request arriving
 * with anything else was hand-made — and `Content-Type` on a multipart part is
 * a claim by the sender, which is the one thing a storage bucket must not take
 * on trust. Two signatures, because two formats can be stored: PNG's eight-byte
 * magic, and WebP's `RIFF….WEBP` container.
 */
export function sniffAvatarType(bytes: Uint8Array): StoredAvatarType | null {
  const startsWith = (offset: number, signature: number[]) =>
    signature.every((byte, index) => bytes[offset + index] === byte);

  if (bytes.length >= 8 && startsWith(0, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) {
    return "image/png";
  }
  // "RIFF" … "WEBP" — the four size bytes between them are content.
  if (
    bytes.length >= 12 &&
    startsWith(0, [0x52, 0x49, 0x46, 0x46]) &&
    startsWith(8, [0x57, 0x45, 0x42, 0x50])
  ) {
    return "image/webp";
  }
  return null;
}

/**
 * Is this Storage error "the bucket does not exist"?
 *
 * A real production state, not a hypothetical: the bucket is created by hand
 * against the live project (`docs/avatars-bucket-2026-08-19.sql`) because a
 * public bucket and its RLS policies are new security surface in a product
 * mid-way through a Google restricted-scope review, and that is a change to
 * make deliberately. Until it is applied, uploads must say so plainly — and
 * account deletion must treat "no bucket" as "no photos to remove" rather than
 * refusing to close the account over a bucket that was never there.
 */
export function isBucketMissing(error: { message?: string } | null): boolean {
  return /bucket not found/i.test(error?.message ?? "");
}

/** The object path for a freshly accepted upload. The random segment is what
 *  makes a 30-day image cache safe: a replacement is a different URL, so
 *  nothing has to be invalidated and no stale face can survive a change. */
export function newAvatarPath(userId: string, type: StoredAvatarType, random: string): string {
  return `${userId}/${random}.${type === "image/png" ? "png" : "webp"}`;
}
