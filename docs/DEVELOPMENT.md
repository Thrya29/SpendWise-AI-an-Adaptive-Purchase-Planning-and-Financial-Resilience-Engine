# Development guide

## Prerequisites

Python 3.12, Node.js 22 (≥ 20.9), and Docker (optional for local dev, required for the full stack).

## Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"

# Quality gate (same as CI)
ruff check app tests alembic && ruff format --check app tests alembic
mypy app
pytest --cov                       # SQLite by default; set SPENDWISE_DATABASE_URL for PostgreSQL

# Run locally against SQLite
export SPENDWISE_DATABASE_URL="sqlite+aiosqlite:///./dev.db"
alembic upgrade head
uvicorn app.main:app --reload      # http://127.0.0.1:8000/api/v1/docs
python -m app.worker               # optional: FX refresh + tracked price checks
```

### Database migrations

```bash
alembic revision --autogenerate -m "describe the change"   # then review the generated file
alembic upgrade head
```

`tests/integration/test_migrations.py` fails if models and migrations drift, or if a migration
cannot be downgraded.

### Regenerating the runtime lock

```bash
python -m venv /tmp/lock && /tmp/lock/bin/pip install . && /tmp/lock/bin/pip freeze --exclude spendwise --exclude pip > requirements.lock
```

## Frontend

```bash
cd frontend
npm ci
API_INTERNAL_URL=http://127.0.0.1:8000 npm run dev   # http://localhost:3000

npm run format:check && npm run lint && npm run typecheck && npm test && npm run build
```

### Keeping the API contract in sync

After changing any backend schema or route:

```bash
cd backend && python scripts/export_openapi.py ../frontend/openapi.json
cd ../frontend && npm run gen:api
```

CI fails if either generated file is out of date.

## Full stack with Docker

```bash
python scripts/generate_env.py
docker compose up --build -d
docker compose logs -f api
```

## Conventions

* Money: always `*_minor` integers plus `currency`. Never floats.
* Every user-owned query goes through `OwnedRepository`.
* `domain/` must stay free of I/O and framework imports.
* Backend tests treat warnings as errors.

## Re-recording the walkthrough, GIF and manual screenshots

The video, the README GIF and every picture in the user manual come from the real app, driven by
`e2e/demo/record.spec.ts` (Playwright) against a local SpendWise with made-up demo data.

```bash
# 1. A throwaway database and the demo data (backend/, with its virtualenv)
export SPENDWISE_DATABASE_URL=sqlite+aiosqlite:///./demo.db
alembic upgrade head
python scripts/demo_seed.py reference          # real ECB, AMFI and gold reference data
uvicorn app.main:app --port 8000 &             # then, in frontend/: npm run build && npm start
python scripts/demo_seed.py everyday           # "Asha Rao", a lived-in demo account

# 2. Record (e2e/). Writes videos to test-results/demo-videos and pictures to docs/manual/img
npx playwright test --config demo/playwright.demo.config.ts

# 3. Build the MP4 and the GIF with ffmpeg (commands in docs/media/README.md)
```

