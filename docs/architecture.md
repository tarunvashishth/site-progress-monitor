# Architecture & data model

## Flow
1. Admin creates a project with work packages (weights = 100%, each with a required approved baseline).
2. `POST /projects/{id}/videos/upload-url` validates type/size/date, creates a `drone_videos` row (`pending_upload`) and returns a **signed upload URL**.
   The browser PUTs the file straight to private Storage; `POST /videos/{id}/complete` verifies the object exists and queues a job.
3. The worker claims a job (`claim_next_job()`, `SKIP LOCKED`, stale-lock recovery, max 3 attempts), downloads the video, validates it with `ffprobe`,
   samples frames with OpenCV (interval, blur filter, dHash de-duplication, cap), stores frames + thumbnails in a private bucket and inserts `video_frames`.
4. The worker builds the prompt (project + packages + last approved values + up to 3 earlier evidence frames), calls the configured Qwen3-VL endpoint,
   validates the JSON with Pydantic (one repair retry), checks every referenced package id and frame index against real records, and stores
   `ai_analyses` (model, prompt version, raw + structured output) and `ai_observations` (all `pending`) in one transaction.
5. Admin reviews observations (edit / approve / reject), creates a **draft report** whose package items start as AI proposals awaiting a decision
   (accept / set value / keep earlier value), then publishes.
6. Publish (single transaction, row-locked) re-checks everything, computes `overall = Σ weight × approved / 100` and *assessment coverage*, and freezes
   `package_progress_snapshot` + `approved_observations_snapshot`. A trigger makes published reports immutable.
7. Clients read published reports only (RLS + API), with signed URLs for the video and evidence thumbnails.

## Key rules
- Unknown ≠ 0: packages the model can't assess default to **retain** their previous approved value.
- AI timestamps are never trusted: evidence timestamps come from our `video_frames` rows.
- Progress is always derived from the latest *published* snapshot (or the initial baseline), never from AI output.
- Retries are idempotent: one analysis per job (`unique(job_id)`), observations replaced in one transaction, frames inserted all-or-nothing and reused.
- Identical inputs (frame hashes + model + prompt + package state) reuse the stored analysis unless `force`.

## Tables
`profiles, projects, project_members, work_packages, drone_videos, video_processing_jobs, video_frames, ai_analyses, ai_observations, progress_reports`
(see `supabase/migrations/`). Composite foreign keys `(id, project_id)` guarantee a video/analysis/package can never be linked across projects.
