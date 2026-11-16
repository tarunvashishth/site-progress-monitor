"""Worker end-to-end against the real schema: fake storage, scripted AI provider, generated video."""

import json
import shutil
import subprocess

import pytest

from cpm.core.config import get_settings
from cpm.core.storage import StorageError
from cpm.pipeline.errors import TransientError
from cpm.worker import main as worker


class FakeStorage:
    def __init__(self, video):
        self.video, self.files, self.fail_download = video, {}, False

    def download(self, bucket, path, dest):
        if self.fail_download:
            raise StorageError("storage down")
        shutil.copy(self.video, dest)

    def upload_bytes(self, bucket, path, data, content_type="image/jpeg"):
        self.files[(bucket, path)] = data

    def read(self, bucket, path):
        return self.files[(bucket, path)]


class Provider:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, 0

    def complete(self, messages):
        self.calls += 1
        if self.error:
            raise self.error
        return self.reply(messages) if callable(self.reply) else self.reply


@pytest.fixture(scope="module")
def video_file(tmp_path_factory):
    p = tmp_path_factory.mktemp("w") / "site.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=duration=20:size=640x360:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(p),
        ],
        check=True,
    )
    return p


@pytest.fixture(autouse=True)
def _frames_env(monkeypatch):
    monkeypatch.setenv("FRAME_SAMPLE_INTERVAL_SEC", "4")
    monkeypatch.setenv("MAX_FRAMES", "4")
    monkeypatch.setenv("BLUR_THRESHOLD", "1")
    monkeypatch.setenv("DUP_HASH_DISTANCE", "0")
    get_settings.cache_clear()


def configure_ai(monkeypatch):
    monkeypatch.setenv("QWEN_VL_BASE_URL", "http://ai.test/v1")
    monkeypatch.setenv("QWEN_VL_MODEL", "served-model")
    get_settings.cache_clear()


def reply_for(world):
    def make(messages):
        return json.dumps(
            {
                "summary": "Foundation work visible.",
                "observations": [
                    {
                        "title": "Foundation",
                        "description": "Excavation visible",
                        "category": "foundation",
                        "observation_type": "ongoing",
                        "work_package_id": world.A["wp1"],
                        "confidence": 0.8,
                        "evidence_frame_indices": [0, 1],
                    }
                ],
                "package_assessments": [
                    {
                        "work_package_id": world.A["wp1"],
                        "assessable": True,
                        "proposed_completion_percentage": 60,
                        "confidence": 0.7,
                        "reasoning": "visible",
                    },
                    {
                        "work_package_id": world.A["wp2"],
                        "assessable": False,
                        "reasoning": "not visible",
                    },
                ],
            }
        )

    return make


def new_video(world):
    c = world.c
    v = c.execute(
        "insert into public.drone_videos (project_id,storage_path,original_filename,capture_date,status) "
        "values (%s,%s,'s.mp4','2026-05-01','uploaded') returning id",
        (world.A["id"], f"{world.A['id']}/new/original.mp4"),
    ).fetchone()[0]
    c.execute(
        "insert into public.video_processing_jobs (video_id, job_type) values (%s,'process')", (v,)
    )
    return v


def clear_other_jobs(world):
    world.c.execute(
        "delete from public.video_processing_jobs where status='queued' and video_id <> %s",
        (world.A["video_draft"],),
    )  # keep only the job we create
    world.c.execute(
        "delete from public.video_processing_jobs where video_id in (%s,%s)",
        (world.A["video_draft"], world.B["video_draft"]),
    )


def state(world, v):
    c = world.c
    vid = c.execute(
        "select status, processing_error, duration_seconds from public.drone_videos where id=%s",
        (v,),
    ).fetchone()
    job = c.execute(
        "select status, attempts, error_message from public.video_processing_jobs where video_id=%s "
        "order by created_at desc limit 1",
        (v,),
    ).fetchone()
    return vid, job


