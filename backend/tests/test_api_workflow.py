import json
import time

import jwt
import psycopg
import pytest
from conftest import JWT_SECRET
from fastapi.testclient import TestClient

from cpm.api.deps import get_storage
from cpm.api.main import app


class FakeStorage:
    def __init__(self):
        self.objects: dict[str, int] = {}

    def create_upload(self, bucket, path):
        return {"upload_url": f"https://st.test/upload/{bucket}/{path}?token=t", "token": "t"}

    def signed_url(self, bucket, path, ttl=None):
        return f"https://st.test/sign/{bucket}/{path}?token=s"

    def object_size(self, bucket, path):
        return self.objects.get(f"{bucket}/{path}")


@pytest.fixture
def storage():
    fs = FakeStorage()
    app.dependency_overrides[get_storage] = lambda: fs
    yield fs
    app.dependency_overrides.clear()


client = TestClient(app)


def H(uid):
    return {
        "Authorization": "Bearer "
        + jwt.encode(
            {"sub": uid, "aud": "authenticated", "exp": int(time.time()) + 600}, JWT_SECRET, "HS256"
        )
    }


UP = {
    "filename": "site.mp4",
    "content_type": "video/mp4",
    "file_size": 1000,
    "capture_date": "2026-03-01",
}


# ---------- upload ----------


def test_upload_flow(world, storage):
    pid = world.A["id"]
    r = client.post(f"/projects/{pid}/videos/upload-url", json=UP, headers=H(world.admin))
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["path"].startswith(f"{pid}/{d['video_id']}/original") and "token=t" in d["upload_url"]
    # not uploaded yet
    assert (
        client.post(f"/videos/{d['video_id']}/complete", headers=H(world.admin)).status_code == 409
    )
    storage.objects[f"drone-videos/{d['path']}"] = 999
    done = client.post(f"/videos/{d['video_id']}/complete", headers=H(world.admin))
    assert (
        done.status_code == 200
        and done.json()["status"] == "queued"
        and done.json()["file_size"] == 999
    )
    again = client.post(f"/videos/{d['video_id']}/complete", headers=H(world.admin))  # idempotent
    assert again.status_code == 200
    world.c.execute("select 1")
    n = world.c.execute(
        "select count(*) from public.video_processing_jobs where video_id=%s", (d["video_id"],)
    ).fetchone()[0]
    assert n == 1


@pytest.mark.parametrize(
    "patch,code",
    [
        ({"filename": "x.avi", "content_type": "video/x-msvideo"}, 422),
        ({"content_type": "application/pdf"}, 422),
        ({"filename": "x.exe"}, 422),
        ({"file_size": 10**12}, 413),
        ({"file_size": 0}, 422),
        ({"capture_date": "2999-01-01"}, 422),
    ],
)
def test_upload_validation(world, storage, patch, code):
    r = client.post(
        f"/projects/{world.A['id']}/videos/upload-url", json={**UP, **patch}, headers=H(world.admin)
    )
    assert r.status_code == code


def test_upload_authorization_and_safe_paths(world, storage):
    url = f"/projects/{world.A['id']}/videos/upload-url"
    assert client.post(url, json=UP, headers=H(world.ca)).status_code == 403
    assert client.post(url, json=UP).status_code == 401
    evil = client.post(
        url, json={**UP, "filename": "../../etc/passwd.mp4"}, headers=H(world.admin)
    ).json()
    assert ".." not in evil["path"] and "etc" not in evil["path"]
    row = world.c.execute(
        "select original_filename from public.drone_videos where id=%s", (evil["video_id"],)
    ).fetchone()
    assert row[0] == "passwd.mp4"
    assert (
        client.post(
            "/projects/00000000-0000-0000-0000-000000000000/videos/upload-url",
            json=UP,
            headers=H(world.admin),
        ).status_code
        == 404
    )


def test_clients_cannot_use_video_admin_endpoints(world, storage):
    v = world.A["video_pub"]
    h = H(world.ca)
    assert client.get(f"/projects/{world.A['id']}/videos", headers=h).status_code == 403
    assert client.post(f"/videos/{v}/analyze", headers=h).status_code == 403
    assert client.post(f"/videos/{v}/retry", headers=h).status_code == 403
    assert client.get(f"/videos/{v}/analysis", headers=h).status_code == 403
    assert client.get(f"/videos/{world.B['video_pub']}/playback-url", headers=h).status_code == 404


def test_client_video_access_only_when_published(world, storage):
    h = H(world.ca)
    assert client.get(f"/videos/{world.A['video_pub']}/playback-url", headers=h).status_code == 200
    assert (
        client.get(f"/videos/{world.A['video_draft']}/playback-url", headers=h).status_code == 404
    )
    assert client.get(f"/frames/{world.A['frame_draft']}/image-url", headers=h).status_code == 404
    assert client.get(f"/frames/{world.A['frame_pub']}/image-url", headers=h).status_code == 200


