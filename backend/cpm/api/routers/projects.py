from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, model_validator

from cpm.api.auth import Admin, User
from cpm.core import progress
from cpm.core.db import all_, one, user_tx
from cpm.core.errors import ApiError, NotFound

router = APIRouter()
Pct = Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]


class PackageIn(BaseModel):
    id: UUID | None = None
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    weight_percentage: Annotated[Decimal, Field(gt=0, le=100, max_digits=5, decimal_places=2)]
    initial_approved_percentage: Pct  # required baseline: unknown is never silently 0
    display_order: int = 0


def _check_packages(pkgs: list[PackageIn]) -> None:
    try:
        progress.validate_weights([p.weight_percentage for p in pkgs])
    except ValueError as e:
        raise ApiError(422, "invalid_weights", str(e)) from None
    if len({p.name.strip().lower() for p in pkgs}) != len(pkgs):
        raise ApiError(422, "duplicate_package", "Work package names must be unique")


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    location: str | None = None
    description: str | None = None
    start_date: date | None = None
    work_packages: list[PackageIn]

    @model_validator(mode="after")
    def _v(self):
        _check_packages(self.work_packages)
        return self


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    location: str | None = None
    description: str | None = None
    start_date: date | None = None
    status: str | None = Field(default=None, pattern="^(active|on_hold|completed|archived)$")


class PackagesIn(BaseModel):
    work_packages: list[PackageIn]

    @model_validator(mode="after")
    def _v(self):
        _check_packages(self.work_packages)
        return self


