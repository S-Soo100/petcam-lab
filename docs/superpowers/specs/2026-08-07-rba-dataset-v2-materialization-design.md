# RBA Dataset v2 Materialization Design

**상태:** OWNER_APPROVED_DESIGN

## 1. 목표

기존 `dataset-203`의 frozen 197개와 최근 canonical Owner-final GT 영상을 합쳐, 새 영상을
안전하게 계속 추가할 수 있는 버전형 Dataset v2를 만든다. Dataset v2는 사람 정답과 원본
provenance만 보존하며 GME·OpenAI·과거 VLM 예측은 포함하지 않는다.

## 2. 채택한 접근

`exact316`을 영구 계약으로 삼지 않는다. 첫 materialization의 기대 기준은 legacy 197개와 기존
recent 119개지만, 입력을 media hash와 source clip identity로 중복 제거한 뒤 실제 행 수를 확정한다.

- 요청 영상이 recent 119에 이미 있으면 최신 canonical GT로 교정하고 전체 수는 316을 유지한다.
- 요청 영상이 새 eligible media이면 새 행으로 추가해 전체 수는 317이 된다.
- 이후 새 영상도 새 dataset version을 만들 때 같은 규칙으로 추가한다.
- 이미 봉인된 version의 manifest와 GT는 수정하지 않는다.

## 3. 입력 경계

### 3.1 Legacy partition

- `storage/dataset-203/manifest.csv`의 실제 frozen 197행을 읽는다.
- 기존 행동 GT는 그대로 보존한다.
- Owner가 일괄 확정한 `highlight=include`를 기록한다.
- 당시 측정하지 않은 행동 구간은 `not_measured`로 남긴다.
- 원본 dataset-203 파일과 manifest는 수정하지 않는다.

### 3.2 Recent partition

다음을 모두 만족한 영상만 포함한다.

1. `clip_purpose=production`이거나 역사 데이터에서 production 자격이 별도로 확인된다.
2. canonical GT head가 `final`이고 최신 revision을 가리킨다.
3. R2 원본이 두 번의 HEAD 검사에서 존재하고 실제로 디코딩된다.
4. media SHA-256과 source clip identity가 다른 포함 행과 중복되지 않는다.
5. cleanup 상태가 `keep`이거나 cleanup 비대상 정상 영상이다.
6. `test`, `pending`, `uncertain`, 삭제·격리·source missing 대상이 아니다.

Owner detail session, 과거 consensus, blind submission이 서로 다르면 canonical GT revision만 정답으로
채택한다. 과거 값은 provenance reference로만 남긴다.

## 4. 요청 영상 계약

clip `2842fdf8-40b5-4f73-aaec-dbc6d8e84360`은 materialization 시 다음 최신 canonical GT를 읽는다.

- primary action: `eating_paste` (`슈퍼푸드 자율급여`)
- segment 1: `licking`, `0.0 <= t < 11.0`
- segment 2: `moving`, `11.0 <= t <= media_duration`
- visibility: 기존 canonical 값 보존

`상단 중앙`은 현재 정식 GT 필드가 없으므로 자유문자열 위치 정답으로 만들지 않는다. 향후 공간
annotation schema가 생기면 별도 revision으로 추가한다.

## 5. Manifest 구조

Dataset version마다 private JSONL manifest와 공개 aggregate report를 만든다. 각 private row는 최소한
다음을 가진다.

```text
schema_version
dataset_version
sample_id
source_partition
source_clip_id
source_dataset
media_sha256
media_duration_sec
isolated_media_key
primary_action
observed_actions[]
segments[]
visibility
quality_tags[]
uncertainty
gt_revision
gt_provenance
camera_night_group
dataset_role
```

- `sample_id`는 source identity와 media hash에서 결정론적으로 만든다.
- `segments[]`는 시간순이며 음수, 영상 범위 초과, 역전 구간을 금지한다.
- `not_measured`와 빈 배열을 구분한다.
- 모델명, prompt, confidence, reasoning, GME 판정은 넣지 않는다.
- 공개 보고서에는 clip ID, R2 key, 원문 GT, 개인정보를 넣지 않는다.

## 6. 버전과 split

- 첫 생성 버전은 `rba-dataset-v2.0.0`이다.
- 입력 행, GT revision, split, media digest가 바뀌면 새 version을 만든다.
- 같은 `camera_id + activity_day`는 하나의 `camera_night_group`으로 묶는다.
- 같은 group과 인접 파생 clip은 development/evaluation/future-holdout 사이에 갈라지지 않는다.
- legacy 197은 과거 연구 노출 이력이 있으므로 최종 일반화 증거가 아니다.
- future holdout은 모델·prompt·입력 정책을 동결한 뒤 별도 version과 digest로 봉인한다.

## 7. R2 materialization

- 원본을 이동하거나 삭제하지 않는다.
- Dataset v2 전용 격리 prefix로 copy한다.
- copy 전 원본 HEAD 2회, copy 후 size와 content digest를 검증한다.
- 같은 version 재실행은 동일 destination과 digest를 만들며 중복 object를 만들지 않는다.
- prefix 전체 삭제, 원본 덮어쓰기, test 영상 승격은 지원하지 않는다.
- credential, 원문 R2 key, presigned URL은 manifest 공개본·로그·git에 남기지 않는다.

## 8. 구성 요소

1. `rba_dataset_v2_schema.py`: row와 manifest validator
2. `prepare_rba_dataset_v2.py`: legacy/recent 입력을 읽고 eligibility를 fail-closed로 판정
3. `build_rba_dataset_v2.py`: 중복 제거, version/digest, group split, private manifest 생성
4. materialization adapter: R2 copy와 이중 검증. DB/R2 없는 테스트에서는 fake adapter 사용
5. TEST-SHEET와 aggregate report: 수량, 출처, 행동, 복수 행동, 제외 사유, split 분포만 공개

각 구성 요소는 입력을 명시적으로 받고 import 시 DB/R2/network write를 수행하지 않는다.

## 9. 실패 처리

- legacy count/digest 불일치: 전체 중단
- canonical GT conflict/pending: 해당 영상을 조용히 제외하지 않고 전체 중단
- R2 HEAD·decode·hash 실패: 해당 영상과 이유를 private preflight에 남기고 전체 중단
- 중복 media: 자동으로 하나를 고르지 않고 source priority와 충돌 내역을 보고한 뒤 중단
- segment 범위 오류: 전체 중단
- split leakage: 전체 중단
- 기존 version destination의 digest 불일치: 덮어쓰지 않고 전체 중단

## 10. 성공 조건

- legacy 197개가 원본 GT·digest를 바꾸지 않고 포함된다.
- recent Owner-final eligible 영상이 최신 canonical revision으로 포함된다.
- 요청 영상이 중복 여부에 따라 316 유지 또는 317 추가로 정확히 처리된다.
- private manifest의 sample/media 중복이 0이다.
- test·cleanup 제외 대상과의 교집합이 0이다.
- camera-night split leakage가 0이다.
- 격리 R2 copy가 원본과 size·digest 모두 일치한다.
- 같은 입력으로 세 번 생성한 manifest digest가 동일하다.
- prediction 필드와 비밀값이 manifest에 없다.

## 11. 현재 범위 밖

- 라벨링 웹의 Owner 전용 `Dataset에 추가` 버튼
- OpenAI API 실행과 prediction ledger 적재
- GME 기반 자동 포함·제외·행동명·하이라이트 확정
- 자동 사건 묶기
- 원본 삭제 또는 기존 dataset-203 변경
