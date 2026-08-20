import type { ReactNode } from "react";

/**
 * The lab's one structural device: a numbered specimen plate.
 *
 * Every candidate motion treatment renders inside one of these, and the frame
 * carries the four things the owner needs to judge it in a minute — what it
 * argues, what it costs, how it could lie, and what makes it honest — plus a
 * short ID he can reply with ("build 02, 06, 09"). The ID is the reply key,
 * which is why it renders in the machine face.
 *
 * `fidelity` is the page's honesty gradient made visible: LIVE plates really
 * run in this page; STORYBOARD plates have not been recorded or built, and the
 * amber dashed stamp says so before anything else does.
 *
 * STORYBOARD does NOT mean "needs footage", which is what this said until the
 * 03c round: two of that family's four options are buildable as real DOM and
 * need no render at all. The stamp is a claim about what the plate IS — held
 * frames and notation — not a prediction about how the shot would be made.
 * Each plate says which it needs, in its own `costs`.
 */
export type Fidelity = "live" | "storyboard";

export interface PlateInfo {
  /** The reply key — two digits, matching the brief's own numbering. */
  id: string;
  anchor: string;
  title: string;
  fidelity: Fidelity;
  /** One line: the claim this treatment makes for itself. */
  argues: string;
  /** Bytes, build time, risk. */
  costs: string;
  /** The specific dishonesty this treatment is one step away from. */
  lie: string;
  /** The construction that closes that door. */
  honest: string;
}

export function FidelityStamp({ fidelity }: { fidelity: Fidelity }) {
  return fidelity === "live" ? (
    <span className="label-caps inline-flex items-center gap-1.5 rounded-full border border-viz-rules/40 px-2.5 py-1 text-viz-rules">
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-viz-rules" />
      live now
    </span>
  ) : (
    <span className="label-caps inline-flex items-center rounded-full border border-dashed border-review/50 px-2.5 py-1 text-review">
      storyboard · not recorded
    </span>
  );
}

export function Plate({ info, children }: { info: PlateInfo; children: ReactNode }) {
  return (
    <section id={info.anchor} className="scroll-mt-16 border-t border-line-soft">
      <div className="mx-auto w-full max-w-5xl px-6 py-14">
        <header className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <span className="font-mono text-2xl text-viz-rules">{info.id}</span>
          <h2 className="text-xl font-medium tracking-tight text-strong">{info.title}</h2>
          <FidelityStamp fidelity={info.fidelity} />
        </header>
        <p className="mt-3 max-w-2xl text-muted">{info.argues}</p>

        <div className="mt-8">{children}</div>

        <dl className="mt-8 grid gap-x-8 gap-y-4 border-t border-line-soft pt-5 text-sm sm:grid-cols-3">
          <div>
            <dt className="label-caps">What it costs</dt>
            <dd className="mt-1.5 leading-relaxed text-dim">{info.costs}</dd>
          </div>
          <div>
            <dt className="label-caps">How it could lie</dt>
            <dd className="mt-1.5 leading-relaxed text-dim">{info.lie}</dd>
          </div>
          <div>
            <dt className="label-caps">What makes it honest</dt>
            <dd className="mt-1.5 leading-relaxed text-dim">{info.honest}</dd>
          </div>
        </dl>
      </div>
    </section>
  );
}
