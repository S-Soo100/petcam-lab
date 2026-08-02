"""Mac mini에서 local VLM 사건 경계 development baseline을 one-shot으로 실행해."""

from __future__ import annotations

import argparse
import base64
from dataclasses import asdict, dataclass
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
from urllib import error as urlerror
from urllib import request

import cv2
import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path[:0] = [str(_REPO_ROOT)]

from scripts.local_vlm_event_boundary import (
    A_FRAME_FRACTIONS,
    B_FRAME_FRACTIONS,
    PROMPT,
    PROMPT_VERSION,
    RESULT_SCHEMA,
    BoundaryPrediction,
    parse_prediction,
    score_predictions,
    stable_pair_order,
)
from scripts.seed_rba_boundary_review import load_env_file


EXPECTED_EXPERIMENT = "rba-event-sequence-review-v2"
EXPECTED_MANIFEST = "edd3f2c230adacb70c0b8bc70072eb632eb0ac48718bdd1ffbeca88649e9dfca"
EXPECTED_PAIRS = 74
EXPECTED_CLIPS = 78
MODELS = ("minicpm-v4.6:latest", "qwen3-vl:2b")
OLLAMA_BASE = "http://127.0.0.1:11434"
REQUEST_TIMEOUT_SEC = 120


class RunnerSafetyError(RuntimeError):
    """쓰기·정본·privacy 계약을 지키지 못하면 fail-closed해."""


@dataclass(frozen=True, slots=True)
class MappedPair:
    private_key: str
    pair_digest: str
    left_clip_id: str
    right_clip_id: str
    human_decision: str


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _token(salt: bytes, namespace: str, raw: str) -> str:
    return hmac.new(
        salt,
        f"{namespace}\0{raw}".encode(),
        hashlib.sha256,
    ).hexdigest()[:16]


def require_private_file(path: Path, *, expected_size: int | None = None) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise RunnerSafetyError("private_file_missing")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise RunnerSafetyError("private_file_mode")
    payload = path.read_bytes()
    if expected_size is not None and len(payload) != expected_size:
        raise RunnerSafetyError("private_file_size")
    return payload


def _new_private_dir(path: Path) -> None:
    if not path.parent.is_dir() or stat.S_IMODE(path.parent.stat().st_mode) != 0o700:
        raise RunnerSafetyError("output_parent_mode")
    try:
        path.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise RunnerSafetyError("output_exists") from exc
    path.chmod(0o700)


