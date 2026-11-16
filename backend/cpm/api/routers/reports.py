from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from cpm.api.auth import Admin, User
from cpm.api.deps import get_storage  # noqa: F401
from cpm.api.routers.projects import _project_or_404
from cpm.api.routers.videos import Store
from cpm.core import progress
from cpm.core.config import get_settings
from cpm.core.db import Jsonb, all_, one, user_tx
from cpm.core.errors import ApiError, NotFound

router = APIRouter()


class DraftIn(BaseModel):
    video_id: UUID
    analysis_id: UUID | None = None


class Decision(BaseModel):
    work_package_id: UUID
    decision: Literal["accept", "edit", "retain"]
    approved_percentage: float | None = Field(default=None, ge=0, le=100)


class ReportPatch(BaseModel):
    summary: str | None = Field(default=None, max_length=10000)
    packages: list[Decision] | None = None


class ObservationPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, min_length=1, max_length=5000)
    category: str | None = Field(
        default=None,
        pattern="^(foundation|concrete|structural|masonry|roofing|exterior|site|issue|other)$",
    )
    work_package_id: UUID | None = None
    review_status: Literal["pending", "approved", "rejected"] | None = None


def _packages(c, pid):
    return all_(
        c,
        "select * from public.work_packages where project_id=%s order by display_order, name",
        (pid,),
    )


def _last_snapshot(c, pid, exclude=None):
    r = one(
        c,
        "select package_progress_snapshot s from public.progress_reports where project_id=%s and "
        "status='published' and id is distinct from %s order by published_at desc limit 1",
        (pid, exclude),
    )
    return r["s"] if r else None


def _published_guard(c, analysis_id):
    if one(
        c,
        "select 1 from public.progress_reports where analysis_id=%s and status='published'",
        (analysis_id,),
    ):
        raise ApiError(
            409, "published", "The report for this analysis is published and can no longer change"
        )


def sign_thumbs(storage, paths) -> dict[str, str]:
    s = get_settings()
    return {p: storage.signed_url(s.frames_bucket, p) for p in {p for p in paths if p}}


@router.post("/projects/{project_id}/reports/draft", status_code=201)
def create_draft(project_id: UUID, body: DraftIn, admin: Admin):
    with user_tx(admin.id) as c:
        _project_or_404(c, project_id)
        v = one(
            c,
            "select * from public.drone_videos where id=%s and project_id=%s",
            (body.video_id, project_id),
        )
        if not v:
            raise NotFound("Video")
        if v["status"] != "analyzed":
            raise ApiError(409, "not_analyzed", "The video has not been analysed successfully yet")
        if ex := one(
            c, "select id from public.progress_reports where video_id=%s", (body.video_id,)
        ):
            raise ApiError(
                409,
                "report_exists",
                "A report already exists for this video",
                {"report_id": str(ex["id"])},
            )
        a = one(
            c,
            "select * from public.ai_analyses where video_id=%s and status='completed' and "
            "(%s::uuid is null or id=%s) order by created_at desc limit 1",
            (body.video_id, body.analysis_id, body.analysis_id),
        )
        if not a:
            raise ApiError(409, "no_analysis", "No completed AI analysis available for this video")
        pkgs = _packages(c, project_id)
        cur = progress.current_values(pkgs, _last_snapshot(c, project_id))
        sr = a["structured_response"] or {}
        items = progress.build_draft_items(pkgs, cur, sr.get("package_assessments", []))
        r = one(
            c,
            "insert into public.progress_reports (project_id, video_id, analysis_id, summary, "
            "package_progress_snapshot, created_by) values (%s,%s,%s,%s,%s,%s) returning id",
            (project_id, body.video_id, a["id"], sr.get("summary", ""), Jsonb(items), admin.id),
        )
        return {"id": r["id"]}


