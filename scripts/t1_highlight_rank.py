"""T1: DB-only 합성점수 하이라이트 랭킹 → S(top20)+R(random20) → R2 다운로드 → blind 시트.

TEST-SHEET: experiments/t1-highlight-selection/TEST-SHEET.md (🔒 2026-07-21 동결)
하드 계약: production DB SELECT 만 · blind(시트/파일명에 clip_id/점수/그룹 미노출) ·
LLM/VLM 0회 · seed=20260721 고정(시험지 §2와 불일치 = 실험 무효).
"""
from __future__ import annotations

import csv
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path[:0] = [str(_REPO_ROOT)]

SEED = 20260721
TOP_N = 20
RANDOM_N = 20
BUCKET_CAP = 4          # (camera, KST date, 2h 창)당 최대 — production selector 정렬
MIN_OBSERVED_SEC = 5.0  # eligible 조건은 T0 §2와 동일
MIN_OBSERVATIONS = 3

EXP_DIR = _REPO_ROOT / "experiments" / "t1-highlight-selection"
T0_KEY = _REPO_ROOT / "experiments" / "t0-bowl-dwell-probe" / "key" / "assignment_key.json"
CLIP_DIR = _REPO_ROOT / "storage" / "t1-highlight" / "clips"
VERDICTS = "informative_care|informative_other|not_informative|absent|unsure"
_KST = timezone(timedelta(hours=9))


def percentile_rank(values: list[float]) -> list[float]:
    """평균 순위 기반 백분위(0~1). 동률은 평균 순위, n=1 은 중립 0.5."""
    n = len(values)
    if n == 1:
        return [0.5]
    order = sorted(range(n), key=lambda i: values[i])
    avg_rank = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        mean_rank = (i + j) / 2
        for k in range(i, j + 1):
            avg_rank[order[k]] = mean_rank
        i = j + 1
    return [r / (n - 1) for r in avg_rank]


def compute_scores(rows: list[dict]) -> dict[str, float]:
    """합성점수 = mean(pr(observed_sec), pr(roi_mean), pr(peak_autocorr)). 결측 성분=0."""
    scores = {r["clip_id"]: 0.0 for r in rows}
    for feat in ("observed_sec", "roi_mean", "peak_autocorr"):
        present = [r for r in rows if r.get(feat) is not None]
        prs = percentile_rank([float(r[feat]) for r in present]) if present else []
        for r, pr in zip(present, prs):
            scores[r["clip_id"]] += pr / 3
    return {cid: round(s, 6) for cid, s in scores.items()}


