"""Video validation (ffprobe) and representative-frame extraction (OpenCV)."""

import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from cpm.core.config import Settings
from cpm.pipeline.errors import PermanentError


@dataclass
class Frame:
    index: int
    timestamp: float
    jpeg: bytes
    thumb: bytes
    hash: str
    sharpness: float


def probe(path: Path) -> dict:
    """Validate the file with ffprobe and return {duration, width, height, codec}."""
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except FileNotFoundError:
        raise PermanentError("ffprobe is not installed on the worker") from None
    except subprocess.TimeoutExpired:
        raise PermanentError("Video metadata could not be read (timeout)") from None
    if r.returncode != 0:
        raise PermanentError("The file is not a readable video")
    info = json.loads(r.stdout or "{}")
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    if not v:
        raise PermanentError("The file contains no video stream")
    duration = float(info.get("format", {}).get("duration") or v.get("duration") or 0)
    if duration <= 0:
        raise PermanentError("The video has no measurable duration")
    return {
        "duration": duration,
        "width": int(v.get("width", 0)),
        "height": int(v.get("height", 0)),
        "codec": v.get("codec_name"),
    }


def sample_timestamps(duration: float, interval: float, max_candidates: int) -> list[float]:
    """Evenly spaced sample times (mid-interval). Interval grows for long videos to cap candidates."""
    step = max(interval, duration / max_candidates)
    n = max(1, math.floor(duration / step))
    return [
        min(duration - 0.05, (i + 0.5) * step) for i in range(n) if (i + 0.5) * step < duration
    ] or [duration / 2]


def sharpness(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def dhash(gray: np.ndarray) -> str:
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return f"{int(''.join('1' if b else '0' for b in bits), 2):016x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def _resize(img: np.ndarray, max_side: int) -> np.ndarray:
    h, w = img.shape[:2]
    scale = max_side / max(h, w)
    return (
        cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
        if scale < 1
        else img
    )


def _jpeg(img: np.ndarray, q: int) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    if not ok:
        raise PermanentError("Could not encode a frame")
    return buf.tobytes()


def extract_frames(path: Path, duration: float, s: Settings) -> list[Frame]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise PermanentError("OpenCV could not open the video")
    kept: list[tuple[float, np.ndarray, str, float]] = []
    try:
        for t in sample_timestamps(duration, s.frame_sample_interval_sec, s.max_candidate_frames):
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, img = cap.read()
            if not ok or img is None:
                continue
            img = _resize(img, s.frame_max_side)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            sharp = sharpness(gray)
            if sharp < s.blur_threshold:
                continue  # blurry
            h = dhash(gray)
            if kept and hamming(h, kept[-1][2]) <= s.dup_hash_distance:
                continue  # near-duplicate of the previous kept frame
            kept.append((t, img, h, sharp))
    finally:
        cap.release()
    if not kept:
        raise PermanentError("No usable frames: the video is too blurry, static or unreadable")
    if len(kept) > s.max_frames:  # keep an evenly spaced subset
        pick = np.linspace(0, len(kept) - 1, s.max_frames).round().astype(int)
        kept = [kept[i] for i in sorted(set(pick.tolist()))]
    return [
        Frame(i, round(t, 2), _jpeg(img, 85), _jpeg(_resize(img, s.thumb_max_side), 75), h, sh)
        for i, (t, img, h, sh) in enumerate(kept)
    ]
