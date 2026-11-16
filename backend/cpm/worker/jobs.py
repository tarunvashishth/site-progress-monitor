"""Job execution: validate -> extract frames -> store -> AI analysis -> persist. Safe to retry."""

import logging
import tempfile
from pathlib import Path

from cpm.core import progress
from cpm.core.config import Settings
from cpm.core.db import Jsonb, all_, one, service_tx
from cpm.core.storage import Storage, StorageError
from cpm.pipeline import ai, frames
from cpm.pipeline.errors import PermanentError, TransientError

log = logging.getLogger("cpm.worker")


def touch(job_id) -> None:
    with service_tx() as c:
        c.execute("update public.video_processing_jobs set locked_at=now() where id=%s", (job_id,))


def run_job(
    job: dict, storage: Storage, s: Settings, provider: ai.VisionProvider | None = None
) -> None:
    vid = job["video_id"]
    with service_tx() as c:
        video = one(c, "select * from public.drone_videos where id=%s", (vid,))
        if not video:
            raise PermanentError("Video no longer exists")
        c.execute(
            "update public.drone_videos set status='processing', processing_error=null where id=%s",
            (vid,),
        )
        has_frames = (
            one(c, "select 1 from public.video_frames where video_id=%s limit 1", (vid,))
            is not None
        )
    if not has_frames:
        if job["job_type"] != "process" and job["job_type"] != "analyze":
            raise PermanentError("Unknown job type")
        ensure_frames(job, video, storage, s)
    touch(job["id"])
    analyze(job, video, storage, s, provider)


def ensure_frames(job: dict, video: dict, storage: Storage, s: Settings) -> None:
    try:
        with tempfile.TemporaryDirectory(prefix="cpm-") as td:
            local = Path(td) / ("video" + Path(video["storage_path"]).suffix)
            storage.download(s.videos_bucket, video["storage_path"], local)
            touch(job["id"])
            meta = frames.probe(local)
            if meta["duration"] > s.max_video_duration_sec:
                raise PermanentError(
                    f"Video is longer than the {s.max_video_duration_sec // 60}-minute limit"
                )
            with service_tx() as c:
                c.execute(
                    "update public.drone_videos set duration_seconds=%s where id=%s",
                    (meta["duration"], video["id"]),
                )
            found = frames.extract_frames(local, meta["duration"], s)
            touch(job["id"])
        base = f"{video['project_id']}/{video['id']}"
        rows = []
        for f in found:
            p, t = f"{base}/{f.index:04d}.jpg", f"{base}/{f.index:04d}_t.jpg"
            storage.upload_bytes(s.frames_bucket, p, f.jpeg)
            storage.upload_bytes(s.frames_bucket, t, f.thumb)
            rows.append((video["id"], f.index, f.timestamp, p, t, f.hash))
        with service_tx() as c:  # all-or-nothing => retry-safe
            for r in rows:
                c.execute(
                    "insert into public.video_frames (video_id, frame_index, timestamp_seconds, storage_path,"
                    " thumbnail_path, image_hash) values (%s,%s,%s,%s,%s,%s) "
                    "on conflict (video_id, frame_index) do nothing",
                    r,
                )
    except StorageError as e:
        raise TransientError(str(e)) from None


def _upsert_analysis(c, job, video, s, status, fp, error=None, raw=None) -> str:
    return one(
        c,
        """insert into public.ai_analyses (video_id, project_id, job_id, model_name, prompt_version,
          input_fingerprint, status, error_message, raw_response)
        values (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        on conflict (job_id) do update set status=excluded.status, error_message=excluded.error_message,
          model_name=excluded.model_name, prompt_version=excluded.prompt_version,
          input_fingerprint=excluded.input_fingerprint, raw_response=coalesce(excluded.raw_response, ai_analyses.raw_response),
          completed_at=null returning id""",
        (
            video["id"],
            video["project_id"],
            job["id"],
            s.qwen_vl_model or "unconfigured",
            s.prompt_version,
            fp,
            status,
            error,
            raw,
        ),
    )["id"]