@router.patch("/reports/{report_id}")
def patch_report(report_id: UUID, body: ReportPatch, admin: Admin):
    with user_tx(admin.id) as c:
        r = one(c, "select * from public.progress_reports where id=%s for update", (report_id,))
        if not r:
            raise NotFound("Report")
        if r["status"] != "draft":
            raise ApiError(409, "published", "Published reports are immutable")
        items = r["package_progress_snapshot"]
        if body.packages:
            try:
                items = progress.apply_decisions(
                    items, [d.model_dump(mode="json") for d in body.packages]
                )
            except ValueError as e:
                raise ApiError(422, "invalid_decision", str(e)) from None
        c.execute(
            "update public.progress_reports set summary=%s, package_progress_snapshot=%s where id=%s",
            (body.summary if body.summary is not None else r["summary"], Jsonb(items), report_id),
        )
    return {"ok": True}


@router.patch("/observations/{observation_id}")
def patch_observation(observation_id: UUID, body: ObservationPatch, admin: Admin):
    ch = body.model_dump(exclude_unset=True)
    with user_tx(admin.id) as c:
        o = one(c, "select * from public.ai_observations where id=%s", (observation_id,))
        if not o:
            raise NotFound("Observation")
        _published_guard(c, o["analysis_id"])
        if ch:
            if {"title", "description", "category", "work_package_id"} & ch.keys():
                ch["edited_by"] = admin.id
            sets = ", ".join(f"{k}=%s" for k in ch)
            c.execute(
                f"update public.ai_observations set {sets} where id=%s",
                (*ch.values(), observation_id),
            )
        return one(c, "select * from public.ai_observations where id=%s", (observation_id,))


@router.post("/reports/{report_id}/publish")
def publish(report_id: UUID, admin: Admin):
    with user_tx(admin.id) as c:
        r = one(c, "select * from public.progress_reports where id=%s for update", (report_id,))
        if not r:
            raise NotFound("Report")
        if r["status"] != "draft":
            raise ApiError(409, "published", "Report is already published")
        if not (r["summary"] or "").strip():
            raise ApiError(422, "summary_required", "A summary is required before publishing")
        pkgs = _packages(c, r["project_id"])
        items = r["package_progress_snapshot"]
        if {i["work_package_id"] for i in items} != {str(p["id"]) for p in pkgs}:
            raise ApiError(
                409,
                "packages_changed",
                "Work packages changed since this draft was created; recreate the draft",
            )
        if names := progress.pending_items(items):
            raise ApiError(
                422,
                "pending_packages",
                "Approve, edit or retain every work package first",
                {"packages": names},
            )
        pending = one(
            c,
            "select count(*) n from public.ai_observations where analysis_id=%s and "
            "review_status='pending'",
            (r["analysis_id"],),
        )["n"]
        if pending:
            raise ApiError(
                422, "pending_observations", f"{pending} observation(s) still need review"
            )
        # freeze names/weights as of publish time, then compute deterministically
        pk = {str(p["id"]): p for p in pkgs}
        for i in items:
            i["name"], i["weight_percentage"] = (
                pk[i["work_package_id"]]["name"],
                float(pk[i["work_package_id"]]["weight_percentage"]),
            )
        overall, coverage = progress.overall_progress(items), progress.assessment_coverage(items)
        frames = {
            str(f["id"]): f
            for f in all_(
                c, "select * from public.video_frames where video_id=%s", (r["video_id"],)
            )
        }
        obs = all_(
            c,
            """select o.*, w.name as wp_name from public.ai_observations o
                         left join public.work_packages w on w.id=o.work_package_id
                         where o.analysis_id=%s and o.review_status='approved' order by o.created_at, o.title""",
            (r["analysis_id"],),
        )
        snap = [
            {
                "id": str(o["id"]),
                "title": o["title"],
                "description": o["description"],
                "category": o["category"],
                "observation_type": o["observation_type"],
                "confidence": o["confidence"],
                "work_package_id": str(o["work_package_id"]) if o["work_package_id"] else None,
                "work_package_name": o["wp_name"],
                "edited": o["edited_by"] is not None,
                "evidence": [
                    {
                        "frame_id": e["frame_id"],
                        "frame_index": e["frame_index"],
                        "timestamp_seconds": e["timestamp_seconds"],
                        "thumbnail_path": (frames.get(e["frame_id"]) or {}).get("thumbnail_path"),
                    }
                    for e in o["evidence_frames"]
                ],
            }
            for o in obs
        ]
        c.execute(
            "update public.progress_reports set status='published', overall_progress_percentage=%s, "
            "assessment_coverage_percentage=%s, package_progress_snapshot=%s, "
            "approved_observations_snapshot=%s, published_by=%s, published_at=now() where id=%s",
            (overall, coverage, Jsonb(items), Jsonb(snap), admin.id, report_id),
        )
    return {
        "id": report_id,
        "status": "published",
        "overall_progress_percentage": overall,
        "assessment_coverage_percentage": coverage,
    }


