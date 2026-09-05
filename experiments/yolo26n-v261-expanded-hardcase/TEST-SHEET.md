# YOLO26n v2.6.1 expanded hard-case queue — TEST-SHEET

**상태:** `V261_DATASET_READY_AWAITING_TRAINING_APPROVAL`
**설계:** `docs/superpowers/specs/2026-09-04-yolo26n-v261-expanded-hardcase-design.md`

## 입력과 역할

- v2.6 source window·selection·dataset manifest: 사용/보호 fingerprint 정본
- post-v2.6 production clips: future holdout 300을 먼저 봉인한 뒤 나머지만 development
- historical unused clips: current GME detector quality anomaly + IID control
- Owner-confirmed 4 clips: development hard-case, 사람 판정 구간만 고밀도
- old validation153/test151: fingerprint 대조 외 접근 금지

## 고정 선택 계약

- seed: `yolo26n-v261-expanded-hardcase-v1`
- future holdout: exact 300 clips, 양 카메라, 최소 3 camera-nights
- historical anomaly source limit: 600
- historical IID control source limit: 150
- post-v2.6 development: holdout을 뺀 고정 snapshot 전량
- minimum duration: 55 sec
- anomaly thresholds: gap `>=10`, fragmentation `>=10`, position jump `>=3`,
  max simultaneous geckos `>=2`, unknown ratio `>=0.8`, visible sec `=0`
- GME moving-time만의 이상은 detector anomaly에 넣지 않음

## frame 계약

- base sampling 1fps
- anomaly/Owner 오류 구간 5fps, 구간 전후 1 sec
- 일반 clip 최종 상한 6장, anomaly clip 상한 12장, Owner-confirmed clip 상한 80장
- global exact SHA reject
- same-clip dHash Hamming `<=2` reject, source coverage용 near-duplicate 예외 최대 2장
- Owner-confirmed 4개 복합 오류 source는 dense 교정을 위해 near-duplicate 예외 최대 20장
- v2.6 selected/protected fingerprint overlap 0
- blind filename만 CVAT ZIP에 포함, source/GME/prediction 정보 0

## 판정

- `SOURCE_PLAN_READY`: source snapshot·holdout·development가 exact/불변이고 overlap 0
- `BLIND_QUEUE_READY`: download/decode/dedup/ZIP/integrity가 통과하고 명시적 media 제외율 `<=5%`
- `SHORTAGE`: 300 holdout·양 카메라·3 nights·selected frame 조건 중 하나라도 미달
- `INTEGRITY_FAILED`: source drift, protected overlap, ZIP/hash mismatch, private permission 위반 또는
  download/decode 제외율 `>5%`

## 금지

- production DB/R2 write/delete
- service/model/GME/labeling web 변경·배포
- GME/Claude prediction을 GT로 사용
- future holdout frame/label 접근
- 기존 artifact 삭제·덮어쓰기

## 실행 결과

- source snapshot: 2,004 clips
- post-v2.6: 1,215 clips
- future holdout: 300 clips, 2 cameras, 10 nights, development overlap 0
- development source: 1,187 clips
- 원본 GET: 1,187/1,187, download failure 0, 총 11,445,567,086 bytes
- decode: 1,187/1,187, failure 0
- pre-dedup candidate: 10,785 frames
- final blind queue: 4,096 frames, source coverage 1,187/1,187
- source당 최종 frame: minimum 3, median 3, maximum 21
- GME detector anomaly signal 포함 frame: 2,093
- IID control frame: 510
- Owner-confirmed 복합 오류 frame: 84
- CVAT ZIP: 3개 (`2,000 + 2,000 + 96`)
- v2.6 dataset exact image overlap 0, future holdout 접근 0
- DB/R2 write, service/model change 0
- superseded queue v1/v2/v3는 삭제·덮어쓰기 없이 private 감사 이력으로 보존
- CVAT 17 jobs 완료: Task 4/5/6 export 3개 동결
- export image: 4,096
- positive image / empty image: 2,699 / 1,397
- gecko bbox: 2,732
- uncertain / media_error: 0 / 0
- queue/export 익명 filename·순서, label set, bbox bounds, tag conflict, 전역 번호 검증 통과
- dataset/train/validation 구현 계획:
  `docs/superpowers/plans/2026-09-04-yolo26n-v261-dataset-training-validation.md`
- GT normalizer·episode-group dataset builder·matched training runner·validation/freeze/regression
  evaluator 구현 완료
- 관련 v2.6.1 unit/regression test: 68 passed
- 전체 저장소 회귀 테스트: 2,478 passed, 5 skipped
- 독립 최종 코드리뷰: Critical 0, Important 0, Ready Yes
- GT exact count·익명 번호·입력 전후 SHA, protected dHash, 승인 split 재사용, 학습 dataset 전후
  전수 byte/file-set, 외부 승인 split SHA·입력 lineage, 7-checkpoint evaluation preflight, 승인 v2.6
  baseline SHA, freeze 및 505/151 fixed-suite regression binding 회귀 테스트 포함
- 실제 private GT normalize 완료: 4,096장, 양성 2,699, 음성 1,397, bbox 2,732,
  uncertain/media_error 0
- episode split dry-run 완료: 신규 train 3,274, validation 822, source episode 817,
  near-duplicate-safe split group 341, 교차 근사중복 0
- 승인 split SHA: `be96453c6738a9af9fa735befe39591ddd5144a782f541b7d0038f7c2276cfc0`
- canonical dataset `dataset-v261-v2`: 총 7,758장, train 6,936, validation 822,
  file/SHA drift·누락·미기록 파일 0, private 권한 위반 0
- 첫 `dataset-v261-v1`은 잘못된 source commit lineage로 격리했고 recovery receipt를 보존
- training, evaluation은 미실행
- 상세: [`REPORT.md`](REPORT.md)
