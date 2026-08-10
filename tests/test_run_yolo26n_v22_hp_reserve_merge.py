from __future__ import annotations

import csv
import hashlib
import json
import sys
import types
from collections import Counter
from pathlib import Path

import pytest

import scripts.run_yolo26n_v22_hp_reserve_merge as reserve_merge


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, payload: object) -> str:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return _digest(path.read_bytes())


def _candidate(
    name: str,
    *,
    source: str,
    night: str,
    image_sha256: str | None = None,
    dhash: int = 0,
) -> dict[str, object]:
    return {
        "local_name": f"{name}.jpg",
        "source_ref": source,
        "camera_id": "camera-a",
        "camera_night": night,
        "candidate_bucket": "hard_positive",
        "probe_index": 0,
        "frame_index": 10,
        "image_sha256": image_sha256 or _digest(name.encode()),
        "dhash": dhash,
    }


def _inventory_argv() -> list[str]:
    return [
        "inventory",
        "--output",
        str(reserve_merge.RESERVE_OUTPUT_DIR),
        "--parent",
        str(reserve_merge.PARENT_OUTPUT_DIR),
        "--reporter-repo",
        "/tmp/reporter",
        "--dataset-v21-provenance",
        str(reserve_merge.DATASET_V21_PROVENANCE),
        "--dataset-v21-provenance-sha256",
        "a" * 64,
        "--v1-provenance",
        str(reserve_merge.V1_PROVENANCE),
        "--v1-provenance-sha256",
        "b" * 64,
        "--v2-provenance",
        str(reserve_merge.V2_PROVENANCE),
        "--v2-provenance-sha256",
        "c" * 64,
        "--expected-parent-manifest-sha256",
        "d" * 64,
        "--expected-reserve-source-commit",
        "e" * 40,
    ]


def test_residual_night_max_flow_selects_exact_23_and_is_order_independent() -> None:
    parent_nights = {"nearly-full": 11}
    rows = [
        _candidate(
            f"near-{index}", source=f"near-source-{index}", night="nearly-full", dhash=index
        )
        for index in range(10)
    ] + [
        _candidate(
            f"open-{index}", source=f"open-source-{index}", night=f"open-{index // 12}", dhash=100 + index
        )
        for index in range(22)
    ]

    first = reserve_merge.select_reserve_frames(
        rows, parent_night_counts=parent_nights, target=23, seed="owner-v2.2"
    )
    second = reserve_merge.select_reserve_frames(
        reversed(rows), parent_night_counts=parent_nights, target=23, seed="owner-v2.2"
    )

    assert [row["image_sha256"] for row in first] == [
        row["image_sha256"] for row in second
    ]
    assert len(first) == 23
    counts = Counter(str(row["camera_night"]) for row in first)
    assert counts["nearly-full"] == 1


def test_residual_max_flow_avoids_greedy_shared_sha_dead_end() -> None:
    shared = _digest(b"shared")
    rows = [
        _candidate("a-shared", source="source-a", night="night-a", image_sha256=shared, dhash=0),
        _candidate("a-unique", source="source-a", night="night-a", dhash=8),
        _candidate("b-shared", source="source-b", night="night-b", image_sha256=shared, dhash=16),
    ]

    selected = reserve_merge.select_reserve_frames(
        rows,
        parent_night_counts={"night-a": 11, "night-b": 11},
        target=2,
        seed="owner-v2.2",
    )

    assert {(row["source_ref"], row["image_sha256"]) for row in selected} == {
        ("source-a", _digest(b"a-unique")),
        ("source-b", shared),
    }


