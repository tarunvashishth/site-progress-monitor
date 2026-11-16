import re
from datetime import date, timedelta
from pathlib import PurePosixPath
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from psycopg import errors as pg
from pydantic import BaseModel, Field

from cpm.api.auth import Admin, User
from cpm.api.deps import get_storage
from cpm.api.routers.projects import _project_or_404
from cpm.core.config import get_settings
from cpm.core.db import all_, one, user_tx
from cpm.core.errors import ApiError, NotFound
from cpm.core.storage import Storage, StorageError

router = APIRouter()
Store = Annotated[Storage, Depends(get_storage)]
ALLOWED = {".mp4": "video/mp4", ".mov": "video/quicktime"}


def safe_filename(name: str) -> str:
    base = PurePosixPath(name.replace("\\", "/")).name
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip(" .")[:150]
    return base or "video"


class UploadIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str
    file_size: int = Field(gt=0)
    capture_date: date
    description: str | None = Field(default=None, max_length=2000)


class AnalyzeIn(BaseModel):
    force: bool = False
    compare_to_video_id: UUID | None = (
        None  # earlier capture of the same project; default = latest earlier
    )


def _video(c, vid):
    v = one(c, "select * from public.drone_videos where id=%s", (vid,))  # RLS-scoped
    if not v:
        raise NotFound("Video")
    return v


def enqueue(
    c, video_id, job_type: str, user_id: str, force: bool = False, compare_to: UUID | None = None
) -> dict:
    try:
        with c.transaction():
            job = one(
                c,
                "insert into public.video_processing_jobs (video_id, job_type, created_by, force_reanalysis,"
                " compare_to_video_id) values (%s,%s,%s,%s,%s) returning *",
                (video_id, job_type, user_id, force, compare_to),
            )
    except pg.UniqueViolation:
        raise ApiError(
            409, "job_active", "This video is already queued or being processed"
        ) from None
    c.execute(
        "update public.drone_videos set status='queued', processing_error=null where id=%s",
        (video_id,),
    )
    return job


@router.post("/projects/{project_id}/videos/upload-url", status_code=201)
def upload_url(project_id: UUID, body: UploadIn, admin: Admin, storage: Store):
    s = get_settings()
    name = safe_filename(body.filename)
    ext = PurePosixPath(name).suffix.lower()
    if ext not in ALLOWED or body.content_type not in ALLOWED.values():
        raise ApiError(422, "unsupported_type", "Only MP4 and MOV videos are supported")
    if body.file_size > s.max_video_bytes:
        raise ApiError(
            413, "too_large", f"Video exceeds the {s.max_video_bytes // 1024**2} MB limit"
        )
    if body.capture_date > date.today() + timedelta(days=1):
        raise ApiError(422, "invalid_date", "Capture date cannot be in the future")
    vid = uuid4()
    path = (
        f"{project_id}/{vid}/original{ext}"  # server-chosen path; the filename is never used in it
    )
    with user_tx(admin.id) as c:
        _project_or_404(c, project_id)
        c.execute(
            "insert into public.drone_videos (id, project_id, uploaded_by, storage_path, original_filename,"
            " capture_date, description, file_size, status) values (%s,%s,%s,%s,%s,%s,%s,%s,'pending_upload')",
            (
                vid,
                project_id,
                admin.id,
                path,
                name,
                body.capture_date,
                body.description,
                body.file_size,
            ),
        )
    try:
        up = storage.create_upload(s.videos_bucket, path)
    except StorageError:
        raise ApiError(502, "storage_unavailable", "Could not prepare the upload") from None
    return {"video_id": vid, "bucket": s.videos_bucket, "path": path, "method": "PUT", **up}


@router.post("/videos/{video_id}/complete")
def complete(video_id: UUID, admin: Admin, storage: Store):
    s = get_settings()
    with user_tx(admin.id) as c:
        v = _video(c, video_id)
        if v["status"] != "pending_upload":
            return v  # idempotent
        try:
            size = storage.object_size(s.videos_bucket, v["storage_path"])
        except StorageError:
            raise ApiError(502, "storage_unavailable", "Could not verify the upload") from None
        if size is None:
            raise ApiError(409, "upload_missing", "The file has not been uploaded yet")
        if size > s.max_video_bytes:
            c.execute(
                "update public.drone_videos set status='failed', processing_error=%s where id=%s",
                ("File exceeds the size limit", video_id),
            )
            raise ApiError(413, "too_large", "Uploaded file exceeds the size limit")
        c.execute(
            "update public.drone_videos set file_size=%s, status='uploaded' where id=%s",
            (size, video_id),
        )
        enqueue(c, video_id, "process", admin.id)
        return _video(c, video_id)


@router.get("/projects/{project_id}/videos")
def list_videos(project_id: UUID, admin: Admin, limit: int = 50, offset: int = 0):
    limit, offset = max(1, min(limit, 200)), max(0, offset)
    with user_tx(admin.id) as c:
        _project_or_404(c, project_id)
        rows = all_(
            c,
            """select v.*, count(*) over() as total,
              j.status as job_status, j.job_type, j.attempts, j.error_message as job_error,
              r.id as report_id, r.status as report_status
            from public.drone_videos v
            left join lateral (select * from public.video_processing_jobs where video_id=v.id
                               order by created_at desc limit 1) j on true
            left join public.progress_reports r on r.video_id=v.id
            where v.project_id=%s and v.status <> 'pending_upload'
            order by v.capture_date desc, v.created_at desc limit %s offset %s""",
            (project_id, limit, offset),
        )
        return {
            "items": rows,
            "total": rows[0]["total"] if rows else 0,
            "limit": limit,
            "offset": offset,
        }


