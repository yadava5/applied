"use client";

import { useEffect, useMemo, useState } from "react";

import { ApplicationRow } from "@/components/dashboard/ApplicationRow";
import { showcaseApplications } from "@/components/marketing/showcase";
import { todayISO } from "@/lib/dashboard/age";
import { boardColumns } from "@/lib/dashboard/board";
import { STAGES, type Application } from "@/lib/dashboard/summary";
import type { BoardTransport } from "@/lib/dashboard/transport";

import { TRIO } from "./heldCast";
import { buildTraceView, categoryWord, segments } from "./traceEvidence";

/**
 * 03c — four storyboards for one question: how does a visitor watch ONE piece
 * of mail become ONE row on the board?
 *
 * The four differ in CAMERA LOGIC, not in easing or palette, and the page is
 * built so that difference is the only thing that varies. Every frame below
 * draws the same two subjects — the cast's Kestrel assessment mail and the
 * showcase board it files into — from real components; what changes between
 * options is where the camera is, how it moves, and whether it cuts. Four
 * grammars, in the order a director would name them:
 *
 *   i   TRACK — the subject moves, the camera rides with it.
 *   ii  CUT   — nothing moves; two locked frames joined on a graphic match.
 *   iii RACK  — one frame holds both subjects; the depth of field changes.
 *   iv  PUSH  — the subject is still, the camera travels in on axis, through it.
 *
 * NOTHING HERE ANIMATES, deliberately. The plate's honest line has always
 * been "the storyboard is cards, not a canned animation", and a strip that
 * played would be claiming a take nobody has recorded. The motion argument is
 * carried by the notation glyph over each strip — a director's mark for the
 * camera's path across the shot's own seconds — and by held frames either
 * side of every move.
 *
 * SIZED FOR THE RAIL, NOT THE STAGE. The winner mounts on the landing's right
 * retention rail, whose column is `minmax(0,26rem)` = 416px and whose box is
 * 16.5rem tall (that number is `ClaimsDescent`'s own measured constant, taken
 * at 1024). Net of the clip frame's head strip, track and stacked caption the
 * PICTURE there is about 416x160 — a 2.6:1 letterbox. So the frames below are
 * drawn at exactly 416x160. What is illegible in one of these boxes will be
 * illegible on the landing, and that is the point of drawing them at size.
 *
 * TWO REFUSALS, carried into every option:
 *   - no frame may imply a sync classified the mail live. The verdict and the
 *     lit spans are computed before any camera moves, exactly as 02a's caption
 *     already scopes it;
 *   - the tracked letter is NEVER a rejection. Production has never
 *     auto-detected one — every rejection on a real board came through the
 *     human review gate — so a shot that files one on its own would be
 *     fabricating a capability. Kestrel's assessment is the subject in all
 *     four, and it is the same mail and the same row the rest of the lab uses.
 */

/* -------------------------------------------------------------------------
 * The two subjects, as real surfaces
 * ---------------------------------------------------------------------- */

/** The cast's assessment mail — 08's second card, and the row it files into is
 *  the showcase board's own `assessment` row. One story across the lab. */
const KESTREL = TRIO[1]!;

/** A second and third arrival, for the frames where mail comes in a stream.
 *  Fabricated data (the owner's allowance), cast-consistent: Waypoint is the
 *  showcase board's freshest `applied` row and Cedar is 08's held mail. Both
 *  are acknowledgments or questions — no rejection ever arrives this way. */
const COMPANIONS = [
  { subject: "Thanks for applying to Waypoint Robotics", sender: "careers@waypointrobotics.com" },
  { subject: TRIO[2]!.subject, sender: TRIO[2]!.sender },
] as const;

/** In-memory no-ops: the storyboard's rows render and behave, and can reach
 *  nothing. Same guard the 02 plates mount their row behind. */
const inertTransport: BoardTransport = {
  async changeStatus(_id, status) {
    return { ok: true, status };
  },
  async setDeadline() {
    return { ok: true };
  },
  async setRole() {
    return { ok: true };
  },
  async dismiss() {
    return { ok: true };
  },
  async deleteRow() {
    return { ok: true };
  },
  async detail() {
    return { ok: false, body: {} };
  },
};

/** Natural widths of the two surfaces, in the world the camera crops. */
const MAIL_W = 360;
const BOARD_W = 440;

/** The rail's picture box — see the header for where these come from. */
const FRAME_W = 416;
const FRAME_H = 160;

