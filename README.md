# MiniCI

MiniCI is a local CI demonstration with a React/Vite dashboard, a FastAPI API, PostgreSQL persistence, and a separate queue worker. The worker runs a fixed lint → test → build sequence against the checked-in TypeScript sample repository.

## Run locally with Docker Compose

Prerequisites: Docker Desktop or Docker Engine with the Compose plugin.

```powershell
docker compose up --build -d
docker compose ps
```

The Compose stack starts PostgreSQL, the API, the worker, and Vite. The API creates the tables and inserts the initial project/pipeline idempotently at startup; existing runs are not deleted. Open `http://localhost:5173` and confirm the API at `http://localhost:8000/api/health`.

Click **Run pipeline** and wait for all three jobs to finish. The UI polls every two seconds. **Failure demo** intentionally makes the sample test fail; Build should then be skipped.

The worker is a required, separate long-running process: it claims queued runs from PostgreSQL, copies the bundled sample into a temporary workspace, installs dependencies, and invokes only the fixed npm command allowlist. Compose starts this worker automatically. If running the services manually, start `python -m app.worker` as well as the API; without it, runs remain queued. The worker does not require Docker or mount the Docker socket.

### Run the worker/API on the host

With Docker available for PostgreSQL, start only the database:

```powershell
docker compose up -d db
python -m pip install -r backend/requirements.txt
```

In a PowerShell window for the API:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://minici:localdev@127.0.0.1:5432/minici"
$env:CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
Set-Location backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second PowerShell window for the worker:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://minici:localdev@127.0.0.1:5432/minici"
$env:SAMPLE_ROOT = (Resolve-Path .\sample-repo).Path
Set-Location backend
python -m app.worker
```

In a third window for the frontend:

```powershell
Set-Location frontend
npm install
npm run dev
```

The worker host needs Python dependencies, Node.js/npm, network access to the public npm registry for dependency installation, and read access to `sample-repo`. Commands run in a temporary copy, not in the checked-in source tree.

## Configuration

See [.env.example](./.env.example) for the Compose/local defaults. Never copy example credentials into a public deployment.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy PostgreSQL URL (`postgresql+psycopg://...`). Compose defaults to its `db` service; host-run processes use `127.0.0.1`. |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Local Compose database initialization. If changing them, set a matching `DATABASE_URL`. |
| `CORS_ORIGINS` | Comma-separated exact browser origins. Defaults to the two local Vite origins. |
| `VITE_API_PROXY_TARGET` | Vite development proxy target. Defaults to `127.0.0.1:8000` on the host and is set to `api:8000` in Compose. |
| `VITE_API_URL` | Optional API origin compiled into a separately hosted static frontend. Leave unset when using Vite's `/api` proxy. |
| `SAMPLE_ROOT` | Worker sample repository path. Defaults to the checked-in `sample-repo`; Compose sets `/sample-repo`. |

The app requires PostgreSQL; it does not silently fall back to an in-memory or SQLite database. The API health endpoint checks database connectivity.

## Architecture and data model

- **API:** FastAPI validates fixture choices (`success` or `failure`), creates runs and jobs, handles cancellation/rerun, and returns explicit JSON representations. Schema creation and initial seeding are idempotent at API startup.
- **Worker:** One continuously running worker claims a queued run using a PostgreSQL row lock, executes Lint, Test, and Build sequentially, and saves job/run state and bounded logs. A second worker is not recommended: worker startup recovery treats previously running work as interrupted.
- **Execution:** The worker copies only the bundled fixture, installs dependencies with npm lifecycle scripts disabled, and executes the fixed `npm run lint`, `npm run test -- --run`, and `npm run build` commands with `shell=False` on POSIX, bounded timeouts, process-tree cancellation, and a restricted child environment. On Windows, npm's fixed command line is passed through the platform command interpreter; no command or repository path is accepted from the API. Do not add user-controlled repositories or scripts without introducing a stronger isolation boundary.
- **Polling:** The frontend requests runs every two seconds. Each run response includes its ordered jobs, statuses, timing, exit codes, and logs.
- **Database:** `projects` stores the sample project metadata; `pipelines` references a project and stores step configuration; `runs` references a pipeline and stores fixture, lifecycle timestamps, worker/cancellation state and failure reason; `jobs` references a run and stores ordered step status, exit code, bounded output and timing. Foreign keys and ORM relationships are defined in `backend/app/models.py`.
- **Schema evolution:** Startup uses SQLAlchemy `create_all` for missing tables and does not drop or reset data. There is no versioned migration framework yet; use explicit migrations before changing an existing production schema.
- **Cancellation/failures:** Queued runs can be cancelled immediately. For active runs the API records a cancellation request; the worker stops the active process tree and persists the final cancelled state. A nonzero command marks that job and run failed and skips later jobs. Timeouts and missing executables are reported as failures.

The worker executes trusted, bundled sample code directly in its own service. Run the worker as a non-root account on a trusted machine; it is not a multi-tenant sandbox. A job can use network only during dependency installation; lint/test/build run without application-provided credentials. Do not expose the unauthenticated API publicly without authentication, rate limiting, and a stronger execution sandbox.

## Tests and verification

From the project root:

```powershell
$env:PYTHONPATH = "backend"
python -m pytest backend/tests -q
Set-Location frontend
npm run build
```

For an end-to-end check, start the full Compose stack, click **Run pipeline**, and verify the selected run ends as `passed` with Lint, Test, and Build all `passed`. Use **Failure demo** and verify the run and Test job end as `failed` while Build is `skipped`. You can also inspect the worker with `docker compose logs -f worker`.

## Deployment plan

Deployment is not performed by this repository setup. Use separate services that share a managed PostgreSQL database:

1. **Provision PostgreSQL** (for example Neon or Supabase). Set a private `DATABASE_URL` for both the API and worker; do not use the Compose `db` hostname or local example password in production. Back up the database and retain existing records.
2. **Deploy the API as a web service** from the repository root using `backend/Dockerfile`, start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, and set `DATABASE_URL` plus `CORS_ORIGINS` to the exact deployed frontend origin. Configure the platform health check to `/api/health`.
3. **Deploy one persistent background worker** from the same image and repository, with start command `python -m app.worker`, the same private `DATABASE_URL`, and `SAMPLE_ROOT=/sample-repo`. The image includes Node/npm and the trusted sample fixture. Keep the worker running and do not scale it beyond one without changing recovery/claim semantics.
4. **Deploy the frontend** to a static host such as Netlify or Vercel with root directory `frontend`, build command `npm run build`, and output directory `dist`. Set `VITE_API_URL` at build time to the deployed API origin (no trailing slash), and redeploy the frontend whenever this value changes. Set the API's `CORS_ORIGINS` to this static site origin.
5. **Verify** API health, trigger a successful run, confirm all jobs pass and logs persist, then exercise the failure demo and cancellation flow. Review API/worker logs and configure database backups/retention.

The API and worker may use the same container image but must run as separate processes/services so API restarts do not interrupt queue polling and background jobs. A sleeping/free web service or stopped background worker leaves queued work unprocessed; a reliable live demo needs an always-on worker and a PostgreSQL service whose data is retained by the provider. Check current provider plan limits before choosing a free tier. The current application has no user authentication, and deployment does not enable it automatically.
