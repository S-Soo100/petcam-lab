"""Mac mini local Track A 분석 유틸.

production Gemini worker(`backend.vlm.worker`)와 분리된 로컬 검증 경로다.
여기는 `behavior_logs`에 쓰지 않고, contact sheet + JSON artifact만 만든다.
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

from backend.r2_uploader import get_r2_bucket, get_r2_client
from backend.vlm.prompts import BEHAVIOR_CLASSES, SPECIES_CLASSES, Species

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "storage" / "local-track-a"
DEFAULT_MODEL = "gemma3:4b"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_PROMPT_VERSION = "local-track-a-v1"


class LocalTrackAError(RuntimeError):
    """local Track A smoke/eval 단계에서 복구 불가한 오류."""


@dataclass(frozen=True, slots=True)
class LocalTrackAResult:
    """local VLM 출력 artifact. DB row가 아니라 비교용 파일 포맷이다."""

    clip_id: str
    label: str
    confidence: float
    needs_review: bool
    model: str
    prompt_version: str
    evidence: str
    source: str
    contact_sheet_path: str
    latency_sec: float
    raw_response: dict[str, Any]


def _clamp_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))


def _extract_json(text: str) -> dict[str, Any]:
    """Ollama 응답이 ```json fence를 섞어도 object만 회수한다."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end < start:
            raise LocalTrackAError(f"Ollama JSON 파싱 실패: {text[:300]}")
        parsed = json.loads(stripped[start : end + 1])
    if not isinstance(parsed, dict):
        raise LocalTrackAError(f"Ollama 응답이 object가 아님: {parsed!r}")
    return parsed


def download_r2_clip_to_temp(r2_key: str) -> Path:
    """R2 object를 임시 mp4로 다운로드. 호출자가 삭제할 필요 없는 /tmp 파일."""
    client = get_r2_client()
    bucket = get_r2_bucket()
    suffix = Path(r2_key).suffix or ".mp4"
    fd, tmp_name = tempfile.mkstemp(prefix="local-track-a-", suffix=suffix)
    tmp_path = Path(tmp_name)
    with os.fdopen(fd, "wb") as f:
        client.download_fileobj(bucket, r2_key, f)
    return tmp_path


def sample_video_frames(
    video_path: Path,
    *,
    sample_fps: float = 1.0,
    max_frames: int = 60,
) -> list[Image.Image]:
    """mp4에서 균등 시간 간격 프레임을 PIL 이미지로 추출한다."""
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise LocalTrackAError(f"video open 실패: {video_path}")

        source_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if frame_count <= 0:
            raise LocalTrackAError(f"frame_count=0: {video_path}")

        step = max(1, int(round(source_fps / sample_fps)))
        frame_indices = list(range(0, frame_count, step))[:max_frames]
        frames: list[Image.Image] = []
        for frame_idx in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frames.append(Image.fromarray(rgb))

        if not frames:
            raise LocalTrackAError(f"프레임 추출 실패: {video_path}")
        return frames
    finally:
        cap.release()


def make_contact_sheet(
    frames: list[Image.Image],
    output_path: Path,
    *,
    columns: int = 6,
    thumb_width: int = 320,
) -> Path:
    """프레임 여러 장을 로컬 VLM이 보기 쉬운 한 장의 JPG로 합친다."""
    if not frames:
        raise LocalTrackAError("contact sheet 입력 프레임 없음")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    columns = max(1, columns)
    thumb_sizes: list[tuple[int, int]] = []
    resized: list[Image.Image] = []
    for frame in frames:
        ratio = thumb_width / frame.width
        size = (thumb_width, max(1, int(frame.height * ratio)))
        resized.append(frame.resize(size, Image.Resampling.LANCZOS))
        thumb_sizes.append(size)

    label_height = 24
    rows = (len(resized) + columns - 1) // columns
    thumb_height = max(h for _, h in thumb_sizes)
    sheet = Image.new(
        "RGB",
        (columns * thumb_width, rows * (thumb_height + label_height)),
        (18, 18, 18),
    )
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    for idx, frame in enumerate(resized):
        row = idx // columns
        col = idx % columns
        x = col * thumb_width
        y = row * (thumb_height + label_height)
        sheet.paste(frame, (x, y + label_height))
        draw.rectangle((x, y, x + thumb_width, y + label_height), fill=(32, 32, 32))
        draw.text((x + 6, y + 6), f"t+{idx}s", fill=(235, 235, 235), font=font)

    sheet.save(output_path, format="JPEG", quality=88, optimize=True)
    return output_path


def build_local_track_a_prompt(*, species: Species = "crested_gecko") -> str:
    """Track A와 같은 top-1 행동 분류를 local VLM에 요구한다."""
    classes = SPECIES_CLASSES.get(species, BEHAVIOR_CLASSES)
    return "\n".join(
        [
            "You are classifying a reptile petcam contact sheet.",
            "The sheet contains evenly sampled frames from one 60 second motion clip.",
            "Return exactly one JSON object, with no markdown.",
            "",
            "Choose one label from:",
            ", ".join(classes),
            "",
            "Schema:",
            '{"label":"moving","confidence":0.0,"needs_review":true,"evidence":"short visual evidence"}',
            "",
            "Rules:",
            "- confidence must be a number between 0 and 1.",
            "- needs_review is true when the scene is unclear, animal is unseen, or a P0 behavior is possible.",
            "- P0 behaviors are eating_prey, drinking, defecating, shedding.",
            "- evidence must describe visible facts only.",
        ]
    )


def classify_contact_sheet_with_ollama(
    contact_sheet_path: Path,
    *,
    model: str = DEFAULT_MODEL,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    species: Species = "crested_gecko",
    timeout_sec: int = 180,
) -> dict[str, Any]:
    """Ollama vision model 호출. 네트워크 SDK 없이 로컬 HTTP API만 쓴다."""
    image_b64 = base64.b64encode(contact_sheet_path.read_bytes()).decode("ascii")
    payload = {
        "model": model,
        "prompt": build_local_track_a_prompt(species=species),
        "images": [image_b64],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1, "top_p": 0.95},
    }
    req = urllib.request.Request(
        f"{ollama_url.rstrip('/')}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise LocalTrackAError(f"Ollama 호출 실패: {exc}") from exc

    response_text = str(body.get("response") or "")
    return _extract_json(response_text)


def normalize_local_result(
    *,
    clip_id: str,
    model: str,
    contact_sheet_path: Path,
    latency_sec: float,
    raw: dict[str, Any],
    species: Species = "crested_gecko",
    prompt_version: str = DEFAULT_PROMPT_VERSION,
) -> LocalTrackAResult:
    """Ollama 자유 응답을 비교 가능한 local Track A JSON으로 정규화한다."""
    classes = SPECIES_CLASSES.get(species, BEHAVIOR_CLASSES)
    label = str(raw.get("label") or raw.get("action") or "unseen").strip()
    if label not in classes:
        label = "unseen"

    confidence = _clamp_confidence(raw.get("confidence"))
    p0_labels = {"eating_prey", "drinking", "defecating", "shedding"}
    needs_review_raw = raw.get("needs_review")
    needs_review = (
        bool(needs_review_raw)
        if isinstance(needs_review_raw, bool)
        else confidence < 0.7 or label in p0_labels or label == "unseen"
    )
    evidence = str(raw.get("evidence") or raw.get("reasoning") or "").strip()

    return LocalTrackAResult(
        clip_id=clip_id,
        label=label,
        confidence=confidence,
        needs_review=needs_review,
        model=model,
        prompt_version=prompt_version,
        evidence=evidence,
        source="local_vlm",
        contact_sheet_path=str(contact_sheet_path),
        latency_sec=round(latency_sec, 3),
        raw_response=raw,
    )


def analyze_clip_file(
    video_path: Path,
    *,
    clip_id: str | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    model: str = DEFAULT_MODEL,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    species: Species = "crested_gecko",
    sample_fps: float = 1.0,
    max_frames: int = 60,
    thumb_width: int = 320,
    timeout_sec: int = 180,
) -> LocalTrackAResult:
    """로컬 mp4 하나를 contact sheet 기반 local Track A JSON으로 분석한다."""
    load_dotenv(REPO_ROOT / ".env")
    clip_name = clip_id or video_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    contact_sheet_path = output_dir / f"{clip_name}.contact-sheet.jpg"

    started = time.monotonic()
    frames = sample_video_frames(
        video_path,
        sample_fps=sample_fps,
        max_frames=max_frames,
    )
    make_contact_sheet(frames, contact_sheet_path, thumb_width=thumb_width)
    raw = classify_contact_sheet_with_ollama(
        contact_sheet_path,
        model=model,
        ollama_url=ollama_url,
        species=species,
        timeout_sec=timeout_sec,
    )
    latency = time.monotonic() - started
    result = normalize_local_result(
        clip_id=clip_name,
        model=model,
        contact_sheet_path=contact_sheet_path,
        latency_sec=latency,
        raw=raw,
        species=species,
    )
    artifact_path = output_dir / f"{clip_name}.local-track-a.json"
    artifact_path.write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_OLLAMA_URL",
    "DEFAULT_OUTPUT_DIR",
    "DEFAULT_PROMPT_VERSION",
    "LocalTrackAError",
    "LocalTrackAResult",
    "analyze_clip_file",
    "build_local_track_a_prompt",
    "classify_contact_sheet_with_ollama",
    "download_r2_clip_to_temp",
    "make_contact_sheet",
    "normalize_local_result",
    "sample_video_frames",
]