function MailSurface({
  subject,
  sender,
  body,
  lit = false,
  stamped = false,
  verdict,
}: {
  subject: string;
  sender: string;
  body?: string;
  /** The deciding phrases, at the offsets the scoring walk recorded. */
  lit?: boolean;
  stamped?: boolean;
  verdict?: string;
}) {
  const view = useMemo(
    () => (body ? buildTraceView({ subject, body, senderEmail: sender }) : null),
    [subject, body, sender],
  );

  const field = (text: string, which: "subject" | "body") => {
    if (!view || !lit) return text;
    const ranges = which === "subject" ? view.subjectRanges : view.bodyRanges;
    return segments(text, ranges).map((seg, i) =>
      seg.mark ? (
        <mark
          key={i}
          className="rounded-sm bg-viz-rules/15 px-0.5 text-strong shadow-[inset_0_-1px_0_var(--viz-rules)]"
        >
          {seg.text}
        </mark>
      ) : (
        <span key={i}>{seg.text}</span>
      ),
    );
  };

  return (
    <div
      style={{ width: MAIL_W }}
      className="overflow-hidden rounded-xl border border-line-soft bg-surface"
    >
      <div className="border-b border-line-soft px-3.5 py-2.5">
        <div className="flex items-start justify-between gap-2">
          <p className="min-w-0 text-[0.8125rem] font-medium leading-snug text-strong">
            {field(subject, "subject")}
          </p>
          {stamped && verdict && (
            <span className="label-caps inline-flex shrink-0 items-center gap-1.5 rounded-full border border-viz-rules/40 px-2 py-0.5 text-viz-rules">
              <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-viz-rules" />
              {verdict}
            </span>
          )}
        </div>
        <p className="mt-0.5 font-mono text-[0.6875rem] text-dim">{sender}</p>
      </div>
      {body && (
        <p className="px-3.5 py-2.5 text-[0.75rem] leading-relaxed text-muted">
          {field(body, "body")}
        </p>
      )}
    </div>
  );
}

/** The stage group heading, in the board's own grammar — dot, label, count,
 *  rule (`PipelineBoard`'s header markup, same tokens). */
function GroupHead({ label, color, count }: { label: string; color: string; count: number }) {
  return (
    <div className="mb-1.5 flex items-baseline gap-2 px-1">
      <span className="label-caps inline-flex items-center gap-1.5 text-muted">
        <span aria-hidden className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
        {label}
      </span>
      <span className="tabular font-mono text-xs text-muted">{count}</span>
      <span aria-hidden className="h-px flex-1 bg-line-soft" />
    </div>
  );
}

/** Where the `assessment` heading sits inside `BoardSurface`, in surface px —
 *  measured off the rendered strip, and the anchor every board crop below is
 *  written against (`top: WANT - ASSESS * scale` puts the heading at WANT).
 *  Re-measure it if the surface above gains a row. */
const ASSESS = 95;

/** Two of the board's stage groups: the one the mail comes from and the one it
 *  lands in. `seated` is the whole difference between a before frame and an
 *  after frame — before it, the `assessment` group is empty, and it renders
 *  the board's OWN empty cell rather than a placeholder drawn for the shot. */