# ---------- retry / analyze state rules ----------


def test_retry_and_analyze_rules(world, storage):
    h, v = H(world.admin), world.A["video_draft"]
    assert client.post(f"/videos/{v}/retry", headers=h).status_code == 409  # not failed
    world.c.execute(
        "update public.video_processing_jobs set status='failed' where video_id=%s", (v,)
    )
    world.c.execute("update public.drone_videos set status='failed' where id=%s", (v,))
    r = client.post(f"/videos/{v}/retry", headers=h)
    assert (
        r.status_code == 202 and r.json()["job_type"] == "analyze"
    )  # frames exist -> only re-analyse
    assert client.post(f"/videos/{v}/retry", headers=h).status_code == 409  # already queued
    assert (
        client.post(f"/videos/{world.A['video_pub']}/analyze", headers=h).status_code == 409
    )  # published


def test_retry_without_frames_reprocesses(world, storage):
    v = world.c.execute(
        "insert into public.drone_videos (project_id,storage_path,original_filename,capture_date,"
        "status) values (%s,'p/new.mp4','n.mp4','2026-04-01','failed') returning id",
        (world.A["id"],),
    ).fetchone()[0]
    assert client.post(f"/videos/{v}/retry", headers=H(world.admin)).json()["job_type"] == "process"


# ---------- full approval + publish workflow ----------


def make_analyzed_video(world, with_pending_obs=True):
    c, pid = world.c, world.A["id"]
    v = c.execute(
        "insert into public.drone_videos (project_id,storage_path,original_filename,capture_date,status) "
        "values (%s,%s,'d2.mp4','2026-03-02','analyzed') returning id",
        (pid, f"{pid}/d2.mp4"),
    ).fetchone()[0]
    f = c.execute(
        "insert into public.video_frames (video_id,frame_index,timestamp_seconds,storage_path,"
        "thumbnail_path,image_hash) values (%s,0,12,'fr/0.jpg','fr/0_t.jpg','h') returning id",
        (v,),
    ).fetchone()[0]
    sr = {
        "summary": "Slab poured on level 1.",
        "package_assessments": [
            {
                "work_package_id": world.A["wp1"],
                "assessable": True,
                "proposed_completion_percentage": 70,
                "confidence": 0.8,
                "reasoning": "slab visible",
            },
            {
                "work_package_id": world.A["wp2"],
                "assessable": False,
                "proposed_completion_percentage": None,
                "confidence": 0.2,
                "reasoning": "obstructed",
            },
        ],
    }
    a = c.execute(
        "insert into public.ai_analyses (video_id,project_id,model_name,prompt_version,input_fingerprint,"
        "status,structured_response) values (%s,%s,'qwen','v1','fp2','completed',%s) returning id",
        (v, pid, json.dumps(sr)),
    ).fetchone()[0]
    ev = json.dumps([{"frame_id": f, "frame_index": 0, "timestamp_seconds": 12}])
    o = c.execute(
        "insert into public.ai_observations (analysis_id,project_id,title,description,observation_type,"
        "confidence,evidence_frames,ai_original,work_package_id) values (%s,%s,'Slab work','Crew pouring',"
        "'ongoing',0.9,%s,'{}',%s) returning id",
        (a, pid, ev, world.A["wp1"]),
    ).fetchone()[0]
    return v, a, o


