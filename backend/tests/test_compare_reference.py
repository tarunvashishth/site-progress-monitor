"""Day-to-day comparison + completed-site reference images."""

import json

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from test_api_workflow import H
from test_worker import FakeStorage as WorkerStorage
from test_worker import Provider, configure_ai, video_file  # noqa: F401

from cpm.api.main import app
from cpm.core.config import get_settings
from cpm.pipeline import ai
from cpm.pipeline.compare import pair_frames
from cpm.worker import main as worker

client = TestClient(app)


def png(w=200, h=120, color=(40, 120, 200)) -> bytes:
    img = np.full((h, w, 3), color, np.uint8)
    cv2.rectangle(img, (20, 20), (90, 80), (255, 255, 255), -1)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


# ---------- pairing ----------


def fr(i, h):
    return {"frame_index": i, "image_hash": h}


def test_pairs_only_similar_views_one_to_one():
    cur = [fr(0, "0" * 16), fr(1, "f" * 16)]
    old = [fr(0, "0" * 16), fr(1, "0" * 15 + "1")]
    pairs = pair_frames(cur, old, max_pairs=4, max_distance=8)
    assert [(p["current_index"], p["earlier"]["frame_index"], p["distance"]) for p in pairs] == [
        (0, 0, 0)
    ]  # frame 1 looks nothing like the earlier ones; earlier frame 0 is used once


def test_pairing_caps_and_tolerates_bad_hashes():
    cur = [fr(i, "0" * 16) for i in range(5)] + [fr(9, "not-hex")]
    old = [fr(i, "0" * 16) for i in range(5)]
    assert len(pair_frames(cur, old, max_pairs=3, max_distance=8)) == 3
    assert pair_frames([fr(0, "zz")], old, 4, 8) == []


# ---------- validation ----------

FRAMES = {0: {"id": "f0", "timestamp_seconds": 1.0}, 1: {"id": "f1", "timestamp_seconds": 9.0}}


def out(**kw):
    base = {"summary": "s", "observations": [], "package_assessments": []}
    return ai.AnalysisOut.model_validate({**base, **kw})


def test_comparison_discarded_without_earlier_capture():
    structured, warnings = ai.resolve(
        out(
            comparison=[
                {
                    "work_package_id": "p",
                    "comparable": True,
                    "changed": "yes",
                    "current_frame_indices": [0],
                }
            ]
        ),
        FRAMES,
        {"p"},
        has_comparison=False,
    )
    assert structured["comparison"] == [] and any("discarded" in w for w in warnings)


def test_uncomparable_or_unevidenced_change_becomes_unclear():
    structured, _ = ai.resolve(
        out(
            comparison=[
                {
                    "work_package_id": "p",
                    "comparable": False,
                    "changed": "yes",
                    "current_frame_indices": [0],
                },
                {
                    "work_package_id": "q",
                    "comparable": True,
                    "changed": "yes",
                    "current_frame_indices": [7],
                },
                {
                    "work_package_id": "zz",
                    "comparable": True,
                    "changed": "no",
                    "current_frame_indices": [0],
                },
            ]
        ),
        FRAMES,
        {"p", "q"},
        has_comparison=True,
    )
    assert [(c["work_package_id"], c["changed"]) for c in structured["comparison"]] == [
        ("p", "unclear"),
        ("q", "unclear"),
    ]  # unknown package dropped
    assert (
        structured["comparison"][0]["evidence"][0]["timestamp_seconds"] == 1.0
    )  # from our records


def test_basis_cannot_cite_missing_references():
    a = {
        "work_package_id": "p",
        "assessable": True,
        "proposed_completion_percentage": 40,
        "basis": "both",
    }
    s1, w1 = ai.resolve(out(package_assessments=[a]), FRAMES, {"p"}, has_targets=False)
    assert s1["package_assessments"][0]["basis"] == "visible_work" and w1
    s2, _ = ai.resolve(out(package_assessments=[a]), FRAMES, {"p"}, has_targets=True)
    assert s2["package_assessments"][0]["basis"] == "both"


def test_prompt_labels_targets_and_previous_before_current():
    msgs = ai.build_messages(
        {"name": "P"},
        [{"id": "p", "name": "Roof", "weight_percentage": 100}],
        {"p": 0.0},
        [{"frame_index": 0, "timestamp_seconds": 1, "jpeg": b"x"}],
        None,
        [("PREVIOUS-1 (captured 2026-01-01, same view as Frame 0)", b"y")],
        [("TARGET-1", b"z", "south elevation")],
        "Earlier capture for comparison: 2026-01-01.",
    )
    texts = [c["text"] for c in msgs[1]["content"] if c["type"] == "text"]
    joined = "\n".join(texts)
    assert (
        joined.index("TARGET-1")
        < joined.index("PREVIOUS-1")
        < joined.index("CURRENT frames follow")
    )
    assert "south elevation" in joined and "Earlier capture for comparison" in joined


