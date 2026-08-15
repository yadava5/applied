import { QuietEnvelope } from "@/components/boot/QuietEnvelope";

/**
 * Instant pending state for /import — the Triage boot's quiet form. The route
 * is dual-mode (shell-wrapped when signed in, standalone public page when
 * not) and the pending UI cannot know which branch is coming, so it renders
 * the one thing both share: the centred drop-zone measure, as a hairline
 * outline with the classify envelope alive at its centre. What it buys is an
 * answer to the click — before this, a signed-in navigation here held the
 * previous page on screen for the whole origin wait (700–1150 ms, #203).
 */
export default function ImportLoading() {
  return (
    <div
      aria-busy="true"
      aria-label="Loading mail import"
      className="boot-quiet mx-auto my-auto w-full max-w-3xl px-6 py-10"
    >
      <div className="flex h-44 items-center justify-center rounded-2xl border border-line-soft">
        <QuietEnvelope index={0} lit className="h-[24px] w-[34px]" />
      </div>
      <div className="mx-auto mt-6 h-4 w-64 rounded border border-line" />
    </div>
  );
}
