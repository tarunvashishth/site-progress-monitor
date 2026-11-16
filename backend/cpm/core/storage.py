"""Supabase Storage REST client (service role). Private buckets only; the browser gets signed URLs."""

from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import httpx

from cpm.core.config import Settings, get_settings


class StorageError(RuntimeError):
    pass


class Storage:
    def __init__(self, settings: Settings | None = None):
        self.s = settings or get_settings()
        self.base = f"{self.s.supabase_url.rstrip('/')}/storage/v1"
        self.h = {
            "Authorization": f"Bearer {self.s.supabase_service_role_key}",
            "apikey": self.s.supabase_anon_key or self.s.supabase_service_role_key,
        }

    def _p(self, bucket: str, path: str) -> str:
        return f"{bucket}/{quote(path, safe='/')}"

    def _absolute(self, rel: str) -> str:
        """Storage returns a path relative to /storage/v1 (or, in some versions, an absolute URL)."""
        if rel.startswith("http"):
            return rel
        rel = rel if rel.startswith("/") else "/" + rel
        return f"{self.s.public_supabase_url}/storage/v1{rel}"

    def create_upload(self, bucket: str, path: str) -> dict:
        r = httpx.post(
            f"{self.base}/object/upload/sign/{self._p(bucket, path)}", headers=self.h, timeout=20
        )
        if r.status_code >= 300:
            raise StorageError(f"could not create upload URL ({r.status_code})")
        data = r.json()
        rel = data.get("url") or data.get("signedURL") or data.get("signedUrl")
        if not rel:
            raise StorageError("unexpected response creating upload URL")
        token = data.get("token") or parse_qs(urlparse(rel).query).get("token", [None])[0]
        return {"upload_url": self._absolute(rel), "token": token}

    def signed_url(self, bucket: str, path: str, ttl: int | None = None) -> str:
        r = httpx.post(
            f"{self.base}/object/sign/{self._p(bucket, path)}",
            headers=self.h,
            timeout=20,
            json={"expiresIn": ttl or self.s.signed_url_ttl_sec},
        )
        if r.status_code >= 300:
            raise StorageError(f"could not sign URL ({r.status_code})")
        data = r.json()
        rel = data.get("signedURL") or data.get("signedUrl")
        if not rel:
            raise StorageError("unexpected response signing URL")
        return self._absolute(rel)

    def object_size(self, bucket: str, path: str) -> int | None:
        folder, _, name = path.rpartition("/")
        r = httpx.post(
            f"{self.base}/object/list/{bucket}",
            headers=self.h,
            timeout=20,
            json={"prefix": folder, "search": name, "limit": 5},
        )
        if r.status_code >= 300:
            raise StorageError(f"could not list objects ({r.status_code})")
        for o in r.json():
            if o.get("name") == name:
                return int((o.get("metadata") or {}).get("size") or 0) or None
        return None

    def download(self, bucket: str, path: str, dest: Path) -> None:
        with httpx.stream(
            "GET",
            f"{self.base}/object/authenticated/{self._p(bucket, path)}",
            headers=self.h,
            timeout=httpx.Timeout(30, read=600),
        ) as r:
            if r.status_code >= 300:
                raise StorageError(f"download failed ({r.status_code})")
            with open(dest, "wb") as f:
                f.writelines(r.iter_bytes(1 << 20))

    def read(self, bucket: str, path: str) -> bytes:
        r = httpx.get(
            f"{self.base}/object/authenticated/{self._p(bucket, path)}", headers=self.h, timeout=60
        )
        if r.status_code >= 300:
            raise StorageError(f"download failed ({r.status_code})")
        return r.content

    def upload_bytes(
        self, bucket: str, path: str, data: bytes, content_type: str = "image/jpeg"
    ) -> None:
        r = httpx.post(
            f"{self.base}/object/{self._p(bucket, path)}",
            content=data,
            timeout=60,
            headers={**self.h, "Content-Type": content_type, "x-upsert": "true"},
        )
        if r.status_code >= 300:
            raise StorageError(f"upload failed ({r.status_code})")
