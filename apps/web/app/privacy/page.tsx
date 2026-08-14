import type { Metadata } from "next";
import Link from "next/link";

import { Logo } from "@/components/brand/Logo";
import { AppShell } from "@/components/shell/AppShell";
import { getCurrentUser, userDisplayName } from "@/lib/supabase/auth";
import { cn } from "@/lib/utils";

/**
 * Privacy policy — a public document, required for Google's OAuth verification
 * of the restricted `gmail.readonly` scope.
 *
 * The route is dual-mode, the same split `/import` already uses (#147):
 *   - Signed in  → the document renders INSIDE the app shell, so the rail and
 *     the top bar ARE the way back. The page is linked from Settings' Gmail
 *     card and from the inbox, and a signed-in reader who followed one of
 *     those used to land on a page whose only navigation was `href="/"` — the
 *     MARKETING page, which reads as having been signed out (#155).
 *   - Signed out → the standalone public document, header and footer intact.
 *     It has to stay complete and reachable without a session: Google's
 *     reviewer fetches it anonymously, and the landing page links to it.
 *
 * No nav item lights up in shell mode, and that is correct — the policy is not
 * one of the app's four destinations, it is a document the app links to.
 *
 * EVERY SENTENCE ON THIS PAGE IS A DESCRIPTION OF CODE IN THIS REPO. It is not
 * a template, and it must not be edited into one. If a behaviour changes, the
 * sentence changes with it — the sources each claim is read from:
 *
 *   · one scope, `gmail.readonly`          — backend/jobtracker/config.py:176-179,
 *     backend/jobtracker/email_clients/gmail.py:53
 *   · no incremental scope merging          — backend/jobtracker/cloud/gmail_oauth.py:586-599
 *   · sign-in passes no scopes of its own   — components/auth/GoogleSignInButton.tsx:92-99
 *   · Google password never reaches Applied — both flows are redirects to
 *     accounts.google.com (same two sources as the consent-screen and sign-in
 *     claims above; there is no password field for a Google credential
 *     anywhere in this repo). Claim moved here from the Settings Gmail card's
 *     safeguards fold when #201 retired it — the policy is the one place the
 *     product argues its own safety.
 *   · metadata-only fetch, never a body     — backend/jobtracker/cloud/gmail_client.py:17-19,
 *     292-293, 413
 *   · the stored row                        — backend/jobtracker/database/models.py:348-429
 *     (`body_snippet` caps at 500 chars, models.py:398-402); the cloud path
 *     writes no `body_text`/`body_html`/`raw_headers`
 *     (backend/jobtracker/cloud/applications.py:420-422, 2924-2925)
 *   · hosted app is rules-only, no ML stack — backend/jobtracker/classifier/hybrid.py:157,276;
 *     requirements.txt:7-17 (torch/setfit/sentence-transformers excluded);
 *     vercel.json sets JOBTRACKER_DEPLOYMENT=cloud, api/index.py:35
 *   · no pooled training                    — backend/jobtracker/classifier/setfit_model.py:38-66,
 *     620-633; hybrid.py:549-560
 *   · encrypted token row                   — backend/jobtracker/database/models.py:674-740
 *   · disconnect revokes at Google          — backend/jobtracker/cloud/gmail_oauth.py:700-733
 *   · account deletion does NOT revoke      — backend/jobtracker/cloud/account.py:84-85
 *   · the eight purged tables               — backend/jobtracker/cloud/account.py:51-60
 *   · purge is best-effort, 501 when the
 *     service-role key is missing           — app/api/account/delete/route.ts:31-56
 *   · nothing expires                       — no `crons` in either vercel.json
 *   · on-device import never uploads        — components/import/ImportMail.tsx ("use client":
 *     the file is read with File.text() and classified by lib/import/parseMail.ts +
 *     lib/demo/rulesLayer.ts in the tab; no fetch on that path, no storage write —
 *     results are React state only)
 *
 * Apostrophes are the typographic character, never `&apos;`. A JSX text node
 * containing an entity loses its LEADING space in this toolchain — the defect
 * documented in components/settings/GmailConnectionCard.tsx, and it bit this
 * page too: "for message <M>metadata</M> in bounded batches" rendered as
 * "metadatain", because the text node after the code element also carried an
 * `&apos;`. No entity, no lost space.
 *
 * Design: the app's own monochrome system, no new colour values, no motion, no
 * client JavaScript. Prose is Atkinson (the product's voice); mono appears only
 * where the page is quoting a machine value — a scope string, a column name, an
 * endpoint, a table. The hero artifact is the scope string itself, which is the
 * single most important fact a reader (or a Google reviewer) came here for.
 */

