# RBA Owner Media Cleanup v1 — Preflight

검사일: 2026-08-03 KST

## 고정 범위

- 초기 두 camera-day의 영상: 951개
- Owner가 이미 확정한 삭제 대상: 46개
  - 게코가 안 보임: 23개
  - 실제 게코 활동 없음: 23개
- canonical GT 보호: 1개
- Owner 재검수 예정: 904개
- 삭제 대상과 canonical GT 중복: 0개
- clip 중복: 0개

## R2 실객체 검사

- 영상 원본 존재: 944/951
- 썸네일 원본 존재: 943/951
- 원본이 이미 없던 영상: 7개
- 7개는 전부 Owner 재검수 예정 partition이며, 삭제 46개와 canonical GT 1개는 모두 존재했다.
- R2 전체 경로를 다시 찾아도 7개는 다른 경로에서 발견되지 않았다.
- 기존 short-device-error 원장 11개는 새 판단으로 덮지 않고 같은 cleanup scope에서 재사용했다.

## 실행 판정

`GO_WITH_SOURCE_MISSING_PARTITION`

7개를 있는 것처럼 복구하거나 다른 영상으로 바꾸지 않고 `source_missing`으로 분리한다. 존재하는
944개에만 copy→HEAD 일치→DB CAS→원본 삭제 순서를 적용하고, 물리 삭제 권한은 사람 확정 46개로
제한한다. 모델·Python Evidence·Gate 결과는 삭제 근거로 쓰지 않는다.
