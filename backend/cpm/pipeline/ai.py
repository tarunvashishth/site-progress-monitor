"""Vision-language analysis: prompt, provider adapter, strict validation. Never invents data."""

import base64
import hashlib
import json
import re
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from cpm.core.config import Settings
from cpm.pipeline.errors import PermanentError, TransientError

CATEGORIES = (
    "foundation",
    "concrete",
    "structural",
    "masonry",
    "roofing",
    "exterior",
    "site",
    "issue",
    "other",
)
TYPES = (
    "newly_visible",
    "ongoing",
    "no_visible_change",
    "possible_change",
    "unclear",
    "not_assessable",
)


# ---------- output contract ----------


class ObservationOut(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=5000)
    category: str = "other"
    observation_type: Literal[
        "newly_visible",
        "ongoing",
        "no_visible_change",
        "possible_change",
        "unclear",
        "not_assessable",
    ]
    work_package_id: str | None = None
    confidence: float = Field(ge=0, le=1)
    evidence_frame_indices: list[int] = Field(min_length=1)
    evidence_timestamps_seconds: list[float] = []

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str) -> str:
        v = v.strip().lower()
        return v if v in CATEGORIES else "other"


class AssessmentOut(BaseModel):
    work_package_id: str
    assessable: bool
    proposed_completion_percentage: float | None = Field(default=None, ge=0, le=100)
    confidence: float = Field(default=0, ge=0, le=1)
    reasoning: str = ""
    basis: Literal["visible_work", "target_comparison", "both"] = "visible_work"

    @model_validator(mode="after")
    def _consistent(self):
        if self.assessable and self.proposed_completion_percentage is None:
            raise ValueError("assessable=true requires proposed_completion_percentage")
        if not self.assessable:
            self.proposed_completion_percentage = None  # unknown is never turned into a number
        return self


class ComparisonOut(BaseModel):
    """What changed for one work package between an earlier capture and the current video."""

    work_package_id: str
    comparable: bool
    changed: Literal["yes", "no", "unclear"] = "unclear"
    description: str = Field(default="", max_length=3000)
    current_frame_indices: list[int] = []


class AnalysisOut(BaseModel):
    summary: str = Field(min_length=1, max_length=5000)
    observations: list[ObservationOut] = []
    package_assessments: list[AssessmentOut] = []
    comparison: list[ComparisonOut] = []


def parse_output(raw: str) -> AnalysisOut:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("response contains no JSON object")
    return AnalysisOut.model_validate(json.loads(text[a : b + 1]))


def resolve(
    out: AnalysisOut,
    frames: dict[int, dict],
    package_ids: set[str],
    has_targets: bool = False,
    has_comparison: bool = False,
) -> tuple[dict, list[str]]:
    """Check references against real records. Evidence timestamps come from our frame records,
    never from the model. Returns (structured_response, warnings)."""
    warnings: list[str] = []
    observations = []
    for o in out.observations:
        idx = [i for i in dict.fromkeys(o.evidence_frame_indices) if i in frames]
        if len(idx) != len(set(o.evidence_frame_indices)):
            warnings.append(f"'{o.title}': dropped evidence frame indices that do not exist")
        if not idx:
            warnings.append(f"'{o.title}': discarded (no valid evidence frames)")
            continue
        wp = o.work_package_id
        if wp is not None and wp not in package_ids:
            warnings.append(f"'{o.title}': unknown work_package_id ignored")
            wp = None
        observations.append(
            {
                "title": o.title.strip(),
                "description": o.description.strip(),
                "category": o.category,
                "observation_type": o.observation_type,
                "work_package_id": wp,
                "confidence": o.confidence,
                "evidence": [
                    {
                        "frame_id": str(frames[i]["id"]),
                        "frame_index": i,
                        "timestamp_seconds": float(frames[i]["timestamp_seconds"]),
                    }
                    for i in idx
                ],
            }
        )
    seen, assessments = set(), []
    for a in out.package_assessments:
        if a.work_package_id not in package_ids:
            warnings.append(f"assessment for unknown work package {a.work_package_id} discarded")
        elif a.work_package_id in seen:
            warnings.append(f"duplicate assessment for {a.work_package_id} ignored")
        else:
            seen.add(a.work_package_id)
            d = a.model_dump()
            if d["basis"] != "visible_work" and not has_targets:
                d["basis"] = "visible_work"  # cannot cite a reference that was not provided
                warnings.append(
                    f"assessment {a.work_package_id}: basis reset (no reference images)"
                )
            assessments.append(d)
    comparison = []
    if out.comparison and not has_comparison:
        warnings.append("comparison output discarded (no earlier capture was provided)")
    for k in out.comparison if has_comparison else []:
        if k.work_package_id not in package_ids:
            warnings.append(f"comparison for unknown work package {k.work_package_id} discarded")
            continue
        idx = [i for i in dict.fromkeys(k.current_frame_indices) if i in frames]
        changed = k.changed if k.comparable else "unclear"  # unreliable views never claim change
        if changed == "yes" and not idx:
            changed = "unclear"
            warnings.append(
                f"comparison {k.work_package_id}: change claimed without evidence frames"
            )
        comparison.append(
            {
                "work_package_id": k.work_package_id,
                "comparable": k.comparable,
                "changed": changed,
                "description": k.description.strip(),
                "evidence": [
                    {
                        "frame_id": str(frames[i]["id"]),
                        "frame_index": i,
                        "timestamp_seconds": float(frames[i]["timestamp_seconds"]),
                    }
                    for i in idx
                ],
            }
        )
    return {
        "summary": out.summary.strip(),
        "observations": observations,
        "package_assessments": assessments,
        "comparison": comparison,
        "validation_warnings": warnings,
    }, warnings


