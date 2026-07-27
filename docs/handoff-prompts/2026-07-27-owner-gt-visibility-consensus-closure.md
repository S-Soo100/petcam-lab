# Owner GT · Visibility ROI · VLM Consensus 연구 정리

## 현재 판정

`RESEARCH_CHAIN_CLOSED_CONSENSUS_SHADOW_PENDING`

2026-07-27 연구 흐름은 아래 순서로 연결된다.

1. Owner GT 172건 감사
2. Owner GT × Python Evidence motion signal benchmark
3. legacy GT를 포함한 통합 실패 감사
4. visibility ROI current-baseline 재현
5. read-only 독립 교차검수
6. 위험 라벨 VLM 3회 consensus shadow 설계

여기까지의 결론은 ROI를 production에 추가하는 것이 아니라, VLM 판정 변동을 별도 shadow
원장으로 측정하면서 fresh 사람 GT를 2~3주 축적하는 것이다.

## 1. Owner GT 데이터 판정

Owner GT 데이터 자체는 실패하지 않았다.

- completed GT 172 clips
- 필수 key·enum·segment 무결성 위반 0
- Python Evidence 172/172, level0/level1 `ok`
- Gate/prelabel 172/172
- 2 cameras, 3 days, 39 five-minute episodes
- rare care primary 4 clips

따라서 기술 coverage와 retrospective diagnostic에는 사용할 수 있다. 다만 production 일반화,
rare-class recall, selector adoption에는 다양성이 부족하다.

정본:

- `experiments/owner-gt-audit-20260727/REPORT.md`
- branch `codex/owner-gt-audit-20260727` @ `53fb5b238c3e`

## 2. 실패한 가설

실패한 것은 Owner GT가 아니라 raw Python Evidence `roi_mean`을 전 카메라 공통 motion 신호로
사용하려던 가설이다.

- pooled AUROC `0.7133`
- camera_1 AUROC `0.4832`
- camera_2 AUROC `0.8227`
- camera_1 static-only 표본 7
- verdict `PE_MOTION_SIGNAL_INCONCLUSIVE`

카메라별 방향이 일치하지 않으므로 global threshold, 자동 제외, activity filter, selector rank에
사용하지 않는다. 사후 normalization·threshold tuning도 하지 않는다.

정본:

- `experiments/owner-gt-python-evidence-benchmark-20260727/REPORT.md`
- branch `codex/owner-gt-python-evidence-benchmark-20260727` @ `dd92a0950ea1`

## 3. 통합 감사와 ROI 판정

Owner GT에 legacy GT를 합쳐 중복을 제거했을 때 431 unique clips / 122 episodes가 됐고,
visibility/scale/occlusion이 반복 VLM 실패 후보로 좁혀졌다. 그러나 historical error-selected
44 clips를 현행 `v4.0 + six-768q85-v1 + claude-sonnet-5`로 재측정한 결과:

- pass 간 label 변경 10/44
- 같은 non-`moving` 유지 7/44
- 3/3 stable error의 수학적 상한 7
- Phase 1 진입 기준 10 clips에 도달 불가
- verdict `VISIBILITY_ROI_REJECT_NO_CURRENT_REPRODUCIBLE_FAILURE`

이는 ROI가 무효라는 뜻이 아니다. 현재 조건에서 ROI 투자를 정당화할 안정적인 반복 실패 표적이
부족하다는 뜻이다. read-only 교차검수는 계산·해석·민감정보 경계를 모두
`CROSS_REVIEW_PASS`로 확인했다.

정본:

- `experiments/unified-gt-failure-audit-20260727/REPORT.md`
- `experiments/visibility-bbox-roi-20260727/REPORT.md`
- branch `codex/visibility-bbox-roi-20260727`

## 4. 다음 운영 연구

### 사람 교차검수

- 이중 블라인드 라벨링을 2~3주 운영한다.
- 같은 clip을 두 라벨러가 독립 판정한다.
- 불일치는 Owner가 최종 해결한다.
- clip 수뿐 아니라 camera, camera-night, five-minute episode, 행동별 분포를 함께 기록한다.

### VLM consensus shadow

- 첫 production VLM 결과는 그대로 유지한다.
- 첫 batch에 위험 action이 하나라도 있으면 같은 frames·prompt·model·clip order로 두 번 더
  판독한다.
- 세 attempt는 production 결과와 분리된 append-only 원장에 저장한다.
- 만장일치·2대1·완전 불일치와 행동별 변동을 측정한다.
- consensus 결과로 app, Slack, GT, behavior, selector를 자동 변경하지 않는다.
- 2~3주 뒤 사람 최종 GT와 1회 판정/3회 consensus를 비교해 production 채택 여부를 결정한다.

활성 계획 브랜치:

- Lab DB ledger plan:
  `codex/vlm-risk-consensus-ledger-plan` @ `afbffd67e136`
- Nightly worker plan:
  `codex/vlm-risk-consensus-shadow-design` @ `bf7011686e65`

두 브랜치는 설계·구현계획만 완료됐다. production migration apply, main merge, Mac mini install/run은
아직 하지 않았다.

## 5. 브랜치 정리

연구 정본 브랜치:

- `codex/visibility-bbox-roi-20260727`

아래 브랜치는 위 정본의 ancestor이며 이력 보존용이다. 별도 재개하지 않는다.

- `codex/owner-gt-audit-20260727`
- `codex/owner-gt-python-evidence-benchmark-20260727`
- `codex/unified-gt-failure-audit-20260727`

원격 branch 삭제나 main merge는 이번 정리에서 하지 않는다.

## 6. 다음 세션 재개점

1. Lab ledger plan의 Task 1부터 새 clean implementation session에서 다시 시작한다.
2. 이전 SDD 실패가 만든 미커밋 Task 1 파일을 재사용하지 않는다.
3. Lab 원장 구현·검수 완료 후 Nightly worker Task 1부터 실행한다.
4. 두 브랜치 전체 회귀·독립 리뷰 후 별도 deployment handoff를 만든다.
5. 배포 후에도 feature flag 기본값은 false이며 Owner의 runtime 승인 전에는 shadow를 켜지 않는다.

## 금지 경계

- 현재 production 결과 덮어쓰기
- ROI/bbox/crop/detector 재도입
- prompt/threshold/selector tuning
- consensus 다수결의 자동 GT·행동 라벨 승격
- fresh holdout과 historical diagnostic set 혼합
- 연구 브랜치의 임의 main merge·deploy
