"use client";

import Image from "next/image";
import { useState } from "react";

/**
 * The identity tile: a photo when there is one, the initial when there is not.
 *
 * WHY THE MONOGRAM IS ALWAYS RENDERED, UNDER THE PHOTO rather than instead of
 * it. The tile is a fixed square in the rail's footer, and that footer's height
 * is load-bearing — `components/shell/RailFooter` documents the 157px it has to
 * live inside at the owner's real 1309×693. A tile that is empty until an image
 * decodes is a hole in the identity row on every cold load, and a tile that
 * swaps monogram → photo is a flicker. Painting the letter as the tile's
 * content and layering the image over it means the letter is what shows during
 * SSR, before the decode, if the object 404s, and with JavaScript off — three
 * fallbacks and a no-JS case for free, none of them a separate code path.
 *
 * WHY `next/image` AND NOT `<img>`. This is the whole privacy mechanism, and it
 * is easy to "simplify" away: the optimizer fetches the remote bytes
 * SERVER-SIDE and the browser only ever requests `/_next/image?…` from
 * Applied's own origin. Point an `<img>` at `lh3.googleusercontent.com`
 * directly and every dashboard load becomes a beacon to Google carrying the
 * reader's IP. `lib/profile/avatar.ts` is the long version, and
 * `next.config.ts` holds the hosts the optimizer will accept.
 *
 * The one exception is a `data:` preview — the freshly cropped image, held in
 * the browser, before or instead of an upload. There is nothing to optimize and
 * nothing to leak, and the optimizer cannot take a data URL as input at all.
 *
 * DECORATIVE, ALWAYS. The root is `aria-hidden`: both call sites put this
 * beside the identity's visible name, and `alt={name}` would drop a second copy
 * of the name into a link that already carries it — the exact adjacent-name
 * problem `RailFooter`'s accessible-name note exists to avoid. The photo's
 * PRESENCE is stated in words on the Settings card, where it is a fact the user
 * can act on.
 */
export function AvatarTile({
  src,
  initial,
  size,
  className = "",
}: {
  /** Absolute URL, or a `data:` preview, or `null` for the monogram alone. */
  src: string | null;
  /** Already upper-cased by the caller, which owns what the row prints. */
  initial: string;
  /** Rendered edge in CSS pixels — must match the `className`'s box, since it
   *  is what the optimizer sizes the fetch to. */
  size: number;
  /** The box: the caller owns geometry so each surface keeps its own. */
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  // Render-time reset on the `src` edge (the same "adjust state when a prop
  // changes" pattern as `useLinger`): a new photo must not inherit the last
  // one's failure, or replacing a broken object would look broken too.
  const [prevSrc, setPrevSrc] = useState(src);
  if (src !== prevSrc) {
    setPrevSrc(src);
    setFailed(false);
  }

  const local = src?.startsWith("data:") === true;

  return (
    <span
      aria-hidden="true"
      className={`relative grid shrink-0 place-items-center overflow-hidden rounded-md border border-line bg-surface-2 font-semibold text-strong ${className}`.trim()}
    >
      {initial}
      {src && !failed ? (
        local ? (
          // A data: URL is already in the browser; `next/image` would hand it to
          // the optimizer, which cannot fetch one. Nothing the rule protects
          // against applies: no bytes cross the network, and the box is the
          // parent's and is fixed, so there is no layout shift either.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={src}
            alt=""
            className="absolute inset-0 h-full w-full object-cover"
            onError={() => setFailed(true)}
          />
        ) : (
          <Image
            src={src}
            alt=""
            width={size}
            height={size}
            onError={() => setFailed(true)}
            className="absolute inset-0 h-full w-full object-cover"
          />
        )
      ) : null}
    </span>
  );
}
