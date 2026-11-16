-- Day-to-day comparison + completed-site reference images.
-- AI still only proposes: nothing here changes how progress is computed or published.

-- 1) Which earlier video an analysis was compared against (chosen by the admin or defaulted by the API).
alter table public.video_processing_jobs
  add column compare_to_video_id uuid references public.drone_videos (id) on delete set null;
alter table public.ai_analyses
  add column compare_to_video_id uuid;
alter table public.ai_analyses
  add constraint ai_analyses_compare_fk foreign key (compare_to_video_id, project_id)
    references public.drone_videos (id, project_id) on delete set null (compare_to_video_id);

-- 2) Reference images of the COMPLETED site (renders, elevations, design visuals). Admin-only.
create table public.reference_images (
  id                uuid primary key default gen_random_uuid(),
  project_id        uuid not null references public.projects (id) on delete cascade,
  work_package_id   uuid,
  storage_path      text not null unique,
  original_filename text not null,
  caption           text check (caption is null or length(caption) <= 500),
  created_by        uuid references public.profiles (id) on delete set null,
  created_at        timestamptz not null default now(),
  foreign key (work_package_id, project_id) references public.work_packages (id, project_id)
    on delete set null (work_package_id)
);
create index reference_images_project_idx on public.reference_images (project_id, created_at);

-- Keep the prompt small enough for free-tier vision endpoints: at most 6 per project.
create function public.limit_reference_images() returns trigger
language plpgsql set search_path = '' as $$
begin
  if (select count(*) from public.reference_images where project_id = new.project_id) >= 6 then
    raise exception 'a project can have at most 6 reference images' using errcode = '23514';
  end if;
  return new;
end $$;
create trigger reference_images_limit before insert on public.reference_images
  for each row execute function public.limit_reference_images();
revoke execute on function public.limit_reference_images() from public, anon, authenticated;

alter table public.reference_images enable row level security;
grant select, insert, update, delete on public.reference_images to authenticated;
create policy reference_images_admin on public.reference_images for all to authenticated
  using (public.is_admin()) with check (public.is_admin());

-- 3) Private bucket; clients never read it (design references are not part of published reports).
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types) values
  ('reference-images', 'reference-images', false, 10485760, array['image/jpeg'])
on conflict (id) do nothing;
create policy storage_admin_reference on storage.objects for all to authenticated
  using (bucket_id = 'reference-images' and public.is_admin())
  with check (bucket_id = 'reference-images' and public.is_admin());
