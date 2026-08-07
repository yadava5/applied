<div align="center">

# Applied

### Your job search, tracked automatically.

Applied reads your inbox, classifies every message with a purpose-built ML pipeline, and assembles your application pipeline for you — no spreadsheets, no manual data entry.

<br/>

[![Live app](https://img.shields.io/badge/Live-getapplied.vercel.app-111111?style=for-the-badge)](https://getapplied.vercel.app)
[![System Card](https://img.shields.io/badge/System_Card-read-2b2b2b?style=for-the-badge)](https://getapplied.vercel.app/system-card)
[![In-browser classifier](https://img.shields.io/badge/%F0%9F%A4%97_Space-classifier-ffcc4d?style=for-the-badge)](https://huggingface.co/spaces/yadava5/jobtracker-classifier)

![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/license-PolyForm_Noncommercial_1.0.0-blue)
![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)
![React 19](https://img.shields.io/badge/React-19-61dafb?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-strict-3178c6?logo=typescript&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776ab?logo=python&logoColor=white)
![ONNX in-browser](https://img.shields.io/badge/ONNX-runs_in_browser-005ce6)

**[Live app](https://getapplied.vercel.app) · [Try the demo](https://getapplied.vercel.app/demo) · [System Card](https://getapplied.vercel.app/system-card) · [Classifier Space](https://huggingface.co/spaces/yadava5/jobtracker-classifier)**

Applied is part of a six-project portfolio — browse the rest at [yadava5.github.io/Portfolio-2.0](https://yadava5.github.io/Portfolio-2.0/).

</div>

---

## What it is

Job hunting generates a flood of email — confirmations, rejections, interview invites, take-home assessments, recruiter follow-ups — and keeping a spreadsheet in sync with it by hand is tedious and error-prone. **Applied turns that inbox into a live pipeline automatically.** It connects to Gmail or iCloud, classifies each message into a job-search category, links related emails into a single application, and surfaces where every opportunity actually stands.

Applied ships as a **Next.js 16 web product**, a **SwiftUI macOS app** on a local FastAPI backend, and a portable **3-layer email classifier** — the same model, deployable in the cloud, on the desktop, or entirely inside the browser.

## Why it's interesting

The classifier is the heart of the product, and it's built to be both accurate and honest about its accuracy:

- **Three layers, escalating cost.** A message is first matched against **201 deterministic regex rules**; unmatched messages fall through to **e5 embedding similarity**; ambiguous cases are resolved by a **fine-tuned SetFit head**. Cheap and explainable first, learned model only when needed.
- **A load-bearing metric with a CI gate.** The **rules stage** scores **0.9791 macro-F1** on a held-out evaluation set — not the full cascade, which scores 0.9583 on the same set (`docs/ML_EXECUTION_TRACKER.md`). The evaluation runs under the `deterministic` hybrid profile, which disables SetFit and blanks the embedding examples, so the file named `baseline_hybrid_v3.json` measures the regexes alone, and continuous integration **fails any merge that drops below 0.95** — the number can't quietly rot.
- **Runs entirely in the browser.** The model is exported to **int8 ONNX (22.8 MB)** and executed client-side via Transformers.js — **zero servers, zero data leaving the device** — and verified to produce output identical to the Python model.
- **A confidence gate, not a guess.** Predictions below **0.85 confidence** are routed to a human review queue rather than silently accepted, and every correction feeds back into training data.

The live landing page runs a real email through all three layers in front of you, and the full methodology is documented in the [System Card](https://getapplied.vercel.app/system-card).

## Features

- **Inbox sync** — connect Gmail or iCloud; incremental or full sync with live status over WebSocket
- **Automatic classification** into nine categories: `applied`, `pending_application`, `interview`, `rejection`, `offer`, `assessment`, `follow_up`, `needs_review`, `other`
- **Application linking** — related emails are automatically grouped into a single tracked application, with relinking from new signals
- **Human-in-the-loop review** — a review queue for low-confidence predictions; corrections become training data
- **Flexible pipeline views** — Feature Cards, Compact Rows, or a Status Board, with filters for unreviewed and unlinked mail
- **Fixture demo** — explore the full UI with synthetic data at [`/demo`](https://getapplied.vercel.app/demo), no login required
- **Cross-platform** — a hosted web app and a native macOS app share the same backend and model

## Architecture

Applied is a monorepo with three deployable surfaces over one FastAPI core and one shared classifier.

```text
applied/  (formerly jobtracker)
├── apps/
│   ├── web/        # Next.js 16 web product (App Router, React 19)
│   ├── macos/      # SwiftUI native macOS app
│   └── mobile/     # reserved for future mobile client
├── backend/        # FastAPI backend, classifier, DB, tests
│   └── jobtracker/ # api · auth · classifier · cloud · email_clients · database
├── ml/             # training, evaluation, ONNX export, browser + Spaces demos
├── docs/           # architecture, API spec, ML strategy, setup
└── .github/        # backend / frontend / macOS / e2e / ML-monitoring CI
```

**Data flow.** Email clients pull messages → the classifier assigns a category and confidence → high-confidence results build applications, low-confidence results enter the review queue → the web and macOS clients render the pipeline. The web app calls a private FastAPI backend (`jobtracker-api-seven.vercel.app`, internal); the desktop app talks to a local backend on `127.0.0.1:8000`.

### Tech stack

| Layer | Technologies |
|---|---|
| **Web** | Next.js 16 (App Router, Turbopack), React 19, TypeScript (strict), Tailwind CSS 4, shadcn/ui, Supabase Auth (`@supabase/ssr`), zod, Playwright |
| **Backend** | FastAPI, SQLModel / SQLAlchemy 2 (async), Alembic, SQLite (desktop) + Postgres/Supabase (cloud), WebSockets, PyJWT |
| **ML** | `intfloat/e5-small-v2` embeddings, SetFit fine-tuning, hybrid rules engine, int8 ONNX + Transformers.js (in-browser), MLflow tracking |
| **Desktop** | SwiftUI (macOS), local FastAPI sidecar, packaged `.app` |
| **Infra** | Vercel (web + serverless API), Hugging Face Spaces (classifier demo), GitHub Actions CI |

Quality is enforced by CI: a macro-F1 floor on the classifier, a CI-gated backend test suite spanning the classifier, API, sync, and auth, plus frontend, e2e, and macOS build gates. All pipelines are read-only quality gates.

### Measured, not asserted

**305 backend tests, 0 skipped.** The 10 that used to skip are the Postgres
row-level-security module; they needed a live database URL no workflow provided,
so the isolation guarantees were described but never demonstrated. They now start
their own `postgres:16` via testcontainers, creating a non-superuser app role —
which is the part that makes RLS mean anything, since policies do nothing against
a superuser.

**Per-layer classifier latency**, 96-sample v3 set, warm, 3 repetitions:

| Layer | p50 | p95 | answered |
| --- | ---: | ---: | ---: |
| `content_filter` | 0.036 ms | 0.043 ms | 15 |
| `rules` | **0.176 ms** | 0.241 ms | 174 |
| `fallback` | 0.262 ms | 21.176 ms | 39 |
| `setfit` | **17.649 ms** | 37.702 ms | 60 |

The ratio is the result: SetFit costs roughly **100×** the rules layer at p50, and
174 of 288 classifications never reach it. That is the cascade doing its job, as a
measurement rather than an assertion. Reported per layer because a single mean is
a statement about the corpus mix as much as the code — change the proportion of
inputs the regexes catch and the mean moves with no code change.

```bash
python -m jobtracker.scripts.benchmark_classifier_latency --require-semantic
```

`--require-semantic` fails a run in which no model answered. The cascade degrades
to rules when SetFit will not import, and a degraded run reports flatteringly low
latency for a classifier that is not actually running.

**Coverage**, `pytest tests -q --cov=jobtracker` in the project's Python 3.11
venv: **53.2%** overall (8,210 statements, 3,844 missed), from a run of 305
tests with 0 skipped. The distribution matters more than the total —
`jobtracker/cloud`, the code actually deployed, is at **82.2%**; `auth` 80.5%;
`database` 76.6%. What pulls the average down is `jobtracker/scripts` at
**2,240 statements and 33.7%**, of which the eight modules no test imports are
1,006 statements at 0%.

This paragraph read "54% overall, 61% excluding one-off scripts ... 2,163
statements of dataset importers" until 2026-08-03. Three of those four numbers
were wrong, and the portfolio was citing this README rather than a run, which
is how they persisted. The corrections: 54% came from a run on Python 3.14,
where PEP 649 stops emitting line events for annotation-only class attributes
and the same tree measures 8,018 statements instead of 8,210 — a 192-statement
gap across 13 Pydantic models. 61% is dropped rather than restated, because it
reaches 60.5% only by excluding 1,234 statements of code that CI invokes
directly as gates. And 2,163 never described dataset importers: those are 662
statements at 0%; `scripts/` as a whole was already 2,240 when the line was
written.

CI now runs `--cov` on every push, so this figure appears in a public run log
rather than resting on a line of prose.

**Dependencies:** `pip-audit -r requirements.txt` reports **0 known
vulnerabilities** on the deployed Vercel surface. Use `pip-audit`, not
`osv-scanner`, against these files: osv-scanner resolves each `>=` floor to its
*minimum* and reports the worst case the constraints permit, which overstated
this repository by two orders of magnitude.

## Quick start

### Web app

```bash
cd apps/web
cp .env.example .env.local       # Supabase URL + anon key, BACKEND_API_URL
pnpm install --frozen-lockfile
pnpm dev                         # http://localhost:3000
```

The landing page (`/`) and the fixture demo (`/demo`) run with **no backend and no Supabase**, so a recruiter-ready deploy needs only placeholder env values. See [`apps/web/README.md`](apps/web/README.md) for the full web setup.

### Backend + macOS app

```bash
./scripts/install.sh             # one-time: venv, PyTorch CPU wheels, deps, model, DB
./scripts/start_backend.sh       # FastAPI on 127.0.0.1:8000
open apps/macos/JobTracker/JobTracker/JobTracker.xcodeproj
```

Requires macOS with Xcode and Python 3.11+. Full walkthrough in [`docs/SETUP.md`](docs/SETUP.md).

## Documentation

| Doc | What's inside |
|---|---|
| [System Card](https://getapplied.vercel.app/system-card) | Classifier design, evaluation, limitations, and safety notes |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System architecture and component boundaries |
| [`docs/WEB_ARCHITECTURE.md`](docs/WEB_ARCHITECTURE.md) | Web app architecture and auth flow |
| [`docs/API_SPEC.md`](docs/API_SPEC.md) | Backend REST + WebSocket contract |
| [`docs/ML_STRATEGY.md`](docs/ML_STRATEGY.md) | Classifier behavior and training lifecycle |
| [`docs/SETUP.md`](docs/SETUP.md) | Local setup and day-to-day development |
| [`DEPLOY.md`](DEPLOY.md) | Cloud deployment paths (auth, applications API, Gmail OAuth) |

## Author

**Ayush Yadav** — sole author. Design, full-stack engineering, and ML.
[github.com/yadava5](https://github.com/yadava5)

## License

Applied is **source-available** under the **[PolyForm Noncommercial License 1.0.0](LICENSE)**. It is free to use, run, self-host, study, and modify for any **noncommercial** purpose. **Commercial use of any kind requires a separate commercial license** — reach out to Ayush Yadav at **aesh.03.23@gmail.com** to discuss commercial licensing or sponsorship.

<div align="center">
<sub>Built by Ayush Yadav · <a href="https://getapplied.vercel.app">getapplied.vercel.app</a></sub>
</div>
