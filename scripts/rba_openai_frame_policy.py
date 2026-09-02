"""OpenAI VLM에 보낼 시간순 개별 JPEG와 window manifest를 만들어."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Iterable, Mapping

import cv2


class FramePolicyError(ValueError):
    """프레임 입력 계약이 깨졌을 때 일부 입력으로 진행하지 않아."""


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def _desired_indices(
    *, frame_count: int, fps: float, start_sec: float, end_sec: float, sample_fps: float
) -> set[int]:
    if sample_fps <= 0 or start_sec < 0 or end_sec < start_sec:
        raise FramePolicyError("sampling_contract")
    indices: set[int] = set()
    step = 1.0 / sample_fps
    timestamp = start_sec
    last_timestamp = min(end_sec, frame_count / fps)
    while timestamp < last_timestamp - 1e-9:
        indices.add(min(frame_count - 1, max(0, round(timestamp * fps))))
        timestamp += step
    return indices


def materialize_frame_manifest(
    video_path: Path,
    *,
    output_dir: Path,
    base_fps: float = 4.0,
    dense_fps: float = 20.0,
    dense_intervals: Iterable[Mapping[str, object]] = (),
    window_sec: float = 6.0,
    overlap_sec: float = 1.0,
) -> dict[str, object]:
    if (
        base_fps <= 0
        or dense_fps < base_fps
        or window_sec <= 0
        or overlap_sec < 0
        or overlap_sec >= window_sec
    ):
        raise FramePolicyError("policy_contract")
    path = video_path.resolve()
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise FramePolicyError("video_open")
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if not math.isfinite(fps) or fps <= 0 or frame_count <= 0:
            raise FramePolicyError("video_metadata")
        duration_sec = frame_count / fps
        policies: dict[int, set[str]] = {}
        base_indices = _desired_indices(
            frame_count=frame_count,
            fps=fps,
            start_sec=0.0,
            end_sec=duration_sec,
            sample_fps=base_fps,
        )
        for index in base_indices:
            policies.setdefault(index, set()).add("base4fps")
        normalized_dense: list[dict[str, float]] = []
        for raw in dense_intervals:
            start = raw.get("start_sec")
            end = raw.get("end_sec")
            if (
                isinstance(start, bool)
                or not isinstance(start, (int, float))
                or isinstance(end, bool)
                or not isinstance(end, (int, float))
                or not math.isfinite(float(start))
                or not math.isfinite(float(end))
                or float(start) < 0
                or float(end) < float(start)
            ):
                raise FramePolicyError("dense_interval")
            start_value = min(duration_sec, float(start))
            end_value = min(duration_sec, float(end))
            normalized_dense.append(
                {"start_sec": start_value, "end_sec": end_value}
            )
            for index in _desired_indices(
                frame_count=frame_count,
                fps=fps,
                start_sec=start_value,
                end_sec=end_value + (1.0 / dense_fps),
                sample_fps=dense_fps,
            ):
                policies.setdefault(index, set()).add("dense20fps")

        if output_dir.exists() or output_dir.is_symlink():
            raise FramePolicyError("output_exists")
        output_dir.mkdir(parents=True, mode=0o700)
        output_dir.chmod(0o700)
        selected = set(policies)
        frames: list[dict[str, object]] = []
        decoded_index = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if decoded_index in selected:
                encode_ok, encoded = cv2.imencode(
                    ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92]
                )
                if not encode_ok:
                    raise FramePolicyError("jpeg_encode")
                payload = encoded.tobytes()
                digest = hashlib.sha256(payload).hexdigest()
                frame_ref = f"frame-{decoded_index:06d}-{digest[:12]}"
                frame_path = output_dir / f"{frame_ref}.jpg"
                descriptor = os.open(
                    frame_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                )
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(payload)
                frame_path.chmod(0o600)
                frames.append(
                    {
                        "frame_ref": frame_ref,
                        "frame_index": decoded_index,
                        "timestamp_sec": round(decoded_index / fps, 6),
                        "sha256": digest,
                        "path": str(frame_path),
                        "source_policies": sorted(policies[decoded_index]),
                        "window_ids": [],
                    }
                )
            decoded_index += 1
    finally:
        capture.release()

    if {row["frame_index"] for row in frames} != selected:
        raise FramePolicyError("incomplete_input")
    windows: list[dict[str, object]] = []
    window_start = 0.0
    window_index = 0
    while window_start < duration_sec - 1e-9:
        window_end = min(duration_sec, window_start + window_sec)
        window_id = f"window-{window_index:03d}"
        refs: list[str] = []
        for row in frames:
            timestamp = float(row["timestamp_sec"])
            if window_start <= timestamp < window_end or (
                window_end == duration_sec and timestamp <= window_end
            ):
                refs.append(str(row["frame_ref"]))
                row["window_ids"].append(window_id)  # type: ignore[union-attr]
        if not refs:
            raise FramePolicyError("empty_window")
        windows.append(
            {
                "window_id": window_id,
                "start_sec": round(window_start, 6),
                "end_sec": round(window_end, 6),
                "frame_refs": refs,
            }
        )
        window_start += window_sec - overlap_sec
        window_index += 1

    covered = {ref for window in windows for ref in window["frame_refs"]}
    expected_refs = {str(row["frame_ref"]) for row in frames}
    if covered != expected_refs:
        raise FramePolicyError("window_coverage")
    manifest: dict[str, object] = {
        "schema_version": "rba-openai-frame-manifest-v1",
        "media_sha256": _sha256_file(path),
        "source_fps": round(fps, 6),
        "duration_sec": round(duration_sec, 6),
        "base_fps": base_fps,
        "dense_fps": dense_fps,
        "dense_intervals": normalized_dense,
        "window_sec": window_sec,
        "overlap_sec": overlap_sec,
        "planned_frame_count": len(selected),
        "actual_frame_count": len(frames),
        "base_coverage_preserved": base_indices.issubset(selected),
        "frames": frames,
        "windows": windows,
    }
    manifest_path = output_dir / "frame-manifest.json"
    descriptor = os.open(
        manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
    )
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(_canonical_bytes(manifest))
        handle.flush()
        os.fsync(handle.fileno())
    manifest_path.chmod(0o600)
    return manifest


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
