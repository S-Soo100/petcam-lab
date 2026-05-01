"""dish-presence post-filter — 5룰 + fallback.

스펙: specs/feature-vlm-feeding-postfilter.md §2.3

입력: raw VLM 9-class 출력 + dish_present + licking_behavior
출력: final 9-class 라벨

룰 표 (raw가 drinking|eating_paste 아니면 raw 그대로):

  raw            dish    lick     final
  -----------    ----    ----     -------------
  eating_paste   true    *        eating_paste   (confirm)
  eating_paste   false   true     drinking       (다른 사물 핥음)
  eating_paste   false   false    moving         (먹지도 핥지도 않음)
  drinking       true    *        eating_paste   (그릇 보고 사료 먹는 중)
  drinking       false   *        drinking       (confirm)
  *              *       *        raw            (그대로)
"""
from typing import Optional


FEED_CLASSES = {"drinking", "eating_paste"}


def apply_dish_postfilter(
    raw: str,
    dish_present: Optional[bool],
    licking_behavior: Optional[bool],
) -> str:
    """raw + dish 시그널 → final 라벨.

    dish_present / licking_behavior가 None이면 (router 호출 안 됐거나 실패),
    raw 그대로 반환 — fail-safe.
    """
    if raw not in FEED_CLASSES:
        return raw

    if dish_present is None:
        return raw  # router 결과 없음 — raw 그대로

    if raw == "eating_paste":
        if dish_present:
            return "eating_paste"
        # dish=false: licking 시그널로 분기
        if licking_behavior is None:
            return "drinking"  # licking 결측 시 보수적으로 drinking
        return "drinking" if licking_behavior else "moving"

    # raw == "drinking"
    if dish_present:
        return "eating_paste"
    return "drinking"


def _test() -> None:
    """단위 검증 — 5룰 + fallback 케이스."""
    cases = [
        # (raw, dish, lick, expected, label)
        ("eating_paste", True,  True,  "eating_paste", "rule 1: confirm"),
        ("eating_paste", True,  False, "eating_paste", "rule 1: confirm (lick irrelevant)"),
        ("eating_paste", False, True,  "drinking",     "rule 2: lick other surface"),
        ("eating_paste", False, False, "moving",       "rule 3: not feeding, not licking → moving"),
        ("drinking",     True,  False, "eating_paste", "rule 4: dish + raw drinking → paste"),
        ("drinking",     True,  True,  "eating_paste", "rule 4: dish + raw drinking → paste"),
        ("drinking",     False, True,  "drinking",     "rule 5: confirm"),
        ("drinking",     False, False, "drinking",     "rule 5: confirm"),
        # fallback: raw가 다른 클래스
        ("moving",       True,  True,  "moving",       "fallback: non-feed raw"),
        ("basking",      False, False, "basking",      "fallback: non-feed raw"),
        ("hiding",       True,  False, "hiding",       "fallback: non-feed raw"),
        ("unseen",       False, True,  "unseen",       "fallback: non-feed raw"),
        # router 결측 — fail-safe
        ("eating_paste", None,  None,  "eating_paste", "router 결측: raw 보존"),
        ("drinking",     None,  None,  "drinking",     "router 결측: raw 보존"),
        # licking 결측만
        ("eating_paste", False, None,  "drinking",     "licking 결측 + dish=false: 보수적 drinking"),
    ]
    fail = 0
    for raw, dish, lick, expected, label in cases:
        got = apply_dish_postfilter(raw, dish, lick)
        ok = got == expected
        mark = "✓" if ok else "✗"
        print(f"  {mark} [{label}]")
        print(f"     raw={raw}, dish={dish}, lick={lick} → {got} (expected {expected})")
        if not ok:
            fail += 1
    print()
    print(f"단위 검증: {len(cases) - fail}/{len(cases)} 통과")
    if fail:
        raise SystemExit(f"{fail} 실패")


if __name__ == "__main__":
    _test()
