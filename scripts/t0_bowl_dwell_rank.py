"""T0: bowl-dwell 랭킹 → top60+random20 샘플링 → R2 다운로드 → blind 판정 시트.

하드 계약: production DB SELECT 만 · blind(시트/파일명에 clip_id/dwell/그룹 미노출) ·
seed=20260720 고정(TEST-SHEET §2와 동일해야 함 — 불일치=실험 무효).
"""
from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path[:0] = [str(_REPO_ROOT)]

SEED = 20260720
TOP_N = 60
RANDOM_N = 20
MIN_OBSERVED_SEC = 5.0
MIN_OBSERVATIONS = 3

EXP_DIR = _REPO_ROOT / "experiments" / "t0-bowl-dwell-probe"
CLIP_DIR = _REPO_ROOT / "storage" / "t0-probe" / "clips"
VERDICTS = "eating|drinking|licking_surface|near_bowl_no_care|elsewhere|absent|unsure"


def bowl_dwell_sec(dwell: dict, bowl_cells: list) -> float:
    """그릇 셀 체류 초 = Σ(cells[r][c] 비율) × observed_sec."""
    if not bowl_cells or not dwell:
        return 0.0
    cells = dwell["cells"]
    frac = sum(cells[r][c] for r, c in bowl_cells)
    return round(frac * dwell["observed_sec"], 3)


def is_eligible(run: dict) -> bool:
    """TEST-SHEET §2 eligible 필터. sparse 관찰 dwell 은 노이즈라 제외."""
    d = run.get("spatial_dwell")
    return bool(
        run.get("level0_status") == "ok"
        and run.get("level1_status") == "ok"
        and d
        and d.get("observed_sec", 0) >= MIN_OBSERVED_SEC
        and d.get("n_observations", 0) >= MIN_OBSERVATIONS
    )


def sample_split(ranked: list, top_n: int, random_n: int, seed: int):
    """dwell 내림차순 상위 top_n + 나머지에서 무작위 random_n (결정론)."""
    ordered = sorted(ranked, key=lambda x: (-x["bowl_dwell"], x["clip_id"]))
    top = ordered[:top_n]
    rest = ordered[top_n:]
    rng = random.Random(seed)
    rand = rng.sample(rest, min(random_n, len(rest)))
    return top, rand


def _fetch_all(client, table: str, columns: str, page: int = 1000) -> list:
    """supabase-py 기본 1000행 제한 → range 페이지네이션."""
    rows, offset = [], 0
    while True:
        batch = (client.table(table).select(columns)
                 .range(offset, offset + page - 1).execute().data)
        rows.extend(batch)
        if len(batch) < page:
            return rows
        offset += page


def main() -> int:
    from backend.r2_uploader import get_r2_bucket, get_r2_client
    from backend.supabase_client import get_supabase_client

    client = get_supabase_client()
    bowl_cfg = json.loads((EXP_DIR / "bowl_cells.json").read_text())

    cams = {c["id"]: c["name"] for c in
            client.table("cameras").select("id,name").execute().data}
    runs = _fetch_all(client, "clip_python_evidence_runs",
                      "clip_id,level0_status,level1_status,spatial_dwell,created_at")
    clips = {m["id"]: m for m in _fetch_all(
        client, "motion_clips", "id,camera_id,r2_key,started_at,duration_sec")}

    # clip 당 최신 run 1건 (재처리 대비)
    latest: dict[str, dict] = {}
    for r in runs:
        prev = latest.get(r["clip_id"])
        if prev is None or r["created_at"] > prev["created_at"]:
            latest[r["clip_id"]] = r

    ranked = []
    for clip_id, run in latest.items():
        if not is_eligible(run):
            continue
        clip = clips.get(clip_id)
        if clip is None:
            continue
        cam_name = cams.get(clip["camera_id"], "?")
        cells = [tuple(rc) for rc in
                 bowl_cfg.get(cam_name, {}).get("bowl_cells", [])]
        if not cells:  # 그릇 안 보이는 카메라는 랭킹 제외 (TEST-SHEET §2)
            continue
        ranked.append({
            "clip_id": clip_id,
            "camera": cam_name,
            "r2_key": clip["r2_key"],
            "started_at": clip["started_at"],
            "bowl_dwell": bowl_dwell_sec(run["spatial_dwell"], cells),
        })

    top, rand = sample_split(ranked, TOP_N, RANDOM_N, SEED)
    print(f"eligible={len(ranked)} top={len(top)} random={len(rand)}")

    # blind 셔플: top/random 섞고 review_id 재부여 (시드 고정, 그룹 미노출)
    combined = [dict(x, group="top") for x in top] + \
               [dict(x, group="random") for x in rand]
    random.Random(SEED + 1).shuffle(combined)

    CLIP_DIR.mkdir(parents=True, exist_ok=True)
    (EXP_DIR / "key").mkdir(parents=True, exist_ok=True)
    r2, bucket = get_r2_client(), get_r2_bucket()

    key_rows, sheet_rows = [], []
    for i, item in enumerate(combined, 1):
        rid = f"t0-{i:03d}"
        local = CLIP_DIR / f"{rid}.mp4"
        if not local.exists():  # 재실행 안전 (다운로드만 재개)
            r2.download_file(bucket, item["r2_key"], str(local))
        key_rows.append({"review_id": rid, **item})
        sheet_rows.append({"review_id": rid,
                           "video": f"storage/t0-probe/clips/{rid}.mp4",
                           "verdict": "", "note": ""})
        print(f"[{i}/{len(combined)}] {rid}")

    (EXP_DIR / "key" / "assignment_key.json").write_text(
        json.dumps({"seed": SEED, "items": key_rows}, ensure_ascii=False, indent=2))
    with (EXP_DIR / "blind_sheet.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["review_id", "video", "verdict", "note"])
        w.writeheader()
        w.writerows(sheet_rows)
        f.write(f"# verdict 허용값: {VERDICTS}\n")
    print(f"sheet={EXP_DIR / 'blind_sheet.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
