-- Authorization. Roles come from public.profiles (set server-side), never from JWT claims/metadata.
-- Admins manage everything. Clients read ONLY published reports (and what they reference) of ASSIGNED projects.
-- The backend/worker use service-level credentials; the API additionally executes user-initiated
-- queries under the caller's identity (SET ROLE authenticated + claims) so these policies apply there too.

create function public.is_admin() returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.profiles where id = auth.uid() and role = 'admin')
$$;

create function public.is_project_member(pid uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.project_members where project_id = pid and user_id = auth.uid())
$$;

-- Client-visible video: a published report references it and the caller is a member of its project.
create function public.video_is_published_for_member(vid uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.progress_reports r
     where r.video_id = vid and r.status = 'published'
       and exists (select 1 from public.project_members m
                    where m.project_id = r.project_id and m.user_id = auth.uid()))
$$;

revoke execute on function public.is_admin(), public.is_project_member(uuid),
  public.video_is_published_for_member(uuid) from public, anon;
grant execute on function public.is_admin(), public.is_project_member(uuid),
  public.video_is_published_for_member(uuid) to authenticated;

-- Least privilege: Supabase grants broadly by default; start from nothing.
revoke all on all tables in schema public from anon, authenticated;
grant select on all tables in schema public to authenticated;
grant insert, update, delete on
  public.projects, public.project_members, public.work_packages, public.drone_videos,
  public.video_processing_jobs, public.video_frames, public.ai_analyses, public.ai_observations,
  public.progress_reports
  to authenticated;
grant update (full_name) on public.profiles to authenticated;  -- role/email/id are NOT writable

alter table public.profiles               enable row level security;
alter table public.projects               enable row level security;
alter table public.project_members        enable row level security;
alter table public.work_packages          enable row level security;
alter table public.drone_videos           enable row level security;
alter table public.video_processing_jobs  enable row level security;
alter table public.video_frames           enable row level security;
alter table public.ai_analyses            enable row level security;
alter table public.ai_observations        enable row level security;
alter table public.progress_reports       enable row level security;

create policy profiles_select on public.profiles for select to authenticated
  using (id = auth.uid() or public.is_admin());
create policy profiles_update_self on public.profiles for update to authenticated
  using (id = auth.uid()) with check (id = auth.uid());

create policy projects_select on public.projects for select to authenticated
  using (public.is_admin() or public.is_project_member(id));
create policy projects_admin on public.projects for all to authenticated
  using (public.is_admin()) with check (public.is_admin());

create policy members_select on public.project_members for select to authenticated
  using (public.is_admin() or user_id = auth.uid());
create policy members_admin on public.project_members for all to authenticated
  using (public.is_admin()) with check (public.is_admin());

create policy packages_select on public.work_packages for select to authenticated
  using (public.is_admin() or public.is_project_member(project_id));
create policy packages_admin on public.work_packages for all to authenticated
  using (public.is_admin()) with check (public.is_admin());

create policy videos_select on public.drone_videos for select to authenticated
  using (public.is_admin() or public.video_is_published_for_member(id));
create policy videos_admin on public.drone_videos for all to authenticated
  using (public.is_admin()) with check (public.is_admin());

create policy frames_select on public.video_frames for select to authenticated
  using (public.is_admin() or public.video_is_published_for_member(video_id));
create policy frames_admin on public.video_frames for all to authenticated
  using (public.is_admin()) with check (public.is_admin());

-- Draft AI output is never visible to clients: jobs, analyses and observations are admin-only.
create policy jobs_admin on public.video_processing_jobs for all to authenticated
  using (public.is_admin()) with check (public.is_admin());
create policy analyses_admin on public.ai_analyses for all to authenticated
  using (public.is_admin()) with check (public.is_admin());
create policy observations_admin on public.ai_observations for all to authenticated
  using (public.is_admin()) with check (public.is_admin());

create policy reports_select on public.progress_reports for select to authenticated
  using (public.is_admin() or (status = 'published' and public.is_project_member(project_id)));
create policy reports_admin on public.progress_reports for all to authenticated
  using (public.is_admin())
  with check (public.is_admin() and (status = 'draft' or published_by = auth.uid()));

-- Storage: private buckets. Clients never get direct bucket listing; the API issues signed URLs
-- after checking membership + publication. These policies are defense in depth.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types) values
  ('drone-videos', 'drone-videos', false, 2147483648, array['video/mp4', 'video/quicktime']),
  ('video-frames', 'video-frames', false, 10485760, array['image/jpeg'])
on conflict (id) do nothing;

create policy storage_admin_all on storage.objects for all to authenticated
  using (bucket_id in ('drone-videos', 'video-frames') and public.is_admin())
  with check (bucket_id in ('drone-videos', 'video-frames') and public.is_admin());

create policy storage_client_read_videos on storage.objects for select to authenticated
  using (bucket_id = 'drone-videos' and exists (
    select 1 from public.drone_videos v where v.storage_path = storage.objects.name));

create policy storage_client_read_frames on storage.objects for select to authenticated
  using (bucket_id = 'video-frames' and exists (
    select 1 from public.video_frames f
     where f.storage_path = storage.objects.name or f.thumbnail_path = storage.objects.name));
