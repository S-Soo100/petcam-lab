"""v4.1 shedding IR-guard — Set-FP(오탐셋) sample_list 재현 빌더.

정의: nightly VLM(source=vlm)이 shedding 으로 예측했으나 사람 GT 는 moving 인
production 카메라 클립. = 흰 모프 IR 오탐. v4.1 이 이걸 shedding→moving 으로
회복시켜야 한다 (Part A "does it fix?").

GT 출처: behavior_logs(source=human) 우선, 없으면 behavior_labels (라벨링 웹 큐).
두 스토어 이원화(메모리 gt-label-store-split) 때문에 union 으로 잡는다.

출력: sample_list_fp.json — clip_id 정렬 고정(재현). pre-reg 시험지의 sample list.
실행: `uv run python experiments/v41-shedding-ir-guard/_build_fp_sample.py`
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUT = Path(__file__).resolve().parent / "sample_list_fp.json"


def main() -> None:
    load_dotenv(REPO_ROOT / ".env")
    sb = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )

    def fetch_all(table: str, select: str, **eq: str) -> list[dict]:
        rows: list[dict] = []
        off = 0
        while True:
            q = sb.table(table).select(select)
            for k, v in eq.items():
                q = q.eq(k, v)
            page = q.range(off, off + 999).execute().data
            if not page:
                break
            rows.extend(page)
            if len(page) < 1000:
                break
            off += 1000
        return rows

    # VLM 이 shedding 찍은 클립
    vlm_shed = {r["clip_id"] for r in fetch_all("behavior_logs", "clip_id", source="vlm", action="shedding")}

    # GT 두 스토어 (human 우선, 없으면 labels)
    human_gt = {r["clip_id"]: r["action"] for r in fetch_all("behavior_logs", "clip_id, action", source="human")}
    label_gt = {r["clip_id"]: r["action"] for r in fetch_all("behavior_labels", "clip_id, action")}

    # camera_clips 메타
    clips = {c["id"]: c for c in fetch_all("camera_clips", "id, r2_key, source")}

    rows: list[dict] = []
    for cid in vlm_shed:
        gt = human_gt.get(cid) or label_gt.get(cid)
        if gt != "moving":  # 오탐(진짜 GT=moving)만
            continue
        c = clips.get(cid)
        if not c or not c.get("r2_key"):
            continue
        rows.append(
            {
                "clip_id": cid,
                "r2_key": c["r2_key"],
                "gt": "moving",
                "source": c.get("source"),
                "gt_store": "human" if cid in human_gt else "labels",
            }
        )

    rows.sort(key=lambda r: r["clip_id"])  # 재현 고정
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Set-FP: {len(rows)}건 → {OUT.relative_to(REPO_ROOT)}")
    by_src: dict[str, int] = {}
    by_store: dict[str, int] = {}
    for r in rows:
        by_src[r["source"]] = by_src.get(r["source"], 0) + 1
        by_store[r["gt_store"]] = by_store.get(r["gt_store"], 0) + 1
    print(f"  source 분포: {by_src}")
    print(f"  GT 스토어 분포: {by_store}")


if __name__ == "__main__":
    main()
