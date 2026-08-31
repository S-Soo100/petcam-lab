# YOLO26n v2.6 recent dense — 비교학습 완료 보고서

## 1. 결론

YOLO26n v2.6의 matched warm-start / clean-reference 3-seed 비교학습 6회를
완료했다. 학습 내부 validation에서는 `warm-start-s28`이 recall `0.92617`,
mAP50-95 `0.64734`로 잠정 선두다. 다만 이 값은 후보 탐색 참고값이며,
독립 same-protocol validation과 old fixed-test regression 전에는 v2.6 선택 후보나
운영 모델로 확정하지 않는다.

## 2. 고정 입력

- reviewed source commit: `e4566db750f8e0f668d72aeadd6f8305a2361f90`
- dataset status: `V26_DATASET_READY`
- 전체 이미지: 4,471장
- active split: train 3,662장 / validation 505장
- regression 전용: old validation 153장 / old test 151장
- 신규 사람 GT: 2,508장, present 1,465장 / absent 1,043장 / bbox 1,474개
- evaluation tier: development
- sealed future holdout: 별도 필요

학습 manifest 기준 DB / R2 / service write와 deploy는 모두 0이다. 원문 이미지,
사람 GT와 model weight는 private attempt 밖으로 복사하거나 커밋하지 않았다.

## 3. 실행 기간과 비용

- 시작: 2026-08-27 15:24:51 KST
- 완료: 2026-08-31 21:10:56 KST
- 전체 경과시간: 4일 5시간 46분
- 6개 run의 `results.csv` 누적 학습시간 합계: 78시간 43분

`warm-start-s27`은 중간 중단 후 기존 checkpoint에서 이어 실행했으며, 기존 결과를
삭제하거나 덮어쓰지 않고 completion manifest까지 복구했다. 최종 6개 run은 모두
return code 0과 `results.csv`, `best.pt`, completion manifest를 갖는다.

## 4. 학습 내부 validation

| run | 완료 epoch | best epoch | precision | recall | mAP50 | mAP50-95 |
|---|---:|---:|---:|---:|---:|---:|
| warm-start-s26 | 100 | 89 | 0.87863 | 0.86577 | 0.92243 | 0.62489 |
| warm-start-s27 | 83 | 63 | 0.86456 | 0.87584 | 0.92626 | 0.62488 |
| warm-start-s28 | 93 | 73 | 0.87420 | 0.92617 | 0.94695 | 0.64734 |
| clean-reference-s26 | 79 | 59 | 0.85069 | 0.82550 | 0.91235 | 0.59928 |
| clean-reference-s27 | 76 | 56 | 0.81834 | 0.87675 | 0.90842 | 0.59722 |
| clean-reference-s28 | 100 | 97 | 0.90139 | 0.85888 | 0.94429 | 0.64256 |

`warm-start-s28`은 recall이 가장 높아 최근 v2.5 미탐 문제와 관련해 유망하다.
`clean-reference-s28`은 precision이 더 높지만 recall이 낮다. seed 간 차이가 있으므로
한 run의 학습 내부 최고점만으로 운영 후보를 고르는 것은 금지한다.

## 5. 다음 단계

Task 9 evaluation freeze를 다음 순서로 수행한다.

1. 6개 completion manifest, `results.csv`, `best.pt`와 dataset/source/runtime lineage를 독립 검증한다.
2. frozen v2.5 baseline과 합격 v2.6 후보의 validation prediction ledger를 fresh no-overwrite 경로에 각각 한 번 생성한다.
3. 같은 GT·전처리·inference 계약에서 frame precision/recall/specificity와 camera/night strata를 재계산한다.
4. 합격 후보에 대해서만 threshold / NMS / 10fps `3-of-5` temporal rule을 freeze한다.
5. freeze 이후 old fixed-test를 regression 용도로 한 번 실행한다.

Task 9가 통과해도 결과는 development-only `shadow candidate`다. production GME
checkpoint 교체와 라벨링 웹 반영은 sealed future holdout 및 별도 Owner 승인 전에는
수행하지 않는다.
