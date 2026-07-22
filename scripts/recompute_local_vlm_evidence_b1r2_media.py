"""Gate B1R2 독립 재계산 — private manifest 를 stdlib 만으로 다시 계산해 tracked aggregate 와 대조.

**주 구현(media availability 감사 모듈)을 import 하지 않는다.** manifest JSONL 의 per-clip status 에서
상태별 count, camera/date 분포, availability SHA 를 독립 하드코딩으로 재계산하고 aggregate 선언값과
정확히 일치하는지 확인한다. mismatch 면 exit 1 (→ B1R2_BLOCKED_INVENTORY_INTEGRITY).

독립성 계약: SHA canonical 형식(정렬 규칙·직렬화)을 이 파일에 별도 하드코딩한다. 같은 코드 재사용이면
검증이 아니다. 그래서 audit 모듈을 import 하지 않고 formula 를 재구현한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# frozen 5-state 순서 (독립 하드코딩 — 주 구현 import 금지).
STATUSES = (
    "evidence_succeeded",
    "media_available_open",
    "media_available_silent",
    "media_available_terminal",
    "source_expired",
)


@dataclass(frozen=True, slots=True)
class RecomputeResult:
    matched: bool
    reasons: list = field(default_factory=list)
    recomputed_sha256: str = ""
    recomputed_counts: dict = field(default_factory=dict)
    study_total: int = 0


def _canonical_sha256(rows: list[dict]) -> str:
    """audit 의 availability_sha256 과 동치인 독립 재구현: 정렬된 (clip_id, status) 쌍."""
    payload = "\n".join(
        f"{r['clip_id']}\t{r['status']}" for r in sorted(rows, key=lambda x: x["clip_id"])
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_manifest(path) -> list[dict]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def recompute(aggregate, manifest) -> RecomputeResult:
    """aggregate JSON path 와 manifest JSONL path 를 읽어 독립 재계산·대조."""
    agg = json.loads(Path(aggregate).read_text(encoding="utf-8"))
    rows = _read_manifest(manifest)

    reasons: list[str] = []

    # 필수 필드/알 수 없는 상태 검사
    for r in rows:
        for key in ("clip_id", "camera_id", "started_at", "source_date", "status"):
            if key not in r:
                reasons.append(f"manifest row missing field {key!r}")
        if r.get("status") not in STATUSES:
            reasons.append(f"unknown status {r.get('status')!r}")

    clip_ids = [r["clip_id"] for r in rows if "clip_id" in r]
    if len(clip_ids) != len(set(clip_ids)):
        reasons.append("duplicate clip_id in manifest")

    counts = Counter(r.get("status") for r in rows)
    recomputed_counts = {s: counts.get(s, 0) for s in STATUSES}
    study_total = len(rows)

    if study_total != agg.get("study_total"):
        reasons.append("study_total mismatch")
    for s in STATUSES:
        if recomputed_counts[s] != agg.get(s):
            reasons.append(f"{s} count mismatch")

    equation_ok = study_total == sum(recomputed_counts.values())
    if not equation_ok:
        reasons.append("partition equation broken")

    expired = recomputed_counts["source_expired"]
    if (study_total - expired) != agg.get("recoverable_total"):
        reasons.append("recoverable_total mismatch")
    closed = recomputed_counts["media_available_open"] == 0 and recomputed_counts["media_available_silent"] == 0
    if closed != agg.get("recoverable_coverage_closed"):
        reasons.append("recoverable_coverage_closed mismatch")

    cam_date = Counter(
        f"{r['camera_id']}|{r['source_date']}|{r['status']}"
        for r in rows
        if all(k in r for k in ("camera_id", "source_date", "status"))
    )
    recomputed_cd = dict(sorted(cam_date.items()))
    if agg.get("camera_date_status_counts") is not None and recomputed_cd != agg["camera_date_status_counts"]:
        reasons.append("camera_date_status_counts mismatch")

    recomputed_sha = _canonical_sha256([r for r in rows if "clip_id" in r and "status" in r])
    if recomputed_sha != agg.get("availability_sha256"):
        reasons.append("availability_sha256 mismatch")

    return RecomputeResult(
        matched=not reasons,
        reasons=reasons,
        recomputed_sha256=recomputed_sha,
        recomputed_counts=recomputed_counts,
        study_total=study_total,
    )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="B1R2 media availability 독립 재계산 (audit 미의존)")
    p.add_argument("--aggregate", required=True, help="tracked aggregate JSON")
    p.add_argument("--private-manifest", required=True, help="gitignored per-clip JSONL")
    args = p.parse_args(argv)

    res = recompute(args.aggregate, args.private_manifest)
    if res.matched:
        print(f"MATCH availability_sha256={res.recomputed_sha256} "
              f"study_total={res.study_total} counts={res.recomputed_counts}")
        return 0
    print("MISMATCH: " + "; ".join(res.reasons), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
