import json
import subprocess

import cv2
import httpx
import numpy as np
import pytest

from cpm.core.config import Settings
from cpm.pipeline import ai, frames
from cpm.pipeline.errors import PermanentError, TransientError


def make_video(path, lavfi, seconds=30):
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"{lavfi}{':' if '=' in lavfi else '='}duration={seconds}:size=640x360:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path


@pytest.fixture(scope="module")
def moving_video(tmp_path_factory):
    return make_video(tmp_path_factory.mktemp("v") / "moving.mp4", "testsrc2")


S = Settings(frame_sample_interval_sec=5, max_frames=4, blur_threshold=1.0)


# ---------- metadata / validation ----------


def test_probe_reads_metadata(moving_video):
    m = frames.probe(moving_video)
    assert round(m["duration"]) == 30 and (m["width"], m["height"]) == (640, 360)


def test_probe_rejects_non_video(tmp_path):
    bad = tmp_path / "x.mp4"
    bad.write_bytes(b"not a video at all")
    with pytest.raises(PermanentError):
        frames.probe(bad)


# ---------- sampling ----------


def test_sample_timestamps_respect_interval_and_cap():
    ts = frames.sample_timestamps(60, 10, 120)
    assert len(ts) == 6 and ts[0] == 5 and all(t < 60 for t in ts)
    assert len(frames.sample_timestamps(3600, 5, 120)) <= 120  # interval widened for long videos
    assert frames.sample_timestamps(2, 10, 120)  # shorter than one interval still yields a frame


def test_extraction_is_timestamped_capped_and_encoded(moving_video):
    out = frames.extract_frames(moving_video, 30, S)
    assert 1 <= len(out) <= 4
    assert [f.index for f in out] == list(range(len(out)))
    assert all(a.timestamp < b.timestamp for a, b in zip(out, out[1:], strict=False))
    img = cv2.imdecode(np.frombuffer(out[0].jpeg, np.uint8), cv2.IMREAD_COLOR)
    assert max(img.shape[:2]) <= S.frame_max_side
    thumb = cv2.imdecode(np.frombuffer(out[0].thumb, np.uint8), cv2.IMREAD_COLOR)
    assert max(thumb.shape[:2]) <= S.thumb_max_side


def test_static_video_collapses_to_one_frame(tmp_path):
    v = make_video(tmp_path / "static.mp4", "color=c=gray", 20)
    s = Settings(
        frame_sample_interval_sec=2, max_frames=10, blur_threshold=0
    )  # flat colour: only dedupe is tested
    assert len(frames.extract_frames(v, 20, s)) == 1  # duplicates removed


def test_blurry_video_rejected(tmp_path):
    v = make_video(tmp_path / "flat.mp4", "color=c=gray", 10)
    with pytest.raises(PermanentError, match="No usable frames"):
        frames.extract_frames(v, 10, Settings(frame_sample_interval_sec=2, blur_threshold=60))


def test_hash_and_blur_primitives():
    rng = np.random.default_rng(0)
    sharp = rng.integers(0, 255, (120, 160), dtype=np.uint8)
    blurred = cv2.GaussianBlur(sharp, (31, 31), 0)
    assert frames.sharpness(sharp) > 10 * frames.sharpness(blurred)
    assert frames.hamming(frames.dhash(sharp), frames.dhash(sharp.copy())) == 0
    assert (
        frames.hamming(
            frames.dhash(sharp), frames.dhash(rng.integers(0, 255, (120, 160), dtype=np.uint8))
        )
        > 8
    )


# ---------- AI output validation ----------

GOOD = {
    "summary": "Slab work ongoing.",
    "observations": [
        {
            "title": "Slab",
            "description": "Concrete slab visible",
            "category": "concrete",
            "observation_type": "ongoing",
            "work_package_id": "wp1",
            "confidence": 0.8,
            "evidence_frame_indices": [0, 7],
            "evidence_timestamps_seconds": [999],
        }
    ],
    "package_assessments": [
        {
            "work_package_id": "wp1",
            "assessable": True,
            "proposed_completion_percentage": 40,
            "confidence": 0.7,
            "reasoning": "r",
        }
    ],
}
FR = {0: {"id": "f0", "timestamp_seconds": 5.0}, 1: {"id": "f1", "timestamp_seconds": 10.0}}


def test_valid_output_resolves_with_server_side_timestamps():
    structured, warnings = ai.resolve(ai.parse_output(json.dumps(GOOD)), FR, {"wp1"})
    ev = structured["observations"][0]["evidence"]
    assert ev == [
        {"frame_id": "f0", "frame_index": 0, "timestamp_seconds": 5.0}
    ]  # 7 unknown, 999 ignored
    assert any("do not exist" in w for w in warnings)


def test_fenced_json_is_accepted():
    assert ai.parse_output("```json\n" + json.dumps(GOOD) + "\n```").summary


@pytest.mark.parametrize("raw", ["", "no json", "{bad", json.dumps({"observations": []})])
def test_malformed_output_rejected(raw):
    with pytest.raises(ValueError):
        ai.parse_output(raw)


