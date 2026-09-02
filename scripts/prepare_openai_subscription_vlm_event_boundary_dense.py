"""기존 74경계의 원본 영상을 재사용해 A끝/B시작 6+6 입력을 만들어."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
from typing import Iterable, Mapping

import cv2

from scripts.run_local_vlm_event_boundary import (
    EXPECTED_CLIPS,
    EXPECTED_EXPERIMENT,
    EXPECTED_MANIFEST,
    EXPECTED_PAIRS,
    MappedPair,
    _load_db_pairs,
    _token,
    map_effective_pairs,
    require_private_file,
)
from scripts.seed_rba_boundary_review import load_env_file
from scripts.vlm_event_boundary_dense import (
    A_BOUNDARY_OFFSETS_SEC,
    B_BOUNDARY_OFFSETS_SEC,
    DENSE_PROMPT,
    DENSE_PROMPT_VERSION,
    DENSE_REPRESENTATION,
    build_boundary_sheets,
    extract_boundary_frames,
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def _write_new(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o600)


def _new_private_dir(path: Path) -> None:
    if path.exists():
        raise ValueError("output_exists")
    path.mkdir(mode=0o700)
    path.chmod(0o700)


def gap_seconds_by_digest(
    manifest_pairs: Iterable[Mapping[str, object]],
) -> dict[str, float]:
    result: dict[str, float] = {}
    for row in manifest_pairs:
        digest = row.get("pair_digest")
        gap = row.get("gap_sec")
        if (
            not isinstance(digest, str)
            or not digest
            or digest in result
            or isinstance(gap, bool)
            or not isinstance(gap, (int, float))
            or float(gap) < 0
        ):
            raise ValueError("gap_mapping")
        result[digest] = float(gap)
    return result


def load_cached_media(
    *,
    mapped: Iterable[MappedPair],
    salt: bytes,
    source_media_dir: Path,
    source_media_rows: Iterable[Mapping[str, object]],
) -> dict[str, Path]:
    source = {}
    for row in source_media_rows:
        token = row.get("clip")
        size = row.get("size")
        digest = row.get("sha256")
        if (
            not isinstance(token, str)
            or token in source
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size <= 0
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            raise ValueError("source_media_manifest")
        source[token] = (size, digest)

    clip_ids = {
        clip_id
        for row in mapped
        for clip_id in (row.left_clip_id, row.right_clip_id)
    }
    result: dict[str, Path] = {}
    for clip_id in clip_ids:
        token = _token(salt, "clip", clip_id)
        expected = source.get(token)
        path = source_media_dir / f"{token}.mp4"
        if expected is None or not path.is_file() or path.is_symlink():
            raise ValueError("source_media_missing")
        payload = path.read_bytes()
        if len(payload) != expected[0] or _sha256(payload) != expected[1]:
            raise ValueError("source_media_hash")
        result[clip_id] = path
    if len(result) != EXPECTED_CLIPS and len(clip_ids) == EXPECTED_CLIPS:
        raise ValueError("source_media_count")
    return result


def _jpeg(frame: object) -> bytes:
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise ValueError("jpeg_encode")
    return encoded.tobytes()


def prepare(args: argparse.Namespace) -> dict[str, object]:
    if socket.gethostname() != args.expected_host:
        raise ValueError("host_mismatch")
    salt = require_private_file(args.salt_file, expected_size=32)
    require_private_file(args.env_file)
    require_private_file(args.base_artifact)
    require_private_file(args.analysis_private)
    require_private_file(args.source_manifest)

    base = json.loads(args.base_artifact.read_text())
    analysis = json.loads(args.analysis_private.read_text())
    source_frozen = json.loads(args.source_manifest.read_text())
    if (
        base.get("experiment_id") != EXPECTED_EXPERIMENT
        or base.get("manifest_sha256") != EXPECTED_MANIFEST
        or not isinstance(base.get("pairs"), list)
        or not isinstance(analysis.get("final_boundaries"), list)
        or source_frozen.get("pair_count") != EXPECTED_PAIRS
        or source_frozen.get("clip_count") != EXPECTED_CLIPS
        or not isinstance(source_frozen.get("inputs"), list)
        or not isinstance(source_frozen.get("media"), list)
    ):
        raise ValueError("source_contract")

    load_env_file(args.env_file)
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise ValueError("supabase_env")
    client = create_client(url, key)
    mapped = map_effective_pairs(
        base["pairs"],
        _load_db_pairs(client),
        analysis["final_boundaries"],
        salt,
    )
    if len(mapped) != EXPECTED_PAIRS:
        raise ValueError("pair_count")
    mapped_by_key = {row.private_key: row for row in mapped}
    source_order = [row.get("pair") for row in source_frozen["inputs"]]
    if (
        any(not isinstance(pair, str) for pair in source_order)
        or len(set(source_order)) != EXPECTED_PAIRS
        or set(source_order) != set(mapped_by_key)
    ):
        raise ValueError("pair_identity")

    gap_by_digest = gap_seconds_by_digest(base["pairs"])
    media = load_cached_media(
        mapped=mapped,
        salt=salt,
        source_media_dir=args.source_media_dir,
        source_media_rows=source_frozen["media"],
    )

    _new_private_dir(args.output_dir)
    input_dir = args.output_dir / "inputs"
    input_dir.mkdir(mode=0o700)
    input_dir.chmod(0o700)
    input_rows: list[dict[str, object]] = []
    for pair in source_order:
        row = mapped_by_key[pair]
        gap = gap_by_digest[row.pair_digest]
        frames_a = extract_boundary_frames(
            media[row.left_clip_id],
            offsets_sec=A_BOUNDARY_OFFSETS_SEC,
            anchor="end",
        )
        frames_b = extract_boundary_frames(
            media[row.right_clip_id],
            offsets_sec=B_BOUNDARY_OFFSETS_SEC,
            anchor="start",
        )
        sheet_a, sheet_b = build_boundary_sheets(frames_a, frames_b, gap_sec=gap)
        payloads = (_jpeg(sheet_a), _jpeg(sheet_b))
        for suffix, payload in zip(("A", "B"), payloads, strict=True):
            _write_new(input_dir / f"{pair}-{suffix}.jpg", payload)
        input_rows.append({
            "pair": pair,
            "human": row.human_decision,
            "gap_sec": gap,
            "images": [_sha256(payload) for payload in payloads],
        })

    frozen = {
        "schema_version": "vlm-event-boundary-dense-input-v2",
        "experiment_id": EXPECTED_EXPERIMENT,
        "manifest_digest": EXPECTED_MANIFEST,
        "source_manifest_sha256": _sha256(args.source_manifest.read_bytes()),
        "pair_count": EXPECTED_PAIRS,
        "clip_count": EXPECTED_CLIPS,
        "representation": DENSE_REPRESENTATION,
        "prompt_version": DENSE_PROMPT_VERSION,
        "prompt_sha256": _sha256(DENSE_PROMPT.encode()),
        "sampling": {
            "a_before_end_sec": list(A_BOUNDARY_OFFSETS_SEC),
            "b_after_start_sec": list(B_BOUNDARY_OFFSETS_SEC),
            "layout_per_image": "3x2_chronological",
        },
        "inputs": input_rows,
    }
    manifest_path = args.output_dir / "frozen-manifest.json"
    _write_new(manifest_path, _canonical_bytes(frozen))
    return {
        "pair_count": len(input_rows),
        "image_count": len(input_rows) * 2,
        "manifest_sha256": _sha256(manifest_path.read_bytes()),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-host", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--salt-file", type=Path, required=True)
    parser.add_argument("--base-artifact", type=Path, required=True)
    parser.add_argument("--analysis-private", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--source-media-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    print(json.dumps(prepare(parse_args()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
