# YOLO26n v2.5 historical hard-case 보강 후보 설계

**상태:** Owner 승인 / 설계·계획 독립 리뷰 통과 / 구현 검증 중
**승인일:** 2026-08-14 KST
**목적:** 이미 검증된 과거 사람 bbox와 Owner 개인 영상의 어려운 장면에서 다음 개발용 bbox 후보를
결정론적으로 만들되, 불변 평가 자산·formal future holdout·production을 건드리지 않는다.

## 1. 한 줄 결정

v2.4 train 1,458장에 아직 들어가지 않은 Gecko Vision Gate의 train-eligible 사람 GT만 계보·라이선스·
label semantics를 다시 검증해 보강 후보로 남긴다. Owner 개인 MOV 35개는 frozen v2.4 shadow 예측으로
어려운 장면을 **찾기만** 하고, 예측 bbox를 숨긴 익명 CVAT queue에서 사람이 새 bbox를 확정하기 전에는
v2.5 dataset materialization이나 학습을 시작하지 않는다.

이번 결과는 `development-only hard-case review queue`다. v2.4b의 production future footage shortage를
해소하거나 formal future holdout을 대신한다고 주장하지 않는다.

## 2. Decision gate

- **G1 SOT 부합:** GME SOT는 Gecko Vision Gate를 계속 업그레이드하되 detector 결과를 자동 부재·행동·
  skip·삭제로 쓰지 않고, 사람 bbox hard case를 append-only로 축적하도록 한다.
- **G2 기대효과:** v2.4가 어려워하는 무검출·고립 검출·중복 박스·부분 가림 신호와 여러 Owner 영상의
  장면을 사람 검수 대상으로 압축해, 다음 학습의 재현율 개선 재료를 만든다.
- **G3 측정 가능:** Gate 포함/미포함 수, 영상 decode 수, exact/dHash 제외 수, bucket 수, source-video
  coverage, blind queue 독립 acceptance를 모두 immutable private ledger로 재계산한다.
- **G4 유효한 계획:** 원본·v2.4/v2.4b artifact는 read-only다. 새 private attempt 안에서만 one-shot
  산출물을 만들고 사람 검수 전에 멈춘다. DB/R2/service/model/GME/labeling web write·배포는 0이다.

판정은 `adopt / development-only blind bbox queue`다. 상세 로그는
[`docs/decision-gate.md`](../../decision-gate.md)에 append한다.

## 3. 불변 역할

| 자산 | 장수 | 이번 역할 | 금지 |
|---|---:|---|---|
| v2.4 train | 1,458 | 계보·중복 비교 기준, 다음 학습의 고정 parent | 수정·재라벨·중복 재추가 |
| v2.4 validation | 153 | frozen v2.4 후처리 선택 자산 | mining·학습·재선택 |
| internal fixed-test | 151 | 불변 회귀 자산 | mining·학습·재평가 |
| Owner external diagnostic | 60 | 불변 외부 진단 자산 | mining·학습·재평가 |
| historical fingerprint | unique 1,822 | 모든 새 frame의 global exact/dHash exclusion | 삭제·덮어쓰기·재생성 |
| Gate operational human GT | 1,951 원본 | v2.4 포함 여부·train eligibility 감사 | 과거 val/test 역할 재사용, bbox 자동 수정 |
| Owner 개인 MOV | 기대 35 | read-only hard-case 원천 | 이동·삭제·수정, 예측을 GT로 승격 |
| v2.4b future holdout | shortage | 보존된 별도 formal 평가 계약 | 이번 queue와 합치거나 완료 주장 |

validation 153, internal 151, external 60의 bytes·순서·GT·기존 ledger는 이번 실행에서 열어 평가하지
않는다. 오직 기존 historical fingerprint ledger의 SHA/dHash exclusion record만 읽는다.

## 4. 확인된 입력과 신뢰 경계

### 4.1 Gate 운영 사람 GT

Gate dataset SOT는 `operational`을 자체 운영 펫캠 프레임으로 정의한다. 후보는 과거 COCO에서
`source=operational`, `labeled=yes`, 사람 검수 bbox인 record만 허용한다. Roboflow, crawler,
autolabel-only, 과거 Gate validation/test 역할은 모두 제외한다.

각 record는 다음을 통과해야 한다.

