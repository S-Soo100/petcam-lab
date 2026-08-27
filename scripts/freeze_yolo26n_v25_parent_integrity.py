"""Freeze every v2.5 replay image and label byte into an approved integrity ledger."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
import hashlib
import json
import os
from pathlib import Path
import re


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PRODUCTION_SPLITS = {"train": 1659, "val": 153, "test": 151}


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_file(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"parent {label} path malformed")
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError(f"parent {label} path malformed")
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise ValueError(f"parent {label} path escaped or missing")
    return resolved


def _label_box_count(payload: bytes) -> int:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("parent label encoding malformed") from error
    count = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 5 or fields[0] != "0":
            raise ValueError("parent label row malformed")
        try:
            x, y, width, height = (float(value) for value in fields[1:])
        except ValueError as error:
            raise ValueError("parent label row malformed") from error
        if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < width <= 1 and 0 < height <= 1):
            raise ValueError("parent label row malformed")
        count += 1
    return count


def build_parent_integrity_manifest(
    dataset_root: Path,
    parent_manifest: Mapping[str, object],
    *,
    expected_split_counts: Mapping[str, int] | None = None,
) -> dict[str, object]:
    """Recalculate the full v2.5 replay byte ledger without trusting label bytes."""

    split_counts = dict(expected_split_counts or _PRODUCTION_SPLITS)
    records = parent_manifest.get("records")
    if (
        parent_manifest.get("schema") != "yolo26n-owner-dataset-v25"
        or parent_manifest.get("status") != "V25_DATASET_READY"
        or parent_manifest.get("split_counts") != split_counts
        or parent_manifest.get("image_count") != sum(split_counts.values())
        or not isinstance(records, list)
        or len(records) != sum(split_counts.values())
        or Counter(
            str(row.get("split")) for row in records if isinstance(row, Mapping)
        )
        != Counter(split_counts)
    ):
        raise ValueError("parent manifest contract mismatch")
    expected_val_test = parent_manifest.get("parent_val_test_sha256")
    if not isinstance(expected_val_test, str) or _SHA256.fullmatch(expected_val_test) is None:
        raise ValueError("parent val/test SHA malformed")

    frozen: list[dict[str, object]] = []
    sequences: set[str] = set()
    image_paths: set[Path] = set()
    label_paths: set[Path] = set()
    val_test = hashlib.sha256()
    for raw in records:
        if not isinstance(raw, Mapping):
            raise ValueError("parent record malformed")
        sequence = raw.get("sequence")
        split = raw.get("split")
        if (
            not isinstance(sequence, str)
            or not sequence
            or sequence in sequences
            or split not in split_counts
        ):
            raise ValueError("parent record identity malformed")
        image = _safe_file(dataset_root, raw.get("image_path"), "image")
        label = _safe_file(dataset_root, raw.get("label_path"), "label")
        if image in image_paths or label in label_paths:
            raise ValueError("parent record path duplicated")
        image_sha = _file_sha256(image)
        declared_image_sha = raw.get("image_sha256")
        if declared_image_sha != image_sha:
            raise ValueError("parent image bytes drift")
        label_payload = label.read_bytes()
        label_sha = hashlib.sha256(label_payload).hexdigest()
        box_count = _label_box_count(label_payload)
        if raw.get("box_count") != box_count:
            raise ValueError("parent label box count drift")
        if split in {"val", "test"}:
            val_test.update(image.read_bytes())
            val_test.update(label_payload)
        sequences.add(sequence)
        image_paths.add(image)
        label_paths.add(label)
        frozen.append(
            {
                "sequence": sequence,
                "split": split,
                "image_path": str(raw["image_path"]),
                "label_path": str(raw["label_path"]),
                "image_sha256": image_sha,
                "label_sha256": label_sha,
                "box_count": box_count,
            }
        )
    if val_test.hexdigest() != expected_val_test:
        raise ValueError("parent val/test bytes drift")
    result: dict[str, object] = {
        "schema": "yolo26n-v25-parent-integrity-v1",
        "status": "V25_PARENT_INTEGRITY_APPROVED",
        "parent_manifest_sha256": canonical_sha256(parent_manifest),
        "parent_val_test_sha256": expected_val_test,
        "image_count": len(frozen),
        "split_counts": split_counts,
        "records": frozen,
    }
    result["records_sha256"] = canonical_sha256(frozen)
    return result


def _write_once(path: Path, value: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(
            fd,
            (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        )
        os.fsync(fd)
    finally:
        os.close(fd)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--digest-only", action="store_true")
    parser.add_argument("--approved-records-sha256")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    parent = json.loads((args.dataset_root / "manifest.private.json").read_bytes())
    if not isinstance(parent, dict):
        raise ValueError("parent manifest root malformed")
    frozen = build_parent_integrity_manifest(args.dataset_root, parent)
    records_sha = str(frozen["records_sha256"])
    if args.digest_only:
        if args.output is not None or args.approved_records_sha256 is not None:
            raise ValueError("digest-only cannot write or self-approve")
        print(records_sha)
        return 0
    if (
        args.output is None
        or not isinstance(args.approved_records_sha256, str)
        or _SHA256.fullmatch(args.approved_records_sha256) is None
        or args.approved_records_sha256 != records_sha
    ):
        raise ValueError("independent parent records SHA approval mismatch")
    _write_once(args.output, frozen)
    print("V25_PARENT_INTEGRITY_APPROVED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
