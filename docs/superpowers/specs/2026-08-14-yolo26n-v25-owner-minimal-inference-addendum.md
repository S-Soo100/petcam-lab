# YOLO26n v2.5 Owner minimal inference 실행 계약 addendum

**상태:** owner 승인 / 고정 체크리스트 사전리뷰 대기
**적용 범위:** accepted Owner 280-frame bundle에서 blind CVAT queue를 만드는 development-only one-shot
**대체 범위:** 기존 hardened all-in-one runtime 경로의 live 실행만 대체한다. 기존 코드·attempt·lock·artifact는 감사 이력으로 보존한다.

## 1. 목적과 데이터 경계

v2.4 checkpoint와 postprocess freeze는 이미 확정됐다. 이 addendum은 새 모델을 학습하거나 평가하지 않고,
accepted Owner bundle 280장을 frozen v2.4로 추론해 v2.5 사람 bbox 보강 후보를 만든다.

```text
accepted Owner bundle 280
  -> pin/count/member 검증
  -> frozen v2.4 shadow inference
  -> deterministic hard-case signal/selection
  -> prediction-private provenance ledger
  -> blind CVAT queue + ZIP
  -> 기존 independent validator
  -> V25_BLIND_CVAT_QUEUE_READY
```

- Gate 1,951건은 `quarantine_all`이며 downstream consumption은 정확히 0이다. Gate raw/COCO/lineage/path/count는
  runner 입력·provenance gate·identity에 포함하지 않는다.
- validation 153, internal fixed-test 151, Owner external 60은 runner가 경로 인자를 받지 않으며 접근·추론·
  선택·학습이 모두 0이다.
- bundle은 immutable accepted input이다. decode/mining을 반복하지 않고 expected directory SHA, manifest/member
  set, 각 JPEG SHA와 count 280만 시작 시 검증한다.
- 사람 bbox 전에는 v2.5 dataset materialization, training, evaluation을 시작하지 않는다.

## 2. 고정 hard stop

다음 일곱 경우에만 실행을 중단한다.

1. bundle directory/member/image SHA 또는 expected count 280 불일치
2. v2.4 checkpoint raw SHA 불일치
3. freeze selected가 `conf=.25`, `nms_iou=.40`, `duplicate=4`와 불일치하거나 runner의 approved
   inference params가 `imgsz=960`, `max_det=50`과 불일치
4. protected 153/151/60 경로 또는 role을 입력하려는 시도
5. blind 산출물에 prediction, confidence, bucket/signal, source 식별자가 노출됨
6. DB/R2/service/production model/GME/labeling web write 또는 deploy 시도
7. 정상적으로 처리된 frame 중 selected frame이 0장임: `V25_HARDCASE_QUEUE_SHORTAGE`

개별 frame decode/inference 실패는 해당 frame만 제외하고 reason별 count를 ledger에 남긴다. 처리 가능한 frame과
selected frame이 하나 이상이면 계속한다.

## 3. warning·ledger-only 경계

- bundle `producer_code_sha256`과 현재 `inference_code_sha256`은 서로 다른 provenance 필드다. 둘의 equality를
  요구하지 않는다.
- Python과 핵심 package의 현재 version을 기록하고 import/model-load smoke를 수행한다. package version 차이,
  전체 site-packages tree/aggregate fingerprint 차이는 이 실행의 hard stop이 아니다.
- mtime, ctime, inode 차이와 historical Gate quarantine 상태는 hard stop이 아니다.
- JPEG는 blind publish 전에 metadata를 제거하고 실제 JPEG·EXIF 없음·허용 metadata만 재확인한다.

현재 위협모델은 pinned content, protected-role 차단, blind 누출 0, write 0, fresh no-overwrite에 집중한다.
TOCTOU/ABA/FIFO/inode/full-runtime-tree의 추가 강화는 이번 고정 체크리스트 밖이며 새 실행 요구로 확장하지 않는다.

## 4. 최소 실행기와 산출물

- 새 live entrypoint는 `scripts/run_yolo26n_v25_owner_inference_minimal.py` 하나다.
- scientific policy는 별도 pure module에 고정하고 기존 결과와 parity fixture로 검증한다: duplicate IoU `>=.70`,
  no-detection miss, unsupported single detection confidence `<.50`와 same-source `<=2.0s` support, frame edge
  `2%/98%` partial-occlusion, source round-robin diversity.
- 정책 id/seed는 기존 `yolo26n-v25-blind-queue-v1` /
  `yolo26n-v25-historical-hardcase-reinforcement-v1`, cap은 source당 6장·전체 210장이다.
- fresh private output만 허용하고 기존 경로가 있으면 중단한다. private directory/file mode는 0700/0600이다.
- private provenance ledger 하나에 bundle/checkpoint/freeze pin, separate producer/inference code SHA, runtime versions,
  input/success/exclusion/bucket/selection count와 모든 write-zero count를 기록한다.
- public CVAT 이름은 `V25####.jpg`; manifest/COCO/ZIP에는 source, prediction, confidence, bucket/signal이 없다.
- 기존 `scripts/validate_yolo26n_v25_blind_queue.py`가 queue/ZIP/JPEG/empty-annotation/blindness를 독립 검증하고
  acceptance를 만들 때만 `V25_BLIND_CVAT_QUEUE_READY`를 보고한다.

## 5. 리뷰와 실행 선형화

1. 이 addendum과 계획을 fixed checklist로 Claude 사전리뷰 **1회** 한다.
2. PASS 또는 위 checklist 내부 수정만 반영한 뒤 TDD 구현·검증·commit·push를 연속 수행한다.
3. Mac mini는 기존 approved execution repo/host와 model-load 가능한 isolated runtime을 사용한다. 새 handoff chain
   대신 exact code SHA, checkpoint SHA, bundle directory SHA만 실행 직전 재확인한다.
4. fresh output에서 280장 inference와 queue build를 한 번에 수행한다.
5. 기존 validator와 비민감 aggregate로 사후검수 **1회** 한다.

구현 버그와 테스트 실패는 같은 승인 범위에서 자동 수정·재실행한다. 위 hard stop 외 중간 승인이나 새 security
cycle을 만들지 않는다. 정상 종착점은 `V25_BLIND_CVAT_QUEUE_READY`다.
