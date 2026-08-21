# Restricted scope justification — `gmail.readonly`

Prepared for Google's OAuth API verification / restricted-scope review.

§§2–6 are written to be pasted into the verification form. §7 onward is
supporting evidence for a reviewer who wants to check the claims against the
code.

---

## 1. The scope requested

**One** restricted scope, and no other Gmail scope:

```
https://www.googleapis.com/auth/gmail.readonly
```

Applied requests no write, send, modify, compose, settings or label scope. It
cannot send mail, delete mail, alter labels or change any mailbox setting, and
no code path exists that would.

---

## 2. What the application does

Applied tracks a person's job applications by reading their mailbox and
recognising which messages are application-related — a confirmation, an
interview invitation, an assessment request, a rejection — and filing each onto
a board with the employer, the role and the current stage.

The user's problem is that this information arrives as email and stays there.
Nobody reliably updates a spreadsheet after being rejected. The application's
whole value is that the mailbox is the source of truth and the user does not
have to transcribe it.

---

## 3. Why a narrower scope will not work

**Because the decision is in the body of the message, and Applied measured
exactly how often it is.**

Applied originally ran on `format="metadata"` — Subject, From, Date, and
Gmail's own `snippet`, roughly 200 characters. That is the narrowest
possible reading of a message that still identifies it. It was not adequate,
and the failure is recorded in the source at
`backend/jobtracker/cloud/gmail_client.py:27-34`:

> Measured on the owner's 52 stored messages: the snippet averages 186
> characters, an ATS rejection spends that budget on its polite preamble, and
> the sentence carrying the decision falls off the end. **Of four real
> rejections, one was decidable from the snippet and three were not** — one of
> them has no snippet at all. The classifier had never once filed a rejection
> without a human.

The mechanism is specific to how applicant tracking systems write. A rejection
opens with gratitude and closes with the decision:

> *"Thank you for your interest in [Company] and for taking the time to apply
> for the [Role] position. We truly appreciate the effort you put into your
> application and enjoyed learning about your background…"*

That is already the entire snippet. The sentence that makes it a rejection —
*"we have decided to move forward with other candidates"* — is in the next
paragraph, outside anything a metadata-only read returns.

The consequence is not that classification gets *worse* without the body. It
is that an entire category becomes **undetectable**. In the whole period Applied
ran on metadata, it never once auto-detected a rejection — every rejection in
production had to be corrected by a human (§3.1 shows the reversal). A job
tracker that cannot tell a user they were rejected does not do the one thing it
exists to do.

This is verified by a test, not just asserted. `test_the_fetched_body_is_what_makes_the_verdict_right`
(`backend/tests/test_body_is_never_persisted.py:335-354`) takes one real
Greenhouse rejection and classifies it twice:

| Input | Verdict |
| --- | --- |
| Gmail snippet only | `APPLIED` — **wrong** |
| Message body | `REJECTION` — correct |

### 3.1 The before-and-after, in production data

The body-reading change is commit `b6e986e`, "read the message body to
classify, and never keep it", authored **2026-08-15 01:47 UTC**. Production's
`emails` table straddles it:

```sql
SELECT classified_as, user_corrected, classification_method,
       to_char(created_at,'YYYY-MM-DD HH24:MI:SS') AS created_utc,
       round(classification_confidence::numeric,3) AS conf
FROM emails WHERE classified_as = 'REJECTION' ORDER BY created_at;
```

| Created (UTC) | `user_corrected` | Method | Confidence |
| --- | --- | --- | --- |
| 2026-08-13 04:22:57 | **true** | `user` | — |
| 2026-08-13 16:50:06 | **true** | `user` | — |
| 2026-08-13 17:41:31 | **true** | `user` | — |
| 2026-08-14 19:56:25 | **true** | `user` | — |
| — *commit `b6e986e`, 2026-08-15 01:47 UTC* — | | | |
| 2026-08-15 05:58:07 | false | `rules` | 0.900 |
| 2026-08-15 05:58:08 | false | `rules` | 0.950 |

Every rejection recorded **before** the change was filed by a human correcting
the classifier. Both recorded **after** it — about four hours later — were
filed by the classifier itself, at 0.90 and 0.95 confidence. The scope is what
changed; the rules did not.

