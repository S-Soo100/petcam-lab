"""Stream recent R2 clips into resumable private 2fps dense ledgers."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

import cv2
import numpy as np


_FILES = frozenset({"ledger.jsonl", "completion.private.json"})
_FRAME_COUNT_DRIFT_RATIO = 0.01


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dhash64(frame: np.ndarray) -> int:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    reduced = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = reduced[:, 1:] > reduced[:, :-1]
    value = 0
    for bit in bits.flat:
        value = (value << 1) | int(bit)
    return value


def _analysis_gray(frame: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, (64, 36), interpolation=cv2.INTER_AREA)


def _histogram(gray: np.ndarray) -> np.ndarray:
    histogram = cv2.calcHist([gray], [0], None, [32], [0, 256])
    return cv2.normalize(histogram, histogram).flatten()


def _frame_count_tolerance(reported_frame_count: int) -> int:
    """Allow OpenCV's common off-by-one metadata drift, capped at one percent."""

    return max(1, math.floor(reported_frame_count * _FRAME_COUNT_DRIFT_RATIO))


def extract_video_to_directory(
    video_path: Path,
    destination: Path,
    *,
    clip_ref: str,
    camera_night: str,
    expected_size_bytes: int,
    sample_fps: float = 2.0,
) -> dict[str, object]:
    """Decode all native frames and atomically publish one completed clip ledger."""

    if destination.exists():
        raise FileExistsError(destination)
    if not isinstance(clip_ref, str) or not clip_ref:
        raise ValueError("clip_ref is missing")
    if not isinstance(camera_night, str) or not camera_night:
        raise ValueError("camera_night is missing")
    if type(expected_size_bytes) is not int or expected_size_bytes < 1:
        raise ValueError("expected_size_bytes is invalid")
    if video_path.stat().st_size != expected_size_bytes:
        raise ValueError("downloaded source size drift")
    if (
        isinstance(sample_fps, bool)
        or not isinstance(sample_fps, (int, float))
        or not math.isfinite(float(sample_fps))
        or float(sample_fps) <= 0
    ):
        raise ValueError("sample_fps is invalid")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".staging-", dir=destination.parent) as staging_raw:
        staging = Path(staging_raw)
        ledger_path = staging / "ledger.jsonl"
        source_sha256 = _sha256_file(video_path)
        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise ValueError("source video cannot be opened")
        source_fps = float(capture.get(cv2.CAP_PROP_FPS))
        reported_frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if (
            not math.isfinite(source_fps)
            or source_fps <= 0
            or reported_frame_count <= 0
            or width <= 0
            or height <= 0
        ):
            capture.release()
            raise ValueError("source video metadata is invalid")

        decoded = 0
        sampled = 0
        next_sample_sec = 0.0
        sample_interval_sec = 1.0 / float(sample_fps)
        prior_gray: np.ndarray | None = None
        prior_histogram: np.ndarray | None = None
        try:
            with ledger_path.open("x", encoding="utf-8") as ledger:
                while True:
                    ok, frame = capture.read()
                    if not ok:
                        break
                    frame_index = decoded
                    decoded += 1
                    timestamp_sec = frame_index / source_fps
                    if timestamp_sec + 1e-12 < next_sample_sec:
                        continue
                    next_sample_sec += sample_interval_sec

                    encoded_ok, encoded = cv2.imencode(
                        ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 95]
                    )
                    if not encoded_ok:
                        raise ValueError("sample JPEG encoding failed")
                    gray = _analysis_gray(frame)
                    histogram = _histogram(gray)
                    motion_score = (
                        0.0
                        if prior_gray is None
                        else float(np.mean(cv2.absdiff(gray, prior_gray)))
                    )
                    scene_score = (
                        0.0
                        if prior_histogram is None
                        else float(
                            cv2.compareHist(
                                prior_histogram.astype(np.float32),
                                histogram.astype(np.float32),
                                cv2.HISTCMP_BHATTACHARYYA,
                            )
                            * 100.0
                        )
                    )
                    row = {
                        "clip_ref": clip_ref,
                        "camera_night": camera_night,
                        "frame_index": frame_index,
                        "timestamp_ms": round(timestamp_sec * 1000),
                        "image_sha256": hashlib.sha256(encoded.tobytes()).hexdigest(),
                        "dhash64": _dhash64(frame),
                        "motion_score": round(motion_score, 6),
                        "scene_score": round(scene_score, 6),
                        "detector_status": "pending",
                    }
                    ledger.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
                    sampled += 1
                    prior_gray = gray
                    prior_histogram = histogram
        finally:
            capture.release()
        frame_count_tolerance = _frame_count_tolerance(reported_frame_count)
        frame_count_drift = decoded - reported_frame_count
        if frame_count_drift < -frame_count_tolerance:
            raise ValueError("source decode stopped before expected EOF")
        if frame_count_drift > frame_count_tolerance:
            raise ValueError("source decode exceeds reported frame count tolerance")
        if decoded < 1 or sampled < 1:
            raise ValueError("source decode produced no samples")

        completion: dict[str, object] = {
            "status": "DENSE_CLIP_COMPLETE",
            "clip_ref": clip_ref,
            "camera_night": camera_night,
            "source_size_bytes": expected_size_bytes,
            "source_sha256": source_sha256,
            "source_fps": round(source_fps, 6),
            "reported_frame_count": reported_frame_count,
            "decoded_frame_count": decoded,
            "frame_count_drift": frame_count_drift,
            "frame_count_tolerance": frame_count_tolerance,
            "sample_fps": float(sample_fps),
            "sampled_frame_count": sampled,
            "width": width,
            "height": height,
            "ledger_sha256": _sha256_file(ledger_path),
            "opencv_version": cv2.__version__,
        }
        with (staging / "completion.private.json").open("x", encoding="utf-8") as handle:
            json.dump(completion, handle, sort_keys=True, indent=2)
            handle.write("\n")
        os.rename(staging, destination)
        return completion