def test_happy_path_extracts_frames_and_stores_analysis(world, video_file, monkeypatch):
    configure_ai(monkeypatch)
    clear_other_jobs(world)
    v = new_video(world)
    st, p = FakeStorage(video_file), Provider(reply_for(world))
    assert worker.run_once(st, p) is True
    vid, job = state(world, v)
    assert vid[0] == "analyzed" and round(vid[2]) == 20 and job[0] == "succeeded"
    n = world.c.execute(
        "select count(*), min(timestamp_seconds) from public.video_frames where video_id=%s", (v,)
    ).fetchone()
    assert 2 <= n[0] <= 4 and n[1] > 0
    assert (
        len([k for k in st.files if k[0] == "video-frames"]) == 2 * n[0]
    )  # frame + thumbnail each
    a = world.c.execute(
        "select status, model_name, prompt_version, raw_response is not null, "
        "structured_response->'validation_warnings' from public.ai_analyses where video_id=%s",
        (v,),
    ).fetchone()
    assert a[:4] == ("completed", "served-model", get_settings().prompt_version, True)
    o = world.c.execute(
        "select review_status, jsonb_array_length(evidence_frames), ai_original->>'title' "
        "from public.ai_observations where project_id=%s and title='Foundation' "
        "and analysis_id=(select id from public.ai_analyses where video_id=%s)",
        (world.A["id"], v),
    ).fetchone()
    assert o == ("pending", 2, "Foundation")  # AI never auto-approves
    assert (
        world.c.execute(  # a draft is prepared automatically; nothing is ever published by the worker
            "select status, count(*) from public.progress_reports where video_id=%s group by 1",
            (v,),
        ).fetchall()
        == [("draft", 1)]
    )
    assert worker.run_once(st, p) is False  # queue empty


def test_ai_not_configured_fails_cleanly_keeps_frames_then_retry_works(
    world, video_file, monkeypatch
):
    clear_other_jobs(world)
    v = new_video(world)
    st = FakeStorage(video_file)
    worker.run_once(st, None)
    vid, job = state(world, v)
    assert vid[0] == "failed" and "not configured" in vid[1] and job[0] == "failed"
    assert (
        world.c.execute(
            "select count(*) from public.video_frames where video_id=%s", (v,)
        ).fetchone()[0]
        >= 2
    )
    a = world.c.execute(
        "select status, error_message from public.ai_analyses where video_id=%s", (v,)
    ).fetchone()
    assert a[0] == "unavailable"
    assert (
        world.c.execute(
            "select count(*) from public.ai_observations o join public.ai_analyses a on a.id=o.analysis_id "
            "where a.video_id=%s",
            (v,),
        ).fetchone()[0]
        == 0
    )  # nothing fabricated
    # admin configures AI and retries: only analysis runs, frames are not re-extracted
    configure_ai(monkeypatch)
    world.c.execute(
        "insert into public.video_processing_jobs (video_id, job_type) values (%s,'analyze')", (v,)
    )
    world.c.execute("update public.drone_videos set status='queued' where id=%s", (v,))
    before = world.c.execute(
        "select array_agg(id order by frame_index) from public.video_frames where video_id=%s", (v,)
    ).fetchone()[0]
    st.fail_download = True  # would blow up if the worker tried to re-download the video
    assert worker.run_once(st, Provider(reply_for(world))) is True
    assert state(world, v)[0][0] == "analyzed"
    after = world.c.execute(
        "select array_agg(id order by frame_index) from public.video_frames where video_id=%s", (v,)
    ).fetchone()[0]
    assert before == after


