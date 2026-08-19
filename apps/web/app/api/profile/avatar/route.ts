import { NextResponse, type NextRequest } from "next/server";

import { createClientWithSessionHeaders } from "@/lib/supabase/server";
import {
  AVATAR_BUCKET,
  AVATAR_METADATA_KEY,
  MAX_AVATAR_BYTES,
  customAvatarPath,
  isBucketMissing,
  newAvatarPath,
  sniffAvatarType,
} from "@/lib/profile/avatar";

/**
 * The uploaded profile photo: store one (POST), or go back to Google's / the
 * monogram (DELETE).
 *
 * WHY THE BYTES COME THROUGH THE SERVER AT ALL. The browser holds a Supabase
 * session and could upload straight to Storage — RLS would still scope the
 * write to the caller's own folder. It does not, because a bucket's
 * `allowed_mime_types` is checked against the `Content-Type` the CLIENT
 * declares, and a declared content type is a claim by the sender. Passing the
 * bytes through here means the file's own signature decides what it is
 * (`sniffAvatarType`), and a hand-made request cannot park arbitrary content in
 * a public bucket under an image's name.
 *
 * WHAT IT DOES NOT DO. It does not re-encode — that already happened, in the
 * browser, on a canvas (`lib/profile/prepareAvatarFile.ts`), which is also what
 * strips the EXIF/GPS block off a phone photo before it ever leaves the device.
 * Re-encoding a second time here would mean `sharp` on the request path to
 * re-derive an image we drew ourselves. The honest limit, stated rather than
 * implied: this verifies the container, not every byte inside it.
 *
 * WHY THE USER'S OWN CLIENT AND NOT THE SERVICE ROLE. The upload runs on the
 * caller's session, so the bucket's RLS policies apply exactly as written
 * (`docs/avatars-bucket-2026-08-19.sql`) — the folder is the user's id, and the
 * database enforces that rather than this handler remembering to. The
 * service-role key stays where it is, on account deletion alone.
 *
 * ORPHANS ARE THE FAILURE MODE TO WATCH. The artifact is a photograph of the
 * user's face; leaving one in a bucket after they replaced it, removed it, or
 * closed their account is the same defect family as #214. So: a metadata write
 * that fails takes the just-uploaded object back out, a successful replacement
 * deletes what it replaced, and `app/api/account/delete/route.ts` purges the
 * whole folder before the auth user is destroyed.
 *
 * `Cache-Control` comes from the `/api/:path*` entry in `next.config.ts`
 * (#315); `applySessionHeaders` adds what `@supabase/ssr` asks for when
 * `updateUser` rotates the session cookie (#242).
 */

/** Supabase Storage's answer when the bucket has never been created. The SQL
 *  in `docs/` is applied by hand against the live project, so this is a real
 *  state in production until it is — and the user is told so plainly rather
 *  than meeting a generic failure. */
const NOT_ENABLED = "Photo uploads aren’t enabled on this deployment yet.";
const SIGNED_OUT = "Your session expired. Sign in again and retry.";
const STORE_FAILED = "Couldn’t store the photo. Try again in a moment.";

export async function POST(request: NextRequest) {
  const { supabase, applySessionHeaders } = await createClientWithSessionHeaders();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return applySessionHeaders(NextResponse.json({ detail: SIGNED_OUT }, { status: 401 }));
  }

  const form = await request.formData().catch(() => null);
  const photo = form?.get("photo");
  if (!(photo instanceof Blob)) {
    return applySessionHeaders(
      NextResponse.json({ detail: "No image was uploaded." }, { status: 400 }),
    );
  }
  if (photo.size > MAX_AVATAR_BYTES) {
    return applySessionHeaders(
      NextResponse.json({ detail: "That image is too large to store." }, { status: 413 }),
    );
  }

  const bytes = new Uint8Array(await photo.arrayBuffer());
  const type = sniffAvatarType(bytes);
  if (!type) {
    // The browser re-encodes every upload, so this is either a hand-made
    // request or an encode that went wrong — neither is worth guessing about.
    return applySessionHeaders(
      NextResponse.json(
        { detail: "That file isn’t an image Applied can store." },
        { status: 415 },
      ),
    );
  }

  const previous = customAvatarPath(user);
  const path = newAvatarPath(user.id, type, crypto.randomUUID());

  const { error: uploadError } = await supabase.storage
    .from(AVATAR_BUCKET)
    .upload(path, bytes, {
      contentType: type,
      // The path is unique per upload, so nothing is ever overwritten and the
      // object may be cached for as long as anything wants to.
      upsert: false,
      cacheControl: "31536000",
    });

  if (uploadError) {
    const missing = isBucketMissing(uploadError);
    return applySessionHeaders(
      NextResponse.json(
        { detail: missing ? NOT_ENABLED : STORE_FAILED },
        { status: missing ? 501 : 502 },
      ),
    );
  }

  const { error: metaError } = await supabase.auth.updateUser({
    data: { [AVATAR_METADATA_KEY]: path },
  });
  if (metaError) {
    // Nothing points at the object, so it would sit in the bucket forever.
    await supabase.storage.from(AVATAR_BUCKET).remove([path]);
    return applySessionHeaders(NextResponse.json({ detail: STORE_FAILED }, { status: 502 }));
  }

  // Only now — the replacement is live and referenced, so losing this call
  // costs a stray object rather than the user's photo.
  if (previous && previous !== path) {
    await supabase.storage.from(AVATAR_BUCKET).remove([previous]);
  }

  return applySessionHeaders(NextResponse.json({ path }, { status: 200 }));
}

export async function DELETE() {
  const { supabase, applySessionHeaders } = await createClientWithSessionHeaders();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return applySessionHeaders(NextResponse.json({ detail: SIGNED_OUT }, { status: 401 }));
  }

  // Object first, metadata second. The other order can leave a photo in the
  // bucket that nothing references; this order can at worst leave metadata
  // pointing at a missing object, which the tile already renders as the
  // monogram and a retry clears. Removing an object that is not there is not
  // an error in Storage, so the retry is idempotent.
  const path = customAvatarPath(user);
  if (path) {
    const { error } = await supabase.storage.from(AVATAR_BUCKET).remove([path]);
    if (error && !isBucketMissing(error)) {
      return applySessionHeaders(
        NextResponse.json({ detail: "Couldn’t remove the photo. Try again." }, { status: 502 }),
      );
    }
  }

  const { error: metaError } = await supabase.auth.updateUser({
    data: { [AVATAR_METADATA_KEY]: null },
  });
  if (metaError) {
    return applySessionHeaders(
      NextResponse.json({ detail: "Couldn’t update your profile. Try again." }, { status: 502 }),
    );
  }

  return applySessionHeaders(NextResponse.json({ removed: true }, { status: 200 }));
}