@router.get("/projects/{project_id}/reports")
def list_reports(
    project_id: UUID, user: User, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)
):
    with user_tx(user.id) as c:  # RLS hides drafts from clients
        _project_or_404(c, project_id)
        rows = all_(
            c,
            """select r.id, r.video_id, r.status, r.summary, r.overall_progress_percentage,
                 r.assessment_coverage_percentage, r.published_at, r.created_at, v.capture_date,
                 count(*) over() as total from public.progress_reports r
                 join public.drone_videos v on v.id=r.video_id and v.project_id=r.project_id
                 where r.project_id=%s order by v.capture_date desc, r.created_at desc limit %s offset %s""",
            (project_id, limit, offset),
        )
        return {
            "items": rows,
            "total": rows[0]["total"] if rows else 0,
            "limit": limit,
            "offset": offset,
        }


@router.get("/reports/{report_id}")
def get_report(report_id: UUID, user: User, storage: Store):
    s = get_settings()
    with user_tx(user.id) as c:
        r = one(
            c,
            "select r.*, v.capture_date, v.storage_path from public.progress_reports r join "
            "public.drone_videos v on v.id=r.video_id where r.id=%s",
            (report_id,),
        )
        if not r:
            raise NotFound("Report")
        live = []
        if user.is_admin and r["status"] == "draft":
            live = all_(
                c,
                """select o.*, w.name as work_package_name from public.ai_observations o
                              left join public.work_packages w on w.id=o.work_package_id
                              where o.analysis_id=%s order by o.created_at, o.title""",
                (r["analysis_id"],),
            )
            frames = {
                str(f["id"]): f["thumbnail_path"]
                for f in all_(
                    c,
                    "select id, thumbnail_path from public.video_frames where video_id=%s",
                    (r["video_id"],),
                )
            }
    published = r["status"] == "published"
    items = r["package_progress_snapshot"]
    if published:
        observations = r["approved_observations_snapshot"]
    else:
        items = progress.provisional(items)
        observations = [
            {
                **o,
                "evidence": [
                    {**e, "thumbnail_path": frames.get(e["frame_id"])} for e in o["evidence_frames"]
                ],
            }
            for o in live
        ]
    thumbs = sign_thumbs(
        storage, [e.get("thumbnail_path") for o in observations for e in o["evidence"]]
    )
    for o in observations:
        for e in o["evidence"]:
            e["thumb_url"] = thumbs.get(e.pop("thumbnail_path", None))
    out = {
        "id": r["id"],
        "project_id": r["project_id"],
        "video_id": r["video_id"],
        "status": r["status"],
        "summary": r["summary"],
        "capture_date": r["capture_date"],
        "published_at": r["published_at"],
        "overall_progress_percentage": r["overall_progress_percentage"]
        if published
        else progress.overall_progress(items),
        "assessment_coverage_percentage": r["assessment_coverage_percentage"]
        if published
        else progress.assessment_coverage(items),
        "video_url": storage.signed_url(s.videos_bucket, r["storage_path"]),
        "retained_package_count": sum(1 for i in items if not i.get("assessed")),
    }
    if user.is_admin:
        out |= {
            "analysis_id": r["analysis_id"],
            "work_packages": items,
            "observations": observations,
            "pending_packages": progress.pending_items(items),
        }
    else:  # clients never see AI suggestions, confidence or review state
        out["work_packages"] = [
            {
                k: i[k]
                for k in (
                    "work_package_id",
                    "name",
                    "weight_percentage",
                    "previous_approved_percentage",
                    "approved_percentage",
                    "assessed",
                )
            }
            for i in items
        ]
        out["observations"] = [
            {
                k: o[k]
                for k in (
                    "id",
                    "title",
                    "description",
                    "category",
                    "observation_type",
                    "work_package_name",
                    "evidence",
                )
            }
            for o in observations
        ]
    return out
