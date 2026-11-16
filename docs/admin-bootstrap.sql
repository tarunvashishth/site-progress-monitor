-- Promote the FIRST administrator. Run in the Supabase SQL editor (project owner) or via psql as the postgres role.
-- 1) Register the person normally in the app. Every new account is a 'client'; no signup path can set a role.
-- 2) Then run (replace the email):
update public.profiles
   set role = 'admin'
 where email = 'you@company.com'
returning id, email, role;

-- Verify exactly who the admins are:
select id, email, role from public.profiles where role = 'admin';

-- Demote:
-- update public.profiles set role = 'client' where email = 'former.admin@company.com';

-- Why this is safe: authenticated users only have UPDATE on profiles.full_name (column grant) and the row policy
-- limits them to their own row, so a user cannot change role. Roles are read from this table (never from JWT claims).
