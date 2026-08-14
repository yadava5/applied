<p align="center">
  <img src="docs/branding/readme-light.svg#gh-light-mode-only" width="800" alt="Applied — your job search, tracked automatically">
  <img src="docs/branding/readme-dark.svg#gh-dark-mode-only" width="800" alt="Applied — your job search, tracked automatically">
</p>

<h1 align="center">Applied</h1>

<p align="center">
  <strong>A job-application tracker driven by your inbox — it classifies every message through a three-layer cascade that escalates only when the cheap layer cannot decide, and builds the pipeline for you.</strong>
</p>

<p align="center">
  <a href="https://getapplied.vercel.app"><strong>Live App</strong></a> ·
  <a href="https://getapplied.vercel.app/system-card"><strong>System Card</strong></a> ·
  <a href="https://getapplied.vercel.app/demo"><strong>Fixture Demo</strong></a> ·
  <a href="https://huggingface.co/spaces/yadava5/jobtracker-classifier"><strong>Classifier Space</strong></a> ·
  <a href="#features">Features</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#testing">Testing</a> ·
  <a href="#getting-started">Getting Started</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/tests-700%20collected%20%C2%B7%200%20skipped-brightgreen" alt="Tests">
  <img src="https://img.shields.io/badge/rules%20macro--F1-0.9791%20(CI%20floor%200.95)-2b9348" alt="Rules macro-F1">
  <img src="https://img.shields.io/badge/Next.js-16.2-000000?logo=nextdotjs&logoColor=white" alt="Next.js">
  <img src="https://img.shields.io/badge/React-19.2-61dafb?logo=react&logoColor=black" alt="React">
  <img src="https://img.shields.io/badge/Python-3.11-3776ab?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Postgres-RLS%20forced-336791?logo=postgresql&logoColor=white" alt="Postgres RLS">
  <img src="https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-blue" alt="License">
</p>

<p align="center">
  Applied is one of six projects presented together at
  <a href="https://yadava5.github.io/Portfolio-2.0/">yadava5.github.io/Portfolio-2.0</a>.
</p>

---

## Overview

Job hunting generates a flood of email — confirmations, rejections, interview invites, take-home assessments, recruiter follow-ups — and keeping a spreadsheet in sync with it by hand is tedious and wrong within a week. Applied connects to Gmail or iCloud, classifies each message into a job-search category, links related messages into a single tracked application, and shows where every opportunity actually stands. Predictions below a 0.85 confidence gate go to a human review queue instead of being silently accepted, and each correction is written back as training data.

