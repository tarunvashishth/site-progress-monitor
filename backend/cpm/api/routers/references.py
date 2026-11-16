"""Completed-site reference images (renders / elevations). Admin-only; used only as AI context."""

from typing import Annotated
from uuid import UUID, uuid4

import cv2
import numpy as np
from fastapi import APIRouter, Depends, Request
from psycopg import errors as pg

from cpm.api.auth import Admin
from cpm.api.deps import get_storage
from cpm.api.routers.projects import _project_or_404
from cpm.core.config import get_settings
from cpm.core.db import all_, one, user_tx
from cpm.core.errors import ApiError, NotFound
from cpm.core.storage import Storage, StorageError

router = APIRouter()
Store = Annotated[Storage, Depends(get_storage)]
TYPES = ("image/jpeg", "image/png")


def normalize_image(data: bytes, max_side: int) -> bytes:
    """Decode (rejects anything that is not a real image), downscale, re-encode as JPEG."""
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None or min(img.shape[:2]) < 64:
        raise ApiError(422, "invalid_image", "The file is not a readable image (min 64 px)")
    h, w = img.shape[:2]
    scale = max_side / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise ApiError(422, "invalid_image", "Could not process the image")
    return buf.tobytes()


@router.get("/projects/{project_id}/reference-images")
def list_references(project_id: UUID, admin: Admin, storage: Store):
    s = get_settings()
    with user_tx(admin.id) as c:
        _project_or_404(c, project_id)
        rows = all_(
            c,
            "select r.id, r.work_package_id, w.name as work_package_name, r.caption, r.original_filename,"
            " r.storage_path, r.created_at from public.reference_images r"
            " left join public.work_packages w on w.id = r.work_package_id"
            " where r.project_id=%s order by r.created_at",
            (project_id,),
        )
    for r in rows:
        r["url"] = storage.signed_url(s.reference_bucket, r.pop("storage_path"))
    return {"items": rows}


@router.post("/projects/{project_id}/reference-images", status_code=201)
async def add_reference(
    project_id: UUID,
    request: Request,
    admin: Admin,
    storage: Store,
    filename: str = "reference.jpg",
    caption: str | None = None,
    work_package_id: UUID | None = None,
):
    s = get_settings()
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype not in TYPES:
        raise ApiError(422, "unsupported_type", "Reference images must be JPEG or PNG")
    declared = int(request.headers.get("content-length") or 0)
    if declared > s.max_reference_upload_bytes:
        raise ApiError(413, "too_large", "Reference image is larger than 10 MB")
    data = await request.body()
    if len(data) > s.max_reference_upload_bytes:
        raise ApiError(413, "too_large", "Reference image is larger than 10 MB")
    jpeg = normalize_image(data, s.reference_max_side)
    rid = uuid4()
    path = f"{project_id}/{rid}.jpg"
    with user_tx(admin.id) as c:
        _project_or_404(c, project_id)
        try:
            row = one(
                c,
                "insert into public.reference_images (id, project_id, work_package_id, storage_path,"
                " original_filename, caption, created_by) values (%s,%s,%s,%s,%s,%s,%s)"
                " returning id, work_package_id, caption, original_filename, created_at",
                (
                    rid,
                    project_id,
                    work_package_id,
                    path,
                    filename[:200],
                    (caption or "").strip()[:500] or None,
                    admin.id,
                ),
            )
        except pg.CheckViolation:
            raise ApiError(409, "limit", "A project can have at most 6 reference images") from None
        except pg.ForeignKeyViolation:
            raise ApiError(422, "bad_package", "Unknown work package for this project") from None
        try:
            storage.upload_bytes(s.reference_bucket, path, jpeg)
        except StorageError:
            raise ApiError(502, "storage_unavailable", "Could not store the image") from None
    return row


@router.delete("/reference-images/{image_id}", status_code=204)
def delete_reference(image_id: UUID, admin: Admin, storage: Store):
    s = get_settings()
    with user_tx(admin.id) as c:
        row = one(
            c, "delete from public.reference_images where id=%s returning storage_path", (image_id,)
        )
        if not row:
            raise NotFound("Reference image")
    try:
        storage.remove(s.reference_bucket, row["storage_path"])
    except StorageError:
        pass  # row is gone; an orphaned private object is harmless
