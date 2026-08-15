/**
 * The two measurements every clip is judged on, and the thresholds they are
 * judged against.
 *
 * This module exists so that `verify.mjs` and `verify-negative.mjs` run the
 * SAME code. The negative control first shipped with its own copy of the
 * arithmetic, which proves nothing: a control that exercises a duplicate of the
 * gate can pass while the gate itself is broken. It has to be the same function
 * or it is theatre.
 *
 * Both measurements count PIXELS THAT MOVED, not the average difference. The
 * mean was tried first and failed twice, in both directions:
 *
 *   · it called `board-syncs` a still image (mean 1.72) when what changes is a
 *     handful of digits on an 832x224 ground — a real, obvious change;
 *   · and worse, it passed a clip whose loop dissolve had been deliberately cut
 *     off (mean 1.77, under a tolerance of 3), which is the exact defect the
 *     seam gate exists to catch. The negative control is what surfaced that.
 *
 * The share of the frame that changes is the statistic that separates those two
 * cases, because it does not average a small real change into a large
 * unchanging background.
 */

/** Per-channel difference at which a pixel counts as having moved. Above
 *  encode noise on flat UI, below any change a reader would notice. */
export const MOVED_DELTA = 24;

/** A clip must change at least this share of its frame between its opening and
 *  its closing beat, or it is a still image with a duration. */
export const MOVED_MIN_PCT = 0.15;

/** A clip's last frame must match its first to within this share of the frame,
 *  or the loop has a visible cut. Measured: a clean dissolve lands at 0.00-0.02%
 *  and the same clip with the dissolve removed lands at 1.7%. */
export const SEAM_MAX_PCT = 0.1;

/**
 * The share of two same-sized images' pixels that differ by more than
 * `MOVED_DELTA` on any channel, as a percentage. Runs in a browser page, on
 * STILL images — never on a seeking `<video>`, which returns stale frames.
 *
 * @param page a Playwright page
 * @param a base64 PNG
 * @param b base64 PNG
 */
export function changedPct(page, a, b) {
  return page.evaluate(
    async ([a, b, delta]) => {
      const load = (src) =>
        new Promise((resolve, reject) => {
          const img = new Image();
          img.onload = () => resolve(img);
          img.onerror = () => reject(new Error("could not decode a sampled frame"));
          img.src = src;
        });
      const [ia, ib] = await Promise.all([load(a), load(b)]);
      if (ia.width !== ib.width || ia.height !== ib.height) {
        throw new Error(`frames differ in size: ${ia.width}x${ia.height} vs ${ib.width}x${ib.height}`);
      }
      const data = (img) => {
        const c = document.createElement("canvas");
        c.width = img.width;
        c.height = img.height;
        const ctx = c.getContext("2d", { willReadFrequently: true });
        ctx.drawImage(img, 0, 0);
        return ctx.getImageData(0, 0, c.width, c.height).data;
      };
      const [pa, pb] = [data(ia), data(ib)];
      let n = 0;
      for (let i = 0; i < pa.length; i += 4) {
        if (
          Math.abs(pa[i] - pb[i]) > delta ||
          Math.abs(pa[i + 1] - pb[i + 1]) > delta ||
          Math.abs(pa[i + 2] - pb[i + 2]) > delta
        ) {
          n++;
        }
      }
      return (100 * n) / (pa.length / 4);
    },
    [`data:image/png;base64,${a}`, `data:image/png;base64,${b}`, MOVED_DELTA],
  );
}