*Stated honestly, three limits:* this is `N = 6` over three days on a two-user
deployment. The boundary is the **commit** timestamp; the deploy followed the
push to `main` and is not separately recorded here, so the four-hour gap is the
margin rather than a measured interval. And it is a clean before-and-after on
the only production data that exists, not a statistically powered study. It is
offered as exactly that.

### 3.2 Narrower Gmail scopes, considered and rejected

**`gmail.metadata` is itself a Restricted scope** — Google classifies it in the
same tier as `gmail.readonly` ([Choose Gmail API scopes](https://developers.google.com/workspace/gmail/api/auth/scopes)).
Moving to it would not reduce the review burden, the CASA requirement, or the
Limited Use obligations. It would only reduce what the product can do. It is
nonetheless the narrower scope, so it was evaluated on capability:

| Scope | Google's tier | Why it does not work |
| --- | --- | --- |
| `gmail.metadata` | **Restricted** | **Cannot run a Gmail query.** Applied lists messages with a `q` it builds itself — by default `in:inbox` plus a `newer_than:<N>m` age filter (`backend/jobtracker/cloud/gmail_client.py:92`, `:325-343`), passed to `users.messages.list` at `:629`. Google documents on [`users.messages.list`](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list) that the `q` parameter "cannot be used when accessing the api using the gmail.metadata scope." Without `q`, Applied cannot restrict its read to the inbox or to a recent window — it would have to enumerate *more* of the mailbox, not less. Separately, it returns no message body, which §3 shows is decisive. |
| `gmail.addons.current.message.metadata` | Sensitive | Grants access only to the message a Google Workspace Add-on is currently open on. Applied is a standalone web application whose sync runs on a schedule with no user present and no add-on surface. |
| `gmail.addons.current.message.readonly` | Sensitive | Same architectural limitation. |
| `gmail.labels` | Non-sensitive | Labels only — no message content of any kind. |

The `q` restriction is worth emphasising because it inverts the usual
expectation: **the narrower scope would force Applied to read more of the
mailbox, not less.** `gmail.readonly` is what lets it ask Google for the inbox
only, and only recently, before any message is transferred.

There is no Gmail scope between "metadata only" and `gmail.readonly`.
`gmail.readonly` is therefore the narrowest scope that permits the product to
function, and Applied uses the read half of it only.

---

## 4. What Applied does with the data

| Data | Read | Stored |
| --- | --- | --- |
| Subject, From, Date | ✔ | ✔ |
| Gmail's own `snippet` | ✔ | ✔ |
| **Message body** | ✔ — in memory, for classification | ✘ **never** |
| Attachments | ✘ | ✘ |

**The message body is read in flight and never retained.** It is passed to the
classifier and falls out of scope when the request ends. This is a structural
property of the code, not a policy promise:

- `CloudGmailMessage`, the object every persistence path receives, **has no
  body field**. Bodies travel separately, in a `dict[message_id, str]` that
  never reaches the database layer.
- `backend/tests/test_body_is_never_persisted.py` drives a real scan whose
  message bodies carry a sentinel string, then asserts that the sentinel
  reaches no column of any table in the schema, no log record, and no response
  of any endpoint the scan touches.

Classification runs entirely within Applied's own backend — message content is
never sent to a third-party API, a hosted LLM, or any service other than
Applied's own.

*On snippet length:* Google documents `snippet` only as "A short part of the
message text" and publishes no character limit. The ~200-character figure used
throughout this document is **observed** on Applied's own production data
(longest stored value: 201 characters across 54 messages, read 2026-08-15), not
a Google guarantee.

---

## 5. Limited Use compliance

Assessed against the [Google Workspace API User Data and Developer
Policy](https://developers.google.com/workspace/workspace-api-user-data-developer-policy),
which is the governing policy for a Gmail application, quoting its own
language.

**Appropriate use case.** Applied falls under the policy's fourth listed
permitted Gmail restricted-scope use case: *"Applications that use information
from emails to provide reporting or monitoring services for the benefit of
users that improve the email experience (such as applications that automate
travel itineraries or track flights or package delivery statuses)."* Applied
tracks job applications from the mail that reports them. The board is the
prominent, user-facing feature the data serves; there is no other use.

- **No transfer.** Gmail data is never sold, rented or transferred to anyone.
  There are no advertising, analytics or data-broker integrations, and no third
  party receives message content. Message content is not sent to any external
  API, including any hosted language model. The application-level claim is
  backed by a platform-level setting: the Supabase organisation's **Supabase
  Assistant Opt-in Level is set to `Disabled`** — confirmed in the dashboard on
  2026-08-15 — so no database schema, logs or data are shared with third-party
  AI providers by the database platform either. The "no AI touches user mail"
  claim therefore holds at both layers, not only in Applied's own code.
- **No human reads mail.** No employee, contractor or operator reads user
  messages. There are no contractors; the project has one operator, who has no
  route to another user's message content — see the tenant-isolation evidence
  linked in §7.
- **No model training on user data at all.** The policy prohibits *"using user
  data to create, train, or improve a machine learning or artificial
  intelligence model beyond that specific user's personalized model for the
  appropriate use case or user-facing feature."* Applied does not reach that
  limit, because the hosted deployment trains **nothing** — not a pooled model,
  and not a per-user one either. A user's correction is recorded against that
  user's own account; corrections are never pooled across accounts, and no
  shared or generalized model is trained on user data. There is nothing
  installed to train one with, and no retrain runs in production.

  The classifier that runs in production is **rules-based**: hand-written regex
  patterns over the category vocabulary, scored and weighted, in
  `backend/jobtracker/classifier/rules.py` — no model weights and nothing
  learned. When `settings.deployment == "cloud"` — which is every hosted
  request — the classifier is built in lite mode and **the embedding and SetFit
  layers are never constructed at all**
  (`backend/jobtracker/classifier/hybrid.py:199-200`); `classify` then returns
  the rules verdict rather than escalating past it (`:326`). Construction is
  the load-bearing half: a layer that is never built cannot run, whatever any
  later branch does. Their
  dependencies — torch, sentence-transformers, setfit — are absent from the
  deployment's dependency set (`requirements.txt`, which documents the
  exclusion explicitly), which is what "nothing installed to train one with"
  means concretely.

  What a user's correction does, precisely: it is written to `training_data`
  and the email is flagged reviewed, so the answer is durable and a later sync
  will not overwrite it. It does **not** change any future classification.
  There is no per-user model and no per-user classifier state of any kind —
  `get_rules_classifier()` (`backend/jobtracker/classifier/rules.py:984`) is a
  process-wide singleton that takes no user argument, so the same message
  classifies identically before and after any correction, for every account.

  The training machinery ships in the repository (it is what the single-user
  desktop build described below used) and is deliberately named here rather
  than deleted, so a reviewer reading the tree finds it described rather than
  hidden. No hosted path reaches it: no route defines `POST /classify/retrain`
  — the four routers the production app registers are applications, Gmail,
  account and cron (`backend/jobtracker/main_cloud.py:667-684`) — and the
  retraining entry points are refused by default in any case. Training requires
  the corpus to be either wholly synthetic or owned by a user on an explicit
  allowlist that is **empty by default and set by nothing in the hosted
  deployment**, so production refuses every user, including the operator
  (`backend/jobtracker/classifier/setfit_model.py:38-75`).

  **An earlier checkpoint, disclosed for completeness — and it contains no
  Gmail data.** Before Applied was a hosted application it was a single-user
  macOS program over local SQLite, and at that stage it fine-tuned a SetFit
  classifier offline on 2026-03-06. Its `training_metadata.json` records 39 of
  192 training examples as user corrections. **Those corrections came from an
  iCloud IMAP mailbox, not from the Gmail API**, and the desktop store that
  produced them still exists and can be checked:

  | Check | Result |
  | --- | --- |
  | `SELECT source_account, COUNT(*) FROM emails GROUP BY 1` | `ICLOUD` — 856 rows, one value |
  | `thread_id` populated (a Gmail-only column) | 0 of 856 |
  | `sync_state` | one row: `icloud`, `aesh_1055@icloud.com`, `gmail_history_id` NULL |
  | `user_corrected` messages | 81, all `ICLOUD` |

  A Gmail client shipped in that build and the interface exposed it, but it was
  never authenticated or run on that machine. **No Google user data has ever
  entered a training corpus for this project**, and the Workspace API user-data
  policy did not govern that checkpoint. It is recorded here because a reviewer
  reading the repository's history will find a published model trained on mail,
  and should have the provenance rather than have to infer it.

  The checkpoint was nonetheless withdrawn on **2026-08-15** — published weights
  trained on anyone's real mailbox are a poor practice regardless of which
  provider it came from. The artifacts were deleted from the source tree,
  blocked from returning, and both Hugging Face surfaces were made private;
  the weights remain reachable through the public repository's git history, and
  the model repository had been downloaded 13 times before it was closed.
  Training is now default-deny in code — refused unless the corpus is entirely
  synthetic or its single owner is explicitly allowlisted. Full provenance,
  including which of two same-day checkpoints was the published one, is in
  `docs/ML_PROMOTION_POLICY.md`.
- **No permanent copies.** The policy's Terms of Service note prohibits
  *"scraping, building databases … or otherwise creating permanent copies of
  Google User data."* Applied does not archive mail. The message body is never
  written at all. What is stored is a working copy — the message identifiers,
  the headers, and Gmail's own snippet — retained only to render the user's own
  board, and removable by the user at any time.
- **Deletion.** A user can delete their account from within the application.
  Doing so revokes the Gmail grant at Google **first**, then purges every row
  the user owns across all nine user-bearing tables.

  Deleting a single application removes its messages with it, with one
  exception worth naming: a `training_data` row the user created by correcting
  a verdict survives the application's deletion and is unlinked rather than
  removed (`backend/tests/test_application_delete_children.py`,
  `test_delete_keeps_the_training_example_but_unlinks_it`). What it holds is a
  copy of Gmail's snippet and the user's own label, never a body. **Account**
  deletion purges it along with everything else, so this is a difference
  between deleting one application and deleting the account, not a row that
  outlives the user.

---

## 6. Minimisation measures actually implemented

1. **One scope, read-only.** No write capability of any kind.
2. **The body is never stored** (§4), enforced by a test that fails if it ever is.
3. **Bodies are truncated at 4,000 characters** before the classifier sees them
   (`gmail_client.py:163`), so even the in-memory copy is bounded.
4. **Only Gmail's own snippet is retained**, never a slice of the body that was
   just read — a separate assertion checks that the stored snippet *equals*
   Gmail's, because a sentinel search alone would pass for a body prefix that
   stops short of the sentinel.
5. **Server-side narrowing before any message is transferred.** Applied builds
   a Gmail `q` rather than enumerating the mailbox
   (`gmail_client.py:340-343`), and the default read is `in:inbox` plus a
   `newer_than:<N>m` age filter, so ordinary syncs never see archived or sent
   mail, or mail older than the window. This is the minimisation that
   `gmail.metadata` would make impossible (§3.2).

   Two exceptions, stated because they are real and a reviewer will find them
   in the code:

   - **A user-initiated rebuild searches `in:anywhere`**, which includes
     archived and sent mail. The caller does not get a say: `gmail_oauth.py:1969`
     forces it. A rebuild is a *destructive* scan — it can delete application
     rows whose mail no longer matches — and one that reads only `in:inbox`
     judges on a partial mailbox. On 2026-08-10 exactly that removed two
     applications whose confirmations had been archived. The wider read is the
     safeguard, not an oversight.
   - **`range` is not a closed set.** `_parse_range_months` accepts 3, 6, 9 and
     12; any other value, including `all` and an unrecognised one, yields no
     age bound at all, and `build_gmail_query` then emits the base query alone.
     The hosted UI only ever sends an allowed window, but the API accepts more
     than the UI sends.

   Neither exception widens the *scope*: `gmail.readonly` is what is granted
   either way, the body is still discarded after classification (§4), and
   nothing under `in:anywhere` is stored that would not be stored under
   `in:inbox`. What they change is how much of the mailbox is READ, which is
   the claim this section makes, so they belong here rather than in a footnote.
6. **Encrypted tokens.** The OAuth refresh token is Fernet-encrypted at rest
   (AES-128-CBC + HMAC-SHA256) in a row protected by forced row-level security,
   accessed by a database role that cannot bypass it.
7. **Per-user isolation in the database**, not only in application code: 35
   row-level-security policies across 9 tables, `FORCE`d, with the application
   connecting as a `NOBYPASSRLS` role. Every policy carrying user data
   predicates on `user_id = auth.uid()`, so a query for another tenant's rows
   matches nothing regardless of what the application code asks for.

   One table is deliberately not per-user, and stating it is cheaper than a
   reviewer finding it: `gmail_sync_enrollment` carries a `SELECT` policy of
   `USING (true)` for the runtime role. It holds a user id and an enrolment
   timestamp and nothing else — no token, no address, no `kind`. The scheduled
   sync carries no JWT, so `auth.uid()` is NULL for it and a per-user predicate
   would match no rows; publishing the membership fact in a table with no secret
   in it is what avoids granting the cron a path to `user_credentials`, where the
   refresh tokens live. Writes to it remain owner-scoped.

---

## 7. Supporting evidence for a reviewer

| Claim | Where to check |
| --- | --- |
| Single scope, read-only | `backend/jobtracker/config.py:292-295`, requested at `backend/jobtracker/cloud/gmail_oauth.py:651` |
| The metadata measurement | `backend/jobtracker/cloud/gmail_client.py:27-34` |
| Snippet gets a rejection wrong; body gets it right | `backend/tests/test_body_is_never_persisted.py:335-354` |
| Body is never persisted | `backend/tests/test_body_is_never_persisted.py` (whole file) |
| Stored snippet equals Gmail's own | `backend/tests/test_body_is_never_persisted.py:714` |
| Body truncation | `backend/jobtracker/cloud/gmail_client.py:163` |
| The hosted classifier is rules-only (the short-circuit itself) | `backend/jobtracker/classifier/hybrid.py:284` |
| No per-user classifier state — a process-wide singleton, no user argument | `backend/jobtracker/classifier/rules.py:984` |
| Training is default-deny: allowlist empty, nothing in the deployment sets it | `backend/jobtracker/classifier/setfit_model.py:38-75` |
| A training corpus spanning two users raises rather than trains | `backend/tests/test_training_is_single_user.py` |
| One user's corpus still refuses unless that user is allowlisted | `backend/tests/test_training_is_owner_only.py` |
| No `POST /classify/retrain` route exists — the four routers the app registers | `backend/jobtracker/main_cloud.py:667-684` |
| Account deletion revokes at Google, then purges | `backend/jobtracker/cloud/account.py` |
| Encryption, key management | [`../casa/CRYPTOGRAPHY.md`](../casa/CRYPTOGRAPHY.md) |
| Architecture, data flow, tenant isolation | [`../casa/ARCHITECTURE-AND-TENANT-ISOLATION.md`](../casa/ARCHITECTURE-AND-TENANT-ISOLATION.md) |

### A note on the schema, for a reviewer who reads it directly

Two columns are named in a way that invites a wrong conclusion, so they are
disclosed here rather than discovered:

- **`emails.body_text` and `emails.body_html` exist and are populated on 0 of
  54 production rows.** They are legacy columns from the desktop application
  that preceded this one and was de-scoped in August 2026. The only code that
  writes them lives under `backend/jobtracker/email_clients/`, which is **not
  in the deployed import graph**: nothing under `backend/jobtracker/` imports
  that package except the package itself, so no hosted request can reach the
  code that writes those columns.

  That is enforced rather than asserted, by
  `test_cloud_app_does_not_import_the_desktop_email_clients`
  (`backend/tests/test_main_cloud.py`). It imports the deployed app in a clean
  subprocess and fails if any `jobtracker.email_clients` module has entered
  `sys.modules`. The test then imports that package **on purpose** and requires
  the same expression to find it — so a rename, a typo or a package that cannot
  be imported at all fails the test rather than passing it, which is the way a
  check of this shape usually rots.

  Recorded because the correction matters: an earlier revision of this document
  claimed that test already existed. It did not — the file guarded `keyring`,
  `aiosqlite`, `torch`, `setfit` and two classifier submodules, and said nothing
  about `email_clients`. The claim was written before the gate. The gate exists
  now, and the sentence above is true as written.
- **`training_data.body_text` is populated, and it does not hold a body.** It
  holds a copy of Gmail's snippet. The longest value across every row is 201
  characters. `test_body_is_never_persisted.py:714` pins it to the snippet by
  equality and rejects a full-body sentinel.

---

*Prepared 2026-08-15. Production figures were read on that date; the code
citations are against `main`.*
