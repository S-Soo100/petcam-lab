"""평가셋 정리 (2026-06-13): defecating 16건 폐기 + cf698b78 평가부적합 제외. 202→185. 임시.

사용자 결정(대화):
- defecating 클래스 폐기 (잔류물 육안확인·3일1회·판정난도 → v4.0에서 클래스 제외).
- cf698b78 (drinking GT지만 60초 이동 dominant, 단일행동 평가 부적합 — 사용자 영상 직접 확인).

방식: manifest.csv 수정(백업) + dataset-203 파일 `_excluded/` 이동(삭제 X, 되돌리기 가능).
DB(behavior_logs)는 보류 — Gemini 퇴역으로 DB 회귀(eval_vlm_worker_regression) 무의미,
Claude 트랙은 dataset-203 manifest 가 SOT. (DB sync 필요 시 별도)

실행: PYTHONPATH=. uv run python scripts/_cleanup_eval_185.py [--apply]
"""
from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path

DS = Path("/Users/baek/petcam-lab/storage/dataset-203")
EXCL = DS / "_excluded"
APPLY = "--apply" in sys.argv


def drop(r: dict) -> str | None:
    if r["gt"] == "defecating":
        return "defecating 폐기 (클래스 정책)"
    if r["clip_id"][:8] == "cf698b78":
        return "cf698b78 평가부적합 (60초 이동 dominant, 사용자 확인)"
    return None


def main() -> int:
    rows = list(csv.DictReader(open(DS / "manifest.csv")))
    fields = list(rows[0].keys())
    keep = [r for r in rows if not drop(r)]
    remove = [(r, drop(r)) for r in rows if drop(r)]

    print(f"{'APPLY' if APPLY else 'DRY-RUN'}: {len(rows)} → {len(keep)} (제거 {len(remove)})")
    for r, reason in remove:
        print(f"  - {r['clip_id'][:8]} {r['gt']:12s} [{reason}]")

    if not APPLY:
        print("\n실제 적용: --apply")
        return 0

    EXCL.mkdir(exist_ok=True)
    moved = 0
    for r, _ in remove:
        src = DS / r["filename"]
        if src.exists():
            shutil.move(str(src), str(EXCL / r["filename"]))
            moved += 1
        else:
            print(f"  ⚠️ 파일 없음(skip): {r['filename']}")
    shutil.copy(DS / "manifest.csv", DS / "manifest.csv.bak-202")
    with (DS / "manifest.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(keep)
    print(f"\n✅ 파일 {moved}개 → _excluded/ · manifest {len(keep)}행 (백업 manifest.csv.bak-202)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