1. expected raw SHA로 pin한 tracked manifest·세 COCO의 `operational+labeled` 전체 set이 exact
   bijection이다. 각 manifest `split`은 같은 이름의 `train.json`/`val.json`/`test.json`에만 존재해야
   하며 split 간 이동·복제를 허용하지 않는다. reviewed subset만 맞고 manifest-only/COCO-only record가
   남는 상태는 실패다.
2. 원본 image bytes SHA-256, decoded dimensions, COCO dimensions가 일치한다.
3. manifest `clip_id`는 source path clip component와 일치하고, 별도 expected-SHA-pinned private Gate
   lineage의 path set은 `operational+labeled` manifest/COCO 전체 set과 exact bijection이어야 한다. 각
   record의 `source_clip_ref`·`camera_night_ref`를 exact 연결한다. license role은
   `owner-operated/private-training`으로 고정된다. 외부 공개·재배포 권한을 뜻하지 않는다.
4. class는 단일 `gecko`이며 accepted subset뿐 아니라 operational COCO 전체 bbox의 좌표·폭·높이·area가
   finite이고, 폭·높이·area는 양수이며, `area == width * height`, image boundary 내부여야 한다.
5. 현재 정책 호환은 v2.4의 실제 2단계 review 의미를 그대로 사용한다. 표본 audit은 positive 40장·
   negative 20장 중 positive fix 2장, negative mislabeled 0장을 기록했고, 그 결과 positive 293장만
   전수 검수해 284장을 accept하고 9장을 quarantine했다. 최종 accepted manifest의 positive 284장은
   전수검수 accepted record와 exact 일치해야 하고, negative 285장은 표본 zero-defect 정책으로 승인된
   cohort임을 세 ledger의 raw SHA와 owner-verdict SHA 교차 pin으로 증명한다.
6. 최종 accepted manifest 569장 밖의 과거 Gate frame은 현재-policy train-eligible이라고 추정하지
   않는다. 미포함·invalid·unresolved record는 별도 새 사람 blind review 없이는 quarantine이다.
7. v2.4 train manifest의 Gate derivation record와 exact source/image SHA로 대조한다. 이미 포함된 것은
   `already_in_v24_train`으로 제외하고 다시 복사하지 않는다.
8. v2.4 validation/test, internal fixed-test, external 60, ambiguous 역할과 SHA/dHash overlap이 있거나
   lineage가 불명확하면 train 후보가 아니라 quarantine이다.

v2.4가 Gate accepted candidate 전부를 포함했다면 신규 Gate 후보 0은 정상 결과다. 수량을 만들려고
invalid/unresolved/과거 평가 role을 승격하지 않는다.

### 4.2 Owner 개인 영상

승인된 source root의 `.MOV` regular non-symlink 파일만 inventory한다. 기대 수는 35지만 실제 존재 수가
다르면 존재하는 범위만 처리하고 missing count만 보고한다. 파일명·원경로는 private ledger 밖으로
내보내지 않는다.

- license: Owner 제공 개인 영상, 이 개발 실험과 사람 bbox 검수에만 사용한다.
- provenance: source video SHA-256, byte size, capture metadata, decode metadata를 private record에 고정한다.
- prior exposure: 과거 artifact에서 source-video SHA ledger가 발견되면 exact join한다. 그런 ledger가 없으면
  “video-level exposure unknown”을 숨기지 않고 기록하되, 추출 frame은 historical 1,822 전체와 global
  content fingerprint를 반드시 비교한다.
- 원본은 `O_NOFOLLOW|O_NONBLOCK` read-only regular-file descriptor로 한 번만 열고 inventory 전체 pin을
  확인한다. 두 번의 OpenCV decode도 mutable pathname 재개방 없이 같은 descriptor의 `/dev/fd` capability를
  소비한다. decode 전후 descriptor의 device/inode/size/mtime/content SHA가 같아야 한다. namespace rename만
  반영하는 ctime 변화는 내용 capability 변화로 간주하지 않지만, 시작 전 inventory ctime pin은 확인한다.
- decode failure, zero-frame, invalid fps/dimensions, 중간 원본 변경은 그 영상만 fail-closed exclude한다.

## 5. 결정론적 frame mining

정책 id는 `yolo26n-v25-owner-frame-mining-v1`이다. OpenCV/Python/NumPy version과 miner code SHA를
private ledger에 pin한다.

### 5.1 Uniform anchors