# ---------- prompt ----------

SYSTEM = """You are a construction site progress analyst reviewing drone imagery. Rules:
- Describe ONLY what is visible in the provided frames. Never invent activity, measurements, quantities, dates or completion claims.
- Never treat changes in lighting, shadows, weather, camera angle, zoom or image quality as construction progress.
- Reference frames use labels like "PREVIOUS-1" and are from an earlier capture; only claim a change when the views are reasonably comparable (similar angle and distance). Otherwise say the comparison is unreliable.
- Every observation MUST cite evidence_frame_indices of CURRENT frames (the integer after "Frame").
- observation_type is one of: newly_visible, ongoing, no_visible_change, possible_change, unclear, not_assessable.
- category is one of: foundation, concrete, structural, masonry, roofing, exterior, site, issue, other.
- For each work package give an assessment. If the footage cannot support an estimate set assessable=false and proposed_completion_percentage=null. NEVER output 0 to mean "unknown".
- "summary" lists the NEW progress as 3-6 short bullet points, one fact per line, each line starting with "- ". Say what is new since the earlier capture when one is given, otherwise what is visible now. No introduction, no repeated numbers, no padding.
- Estimates are suggestions reviewed by a human; explain visible evidence and limitations in reasoning.
- You are deliberately NOT told earlier approved percentages. Estimate each package's absolute completion from the evidence alone (CURRENT frames, and TARGET images when given). Do not guess a number to look consistent with earlier work; if the evidence is insufficient set assessable=false. Any previous report text is background, never an estimate to repeat.
- "TARGET-n" images show the DESIGN of the finished site (renders or drawings), not the site today. Use them only to judge how much of the finished scope is already visible in the CURRENT frames. Never treat a TARGET image as evidence that work exists; if the CURRENT views cannot be matched to a target view, set assessable=false.
- Earlier-capture images are paired with a current frame when the views look alike ("PREVIOUS-n ... same view as Frame k"). For each work package you can compare, add a "comparison" entry: comparable=false if angle, distance or visibility differ, else changed = yes/no/unclear with what you see. Never infer change from lighting, shadows, weather or camera differences.
- basis says what an estimate rests on: visible_work, target_comparison (needs TARGET images) or both.
Respond with ONE JSON object only, no markdown:
{"summary": "- point\\n- point", "observations": [{"title": str, "description": str, "category": str, "observation_type": str,
 "work_package_id": str|null, "confidence": 0-1, "evidence_frame_indices": [int], "evidence_timestamps_seconds": [number]}],
 "package_assessments": [{"work_package_id": str, "assessable": bool, "proposed_completion_percentage": 0-100|null,
 "confidence": 0-1, "reasoning": str, "basis": "visible_work"|"target_comparison"|"both"}],
 "comparison": [{"work_package_id": str, "comparable": bool, "changed": "yes"|"no"|"unclear", "description": str,
 "current_frame_indices": [int]}]}"""