def _write_new(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(mode)


def map_effective_pairs(
    manifest_pairs: Iterable[Mapping[str, object]],
    db_pairs: Iterable[Mapping[str, object]],
    final_boundaries: Iterable[Mapping[str, object]],
    salt: bytes,
) -> tuple[MappedPair, ...]:
    manifest_by_digest: dict[str, Mapping[str, object]] = {}
    for row in manifest_pairs:
        digest = str(row.get("pair_digest", ""))
        if not digest or digest in manifest_by_digest:
            raise RunnerSafetyError("manifest_mapping")
        manifest_by_digest[digest] = row

    db_by_token: dict[str, Mapping[str, object]] = {}
    for row in db_pairs:
        identity = str(row.get("id", ""))
        digest = str(row.get("pair_digest", ""))
        token = _token(salt, "pair", identity)
        if not identity or not digest or token in db_by_token:
            raise RunnerSafetyError("db_mapping")
        db_by_token[token] = row

    mapped: list[MappedPair] = []
    seen: set[str] = set()
    for final in final_boundaries:
        token = str(final.get("pair", ""))
        decision = str(final.get("decision", ""))
        if token in seen or token not in db_by_token or decision not in {
            "same_event", "different_event"
        }:
            raise RunnerSafetyError("final_mapping")
        seen.add(token)
        db_row = db_by_token[token]
        digest = str(db_row["pair_digest"])
        source = manifest_by_digest.get(digest)
        if source is None:
            raise RunnerSafetyError("manifest_mapping")
        left = str(source.get("left_clip_id", ""))
        right = str(source.get("right_clip_id", ""))
        if not left or not right or left == right:
            raise RunnerSafetyError("clip_mapping")
        mapped.append(MappedPair(token, digest, left, right, decision))
    return tuple(sorted(mapped, key=lambda row: row.private_key))


def _fit_long_edge(frame: np.ndarray, maximum: int = 384) -> np.ndarray:
    height, width = frame.shape[:2]
    scale = min(1.0, maximum / max(height, width))
    if scale == 1.0:
        return frame
    return cv2.resize(
        frame,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA,
    )


def build_contact_sheet(frames: Iterable[np.ndarray], *, label: str) -> np.ndarray:
    rows = [_fit_long_edge(frame) for frame in frames]
    if len(rows) != 4 or any(frame.ndim != 3 or frame.shape[2] != 3 for frame in rows):
        raise RunnerSafetyError("frame_count_or_shape")
    cell_height = max(frame.shape[0] for frame in rows)
    cell_width = max(frame.shape[1] for frame in rows)
    normalized: list[np.ndarray] = []
    for frame in rows:
        canvas = np.zeros((cell_height, cell_width, 3), dtype=np.uint8)
        y = (cell_height - frame.shape[0]) // 2
        x = (cell_width - frame.shape[1]) // 2
        canvas[y:y + frame.shape[0], x:x + frame.shape[1]] = frame
        normalized.append(canvas)
    grid = np.vstack((np.hstack(normalized[:2]), np.hstack(normalized[2:])))
    header = np.full((24, grid.shape[1], 3), 32, dtype=np.uint8)
    cv2.putText(
        header,
        f"VIDEO {label} - chronological frames",
        (8, 17),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return np.vstack((header, grid))


def extract_frames(path: Path, fractions: tuple[float, ...]) -> list[np.ndarray]:
    capture = cv2.VideoCapture(str(path))
    try:
        count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if count < 4:
            raise RunnerSafetyError("video_too_short")
        frames: list[np.ndarray] = []
        for fraction in fractions:
            index = min(count - 1, max(0, round((count - 1) * fraction)))
            if not capture.set(cv2.CAP_PROP_POS_FRAMES, index):
                raise RunnerSafetyError("video_seek_failed")
            ok, frame = capture.read()
            if not ok or frame is None:
                raise RunnerSafetyError("video_decode_failed")
            frames.append(frame)
        return frames
    finally:
        capture.release()


def select_representation(smoke_results: Mapping[str, bool]) -> str:
    if set(smoke_results) != set(MODELS):
        # tests may use arbitrary two model names, but an empty/partial smoke is forbidden.
        if len(smoke_results) != 2:
            raise RunnerSafetyError("smoke_incomplete")
    return "two_images" if all(smoke_results.values()) else "combined_4x2"


def build_ollama_payload(model: str, images: Iterable[bytes]) -> dict[str, object]:
    return {
        "model": model,
        "messages": [{
            "role": "user",
            "content": PROMPT,
            "images": [base64.b64encode(value).decode("ascii") for value in images],
        }],
        "stream": False,
        "think": False,
        "format": RESULT_SCHEMA,
        "keep_alive": "15m",
        "options": {
            "temperature": 0,
            "seed": 20260802,
            "num_ctx": 4096,
            "num_predict": 96,
        },
    }


def _ollama_json(endpoint: str, payload: object, *, timeout: int = REQUEST_TIMEOUT_SEC) -> dict[str, object]:
    body = _canonical_bytes(payload)
    req = request.Request(
        f"{OLLAMA_BASE}{endpoint}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as response:
        parsed = json.loads(response.read())
    if not isinstance(parsed, dict):
        raise RunnerSafetyError("ollama_response")
    return parsed


def _ollama_get(endpoint: str) -> dict[str, object]:
    with request.urlopen(f"{OLLAMA_BASE}{endpoint}", timeout=10) as response:
        parsed = json.loads(response.read())
    if not isinstance(parsed, dict):
        raise RunnerSafetyError("ollama_response")
    return parsed


def model_lifecycle_payload(model: str, *, unload: bool) -> dict[str, object]:
    return {
        "model": model,
        "messages": [],
        "stream": False,
        "keep_alive": 0 if unload else "15m",
    }


def _load_model(model: str) -> float:
    started = time.monotonic()
    result = _ollama_json(
        "/api/chat",
        model_lifecycle_payload(model, unload=False),
        timeout=REQUEST_TIMEOUT_SEC,
    )
    if result.get("done_reason") not in {"load", "stop"}:
        raise RunnerSafetyError("ollama_load")
    return time.monotonic() - started


def _unload_model(model: str) -> None:
    result = _ollama_json(
        "/api/chat",
        model_lifecycle_payload(model, unload=True),
        timeout=30,
    )
    if result.get("done_reason") not in {"unload", "stop"}:
        raise RunnerSafetyError("ollama_unload")


def _model_inventory() -> dict[str, dict[str, object]]:
    payload = _ollama_get("/api/tags")
    models = payload.get("models")
    if not isinstance(models, list):
        raise RunnerSafetyError("ollama_models")
    return {
        str(row["name"]): {
            "digest": str(row["digest"]),
            "size": int(row["size"]),
        }
        for row in models
        if isinstance(row, dict) and row.get("name") and row.get("digest")
    }


def _make_smoke_images() -> tuple[bytes, bytes]:
    a = np.full((220, 320, 3), 255, dtype=np.uint8)
    b = np.full((220, 320, 3), 255, dtype=np.uint8)
    cv2.rectangle(a, (80, 40), (240, 200), (0, 0, 255), -1)
    points = np.array([[160, 35], [55, 200], [265, 200]], np.int32)
    cv2.fillPoly(b, [points], (255, 0, 0))
    return _encode_jpeg(a), _encode_jpeg(b)


def _smoke_model(model: str) -> bool:
    first, second = _make_smoke_images()
    payload = build_ollama_payload(model, (first, second))
    payload["format"] = "json"
    payload["messages"][0]["content"] = (
        "Look at both images. Return JSON with a and b. "
        "a must name the color and shape in image A; b must name the color and shape in image B."
    )
    try:
        result = _ollama_json("/api/chat", payload)
        content = str(result.get("message", {}).get("content", "")).lower()
        return all(word in content for word in ("red", "square", "blue", "triangle"))
    except urlerror.HTTPError as exc:
        if 400 <= exc.code < 500:
            return False
        raise
    finally:
        _unload_model(model)


def _encode_jpeg(frame: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise RunnerSafetyError("jpeg_encode")
    return encoded.tobytes()


def _combined_sheet(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    width = max(first.shape[1], second.shape[1])
    rows: list[np.ndarray] = []
    for sheet in (first, second):
        canvas = np.zeros((sheet.shape[0], width, 3), dtype=np.uint8)
        canvas[:, :sheet.shape[1]] = sheet
        rows.append(canvas)
    combined = np.vstack(rows)
    if max(combined.shape[:2]) > 768:
        combined = _fit_long_edge(combined, 768)
    return combined


def parse_swap_used_bytes(payload: str) -> float:
    match = re.search(r"\bused\s*=\s*([0-9]+(?:\.[0-9]+)?)([KMG])\b", payload)
    if match is None:
        raise RunnerSafetyError("swap_parse")
    multipliers = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}
    return float(match.group(1)) * multipliers[match.group(2)]


class ResourceMonitor:
    def __init__(self, output: Path):
        self.output = output
        self.stop = threading.Event()
        self.abort = threading.Event()
        self.rows: list[dict[str, object]] = []
        self.baseline_swap_bytes: float | None = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    @staticmethod
    def _command(args: list[str]) -> str:
        try:
            result = subprocess.run(args, text=True, capture_output=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as exc:
            raise RunnerSafetyError("resource_command") from exc
        if result.returncode != 0:
            raise RunnerSafetyError("resource_command")
        return result.stdout.strip()

    def _run(self) -> None:
        low_free_streak = 0
        try:
            while not self.stop.is_set():
                pressure = self._command(["/usr/bin/memory_pressure", "-Q"])
                vm_swap = self._command(["/usr/sbin/sysctl", "-n", "vm.swapusage"])
                rss = self._command(["/bin/ps", "-axo", "rss=,comm="])
                free_percent = None
                for token in pressure.replace("%", "").split():
                    try:
                        value = int(token)
                    except ValueError:
                        continue
                    if 0 <= value <= 100:
                        free_percent = value
                ollama_rss = sum(
                    int(line.strip().split(maxsplit=1)[0])
                    for line in rss.splitlines()
                    if "ollama" in line.lower() and line.strip().split(maxsplit=1)[0].isdigit()
                )
                swap_used_bytes = parse_swap_used_bytes(vm_swap)
                if self.baseline_swap_bytes is None:
                    self.baseline_swap_bytes = swap_used_bytes
                self.rows.append({
                    "monotonic_sec": time.monotonic(),
                    "free_percent": free_percent,
                    "swap": vm_swap[:256],
                    "swap_used_bytes": swap_used_bytes,
                    "ollama_rss_kib": ollama_rss,
                })
                low_free_streak = low_free_streak + 1 if free_percent is not None and free_percent <= 5 else 0
                if low_free_streak >= 2:
                    self.abort.set()
                if swap_used_bytes - self.baseline_swap_bytes > 1024 ** 3:
                    self.abort.set()
                self.stop.wait(2)
        except Exception as exc:
            self.rows.append({"monitor_error": type(exc).__name__})
            self.abort.set()

    def __enter__(self) -> "ResourceMonitor":
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop.set()
        self.thread.join(timeout=5)
        _write_new(self.output, _canonical_bytes(self.rows))


def _select_all(query: Any, *, identity: str, page_size: int = 1000) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    seen: set[object] = set()
    start = 0
    while True:
        response = query.range(start, start + page_size - 1).execute()
        page = response.data
        if not isinstance(page, list):
            raise RunnerSafetyError("select_response")
        for raw in page:
            if not isinstance(raw, dict) or raw.get(identity) in seen or raw.get(identity) is None:
                raise RunnerSafetyError("select_identity")
            seen.add(raw[identity])
            rows.append(dict(raw))
        if len(page) < page_size:
            break
        start += page_size
    return tuple(rows)


def _load_db_pairs(client: Any) -> tuple[dict[str, object], ...]:
    cohorts = _select_all(
        client.table("rba_boundary_review_cohorts")
        .select("id,experiment_id,manifest_digest")
        .eq("experiment_id", EXPECTED_EXPERIMENT)
        .eq("manifest_digest", EXPECTED_MANIFEST),
        identity="id",
    )
    if len(cohorts) != 1:
        raise RunnerSafetyError("cohort_drift")
    return _select_all(
        client.table("rba_boundary_review_pairs")
        .select("id,pair_digest")
        .eq("cohort_id", str(cohorts[0]["id"])),
        identity="id",
    )


def _load_r2_keys(client: Any, clip_ids: set[str]) -> dict[str, str]:
    rows: list[dict[str, object]] = []
    ordered = sorted(clip_ids)
    for start in range(0, len(ordered), 100):
        response = (
            client.table("motion_clips")
            .select("id,r2_key")
            .in_("id", ordered[start:start + 100])
            .execute()
        )
        if not isinstance(response.data, list):
            raise RunnerSafetyError("clip_select")
        rows.extend(response.data)
    keys = {
        str(row["id"]): str(row["r2_key"])
        for row in rows
        if isinstance(row, dict) and row.get("id") and row.get("r2_key")
    }
    if set(keys) != clip_ids or any(not value.strip() for value in keys.values()):
        raise RunnerSafetyError("r2_key_mapping")
    return keys


def _r2_client() -> tuple[Any, str]:
    import boto3

    endpoint = os.environ.get("R2_ENDPOINT_URL") or os.environ.get("R2_ENDPOINT")
    access = os.environ.get("R2_ACCESS_KEY_ID")
    secret = os.environ.get("R2_SECRET_ACCESS_KEY")
    bucket = os.environ.get("R2_BUCKET_NAME") or os.environ.get("R2_BUCKET")
    if not all((endpoint, access, secret, bucket)):
        raise RunnerSafetyError("r2_env")
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name="auto",
    ), str(bucket)


def _latency_stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"p50": 0.0, "p95": 0.0, "max": 0.0}
    def percentile(value: float) -> float:
        index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * value)))
        return ordered[index]
    return {"p50": percentile(0.5), "p95": percentile(0.95), "max": ordered[-1]}