decode된 총 frame 수를 `N`이라 할 때 최대 8개 anchor를
`round((i + 1) * (N - 1) / (K + 1))`, `i=0..K-1`, `K=min(8,N)`로 선택한다. 같은 index가 나오면
첫 index만 남긴다. 시작·끝 한 장에 편중되지 않는 고정 coverage다.

### 5.2 Scene-aware anchors

영상을 순차 decode하면서 1초 간격 frame을 64×36 grayscale로 축소하고 바로 이전 scan frame과의
mean absolute difference를 계산한다. 점수가 큰 순으로 최대 4개를 선택하되:

- uniform/이미 선택한 anchor와 1초 이내면 제외한다.
- scene-aware anchor끼리 2초 이내면 높은 점수 하나만 남긴다.
- 동률은 source-video SHA, frame index의 canonical rank로 결정한다.

영상당 최대 12장이다. scene score는 장면 변화 후보일 뿐 게코 움직임·행동 GT가 아니다.

## 6. Global content dedup

정책 id는 기존 historical ledger와 같은 `historical-image-dhash64-v1`을 재사용한다.

- exact: encoded candidate bytes SHA-256 동일 시 제외한다.
- perceptual: RGB를 grayscale 9×8로 BOX resize하고 각 행에서 `right > left` 64bit dHash를 만든다.
- global threshold: historical 1,822 record 또는 이번 Owner 후보 전체에서 Hamming distance `<=2`이면
  near duplicate다. `3`부터는 통과한다.
- canonical keeper: `(source_video_sha256, frame_index, frame_sha256)` 오름차순 첫 record다.
- 비교는 source-local이 아니라 historical 전체와 Owner 후보 전체에 대해 수행한다.

historical ledger가 exact schema/status, unique 1,822, role count 1,973, parent artifact SHA pin을 모두
통과하지 않으면 추출·inference 전에 멈춘다. fingerprint coverage 결손을 temporal/source 추정으로
메우지 않는다.

## 7. Frozen v2.4 shadow inference

inference는 v2.4 checkpoint와 v2.4b freeze의 SHA를 독립 검증한 뒤에만 실행한다. 실제 freeze의
`selected`는 exact `{"confidence":0.25,"nms_iou":0.40,"duplicate":4}`이고 실행 고정값은
`imgsz=960`, `conf=0.25`, `nms_iou=0.40`, `max_det=50`이다. prediction ledger도 이 exact selected 계약을
고정한다. validation/test/external image나 GT는 inference input으로 열지 않는다.

runtime preflight는 artifact raw SHA만 신뢰하지 않는다. 승인 artifact의 Python binary·`uv.lock`·설치
distribution set·Ultralytics package tree·Torch/TorchVision/NumPy/OpenCV/Pillow version fingerprint를 현재
runtime에서 독립 재계산해 exact 비교한다. Python/lock/package tree reads는 verified regular-file descriptor로
수행한다. 같은 fingerprint를 model 실행 직전과 직후 다시 계산해 drift가 있으면 prediction을 publish하지
않는다. checkpoint SHA와 runtime artifact의 model pin도 exact 일치해야 한다.

이 pre/post 계약의 검출 대상은 승인 runtime의 persistent/observable drift다. 같은 UID의 별도 악성
process가 model 실행 중 runtime file을 바꿨다가 두 snapshot 전에 원복하는 transient ABA까지 atomic하게
봉인했다고 주장하지 않는다. 그런 actor는 process memory에도 간섭할 수 있어 현재 로컬 artifact 위협
경계 밖이다. live 실행은 approved isolated runtime에 concurrent package writer가 없다는 운영 전제를
요구하며, 이를 보장할 수 없으면 immutable/root-owned runtime 범위를 별도 승인받기 전 fail-closed다.

새 frame에는 GT가 없으므로 자동 bucket은 **실제 error 판정이 아니라 사람 검수 triage 신호**다.

| bucket | 결정론적 신호 | 자동으로 주장하지 않는 것 |
|---|---|---|
| `suspected_miss` | prediction 0개 | 게코가 반드시 있음 |
| `suspected_false_positive` | 같은 영상의 ±2.0초 mined frame에 detection이 없고, 현재 frame에 confidence `<0.50`인 detection 정확히 1개 | detection이 실제 오탐 |
| `duplicate_box_signal` | 같은 frame same-class box pair IoU ≥ 0.70 | 어느 box가 정답 |
| `partial_occlusion_signal` | box의 left/top이 frame 2% band 이내이거나 right/bottom이 반대쪽 98% band 이상 | 실제 가림 종류 |
| `source_diversity` | 아직 queue가 적은 source video에서 선택 | 동물 종·모프 이름 |

