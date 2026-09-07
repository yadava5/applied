import { FeedbackToaster } from "@/components/feedback/Toaster";

/**
 * THE TWIN'S TOASTER (#511).
 *
 * `/demo` sits outside the `(app)` route group, so it never inherited the one
 * instance mounted there, and `(app)/layout.tsx` said so in its own comment:
 * "the /demo twins live outside this group and deliberately have no toaster
 * yet." The consequence was not cosmetic. The twin runs the SAME mutating
 * components as the signed-in board — `ApplicationRow`'s stage select already
 * calls `notifySuccess` — so on `/demo` those calls resolved into nothing at
 * all. A visitor changed a card's stage and the product said nothing back.
 *
 * It also made the feedback system unverifiable. Every emitting surface in the
 * app is session-gated, and there is no local signed-in session, so no toast
 * had ever been OBSERVED rendering — the acceptance evidence for #511 was a
 * source read. With this mount the twin is a real browser check for it.
 *
 * ONE INSTANCE, AT THE GROUP ROOT, for the reason `(app)/layout.tsx` gives:
 * mounted as a sibling of `children` rather than inside a page, so a client
 * navigation between `/demo`, `/demo/scan`, `/demo/inbox` and `/demo/settings`
 * cannot remount it and drop a toast that is still on screen.
 *
 * This adds no emitter. It makes the ones already compiled into these
 * components reach the screen, which is why it changes what a visitor sees
 * without changing what any of them decide.
 */
export default function DemoLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <FeedbackToaster />
      {children}
    </>
  );
}
