"""새 production motion clip을 local VLM으로만 관찰하는 private shadow runner야."""

from __future__ import annotations

import argparse
import base64
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import threading
import time
from typing import Any, Iterable, Mapping
from urllib import request

import cv2
import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path[:0] = [str(_REPO_ROOT)]

from scripts.local_vlm_clip_shadow import (
    FRAME_FRACTIONS,
    PROMPT,
    PROMPT_VERSION,
    RESULT_SCHEMA,
    build_contact_sheet,
    parse_observation,
    stop_reason,
)
from scripts.seed_rba_boundary_review import load_env_file


MODEL = "gemma3:4b"
OLLAMA_BASE = "http://127.0.0.1:11434"
SOURCE_COLUMNS = "id,camera_id,r2_key,started_at,duration_sec"
MAX_REQUESTS = 20
POLL_INTERVAL_SEC = 60
REQUEST_TIMEOUT_SEC = 120
END_AT = datetime.fromisoformat("2026-08-03T07:00:00+09:00")


class RunnerSafetyError(RuntimeError):
    """읽기 전용·privacy·무중복 계약이 깨지면 fail-closed해."""


class MediaRetryError(RuntimeError):
    """모델 호출 전 R2 일시 오류라 다음 poll에서 다시 확인해."""


class MediaPermanentError(RuntimeError):
    """R2 부재나 decode 실패라 이 표본을 media_error로 확정해."""


@dataclass(frozen=True, slots=True)
class ClipCandidate:
    private_key: str
    clip_id: str
    camera_id: str
    r2_key: str
    started_at: str
    duration_sec: float | None


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def private_token(salt: bytes, namespace: str, raw: str) -> str:
    return hmac.new(salt, f"{namespace}\0{raw}".encode(), hashlib.sha256).hexdigest()[:16]


def require_private_file(path: Path, *, expected_size: int | None = None) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise RunnerSafetyError("private_file_missing")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise RunnerSafetyError("private_file_mode")
    payload = path.read_bytes()
    if expected_size is not None and len(payload) != expected_size:
        raise RunnerSafetyError("private_file_size")
    return payload


def require_private_dir(path: Path) -> None:
    if not path.is_dir() or path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise RunnerSafetyError("private_dir_mode")


