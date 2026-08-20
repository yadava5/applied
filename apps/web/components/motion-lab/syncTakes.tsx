"use client";

import dynamic from "next/dynamic";

import { useWideViewport } from "@/components/marketing/scrub";

import type { Director } from "./director";
import { NarrowNote, TakeStage } from "./TakeStage";

/**
 * 03a and 03b — two cameras on the one loop the product actually runs:
 * whole dashboard, the Sync control, a real press, the spinner, and what
 * the pass filed. Both takes mount `LabSyncBoard` — the shipped SyncBar +
 * PipelineBoard + ReviewQueue over the showcase fixture — and the press is
 * a real click, so the run, the receipt, the subtitle's new totals and the
 * held arrival are all the components' own doing.
 *
 * Honesty constraint carried from the old plate 03, unchanged: the
 * simulated sync commits pre-labelled fixture rows — it classifies nothing
 * in this frame — so every caption stays scoped to what the pass FILED.
 * And the content rule from production truth: no rejection ever arrives by
 * sync; the ambiguous mail lands held, which is where a real rejection
 * actually enters the board.
 */
const LabSyncBoard = dynamic(() => import("./LabSyncBoard").then((m) => m.LabSyncBoard), {
  ssr: false,
});

/** 03a — the round trip. The industry default zooms in on the click and
 *  lingers; this take pulls OUT while the spinner runs, so the wait becomes
 *  anticipation and the payoff lands in the wide shot. */
const roundTrip = async (d: Director) => {
  await d.waitFor(() => d.buttonByText("Sync"), 14000, "the dashboard");
  await d.fitAll(0);
  d.say("Tuesday morning. The board is yesterday's truth.");
  await d.hold(1500);

  d.enterCursor();
  const sync = () => d.buttonByText("Sync");
  d.say("One control asks Gmail what's new.");
  await Promise.all([d.zoomTo(sync, 1.35, 1600), d.moveTo(sync, 1500)]);
  await d.click(sync);

  d.say("It runs — and you can step back while it looks.");
  await d.fitAll(1900);

  await d.waitFor(() => d.query('button[aria-label^="Open Foxglove"]'), 9000, "the arrivals");
  d.say("Two fresh confirmations file themselves at the top…");
  await d.zoomTo(() => d.query('button[aria-label^="Open Foxglove"]'), 1, 1500);
  await d.hold(2000);

  await d.waitFor(() => d.query("#needs-classification"), 6000, "the review tray");
  d.say("…and the one mail it wouldn't guess about lands amber — held for you, never filed over your head.");
  await d.zoomTo(() => d.query("#needs-classification"), 1, 1600);
  await d.hold(2400);

  d.say("The top line keeps the receipt, and the totals already moved. Mail in, board current.");
  await d.zoomTo(sync, 1, 1500);
  await d.hold(1800);
  await d.fitAll(1500);
  await d.hold(800);
  d.hideCursor();
};

/** 03b — the master shot: the camera never moves after the establishing
 *  frame. Restraint as the effect — the product's own motion (the running
 *  state, the arrivals' glide, the tray appearing) is the whole show. */
const masterShot = async (d: Director) => {
  await d.waitFor(() => d.buttonByText("Sync"), 14000, "the dashboard");
  await d.fitAll(0);
  d.say("A master shot — the camera holds, and the product is the only effect.");
  await d.hold(1400);

  d.enterCursor();
  const sync = () => d.buttonByText("Sync");
  await d.moveTo(sync);
  await d.click(sync);
  d.say("The top line reports while it runs — scope and elapsed time, never an invented percentage.");

  await d.waitFor(() => d.query('button[aria-label^="Open Foxglove"]'), 9000, "the arrivals");
  d.say("Two arrivals glide in, newest first; one ambiguous mail waits amber in the tray below.");
  await d.hold(2800);
  d.say("The shipped dashboard over a simulated account — the behaviour is the product's own.");
  await d.hold(1200);
  d.hideCursor();
};

function SyncTake({
  take,
  opening,
}: {
  take: (d: Director) => Promise<void>;
  opening: string;
}) {
  const wide = useWideViewport();
  if (!wide) return <NarrowNote what="The sync story" />;
  return (
    <TakeStage
      take={take}
      height={600}
      frameLabel="live sync — the shipped SyncBar and board; the press is a real press"
      opening={opening}
    >
      <LabSyncBoard />
    </TakeStage>
  );
}

export function RoundTrip() {
  return (
    <SyncTake
      take={roundTrip}
      opening="Wide, in to the control, a real press — then out while it runs, and the payoff lands wide."
    />
  );
}

export function MasterShot() {
  return (
    <SyncTake
      take={masterShot}
      opening="One fixed frame; the sync's own states carry the scene."
    />
  );
}