def test_prompt_hides_earlier_approved_values_to_avoid_anchoring():
    msgs = ai.build_messages(
        {"name": "P"},
        [{"id": "p", "name": "Roof", "weight_percentage": 40, "description": "Steel roof"}],
        {"p": 37.5},
        [{"frame_index": 0, "timestamp_seconds": 1, "jpeg": b"x"}],
        {"date": "2026-01-01", "summary": "Earlier work described"},
        [],
    )
    head = msgs[1]["content"][0]["text"]
    assert "Roof" in head and "weight 40%" in head and "Steel roof" in head
    assert "37.5" not in head and "approved completion" not in head
    assert "NOT told earlier approved percentages" in msgs[0]["content"]


# ---------- RLS ----------


def test_reference_images_are_admin_only(world, as_, admin_conn):
    admin_conn.execute(
        "insert into public.reference_images (project_id, storage_path, original_filename) "
        "values (%s,'a/b.jpg','b.jpg')",
        (world.A["id"],),
    )
    with as_(world.ca) as c:  # client assigned to the project still sees nothing
        assert c.execute("select count(*) from public.reference_images").fetchone()[0] == 0
    with as_(world.admin) as c:
        assert c.execute("select count(*) from public.reference_images").fetchone()[0] == 1


def test_client_cannot_write_reference_images(world, as_):
    import psycopg

    with pytest.raises(psycopg.errors.InsufficientPrivilege | psycopg.errors.InsufficientPrivilege):
        with as_(world.ca) as c:
            c.execute(
                "insert into public.reference_images (project_id, storage_path, original_filename) "
                "values (%s,'x.jpg','x.jpg')",
                (world.A["id"],),
            )
    with as_(world.ca) as c:  # RLS filters the row: nothing is deleted or visible
        assert c.execute("delete from public.reference_images").rowcount == 0


def test_reference_image_limit_and_package_integrity(world, admin_conn):
    import psycopg

    for i in range(6):
        admin_conn.execute(
            "insert into public.reference_images (project_id, storage_path, original_filename) "
            "values (%s,%s,'f')",
            (world.A["id"], f"a/{i}.jpg"),
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute(
            "insert into public.reference_images (project_id, storage_path, original_filename) "
            "values (%s,'a/7.jpg','f')",
            (world.A["id"],),
        )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):  # package of another project
        admin_conn.execute(
            "insert into public.reference_images (project_id, work_package_id, storage_path, original_filename) "
            "values (%s,%s,'b/1.jpg','f')",
            (world.B["id"], world.A["wp1"]),
        )


# ---------- API ----------


class RefStorage:
    def __init__(self):
        self.up, self.removed = {}, []

    def upload_bytes(self, bucket, path, data, content_type="image/jpeg"):
        self.up[(bucket, path)] = data

    def signed_url(self, bucket, path, ttl=None):
        return f"https://st.test/{bucket}/{path}"

    def remove(self, bucket, path):
        self.removed.append((bucket, path))


@pytest.fixture
def refstore():
    from cpm.api.deps import get_storage

    fs = RefStorage()
    app.dependency_overrides[get_storage] = lambda: fs
    yield fs
    app.dependency_overrides.clear()


def test_reference_image_upload_list_delete(world, refstore):
    pid, h = world.A["id"], {**H(world.admin), "Content-Type": "image/png"}
    r = client.post(
        f"/projects/{pid}/reference-images",
        params={
            "filename": "south.png",
            "caption": "South elevation",
            "work_package_id": world.A["wp1"],
        },
        content=png(2000, 1000),
        headers=h,
    )
    assert r.status_code == 201, r.text
    stored = next(iter(refstore.up.values()))
    img = cv2.imdecode(np.frombuffer(stored, np.uint8), cv2.IMREAD_COLOR)
    assert max(img.shape[:2]) == get_settings().reference_max_side  # downscaled, re-encoded JPEG
    items = client.get(f"/projects/{pid}/reference-images", headers=H(world.admin)).json()["items"]
    assert (
        items[0]["caption"] == "South elevation" and items[0]["work_package_name"] == "Foundation"
    )
    assert "storage_path" not in items[0] and items[0]["url"].startswith("https://st.test/")
    assert (
        client.delete(f"/reference-images/{r.json()['id']}", headers=H(world.admin)).status_code
        == 204
    )
    assert refstore.removed


