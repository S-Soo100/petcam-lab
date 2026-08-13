# YOLO26n v2.4b 후처리 선택·Future Holdout 설계

**상태:** 설계 승인 / 구현 전

**승인일:** 2026-08-13 KST

**목적:** v2.4가 얻은 게코 검출 재현율 향상은 유지하면서 중복 박스와 오탐을 validation 전용
후처리 선택으로 낮추고, 한 번도 열지 않은 새 120장 시험지로 Gate/GME shadow 승격 여부를 판정한다.

## 1. 한 줄 결정

기존 v2.4 학습 데이터 1,458장은 그대로 보존한다. 새 학습을 바로 시작하지 않고 validation 153장만
사용해 confidence threshold와 NMS IoU의 고정 조합을 선택한다. 기존 test 151장과 Owner 외부 60장은
다시 선택·튜닝에 사용하지 않는다. 선택이 끝난 뒤 새 영상으로 만든 blind future holdout 120장을
Owner가 bbox 검수하고, 그 시험지에 정확히 한 번만 평가한다.

## 2. 왜 이 순서인가

v2.4는 모델 자체가 실패한 결과가 아니다.

| 평가 | v2.3 | v2.4 | 변화 |
|---|---:|---:|---:|
| 내부 precision | 0.7361 | 0.7326 | -0.0035 |
| 내부 recall | 0.5889 | 0.7000 | +0.1111 |
| 외부 precision 참고값 | 0.5455 | 0.5893 | +0.0438 |
| 외부 recall | 0.4211 | 0.5789 | +0.1579 |
| 외부 FP | 20 | 23 | +3 |
| 외부 duplicate | 4 | 6 | +2 |

게코를 놓치는 문제는 크게 줄었고 precision도 유지됐다. 탈락 원인은 외부 FP와 duplicate가 사전 기준을
초과한 것이다. 따라서 학습 데이터를 다시 바꾸기 전에 validation에서만 중복 억제 후처리를 고정하는
것이 가장 작은 실험이다.

## 3. 데이터 역할 고정

| 데이터 | 수량 | 허용 역할 | 금지 역할 |
|---|---:|---|---|
| v2.4 train | 1,458 | 기존 모델 학습의 고정 재료, 향후 v2.5의 부모 | v2.4b 새 시험지 |
| v2.4 validation | 153 | confidence·NMS 선택 | 최종 성능 주장 |
| 기존 internal test | 151 | v2.3/v2.4 역사 비교 원장 | v2.4b 선택·재시험 |
| 기존 Owner 외부 진단 | 60 | 실패 유형 설명과 역사 비교 | v2.4b 선택·재시험·학습 |
| 새 future holdout | 120 | v2.4b 최종 one-shot 시험 | 학습·threshold/NMS 선택 |

기존 test와 외부 60장을 다시 열어 v2.4b를 조정하면 이미 본 시험지에 맞추는 누수가 된다. 이 두
집합은 원본·GT·예측·보고서 SHA를 동결하고 읽기 전용 역사 자료로만 남긴다.

## 4. v2.4b 후처리 선택

### 입력

- v2.4 고정 best checkpoint SHA
  `3c9f752b9369b30be4083f837676271640cfd1f4cbfa6027382a380efc4212c4`
- v2.4 validation 153장과 사람 GT
- inference 기본값: `imgsz=960`, `max_det=50`, `device=mps`
- confidence 수집 하한: `0.001`

### 탐색 공간

- NMS IoU: `0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70`
- confidence threshold: `0.05`부터 `0.80`까지 `0.05` 간격
- bbox match IoU: `0.50`

각 NMS IoU는 validation 153장에 한 번만 low-confidence inference한다. threshold는 그 고정 원장을
재계산하므로 추가 모델 호출이 아니다. 각 조합은 TP, FP, FN, precision, recall, duplicate prediction,
positive-image recall을 기록한다.

### 선택 규칙

다음 조건을 만족하는 조합만 후보로 둔다.

1. validation precision `>=0.60`
2. validation recall `>=0.65`
3. 현재 v2.4 기준점 `(confidence=0.20, NMS IoU=0.70)`보다 duplicate가 증가하지 않음

후보가 여러 개면 다음 순서로 하나를 결정론적으로 선택한다.

1. duplicate prediction이 가장 적음
2. recall이 가장 높음
3. FP가 가장 적음
4. confidence threshold가 가장 높음
5. NMS IoU가 가장 낮음

후보가 없으면 `V24B_POSTPROCESS_SHORTAGE`로 종료한다. 기존 test나 외부 60장을 보고 조건을
완화하지 않으며 v2.5 재학습 설계로 넘어간다.

### 고정 산출물

`v24b-postprocess-freeze.private.json`에 checkpoint, dataset manifest, validation 원장, 코드 SHA,
탐색 격자, 전체 metric table, 선택 조합을 기록한다. 선택 후 이 파일을 수정하거나 같은 시도 경로에서
다시 생성하지 않는다.

## 5. 새 future holdout 120장

### 시간·누수 경계

- v2.4b 탐색 규칙과 코드 SHA를 고정한 뒤 촬영·수집된 새 영상만 사용한다.
- 기존 train/validation/test/외부 60장과 image SHA, source clip, camera-night, 원본 파생 관계가
  겹치면 제외한다.
- source identity나 촬영 시간이 불명확하면 억지로 포함하지 않고 격리한다.
- 테스트 클립(`clip_purpose=test`)이나 펌웨어 개발 영상은 제외한다.

### 정확한 구성

- 총 120장
- 게코 양성 60장, 음성 60장
- 서로 다른 카메라 최소 3개
- 서로 다른 camera-night 최소 6개
- camera-night당 최대 20장
- source clip당 최대 2장
- 동일 source 안의 선택 frame은 dHash 거리 `>2`

