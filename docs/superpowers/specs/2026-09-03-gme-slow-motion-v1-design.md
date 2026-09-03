# GME 느린 움직임 판정 v1 설계

> 상태: `APPROVED_FOR_IMPLEMENTATION`
>
> 승인일: 2026-09-03 KST

## 목표

YOLO가 게코를 계속 추적하지만 0.1초 단위 변위가 작아 `static`으로만 기록되는 느린 이동을
관측 움직임 시간에 포함한다. 기존 `gme-motion-v0` 원장은 수정하지 않고 새
`gme-motion-v1` 결과를 append-only로 추가한다.

## 판정

- 기존 0.1초 즉시 변위 판정은 유지한다.
- 같은 track의 3초 중심 시간창 양끝 bbox 중심 순이동이 몸 크기의 8% 이상이면 해당 중심 시점을
  `moving`으로 승격한다.
- 3초 창의 80% 이상이 연속 관측되고 인접 track point 간격이 0.25초 이하여야 한다.
- 카메라 움직임은 계속 local track 상태보다 우선하며, track 단절을 가로질러 계산하지 않는다.
- 단순 박스 떨림을 누적하는 path length는 쓰지 않는다.

## 운영 버전 격리

- queue·run 정본은 `(clip, engine schema, algorithm, detector identity)`를 유지한다.
- worker claim, historical/live enqueue, 웹 overlay와 관측 시간 조회는 algorithm까지 정확히 고정한다.
- DB 읽기 계약을 먼저 배포하고 웹은 v0를 유지한 채 v1 canary를 실행한다.
- 문제 영상과 정지 음성 구간이 통과한 뒤 live trigger와 웹 active algorithm을 v1로 전환한다.
- 과거 영상은 신규 v1 job으로 재계산하며 v0 job/run/artifact는 삭제하거나 덮어쓰지 않는다.

## 사용자 체험

- **[화면]** 상세를 열면 재생 전부터 느린 이동까지 반영된 움직임 시간이 보인다.
- **[조작]** 48초 부근으로 이동한다.
- **[반응]** 실제로 천천히 이동한 구간은 초록 움직임 상태로, 앞선 정지 구간은 회색으로 남는다.
- **[감정]** 사용자는 YOLO 박스가 보이는 시간과 실제 움직인 시간을 구분해 신뢰할 수 있다.

## 완료 조건

1. 문제 영상은 기존 0초에서 움직임이 0초 초과로 바뀐다.
2. 같은 영상의 3~29초 정지 구간은 움직임 0초를 유지한다.
3. 합성 bbox jitter 회귀 표본은 `static`을 유지한다.
4. worker가 다른 algorithm job을 claim하거나 다른 버전으로 저장하지 않는다.
5. 웹이 active algorithm과 다른 과거 결과로 fallback하지 않는다.
6. 기존 v0 원장·사람 GT·원본 영상은 불변이다.
