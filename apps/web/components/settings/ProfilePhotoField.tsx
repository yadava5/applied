"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { AvatarTile } from "@/components/ui/AvatarTile";
import { secondaryBtnClass, fieldLabelClass } from "@/components/ui/formStyles";
import { ACCEPTED_SOURCE_TYPES, type AvatarSource } from "@/lib/profile/avatar";
import { prepareAvatarFile } from "@/lib/profile/prepareAvatarFile";
import { settingsTransport, type SettingsMode } from "@/lib/settings/transport";
import { TransientStatus, useLinger } from "./SettingsSection";

/**
 * Settings → Profile → photo: the first place in Applied where a picture of a
 * person can be chosen, and the only place the choice can be undone.
 *
 * THE FOUR STATES IT HAS TO TELL APART, and what each of them says out loud —
 * because the interesting thing here is not the upload, it is that a photo has
 * a PROVENANCE and the user is entitled to know which one they are looking at:
 *
 *   - Google's photo (the default for a Google sign-in). The line says where it
 *     came from AND that the browser never fetched it, which is the one
 *     non-obvious thing about how this works and the reason the whole feature
 *     is shaped the way it is (`lib/profile/avatar.ts`).
 *   - An uploaded photo. It wins over Google's unconditionally, survives the
 *     next Google sign-in (it is stored under a key GoTrue's identity merge
 *     never touches), and the line names removal as the way back.
 *   - No photo at all. An invitation, not an apology — plus the fact worth
 *     knowing before you pick a file: the crop and the re-encode happen here,
 *     so a phone photo's GPS block never leaves the device.
 *   - Working / failed. A transient success clears itself (`useLinger`, #213);
 *     an error is a current fact and stays until the user acts on it.
 *
 * THE TILE IS THE RAIL'S TILE, at twice the size and with the same class
 * string: same square, same radius, same hairline, same `object-cover`. What
 * Settings shows IS what the sidebar will draw, including the crop — which is
 * what lets the centred square stand in for a drag-and-zoom cropper instead of
 * a 15 KB dependency spent on choosing pixels for a 32px square.
 *
 * IT PUBLISHES. Both writes end in `router.refresh()`: the photo is
 * server-rendered into the shell's rail, and every route can be sitting in the
 * 300 s router cache when one lands (#216, and the gate in
 * `tests/unit/settings-publish-contract.test.mjs`, which covers these two calls
 * by name). `local` is what the user sees in the meantime — the prepared image
 * is already in the browser, so the tile can be right before the server agrees,
 * and on `/demo/settings`, where the server never will, it is the whole
 * mechanism that makes the control real.
 */
