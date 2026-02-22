# Repository Structure and Workflow

## Goals

- Keep **one source-control root** for the entire product.
- Keep platform apps isolated so backend and UI can evolve independently.
- Keep CI as a read-only safety net that catches regressions without rewriting code.

## Monorepo Layout

```text
jobtracker/
├── backend/                    # Python FastAPI backend + tests
├── apps/
│   ├── macos/                  # Native macOS SwiftUI app
│   └── mobile/                 # Reserved for future mobile app(s)
├── docs/                       # Product, architecture, setup, and process docs
├── scripts/                    # Build, run, packaging, and repair utilities
└── .github/workflows/          # CI pipelines
```

## Boundaries

- `backend/` owns API, database models, classifier logic, and backend tests.
- `apps/macos/` owns SwiftUI app code, app assets, and Xcode project files.
- `apps/mobile/` is the reserved home for future iOS/Android code.
- `scripts/` contains tooling that can be called locally and from CI.

## Git Hygiene

- Do not create nested Git repositories under `apps/`.
- Keep local-only files out of source control:
  - virtual environments (for example `.venv*`)
  - local secrets (for example `backend/client_secret.json`)
  - machine-specific Xcode user state (`xcuserdata`, `.xcuserstate`)

## CI Policy

- Backend CI runs when backend-related files change.
- macOS CI runs when macOS app files change.
- CI jobs only **build/test**; they do not auto-commit or rewrite source files.
- CI is expected to pass before merging to protected branches.

## Adding Mobile in Future

When mobile work begins:

1. Create platform directory under `apps/mobile/` (for example `ios/` or `react-native/`).
2. Add a dedicated CI workflow with path filters for that directory.
3. Keep platform-specific tooling inside that app directory to avoid cross-platform coupling.
