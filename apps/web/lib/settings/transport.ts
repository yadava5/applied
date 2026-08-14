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
 * refusal.
 */
import { createClient } from "@/lib/supabase/client";
import { demoApplicationsAsApi } from "@/lib/demo/asApplications";

export type SettingsMode = "live" | "demo";

export interface SettingsTransport {
  mode: SettingsMode;
  /** Persist a patch of the user's metadata (display name, prefs, gate). */
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

const demo: SettingsTransport = {
  mode: "demo",
  async saveMetadata() {
    // Long enough that "Saving…" renders and can be asserted; nothing persists.
    await delay(300);
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
