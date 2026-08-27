"""Extract the frozen v2.6 selection into anonymous, prediction-free blind ZIPs."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any
import zipfile

import cv2
from PIL import Image

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def historical_dhash_int(payload: bytes) -> int:
    """Match the frozen Pillow RGB→luma→BOX 9x8 historical fingerprint."""

    from io import BytesIO

    with Image.open(BytesIO(payload)) as image:
        resized = image.convert("RGB").convert("L").resize((9, 8), Image.Resampling.BOX)
        pixels = list(resized.get_flattened_data())
    value = 0
    for row in range(8):
        offset = row * 9
        for column in range(8):
            value = (value << 1) | int(pixels[offset + column + 1] > pixels[offset + column])
    return value


def extract_selected_jpegs(
    video_path: Path,
    destination: Path,
    *,
    selections: list[dict[str, object]],
    fallback_selections: list[dict[str, object]] | None = None,
    selection_sha256: str,
    expected_size_bytes: int,
    protected_dhash64: set[int],
) -> dict[str, object]:
    if destination.exists():
        raise FileExistsError(destination)
    if not selections:
        raise ValueError("clip selection is empty")
    if _SHA256.fullmatch(selection_sha256) is None:
        raise ValueError("selection SHA is invalid")
    if video_path.stat().st_size != expected_size_bytes:
        raise ValueError("downloaded source size drift")
    if any(type(value) is not int or not 0 <= value < 2**64 for value in protected_dhash64):
        raise ValueError("protected dHash is invalid")

    fallback_selections = fallback_selections or []
    by_frame_index: dict[int, dict[str, object]] = {}
    for selection in [*selections, *fallback_selections]:
        frame_index = selection.get("frame_index")
        image_sha = selection.get("image_sha256")
        if type(frame_index) is not int or frame_index < 0:
            raise ValueError("selected frame index is invalid")
        if not isinstance(image_sha, str) or _SHA256.fullmatch(image_sha) is None:
            raise ValueError("selected image SHA is invalid")
        if frame_index in by_frame_index:
            raise ValueError("selected frame index is duplicated")
        by_frame_index[frame_index] = selection

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bundle-staging-", dir=destination.parent) as raw:
        staging = Path(raw)
        images = staging / "images"
        images.mkdir()
        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise ValueError("source video cannot be opened")
        records: list[dict[str, object]] = []
        found: set[int] = set()
        payload_by_frame: dict[int, bytes] = {}
        decoded = 0
        max_index = max(by_frame_index)
        try:
            while decoded <= max_index:
                ok, frame = capture.read()
                if not ok:
                    break
                frame_index = decoded
                decoded += 1
                target = by_frame_index.get(frame_index)
                if target is None:
                    continue
                encoded_ok, encoded = cv2.imencode(
                    ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 95]
                )
                if not encoded_ok:
                    raise ValueError("selected JPEG encoding failed")
                payload_by_frame[frame_index] = encoded.tobytes()
                found.add(frame_index)
        finally:
            capture.release()
        if found != set(by_frame_index):
            raise ValueError("selected frame decode shortage")

        def materialize_status(candidate: dict[str, object]) -> tuple[str, bytes, int]:
            payload = payload_by_frame[int(candidate["frame_index"])]
            image_sha = hashlib.sha256(payload).hexdigest()
            if image_sha != candidate["image_sha256"]:
                return "sha-mismatch", payload, 0
            dhash = historical_dhash_int(payload)
            if any((dhash ^ protected).bit_count() <= 2 for protected in protected_dhash64):
                return "protected", payload, dhash
            return "ok", payload, dhash

        reserves = sorted(
            fallback_selections,
            key=lambda row: hashlib.sha256(
                f"{selection_sha256}:reserve:{row['image_sha256']}".encode()
            ).hexdigest(),
        )
        used_frames: set[int] = set()
        replacement_count = 0
        for selection in selections:
            status, payload, dhash = materialize_status(selection)
            chosen = selection
            materialization_reason = "selected"
            if status != "ok":
                replacement = next(
                    (
                        candidate
                        for candidate in reserves
                        if int(candidate["frame_index"]) not in used_frames
                        and materialize_status(candidate)[0] == "ok"
                    ),
                    None,
                )
                if replacement is None:
                    if status == "protected":
                        raise ValueError("protected historical near-duplicate")
                    raise ValueError("selected image SHA reproduction failed")
                chosen = replacement
                status, payload, dhash = materialize_status(chosen)
                assert status == "ok"
                replacement_count += 1
                materialization_reason = "decode-replacement"
            used_frames.add(int(chosen["frame_index"]))
            image_sha = hashlib.sha256(payload).hexdigest()
            blind_id = hashlib.sha256(
                f"{selection_sha256}:primary:{image_sha}".encode()
            ).hexdigest()[:24]
            filename = f"frame_{blind_id}.jpg"
            with (images / filename).open("xb") as handle:
                handle.write(payload)
            reasons = list(selection.get("reasons", []))
            if materialization_reason == "decode-replacement":
                reasons.append("decode-replacement")
            records.append(
                {
                    "blind_filename": filename,
                    "clip_ref": chosen.get("clip_ref"),
                    "private_ref": chosen.get("private_ref"),
                    "timestamp_ms": chosen.get("timestamp_ms"),
                    "frame_index": chosen.get("frame_index"),
                    "image_sha256": image_sha,
                    "selection_image_sha256": selection.get("image_sha256"),
                    "historical_dhash64": f"{dhash:016x}",
                    "stratum": selection.get("stratum"),
                    "reasons": reasons,
                    "double_review": bool(selection.get("double_review")),
                    "materialization_reason": materialization_reason,
                }
            )
        records.sort(key=lambda row: str(row["blind_filename"]))
        completion: dict[str, object] = {
            "status": "BLIND_CLIP_COMPLETE",
            "selection_sha256": selection_sha256,
            "source_size_bytes": expected_size_bytes,
            "image_count": len(records),
            "replacement_count": replacement_count,
            "records": records,
        }
        with (staging / "completion.private.json").open("x", encoding="utf-8") as handle:
            json.dump(completion, handle, sort_keys=True, indent=2)
            handle.write("\n")
        os.rename(staging, destination)
        return completion


def _validate_completed_clip(
    directory: Path, *, selection_sha256: str, expected_count: int
) -> dict[str, object]:
    completion_path = directory / "completion.private.json"
    images_path = directory / "images"
    if not completion_path.is_file() or not images_path.is_dir():
        raise ValueError("blind clip artifact is partial")
    completion = json.loads(completion_path.read_text())
    if completion.get("status") != "BLIND_CLIP_COMPLETE":
        raise ValueError("blind clip status is invalid")
    if completion.get("selection_sha256") != selection_sha256:
        raise ValueError("blind clip selection drift")
    if completion.get("image_count") != expected_count:
        raise ValueError("blind clip image count drift")
    actual_names = {path.name for path in images_path.glob("*.jpg")}
    expected_names = {str(row["blind_filename"]) for row in completion["records"]}
    if actual_names != expected_names:
        raise ValueError("blind clip file set drift")
    for record in completion["records"]:
        path = images_path / str(record["blind_filename"])
        if _sha256_file(path) != record["image_sha256"]:
            raise ValueError("blind clip image SHA drift")
    return completion


def _load_r2(env_file: Path) -> tuple[Any, str]:
    import boto3
    from botocore.config import Config
    from dotenv import load_dotenv

    load_dotenv(env_file, override=False)
    required = ("R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
    if any(not os.environ.get(name) for name in required):
        raise RuntimeError("required R2 environment is incomplete")
    return (
        boto3.client(
            "s3",
            endpoint_url=os.environ["R2_ENDPOINT"],
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            region_name="auto",
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        ),
        os.environ["R2_BUCKET"],
    )


def _write_archives(
    output_root: Path,
    *,
    all_records: list[dict[str, object]],
    bundle_root: Path,
    selection_sha256: str,
) -> dict[str, object]:
    primary_zip = output_root / "blind-primary.zip"
    gold_zip = output_root / "blind-double-review.zip"
    index_path = output_root / "review-index.private.json"
    final_path = output_root / "bundle-completion.private.json"
    for path in (primary_zip, gold_zip, index_path, final_path):
        if path.exists():
            raise FileExistsError(path)

    readme = (
        "YOLO26n v2.6 blind bbox review\n\n"
        "1. 모델 박스나 점수 없이 실제 화면만 보고 판단해.\n"
        "2. 게코가 보이면 보이는 각 게코 몸 전체를 가능한 한 타이트한 bbox로 그려.\n"
        "3. 꼬리나 발이 가려졌다면 보이는 몸을 기준으로 하고 추측해 확장하지 마.\n"
        "4. 게코가 없으면 빈 라벨로 확정해. 불확실하거나 영상이 깨졌으면 학습 제외로 표시해.\n"
    )
    private_index: list[dict[str, object]] = []
    with zipfile.ZipFile(primary_zip, "x", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("README.txt", readme)
        for record in sorted(all_records, key=lambda row: str(row["blind_filename"])):
            image = (
                bundle_root
                / "clips"
                / str(record["private_ref"])
                / "images"
                / str(record["blind_filename"])
            )
            archive.write(image, arcname=f"images/{record['blind_filename']}")
            private_index.append({"review_round": "primary", **record})

    with zipfile.ZipFile(gold_zip, "x", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("README.txt", readme)
        for record in sorted(
            (row for row in all_records if row["double_review"]),
            key=lambda row: str(row["image_sha256"]),
        ):
            second_id = hashlib.sha256(
                f"{selection_sha256}:gold:{record['image_sha256']}".encode()
            ).hexdigest()[:24]
            second_name = f"frame_{second_id}.jpg"
            image = (
                bundle_root
                / "clips"
                / str(record["private_ref"])
                / "images"
                / str(record["blind_filename"])
            )
            archive.write(image, arcname=f"images/{second_name}")
            private_index.append(
                {"review_round": "double-review", "review_filename": second_name, **record}
            )

    index = {
        "schema": "yolo26n-v26-blind-review-index-v1",
        "selection_sha256": selection_sha256,
        "primary_count": len(all_records),
        "double_review_count": sum(bool(row["double_review"]) for row in all_records),
        "records": private_index,
    }
    with index_path.open("x", encoding="utf-8") as handle:
        json.dump(index, handle, sort_keys=True, indent=2)
        handle.write("\n")
    final = {
        "status": "V26_BLIND_BBOX_QUEUE_READY",
        "selection_sha256": selection_sha256,
        "primary_count": index["primary_count"],
        "double_review_count": index["double_review_count"],
        "primary_zip_sha256": _sha256_file(primary_zip),
        "primary_zip_bytes": primary_zip.stat().st_size,
        "gold_zip_sha256": _sha256_file(gold_zip),
        "gold_zip_bytes": gold_zip.stat().st_size,
        "review_index_sha256": _sha256_file(index_path),
    }
    with final_path.open("x", encoding="utf-8") as handle:
        json.dump(final, handle, sort_keys=True, indent=2)
        handle.write("\n")
    return final


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--selection-manifest", type=Path, required=True)
    parser.add_argument("--dense-root", type=Path, required=True)
    parser.add_argument("--protected-fingerprints", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    source_manifest = json.loads(args.source_manifest.read_text())
    selection_manifest = json.loads(args.selection_manifest.read_text())
    selection_sha256 = str(selection_manifest["selection_sha256"])
    protected = json.loads(args.protected_fingerprints.read_text())
    protected_dhash = {int(str(row["dhash64"]), 16) for row in protected["records"]}
    source_by_clip = {
        str(row["clip_id"]): row
        for row in source_manifest["sources"]
        if row["object_status"] == "available"
    }
    selected_by_clip: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in selection_manifest["records"]:
        selected_by_clip[str(record["clip_ref"])].append(dict(record))
    if set(selected_by_clip) != set(source_by_clip):
        raise ValueError("selection must preserve every available clip")

    dense_final = json.loads((args.dense_root / "completion.private.json").read_text())
    dense_ref_by_clip = {
        str(row["clip_ref"]): str(row["private_ref"]) for row in dense_final["clips"]
    }
    for clip_ref, records in selected_by_clip.items():
        ledger = args.dense_root / "clips" / dense_ref_by_clip[clip_ref] / "ledger.jsonl"
        dense_rows = [json.loads(line) for line in ledger.open()]
        frame_by_sha = {row["image_sha256"]: row for row in dense_rows}
        for record in records:
            dense = frame_by_sha.get(record["image_sha256"])
            if dense is None:
                raise ValueError("selection image is missing from dense lineage")
            record["frame_index"] = int(dense["frame_index"])
        selected_sha = {str(record["image_sha256"]) for record in records}
        reserves = [
            {
                "clip_ref": clip_ref,
                "private_ref": records[0]["private_ref"],
                "timestamp_ms": int(row["timestamp_ms"]),
                "frame_index": int(row["frame_index"]),
                "image_sha256": str(row["image_sha256"]),
                "reasons": ["decode-reserve"],
            }
            for row in dense_rows
            if row["image_sha256"] not in selected_sha
            and not any(
                (int(row["dhash64"]) ^ protected_value).bit_count() <= 4
                for protected_value in protected_dhash
            )
        ]
        reserves.sort(
            key=lambda row: hashlib.sha256(
                f"{selection_sha256}:reserve-pool:{row['image_sha256']}".encode()
            ).hexdigest()
        )
        for record in records:
            record["fallback_selections"] = reserves[:12]

    bundle_root = args.output_root / "frame-bundle"
    clips_root = bundle_root / "clips"
    clips_root.mkdir(parents=True, exist_ok=True)
    r2, bucket = _load_r2(args.env_file)
    all_records: list[dict[str, object]] = []
    reused = 0
    for index, clip_ref in enumerate(sorted(selected_by_clip), start=1):
        records = selected_by_clip[clip_ref]
        private_ref = str(records[0]["private_ref"])
        destination = clips_root / private_ref
        if destination.exists():
            completion = _validate_completed_clip(
                destination,
                selection_sha256=selection_sha256,
                expected_count=len(records),
            )
            reused += 1
        else:
            source = source_by_clip[clip_ref]
            with tempfile.TemporaryDirectory(prefix="yolo-v26-bundle-source-") as raw:
                video = Path(raw) / "source.mp4"
                r2.download_file(bucket, str(source["r2_key"]), str(video))
                completion = extract_selected_jpegs(
                    video,
                    destination,
                    selections=records,
                    fallback_selections=list(records[0]["fallback_selections"]),
                    selection_sha256=selection_sha256,
                    expected_size_bytes=int(source["size_bytes"]),
                    protected_dhash64=protected_dhash,
                )
        all_records.extend(completion["records"])
        if index % 10 == 0 or index == len(selected_by_clip):
            print(
                json.dumps(
                    {
                        "status": "BLIND_BUNDLE_PROGRESS",
                        "completed_clips": index,
                        "expected_clips": len(selected_by_clip),
                        "reused": reused,
                        "images": len(all_records),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
    if len(all_records) != int(selection_manifest["aggregate"]["unique_image_count"]):
        raise ValueError("blind bundle image count drift")
    final = _write_archives(
        args.output_root,
        all_records=all_records,
        bundle_root=bundle_root,
        selection_sha256=selection_sha256,
    )
    print(json.dumps(final, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