def test_percentage_out_of_range_and_inconsistent_assessable_rejected():
    for pct in (150, -1):
        bad = {
            **GOOD,
            "package_assessments": [
                {
                    "work_package_id": "wp1",
                    "assessable": True,
                    "proposed_completion_percentage": pct,
                }
            ],
        }
        with pytest.raises(ValueError):
            ai.parse_output(json.dumps(bad))
    bad = {**GOOD, "package_assessments": [{"work_package_id": "wp1", "assessable": True}]}
    with pytest.raises(ValueError):
        ai.parse_output(json.dumps(bad))


def test_unassessable_never_becomes_a_number():
    d = {
        **GOOD,
        "package_assessments": [
            {"work_package_id": "wp1", "assessable": False, "proposed_completion_percentage": 0}
        ],
    }
    out = ai.parse_output(json.dumps(d))
    assert out.package_assessments[0].proposed_completion_percentage is None


def test_invalid_references_dropped():
    d = {
        **GOOD,
        "observations": GOOD["observations"]
        + [
            {
                "title": "Ghost",
                "description": "x",
                "observation_type": "ongoing",
                "confidence": 0.9,
                "evidence_frame_indices": [42],
            },
            {
                "title": "BadPkg",
                "description": "x",
                "observation_type": "ongoing",
                "confidence": 0.9,
                "work_package_id": "nope",
                "evidence_frame_indices": [1],
            },
        ],
        "package_assessments": GOOD["package_assessments"]
        + [
            {"work_package_id": "unknown", "assessable": False},
            {"work_package_id": "wp1", "assessable": False},
        ],
    }
    s, w = ai.resolve(ai.parse_output(json.dumps(d)), FR, {"wp1"})
    titles = [o["title"] for o in s["observations"]]
    assert titles == ["Slab", "BadPkg"]  # observation without valid evidence is discarded
    assert s["observations"][1]["work_package_id"] is None
    assert len(s["package_assessments"]) == 1


def test_observation_requires_evidence_and_valid_confidence():
    for patch in (
        {"evidence_frame_indices": []},
        {"confidence": 1.5},
        {"observation_type": "made_up"},
    ):
        bad = {**GOOD, "observations": [{**GOOD["observations"][0], **patch}]}
        with pytest.raises(ValueError):
            ai.parse_output(json.dumps(bad))


# ---------- provider ----------

CFG = Settings(
    qwen_vl_base_url="http://ai.test/v1", qwen_vl_model="served-model", qwen_vl_api_key="k"
)


def provider_with(handler):
    return ai.OpenAICompatibleProvider(CFG, httpx.Client(transport=httpx.MockTransport(handler)))


def chat(content):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_provider_not_configured_is_permanent():
    with pytest.raises(PermanentError, match="not configured"):
        ai.OpenAICompatibleProvider(Settings())


def test_provider_request_shape():
    seen = {}

    def h(req):
        seen["url"], seen["auth"], seen["body"] = (
            str(req.url),
            req.headers["authorization"],
            json.loads(req.content),
        )
        return chat("{}")

    msgs = ai.build_messages(
        {"name": "P"},
        [{"id": "wp1", "name": "Found", "weight_percentage": 100}],
        {"wp1": 10.0},
        [{"frame_index": 0, "timestamp_seconds": 65, "jpeg": b"\xff\xd8"}],
        None,
        [],
    )
    provider_with(h).complete(msgs)
    assert seen["url"] == "http://ai.test/v1/chat/completions" and seen["auth"] == "Bearer k"
    b = seen["body"]
    assert b["model"] == "served-model" and b["response_format"] == {"type": "json_object"}
    parts = b["messages"][1]["content"]
    assert any(
        p["type"] == "image_url" and p["image_url"]["url"].startswith("data:image/jpeg;base64,")
        for p in parts
    )
    assert any(p.get("text") == "Frame 0 at 00:01:05:" for p in parts)


def test_provider_error_classification():
    for status, exc in (
        (500, TransientError),
        (429, TransientError),
        (401, PermanentError),
        (422, PermanentError),
    ):
        with pytest.raises(exc):
            provider_with(lambda r, s=status: httpx.Response(s, text="x")).complete([])

    def boom(req):
        raise httpx.ConnectError("down")

    with pytest.raises(TransientError):
        provider_with(boom).complete([])
    with pytest.raises(TransientError):
        provider_with(lambda r: httpx.Response(200, json={"weird": 1})).complete([])


def test_provider_falls_back_when_json_mode_unsupported():
    calls = []

    def h(req):
        body = json.loads(req.content)
        calls.append("response_format" in body)
        return httpx.Response(400, text="unsupported") if "response_format" in body else chat("ok")

    assert provider_with(h).complete([]) == "ok" and calls == [True, False]


class Scripted:
    def __init__(self, *replies):
        self.replies, self.n = list(replies), 0

    def complete(self, messages):
        self.n += 1
        return self.replies.pop(0)


def test_repair_retries_exactly_once():
    p = Scripted("garbage", json.dumps(GOOD))
    out, _ = ai.run_with_repair(p, [])
    assert out.summary and p.n == 2
    p = Scripted("garbage", "still garbage", json.dumps(GOOD))
    with pytest.raises(PermanentError, match="invalid structured response twice"):
        ai.run_with_repair(p, [])
    assert p.n == 2
