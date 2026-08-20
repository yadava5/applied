import manifest from "@/public/footage/manifest.json";

/**
 * Candidate 06 — provenance receipts: every fact under a clip read from
 * `public/footage/manifest.json`, which the render pipeline writes with the
 * real dimensions and byte counts of what it encoded. Nothing below is
 * typed by hand; delete a field from the manifest and it disappears here.
 *
 * Two fields the receipt SHOULD carry do not exist yet — the route the take
 * was captured from and the commit it was rendered at. `render.mjs` knows
 * both at render time and just doesn't write them; that is the one-line
 * pipeline change this candidate asks for, and until it lands those lines
 * are absent rather than invented.
 */

const kb = (bytes: number) => `${Math.round(bytes / 1024)} KB`;

export function ProvenanceReceipt() {
  const generated = manifest.generated.slice(0, 10);
  const exhibit = manifest.clips.find((c) => c.id === "board-syncs") ?? manifest.clips[0];

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,30rem)_minmax(0,1fr)] lg:items-start">
      <figure className="overflow-hidden rounded-xl border border-line-soft bg-surface">
        {/* The poster, not a fourth <video> — the receipt is the exhibit here. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={`/footage/${exhibit.id}.jpg`}
          alt={`Poster frame of the ${exhibit.id} recording`}
          width={exhibit.width}
          height={exhibit.height}
          className="block h-auto w-full"
        />
        <figcaption className="border-t border-line-soft px-4 py-2.5 font-mono text-[11px] leading-relaxed text-dim">
          {exhibit.id} · {exhibit.width}×{exhibit.height} · {exhibit.seconds}s ·{" "}
          {kb(exhibit.webm)} webm · rendered {generated}
        </figcaption>
      </figure>

      <div>
        <p className="label-caps">Every clip&apos;s receipt, from the same file</p>
        <ul className="mt-3 space-y-1.5 font-mono text-xs text-muted">
          {manifest.clips.map((clip) => (
            <li key={clip.id}>
              {clip.id} · {clip.width}×{clip.height} · {clip.seconds}s · {kb(clip.webm)} webm ·{" "}
              {kb(clip.mp4)} mp4
            </li>
          ))}
        </ul>
        <p className="mt-4 max-w-sm text-xs leading-relaxed text-dim">
          Missing on purpose: capture route and commit. The pipeline knows both and doesn&apos;t write
          them yet; adding the fields to <span className="font-mono">render.mjs</span> makes this
          receipt complete. Until then no route or commit appears — absent beats invented.
        </p>
      </div>
    </div>
  );
}
