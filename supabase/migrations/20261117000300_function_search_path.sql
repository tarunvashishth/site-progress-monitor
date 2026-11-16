-- Pin search_path on trigger functions (Supabase linter 0011).
-- Note: is_admin()/is_project_member()/video_is_published_for_member() are intentionally executable by
-- `authenticated`: RLS policies evaluate as the caller. They only return booleans about the caller's own access.
alter function public.set_updated_at()             set search_path = '';
alter function public.protect_published_reports()  set search_path = '';
alter function public.guard_report_publish()       set search_path = '';
