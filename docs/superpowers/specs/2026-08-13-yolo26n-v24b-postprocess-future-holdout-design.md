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

### 보호 overlap ledger 준비

inventory가 소비하는 overlap ledger는 실제 역사 artifact를 임의의 공통 구조로 해석한 파일이 아니다.
다음 세 역할을 각각 독립 SHA로 pin한 실제 artifact와 별도 protected-lineage SOT를 exact join해 만든다.

| 역할 | 실제 artifact 계약 | exact 수량 |
|---|---|---:|
| `dataset` | `yolo26n-owner-dataset-v24`, split train 1458/val 153/test 151 | 1,762 |
| `internal-test151` | `yolo26n-v24-prediction-ledger-v1`, `V24_PREDICTIONS_READY`, split `test` | 151 |
| `owner-external60` | `yolo26n-owner-media-external-predictions-v1`, `PREDICTIONS_COMPLETE`, frozen provenance pins | 60 |

dataset v24 root는 raw artifact independent SHA가 전체 bytes를 고정하므로 producer에서 확인된
schema/image_count/split_counts/evaluation/write/records 필드를 strict 검증하되, SHA에 포함된 추가
top-level producer metadata는 허용한다. 대신 각 dataset record는
`sequence,split,image_path,label_path,image_sha256,box_count,positive,source_dataset,camera_night_group,final_holdout_eligible`
exact key/type/value와 unique sequence/image SHA를 요구한다. internal test와 external artifact는 producer가
고정한 root/provenance/record key를 exact 검증한다. 모든 입력 JSON은 duplicate key, bool-as-number,
NaN/inf, malformed SHA/count/record를 fail-closed로 거부한다.

protected lineage SOT의 exact root 계약은 다음과 같다.

- `schema=yolo26n-v24b-protected-lineage-v1`
- `status=V24B_PROTECTED_LINEAGE_FROZEN`
- `role=dataset|internal-test151|owner-external60`
- 역할별 exact `record_count`와 `records`
- 각 record exact key:
  `sequence,image_sha256,source_ref,camera_night,derivation_refs`
- `derivation_refs`는 비어 있지 않은 unique string list
- `db_write_count=r2_write_count=service_write_count=0`

실제 artifact와 lineage SOT는 `(sequence,image_sha256)`가 exact bijection이어야 한다. source clip,
camera-night, derivation은 dataset record, prediction, 파일 경로에서 추측하거나 보충하지 않고 이 protected
SOT에서만 가져온다. missing/extra/mismatch/duplicate/incomplete lineage면 정확히
`V24B_PROTECTED_LINEAGE_SHORTAGE`로 종료하고 normalized overlap output을 만들지 않는다.

`prepare-overlap`은 artifact와 lineage에 서로 다른 independent SHA pin을 필수로 받고, 둘 다
0600/non-symlink/single-read/pre-post dev·inode·size·mtime·ctime identity로 고정한다. 입력을 읽기 전에
0600 atomic O_EXCL started lock을 선점한다. 재호출·동시 loser는 입력 처리 0이고 rival lock/output을
정리하지 않는다. 성공 output은 기존 `yolo26n-v24b-future-overlap-ledger-v1` exact schema의 0600
atomic no-overwrite private 파일이다.

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
하나여야 한다. source clip, camera-night, 원본 파일명 등 source identity와 원본 식별 메타데이터는
Owner-facing P frame과 presence-screen에 노출하지 않고, private ledger/review-index에만 보존한다.

결정론적 선택기는 이 입력에서 모든 cap을 지키며 positive 60장과 negative 60장을 고른다. ambiguous는
final 시험지에서 제외한다. 요구 수량을 공급할 수 없으면 `V24B_FUTURE_HOLDOUT_SHORTAGE`로 종료하며,
모델 예측으로 정답이나 부족분을 채우지 않는다. 이 선별을 통과한 final CVAT에는 generic
`H0001..H0120`만 들어간다. positive는 bbox가 1개 이상이어야 하고, negative는 bbox가 0개여야 한다.

final private `review-index.csv`는 source identity와 함께 각 선택 frame의 canonical nonnegative integer
dHash를 보존한다. 완성된 CSV bytes는 정확히 한 번 읽어 SHA-256으로 고정하고, candidate
`manifest.private.json`의 `review_index_sha256`과 독립 실행 pin이 같은 값이어야 한다. dHash와 source
identity는 private review-index에만 존재하며 Owner-facing image/CVAT ZIP과 manifest record에는 넣지 않는다.
CSV와 manifest는 같은 private staging directory에서 all-or-none으로 publish하고, manifest 생성 중 CSV
identity가 바뀌면 final directory를 publish하지 않는다.

postprocess freeze의 raw bytes SHA-256은 private provenance에서
`freeze_sha256`(inventory) → `postprocess_freeze_sha256`(pool ledger) →
`postprocess_freeze_sha256`(final candidate manifest)로 값 변경 없이 이어진다. 각 단계는 exact lowercase
64-hex를 다음 외부 읽기나 image read 전에 검증한다. Task 6은 freeze bytes를 독립 해시한 값과 manifest의
pin을 exact 비교한 뒤에만 평가한다. 이 계보 SHA는 private manifest/provenance에만 있고 Owner-facing
P/H image, presence CSV, CVAT ZIP, manifest record에는 넣지 않는다.

