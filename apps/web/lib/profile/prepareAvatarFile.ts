/**
 * Turn a file the user picked into the square image Applied stores.
 *
 * Browser-only (it needs a canvas), and deliberately the ONLY thing standing
 * between a camera roll and the bucket:
 *
 *   - **It re-encodes.** The bytes uploaded are drawn pixels, not the file the
 *     user chose, so the EXIF block — which on a phone photo carries the GPS
 *     coordinates of wherever it was taken — never leaves the device. That is
 *     worth saying in the UI, and the Settings copy does.
 *   - **It crops square, centred, at {@link AVATAR_EDGE}.** A photo is shown in
 *     a 32px tile in the rail and a 64px tile in Settings; storing anything
 *     bigger is storing bytes nothing will ever draw.
 *   - **It bounds the work.** The size check happens before the decode, because
 *     a 50 MP photo becomes ~200 MB of bitmap and a frozen tab is a worse
 *     answer than a sentence.
 *
 * NO CROPPER LIBRARY, and that is a decision rather than an omission. A
 * drag-and-zoom cropper is ~15 KB of dependency and a second interaction model
 * to teach, spent on choosing which pixels land in a 32px square. A centred
 * square from a photo of a face is that square. The Settings card shows the
 * result at the exact size the rail draws it, before anything is uploaded, so
 * the crop is never a surprise — and "pick a different photo" is one click.
 *
 * The `<img>` + `data:` URL route is taken over `createImageBitmap` on purpose:
 * `URL.createObjectURL` would need `blob:` added to the app's `img-src`, and
 * this whole feature is built so the Content-Security-Policy does not have to
 * move (see `lib/profile/avatar.ts`). Browsers have applied EXIF orientation to
 * `<img>` by default since 2020, so the decoded frame is already upright.
 */
import {
  ACCEPTED_SOURCE_TYPES,
  AVATAR_EDGE,
  MAX_SOURCE_BYTES,
  STORED_AVATAR_TYPES,
  type StoredAvatarType,
} from "./avatar";

export type PreparedAvatar =
  | { ok: true; blob: Blob; type: StoredAvatarType; dataUrl: string }
  | { ok: false; message: string };

/** Human-readable, and only ever used inside a refusal sentence. */
function megabytes(bytes: number): string {
  return `${Math.round((bytes / (1024 * 1024)) * 10) / 10} MB`;
}

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error("read failed"));
    reader.readAsDataURL(file);
  });
}

function decode(dataUrl: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("decode failed"));
    image.src = dataUrl;
  });
}

/**
 * Ask the canvas for `type`, and report what it actually produced.
 *
 * `toBlob` is specified to fall back to PNG when it cannot encode the requested
 * format, silently — so the answer has to be inspected rather than assumed.
 * That fallback is the reason `STORED_AVATAR_TYPES` has two entries: a browser
 * without WebP encoding (Safari before 16.4) still gets to set a photo.
 */
function encode(canvas: HTMLCanvasElement, type: string): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, type, 0.9));
}

export async function prepareAvatarFile(file: File): Promise<PreparedAvatar> {
  if (!(ACCEPTED_SOURCE_TYPES as readonly string[]).includes(file.type)) {
    return { ok: false, message: "Choose a PNG, JPEG or WebP image." };
  }
  if (file.size > MAX_SOURCE_BYTES) {
    return {
      ok: false,
      message: `That image is ${megabytes(file.size)}. Choose one under ${megabytes(MAX_SOURCE_BYTES)}.`,
    };
  }

  let image: HTMLImageElement;
  try {
    image = await decode(await readAsDataUrl(file));
  } catch {
    return { ok: false, message: "That file couldn’t be read as an image. Try another one." };
  }

  const edge = Math.min(image.naturalWidth, image.naturalHeight);
  if (edge === 0) {
    return { ok: false, message: "That file couldn’t be read as an image. Try another one." };
  }

  const canvas = document.createElement("canvas");
  canvas.width = AVATAR_EDGE;
  canvas.height = AVATAR_EDGE;
  const context = canvas.getContext("2d");
  if (!context) {
    return { ok: false, message: "This browser couldn’t prepare the image. Try another one." };
  }
  context.imageSmoothingQuality = "high";
  context.drawImage(
    image,
    // The centred square of the source, scaled to fill the whole tile.
    (image.naturalWidth - edge) / 2,
    (image.naturalHeight - edge) / 2,
    edge,
    edge,
    0,
    0,
    AVATAR_EDGE,
    AVATAR_EDGE,
  );

  const blob = (await encode(canvas, "image/webp")) ?? (await encode(canvas, "image/png"));
  if (!blob || !(STORED_AVATAR_TYPES as readonly string[]).includes(blob.type)) {
    // Said here rather than let the server refuse it: a rejection that arrives
    // after an upload reads as "Applied is broken", and this one is the
    // browser's limitation, which the user can act on.
    return { ok: false, message: "This browser couldn’t prepare the image. Try another one." };
  }

  return {
    ok: true,
    blob,
    type: blob.type as StoredAvatarType,
    // The preview is the encoded result, not the source — what you see before
    // you upload is the image that gets uploaded.
    dataUrl: canvas.toDataURL(blob.type),
  };
}