def test_reference_image_rejects_non_images_and_clients(world, refstore):
    pid = world.A["id"]
    bad = client.post(
        f"/projects/{pid}/reference-images",
        content=b"not an image",
        headers={**H(world.admin), "Content-Type": "image/png"},
    )
    assert bad.status_code == 422
    wrong = client.post(
        f"/projects/{pid}/reference-images",
        content=png(),
        headers={**H(world.admin), "Content-Type": "application/pdf"},
    )
    assert wrong.status_code == 422
    as_client = client.post(
        f"/projects/{pid}/reference-images",
        content=png(),
        headers={**H(world.ca), "Content-Type": "image/png"},
    )
    assert as_client.status_code == 403
    assert client.get(f"/projects/{pid}/reference-images", headers=H(world.ca)).status_code == 403
    assert not refstore.up


def test_analyze_compare_target_must_be_earlier_analyzed_same_project(world, refstore):
    a = world.A
    # video_draft (2026-01-02) may be compared with video_pub (2026-01-01) ...
    ok = client.post(
        f"/videos/{a['video_draft']}/analyze",
        json={"compare_to_video_id": a["video_pub"]},
        headers=H(world.admin),
    )
    # ... but the published video can't be re-analyzed (409), and a later/other-project target is refused
    assert ok.status_code in (202, 409)
    for target in (a["video_draft"], world.B["video_pub"]):
        r = client.post(
            f"/videos/{a['video_pub']}/analyze",
            json={"compare_to_video_id": target},
            headers=H(world.admin),
        )
        assert r.status_code in (409, 422)
    r = client.post(
        f"/videos/{a['video_draft']}/analyze",
        json={"compare_to_video_id": world.B["video_pub"], "force": True},
        headers=H(world.admin),
    )
    assert r.status_code in (409, 422)


# ---------- worker: two days + reference ----------


def reply(world, basis):
    def make(messages):
        return json.dumps(
            {
                "summary": "Compared.",
                "observations": [],
                "package_assessments": [
                    {
                        "work_package_id": world.A["wp1"],
                        "assessable": True,
                        "proposed_completion_percentage": 55,
                        "confidence": 0.6,
                        "reasoning": "ok",
                        "basis": basis,
                    }
                ],
                "comparison": [
                    {
                        "work_package_id": world.A["wp1"],
                        "comparable": True,
                        "changed": "yes",
                        "description": "More formwork",
                        "current_frame_indices": [0],
                    }
                ],
            }
        )

    return make


def queue(world, vid, compare_to=None, date="2026-06-01"):
    c = world.c
    v = c.execute(
        "insert into public.drone_videos (project_id,storage_path,original_filename,capture_date,status) "
        "values (%s,%s,'s.mp4',%s,'uploaded') returning id",
        (world.A["id"], f"{world.A['id']}/{vid}/original.mp4", date),
    ).fetchone()[0]
    c.execute(
        "insert into public.video_processing_jobs (video_id, job_type, compare_to_video_id) "
        "values (%s,'process',%s)",
        (v, compare_to),
    )
    return v


def drain(world, st, p):
    world.c.execute(
        "delete from public.video_processing_jobs where status='queued' and video_id in (%s,%s)",
        (world.A["video_draft"], world.B["video_draft"]),
    )
    while worker.run_once(st, p):
        pass


