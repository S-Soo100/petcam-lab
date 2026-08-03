# RBA Dataset v2 Implementation Plan

**상태:** `READY_AFTER_OWNER_CLEANUP_REVIEW` — 구현 준비 완료, 897개 Owner 정리 판단 완료 전 materialize 금지.

**목표:** 기존 `dataset-203`의 실제 197개 정본은 그대로 보존하면서, 최근 Owner-final GT와 이번
초기 영상 정리에서 `keep`으로 확정된 유효 영상만 더해 새 Dataset v2를 만든다.

**핵심 원칙:** Dataset은 사람이 확인한 사실만 담고, OpenAI·과거 VLM·local VLM·Python Evidence
예측은 별도 prediction ledger에 저장한다. 같은 카메라의 같은 밤이 train과 평가에 갈라져 답을
외우는 일이 없게 camera-night 단위로 분리한다.

## 입력 Gate

- legacy dataset: 이름은 `dataset-203`이지만 frozen manifest의 실제 영상 197개를 digest와 함께 보존
- recent source: Owner-final GT가 있고 R2 HEAD가 성공하는 영상
- cleanup source: `rba_owner_media_cleanup_decisions.decision='keep'`만 허용
- 금지: pending, uncertain, delete 후보/확정, source_missing, 미결 quarantined, 자동 라벨, VLM 예측
- future holdout: 만들 때부터 별도 manifest/digest로 봉인하고 모델·프롬프트 선택에 사용 금지

---

### Task 1: 입력 정본과 제외 규칙 동결

**Files:**
- Create: `experiments/rba-dataset-v2/TEST-SHEET.md`
- Create: `scripts/prepare_rba_dataset_v2.py`
- Create: `tests/test_prepare_rba_dataset_v2.py`

- [ ] legacy 197개의 기존 manifest와 media digest를 읽기 전용으로 재검증한다.
- [ ] Owner cleanup 진행률이 `completed=available`인지 확인하고, 아니면 fail-closed한다.
- [ ] eligible source마다 `owner_final`, `cleanup_keep`, `legacy_frozen` 중 하나의 provenance만 기록한다.
- [ ] R2 HEAD 2회, clip 중복 0, 제외 원장과 교집합 0을 확인한다.

### Task 2: 여러 행동을 잃지 않는 사람 GT 스키마

**Files:**
- Create: `specs/rba-dataset-v2-schema.md`
- Create: `tests/fixtures/rba_dataset_v2/`

- [ ] 영상 하나에 `primary_behavior` 하나만 강제하지 않고 `segments[]`를 둔다.
- [ ] 각 segment는 `start_sec`, `end_sec`, `behavior`, `target`, `visibility`, `owner_final_source`를 가진다.
- [ ] 같은 영상에 여러 행동과 전환이 있으면 순서대로 모두 보존한다.
- [ ] 구간 겹침·범위 초과·음수·빈 행동·영상 길이 불일치를 validator가 차단한다.
- [ ] 사건 경계 연구 결과는 참고 provenance일 뿐, 자동 segment 정답으로 복사하지 않는다.

### Task 3: Dataset v2 manifest 생성

**Files:**
- Create: `scripts/build_rba_dataset_v2.py`
- Create: `tests/test_build_rba_dataset_v2.py`
- Create at runtime: private media manifest and public aggregate report

- [ ] legacy 197개는 행·GT·digest를 수정하지 않고 `legacy_frozen` partition으로 포함한다.
- [ ] 최근 Owner-final 및 cleanup keep 영상은 새 UUID가 아니라 원래 clip identity로 포함한다.
- [ ] manifest에는 media identity, 사람 GT, provenance, camera-night stratum, digest만 둔다.
- [ ] model name, prompt, prediction, confidence, cost는 manifest에 넣지 않는다.
- [ ] 전체/행동/카메라/밤/다중행동 분포를 공개 aggregate로 만든다.

### Task 4: 누수 없는 split과 future holdout 봉인

- [ ] 동일 `camera_id + activity_day`는 한 split에만 들어가게 group split한다.
- [ ] 같은 clip·인접 파생 clip·같은 사건이 train/validation/holdout에 동시에 나타나지 않게 검사한다.
- [ ] 행동 희소군은 수량을 숨기지 말고 분포표와 부족 경고를 낸다.
- [ ] future holdout은 clip 목록과 digest를 별도 private artifact로 만들고 일반 개발 runner에서 차단한다.
- [ ] split을 세 번 다시 계산해 같은 seed에서 digest가 동일한지 확인한다.

### Task 5: Prediction ledger 분리

**Files:**
- Create: `specs/rba-prediction-ledger-v1.md`
- Create: `tests/test_rba_prediction_ledger_contract.py`

- [ ] OpenAI API pilot 결과는 `dataset_version + clip_id + model + prompt/schema version + usage + output`으로 별도 저장한다.
- [ ] 예측이 Dataset v2 사람 GT를 UPDATE하거나 manifest에 섞이지 못하게 정적/DB 계약으로 차단한다.
- [ ] 비용·오류·retry는 예측 run 단위로 남기고, 자동 skip·자동 사건 병합은 지원하지 않는다.

### Task 6: 검증과 인계

- [ ] private manifest에 개인정보·secret이 없고 public 보고서에 clip/R2 key/원문 GT가 없는지 감사한다.
- [ ] 전체 테스트, schema validator, R2 이중 preflight, split leakage test를 통과한다.
- [ ] Dataset v2 version, row count, multi-action count, strata 분포, digest를 보고한다.
- [ ] 그 뒤에만 같은 frozen 300 human-first 표본으로 OpenAI API 행동·관찰 pilot 계획을 연다.

## 지금 가능한 일 / 기다릴 일

- 지금: 코드·TEST-SHEET 작성과 legacy 197 read-only 재검증
- 기다림: Owner가 cleanup 897개를 모두 판단
- 이후: `keep`만 합쳐 Dataset v2를 materialize하고 future holdout을 봉인
