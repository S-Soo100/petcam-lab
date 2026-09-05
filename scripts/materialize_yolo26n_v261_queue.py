"""Download and materialize the private YOLO26n v2.6.1 blind review queue."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import Path

try:
    from scripts.build_yolo26n_v261_expanded_queue import deduplicate_candidate_frames
    from scripts.build_yolo26n_v25_owner_hardcase_queue import (
        _snapshot_source,
        mine_owner_video,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from build_yolo26n_v261_expanded_queue import deduplicate_candidate_frames
    from build_yolo26n_v25_owner_hardcase_queue import _snapshot_source, mine_owner_video


DETECTOR_ANOMALY_REASONS = {
    "zero_visible",
    "unknown_high",
    "detection_gap",
    "fragmentation",
    "position_jump",
    "multi_gecko_or_reflection",
}


def mining_limits(reasons: Iterable[str]) -> tuple[int, int]:
    reason_set = set(reasons)
    if "owner_confirmed" in reason_set:
        return (40, 40)
    if reason_set & DETECTOR_ANOMALY_REASONS:
        return (6, 6)
    return (4, 2)


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError("JSON object required")
    return payload


def load_protected_exact_shas(dataset_manifest: Path) -> set[str]:
    records = _read_json(dataset_manifest).get("records")
    if not isinstance(records, list):
        raise ValueError("invalid protected dataset manifest")
    result = {
        str(row.get("image_sha256"))
        for row in records
        if isinstance(row, Mapping) and len(str(row.get("image_sha256") or "")) == 64
    }
    if not result:
        raise ValueError("protected dataset fingerprints missing")
    return result


def load_protected_fingerprints(
    dataset_manifest: Path, selection_manifest: Path
) -> list[dict[str, str]]:
    load_protected_exact_shas(dataset_manifest)
    records = _read_json(selection_manifest).get("records")
    if not isinstance(records, list):
        raise ValueError("invalid protected selection manifest")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in records:
        if not isinstance(row, Mapping):
            raise ValueError("invalid protected fingerprint row")
        image_sha = str(row.get("image_sha256") or "")
        dhash = str(row.get("dhash64") or "")
        clip_ref = str(row.get("clip_ref") or "")
        if len(image_sha) != 64 or len(dhash) != 16 or not clip_ref:
            raise ValueError("protected fingerprint mismatch")
        if image_sha not in seen:
            result.append(
                {"clip_ref": clip_ref, "image_sha256": image_sha, "dhash64": dhash}
            )
            seen.add(image_sha)
    if not result:
        raise ValueError("protected perceptual fingerprints missing")
    return sorted(result, key=lambda row: row["image_sha256"])


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _write_json_new(path: Path, payload: object) -> None:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _development_records(path: Path, expected_sha256: str) -> list[dict[str, object]]:
    payload = _read_json(path)
    if _canonical_sha256(payload) != expected_sha256:
        raise ValueError("development manifest SHA mismatch")
    if payload.get("schema") != "yolo26n-v261-development-sources-v1":
        raise ValueError("development manifest schema mismatch")
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("development source shortage")
    result: list[dict[str, object]] = []
    for row in records:
        if not isinstance(row, Mapping):
            raise ValueError("development source contract mismatch")
        if not all(row.get(key) for key in ("clip_ref", "camera_ref", "r2_key", "reasons")):
            raise ValueError("development source contract mismatch")
        result.append(dict(row))
    return result


def download_sources(args: argparse.Namespace) -> dict[str, object]:
    from dotenv import load_dotenv

    output = args.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    output.chmod(0o700)
    completion_path = output / "download-completion.private.json"
    if completion_path.exists():
        return _read_json(completion_path)

    load_dotenv(args.env_file)
    sys.path.insert(0, str(args.reporter_repo.resolve()))
    from reporter import config, r2

    if not all(
        (
            config.R2_ENDPOINT,
            config.R2_ACCESS_KEY_ID,
            config.R2_SECRET_ACCESS_KEY,
            config.R2_BUCKET,
        )
    ):
        raise RuntimeError("R2 configuration missing")
    records = _development_records(
        args.development_manifest, args.expected_development_sha256
    )
    clips_dir = output / "source-clips"
    rows_dir = output / "download-rows"
    clips_dir.mkdir(mode=0o700, exist_ok=True)
    rows_dir.mkdir(mode=0o700, exist_ok=True)
    client = r2.get_r2_client()
    completed: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    for ordinal, source in enumerate(records, start=1):
        token = f"S{ordinal:06d}"
        destination = clips_dir / f"{token}.mp4"
        row_path = rows_dir / f"{token}.private.json"
        if row_path.exists():
            row = _read_json(row_path)
            if (
                not destination.is_file()
                or destination.stat().st_size != row.get("byte_size")
                or _sha256_file(destination) != row.get("source_video_sha256")
            ):
                raise ValueError("resumed download integrity mismatch")
            completed.append(row)
            continue
        temporary = clips_dir / f".{token}.part"
        if temporary.exists():
            temporary.unlink()
        try:
            head = client.head_object(Bucket=config.R2_BUCKET, Key=str(source["r2_key"]))
            expected_size = int(head.get("ContentLength") or 0)
            if expected_size <= 0:
                raise ValueError("empty R2 object")
            client.download_file(config.R2_BUCKET, str(source["r2_key"]), str(temporary))
            if temporary.stat().st_size != expected_size:
                raise ValueError("R2 download size mismatch")
            os.replace(temporary, destination)
            row = {
                "schema": "yolo26n-v261-downloaded-source-v1",
                "token": token,
                "clip_ref": source["clip_ref"],
                "camera_ref": source["camera_ref"],
                "camera_night": source["camera_night"],
                "started_at": source["started_at"],
                "duration_sec": source["duration_sec"],
                "cohort": source["cohort"],
                "reasons": source["reasons"],
                "source_video_sha256": _sha256_file(destination),
                "byte_size": expected_size,
                "local_name": destination.name,
            }
            _write_json_new(row_path, row)
            completed.append(row)
        except Exception as error:
            if temporary.exists():
                temporary.unlink()
            failures.append(
                {
                    "token": token,
                    "error_type": type(error).__name__,
                }
            )
        if ordinal % 50 == 0:
            print(
                json.dumps(
                    {
                        "progress": ordinal,
                        "total": len(records),
                        "completed": len(completed),
                        "failed": len(failures),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

    status = "DOWNLOAD_COMPLETE" if not failures and len(completed) == len(records) else "DOWNLOAD_SHORTAGE"
    payload = {
        "schema": "yolo26n-v261-download-completion-v1",
        "status": status,
        "requested_count": len(records),
        "downloaded_count": len(completed),
        "failed_count": len(failures),
        "source_bytes": sum(int(row["byte_size"]) for row in completed),
        "records": completed,
        "failures": failures,
        "r2_head_count": len(completed) + len(failures),
        "r2_get_count": len(completed),
        "r2_write_count": 0,
        "db_write_count": 0,
    }
    _write_json_new(completion_path, payload)
    return payload


def _load_download_records(path: Path) -> tuple[list[dict[str, object]], int, int]:
    payload = _read_json(path)
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("download completion records missing")
    requested = int(payload.get("requested_count") or 0)
    failed = int(payload.get("failed_count") or 0)
    if requested <= 0 or len(records) + failed != requested:
        raise ValueError("download completion count mismatch")
    if failed / requested > 0.05:
        raise ValueError("download exclusion ratio exceeds five percent")
    return [dict(row) for row in records if isinstance(row, Mapping)], requested, failed


def _load_holdout_refs(path: Path) -> set[str]:
    payload = _read_json(path)
    if payload.get("status") != "SEALED_SOURCE_ONLY":
        raise ValueError("future holdout is not sealed")
    records = payload.get("records")
    if not isinstance(records, list) or len(records) != 300:
        raise ValueError("future holdout count mismatch")
    return {
        str(row.get("clip_ref"))
        for row in records
        if isinstance(row, Mapping) and row.get("clip_ref")
    }


def _strip_jpeg_bytes(row: Mapping[str, object], *, candidate_name: str) -> dict[str, object]:
    return {
        **{key: value for key, value in row.items() if key != "jpeg_bytes"},
        "candidate_name": candidate_name,
    }


def _write_bbox_rules(path: Path) -> None:
    rules = (
        "# YOLO26n v2.6.1 blind bbox rules\n\n"
        "- 모델 박스나 GME 점수 없이 화면의 사실만 판정해.\n"
        "- 실제 게코가 있으면 보이는 머리와 몸통 중심으로 tight bbox를 그려.\n"
        "- 여러 실제 게코가 있으면 각각 따로 그려.\n"
        "- 유리 반사상은 실제 개체로 라벨하지 마.\n"
        "- 식물, 코르크, 선반, 장식물은 게코 bbox에 포함하지 마.\n"
        "- 가려진 부분이나 화면 밖 꼬리를 추정해서 늘리지 마.\n"
        "- 실제 게코가 없으면 빈 frame으로 제출해.\n"
        "- 확신할 수 없거나 영상이 깨졌으면 uncertain/media_error로 분리해.\n"
    ).encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, rules)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def extract_queue(args: argparse.Namespace) -> dict[str, object]:
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError("queue output already exists")
    download_records, requested_count, download_failure_count = _load_download_records(
        args.download_completion
    )
    holdout_refs = _load_holdout_refs(args.future_holdout_manifest)
    if any(str(row.get("clip_ref")) in holdout_refs for row in download_records):
        raise ValueError("future holdout source reached materialization")
    protected_exact = load_protected_exact_shas(args.protected_dataset_manifest)
    protected_perceptual = load_protected_fingerprints(
        args.protected_dataset_manifest, args.protected_selection_manifest
    )

    output.mkdir(mode=0o700, parents=True)
    candidate_dir = output / "candidate-images"
    blind_dir = output / "blind-images"
    candidate_dir.mkdir(mode=0o700)
    blind_dir.mkdir(mode=0o700)
    candidates: list[dict[str, object]] = []
    decode_failures: list[dict[str, object]] = []
    source_rows: list[dict[str, object]] = []
    clips_dir = args.download_completion.parent / "source-clips"
    for ordinal, source in enumerate(download_records, start=1):
        local_path = clips_dir / str(source["local_name"])
        if (
            not local_path.is_file()
            or local_path.stat().st_size != source.get("byte_size")
            or _sha256_file(local_path) != source.get("source_video_sha256")
        ):
            raise ValueError("downloaded source changed before extraction")
        uniform_limit, scene_limit = mining_limits(
            str(reason) for reason in source.get("reasons", [])
        )
        try:
            mined = mine_owner_video(
                _snapshot_source(local_path),
                uniform_limit=uniform_limit,
                scene_limit=scene_limit,
                strict_reported_frame_count=False,
            )
        except Exception as error:
            decode_failures.append(
                {"token": source["token"], "error_type": type(error).__name__}
            )
            continue
        source_rows.append(
            {
                "token": source["token"],
                "source_video_sha256": source["source_video_sha256"],
                "decoded_frame_count": mined["decoded_frame_count"],
                "reported_frame_count": mined["reported_frame_count"],
                "frame_count_mismatch": mined["frame_count_mismatch"],
                "fps": mined["fps"],
                "selected_before_dedup": len(mined["records"]),
            }
        )
        for frame in mined["records"]:
            candidate_name = f"C{len(candidates) + 1:07d}.jpg"
            payload = frame.get("jpeg_bytes")
            if not isinstance(payload, bytes):
                raise ValueError("mined JPEG payload missing")
            candidate_path = candidate_dir / candidate_name
            descriptor = os.open(
                candidate_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            try:
                os.write(descriptor, payload)
            finally:
                os.close(descriptor)
            candidates.append(
                {
                    **_strip_jpeg_bytes(frame, candidate_name=candidate_name),
                    "clip_ref": source["clip_ref"],
                    "camera_ref": source["camera_ref"],
                    "camera_night": source["camera_night"],
                    "cohort": source["cohort"],
                    "source_reasons": source["reasons"],
                }
            )
        if ordinal % 25 == 0:
            print(
                json.dumps(
                    {
                        "progress": ordinal,
                        "total": len(download_records),
                        "candidate_frames": len(candidates),
                        "decode_failures": len(decode_failures),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

    total_failures = download_failure_count + len(decode_failures)
    if total_failures / requested_count > 0.05:
        raise ValueError("combined media exclusion ratio exceeds five percent")
    exact_prefiltered: list[dict[str, object]] = []
    protected_exact_rejects = 0
    for row in candidates:
        if row["image_sha256"] in protected_exact:
            protected_exact_rejects += 1
        else:
            exact_prefiltered.append(row)
    perceptual_exception_limits = {
        str(row["clip_ref"]): (
            20 if "owner_confirmed" in row.get("source_reasons", []) else 2
        )
        for row in exact_prefiltered
    }
    dedup = deduplicate_candidate_frames(
        exact_prefiltered,
        protected_perceptual,
        perceptual_exception_limits=perceptual_exception_limits,
    )
    accepted = list(dedup["records"])
    if not accepted:
        raise ValueError("selected frame shortage")

    review_records: list[dict[str, object]] = []
    zip_part_size = args.zip_part_size
    zip_paths: list[Path] = []
    archives: dict[int, zipfile.ZipFile] = {}
    try:
        for ordinal, row in enumerate(accepted, start=1):
            blind_name = f"V{ordinal:07d}.jpg"
            source_path = candidate_dir / str(row["candidate_name"])
            destination = blind_dir / blind_name
            shutil.copyfile(source_path, destination)
            destination.chmod(0o600)
            if _sha256_file(destination) != row["image_sha256"]:
                raise ValueError("blind image SHA mismatch")
            part = (ordinal - 1) // zip_part_size + 1
            if part not in archives:
                zip_path = output / f"cvat-upload-part-{part:02d}.zip"
                zip_paths.append(zip_path)
                archives[part] = zipfile.ZipFile(
                    zip_path, mode="x", compression=zipfile.ZIP_STORED
                )
            archives[part].write(destination, arcname=blind_name)
            review_records.append(
                {
                    **row,
                    "blind_name": blind_name,
                    "zip_part": part,
                }
            )
    finally:
        for archive in archives.values():
            archive.close()

    for zip_path in zip_paths:
        zip_path.chmod(0o600)
        with zipfile.ZipFile(zip_path) as archive:
            if archive.testzip() is not None:
                raise ValueError("CVAT ZIP integrity failure")
            if any("/" in name or not name.startswith("V") for name in archive.namelist()):
                raise ValueError("CVAT ZIP blind filename failure")

    _write_bbox_rules(output / "BBOX-RULES.md")
    private_manifest = {
        "schema": "yolo26n-v261-blind-review-index-v1",
        "records": review_records,
        "source_rows": source_rows,
        "download_failures": download_failure_count,
        "decode_failures": decode_failures,
    }
    _write_json_new(output / "review-index.private.json", private_manifest)
    dedup_counts = dict(dedup["counts"])
    dedup_counts["protected_exact"] = (
        int(dedup_counts["protected_exact"]) + protected_exact_rejects
    )
    summary = {
        "schema": "yolo26n-v261-blind-queue-completion-v1",
        "status": "BLIND_QUEUE_READY",
        "requested_source_count": requested_count,
        "downloaded_source_count": len(download_records),
        "download_failure_count": download_failure_count,
        "decoded_source_count": len(source_rows),
        "decode_failure_count": len(decode_failures),
        "candidate_frame_count": len(candidates),
        "accepted_frame_count": len(review_records),
        "zip_part_count": len(zip_paths),
        "dedup_counts": dedup_counts,
        "future_holdout_access_count": 0,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_change_count": 0,
        "model_change_count": 0,
        "review_index_sha256": _canonical_sha256(private_manifest),
        "zip_sha256": {
            path.name: _sha256_file(path) for path in zip_paths
        },
    }
    _write_json_new(output / "completion.private.json", summary)
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    download = subparsers.add_parser("download")
    download.add_argument("--development-manifest", required=True, type=Path)
    download.add_argument("--expected-development-sha256", required=True)
    download.add_argument("--output", required=True, type=Path)
    download.add_argument("--env-file", required=True, type=Path)
    download.add_argument("--reporter-repo", required=True, type=Path)
    extract = subparsers.add_parser("extract")
    extract.add_argument("--download-completion", required=True, type=Path)
    extract.add_argument("--future-holdout-manifest", required=True, type=Path)
    extract.add_argument("--protected-dataset-manifest", required=True, type=Path)
    extract.add_argument("--protected-selection-manifest", required=True, type=Path)
    extract.add_argument("--output", required=True, type=Path)
    extract.add_argument("--zip-part-size", type=int, default=2_000)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.command == "download":
        result = download_sources(args)
    elif args.command == "extract":
        result = extract_queue(args)
    else:  # pragma: no cover
        raise AssertionError("unreachable")
    print(
        json.dumps(
            {key: value for key, value in result.items() if key not in {"records", "failures"}},
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if result["status"] in {"DOWNLOAD_COMPLETE", "BLIND_QUEUE_READY"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