def test_full_report_workflow(world, storage):
    adm, cl = H(world.admin), H(world.ca)
    v, a, o = make_analyzed_video(world)
    pid = world.A["id"]

    r = client.post(f"/projects/{pid}/reports/draft", json={"video_id": str(v)}, headers=adm)
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert (
        client.post(
            f"/projects/{pid}/reports/draft", json={"video_id": str(v)}, headers=adm
        ).status_code
        == 409
    )

    d = client.get(f"/reports/{rid}", headers=adm).json()
    wp = {i["name"]: i for i in d["work_packages"]}
    assert wp["Foundation"]["decision"] == "pending" and wp["Roof"]["decision"] == "retain"
    assert (
        wp["Roof"]["approved_percentage"] == 0
        and wp["Foundation"]["previous_approved_percentage"] == 50
    )
    # draft invisible to clients
    assert client.get(f"/reports/{rid}", headers=cl).status_code == 404
    assert rid not in {
        x["id"] for x in client.get(f"/projects/{pid}/reports", headers=cl).json()["items"]
    }

    # cannot publish with pending package / pending observation
    assert (
        client.post(f"/reports/{rid}/publish", headers=adm).json()["error"]["code"]
        == "pending_packages"
    )
    dec = {"packages": [{"work_package_id": world.A["wp1"], "decision": "accept"}]}
    assert client.patch(f"/reports/{rid}", json=dec, headers=adm).status_code == 200
    assert (
        client.post(f"/reports/{rid}/publish", headers=adm).json()["error"]["code"]
        == "pending_observations"
    )

    # edit + approve observation (original AI text is preserved separately)
    p = client.patch(
        f"/observations/{o}",
        json={"description": "Crew pouring level 1 slab", "review_status": "approved"},
        headers=adm,
    )
    assert p.status_code == 200 and p.json()["edited_by"] is not None

    # invalid decisions rejected
    bad = {"packages": [{"work_package_id": world.A["wp2"], "decision": "accept"}]}
    assert client.patch(f"/reports/{rid}", json=bad, headers=adm).status_code == 422
    bad = {"packages": [{"work_package_id": world.A["wp2"], "decision": "edit"}]}
    assert client.patch(f"/reports/{rid}", json=bad, headers=adm).status_code == 422

    # clients can never publish or edit
    assert client.post(f"/reports/{rid}/publish", headers=cl).status_code == 403
    assert client.patch(f"/reports/{rid}", json={"summary": "x"}, headers=cl).status_code == 403

    pub = client.post(f"/reports/{rid}/publish", headers=adm)
    assert pub.status_code == 200, pub.text
    # 60% weight * 70% + 40% weight * 0% retained
    assert pub.json()["overall_progress_percentage"] == 42.0
    assert pub.json()["assessment_coverage_percentage"] == 60.0

    # published => immutable via API and DB
    assert (
        client.patch(f"/reports/{rid}", json={"summary": "rewrite"}, headers=adm).status_code == 409
    )
    assert client.post(f"/reports/{rid}/publish", headers=adm).status_code == 409
    assert (
        client.patch(f"/observations/{o}", json={"title": "changed"}, headers=adm).status_code
        == 409
    )
    with pytest.raises(psycopg.errors.Error, match="immutable"):
        world.c.execute("update public.progress_reports set summary='x' where id=%s", (rid,))

    # client now sees it, without AI internals
    cr = client.get(f"/reports/{rid}", headers=cl)
    assert cr.status_code == 200
    body = cr.json()
    assert body["overall_progress_percentage"] == 42.0 and body["video_url"].startswith(
        "https://st.test/sign/drone-videos"
    )
    assert body["observations"][0]["description"] == "Crew pouring level 1 slab"
    assert "confidence" not in body["observations"][0] and "ai" not in body["work_packages"][0]
    assert body["observations"][0]["evidence"][0]["thumb_url"].endswith("fr/0_t.jpg?token=s")
    assert body["retained_package_count"] == 1
    proj = client.get(f"/projects/{pid}", headers=cl).json()
    assert proj["overall_progress"] == 42.0 and len(proj["history"]) == 2
    # other project's client sees nothing
    assert client.get(f"/reports/{rid}", headers=H(world.cb)).status_code == 404

    # later config changes do not rewrite the published report
    wps = client.get(f"/projects/{pid}", headers=adm).json()["work_packages"]
    new = [
        {
            "id": w["work_package_id"],
            "name": w["name"] + " v2",
            "weight_percentage": 50,
            "initial_approved_percentage": 10,
        }
        for w in wps
    ]
    assert (
        client.post(
            f"/projects/{pid}/work-packages", json={"work_packages": new}, headers=adm
        ).status_code
        == 200
    )
    after = client.get(f"/reports/{rid}", headers=cl).json()
    assert after["overall_progress_percentage"] == 42.0
    assert {w["name"] for w in after["work_packages"]} == {"Foundation", "Roof"}
    assert {w["weight_percentage"] for w in after["work_packages"]} == {60.0, 40.0}


def test_edit_decision_and_coverage(world, storage):
    adm = H(world.admin)
    v, a, o = make_analyzed_video(world)
    rid = client.post(
        f"/projects/{world.A['id']}/reports/draft", json={"video_id": str(v)}, headers=adm
    ).json()["id"]
    dec = {
        "packages": [
            {"work_package_id": world.A["wp1"], "decision": "edit", "approved_percentage": 65},
            {"work_package_id": world.A["wp2"], "decision": "edit", "approved_percentage": 25},
        ]
    }
    client.patch(f"/reports/{rid}", json=dec, headers=adm)
    client.patch(f"/observations/{o}", json={"review_status": "rejected"}, headers=adm)
    out = client.post(f"/reports/{rid}/publish", headers=adm).json()
    assert (
        out["overall_progress_percentage"] == 49.0
        and out["assessment_coverage_percentage"] == 100.0
    )
    snap = client.get(f"/reports/{rid}", headers=adm).json()
    assert snap["observations"] == []  # rejected observations never reach the report


def test_draft_requires_analyzed_video(world, storage):
    assert (
        client.post(
            f"/projects/{world.A['id']}/reports/draft",
            json={"video_id": str(world.B["video_pub"])},
            headers=H(world.admin),
        ).status_code
        == 404
    )  # video of another project
