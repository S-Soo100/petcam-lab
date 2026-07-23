# 쳇바퀴 에피소드 중복 묶음 — 제품 종료 기록

**날짜:** 2026-07-23  
**branch:** `codex/wheel-episode-boundary-fix`  
**최종 제품 판정:** `AUTOMATION_REJECTED_LOW_UTILITY`

## 결론

10분 경계 chaining 결함은 교정됐고 기계 계약은 모두 통과했다. 그러나 실제 fresh 779개에서
검토량은 643개로 줄어드는 데 그쳤다. 감소율은 17.46%이며, 합의한 50% 기준을 충족하지 못했다.

채택 품질을 확인하려면 80그룹·300 clip을 사람이 추가 감사해야 한다. 이는 136개 검수를
줄이기 위한 검증 비용으로 과도하다. 따라서 owner는 추가 감사를 생략하고 자동 중복 묶음
연구를 종료하기로 결정했다.

## 독립 재계산

```text
fresh_total = 779
representatives = 164
ungrouped = 479
actual_review = 164 + 479 = 643
saved = 779 - 643 = 136
reduction = 1 - 643 / 779 = 0.174583 = 17.46%
```

그룹 분포:

```text
size 2: 25 groups
size 3: 22 groups
size 4: 9 groups
size 5: 7 groups
size 6: 9 groups
size 7: 5 groups
size 8: 3 groups
```

대표 수와 멤버 수가 같아 절감이 0인 그룹은 27개·56 clip이다.

## 판정 우선순위

1. `BOUNDARY_CORRECTION_READY_FOR_OWNER_REVIEW`
   - 의미: 10분 경계 버그의 기계적 교정 성공
   - 채택 의미 없음
2. `AUTOMATION_REJECTED_LOW_UTILITY`
   - 의미: 실제 workload reduction 부족으로 제품 채택 거부
   - **최종 판정이며 1번보다 우선**

## 후속 조치

- owner blind audit 취소
- threshold·ROI·IR/day 추가 튜닝 금지
- main merge·UI 연결·canary·배포 금지
- 자동 label/hold/skip 연결 금지
- 기존 수동 라벨링 유지
- branch·코드·artifact는 실패 근거로 보존

다시 제안하려면 동일 알고리즘의 추가 튜닝이 아니라, 실제 fresh 검수량을 사전 등록 기준으로
50% 이상 줄일 수 있는 새로운 증거와 독립 계획이 필요하다.
