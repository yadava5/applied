/**
 * The Settings page's table of contents — plain anchors into the section ids,
 * sticky beside the cards at desktop, absent below `lg` (five cards on a
 * phone don't need a map). Server-rendered: no scroll-spy, no state — the
 * shell's scroll pane honours the fragment jumps, and each section's
 * `scroll-mt` keeps its heading clear of the pane's edge.
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
  );
}
