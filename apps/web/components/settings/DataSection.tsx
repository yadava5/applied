"use client";

import Link from "next/link";
import { useState } from "react";
import { Download, Upload } from "lucide-react";

import { SettingsSection } from "./SettingsSection";
import { notifySuccess } from "@/components/feedback/notify";
import { secondaryBtnClass } from "@/components/ui/formStyles";
import { buildExportFile } from "@/lib/applications/export";
import { localTodayISO } from "@/lib/dashboard/age";
import { settingsTransport, type SettingsMode } from "@/lib/settings/transport";

type ExportState = "idle" | "working" | "error";

/** What the export endpoint hands back. Both arrays are optional: the
 *  `/demo/settings` twin's transport answers with the fixture board alone. */
type ExportPayload = { applications?: unknown[]; messages?: unknown[] };

/**
 * Data: your applications and your stored mail, out of Applied and onto your
 * disk, plus the on-device mail import path. Export pulls the rows through the
 * settings transport (live: the server-side proxy, which carries your JWT) and
 * downloads them as JSON entirely in the browser — no third party, nothing
 * emailed.
 *
 * It used to say "everything Applied holds for you" over a file that held the
 * live board and nothing else (#217). It now carries every application
 * including the removed ones, and every stored message as metadata; the file
 * names its own contents and states what it leaves out, because a download
 * that is opened six months later has no other context. What it leaves out is
 * deliberate — the Google OAuth credentials above all, which belong on the
 * server and nowhere near a Downloads folder.
 */
export function DataSection({ mode = "live" }: { mode?: SettingsMode }) {
  const [state, setState] = useState<ExportState>("idle");
  const transport = settingsTransport(mode);

  async function exportData() {
    setState("working");
    const result = await transport.exportApplications();
    if (!result.ok) {
      setState("error");
      return;
    }
    // The envelope is built by a shared pure function, not here and not in the
    // route: the live export and the demo twin have to produce the same file
    // shape, and the twin's download is the only one an e2e can capture.
    const payload = (result.data ?? {}) as ExportPayload;
    const file = buildExportFile({
      applications: payload.applications ?? [],
      messages: payload.messages ?? [],
    });
    const blob = new Blob([JSON.stringify(file, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    // The user's own day, not UTC. `toISOString()` here put tomorrow's date
    // on the file for anyone west of Greenwich after their evening cutoff —
    // a New York export at 9pm was stamped with the next day. Same defect as
    // the deadline bucketing, in a filename rather than a card.
    a.download = `applied-export-${localTodayISO()}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    setState("idle");
    // The one acknowledgement the flow gets from the APP (#511): the button
    // face reverting to idle is indistinguishable from nothing having
    // happened, and the download strip is browser chrome, not this page.
    // Failure keeps its inline `role="alert"` below — closer to the control,
    // and already reporting itself, so it must not also toast.
    notifySuccess("data.export", "Export ready — check your downloads");
  }

  return (
    <SettingsSection id="data" title="Your data">
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={exportData} disabled={state === "working"} className={secondaryBtnClass}>
          <Download className="h-4 w-4" aria-hidden="true" />
          {state === "working" ? "Preparing…" : "Export applications and mail (JSON)"}
        </button>
        <Link href="/import" className={secondaryBtnClass}>
          <Upload className="h-4 w-4" aria-hidden="true" />
          Import mail
        </Link>
      </div>
      {state === "error" ? (
        <p role="alert" className="mt-3 text-xs text-reject-ink">
          Couldn’t prepare the export — the backend may be unreachable. Try again shortly.
        </p>
      ) : null}
    </SettingsSection>
  );
}