def test_selection_enforces_source_hash_dhash_and_residual_night_caps() -> None:
    duplicate_parent_sha = _digest(b"parent")
    rows = [
        _candidate("blocked-parent", source="s0", night="n0", image_sha256=duplicate_parent_sha),
        _candidate("s1-a", source="s1", night="n1", dhash=0),
        _candidate("s1-near", source="s1", night="n1", dhash=1),
        _candidate("s1-far", source="s1", night="n1", dhash=255),
        _candidate("s1-third", source="s1", night="n1", dhash=65535),
        _candidate("s2", source="s2", night="n1", dhash=3),
    ]

    selected = reserve_merge.select_reserve_frames(
        rows,
        parent_night_counts={"n1": 9},
        target=3,
        seed="owner-v2.2",
        excluded_image_sha256={duplicate_parent_sha},
    )

    assert len(selected) == 3
    assert max(Counter(str(row["source_ref"]) for row in selected).values()) <= 2
    assert len({str(row["image_sha256"]) for row in selected}) == 3
    assert all(row["image_sha256"] != duplicate_parent_sha for row in selected)
    s1 = [int(row["dhash"]) for row in selected if row["source_ref"] == "s1"]
    assert all((left ^ right).bit_count() > 2 for i, left in enumerate(s1) for right in s1[i + 1 :])
    assert len(selected) + 9 <= 12


def test_inventory_selection_is_hp_only_exact_and_bounded_to_four_sources_per_night() -> None:
    rows = [
        {
            "source_ref": f"source-{index:03d}",
            "camera_id": "camera-a",
            "camera_night": f"night-{index % 26:02d}",
            "r2_key": f"clips/{index}.mp4",
            "gme_max_geckos": 1,
        }
        for index in range(104)
    ] + [
        {
            "source_ref": "negative",
            "camera_id": "camera-a",
            "camera_night": "night-negative",
            "r2_key": "clips/negative.mp4",
            "gme_max_geckos": 0,
        }
    ]

    selected = reserve_merge.select_reserve_inventory_sources(
        rows,
        parent_night_counts={"full-parent-night": 12},
        excluded_source_refs={"source-000"},
        quota=100,
        max_sources_per_night=4,
        seed="owner-v2.2",
    )

    assert len(selected) == 100
    assert all(int(row["gme_max_geckos"]) >= 1 for row in selected)
    assert "source-000" not in {row["source_ref"] for row in selected}
    assert max(Counter(str(row["camera_night"]) for row in selected).values()) <= 4
    assert selected == reserve_merge.select_reserve_inventory_sources(
        reversed(rows),
        parent_night_counts={"full-parent-night": 12},
        excluded_source_refs={"source-000"},
        quota=100,
        max_sources_per_night=4,
        seed="owner-v2.2",
    )


def test_cli_rejects_wrong_or_legacy_paths_before_dispatch(monkeypatch) -> None:
    argv = _inventory_argv()
    argv[argv.index("--output") + 1] = str(reserve_merge.V2_OUTPUT_DIR)
    dispatched: list[object] = []
    monkeypatch.setattr(reserve_merge, "inventory", dispatched.append)
    monkeypatch.setattr(reserve_merge.sys, "argv", ["runner", *argv])

    with pytest.raises(SystemExit):
        reserve_merge.main()

    assert dispatched == []


def test_cli_rejects_dotdot_alias_of_approved_reserve_path() -> None:
    argv = _inventory_argv()
    argv[argv.index("--output") + 1] = str(
        reserve_merge.RESERVE_OUTPUT_DIR.parent
        / "other"
        / ".."
        / reserve_merge.RESERVE_OUTPUT_DIR.name
    )

    with pytest.raises(ValueError, match="--output"):
        reserve_merge.validate_cli_contract(
            reserve_merge.build_parser().parse_args(argv)
        )


def test_cli_rejects_missing_phase_specific_paths_as_contract_error() -> None:
    args = reserve_merge.build_parser().parse_args(
        [
            "inventory",
            "--output",
            str(reserve_merge.RESERVE_OUTPUT_DIR),
            "--parent",
            str(reserve_merge.PARENT_OUTPUT_DIR),
            "--expected-parent-manifest-sha256",
            "d" * 64,
            "--expected-reserve-source-commit",
            "e" * 40,
        ]
    )

    with pytest.raises(ValueError, match="unsafe Task4b CLI contract"):
        reserve_merge.validate_cli_contract(args)


def test_dataset_v21_source_provenance_matches_observed_candidate_artifact() -> None:
    assert reserve_merge.DATASET_V21_PROVENANCE == Path(
        "/Users/baek-end/private-rba/yolo26n-v21-targeted/"
        "attempt-20260810-owner-v2/candidate-manifest.private.json"
    )