종 다양성은 영상별 cap과 round-robin으로 **source coverage**를 넓히는 방식으로만 근사한다. 영상 또는
Owner metadata에 검증된 species label이 없으면 모델·파일명·외형으로 종을 추정하지 않는다.

## 8. Blind queue 선택

정책 id는 `yolo26n-v25-blind-queue-v1`, seed는
`yolo26n-v25-historical-hardcase-reinforcement-v1`이다.

- bucket별 canonical rank를 만든 뒤 source video round-robin으로 선택한다.
- 한 영상 cap은 6장, 전체 cap은 210장이다.
- 한 frame이 여러 signal을 가지면 우선순위는 duplicate, suspected miss, suspected false positive,
  partial occlusion, source diversity 순이다. 모든 signal은 private review index에만 남는다.
- input이 부족하면 cap을 억지로 채우지 않는다. 모든 존재·decode 가능 영상을 처리하고 candidate가
  1장 이상이면 작은 queue도 `READY`; 0장이면 `V25_HARDCASE_QUEUE_SHORTAGE`다.

CVAT bundle에는 `V250001.jpg` 같은 sequence, 빈 COCO annotation skeleton, bbox 규칙만 넣는다.
각 image는 확장자만 JPEG가 아니라 Pillow decode format `JPEG`, empty EXIF, exact canonical JFIF info
(`1.1`, unit 0, density 1×1)여야 하며 PNG/text/ICC/XMP/comment metadata payload는 builder와 validator가
모두 거부한다.
source path/video SHA/frame index/model predictions/confidence/bucket은 bundle에 넣지 않는다. predictions를
그린 overlay도 만들지 않는다. private review index만 sequence와 provenance를 연결한다.

## 9. 사람 경험 계약

1. `[화면]` Owner는 source 이름이나 모델 bbox가 없는 익명 frame만 본다.
2. `[조작]` 보이는 각 게코의 머리·몸통 중심으로 tight bbox를 그리고, 가린 부분·화면 밖 꼬리를
   추정하지 않는다. 여러 마리면 각 개체를 따로 그린다.
3. `[조작]` 게코가 없거나 사람도 확신할 수 없으면 빈 frame으로 제출할 수 있다. 억지 positive를 만들지
   않는다.
4. `[반응]` validator는 image count·dimensions·category·bbox boundary·sequence bijection을 검사하되
   모델 prediction과 사람 bbox를 합치지 않는다.
5. `[감정]` Owner는 모델 답을 고치는 것이 아니라 새 시험지를 독립적으로 채운다는 감각을 유지한다.

READY 보고에는 비민감 집계로 이미지 수, 영상 coverage 수, CVAT zip/manifest/checksum 위치, 위 bbox
규칙, `장당 45~90초 + 업로드/최종검수 15분` 범위의 예상 시간을 제공한다.

## 10. Private publication과 one-shot 경계

- 새 attempt root directory는 0700, 모든 artifact/image/lock은 exact 0600 regular non-symlink다.
- 각 단계는 input SHA와 output path를 pin한 `STARTED` lock을 `O_EXCL`로 먼저 만든다.
- output은 no-overwrite이고 partial publish 0이다. directory output은 자기 소유 reservation으로 final
  name을 먼저 선점한 뒤 verified staging과 atomic exchange한다. staging ABA면 reservation으로 rollback해
  final name을 회수하고 제3자 inode는 quarantine namespace에 보존한다.
- 실패 cleanup은 mutable public pathname을 unlink하지 않고 자기 소유 inode를 quarantine/exchange한 경우만
  정리한다. 제3자 inode unlink는 0이다.
- 원본과 모든 불변 input은 pre/post size·SHA가 같아야 한다.
- conversation/public report에는 count/status/code SHA만 허용한다. 원문 이미지·GT·source identifier·
  credential은 private artifact 밖으로 출력하지 않는다.

## 11. Stage 순서와 write budget