function BoardSurface({ seated, today }: { seated: boolean; today: string }) {
  const columns = useMemo(() => boardColumns(STAGES), []);
  const apps = useMemo(() => showcaseApplications(today), [today]);
  const applied = apps.find((a) => a.status === "applied");
  const kestrel = apps.find((a) => a.company === "Kestrel Dynamics");
  const appliedCol = columns.find((c) => c.key === "applied");
  const assessCol = columns.find((c) => c.key === "assessment");
  if (!applied || !kestrel || !appliedCol || !assessCol) return null;

  // NOT overridden: `ApplicationRow` does not render `notes` at all, so a row
  // whose last signal was set to the mail's subject would look identical and
  // the match cut would be matching on something the product never draws. The
  // line the cut matches is the row's NAME — which is a fact about the data,
  // not a projection: the company on the row came from this mail.
  const seatedRow: Application = kestrel;

  return (
    <div style={{ width: BOARD_W }} className="text-left">
      <GroupHead label={appliedCol.label} color={appliedCol.color} count={3} />
      <ApplicationRow
        app={applied}
        columnLabel={appliedCol.label}
        today={today}
        transport={inertTransport}
        revealOnOpen={false}
      />
      <div className="mt-3">
        <GroupHead label={assessCol.label} color={assessCol.color} count={seated ? 1 : 0} />
        {seated ? (
          <ApplicationRow
            app={seatedRow}
            columnLabel={assessCol.label}
            today={today}
            transport={inertTransport}
            revealOnOpen={false}
          />
        ) : (
          <p className="rounded-lg border border-dashed border-line-soft p-4 text-center text-xs text-dim">
            none yet
          </p>
        )}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------
 * The camera: a frame is a crop, and a layer is a subject inside it
 * ---------------------------------------------------------------------- */

interface Layer {
  subject: "mail" | "board";
  /** Frame-local position of the layer's top-left, before scale. */
  left: number;
  top: number;
  scale: number;
  opacity?: number;
  /** Storyboard shorthand for out-of-focus; a blur is composition, not a lens. */
  blur?: number;
  /** mail only */
  lit?: boolean;
  stamped?: boolean;
  which?: 0 | 1;
  /** board only */
  seated?: boolean;
  /** Half-frame, for the one frame that draws a cut. */
  clip?: "left" | "right";
}

interface FrameSpec {
  /** Beat bounds in seconds — machine values, so they set in mono. */
  from: number;
  to: number;
  name: string;
  what: string;
  layers: Layer[];
  /** Draws the splice rule at this frame-local x — the cut, on paper. */
  splice?: number;
  /** The match mark: one baseline, and a tick at each left edge that lands on
   *  it. Storyboard notation, never product UI. */
  match?: { y: number; xs: number[] };
}

/** Notation ink. Achromatic on purpose — in this system colour is semantic
 *  (green live, amber held, red closed) and a camera mark is not a semantic. */
const MARK = "color-mix(in oklab, var(--stage-applied) 60%, transparent)";

function Frame({ spec, today, verdict }: { spec: FrameSpec; today: string; verdict: string }) {
  return (
    <div
      className="relative shrink-0 overflow-hidden rounded-lg border border-line bg-background"
      style={{ width: FRAME_W, height: FRAME_H }}
    >
      {/* The surfaces are real components, cropped by the frame. They are inert
          and hidden from assistive tech: a crop can put a control half off
          screen, and every frame's meaning is in the visible line beneath it. */}
      <div aria-hidden className="pointer-events-none absolute inset-0 select-none">
        {spec.layers.map((layer, i) => (
          <div
            key={i}
            className="absolute left-0 top-0"
            style={
              layer.clip
                ? {
                    clipPath:
                      layer.clip === "left"
                        ? `inset(0 ${FRAME_W - (spec.splice ?? FRAME_W / 2)}px 0 0)`
                        : `inset(0 0 0 ${spec.splice ?? FRAME_W / 2}px)`,
                    inset: 0,
                  }
                : undefined
            }
          >
            <div
              className="absolute left-0 top-0 origin-top-left"
              style={{
                transform: `translate(${layer.left}px, ${layer.top}px) scale(${layer.scale})`,
                opacity: layer.opacity ?? 1,
                filter: layer.blur ? `blur(${layer.blur}px)` : undefined,
              }}
            >
              {layer.subject === "mail" ? (
                layer.which === undefined ? (
                  <MailSurface
                    subject={KESTREL.subject}
                    sender={KESTREL.sender}
                    body={KESTREL.body}
                    lit={layer.lit}
                    stamped={layer.stamped}
                    verdict={verdict}
                  />
                ) : (
                  <MailSurface
                    subject={COMPANIONS[layer.which]!.subject}
                    sender={COMPANIONS[layer.which]!.sender}
                  />
                )
              ) : (
                <BoardSurface seated={layer.seated ?? false} today={today} />
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Notation drawn ON the frame — the two marks a storyboard needs that a
          camera cannot show: where the cut falls, and what holds across it. */}
      {spec.splice !== undefined && (
        <span
          aria-hidden
          className="absolute inset-y-0 w-px"
          style={{ left: spec.splice, background: "var(--stage-applied)" }}
        />
      )}
      {spec.match && (
        <span aria-hidden>
          <span
            className="absolute inset-x-0 border-t border-dashed"
            style={{ top: spec.match.y, borderColor: MARK }}
          />
          {spec.match.xs.map((mx) => (
            <span
              key={mx}
              className="absolute w-px"
              style={{ left: mx, top: spec.match!.y - 9, height: 18, background: MARK }}
            />
          ))}
        </span>
      )}
      <span className="absolute bottom-1 right-1.5 font-mono text-[0.6rem] text-dim">
        {spec.from.toFixed(1)}–{spec.to.toFixed(1)}s
      </span>
    </div>
  );
}

/* -------------------------------------------------------------------------
 * The signature: a director's mark for each camera, on one shared clock
 * ---------------------------------------------------------------------- */

/** Every glyph is drawn on the same 0–9s axis, so a shot that takes longer
 *  draws a longer mark. Achromatic on purpose: in this system colour is
 *  semantic (green live, amber held, red closed) and the camera is not a
 *  semantic. `--stage-applied` is the one achromatic accent, and it is a
 *  fill/stroke token by definition — never text. */
const AXIS = 9;
const GW = 360;
const GH = 46;
const x = (t: number) => 6 + (t / AXIS) * (GW - 12);

function Notation({ kind, end }: { kind: OptionId; end: number }) {
  const stroke = "var(--stage-applied)";
  return (
    <svg
      viewBox={`0 0 ${GW} ${GH}`}
      className="h-12 w-full"
      role="img"
      aria-label={NOTATION_ALT[kind]}
    >
      {/* The clock: one tick a second, the shot's own end marked solid. */}
      {Array.from({ length: AXIS + 1 }, (_, s) => (
        <line
          key={s}
          x1={x(s)}
          x2={x(s)}
          y1={GH - 7}
          y2={GH - (s <= end ? 3 : 5)}
          stroke={stroke}
          strokeWidth={1}
          opacity={s <= end ? 0.55 : 0.18}
        />
      ))}

      {kind === "i" && (
        <g fill="none" stroke={stroke} strokeWidth={1.25}>
          {/* the camera's rail, and three brackets riding it */}
          <line x1={x(0)} x2={x(end)} y1={30} y2={30} opacity={0.45} />
          {[0.6, 4.2, 8.4].map((t) => (
            <path key={t} d={`M${x(t) - 7} 26 h-3 v8 h3 M${x(t) + 7} 26 h3 v8 h-3`} opacity={0.7} />
          ))}
          {/* the subject, travelling */}
          <path d={`M${x(0.3)} 15 C ${x(3)} 15, ${x(5.5)} 12, ${x(end - 0.6)} 17`} strokeWidth={1.5} />
          <path d={`M${x(end - 0.9)} 13 L${x(end - 0.3)} 17 L${x(end - 0.9)} 21`} strokeWidth={1.5} />
          <circle cx={x(0.3)} cy={15} r={2.6} fill="var(--text-strong)" stroke="none" />
        </g>
      )}

      {kind === "ii" && (
        <g fill="none" stroke={stroke} strokeWidth={1.25}>
          {/* three locked frames, two splices, and the line that survives both */}
          {([0.1, 1.75, 4.25] as const).map((t) => (
            <rect key={t} x={x(t)} y={11} width={13} height={10} opacity={0.85} />
          ))}
          <line x1={x(0.1) + 13} x2={x(1.42)} y1={16} y2={16} strokeWidth={1.5} />
          <line x1={x(1.75) + 13} x2={x(3.92)} y1={16} y2={16} strokeWidth={1.5} />
          <line x1={x(4.25) + 13} x2={x(end)} y1={16} y2={16} strokeWidth={1.5} />
          {([1.5, 4] as const).map((t) => (
            <path key={t} d={`M${x(t)} 6 l-6 20 M${x(t) + 5} 6 l-6 20`} strokeWidth={1.5} />
          ))}
          <line x1={x(0.1)} x2={x(end)} y1={31} y2={31} strokeDasharray="3 3" opacity={0.8} />
          <line x1={x(0.1)} x2={x(0.1)} y1={26} y2={36} opacity={0.8} />
          <line x1={x(1.75)} x2={x(1.75)} y1={26} y2={36} opacity={0.8} />
          <line x1={x(4.25)} x2={x(4.25)} y1={26} y2={36} opacity={0.8} />
        </g>
      )}

      {kind === "iii" && (
        <g stroke="none">
          {/* two planes trading sharpness — thickness IS focus, and they stay
              apart vertically so the handover reads as two planes, not one bar */}
          <path
            d={`M${x(0.1)} 6 L${x(end)} 25 L${x(end)} 26 L${x(0.1)} 14 Z`}
            fill={stroke}
            opacity={0.9}
          />
          <path
            d={`M${x(0.1)} 32 L${x(end)} 31 L${x(end)} 40 L${x(0.1)} 33 Z`}
            fill={stroke}
            opacity={0.65}
          />
          <circle cx={x(4.3)} cy={22} r={2.8} fill="var(--text-strong)" />
        </g>
      )}

      {kind === "iv" && (
        <g fill="none" stroke={stroke} strokeWidth={1.25}>
          {/* one axial move: wide, through the waist, wide again */}
          <path d={`M${x(0.1)} 8 L${x(4.4)} 21 L${x(end)} 9`} strokeWidth={1.4} />
          <path d={`M${x(0.1)} 35 L${x(4.4)} 22 L${x(end)} 34`} strokeWidth={1.4} />
          <path d={`M${x(3.9)} 16 L${x(4.7)} 21.5 L${x(3.9)} 27`} strokeWidth={1.6} />
          <circle cx={x(4.4)} cy={21.5} r={2.2} fill="var(--text-strong)" stroke="none" />
        </g>
      )}
    </svg>
  );
}

/* -------------------------------------------------------------------------
 * The four options
 * ---------------------------------------------------------------------- */

export type OptionId = "i" | "ii" | "iii" | "iv";

const NOTATION_ALT: Record<OptionId, string> = {
  i: "Camera notation: a rail running the length of the shot with three camera brackets on it, and a subject travelling above them.",
  ii: "Camera notation: three locked frames on one line, split by two film splices, with a dashed rule running under all three and a tick where each frame meets it — the line that holds across both cuts.",
  iii: "Camera notation: two planes crossing — one starting thick and thinning, one starting thin and thickening — with the handover marked at 4.3 seconds.",
  iv: "Camera notation: two lines converging from a wide opening to a waist at 4.4 seconds and opening out again — one axial move, through.",
};

interface Option {
  id: OptionId;
  grammar: string;
  title: string;
  /** The one-line answer to "what camera is this". */
  logic: string;
  frames: FrameSpec[];
  /** What a visitor knows when the last frame lands. */
  understands: string;
  /** Recorded take, or choreographed real DOM — one verdict, not a hedge. */
  needs: { kind: "take" | "dom"; what: string };
  /** Whether it survives a 416x160 rail picture, in its own words. */
  rail: string;
}

const OPTIONS: Option[] = [
  {
    id: "i",
    grammar: "track",
    title: "Ride the letter",
    logic:
      "The subject moves and the camera moves with it, locked, for the whole shot. One continuous travel; no cut, no held frame.",
    understands:
      "That one mail out of several was followed the whole way, and the row at the end is that same object — because the camera never let go of it.",
    needs: {
      kind: "take",
      what: "A Remotion take. Continuous travel with a mid-flight transformation and real depth is the one thing DOM cannot do honestly — layered blur is not parallax, and a transform tween through a component swap reads as a glitch at 60fps.",
    },
    rail: "The hardest fit of the four. Travel needs distance, and 160px of height gives none — the move has to run laterally, which means the mail is legible only while the camera is close, so the board is off-frame until the last beat. Budget a second pass on the crop before committing the render.",
    frames: [
      {
        from: 0,
        to: 1.8,
        name: "The stream, and the lock",
        what: "Three arrivals drift in at reading pace; the camera settles on Kestrel's and the other two soften out of the focal plane.",
        layers: [
          { subject: "mail", which: 0, left: -60, top: -4, scale: 0.52, opacity: 0.62, blur: 1.5 },
          { subject: "mail", left: 96, top: 10, scale: 0.62 },
          { subject: "mail", which: 1, left: 312, top: 22, scale: 0.52, opacity: 0.62, blur: 1.5 },
        ],
      },
      {
        from: 1.8,
        to: 4.4,
        name: "The reading, in flight",
        what: "Still travelling, the mail opens to full legibility and the reading light sweeps it once — 02a's grammar, at the offsets the scoring walk recorded.",
        layers: [{ subject: "mail", left: 16, top: -10, scale: 1.08, lit: true }],
      },
      {
        from: 4.4,
        to: 6.6,
        name: "The fold",
        what: "The mail compresses toward row proportions as the board comes into frame; nothing about the row is drawn for the shot.",
        layers: [
          { subject: "mail", left: 4, top: 30, scale: 0.7, opacity: 0.34, blur: 1.5, lit: true },
          { subject: "board", left: 150, top: 36 - ASSESS * 0.82, scale: 0.82, seated: true },
        ],
      },
      {
        from: 6.6,
        to: 9,
        name: "The seat",
        what: "The camera rides the row down into its group and stops as the board absorbs it — the group's count is the board's own.",
        layers: [{ subject: "board", left: 10, top: 44 - ASSESS * 0.92, scale: 0.92, seated: true }],
      },
    ],
  },
  {
    id: "ii",
    grammar: "cut",
    title: "The match cut",
    logic:
      "The camera never moves, and it is in the same place at the end as at the start. Board, letter, board — three locked frames, and one line that does not move across any of the splices.",
    understands:
      "That the row IS the letter: the frame opened on a group with nothing in it, cut away to one piece of mail, and came back to find the mail's own name sitting on exactly the mark the subject line had been on. Nothing travelled, and nothing needed to.",
    needs: {
      kind: "dom",
      what: "Choreographed real DOM. Two mounted surfaces and a shared-layout element on the naming line; the lab's stage already namespaces `layoutId` per plate, which is the only trap here. Zero media, no covenant to amend.",
    },
    rail: "The best fit of the four, and not by a little: a cut needs no travel distance, so each subject owns the entire 416x160 in turn instead of sharing it. It is the only option where the mail is read at full width AND the group it lands in is seen whole.",
    frames: [
      {
        from: 0,
        to: 1.6,
        name: "The empty group",
        what: "Locked off on the board, on the stage this mail will land in. The group is empty, and it says so in the product's own words.",
        layers: [{ subject: "board", left: 12, top: 26 - ASSESS, scale: 1, seated: false }],
        match: { y: 52, xs: [26] },
      },
      {
        from: 1.6,
        to: 4,
        name: "Frame A — the letter",
        what: "Cut to the mail, locked. Its subject line starts on the same mark the empty cell just occupied; the camera holds long enough to read it.",
        layers: [{ subject: "mail", left: 12, top: 34, scale: 1 }],
        match: { y: 52, xs: [26] },
      },
      {
        from: 4,
        to: 4.1,
        name: "The cut",
        what: "One splice, drawn here as a split frame: the letter's last frame and the board's first, each on its own left edge, both on the one mark.",
        layers: [
          { subject: "mail", left: 12, top: 34, scale: 1, clip: "left" },
          { subject: "board", left: 220, top: 26 - ASSESS, scale: 1, seated: true, clip: "right" },
        ],
        splice: 208,
        match: { y: 52, xs: [26, 234] },
      },
      {
        from: 4.1,
        to: 6.4,
        name: "Frame B — the board",
        what: "Back to the opening frame, unmoved. Where the empty cell was, and where the subject line was, the row now carries the mail's own name.",
        layers: [{ subject: "board", left: 12, top: 26 - ASSESS, scale: 1, seated: true }],
        match: { y: 52, xs: [26] },
      },
    ],
  },
  {
    id: "iii",
    grammar: "rack",
    title: "One frame, two depths",
    logic:
      "The camera never moves and never cuts. Both subjects are in frame the whole time and the FOCUS travels between them — the only shot of the four where nothing can be swapped off-camera.",
    understands:
      "Cause and effect held together: the letter was never somewhere else while the board changed, because both were on screen the whole time.",
    needs: {
      kind: "dom",
      what: "Choreographed real DOM. Blur, scale and opacity on two mounted surfaces — all compositor work, no media, no covenant to amend.",
    },
    rail: "Survives, but it is the option the rail taxes most: holding both subjects inside 416x160 means neither ever owns the frame, so the mail is read at about 0.85x and the board sits at 0.6x behind it. Legible; not generous.",
    frames: [
      {
        from: 0,
        to: 2,
        name: "Near — the letter",
        what: "The mail sharp in the foreground; the board is already there behind it, soft, with nothing in the group yet.",
        layers: [
          { subject: "board", left: 216, top: 22 - ASSESS * 0.72, scale: 0.72, blur: 2.5, opacity: 0.8 },
          { subject: "mail", left: 4, top: -6, scale: 0.84 },
        ],
      },
      {
        from: 2,
        to: 3.6,
        name: "The verdict holds",
        what: "The reading finishes and the verdict stamps on the mail. The board has not moved; the focus has not moved.",
        layers: [
          { subject: "board", left: 216, top: 22 - ASSESS * 0.72, scale: 0.72, blur: 2.5, opacity: 0.8 },
          { subject: "mail", left: 4, top: -6, scale: 0.84, lit: true, stamped: true },
        ],
      },
      {
        from: 3.6,
        to: 5.2,
        name: "The pull",
        what: "The handover, and the shot's only risky half-second: neither plane is sharp, which is what makes it read as one lens rather than a crossfade. The row seats HERE, in frame, where it can be watched.",
        layers: [
          { subject: "board", left: 178, top: 22 - ASSESS * 0.78, scale: 0.78, blur: 1.2, opacity: 0.92, seated: true },
          { subject: "mail", left: -24, top: 0, scale: 0.8, blur: 1.8, opacity: 0.7, lit: true, stamped: true },
        ],
      },
      {
        from: 5.2,
        to: 7.2,
        name: "Far — the board",
        what: "The board comes sharp with the row in its group; the mail stays in frame, soft, still legible as the thing that caused it.",
        layers: [
          { subject: "mail", left: -74, top: 8, scale: 0.7, blur: 4, opacity: 0.3 },
          { subject: "board", left: 116, top: 22 - ASSESS * 0.86, scale: 0.86, seated: true },
        ],
      },
    ],
  },
  {
    id: "iv",
    grammar: "push",
    title: "Through the sentence",
    logic:
      "The subject is still; the camera travels straight in on axis, through the line that decided, and comes out on the board. One move, no cut.",
    understands:
      "That the row is what is left of the letter after the reading — the same object at a different scale, not a summary written about it.",
    needs: {
      kind: "dom",
      what: "Real DOM is possible — transformed text stays vector-crisp at any scale — but the honest range is the open question: the move is roughly 40x, and DOM has no motion blur to hide the last two seconds of it. Prototype the push at 8x in DOM before deciding whether it needs the take.",
    },
    rail: "Fits, with a caveat that is really an argument for it: an axial push needs no room, only scale, so the letterbox costs it nothing. At 160px tall the waist of the move is where all the risk sits, not the ends.",
    frames: [
      {
        from: 0,
        to: 1.8,
        name: "Wide on the letter",
        what: "The whole mail, still, centred. Nothing moves yet; the camera is choosing where to go.",
        layers: [{ subject: "mail", left: 34, top: 2, scale: 0.8 }],
      },
      {
        from: 1.8,
        to: 3.6,
        name: "Into the line",
        what: "Straight in on the sentence that decided — lit before the camera started moving, which is the whole of what keeps this frame honest.",
        layers: [{ subject: "mail", left: -180, top: -168, scale: 2.2, lit: true }],
      },
      {
        from: 3.6,
        to: 5.4,
        name: "Through",
        what: "The words become shapes and the camera keeps going; the board is already on the far side, small and growing.",
        layers: [
          { subject: "mail", left: -820, top: -520, scale: 6.4, opacity: 0.32, lit: true },
          { subject: "board", left: 172, top: 62, scale: 0.09, opacity: 0.95, seated: true },
        ],
      },
      {
        from: 5.4,
        to: 8,
        name: "Out on the board",
        what: "The push decelerates into the board at rest, the row seated in its group. The shot has never cut.",
        layers: [{ subject: "board", left: 8, top: 40 - ASSESS * 0.9, scale: 0.9, seated: true }],
      },
    ],
  },
];

/* -------------------------------------------------------------------------
 * Rendering
 * ---------------------------------------------------------------------- */

function NeedsChip({ kind }: { kind: "take" | "dom" }) {
  return kind === "take" ? (
    <span className="label-caps inline-flex shrink-0 items-center gap-1.5 rounded-full border border-review/50 px-2.5 py-1 text-review">
      needs a recorded take
    </span>
  ) : (
    <span className="label-caps inline-flex shrink-0 items-center gap-1.5 rounded-full border border-viz-rules/40 px-2.5 py-1 text-viz-rules">
      buildable as real DOM
    </span>
  );
}

/**
 * The doorway into the four, rendered once above 03c-i: the same question,
 * four camera marks, no prose to read first. If two of these glyphs look alike
 * the options are not different enough and the set has failed.
 */
export function OneLetterIndex() {
  return (
    <div className="border-t border-line">
      <div className="mx-auto w-full max-w-5xl px-6 pb-2 pt-12">
        <p className="label-caps">03c · four cameras, one question</p>
        <h3 className="mt-2 max-w-2xl text-xl font-medium tracking-tight text-strong">
          How does a visitor watch one piece of mail become one row?
        </h3>
        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-dim">
          Four answers, and they differ in where the camera is — not in easing or palette. Each
          storyboard below draws the same two subjects from real components, at the exact size the
          landing&apos;s retention rail would give them, so what is illegible here is illegible
          there. All four are unrecorded; two of them never need to be recorded.
        </p>
        <ul className="mt-6 grid gap-x-8 gap-y-6 sm:grid-cols-2 lg:grid-cols-4">
          {OPTIONS.map((o) => (
            <li key={o.id}>
              <a href={`#one-letter-${o.id}`} className="group block">
                <Notation kind={o.id} end={o.frames[o.frames.length - 1]!.to} />
                <p className="mt-2 flex items-baseline gap-2">
                  <span className="font-mono text-sm text-viz-rules">03c-{o.id}</span>
                  <span className="label-caps">{o.grammar}</span>
                </p>
                <p className="mt-0.5 text-sm text-strong group-hover:underline group-hover:underline-offset-4">
                  {o.title}
                </p>
              </a>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export function OneLetter({ option }: { option: OptionId }) {
  const o = OPTIONS.find((entry) => entry.id === option)!;
  // The board rows read the calendar for their age tags. Deferred off the
  // effect body — the house rule every fixture mount in this lab follows.
  const [today, setToday] = useState<string | null>(null);
  useEffect(() => {
    const id = window.setTimeout(() => setToday(todayISO()), 0);
    return () => window.clearTimeout(id);
  }, []);

  // The verdict word on the tracked mail, from the shipped rules layer — never
  // typed here, and never a number. If the rules change, the frames follow.
  const verdict = useMemo(
    () =>
      categoryWord(
        buildTraceView({
          subject: KESTREL.subject,
          body: KESTREL.body,
          senderEmail: KESTREL.sender,
        }).category,
      ),
    [],
  );

  // No id here: the anchor `one-letter-{id}` belongs to the enclosing Plate's
  // <section>, which is what the lab's nav and the index above both link to.
  return (
    <div>
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
        <p className="label-caps">
          camera logic · <span className="text-strong">{o.grammar}</span>
        </p>
        <p className="max-w-xl text-sm leading-relaxed text-muted">{o.logic}</p>
      </div>

      <div className="mt-4 max-w-sm">
        <Notation kind={o.id} end={o.frames[o.frames.length - 1]!.to} />
      </div>

      {/* Frames at the rail's real picture size. Below `lg` they exceed the
          column, so the STRIP scrolls inside itself — the page body never
          does. */}
      <ol className="mt-2 flex snap-x gap-4 overflow-x-auto pb-3 lg:grid lg:grid-cols-2 lg:gap-x-8 lg:gap-y-6 lg:overflow-visible">
        {o.frames.map((spec, i) => (
          <li key={spec.name} className="w-[416px] shrink-0 snap-start lg:w-auto">
            {today ? (
              <Frame spec={spec} today={today} verdict={verdict} />
            ) : (
              <div
                className="rounded-lg border border-line bg-background"
                style={{ width: FRAME_W, height: FRAME_H }}
              />
            )}
            <p className="mt-2 flex items-baseline gap-2">
              <span className="font-mono text-xs text-dim">{i + 1}</span>
              <span className="text-sm font-medium text-strong">{spec.name}</span>
            </p>
            <p className="mt-1 max-w-[416px] text-xs leading-relaxed text-dim">{spec.what}</p>
          </li>
        ))}
      </ol>

      <dl className="mt-6 grid gap-x-8 gap-y-4 border-t border-line-soft pt-5 text-sm sm:grid-cols-3">
        <div>
          <dt className="label-caps">What the visitor ends up knowing</dt>
          <dd className="mt-1.5 leading-relaxed text-dim">{o.understands}</dd>
        </div>
        <div>
          <dt className="label-caps">How it gets made</dt>
          <dd className="mt-1.5 leading-relaxed text-dim">
            <NeedsChip kind={o.needs.kind} />
            <span className="mt-2 block">{o.needs.what}</span>
          </dd>
        </div>
        <div>
          <dt className="label-caps">In the 416 x 160 rail</dt>
          <dd className="mt-1.5 leading-relaxed text-dim">{o.rail}</dd>
        </div>
      </dl>

      <p className="mt-5 max-w-3xl text-xs leading-relaxed text-dim">
        Frames are real components under a crop, held — nothing on this plate animates, and no
        take of this shot exists. Any dashed rule, tick or vertical splice drawn on a frame is
        storyboard notation, not product UI. The mail is the cast&apos;s Kestrel assessment and the
        row is the showcase board&apos;s own assessment row, so the letter and the row are the same
        story the rest of the lab tells.
      </p>
    </div>
  );
}