def test_fresh_preflight_rejects_stale_reserve_before_external_read(monkeypatch, tmp_path) -> None:
    reserve = tmp_path / "reserve"
    reserve.mkdir()
    (reserve / "code").mkdir()
    (reserve / "stale.json").write_text("{}", encoding="utf-8")
    external_reads: list[str] = []
    monkeypatch.setattr(reserve_merge, "RESERVE_OUTPUT_DIR", reserve.resolve())
    args = reserve_merge.build_parser().parse_args(
        [value if value != str(Path(_inventory_argv()[2])) else str(reserve) for value in _inventory_argv()]
    )
    monkeypatch.setattr(reserve_merge, "_inventory_external_read", lambda *_args: external_reads.append("read"))

    with pytest.raises(ValueError, match="fresh"):
        reserve_merge.inventory(args)

    assert external_reads == []


def test_pinned_provenance_rejects_empty_wrong_hash_and_non_string_source(tmp_path) -> None:
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    fake = tmp_path / "fake.json"
    fake_digest = _write_json(fake, {"frames": [{"source_ref": 7}]})
    good = tmp_path / "good.json"
    good_digest = _write_json(good, {"frames": [{"source_ref": "source-a"}]})

    with pytest.raises(ValueError, match="empty"):
        reserve_merge.load_pinned_source_refs([(empty, _digest(b""))])
    with pytest.raises(ValueError, match="sha256"):
        reserve_merge.load_pinned_source_refs([(good, "0" * 64)])
    with pytest.raises(ValueError, match="source_ref"):
        reserve_merge.load_pinned_source_refs([(fake, fake_digest)])
    assert reserve_merge.load_pinned_source_refs([(good, good_digest)]) == {"source-a"}


def test_inventory_metadata_shortage_performs_zero_r2_get(monkeypatch, tmp_path) -> None:
    class FakeQuery:
        def __init__(self, rows):
            self.rows = rows

        def __getattr__(self, _name):
            return lambda *_args, **_kwargs: self

        @property
        def not_(self):
            return self

        def execute(self):
            return types.SimpleNamespace(data=self.rows)

    rows = {
        "motion_clips": [
            {
                "id": "one-source",
                "camera_id": "camera-a",
                "started_at": "2026-07-16T00:00:00Z",
                "duration_sec": 60,
                "r2_key": "clips/one.mp4",
                "clip_purpose": "production",
            }
        ],
        "motion_clip_system_exclusions": [],
        "gme_runs": [
            {
                "clip_id": "one-source",
                "created_at": "2026-07-16T01:00:00Z",
                "duration_sec": 60,
                "visible_sec": 30,
                "unknown_sec": 0,
                "max_simultaneous_geckos": 1,
                "status": "ok",
            }
        ],
    }
    fake_client = types.SimpleNamespace(table=lambda name: FakeQuery(rows[name]))
    supabase_module = types.ModuleType("supabase")
    supabase_module.create_client = lambda *_args: fake_client
    downloads: list[object] = []
    reporter_module = types.ModuleType("reporter")
    reporter_module.config = types.SimpleNamespace(
        SUPABASE_URL="https://example.invalid", SUPABASE_KEY="fake"
    )
    reporter_module.r2 = types.SimpleNamespace(
        R2SourceMissing=type("R2SourceMissing", (Exception,), {}),
        download_clip=lambda *_args: downloads.append(_args),
    )
    monkeypatch.setitem(sys.modules, "supabase", supabase_module)
    monkeypatch.setitem(sys.modules, "reporter", reporter_module)
    args = types.SimpleNamespace(
        reporter_repo=tmp_path,
        cutoff="2026-07-15T00:00:00Z",
        output=tmp_path / "reserve",
        probe_hard_positive_sources=100,
        probe_max_sources_per_night=4,
        seed="owner-v2.2",
        dataset_v21_provenance_sha256="a" * 64,
        v1_provenance_sha256="b" * 64,
        v2_provenance_sha256="c" * 64,
        expected_parent_manifest_sha256="d" * 64,
    )

    with pytest.raises(SystemExit, match="INVENTORY_SHORTAGE"):
        reserve_merge._inventory_external_read(args, set(), [])

    assert downloads == []
    summary = json.loads(
        (args.output / "inventory-selection.private.json").read_text(encoding="utf-8")
    )
    assert summary["selected_hp_source_count"] == 1
    assert summary["selected_hn_source_count"] == 0


