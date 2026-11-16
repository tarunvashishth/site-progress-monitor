# Deployment & external setup

## Supabase
1. Create a project. Apply `supabase/migrations/*.sql` (CLI `supabase db push`, or paste in order into the SQL editor).
2. Authentication → enable email/password; decide on email confirmation. Add your web URL to *Site URL / Redirect URLs*.
3. Storage: migrations create private buckets `drone-videos` (MP4/MOV, 2 GB limit) and `video-frames` (JPEG). **Check your plan's maximum upload size** (the free tier caps files far below drone-video sizes) and raise it in Storage settings.
   For files > ~6 MB Supabase recommends resumable (TUS) uploads; the MVP uses a single signed PUT with progress. Switch to TUS if your connections are unreliable.
4. Copy keys: public URL + anon key → `web`; service-role key, DB connection string, JWT secret (or leave empty for JWKS) → `backend`.

## API + worker (Docker)
`backend/Dockerfile` builds one image (includes FFmpeg). Run it twice: default command = API, `python -m cpm.worker.main` = worker (persistent, single instance for the MVP).
`docker-compose.yml` shows both. Use the Supabase **direct** Postgres connection (the API uses `SET ROLE`, which transaction poolers may not allow).
Health check: `GET /healthz`. API docs: `/docs`.

## Frontend
Deploy `web/` to Vercel (or any Next.js host). Set `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_MAX_VIDEO_MB`.
Set the API's `WEB_ORIGIN` to the deployed web origin.

## Qwen3-VL inference
The worker needs an OpenAI-compatible **chat completions** endpoint that accepts `image_url` parts (data URLs). Example with vLLM on a GPU host:
```bash
vllm serve <qwen3-vl-model-id> --port 8000 --max-model-len 32768 --limit-mm-per-prompt '{"image": 30}'
```
Then set `QWEN_VL_BASE_URL=http://<host>:8000/v1`, `QWEN_VL_MODEL=<served model name>` (and `QWEN_VL_API_KEY` if you enabled one).
Nothing about the model name or endpoint is hard-coded. **Verify on your deployment**: send one analysis and check that observations parse; if the
server rejects `response_format`, set `QWEN_VL_JSON_MODE=false` (the adapter also retries once without it on HTTP 400). Reduce `MAX_FRAMES` if the
model's image limit or context is smaller. Without configuration the worker marks analysis *unavailable*, keeps the frames, and you can Retry later.

## Using a free hosted vision model instead of self-hosting
Any provider that exposes an OpenAI-compatible `/chat/completions` endpoint and accepts `image_url` data URLs works; the product's preferred model is
Qwen3-VL, but the model name is configuration and is recorded on every analysis (`ai_analyses.model_name`).
```
QWEN_VL_BASE_URL=<provider's OpenAI-compatible base URL>     # e.g. Google's is https://generativelanguage.googleapis.com/v1beta/openai
QWEN_VL_API_KEY=<your key>                                   # put it in backend/.env only, never in chat or the web app
QWEN_VL_MODEL=<a vision-capable model id from the provider's list>
QWEN_VL_JSON_MODE=true                                       # the adapter retries once without it if the provider returns HTTP 400
```
Free tiers have small request-size and per-minute limits, so send fewer, smaller frames:
```
MAX_FRAMES=8
FRAME_MAX_SIDE=768
```
Notes: (1) video frames are sent to the provider, so check its data-use terms for free tiers before using real site footage;
(2) rate-limit errors (HTTP 429) are treated as transient: the job is re-queued and retried up to 3 times; use **Retry** afterwards;
(3) quality varies by model; the admin review step exists precisely because AI output is only a suggestion.

## Netlify (frontend) — what was done and how to redeploy
`web/netlify.toml` builds with `next build` and loads `@netlify/plugin-nextjs` (required for server rendering and the auth proxy; without the plugin Netlify
publishes the raw `.next` folder as static files and every route returns 404). It also holds the **public** build values (`NEXT_PUBLIC_*`); never put secrets there.
- Live site: https://site-progress-monitor-mvp.netlify.app (Netlify project `site-progress-monitor-mvp`).
- `NEXT_PUBLIC_API_URL` is currently `http://localhost:8000`, so the deployed UI only talks to an API running on the same machine as the browser.
  After hosting the API, change it in `web/netlify.toml` and redeploy, and set the API's `WEB_ORIGIN` to the Netlify URL (CORS allows one origin).
