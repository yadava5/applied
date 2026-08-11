/**
 * Shared control class strings so the file-application form and every Settings
 * section share one visual language — same borders, focus ring, radii, and
 * button treatments. Centralised so a polish tweak lands everywhere at once.
 */

export const inputClass =
  "w-full rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-strong outline-none transition-colors placeholder:text-dim focus:border-line-strong focus:ring-1 focus:ring-line-strong";

export const selectClass = inputClass;
export const textareaClass = `${inputClass} min-h-[72px] resize-y`;

export const fieldLabelClass = "label-caps";

export const primaryBtnClass =
  "inline-flex items-center justify-center gap-2 rounded-lg bg-strong px-4 py-2 text-sm font-medium text-background transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-line-strong disabled:cursor-not-allowed disabled:opacity-40";

export const secondaryBtnClass =
  "inline-flex items-center justify-center gap-2 rounded-lg border border-line px-4 py-2 text-sm text-foreground transition-colors hover:border-line-strong hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong disabled:opacity-40";

export const dangerBtnClass =
  "inline-flex items-center justify-center gap-2 rounded-lg border border-reject/50 px-4 py-2 text-sm text-reject-ink transition-colors hover:border-reject hover:bg-reject/10 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-reject disabled:cursor-not-allowed disabled:opacity-40";