def test_analyze_rejects_fake_or_unlinked_inventory_provenance(tmp_path) -> None:
    inventory = tmp_path / "inventory-selection.private.json"
    inventory_sha = _write_json(
        inventory,
        {
            "schema": "yolo26n-v22-hp-reserve-inventory-v1",
            "status": "V22_HP_RESERVE_INVENTORY_READY",
            "seed": "owner-v2.2",
            "selected_hp_source_count": 100,
            "selected_hn_source_count": 0,
            "hp_source_quota": 100,
            "db_write_count": 0,
            "r2_write_count": 0,
        },
    )
    source = {
        "source_ref": "source-a",
        "camera_id": "camera-a",
        "camera_night": "night-a",
        "r2_key": "clips/0.mp4",
        "probe_bucket": "hard_positive",
        "local_name": "S0001.mp4",
        "duration_sec": 60.0,
        "gme_visible_ratio": 0.5,
        "gme_unknown_ratio": 0.0,
        "gme_max_geckos": 1,
    }
    selected_sources = [
        {
            "source_ref": "source-a" if index == 0 else f"missing-{index:03d}",
            "camera_id": "camera-a",
            "camera_night": "night-a" if index == 0 else f"night-{index // 4:02d}",
            "r2_key": f"clips/{index}.mp4",
            "duration_sec": 60.0,
            "gme_visible_ratio": 0.5,
            "gme_unknown_ratio": 0.0,
            "gme_max_geckos": 1,
            "probe_bucket": "hard_positive",
            "local_name": f"S{index + 1:04d}.mp4",
        }
        for index in range(100)
    ]
    selection_sha = reserve_merge.source_selection_sha256(selected_sources)
    excluded_sha = reserve_merge.source_ref_set_sha256(set())
    inventory_payload = json.loads(inventory.read_text(encoding="utf-8"))
    inventory_payload["selected_sources_sha256"] = selection_sha
    inventory_payload["excluded_source_refs_sha256"] = excluded_sha
    inventory_payload["selected_sources"] = selected_sources
    inventory_sha = _write_json(inventory, inventory_payload)
    payload = {
        "schema": "yolo26n-v22-hp-reserve-probe-sources-v1",
        "status": "V22_HP_RESERVE_INVENTORY_READY",
        "seed": "owner-v2.2",
        "selected_hp_source_count": 100,
        "selected_hn_source_count": 0,
        "downloaded_source_count": 1,
        "missing_source_count": 99,
        "inventory_summary_sha256": inventory_sha,
        "selected_sources_sha256": selection_sha,
        "excluded_source_refs_sha256": excluded_sha,
        "db_write_count": 0,
        "r2_write_count": 0,
        "selected_sources": selected_sources,
        "sources": [source],
    }

    reserve_merge.validate_reserve_probe_payload(
        payload, inventory, parent_frames=[], excluded_source_refs=set()
    )

    wrong_hash = dict(payload, inventory_summary_sha256="0" * 64)
    with pytest.raises(ValueError, match="inventory summary sha256"):
        reserve_merge.validate_reserve_probe_payload(
            wrong_hash, inventory, parent_frames=[], excluded_source_refs=set()
        )
    wrong_bucket = dict(payload, sources=[dict(source, probe_bucket="hard_negative")])
    with pytest.raises(ValueError, match="HP-only"):
        reserve_merge.validate_reserve_probe_payload(
            wrong_bucket, inventory, parent_frames=[], excluded_source_refs=set()
        )
    duplicate = dict(payload, downloaded_source_count=2, missing_source_count=98, sources=[source, source])
    with pytest.raises(ValueError, match="duplicate source_ref"):
        reserve_merge.validate_reserve_probe_payload(
            duplicate, inventory, parent_frames=[], excluded_source_refs=set()
        )

    path_escape = dict(payload, sources=[dict(source, local_name="../other.mp4")])
    with pytest.raises(ValueError, match="local_name"):
        reserve_merge.validate_reserve_probe_payload(
            path_escape, inventory, parent_frames=[], excluded_source_refs=set()
        )
    changed_gme = dict(payload, sources=[dict(source, gme_max_geckos=2)])
    with pytest.raises(ValueError, match="metadata selection"):
        reserve_merge.validate_reserve_probe_payload(
            changed_gme, inventory, parent_frames=[], excluded_source_refs=set()
        )

    same_night = [dict(row, camera_night="one-night") for row in selected_sources]
    same_night_payload = dict(
        payload,
        selected_sources=same_night,
        selected_sources_sha256=reserve_merge.source_selection_sha256(same_night),
    )
    same_night_inventory = dict(
        inventory_payload,
        selected_sources_sha256=same_night_payload["selected_sources_sha256"],
        selected_sources=same_night,
    )
    same_night_payload["inventory_summary_sha256"] = _write_json(
        inventory, same_night_inventory
    )
    with pytest.raises(ValueError, match="night cap"):
        reserve_merge.validate_reserve_probe_payload(
            same_night_payload, inventory, parent_frames=[], excluded_source_refs=set()
        )

    excluded = {"source-a"}
    excluded_payload = dict(
        payload,
        excluded_source_refs_sha256=reserve_merge.source_ref_set_sha256(excluded),
    )
    excluded_inventory = dict(
        inventory_payload,
        excluded_source_refs_sha256=excluded_payload["excluded_source_refs_sha256"],
    )
    excluded_payload["inventory_summary_sha256"] = _write_json(
        inventory, excluded_inventory
    )
    with pytest.raises(ValueError, match="excluded source"):
        reserve_merge.validate_reserve_probe_payload(
            excluded_payload, inventory, parent_frames=[], excluded_source_refs=excluded
        )


