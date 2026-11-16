-- Construction Progress Monitor — core schema.
-- Access control is in 20261117000200_rls.sql; functions/triggers in ..._functions.sql.

create type public.user_role         as enum ('admin', 'client');
create type public.project_status    as enum ('active', 'on_hold', 'completed', 'archived');
create type public.video_status      as enum ('pending_upload', 'uploaded', 'queued', 'processing', 'analyzed', 'failed');
create type public.job_type          as enum ('process', 'analyze');
create type public.job_status        as enum ('queued', 'running', 'succeeded', 'failed');
create type public.analysis_status   as enum ('running', 'completed', 'failed', 'unavailable');
create type public.review_status     as enum ('pending', 'approved', 'rejected');
create type public.report_status     as enum ('draft', 'published');
create type public.observation_category as enum
  ('foundation', 'concrete', 'structural', 'masonry', 'roofing', 'exterior', 'site', 'issue', 'other');
create type public.observation_type  as enum
  ('newly_visible', 'ongoing', 'no_visible_change', 'possible_change', 'unclear', 'not_assessable');

create table public.profiles (
  id          uuid primary key references auth.users (id) on delete cascade,
  email       text not null default '',
  full_name   text not null default '',
  role        public.user_role not null default 'client',
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create table public.projects (
  id           uuid primary key default gen_random_uuid(),
  name         text not null check (length(btrim(name)) > 0),
  location     text,
  description  text,
  start_date   date,
  status       public.project_status not null default 'active',
  created_by   uuid references public.profiles (id) on delete set null,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create table public.project_members (
  id          uuid primary key default gen_random_uuid(),
  project_id  uuid not null references public.projects (id) on delete cascade,
  user_id     uuid not null references public.profiles (id) on delete cascade,
  created_at  timestamptz not null default now(),
  unique (project_id, user_id)
);
create index project_members_user_idx on public.project_members (user_id);

-- Weights per project must total exactly 100 (deferred constraint trigger in the functions migration).
-- initial_approved_percentage is the REQUIRED admin-approved baseline: unknown is never treated as 0.
create table public.work_packages (
  id                          uuid primary key default gen_random_uuid(),
  project_id                  uuid not null references public.projects (id) on delete cascade,
  name                        text not null check (length(btrim(name)) > 0),
  description                 text,
  weight_percentage           numeric(5,2) not null check (weight_percentage > 0 and weight_percentage <= 100),
  initial_approved_percentage numeric(5,2) not null check (initial_approved_percentage between 0 and 100),
  display_order               integer not null default 0,
  created_at                  timestamptz not null default now(),
  updated_at                  timestamptz not null default now(),
  unique (id, project_id),
  unique (project_id, name)
);
create index work_packages_project_idx on public.work_packages (project_id, display_order);

create table public.drone_videos (
  id                uuid primary key default gen_random_uuid(),
  project_id        uuid not null references public.projects (id) on delete cascade,
  uploaded_by       uuid references public.profiles (id) on delete set null,
  storage_path      text not null unique,
  original_filename text not null,
  capture_date      date not null,
  description       text,
  duration_seconds  real check (duration_seconds is null or duration_seconds >= 0),
  file_size         bigint check (file_size is null or file_size > 0),
  status            public.video_status not null default 'pending_upload',
  processing_error  text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (id, project_id)
);
create index drone_videos_project_idx on public.drone_videos (project_id, capture_date desc);

create table public.video_processing_jobs (
  id              uuid primary key default gen_random_uuid(),
  video_id        uuid not null references public.drone_videos (id) on delete cascade,
  job_type        public.job_type not null default 'process',
  status          public.job_status not null default 'queued',
  attempts        smallint not null default 0,
  max_attempts    smallint not null default 3,
  force_reanalysis boolean not null default false,
  error_message   text,
  created_by      uuid references public.profiles (id) on delete set null,
  locked_at       timestamptz,
  started_at      timestamptz,
  completed_at    timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
-- at most one active job per video
create unique index video_jobs_one_active_idx on public.video_processing_jobs (video_id)
  where status in ('queued', 'running');
create index video_jobs_poll_idx on public.video_processing_jobs (status, created_at);

create table public.video_frames (
  id                uuid primary key default gen_random_uuid(),
  video_id          uuid not null references public.drone_videos (id) on delete cascade,
  frame_index       integer not null check (frame_index >= 0),
  timestamp_seconds real not null check (timestamp_seconds >= 0),
  storage_path      text not null,
  thumbnail_path    text,
  image_hash        text not null,
  created_at        timestamptz not null default now(),
  unique (video_id, frame_index)
);

create table public.ai_analyses (
  id                  uuid primary key default gen_random_uuid(),
  video_id            uuid not null,
  project_id          uuid not null,
  job_id              uuid unique references public.video_processing_jobs (id) on delete set null,
  model_name          text not null,
  prompt_version      text not null,
  input_fingerprint   text not null,   -- hash(frame hashes, model, prompt, package config)
  status              public.analysis_status not null default 'running',
  raw_response        text,
  structured_response jsonb,
  error_message       text,
  created_at          timestamptz not null default now(),
  completed_at        timestamptz,
  unique (id, project_id),
  foreign key (video_id, project_id) references public.drone_videos (id, project_id) on delete cascade
);
create index ai_analyses_video_idx on public.ai_analyses (video_id, created_at desc);
create index ai_analyses_fingerprint_idx on public.ai_analyses (video_id, input_fingerprint) where status = 'completed';

create table public.ai_observations (
  id               uuid primary key default gen_random_uuid(),
  analysis_id      uuid not null,
  project_id       uuid not null,
  work_package_id  uuid,
  title            text not null check (length(btrim(title)) > 0),
  description      text not null,
  category         public.observation_category not null default 'other',
  observation_type public.observation_type not null,
  confidence       real not null check (confidence between 0 and 1),
  -- [{frame_id, frame_index, timestamp_seconds}] — every observation must cite evidence
  evidence_frames  jsonb not null
    check (jsonb_typeof(evidence_frames) = 'array' and jsonb_array_length(evidence_frames) >= 1),
  review_status    public.review_status not null default 'pending',
  ai_original      jsonb not null,   -- {title, description} as generated, preserved across edits
  edited_by        uuid references public.profiles (id) on delete set null,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  foreign key (analysis_id, project_id) references public.ai_analyses (id, project_id) on delete cascade,
  foreign key (work_package_id, project_id) references public.work_packages (id, project_id)
    on delete set null (work_package_id)
);
create index ai_observations_analysis_idx on public.ai_observations (analysis_id, review_status);

-- Published reports are immutable snapshots (enforced by trigger).
-- Draft: package_progress_snapshot is the admin's working copy. Published: frozen evidence.
create table public.progress_reports (
  id                              uuid primary key default gen_random_uuid(),
  project_id                      uuid not null references public.projects (id) on delete cascade,
  video_id                        uuid not null,
  analysis_id                     uuid,
  status                          public.report_status not null default 'draft',
  overall_progress_percentage     numeric(5,2) check (overall_progress_percentage between 0 and 100),
  assessment_coverage_percentage  numeric(5,2) check (assessment_coverage_percentage between 0 and 100),
  summary                         text not null default '',
  package_progress_snapshot       jsonb not null default '[]'::jsonb check (jsonb_typeof(package_progress_snapshot) = 'array'),
  approved_observations_snapshot  jsonb not null default '[]'::jsonb check (jsonb_typeof(approved_observations_snapshot) = 'array'),
  created_by                      uuid references public.profiles (id) on delete set null,
  published_by                    uuid references public.profiles (id) on delete set null,
  published_at                    timestamptz,
  created_at                      timestamptz not null default now(),
  updated_at                      timestamptz not null default now(),
  unique (video_id),   -- one report per video
  foreign key (video_id, project_id) references public.drone_videos (id, project_id) on delete cascade,
  foreign key (analysis_id, project_id) references public.ai_analyses (id, project_id) on delete set null (analysis_id),
  check (status = 'draft' or (published_at is not null and published_by is not null
         and overall_progress_percentage is not null and assessment_coverage_percentage is not null
         and length(btrim(summary)) > 0))
);
create index progress_reports_project_idx on public.progress_reports (project_id, status, published_at desc);