def test_second_day_is_compared_with_first_and_uses_reference(world, video_file, monkeypatch):
    configure_ai(monkeypatch)
    world.c.execute("delete from public.video_processing_jobs")
    st = WorkerStorage(video_file)
    seen = []

    def spy(messages):
        seen.append(messages)
        return reply(world, "both")(messages)

    p = Provider(spy)
    day1 = queue(world, "d1", date="2026-06-01")
    # first capture of the project's new series: nothing earlier than 2026-06-01 except World fixtures
    # (their frames carry non-hex hashes, so no pair is ever formed with them)
    worker.run_once(st, p)
    day2 = queue(world, "d2", compare_to=day1, date="2026-06-08")
    ref_path = f"{world.A['id']}/ref.jpg"
    world.c.execute(
        "insert into public.reference_images (project_id, work_package_id, storage_path, original_filename, caption) "
        "values (%s,%s,%s,'r.png','North elevation, finished')",
        (world.A["id"], world.A["wp1"], ref_path),
    )
    st.files[("reference-images", ref_path)] = png()
    assert worker.run_once(st, p) is True

    a = world.c.execute(
        "select compare_to_video_id, structured_response from public.ai_analyses where video_id=%s",
        (day2,),
    ).fetchone()
    assert str(a[0]) == str(day1)
    sr = a[1]
    assert sr["compared_with"]["video_id"] == str(day1) and sr["compared_with"]["pairs"]
    assert sr["comparison"][0]["changed"] == "yes" and sr["comparison"][0]["evidence"]
    assert sr["package_assessments"][0]["basis"] == "both" and len(sr["reference_image_ids"]) == 1
    texts = "\n".join(c["text"] for c in seen[-1][1]["content"] if c["type"] == "text")
    assert "TARGET-1" in texts and "North elevation, finished" in texts and "PREVIOUS-1" in texts
    # AI still proposes only: observations pending, nothing published
    assert (
        world.c.execute(
            "select count(*) from public.progress_reports where video_id=%s and status='published'",
            (day2,),
        ).fetchone()[0]
        == 0
    )


def test_no_reference_means_basis_reset_and_no_earlier_means_no_comparison(
    world, video_file, monkeypatch
):
    configure_ai(monkeypatch)
    world.c.execute("delete from public.video_processing_jobs")
    world.c.execute(
        "update public.drone_videos set capture_date='2030-01-01' where project_id=%s",
        (world.A["id"],),
    )
    st, p = WorkerStorage(video_file), Provider(reply(world, "target_comparison"))
    solo = queue(world, "solo", date="2026-02-01")  # earlier than every other video of the project
    assert worker.run_once(st, p) is True
    sr = world.c.execute(
        "select structured_response from public.ai_analyses where video_id=%s", (solo,)
    ).fetchone()[0]
    assert sr["comparison"] == [] and "compared_with" not in sr
    assert sr["package_assessments"][0]["basis"] == "visible_work"
    assert any("discarded" in w for w in sr["validation_warnings"])


# ---------- simple admin flow: auto draft + accept-all ----------


def test_draft_is_created_automatically_but_stays_unreviewed(world, video_file, monkeypatch):
    configure_ai(monkeypatch)
    world.c.execute("delete from public.video_processing_jobs")
    st, p = WorkerStorage(video_file), Provider(reply(world, "visible_work"))
    v = queue(world, "auto", date="2026-06-01")
    assert worker.run_once(st, p) is True
    rep = world.c.execute(
        "select status, package_progress_snapshot from public.progress_reports where video_id=%s",
        (v,),
    ).fetchone()
    assert rep and rep[0] == "draft"
    decisions = {i["name"]: i["decision"] for i in rep[1]}
    assert decisions["Foundation"] == "pending"  # AI value proposed, not accepted
    assert decisions["Roof"] == "retain"  # not assessed -> keeps earlier value, never 0
    pending = world.c.execute(
        "select count(*) from public.ai_observations o join public.ai_analyses a on a.id=o.analysis_id "
        "where a.video_id=%s and o.review_status<>'pending'",
        (v,),
    ).fetchone()[0]
    assert pending == 0  # nothing approved automatically
    # re-analysis does not create a second report
    world.c.execute(
        "insert into public.video_processing_jobs (video_id, job_type, force_reanalysis) values (%s,'analyze',true)",
        (v,),
    )
    worker.run_once(st, p)
    assert (
        world.c.execute(
            "select count(*) from public.progress_reports where video_id=%s", (v,)
        ).fetchone()[0]
        == 1
    )


def seed_obs_and_draft(world):
    """Draft for the World's draft video: package 1 pending AI proposal, one pending + one rejected observation."""
    a = world.A
    c = world.c
    c.execute("delete from public.progress_reports where id=%s", (a["report_draft"],))
    c.execute(
        "update public.ai_observations set review_status='pending' where id=%s", (a["obs_draft"],)
    )
    ev = json.dumps([{"frame_id": a["frame_draft"], "frame_index": 0, "timestamp_seconds": 5}])
    c.execute(
        "insert into public.ai_observations (analysis_id,project_id,title,description,observation_type,"
        "confidence,evidence_frames,review_status,ai_original) values (%s,%s,'r','d','ongoing',0.5,%s,"
        "'rejected','{}')",
        (a["analysis_draft"], a["id"], ev),
    )
    items = [
        {
            "work_package_id": a["wp1"],
            "name": "Foundation",
            "weight_percentage": 60,
            "previous_approved_percentage": 50,
            "approved_percentage": None,
            "assessed": False,
            "decision": "pending",
            "ai": {
                "assessable": True,
                "proposed_completion_percentage": 70,
                "confidence": 0.8,
                "reasoning": "x",
            },
        },
        {
            "work_package_id": a["wp2"],
            "name": "Roof",
            "weight_percentage": 40,
            "previous_approved_percentage": 0,
            "approved_percentage": 0,
            "assessed": False,
            "decision": "retain",
            "ai": None,
        },
    ]
    return c.execute(
        "insert into public.progress_reports (project_id,video_id,analysis_id,summary,package_progress_snapshot)"
        " values (%s,%s,%s,'s',%s) returning id",
        (a["id"], a["video_draft"], a["analysis_draft"], json.dumps(items)),
    ).fetchone()[0]