def test_reserve_manifest_preserves_safe_count_and_provenance_summary() -> None:
    manifest = reserve_merge.build_reserve_manifest(
        accepted_frames=[_candidate("safe", source="source-a", night="night-a", dhash=8)],
        analyzed_sources=[
            {
                "source_ref": "source-a",
                "probe_extraction": {
                    "requested": 24,
                    "readable": 23,
                    "decode_failed": 1,
                    "imwrite_failed": 0,
                },
            }
        ],
        hp_classifier_source_count=1,
        rejection_counts={"exact_sha": 2, "dhash": 3, "unreadable": 4},
        model_name="best.pt",
        checkpoint_sha256="c" * 64,
        analyzed_ledger_sha256="a" * 64,
        inventory_summary_sha256="i" * 64,
        parent_manifest_sha256="p" * 64,
        source_commit="e" * 40,
        code_sha256="f" * 64,
    )

    assert manifest["safe_counts"] == {
        "analyzed_sources": 1,
        "hp_classifier_sources": 1,
        "accepted_sources": 1,
        "accepted_frames": 1,
        "shortfall": 22,
        "exact_sha_rejected": 2,
        "dhash_rejected": 3,
        "unreadable_rejected": 4,
    }
    assert manifest["probe_extraction_counts"] == {
        "requested": 24,
        "readable": 23,
        "decode_failed": 1,
        "imwrite_failed": 0,
    }
    assert manifest["provenance"]["inventory_summary_sha256"] == "i" * 64
    assert manifest["provenance"]["parent_manifest_sha256"] == "p" * 64
    assert manifest["provenance"]["source_commit"] == "e" * 40
    assert manifest["provenance"]["code_sha256"] == "f" * 64