def write_new(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(mode)


def _ledger_rows(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    require_private_file(path)
    rows: list[dict[str, object]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if not isinstance(row, dict) or not isinstance(row.get("type"), str):
                raise ValueError
            rows.append(row)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise RunnerSafetyError("ledger_corrupt") from exc
    return rows


def load_processed_keys(path: Path) -> set[str]:
    return {
        str(row["clip"])
        for row in _ledger_rows(path)
        if row["type"] in {"request_intent", "media_error"} and isinstance(row.get("clip"), str)
    }


def append_ledger(path: Path, row: Mapping[str, object]) -> None:
    if not isinstance(row.get("type"), str) or not isinstance(row.get("clip"), str):
        raise RunnerSafetyError("ledger_record")
    existing = _ledger_rows(path)
    if row["type"] == "request_intent" and any(
        old.get("type") == "request_intent" and old.get("clip") == row["clip"] for old in existing
    ):
        raise RunnerSafetyError("duplicate_request_intent")
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "ab") as handle:
            handle.write(canonical_bytes(dict(row)))
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        path.chmod(0o600)


def candidate_from_row(row: Mapping[str, object], salt: bytes) -> ClipCandidate:
    if set(row) != set(SOURCE_COLUMNS.split(",")):
        raise RunnerSafetyError("source_row_fields")
    clip_id = row.get("id")
    camera_id = row.get("camera_id")
    r2_key = row.get("r2_key")
    started_at = row.get("started_at")
    duration = row.get("duration_sec")
    if not all(isinstance(value, str) and value.strip() for value in (clip_id, camera_id, r2_key, started_at)):
        raise RunnerSafetyError("source_row_value")
    duration_value = (
        float(duration)
        if not isinstance(duration, bool) and isinstance(duration, (int, float)) and float(duration) > 0
        else None
    )
    try:
        parsed = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
    except ValueError as exc:
        raise RunnerSafetyError("source_row_started_at") from exc
    if parsed.tzinfo is None:
        raise RunnerSafetyError("source_row_started_at")
    return ClipCandidate(
        private_key=private_token(salt, "clip", str(clip_id)),
        clip_id=str(clip_id),
        camera_id=str(camera_id),
        r2_key=str(r2_key),
        started_at=parsed.isoformat(),
        duration_sec=duration_value,
    )


def fetch_candidates(
    client: Any,
    *,
    start_at: datetime,
    salt: bytes,
    page_size: int = 1000,
) -> tuple[ClipCandidate, ...]:
    # 매 poll마다 같은 start를 다시 조회해야 늦게 기록된 더 이른 started_at row도 잡아.
    query = (
        client.table("motion_clips")
        .select(SOURCE_COLUMNS)
        .gte("started_at", start_at.isoformat())
        .not_.is_("r2_key", "null")
        .order("started_at")
        .order("id")
    )
    rows: list[ClipCandidate] = []
    seen: set[str] = set()
    offset = 0
    while True:
        response = query.range(offset, offset + page_size - 1).execute()
        page = response.data
        if not isinstance(page, list):
            raise RunnerSafetyError("source_select_response")
        for raw in page:
            if not isinstance(raw, dict):
                raise RunnerSafetyError("source_row")
            candidate = candidate_from_row(raw, salt)
            if candidate.clip_id in seen:
                raise RunnerSafetyError("source_duplicate")
            seen.add(candidate.clip_id)
            rows.append(candidate)
        if len(page) < page_size:
            break
        offset += page_size
    return tuple(sorted(rows, key=lambda row: (row.started_at, row.clip_id)))


def select_next_candidate(
    candidates: Iterable[ClipCandidate], processed: set[str]
) -> ClipCandidate | None:
    return next((row for row in candidates if row.private_key not in processed), None)


def build_ollama_payload(jpeg: bytes) -> dict[str, object]:
    return {
        "model": MODEL,
        "messages": [{
            "role": "user",
            "content": PROMPT,
            "images": [base64.b64encode(jpeg).decode("ascii")],
        }],
        "stream": False,
        "think": False,
        "format": RESULT_SCHEMA,
        "keep_alive": "5m",
        "options": {
            "temperature": 0,
            "seed": 20260802,
            "num_ctx": 4096,
            "num_predict": 320,
        },
    }


def ollama_json(endpoint: str, payload: object, *, timeout: int = REQUEST_TIMEOUT_SEC) -> dict[str, object]:
    req = request.Request(
        f"{OLLAMA_BASE}{endpoint}",
        data=canonical_bytes(payload),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as response:
        result = json.loads(response.read())
    if not isinstance(result, dict):
        raise RunnerSafetyError("ollama_response")
    return result


def ollama_get(endpoint: str) -> dict[str, object]:
    with request.urlopen(f"{OLLAMA_BASE}{endpoint}", timeout=10) as response:
        result = json.loads(response.read())
    if not isinstance(result, dict):
        raise RunnerSafetyError("ollama_response")
    return result


def model_inventory() -> dict[str, dict[str, object]]:
    rows = ollama_get("/api/tags").get("models")
    if not isinstance(rows, list):
        raise RunnerSafetyError("ollama_models")
    return {
        str(row["name"]): {"digest": str(row["digest"]), "size": int(row["size"])}
        for row in rows
        if isinstance(row, dict) and row.get("name") and row.get("digest") and row.get("size")
    }


def unload_model() -> None:
    response = ollama_json("/api/chat", {
        "model": MODEL, "messages": [], "stream": False, "keep_alive": 0,
    }, timeout=30)
    if response.get("done_reason") not in {"unload", "stop"}:
        raise RunnerSafetyError("ollama_unload")


def encode_jpeg(frame: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise RunnerSafetyError("jpeg_encode")
    return encoded.tobytes()


def extract_frames(path: Path) -> list[np.ndarray]:
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise MediaPermanentError("video_open")
        count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if count < len(FRAME_FRACTIONS):
            raise MediaPermanentError("video_too_short")
        frames: list[np.ndarray] = []
        for fraction in FRAME_FRACTIONS:
            index = min(count - 1, max(0, round((count - 1) * fraction)))
            if not capture.set(cv2.CAP_PROP_POS_FRAMES, index):
                raise MediaPermanentError("video_seek")
            ok, frame = capture.read()
            if not ok or frame is None:
                raise MediaPermanentError("video_decode")
            frames.append(frame)
        return frames
    finally:
        capture.release()


def parse_swap_used_bytes(payload: str) -> float:
    match = re.search(r"\bused\s*=\s*([0-9]+(?:\.[0-9]+)?)([KMG])\b", payload)
    if match is None:
        raise RunnerSafetyError("swap_parse")
    return float(match.group(1)) * {"K": 1024, "M": 1024**2, "G": 1024**3}[match.group(2)]


def parse_resource_sample(pressure: str, swap: str, processes: str) -> dict[str, object]:
    match = re.search(r"free percentage:\s*([0-9]+)%", pressure, re.IGNORECASE)
    if match is None:
        raise RunnerSafetyError("memory_parse")
    serve: list[tuple[int, int]] = []
    for line in processes.splitlines():
        parts = line.strip().split(maxsplit=2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit() and "ollama serve" in parts[2]:
            serve.append((int(parts[0]), int(parts[1])))
    if len(serve) != 1:
        raise RunnerSafetyError("ollama_serve_pid")
    return {
        "free_percent": int(match.group(1)),
        "swap_used_bytes": parse_swap_used_bytes(swap),
        "serve_pid": serve[0][0],
        "serve_rss_kib": serve[0][1],
    }


def resource_probe() -> dict[str, object]:
    def command(args: list[str]) -> str:
        try:
            result = subprocess.run(args, text=True, capture_output=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as exc:
            raise RunnerSafetyError("resource_command") from exc
        if result.returncode != 0:
            raise RunnerSafetyError("resource_command")
        return result.stdout.strip()

    return parse_resource_sample(
        command(["/usr/bin/memory_pressure", "-Q"]),
        command(["/usr/sbin/sysctl", "-n", "vm.swapusage"]),
        command(["/bin/ps", "-axo", "pid=,rss=,command="]),
    )


class ResourceMonitor:
    def __init__(self, ledger: Path):
        self.ledger = ledger
        self.abort = threading.Event()
        self.stop = threading.Event()
        self.reason: str | None = None
        self.baseline = resource_probe()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        low_streak = 0
        try:
            while not self.stop.is_set():
                row = resource_probe()
                append_ledger(self.ledger, {
                    "type": "resource", "clip": "monitor", "sample": row,
                    "at": datetime.now(timezone.utc).isoformat(),
                })
                low_streak = low_streak + 1 if int(row["free_percent"]) <= 5 else 0
                if low_streak >= 2:
                    self.reason = "free_memory"
                elif float(row["swap_used_bytes"]) - float(self.baseline["swap_used_bytes"]) > 1024**3:
                    self.reason = "swap_growth"
                elif row["serve_pid"] != self.baseline["serve_pid"]:
                    self.reason = "ollama_pid_drift"
                if self.reason:
                    self.abort.set()
                    return
                self.stop.wait(2)
        except Exception as exc:
            self.reason = f"probe_{type(exc).__name__}"
            self.abort.set()

    def __enter__(self) -> "ResourceMonitor":
        append_ledger(self.ledger, {
            "type": "resource", "clip": "monitor", "sample": self.baseline,
            "at": datetime.now(timezone.utc).isoformat(), "baseline": True,
        })
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop.set()
        self.thread.join(timeout=5)


SMOKE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"scene": {"type": "string", "enum": [
        "dark_empty", "static_silhouette", "moving_silhouette"
    ]}},
    "required": ["scene"],
    "additionalProperties": False,
}


def make_synthetic_sheet(scene: str) -> bytes:
    frames = [np.zeros((160, 240, 3), dtype=np.uint8) for _ in range(6)]
    if scene == "static_silhouette":
        for frame in frames:
            frame[:] = 235
            cv2.ellipse(frame, (120, 80), (58, 26), 0, 0, 360, (15, 15, 15), -1)
    elif scene == "moving_silhouette":
        for index, frame in enumerate(frames):
            frame[:] = 235
            cv2.ellipse(frame, (45 + index * 28, 80), (38, 18), 0, 0, 360, (15, 15, 15), -1)
    elif scene != "dark_empty":
        raise RunnerSafetyError("synthetic_scene")
    return encode_jpeg(build_contact_sheet(frames))


def smoke_payload(scene: str, image: bytes) -> dict[str, object]:
    payload = build_ollama_payload(image)
    payload["format"] = SMOKE_SCHEMA
    payload["messages"][0]["content"] = (
        "Classify these six synthetic chronological frames. "
        "Return dark_empty when all frames are empty and dark; static_silhouette when one shape stays fixed; "
        "moving_silhouette when one shape changes location. Return only the schema JSON."
    )
    return payload


def git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=_REPO_ROOT, text=True, capture_output=True, timeout=10
    )
    if result.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}\n?", result.stdout):
        raise RunnerSafetyError("git_head")
    return result.stdout.strip()


def gate_a(args: argparse.Namespace) -> dict[str, object]:
    if args.expected_model != MODEL or datetime.fromisoformat(args.end_at) != END_AT:
        raise RunnerSafetyError("model_or_end_mismatch")
    if socket.gethostname() != args.expected_host or git_head() != args.expected_head:
        raise RunnerSafetyError("host_or_head_mismatch")
    require_private_dir(args.output_dir.parent)
    args.output_dir.mkdir(mode=0o700)
    require_private_dir(args.output_dir)
    require_private_file(args.env_file)
    require_private_file(args.salt_file, expected_size=32)
    inventory = model_inventory()
    if MODEL not in inventory:
        raise RunnerSafetyError("model_missing")
    expected: dict[str, str] = {}
    try:
        for scene in ("dark_empty", "static_silhouette", "moving_silhouette"):
            response = ollama_json("/api/chat", smoke_payload(scene, make_synthetic_sheet(scene)))
            content = response.get("message", {}).get("content") if isinstance(response.get("message"), dict) else None
            parsed = json.loads(str(content))
            if not isinstance(parsed, dict) or parsed != {"scene": scene}:
                raise RunnerSafetyError(f"smoke_{scene}")
            expected[scene] = scene
        production_response = ollama_json("/api/chat", build_ollama_payload(make_synthetic_sheet("moving_silhouette")))
        message = production_response.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        parse_observation(str(content))
        start_at = datetime.now(timezone.utc)
        manifest = {
            "schema_version": "production-local-vlm-clip-shadow-gate-a-v1",
            "host": args.expected_host,
            "code_head": args.expected_head,
            "model": MODEL,
            "model_inventory": inventory[MODEL],
            "prompt_version": PROMPT_VERSION,
            "prompt_sha256": sha256(PROMPT.encode()),
            "schema_sha256": sha256(canonical_bytes(RESULT_SCHEMA)),
            "start_at": start_at.isoformat(),
            "end_at": END_AT.isoformat(),
            "smoke": expected,
            "production_schema_smoke": "valid",
            "pre_resource": resource_probe(),
        }
        write_new(args.output_dir / "gate-a.json", canonical_bytes(manifest))
    finally:
        unload_model()
    return manifest


def load_gate_manifest(args: argparse.Namespace) -> dict[str, object]:
    manifest_path = args.output_dir / "gate-a.json"
    manifest = json.loads(require_private_file(manifest_path))
    inventory = model_inventory()
    expected = {
        "host": args.expected_host,
        "code_head": args.expected_head,
        "model": MODEL,
        "model_inventory": inventory.get(MODEL),
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": sha256(PROMPT.encode()),
        "schema_sha256": sha256(canonical_bytes(RESULT_SCHEMA)),
        "end_at": END_AT.isoformat(),
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise RunnerSafetyError("gate_manifest_drift")
    return manifest


def _r2_client() -> tuple[Any, str]:
    import boto3

    endpoint = os.environ.get("R2_ENDPOINT_URL") or os.environ.get("R2_ENDPOINT")
    access = os.environ.get("R2_ACCESS_KEY_ID")
    secret = os.environ.get("R2_SECRET_ACCESS_KEY")
    bucket = os.environ.get("R2_BUCKET_NAME") or os.environ.get("R2_BUCKET")
    if not all((endpoint, access, secret, bucket)):
        raise RunnerSafetyError("r2_env")
    return boto3.client(
        "s3", endpoint_url=endpoint, aws_access_key_id=access,
        aws_secret_access_key=secret, region_name="auto",
    ), str(bucket)


def download_media(r2: Any, bucket: str, candidate: ClipCandidate, path: Path) -> tuple[int, str]:
    part = path.with_suffix(".part")
    if part.exists():
        if part.is_symlink() or not part.is_file():
            raise RunnerSafetyError("media_part_path")
        part.unlink()
    body: object | None = None
    try:
        head = r2.head_object(Bucket=bucket, Key=candidate.r2_key)
        expected = int(head.get("ContentLength", 0))
        if expected <= 0:
            raise MediaPermanentError("r2_empty")
        response = r2.get_object(Bucket=bucket, Key=candidate.r2_key)
        body = response.get("Body")
        if body is None:
            raise MediaRetryError("r2_body")
        descriptor = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        size = 0
        with os.fdopen(descriptor, "wb") as handle:
            while True:
                chunk = body.read(1024 * 1024)  # type: ignore[attr-defined]
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise MediaRetryError("r2_stream")
                size += len(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        part.chmod(0o600)
        if size != expected:
            raise MediaRetryError("r2_get_size")
        part.replace(path)
        path.chmod(0o600)
    except (MediaRetryError, MediaPermanentError):
        part.unlink(missing_ok=True)
        raise
    except Exception as exc:
        part.unlink(missing_ok=True)
        response_payload = getattr(exc, "response", None)
        error = response_payload.get("Error", {}) if isinstance(response_payload, dict) else {}
        code = str(error.get("Code", "")) if isinstance(error, dict) else ""
        if code in {"404", "NoSuchKey", "NotFound"}:
            raise MediaPermanentError("r2_missing") from exc
        raise MediaRetryError("r2_transient") from exc
    finally:
        close = getattr(body, "close", None)
        if callable(close):
            close()
    with path.open("rb") as handle:
        digest_hex = hashlib.file_digest(handle, "sha256").hexdigest()
    return size, digest_hex


def _existing_media(path: Path) -> tuple[int, str]:
    payload = require_private_file(path)
    return len(payload), sha256(payload)


def media_retry_count(path: Path, private_key: str) -> int:
    return sum(
        row.get("type") == "media_retry" and row.get("clip") == private_key
        for row in _ledger_rows(path)
    )


def ledger_counts(path: Path) -> tuple[int, int]:
    rows = _ledger_rows(path)
    attempted = sum(row.get("type") == "request_intent" for row in rows)
    valid = sum(row.get("type") == "result" and row.get("status") == "schema_valid" for row in rows)
    return attempted, valid


def process_candidate(
    candidate: ClipCandidate,
    *,
    salt: bytes,
    output_dir: Path,
    ledger: Path,
    r2: Any,
    bucket: str,
    model_digest: str,
) -> str:
    media_dir = output_dir / "media"
    input_dir = output_dir / "inputs"
    media_path = media_dir / f"{candidate.private_key}.mp4"
    input_path = input_dir / f"{candidate.private_key}.jpg"
    try:
        if media_path.exists():
            size, media_sha = _existing_media(media_path)
        else:
            if input_path.exists():
                require_private_file(input_path)
                input_path.unlink()
            size, media_sha = download_media(r2, bucket, candidate, media_path)
        if input_path.exists():
            jpeg = require_private_file(input_path)
        else:
            jpeg = encode_jpeg(build_contact_sheet(extract_frames(media_path)))
            write_new(input_path, jpeg)
    except MediaRetryError as exc:
        retries = media_retry_count(ledger, candidate.private_key)
        if retries < 2:
            append_ledger(ledger, {
                "type": "media_retry", "clip": candidate.private_key,
                "camera": private_token(salt, "camera", candidate.camera_id),
                "started_at": candidate.started_at, "attempt": retries + 1,
                "error": type(exc).__name__,
            })
            return "retry"
        append_ledger(ledger, {
            "type": "media_error", "clip": candidate.private_key,
            "camera": private_token(salt, "camera", candidate.camera_id),
            "started_at": candidate.started_at, "error": "transient_exhausted",
        })
        return "processed"
    except (MediaPermanentError, ValueError) as exc:
        append_ledger(ledger, {
            "type": "media_error", "clip": candidate.private_key,
            "camera": private_token(salt, "camera", candidate.camera_id),
            "started_at": candidate.started_at, "error": type(exc).__name__,
        })
        return "processed"

    input_sha = sha256(jpeg)
    append_ledger(ledger, {
        "type": "request_intent", "clip": candidate.private_key,
        "camera": private_token(salt, "camera", candidate.camera_id),
        "started_at": candidate.started_at, "duration_sec": candidate.duration_sec,
        "media_size": size, "media_sha256": media_sha, "input_sha256": input_sha,
        "prompt_sha256": sha256(PROMPT.encode()), "model_digest": model_digest,
        "at": datetime.now(timezone.utc).isoformat(),
    })
    started = time.monotonic()
    raw = ""
    status = "invalid"
    prediction: dict[str, object] | None = None
    error_name: str | None = None
    response_meta: dict[str, object] = {}
    try:
        response = ollama_json("/api/chat", build_ollama_payload(jpeg))
        message = response.get("message")
        raw = str(message.get("content", "")) if isinstance(message, dict) else ""
        if not raw or len(raw.encode()) > 4096:
            raise ValueError("response_size")
        prediction = asdict(parse_observation(raw))
        status = "schema_valid"
        response_meta = {
            "total_duration_ns": int(response.get("total_duration", 0)),
            "load_duration_ns": int(response.get("load_duration", 0)),
            "prompt_eval_count": int(response.get("prompt_eval_count", 0)),
            "eval_count": int(response.get("eval_count", 0)),
        }
    except TimeoutError as exc:
        status = "timeout"
        error_name = type(exc).__name__
    except Exception as exc:  # retry 0: 실패도 그대로 측정값이야.
        error_name = type(exc).__name__
    append_ledger(ledger, {
        "type": "result", "clip": candidate.private_key, "status": status,
        "elapsed_sec": time.monotonic() - started, "prediction": prediction,
        "error": error_name, "raw": raw[:4096], "response_meta": response_meta,
    })
    return "processed"


def run_live(args: argparse.Namespace) -> dict[str, object]:
    if args.expected_model != MODEL or datetime.fromisoformat(args.end_at) != END_AT:
        raise RunnerSafetyError("model_or_end_mismatch")
    if socket.gethostname() != args.expected_host or git_head() != args.expected_head:
        raise RunnerSafetyError("host_or_head_mismatch")
    require_private_dir(args.output_dir)
    require_private_file(args.env_file)
    salt = require_private_file(args.salt_file, expected_size=32)
    load_env_file(args.env_file)
    manifest = load_gate_manifest(args)
    start_at = datetime.fromisoformat(str(manifest["start_at"]))
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RunnerSafetyError("supabase_env")
    client = create_client(url, key)
    r2, bucket = _r2_client()
    for name in ("media", "inputs"):
        path = args.output_dir / name
        if path.exists():
            require_private_dir(path)
        else:
            path.mkdir(mode=0o700)
    ledger = args.output_dir / "ledger.jsonl"
    model_digest = str(manifest["model_inventory"]["digest"])
    verdict = "INCOMPLETE_LIVE_VOLUME"
    try:
        with ResourceMonitor(args.output_dir / "resources.jsonl") as monitor:
            while True:
                attempted, valid = ledger_counts(ledger)
                reason = stop_reason(datetime.now(timezone.utc), END_AT, valid, MAX_REQUESTS, attempted)
                if reason:
                    verdict = reason
                    break
                if monitor.abort.is_set():
                    verdict = "REJECT_RESOURCE"
                    break
                candidates = fetch_candidates(client, start_at=start_at, salt=salt)
                candidate = select_next_candidate(candidates, load_processed_keys(ledger))
                if candidate is None:
                    time.sleep(POLL_INTERVAL_SEC)
                    continue
                outcome = process_candidate(
                    candidate, salt=salt, output_dir=args.output_dir, ledger=ledger,
                    r2=r2, bucket=bucket, model_digest=model_digest,
                )
                if outcome == "retry":
                    time.sleep(POLL_INTERVAL_SEC)
            if monitor.abort.is_set():
                verdict = "REJECT_RESOURCE"
    except RunnerSafetyError:
        verdict = "REJECT_INTEGRITY"
        raise
    finally:
        try:
            unload_model()
        except Exception:
            if verdict not in {"REJECT_INTEGRITY", "REJECT_RESOURCE"}:
                verdict = "REJECT_RESOURCE"
        attempted, valid = ledger_counts(ledger)
        summary = {
            "schema_version": "production-local-vlm-clip-shadow-summary-v1",
            "verdict": verdict, "attempted": attempted, "schema_valid": valid,
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "ledger_sha256": sha256(ledger.read_bytes()) if ledger.exists() else None,
        }
        summary_path = args.output_dir / "summary.json"
        if not summary_path.exists():
            write_new(summary_path, canonical_bytes(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("gate-a", "run"):
        command = sub.add_parser(name)
        command.add_argument("--env-file", type=Path, required=True)
        command.add_argument("--salt-file", type=Path, required=True)
        command.add_argument("--output-dir", type=Path, required=True)
        command.add_argument("--expected-host", required=True)
        command.add_argument("--expected-head", required=True)
        command.add_argument("--expected-model", required=True)
        command.add_argument("--end-at", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = gate_a(args) if args.command == "gate-a" else run_live(args)
    print(json.dumps({
        "status": "GATE_A_PASS" if args.command == "gate-a" else result["verdict"],
        "output_dir": str(args.output_dir),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
