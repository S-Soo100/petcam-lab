# YOLO26n v2.6.1 recent·unused hard-case 확장 설계

**상태:** 사람 bbox·export 검증·후속 코드 구현/단위 테스트 완료 / private 실행 승인 대기
**승인일:** 2026-09-04 KST
**목적:** v2.6 이후 새 영상과 v2.6 미사용 영상을 폭넓게 사람 bbox 후보로 만들고, 반사·가림·배경
오탐·실제 게코 누락·과대 bbox를 보강한다.

## 결정

1. cutoff 이후 production clip을 먼저 고정 snapshot으로 잡는다.
2. 그중 최소 3개 camera-night, 300 clip은 future holdout으로 봉인하고 frame·GT를 열지 않는다.
3. 남은 post-v2.6 clip은 영상당 최소 1장 coverage 후보를 만든다.
4. v2.6 미사용 historical clip은 GME 품질 이상 상위와 모델 점수와 무관한 IID control을 함께 뽑는다.
5. Owner가 확정한 4개 복합 오류 영상은 오류 구간 주변을 더 촘촘히 뽑는다.
6. GME는 후보 신호일 뿐 정답이 아니다. 사람의 blind presence+bbox만 학습 GT가 된다.

## 데이터 역할

| 데이터 | 역할 | 금지 |
|---|---|---|
| post-v2.6 future 300 clip | 독립 미래 평가 source | frame 열람·후보 채굴·threshold 선택 |
| post-v2.6 나머지 | 새 분포 coverage·hard-case 개발 | 자동 GT화 |
| v2.6 미사용 historical | 반사·가림·오탐·미탐 다양성 보강 | v2.6 사용 frame 재편입 |
| Owner 확정 4개 | 고밀도 오류 교정 | 동일 정지 장면 무제한 복제 |
| GME quality summary | detector 오류 가능성 순위 | present/absent/bbox 정답 |
| 활동시간 불일치 | GME activity 알고리즘 별도 후보 | YOLO bbox 오류로 혼합 |

## 후보 추출

- 일반 coverage: 영상 전체에서 균일 1fps 후보를 만들되 최종 큐에서는 clip별 상한을 둔다.
- hard-case: detection gap·fragmentation·position jump·복수 box·zero-visible 주변은 최대 5fps로 보강한다.
- Owner 확정 구간: 구간 전후 1초를 포함해 5fps, 나머지 영상은 1fps로 본다.
- exact SHA는 전역 중복 제거한다.
- dHash distance `<=2`는 같은 clip의 반복 frame을 제거한다. source coverage 보존을 위해 clip당 최대
  2장, Owner-confirmed 복합 오류 4개에는 최대 20장의 near-duplicate 예외를 허용한다.
- v2.6 selected image SHA/dHash와 old protected fingerprint에 겹치면 제외한다.
- frame random split은 금지하고 clip/인접 episode 단위로 train/validation을 분리한다.

## 사람 경험

`[화면]` 예측 박스·GME 점수·source 정보가 없는 frame을 본다.
`[조작]` 게코 있음/없음/불확실/영상 오류를 고른다.
`[반응]` 있음이면 보이는 실제 게코마다 tight bbox를 직접 그린다. 반사상은 실제 개체와 별도 표시
규칙에 따라 판정하고, 식물·코르크·선반은 bbox에 넣지 않는다.
`[감정]` 모델 답을 고치는 일이 아니라 화면의 사실을 독립 기록한다고 느낀다.

## 성공·중단 조건

- future holdout: 300 clip, 양 카메라, 최소 3 nights, development overlap 0
- source snapshot·selection manifest·R2 GET 결과·frame SHA/dHash를 private append-only artifact로 보존
- v2.6 사용 source는 Owner-confirmed 예외 외 제외하고, 예외도 frame fingerprint 중복은 제외
- blind ZIP에는 source/GME/model prediction을 넣지 않음
- DB write, R2 write/delete, service/model/labeling web deploy 0
- holdout shortage, protected overlap, source drift, decode 실패 은폐, selected frame 0이면 fail closed
- 개별 R2 object missing·decode 불가 영상은 자동 대체하지 않고 token·오류 종류·exact count로 격리한 뒤
  나머지 큐를 계속 만든다. 누락률이 5%를 넘으면 queue ready를 선언하지 않는다.

## 완료 순서

- [x] source snapshot과 300-clip future holdout 봉인
- [x] post-v2.6 development·historical anomaly/IID source 선택
- [x] private 원본 GET과 decode 감사
- [x] dense candidate 추출과 전역 dedup
- [x] blind CVAT ZIP·review index·독립 integrity report
- [x] 사람 bbox와 CVAT export 동결·무결성 검증
- [x] v2.6.1 dataset/train/validation 구현 계획 작성
- [x] GT normalizer·dataset builder·training runner·evaluator 구현과 단위 테스트
- [ ] private GT normalize·dataset build·학습·평가는 각 단계 별도 실행 승인

## 사람 GT 동결 결과

- 검수 대상: 4,096 images
- 실제 게코 bbox가 있는 image: 2,699
- 사람 확인 empty image: 1,397
- 실제 게코 bbox: 2,732
- uncertain/media_error: 0 / 0
- CVAT export 3개와 queue part의 익명 filename·순서가 정확히 일치한다.
- label set, image bounds, bbox 양의 면적, tag 충돌, 전역 익명 번호 `1..4096` 검사를 통과했다.
- export는 private `cvat-export-v1`에 원본 ZIP 그대로 동결했으며 기존 queue와 export를 삭제하거나
  덮어쓰지 않았다.
- 후속 실행 정본은
  `docs/superpowers/plans/2026-09-04-yolo26n-v261-dataset-training-validation.md`다.
