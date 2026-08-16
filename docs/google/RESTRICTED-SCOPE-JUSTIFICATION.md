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
| `gmail.metadata` | **Restricted** | **Cannot run a Gmail query.** Applied lists messages with `q="in:inbox"` plus a `newer_than:<N>m` age filter (`backend/jobtracker/cloud/gmail_client.py:92`, `:326`, `:613`). Google documents on [`users.messages.list`](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list) that the `q` parameter "cannot be used when accessing the api using the gmail.metadata scope." Without `q`, Applied cannot restrict its read to the inbox or to a recent window — it would have to enumerate *more* of the mailbox, not less. Separately, it returns no message body, which §3 shows is decisive. |
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
  and not a per-user one either.

  The classifier that runs in production is **rules-based**: hand-written regex
  patterns over the category vocabulary, scored and weighted, in
  `backend/jobtracker/classifier/rules.py` — no model weights and nothing
  learned. `HybridClassifier.classify` short-circuits to the rules
  layer on the first line of work when `settings.deployment == "cloud"`
  (`backend/jobtracker/classifier/hybrid.py:284`), which is every hosted
  request, so the embedding and SetFit layers are never constructed and their
  dependencies are excluded from the deployment bundle outright.

  What a user's correction does, precisely: it is written to `training_data` and
  the email is flagged reviewed, so the answer is durable and a later sync will
  not overwrite it. It does **not** change any future classification. There is
  no per-user model and no per-user classifier state of any kind —
  `get_rules_classifier()` (`backend/jobtracker/classifier/rules.py:984`) is a
  process-wide singleton that takes no user argument, so the same message
  classifies identically before and after any correction, for every account.

  The training machinery ships in the repository (it is what the single-user
  desktop build used) and is deliberately named here rather than deleted, so a
  reviewer reading the tree finds it described rather than hidden. No hosted
  path reaches it: no route defines `POST /classify/retrain` — the four routers
  the production app registers are applications, Gmail, account and cron
  (`backend/jobtracker/main_cloud.py:667-684`) — and the retraining entry points
  are refused by default in any case. Training requires the corpus to be either
  wholly synthetic or owned by a user on an explicit allowlist that is **empty
  by default and set by nothing in the hosted deployment**, so production
  refuses every user, including the operator
  (`backend/jobtracker/classifier/setfit_model.py:38-75`). Corrections are
  therefore never pooled across accounts, and no model — shared, generalized or
  personalized — is trained on user data.
- **No permanent copies.** The policy's Terms of Service note prohibits
  *"scraping, building databases … or otherwise creating permanent copies of
  Google User data."* Applied does not archive mail. The message body is never
  written at all. What is stored is a working copy — the message identifiers,
  the headers, and Gmail's own snippet — retained only to render the user's own
  board, and removable by the user at any time.
- **Deletion.** A user can delete their account from within the application.
  Doing so revokes the Gmail grant at Google **first**, then purges every row
  the user owns across all nine user-bearing tables. Deleting a single
  application removes its messages with it.

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
5. **Server-side narrowing before any message is transferred.** Applied asks
   Google for `in:inbox` plus a `newer_than:<N>m` age filter
   (`gmail_client.py:92`, `:326`), so archived, sent and older mail is never
   returned to us at all. This is the minimisation that `gmail.metadata` would
   make impossible (§3.2).
6. **Encrypted tokens.** The OAuth refresh token is Fernet-encrypted at rest
   (AES-128-CBC + HMAC-SHA256) in a row protected by forced row-level security,
   accessed by a database role that cannot bypass it.
7. **Per-user isolation in the database**, not only in application code: 35
   row-level-security policies across 9 tables, `FORCE`d, with the application
   connecting as a `NOBYPASSRLS` role.

---

## 7. Supporting evidence for a reviewer

| Claim | Where to check |
| --- | --- |
| Single scope, read-only | `backend/jobtracker/email_clients/gmail.py:53` |
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
  in the deployed import graph** — `backend/tests/test_main_cloud.py` enforces
  that as an import-hygiene test, because pulling those modules in would break
  the serverless deploy outright.
- **`training_data.body_text` is populated, and it does not hold a body.** It
  holds a copy of Gmail's snippet. The longest value across every row is 201
  characters. `test_body_is_never_persisted.py:714` pins it to the snippet by
  equality and rejects a full-body sentinel.

---

*Prepared 2026-08-15. Production figures were read on that date; the code
citations are against `main`.*