export function ProfilePhotoField({
  source,
  src,
  googleSrc,
  initial,
  mode = "live",
}: {
  source: AvatarSource;
  /** What is on screen now: the uploaded object, or Google's, or nothing. */
  src: string | null;
  /** Google's photo, when there is one — what removal falls back to, and
   *  what the copy is allowed to promise before it happens. */
  googleSrc: string | null;
  /** The monogram under the photo. Follows the display-name field as it is
   *  typed, so the fallback is never a letter from the old name. */
  initial: string;
  mode?: SettingsMode;
}) {
  const transport = settingsTransport(mode);
  const router = useRouter();

  // What the browser knows that the server has not confirmed yet. `null` means
  // "the props are the truth", which is the state after every page load.
  const [local, setLocal] = useState<{ source: AvatarSource; src: string | null } | null>(null);
  const [busy, setBusy] = useState<"upload" | "remove" | null>(null);
  const [done, setDone] = useState<"Uploaded" | "Removed" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const settled = useLinger(done !== null);

  const shown = local ?? { source, src };
  const hasPhoto = shown.source !== "none";

  async function upload(file: File) {
    setError(null);
    setDone(null);
    setBusy("upload");
    const prepared = await prepareAvatarFile(file);
    if (!prepared.ok) {
      setBusy(null);
      setError(prepared.message);
      return;
    }
    const { ok, message } = await transport.uploadAvatar(prepared.blob);
    setBusy(null);
    if (!ok) {
      setError(message ?? "Couldn’t save the photo. Try again.");
      return;
    }
    setLocal({ source: "custom", src: prepared.dataUrl });
    setDone("Uploaded");
    router.refresh();
  }

  async function remove() {
    setError(null);
    setDone(null);
    setBusy("remove");
    const { ok, message } = await transport.removeAvatar();
    setBusy(null);
    if (!ok) {
      setError(message ?? "Couldn’t remove the photo. Try again.");
      return;
    }
    setLocal({ source: googleSrc ? "google" : "none", src: googleSrc });
    setDone("Removed");
    router.refresh();
  }

  return (
    <div className="flex items-start gap-4">
      <AvatarTile
        src={shown.src}
        initial={initial}
        size={64}
        // 1.75rem, not a `text-*` step: the rail draws a 14px letter in a 32px
        // tile, and holding that ratio at 64px is what makes this a preview of
        // the sidebar rather than a differently-proportioned second tile.
        className="h-16 w-16 text-[1.75rem]"
      />

      <div className="min-w-0 flex-1">
        <span className={fieldLabelClass}>photo</span>

        <div className="mt-2 flex flex-wrap items-center gap-2">
          {/* A label around a visually-hidden input, rather than a button that
              clicks a hidden one: the native control keeps its own keyboard and
              screen-reader behaviour, and the label supplies the name. The
              wrapper is `relative` deliberately — `sr-only` is
              `position: absolute`, and an unparented one extends the document's
              scroll area, which is a defect this codebase has already swept
              (#149/#152/#153). `focus-within` is what makes the ring appear
              when the input inside takes focus. */}
          <label
            className={`${secondaryBtnClass} relative cursor-pointer focus-within:ring-1 focus-within:ring-line-strong ${
              busy ? "pointer-events-none opacity-40" : ""
            }`}
          >
            {hasPhoto ? "Replace photo" : "Upload a photo"}
            <input
              type="file"
              accept={ACCEPTED_SOURCE_TYPES.join(",")}
              disabled={busy !== null}
              className="sr-only"
              onChange={(e) => {
                const file = e.target.files?.[0];
                // Cleared so choosing the SAME file again still fires a change
                // — otherwise a failed upload cannot be retried as-is.
                e.target.value = "";
                if (file) void upload(file);
              }}
            />
          </label>

          {shown.source === "custom" ? (
            <button
              type="button"
              onClick={() => void remove()}
              disabled={busy !== null}
              className="rounded-lg px-2 py-2 text-sm text-dim transition-colors hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong disabled:opacity-40"
            >
              Remove photo
            </button>
          ) : null}

          {busy ? (
            <span role="status" className="text-xs text-dim">
              {busy === "upload" ? "Uploading…" : "Removing…"}
            </span>
          ) : (
            <TransientStatus show={done !== null && settled} className="text-live">
              {done}
            </TransientStatus>
          )}
        </div>

        {error ? (
          <p role="alert" className="mt-2 max-w-md text-xs text-reject-ink">
            {error}
          </p>
        ) : (
          // The measure is capped rather than left to the card: this line is
          // 12px dim text, and a 700px column of it under a button reads as a
          // paragraph the eye has to work at instead of a caption it can take
          // in.
          <p className="mt-2 max-w-md text-xs text-dim">
            {shown.source === "custom"
              ? googleSrc
                ? "Your photo. Remove it to go back to the one from your Google account."
                : "Your photo. Remove it to go back to your initial."
              : shown.source === "google"
                ? "From your Google account. Applied fetches it server-side, so your browser never asks Google for it."
                : "Your initial stands in until you add one. Photos are cropped square and re-encoded in your browser, so camera location data never leaves your device."}
          </p>
        )}
      </div>
    </div>
  );
}
