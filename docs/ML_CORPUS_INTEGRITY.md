# Training corpus integrity

What `training_data` is allowed to contain, what the production table contains
today, and which of those rows nobody should trust. Written 2026-08-11 alongside
the fix in `backend/jobtracker/cloud/applications.py` and the guard in
`backend/tests/test_training_corpus_integrity.py`.

## The rule

A row in `training_data` is a human saying **"this message is X"**. Only a
per-message decision may write one, which in the cloud app means exactly one
code path: `classify_review_item` (`POST /applications/review/{id}/classify`).

Two whole-row actions used to write them and no longer do:

| Action | What it used to write | Why it was wrong |
| --- | --- | --- |
| `PATCH /applications/{id}` (stage correction) | one example per linked email, labelled from the new **stage**, plus `user_corrected` + `is_reviewed` on every one of those emails | a stage is a fact about an application. `rejected` labelled whatever mail happened to be linked a `rejection`; `withdrawn`/`ghosted` mapped to `other`, i.e. "not job mail", and taught the classifier that a genuine application confirmation was noise. The flags then froze those emails: `_persist_message_refs` never re-classifies a flagged row |
| `POST /applications/{id}/dismiss` | one `other` example per linked email | "this row is not an application" is also a statement about the row. It left the corpus saying `other` while each email's stored `classified_as` still said `applied` — a silent disagreement about the same message. Making them agree would mean flagging the mail, which freezes it, on an action `POST /{id}/restore` can undo |

The invariant now asserted in tests:

1. an example that names an email names one that **exists** — `training_data.email_id`
   is a bare indexed integer, **not** a foreign key, so the database will not
   enforce this and cannot without a migration;
2. where the email exists and is settled, the example's label **is** the email's
   stored `classified_as`. The one tolerated difference is an item still sitting
   in the review queue (`needs_review`, unlinked, un-reviewed) whose label was
   kept because the employer could not be named — an absence of a verdict, not a
   competing one.

## The production rows

The owner's `training_data` held **5 rows** when this was written. Two are known
to be suspect; the state of the other three has not been read, and this document
does not guess at them.

| id | label | email | verdict |
| --- | --- | --- | --- |
| 2 | `rejection` | `emails` id 35, **deleted** | **Poisoned.** Written by a stage correction, not by anyone looking at the message. The message was an assessment invite ("complete your … assessment"), so the corpus teaches an assessment invite as a rejection. Its email row has since been hard-deleted, so the label has no provenance left: only `training_data.subject` / `body_text` survive |
| 4 | `applied` | `emails` id 58, stored `NEEDS_REVIEW` | **Label is legitimate, the mailbox is wrong.** The label came from a real review-queue decision that could not be filed (the `needs_employer` branch). The email was then flagged by a stage correction, which froze it at `needs_review` forever — so the card renders "needs review" for a message that was reviewed and filed |
| 1, 3, 5 | — | — | Unread. Classify them with the two queries below |

Nothing distinguishes a stage-correction row from a review-queue row after the
fact: every row carries `source = 'user_correction'`. Provenance can only be
inferred from the label and the linked email.

Run these read-only against production to sort the remaining rows. Note that the
Postgres enum stores the member **name** (`APPLIED`), while `training_data.label`
stores the **value** (`applied`), hence the `lower()`:

```sql
-- 1. ghosts: an example naming an email that no longer exists
SELECT t.id, t.email_id, t.label, t.created_at
FROM training_data t
LEFT JOIN emails e ON e.id = t.email_id
WHERE t.email_id IS NOT NULL AND e.id IS NULL;

-- 2. contradictions and frozen rows
SELECT t.id, t.email_id, t.label, e.classified_as,
       e.application_id, e.is_reviewed, e.user_corrected
FROM training_data t
JOIN emails e ON e.id = t.email_id
WHERE (e.classified_as <> 'NEEDS_REVIEW'
       AND lower(e.classified_as::text) <> t.label)
   OR (e.classified_as = 'NEEDS_REVIEW'
       AND (e.application_id IS NOT NULL OR e.is_reviewed));
```

## Nothing here was rewritten

**The five rows are untouched.** Deleting or relabelling a user's training data
is the owner's decision, not a code change's, so this branch only stops new bad
rows being written. Stated plainly: **any model trained on the corpus as it
stands inherits row 2**, and every future retrain will, until someone acts. The
corpus is below the SetFit gate today (40 examples, 3 categories, 5 each —
`classifier/setfit_model.py`), so a retrain has not yet consumed it; the rows do
count toward that gate.

Options, in the order they get more destructive:

1. **Do nothing.** Five rows cannot train anything; if the corpus is ever
   discarded and rebuilt from the review queue, the problem evaporates.
2. **Fix row 4's mailbox side** (no corpus change): clear `user_corrected` /
   `is_reviewed` on `emails` id 58 and let the next sync re-classify it, or set
   its `classified_as` to `APPLIED` to match the label the user actually gave.
   This is the one change with no downside — the label is real, only the frozen
   email disagrees with it.
3. **Delete row 2.** It records nobody's judgement about the message. Its email
   is gone, so it cannot be re-derived — but `training_data.subject` still holds
   the text, so it could instead be **relabelled by hand** (`assessment`) after
   reading it.
4. **Delete every row whose email no longer exists.** Blunt: it would also
   discard legitimate review-queue labels whose message was later purged.

## Known consequences of the fix

- A dismissal no longer teaches the classifier anything. That was the only
  signal Applied had for a **confident** false positive (the review queue only
  ever sees verdicts under 0.85). If that signal is wanted back it needs a
  per-message affordance — "this message is not job mail", on the message — not
  a row-level action reinterpreted as one.
- `_orphan_training_examples` sets `email_id = NULL` rather than deleting the
  example when its email is deleted. The label and its text survive; the link
  does not. A review-queue message that a rebuild deletes and re-persists comes
  back with a **new** id, so a later classification of it writes a *second*
  example instead of updating the first (`_add_training_example` is idempotent
  on `email_id` only).