export const metadata: Metadata = {
  title: "Privacy",
  description:
    "What Applied reads from your Gmail, what it stores, where it runs, and how to delete it. One scope — gmail.readonly — metadata only, no message bodies, and no third-party model ever sees your mail.",
};

const UPDATED = "14 August 2026";
/**
 * The database measurements in §4 were taken on this date and stay pinned to
 * it — bumping `UPDATED` must never silently re-date a measurement that was
 * not re-run.
 */
const MEASURED = "12 August 2026";
const CONTACT = "aesh.03.23@gmail.com";
const GOOGLE_PERMISSIONS = "https://myaccount.google.com/permissions";
const GOOGLE_USER_DATA_POLICY = "https://developers.google.com/terms/api-services-user-data-policy";

const SECTIONS = [
  { id: "who", title: "Who runs Applied" },
  { id: "permission", title: "The Google permission it asks for" },
  { id: "fetches", title: "What it fetches from Gmail" },
  { id: "stores", title: "What it stores" },
  { id: "runs", title: "Where it runs, and who never sees it" },
  { id: "other", title: "The rest of what it holds" },
  { id: "retention", title: "How long it is kept" },
  { id: "delete", title: "Disconnecting and deleting" },
  { id: "training", title: "Training, and what is forbidden" },
  { id: "on-device", title: "On-device import" },
  { id: "changes", title: "Changes, and how to reach a human" },
] as const;

/** Prose link — underlined on hover, never a bare colour change. */
const LINK =
  "text-strong underline decoration-line-strong underline-offset-4 transition-colors hover:decoration-current";

/** A machine value quoted inside prose: a scope, a column, an endpoint. */
function M({ children }: { children: React.ReactNode }) {
  return <code className="font-mono text-[0.9em] text-strong">{children}</code>;
}

function P({ children }: { children: React.ReactNode }) {
  return <p className="mt-4 text-[1.0625rem] leading-[1.75] text-foreground">{children}</p>;
}

function Section({
  id,
  n,
  title,
  children,
}: {
  id: string;
  n: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-24 border-t border-line-soft pt-10">
      <h2 className="flex items-baseline gap-3 text-[1.375rem] font-medium tracking-tight text-strong">
        {/* The numeral is mono because §7 is a reference, not a word — this is
            a document people cite back at you by number. */}
        <span className="tabular font-mono text-[0.8rem] font-normal text-dim">
          {String(n).padStart(2, "0")}
        </span>
        {title}
      </h2>
      {children}
    </section>
  );
}

/** One row of the stored-record manifest. */
function Field({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-x-6 gap-y-1 px-4 py-3 sm:grid-cols-[13rem_minmax(0,1fr)] sm:px-5">
      <dt className="font-mono text-[0.8125rem] leading-6 text-strong">{name}</dt>
      <dd className="text-[0.9375rem] leading-6 text-muted">{children}</dd>
    </div>
  );
}

/**
 * The policy itself — identical in both modes. Only the CHROME around it
 * differs; the document does not, and the note at the top of this file governs
 * every sentence of it either way.
 *
 * `inShell` buys exactly one thing: where the sticky contents rail parks. A
 * sticky offset is measured against the SCROLLPORT, and the two modes have
 * different ones — the document itself when standalone, where `top-24` clears
 * this page's own 56px sticky header, and the shell's <main> when signed in,
 * which carries no header inside it, so the same 24 would just be a hole.
 */