It is a monorepo with two deployment modes over one Python package. On the desktop it is a SwiftUI macOS app driving a local FastAPI process with the full three-layer classifier; in the cloud it is a Next.js 16 app on Vercel over Supabase Postgres, where the classifier runs its rules layer only. Both modes import `backend/jobtracker/`; the divergence is deliberate and is described under [Architecture](#architecture).

> **A note on names.** The product was renamed from JobTracker to Applied. The internal identifiers were not renamed with it, and this README prints them verbatim wherever it gives a path or a command: the Python package is `backend/jobtracker/`, the Xcode project is `JobTracker.xcodeproj`, the macOS app stores its database under `~/Library/Application Support/JobTracker/`, and every environment variable is prefixed `JOBTRACKER_` (`config.py`, `env_prefix="JOBTRACKER_"`). Renaming them would be a migration with no user-visible benefit, so they stayed.

### Why it's interesting

- **A metric that names its stage.** The **rules layer** — 212 regex patterns, no model — scores **0.9791 macro-F1** on the 96-example v3 evaluation set, committed at `backend/data/evaluation/baseline_rules_v3.json`. `backend-ci.yml` fails any merge that drops below a **0.95** floor. That number belongs to the rules layer and not to the full cascade; the difference, and why the filenames mislead, is spelled out in [Classifier evaluation](#classifier-evaluation).
- **Cost measured per layer, not averaged.** SetFit costs roughly **100×** the rules layer at p50 — 17.649 ms against 0.176 ms — and the rules layer answers 174 of the 288 classifications in the benchmark run. That is the cascade justifying itself as a measurement rather than an assertion. See [Performance](#performance).
- **Tenant isolation enforced by Postgres, live in production.** Eight tenant tables carry `ENABLE` + `FORCE ROW LEVEL SECURITY` with four policies each — **32 policies** — and production connects as `jobtracker_app`, a `NOSUPERUSER NOBYPASSRLS` role. Twelve tests drive the real connection machinery against a real Postgres, and CI fails the build if they *skip*.
- **The trained model exports to something a browser can run.** The SetFit head quantizes from 90,362,391 bytes of float32 to a **22,843,695-byte int8 ONNX** file (`ml/browser/artifacts/`). Transformers.js executes it on the CPU in the Hugging Face Space with `allowRemoteModels = false`. Which surfaces actually run it, and which do not, is stated in [Implemented vs delegated vs planned](#implemented-vs-delegated-vs-planned).
- **A README that was wrong on the record.** The coverage paragraph below documents its own correction from 54% to 53.2% and the Python-version artifact that caused it. Commit `5b895d8` carries the full derivation.

---

## Features

- **Inbox sync** — Gmail (OAuth, `gmail.readonly` scope only) or iCloud (IMAP); incremental or full sync, with live status over WebSocket on the desktop and polling in the cloud
- **Automatic classification** into the nine `EmailCategory` enum values — `applied`, `pending_application`, `interview`, `rejection`, `offer`, `assessment`, `follow_up`, `other`, plus `needs_review` for anything under the gate. Eight of the nine are predicted labels; `needs_review` is the routing outcome.
- **Application linking** — related messages are grouped into one tracked application and relinked when new signals arrive
- **Human-in-the-loop review** — anything below `CONFIDENCE_AUTO = 0.85` (`classifier/hybrid.py`) lands in a review queue; corrections persist to `training_data` and feed the next retrain
- **Pipeline views** — Feature Cards, Compact Rows, or a Status Board, filterable by unreviewed and unlinked
- **Fixture demo** — the full UI on synthetic data at [`/demo`](https://getapplied.vercel.app/demo), no login. Layer 1 recomputes **live in the browser** there via `apps/web/lib/demo/rulesLayer.ts`, a port of the same 212 patterns; layers 2 and 3 are precomputed, because the app's CSP forbids the WASM eval and CDN fetch Transformers.js needs.
- **Weekly ML operations** — candidate mining for sparse labels, drift and confidence monitoring, and an alert-issue path, all scripted (`scripts/weekly_labeling_cycle.sh`, `scripts/monitoring_cycle.sh`)

### The three-layer cascade

Each layer is cheaper and more explainable than the next, so the expensive one only runs on what the cheap ones could not settle.

```mermaid
flowchart TB
    In["Email — subject · body · sender"] --> CF

    CF{{"0 · content filter<br/>newsletter / promo / security guards"}}
    CF -->|"matched"| Out1["category · method=content_filter"]
    CF -->|"pass"| R

    R{{"1 · rules<br/>212 regex patterns over 7 categories<br/>115 strong · 27 weak · 70 negative<br/>hand-written · classifier/rules.py"}}
    R -->|"scores a category"| Out2["category · method=rules"]
    R -->|"nothing scored"| CLOUD

    CLOUD{"deployment == cloud ?"}
    CLOUD -->|"yes"| Out3["other · confidence 0.0 · method=rules<br/>cloud never escalates"]
    CLOUD -->|"no"| E

    E{{"2 · embeddings<br/>intfloat/e5-small-v2 · PRETRAINED, not trained here<br/>cosine similarity vs stored examples<br/>accepts at ≥ 0.85"}}
    E -->|"≥ 0.85"| Out4["category · method=embeddings"]
    E -->|"below"| S

    S{{"3 · SetFit<br/>the ONE model fine-tuned in this repo<br/>body: sentence-transformers/paraphrase-MiniLM-L6-v2<br/>8 labels · accepts at ≥ 0.70"}}
    S -->|"≥ 0.70"| Out5["category · method=setfit"]
    S -->|"below"| F["4 · fallback<br/>best available signal · method=fallback"]

    Out2 --> G
    Out4 --> G
    Out5 --> G
    F --> G
    G{"confidence ≥ 0.85 ?"}
    G -->|"yes"| Auto["auto-classified"]
    G -->|"no"| Review["needs_review queue<br/>correction → training_data"]
```

Thresholds are `CONFIDENCE_AUTO = 0.85` and `CONFIDENCE_MIN_CLASSIFICATION = 0.70`, both defined in `backend/jobtracker/classifier/hybrid.py`. The 212 patterns are counted at their definition site — the `PATTERNS` dict in `classifier/rules.py` — not at any call site.

---

## Architecture

### Two deployment modes, one package

`JOBTRACKER_DEPLOYMENT` selects the mode. The table in `docs/WEB_ARCHITECTURE.md` is the source for this diagram.

```mermaid
flowchart TB
    subgraph Desktop["desktop mode — JOBTRACKER_DEPLOYMENT=desktop (default)"]
        direction TB
        Swift["SwiftUI app<br/>apps/macos/…/JobTracker.xcodeproj"]
        Local["FastAPI · 127.0.0.1:8000<br/>jobtracker.main"]
        SQLite[("SQLite<br/>~/Library/Application Support/JobTracker/")]
        Keychain["macOS Keychain via keyring"]
        Full["classifier: rules + embeddings + SetFit"]
        Swift --> Local
        Local --> SQLite
        Local --> Keychain
        Local --> Full
    end

    subgraph Cloud["cloud mode — JOBTRACKER_DEPLOYMENT=cloud"]
        direction TB
        Web["Next.js 16 · React 19<br/>apps/web/ on Vercel"]
        Fn["FastAPI on Vercel Python<br/>api/index.py → jobtracker.main_cloud"]
        PG[("Supabase Postgres<br/>asyncpg · transaction pooler")]
        Fernet["user_credentials<br/>Fernet-encrypted rows"]
        Rules["classifier: RULES ONLY"]
        Web -->|"Authorization: Bearer supabase JWT"| Fn
        Fn -->|"per-transaction request.jwt.claims<br/>RLS: 32 policies, FORCE"| PG
        Fn --> Fernet
        Fn --> Rules
    end

    Pkg["backend/jobtracker/ — one package, both modes"]
    Pkg -.-> Local
    Pkg -.-> Fn

    Mail["Gmail API · iCloud IMAP"] --> Local
    Mail --> Fn
```

### The design decision that shaped the repo

**One classifier package, two import graphs.** The desktop app runs all three layers. The cloud deployment runs the rules layer alone, and that is not a simplification for the README — it is enforced in code.

The reason is a hard budget. Root `requirements.txt` states it: torch (~800 MB) plus sentence-transformers plus SetFit exceeds Vercel's Python function budget of 50 MB zipped on Hobby and 250 MB zipped on Pro, and `docs/WEB_ARCHITECTURE.md` adds that even on Pro the cold-start cost blows the 60-second wall clock. So the deployed function must never *import* the heavy stack, not merely never call it.

Three mechanisms hold that line:

- `HybridClassifier.__init__` sets `_cloud_rules_only` when `settings.deployment == "cloud"` and lazy-imports `embeddings` / `setfit_model` inside method bodies (`classifier/hybrid.py`). The `jobtracker.classifier` package uses PEP 562 `__getattr__` so heavy re-exports resolve only on demand.
- Root `requirements.txt` is deliberately different from `backend/requirements.txt` and carries a DO-NOT-ADD list.
- `tests/test_main_cloud.py::test_cloud_classifier_is_rules_only_and_skips_heavy_ml_imports` subprocess-invokes `get_classifier()` under `JOBTRACKER_DEPLOYMENT=cloud` and asserts that neither `torch`, `sentence_transformers`, `setfit` nor `transformers` entered `sys.modules`. The `cloud-smoke` CI job runs it on every push.

The honest consequence: a cloud rules miss collapses to `{category: "other", confidence: 0.0, method: "rules"}`. It does not escalate. Corrections still persist and sync back to macOS, where the full cascade remains canonical.

### Data model

Every tenant table carries `user_id UUID NOT NULL` (Alembic rev `6e64c46d32fd`), keyed to Supabase `auth.users.id`. Desktop rows are owned by a fixed sentinel UUID, `LOCAL_USER_ID`.

```mermaid
erDiagram
    auth_users ||--o{ applications : owns
    auth_users ||--o{ emails : owns
    auth_users ||--o{ sync_state : owns
    auth_users ||--o{ user_credentials : owns
    applications ||--o{ emails : "links (nullable FK)"
    applications ||--o{ contacts : has
    applications ||--o{ interviews : has
    emails ||--o| email_embeddings : "has vector"
    emails ||--o{ training_data : "yields correction"

    applications {
        int id PK
        uuid user_id FK
        string company
        string position
        enum status
        date applied_date
        string source
        string url
    }
    emails {
        int id PK
        uuid user_id FK
        int application_id FK "nullable"
        enum source_account "gmail | icloud"
        string message_id UK
        datetime received_at
        string subject
        string sender_email
        enum classified_as
        float classification_confidence
        string classification_method
        bool user_corrected
        bool is_reviewed
    }
    contacts {
        int id PK
        uuid user_id FK
        int application_id FK
    }
    interviews {
        int id PK
        uuid user_id FK
        int application_id FK
        enum type
        datetime scheduled_at
        enum status
    }
    training_data {
        int id PK
        uuid user_id FK
        int email_id FK "nullable"
        string label
        string source "user_correction | mock_seed_v3 | external_dataset"
    }
    email_embeddings {
        int id PK
        uuid user_id FK
        int email_id FK
        string label
        bytes embedding "384 floats"
        string model_version
    }
    sync_state {
        int id PK
        uuid user_id FK
        string account_type
        string account_email
        string gmail_history_id
        int imap_last_uid
    }
    user_credentials {
        uuid user_id PK
        string kind PK "gmail_oauth | icloud_mail"
        bytes ciphertext "Fernet"
        string key_id
    }
```

`auth_users` is Supabase's `auth.users`; it is not defined by this repo's migrations, and it does not exist under SQLite, where the same columns are plain UUIDs.

### Row-level security, as deployed

RLS here is live, not staged. Verified against the production database on 2026-08-03 and re-read for this README against the migrations and `docs/RLS-AUDIT-2026-08-03.md`:

- **Eight tenant tables** — `applications`, `emails`, `contacts`, `interviews`, `training_data`, `email_embeddings`, `sync_state` (rev `a8d4ec5fba26`) and `user_credentials` (revs `c4_user_credentials_rls`, `c5_force_user_credentials_rls`) — each with `ENABLE` **and** `FORCE ROW LEVEL SECURITY` and four policies (`SELECT` / `INSERT` / `UPDATE` / `DELETE`). That is **32 policies**. `FORCE` is the part that matters: without it the table owner is exempt, and the owner is what an application usually connects as.
- **The application role cannot bypass any of it.** Production connects as `jobtracker_app`: `rolsuper=false`, `rolbypassrls=false`, `rolcanlogin=true`.
- **Identity is bound per transaction.** `_install_rls_guc_listener` in `database/connection.py` sets `request.jwt.claims` transaction-locally on every `begin`, so nothing leaks across the PgBouncer transaction pool, and `search_path` is pinned to `public` so a policy cannot be fooled by a shadowed relation.
- **It fails closed.** With no user bound, `auth.uid()` is NULL, `user_id = NULL` matches nothing, and an unauthenticated path sees zero rows rather than everything.
- **All 32 predicates are `user_id = (SELECT auth.uid())`** after rev `c6_rls_initplan_hoist`. This is a planning-time change: bare `auth.uid()` is `STABLE` and re-evaluated once per *row*; the sub-select is hoisted into an `InitPlan` evaluated once per *query*. Measured on a **synthetic** 200,000-row sequential scan in a throwaway `postgres:16` — **not** a production measurement — invocations went 200,001 → 1 and the query 126 ms → 10 ms, with an identical row set. The invocation ratio is the part that holds at any table size; Applied's real tables are far smaller.
- The migration is a **no-op on SQLite**, so `alembic upgrade head` stays green for the desktop build and for CI.

---

## Tech Stack

Versions are pinned from `apps/web/package.json`, `requirements.txt`, and the CI workflows.

### Web

| Category | Technologies |
| --- | --- |
| **Framework** | Next.js 16.2.11 (App Router, Turbopack), React 19.2.4 |
| **Language** | TypeScript 5 (strict), zod 3.25 for runtime env validation |
| **Styling** | Tailwind CSS 4, shadcn/ui-compatible scaffold, Radix Slot |
| **Auth** | Supabase Auth via `@supabase/ssr` 0.5 (SSR cookie `getAll`/`setAll`) |
| **API client** | `openapi-fetch` 0.17 over types generated by `openapi-typescript` 7 |
| **Testing** | Playwright 1.48+ (17 spec files under `apps/web/tests/e2e/`) |

### Backend

| Category | Technologies |
| --- | --- |
| **Runtime** | Python 3.11, FastAPI, Uvicorn |
| **Data** | SQLModel / SQLAlchemy 2 (async), Alembic, SQLite on desktop, Supabase Postgres via asyncpg in the cloud |
| **Auth** | PyJWT `[crypto]`, HS256 pinned, `audience="authenticated"`, `require=["exp","sub","aud"]` |
| **Secrets** | macOS Keychain via `keyring` on desktop; `cryptography.fernet` rows in the cloud |
| **Email** | `google-api-python-client` (Gmail, `gmail.readonly`), `aioimaplib` (iCloud), BeautifulSoup + lxml for parsing |

### ML

| Category | Technologies |
| --- | --- |
| **Layer 1** | Hand-written regex engine, 212 patterns across 7 categories |
| **Layer 2** | `intfloat/e5-small-v2` (pretrained, downloaded, not trained here) |
| **Layer 3** | SetFit fine-tuned in this repo on `sentence-transformers/paraphrase-MiniLM-L6-v2`, 8 labels |
| **Export** | int8 ONNX + Transformers.js (`ml/browser/`), Gradio Space (`ml/demo/`), BentoML service (`ml/bento_service.py`) |
| **Tracking** | MLflow (`ml/mlruns`, registry alias `production` gated at the 0.95 floor), W&B mirror (offline) |

### Desktop and infrastructure

| Category | Technologies |
| --- | --- |
| **macOS app** | SwiftUI, Xcode project target macOS 26.2, local FastAPI sidecar, packaged `.app` |
| **Hosting** | Vercel (Next.js + one Python function, `maxDuration` 60), Supabase Postgres, Hugging Face Spaces |
| **CI** | GitHub Actions — 13 workflows (see [Verify it](#verify-it)) |

---

## Classifier evaluation

**The 0.9791 belongs to the rules layer. It is not a whole-system accuracy figure, and the filenames actively mislead on this point.**

The **rules layer** — 212 regex patterns and no model — scores **0.9791 macro-F1** (accuracy 0.9792, 2 of 96 misclassified) on the v3 evaluation set, committed at `backend/data/evaluation/baseline_rules_v3.json` over `classifier_eval_v3.jsonl`, and `backend-ci.yml` fails any merge below a **0.95** floor. The **full three-layer cascade** scores **0.9583** on that same set (accuracy 0.9583, 4 misclassified), recorded in `docs/ML_EXECUTION_TRACKER.md` Cycle H.

The trap is that `baseline_hybrid_v3.json` reports 0.9791 too. It does so because it was regenerated under the evaluator's `deterministic` hybrid profile, which calls `set_lite_mode(True)` and blanks `_known_embeddings` — so it measures the deterministic path, which is the regexes. Every metric block in the two files is identical, including both mismatch records; only the `meta` block differs, by `mode`, `hybrid_profile` and timestamp. `benchmark_history.md` says this in its own header. CI runs that profile on purpose, because a gate that consults a stochastic model is a gate that goes red for reasons unrelated to the change under test.

Being fair to the model: on the **v2** set the cascade beat the rules — 0.9843 against 0.9686 macro-F1 (`docs/ML_EXECUTION_TRACKER.md`, Cycle B5). The learned layers are not decoration; they lost on v3.

That comparison is now a measurement rather than a citation. `scripts/cascade_gate.sh` scores the full cascade and the rules layer over the same set in one run, and commits the delta, the per-example exchange and the checkpoint that produced it to `backend/data/evaluation/baseline_cascade_v3.json`. It does **not** run in CI, and the reason is not an omission: no SetFit checkpoint ships in this repository, so a GitHub-hosted runner has nothing to load. `learning-gate.yml` is therefore `workflow_dispatch`, and on a hosted runner it fails naming the directory it searched rather than degrading to the rules layer and reporting that as the cascade. What the number gates — the margin a learned layer has to clear before it may touch real mail, and what puts it back — is [`docs/ML_PROMOTION_POLICY.md`](docs/ML_PROMOTION_POLICY.md).

What the v3 set is, exactly, from `classifier_eval_v3_spec.json` and the dataset itself: **96 examples, 12 per label across 8 labels**, grouped as 65 core-positive, 17 edge-noise, 8 historical-miss and 6 core-negative, with confusion-pair tagging. The rows carry `subject`, `body_text`, `label`, `sender_email`, `scenario_group` and `confusion_pair` — and **no provenance field**, so the dataset does not record how many examples came from a real inbox versus a generator. That is a real limit on how far 0.9791 generalizes, and 96 examples is a small sample under any reading.

```bash
cd backend
# the exact rules gate CI runs
python -m jobtracker.scripts.evaluate_classifier \
  --mode rules \
  --dataset data/evaluation/classifier_eval_v3.jsonl \
  --baseline data/evaluation/baseline_rules_v3.json \
  --tolerance 0.001 --min-macro-f1 0.95

# the deterministic hybrid gate — same numbers, and that is the point
python -m jobtracker.scripts.evaluate_classifier \
  --mode hybrid --hybrid-profile deterministic \
  --dataset data/evaluation/classifier_eval_v3.jsonl \
  --baseline data/evaluation/baseline_hybrid_v3.json \
  --tolerance 0.001 --min-macro-f1 0.95

# the full cascade — this is the one that reads 0.9583
python -m jobtracker.scripts.evaluate_classifier \
  --mode hybrid --hybrid-profile full \
  --dataset data/evaluation/classifier_eval_v3.jsonl
```

The last command prints an `answered by:` line next to the score, and it refuses to report a verdict at all when no semantic layer answered: `_assert_layers_exercised` fails a `full`-profile run whose ML layers never loaded, unless you override it with `--allow-degraded-layers`. That guard exists because a cascade with no SetFit model on disk degrades to rules and reports 0.9791 again — flatteringly, for a classifier that is not running. It is the same failure `--require-semantic` guards in the latency benchmark.

---

## Performance

**Per-layer classifier latency.** 96-example v3 set, warm (a warmup pass excludes model load and lazy imports), 3 repetitions — 288 classifications.

| Layer | p50 | p95 | answered |
| --- | ---: | ---: | ---: |
| `content_filter` | 0.036 ms | 0.043 ms | 15 |
| `rules` | **0.176 ms** | 0.241 ms | 174 |
| `fallback` | 0.262 ms | 21.176 ms | 39 |
| `setfit` | **17.649 ms** | 37.702 ms | 60 |

The ratio is the result: SetFit costs roughly **100×** the rules layer at p50, and the rules layer alone answers 174 of the 288. That is the cascade doing its job as a measurement rather than an assertion. It is reported per layer because a single mean is a statement about the corpus mix as much as about the code — change the proportion of inputs the regexes catch and the mean moves with no code change. The script uses nearest-rank percentiles deliberately, because numpy's interpolated default disagrees on a sample this small.

**Provenance, stated plainly:** these figures come from the run recorded in commit `2c17470` (2026-08-03). **No results artifact is committed**, and the commit does not record the machine, so treat the absolute milliseconds as machine-dependent and the ratio as the durable claim. Regenerate with:

```bash
cd backend
python -m jobtracker.scripts.benchmark_classifier_latency --require-semantic --output latency.json
```

`--require-semantic` fails a run in which no model answered. The cascade degrades to rules when SetFit will not import, and a degraded run reports flatteringly low latency for a classifier that is not actually running.

**Model size.** The SetFit head exports to ONNX at **90,362,391 bytes** float32 and quantizes to **22,843,695 bytes** int8 — measured on `ml/browser/artifacts/model.onnx` and `model_quantized.onnx`, both committed.

---

## Testing

**700 tests collected, 0 skipped.** These figures were recorded on 2026-08-12 by `python3 scripts/readme_facts.py --record`, which runs `pytest tests -q --cov=jobtracker` in the project's Python 3.11.14 venv and writes `docs/readme-facts.json`; `--check` fails the build when this page and that artifact disagree. The count was first published from commit `37dd805` and corrected in `5b895d8`. It has grown since: a static parse counts 661 `test_*` functions across 50 modules at HEAD, against 300 across 25 modules at `37dd805` — the tests added with the sync-cursor, recoverable-removal, company-matching, stage-vocabulary, application-identity, RLS, migration-chain and expand-only-gate work, five of which brought their own module (`test_status_vocabulary.py`, `test_application_identity.py`, `test_rls_postgres.py`, `test_migrations_postgres.py`, `test_expand_only_gate.py`). The bold 700 is the artifact's and moves only on `--record`, while the static parse is recomputed on every `--check`, so between recordings the two drift apart — and parametrization lifts collected above the parse besides. CI reruns the suite with `--cov` on every push, so the current number lands in a public run log rather than resting on this sentence.

The Postgres row-level-security module is the only thing in the repo that can demonstrate the isolation the product claims, and **12 tests** now exercise it. It has not always run: its tests waited on a database URL no workflow set, and a skip is green, so the 10 it held on 2026-08-02 had **never executed anywhere**. Two fixes: `test_rls_postgres.py` now starts its own `postgres:16` via testcontainers when `JOBTRACKER_TEST_PG_ADMIN_URL` is absent and Docker is available, and the `rls-postgres` CI job supplies its own service container. That job then parses the JUnit XML and **fails the build if the suite reports zero tests or any skip**, because a skipped security test and a passing one produce the same green tick.

Those tests drive the production machinery, not a fixture: `jobtracker.database.connection.get_session` with its real GUC and `search_path` handling, against a non-`BYPASSRLS` role, asserting that a raw query with the application-level `WHERE user_id = ...` filter *removed* still returns nothing for another tenant.

`test_migrations_postgres.py` rides in the same job, for a defect the rest of the suite is structurally blind to: on SQLite, `sa.Enum` renders as `VARCHAR`, so a migration can add an enum label in the wrong case and every other test stays green while production 500s on the first write. It applies the whole Alembic chain to a bare database through the real CLI, then asserts the `applicationstatus` labels are the Python enum's member names in declaration order, that a row round-trips, and that the lowercase spelling is genuinely rejected. It is guarded by the same "did it actually run" JUnit check as the RLS suite.

**Coverage**, from the same run: **59.56%** overall — 9,503 statements, 3,843 missed. The distribution matters more than the total. `jobtracker/cloud`, the code that actually deploys, is at **88.7%**; `auth` 80.5%; `database` 77.5%. What pulls the average down is `jobtracker/scripts` at 2,357 statements and 33.6%, of which eight modules no test imports account for 1,010 statements at 0%.

This paragraph read "54% overall, 61% excluding one-off scripts … 2,163 statements of dataset importers" until 2026-08-03, and three of those four numbers were wrong. The corrections, in full, are in commit `5b895d8`: 54% came from a Python 3.14 run, where PEP 649 stops emitting line events for annotation-only class attributes, so the same tree measures 8,018 statements instead of 8,210 — a 192-statement gap across 13 Pydantic models. 61% is dropped rather than restated, because it reaches 60.5% only by excluding 1,234 statements that CI invokes directly as gates. And 2,163 never described dataset importers; those are 662 statements at 0%. The portfolio was citing this README instead of a run, which is how they persisted.

| Layer | Tooling | Scope |
| --- | --- | --- |
| **Backend unit + integration** | pytest | classifier, API, sync, auth, cloud entrypoint, evaluator, ML-ops scripts |
| **Database isolation** | pytest + testcontainers / CI service container | 12 RLS enforcement tests against real Postgres |
| **Web e2e** | Playwright | 17 spec files — auth, beta, connect, dashboard, demo, file-application, import, landing, navigation, production, sample-inbox, scan-correct, session-edge, settings, shell, smoke |
| **Web e2e, production build** | Playwright vs `next build` + `next start` | the `production` spec: every route driven against a real production build, failing on React hydration errors, uncaught exceptions and 5xx |
| **Web static** | `tsc --noEmit`, ESLint, `next build` | every push touching `apps/web/**` |
| **macOS** | `xcodebuild` | resolve packages and build the `JobTracker` scheme |

Two lint gates run **advisory**, on purpose. `ruff check .` reported 379 findings on its first CI run (2026-08-07) and `mypy .` under `strict = true` reported 879 across 65 of 92 files. Both were configured in `pyproject.toml` from the start and had never actually run. They print their count on every build and flip to blocking when they reach zero; a gate that is red from birth gets ignored or deleted, and neither should be silenced with `--fix` or blanket `# type: ignore`.

**Dependencies.** A local `pip-audit -r requirements.txt` against the root file — the set that ships to Vercel — reported **0 known vulnerabilities** when the audit ran on 2026-08-03. The CI step is advisory and, because the job's working directory is `backend/`, it resolves `backend/requirements.txt` instead — the full desktop set. It reported **8 known vulnerabilities in 2 packages** (cryptography, transformers) on 2026-08-07, and `transformers` is the tell: it is pinned in `backend/requirements.txt` and appears nowhere in the root file, so the findings cannot be describing the Vercel surface the step's own comment names. Neither figure covers torch, which CI installs out-of-band from the PyTorch CPU index. Use `pip-audit` and not `osv-scanner` against these files: osv-scanner resolves each `>=` floor to its *minimum* and reports the worst case the constraints permit, which overstated this repository by two orders of magnitude.

---

## Implemented vs delegated vs planned

Being precise about this is the point.

### Implemented — hand-written in this repo

- **The rules engine.** 212 regex patterns across 7 categories (115 strong, 27 weak, 70 negative), the scoring weights (strong +3, +6 in subject; weak +1, +2; negative −5), the margin-to-confidence tiers, and the ATS-domain boost. Ported byte-for-byte to JavaScript in `apps/web/lib/demo/rulesLayer.ts` and to `ml/browser/site/app.js`. A further 27 **veto** patterns sit outside that count, because they score nothing: a veto caps its category at zero, which is the only way to overrule a strong subject match — +6 survives a negative's −5, so "Complete your self-assessment" read as an `assessment` invitation for as long as the negative was the strongest tool available. Only `assessment` declares vetoes today, for the senses of the noun that are not a candidate test (risk, self, needs, impact, performance, damages). They name no marketing vocabulary on purpose: that belongs to the content guard which runs *ahead* of the rules layer, and a veto would apply it to message bodies at a threshold of one, suppressing every real invitation with an unsubscribe footer.
- **The cascade and its gate** — layer ordering, escalation conditions, the 0.85 auto-classify threshold and the 0.70 minimum for trusting a semantic layer, the `needs_review` routing, and the correction-to-training-data loop.
- **The SetFit head is the one model trained here.** Fine-tuned on `sentence-transformers/paraphrase-MiniLM-L6-v2` over 8 labels, with a provenance contract (`training_metadata.json`) that is schema-versioned and validated *before* it is written, covering label counts, source counts, split sizes and exact `label_to_id` / `id_to_label` inversion.
- **The evaluation harness** — `evaluate_classifier.py` with its `deterministic` and `full` hybrid profiles, baseline comparison with tolerance, the macro-F1 floor, and `benchmark_classifier_latency.py`.
- **Multi-tenant isolation** — the `user_id` column and composite indexes, the 32 RLS policies, the per-transaction `request.jwt.claims` GUC with `search_path` pinning, and the Fernet credential envelope with a `key_id` column for rotation.
- **The cloud/desktop split** — lazy imports, PEP 562 module `__getattr__`, and the subprocess guard test that proves the heavy stack never enters `sys.modules`.
- **ML operations** — weekly sparse-label candidate mining with gap-based quotas, drift and confidence monitoring with thresholded alerts, and the alert-issue automation.

### Delegated — on purpose

- **The embedding model.** `intfloat/e5-small-v2` is **pretrained and used as shipped**. It is downloaded, not trained here; only the stored example set it compares against is this project's.
- **The SetFit body and training loop.** The `setfit` library does contrastive fine-tuning over a sentence-transformers backbone. This project supplies the data, the sampling policy and the provenance contract.
- **ONNX quantization.** The int8 export is produced by the standard toolchain (`ml/browser/export_onnx.py`) and executed by Transformers.js. No custom kernel, no custom quantizer.
- **Identity.** Supabase Auth issues and signs the JWT. This repo verifies it — HS256 pinned, so `alg: none` and `alg: RS256` are rejected — and never mints one.
- **Mail access.** `google-api-python-client` for Gmail and `aioimaplib` for iCloud. No hand-rolled IMAP or OAuth transport.

### Planned — not in this build

- **Semantic layers in the cloud.** The deployed Vercel product runs the **rules layer only**, and there is no embedding or SetFit inference on that path. Moving them behind an external inference service is a documented follow-up in `requirements.txt` and `docs/WEB_ARCHITECTURE.md`; nothing is wired.
- **In-browser inference inside the Applied web app.** The 22.8 MB int8 ONNX build is real and runs in the Hugging Face Space and under `ml/browser/site/`. It does **not** run on `getapplied.vercel.app`: the app's strict CSP forbids the WASM eval and CDN fetch Transformers.js needs, so `/demo` runs layer 1 live in the browser and serves precomputed layer 2 and 3 verdicts.
- **WebSocket sync in the cloud.** Vercel's Python runtime does not support it; the cloud path polls. The desktop path has live WebSocket status.
- **Credential rotation.** `user_credentials.key_id` and a multi-key decrypt path are scaffolded. Only key `v1` is active and rotation is not wired.
- **A mobile client.** `apps/mobile/` is a reserved directory. There is no app in it.
- **Green ruff and mypy gates.** Both currently report and do not block. See [Testing](#testing).

---

## Getting Started

### Prerequisites

- Python 3.11+ (the desktop stack pins 3.11; `backend/.venv311` is the correct venv, not `backend/.venv`)
- Node.js 22 and pnpm 10, for the web app — the major is load-bearing, not incidental. `pnpm test:unit` imports `.ts` modules straight from `.mjs` test files and runs them on the runtime's built-in type stripping, which needs **22.6 or newer** (and the built-in glob, 21 or newer). On Node 20 those tests do not fail, they refuse to load with `ERR_UNKNOWN_FILE_EXTENSION` — which is how they once existed while no job ran them
- macOS with Xcode, for the desktop app only
- Internet on first run, to download `intfloat/e5-small-v2`

### Web app

```bash
git clone https://github.com/yadava5/applied.git
cd applied/apps/web

cp .env.example .env.local     # Supabase URL + anon key, BACKEND_API_URL
pnpm install --frozen-lockfile
pnpm dev                       # http://localhost:3000
```

The landing page (`/`) and the fixture demo (`/demo`) run with **no backend and no Supabase**, so a review deploy needs only placeholder values — which is exactly what `frontend-ci.yml` supplies. See [`apps/web/README.md`](apps/web/README.md) for the full web setup.

### Backend and macOS app

```bash
./scripts/install.sh           # venv, PyTorch CPU wheels, deps, model, DB
./scripts/start_backend.sh     # FastAPI on 127.0.0.1:8000
open apps/macos/JobTracker/JobTracker/JobTracker.xcodeproj
```

The full walkthrough is in [`docs/SETUP.md`](docs/SETUP.md).

### Environment variables

Backend settings use the `JOBTRACKER_` prefix (`backend/jobtracker/config.py`).

```env
# Mode
JOBTRACKER_DEPLOYMENT=cloud             # or `desktop` (default)
JOBTRACKER_ENVIRONMENT=test             # used by CI and local test runs

# Cloud only
JOBTRACKER_SUPABASE_JWT_SECRET=...      # Supabase project HS256 signing key
JOBTRACKER_SECRET_ENCRYPTION_KEY=...    # urlsafe base64, 32 bytes, for Fernet
JOBTRACKER_CORS_ALLOWED_HOSTS=...

# Tests
JOBTRACKER_TEST_PG_ADMIN_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/test_db
```

```env
# apps/web/.env.local
NEXT_PUBLIC_SUPABASE_URL=https://<project>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
BACKEND_API_URL=http://localhost:8000
```

Generate a Fernet key with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Commands

| Command | What it does |
| --- | --- |
| `./scripts/install.sh` | One-time backend setup: venv, CPU torch, deps, model, DB |
| `./scripts/start_backend.sh` | Run FastAPI on `127.0.0.1:8000` |
| `pnpm dev` / `pnpm build` | Web app, from `apps/web/` |
| `pnpm typecheck` / `pnpm lint` / `pnpm e2e` | The three checks `frontend-ci.yml` and `e2e-ci.yml` run |
| `pytest tests -q --cov=jobtracker` | Backend suite with coverage, from `backend/` |
| `./scripts/generate_eval_baselines.sh --version 3` | Regenerate the committed rules and hybrid baselines |
| `./scripts/train_pipeline.sh` | Retrain the SetFit head and write the provenance artifact |
| `./scripts/weekly_labeling_cycle.sh --append-tracker` | Weekly sparse-label candidate mining |
| `./scripts/monitoring_cycle.sh` | Drift and confidence monitoring report |
| `python3 scripts/readme_facts.py` | Verify every number in this README against the code (`--write` to repair, `--record` to re-measure the suite) |

---

## Project Structure

```
applied/
├── apps/
│   ├── web/                 # Next.js 16 App Router product (the cloud UI)
│   │   ├── app/             # (auth) · (app) · demo · import · api routes
│   │   ├── lib/demo/        # rulesLayer.ts — layer 1 ported to run live in the tab
│   │   └── tests/e2e/       # 17 Playwright specs
│   ├── macos/               # SwiftUI app; path still says JobTracker (see the naming note)
│   └── mobile/              # reserved; empty
│
├── backend/
│   ├── jobtracker/          # the one package both modes import
│   │   ├── classifier/      # rules.py (212 patterns) · embeddings.py · setfit_model.py · hybrid.py
│   │   ├── api/             # desktop routers, unauthenticated by design
│   │   ├── cloud/           # cloud-only routers, require_user() at the router level
│   │   ├── auth/            # supabase_jwt.py — HS256 pinned verification
│   │   ├── credentials/     # types · desktop (Keychain) · cloud (Fernet)
│   │   ├── database/        # models, connection (the RLS GUC listener lives here)
│   │   └── scripts/         # evaluator, latency benchmark, ML-ops tooling
│   ├── alembic/versions/    # 13 revisions incl. the RLS + InitPlan-hoist migrations
│   ├── data/evaluation/     # eval sets, committed baselines, benchmark + monitoring history
│   └── tests/               # 50 modules
│
├── ml/                      # the classifier as a deployable service
│   ├── browser/             # ONNX export + the in-browser site (Transformers.js)
│   ├── demo/                # Gradio Space
│   ├── service.py           # standalone sync facade
│   └── track_run.py         # MLflow run + registry promotion past the 0.95 floor
│
├── api/index.py             # Vercel Python entry → jobtracker.main_cloud
├── requirements.txt         # the CLOUD dependency set; deliberately not backend/requirements.txt
├── docs/                    # architecture, API spec, ML strategy + runbooks, RLS audit
└── .github/workflows/       # 13 workflows
```

---

## Technical Decisions

**Rules first, model last.** Ordering the cascade cheapest-first is not only a latency decision; it is an explainability one. A regex hit can be shown to a user as the phrase that matched. The measured cost — 0.176 ms against 17.649 ms at p50 — is what makes the ordering worth the extra code path, and the review queue is what catches the cases where the cheap layer was confidently wrong. The tradeoff is real: the rules are hand-maintained and every new ATS phrasing is a code change.

**A gate below the measured value, and a gate on the gate.** The macro-F1 floor is 0.95 against a measured 0.9791, deliberately loose, because a gate pinned at the current number turns every honest refactor red; what it guards against is a collapse, not a two-point drift. Separately, the RLS job asserts that its own suite *ran*, because the failure mode that actually occurred here was not a failing test but ten silently skipped ones.

**Deployment mode as an import-graph decision.** The alternative to splitting the classifier by deployment was a single build that carries torch everywhere — which does not fit in a Vercel function — or two divergent packages, which drift. Applied keeps one package and makes the divergence a property of the import graph, then tests that property in a subprocess. The cost is honesty overhead: the cloud is a weaker classifier than the desktop, and every surface that talks about accuracy has to say which one it means.

---

## Verify it

Every number above terminates in something you can open.

**Continuous integration** — `.github/workflows/`:

| Workflow | What it proves |
| --- | --- |
| `backend-ci.yml` | `pytest tests -q --cov=jobtracker` (the coverage number lands in the public run log); the rules gate at `--min-macro-f1 0.95`; the deterministic hybrid gate; the `rls-postgres` job with its assert-it-ran step; the `expand-only` job, which walks the Alembic chain one revision at a time against a `postgres:16` service and fails a revision that drops or narrows anything without a module-level `CONTRACT_STEP` saying why; the `cloud-smoke` job that imports the cloud app under `JOBTRACKER_DEPLOYMENT=cloud` and probes `/health` |
| `frontend-ci.yml` | `pnpm typecheck`, `pnpm lint` (`--max-warnings 0`, so every warn-level rule next ships — the six `jsx-a11y/*` among them — is a red build rather than a printed suggestion), `pnpm test:unit`, `pnpm build` on Node 22 / pnpm 10. The Node major is a constraint, not a default: `test:unit` needs the runtime's type stripping (22.6+), so pinning back to 20 does not fail the job — it stops running the unit suite, which is exactly what happened before |
| `e2e-ci.yml` | Playwright against a real backend + frontend pair, uploading traces and server logs |
| `macos-ci.yml` | `xcodebuild` resolves packages and builds the `JobTracker` scheme |
| `codeql.yml`, `gitleaks.yml` | SAST and full-history secret scanning |
| `.githooks/pre-commit` (local, opt-in) | The same scan over the *staged* diff, before the commit exists. Not a workflow — git does not enable a hooks path for you, so each clone runs `git config core.hooksPath .githooks` once. CI is the net that always runs; this one exists because a credential that reaches GitHub is published even if the next commit deletes it |
| `ml-monitoring-weekly.yml` | Scheduled drift/confidence report, artifacts uploaded, alert issue opened on threshold breach |
| `scorecard.yml`, `booklet.yml` | Supply-chain grading; the system-card booklet build |
| `readme-facts.yml` | `python3 scripts/readme_facts.py --check` — every number on this page recomputed from the source that defines it. Unfiltered by path, because a claim here can be invalidated from anywhere; and a claim site whose sentence was reworded so the checker can no longer find it fails the build rather than passing quietly |

**Committed evaluation artifacts** — `backend/data/evaluation/`:

- `classifier_eval_v3.jsonl` and `classifier_eval_v3_spec.json` — the 96 examples and the coverage contract they must satisfy
- `baseline_rules_v3.json` — where 0.9791 lives, with the confusion matrix and both mismatches
- `baseline_hybrid_v3.json` — the deterministic-profile file that reads the same, which is the trap this README exists to defuse
- `baseline_cascade_v3.json` — the cascade with its models actually answering, with the checkpoint that produced it, the layer that answered each mismatch, and the delta to rules
- `benchmark_history.{md,jsonl}` — every baseline, v1 through v3, with its profile
- `ml_monitoring_report.{md,json}`, `ml_monitoring_history.jsonl`, `label_balance_report.md`
- `ml/browser/artifacts/model_quantized.onnx` — 22,843,695 bytes; check it with `stat`

**Third-party score.** [OpenSSF Scorecard](https://scorecard.dev/viewer/?uri=github.com/yadava5/applied) grades this repository against 18 supply-chain checks and publishes the result. It is computed by someone else, which is the entire value: a number this project calculates about itself is a claim. Several of the 18 grade repository *settings* that no file in the repo can turn on, so the score moving up over time is a better signal than wherever it starts.

**Security posture.** `docs/RLS-AUDIT-2026-08-03.md` is the read of the live database, including a retracted finding it kept rather than deleted, and `docs/harden-2026-08-03.sql` is the applied fix with its verification query.

---

## Documentation

| Doc | What's inside |
| --- | --- |
| [System Card](https://getapplied.vercel.app/system-card) | Classifier design, evaluation, limitations, safety notes |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System architecture and component boundaries |
| [`docs/WEB_ARCHITECTURE.md`](docs/WEB_ARCHITECTURE.md) | Deployment modes, cloud auth flow, credential storage |
| [`docs/API_SPEC.md`](docs/API_SPEC.md) | Backend REST + WebSocket contract |
| [`docs/ML_STRATEGY.md`](docs/ML_STRATEGY.md) | Classifier behaviour, training lifecycle, metadata contract |
| [`docs/ML_EXECUTION_TRACKER.md`](docs/ML_EXECUTION_TRACKER.md) | Every ML cycle with its measured results — the source for the cascade's 0.9583 |
| [`docs/ML_PROMOTION_POLICY.md`](docs/ML_PROMOTION_POLICY.md) | What a learned layer must beat before it serves real mail, and what puts it back |
| [`docs/ML_WEEKLY_OPERATIONS.md`](docs/ML_WEEKLY_OPERATIONS.md) · [`docs/ML_MONITORING_RUNBOOK.md`](docs/ML_MONITORING_RUNBOOK.md) | Weekly SOP and monitoring triage |
| [`docs/RLS-AUDIT-2026-08-03.md`](docs/RLS-AUDIT-2026-08-03.md) | Live row-level-security audit |
| [`docs/SETUP.md`](docs/SETUP.md) | Local setup and day-to-day development |
| [`DEPLOY.md`](DEPLOY.md) | Cloud deployment paths (auth, applications API, Gmail OAuth) |

---

## Author

**Ayush Yadav** — sole author and maintainer. Design, full-stack engineering, and ML.
[github.com/yadava5](https://github.com/yadava5)

---

## License

Applied is **source-available** under the [PolyForm Noncommercial License 1.0.0](LICENSE).

You may use, run, self-host, study, and modify it for any **noncommercial** purpose. **Commercial use of any kind requires a separate license** — contact Ayush Yadav at **aesh.03.23@gmail.com** to discuss commercial licensing or sponsorship.

See the [LICENSE](LICENSE) file for the full terms.

---

<p align="center">
  <sub>Built by Ayush Yadav · <a href="https://getapplied.vercel.app">getapplied.vercel.app</a></sub>
</p>