def analyze(
    job: dict, video: dict, storage: Storage, s: Settings, provider: ai.VisionProvider | None
) -> None:
    if provider is None and not s.ai_configured:
        with service_tx() as c:
            _upsert_analysis(
                c,
                job,
                video,
                s,
                "unavailable",
                "n/a",
                "AI analysis unavailable: QWEN_VL_BASE_URL / QWEN_VL_MODEL not configured",
            )
        raise PermanentError(
            "AI analysis unavailable: the AI service is not configured. Frames were kept; "
            "configure the service and use Retry."
        )
    with service_tx() as c:
        project = one(c, "select * from public.projects where id=%s", (video["project_id"],))
        pkgs = all_(
            c,
            "select * from public.work_packages where project_id=%s order by display_order, name",
            (video["project_id"],),
        )
        last = one(
            c,
            "select r.summary, r.package_progress_snapshot, r.approved_observations_snapshot, v.capture_date"
            " from public.progress_reports r join public.drone_videos v on v.id=r.video_id "
            "where r.project_id=%s and r.status='published' and r.video_id<>%s "
            "order by r.published_at desc limit 1",
            (video["project_id"], video["id"]),
        )
        rows = all_(
            c,
            "select id, frame_index, timestamp_seconds, storage_path, image_hash from public.video_frames "
            "where video_id=%s order by frame_index",
            (video["id"],),
        )
        prev_paths: list[tuple[str, str]] = []
        if last:
            ids = list(
                dict.fromkeys(
                    e["frame_id"]
                    for o in last["approved_observations_snapshot"]
                    for e in o["evidence"]
                )
            )[: s.max_prev_frames]
            if ids:
                prev_paths = [
                    (f"PREVIOUS-{n + 1}", r["storage_path"])
                    for n, r in enumerate(
                        all_(
                            c,
                            "select storage_path from public.video_frames where id = any(%s::uuid[])",
                            (ids,),
                        )
                    )
                ]
    current = {
        k: float(v)
        for k, v in progress.current_values(
            pkgs, last["package_progress_snapshot"] if last else None
        ).items()
    }
    fp = ai.fingerprint(
        s, [r["image_hash"] for r in rows], pkgs, current, [p for _, p in prev_paths]
    )
    if not job.get("force_reanalysis"):
        with service_tx() as c:
            same = one(
                c,
                "select id from public.ai_analyses where video_id=%s and input_fingerprint=%s and "
                "status='completed' limit 1",
                (video["id"], fp),
            )
            if same:
                log.info("analysis reused for video %s (identical inputs)", video["id"])
                c.execute(
                    "update public.drone_videos set status='analyzed', processing_error=null where id=%s",
                    (video["id"],),
                )
                return
    try:
        imgs = [
            {
                "frame_index": r["frame_index"],
                "timestamp_seconds": r["timestamp_seconds"],
                "jpeg": storage.read(s.frames_bucket, r["storage_path"]),
            }
            for r in rows
        ]
        prev_imgs = [(label, storage.read(s.frames_bucket, p)) for label, p in prev_paths]
    except StorageError as e:
        raise TransientError(str(e)) from None
    messages = ai.build_messages(
        project,
        pkgs,
        current,
        imgs,
        {"date": last["capture_date"], "summary": last["summary"]} if last else None,
        prev_imgs,
    )
    with service_tx() as c:
        analysis_id = _upsert_analysis(c, job, video, s, "running", fp)
    touch(job["id"])
    provider = provider or ai.OpenAICompatibleProvider(s)
    try:
        out, raw = ai.run_with_repair(provider, messages)
    except PermanentError as e:
        with service_tx() as c:
            c.execute(
                "update public.ai_analyses set status='failed', error_message=%s, raw_response=%s, "
                "completed_at=now() where id=%s",
                (str(e), getattr(e, "raw", None), analysis_id),
            )
        raise
    structured, _ = ai.resolve(
        out, {r["frame_index"]: r for r in rows}, {str(p["id"]) for p in pkgs}
    )
    with service_tx() as c:  # one transaction: retries can never duplicate observations
        c.execute(
            "update public.ai_analyses set status='completed', raw_response=%s, structured_response=%s, "
            "error_message=null, completed_at=now() where id=%s",
            (raw, Jsonb(structured), analysis_id),
        )
        c.execute("delete from public.ai_observations where analysis_id=%s", (analysis_id,))
        for o in structured["observations"]:
            c.execute(
                """insert into public.ai_observations (analysis_id, project_id, work_package_id, title,
                  description, category, observation_type, confidence, evidence_frames, ai_original)
                  values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    analysis_id,
                    video["project_id"],
                    o["work_package_id"],
                    o["title"],
                    o["description"],
                    o["category"],
                    o["observation_type"],
                    o["confidence"],
                    Jsonb(o["evidence"]),
                    Jsonb({"title": o["title"], "description": o["description"]}),
                ),
            )
        c.execute(
            "update public.drone_videos set status='analyzed', processing_error=null where id=%s",
            (video["id"],),
        )