- Before uploading from a working copy, delete `web/.next` and `web/.netlify` (large, regenerable); a bloated upload returned HTTP 500.
- Add the Netlify URL to Supabase Auth → URL configuration (Site URL / redirect URLs) before relying on email confirmation or password reset links.

## Free hosting recipe (all $0, no card)
| Part | Host | Notes |
|---|---|---|
| DB / Auth / Storage | Supabase free | Free plan caps uploads at 50 MB per file; use short clips or upgrade for real drone video |
| Frontend | Netlify free | Already configured (`web/netlify.toml`) |
| API + worker | Hugging Face Docker Space (free CPU, 16 GB RAM) | One container runs both (`backend/start.sh`); sleeps after ~48 h idle, queued jobs resume on wake |
| AI | OpenRouter / Google free tier | `QWEN_VL_*` secrets, see above |

1. Create a Space at huggingface.co/new-space (SDK: Docker, blank) and a **write** token at huggingface.co/settings/tokens.
2. `HF_TOKEN=hf_xxx deploy/hf-space.sh <user>/<space>`
3. Space → Settings → *Variables and secrets*: add every key from `backend/.env.example` (use the Supabase **direct** DB string, or the session pooler if direct is IPv6-only and unreachable), with `WEB_ORIGIN=https://site-progress-monitor-mvp.netlify.app`.
4. Set `NEXT_PUBLIC_API_URL=https://<user>-<space>.hf.space` in `web/netlify.toml` and redeploy the frontend. Check `/healthz`.

## Free alternative: Cloudflare Tunnel (API + worker on your own machine)
Cloudflare's free plan cannot run the Python/FFmpeg worker, but a Tunnel exposes a local Docker stack over free HTTPS:
1. Fill `backend/.env` (set `WEB_ORIGIN` to the Netlify URL), then `docker compose --profile tunnel up --build -d`.
2. `docker compose logs tunnel | grep trycloudflare` gives the API URL; put it in `NEXT_PUBLIC_API_URL` (`web/netlify.toml`) and redeploy the frontend.
3. The quick-tunnel URL changes on every restart. For a stable URL, create a named tunnel in Cloudflare Zero Trust (needs a domain on Cloudflare) and use `command: tunnel run` with `TUNNEL_TOKEN`.
The API is only reachable while the machine is on.

## Web app on the VM too (`https://spm.cuelatch.com`)
`docker compose --profile tunnel up -d --build` also builds `web/Dockerfile` (Next.js, `next start`) as the `web` service on host port `WEB_PORT` (3010 on the VM).
The named Cloudflare tunnel routes `spm.cuelatch.com` to `http://web:3000` and `spm-api.cuelatch.com` to `http://api:8000` (ingress is managed in Cloudflare Zero Trust).
The API's `WEB_ORIGIN` lists both web origins, comma-separated (Netlify and the VM), and Supabase Auth's Site URL / redirect URLs include both. Netlify stays as a spare copy.

## Current deployment (Oracle Always Free VM)
API + worker + a named Cloudflare Tunnel (`https://spm-api.cuelatch.com`, token in the VM's `~/site-progress-monitor/.env` as `TUNNEL_TOKEN`) run from `~/site-progress-monitor` on the Oracle ARM VM (`API_PORT=8010`, since 8000 is used there):
`DOCKER_CONFIG=$HOME/.dockercfg docker compose --profile tunnel up -d`. The VM is IPv4-only, so `DATABASE_URL` uses the Supabase **session pooler**
(`cpm_api.<ref>@aws-0-ap-south-1.pooler.supabase.com:5432`). The hostname is stable; ingress is managed in Cloudflare Zero Trust.
