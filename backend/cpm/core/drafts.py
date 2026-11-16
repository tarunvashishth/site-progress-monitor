"""Draft report creation shared by the API and the worker. A draft only holds AI *proposals*:
every package decision stays 'pending' and every observation stays 'pending' until an admin acts."""

from cpm.core import progress
from cpm.core.db import Jsonb, all_, one


def insert_draft(c, project_id, video_id, analysis: dict, created_by) -> str:
    pkgs = all_(
        c,
        "select * from public.work_packages where project_id=%s order by display_order, name",
        (project_id,),
    )
    last = one(
        c,
        "select package_progress_snapshot s from public.progress_reports where project_id=%s and "
        "status='published' order by published_at desc limit 1",
        (project_id,),
    )
    cur = progress.current_values(pkgs, last["s"] if last else None)
    sr = analysis["structured_response"] or {}
    items = progress.build_draft_items(pkgs, cur, sr.get("package_assessments", []))
    r = one(
        c,
        "insert into public.progress_reports (project_id, video_id, analysis_id, summary, "
        "package_progress_snapshot, created_by) values (%s,%s,%s,%s,%s,%s) returning id",
        (project_id, video_id, analysis["id"], sr.get("summary", ""), Jsonb(items), created_by),
    )
    return r["id"]


def auto_draft(c, video: dict, analysis_id, created_by) -> str | None:
    """Worker hook: create the draft as soon as an analysis completes (no-op if one exists)."""
    if one(c, "select 1 from public.progress_reports where video_id=%s", (video["id"],)):
        return None
    a = one(
        c,
        "select * from public.ai_analyses where id=%s and status='completed'",
        (analysis_id,),
    )
    return insert_draft(c, video["project_id"], video["id"], a, created_by) if a else None
