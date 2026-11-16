# AGENTS.md — Site Progress Monitor

AI-assisted construction progress monitoring (MVP). Read `README.md`, then `docs/architecture.md` and `docs/security.md`.

## Layout
`supabase/migrations/` (schema + RLS, the source of truth) · `backend/cpm/{api,pipeline,worker,core}` · `web/` (Next.js 16: note `proxy.ts`, not `middleware.ts`; read `web/node_modules/next/dist/docs/` before changing framework APIs).

## Commands
```bash
cd backend && uv sync && uv run pytest && uv run ruff check .
cd web && npm test && npm run lint && npm run typecheck && npm run build
```
Backend tests need local PostgreSQL 16 binaries (`initdb`, `pg_ctl`).

## Rules
1. AI proposes, admin approves. Never auto-publish; never compute final progress with the model; never fabricate observations when AI is unconfigured or fails.
2. Unknown is not 0: unassessable packages retain their previous approved value.
3. Authorization in FastAPI **and** Postgres RLS. User-initiated queries run through `user_tx` (RLS applies); `service_tx` is for the worker only.
4. Roles come from `public.profiles`, never from token claims or client input. Service-role key never reaches `web/`.
5. Published reports are immutable snapshots. Schema changes only via new migration files (never edit applied ones).
6. Postgres is the queue (`claim_next_job`). Do not add Redis/Celery/Kafka/microservices.
7. All AI output goes through Pydantic validation and reference checks (`pipeline/ai.py`); model calls go through the `VisionProvider` interface so tests use scripted providers. Never call a real model in tests.
8. Keep the MVP small: no billing, multi-tenancy, mobile apps, real-time collaboration, GIS/3D, custom model training.
