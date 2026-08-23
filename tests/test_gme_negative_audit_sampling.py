"""Contract tests for deterministic GME-negative audit sampling."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import stat
from typing import get_type_hints
from uuid import UUID, uuid5

import pytest

from scripts.gme_negative_audit_sampling import (
    CHECKPOINT_SHA256,
    DETECTOR_IDENTITY,
    AuditSelectionResult,
    AuditContractError,
    AuditShortageError,
    build_private_manifest,
    parse_candidate,
    select_calibration_batch,
    write_private_json_new,
    _selection_provenance,
)


_NAMESPACE = UUID("5a73ec69-4368-47f4-aa4f-8a6c15d0715e")


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def candidate(
    *,
    index: int = 0,
    stratum: str = "random_negative",
    camera_night_key: str = "camera-night-00",
    episode_key: str | None = None,
) -> dict[str, object]:
    """Return a complete, hand-authored candidate mapping."""
    is_control = stratum == "positive_control"
    return {
        "clip_id": str(uuid5(_NAMESPACE, f"clip:{stratum}:{index}")),
        "stratum": stratum,
        "started_at": (
            datetime(2026, 8, 1, tzinfo=timezone.utc) + timedelta(minutes=index)
        ).isoformat().replace("+00:00", "Z"),
        "duration_sec": 60.0,
        "camera_night_key": camera_night_key,
        "episode_key": episode_key or f"episode-{index:03d}",
        "gme_run_id": str(uuid5(_NAMESPACE, "gme-run-v25")),
        "detector_identity": DETECTOR_IDENTITY,
        "media_sha256": _digest(f"media:{stratum}:{index}"),
        "media_dhash": f"{0x7000000000000000 | ((index + (10_000 if is_control else 0)) << 8):016x}",
        "gme_detected": is_control,
        "human_gt_digest": _digest(f"human-gt:{index}") if is_control else None,
    }


def candidates(count: int, *, stratum: str) -> list[dict[str, object]]:
    return [candidate(index=index, stratum=stratum) for index in range(count)]


def controls(count: int) -> list[dict[str, object]]:
    return candidates(count, stratum="positive_control")


def negatives_across_nights() -> list[dict[str, object]]:
    return [
        candidate(
            index=index,
            camera_night_key=f"camera-night-{index % 6:02d}",
            episode_key=f"episode-{index // 2:03d}",
        )
        for index in range(180)
    ]


def _canonical_sha256(payload: dict[str, object]) -> str:
    unsigned = dict(payload)
    unsigned.pop("manifest_sha256", None)
    return hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def valid_manifest() -> dict[str, object]:
    selection = select_calibration_batch(
        negatives_across_nights(),
        controls(30),
        protected_sha256=set(),
        protected_dhash64=set(),
        seed="gme-negative-audit-v1",
    )
    return build_manifest(selection)


def build_manifest(selection: object) -> dict[str, object]:
    return build_private_manifest(
        selection,
        test_sheet_sha256=_digest("test-sheet"),
        cutoff="2026-08-01T00:00:00Z",
        checkpoint_sha256=CHECKPOINT_SHA256,
        protected_manifest_sha256=[_digest("v25-training-manifest")],
    )


def test_parse_candidate_requires_exact_lineage_and_available_media() -> None:
    raw = candidate()

    assert parse_candidate(raw).gme_detected is False

    for key in (
        "gme_run_id",
        "detector_identity",
        "media_sha256",
        "camera_night_key",
        "episode_key",
    ):
        broken = dict(raw)
        broken.pop(key)

        with pytest.raises(AuditContractError):
            parse_candidate(broken)


def test_selector_annotation_exposes_atomic_selection_result() -> None:
    assert get_type_hints(select_calibration_batch)["return"] is AuditSelectionResult


def test_parse_candidate_rejects_noncanonical_identity_and_invalid_stratum_contract() -> None:
    malformed_uuid = candidate()
    malformed_uuid["clip_id"] = str(malformed_uuid["clip_id"]).upper()
    with pytest.raises(AuditContractError, match="clip_id"):
        parse_candidate(malformed_uuid)

    noncanonical_time = candidate()
    noncanonical_time["started_at"] = "2026-08-01T00:00:00+00:00"
    with pytest.raises(AuditContractError, match="started_at"):
        parse_candidate(noncanonical_time)

    negative_with_gt = candidate()
    negative_with_gt["human_gt_digest"] = _digest("not-allowed")
    with pytest.raises(AuditContractError, match="random_negative"):
        parse_candidate(negative_with_gt)

    control_without_gt = candidate(stratum="positive_control")
    control_without_gt["human_gt_digest"] = None
    with pytest.raises(AuditContractError, match="positive_control"):
        parse_candidate(control_without_gt)


def test_parse_candidate_maps_overflowing_duration_to_a_contract_error() -> None:
    raw = candidate()
    raw["duration_sec"] = 10**10000

    with pytest.raises(AuditContractError, match="duration_sec"):
        parse_candidate(raw)


def test_selection_rejects_protected_and_duplicate_media() -> None:
    rows = candidates(120, stratum="random_negative")

    with pytest.raises(AuditContractError, match="protected overlap"):
        select_calibration_batch(
            rows,
            controls(30),
            protected_sha256={str(rows[0]["media_sha256"])},
            protected_dhash64=set(),
            seed="v1",
        )

    with pytest.raises(AuditContractError, match="near-duplicate overlap"):
        near = [dict(rows[0], media_dhash="0000000000000003"), *rows[1:]]
        select_calibration_batch(
            near,
            controls(30),
            protected_sha256=set(),
            protected_dhash64={"0000000000000000"},
            seed="v1",
        )

    duplicate = [dict(rows[0]), *rows[1:]]
    duplicate[1]["media_sha256"] = duplicate[0]["media_sha256"]
    with pytest.raises(AuditContractError, match="duplicate media"):
        select_calibration_batch(
            duplicate,
            controls(30),
            protected_sha256=set(),
            protected_dhash64=set(),
            seed="v1",
        )


def test_selection_accepts_hamming_distance_three_from_protected_media() -> None:
    rows = candidates(120, stratum="random_negative")
    rows[0]["media_dhash"] = "0000000000000007"

    selected = select_calibration_batch(
        rows,
        controls(30),
        protected_sha256=set(),
        protected_dhash64={"0000000000000000"},
        seed="v1",
    )

    assert len(selected) == 150


def test_selection_uses_the_brief_rank_and_fixed_blind_order_domain() -> None:
    seed = "preview-rank-contract"
    negative_rows = candidates(6, stratum="random_negative")
    control_rows = controls(4)

    selected = select_calibration_batch(
        negative_rows,
        control_rows,
        protected_sha256=set(),
        protected_dhash64=set(),
        seed=seed,
        batch_kind="preview_canary",
        negative_count=4,
        control_count=2,
    )

    expected_negative_ids = {
        row["clip_id"]
        for row in sorted(
            negative_rows,
            key=lambda row: hashlib.sha256(
                f"{seed}:random_negative:{row['clip_id']}".encode("utf-8")
            ).hexdigest(),
        )[:4]
    }
    assert {
        item.candidate.clip_id
        for item in selected
        if item.candidate.stratum == "random_negative"
    } == expected_negative_ids
    assert [item.candidate.clip_id for item in selected] == [
        item.candidate.clip_id
        for item in sorted(
            selected,
            key=lambda item: hashlib.sha256(
                f"{seed}:blind-order:{item.candidate.stratum}:{item.candidate.clip_id}".encode(
                    "utf-8"
                )
            ).hexdigest(),
        )
    ]


def test_selection_is_deterministic_stratified_and_caps_episode() -> None:
    first = select_calibration_batch(
        negatives_across_nights(),
        controls(30),
        protected_sha256=set(),
        protected_dhash64=set(),
        seed="gme-negative-audit-v1",
    )
    second = select_calibration_batch(
        negatives_across_nights(),
        controls(30),
        protected_sha256=set(),
        protected_dhash64=set(),
        seed="gme-negative-audit-v1",
    )

    assert first == second
    assert sum(item.candidate.stratum == "random_negative" for item in first) == 120
    assert sum(item.candidate.stratum == "positive_control" for item in first) == 30
    assert (
        max(
            Counter(
                item.candidate.episode_key
                for item in first
                if item.candidate.stratum == "random_negative"
            ).values()
        )
        <= 2
    )
    assert [item.ordinal for item in first] == list(range(1, 151))


def test_selection_fails_closed_when_episode_cap_leaves_too_few_negatives() -> None:
    rows = [candidate(index=index, episode_key="single-episode") for index in range(120)]

    with pytest.raises(AuditShortageError, match="random_negative"):
        select_calibration_batch(
            rows,
            controls(30),
            protected_sha256=set(),
            protected_dhash64=set(),
            seed="gme-negative-audit-v1",
        )


def test_preview_canary_has_a_separate_exact_size_contract() -> None:
    selected = select_calibration_batch(
        negatives_across_nights(),
        controls(30),
        protected_sha256=set(),
        protected_dhash64=set(),
        seed="preview",
        batch_kind="preview_canary",
        negative_count=4,
        control_count=2,
    )

    assert len(selected) == 6

    with pytest.raises(AuditContractError):
        select_calibration_batch(
            negatives_across_nights(),
            controls(30),
            protected_sha256=set(),
            protected_dhash64=set(),
            seed="preview",
            batch_kind="preview_canary",
            negative_count=5,
            control_count=1,
        )


def test_private_manifest_is_canonical_complete_and_0600_no_overwrite(
    tmp_path: Path,
) -> None:
    payload = valid_manifest()
    path = tmp_path / "manifest.private.json"

    assert payload["schema_version"] == "gme-negative-audit-v1"
    assert payload["status"] == "prepared"
    assert payload["manifest_sha256"] == _canonical_sha256(payload)
    assert payload["manifest_sha256_rule"] == "sha256(canonical-json-excluding-manifest_sha256)"
    assert payload["candidate_counts"] == {
        "random_negative": 180,
        "positive_control": 30,
    }
    assert len(payload["items"]) == 150
    assert payload["items"][0]["ordinal"] == 1
    assert payload["items"][-1]["ordinal"] == 150

    write_private_json_new(path, payload)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text(encoding="utf-8")) == payload
    with pytest.raises(FileExistsError):
        write_private_json_new(path, payload)


def test_private_manifest_revalidates_dataclass_identity_before_freezing() -> None:
    selection = select_calibration_batch(
        negatives_across_nights(),
        controls(30),
        protected_sha256=set(),
        protected_dhash64=set(),
        seed="gme-negative-audit-v1",
    )
    items = list(selection)
    items[0] = replace(
        items[0], candidate=replace(items[0].candidate, detector_identity="not-pinned")
    )

    with pytest.raises(AuditContractError, match="detector_identity"):
        build_manifest(replace(selection, items=tuple(items)))


def test_private_manifest_rejects_reordered_selector_items() -> None:
    seed = "gme-negative-audit-v1"
    selection = select_calibration_batch(
        negatives_across_nights(),
        controls(30),
        protected_sha256=set(),
        protected_dhash64=set(),
        seed=seed,
    )
    reordered = tuple(
        replace(item, ordinal=ordinal)
        for ordinal, item in enumerate(reversed(selection), start=1)
    )

    with pytest.raises(AuditContractError, match="blind order"):
        build_manifest(replace(selection, items=reordered))


def test_private_manifest_rejects_episode_cap_tampering() -> None:
    seed = "gme-negative-audit-v1"
    selection = select_calibration_batch(
        negatives_across_nights(),
        controls(30),
        protected_sha256=set(),
        protected_dhash64=set(),
        seed=seed,
    )
    selected = list(selection)
    negative_indexes = [
        index
        for index, item in enumerate(selected)
        if item.candidate.stratum == "random_negative"
    ]
    for index in negative_indexes[:3]:
        selected[index] = replace(
            selected[index],
            candidate=replace(selected[index].candidate, episode_key="tampered-episode"),
        )

    with pytest.raises(AuditContractError, match="episode cap"):
        build_manifest(replace(selection, items=tuple(selected)))


def test_private_manifest_rejects_dataclass_candidate_replacement() -> None:
    seed = "gme-negative-audit-v1"
    selection = select_calibration_batch(
        negatives_across_nights(),
        controls(30),
        protected_sha256=set(),
        protected_dhash64=set(),
        seed=seed,
    )
    selected = list(selection)
    selected[0] = replace(
        selected[0],
        candidate=replace(selected[0].candidate, duration_sec=61.0),
    )

    with pytest.raises(AuditContractError, match="selection provenance"):
        build_manifest(replace(selection, items=tuple(selected)))


def test_manifest_binds_actual_source_pool_counts_without_caller_claims() -> None:
    full_negative_pool = negatives_across_nights()
    selection = select_calibration_batch(
        full_negative_pool,
        controls(30),
        protected_sha256=set(),
        protected_dhash64=set(),
        seed="gme-negative-audit-v1",
    )

    with pytest.raises(AuditContractError, match="source pool digest"):
        build_manifest(
            replace(selection, negative_pool=selection.negative_pool[:120])
        )

    manifest = build_manifest(selection)

    assert manifest["candidate_counts"] == {
        "random_negative": 180,
        "positive_control": 30,
    }
    with pytest.raises(TypeError):
        build_private_manifest(
            selection,
            test_sheet_sha256=_digest("test-sheet"),
            cutoff="2026-08-01T00:00:00Z",
            checkpoint_sha256=CHECKPOINT_SHA256,
            protected_manifest_sha256=[_digest("v25-training-manifest")],
            candidate_counts={"random_negative": 180, "positive_control": 30},
        )


def test_manifest_rejects_substituted_item_with_recomputed_provenance() -> None:
    selection = select_calibration_batch(
        negatives_across_nights(),
        controls(30),
        protected_sha256=set(),
        protected_dhash64=set(),
        seed="gme-negative-audit-v1",
    )
    items = list(selection)
    replacement = replace(items[0].candidate, duration_sec=61.0)
    items[0] = replace(
        items[0],
        candidate=replacement,
        selection_provenance=_selection_provenance(
            selection.seed,
            items[0].ordinal,
            replacement,
        ),
    )

    with pytest.raises(AuditContractError, match="selection result"):
        build_manifest(replace(selection, items=tuple(items)))


def test_manifest_accepts_full_pool_selection_and_carries_pool_digests() -> None:
    selection = select_calibration_batch(
        negatives_across_nights(),
        controls(30),
        protected_sha256=set(),
        protected_dhash64=set(),
        seed="gme-negative-audit-v1",
    )

    manifest = build_manifest(selection)

    assert manifest["candidate_counts"] == {
        "random_negative": 180,
        "positive_control": 30,
    }
    assert manifest["source_pools"] == {
        "random_negative": {
            "count": 180,
            "sha256": selection.negative_pool_sha256,
        },
        "positive_control": {
            "count": 30,
            "sha256": selection.control_pool_sha256,
        },
    }
