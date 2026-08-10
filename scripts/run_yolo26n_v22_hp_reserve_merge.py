"""Build an immutable HP-only reserve and merge it with frozen v2.2 v3.

Supabase and R2 are read-only inputs.  Predictions remain in private ledgers;
the merged reviewer CSV/ZIP contains generic sequence names and source pixels only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from scripts.build_yolo26n_v22_candidate_queue import classify_v22_candidate
from scripts.run_yolo26n_v22_candidate_mining import (
    _camera_night,
    _dhash,
    _extract_probes,
    _near_duplicate,
    _paged,
    _sha256_file,
    choose_review_probe_indices,
    eligible_clips,
)


PRIVATE_ROOT = Path("/Users/baek-end/private-rba/yolo26n-v22-candidates")
V1_OUTPUT_DIR = PRIVATE_ROOT / "attempt-20260810-owner-v1"
V2_OUTPUT_DIR = PRIVATE_ROOT / "attempt-20260810-owner-v2"
PARENT_OUTPUT_DIR = PRIVATE_ROOT / "attempt-20260811-owner-v3"
RESERVE_OUTPUT_DIR = PRIVATE_ROOT / "attempt-20260811-owner-v3-hp-reserve-v1"
MERGED_OUTPUT_DIR = PRIVATE_ROOT / "attempt-20260811-owner-v3-merged-v1"
DATASET_V21_ROOT = Path(
    "/Users/baek-end/private-rba/yolo26n-owner-dataset-v21/attempt-20260810-owner-final-v1"
)
DATASET_V21_PROVENANCE = Path(
    "/Users/baek-end/private-rba/yolo26n-v21-targeted/"
    "attempt-20260810-owner-v2/candidate-manifest.private.json"
)
DATASET_V21_IMAGES_DIR = DATASET_V21_ROOT / "input-images"
V1_PROVENANCE = V1_OUTPUT_DIR / "candidate-manifest.private.json"
V2_PROVENANCE = V2_OUTPUT_DIR / "candidate-manifest.private.json"
V1_PROBE_SOURCES = V1_OUTPUT_DIR / "probe-sources.private.json"
V2_PROBE_SOURCES = V2_OUTPUT_DIR / "probe-sources.private.json"
V3_PROBE_SOURCES = PARENT_OUTPUT_DIR / "probe-sources.private.json"
V3_ANALYZED_SOURCES = PARENT_OUTPUT_DIR / "analyzed-sources.private.json"

PARENT_SOURCE_COMMIT = "dc9de5c3e3c34697fc66837c4680c13d42f13f40"
APPROVED_SEED = "owner-v2.2"
APPROVED_CUTOFF = "2026-07-15T00:00:00Z"
APPROVED_IMGSZ = 960
APPROVED_INFERENCE_CONF = 0.05
PROBE_FRAMES_PER_SOURCE = 24
FRAMES_PER_SOURCE = 2
MAX_FINAL_FRAMES_PER_NIGHT = 12
RESERVE_SOURCE_QUOTA = 100
MAX_RESERVE_SOURCES_PER_NIGHT = 4
RESERVE_FRAME_TARGET = 23
PARENT_BUCKET_COUNTS = {"hard_positive": 197, "hard_negative": 100}
FINAL_BUCKET_COUNTS = {"hard_positive": 220, "hard_negative": 100}
REVIEW_INSTRUCTION = "게코가 보이면 각 개체의 보이는 몸 영역에 bbox"
SHA256_LENGTH = 64
SOURCE_SELECTION_FIELDS = (
    "source_ref",
    "camera_id",
    "camera_night",
    "r2_key",
    "duration_sec",
    "gme_visible_ratio",
    "gme_unknown_ratio",
    "gme_max_geckos",
    "probe_bucket",
    "local_name",
)
REQUIRED_SOURCE_LEDGER_NAMES = (
    "dataset_v21_candidate",
    "v1_candidate",
    "v1_probe_sources",
    "v2_candidate",
    "v2_probe_sources",
    "v3_candidate",
    "v3_probe_sources",
    "v3_analyzed_sources",
)


def _require_exact_path(actual: Path | None, expected: Path, label: str) -> None:
    if not isinstance(actual, Path) or not actual.is_absolute() or actual != expected:
        raise ValueError(f"{label}={actual} (expected {expected})")


def _require_digest(value: str | None, label: str, *, length: int = SHA256_LENGTH) -> str:
    if not isinstance(value, str) or len(value) != length or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{label} must be {length} lowercase hex characters")
    return value


def _canonical_cutoff(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("cutoff must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_private_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def _extract_source_refs(payload: object) -> set[str]:
    if isinstance(payload, Mapping):
        refs: set[str] = set()
        for key, value in payload.items():
            if key == "source_ref":
                if not isinstance(value, str):
                    raise ValueError("source_ref must be a string")
                if not value.strip():
                    raise ValueError("source_ref must be nonempty")
                if value != value.strip():
                    raise ValueError("source_ref must not contain surrounding whitespace")
                refs.add(value)
            else:
                refs |= _extract_source_refs(value)
        return refs
    if isinstance(payload, list):
        refs: set[str] = set()
        for item in payload:
            refs |= _extract_source_refs(item)
        return refs
    return set()


def load_pinned_source_refs(pins: Sequence[tuple[Path, str]]) -> set[str]:
    """Load nonempty source provenance only after every file identity is pinned."""
    if not pins:
        raise ValueError("at least one pinned provenance file is required")
    refs: set[str] = set()
    for path, expected_sha256 in pins:
        _require_digest(expected_sha256, f"{path} sha256")
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"empty or missing provenance file: {path}")
        if _sha256_file(path) != expected_sha256:
            raise ValueError(f"provenance sha256 mismatch: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid provenance JSON: {path}") from exc
        path_refs = _extract_source_refs(payload)
        if not path_refs:
            raise ValueError(f"provenance has no source_ref: {path}")
        refs |= path_refs
    return refs


def load_required_source_exclusions(
    pins: Mapping[str, tuple[Path, str]],
) -> tuple[set[str], dict[str, str]]:
    """Load every frozen source ledger and return its exact pin manifest."""
    if set(pins) != set(REQUIRED_SOURCE_LEDGER_NAMES):
        missing = sorted(set(REQUIRED_SOURCE_LEDGER_NAMES) - set(pins))
        extra = sorted(set(pins) - set(REQUIRED_SOURCE_LEDGER_NAMES))
        raise ValueError(f"source provenance ledgers mismatch: missing={missing}, extra={extra}")
    ordered = [(pins[name][0], pins[name][1]) for name in REQUIRED_SOURCE_LEDGER_NAMES]
    refs = load_pinned_source_refs(ordered)
    provenance = {name: pins[name][1] for name in REQUIRED_SOURCE_LEDGER_NAMES}
    return refs, provenance


def _required_source_ledger_pins(
    args: argparse.Namespace,
) -> dict[str, tuple[Path, str]]:
    return {
        "dataset_v21_candidate": (
            args.dataset_v21_provenance,
            args.dataset_v21_provenance_sha256,
        ),
        "v1_candidate": (args.v1_provenance, args.v1_provenance_sha256),
        "v1_probe_sources": (args.v1_probe_sources, args.v1_probe_sources_sha256),
        "v2_candidate": (args.v2_provenance, args.v2_provenance_sha256),
        "v2_probe_sources": (args.v2_probe_sources, args.v2_probe_sources_sha256),
        "v3_candidate": (
            args.parent / "candidate-manifest.private.json",
            args.expected_parent_manifest_sha256,
        ),
        "v3_probe_sources": (args.v3_probe_sources, args.v3_probe_sources_sha256),
        "v3_analyzed_sources": (
            args.v3_analyzed_sources,
            args.v3_analyzed_sources_sha256,
        ),
    }


def _seed_rank(seed: str, purpose: str, *parts: object) -> str:
    material = ":".join((seed, purpose, *(str(part) for part in parts)))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _canonical_json_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def source_ref_set_sha256(source_refs: set[str]) -> str:
    return _canonical_json_sha256(sorted(source_refs))


def source_selection_sha256(rows: Iterable[Mapping[str, object]]) -> str:
    selection = sorted(
        ({field: row[field] for field in SOURCE_SELECTION_FIELDS} for row in rows),
        key=lambda row: (
            str(row["source_ref"]),
            str(row["camera_night"]),
            str(row["probe_bucket"]),
        ),
    )
    return _canonical_json_sha256(selection)


def _parent_night_counts(frames: Iterable[Mapping[str, object]]) -> Counter[str]:
    return Counter(str(frame["camera_night"]) for frame in frames)


def select_reserve_inventory_sources(
    rows: Iterable[Mapping[str, object]],
    *,
    parent_night_counts: Mapping[str, int],
    excluded_source_refs: set[str],
    quota: int = RESERVE_SOURCE_QUOTA,
    max_sources_per_night: int = MAX_RESERVE_SOURCES_PER_NIGHT,
    seed: str = APPROVED_SEED,
) -> list[dict[str, object]]:
    """Select an exact HP metadata pool with a bounded incremental night load."""
    canonical: dict[str, Mapping[str, object]] = {}
    for row in rows:
        source_ref = str(row.get("source_ref", "")).strip()
        camera_night = str(row.get("camera_night", "")).strip()
        camera_id = str(row.get("camera_id", "")).strip()
        r2_key = str(row.get("r2_key", "")).strip()
        if (
            not source_ref
            or not camera_night
            or not camera_id
            or not r2_key
            or source_ref in excluded_source_refs
            or int(row.get("gme_max_geckos", 0) or 0) < 1
            or int(parent_night_counts.get(camera_night, 0)) >= MAX_FINAL_FRAMES_PER_NIGHT
        ):
            continue
        current = canonical.get(source_ref)
        if current is None or json.dumps(row, sort_keys=True, default=str) < json.dumps(
            current, sort_keys=True, default=str
        ):
            canonical[source_ref] = row

    ranked = sorted(
        canonical.values(),
        key=lambda row: (
            _seed_rank(seed, "hp-reserve-inventory", row["source_ref"]),
            str(row["source_ref"]),
        ),
    )
    night_counts: Counter[str] = Counter()
    selected: list[dict[str, object]] = []
    for row in ranked:
        night = str(row["camera_night"])
        if night_counts[night] >= max_sources_per_night:
            continue
        selected.append({**row, "probe_bucket": "hard_positive"})
        night_counts[night] += 1
        if len(selected) == quota:
            break
    return selected


class _Dinic:
    def __init__(self) -> None:
        self.graph: dict[object, list[list[object]]] = {}

    def add_edge(self, start: object, end: object, capacity: int) -> None:
        forward: list[object] = [end, capacity, None]
        backward: list[object] = [start, 0, forward]
        forward[2] = backward
        self.graph.setdefault(start, []).append(forward)
        self.graph.setdefault(end, []).append(backward)

    def flow(self, origin: object, sink: object, limit: int) -> int:
        total = 0
        while total < limit:
            levels = {origin: 0}
            pending = deque([origin])
            while pending:
                node = pending.popleft()
                for edge in self.graph.get(node, []):
                    if int(edge[1]) > 0 and edge[0] not in levels:
                        levels[edge[0]] = levels[node] + 1
                        pending.append(edge[0])
            if sink not in levels:
                break
            offsets = {node: 0 for node in self.graph}

            def send(node: object, amount: int) -> int:
                if node == sink:
                    return amount
                edges = self.graph[node]
                while offsets[node] < len(edges):
                    edge = edges[offsets[node]]
                    destination = edge[0]
                    if int(edge[1]) > 0 and levels.get(destination) == levels[node] + 1:
                        sent = send(destination, min(amount, int(edge[1])))
                        if sent:
                            edge[1] = int(edge[1]) - sent
                            reverse = edge[2]
                            reverse[1] = int(reverse[1]) + sent
                            return sent
                    offsets[node] += 1
                return 0

            while total < limit:
                sent = send(origin, limit - total)
                if not sent:
                    break
                total += sent
        return total


def _validate_reserve_row(row: Mapping[str, object]) -> None:
    if row.get("candidate_bucket") != "hard_positive":
        raise ValueError("reserve candidates must be hard_positive only")
    for field in ("source_ref", "camera_night", "camera_id", "local_name"):
        if not isinstance(row.get(field), str) or not str(row[field]).strip():
            raise ValueError(f"reserve frame requires nonempty {field}")
    _require_digest(str(row.get("image_sha256", "")), "reserve image_sha256")
    if isinstance(row.get("dhash"), bool) or not isinstance(row.get("dhash"), int):
        raise ValueError("reserve frame dhash must be an integer")


def _flow_reserve_frames(
    rows: Sequence[Mapping[str, object]],
    *,
    parent_night_counts: Mapping[str, int],
    target: int,
    forbidden: frozenset[int],
    seed: str,
) -> list[Mapping[str, object]]:
    origin, sink = ("origin",), ("sink",)
    flow = _Dinic()
    by_hash_source: dict[tuple[str, str], list[int]] = {}
    source_night: dict[str, str] = {}
    for index, row in enumerate(rows):
        if index in forbidden:
            continue
        source = str(row["source_ref"])
        night = str(row["camera_night"])
        existing_night = source_night.setdefault(source, night)
        if existing_night != night:
            raise ValueError(f"source spans camera nights: {source}")
        by_hash_source.setdefault((str(row["image_sha256"]), source), []).append(index)

    hashes = sorted(
        {image_sha for image_sha, _source in by_hash_source},
        key=lambda value: (_seed_rank(seed, "merge-hash", value), value),
    )
    sources = sorted(
        source_night,
        key=lambda value: (_seed_rank(seed, "merge-source", value), value),
    )
    nights = sorted(
        set(source_night.values()),
        key=lambda value: (_seed_rank(seed, "merge-night", value), value),
    )
    for image_sha in hashes:
        flow.add_edge(origin, ("hash", image_sha), 1)
    edge_for_pair: dict[tuple[str, str], list[object]] = {}
    for image_sha, source in sorted(
        by_hash_source,
        key=lambda pair: (_seed_rank(seed, "merge-edge", *pair), pair),
    ):
        start = ("hash", image_sha)
        end = ("source", source)
        flow.add_edge(start, end, 1)
        edge_for_pair[(image_sha, source)] = flow.graph[start][-1]
    for source in sources:
        night = source_night[source]
        flow.add_edge(("source", source), ("night", night), FRAMES_PER_SOURCE)
    for night in nights:
        residual = max(0, MAX_FINAL_FRAMES_PER_NIGHT - int(parent_night_counts.get(night, 0)))
        flow.add_edge(("night", night), sink, residual)

    if flow.flow(origin, sink, target) < target:
        return []
    selected: list[Mapping[str, object]] = []
    for pair, edge in edge_for_pair.items():
        reverse = edge[2]
        if int(reverse[1]) != 1:
            continue
        indices = by_hash_source[pair]
        index = min(
            indices,
            key=lambda value: (
                _seed_rank(
                    seed,
                    "merge-frame",
                    rows[value]["source_ref"],
                    rows[value].get("probe_index", 0),
                    rows[value]["image_sha256"],
                ),
                value,
            ),
        )
        selected.append(rows[index])
    return sorted(
        selected,
        key=lambda row: (
            _seed_rank(seed, "merge-output", row["source_ref"], row["image_sha256"]),
            str(row["source_ref"]),
            str(row["image_sha256"]),
        ),
    )


def select_reserve_frames(
    rows: Iterable[Mapping[str, object]],
    *,
    parent_night_counts: Mapping[str, int],
    target: int = RESERVE_FRAME_TARGET,
    seed: str = APPROVED_SEED,
    excluded_image_sha256: set[str] | None = None,
) -> list[dict[str, object]]:
    """Find an exact deterministic SHA/source/night allocation.

    Max-flow handles shared exact hashes without greedy starvation.  If the
    optimistic flow chooses a source-local dHash conflict, bounded branching
    forbids one conflicting frame and retries until it finds a valid flow.
    """
    excluded = excluded_image_sha256 or set()
    canonical: dict[tuple[object, ...], dict[str, object]] = {}
    for raw in rows:
        row = dict(raw)
        _validate_reserve_row(row)
        if str(row["image_sha256"]) in excluded:
            continue
        identity = (
            row["image_sha256"],
            row["source_ref"],
            row.get("probe_index", 0),
            row.get("frame_index", 0),
            row["local_name"],
        )
        canonical[identity] = row
    candidates = sorted(
        canonical.values(),
        key=lambda row: (
            _seed_rank(seed, "merge-candidate", row["source_ref"], row["image_sha256"]),
            str(row["source_ref"]),
            str(row["image_sha256"]),
        ),
    )

    pending: list[frozenset[int]] = [frozenset()]
    visited: set[frozenset[int]] = set()
    while pending:
        forbidden = pending.pop()
        if forbidden in visited:
            continue
        visited.add(forbidden)
        selected = _flow_reserve_frames(
            candidates,
            parent_night_counts=parent_night_counts,
            target=target,
            forbidden=forbidden,
            seed=seed,
        )
        if not selected:
            continue
        selected_indices = [candidates.index(row) for row in selected]
        conflict: tuple[int, int] | None = None
        by_source: dict[str, list[int]] = {}
        for index in selected_indices:
            by_source.setdefault(str(candidates[index]["source_ref"]), []).append(index)
        for source in sorted(by_source):
            indices = by_source[source]
            for left_position, left_index in enumerate(indices):
                for right_index in indices[left_position + 1 :]:
                    if (
                        int(candidates[left_index]["dhash"])
                        ^ int(candidates[right_index]["dhash"])
                    ).bit_count() <= 2:
                        conflict = (left_index, right_index)
                        break
                if conflict:
                    break
            if conflict:
                break
        if conflict is None:
            return [dict(row) for row in selected]
        # LIFO push in reverse rank makes the lower seeded prohibition run first.
        for index in sorted(conflict, reverse=True):
            pending.append(forbidden | {index})
    return []


def validate_fresh_output(output: Path, *, phase: str) -> None:
    if phase == "inventory":
        if not output.exists():
            return
        if not output.is_dir():
            raise ValueError("fresh reserve output is not a directory")
        unexpected = sorted(path.name for path in output.iterdir() if path.name != "code")
        if unexpected:
            raise ValueError("fresh reserve output has stale artifacts: " + ", ".join(unexpected))
        return
    if phase == "analyze":
        required = {
            "code",
            "inventory-selection.private.json",
            "probe-sources.private.json",
            "source-clips",
        }
        if not output.is_dir():
            raise ValueError("fresh analyze output is missing")
        present = {path.name for path in output.iterdir()}
        if present != required:
            raise ValueError(
                "fresh analyze output mismatch: missing="
                f"{sorted(required - present)}, stale={sorted(present - required)}"
            )
        return
    if phase == "merge":
        if output.exists():
            raise ValueError("fresh merged output must not exist")
        return
    raise ValueError(f"unknown phase: {phase}")


def _read_pinned_json(path: Path, expected_sha256: str, label: str) -> dict[str, object]:
    _require_digest(expected_sha256, f"{label} sha256")
    if not path.is_file() or _sha256_file(path) != expected_sha256:
        raise ValueError(f"{label} sha256 mismatch")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label} JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"invalid {label} payload")
    return payload


def _validate_source_commit(code_dir: Path, expected: str, label: str) -> str:
    _require_digest(expected, f"{label} source commit", length=40)
    path = code_dir / "source-commit.txt"
    if not path.is_file() or path.read_text(encoding="utf-8").strip() != expected:
        raise ValueError(f"{label} source commit mismatch")
    return expected


def _code_sha256(code_dir: Path, preferred: str) -> str:
    paths = [code_dir / "scripts" / preferred, code_dir / preferred]
    path = next((candidate for candidate in paths if candidate.is_file()), None)
    if path is None:
        raise ValueError(f"missing frozen code file: {preferred}")
    return _sha256_file(path)


def _validate_parent_payload(payload: Mapping[str, object]) -> list[dict[str, object]]:
    if payload.get("status") != "V22_CANDIDATE_QUEUE_SHORTAGE":
        raise ValueError("parent must remain the reviewed v3 shortage artifact")
    if payload.get("seed") != APPROVED_SEED:
        raise ValueError("parent seed mismatch")
    if payload.get("bucket_counts") != PARENT_BUCKET_COUNTS:
        raise ValueError("parent bucket counts must be HP197/HN100")
    if int(payload.get("review_frame_count", -1)) != 297:
        raise ValueError("parent review frame count must be 297")
    if payload.get("prediction_boxes_exposed_to_reviewer") is not False:
        raise ValueError("parent reviewer predictions must remain hidden")
    if int(payload.get("db_write_count", -1)) != 0 or int(payload.get("r2_write_count", -1)) != 0:
        raise ValueError("parent write audit mismatch")
    if int(payload.get("source_cap_violation_count", -1)) != 0:
        raise ValueError("parent source cap violation")
    if int(payload.get("camera_night_cap_violation_count", -1)) != 0:
        raise ValueError("parent camera-night cap violation")
    frames = payload.get("frames")
    if not isinstance(frames, list) or len(frames) != 297:
        raise ValueError("parent frame ledger mismatch")
    expected_sequences = [f"V{ordinal:04d}" for ordinal in range(1, 298)]
    if [frame.get("sequence") for frame in frames if isinstance(frame, Mapping)] != expected_sequences:
        raise ValueError("parent sequence/order mismatch")
    normalized = [dict(frame) for frame in frames if isinstance(frame, Mapping)]
    frame_bucket_counts = Counter(str(frame.get("candidate_bucket", "")) for frame in normalized)
    if dict(frame_bucket_counts) != PARENT_BUCKET_COUNTS:
        raise ValueError("parent frame bucket counts mismatch")
    return normalized


def _validate_review_csv(
    parent: Path,
    sequences: Sequence[str],
    *,
    expected_sha256: str,
) -> list[dict[str, str]]:
    _require_digest(expected_sha256, "parent review CSV sha256")
    path = parent / "review-index.csv"
    if not path.is_file() or _sha256_file(path) != expected_sha256:
        raise ValueError("parent review CSV sha256 mismatch")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        expected_header = ["sequence", "filename", "instruction"]
        if reader.fieldnames != expected_header:
            raise ValueError("parent review CSV is not blind/generic")
        rows = list(reader)
    if [row["sequence"] for row in rows] != list(sequences):
        raise ValueError("parent review CSV order mismatch")
    if any(row["filename"] != f'{row["sequence"]}.jpg' for row in rows):
        raise ValueError("parent review filenames are not generic")
    if any(row["instruction"] != REVIEW_INSTRUCTION for row in rows):
        raise ValueError("parent review instruction mismatch")
    return rows


def _default_dhash_reader(path: Path) -> int:
    import cv2

    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"unreadable review image: {path}")
    return _dhash(image, cv2)


def _validate_frame_files(
    root: Path,
    frames: Sequence[Mapping[str, object]],
    *,
    dhash_reader: Callable[[Path], int],
) -> tuple[set[str], dict[str, int]]:
    image_hashes: set[str] = set()
    source_counts: Counter[str] = Counter()
    night_counts: Counter[str] = Counter()
    source_dhashes: dict[str, set[int]] = {}
    dhashes: dict[str, int] = {}
    source_buckets: dict[str, str] = {}
    for frame in frames:
        sequence = str(frame["sequence"])
        path = root / "review-frames" / f"{sequence}.jpg"
        expected_sha = _require_digest(str(frame.get("image_sha256", "")), "frame image_sha256")
        if not path.is_file() or _sha256_file(path) != expected_sha:
            raise ValueError(f"frame image sha256 mismatch: {sequence}")
        if expected_sha in image_hashes:
            raise ValueError("global exact SHA duplicate")
        image_hashes.add(expected_sha)
        source = str(frame["source_ref"])
        night = str(frame["camera_night"])
        bucket = str(frame["candidate_bucket"])
        prior_bucket = source_buckets.setdefault(source, bucket)
        if prior_bucket != bucket:
            raise ValueError("cross-bucket source")
        source_counts[source] += 1
        night_counts[night] += 1
        digest = dhash_reader(path)
        if _near_duplicate(digest, source_dhashes.setdefault(source, set())):
            raise ValueError("source-local dHash distance violation")
        source_dhashes[source].add(digest)
        dhashes[sequence] = digest
    if max(source_counts.values(), default=0) > FRAMES_PER_SOURCE:
        raise ValueError("source cap violation")
    if max(night_counts.values(), default=0) > MAX_FINAL_FRAMES_PER_NIGHT:
        raise ValueError("camera-night cap violation")
    return image_hashes, dhashes


def _validate_parent_artifact(
    parent: Path,
    *,
    expected_manifest_sha256: str,
    expected_review_index_sha256: str,
    dhash_reader: Callable[[Path], int],
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, str]], set[str], dict[str, int]]:
    payload = _read_pinned_json(
        parent / "candidate-manifest.private.json", expected_manifest_sha256, "parent manifest"
    )
    frames = _validate_parent_payload(payload)
    _validate_source_commit(parent / "code", PARENT_SOURCE_COMMIT, "parent")
    analyzed_path = parent / "analyzed-sources.private.json"
    if _sha256_file(analyzed_path) != payload.get("analyzed_ledger_sha256"):
        raise ValueError("parent analyzed ledger sha256 mismatch")
    rows = _validate_review_csv(
        parent,
        [str(frame["sequence"]) for frame in frames],
        expected_sha256=expected_review_index_sha256,
    )
    hashes, dhashes = _validate_frame_files(parent, frames, dhash_reader=dhash_reader)
    return payload, frames, rows, hashes, dhashes


def _validate_reserve_artifact(
    reserve: Path,
    *,
    expected_manifest_sha256: str,
    expected_source_commit: str,
    expected_parent_manifest_sha256: str,
    dhash_reader: Callable[[Path], int],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    payload = _read_pinned_json(
        reserve / "reserve-manifest.private.json", expected_manifest_sha256, "reserve manifest"
    )
    _validate_source_commit(reserve / "code", expected_source_commit, "reserve")
    if payload.get("status") != "V22_HP_RESERVE_READY":
        raise SystemExit("V22_HP_RESERVE_SHORTAGE")
    if payload.get("seed") != APPROVED_SEED:
        raise ValueError("reserve seed mismatch")
    if payload.get("prediction_boxes_exposed_to_reviewer") is not False:
        raise ValueError("reserve predictions must remain hidden")
    if int(payload.get("db_write_count", -1)) != 0 or int(payload.get("r2_write_count", -1)) != 0:
        raise ValueError("reserve write audit mismatch")
    frames = payload.get("frames")
    if not isinstance(frames, list) or int(payload.get("accepted_count", -1)) != len(frames):
        raise ValueError("reserve frame count mismatch")
    if len(frames) < RESERVE_FRAME_TARGET:
        raise SystemExit("V22_HP_RESERVE_SHORTAGE")
    analyzed_path = reserve / "analyzed-sources.private.json"
    if _sha256_file(analyzed_path) != payload.get("analyzed_ledger_sha256"):
        raise ValueError("reserve analyzed ledger sha256 mismatch")
    provenance = payload.get("provenance")
    probe_sources_path = reserve / "probe-sources.private.json"
    if not probe_sources_path.is_file():
        raise ValueError("reserve provenance mismatch")
    expected_provenance = {
        "inventory_summary_sha256": _sha256_file(
            reserve / "inventory-selection.private.json"
        ),
        "probe_sources_sha256": _sha256_file(probe_sources_path),
        "parent_manifest_sha256": expected_parent_manifest_sha256,
        "source_commit": expected_source_commit,
        "code_sha256": _code_sha256(
            reserve / "code", "run_yolo26n_v22_hp_reserve_merge.py"
        ),
    }
    if not isinstance(provenance, Mapping) or any(
        provenance.get(key) != value for key, value in expected_provenance.items()
    ):
        raise ValueError("reserve provenance mismatch")
    source_provenance = provenance.get("source_provenance_sha256")
    if not isinstance(source_provenance, Mapping) or set(source_provenance) != set(
        REQUIRED_SOURCE_LEDGER_NAMES
    ):
        raise ValueError("reserve provenance mismatch")
    try:
        for name in REQUIRED_SOURCE_LEDGER_NAMES:
            _require_digest(source_provenance.get(name), f"reserve {name} sha256")
        _require_digest(
            provenance.get("excluded_source_refs_sha256"),
            "reserve excluded source refs sha256",
        )
    except ValueError as exc:
        raise ValueError("reserve provenance mismatch") from exc
    normalized = [dict(frame) for frame in frames if isinstance(frame, Mapping)]
    if len(normalized) != len(frames):
        raise ValueError("reserve frame ledger malformed")
    for frame in normalized:
        _validate_reserve_row(frame)
        path = reserve / "review-frames" / str(frame["local_name"])
        if not path.is_file() or _sha256_file(path) != frame["image_sha256"]:
            raise ValueError("reserve image sha256 mismatch")
        if dhash_reader(path) != int(frame["dhash"]):
            raise ValueError("reserve dHash mismatch")
    return payload, normalized


def merge_artifacts(
    *,
    parent: Path,
    reserve: Path,
    output: Path,
    expected_parent_manifest_sha256: str,
    expected_parent_review_index_sha256: str,
    expected_reserve_manifest_sha256: str,
    expected_reserve_source_commit: str,
    seed: str = APPROVED_SEED,
    dhash_reader: Callable[[Path], int] = _default_dhash_reader,
) -> dict[str, object]:
    """Validate both immutable inputs, then atomically publish an exact 320 queue."""
    validate_fresh_output(output, phase="merge")
    parent_payload, parent_frames, parent_rows, parent_hashes, _ = _validate_parent_artifact(
        parent,
        expected_manifest_sha256=expected_parent_manifest_sha256,
        expected_review_index_sha256=expected_parent_review_index_sha256,
        dhash_reader=dhash_reader,
    )
    reserve_payload, reserve_frames = _validate_reserve_artifact(
        reserve,
        expected_manifest_sha256=expected_reserve_manifest_sha256,
        expected_source_commit=expected_reserve_source_commit,
        expected_parent_manifest_sha256=expected_parent_manifest_sha256,
        dhash_reader=dhash_reader,
    )
    if reserve_payload.get("checkpoint_sha256") != parent_payload.get("checkpoint_sha256"):
        raise ValueError("reserve checkpoint differs from parent")
    parent_source_refs = {str(frame["source_ref"]) for frame in parent_frames}
    reserve_source_refs = {str(frame["source_ref"]) for frame in reserve_frames}
    if parent_source_refs & reserve_source_refs:
        raise ValueError("reserve reuses a parent source")
    selected = select_reserve_frames(
        reserve_frames,
        parent_night_counts=_parent_night_counts(parent_frames),
        target=RESERVE_FRAME_TARGET,
        seed=seed,
        excluded_image_sha256=parent_hashes,
    )
    if len(selected) != RESERVE_FRAME_TARGET:
        raise SystemExit("V22_HP_RESERVE_MERGE_SHORTAGE")

    temporary_root = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        review_dir = temporary_root / "review-frames"
        review_dir.mkdir()
        merged_frames = [dict(frame) for frame in parent_frames]
        merged_rows = [dict(row) for row in parent_rows]
        for frame in parent_frames:
            sequence = str(frame["sequence"])
            shutil.copyfile(
                parent / "review-frames" / f"{sequence}.jpg",
                review_dir / f"{sequence}.jpg",
            )
        for offset, frame in enumerate(selected, start=298):
            sequence = f"V{offset:04d}"
            shutil.copyfile(
                reserve / "review-frames" / str(frame["local_name"]),
                review_dir / f"{sequence}.jpg",
            )
            private_frame = {key: value for key, value in frame.items() if key != "local_name"}
            private_frame["sequence"] = sequence
            merged_frames.append(private_frame)
            merged_rows.append(
                {
                    "sequence": sequence,
                    "filename": f"{sequence}.jpg",
                    "instruction": "게코가 보이면 각 개체의 보이는 몸 영역에 bbox",
                }
            )

        final_hashes, _ = _validate_frame_files(
            temporary_root, merged_frames, dhash_reader=dhash_reader
        )
        if len(final_hashes) != 320:
            raise ValueError("merged global SHA count mismatch")
        final_bucket_counts = Counter(
            str(frame.get("candidate_bucket", "")) for frame in merged_frames
        )
        if dict(final_bucket_counts) != FINAL_BUCKET_COUNTS:
            raise ValueError("merged frame bucket counts mismatch")
        if [frame["sequence"] for frame in merged_frames[:297]] != [
            frame["sequence"] for frame in parent_frames
        ]:
            raise ValueError("parent frame order changed")
        for frame in parent_frames:
            sequence = str(frame["sequence"])
            if _sha256_file(temporary_root / "review-frames" / f"{sequence}.jpg") != frame["image_sha256"]:
                raise ValueError("parent frame bytes changed")

        with (temporary_root / "review-index.csv").open(
            "w", newline="", encoding="utf-8"
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=["sequence", "filename", "instruction"])
            writer.writeheader()
            writer.writerows(merged_rows)

        parent_code_sha = _code_sha256(
            parent / "code", "run_yolo26n_v22_candidate_mining.py"
        )
        reserve_code_sha = _code_sha256(
            reserve / "code", "run_yolo26n_v22_hp_reserve_merge.py"
        )
        manifest = {
            "schema": "yolo26n-v22-candidate-queue-merged-v1",
            "status": "V22_CANDIDATE_QUEUE_READY",
            "seed": seed,
            "model": parent_payload.get("model"),
            "checkpoint_sha256": parent_payload.get("checkpoint_sha256"),
            "prediction_boxes_exposed_to_reviewer": False,
            "human_review_required": True,
            "db_write_count": 0,
            "r2_write_count": 0,
            "review_frame_count": 320,
            "bucket_counts": dict(final_bucket_counts),
            "source_cap": FRAMES_PER_SOURCE,
            "camera_night_cap": MAX_FINAL_FRAMES_PER_NIGHT,
            "frames": merged_frames,
            "selection": {
                "algorithm": "sha-source-night-dinic-with-dhash-branch-v1",
                "seed": seed,
                "reserve_frame_quota": RESERVE_FRAME_TARGET,
                "source_cap": FRAMES_PER_SOURCE,
                "camera_night_cap": MAX_FINAL_FRAMES_PER_NIGHT,
                "exact_sha_scope": "dataset-v21+parent+reserve",
                "source_local_dhash_max_distance": 2,
            },
            "provenance": {
                "parent": {
                    "path": str(parent),
                    "manifest_sha256": expected_parent_manifest_sha256,
                    "review_index_sha256": expected_parent_review_index_sha256,
                    "analyzed_ledger_sha256": parent_payload["analyzed_ledger_sha256"],
                    "checkpoint_sha256": parent_payload["checkpoint_sha256"],
                    "source_commit": PARENT_SOURCE_COMMIT,
                    "code_sha256": parent_code_sha,
                },
                "reserve": {
                    "path": str(reserve),
                    "manifest_sha256": expected_reserve_manifest_sha256,
                    "probe_sources_sha256": reserve_payload["provenance"][
                        "probe_sources_sha256"
                    ],
                    "source_provenance_sha256": reserve_payload["provenance"][
                        "source_provenance_sha256"
                    ],
                    "excluded_source_refs_sha256": reserve_payload["provenance"][
                        "excluded_source_refs_sha256"
                    ],
                    "analyzed_ledger_sha256": reserve_payload["analyzed_ledger_sha256"],
                    "checkpoint_sha256": reserve_payload["checkpoint_sha256"],
                    "source_commit": expected_reserve_source_commit,
                    "code_sha256": reserve_code_sha,
                },
            },
        }
        _write_private_json(temporary_root / "candidate-manifest.private.json", manifest)
        with zipfile.ZipFile(
            temporary_root / "cvat-upload.zip", "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for path in sorted(review_dir.glob("V*.jpg")):
                archive.write(path, arcname=path.name)
        with zipfile.ZipFile(temporary_root / "cvat-upload.zip") as archive:
            if archive.testzip() is not None or archive.namelist() != [
                f"V{ordinal:04d}.jpg" for ordinal in range(1, 321)
            ]:
                raise ValueError("merged CVAT ZIP integrity/order mismatch")
        os.replace(temporary_root, output)
    except BaseException:
        if temporary_root.exists():
            shutil.rmtree(temporary_root)
        raise
    return manifest


def _parent_payload_for_inventory(args: argparse.Namespace) -> tuple[dict[str, object], list[dict[str, object]]]:
    payload = _read_pinned_json(
        args.parent / "candidate-manifest.private.json",
        args.expected_parent_manifest_sha256,
        "parent manifest",
    )
    return payload, _validate_parent_payload(payload)


def _inventory_external_read(
    args: argparse.Namespace,
    excluded_refs: set[str],
    parent_frames: Sequence[Mapping[str, object]],
    source_provenance_sha256: Mapping[str, str],
) -> None:
    reporter_repo = args.reporter_repo.resolve()
    sys.path[:0] = [str(reporter_repo)]
    from supabase import create_client

    from reporter import config, r2

    sb = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    clip_rows = _paged(
        lambda: sb.table("motion_clips")
        .select("id,camera_id,started_at,duration_sec,r2_key,clip_purpose")
        .gte("started_at", args.cutoff)
        .not_.is_("r2_key", "null")
        .order("started_at")
    )
    exclusion_rows = _paged(
        lambda: sb.table("motion_clip_system_exclusions")
        .select("clip_id,state")
        .order("clip_id")
    )
    exclusions = {
        str(row["clip_id"]): str(row["state"])
        for row in exclusion_rows
        if row.get("clip_id") and row.get("state")
    }
    run_rows = _paged(
        lambda: sb.table("gme_runs")
        .select(
            "clip_id,created_at,duration_sec,visible_sec,unknown_sec,"
            "max_simultaneous_geckos,status"
        )
        .eq("status", "ok")
        .order("created_at", desc=True)
    )
    latest_runs: dict[str, Mapping[str, object]] = {}
    for row in run_rows:
        latest_runs.setdefault(str(row["clip_id"]), row)
    eligible: list[dict[str, object]] = []
    for clip in eligible_clips(clip_rows, exclusions):
        source_ref = str(clip["id"])
        run = latest_runs.get(source_ref)
        if source_ref in excluded_refs or run is None or not str(clip.get("r2_key") or ""):
            continue
        duration = float(run.get("duration_sec") or clip.get("duration_sec") or 0.0)
        if duration <= 0:
            continue
        eligible.append(
            {
                "source_ref": source_ref,
                "camera_id": str(clip["camera_id"]),
                "camera_night": _camera_night(str(clip["camera_id"]), str(clip["started_at"])),
                "r2_key": str(clip["r2_key"]),
                "duration_sec": duration,
                "gme_visible_ratio": float(run.get("visible_sec") or 0.0) / duration,
                "gme_unknown_ratio": float(run.get("unknown_sec") or 0.0) / duration,
                "gme_max_geckos": int(run.get("max_simultaneous_geckos") or 0),
            }
        )
    selected = select_reserve_inventory_sources(
        eligible,
        parent_night_counts=_parent_night_counts(parent_frames),
        excluded_source_refs=excluded_refs,
        quota=args.probe_hard_positive_sources,
        max_sources_per_night=args.probe_max_sources_per_night,
        seed=args.seed,
    )
    selected_source_rows = []
    for ordinal, source in enumerate(selected, start=1):
        selected_source_rows.append(
            {
                **{field: source[field] for field in SOURCE_SELECTION_FIELDS[:-2]},
                "probe_bucket": "hard_positive",
                "local_name": f"S{ordinal:04d}.mp4",
            }
        )
    selected_sources_sha256 = source_selection_sha256(selected_source_rows)
    excluded_source_refs_sha256 = source_ref_set_sha256(excluded_refs)
    summary = {
        "schema": "yolo26n-v22-hp-reserve-inventory-v1",
        "status": (
            "V22_HP_RESERVE_INVENTORY_READY"
            if len(selected) == RESERVE_SOURCE_QUOTA
            else "V22_HP_RESERVE_INVENTORY_SHORTAGE"
        ),
        "seed": args.seed,
        "cutoff": args.cutoff,
        "eligible_hp_source_count": sum(int(row.get("gme_max_geckos", 0)) >= 1 for row in eligible),
        "selected_hp_source_count": len(selected),
        "selected_hn_source_count": 0,
        "hp_source_quota": RESERVE_SOURCE_QUOTA,
        "incremental_max_sources_per_night": MAX_RESERVE_SOURCES_PER_NIGHT,
        "selected_sources_sha256": selected_sources_sha256,
        "excluded_source_refs_sha256": excluded_source_refs_sha256,
        "source_provenance_sha256": dict(source_provenance_sha256),
        "selected_sources": selected_source_rows,
        "db_write_count": 0,
        "r2_write_count": 0,
    }
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    output.chmod(0o700)
    inventory_summary_path = output / "inventory-selection.private.json"
    _write_private_json(inventory_summary_path, summary)
    print(
        json.dumps(
            {key: value for key, value in summary.items() if key != "selected_sources"},
            sort_keys=True,
        )
    )
    if len(selected) != RESERVE_SOURCE_QUOTA:
        raise SystemExit("V22_HP_RESERVE_INVENTORY_SHORTAGE")

    clips_dir = output / "source-clips"
    clips_dir.mkdir()
    downloaded: list[dict[str, object]] = []
    missing = 0
    for ordinal, source in enumerate(selected, start=1):
        destination = clips_dir / f"S{ordinal:04d}.mp4"
        try:
            r2.download_clip(str(source["r2_key"]), destination)
        except r2.R2SourceMissing:
            missing += 1
            continue
        downloaded.append(
            {
                **source,
                "local_name": destination.name,
                "source_sha256": _sha256_file(destination),
            }
        )
    _write_private_json(
        output / "probe-sources.private.json",
        {
            **summary,
            "schema": "yolo26n-v22-hp-reserve-probe-sources-v1",
            "inventory_summary_sha256": _sha256_file(inventory_summary_path),
            "selected_sources": selected_source_rows,
            "downloaded_source_count": len(downloaded),
            "missing_source_count": missing,
            "sources": downloaded,
        },
    )


def inventory(args: argparse.Namespace) -> None:
    validate_cli_contract(args)
    validate_fresh_output(args.output, phase="inventory")
    _validate_source_commit(args.output / "code", args.expected_reserve_source_commit, "reserve")
    _, parent_frames = _parent_payload_for_inventory(args)
    excluded_refs, source_provenance_sha256 = load_required_source_exclusions(
        _required_source_ledger_pins(args)
    )
    _inventory_external_read(
        args, excluded_refs, parent_frames, source_provenance_sha256
    )


def _load_image_hashes(paths: Iterable[Path]) -> set[str]:
    hashes: set[str] = set()
    for directory in paths:
        if not directory.is_dir():
            raise ValueError(f"missing image directory: {directory}")
        for path in sorted(directory.glob("*.jpg")):
            digest = _sha256_file(path)
            if digest in hashes:
                raise ValueError("existing image corpus contains exact SHA duplicates")
            hashes.add(digest)
    return hashes


def validate_downloaded_source_clips(
    sources: Sequence[Mapping[str, object]], source_clips_dir: Path
) -> None:
    """Bind each downloaded local MP4 name to the exact bytes recorded by inventory."""
    if not source_clips_dir.is_dir():
        raise ValueError("source-clips directory is missing")
    expected_names: set[str] = set()
    source_refs: set[str] = set()
    for source in sources:
        source_ref = source.get("source_ref")
        local_name = source.get("local_name")
        if not isinstance(source_ref, str) or not source_ref or source_ref != source_ref.strip():
            raise ValueError("downloaded source_ref is invalid")
        if source_ref in source_refs:
            raise ValueError("downloaded source_ref is duplicated")
        source_refs.add(source_ref)
        if not isinstance(local_name, str) or re.fullmatch(r"S\d{4}\.mp4", local_name) is None:
            raise ValueError("downloaded source local_name is unsafe")
        if local_name in expected_names:
            raise ValueError("downloaded source local_name is duplicated")
        expected_names.add(local_name)
        _require_digest(source.get("source_sha256"), "downloaded source sha256")
    actual_names = {path.name for path in source_clips_dir.iterdir()}
    if actual_names != expected_names:
        raise ValueError(
            "source-clips filename set mismatch: "
            f"missing={sorted(expected_names - actual_names)}, "
            f"extra={sorted(actual_names - expected_names)}"
        )
    for source in sources:
        local_name = str(source["local_name"])
        if _sha256_file(source_clips_dir / local_name) != source["source_sha256"]:
            raise ValueError(f"downloaded source sha256 mismatch: {local_name}")


def validate_reserve_probe_payload(
    payload: Mapping[str, object],
    inventory_summary_path: Path,
    *,
    parent_frames: Sequence[Mapping[str, object]],
    excluded_source_refs: set[str],
    expected_source_provenance_sha256: Mapping[str, str] | None = None,
) -> list[dict[str, object]]:
    """Bind analyze input to the exact metadata preflight and HP-only download."""
    expected_inventory_sha = _require_digest(
        str(payload.get("inventory_summary_sha256", "")),
        "inventory summary sha256",
    )
    if not inventory_summary_path.is_file() or _sha256_file(inventory_summary_path) != expected_inventory_sha:
        raise ValueError("inventory summary sha256 mismatch")
    try:
        inventory = json.loads(inventory_summary_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid inventory summary JSON") from exc
    if payload.get("schema") != "yolo26n-v22-hp-reserve-probe-sources-v1":
        raise ValueError("probe provenance schema mismatch")
    exact = {
        "status": "V22_HP_RESERVE_INVENTORY_READY",
        "seed": APPROVED_SEED,
        "selected_hp_source_count": RESERVE_SOURCE_QUOTA,
        "selected_hn_source_count": 0,
        "db_write_count": 0,
        "r2_write_count": 0,
    }
    for key, value in exact.items():
        if payload.get(key) != value or inventory.get(key) != value:
            raise ValueError(f"inventory provenance mismatch: {key}")
    if expected_source_provenance_sha256 is not None:
        expected_provenance = dict(expected_source_provenance_sha256)
        if (
            payload.get("source_provenance_sha256") != expected_provenance
            or inventory.get("source_provenance_sha256") != expected_provenance
        ):
            raise ValueError("inventory source provenance sha256 mismatch")
    expected_excluded_sha = source_ref_set_sha256(excluded_source_refs)
    if (
        payload.get("excluded_source_refs_sha256") != expected_excluded_sha
        or inventory.get("excluded_source_refs_sha256") != expected_excluded_sha
    ):
        raise ValueError("inventory excluded source refs sha256 mismatch")
    raw_selected = payload.get("selected_sources")
    if not isinstance(raw_selected, list) or len(raw_selected) != RESERVE_SOURCE_QUOTA:
        raise ValueError("inventory selected source ledger mismatch")
    if inventory.get("selected_sources") != raw_selected:
        raise ValueError("probe sources are not bound to inventory selection ledger")
    selected_sources: dict[str, dict[str, object]] = {}
    selected_nights: Counter[str] = Counter()
    parent_nights = _parent_night_counts(parent_frames)
    for raw in raw_selected:
        if not isinstance(raw, Mapping):
            raise ValueError("inventory selected source row malformed")
        source_ref = str(raw.get("source_ref", "")).strip()
        night = str(raw.get("camera_night", "")).strip()
        if not source_ref or not night or raw.get("probe_bucket") != "hard_positive":
            raise ValueError("inventory selected source must remain HP-only")
        if any(field not in raw for field in SOURCE_SELECTION_FIELDS):
            raise ValueError("inventory selected source identity is incomplete")
        local_name = raw.get("local_name")
        if not isinstance(local_name, str) or re.fullmatch(r"S\d{4}\.mp4", local_name) is None:
            raise ValueError("inventory selected source local_name is unsafe")
        if int(raw.get("gme_max_geckos", 0) or 0) < 1:
            raise ValueError("inventory selected source must remain HP-only")
        if source_ref in selected_sources:
            raise ValueError("inventory selected duplicate source_ref")
        if source_ref in excluded_source_refs:
            raise ValueError("inventory selected an excluded source")
        if int(parent_nights.get(night, 0)) >= MAX_FINAL_FRAMES_PER_NIGHT:
            raise ValueError("inventory selected a parent-full night")
        selected_nights[night] += 1
        selected_sources[source_ref] = dict(raw)
    if max(selected_nights.values(), default=0) > MAX_RESERVE_SOURCES_PER_NIGHT:
        raise ValueError("inventory selected source night cap violation")
    expected_selection_sha = source_selection_sha256(selected_sources.values())
    if (
        payload.get("selected_sources_sha256") != expected_selection_sha
        or inventory.get("selected_sources_sha256") != expected_selection_sha
    ):
        raise ValueError("inventory selected sources sha256 mismatch")
    downloaded = int(payload.get("downloaded_source_count", -1))
    missing = int(payload.get("missing_source_count", -1))
    if downloaded < 0 or missing < 0 or downloaded + missing != RESERVE_SOURCE_QUOTA:
        raise ValueError("inventory downloaded/missing count mismatch")
    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, list) or len(raw_sources) != downloaded:
        raise ValueError("inventory downloaded source ledger mismatch")
    sources: list[dict[str, object]] = []
    refs: set[str] = set()
    for raw in raw_sources:
        if not isinstance(raw, Mapping):
            raise ValueError("inventory source row malformed")
        source = dict(raw)
        source_ref = str(source.get("source_ref", "")).strip()
        if not source_ref:
            raise ValueError("inventory source_ref missing")
        if source_ref in refs:
            raise ValueError("inventory duplicate source_ref")
        refs.add(source_ref)
        if source.get("probe_bucket") != "hard_positive" or int(
            source.get("gme_max_geckos", 0) or 0
        ) < 1:
            raise ValueError("inventory must remain HP-only")
        for field in ("camera_id", "camera_night", "r2_key", "local_name"):
            if not isinstance(source.get(field), str) or not str(source[field]).strip():
                raise ValueError(f"inventory source {field} missing")
        if re.fullmatch(r"S\d{4}\.mp4", str(source["local_name"])) is None:
            raise ValueError("inventory source local_name is unsafe")
        selected = selected_sources.get(source_ref)
        if selected is None or any(
            selected[field] != source.get(field) for field in SOURCE_SELECTION_FIELDS
        ):
            raise ValueError("downloaded source differs from metadata selection")
        sources.append(source)
    return sources


def build_reserve_manifest(
    *,
    accepted_frames: Sequence[Mapping[str, object]],
    analyzed_sources: Sequence[Mapping[str, object]],
    hp_classifier_source_count: int,
    rejection_counts: Mapping[str, int],
    model_name: str,
    checkpoint_sha256: str,
    analyzed_ledger_sha256: str,
    inventory_summary_sha256: str,
    probe_sources_sha256: str,
    source_provenance_sha256: Mapping[str, str],
    excluded_source_refs_sha256: str,
    parent_manifest_sha256: str,
    source_commit: str,
    code_sha256: str,
) -> dict[str, object]:
    extraction_fields = ("requested", "readable", "decode_failed", "imwrite_failed")
    extraction_totals = {field: 0 for field in extraction_fields}
    for source in analyzed_sources:
        extraction = source.get("probe_extraction", {})
        if not isinstance(extraction, Mapping):
            raise ValueError("analyzed source probe extraction provenance is malformed")
        for field in extraction_fields:
            extraction_totals[field] += int(extraction.get(field, 0) or 0)
    accepted = [dict(frame) for frame in accepted_frames]
    accepted_sources = {str(frame["source_ref"]) for frame in accepted}
    status = (
        "V22_HP_RESERVE_READY"
        if len(accepted) >= RESERVE_FRAME_TARGET
        else "V22_HP_RESERVE_SHORTAGE"
    )
    return {
        "schema": "yolo26n-v22-hp-reserve-v1",
        "status": status,
        "seed": APPROVED_SEED,
        "model": model_name,
        "checkpoint_sha256": checkpoint_sha256,
        "analyzed_ledger_sha256": analyzed_ledger_sha256,
        "prediction_boxes_exposed_to_reviewer": False,
        "human_review_required": True,
        "db_write_count": 0,
        "r2_write_count": 0,
        "accepted_count": len(accepted),
        "shortfall": max(0, RESERVE_FRAME_TARGET - len(accepted)),
        "frames_per_source_cap": FRAMES_PER_SOURCE,
        "probe_frames_per_source": PROBE_FRAMES_PER_SOURCE,
        "safe_counts": {
            "analyzed_sources": len(analyzed_sources),
            "hp_classifier_sources": hp_classifier_source_count,
            "accepted_sources": len(accepted_sources),
            "accepted_frames": len(accepted),
            "shortfall": max(0, RESERVE_FRAME_TARGET - len(accepted)),
            "exact_sha_rejected": int(rejection_counts.get("exact_sha", 0)),
            "dhash_rejected": int(rejection_counts.get("dhash", 0)),
            "unreadable_rejected": int(rejection_counts.get("unreadable", 0)),
        },
        "probe_extraction_counts": extraction_totals,
        "provenance": {
            "inventory_summary_sha256": inventory_summary_sha256,
            "probe_sources_sha256": probe_sources_sha256,
            "source_provenance_sha256": dict(source_provenance_sha256),
            "excluded_source_refs_sha256": excluded_source_refs_sha256,
            "parent_manifest_sha256": parent_manifest_sha256,
            "source_commit": source_commit,
            "code_sha256": code_sha256,
        },
        "frames": accepted,
    }


def analyze(args: argparse.Namespace) -> None:
    validate_cli_contract(args)
    validate_fresh_output(args.output, phase="analyze")
    _validate_source_commit(args.output / "code", args.expected_reserve_source_commit, "reserve")
    parent_payload, parent_frames = _parent_payload_for_inventory(args)
    if _sha256_file(args.model) != parent_payload.get("checkpoint_sha256"):
        raise ValueError("reserve model checkpoint differs from parent")

    probe_payload = _read_pinned_json(
        args.output / "probe-sources.private.json",
        args.expected_probe_sources_sha256,
        "reserve probe sources",
    )
    excluded_refs, source_provenance_sha256 = load_required_source_exclusions(
        _required_source_ledger_pins(args)
    )
    downloaded_sources = validate_reserve_probe_payload(
        probe_payload,
        args.output / "inventory-selection.private.json",
        parent_frames=parent_frames,
        excluded_source_refs=excluded_refs,
        expected_source_provenance_sha256=source_provenance_sha256,
    )
    validate_downloaded_source_clips(
        downloaded_sources, args.output / "source-clips"
    )

    import cv2
    from ultralytics import YOLO

    existing_hashes = _load_image_hashes(
        [args.existing_images, args.parent / "review-frames"]
    )
    parent_refs = {str(frame["source_ref"]) for frame in parent_frames}
    probe_dir = args.output / "probe-frames"
    review_dir = args.output / "review-frames"
    probe_dir.mkdir()
    review_dir.mkdir()
    model = YOLO(str(args.model))
    analyzed: list[dict[str, object]] = []
    paths_by_source: dict[str, dict[int, Path]] = {}
    for ordinal, source in enumerate(downloaded_sources, start=1):
        source_ref = str(source["source_ref"])
        if source_ref in parent_refs:
            raise ValueError("reserve inventory reuses a parent source")
        capture = cv2.VideoCapture(str(args.output / "source-clips" / source["local_name"]))
        try:
            frames, probes, extraction = _extract_probes(
                capture,
                cv2=cv2,
                source_ordinal=ordinal,
                probe_dir=probe_dir,
                count=args.probe_frames_per_source,
            )
        finally:
            capture.release()
        if frames:
            predictions = model.predict(
                source=frames,
                imgsz=args.imgsz,
                conf=args.inference_conf,
                device=args.device,
                verbose=False,
            )
            for probe, prediction in zip(probes, predictions, strict=True):
                confidences = prediction.boxes.conf.tolist() if prediction.boxes is not None else []
                probe["detection_count"] = len(confidences)
                probe["max_conf"] = max(confidences, default=0.0)
        paths_by_source[source_ref] = {
            int(probe["probe_index"]): probe_dir / str(probe["local_name"])
            for probe in probes
        }
        analyzed.append(
            {
                **source,
                "yolo_max_conf": max((float(probe["max_conf"]) for probe in probes), default=0.0),
                "yolo_detection_count": max(
                    (int(probe["detection_count"]) for probe in probes), default=0
                ),
                "probe_extraction": extraction,
                "probes": [
                    {key: probe[key] for key in ("probe_index", "frame_index", "detection_count", "max_conf")}
                    for probe in probes
                ],
            }
        )
    analyzed_path = args.output / "analyzed-sources.private.json"
    _write_private_json(
        analyzed_path,
        {
            "schema": "yolo26n-v22-hp-reserve-analyzed-v1",
            "seed": args.seed,
            "model": args.model.name,
            "imgsz": args.imgsz,
            "inference_conf": args.inference_conf,
            "probe_frames_per_source": args.probe_frames_per_source,
            "db_write_count": 0,
            "r2_write_count": 0,
            "sources": analyzed,
        },
    )

    accepted: list[dict[str, object]] = []
    source_dhashes: dict[str, set[int]] = {}
    rejection_counts: Counter[str] = Counter()
    ranked_sources = sorted(
        (row for row in analyzed if classify_v22_candidate(row) == "hard_positive"),
        key=lambda row: (_seed_rank(args.seed, "reserve-analyzed-source", row["source_ref"]), str(row["source_ref"])),
    )
    for source in ranked_sources:
        source_ref = str(source["source_ref"])
        ranked_probes = choose_review_probe_indices(
            source["probes"], "hard_positive", count=len(source["probes"])
        )
        for probe_index in ranked_probes:
            if sum(frame["source_ref"] == source_ref for frame in accepted) >= FRAMES_PER_SOURCE:
                break
            path = paths_by_source[source_ref].get(probe_index)
            if path is None:
                rejection_counts["unreadable"] += 1
                continue
            image = cv2.imread(str(path))
            if image is None:
                rejection_counts["unreadable"] += 1
                continue
            image_sha = _sha256_file(path)
            if image_sha in existing_hashes:
                rejection_counts["exact_sha"] += 1
                continue
            digest = _dhash(image, cv2)
            current = source_dhashes.setdefault(source_ref, set())
            if _near_duplicate(digest, current):
                rejection_counts["dhash"] += 1
                continue
            existing_hashes.add(image_sha)
            current.add(digest)
            probe = next(row for row in source["probes"] if int(row["probe_index"]) == probe_index)
            accepted.append(
                {
                    "local_name": "",
                    "source_ref": source_ref,
                    "camera_id": source["camera_id"],
                    "camera_night": source["camera_night"],
                    "candidate_bucket": "hard_positive",
                    "probe_index": probe_index,
                    "frame_index": int(probe["frame_index"]),
                    "image_sha256": image_sha,
                    "dhash": digest,
                    "_probe_path": str(path),
                }
            )
    for ordinal, frame in enumerate(accepted, start=1):
        local_name = f"R{ordinal:04d}.jpg"
        shutil.copyfile(str(frame.pop("_probe_path")), review_dir / local_name)
        frame["local_name"] = local_name
    manifest = build_reserve_manifest(
        accepted_frames=accepted,
        analyzed_sources=analyzed,
        hp_classifier_source_count=len(ranked_sources),
        rejection_counts=rejection_counts,
        model_name=args.model.name,
        checkpoint_sha256=_sha256_file(args.model),
        analyzed_ledger_sha256=_sha256_file(analyzed_path),
        inventory_summary_sha256=str(probe_payload["inventory_summary_sha256"]),
        probe_sources_sha256=args.expected_probe_sources_sha256,
        source_provenance_sha256=source_provenance_sha256,
        excluded_source_refs_sha256=source_ref_set_sha256(excluded_refs),
        parent_manifest_sha256=args.expected_parent_manifest_sha256,
        source_commit=args.expected_reserve_source_commit,
        code_sha256=_code_sha256(
            args.output / "code", "run_yolo26n_v22_hp_reserve_merge.py"
        ),
    )
    status = str(manifest["status"])
    _write_private_json(args.output / "reserve-manifest.private.json", manifest)
    print(json.dumps({"status": status, "accepted": len(accepted)}, sort_keys=True))
    if status != "V22_HP_RESERVE_READY":
        raise SystemExit(status)


def validate_cli_contract(args: argparse.Namespace) -> None:
    mismatches: list[str] = []
    try:
        _require_exact_path(args.parent, PARENT_OUTPUT_DIR, "--parent")
        _require_digest(args.expected_parent_manifest_sha256, "parent manifest sha256")
        _require_digest(
            args.expected_parent_review_index_sha256,
            "parent review-index sha256",
        )
        _require_digest(args.expected_reserve_source_commit, "reserve source commit", length=40)
    except ValueError as exc:
        mismatches.append(str(exc))
    if args.seed != APPROVED_SEED:
        mismatches.append(f"--seed={args.seed}")
    if args.phase in {"inventory", "analyze"}:
        try:
            _require_exact_path(args.output, RESERVE_OUTPUT_DIR, "--output")
        except ValueError as exc:
            mismatches.append(str(exc))
    if args.phase == "inventory":
        expected = {
            "probe_hard_positive_sources": RESERVE_SOURCE_QUOTA,
            "probe_hard_negative_sources": 0,
            "inventory_max_sources": RESERVE_SOURCE_QUOTA,
            "probe_max_sources_per_night": MAX_RESERVE_SOURCES_PER_NIGHT,
            "probe_frames_per_source": PROBE_FRAMES_PER_SOURCE,
        }
        for name, value in expected.items():
            if getattr(args, name) != value:
                mismatches.append(f"--{name.replace('_', '-')}={getattr(args, name)}")
        try:
            if _canonical_cutoff(args.cutoff) != APPROVED_CUTOFF:
                mismatches.append(f"--cutoff={args.cutoff}")
            for actual, expected_path, label in (
                (args.dataset_v21_provenance, DATASET_V21_PROVENANCE, "--dataset-v21-provenance"),
                (args.v1_provenance, V1_PROVENANCE, "--v1-provenance"),
                (args.v1_probe_sources, V1_PROBE_SOURCES, "--v1-probe-sources"),
                (args.v2_provenance, V2_PROVENANCE, "--v2-provenance"),
                (args.v2_probe_sources, V2_PROBE_SOURCES, "--v2-probe-sources"),
                (args.v3_probe_sources, V3_PROBE_SOURCES, "--v3-probe-sources"),
                (
                    args.v3_analyzed_sources,
                    V3_ANALYZED_SOURCES,
                    "--v3-analyzed-sources",
                ),
            ):
                _require_exact_path(actual, expected_path, label)
            for value, label in (
                (args.dataset_v21_provenance_sha256, "dataset v2.1 provenance sha256"),
                (args.v1_provenance_sha256, "v1 provenance sha256"),
                (args.v1_probe_sources_sha256, "v1 probe sources sha256"),
                (args.v2_provenance_sha256, "v2 provenance sha256"),
                (args.v2_probe_sources_sha256, "v2 probe sources sha256"),
                (args.v3_probe_sources_sha256, "v3 probe sources sha256"),
                (args.v3_analyzed_sources_sha256, "v3 analyzed sources sha256"),
            ):
                _require_digest(value, label)
        except ValueError as exc:
            mismatches.append(str(exc))
    elif args.phase == "analyze":
        expected = {
            "probe_frames_per_source": PROBE_FRAMES_PER_SOURCE,
            "review_frames_per_source": FRAMES_PER_SOURCE,
            "imgsz": APPROVED_IMGSZ,
            "inference_conf": APPROVED_INFERENCE_CONF,
        }
        for name, value in expected.items():
            if getattr(args, name) != value:
                mismatches.append(f"--{name.replace('_', '-')}={getattr(args, name)}")
        try:
            _require_exact_path(args.existing_images, DATASET_V21_IMAGES_DIR, "--existing-images")
            for actual, expected_path, label in (
                (args.dataset_v21_provenance, DATASET_V21_PROVENANCE, "--dataset-v21-provenance"),
                (args.v1_provenance, V1_PROVENANCE, "--v1-provenance"),
                (args.v1_probe_sources, V1_PROBE_SOURCES, "--v1-probe-sources"),
                (args.v2_provenance, V2_PROVENANCE, "--v2-provenance"),
                (args.v2_probe_sources, V2_PROBE_SOURCES, "--v2-probe-sources"),
                (args.v3_probe_sources, V3_PROBE_SOURCES, "--v3-probe-sources"),
                (
                    args.v3_analyzed_sources,
                    V3_ANALYZED_SOURCES,
                    "--v3-analyzed-sources",
                ),
            ):
                _require_exact_path(actual, expected_path, label)
            for value, label in (
                (args.dataset_v21_provenance_sha256, "dataset v2.1 provenance sha256"),
                (args.v1_provenance_sha256, "v1 provenance sha256"),
                (args.v1_probe_sources_sha256, "v1 probe sources sha256"),
                (args.v2_provenance_sha256, "v2 provenance sha256"),
                (args.v2_probe_sources_sha256, "v2 probe sources sha256"),
                (args.v3_probe_sources_sha256, "v3 probe sources sha256"),
                (args.v3_analyzed_sources_sha256, "v3 analyzed sources sha256"),
                (args.expected_probe_sources_sha256, "reserve probe sources sha256"),
            ):
                _require_digest(value, label)
        except ValueError as exc:
            mismatches.append(str(exc))
    else:
        try:
            _require_exact_path(args.output, MERGED_OUTPUT_DIR, "--output")
            _require_exact_path(args.reserve, RESERVE_OUTPUT_DIR, "--reserve")
            _require_digest(args.expected_reserve_manifest_sha256, "reserve manifest sha256")
        except ValueError as exc:
            mismatches.append(str(exc))
        if args.reserve_hard_positive_frames != RESERVE_FRAME_TARGET:
            mismatches.append(f"--reserve-hard-positive-frames={args.reserve_hard_positive_frames}")
        if args.final_hard_positive_frames != FINAL_BUCKET_COUNTS["hard_positive"]:
            mismatches.append(f"--final-hard-positive-frames={args.final_hard_positive_frames}")
        if args.final_hard_negative_frames != FINAL_BUCKET_COUNTS["hard_negative"]:
            mismatches.append(f"--final-hard-negative-frames={args.final_hard_negative_frames}")
        if args.max_frames_per_source != FRAMES_PER_SOURCE:
            mismatches.append(f"--max-frames-per-source={args.max_frames_per_source}")
        if args.max_frames_per_night != MAX_FINAL_FRAMES_PER_NIGHT:
            mismatches.append(f"--max-frames-per-night={args.max_frames_per_night}")
    if mismatches:
        raise ValueError("unsafe Task4b CLI contract: " + ", ".join(mismatches))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("inventory", "analyze", "merge"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--seed", default=APPROVED_SEED)
    parser.add_argument("--expected-parent-manifest-sha256", required=True)
    parser.add_argument("--expected-parent-review-index-sha256", required=True)
    parser.add_argument("--expected-reserve-source-commit", required=True)
    parser.add_argument("--reporter-repo", type=Path)
    parser.add_argument("--cutoff", default=APPROVED_CUTOFF)
    parser.add_argument("--dataset-v21-provenance", type=Path)
    parser.add_argument("--dataset-v21-provenance-sha256")
    parser.add_argument("--v1-provenance", type=Path)
    parser.add_argument("--v1-provenance-sha256")
    parser.add_argument("--v1-probe-sources", type=Path)
    parser.add_argument("--v1-probe-sources-sha256")
    parser.add_argument("--v2-provenance", type=Path)
    parser.add_argument("--v2-provenance-sha256")
    parser.add_argument("--v2-probe-sources", type=Path)
    parser.add_argument("--v2-probe-sources-sha256")
    parser.add_argument("--v3-probe-sources", type=Path)
    parser.add_argument("--v3-probe-sources-sha256")
    parser.add_argument("--v3-analyzed-sources", type=Path)
    parser.add_argument("--v3-analyzed-sources-sha256")
    parser.add_argument("--existing-images", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--reserve", type=Path)
    parser.add_argument("--expected-reserve-manifest-sha256")
    parser.add_argument("--expected-probe-sources-sha256")
    parser.add_argument("--probe-hard-positive-sources", type=int, default=RESERVE_SOURCE_QUOTA)
    parser.add_argument("--probe-hard-negative-sources", type=int, default=0)
    parser.add_argument("--inventory-max-sources", type=int, default=RESERVE_SOURCE_QUOTA)
    parser.add_argument(
        "--probe-max-sources-per-night", type=int, default=MAX_RESERVE_SOURCES_PER_NIGHT
    )
    parser.add_argument("--probe-frames-per-source", type=int, default=PROBE_FRAMES_PER_SOURCE)
    parser.add_argument("--review-frames-per-source", type=int, default=FRAMES_PER_SOURCE)
    parser.add_argument("--imgsz", type=int, default=APPROVED_IMGSZ)
    parser.add_argument("--inference-conf", type=float, default=APPROVED_INFERENCE_CONF)
    parser.add_argument("--device", default="mps")
    parser.add_argument("--reserve-hard-positive-frames", type=int, default=RESERVE_FRAME_TARGET)
    parser.add_argument(
        "--final-hard-positive-frames", type=int, default=FINAL_BUCKET_COUNTS["hard_positive"]
    )
    parser.add_argument(
        "--final-hard-negative-frames", type=int, default=FINAL_BUCKET_COUNTS["hard_negative"]
    )
    parser.add_argument("--max-frames-per-source", type=int, default=FRAMES_PER_SOURCE)
    parser.add_argument("--max-frames-per-night", type=int, default=MAX_FINAL_FRAMES_PER_NIGHT)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        validate_cli_contract(args)
        validate_fresh_output(args.output, phase=args.phase)
    except ValueError as exc:
        parser.error(str(exc))
    if args.phase == "inventory":
        inventory(args)
    elif args.phase == "analyze":
        analyze(args)
    else:
        result = merge_artifacts(
            parent=args.parent,
            reserve=args.reserve,
            output=args.output,
            expected_parent_manifest_sha256=args.expected_parent_manifest_sha256,
            expected_parent_review_index_sha256=args.expected_parent_review_index_sha256,
            expected_reserve_manifest_sha256=args.expected_reserve_manifest_sha256,
            expected_reserve_source_commit=args.expected_reserve_source_commit,
            seed=args.seed,
        )
        print(json.dumps({"status": result["status"], "review_frames": 320}, sort_keys=True))


if __name__ == "__main__":
    main()
