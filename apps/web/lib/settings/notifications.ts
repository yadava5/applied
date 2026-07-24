import type { NotificationPrefs } from "@/components/settings/NotificationsSection";

/**
 * Read a user's notification preferences out of their Supabase user metadata.
 *
 * Shared by the Settings page (renders the toggles) and the Dashboard (drives
 * the real in-app cues those toggles gate) so both agree on the exact shape and
 * on the safe default of "off" for a never-set flag. Pure and defensive: an
 * absent or malformed `notifications` blob yields both flags false.
 */
export function readNotificationPrefs(meta: Record<string, unknown>): NotificationPrefs {
  const raw = (meta.notifications ?? {}) as Record<string, unknown>;
  return { weekly: raw.weekly === true, reviewAlerts: raw.reviewAlerts === true };
}