class MemberIn(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+$")


def project_progress(c, pid) -> dict:
    """Overall + per-package approved progress, derived from the latest PUBLISHED report only."""
    pkgs = all_(
        c,
        "select * from public.work_packages where project_id=%s order by display_order, name",
        (pid,),
    )
    last = one(
        c,
        "select id, video_id, published_at, package_progress_snapshot, assessment_coverage_percentage,"
        " summary from public.progress_reports where project_id=%s and status='published'"
        " order by published_at desc limit 1",
        (pid,),
    )
    cur = progress.current_values(pkgs, last["package_progress_snapshot"] if last else None)
    items = [
        {
            "work_package_id": str(p["id"]),
            "name": p["name"],
            "description": p["description"],
            "weight_percentage": p["weight_percentage"],
            "approved_percentage": cur[str(p["id"])],
        }
        for p in pkgs
    ]
    return {
        "overall_progress": progress.overall_progress(items) if items else Decimal(0),
        "work_packages": items,
        "latest_report": {
            k: last[k] for k in ("id", "published_at", "summary", "assessment_coverage_percentage")
        }
        if last
        else None,
    }


def _project_or_404(c, pid):
    p = one(c, "select * from public.projects where id=%s", (pid,))  # RLS: members/admin only
    if not p:
        raise NotFound("Project")
    return p


@router.get("/me")
def me(user: User):
    return user


@router.get("/dashboard")
def dashboard(admin: Admin):
    with user_tx(admin.id) as c:
        return one(
            c,
            """select
          (select count(*) from public.projects) as total_projects,
          (select count(*) from public.projects where status='active') as active_projects,
          (select count(*) from public.drone_videos where status <> 'pending_upload') as total_videos,
          (select count(*) from public.progress_reports where status='draft') as reports_awaiting_review""",
        ) | {
            "recent_activity": all_(
                c,
                """select 'report' as kind, r.id, p.name as project, r.status::text as detail,
              coalesce(r.published_at, r.updated_at) as at from public.progress_reports r
              join public.projects p on p.id=r.project_id
              union all select 'video', v.id, p.name, v.status::text, v.updated_at from public.drone_videos v
              join public.projects p on p.id=v.project_id where v.status <> 'pending_upload'
              order by at desc limit 10""",
            )
        }


@router.get("/clients")
def clients(admin: Admin):
    with user_tx(admin.id) as c:
        return all_(
            c, "select id, email, full_name from public.profiles where role='client' order by email"
        )


@router.get("/projects")
def list_projects(user: User, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    with user_tx(user.id) as c:
        rows = all_(
            c,
            "select p.*, count(*) over() as total from public.projects p "
            "order by p.created_at desc limit %s offset %s",
            (limit, offset),
        )
        items = []
        for r in rows:
            pr = project_progress(c, r["id"])
            items.append(
                {
                    **{k: r[k] for k in ("id", "name", "location", "status", "start_date")},
                    "overall_progress": pr["overall_progress"],
                    "latest_report": pr["latest_report"],
                }
            )
        return {
            "items": items,
            "total": rows[0]["total"] if rows else 0,
            "limit": limit,
            "offset": offset,
        }


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, admin: Admin):
    with user_tx(admin.id) as c:
        p = one(
            c,
            "insert into public.projects (name, location, description, start_date, created_by) "
            "values (%s,%s,%s,%s,%s) returning *",
            (body.name, body.location, body.description, body.start_date, admin.id),
        )
        for i, w in enumerate(body.work_packages):
            c.execute(
                "insert into public.work_packages (project_id,name,description,weight_percentage,"
                "initial_approved_percentage,display_order) values (%s,%s,%s,%s,%s,%s)",
                (
                    p["id"],
                    w.name.strip(),
                    w.description,
                    w.weight_percentage,
                    w.initial_approved_percentage,
                    w.display_order or i,
                ),
            )
        return {**p, **project_progress(c, p["id"])}


@router.get("/projects/{project_id}")
def get_project(project_id: UUID, user: User):
    with user_tx(user.id) as c:
        p = _project_or_404(c, project_id)
        history = all_(
            c,
            "select id, published_at, overall_progress_percentage, assessment_coverage_percentage "
            "from public.progress_reports where project_id=%s and status='published' "
            "order by published_at",
            (project_id,),
        )
        return {**p, **project_progress(c, project_id), "history": history}


@router.patch("/projects/{project_id}")
def patch_project(project_id: UUID, body: ProjectPatch, admin: Admin):
    changes = body.model_dump(exclude_unset=True)
    with user_tx(admin.id) as c:
        _project_or_404(c, project_id)
        if changes:
            sets = ", ".join(f"{k}=%s" for k in changes)
            c.execute(
                f"update public.projects set {sets} where id=%s", (*changes.values(), project_id)
            )
        return _project_or_404(c, project_id)


@router.post("/projects/{project_id}/work-packages")
def sync_packages(project_id: UUID, body: PackagesIn, admin: Admin):
    """Replace the project's package configuration atomically (weights must total 100 at commit)."""
    with user_tx(admin.id) as c:
        _project_or_404(c, project_id)
        existing = {
            str(r["id"])
            for r in all_(
                c, "select id from public.work_packages where project_id=%s", (project_id,)
            )
        }
        keep = {str(w.id) for w in body.work_packages if w.id}
        if keep - existing:
            raise ApiError(
                422, "unknown_package", "A work package id does not belong to this project"
            )
        c.execute("set constraints all deferred")
        for gone in existing - keep:
            c.execute("delete from public.work_packages where id=%s", (gone,))
        for i, w in enumerate(body.work_packages):
            args = (
                w.name.strip(),
                w.description,
                w.weight_percentage,
                w.initial_approved_percentage,
                w.display_order or i,
            )
            if w.id:
                c.execute(
                    "update public.work_packages set name=%s, description=%s, weight_percentage=%s,"
                    "initial_approved_percentage=%s, display_order=%s where id=%s",
                    (*args, w.id),
                )
            else:
                c.execute(
                    "insert into public.work_packages (name,description,weight_percentage,"
                    "initial_approved_percentage,display_order,project_id) values (%s,%s,%s,%s,%s,%s)",
                    (*args, project_id),
                )
        c.execute("set constraints all immediate")  # surfaces weight violations here, inside the tx
        return project_progress(c, project_id)


@router.get("/projects/{project_id}/members")
def members(project_id: UUID, admin: Admin):
    with user_tx(admin.id) as c:
        _project_or_404(c, project_id)
        return all_(
            c,
            "select pr.id, pr.email, pr.full_name from public.project_members m "
            "join public.profiles pr on pr.id=m.user_id where m.project_id=%s order by pr.email",
            (project_id,),
        )


@router.post("/projects/{project_id}/members", status_code=201)
def add_member(project_id: UUID, body: MemberIn, admin: Admin):
    with user_tx(admin.id) as c:
        _project_or_404(c, project_id)
        u = one(
            c,
            "select id, role, email from public.profiles where lower(email)=lower(%s)",
            (body.email,),
        )
        if not u:
            raise ApiError(404, "user_not_found", "No registered account with that email")
        if u["role"] != "client":
            raise ApiError(422, "not_a_client", "Only client accounts can be assigned to projects")
        c.execute(
            "insert into public.project_members (project_id,user_id) values (%s,%s) "
            "on conflict do nothing",
            (project_id, u["id"]),
        )
        return {"id": u["id"], "email": u["email"]}


@router.delete("/projects/{project_id}/members/{user_id}", status_code=204)
def remove_member(project_id: UUID, user_id: UUID, admin: Admin):
    with user_tx(admin.id) as c:
        _project_or_404(c, project_id)
        c.execute(
            "delete from public.project_members where project_id=%s and user_id=%s",
            (project_id, user_id),
        )