@router.get("/videos/{video_id}")
def get_video(video_id: UUID, user: User):
    with user_tx(user.id) as c:
        v = _video(c, video_id)
        out = {
            **v,
            "report": one(
                c, "select id, status from public.progress_reports where video_id=%s", (video_id,)
            ),
        }
        if user.is_admin:
            out["jobs"] = all_(
                c,
                "select * from public.video_processing_jobs where video_id=%s "
                "order by created_at desc",
                (video_id,),
            )
            out["frame_count"] = one(
                c, "select count(*) n from public.video_frames where video_id=%s", (video_id,)
            )["n"]
        return out


@router.get("/videos/{video_id}/playback-url")
def playback_url(video_id: UUID, user: User, storage: Store):
    with user_tx(
        user.id
    ) as c:  # RLS: clients only see videos of published reports in assigned projects
        v = _video(c, video_id)
    return {
        "url": storage.signed_url(get_settings().videos_bucket, v["storage_path"]),
        "expires_in": get_settings().signed_url_ttl_sec,
    }


@router.get("/frames/{frame_id}/image-url")
def frame_url(frame_id: UUID, user: User, storage: Store):
    with user_tx(user.id) as c:
        f = one(c, "select storage_path from public.video_frames where id=%s", (frame_id,))
    if not f:
        raise NotFound("Frame")
    return {"url": storage.signed_url(get_settings().frames_bucket, f["storage_path"])}


@router.post("/videos/{video_id}/retry", status_code=202)
def retry(video_id: UUID, admin: Admin):
    with user_tx(admin.id) as c:
        v = _video(c, video_id)
        if v["status"] != "failed":
            raise ApiError(409, "not_failed", "Only failed videos can be retried")
        frames = one(
            c, "select count(*) n from public.video_frames where video_id=%s", (video_id,)
        )["n"]
        return enqueue(c, video_id, "analyze" if frames else "process", admin.id)


@router.post("/videos/{video_id}/analyze", status_code=202)
def analyze(video_id: UUID, admin: Admin, body: AnalyzeIn | None = None):
    with user_tx(admin.id) as c:
        v = _video(c, video_id)
        if v["status"] not in ("analyzed", "failed"):
            raise ApiError(
                409, "not_ready", "The video must finish processing before analysis can be re-run"
            )
        if (
            one(c, "select 1 from public.video_frames where video_id=%s limit 1", (video_id,))
            is None
        ):
            raise ApiError(
                409, "no_frames", "No frames extracted yet; use retry to reprocess the video"
            )
        if one(
            c,
            "select 1 from public.progress_reports where video_id=%s and status='published'",
            (video_id,),
        ):
            raise ApiError(409, "published", "This video already has a published report")
        compare_to = body.compare_to_video_id if body else None
        if compare_to:
            earlier = one(
                c,
                "select 1 from public.drone_videos e where e.id=%s and e.project_id=%s "
                "and e.capture_date < %s and e.status='analyzed'",
                (compare_to, v["project_id"], v["capture_date"]),
            )
            if not earlier:
                raise ApiError(
                    422,
                    "bad_comparison",
                    "Compare against an analyzed video of the same project captured on an earlier date",
                )
        return enqueue(c, video_id, "analyze", admin.id, bool(body and body.force), compare_to)


@router.get("/videos/{video_id}/analysis")
def analysis(video_id: UUID, admin: Admin, storage: Store, raw: bool = False):
    s = get_settings()
    with user_tx(admin.id) as c:
        v = _video(c, video_id)
        a = one(
            c,
            "select * from public.ai_analyses where video_id=%s order by created_at desc limit 1",
            (video_id,),
        )
        job = one(
            c,
            "select * from public.video_processing_jobs where video_id=%s order by created_at desc limit 1",
            (video_id,),
        )
        frames = all_(
            c,
            "select id, frame_index, timestamp_seconds, thumbnail_path from public.video_frames "
            "where video_id=%s order by frame_index",
            (video_id,),
        )
        compared = None
        if a and a.get("compare_to_video_id"):
            compared = one(
                c,
                "select id, capture_date, original_filename from public.drone_videos where id=%s",
                (a["compare_to_video_id"],),
            )
            pairs = ((a.get("structured_response") or {}).get("compared_with") or {}).get(
                "pairs", []
            )
            ids = [p["previous_frame_id"] for p in pairs]
            prev_frames = (
                all_(
                    c,
                    "select id, frame_index, thumbnail_path from public.video_frames "
                    "where id = any(%s::uuid[])",
                    (ids,),
                )
                if ids
                else []
            )
        else:
            prev_frames = []
        obs = (
            all_(
                c,
                """select o.*, w.name as work_package_name from public.ai_observations o
                         left join public.work_packages w on w.id=o.work_package_id
                         where o.analysis_id=%s order by o.created_at, o.title""",
                (a["id"],),
            )
            if a
            else []
        )
    if a and not raw:
        a = {k: v2 for k, v2 in a.items() if k != "raw_response"}
    for f in frames:
        f["thumb_url"] = (
            storage.signed_url(s.frames_bucket, f["thumbnail_path"])
            if f["thumbnail_path"]
            else None
        )
        f.pop("thumbnail_path")
    for f in prev_frames:
        f["thumb_url"] = (
            storage.signed_url(s.frames_bucket, f["thumbnail_path"])
            if f["thumbnail_path"]
            else None
        )
        f.pop("thumbnail_path")
    return {
        "video": v,
        "job": job,
        "compared_video": compared,
        "compared_frames": prev_frames,
        "analysis": a,
        "observations": obs,
        "frames": frames,
        "ai_configured": s.ai_configured,
    }
