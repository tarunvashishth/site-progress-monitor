# Security model

## Authentication & roles
- Supabase Auth. Every new user gets a `profiles` row with role **client** (DB trigger; user metadata is ignored).
- The API verifies the JWT (HS256 secret, or the project's JWKS) and then loads the role **from `profiles`**. Role/`user_metadata`/`app_metadata` claims in a token are never trusted (tested).
- Users can only update `profiles.full_name` (column-level grant + row policy); they cannot change `role`.

## Authorization (defense in depth)
1. **API**: `Admin` dependency on every mutating/admin endpoint; client endpoints are project-scoped.
2. **RLS**: the API runs user-initiated queries as the caller (`SET LOCAL ROLE authenticated` + JWT claims), so Postgres policies also apply to API reads/writes.
   Clients can read only published reports, their videos/frames, and work packages/projects they are members of. Drafts, observations, analyses and jobs are admin-only.
3. **DB constraints/triggers**: weights total 100 (deferred, enforced at commit), published reports immutable, composite FKs prevent cross-project links.
4. **Storage**: private buckets, MIME/size limits, signed URLs only. Client-facing signed URLs are issued after an RLS-checked read.

## Secrets
The service-role key and `DATABASE_URL` exist only in backend/worker environments. The web app only has the public URL + anon key (`web/.env.example`).
Never log tokens: the API logs no Authorization headers and returns generic 500 messages.

## Other controls
Filename sanitization with server-chosen storage paths; video type/size/date validated server-side; CORS restricted to `WEB_ORIGIN`;
request bodies validated by Pydantic; uniform error format.

## Admin bootstrap
Register the person in the app, then run `docs/admin-bootstrap.sql` as the project owner. There is intentionally no API or UI to grant admin.

## Not included (MVP)
Rate limiting, audit log table, MFA enforcement, virus scanning of uploads. Add a gateway/WAF rate limit before exposing the API publicly.
