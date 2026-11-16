-- Triggers and functions: updated_at, signup->profile, weights=100, report immutability, job claiming.

create function public.set_updated_at() returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end $$;

create trigger profiles_updated  before update on public.profiles          for each row execute function public.set_updated_at();
create trigger projects_updated  before update on public.projects          for each row execute function public.set_updated_at();
create trigger packages_updated  before update on public.work_packages     for each row execute function public.set_updated_at();
create trigger videos_updated    before update on public.drone_videos       for each row execute function public.set_updated_at();
create trigger jobs_updated      before update on public.video_processing_jobs for each row execute function public.set_updated_at();
create trigger observations_updated before update on public.ai_observations for each row execute function public.set_updated_at();
create trigger reports_updated   before update on public.progress_reports   for each row execute function public.set_updated_at();

-- New auth user -> profile with role ALWAYS 'client'. Metadata is never trusted for the role.
create function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  insert into public.profiles (id, email, full_name, role)
  values (new.id, coalesce(new.email, ''), coalesce(new.raw_user_meta_data ->> 'full_name', ''), 'client');
  return new;
end $$;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- Work-package weights of a project must total exactly 100 (checked at COMMIT so a whole
-- configuration can be replaced in one transaction). A project with no packages is allowed
-- only transiently / for deletion; the API requires at least one package.
create function public.check_work_package_weights() returns trigger
language plpgsql security definer set search_path = '' as $$
declare pid uuid; total numeric; n int;
begin
  foreach pid in array array[coalesce(new.project_id, old.project_id), old.project_id] loop
    continue when pid is null;
    select coalesce(sum(weight_percentage), 0), count(*) into total, n
      from public.work_packages where project_id = pid;
    if n > 0 and total <> 100 then
      raise exception 'work package weights for project % total %, must total exactly 100', pid, total
        using errcode = '23514';
    end if;
  end loop;
  return null;
end $$;
create constraint trigger work_package_weights_total
  after insert or update or delete on public.work_packages
  deferrable initially deferred for each row execute function public.check_work_package_weights();

-- Published reports never change (nor can they be deleted). Unpublishing is intentionally unsupported.
create function public.protect_published_reports() returns trigger
language plpgsql as $$
begin
  if old.status = 'published' then
    raise exception 'published reports are immutable' using errcode = '55000';
  end if;
  if tg_op = 'DELETE' then return old; end if;
  return new;
end $$;
create trigger reports_immutable before update or delete on public.progress_reports
  for each row execute function public.protect_published_reports();

-- A published report must be the video's own analysis snapshot: frozen at publish time.
-- (Application publishes in one UPDATE draft -> published; this guards other transitions.)
create function public.guard_report_publish() returns trigger
language plpgsql as $$
begin
  if new.status = 'published' and old.status = 'draft' then
    if jsonb_array_length(new.package_progress_snapshot) = 0 then
      raise exception 'cannot publish a report without package progress' using errcode = '23514';
    end if;
  end if;
  return new;
end $$;
create trigger reports_publish_guard before update on public.progress_reports
  for each row execute function public.guard_report_publish();

-- Atomically claim the next job (SKIP LOCKED). Re-claims jobs whose worker died (stale lock).
create function public.claim_next_job(p_stale_after interval default interval '30 minutes')
returns setof public.video_processing_jobs
language plpgsql security definer set search_path = '' as $$
declare j public.video_processing_jobs;
begin
  -- jobs that died repeatedly are failed for good
  with dead as (
    update public.video_processing_jobs
       set status = 'failed', completed_at = now(),
           error_message = coalesce(error_message, 'worker timed out')
     where status = 'running' and locked_at < now() - p_stale_after and attempts >= max_attempts
    returning video_id)
  update public.drone_videos v set status = 'failed',
         processing_error = coalesce(v.processing_error, 'processing timed out')
    from dead where v.id = dead.video_id;

  select * into j from public.video_processing_jobs
   where status = 'queued'
      or (status = 'running' and locked_at < now() - p_stale_after and attempts < max_attempts)
   order by created_at
   for update skip locked limit 1;
  if not found then return; end if;

  update public.video_processing_jobs
     set status = 'running', attempts = attempts + 1, locked_at = now(),
         started_at = coalesce(started_at, now())
   where id = j.id returning * into j;
  return next j;
end $$;
revoke execute on function public.claim_next_job(interval) from public, anon, authenticated;
grant execute on function public.claim_next_job(interval) to service_role;

revoke execute on function public.handle_new_user() from public, anon, authenticated;
revoke execute on function public.check_work_package_weights() from public, anon, authenticated;