def validate_completed_clip(
    directory: Path,
    *,
    expected_clip_ref: str,
    expected_camera_night: str,
    expected_size_bytes: int,
    expected_sample_fps: float,
    expected_source_sha256: object | None = None,
) -> dict[str, object]:
    if not directory.is_dir() or {path.name for path in directory.iterdir()} != _FILES:
        raise ValueError("completed clip artifact is partial")
    completion = json.loads((directory / "completion.private.json").read_text())
    if completion.get("status") != "DENSE_CLIP_COMPLETE":
        raise ValueError("completed clip status is invalid")
    if completion.get("clip_ref") != expected_clip_ref:
        raise ValueError("completed clip identity drift")
    if completion.get("camera_night") != expected_camera_night:
        raise ValueError("completed camera-night drift")
    if completion.get("source_size_bytes") != expected_size_bytes:
        raise ValueError("completed source size drift")
    if completion.get("sample_fps") != float(expected_sample_fps):
        raise ValueError("completed sample fps drift")
    if (
        expected_source_sha256 is not None
        and completion.get("source_sha256") != expected_source_sha256
    ):
        raise ValueError("completed source SHA drift")
    if _sha256_file(directory / "ledger.jsonl") != completion.get("ledger_sha256"):
        raise ValueError("completed ledger SHA drift")
    lines = 0
    with (directory / "ledger.jsonl").open(encoding="utf-8") as ledger:
        for line in ledger:
            row = json.loads(line)
            if row.get("clip_ref") != expected_clip_ref:
                raise ValueError("completed ledger clip identity drift")
            if row.get("camera_night") != expected_camera_night:
                raise ValueError("completed ledger camera-night drift")
            lines += 1
    if lines != completion.get("sampled_frame_count"):
        raise ValueError("completed ledger row count drift")
    return completion


def _camera_night(camera_id: str, started_at: str) -> str:
    parsed = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    return f"{camera_id}:{parsed.astimezone().date().isoformat()}"


def _load_r2(env_file: Path) -> tuple[Any, str]:
    import boto3
    from botocore.config import Config
    from dotenv import load_dotenv

    load_dotenv(env_file, override=False)
    required = (
        "R2_ENDPOINT",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET",
    )
    if any(not os.environ.get(name) for name in required):
        raise RuntimeError("required R2 environment is incomplete")
    client = boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    return client, os.environ["R2_BUCKET"]


