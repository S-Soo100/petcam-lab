"""Owner 휴대폰 촬영물을 예측 없는 CVAT 외부 진단 큐로 만든다."""

from __future__ import annotations

import argparse
import ctypes
import csv
import errno
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image


SCHEMA = "yolo26n-owner-media-diagnostic-v1"
SEED = "owner-media-diagnostic-v1"
INSTRUCTION = "게코가 보이면 각 개체의 보이는 몸 영역에 bbox"
PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic"}
RELEASE_TOTAL = 240
RELEASE_DIAGNOSTIC = 60


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rank(value: str) -> str:
    return hashlib.sha256(f"{SEED}:{value}".encode()).hexdigest()


def _validate_sha(value: object) -> str:
    text = str(value)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ValueError("source sha must be lowercase sha256")
    return text


def _diagnostic_days(counts: dict[str, int], target: int) -> set[str]:
    reachable: dict[int, tuple[str, ...]] = {0: ()}
    for day in sorted(counts, key=_rank):
        for subtotal, chosen in sorted(reachable.items(), reverse=True):
            candidate = subtotal + counts[day]
            if candidate <= target and candidate not in reachable:
                reachable[candidate] = (*chosen, day)
    if target not in reachable:
        raise ValueError("capture-day partition cannot satisfy diagnostic count")
    return set(reachable[target])


def select_owner_media(
    rows: Iterable[dict],
    *,
    total: int,
    diagnostic: int,
    per_day_cap: int = 3,
) -> list[dict]:
    """날짜를 쪼개지 않고 exact diagnostic/training 표본을 결정론적으로 고른다."""
    if not (0 < diagnostic < total) or per_day_cap <= 0:
        raise ValueError("invalid selection quota")
    source_rows = [dict(row) for row in rows]
    seen_sha: set[str] = set()
    by_day: dict[str, list[dict]] = defaultdict(list)
    for row in source_rows:
        source_sha = _validate_sha(row.get("source_sha256"))
        if source_sha in seen_sha:
            raise ValueError("duplicate source sha")
        seen_sha.add(source_sha)
        day = str(row.get("capture_day", "")).strip()
        name = str(row.get("source_name", "")).strip()
        if not day or not name or Path(name).name != name:
            raise ValueError("source name and capture day are required")
        by_day[day].append(row)
    if sum(min(len(items), per_day_cap) for items in by_day.values()) < total:
        raise ValueError("insufficient capture-day capacity")

    for items in by_day.values():
        items.sort(key=lambda row: (_rank(row["source_sha256"]), row["source_name"]))
    selected: list[dict] = []
    day_order = sorted(by_day, key=_rank)
    for position in range(per_day_cap):
        for day in day_order:
            if len(selected) == total:
                break
            if position < len(by_day[day]):
                selected.append(dict(by_day[day][position]))
        if len(selected) == total:
            break

    counts: dict[str, int] = defaultdict(int)
    for row in selected:
        counts[row["capture_day"]] += 1
    diagnostic_days = _diagnostic_days(dict(counts), diagnostic)
    for row in selected:
        row["partition"] = (
            "external_diagnostic"
            if row["capture_day"] in diagnostic_days
            else "training_candidate"
        )
    selected.sort(key=lambda row: (_rank(row["source_sha256"]), row["source_name"]))
    for index, row in enumerate(selected, start=1):
        row["sequence"] = f"O{index:04d}"
    return selected


