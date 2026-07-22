"""Gate B1R2 Task 2 — 독립 재계산기 테스트.

`scripts/recompute_local_vlm_evidence_b1r2_media.py` 는 주 구현(audit 모듈)을 import 하지 않고
private manifest(JSONL) 로부터 count/camera-date 분포/availability SHA 를 stdlib 로 다시 계산해
tracked aggregate 선언값과 대조한다. 상태 하나만 바꿔도 SHA mismatch 로 잡아야 한다.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from scripts.recompute_local_vlm_evidence_b1r2_media import recompute

FIVE_STATE_ROWS = [
    {"clip_id": "c1", "camera_id": "camA", "started_at": "2026-07-01T10:00:00+00:00",
     "source_date": "2026-07-01", "status": "evidence_succeeded"},
    {"clip_id": "c2", "camera_id": "camA", "started_at": "2026-07-01T11:00:00+00:00",
     "source_date": "2026-07-01", "status": "media_available_open"},
    {"clip_id": "c3", "camera_id": "camB", "started_at": "2026-07-02T10:00:00+00:00",
     "source_date": "2026-07-02", "status": "media_available_silent"},
    {"clip_id": "c4", "camera_id": "camB", "started_at": "2026-07-02T11:00:00+00:00",
     "source_date": "2026-07-02", "status": "media_available_terminal"},
    {"clip_id": "c5", "camera_id": "camB", "started_at": "2026-07-02T12:00:00+00:00",
     "source_date": "2026-07-02", "status": "source_expired"},
]


def _sha(rows) -> str:
    payload = "\n".join(
        f"{r['clip_id']}\t{r['status']}" for r in sorted(rows, key=lambda x: x["clip_id"])
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _aggregate_from_rows(rows) -> dict:
    counts = Counter(r["status"] for r in rows)
    cam_date = Counter(f"{r['camera_id']}|{r['source_date']}|{r['status']}" for r in rows)
    expired = counts.get("source_expired", 0)
    return {
        "study_total": len(rows),
        "evidence_succeeded": counts.get("evidence_succeeded", 0),
        "media_available_open": counts.get("media_available_open", 0),
        "media_available_silent": counts.get("media_available_silent", 0),
        "media_available_terminal": counts.get("media_available_terminal", 0),
        "source_expired": expired,
        "recoverable_total": len(rows) - expired,
        "recoverable_coverage_closed": (
            counts.get("media_available_open", 0) == 0
            and counts.get("media_available_silent", 0) == 0
        ),
        "partition_equation_holds": True,
        "availability_sha256": _sha(rows),
        "camera_date_status_counts": dict(sorted(cam_date.items())),
    }


def write_fixture(tmp_path: Path, rows):
    agg_path = tmp_path / "aggregate.json"
    man_path = tmp_path / "manifest.jsonl"
    agg_path.write_text(json.dumps(_aggregate_from_rows(rows), sort_keys=True), encoding="utf-8")
    man_path.write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8"
    )
    return agg_path, man_path


def mutate_one_status(man_path: Path):
    lines = man_path.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[0])
    row["status"] = "source_expired" if row["status"] != "source_expired" else "media_available_silent"
    lines[0] = json.dumps(row, sort_keys=True)
    man_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_recompute_matches_counts_and_sha(tmp_path):
    aggregate, manifest = write_fixture(tmp_path, FIVE_STATE_ROWS)
    assert recompute(aggregate, manifest).matched is True


def test_recompute_rejects_changed_status(tmp_path):
    aggregate, manifest = write_fixture(tmp_path, FIVE_STATE_ROWS)
    mutate_one_status(manifest)
    assert recompute(aggregate, manifest).matched is False


def test_recompute_rejects_duplicate_clip(tmp_path):
    rows = FIVE_STATE_ROWS + [dict(FIVE_STATE_ROWS[0])]
    aggregate, manifest = write_fixture(tmp_path, FIVE_STATE_ROWS)  # aggregate declares 5
    manifest.write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8"
    )
    assert recompute(aggregate, manifest).matched is False


def test_recompute_does_not_import_primary_module():
    source = Path("scripts/recompute_local_vlm_evidence_b1r2_media.py").read_text(encoding="utf-8")
    assert "audit_local_vlm_evidence_b1r2_media" not in source