def test_invalid_ai_response_fails_without_observations_and_stores_raw(
    world, video_file, monkeypatch
):
    configure_ai(monkeypatch)
    clear_other_jobs(world)
    v = new_video(world)
    p = Provider("this is not json")
    worker.run_once(FakeStorage(video_file), p)
    vid, job = state(world, v)
    assert vid[0] == "failed" and "invalid structured response" in vid[1] and job[0] == "failed"
    assert p.calls == 2  # one repair attempt
    a = world.c.execute(
        "select status, raw_response from public.ai_analyses where video_id=%s", (v,)
    ).fetchone()
    assert a == ("failed", "this is not json")
    assert (
        world.c.execute(
            "select count(*) from public.ai_observations o join public.ai_analyses a on a.id=o.analysis_id "
            "where a.video_id=%s",
            (v,),
        ).fetchone()[0]
        == 0
    )


def test_transient_failures_requeue_until_attempts_exhausted(world, video_file, monkeypatch):
    configure_ai(monkeypatch)
    clear_other_jobs(world)
    v = new_video(world)
    st, p = FakeStorage(video_file), Provider(error=TransientError("AI endpoint returned 503"))
    worker.run_once(st, p)
    assert state(world, v)[1][:2] == ("queued", 1) and state(world, v)[0][0] == "queued"
    worker.run_once(st, p)
    assert state(world, v)[1][:2] == ("queued", 2)
    worker.run_once(st, p)
    vid, job = state(world, v)
    assert job[:2] == ("failed", 3) and vid[0] == "failed"
    assert worker.run_once(st, p) is False
    # frames survived all attempts and were extracted only once
    assert world.c.execute(
        "select count(*) = count(distinct frame_index) from public.video_frames where video_id=%s",
        (v,),
    ).fetchone()[0]


def test_rerun_of_same_job_does_not_duplicate_analysis_or_observations(
    world, video_file, monkeypatch
):
    configure_ai(monkeypatch)
    clear_other_jobs(world)
    v = new_video(world)
    st, p = FakeStorage(video_file), Provider(reply_for(world))
    worker.run_once(st, p)
    job_id = world.c.execute(
        "select id from public.video_processing_jobs where video_id=%s", (v,)
    ).fetchone()[0]
    from cpm.worker.jobs import run_job

    s = get_settings()
    job = {"id": job_id, "video_id": v, "job_type": "analyze", "force_reanalysis": True}
    run_job(job, st, s, p)  # simulates a crash-and-retry of the same job
    assert (
        world.c.execute(
            "select count(*) from public.ai_analyses where video_id=%s", (v,)
        ).fetchone()[0]
        == 1
    )
    assert (
        world.c.execute(
            "select count(*) from public.ai_observations o join public.ai_analyses a on a.id=o.analysis_id "
            "where a.video_id=%s",
            (v,),
        ).fetchone()[0]
        == 1
    )


def test_identical_inputs_reuse_existing_analysis(world, video_file, monkeypatch):
    configure_ai(monkeypatch)
    clear_other_jobs(world)
    v = new_video(world)
    st, p = FakeStorage(video_file), Provider(reply_for(world))
    worker.run_once(st, p)
    world.c.execute(
        "insert into public.video_processing_jobs (video_id, job_type) values (%s,'analyze')", (v,)
    )
    worker.run_once(st, p)
    assert p.calls == 1  # second run served from the cached analysis
    assert (
        world.c.execute(
            "select count(*) from public.ai_analyses where video_id=%s", (v,)
        ).fetchone()[0]
        == 1
    )
    world.c.execute(
        "insert into public.video_processing_jobs (video_id, job_type, force_reanalysis) values (%s,'analyze',true)",
        (v,),
    )
    worker.run_once(st, p)
    assert p.calls == 2  # force bypasses the cache


def test_corrupt_video_fails_permanently_without_retries(world, tmp_path, monkeypatch):
    configure_ai(monkeypatch)
    clear_other_jobs(world)
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"garbage" * 100)
    v = new_video(world)
    worker.run_once(FakeStorage(bad), Provider(reply_for(world)))
    vid, job = state(world, v)
    assert vid[0] == "failed" and "not a readable video" in vid[1] and job[:2] == ("failed", 1)