def test_accept_all_approves_pending_only_and_never_publishes(world, refstore):
    rid = seed_obs_and_draft(world)
    r = client.post(f"/reports/{rid}/accept-all", headers=H(world.admin))
    assert r.status_code == 200, r.text
    assert r.json() == {"observations_approved": 1, "packages_accepted": 1, "left_for_review": []}
    st = world.c.execute(
        "select review_status, count(*) from public.ai_observations where analysis_id=%s group by 1 order by 1",
        (world.A["analysis_draft"],),
    ).fetchall()
    assert dict(st) == {"approved": 1, "rejected": 1}  # the rejected one stays rejected
    row = world.c.execute(
        "select status, package_progress_snapshot from public.progress_reports where id=%s", (rid,)
    ).fetchone()
    assert row[0] == "draft"  # publishing is still a separate, explicit admin action
    foundation = next(i for i in row[1] if i["name"] == "Foundation")
    assert foundation["decision"] == "accept" and foundation["approved_percentage"] == 70.0
    # publish still works afterwards and uses only approved values
    pub = client.post(f"/reports/{rid}/publish", headers=H(world.admin))
    assert pub.status_code == 200, pub.text


def test_accept_all_is_admin_only_and_blocked_after_publish(world, refstore):
    rid = seed_obs_and_draft(world)
    assert client.post(f"/reports/{rid}/accept-all", headers=H(world.ca)).status_code == 403
    pub = world.A["report_pub"]
    assert client.post(f"/reports/{pub}/accept-all", headers=H(world.admin)).status_code == 409


def test_accept_all_can_hold_back_big_drops_for_a_human_decision(world, refstore):
    rid = seed_obs_and_draft(world)
    world.c.execute(  # AI now proposes 20 vs 50 approved earlier: a 30-point drop
        "update public.progress_reports set package_progress_snapshot = jsonb_set(package_progress_snapshot,"
        " '{0,ai,proposed_completion_percentage}', '20') where id=%s",
        (rid,),
    )
    r = client.post(f"/reports/{rid}/accept-all", json={"skip_drops": True}, headers=H(world.admin))
    assert r.status_code == 200, r.text
    assert r.json()["packages_accepted"] == 0 and r.json()["left_for_review"] == ["Foundation"]
    row = world.c.execute(
        "select package_progress_snapshot from public.progress_reports where id=%s", (rid,)
    ).fetchone()[0]
    assert next(i for i in row if i["name"] == "Foundation")["decision"] == "pending"
    # publishing stays blocked until the human decides that package
    assert client.post(f"/reports/{rid}/publish", headers=H(world.admin)).status_code == 422
    # without the flag the admin can still accept it knowingly
    r2 = client.post(f"/reports/{rid}/accept-all", headers=H(world.admin))
    assert r2.json()["packages_accepted"] == 1 and r2.json()["left_for_review"] == []


def test_small_changes_are_not_flagged():
    from cpm.core import progress

    def item(prev, proposed):
        return {
            "work_package_id": "x",
            "name": "n",
            "decision": "pending",
            "previous_approved_percentage": prev,
            "ai": {"assessable": True, "proposed_completion_percentage": proposed},
        }

    assert progress.flagged_drops([item(50, 46), item(50, 50), item(50, 70)]) == []
    assert len(progress.flagged_drops([item(50, 44)])) == 1
    assert progress.flagged_drops([{**item(50, 0), "decision": "edit"}]) == []
    assert progress.flagged_drops([{**item(50, 0), "ai": {"assessable": False}}]) == []


def test_prompt_asks_for_new_progress_as_bullets():
    assert "bullet points" in ai.SYSTEM and 'starting with "- "' in ai.SYSTEM
    assert r"- point\n- point" in ai.SYSTEM
