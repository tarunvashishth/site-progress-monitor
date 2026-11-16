"""End-to-end through the real API + real worker + real schema.
Only the external services are replaced: Supabase Storage (in-memory) and the AI endpoint (scripted JSON)."""

import json
import shutil
import subprocess
import time

import jwt
import pytest
from conftest import JWT_SECRET
from fastapi.testclient import TestClient

from cpm.api.deps import get_storage
from cpm.api.main import app
from cpm.core.config import get_settings
from cpm.worker import main as worker

client = TestClient(app)


def H(uid):
    return {
        "Authorization": "Bearer "
        + jwt.encode(
            {"sub": uid, "aud": "authenticated", "exp": int(time.time()) + 600}, JWT_SECRET, "HS256"
        )
    }


class MemoryStorage:
    def __init__(self):
        self.blobs: dict[tuple[str, str], bytes] = {}

    def create_upload(self, bucket, path):
        return {"upload_url": f"https://storage.test/upload/{bucket}/{path}", "token": "t"}

    def signed_url(self, bucket, path, ttl=None):
        assert (bucket, path) in self.blobs, f"signing a missing object {bucket}/{path}"
        return f"https://storage.test/sign/{bucket}/{path}?token=s"

    def object_size(self, bucket, path):
        b = self.blobs.get((bucket, path))
        return len(b) if b else None

    def download(self, bucket, path, dest):
        dest.write_bytes(self.blobs[(bucket, path)])

    def read(self, bucket, path):
        return self.blobs[(bucket, path)]

    def upload_bytes(self, bucket, path, data, content_type="image/jpeg"):
        self.blobs[(bucket, path)] = data


@pytest.fixture
def video_bytes(tmp_path):
    p = tmp_path / "v.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=duration=24:size=640x360:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(p),
        ],
        check=True,
    )
    return p.read_bytes()


