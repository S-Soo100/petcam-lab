"""203건 데이터셋 정리 — storage/dataset-203/ 한 폴더에 {gt}__{pred}__{clip8}.{ext}.

파일명 = GT(정정 반영) + Claude v3.6.1 판정 + clip_id 8자. 파일명만으로 GT vs Claude
일치/불일치가 보인다. 미세행동(contact sheet 평가 불가) 50건은 pred=na.
44건은 inbox/0608 복사, 159건은 R2 다운로드. manifest.csv 동봉.

실행:
  PYTHONPATH=. uv run python scripts/build_dataset_203.py            # dry-run (이름만)
  PYTHONPATH=. uv run python scripts/build_dataset_203.py --apply    # 복사+다운로드
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.vlm.gemini_client import download_clip_bytes  # noqa: E402
from scripts.eval_vlm_worker_regression import load_eval_set, load_eval_set_0608  # noqa: E402

OUT = REPO / "storage" / "dataset-203"
INBOX = REPO / "inbox" / "0608"
APPLY = "--apply" in sys.argv

# v3.6 pred=hand_feeding 33건의 v3.6.1 재판정 (나머지 153건은 v3.6=v3.6.1)
V361 = {
    "sample-08ec5a50": "moving", "sample-70093109": "moving", "sample-f8ffab0a": "moving",
    "sample-e2eef892": "moving", "sample-5477a71a": "moving",
    "sample-49458257": "hand_feeding", "sample-c6f22144": "hand_feeding",
    "sample-41aecaea": "hand_feeding", "sample-dbdd4378": "hand_feeding",
    "sample-hand-feeding-1740": "hand_feeding", "sample-hand-feeding-5075": "hand_feeding",
    "sample-hand-feeding-1741": "moving", "sample-hand-feeding-8971": "hand_feeding",
    "sample-hand-feeding-2731": "hand_feeding", "sample-hand-feeding-5563": "hand_feeding",
    "sample-hand-feeding-5593": "hand_feeding", "sample-hand-feeding-5936": "moving",
    "sample-hand-feeding-4298": "hand_feeding", "sample-hand-feeding-7062": "hand_feeding",
    "sample-hand-feeding-4829": "hand_feeding", "sample-hand-feeding-7214": "hand_feeding",
    "sample-e784eb65": "hand_feeding", "sample-c928b6ff": "hand_feeding",
    "sample-69c4badd": "eating_paste", "sample-7d9b9e8e": "moving",
    "sample-b8317750": "hand_feeding", "sample-cc0c1d04": "hand_feeding",
    "sample-ea36897b": "moving", "sample-cc9463c9": "moving", "sample-e0e38e0c": "moving",
    "sample-9af1ba2e": "hand_feeding", "sample-26c75091": "moving", "sample-5cfe1d48": "moving",
}

# v3.6 base pred (blind jsonl)
V36: dict[str, str] = {}
for folder, jl in [("eval-0608-claude", "claude_v36_blind.jsonl"), ("eval-159-claude", "eval159_blind.jsonl")]:
    p = REPO / "experiments" / folder / jl
    if p.exists():
        for line in p.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                V36[r["sample"]] = r["pred"]

targets = load_eval_set()
new44 = {t.clip_id for t in load_eval_set_0608()}


def sample_of(t) -> str:
    if t.clip_id in new44:
        stem = t.r2_key.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        return f"sample-{stem}"
    return f"sample-{t.clip_id[:8]}"


def pred_v361(t) -> str:
    s = sample_of(t)
    if s in V361:
        return V361[s]
    if s in V36:
        return V36[s]  # 비-hf 153건은 v3.6=v3.6.1
    return "na"  # 미평가 (미세행동 50건)


def source(t) -> str:
    if t.clip_id in new44:
        return "eval-0608"
    return "uploaded" if "/uploaded/" in t.r2_key else "cam-motion"


def new_name(t) -> str:
    ext = t.r2_key.rsplit(".", 1)[-1].lower()
    return f"{t.gt_action}__{pred_v361(t)}__{t.clip_id[:8]}.{ext}"


def main() -> int:
    names = [new_name(t) for t in targets]
    dups = [n for n, c in Counter(names).items() if c > 1]
    if dups:
        print(f"⚠️ 파일명 충돌 {len(dups)}건 (clip8 더 늘려야): {dups[:3]}")
        return 1

    rows = []
    missing_local = []
    for t in sorted(targets, key=lambda x: (x.gt_action, pred_v361(x), x.clip_id)):
        name = new_name(t)
        p = pred_v361(t)
        rows.append({
            "filename": name, "clip_id": t.clip_id, "gt": t.gt_action,
            "pred_v36": V36.get(sample_of(t), "na"), "pred_v361": p,
            "match": "Y" if t.gt_action == p else ("na" if p == "na" else "N"),
            "species": t.species_id, "source": source(t), "r2_key": t.r2_key,
        })
        if t.clip_id in new44:
            srcf = INBOX / t.r2_key.rsplit("/", 1)[-1]
            if not srcf.exists():
                missing_local.append(srcf.name)

    print(f"203건, mode={'APPLY' if APPLY else 'DRY-RUN'}, 충돌 없음 ✅")
    print(f"match 분포: {dict(Counter(r['match'] for r in rows))}  (Y=일치, N=불일치, na=미평가)")
    if missing_local:
        print(f"⚠️ inbox 누락 {len(missing_local)}: {missing_local[:3]}")
    print("\n이름 예시 (gt/pred/match 다양하게):")
    seen = set()
    for r in rows:
        key = (r["gt"], r["match"])
        if key not in seen:
            seen.add(key)
            print(f"  [{r['match']}] {r['filename']}")

    if not APPLY:
        print(f"\n검수 후: PYTHONPATH=. uv run python scripts/build_dataset_203.py --apply")
        return 0

    # 실제 복사/다운로드
    OUT.mkdir(parents=True, exist_ok=True)
    done = 0
    for t in targets:
        dst = OUT / new_name(t)
        if dst.exists():
            done += 1
            continue
        if t.clip_id in new44:
            shutil.copy2(INBOX / t.r2_key.rsplit("/", 1)[-1], dst)
        else:
            dst.write_bytes(download_clip_bytes(t.r2_key))
        done += 1
        if done % 40 == 0:
            print(f"  {done}/203 ...")
    with (OUT / "manifest.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n완료 {done}/203 → {OUT}  (+ manifest.csv)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
