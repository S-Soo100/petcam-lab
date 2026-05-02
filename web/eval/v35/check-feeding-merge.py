"""feeding-merge 매핑 일치 검증.

목적: web/src/types.ts `toFeedingMerged()` ↔ Python `FEEDING_MERGE`
      양쪽 정의가 동치인지 9 케이스로 단언.

매핑 정의 단일 SOT는 web/src/types.ts (UI 노출이 본질).
Python 평가 스크립트는 미러 — 변경 시 반드시 양쪽 갱신.

실행:
  uv run python web/eval/v35/check-feeding-merge.py

실패 시 양쪽 정의를 같게 맞춘 뒤 재실행.

연관:
  - spec: specs/feature-vlm-feeding-merge-ux.md
  - 메모리: feedback_vlm_ux_merge_validation.md
"""
from __future__ import annotations

# Python 측 매핑 (analyze-v35-full.py FEEDING_MERGE의 미러)
FEEDING_MERGE = {"drinking": "feeding", "eating_paste": "feeding"}


def to_feeding_merged(action: str) -> str:
    return FEEDING_MERGE.get(action, action)


# 9 케이스: BEHAVIOR_CLASSES 9개 모두 입력 → 기대 출력
# (web/src/types.ts BEHAVIOR_CLASSES 순서대로)
CASES: list[tuple[str, str]] = [
    ("eating_paste", "feeding"),   # merged
    ("eating_prey", "eating_prey"),
    ("drinking", "feeding"),       # merged
    ("defecating", "defecating"),
    ("shedding", "shedding"),
    ("basking", "basking"),
    ("hiding", "hiding"),
    ("moving", "moving"),
    ("unseen", "unseen"),
]


def main() -> None:
    fail = 0
    for inp, expected in CASES:
        actual = to_feeding_merged(inp)
        ok = actual == expected
        mark = "✓" if ok else "✗"
        print(f"  {mark} {inp:14s} → {actual:14s} (expected {expected})")
        if not ok:
            fail += 1
    print()
    n = len(CASES)
    print(f"매핑 일치: {n - fail}/{n} 통과")
    if fail:
        raise SystemExit(
            f"{fail} 실패 — web/src/types.ts toFeedingMerged()와 동기화 필요"
        )


if __name__ == "__main__":
    main()