def bucket_key(camera: str, started_at_iso: str) -> tuple[str, str, int]:
    """(camera, KST date, 2h 창 index). started_at 은 UTC ISO(Z 또는 +00:00)."""
    dt = datetime.fromisoformat(started_at_iso.replace("Z", "+00:00"))
    kst = dt.astimezone(_KST)
    return (camera, kst.strftime("%Y-%m-%d"), kst.hour // 2)


def select_top_with_cap(ranked: list[dict], n: int, cap: int) -> list[dict]:
    """점수 내림차순 순회, 버킷 캡 초과분은 건너뛰고 다음 순위로."""
    ordered = sorted(ranked, key=lambda x: (-x["score"], x["clip_id"]))
    counts: dict[tuple, int] = {}
    picked = []
    for item in ordered:
        if len(picked) >= n:
            break
        b = item["bucket"]
        if counts.get(b, 0) >= cap:
            continue
        counts[b] = counts.get(b, 0) + 1
        picked.append(item)
    return picked


def split_groups(ranked: list[dict], top_n: int, random_n: int, cap: int, seed: int):
    """S=버킷 캡 top_n, R=S 제외 풀에서 무작위 random_n (결정론)."""
    s_group = select_top_with_cap(ranked, top_n, cap)
    s_ids = {x["clip_id"] for x in s_group}
    rest = sorted((x for x in ranked if x["clip_id"] not in s_ids),
                  key=lambda x: (-x["score"], x["clip_id"]))
    rng = random.Random(seed)
    r_group = rng.sample(rest, min(random_n, len(rest)))
    return s_group, r_group


def is_eligible(run: dict) -> bool:
    d = run.get("spatial_dwell")
    return bool(
        run.get("level0_status") == "ok"
        and run.get("level1_status") == "ok"
        and d
        and d.get("observed_sec", 0) >= MIN_OBSERVED_SEC
        and d.get("n_observations", 0) >= MIN_OBSERVATIONS
    )


def _fetch_all(client, table: str, columns: str, page: int = 1000) -> list:
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
    t0_ids = {it["clip_id"] for it in json.loads(T0_KEY.read_text())["items"]}

    cams = {c["id"]: c["name"] for c in
            client.table("cameras").select("id,name").execute().data}
    runs = _fetch_all(
        client, "clip_python_evidence_runs",
        "clip_id,level0_status,level1_status,spatial_dwell,motion_summary,"
        "periodicity_summary,created_at")
    clips = {m["id"]: m for m in _fetch_all(
        client, "motion_clips", "id,camera_id,r2_key,started_at,duration_sec")}

    latest: dict[str, dict] = {}
    for r in runs:
        prev = latest.get(r["clip_id"])
        if prev is None or r["created_at"] > prev["created_at"]:
            latest[r["clip_id"]] = r

    pool = []
    for clip_id, run in latest.items():
        if clip_id in t0_ids or not is_eligible(run):
            continue
        clip = clips.get(clip_id)
        if clip is None:
            continue
        m = run.get("motion_summary") or {}
        p = run.get("periodicity_summary") or {}
        pool.append({
            "clip_id": clip_id,
            "camera": cams.get(clip["camera_id"], "?"),
            "r2_key": clip["r2_key"],
            "started_at": clip["started_at"],
            "observed_sec": run["spatial_dwell"].get("observed_sec"),
            "roi_mean": m.get("roi_mean"),
            "peak_autocorr": p.get("peak_autocorr"),
        })

    scores = compute_scores(pool)
    for item in pool:
        item["score"] = scores[item["clip_id"]]
        item["bucket"] = bucket_key(item["camera"], item["started_at"])

    s_group, r_group = split_groups(pool, TOP_N, RANDOM_N, BUCKET_CAP, SEED)
    print(f"pool={len(pool)} (t0 제외 {len(t0_ids)}) S={len(s_group)} R={len(r_group)}")

    combined = [dict(x, group="score") for x in s_group] + \
               [dict(x, group="random") for x in r_group]
    random.Random(SEED + 1).shuffle(combined)

    CLIP_DIR.mkdir(parents=True, exist_ok=True)
    (EXP_DIR / "key").mkdir(parents=True, exist_ok=True)
    r2, bucket = get_r2_client(), get_r2_bucket()

    key_rows, sheet_rows = [], []
    for i, item in enumerate(combined, 1):
        rid = f"t1-{i:03d}"
        local = CLIP_DIR / f"{rid}.mp4"
        if not local.exists():
            r2.download_file(bucket, item["r2_key"], str(local))
        row = {k: v for k, v in item.items() if k != "bucket"}
        row["bucket"] = list(item["bucket"])
        key_rows.append({"review_id": rid, **row})
        sheet_rows.append({"review_id": rid,
                           "video": f"storage/t1-highlight/clips/{rid}.mp4",
                           "verdict": "", "note": ""})
        print(f"[{i}/{len(combined)}] {rid}")

    (EXP_DIR / "key" / "assignment_key.json").write_text(
        json.dumps({"seed": SEED, "items": key_rows}, ensure_ascii=False, indent=2))
    (EXP_DIR / "sample_list.json").write_text(json.dumps(
        {"seed": SEED, "pool_n": len(pool), "excluded_t0": len(t0_ids),
         "eligibility": {"min_observed_sec": MIN_OBSERVED_SEC,
                         "min_observations": MIN_OBSERVATIONS},
         "bucket_cap": BUCKET_CAP,
         "review_ids": [r["review_id"] for r in key_rows]},
        ensure_ascii=False, indent=2))
    with (EXP_DIR / "blind_sheet.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["review_id", "video", "verdict", "note"])
        w.writeheader()
        w.writerows(sheet_rows)
        f.write(f"# verdict 허용값: {VERDICTS}\n")
    print(f"sheet={EXP_DIR / 'blind_sheet.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
