/**
 * The Settings sections' transport seam — how a preference write, the data
 * export, and the account actions reach the world.
 *
 * Same pattern as `lib/dashboard/transport.ts`, and for the same reason: the
 * signed-in Settings page is auth-gated, CI has no Supabase session, and every
 * settings e2e was skipping. The sections take a `mode` string (serializable,
 * so a Server Component can choose it) and resolve their transport here:
 * `live` talks to Supabase and the proxy exactly as before; `demo` — the
 * public `/demo/settings` twin — runs the identical component state machines
 * over simulated outcomes, which is what makes the real controls reviewable
 * and testable without a session. Nothing in the demo transport touches the
 * network, and its one refusal (account deletion) says plainly that it is a
 * refusal. It keeps exactly one thing — the notification prefs, in a session
 * cookie scoped to `/demo` — because those toggles promise a change to the
 * board and the twin can actually show it (#216); see
 * `lib/demo/notificationPrefs.ts`.
 */
import type { NotificationPrefs } from "@/components/settings/NotificationsSection";
import { createClient } from "@/lib/supabase/client";
import { demoApplicationsAsApi } from "@/lib/demo/asApplications";
import { writeDemoAmbientPref } from "@/lib/demo/ambientPref";
import { writeDemoNotificationPrefs } from "@/lib/demo/notificationPrefs";

export type SettingsMode = "live" | "demo";

export interface SettingsTransport {
  mode: SettingsMode;
  /** Persist a patch of the user's metadata (display name, notification
   *  prefs). Not the classification gate: that write existed and was inert —
   *  the backend read a module constant, never the metadata (#208). */
  saveMetadata(data: Record<string, unknown>): Promise<{ ok: boolean }>;
  /** Change the account password. Only offered when an `email` identity
   *  exists (the section gates on that), so `live` can always ask Supabase.
   *  `message` carries Supabase's own refusal — "same as the old password",
   *  a reauthentication demand — because that sentence is the actionable
   *  part. */
  updatePassword(password: string): Promise<{ ok: boolean; message?: string }>;
  /** Fetch everything the export downloads. The section owns the blob/anchor
   *  dance — that part is the browser's either way. */
  exportApplications(): Promise<{ ok: boolean; data?: unknown }>;
  /** End the session. The section owns the navigation that follows. */
  signOut(): Promise<void>;
  deleteAccount(): Promise<{ ok: boolean; detail?: string }>;
}

const live: SettingsTransport = {
  mode: "live",
  async saveMetadata(data) {
    const supabase = createClient();
    const { error } = await supabase.auth.updateUser({ data });
    return { ok: !error };
  },
  async updatePassword(password) {
    const supabase = createClient();
    const { error } = await supabase.auth.updateUser({ password });
    if (!error) return { ok: true };
    // If the Supabase project has "secure password change" enabled, this call
    // demands a recent sign-in and refuses with a reauthentication error. The
    // project's setting is unverified, so the refusal is translated into the
    // action that resolves it rather than surfaced as a raw 400 the first
    // time it happens in production.
    const needsReauth =
      error.code === "reauthentication_needed" || /reauthenticat/i.test(error.message);
    return {
      ok: false,
      message: needsReauth
        ? "For security, changing your password needs a fresh sign-in. Sign out, sign back in, then try again."
        : error.message,
    };
  },
  async exportApplications() {
    try {
      const res = await fetch("/api/applications", { headers: { Accept: "application/json" } });
      if (!res.ok) return { ok: false };
      return { ok: true, data: await res.json() };
    } catch {
      return { ok: false };
    }
  },
  async signOut() {
    const supabase = createClient();
    await supabase.auth.signOut();
  },
  async deleteAccount() {
    try {
      const res = await fetch("/api/account/delete", { method: "POST" });
      if (res.ok) return { ok: true };
      const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
      return {
        ok: false,
        detail:
          typeof body.detail === "string"
            ? body.detail
            : "Account deletion isn’t available on this deployment yet.",
      };
    } catch {
      return { ok: false, detail: "Couldn’t reach the server. Try again shortly." };
    }
  },
};

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** `saveMetadata` takes an open patch (`Record<string, unknown>`), so the one
 *  key the demo keeps has to be narrowed rather than asserted. */
function isNotificationPrefs(value: unknown): value is NotificationPrefs {
  if (typeof value !== "object" || value === null) return false;
  const prefs = value as Partial<NotificationPrefs>;
  return typeof prefs.weekly === "boolean" && typeof prefs.reviewAlerts === "boolean";
}

const demo: SettingsTransport = {
  mode: "demo",
  async saveMetadata(data) {
    // Long enough that "Saving…" renders and can be asserted.
    await delay(300);
    // The ONE thing the twin keeps: the notification prefs, in a session
    // cookie scoped to /demo (`lib/demo/notificationPrefs.ts`). Not a
    // concession to testing — it is what makes the toggles honest here. Their
    // own copy promises a change to the board, and until #216 the twin's
    // toggles could not deliver one on any surface, which is the same
    // "control looks dead" complaint the signed-in page had for a different
    // reason. Everything else a section writes (display name, gate) is still
    // dropped: nothing on this twin has anywhere to show it.
    if (isNotificationPrefs(data.notifications)) writeDemoNotificationPrefs(data.notifications);
    // The ambient-mail switch, for the same reason: it promises a change to
    // the shell's rail, and `/demo/shell` reads this cookie exactly as the
    // signed-in layout reads the metadata (`lib/demo/ambientPref.ts`).
    if (typeof data.ambient === "boolean") writeDemoAmbientPref(data.ambient);
    return { ok: true };
  },
  async updatePassword() {
    // The fixture account is email-identity-shaped, so the control renders
    // and the whole machine runs; nothing persists, like every demo write.
    await delay(300);
    return { ok: true };
  },
  async exportApplications() {
    await delay(300);
    // The twin's export is a real download of the fixture board — the control
    // genuinely works, on data that is genuinely synthetic.
    return { ok: true, data: { applications: demoApplicationsAsApi() } };
  },
  async signOut() {
    await delay(150);
  },
  async deleteAccount() {
    await delay(300);
    return { ok: false, detail: "Simulated account — nothing exists to delete on the demo." };
  },
};

export function settingsTransport(mode: SettingsMode): SettingsTransport {
  return mode === "demo" ? demo : live;
}