def _download_source(
    r2: Any,
    *,
    bucket: str,
    key: str,
    destination: Path,
    expected_size_bytes: int,
) -> str:
    r2.download_file(bucket, key, str(destination))
    if destination.stat().st_size != expected_size_bytes:
        raise ValueError("downloaded source size drift")
    return _sha256_file(destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--sample-fps", type=float, default=2.0)
    args = parser.parse_args()

    source_manifest_bytes = args.source_manifest.read_bytes()
    source_manifest = json.loads(source_manifest_bytes)
    sources = [
        row for row in source_manifest["sources"] if row["object_status"] == "available"
    ]
    expected = int(source_manifest["aggregate"]["accessible_clip_count"])
    if len(sources) != expected:
        raise ValueError("source manifest accessible count drift")

    clips_root = args.output_root / "clips"
    final_path = args.output_root / "completion.private.json"
    if final_path.exists():
        raise FileExistsError(final_path)
    clips_root.mkdir(parents=True, exist_ok=True)
    r2, bucket = _load_r2(args.env_file)
    completed_rows: list[dict[str, object]] = []
    reused = 0
    for index, source in enumerate(sources, start=1):
        clip_id = str(source["clip_id"])
        camera_night = _camera_night(
            str(source["camera_id"]), str(source["started_at"])
        )
        expected_source_sha256 = source.get("source_sha256")
        expected_size_bytes = int(source["size_bytes"])
        private_ref = hashlib.sha256(clip_id.encode()).hexdigest()[:24]
        destination = clips_root / private_ref
        if destination.exists():
            if expected_source_sha256 is None:
                with tempfile.TemporaryDirectory(prefix="yolo-v26-source-") as temp_raw:
                    video_path = Path(temp_raw) / "source.mp4"
                    expected_source_sha256 = _download_source(
                        r2,
                        bucket=bucket,
                        key=str(source["r2_key"]),
                        destination=video_path,
                        expected_size_bytes=expected_size_bytes,
                    )
            completion = validate_completed_clip(
                destination,
                expected_clip_ref=clip_id,
                expected_camera_night=camera_night,
                expected_size_bytes=expected_size_bytes,
                expected_sample_fps=args.sample_fps,
                expected_source_sha256=expected_source_sha256,
            )
            reused += 1
        else:
            with tempfile.TemporaryDirectory(prefix="yolo-v26-source-") as temp_raw:
                video_path = Path(temp_raw) / "source.mp4"
                downloaded_source_sha256 = _download_source(
                    r2,
                    bucket=bucket,
                    key=str(source["r2_key"]),
                    destination=video_path,
                    expected_size_bytes=expected_size_bytes,
                )
                if (
                    expected_source_sha256 is not None
                    and downloaded_source_sha256 != expected_source_sha256
                ):
                    raise ValueError("downloaded source SHA drift")
                completion = extract_video_to_directory(
                    video_path,
                    destination,
                    clip_ref=clip_id,
                    camera_night=camera_night,
                    expected_size_bytes=expected_size_bytes,
                    sample_fps=args.sample_fps,
                )
            completion = validate_completed_clip(
                destination,
                expected_clip_ref=clip_id,
                expected_camera_night=camera_night,
                expected_size_bytes=expected_size_bytes,
                expected_sample_fps=args.sample_fps,
                expected_source_sha256=downloaded_source_sha256,
            )
        completed_rows.append(
            {
                "private_ref": private_ref,
                "clip_ref": clip_id,
                "camera_night": completion["camera_night"],
                "source_size_bytes": completion["source_size_bytes"],
                "source_sha256": completion["source_sha256"],
                "ledger_sha256": completion["ledger_sha256"],
                "sample_fps": completion["sample_fps"],
                "sampled_frame_count": completion["sampled_frame_count"],
            }
        )
        if index % 10 == 0 or index == expected:
            print(
                json.dumps(
                    {
                        "status": "DENSE_EXTRACTION_PROGRESS",
                        "completed": index,
                        "expected": expected,
                        "reused": reused,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

    final = {
        "status": "DENSE_EXTRACTION_COMPLETE",
        "source_manifest_sha256": hashlib.sha256(source_manifest_bytes).hexdigest(),
        "source_lineage_sha256": source_manifest["lineage_sha256"],
        "clip_count": len(completed_rows),
        "sampled_frame_count": sum(int(row["sampled_frame_count"]) for row in completed_rows),
        "sample_fps": completed_rows[0]["sample_fps"] if completed_rows else args.sample_fps,
        "clips": completed_rows,
    }
    args.output_root.mkdir(parents=True, exist_ok=True)
    with final_path.open("x", encoding="utf-8") as handle:
        json.dump(final, handle, sort_keys=True, indent=2)
        handle.write("\n")
    print(
        json.dumps(
            {
                "status": final["status"],
                "clip_count": final["clip_count"],
                "sampled_frame_count": final["sampled_frame_count"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