def test_full_mvp_flow(world, video_bytes, monkeypatch):
    for k, v in {
        "FRAME_SAMPLE_INTERVAL_SEC": "4",
        "MAX_FRAMES": "4",
        "BLUR_THRESHOLD": "1",
        "DUP_HASH_DISTANCE": "0",
        "QWEN_VL_BASE_URL": "http://ai.test/v1",
        "QWEN_VL_MODEL": "served-model",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    world.c.execute("delete from public.video_processing_jobs")  # only this test's job
    st = MemoryStorage()
    app.dependency_overrides[get_storage] = lambda: st
    adm, cl, other_cl, pid = H(world.admin), H(world.ca), H(world.cb), world.A["id"]
    try:
        # 1-5: admin uploads a video directly to (private) storage, then completes the upload
        up = client.post(
            f"/projects/{pid}/videos/upload-url",
            headers=adm,
            json={
                "filename": "day3.mp4",
                "content_type": "video/mp4",
                "file_size": len(video_bytes),
                "capture_date": "2026-06-03",
            },
        ).json()
        st.blobs[("drone-videos", up["path"])] = video_bytes  # the browser's PUT to the signed URL
        vid = up["video_id"]
        assert client.post(f"/videos/{vid}/complete", headers=adm).json()["status"] == "queued"

        # 6-8: worker claims the job, extracts timestamped frames and runs the (scripted) AI
        calls = []

        class Ai:
            def complete(self, messages):
                calls.append(messages)
                frames = [
                    p["text"]
                    for p in messages[1]["content"]
                    if p.get("type") == "text" and p["text"].startswith("Frame ")
                ]
                assert (
                    len(frames) >= 2
                    and "last approved completion 50" in messages[1]["content"][0]["text"]
                )
                return json.dumps(
                    {
                        "summary": "Foundation excavation continues; roof not visible.",
                        "observations": [
                            {
                                "title": "Excavation",
                                "description": "Machinery working the foundation pit",
                                "category": "foundation",
                                "observation_type": "ongoing",
                                "work_package_id": world.A["wp1"],
                                "confidence": 0.8,
                                "evidence_frame_indices": [0, 1],
                            },
                            {
                                "title": "Imaginary crane",
                                "description": "invented",
                                "observation_type": "newly_visible",
                                "confidence": 0.9,
                                "evidence_frame_indices": [99],
                            },
                        ],  # bad evidence -> must be discarded
                        "package_assessments": [
                            {
                                "work_package_id": world.A["wp1"],
                                "assessable": True,
                                "proposed_completion_percentage": 62,
                                "confidence": 0.7,
                                "reasoning": "pit deepened",
                            },
                            {
                                "work_package_id": world.A["wp2"],
                                "assessable": False,
                                "reasoning": "no roof in footage",
                            },
                        ],
                    }
                )

        assert worker.run_once(st, Ai()) is True
        an = client.get(f"/videos/{vid}/analysis", headers=adm).json()
        assert an["video"]["status"] == "analyzed" and an["analysis"]["status"] == "completed"
        assert [o["title"] for o in an["observations"]] == [
            "Excavation"
        ]  # unsupported observation never stored
        assert all(f["thumb_url"] for f in an["frames"]) and len(an["frames"]) >= 2
        assert an["observations"][0]["review_status"] == "pending"
        assert (
            client.get(f"/projects/{pid}", headers=cl).json()["latest_report"]["id"]
            == world.A["report_pub"]
        )  # nothing published yet

        # 9-10: admin reviews evidence, edits text, decides every package
        rid = client.post(
            f"/projects/{pid}/reports/draft", headers=adm, json={"video_id": vid}
        ).json()["id"]
        assert client.get(f"/reports/{rid}", headers=cl).status_code == 404  # draft hidden
        oid = an["observations"][0]["id"]
        client.patch(
            f"/observations/{oid}",
            headers=adm,
            json={
                "description": "Excavator working the foundation pit",
                "review_status": "approved",
            },
        )
        client.patch(
            f"/reports/{rid}",
            headers=adm,
            json={
                "packages": [
                    {
                        "work_package_id": world.A["wp1"],
                        "decision": "edit",
                        "approved_percentage": 60,
                    },
                    {"work_package_id": world.A["wp2"], "decision": "retain"},
                ]
            },
        )

        # 11-12: deterministic progress, then publish
        pub = client.post(f"/reports/{rid}/publish", headers=adm).json()
        assert (
            pub["overall_progress_percentage"] == 36.0
        )  # 60% * 60 + 40% * 0 (roof retained, not zeroed by AI)
        assert pub["assessment_coverage_percentage"] == 60.0

        # 13: assigned client sees progress, report, video and evidence
        proj = client.get(f"/projects/{pid}", headers=cl).json()
        assert proj["overall_progress"] == 36.0 and proj["latest_report"]["id"] == rid
        rep = client.get(f"/reports/{rid}", headers=cl).json()
        assert rep["video_url"].startswith("https://storage.test/sign/drone-videos/")
        o = rep["observations"][0]
        assert (
            o["description"] == "Excavator working the foundation pit"
            and o["evidence"][0]["thumb_url"]
        )
        assert "confidence" not in o
        assert client.get(f"/videos/{vid}/playback-url", headers=cl).status_code == 200

        # 14: isolation
        assert client.get(f"/reports/{rid}", headers=other_cl).status_code == 404
        assert client.get(f"/projects/{pid}", headers=other_cl).status_code == 404
        assert client.get(f"/videos/{vid}/analysis", headers=cl).status_code == 403
        assert client.post(f"/reports/{rid}/publish", headers=cl).status_code == 403

        # 15: published history is unchanged by later config changes
        wps = client.get(f"/projects/{pid}", headers=adm).json()["work_packages"]
        client.post(
            f"/projects/{pid}/work-packages",
            headers=adm,
            json={
                "work_packages": [
                    {
                        "id": w["work_package_id"],
                        "name": w["name"],
                        "weight_percentage": 50,
                        "initial_approved_percentage": 90,
                    }
                    for w in wps
                ]
            },
        )
        assert (
            client.get(f"/reports/{rid}", headers=cl).json()["overall_progress_percentage"] == 36.0
        )
        assert len(calls) == 1
    finally:
        app.dependency_overrides.clear()
        shutil.rmtree("/tmp/cpm-none", ignore_errors=True)
