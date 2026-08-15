import { cn } from "@/lib/utils";

/**
 * One line of real text, stood in for at that text's own height.
 *
 * The whole point of a pending surface is that the swap to content does not
 * move anything, and the way this repo got that wrong was by declaring
 * heights: `h-44` for a drop zone that measures 330, `h-11` for a row that
 * measures 61. A declared height is a claim about a box someone else owns,
 * and it goes stale the first time that box changes.
 *
 * So this stands in for a line WITHOUT declaring a height. It is an
 * inline-block 2px hairline dropped into a normal line box; CSS 2.1 §10.8
 * guarantees every line box is at least as tall as its parent's strut, so the
 * height comes out of the parent's own `font-size`/`line-height` — the same
 * two values the real text is set in. The caller's job is therefore not
 * arithmetic but transcription: copy the real element's type classes onto the
 * wrapper (`text-sm`, `text-[13px]`, `leading-relaxed`) and the line lands at
 * the real line's height, in this theme, at this width, forever.
 *
 * `width` is the one thing that IS a guess — it is how much of the line the
 * words fill — and it is the axis nothing reflows on.
 *
 * ONE TRAP, and it is the whole reason this is documented rather than inlined:
 * the strut belongs to a BLOCK container's line box. Drop this straight into a
 * `flex`/`inline-flex` parent and it becomes a flex item — no line box, no
 * strut, and the box collapses to its own 2px. Put the type classes on a plain
 * block (a `<p>`, a `<span>` that is itself a flex ITEM) and the line stands.
 */
export function QuietLine({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn("inline-block h-2 rounded-full border border-line align-middle", className)}
    />
  );
}