1. Gate lineage/license/semantics/inclusion audit
2. Owner 35개 source inventory와 decode preflight
3. historical fingerprint independent validation
4. deterministic frame extraction
5. global exact/dHash dedup
6. frozen v2.4 shadow inference
7. deterministic hard-case selection
8. blind queue publication
9. independent acceptance
10. 사람 bbox 요청 후 중단

각 단계의 `db_select_count`, `r2_get_count`, `db_write_count`, `r2_write_count`, `service_write_count`,
`production_model_write_count`, `gme_write_count`, `labeling_web_write_count`는 모두 0이다. 이번 입력은 로컬
private source뿐이며 DB SELECT/R2 GET도 필요하지 않다.

## 12. Cross-runtime 계약

현재 host에 approved frozen v2.4 runtime이 없으면 shared environment를 수정하지 않는다. code/design/plan을
commit·push하고 `execution_repo`, exact 40-char commit, plan/design absolute path, implementation/runtime host,
private attempt root를 적은 handoff manifest를 만든 뒤 `verify_agent_handoff.py`의 `HANDOFF_OK`를 받아야
한다.

handoff는 두 commit과 repo 밖 validator manifest를 분리한다. 구현 commit `I`를 먼저 push하고, tracked
tracking record는 `I`를 가리키는 직계 child commit `H`로 별도 push한다. runtime checkout은 tracking
HEAD `H`가 아니라 exact `I`의 clean detached checkout이다. validator manifest는 repo 밖 private 경로에
만들어 `execution_repo`, plan/design, `commit_sha=I`, host/runtime을 front matter로 검증한다. input artifact
SHA는 validator가 해석하지 않는 임의 front-matter key로 넣지 않고, manifest body의 exact pin과 별도
preflight shell에서 lowercase 64-hex·regular non-symlink·raw bytes SHA 일치를 검사한다.

Mac mini에서는 별도 clean checkout의 HEAD `I`, checkpoint/dataset/freeze/code/runtime SHA를 독립 확인한다.
dedup 완료 frame bundle은 private manifest+익명 frame bytes의 exact directory SHA, input audit/historical/code/
dedup-ledger SHA를 고정한다. implementation host의 `prepare-owner-bundle`이 0600/no-overwrite bundle을 만들고,
runtime host의 `infer-build-queue`가 member set·mode·각 image SHA/dHash/dimensions·pre/post directory identity를
독립 검증한다. raw 35개 영상은 옮기지 않는다.
공유 venv는 수정하지 않고 기존 승인 runtime을 사용하되, preflight artifact의 raw SHA와 내부 model pin,
현재 Python/package/Ultralytics tree fingerprint를 모두 독립 재계산하고 model 실행 전후 exact 고정한다.

runtime 실행 증거는 `H`에 섞지 않는다. 실행 뒤 비민감 aggregate만 REPORT에 append한 별도 documentation
commit `R`을 만들며, `git diff I..H`는 tracking record 한 파일, `git diff H..R`은 REPORT 한 파일만
포함해야 한다. runtime checkout은 `R`을 따라가지 않고 끝까지 exact `I`다.

## 13. 완료·실패 조건

### Queue READY

- Gate audit exact bijection과 protected-role exclusion 위반 0
- 존재하는 모든 Owner MOV가 processed 또는 explicit safe exclusion
- historical 1,822 fingerprint coverage 완전
- global exact/dHash overlap 0
- frozen v2.4 inference provenance exact
- blind/public bundle에 prediction·source identity 0
- independent acceptance Critical/Important 0
- 모든 write/mutation counter 0, private mode/no-overwrite 위반 0

### Fail-closed

- Gate provenance/license/semantics가 모호한 record는 신규 후보에서 제외한다.
- historical fingerprint coverage가 불완전하면 Owner extraction/inference를 시작하지 않는다.
- frozen model/runtime SHA가 다르면 inference하지 않는다.
- 모든 frame이 중복·invalid로 제외되면 shortage로 멈춘다.
- 부분 queue나 failed staging을 READY로 승격하지 않는다.

## 14. 이번 범위 밖

- 사람 bbox 완료 전 v2.5 dataset materialization·학습·validation·test·external evaluation
- threshold/NMS 재선택
- formal future holdout 대체 또는 v2.4b shortage 해소 주장
- prediction bbox prelabel, 자동 bbox 수정, 자동 absence/behavior/skip/delete
- production/service/GME/model/labeling web 변경·배포
- DB/R2 read/write와 원본 이동·삭제·수정