def run(args: argparse.Namespace) -> dict[str, object]:
    if socket.gethostname() != args.expected_host:
        raise RunnerSafetyError("host_mismatch")
    require_private_file(args.env_file)
    salt = require_private_file(args.salt_file, expected_size=32)
    require_private_file(args.base_artifact)
    require_private_file(args.analysis_private)
    load_env_file(args.env_file)

    manifest = json.loads(args.base_artifact.read_text())
    analysis = json.loads(args.analysis_private.read_text())
    if (
        manifest.get("experiment_id") != EXPECTED_EXPERIMENT
        or manifest.get("manifest_sha256") != EXPECTED_MANIFEST
        or not isinstance(manifest.get("pairs"), list)
        or not isinstance(analysis.get("final_boundaries"), list)
    ):
        raise RunnerSafetyError("source_provenance")

    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RunnerSafetyError("supabase_env")
    client = create_client(url, key)
    mapped = map_effective_pairs(
        manifest["pairs"],
        _load_db_pairs(client),
        analysis["final_boundaries"],
        salt,
    )
    if len(mapped) != EXPECTED_PAIRS:
        raise RunnerSafetyError("effective_pair_count")
    clip_ids = {row.left_clip_id for row in mapped} | {row.right_clip_id for row in mapped}
    if len(clip_ids) != EXPECTED_CLIPS:
        raise RunnerSafetyError("unique_clip_count")

    inventory = _model_inventory()
    if not all(model in inventory for model in MODELS):
        raise RunnerSafetyError("model_missing")

    _new_private_dir(args.output_dir)
    media_dir = args.output_dir / "media"
    input_dir = args.output_dir / "inputs"
    media_dir.mkdir(mode=0o700)
    input_dir.mkdir(mode=0o700)

    smoke = {model: _smoke_model(model) for model in MODELS}
    representation = select_representation(smoke)
    r2_keys = _load_r2_keys(client, clip_ids)
    r2, bucket = _r2_client()
    media_paths: dict[str, Path] = {}
    media_rows: list[dict[str, object]] = []
    for clip_id in sorted(clip_ids):
        key_value = r2_keys[clip_id]
        head = r2.head_object(Bucket=bucket, Key=key_value)
        if int(head.get("ContentLength", 0)) <= 0:
            raise RunnerSafetyError("r2_head")
        token = _token(salt, "clip", clip_id)
        destination = media_dir / f"{token}.mp4"
        r2.download_file(bucket, key_value, str(destination))
        destination.chmod(0o600)
        if destination.stat().st_size != int(head["ContentLength"]):
            raise RunnerSafetyError("r2_get_size")
        capture = cv2.VideoCapture(str(destination))
        try:
            if not capture.isOpened() or int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) < 4:
                raise RunnerSafetyError("r2_media_decode")
        finally:
            capture.release()
        media_paths[clip_id] = destination
        media_rows.append({"clip": token, "size": destination.stat().st_size, "sha256": _sha256(destination.read_bytes())})

    input_rows: list[dict[str, object]] = []
    input_bytes: dict[str, tuple[bytes, ...]] = {}
    mapped_by_key = {row.private_key: row for row in mapped}
    order = stable_pair_order(mapped_by_key, seed="20260802")
    for private_key in order:
        row = mapped_by_key[private_key]
        sheet_a = build_contact_sheet(extract_frames(media_paths[row.left_clip_id], A_FRAME_FRACTIONS), label="A")
        sheet_b = build_contact_sheet(extract_frames(media_paths[row.right_clip_id], B_FRAME_FRACTIONS), label="B")
        if representation == "two_images":
            payloads = (_encode_jpeg(sheet_a), _encode_jpeg(sheet_b))
            suffixes = ("A", "B")
        else:
            payloads = (_encode_jpeg(_combined_sheet(sheet_a, sheet_b)),)
            suffixes = ("AB",)
        for suffix, payload in zip(suffixes, payloads, strict=True):
            path = input_dir / f"{private_key}-{suffix}.jpg"
            _write_new(path, payload)
        input_bytes[private_key] = payloads
        input_rows.append({
            "pair": private_key,
            "human": row.human_decision,
            "images": [_sha256(value) for value in payloads],
        })

    prompt_sha = _sha256(PROMPT.encode())
    model_order = stable_pair_order(MODELS, seed="20260802-model")
    frozen = {
        "experiment_id": EXPECTED_EXPERIMENT,
        "manifest_digest": EXPECTED_MANIFEST,
        "pair_count": len(mapped),
        "clip_count": len(clip_ids),
        "representation": representation,
        "smoke": smoke,
        "models": {model: inventory[model] for model in MODELS},
        "model_order": list(model_order),
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": prompt_sha,
        "media": media_rows,
        "inputs": input_rows,
    }
    _write_new(args.output_dir / "frozen-manifest.json", _canonical_bytes(frozen))

    results_path = args.output_dir / "results.jsonl"
    results_handle = os.fdopen(
        os.open(results_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
        "wb",
    )
    summaries: dict[str, object] = {}
    try:
        with ResourceMonitor(args.output_dir / "resources.json") as monitor:
            for model in model_order:
                predictions: dict[str, BoundaryPrediction | None] = {}
                latencies: list[float] = []
                model_digest = str(inventory[model]["digest"])
                load_sec = _load_model(model)
                try:
                    for private_key in order:
                        if monitor.abort.is_set():
                            raise RunnerSafetyError("resource_abort")
                        started = time.monotonic()
                        raw = ""
                        error = None
                        response_meta: dict[str, object] = {}
                        try:
                            response = _ollama_json(
                                "/api/chat",
                                build_ollama_payload(model, input_bytes[private_key]),
                            )
                            elapsed = time.monotonic() - started
                            message = response.get("message")
                            raw = str(message.get("content", "")) if isinstance(message, dict) else ""
                            if len(raw.encode()) > 4096:
                                raise ValueError("raw_response_too_large")
                            prediction = parse_prediction(raw)
                            response_meta = {
                                "total_duration_ns": int(response.get("total_duration", 0)),
                                "load_duration_ns": int(response.get("load_duration", 0)),
                                "prompt_eval_count": int(response.get("prompt_eval_count", 0)),
                                "eval_count": int(response.get("eval_count", 0)),
                            }
                        except Exception as exc:  # measured key는 retry 없이 실패를 기록해.
                            elapsed = time.monotonic() - started
                            prediction = None
                            error = type(exc).__name__
                        latencies.append(elapsed)
                        predictions[private_key] = prediction
                        record = {
                            "model": model,
                            "model_digest": model_digest,
                            "pair": private_key,
                            "human": mapped_by_key[private_key].human_decision,
                            "input_sha256": [_sha256(value) for value in input_bytes[private_key]],
                            "prompt_sha256": prompt_sha,
                            "elapsed_sec": elapsed,
                            "prediction": asdict(prediction) if prediction is not None else None,
                            "error": error,
                            "raw": raw[:4096],
                            "response_meta": response_meta,
                        }
                        results_handle.write(_canonical_bytes(record))
                        results_handle.flush()
                        os.fsync(results_handle.fileno())
                    score = score_predictions(
                        {key: mapped_by_key[key].human_decision for key in order},  # type: ignore[arg-type]
                        predictions,
                        expected_count=EXPECTED_PAIRS,
                    )
                    summaries[model] = {
                        "score": asdict(score),
                        "load_sec": load_sec,
                        "latency_sec": _latency_stats(latencies),
                    }
                finally:
                    _unload_model(model)
    finally:
        results_handle.close()
        results_path.chmod(0o600)

    post_inventory = _model_inventory()
    if any(post_inventory.get(model) != inventory.get(model) for model in MODELS):
        raise RunnerSafetyError("model_digest_drift")
    summary = {
        "schema_version": "local-vlm-event-boundary-summary-v1",
        "representation": representation,
        "models": summaries,
        "record_count": EXPECTED_PAIRS * len(MODELS),
        "frozen_manifest_sha256": _sha256(_canonical_bytes(frozen)),
        "results_sha256": _sha256(results_path.read_bytes()),
    }
    _write_new(args.output_dir / "summary.json", _canonical_bytes(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--base-artifact", type=Path, required=True)
    parser.add_argument("--analysis-private", type=Path, required=True)
    parser.add_argument("--salt-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-host", required=True)
    return parser.parse_args()


def main() -> int:
    summary = run(parse_args())
    print(json.dumps({
        "status": "MEASURED_RUN_COMPLETE",
        "record_count": summary["record_count"],
        "summary_sha256": _sha256(_canonical_bytes(summary)),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
