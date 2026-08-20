"use client";

import { useEffect, useMemo, useState } from "react";

import { ReviewQueue } from "@/components/dashboard/ReviewQueue";
import { showcaseApplications } from "@/components/marketing/showcase";
import { todayISO } from "@/lib/dashboard/age";

import type { Director } from "./director";
import { TakeStage } from "./TakeStage";
import { atlasReviewItem, cedarReviewItem } from "./heldCast";

/**
 * 08b — twenty seconds on a Tuesday: the human's half of the loop, on the
 * REAL review queue. Two mails wait. The first is obvious to a person and
 * was genuinely ambiguous to a machine reading Gmail's snippet — which is
 * the production-measured truth of how every real rejection has ever
 * reached the board: through this gate, by a human's stamp. The pointer
 * travels to the decision control and the take ends AT the boundary,
 * because the boundary is the product: the next click is yours, and Applied
 * files exactly what you say.
 *
 * Deliberately not staged: the click itself. The queue row's classify call
 * has no injection seam (it POSTs to the API), so a take that "filed" the
 * row would be forging the one decision this surface exists to reserve for
 * a person. Commissioning the full clear-the-tray cut means adding that
 * seam — a product improvement the demo twin already wants.
 */
export function TwentySeconds() {
  // Client-only: the queue rows print calendar days against the real clock.
  // Deferred off the effect body — the house rule every fixture mount follows.
  const [today, setToday] = useState<string | null>(null);
  useEffect(() => {
    const id = window.setTimeout(() => setToday(todayISO()), 0);
    return () => window.clearTimeout(id);
  }, []);

  const items = useMemo(
    () => (today ? [atlasReviewItem(today), cedarReviewItem(today)] : []),
    [today],
  );
  const apps = useMemo(() => (today ? showcaseApplications(today) : []), [today]);

  const take = async (d: Director) => {
    await d.waitFor(() => d.query("#needs-classification li"), 12000, "the review queue");
    d.say("Tuesday, 9:14. Two mails wait — Applied held both rather than guess.");
    await d.hold(2000);
    d.enterCursor();
    const firstRow = () => d.query("#needs-classification li");
    await d.moveTo(firstRow);
    d.say("The first is obvious to a person; the machine saw only the snippet's polite preamble. Your no is a decision, not a guess.");
    await d.hold(2400);
    const control = () => d.query("#needs-classification li select") ?? firstRow();
    await d.moveTo(control);
    d.say("From here the click is yours. Pick the answer and Applied files it exactly as you said — recorded, never overwritten.");
    await d.hold(2200);
    d.say("Twenty seconds on a Tuesday, and the tray is yours to empty.");
    await d.hold(900);
  };

  return (
    <TakeStage
      take={take}
      height={430}
      frameLabel="the real review queue — the take stops where your decision starts"
      opening="The human's half of the loop: two held mails, and the click that is yours alone."
    >
      <div className="mx-auto max-w-3xl">
        {today && <ReviewQueue items={items} applications={apps} />}
      </div>
    </TakeStage>
  );
}
