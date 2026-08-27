"""Build the immutable private v2.6 stratified selection manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import warnings

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.build_yolo26n_v26_recent_dense_queue import DenseFrame
from scripts.select_yolo26n_v26_stratified_queue import (
    StratifiedQueueContract,
    StratifiedSelection,
    select_stratified_queue,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ENRICHED_CLIP_FILES = frozenset({"ledger.jsonl", "completion.private.json"})


def build_selection_manifest(
    selection: StratifiedSelection,
    *,
    private_refs: dict[str, str],
    dense_lineage_sha256: str,
    protected_lineage_sha256: str,
    contract: StratifiedQueueContract,
) -> dict[str, object]:
    contract.validate()
    if _SHA256.fullmatch(dense_lineage_sha256) is None:
        raise ValueError("dense lineage SHA is invalid")
    if _SHA256.fullmatch(protected_lineage_sha256) is None:
        raise ValueError("protected lineage SHA is invalid")
    records: list[dict[str, object]] = []
    for item in selection.items:
        private_ref = private_refs.get(item.frame.clip_ref)
        if not isinstance(private_ref, str) or not private_ref:
            raise ValueError("private clip ref is missing")
        records.append(
            {
                "clip_ref": item.frame.clip_ref,
                "private_ref": private_ref,
                "camera_night": item.frame.camera_night,
                "timestamp_ms": item.frame.timestamp_ms,
                "image_sha256": item.frame.image_sha256,
                "dhash64": f"{item.frame.dhash64:016x}",
                "stratum": item.stratum,
                "reasons": list(item.reasons),
                "double_review": item.double_review,
            }
        )
    aggregate = {
        "unique_image_count": len(records),
        "review_task_count": selection.review_task_count,
        "double_review_count": sum(bool(row["double_review"]) for row in records),
        "excluded_protected_count": selection.excluded_protected,
        "clip_count": len({str(row["clip_ref"]) for row in records}),
        "strata_counts": selection.strata_counts,
    }
    payload = {
        "schema": "yolo26n-v26-recent-dense-selection-v1",
        "status": "SELECTION_FROZEN",
        "dense_lineage_sha256": dense_lineage_sha256,
        "protected_lineage_sha256": protected_lineage_sha256,
        "contract": {
            "coverage_per_clip": contract.coverage_per_clip,
            "uncertainty_count": contract.uncertainty_count,
            "hard_negative_count": contract.hard_negative_count,
            "iid_random_count": contract.iid_random_count,
            "gold_count": contract.gold_count,
            "seed": contract.seed,
            "protected_dhash_distance": contract.protected_dhash_distance,
            "temporal_dhash_distance": contract.temporal_dhash_distance,
            "uncertainty_near_duplicate_per_clip": contract.uncertainty_near_duplicate_per_clip,
            "hard_negative_near_duplicate_per_clip": contract.hard_negative_near_duplicate_per_clip,
            "iid_near_duplicate_per_clip": contract.iid_near_duplicate_per_clip,
        },
        "aggregate": aggregate,
        "records": records,
    }
    selection_sha256 = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {**payload, "selection_sha256": selection_sha256}


def write_selection_once(destination: Path, manifest: dict[str, object]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, sort_keys=True, indent=2)
        handle.write("\n")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_validated_enriched_frames(
    enriched_root: Path,
) -> tuple[dict[str, object], list[DenseFrame], dict[str, str]]:
    """Validate enriched completion lineage before exposing rows to selection."""

    final_path = enriched_root / "completion.private.json"
    enriched_final = json.loads(final_path.read_text())
    if enriched_final.get("status") != "GME_JOIN_COMPLETE":
        raise ValueError("enriched completion status is invalid")
    clips = enriched_final.get("clips")
    if not isinstance(clips, list):
        raise ValueError("enriched completion clips are invalid")
    if enriched_final.get("clip_count") != len(clips):
        raise ValueError("enriched completion clip count drift")

    expected_clip_refs: set[str] = set()
    expected_private_refs: set[str] = set()
    declared_row_count = 0
    for clip in clips:
        if not isinstance(clip, dict):
            raise ValueError("enriched completion clip is invalid")
        clip_ref = clip.get("clip_ref")
        private_ref = clip.get("private_ref")
        row_count = clip.get("row_count")
        if (
            not isinstance(clip_ref, str)
            or not clip_ref
            or clip_ref in expected_clip_refs
            or not isinstance(private_ref, str)
            or not private_ref
            or private_ref in expected_private_refs
            or type(row_count) is not int
            or row_count < 1
        ):
            raise ValueError("enriched completion clip identity/count is invalid")
        expected_clip_refs.add(clip_ref)
        expected_private_refs.add(private_ref)
        declared_row_count += row_count
    if enriched_final.get("row_count") != declared_row_count:
        raise ValueError("enriched completion row count drift")

    clips_root = enriched_root / "clips"
    if not clips_root.is_dir():
        raise ValueError("enriched clip set is missing")
    actual_private_refs = {path.name for path in clips_root.iterdir() if path.is_dir()}
    if actual_private_refs != expected_private_refs or any(
        not path.is_dir() for path in clips_root.iterdir()
    ):
        raise ValueError("enriched clip set does not match completion")

    frames: list[DenseFrame] = []
    private_refs: dict[str, str] = {}
    missing_feedback_band = 0
    for clip in clips:
        clip_ref = str(clip["clip_ref"])
        private_ref = str(clip["private_ref"])
        clip_root = clips_root / private_ref
        if {path.name for path in clip_root.iterdir()} != _ENRICHED_CLIP_FILES:
            raise ValueError("enriched per-clip artifact is partial")
        clip_completion = json.loads(
            (clip_root / "completion.private.json").read_text()
        )
        if (
            clip.get("status") != "GME_JOIN_COMPLETE"
            or clip_completion.get("status") != "GME_JOIN_COMPLETE"
        ):
            raise ValueError("enriched per-clip status is invalid")
        if (
            clip_completion.get("clip_ref") != clip_ref
            or clip_completion.get("private_ref") != private_ref
        ):
            raise ValueError("enriched per-clip identity drift")
        if (
            clip.get("detector_identity") != enriched_final.get("detector_identity")
            or clip_completion.get("detector_identity")
            != enriched_final.get("detector_identity")
        ):
            raise ValueError("enriched detector identity drift")

        ledger_path = clip_root / "ledger.jsonl"
        actual_sha256 = _sha256_file(ledger_path)
        if (
            actual_sha256 != clip.get("ledger_sha256")
            or actual_sha256 != clip_completion.get("ledger_sha256")
        ):
            raise ValueError("enriched ledger SHA drift")
        rows = [json.loads(line) for line in ledger_path.open(encoding="utf-8")]
        if len(rows) != clip.get("row_count") or len(rows) != clip_completion.get(
            "row_count"
        ):
            raise ValueError("enriched ledger row count drift")

        private_refs[clip_ref] = private_ref
        for row in rows:
            if row.get("clip_ref") != clip_ref:
                raise ValueError("enriched ledger clip identity drift")
            if "feedback_band" in row:
                feedback_band = row["feedback_band"]
                if type(feedback_band) is not bool:
                    raise ValueError("feedback_band signal must be bool")
            else:
                feedback_band = False
                missing_feedback_band += 1
            frames.append(
                DenseFrame(
                    clip_ref=clip_ref,
                    camera_night=str(row["camera_night"]),
                    timestamp_ms=int(row["timestamp_ms"]),
                    image_sha256=str(row["image_sha256"]),
                    dhash64=int(row["dhash64"]),
                    detection_count=int(row["detection_count"]),
                    max_confidence=float(row["max_confidence"]),
                    motion_score=float(row["motion_score"]),
                    scene_score=float(row["scene_score"]),
                    feedback_band=feedback_band,
                ).validate()
            )
    if missing_feedback_band:
        warnings.warn(
            "feedback_band is absent for "
            f"{missing_feedback_band} enriched rows; defaulting to false without inference",
            UserWarning,
            stacklevel=2,
        )
    return enriched_final, frames, private_refs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--enriched-root", type=Path, required=True)
    parser.add_argument("--protected-fingerprints", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    enriched_final_path = args.enriched_root / "completion.private.json"
    _enriched_final, frames, private_refs = load_validated_enriched_frames(
        args.enriched_root
    )

    protected_payload = json.loads(args.protected_fingerprints.read_text())
    protected_sha = {str(row["image_sha256"]) for row in protected_payload["records"]}
    protected_dhash = {int(str(row["dhash64"]), 16) for row in protected_payload["records"]}
    contract = StratifiedQueueContract(
        uncertainty_count=900,
        hard_negative_count=350,
        iid_random_count=400,
        gold_count=200,
        # OpenCV and historical Pillow dHash differed by at most one bit in the
        # measured compatibility probe, so distance 4 is the conservative
        # pre-export filter for the historical distance-2 contract.
        protected_dhash_distance=4,
    )
    selection = select_stratified_queue(
        frames,
        contract=contract,
        protected_sha256=protected_sha,
        protected_dhash64=protected_dhash,
    )
    manifest = build_selection_manifest(
        selection,
        private_refs=private_refs,
        dense_lineage_sha256=_sha256_file(enriched_final_path),
        protected_lineage_sha256=_sha256_file(args.protected_fingerprints),
        contract=contract,
    )
    write_selection_once(args.output, manifest)
    print(
        json.dumps(
            {"status": manifest["status"], **manifest["aggregate"]},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
