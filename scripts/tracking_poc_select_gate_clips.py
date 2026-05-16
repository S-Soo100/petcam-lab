"""Tracking PoC Step 0 — 게이트셋 30~50건 stratified 선정.

## 모드

- `--analyze` : 159건 평가셋 메타 분포만 출력 (stratify 임계값 결정용)
- `--sample`  : --hour-ir-start / --hour-ir-end / --motion-cut 받아 stratified sample 실행

## 평가셋 정의

`scripts/eval_vlm_worker_regression.py:load_eval_set` 와 동일 — production DB
`camera_clips` (has_motion=True + r2_key NOT NULL) INNER JOIN `behavior_logs`
(source='human') = 159건.

본 스크립트는 거기에 stratify 용 메타 (started_at, duration_sec, motion_frames, source) 를
추가 조회. `motion_frames` 가 NULL 인 클립 (source='upload') 은 `unknown` intensity 그룹.

## stratify 축

1. **time_band** : started_at 시각 → `ir` (사용자 지정 IR 시간대) / `day` (그 외)
2. **motion_intensity** : motion_frames / duration_sec → `low` / `high` (median cut) / `unknown` (NULL)
3. **action_group** : GT 9 클래스를 4 그룹으로 축소
   - `static` : resting, hiding
   - `feeding` : eating, drinking, eating_paste
   - `active` : moving
   - `rare` : tongue_flicking, defecating, shedding (희귀 클래스, minimum 1건 보장)
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import random
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from supabase import create_client

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("select_gate_clips")

EXPERIMENTS_DIR = REPO_ROOT / "experiments" / "tracking-poc"
META_CSV = EXPERIMENTS_DIR / "clips-gate-meta.csv"
GATE_TXT = EXPERIMENTS_DIR / "clips-gate.txt"

ACTION_GROUP = {
    "resting": "static",
    "hiding": "static",
    "eating": "feeding",
    "drinking": "feeding",
    "eating_paste": "feeding",
    "eating_prey": "feeding",
    "moving": "active",
    "defecating": "physiological",
    "shedding": "physiological",
    "tongue_flicking": "rare",
    "unseen": "unseen",  # vision 한계 — 게이트셋 제외
}

# started_at 은 업로드 시각이라 stratify 기준으로 무의미 (2026-05-14 사용자 확인).
# → time_band 축 제거. action_group × motion_intensity 2축만 사용.


@dataclass
class ClipMeta:
    clip_id: str
    started_at: datetime  # UTC
    duration_sec: float
    motion_frames: int | None  # NULL for source='upload' clips
    source: str | None
    action: str

    @property
    def motion_ratio(self) -> float | None:
        """motion frames per second (duration normalized). None if motion_frames is NULL."""
        if self.motion_frames is None or self.duration_sec <= 0:
            return None
        return self.motion_frames / self.duration_sec

    @property
    def action_group(self) -> str:
        return ACTION_GROUP.get(self.action, "rare")


def load_eval_meta() -> list[ClipMeta]:
    """159건 평가셋 + stratify 용 메타 조회."""
    load_dotenv(REPO_ROOT / ".env")
    sb = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )

    # 1. GT (human 라벨)
    gt_rows: list[dict[str, Any]] = []
    off = 0
    while True:
        page = (
            sb.table("behavior_logs")
            .select("clip_id, action")
            .eq("source", "human")
            .range(off, off + 999)
            .execute()
            .data
        )
        if not page:
            break
        gt_rows.extend(page)
        if len(page) < 1000:
            break
        off += 1000
    gt_map: dict[str, str] = {r["clip_id"]: r["action"] for r in gt_rows}

    # 2. camera_clips + 메타
    clips: list[dict[str, Any]] = []
    off = 0
    while True:
        page = (
            sb.table("camera_clips")
            .select("id, started_at, duration_sec, motion_frames, source, r2_key")
            .eq("has_motion", True)
            .not_.is_("r2_key", None)
            .range(off, off + 999)
            .execute()
            .data
        )
        if not page:
            break
        clips.extend(page)
        if len(page) < 1000:
            break
        off += 1000

    out: list[ClipMeta] = []
    for c in clips:
        cid = c["id"]
        if cid not in gt_map:
            continue
        try:
            started = datetime.fromisoformat(c["started_at"].replace("Z", "+00:00"))
        except (TypeError, ValueError):
            logger.warning("started_at parse fail clip=%s", cid)
            continue
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        mf = c.get("motion_frames")
        out.append(
            ClipMeta(
                clip_id=cid,
                started_at=started,
                duration_sec=float(c.get("duration_sec") or 0.0),
                motion_frames=int(mf) if mf is not None else None,
                source=c.get("source"),
                action=gt_map[cid],
            )
        )
    out.sort(key=lambda m: m.clip_id)
    return out


def motion_ratio_summary(metas: list[ClipMeta]) -> str:
    """motion_frames / duration_sec 분포 — high/low cut 결정용. NULL 별도 카운트."""
    n_null = sum(1 for m in metas if m.motion_ratio is None)
    ratios = sorted(m.motion_ratio for m in metas if m.motion_ratio is not None)
    src_dist = Counter(m.source for m in metas)
    lines = [f"source 분포: {dict(src_dist)}"]
    lines.append(f"motion_frames NULL: {n_null} / {len(metas)} 건")
    if not ratios:
        lines.append("(non-NULL motion_ratio 없음)")
        return "\n".join(lines)
    quartiles = statistics.quantiles(ratios, n=4) if len(ratios) >= 4 else [ratios[0]] * 3
    lines.extend([
        f"motion frames-per-sec 분포 (non-NULL N={len(ratios)})",
        f"  min     : {ratios[0]:.2f}",
        f"  Q1      : {quartiles[0]:.2f}",
        f"  median  : {quartiles[1]:.2f}  ← 기본 cut",
        f"  Q3      : {quartiles[2]:.2f}",
        f"  max     : {ratios[-1]:.2f}",
        f"  mean    : {statistics.mean(ratios):.2f}",
    ])
    return "\n".join(lines)


def action_distribution(metas: list[ClipMeta]) -> str:
    """GT 클래스 + action_group 분포."""
    raw = Counter(m.action for m in metas)
    grp = Counter(m.action_group for m in metas)
    lines = ["raw 9-class:"]
    for k, v in sorted(raw.items(), key=lambda x: -x[1]):
        lines.append(f"  {k:18s} {v:4d}")
    lines.append("\naction group (stratify 축):")
    for k, v in sorted(grp.items(), key=lambda x: -x[1]):
        lines.append(f"  {k:18s} {v:4d}")
    return "\n".join(lines)


def write_meta_csv(metas: list[ClipMeta]) -> None:
    META_CSV.parent.mkdir(parents=True, exist_ok=True)
    with META_CSV.open("w", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["clip_id", "started_at_utc", "duration_sec",
                    "motion_frames", "motion_ratio", "source", "action", "action_group"])
        for m in metas:
            ratio_str = f"{m.motion_ratio:.3f}" if m.motion_ratio is not None else ""
            w.writerow([
                m.clip_id,
                m.started_at.isoformat(),
                f"{m.duration_sec:.2f}",
                m.motion_frames if m.motion_frames is not None else "",
                ratio_str,
                m.source or "",
                m.action,
                m.action_group,
            ])
    logger.info("메타 CSV 저장: %s (%d rows)", META_CSV, len(metas))


def stratified_sample(
    metas: list[ClipMeta],
    *,
    n_target: int,
    motion_cut: float,
    seed: int,
) -> list[ClipMeta]:
    """2축 (action_group × motion_intensity) stratified sample.

    - unseen 그룹은 게이트셋에서 제외 (도마뱀 안 보이는 클립 → tracker 검증 가치 0).
    - static (hiding 3건) 같은 작은 그룹은 minimum 1건 보장.
    """
    rng = random.Random(seed)
    pool = [m for m in metas if m.action_group != "unseen"]

    cells: dict[tuple[str, str], list[ClipMeta]] = defaultdict(list)
    for m in pool:
        if m.motion_ratio is None:
            intensity = "unknown"
        elif m.motion_ratio >= motion_cut:
            intensity = "high"
        else:
            intensity = "low"
        key = (intensity, m.action_group)
        cells[key].append(m)

    total = len(pool)
    selected: list[ClipMeta] = []
    cell_quota: dict[tuple[str, str], int] = {}
    for key, group in cells.items():
        share = round(n_target * len(group) / total)
        if "static" in key or "rare" in key:
            share = max(share, min(1, len(group)))
        cell_quota[key] = min(share, len(group))

    # 총합이 n_target 과 다르면 큰 셀에서 ± 보정 (보정 단계에서 무한루프 방지)
    diff = n_target - sum(cell_quota.values())
    if diff != 0:
        sorted_cells = sorted(cells.items(), key=lambda x: -len(x[1]))
        guard = 0
        while diff != 0 and guard < 200:
            progressed = False
            for key, group in sorted_cells:
                if diff == 0:
                    break
                if diff > 0 and cell_quota[key] < len(group):
                    cell_quota[key] += 1
                    diff -= 1
                    progressed = True
                elif diff < 0 and cell_quota[key] > 0:
                    cell_quota[key] -= 1
                    diff += 1
                    progressed = True
            if not progressed:
                break
            guard += 1

    for key, group in cells.items():
        quota = cell_quota[key]
        if quota == 0:
            continue
        chosen = rng.sample(group, quota)
        selected.extend(chosen)
        logger.info(
            "cell %s : %d / %d 선정", key, quota, len(group)
        )
    return selected


def write_gate_txt(selected: list[ClipMeta], *, args: argparse.Namespace) -> None:
    GATE_TXT.parent.mkdir(parents=True, exist_ok=True)
    with GATE_TXT.open("w") as fp:
        fp.write(f"# Tracking PoC 게이트셋 — {len(selected)}건\n")
        fp.write(f"# 생성: {datetime.now(timezone.utc).isoformat()}\n")
        fp.write(f"# stratify: motion_cut={args.motion_cut} (camera 클립만), seed={args.seed}\n")
        fp.write(f"# unseen 그룹은 제외 (vision 한계 → tracker 검증 가치 0)\n")
        fp.write("#\n# clip_id\tintensity\taction_group\taction\tsource\tmotion_ratio\n")
        for m in sorted(selected, key=lambda x: (x.action_group, x.action, x.clip_id)):
            if m.motion_ratio is None:
                intensity = "unknown"
            elif m.motion_ratio >= args.motion_cut:
                intensity = "high"
            else:
                intensity = "low"
            ratio_str = f"{m.motion_ratio:.2f}" if m.motion_ratio is not None else "-"
            fp.write(f"{m.clip_id}\t{intensity}\t{m.action_group}\t{m.action}\t{m.source}\t{ratio_str}\n")
    logger.info("게이트셋 저장: %s (%d clips)", GATE_TXT, len(selected))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="mode", required=True)

    p_an = sub.add_parser("analyze", help="159건 분포 분석만")
    p_an.add_argument("--csv", action="store_true", help="메타 CSV도 함께 저장")

    p_sa = sub.add_parser("sample", help="stratified sample 실행")
    p_sa.add_argument("--n", type=int, default=40, help="목표 클립 수 (default 40)")
    p_sa.add_argument("--motion-cut", type=float, default=1.75,
                      help="motion_ratio high/low cut (default 1.75 = camera 71건 median)")
    p_sa.add_argument("--seed", type=int, default=42)

    args = p.parse_args()

    metas = load_eval_meta()
    logger.info("평가셋 로드: %d 건", len(metas))

    if args.mode == "analyze":
        print("\n=== motion_ratio (frames/sec) 분포 ===")
        print(motion_ratio_summary(metas))
        print("\n=== action 분포 ===")
        print(action_distribution(metas))
        if args.csv:
            write_meta_csv(metas)
        return

    if args.mode == "sample":
        selected = stratified_sample(
            metas,
            n_target=args.n,
            motion_cut=args.motion_cut,
            seed=args.seed,
        )
        write_gate_txt(selected, args=args)
        print("\n=== 선정된 게이트셋 action 분포 ===")
        print(action_distribution(selected))


if __name__ == "__main__":
    main()