def _make_parent(parent: Path) -> tuple[str, dict[str, int]]:
    (parent / "review-frames").mkdir(parents=True)
    (parent / "code" / "scripts").mkdir(parents=True)
    (parent / "code" / "source-commit.txt").write_text(
        reserve_merge.PARENT_SOURCE_COMMIT + "\n", encoding="utf-8"
    )
    (parent / "code" / "scripts" / "run_yolo26n_v22_candidate_mining.py").write_text(
        "# frozen parent\n", encoding="utf-8"
    )
    analyzed_sha = _write_json(
        parent / "analyzed-sources.private.json", {"schema": "parent-analyzed", "sources": []}
    )
    frames: list[dict[str, object]] = []
    parent_nights: Counter[str] = Counter()
    with (parent / "review-index.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["sequence", "filename", "instruction"])
        writer.writeheader()
        for ordinal in range(1, 298):
            sequence = f"V{ordinal:04d}"
            payload = f"parent-image-{ordinal}".encode()
            (parent / "review-frames" / f"{sequence}.jpg").write_bytes(payload)
            bucket = "hard_positive" if ordinal <= 197 else "hard_negative"
            night = f"parent-night-{(ordinal - 1) // 12:02d}"
            parent_nights[night] += 1
            frames.append(
                {
                    "sequence": sequence,
                    "source_ref": f"parent-source-{ordinal:04d}",
                    "camera_id": "camera-parent",
                    "camera_night": night,
                    "candidate_bucket": bucket,
                    "probe_index": 0,
                    "frame_index": ordinal,
                    "image_sha256": _digest(payload),
                }
            )
            writer.writerow(
                {
                    "sequence": sequence,
                    "filename": f"{sequence}.jpg",
                    "instruction": "게코가 보이면 각 개체의 보이는 몸 영역에 bbox",
                }
            )
    manifest = {
        "schema": "yolo26n-v22-candidate-queue-v1",
        "status": "V22_CANDIDATE_QUEUE_SHORTAGE",
        "seed": "owner-v2.2",
        "model": "best.pt",
        "checkpoint_sha256": "c" * 64,
        "analyzed_ledger_sha256": analyzed_sha,
        "prediction_boxes_exposed_to_reviewer": False,
        "db_write_count": 0,
        "r2_write_count": 0,
        "bucket_counts": {"hard_positive": 197, "hard_negative": 100},
        "review_frame_count": 297,
        "source_cap_violation_count": 0,
        "camera_night_cap_violation_count": 0,
        "frames": frames,
    }
    return _write_json(parent / "candidate-manifest.private.json", manifest), dict(parent_nights)


def _make_reserve(reserve: Path, *, count: int, parent_manifest_sha256: str) -> str:
    (reserve / "review-frames").mkdir(parents=True)
    (reserve / "code").mkdir(parents=True)
    (reserve / "code" / "source-commit.txt").write_text("e" * 40 + "\n", encoding="utf-8")
    (reserve / "code" / "run_yolo26n_v22_hp_reserve_merge.py").write_text(
        "# frozen reserve\n", encoding="utf-8"
    )
    analyzed_sha = _write_json(
        reserve / "analyzed-sources.private.json", {"schema": "reserve-analyzed", "sources": []}
    )
    inventory_sha = _write_json(
        reserve / "inventory-selection.private.json", {"schema": "reserve-inventory"}
    )
    frames = []
    for ordinal in range(1, count + 1):
        payload = f"reserve-image-{ordinal}".encode()
        local_name = f"R{ordinal:04d}.jpg"
        (reserve / "review-frames" / local_name).write_bytes(payload)
        frames.append(
            _candidate(
                f"R{ordinal:04d}",
                source=f"reserve-source-{ordinal:04d}",
                night=f"reserve-night-{(ordinal - 1) // 12:02d}",
                image_sha256=_digest(payload),
                dhash=ordinal * 8,
            )
        )
    manifest = {
        "schema": "yolo26n-v22-hp-reserve-v1",
        "status": "V22_HP_RESERVE_READY" if count >= 23 else "V22_HP_RESERVE_SHORTAGE",
        "seed": "owner-v2.2",
        "model": "best.pt",
        "checkpoint_sha256": "c" * 64,
        "analyzed_ledger_sha256": analyzed_sha,
        "prediction_boxes_exposed_to_reviewer": False,
        "db_write_count": 0,
        "r2_write_count": 0,
        "accepted_count": count,
        "provenance": {
            "inventory_summary_sha256": inventory_sha,
            "parent_manifest_sha256": parent_manifest_sha256,
            "source_commit": "e" * 40,
            "code_sha256": _digest(
                (reserve / "code" / "run_yolo26n_v22_hp_reserve_merge.py").read_bytes()
            ),
        },
        "frames": frames,
    }
    return _write_json(reserve / "reserve-manifest.private.json", manifest)


def test_merge_preserves_parent_bytes_order_and_builds_exact_blind_320(tmp_path) -> None:
    parent = tmp_path / "parent"
    reserve = tmp_path / "reserve"
    merged = tmp_path / "merged"
    parent_sha, _ = _make_parent(parent)
    reserve_sha = _make_reserve(reserve, count=25, parent_manifest_sha256=parent_sha)
    parent_hashes = [
        _digest((parent / "review-frames" / f"V{ordinal:04d}.jpg").read_bytes())
        for ordinal in range(1, 298)
    ]

    result = reserve_merge.merge_artifacts(
        parent=parent,
        reserve=reserve,
        output=merged,
        expected_parent_manifest_sha256=parent_sha,
        expected_reserve_manifest_sha256=reserve_sha,
        expected_reserve_source_commit="e" * 40,
        seed="owner-v2.2",
        dhash_reader=lambda path: int(path.stem[1:]) * 8,
    )

    assert result["status"] == "V22_CANDIDATE_QUEUE_READY"
    manifest = json.loads((merged / "candidate-manifest.private.json").read_text())
    assert manifest["bucket_counts"] == {"hard_positive": 220, "hard_negative": 100}
    assert [row["sequence"] for row in manifest["frames"]] == [
        f"V{ordinal:04d}" for ordinal in range(1, 321)
    ]
    assert [
        _digest((merged / "review-frames" / f"V{ordinal:04d}.jpg").read_bytes())
        for ordinal in range(1, 298)
    ] == parent_hashes
    with (merged / "review-index.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 320
    assert list(rows[0]) == ["sequence", "filename", "instruction"]
    assert all(row["filename"] == f'{row["sequence"]}.jpg' for row in rows)
    assert all("source" not in key and "prediction" not in key for key in rows[0])
    assert (merged / "cvat-upload.zip").is_file()
    assert manifest["provenance"]["parent"]["manifest_sha256"] == parent_sha
    assert manifest["provenance"]["reserve"]["manifest_sha256"] == reserve_sha
    assert manifest["selection"]["algorithm"] == "sha-source-night-dinic-with-dhash-branch-v1"


def test_reserve_shortage_creates_no_merged_csv_or_zip(tmp_path) -> None:
    parent = tmp_path / "parent"
    reserve = tmp_path / "reserve"
    merged = tmp_path / "merged"
    parent_sha, _ = _make_parent(parent)
    reserve_sha = _make_reserve(reserve, count=22, parent_manifest_sha256=parent_sha)

    with pytest.raises(SystemExit, match="SHORTAGE"):
        reserve_merge.merge_artifacts(
            parent=parent,
            reserve=reserve,
            output=merged,
            expected_parent_manifest_sha256=parent_sha,
            expected_reserve_manifest_sha256=reserve_sha,
            expected_reserve_source_commit="e" * 40,
            seed="owner-v2.2",
            dhash_reader=lambda path: int(path.stem[1:]) * 8,
        )

    assert not (merged / "review-index.csv").exists()
    assert not (merged / "cvat-upload.zip").exists()


def test_merge_rejects_tampered_parent_and_reserve_hashes(tmp_path) -> None:
    parent = tmp_path / "parent"
    reserve = tmp_path / "reserve"
    parent_sha, _ = _make_parent(parent)
    reserve_sha = _make_reserve(reserve, count=23, parent_manifest_sha256=parent_sha)

    with pytest.raises(ValueError, match="parent manifest sha256"):
        reserve_merge.merge_artifacts(
            parent=parent,
            reserve=reserve,
            output=tmp_path / "merged-a",
            expected_parent_manifest_sha256="0" * 64,
            expected_reserve_manifest_sha256=reserve_sha,
            expected_reserve_source_commit="e" * 40,
            seed="owner-v2.2",
            dhash_reader=lambda _path: 0,
        )
    (reserve / "reserve-manifest.private.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="reserve manifest sha256"):
        reserve_merge.merge_artifacts(
            parent=parent,
            reserve=reserve,
            output=tmp_path / "merged-b",
            expected_parent_manifest_sha256=parent_sha,
            expected_reserve_manifest_sha256=reserve_sha,
            expected_reserve_source_commit="e" * 40,
            seed="owner-v2.2",
            dhash_reader=lambda _path: 0,
        )


def test_merge_rejects_reserve_dhash_that_does_not_match_pixels(tmp_path) -> None:
    parent = tmp_path / "parent"
    reserve = tmp_path / "reserve"
    parent_sha, _ = _make_parent(parent)
    _make_reserve(reserve, count=23, parent_manifest_sha256=parent_sha)
    manifest_path = reserve / "reserve-manifest.private.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["frames"][0]["dhash"] = 999
    reserve_sha = _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="reserve dHash mismatch"):
        reserve_merge.merge_artifacts(
            parent=parent,
            reserve=reserve,
            output=tmp_path / "merged",
            expected_parent_manifest_sha256=parent_sha,
            expected_reserve_manifest_sha256=reserve_sha,
            expected_reserve_source_commit="e" * 40,
            seed="owner-v2.2",
            dhash_reader=lambda path: int(path.stem[1:]) * 8,
        )


def test_merge_rejects_wrong_reserve_provenance(tmp_path) -> None:
    parent = tmp_path / "parent"
    reserve = tmp_path / "reserve"
    parent_sha, _ = _make_parent(parent)
    _make_reserve(reserve, count=23, parent_manifest_sha256=parent_sha)
    manifest_path = reserve / "reserve-manifest.private.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["provenance"]["parent_manifest_sha256"] = "0" * 64
    reserve_sha = _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="reserve provenance"):
        reserve_merge.merge_artifacts(
            parent=parent,
            reserve=reserve,
            output=tmp_path / "merged",
            expected_parent_manifest_sha256=parent_sha,
            expected_reserve_manifest_sha256=reserve_sha,
            expected_reserve_source_commit="e" * 40,
            seed="owner-v2.2",
            dhash_reader=lambda path: int(path.stem[1:]) * 8,
        )


def test_merge_rejects_parent_reserve_source_overlap(tmp_path) -> None:
    parent = tmp_path / "parent"
    reserve = tmp_path / "reserve"
    parent_sha, _ = _make_parent(parent)
    _make_reserve(reserve, count=23, parent_manifest_sha256=parent_sha)
    manifest_path = reserve / "reserve-manifest.private.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["frames"][0]["source_ref"] = "parent-source-0001"
    reserve_sha = _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="parent source"):
        reserve_merge.merge_artifacts(
            parent=parent,
            reserve=reserve,
            output=tmp_path / "merged",
            expected_parent_manifest_sha256=parent_sha,
            expected_reserve_manifest_sha256=reserve_sha,
            expected_reserve_source_commit="e" * 40,
            seed="owner-v2.2",
            dhash_reader=lambda path: int(path.stem[1:]) * 8,
        )


def test_merge_recomputes_parent_bucket_counts_from_frame_ledger(tmp_path) -> None:
    parent = tmp_path / "parent"
    reserve = tmp_path / "reserve"
    _make_parent(parent)
    parent_manifest_path = parent / "candidate-manifest.private.json"
    parent_manifest = json.loads(parent_manifest_path.read_text(encoding="utf-8"))
    parent_manifest["frames"][0]["candidate_bucket"] = "hard_negative"
    parent_sha = _write_json(parent_manifest_path, parent_manifest)
    reserve_sha = _make_reserve(
        reserve, count=23, parent_manifest_sha256=parent_sha
    )

    with pytest.raises(ValueError, match="parent frame bucket"):
        reserve_merge.merge_artifacts(
            parent=parent,
            reserve=reserve,
            output=tmp_path / "merged",
            expected_parent_manifest_sha256=parent_sha,
            expected_reserve_manifest_sha256=reserve_sha,
            expected_reserve_source_commit="e" * 40,
            seed="owner-v2.2",
            dhash_reader=lambda path: int(path.stem[1:]) * 8,
        )
