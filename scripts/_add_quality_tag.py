"""manifest.csv 에 quality_tag + tag_basis 2컬럼 추가 (B1 층화 태그).

cherry-pick 금지 원칙의 합법적 대안 — 어려운 샘플을 제거하지 않고 태그로 층화 집계.

태깅 정책 (2026-06-15):
- drinking 17건: **육안 판정 (basis=visual)** — closeup/handheld-challenging/production-like.
  적응형@1080 frames(v40-regression 재활용) 대표 프레임 1장씩 확인.
- cam-motion (운영 고정 카메라): **production-like (basis=heuristic)** — 출처가 곧 환경이라 신뢰도 높음.
- uploaded / eval-0608 의 비-drinking: **untagged (basis=none)** — drinking 육안에서
  source 가 quality 를 예측 못 함을 확인(eval-0608·uploaded 둘 다 closeup/handheld/production 섞임).
  거짓 휴리스틱 대신 빈 값으로 두고 필요 시 점진 육안 보정.
- eval-0615 2건(akze/ju): drinking visual 에 포함(closeup).

tag_basis = visual(육안) / heuristic(출처 추정) / none(미태깅). 층화 분석 시 visual 만 신뢰하거나
heuristic 포함 여부를 선택할 수 있게 분리.

실행: uv run python scripts/_add_quality_tag.py  (멱등 — 이미 컬럼 있으면 값만 갱신)
"""
from __future__ import annotations

import csv
import shutil
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "storage" / "dataset-203" / "manifest.csv"
BACKUP = MANIFEST.with_name("manifest.csv.bak-187-preqtag")

# drinking 17건 육안 판정 (clip_id 앞 8자 → quality_tag)
VISUAL: dict[str, str] = {
    # closeup — 게코 크게/혀 또렷/가까움 (쉬운 샘플, 상한선)
    "3d46364a": "closeup", "6d9d504f": "closeup", "71889c3c": "closeup",
    "00c089c8": "closeup", "3369d723": "closeup",
    "d6c57474": "closeup", "9e9f164b": "closeup",  # eval-0615 akze3466 / ju10615
    # handheld-challenging — 응결수 흐림/원거리/뭉갬 (하드 샘플)
    "7124cebe": "handheld-challenging", "685911a0": "handheld-challenging",
    "b5637a1a": "handheld-challenging", "f4b33f32": "handheld-challenging",
    "2c1be3dd": "handheld-challenging", "c9bc5878": "handheld-challenging",
    "d95e9eaa": "handheld-challenging",
    # production-like — 원거리지만 안정·게코 중간·판정됨 (제품 타겟 난이도)
    "036a650d": "production-like", "6a24c2e6": "production-like", "bf83c4cf": "production-like",
}


def main() -> int:
    shutil.copy(MANIFEST, BACKUP)
    rows = list(csv.reader(MANIFEST.open()))
    header, data = rows[0], rows[1:]
    ci = {name: i for i, name in enumerate(header)}

    # 멱등: 기존 quality_tag/tag_basis 컬럼 있으면 잘라내고 재생성
    base_cols = [c for c in header if c not in ("quality_tag", "tag_basis")]
    base_idx = [header.index(c) for c in base_cols]
    new_header = base_cols + ["quality_tag", "tag_basis"]

    out = [new_header]
    dist: Counter = Counter()
    for r in data:
        clip8 = r[ci["clip_id"]][:8]
        source = r[ci["source"]]
        if clip8 in VISUAL:
            qtag, basis = VISUAL[clip8], "visual"
        elif source == "cam-motion":
            qtag, basis = "production-like", "heuristic"
        else:
            qtag, basis = "", "none"
        out.append([r[i] for i in base_idx] + [qtag, basis])
        dist[(qtag or "(untagged)", basis)] += 1

    with MANIFEST.open("w", newline="") as f:
        csv.writer(f).writerows(out)

    print(f"backup → {BACKUP.name}")
    print(f"총 {len(data)}건 태깅 완료 (컬럼 {len(new_header)}개)\n")
    print("=== quality_tag × tag_basis 분포 ===")
    for (tag, basis), n in sorted(dist.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {tag:22} [{basis:9}] : {n}")

    # drinking 17 층화 (제품 1순위 클래스 검증)
    print("\n=== drinking 17건 층화 (visual) ===")
    dr = Counter()
    for r in out[1:]:
        gt = r[base_cols.index("gt")]
        if gt == "drinking":
            dr[r[-2] or "(untagged)"] += 1
    for tag, n in sorted(dr.items(), key=lambda x: -x[1]):
        print(f"  {tag:22}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