function PrivacyDocument({ inShell }: { inShell: boolean }) {
  return (
    <>
      {/* ---- the thesis: one scope, printed at size ---------------------- */}
      <div className="border-b border-line-soft py-16 sm:py-20">
        <p className="label-caps">Privacy policy · updated {UPDATED}</p>
        <h1 className="mt-5 max-w-[20ch] text-balance text-4xl font-medium tracking-tight text-strong sm:text-5xl">
          What Applied reads, and what it keeps.
        </h1>

        <div className="mt-10 border-l-2 border-line-strong pl-5 sm:pl-6">
          <p className="label-caps">The only Google permission it asks for</p>
          <p className="mt-3 font-mono leading-tight break-words">
            <span className="block text-[0.8125rem] text-dim sm:text-sm">
              https://www.googleapis.com/auth/
            </span>
            <span className="mt-1 block text-2xl font-semibold tracking-tight text-strong sm:text-[2.25rem]">
              gmail.readonly
            </span>
          </p>
        </div>

        <p className="mt-10 max-w-[65ch] text-[1.0625rem] leading-[1.75] text-foreground">
          Applied is a job-search tracker. It reads your Gmail to work out which of your
          applications moved — applied, interview, assessment, offer, rejection — so you do not
          have to keep the list by hand. This page says exactly what it fetches, what it writes
          down, where that lives, and how to get rid of it. Every statement here describes the code
          running at <M>getapplied.vercel.app</M>, not an intention.
        </p>
      </div>

      <div className="grid gap-x-16 gap-y-12 py-12 lg:grid-cols-[13rem_minmax(0,65ch)]">
        {/* ---- contents --------------------------------------------------- */}
        <nav
          aria-labelledby="contents-heading"
          className={cn("lg:sticky lg:self-start", inShell ? "lg:top-4" : "lg:top-24")}
        >
          <h2 id="contents-heading" className="label-caps">
            Contents
          </h2>
          <ol className="mt-4 space-y-2.5">
            {SECTIONS.map((section, i) => (
              <li key={section.id} className="flex gap-3">
                <span
                  aria-hidden
                  className="tabular mt-[0.2rem] font-mono text-[0.7rem] text-dim"
                >
                  {String(i + 1).padStart(2, "0")}
                </span>
                <a
                  href={`#${section.id}`}
                  className="text-[0.9375rem] leading-6 text-muted transition-colors hover:text-strong"
                >
                  {section.title}
                </a>
              </li>
            ))}
          </ol>
        </nav>

        {/* ---- the document ---------------------------------------------- */}
        <div className="space-y-12">
          <Section id="who" n={1} title="Who runs Applied">
            <P>
              Applied is built and run by Ayush Yadav, one person, as a personal project. It is in
              invite-only beta. There is no company behind it and no staff. Anything you want to
              ask, correct or have deleted goes to{" "}
              <a href={`mailto:${CONTACT}`} className={LINK}>
                {CONTACT}
              </a>
              , and a person reads it.
            </P>
          </Section>

          <Section id="permission" n={2} title="The Google permission it asks for">
            <P>
              To read mail, Applied requests exactly one Google scope:{" "}
              <M>gmail.readonly</M>. That permission lets it read your messages and their labels.
              It cannot send mail, delete mail, modify a message, or change any Gmail setting —
              not because Applied promises to behave, but because the grant does not carry those
              rights.
            </P>
            <P>
              You approve it on Google’s own consent screen — your Google password is typed
              there, on Google’s page, and never reaches Applied — and Google hands Applied a
              token afterwards. Applied does not ask Google to merge in permissions you granted
              elsewhere (<M>include_granted_scopes</M> is deliberately off), so this grant contains
              that one scope and nothing else.
            </P>
            <P>
              Signing in is separate from mail access. If you sign in with Google, that goes
              through Supabase’s Google provider and Applied requests no scopes of its own;
              what comes back is your Google account’s email address, which is how Applied
              knows who you are. You can also sign in with an email address and password instead.
            </P>
            <P>
              You can withdraw mail access at any time — in Settings, or from{" "}
              <a href={GOOGLE_PERMISSIONS} className={LINK} target="_blank" rel="noopener noreferrer">
                Google’s own permissions page
              </a>
              . Section 8 says exactly what each route does.
            </P>
          </Section>

          <Section id="fetches" n={3} title="What it fetches from Gmail">
            <P>
              The hosted app asks Gmail for message <M>metadata</M> in bounded batches: the
              Subject, From and Date headers, plus Gmail’s own <M>snippet</M> — the short
              preview Gmail itself generates. It never requests a message body. There is no code
              path in the hosted app that downloads one.
            </P>
            <P>
              A scan covers a date range you choose. A full rebuild also searches archived mail,
              because a scan that is allowed to remove applications has to be able to see
              everything it is judging.
            </P>
          </Section>

          <Section id="stores" n={4} title="What it stores">
            <P>
              One row per message, in a table called <M>emails</M>. Rather than describe it, here
              is the whole row — including the three columns the schema declares and the hosted app
              never fills.
            </P>

            <div className="mt-6 overflow-hidden rounded-xl border border-line-soft bg-surface">
              <div className="flex items-baseline justify-between gap-4 border-b border-line px-4 py-3 sm:px-5">
                <p className="font-mono text-[0.8125rem] text-strong">emails</p>
                <p className="label-caps">one row per message</p>
              </div>

              <dl className="divide-y divide-line-soft">
                <Field name="user_id">
                  the account that owns the row — every query is filtered by it, and Postgres
                  row-level security enforces the same restriction underneath
                </Field>
                <Field name="source_account">which mailbox it came from</Field>
                <Field name="message_id">Gmail’s identifier for the message</Field>
                <Field name="thread_id">Gmail’s identifier for the conversation</Field>
                <Field name="subject">the subject line, as it was sent</Field>
                <Field name="sender_name · sender_email">who it came from</Field>
                <Field name="received_at">when it arrived</Field>
                <Field name="body_snippet">
                  Gmail’s own preview of the message. The column stops at 500 characters;
                  measured in the production database on {MEASURED}, the snippets held there
                  averaged 193 characters and the longest was 201.
                </Field>
                <Field name="classified_as">
                  the verdict — applied, interview, assessment, offer, rejection, follow-up, other,
                  or “needs review”
                </Field>
                <Field name="classification_confidence">how sure the classifier was, 0 to 1</Field>
                <Field name="classification_method">which layer produced the verdict</Field>
                <Field name="user_corrected · is_reviewed">
                  whether you overrode the verdict, and whether you have looked at it
                </Field>
                <Field name="application_id">the application this message was filed under</Field>
                <Field name="created_at · updated_at">
                  when Applied wrote the row and last touched it
                </Field>
              </dl>

              <div className="border-t border-line px-4 py-3 sm:px-5">
                <p className="label-caps">Declared by the schema · never written</p>
              </div>
              <dl className="divide-y divide-line-soft">
                {[
                  { name: "body_text", what: "the full plain-text body" },
                  { name: "body_html", what: "the full HTML body" },
                  { name: "raw_headers", what: "the raw message headers" },
                ].map((f) => (
                  <div
                    key={f.name}
                    className="grid gap-x-6 gap-y-1 px-4 py-3 sm:grid-cols-[13rem_minmax(0,1fr)] sm:px-5"
                  >
                    <dt className="font-mono text-[0.8125rem] leading-6 text-dim line-through decoration-line-strong">
                      {f.name}
                    </dt>
                    <dd className="text-[0.9375rem] leading-6 text-dim">{f.what}</dd>
                  </div>
                ))}
              </dl>
            </div>

            <p className="mt-3 text-[0.8125rem] leading-relaxed text-dim">
              Those three stay empty because section 3 is true: the hosted app asks for metadata
              and never fetches a body. Checked against the production database on {MEASURED} —{" "}
              <M>body_text</M> was empty on every row in it.
            </p>

            <P>
              So the honest summary is not “Applied stores your emails”. It stores a subject line,
              a sender, a timestamp, Gmail’s own short preview, and what the classifier decided
              about them.
            </P>
          </Section>

          <Section id="runs" n={5} title="Where it runs, and who never sees it">
            <P>
              The web app and the API run on Vercel. Your rows live in a Postgres database hosted
              by Supabase, which also holds your sign-in. Google is where the mail comes from.
              Those services hold the data because they are what the app runs on; it is not sent
              anywhere else.
            </P>
            <P>
              No large language model and no third-party AI service ever sees your mail. In the
              hosted app, classification is the rules layer alone — regular expressions matched
              against the subject and the snippet, in the same function that fetched them. The
              machine-learning stack is not merely unused there, it is not installed: the cloud
              deployment excludes PyTorch, SetFit and sentence-transformers outright. The
              embeddings and the fine-tuned model you can read about elsewhere on this site run in
              your own browser, on your own CPU, or on a developer’s machine — never on your
              mail on a server.
            </P>
            <P>
              Applied’s use of information received from Google APIs adheres to the{" "}
              <a
                href={GOOGLE_USER_DATA_POLICY}
                className={LINK}
                target="_blank"
                rel="noopener noreferrer"
              >
                Google API Services User Data Policy
              </a>
              , including the Limited Use requirements.
            </P>
            <P>
              There is no analytics, no tracking pixel, no advertising and no third-party script on
              any page — the fonts are served from this origin too. Nobody is buying, selling or
              sharing your data, because there is nobody to sell it to.
            </P>
          </Section>

          <Section id="other" n={6} title="The rest of what it holds">
            <P>
              Beyond the mail rows, Applied keeps: your account — an email address, and a password
              that Supabase Auth stores and Applied never sees; your preferences — display name,
              notification and classification settings, kept in your Supabase user record; and the
              applications the tracker builds, whether derived from mail or typed in by you.
            </P>
            <P>
              Your Gmail token is stored encrypted (Fernet) in a table called{" "}
              <M>user_credentials</M>, one row per account. It is never rendered in the browser,
              never written to a log and never put in a URL.
            </P>
            <P>
              Two things stay on your device and are never sent to the server: your light/dark
              choice, under <M>jt-theme</M> in local storage, and the marker the dashboard uses to
              remember which rows you had already looked at.
            </P>
            <P>
              Applied’s own log lines record identifiers and outcomes — a user id, a count,
              whether a sync failed — not the contents of your messages.
            </P>
          </Section>

          <Section id="retention" n={7} title="How long it is kept">
            <P>
              Nothing expires on its own. There is no retention timer and no scheduled job that
              deletes anything — the deployment declares no cron at all. What Applied has written
              down stays until you remove it, by the routes in section 8.
            </P>
            <P>
              One exception works the other way: a rebuild scan can delete applications it had
              previously derived from mail, when the mail no longer supports them. Anything you
              edited or settled yourself is left alone.
            </P>
          </Section>

          <Section id="delete" n={8} title="Disconnecting and deleting">
            <P>
              <strong className="font-medium text-strong">Disconnect Gmail</strong> (Settings →
              Gmail) revokes the grant at Google and deletes the stored token. Applied stops
              reading mail immediately. The messages it has already classified stay in your
              account.
            </P>
            <P>
              <strong className="font-medium text-strong">Delete your account</strong> (Settings →
              Account) asks the API to purge every row you own — from <M>email_embeddings</M>,{" "}
              <M>contacts</M>, <M>interviews</M>, <M>emails</M>, <M>applications</M>,{" "}
              <M>training_data</M>, <M>sync_state</M> and <M>user_credentials</M> — and then
              deletes the sign-in account itself.
            </P>
            <P>
              Two limits, stated because they are true. First, deleting your account does{" "}
              <em>not</em> revoke the Google grant; that is a separate step you take on{" "}
              <a href={GOOGLE_PERMISSIONS} className={LINK} target="_blank" rel="noopener noreferrer">
                Google’s permissions page
              </a>
              . Second, the purge is attempted first but is not allowed to block the deletion: if
              the API cannot be reached, your sign-in account is removed anyway and rows could
              survive it. If you want that confirmed — or if the deployment tells you deletion is
              not enabled — email{" "}
              <a href={`mailto:${CONTACT}`} className={LINK}>
                {CONTACT}
              </a>{" "}
              and it will be done by hand.
            </P>
          </Section>

          <Section id="training" n={9} title="Training, and what is forbidden">
            <P>
              Your mail is never pooled with anyone else’s to train a shared model. Google’s
              Workspace policy permits data from a restricted scope like <M>gmail.readonly</M> to
              train only a model personalised to a single user, with no co-mingling — and the code
              enforces that rather than trusting itself: every training entry point requires a user
              id, the corpus is filtered by it, and the loaded rows are re-checked so that a corpus
              spanning two users raises instead of training.
            </P>
            <P>
              In the hosted app, no model trains at all — there is nothing installed to train one
              with. When you correct a verdict, Applied records the correction as your own example
              (the subject and the same snippet) in <M>training_data</M>. It is yours, it is scoped
              to you, and deleting your account deletes it.
            </P>
          </Section>

          <Section id="on-device" n={10} title="On-device import">
            <P>
              The import page (<M>/import</M>) is the other way to try Applied on your mail, and
              it is the inverse of everything above: nothing reaches a server at all. You hand it
              a mail export — a Google Takeout <M>.mbox</M>, a single <M>.eml</M>, or a JSON
              batch — and the file is read and classified entirely in your browser tab. The page
              makes no network request with your file, and it works signed out, with no Google
              connection.
            </P>
            <P>
              What runs there is the classifier’s fast first pass — deterministic rules, in the
              tab. The machine-learning model does not run on that page. Nothing is written down
              anywhere: the results live in the tab’s memory and are gone when you clear them or
              close the tab.
            </P>
          </Section>

          <Section id="changes" n={11} title="Changes, and how to reach a human">
            <P>
              If this policy changes, the date at the top changes with it, and the reason is a
              change in the code — this page is maintained as a description of the system, not as a
              document that drifts away from it.
            </P>
            <P>
              Everything else — a question, a correction, a deletion, a complaint —{" "}
              <a href={`mailto:${CONTACT}`} className={LINK}>
                {CONTACT}
              </a>
              .
            </P>
          </Section>
        </div>
      </div>
    </>
  );
}

