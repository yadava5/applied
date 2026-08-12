/**
 * The Settings page's table of contents — plain anchors into the section ids,
 * in the form each viewport can carry. Server-rendered in both: no scroll-spy,
 * no state — the shell's scroll pane honours the fragment jumps, and each
 * section's `scroll-mt` keeps its heading clear of whatever is pinned above it.
 *
 *  - `lg` and up: a sticky rail beside the cards.
 *  - below `lg`: a chip strip pinned to the top of the scroll pane. The rail
 *    used to be `hidden lg:block` and nothing replaced it, which left a phone
 *    with 2819px of settings and no way to move through it. Horizontal scroll
 *    rather than a wrap so the strip stays one row tall whatever the labels
 *    measure, and `SettingsSection`'s `scroll-mt` clears its height so a jump
 *    never lands a heading underneath it.
 *
 * The strip's accessible name is deliberately not the rail's: two navigations
 * answering to "Settings sections" is a worse a11y tree to move through, and an
 * ambiguous selector for anything driving the page.
 */
const ITEMS: { id: string; label: string }[] = [
  { id: "profile", label: "Profile" },
  { id: "appearance", label: "Appearance" },
  { id: "gmail", label: "Gmail" },
  { id: "notifications", label: "Notifications" },
  { id: "classification", label: "Classification" },
  { id: "data", label: "Your data" },
  { id: "account", label: "Account" },
];

export function SettingsNav() {
  return (
    <>
      {/* `-mx-6` bleeds the strip to the scroll pane's edges — both pages that
          render this pad by 6 — so the pinned background covers the full width
          of what passes under it and the chips scroll edge to edge. */}
      <nav
        aria-label="Jump to section"
        className="sticky top-0 z-20 -mx-6 mb-4 border-b border-line-soft bg-background lg:hidden"
      >
        <ul className="flex gap-2 overflow-x-auto px-6 py-2">
          {ITEMS.map((item) => (
            <li key={item.id}>
              <a
                href={`#${item.id}`}
                className="inline-flex min-h-9 items-center whitespace-nowrap rounded-full border border-line px-3 text-[13px] text-muted transition-colors hover:border-line-strong hover:text-strong"
              >
                {item.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <nav
        aria-label="Settings sections"
        className="hidden lg:block lg:self-start lg:sticky lg:top-1"
      >
        <ul className="space-y-0.5 border-l border-line-soft">
          {ITEMS.map((item) => (
            <li key={item.id}>
              <a
                href={`#${item.id}`}
                className="-ml-px block border-l border-transparent py-1 pl-3 text-[13px] text-muted transition-colors hover:border-line-strong hover:text-strong"
              >
                {item.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>
    </>
  );
}
