import httpx
import pytest

from cpm.core.config import Settings
from cpm.core.storage import Storage, StorageError

S = Settings(
    supabase_url="http://sb.internal",
    supabase_public_url="https://x.supabase.co",
    supabase_service_role_key="svc",
)


def patch_post(monkeypatch, status, payload):
    seen = {}

    def post(url, **kw):
        seen["url"], seen["headers"], seen["json"] = url, kw.get("headers"), kw.get("json")
        return httpx.Response(status, json=payload)

    monkeypatch.setattr(httpx, "post", post)
    return seen


@pytest.mark.parametrize(
    "payload",
    [
        {"url": "/object/upload/sign/drone-videos/p/v/original.mp4?token=abc"},
        {"url": "/object/upload/sign/drone-videos/p/v/original.mp4?token=abc", "token": "abc"},
        {"signedURL": "/object/upload/sign/drone-videos/p/v/original.mp4?token=abc"},
    ],
)
def test_create_upload_variants(monkeypatch, payload):
    seen = patch_post(monkeypatch, 200, payload)
    out = Storage(S).create_upload("drone-videos", "p/v/original.mp4")
    assert (
        seen["url"]
        == "http://sb.internal/storage/v1/object/upload/sign/drone-videos/p/v/original.mp4"
    )
    assert seen["headers"]["Authorization"] == "Bearer svc"  # service key stays server-side
    assert (
        out["upload_url"]
        == "https://x.supabase.co/storage/v1/object/upload/sign/drone-videos/p/v/original.mp4?token=abc"
    )
    assert out["token"] == "abc"


def test_signed_url_variants_and_errors(monkeypatch):
    seen = patch_post(monkeypatch, 200, {"signedURL": "/object/sign/b/f.jpg?token=t"})
    assert (
        Storage(S).signed_url("b", "f.jpg", 60)
        == "https://x.supabase.co/storage/v1/object/sign/b/f.jpg?token=t"
    )
    assert seen["json"] == {"expiresIn": 60}
    patch_post(monkeypatch, 200, {"signedUrl": "https://other/x?token=1"})
    assert Storage(S).signed_url("b", "f.jpg") == "https://other/x?token=1"
    patch_post(monkeypatch, 200, {})
    with pytest.raises(StorageError):
        Storage(S).signed_url("b", "f.jpg")
    patch_post(monkeypatch, 404, {"error": "x"})
    with pytest.raises(StorageError):
        Storage(S).create_upload("b", "f")


def test_object_size_lookup(monkeypatch):
    seen = patch_post(monkeypatch, 200, [{"name": "original.mp4", "metadata": {"size": 123}}])
    assert Storage(S).object_size("drone-videos", "p/v/original.mp4") == 123
    assert seen["json"]["prefix"] == "p/v" and seen["json"]["search"] == "original.mp4"
    patch_post(monkeypatch, 200, [{"name": "other.mp4", "metadata": {"size": 1}}])
    assert Storage(S).object_size("drone-videos", "p/v/original.mp4") is None