## 6. 사람 검수 흐름

1. 시스템이 모델 예측·confidence·과거 Gate/GME 결과와 source clip·camera-night·원본 파일명 등 source identity,
   원본 식별 메타데이터를 숨긴 `P0001..P0240` blind presence 선별 화면과 CSV를 만든다. 이 식별자는 private
   ledger/review-index에만 남긴다.
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
- 역할별 protected-lineage SOT pin과 normalized overlap ledger 3개
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

## 9-1. Mac mini handoff와 runtime 불변 계약

실행 repo는 `/Users/baek-end/petcam-lab`, runtime host는 `baeg-endeuui-Macmini.local`이다. 현재 Mac mini의
기존 checkout은 unrelated dirty이며 implementation commit은 remote에 없으므로, 그 checkout·production
git·shared uv environment를 수정하거나 sync해서 실행하지 않는다. read-only preflight의 sealed input은
checkpoint SHA-256 `3c9f752b9369b30be4083f837676271640cfd1f4cbfa6027382a380efc4212c4`와 mode `0600` dataset
manifest SHA-256 `218f32d745e407470c661d97cfe0035e27614cc8f7921ae61835050a0dcd827f`이며 v1/v2 attempt bytes는
동일하다. clean isolated
execution repo가 exact implementation commit을 가리키기 전 상태는 `PENDING_CLEAN_IMPLEMENTATION_CHECKOUT`다.
이는 실행 승인이나 유효 final handoff가 아니다.

freeze SHA는 validation grid/freeze 실행 전에는 존재하지 않는다. 따라서 handoff는 두 단계다.

1. bootstrap handoff는 implementation commit의 clean checkout에서만 검증하며 Task 8 Step 1의
   validation grid와 freeze 생성만 허용한다. exact checkpoint SHA는
   `3c9f752b9369b30be4083f837676271640cfd1f4cbfa6027382a380efc4212c4`이고 exact dataset manifest SHA는
   `218f32d745e407470c661d97cfe0035e27614cc8f7921ae61835050a0dcd827f`다. freeze pin은 artifact가 아직
   없으므로 `PENDING_FREEZE`이며 유효 SHA나 실행 승인이 아니다.
2. freeze가 shortage 없이 만들어진 후 raw bytes SHA-256을 독립 계산한다. same clean implementation
   checkout에서 actual dataset SHA와 exact freeze SHA를 포함한 final handoff/addendum을 다시 validator로
   검증한 뒤에만 Task 8 Step 2 이후를 허용한다.

bootstrap과 final 모두 validator보다 먼저 exact I checkout인지 기계 확인한다. 즉 execution repo root가
`/Users/baek-end/petcam-lab`이고 `git rev-parse HEAD`가
`e822f289b38b61d2d29bbd26370be20874e1eb82`이며 `git status --porcelain`가 비어 있어야 한다. 그 뒤
`cd /Users/baek-end/petcam-lab`에서만 runner를 실행해 runner의 `source_commit`도 I로 고정한다. final은
validator가 front matter밖 body pin을 읽지 않는다는 점을 별도 보완한다. final addendum의 actual lowercase
64-hex dataset/freeze SHA를 strict 검증하고 각각의 raw bytes를 `shasum -a 256`으로 계산해 exact 비교한 뒤,
body의 두 pin line까지 exact 비교해야 한다. placeholder, upper-case, 길이 불일치, missing/non-regular input은
그 validator 실행 전 hard stop이다.

tracked handoff 문서는 위 실행의 이력·절차이지 validator manifest가 아니다. validator는 `commit_sha`와
execution repo HEAD가 일치하고 plan/design이 그 commit에 있어야 하므로 self-referential tracked
handoff commit은 검증할 수 없다. implementation/plan/design commit I를 먼저 만들고, I SHA를 기록한
handoff tracking commit H를 그 다음 만들며, 실제 validator manifest는 clean I checkout 밖 private
location에 untracked로 만든다. `HANDOFF_OK`는 실제 validator 출력 전에는 어떤 문서에도 주장하지 않는다.

runtime은 approved private attempt root에서만 `YOLO_CONFIG_DIR`를 그 root 아래로 지정하고, shared
environment를 변경하지 않는 아래 명령을 사용한다.

```bash
env YOLO_CONFIG_DIR="$ATTEMPT_ROOT/yolo-config" \
  uv run --isolated --with 'ultralytics==8.4.118' python scripts/run_yolo26n_v24b_postprocess.py ...
```

`ATTEMPT_ROOT`가 승인된 private absolute root가 아니면 `PENDING_APPROVED_ATTEMPT_ROOT`로 멈춘다.
runtime kind는 `oneshot`이고 DB/R2/service/git/production write, old test151/external60 사용은 전부
금지한다. private local artifact의 no-overwrite 생성만 허용한다.

## 10. 범위 밖

- v2.5 재학습
- 기존 1,458장 재라벨링
- 기존 test 151장·외부 60장 재평가
- Roboflow 자료 추가
- production checkpoint 교체
- GME의 자동 부재·라우팅·삭제·행동 판정