def _write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict]) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _convert_stripped_jpeg(source: Path, target: Path) -> tuple[int, int]:
    subprocess.run(
        [
            "magick",
            str(source),
            "-auto-orient",
            "-resize",
            "1920x1920>",
            "-strip",
            "-quality",
            "92",
            str(target),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    with Image.open(target) as image:
        image.load()
        if image.format != "JPEG" or max(image.size) > 1920 or image.getexif():
            raise ValueError("derived image contract failed")
        return image.size


def _rename_exclusive(source: Path, destination: Path) -> None:
    """완성된 디렉터리를 기존 목적지 교체 없이 발행한다."""
    libc = ctypes.CDLL(None, use_errno=True)
    renamex = getattr(libc, "renamex_np", None)
    if renamex is None:
        if destination.exists():
            raise FileExistsError(destination)
        os.rename(source, destination)
        return
    renamex.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    renamex.restype = ctypes.c_int
    if renamex(os.fsencode(source), os.fsencode(destination), 0x00000004) != 0:
        error = ctypes.get_errno()
        if error in {errno.EEXIST, errno.ENOTEMPTY}:
            raise FileExistsError(destination)
        raise OSError(error, os.strerror(error), destination)


def materialize_review_queue(
    rows: Iterable[dict], *, source_dir: Path, output_dir: Path
) -> dict:
    """모든 검증 성공 뒤에만 새 private review artifact를 원자적으로 발행한다."""
    source_dir = source_dir.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(output_dir)
    prepared: list[dict] = []
    source_shas: set[str] = set()
    for expected, raw in enumerate(rows, start=1):
        row = dict(raw)
        sequence = str(row.get("sequence", ""))
        if sequence != f"O{expected:04d}":
            raise ValueError("sequences must be contiguous and ordered")
        name = str(row.get("source_name", ""))
        if Path(name).name != name:
            raise ValueError("source name must be a basename")
        source = source_dir / name
        if not source.is_file() or source.suffix.lower() not in PHOTO_SUFFIXES:
            raise ValueError("source photo is missing or unsupported")
        source_sha = _sha256(source)
        declared = str(row.get("source_sha256", ""))
        if declared and source_sha != declared:
            raise ValueError("source sha changed")
        if source_sha in source_shas:
            raise ValueError("duplicate source sha")
        source_shas.add(source_sha)
        row["source_sha256"] = source_sha
        row["source_path"] = str(source)
        prepared.append(row)

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        frames = temp / "review-frames"
        frames.mkdir()
        derived_shas: set[str] = set()
        manifest_items = []
        review_rows = []
        ambiguous_rows = []
        for row in prepared:
            filename = f"{row['sequence']}.jpg"
            target = frames / filename
            width, height = _convert_stripped_jpeg(Path(row["source_path"]), target)
            derived_sha = _sha256(target)
            if derived_sha in derived_shas:
                raise ValueError("duplicate derived sha")
            derived_shas.add(derived_sha)
            manifest_items.append(
                {
                    "sequence": row["sequence"],
                    "source_name": row["source_name"],
                    "source_sha256": row["source_sha256"],
                    "capture_day": row["capture_day"],
                    "camera_model": row.get("camera_model", "unknown"),
                    "partition": row["partition"],
                    "derived_filename": filename,
                    "derived_sha256": derived_sha,
                    "width": width,
                    "height": height,
                }
            )
            review_rows.append(
                {
                    "sequence": row["sequence"],
                    "filename": filename,
                    "instruction": INSTRUCTION,
                }
            )
            ambiguous_rows.append({"sequence": row["sequence"], "ambiguous": "false"})

        _write_csv(
            temp / "review-index.csv",
            ["sequence", "filename", "instruction"],
            review_rows,
        )
        _write_csv(
            temp / "ambiguous.csv", ["sequence", "ambiguous"], ambiguous_rows
        )
        zip_path = temp / "cvat-upload.zip"
        with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in manifest_items:
                source = frames / item["derived_filename"]
                info = zipfile.ZipInfo(item["derived_filename"], (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                archive.writestr(info, source.read_bytes())
        with zipfile.ZipFile(zip_path) as archive:
            if archive.namelist() != [item["derived_filename"] for item in manifest_items]:
                raise ValueError("zip ordering mismatch")
            if archive.testzip() is not None:
                raise ValueError("zip integrity failure")

        partition_counts = {
            partition: sum(item["partition"] == partition for item in manifest_items)
            for partition in ("external_diagnostic", "training_candidate")
        }
        day_counts: dict[str, int] = defaultdict(int)
        for item in manifest_items:
            day_counts[item["capture_day"]] += 1
        manifest = {
            "schema": SCHEMA,
            "status": "OWNER_MEDIA_HUMAN_REVIEW_REQUIRED",
            "prediction_exposed": False,
            "image_count": len(manifest_items),
            "partition_counts": partition_counts,
            "capture_day_count": len(day_counts),
            "max_images_per_capture_day": max(day_counts.values(), default=0),
            "review_index_sha256": _sha256(temp / "review-index.csv"),
            "ambiguous_csv_sha256": _sha256(temp / "ambiguous.csv"),
            "zip_sha256": _sha256(zip_path),
            "db_write_count": 0,
            "r2_write_count": 0,
            "service_write_count": 0,
            "items": manifest_items,
        }
        manifest_path = temp / "manifest.private.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.chmod(manifest_path, 0o600)
        _rename_exclusive(temp, output_dir)
        return manifest
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def inventory_source(source_dir: Path) -> list[dict]:
    rows = []
    for path in sorted(source_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in PHOTO_SUFFIXES:
            continue
        raw = subprocess.check_output(
            ["mdls", "-plist", "-", str(path)], stderr=subprocess.DEVNULL
        )
        metadata = plistlib.loads(raw)
        created = str(metadata.get("kMDItemContentCreationDate", ""))
        day = created[:10]
        if len(day) != 10:
            raise ValueError("capture day is missing")
        rows.append(
            {
                "source_name": path.name,
                "source_sha256": _sha256(path),
                "capture_day": day,
                "camera_model": str(metadata.get("kMDItemAcquisitionModel") or "unknown"),
            }
        )
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--total", type=int, default=240)
    parser.add_argument("--diagnostic", type=int, default=60)
    args = parser.parse_args(argv)
    if args.total != RELEASE_TOTAL or args.diagnostic != RELEASE_DIAGNOSTIC:
        raise ValueError("release requires exactly 240 total and 60 diagnostic")
    rows = inventory_source(args.source_dir)
    selected = select_owner_media(
        rows, total=args.total, diagnostic=args.diagnostic, per_day_cap=3
    )
    manifest = materialize_review_queue(
        selected, source_dir=args.source_dir, output_dir=args.output_dir
    )
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "image_count": manifest["image_count"],
                "capture_day_count": manifest["capture_day_count"],
                "max_images_per_capture_day": manifest[
                    "max_images_per_capture_day"
                ],
                "prediction_exposed": manifest["prediction_exposed"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
