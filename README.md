# Site Progress Monitor (MVP)

Construction companies upload daily drone videos. A worker extracts representative frames and a vision-language model
(Qwen3-VL, via a configurable OpenAI-compatible endpoint) drafts evidence-backed observations and per-package progress
*suggestions*. An administrator reviews, edits and approves them, the backend computes overall progress deterministically,
and the admin publishes a report. Clients see only published reports for projects assigned to them.

**AI never publishes anything.** AI output is a suggestion; progress percentages are computed from admin-approved values only.

```
Next.js (web/) ──► FastAPI (backend/cpm/api) ──► Supabase Postgres (RLS) / Storage / Auth
     │                                                   ▲
     └── signed direct upload ───────────────────────────┤
                         Python worker (backend/cpm/worker): FFmpeg+OpenCV ► Qwen3-VL
```
Modular monolith + one background worker. No Redis/Kafka/Kubernetes: the job queue is a Postgres table claimed with `FOR UPDATE SKIP LOCKED`.

## Repository layout
| Path | Contents |
|---|---|
| `supabase/migrations/` | Schema, triggers/functions, RLS + storage policies (apply in order) |
| `backend/cpm/api` | FastAPI app (`/docs` = OpenAPI) |
| `backend/cpm/pipeline` | Frame extraction, AI adapter, output validation |
| `backend/cpm/worker` | Job loop and runner |
| `backend/tests` | pytest suite (see *Testing*) |
| `web/` | Next.js 16 + Tailwind + shadcn/ui + Recharts |
| `docs/` | Architecture, security model, deployment, admin bootstrap SQL |

## Local development
Prerequisites: Python 3.12 + [uv](https://docs.astral.sh/uv/), Node 20+, FFmpeg (`ffmpeg`, `ffprobe` on PATH), and a Supabase project
(cloud, or local via `supabase start`, which needs Docker).

1. **Database**: link your project and push migrations: `supabase link --project-ref <ref> && supabase db push`
   (or run `supabase/migrations/*.sql` in order in the SQL editor).
2. **Backend**: `cp backend/.env.example backend/.env` and fill it in, then
   ```bash
   cd backend && uv sync
   uv run uvicorn cpm.api.main:app --reload          # API on :8000
   uv run python -m cpm.worker.main                  # worker (separate terminal)
   ```
3. **Frontend**: `cd web && cp .env.example .env.local`, fill in the public Supabase URL/anon key and API URL, then `npm install && npm run dev`.
4. **First admin**: register in the app, then run `docs/admin-bootstrap.sql` (see [docs/security.md](docs/security.md)).
5. **AI**: set `QWEN_VL_BASE_URL` / `QWEN_VL_MODEL` (see [docs/deployment.md](docs/deployment.md)). Without them, videos still upload and frames are
   extracted, but analysis is reported as *unavailable* — nothing is invented. Fix the config and press **Retry**.

Docker: `docker compose up --build` runs the API and worker from `backend/` using `backend/.env`.

## Testing
```bash
cd backend && uv run pytest          # 88 tests: RLS/triggers, API, pipeline, worker
cd backend && uv run ruff check .
cd web && npm test && npm run lint && npm run typecheck && npm run build
```
Backend tests start a throwaway local PostgreSQL 16 (needs `initdb`/`pg_ctl`, e.g. `brew install postgresql@16`) and load a tiny stand-in for
Supabase's `auth`/`storage` schemas (`backend/tests/supabase_shim.sql`), then apply the real migrations.

### Verified on a real Supabase project
Migrations applied; RLS/trigger behaviour re-checked live; real Auth login (ES256 JWT verified via JWKS); real Storage (browser-style signed PUT,
size check, signed download, private bucket, MIME limit, client denial); then API + worker end to end: create project → assign client → upload →
frame extraction → analysis (stub AI) → review → publish → client views report/video/evidence; other client denied; published report immutable.

### What is verified vs. what needs external setup
| Verified by automated tests | **Not verified** (requires your infrastructure) |
|---|---|
| Schema, constraints, RLS, storage policies, weight=100 rule, published-report immutability, job claiming (local Postgres 16) | A browser run through the UI (login form → publish); the Docker images |
| API authn/authz, admin vs client isolation, upload validation, draft→review→publish workflow, deterministic progress math | Qwen3-VL itself: output quality and endpoint compatibility on real drone footage (only a scripted stub endpoint was used) |
| Frame extraction on generated videos, duplicate/blur filtering, AI output validation, provider request shape (mock transport), retries, idempotency | The service-role key path: the real-infrastructure run used a test admin's JWT in its place |
| Frontend: validation, navigation by role, auth form, project lists, observation review, publish flow (jsdom), production build | Browser-level end-to-end flow (no Playwright run), Docker images (Docker not available where this was built) |

## Known limitations
- One report per video; one worker process; per-request DB connections (no pool); no rate limiting yet (put the API behind a gateway/WAF).
- Draft reports are bound to the analysis they were created from; to use a newer analysis, create a new draft for a new video.
- Video playback/frames use signed URLs (1 h); signing happens per request.
- Comparison with earlier captures is limited to up to 3 previous evidence frames given to the model; the model is told to refuse unreliable comparisons, but cannot be forced to.
- Password recovery uses Supabase's built-in flow; there is no custom UI for it yet.
- Deleting projects with published reports is blocked by design (reports are immutable); archive instead.