export default async function PrivacyPage() {
  // `getCurrentUser()` rather than a bare `supabase.auth.getUser()` (what
  // /import reaches for): it is the same read, React-`cache()`d, so the shell
  // below shares this verified round-trip instead of paying for a second one.
  const user = await getCurrentUser();

  // --- Signed in: the document inside the app shell -------------------------
  if (user) {
    return (
      <AppShell userEmail={user.email ?? null} userName={userDisplayName(user)}>
        {/* Measure capped, but on the shell's shared left edge (no mx-auto),
            the same as /import. The page brings NO chrome of its own — the
            rail and the top bar are the way back, which is the whole reason
            it renders here. The shell is viewport-locked (`h-dvh`, <main> the
            one scroll pane) and this is a FLOW page: it scrolls inside that
            pane and declares no `page-locked`, so the document still never
            scrolls. */}
        <div className="w-full max-w-5xl pb-16">
          <PrivacyDocument inShell />
        </div>
      </AppShell>
    );
  }

  // --- Signed out: the standalone public document ---------------------------
  return (
    <div className="flex min-h-full flex-col bg-background text-foreground">
      <header className="sticky top-0 z-50 border-b border-line-soft bg-background">
        <div className="mx-auto flex h-14 w-full max-w-5xl items-center justify-between px-6">
          <Link
            href="/"
            aria-label="Applied — home"
            className="brand-logo-link min-h-11 items-center text-strong"
          >
            <Logo className="h-6 w-auto" />
          </Link>
          <a
            href={`mailto:${CONTACT}`}
            className="inline-flex min-h-11 items-center text-sm text-muted transition-colors hover:text-strong"
          >
            Contact
          </a>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl grow px-6 pb-24">
        <PrivacyDocument inShell={false} />
      </main>

      <footer className="border-t border-line-soft">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-2 px-6 py-8 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-[0.8125rem] text-dim">
            Applied · built and run by Ayush Yadav · updated {UPDATED}
          </p>
          <nav className="flex items-center gap-5 text-[0.8125rem] text-dim">
            <Link href="/" className="transition-colors hover:text-strong">
              Home
            </Link>
            <a href={`mailto:${CONTACT}`} className="transition-colors hover:text-strong">
              {CONTACT}
            </a>
          </nav>
        </div>
      </footer>
    </div>
  );
}