def _ts(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def _img(jpeg: bytes) -> dict:
    return {
        "type": "image_url",
        "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()},
    }


def build_messages(
    project: dict,
    packages: list[dict],
    current: dict[str, float],
    frames: list[dict],
    prev: dict | None,
    prev_images: list[tuple[str, bytes]],
    targets: list[tuple[str, bytes, str]] | None = None,
    compare_note: str | None = None,
) -> list[dict]:
    pk = "\n".join(
        f"- id={p['id']} | {p['name']} | weight {p['weight_percentage']}% | "
        f"{p.get('description') or ''}"
        for p in packages
    )
    head = (
        f"Project: {project['name']}\nLocation: {project.get('location') or 'n/a'}\n"
        f"Description: {project.get('description') or 'n/a'}\nWork packages:\n{pk}\n"
    )
    if prev:
        head += f"Previous published report ({prev['date']}): {prev['summary']}\n"
    if compare_note:
        head += compare_note + "\n"
    content: list[dict] = [{"type": "text", "text": head}]
    for label, jpeg, caption in targets or []:
        content += [
            {
                "type": "text",
                "text": f"{label} (design of the FINISHED site, not today): {caption}",
            },
            _img(jpeg),
        ]
    for label, jpeg in prev_images:
        content += [
            {"type": "text", "text": f"{label} (earlier capture, reference only):"},
            _img(jpeg),
        ]
    content.append({"type": "text", "text": "CURRENT frames follow."})
    for f in frames:
        content += [
            {"type": "text", "text": f"Frame {f['frame_index']} at {_ts(f['timestamp_seconds'])}:"},
            _img(f["jpeg"]),
        ]
    content.append({"type": "text", "text": "Return the JSON object now."})
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}]


def fingerprint(
    s: Settings,
    frame_hashes: list[str],
    packages: list[dict],
    current: dict,
    prev_ids: list[str],
    extra: dict | None = None,
) -> str:
    payload = {
        "model": s.qwen_vl_model,
        "prompt": s.prompt_version,
        "frames": sorted(frame_hashes),
        "packages": [
            [str(p["id"]), p["name"], str(p["weight_percentage"]), str(current[str(p["id"])])]
            for p in packages
        ],
        "prev": sorted(prev_ids),
    }
    if extra:
        payload["extra"] = extra
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


# ---------- provider ----------


class VisionProvider(Protocol):
    def complete(self, messages: list[dict]) -> str: ...


class OpenAICompatibleProvider:
    """POST {base}/chat/completions (OpenAI schema as served by vLLM/SGLang/etc.).
    Images are sent as data-URL `image_url` parts. Endpoint behaviour must be verified on deployment."""

    def __init__(self, s: Settings, client: httpx.Client | None = None):
        if not (s.qwen_vl_base_url and s.qwen_vl_model):
            raise PermanentError(
                "AI analysis unavailable: QWEN_VL_BASE_URL and QWEN_VL_MODEL are not configured"
            )
        self.s, self.client = s, client or httpx.Client(timeout=s.qwen_vl_timeout_sec)

    def complete(self, messages: list[dict]) -> str:
        body = {
            "model": self.s.qwen_vl_model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 4096,
        }
        if self.s.qwen_vl_json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = (
            {"Authorization": f"Bearer {self.s.qwen_vl_api_key}"} if self.s.qwen_vl_api_key else {}
        )
        url = self.s.qwen_vl_base_url.rstrip("/") + "/chat/completions"
        for attempt in (0, 1):
            try:
                r = self.client.post(url, json=body, headers=headers)
            except httpx.HTTPError as e:
                raise TransientError(f"AI endpoint unreachable: {type(e).__name__}") from None
            if r.status_code == 400 and "response_format" in body and attempt == 0:
                body.pop("response_format")  # server without JSON mode: retry once without it
                continue
            break
        if r.status_code in (408, 409, 425, 429) or r.status_code >= 500:
            raise TransientError(f"AI endpoint returned {r.status_code}")
        if r.status_code >= 400:
            raise PermanentError(f"AI endpoint rejected the request ({r.status_code})")
        try:
            msg = r.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError):
            raise TransientError("AI endpoint returned an unexpected response format") from None
        if isinstance(msg, list):
            msg = "".join(p.get("text", "") for p in msg if isinstance(p, dict))
        return msg or ""


def run_with_repair(provider: VisionProvider, messages: list[dict]) -> tuple[AnalysisOut, str]:
    """Call the model; if the structured output is invalid retry ONCE with the validation error."""
    raw = provider.complete(messages)
    try:
        return parse_output(raw), raw
    except (ValueError, ValidationError) as e:
        fix = messages + [
            {"role": "assistant", "content": raw[:4000]},
            {
                "role": "user",
                "content": f"Your reply was invalid ({str(e)[:500]}). Return ONLY the corrected JSON object.",
            },
        ]
        raw2 = provider.complete(fix)
        try:
            return parse_output(raw2), raw2
        except (ValueError, ValidationError) as e2:
            err = PermanentError(
                f"AI returned an invalid structured response twice: {str(e2)[:300]}"
            )
            err.raw = raw2  # type: ignore[attr-defined]
            raise err from None