양성은 가림 뒤를 추정한 임의 박스가 아니라 **확인 가능한 개체마다 정확히 한 bbox**를
갖는다. 꼬리는 화면 밖·가림 뒤를 추정하지 않고 보이는 머리·몸통 중심 영역만 감싼다. 여러 마리가
보이면 개체별로 각각 bbox를 만든다. 게코 여부 자체가 불분명한 frame은 blind presence 선별에서
ambiguous로 표시하고 final 120장 시험지에서 제외한다.

선택기는 가능한 범위에서 야간, 작은 개체, 부분 가림, 쳇바퀴·투명 구조물, 복수 개체, 밝기 전환을
분산한다. 이 항목은 실제 공급량과 함께 coverage report로 공개하되, 존재하지 않는 희귀 장면을 만들기
위해 60/60·카메라·night 독립성 조건을 깨지 않는다.

### Blind presence 선별 계약

최종 120장을 바로 만들지 않는다. 시스템은 위 시간·누수 경계와 camera-night, source clip, dHash cap을
적용한 최대 240장의 blind reserve pool을 먼저 만든다. Owner에게 보이는 화면과 CSV의 sequence 이름은
`P0001..P0240`이며, 모델 bbox·confidence·Gate/GME 결과는 모두 숨긴다. Owner는 예측을 보지 않은
상태에서 `sequence,presence`만 입력하고, presence 값은 `positive`, `negative`, `ambiguous` 셋 중
하나여야 한다.

결정론적 선택기는 이 입력에서 모든 cap을 지키며 positive 60장과 negative 60장을 고른다. ambiguous는
final 시험지에서 제외한다. 요구 수량을 공급할 수 없으면 `V24B_FUTURE_HOLDOUT_SHORTAGE`로 종료하며,
모델 예측으로 정답이나 부족분을 채우지 않는다. 이 선별을 통과한 final CVAT에는 generic
`H0001..H0120`만 들어간다. positive는 bbox가 1개 이상이어야 하고, negative는 bbox가 0개여야 한다.

## 6. 사람 검수 흐름

1. 시스템이 모델 예측·confidence·과거 Gate/GME 결과를 숨긴 `P0001..P0240` blind presence 선별 화면과 CSV를 만든다.
2. Owner는 각 reserve 후보에 `sequence,presence`를 입력하며, `positive`, `negative`, `ambiguous` 중 하나로만 표시한다.
3. 결정론적 선택기가 60/60과 camera/night·clip·dHash cap을 검증해 `H0001..H0120` final CVAT 작업을 만든다.
4. Owner는 final 120장에 `gecko` 단일 class의 axis-aligned bbox를 입력한다. positive에는 bbox 1개 이상,
   negative에는 bbox 0개가 있어야 한다.
5. 제출 후 manifest 순서, image SHA, dimensions, box bounds, class, 60/60, 3 cameras/6 nights,
   clip/night cap을 기계 검증한다.
6. 검증이 끝나면 TEST-SHEET manifest와 사람 GT SHA를 동결한다.

CVAT에는 v2.4b 예측 박스를 미리 올리지 않는다. 사람이 정답을 만든 뒤에만 모델 inference를 실행해
anchoring을 막는다.

## 7. One-shot 평가와 판정

동결된 v2.4b checkpoint·confidence·NMS 조합을 future holdout 120장에 정확히 한 번 실행한다.

### Shadow 승격 조건

다음을 모두 만족해야 `V24B_SHADOW_CANDIDATE`가 된다.

1. box precision `>=0.60`
2. box recall `>=0.60`
3. positive-image recall `>=0.60`
4. 60개 음성 중 prediction이 하나라도 나온 이미지 `<=6` (`<=10%`)
5. duplicate prediction `<=4`
6. decode, label, provenance, overlap, one-shot, DB/R2/service write 위반 `0`

통과해도 역할은 Gecko Vision Gate/GME의 **shadow 관측 후보**다. `not observed`를 부재 확정으로 바꾸거나
영상 A/B 이동, 자동 skip, 삭제, 행동명, 하이라이트에 사용하는 것은 계속 금지한다. 실패하면 future
holdout 결과를 v2.4b 재튜닝에 쓰지 않고, 오류 유형을 집계한 뒤 별도 v2.5 학습 데이터 설계를 승인받는다.

## 8. 산출물과 불변성

- 새 private validation prediction ledgers(NMS IoU별 1개)
- `v24b-postprocess-freeze.private.json`
- future holdout candidate/exclusion manifest
- generic CVAT bundle과 Owner normalized snapshot
- `v24b-future-holdout-predictions.private.json`
- 비민감 최종 report

모든 private JSON은 0600, no-overwrite, one-shot started lock을 사용한다. 입력 파일은 inference 전후 SHA를
대조하고 partial output을 성공으로 취급하지 않는다. DB, R2, service, GME, labeling web production,
active checkpoint는 수정하지 않는다.

## 9. 다음 단계

1. v2.4b validation NMS·threshold selector와 검증 코드 구현
2. selector 실행 후 조합 동결 또는 shortage 종료
3. 새 future 영상이 충분히 쌓였는지 read-only inventory
4. 120장 blind TEST-SHEET·CVAT 작업 생성
5. Owner bbox 검수
6. export 검증과 TEST-SHEET 동결
7. one-shot 평가·독립 재계산
8. 별도 승인 후에만 Gate/GME shadow 통합 설계

## 10. 범위 밖

- v2.5 재학습
- 기존 1,458장 재라벨링
- 기존 test 151장·외부 60장 재평가
- Roboflow 자료 추가
- production checkpoint 교체
- GME의 자동 부재·라우팅·삭제·행동 판정
