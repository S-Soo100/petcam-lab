"""Build a leakage-safe YOLO26n v2.6.1 grouped dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zipfile import ZipFile

GT_SCHEMA = "yolo26n-v261-final-human-gt-v1"
GT_STATUS = "V261_HUMAN_GT_READY"
SOURCE_SCHEMA = "yolo26n-v261-development-sources-v1"
PARENT_SCHEMA = "yolo26n-owner-dataset-v26"
PARENT_STATUS = "V26_DATASET_READY"
SPLIT_SCHEMA = "yolo26n-v261-group-split-plan-v1"
SPLIT_STATUS = "V261_GROUP_SPLIT_READY"
DATASET_SCHEMA = "yolo26n-owner-dataset-v261"
DATASET_STATUS = "V261_DATASET_READY"
SPLIT_SEED = "yolo26n-v261-group-split-v1"


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return value


def _write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
    os.chmod(path, 0o600)


def _secure_tree(root: Path) -> None:
    for path in root.rglob("*"):
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
    os.chmod(root, 0o700)


def _write_json_new(path: Path, value: Mapping[str, Any]) -> None:
    _write_new(
        path,
        (
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode(),
    )


def _object_digest(value: Mapping[str, Any]) -> str:
    return _sha_bytes(
        (
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode()
    )


def _parse_instant(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("source started_at must be an ISO instant")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("source started_at must include timezone")
    return parsed


def _validate_inputs(
    final_gt: Mapping[str, Any],
    development_sources: Mapping[str, Any],
    parent_manifest: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if final_gt.get("schema") != GT_SCHEMA or final_gt.get("status") != GT_STATUS:
        raise ValueError("human GT is not ready")
    if development_sources.get("schema") != SOURCE_SCHEMA:
        raise ValueError("invalid development source manifest")
    if (
        parent_manifest.get("schema") != PARENT_SCHEMA
        or parent_manifest.get("status") != PARENT_STATUS
    ):
        raise ValueError("parent v2.6 dataset is not ready")
    gt_records = final_gt.get("records")
    source_records = development_sources.get("records")
    parent_records = parent_manifest.get("records")
    if not all(
        isinstance(value, list)
        for value in (gt_records, source_records, parent_records)
    ):
        raise ValueError("input records must be lists")
    if not all(
        isinstance(row, dict) for row in gt_records + source_records + parent_records
    ):
        raise ValueError("input record must be an object")
    return gt_records, source_records, parent_records


def _episode_by_clip(source_records: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    by_camera: dict[str, list[tuple[datetime, datetime, str]]] = defaultdict(list)
    seen: set[str] = set()
    for row in source_records:
        clip = row.get("clip_ref")
        camera = row.get("camera_ref")
        duration = row.get("duration_sec")
        if not isinstance(clip, str) or not clip or clip in seen:
            raise ValueError("invalid or duplicate development clip")
        if not isinstance(camera, str) or not camera:
            raise ValueError("invalid development camera")
        if (
            not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or duration <= 0
        ):
            raise ValueError("invalid source duration")
        start = _parse_instant(row.get("started_at"))
        by_camera[camera].append(
            (start, start + timedelta(seconds=float(duration)), clip)
        )
        seen.add(clip)

    result: dict[str, str] = {}
    for camera, rows in by_camera.items():
        rows.sort()
        component: list[str] = []
        component_end: datetime | None = None
        groups: list[list[str]] = []
        for start, end, clip in rows:
            if component_end is None or start > component_end + timedelta(seconds=60):
                if component:
                    groups.append(component)
                component = [clip]
                component_end = end
            else:
                component.append(clip)
                component_end = max(component_end, end)
        if component:
            groups.append(component)
        for clips in groups:
            token = hashlib.sha256(
                f"{SPLIT_SEED}\0{camera}\0{'\0'.join(sorted(clips))}".encode()
            ).hexdigest()[:24]
            episode = f"ep-{token}"
            result.update({clip: episode for clip in clips})
    return result


def _assign_splits(groups: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, str]:
    if not groups:
        raise ValueError("no eligible human GT")
    if len(groups) == 1:
        raise ValueError("at least two episode groups are required")
    total = sum(len(rows) for rows in groups.values())
    target = total * 0.20
    ranked = sorted(
        groups,
        key=lambda episode: hashlib.sha256(
            f"{SPLIT_SEED}\0{episode}".encode()
        ).hexdigest(),
    )
    strata_by_episode = {
        episode: {(str(row["camera_night"]), str(row["state"])) for row in rows}
        for episode, rows in groups.items()
    }
    episodes_by_stratum: dict[tuple[str, str], set[str]] = defaultdict(set)
    for episode, strata in strata_by_episode.items():
        for stratum in strata:
            episodes_by_stratum[stratum].add(episode)
    required_strata = {
        stratum
        for stratum, episodes in episodes_by_stratum.items()
        if len(episodes) >= 2
    }
    selected: set[str] = set()
    count = 0
    for stratum in sorted(required_strata):
        if any(stratum in strata_by_episode[episode] for episode in selected):
            continue
        candidates = [
            episode
            for episode in ranked
            if episode in episodes_by_stratum[stratum]
            and all(
                len(episodes_by_stratum[other] - selected - {episode}) >= 1
                for other in strata_by_episode[episode] & required_strata
            )
        ]
        if not candidates:
            raise ValueError(
                "cannot preserve camera-night/state coverage across splits"
            )
        chosen = candidates[0]
        selected.add(chosen)
        count += len(groups[chosen])
    for episode in ranked:
        if episode in selected:
            continue
        size = len(groups[episode])
        preserves_train = all(
            len(episodes_by_stratum[stratum] - selected - {episode}) >= 1
            for stratum in strata_by_episode[episode] & required_strata
        )
        if preserves_train and (
            not selected or abs((count + size) - target) <= abs(count - target)
        ):
            selected.add(episode)
            count += size
    if not selected or len(selected) == len(groups):
        raise ValueError("cannot produce non-empty train and validation episode splits")
    return {episode: "val" if episode in selected else "train" for episode in groups}


def _near_duplicate_split_groups(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    """Merge episode groups that cannot safely cross the split boundary."""

    episodes = {str(row["episode_id"]) for row in rows}
    parent = {episode: episode for episode in episodes}

    def find(episode: str) -> str:
        while parent[episode] != episode:
            parent[episode] = parent[parent[episode]]
            episode = parent[episode]
        return episode

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    by_night: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_night[str(row["camera_night"])].append(row)
    for night_rows in by_night.values():
        night_rows.sort(key=lambda row: str(row["absolute_timestamp"]))
        for left_index, left in enumerate(night_rows):
            left_time = _parse_instant(left["absolute_timestamp"])
            left_dhash = _parse_dhash(left.get("dhash64"), required=True)
            assert left_dhash is not None
            for right in night_rows[left_index + 1 :]:
                right_time = _parse_instant(right["absolute_timestamp"])
                if (right_time - left_time).total_seconds() > 300:
                    break
                right_dhash = _parse_dhash(right.get("dhash64"), required=True)
                assert right_dhash is not None
                if (left_dhash ^ right_dhash).bit_count() <= 8:
                    union(str(left["episode_id"]), str(right["episode_id"]))

    components: dict[str, list[str]] = defaultdict(list)
    for episode in sorted(episodes):
        components[find(episode)].append(episode)
    result: dict[str, str] = {}
    for members in components.values():
        token = hashlib.sha256(
            f"{SPLIT_SEED}\0near-duplicate\0{'\0'.join(members)}".encode()
        ).hexdigest()[:24]
        result.update({episode: f"sg-{token}" for episode in members})
    return result


def _parse_dhash(value: object, *, required: bool) -> int | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or len(value) != 16:
        message = "dHash is required" if value is None else "invalid dHash"
        raise ValueError(message)
    try:
        return int(value, 16)
    except ValueError as exc:
        raise ValueError("invalid dHash") from exc


def build_group_split(
    *,
    final_gt: Mapping[str, Any],
    development_sources: Mapping[str, Any],
    parent_manifest: Mapping[str, Any],
    protected_image_sha256: set[str] | None = None,
    protected_dhash_by_source: Mapping[str, set[str]] | None = None,
    future_clip_refs: set[str] | None = None,
    input_lineage: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    gt_records, source_records, parent_records = _validate_inputs(
        final_gt, development_sources, parent_manifest
    )
    protected = protected_image_sha256 or set()
    protected_dhash_values = {
        source: {
            parsed
            for parsed in (_parse_dhash(item, required=True) for item in fingerprints)
            if parsed is not None
        }
        for source, fingerprints in (protected_dhash_by_source or {}).items()
    }
    future = future_clip_refs or set()
    episode_by_clip = _episode_by_clip(source_records)
    source_by_clip = {str(row["clip_ref"]): row for row in source_records}
    parent_train_sha = {
        row.get("image_sha256") for row in parent_records if row.get("split") == "train"
    }
    parent_split_counts = Counter(
        str(row.get("split")) for row in parent_records if row.get("split") != "train"
    )

    eligible: list[dict[str, Any]] = []
    excluded = Counter()
    seen_images: set[str] = set()
    for raw in gt_records:
        row = dict(raw)
        clip = row.get("clip_ref")
        image_sha = row.get("image_sha256")
        state = row.get("state")
        if not isinstance(clip, str) or clip not in episode_by_clip:
            raise ValueError("human GT source is not in development manifest")
        if clip in future:
            raise ValueError("future holdout overlap")
        if not isinstance(image_sha, str) or len(image_sha) != 64:
            raise ValueError("invalid human GT image SHA")
        dhash_value = _parse_dhash(row.get("dhash64"), required=True)
        if image_sha in protected:
            raise ValueError("protected image overlap")
        protected_for_source = protected_dhash_values.get(clip, set())
        if any(
            (dhash_value ^ protected_dhash).bit_count() <= 2
            for protected_dhash in protected_for_source
        ):
            raise ValueError("protected near-duplicate overlap")
        if image_sha in parent_train_sha:
            raise ValueError("v2.6 train image overlap")
        if image_sha in seen_images:
            raise ValueError("duplicate human GT image")
        seen_images.add(image_sha)
        if state in {"uncertain", "media_error"}:
            excluded[str(state)] += 1
            continue
        if state not in {"gecko_present", "gecko_absent"}:
            raise ValueError("invalid human GT state")
        if state == "gecko_present" and not row.get("boxes_yolo"):
            raise ValueError("positive image lacks a box")
        if state == "gecko_absent" and row.get("boxes_yolo"):
            raise ValueError("negative image contains a box")
        source = source_by_clip[clip]
        if row.get("camera_ref") != source.get("camera_ref") or row.get(
            "camera_night"
        ) != source.get("camera_night"):
            raise ValueError("human GT source metadata mismatch")
        timestamp = row.get("timestamp_sec")
        if (
            not isinstance(timestamp, (int, float))
            or isinstance(timestamp, bool)
            or timestamp < 0
        ):
            raise ValueError("invalid human GT timestamp")
        row["absolute_timestamp"] = (
            _parse_instant(source.get("started_at"))
            + timedelta(seconds=float(timestamp))
        ).isoformat()
        row["episode_id"] = episode_by_clip[clip]
        eligible.append(row)

    split_group_by_episode = _near_duplicate_split_groups(eligible)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in eligible:
        groups[split_group_by_episode[row["episode_id"]]].append(row)
    split_by_group = _assign_splits(groups)
    records: list[dict[str, Any]] = []
    for row in eligible:
        normalized = dict(row)
        split_group = split_group_by_episode[row["episode_id"]]
        normalized["split_group_id"] = split_group
        normalized["split"] = split_by_group[split_group]
        records.append(normalized)
    records.sort(key=lambda row: row["blind_name"])

    train_episodes = {row["episode_id"] for row in records if row["split"] == "train"}
    val_episodes = {row["episode_id"] for row in records if row["split"] == "val"}
    if train_episodes & val_episodes:
        raise ValueError("episode group leakage")
    by_night: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        dhash = row.get("dhash64")
        _parse_dhash(dhash, required=True)
        by_night[str(row["camera_night"])].append(row)
    for night_rows in by_night.values():
        night_rows.sort(key=lambda row: row["absolute_timestamp"])
        for left_index, left in enumerate(night_rows):
            left_time = _parse_instant(left["absolute_timestamp"])
            for right in night_rows[left_index + 1 :]:
                right_time = _parse_instant(right["absolute_timestamp"])
                if (right_time - left_time).total_seconds() > 300:
                    break
                distance = (
                    int(left["dhash64"], 16) ^ int(right["dhash64"], 16)
                ).bit_count()
                if distance <= 8 and left["split"] != right["split"]:
                    raise ValueError("near-duplicate split leakage")
    split_counts = Counter(row["split"] for row in records)
    state_counts = Counter((row["split"], row["state"]) for row in records)
    return {
        "schema": SPLIT_SCHEMA,
        "status": SPLIT_STATUS,
        "seed": SPLIT_SEED,
        "input_lineage": dict(sorted((input_lineage or {}).items())),
        "records": records,
        "split_counts": dict(sorted(split_counts.items())),
        "split_state_counts": {
            f"{split}:{state}": count
            for (split, state), count in sorted(state_counts.items())
        },
        "episode_count": len({row["episode_id"] for row in records}),
        "split_group_count": len(groups),
        "parent_replay_count": sum(
            row.get("split") == "train" for row in parent_records
        ),
        "parent_excluded_split_counts": dict(sorted(parent_split_counts.items())),
        "excluded_counts": {
            "uncertain": excluded["uncertain"],
            "media_error": excluded["media_error"],
        },
    }


def _parent_file(root: Path, relative: object, *, label: str) -> Path:
    if not isinstance(relative, str):
        raise TypeError(f"missing parent {label} path")
    path = (root / relative).resolve()
    if root.resolve() not in path.parents:
        raise ValueError(f"parent {label} path escapes dataset")
    return path


def _queue_images(queue_root: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for path in sorted(queue_root.glob("cvat-upload-part-*.zip")):
        with ZipFile(path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                name = Path(member.filename).name
                if name in result:
                    raise ValueError("duplicate queue image")
                result[name] = archive.read(member)
    if not result:
        raise ValueError("queue contains no images")
    return result


def _label_bytes(boxes: object) -> bytes:
    if not isinstance(boxes, list):
        raise TypeError("boxes_yolo must be a list")
    lines: list[str] = []
    for box in boxes:
        if not isinstance(box, list) or len(box) != 5 or box[0] != 0:
            raise ValueError("invalid YOLO box")
        values = [float(value) for value in box[1:]]
        if (
            not all(0 <= value <= 1 for value in values)
            or values[2] <= 0
            or values[3] <= 0
            or values[0] - values[2] / 2 < 0
            or values[0] + values[2] / 2 > 1
            or values[1] - values[3] / 2 < 0
            or values[1] + values[3] / 2 > 1
        ):
            raise ValueError("invalid normalized YOLO box")
        lines.append("0 " + " ".join(f"{value:.10f}" for value in values))
    return (("\n".join(lines) + "\n") if lines else "").encode()


def materialize_dataset(
    *,
    final_gt: Mapping[str, Any],
    split_plan: Mapping[str, Any],
    expected_split_sha256: str,
    development_sources: Mapping[str, Any],
    parent_manifest: Mapping[str, Any],
    protected_image_sha256: set[str],
    protected_dhash_by_source: Mapping[str, set[str]],
    future_clip_refs: set[str],
    input_lineage: Mapping[str, str],
    parent_dataset_root: Path,
    queue_root: Path,
    output_root: Path,
    source_commit: str,
    lineage: Mapping[str, str],
) -> dict[str, Any]:
    if output_root.exists():
        raise FileExistsError(output_root)
    if len(source_commit) != 40 or any(
        character not in "0123456789abcdef" for character in source_commit
    ):
        raise ValueError("source commit must be a 40-character lowercase SHA")
    if (
        split_plan.get("schema") != SPLIT_SCHEMA
        or split_plan.get("status") != SPLIT_STATUS
    ):
        raise ValueError("group split is not ready")
    if _object_digest(split_plan) != expected_split_sha256:
        raise ValueError("approved split SHA mismatch")
    rebuilt_split = build_group_split(
        final_gt=final_gt,
        development_sources=development_sources,
        parent_manifest=parent_manifest,
        protected_image_sha256=protected_image_sha256,
        protected_dhash_by_source=protected_dhash_by_source,
        future_clip_refs=future_clip_refs,
        input_lineage=input_lineage,
    )
    if rebuilt_split != split_plan:
        raise ValueError("approved split does not match rebuilt source contract")
    gt_records, _, parent_records = _validate_inputs(
        final_gt, development_sources, parent_manifest
    )
    gt_by_name = {row.get("blind_name"): row for row in gt_records}
    split_records = split_plan.get("records")
    if not isinstance(split_records, list):
        raise TypeError("split records must be a list")
    queue_images = _queue_images(queue_root)

    output_root.mkdir(mode=0o700)
    manifest_records: list[dict[str, Any]] = []
    seen_sha: set[str] = set()
    parent_index = 0
    for row in parent_records:
        if row.get("split") != "train":
            continue
        parent_index += 1
        source_image = _parent_file(
            parent_dataset_root, row.get("image_path"), label="image"
        )
        source_label = _parent_file(
            parent_dataset_root, row.get("label_path"), label="label"
        )
        if _sha(source_image) != row.get("image_sha256") or _sha(
            source_label
        ) != row.get("label_sha256"):
            raise ValueError("parent dataset byte drift")
        suffix = source_image.suffix.lower() or ".jpg"
        image_relative = Path("images/train") / f"P{parent_index:07d}{suffix}"
        label_relative = Path("labels/train") / f"P{parent_index:07d}.txt"
        image_bytes = source_image.read_bytes()
        label_bytes = source_label.read_bytes()
        _write_new(output_root / image_relative, image_bytes)
        _write_new(output_root / label_relative, label_bytes)
        seen_sha.add(str(row["image_sha256"]))
        manifest_records.append(
            {
                "origin": "v26-replay",
                "split": "train",
                "image_path": str(image_relative),
                "label_path": str(label_relative),
                "image_sha256": row["image_sha256"],
                "label_sha256": row["label_sha256"],
                "positive": bool(row.get("positive")),
                "box_count": int(row.get("box_count", 0)),
            }
        )

    new_index = 0
    for split_row in split_records:
        name = split_row.get("blind_name")
        gt = gt_by_name.get(name)
        if not isinstance(name, str) or gt is None:
            raise ValueError("split row is not bound to final GT")
        if any(
            split_row.get(key) != gt.get(key)
            for key in ("image_sha256", "state", "boxes_yolo")
        ):
            raise ValueError("split/final GT mismatch")
        split = split_row.get("split")
        if split not in {"train", "val"}:
            raise ValueError("invalid active split")
        image_bytes = queue_images.get(name)
        if image_bytes is None or _sha_bytes(image_bytes) != gt.get("image_sha256"):
            raise ValueError("queue image does not match human GT")
        if gt["image_sha256"] in seen_sha:
            raise ValueError("dataset exact image overlap")
        seen_sha.add(gt["image_sha256"])
        new_index += 1
        suffix = Path(name).suffix.lower() or ".jpg"
        stem = f"N{new_index:07d}"
        image_relative = Path(f"images/{split}") / f"{stem}{suffix}"
        label_relative = Path(f"labels/{split}") / f"{stem}.txt"
        label_bytes = _label_bytes(gt["boxes_yolo"])
        _write_new(output_root / image_relative, image_bytes)
        _write_new(output_root / label_relative, label_bytes)
        manifest_records.append(
            {
                "origin": "v261-human-gt",
                "split": split,
                "image_path": str(image_relative),
                "label_path": str(label_relative),
                "image_sha256": gt["image_sha256"],
                "label_sha256": _sha_bytes(label_bytes),
                "positive": gt["state"] == "gecko_present",
                "state": gt["state"],
                "box_count": len(gt["boxes_yolo"]),
                "episode_id": split_row["episode_id"],
                "camera_night": gt.get("camera_night"),
            }
        )

    yaml = f"path: {output_root.resolve()}\ntrain: images/train\nval: images/val\nnames:\n  0: gecko\n"
    _write_new(output_root / "data.yaml", yaml.encode())
    counts = Counter(row["split"] for row in manifest_records)
    manifest = {
        "schema": DATASET_SCHEMA,
        "status": DATASET_STATUS,
        "source_commit": source_commit,
        "lineage": dict(sorted(lineage.items())),
        "records": manifest_records,
        "image_count": len(manifest_records),
        "active_split_counts": dict(sorted(counts.items())),
        "parent_train_count": parent_index,
        "new_image_count": new_index,
        "data_yaml_sha256": _sha(output_root / "data.yaml"),
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "deploy_count": 0,
        "future_holdout_access_count": 0,
    }
    _write_json_new(output_root / "manifest.private.json", manifest)
    _secure_tree(output_root)
    return manifest


def _collect_hashes(value: object, *, key: str = "") -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        for child_key, child in value.items():
            result.update(_collect_hashes(child, key=str(child_key)))
    elif isinstance(value, list):
        for child in value:
            result.update(_collect_hashes(child, key=key))
    elif (
        key in {"image_sha256", "sha256"}
        and isinstance(value, str)
        and len(value) == 64
    ):
        result.add(value)
    return result


def _collect_dhashes_by_source(value: object) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    if isinstance(value, dict):
        dhash = value.get("dhash64")
        if dhash is not None:
            _parse_dhash(dhash, required=True)
            source = value.get("clip_ref") or value.get("source_video_sha256")
            if not isinstance(source, str) or not source:
                raise ValueError("protected dHash lacks source identity")
            result[source].add(str(dhash))
        for child in value.values():
            nested = _collect_dhashes_by_source(child)
            for source, fingerprints in nested.items():
                result[source].update(fingerprints)
    elif isinstance(value, list):
        for child in value:
            nested = _collect_dhashes_by_source(child)
            for source, fingerprints in nested.items():
                result[source].update(fingerprints)
    return dict(result)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final-human-gt", type=Path, required=True)
    parser.add_argument("--review-index", type=Path, required=True)
    parser.add_argument("--source-plan-root", type=Path, required=True)
    parser.add_argument("--parent-dataset", type=Path, required=True)
    parser.add_argument("--split-output", type=Path)
    parser.add_argument("--split-input", type=Path)
    parser.add_argument("--protected-dataset-manifest", type=Path, required=True)
    parser.add_argument("--protected-selection-manifest", type=Path, required=True)
    parser.add_argument("--dataset-output", type=Path)
    parser.add_argument("--materialize", action="store_true")
    parser.add_argument("--source-commit")
    parser.add_argument("--approved-split-sha256")
    args = parser.parse_args(argv)

    final_gt = _load_object(args.final_human_gt, label="final human GT")
    review_index = _load_object(args.review_index, label="review index")
    export_freeze_path = args.final_human_gt.parent / "export-freeze.private.json"
    export_freeze = _load_object(export_freeze_path, label="export freeze")
    if final_gt.get("export_freeze_sha256") != _sha(export_freeze_path):
        raise ValueError("final GT/export freeze SHA mismatch")
    if export_freeze.get("review_index_sha256") != _sha(args.review_index):
        raise ValueError("export freeze/review index SHA mismatch")
    if review_index.get("schema") != "yolo26n-v261-blind-review-index-v1":
        raise ValueError("invalid review index schema")
    development = _load_object(
        args.source_plan_root / "development-sources.private.json",
        label="development sources",
    )
    future = _load_object(
        args.source_plan_root / "future-holdout.private.json", label="future holdout"
    )
    parent_manifest = _load_object(
        args.parent_dataset / "manifest.private.json", label="parent dataset"
    )
    protected_dataset = _load_object(
        args.protected_dataset_manifest, label="protected dataset manifest"
    )
    protected_selection = _load_object(
        args.protected_selection_manifest, label="protected selection manifest"
    )
    protected = _collect_hashes(protected_dataset) | _collect_hashes(
        protected_selection
    )
    protected_dhash = _collect_dhashes_by_source(protected_dataset)
    for source, fingerprints in _collect_dhashes_by_source(protected_selection).items():
        protected_dhash.setdefault(source, set()).update(fingerprints)
    if not protected:
        raise ValueError("protected fingerprints are empty")
    if not protected_dhash:
        raise ValueError("protected perceptual fingerprints are empty")
    future_records = future.get("records", [])
    future_refs = {
        row.get("clip_ref")
        for row in future_records
        if isinstance(row, dict) and isinstance(row.get("clip_ref"), str)
    }
    split_input_lineage = {
        "final_human_gt_sha256": _sha(args.final_human_gt),
        "review_index_sha256": _sha(args.review_index),
        "export_freeze_sha256": _sha(export_freeze_path),
        "development_sources_sha256": _sha(
            args.source_plan_root / "development-sources.private.json"
        ),
        "future_holdout_sha256": _sha(
            args.source_plan_root / "future-holdout.private.json"
        ),
        "parent_manifest_sha256": _sha(args.parent_dataset / "manifest.private.json"),
        "protected_dataset_manifest_sha256": _sha(args.protected_dataset_manifest),
        "protected_selection_manifest_sha256": _sha(args.protected_selection_manifest),
    }
    rebuilt_split = build_group_split(
        final_gt=final_gt,
        development_sources=development,
        parent_manifest=parent_manifest,
        protected_image_sha256=protected,
        protected_dhash_by_source=protected_dhash,
        future_clip_refs=future_refs,
        input_lineage=split_input_lineage,
    )

    if args.materialize:
        if (
            args.dataset_output is None
            or args.source_commit is None
            or args.split_input is None
            or args.approved_split_sha256 is None
        ):
            parser.error(
                "--materialize requires --split-input, --approved-split-sha256, "
                "--dataset-output and --source-commit"
            )
        split = _load_object(args.split_input, label="approved group split")
        split_sha = _sha(args.split_input)
        if split_sha != args.approved_split_sha256:
            raise ValueError("approved split external SHA mismatch")
        attempt_root = args.final_human_gt.resolve().parent.parent
        if args.dataset_output.resolve().parent != attempt_root:
            raise ValueError(
                "dataset output must be a direct child of the private attempt"
            )
        materialize_dataset(
            final_gt=final_gt,
            split_plan=split,
            expected_split_sha256=_object_digest(split),
            development_sources=development,
            parent_manifest=parent_manifest,
            protected_image_sha256=protected,
            protected_dhash_by_source=protected_dhash,
            future_clip_refs=future_refs,
            input_lineage=split_input_lineage,
            parent_dataset_root=args.parent_dataset,
            queue_root=args.final_human_gt.parent.parent / "blind-queue-v4",
            output_root=args.dataset_output,
            source_commit=args.source_commit,
            lineage={
                "final_human_gt_sha256": _sha(args.final_human_gt),
                "review_index_sha256": _sha(args.review_index),
                "development_sources_sha256": _sha(
                    args.source_plan_root / "development-sources.private.json"
                ),
                "future_holdout_sha256": _sha(
                    args.source_plan_root / "future-holdout.private.json"
                ),
                "parent_manifest_sha256": _sha(
                    args.parent_dataset / "manifest.private.json"
                ),
                "protected_dataset_manifest_sha256": _sha(
                    args.protected_dataset_manifest
                ),
                "protected_selection_manifest_sha256": _sha(
                    args.protected_selection_manifest
                ),
                "approved_group_split_sha256": args.approved_split_sha256,
                "export_freeze_sha256": _sha(export_freeze_path),
            },
        )
        print(DATASET_STATUS)
    else:
        if (
            args.split_output is None
            or args.split_input is not None
            or args.approved_split_sha256 is not None
        ):
            parser.error("dry-run requires --split-output and forbids --split-input")
        attempt_root = args.final_human_gt.resolve().parent.parent
        if args.split_output.resolve().parent.parent != attempt_root:
            raise ValueError(
                "split output must be inside the private attempt build root"
            )
        args.split_output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _write_json_new(args.split_output, rebuilt_split)
        print(SPLIT_STATUS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
