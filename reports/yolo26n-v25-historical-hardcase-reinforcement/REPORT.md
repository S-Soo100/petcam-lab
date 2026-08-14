# YOLO26n v2.5 historical hard-case 보강 후보 보고서

**상태:** BLOCKED_GATE_COCO_BBOX_CONTRACT
**기준 commit:** `5b7fb0ca9f7066d033a73179b7a19a5b071b6d0a`
**branch:** `codex/yolo-v25-historical-hardcase-reinforcement`

## 승인 경계

- 결과는 development-only blind bbox queue이며 formal future holdout이 아니다.
- validation 153, internal fixed-test 151, Owner external diagnostic 60은 mining·학습·재평가에서 제외한다.
- frozen v2.4b freeze, historical fingerprint, shortage inventory, 기존 locks/ledgers는 read-only다.
- 사람 bbox 완료 전 v2.5 dataset/train/eval을 시작하지 않는다.
- DB/R2/service/production model/GME/labeling web write·deploy는 0이다.

## 2026-08-14 구현 전 확인

- 시작 worktree clean, 기준 branch HEAD가 위 commit과 exact 일치했다.
- fresh baseline: `1809 passed, 5 skipped in 30.88s`.
- decision gate G1~G4 통과를 append했다.
- 설계·계획 독립 review fix round 2 최종: Spec PASS, Critical 0 / Important 0 / Minor 0.
- Owner source preflight: 기대 35, actual regular MOV 35, symlink 0, open 35, 첫/중간/끝 sample decode 35,
  decode failure 0.
- 기존 private artifact에서 source-video SHA 직접 scalar join은 0이었다. 이는 “과거 모델 노출 0” 증명이
  아니며 video-level ledger가 없다는 뜻이다. 모든 mined frame은 historical unique 1,822와 global
  SHA/dHash 비교를 계속 강제한다.

## TDD evidence

### Historical Gate/v2.4 audit

- initial RED: 새 module import 부재로 collection error 1.
- review-evidence RED: 새 three-ledger API 부재로 17 failed.
- file-level RED: `run_private_audit` 부재로 2 failed / 기존 20 passed.
- current GREEN: Gate raw provenance·late-publication attacks 포함 audit test 29 passed.
- sample audit, positive full-review, accepted manifest의 count/raw SHA/owner-verdict 교차 pin을 요구한다.
- accepted cohort 밖 Gate frame은 새 blind review 없이 train-eligible로 승격하지 않는다.

### Owner frame mining·shadow inference

- initial RED: 새 miner module import 부재로 collection error 1.
- decode RED: `mine_owner_video`/OpenCV boundary 부재로 2 failed.
- bucket RED: exact confidence/time/IoU/edge API 부재로 11 failed.
- inference RED: verified-checkpoint shadow API 부재로 2 failed.
- current GREEN: full-provenance prediction ledger·ordered pipeline 포함 builder test 41 passed.

### Blind queue·validator

- builder RED: selection/publication API 부재로 3 failed.
- validator RED: independent validator module 부재로 collection error 1.
- integration failure 1: quarantine residue가 public result root에 남는 root cause를 재현했다.
- fix: 아직 public이 아닌 self-owned staging 내부는 O_EXCL direct write를 사용해 residue 생성 자체를
  제거했다. mutable public path cleanup은 수행하지 않았다.
- current GREEN: FIFO·late-acceptance attacks 포함 validator test 5 passed.

### Independent implementation review fix cycle 1/3

- initial verdict: Critical 0 / Important 5 / Minor 1.
- adversarial RED: Gate 원본 미검증 4, protected-role inference 3, late-publication residue 3,
  FIFO/non-regular 2 = `12 failed, 55 passed`.
- operational RED: stage/prediction ledger와 CLI 부재 = `7 failed, 67 deselected`.
- Gate `manifest.csv`·세 COCO·raw image SHA/dimensions/bbox bijection을 실제 bytes로 검증한다.
  original Gate split이 `train`이 아닌 novel record는 별도 role exclusion으로 격리한다.
- inference 전에 role=`owner-development-video`를 요구하고 protected roles는 model load 전에 거부한다.
- prediction ledger는 input audit, historical fingerprint, checkpoint, freeze, current code bytes,
  runtime preflight의 여섯 SHA를 묶고 queue publisher가 ledger records와 exact cross-pin한다.
- inventory→mining→dedup→prediction→queue는 각 단계 직전 0600 O_EXCL STARTED lock과 별도
  no-overwrite private ledger를 낸다.
- audit/queue/acceptance가 final publication 이후 실패하면 hardened atomic exchange/quarantine으로
  exact self-owned inode만 success namespace에서 격리한다. rival inode unlink는 하지 않는다.
- FIFO/socket/device는 directory hashing·validation 전에 regular-file gate에서 거부한다.
- scene anchor exact 2.0초도 exclusion으로 고정했다.

### Independent implementation review fix cycle 2/3

- cycle 1 re-review: Critical 0 / Important 5 / Minor 0.
- RED: full Gate set/lineage/pin과 queue expected provenance 부재 `7 failed`; strict historical empty-ledger
  acceptance `1 failed`; cross-runtime bundle API/CLI 부재 `3 failed`.
- Gate audit는 expected SHA로 pin한 manifest·private lineage·세 COCO를 열고 `operational+labeled`
  전체 set의 exact bijection, manifest path↔clip id, lineage source/night, 모든 raw image SHA/dimensions를
  canonical aggregate로 고정한다. accepted 569 subset은 raw SHA·COCO bbox와 추가로 exact join한다.
- historical input은 CLI production path에서 unique 1,822, role total 1,973, global dHash policy,
  freeze SHA, parent artifact SHA 4개, zero-write, input-audit raw SHA cross-pin을 전부 요구한다.
- directory publish는 final name에 owned reservation을 먼저 no-overwrite 배치하고 verified staging과 atomic
  exchange한다. staging ABA는 exchange-back 뒤 owned reservation만 quarantine해 final path를 없애고 rival은
  보존한다.
- audit/acceptance도 input/output-pinned 0600 STARTED lock을 먼저 만든다.
- `prepare-owner-bundle`은 raw MOV가 있는 host에서 inventory→mining→dedup→0600 frame bundle까지만 수행한다.
  `infer-build-queue`는 runtime host에서 bundle directory SHA, provenance, member set, 각 image SHA/dHash/
  dimensions와 pre/post identity를 검증한 뒤 frozen inference→queue를 수행한다. raw MOV는 전송하지 않는다.
- directory hashing, bundle loader, validator의 file reads는 nonblocking verified snapshot을 사용해
  check-to-open FIFO/socket 교체도 거부한다.

### Independent implementation review fix cycle 3/3

- cycle 2 re-review: Critical 0 / Important 3 / Minor 0.
- fresh RED: duplicate COCO image/annotation id, reservation destination ABA, downstream queue SHA omission을
  각각 재현해 targeted `3 failed`를 확인했다.
- 각 COCO에서 image id와 annotation id의 uniqueness를 bijection 계약에 포함했다.
- destination reservation이 exchange 직전 rival로 바뀌면 atomic exchange-back으로 rival inode를 원래
  공개 pathname에 복구하고 self-owned expected tree만 staging namespace로 회수한다. 제3자 inode는
  unlink하지 않는다.
- prepare/infer API와 CLI는 다음 단계가 별도 재계산 없이 검증할 bundle, dedup ledger, prediction ledger,
  queue SHA를 모두 반환한다.
- targeted GREEN: `4 passed, 73 deselected`; scoped GREEN: `84 passed`.

### 이전 cycle 3 scoped verification

```text
84 passed in 0.46s
py_compile exit 0
git diff --check exit 0
full regression: 1893 passed, 5 skipped in 27.67s
```

### Cycle 3 final independent review

- verdict: Spec FAIL / Quality FAIL, Critical 0 / Important 4 / Minor 1.
- 실제 v2.4b freeze의 selected 계약에는 `duplicate=4`가 포함되지만 shadow inference가 이를 받지 않아
  live 실행은 freeze preflight에서 중단된다.
- Owner MOV는 snapshot fd 검증 뒤 mutable pathname으로 두 번 다시 열어 decode하므로 pathname ABA와
  non-regular 교체를 막는 immutable decode capability가 필요하다.
- runtime preflight artifact raw SHA만 확인하고 현재 Python/package/model runtime fingerprint를 재계산하지
  않아 shared runtime drift를 탐지하지 못한다.
- Gate COCO 세 split을 합친 뒤 filename set만 비교해 manifest split↔COCO split 결속과 전체 operational
  bbox finite/positive/bounds 검증이 빠져 있다.
- 독립 validator의 JPEG EXIF absence와 BBOX-RULES exact canonical bytes 검증 누락은 Minor다.
- 수정 cycle 3/3을 소진했으므로 commit·push·handoff·live audit/mining/inference/queue 생성을 금지하고
  fail-closed 상태로 멈췄다.

### 별도 승인 보안 수정 cycle 1/3

- 사용자가 이전 3회와 분리된 새 cycle을 명시 승인했다. 범위는 위 Important 4건과 같은 경계의 Minor
  1건뿐이며, 독립 review Critical/Important 0 전 commit·push·handoff·live 실행을 계속 금지한다.
- fresh adversarial RED: 실제 freeze `duplicate=4`, mutable MOV pathname regular/FIFO ABA, runtime drift,
  Gate split swap와 operational full-set NaN/Inf/degenerate/OOB bbox, JPEG EXIF, canonical rules 변조를
  `16 failed, 83 deselected`로 재현했다.
- Owner MOV는 inventory pin을 통과한 `O_NOFOLLOW|O_NONBLOCK` regular descriptor 하나를 두 decode pass가
  `/dev/fd`로 공유한다. 시작 전 full inventory를, 종료 시 descriptor device/inode/size/mtime/content SHA를
  재검증하며 mutable source pathname은 decoder에 전달하지 않는다.
- 실제 freeze selected를 exact `confidence=.25/nms_iou=.40/duplicate=4`로 고정하고 prediction ledger에도
  같은 값을 기록·검증한다.
- runtime preflight는 승인 artifact 내부의 Python binary, uv.lock, installed distribution set,
  Ultralytics package tree, Torch/TorchVision/NumPy/OpenCV/Pillow fingerprint를 현재 runtime에서 독립
  재계산한다. model 실행 전후 exact fingerprint가 다르면 publish 전에 실패한다. package file은
  no-follow regular descriptor bytes로 읽어 pathname ABA를 차단한다.
- Gate manifest split과 각 COCO file origin을 exact 결속하고, operational 전체 bbox를 finite/positive/
  area-consistent/in-bounds로 검증한다. validator는 JPEG EXIF absence와 BBOX-RULES raw canonical bytes를
  독립 확인한다.
- focused GREEN: 공격 경계 `15 passed, 84 deselected`, runtime tree pathname ABA `1 passed`, 세 scoped
  test 전체 `100 passed`.

### 별도 승인 보안 수정 cycle 2/3

- cycle 1 독립 보안 리뷰에서 Important 1건을 재현했다. manifest/COCO full operational set과 달리 private
  lineage는 reviewed subset에서만 조회돼, unreviewed operational record의 lineage 결손이 통과했다.
- fresh RED: 두 장 full set에서 unreviewed lineage row 하나를 제거하고 pinned lineage SHA를 갱신했을 때
  `DID NOT RAISE` 1건을 확인했다.
- fix: private lineage path set을 `operational+labeled` manifest/COCO full set과 exact bijection으로
  검증한다. missing·extra lineage 모두 live audit 전에 fail-closed다.
- 추가 RED: PNG bytes+text metadata를 `.jpg`로 넣고 SHA/dHash/zip을 다시 pin하면 validator가 성공하는
  형식 위장을 재현했다. builder와 validator 모두 actual JPEG format, empty EXIF, exact canonical JFIF
  metadata만 허용하도록 수정했고 JPEG EXIF/PNG-text 공격 `2 passed`로 닫았다.
- runtime pre/post fingerprint는 persistent/observable drift를 검출한다. 같은-UID 악성 process의
  model-execution 중 transient package ABA를 atomic runtime snapshot으로 해결했다고 주장하지 않는다.
  live는 concurrent package writer 없는 approved isolated runtime만 허용하며 이 운영 전제가 불명확하면
  별도 immutable runtime 승인 전 fail-closed다.
- GREEN: Gate audit 전체 `39 passed`; JPEG metadata focused `2 passed`.

### 새 보안 cycle 최종 독립 review와 verification

- 독립 security/spec review: Critical 0 / Important 0 / Minor 0, Spec PASS, Quality PASS.
- 별도 공격으로 lineage missing/extra, PNG-text/JPEG-COM metadata, runtime drift, source pathname ABA,
  split/bbox/publication 경계를 재확인했다.
- scoped: `102 passed`; py_compile PASS; 세 CLI help-contract PASS; changed-file diff-check PASS.
- cache/bytecode 없는 fresh full regression: `1911 passed, 5 skipped in 28.77s`.
- write/domain audit: 새 scripts에 DB/R2/network client 또는 production/service/model/GME/labeling-web mutation
  path 0, 모든 공개 write counter 0. live artifact 생성은 아직 0이다.

## Pending

- implementation commit/push와 exact-I runtime handoff
- Gate inclusion live audit, full Owner decode/mining, frozen v2.4 inference, blind queue acceptance
- 사람 bbox queue READY 또는 fail-closed terminal aggregate

## 2026-08-14 handoff와 live terminal

- implementation `I`: `70f7bd66fc6bdfcff463de39824fcf28082d4ab6`; local/remote branch exact push와
  clean status를 확인했다.
- tracked handoff record를 별도 commit으로 push했다. 첫 private manifest preflight는 checkpoint의
  `.pinned/` 위치를 확인하기 전에 0700 빈 v1 directory만 만들고 실패했다. v1은 삭제·재사용하지 않았다.
- Mac mini의 기존 dirty checkout은 그대로 보존했다. 별도 execution repo는 exact `I` detached HEAD이고
  tracked/untracked clean이다. v2 private manifest와 input raw pins는 0600/no-overwrite이며 실제 verifier가
  `HANDOFF_OK`를 반환했다. system Python 3.9 실패 뒤 shared env를 수정하지 않고 기존 승인 Python 3.12로
  verifier만 실행했다.
- Gate 표본 verdict는 기존 v2.4 deterministic selector와 원문 사람 verdict bytes로 재검산돼 60장 계약을
  만족했다. accepted 569장과 positive quarantine 9장의 preserved review lineage도 exact join됐다.
- hard stop: 현재 Gate manifest의 `operational+labeled` full set은 1,951장인데 preserved explicit private
  lineage는 578장뿐이다. missing 1,373, extra 0이다. 결손 source/night lineage를 파일명·timestamp에서
  추정하지 않았고 full-set exact bijection 전에 멈췄다.
- 독립 terminal audit도 같은 1,951/578/missing 1,373/extra 0과 downstream artifact 0을 재계산해
  Gate audit 전 fail-closed 판정을 확인했다.
- Gate normalized summary/lineage/expected-pin artifact, audit STARTED/result, Owner inventory/decode/mining/dedup,
  runtime inference, prediction, blind queue, acceptance artifact는 모두 0이다. validation153/internal151/
  external60 재평가와 DB/R2/service/production model/GME/labeling-web write/deploy도 0이다.
- terminal은 `BLOCKED_GATE_FULL_LINEAGE_SHORTAGE`다. 다음 안전한 선택은 (a) 1,951장 full-set의 explicit
  private source/night lineage를 제공하거나, (b) Gate 전체를 quarantine하고 Owner-only pipeline을 허용하는
  별도 설계·TDD·독립 review를 승인하는 것이다. 현 commit으로 subset 578만 몰래 승격하지 않는다.

## 2026-08-14 Owner-only 승인 cycle

- owner는 Gate 1,951건 전량을 후보·학습·선택에서 quarantine하고 Owner MOV 35개만 새 attempt에서
  development-only hard-case 원천으로 쓰는 변경을 승인했다.
- 명시 lineage 578건도 부분 채택하지 않는다. lineage 잔존 여부가 과거 검수 흐름과 결합돼 있어
  subset 채택은 선택편향을 만든다.
- 이 cycle은 기존 blocked attempt와 artifact를 보존하고, Gate candidate exact 0·Owner-only fresh
  attempt/no-overwrite를 RED부터 검증한 뒤에만 live 실행한다.

### Owner-only 문서·구현 보안 검증

- design/plan은 Gate operational+labeled 1,951건 전량 quarantine, candidate exact 0, preserved partial
  lineage 578건도 train 후보로 승격하지 않는 계약으로 최소 수정했다. partial subset의 과거 검수 경로
  의존성이 만드는 선택편향을 피하고 Owner MOV만 새 development-only 원천으로 사용한다.
- 문서 독립 review는 Critical 0 / Important 0 / Minor 0, Spec PASS, Quality APPROVE였다.
- 기존 full-lineage blocker를 재현한 뒤 Owner-only API/CLI, Gate candidate 0, missing lineage non-blocking,
  Gate record downstream 0, protected role 불변, fresh no-overwrite를 TDD로 구현했다.
- Gate raw bytes 전체의 비공개 content aggregate를 첫/두 번째 origin validation 사이 exact 비교한다.
  unreviewed raw image의 같은-dimension 영구 교체 RED 1건은 publication 전 fail-closed로 닫았다.
- 독립 review가 STARTED/result publish 직후 final pathname을 rival inode로 교체하면 성공할 수 있는 late
  ABA를 재현했다. lineage STARTED/result fresh RED는 `2 failed, 45 deselected`였고, audit 쌍을 포함한
  회귀는 최종 성공 경계에서 두 artifact의 device/inode/size/content SHA를 함께 재검증하도록 고쳤다.
  실패 cleanup은 self-owned result inode만 atomic quarantine 대상으로 삼고 rival inode는 보존한다.
- late ABA targeted GREEN: `4 passed, 45 deselected`; Owner-only audit/builder/validator scoped GREEN:
  `114 passed`.
- final independent security/spec re-review는 네 STARTED/result 경계를 직접 재공격했고 Critical 0 /
  Important 0 / Minor 0, Spec PASS, Quality PASS였다. raw mutation을 포함한 reviewer targeted는
  `5 passed`이며 third-party inode unlink 0과 partial success 0을 확인했다.
- fresh full regression: `1923 passed, 5 skipped in 28.51s`. 세 변경 script `py_compile`, CLI help-contract,
  `git diff --check`가 모두 exit 0이다. 승인된 변경 파일은 design/plan/decision/report, audit/builder와
  두 test의 정확히 8개이며 DB/R2/network/production/service/model/GME/labeling-web mutation path는 0이다.

### 첫 Owner-only handoff 이후 live-layout preflight

- implementation `I2=4cad3a31d54c5c7a1740e2e496018dfbd3083aac`, tracking `H2`를 push했고 MacBook/Mac mini
  별도 checkout이 clean detached exact I2임을 확인했다. repo 밖 handoff manifest는 0600이며 실제
  verifier가 `HANDOFF_OK`를 반환했다.
- handoff manifest writer를 처음 호출할 때 양쪽 fresh checkout에 uv가 만든 transient `.venv`는 승인
  runtime으로 사용하지 않았고 즉시 제거/휴지통 이동했다. 기존 shared runtime과 dirty checkout은
  수정하지 않았으며 이후 절대경로의 기존 승인 Python만 사용한다.
- live STARTED lock 0 상태에서 Gate manifest/COCO set은 operational+labeled 1,951 exact였고 실제 regular
  raw bytes도 `gate_root/raw/<manifest filename>`에 1,951개였다. 기존 구현의 테스트 전용
  `coco/images` 경로는 실제로 비어 있어 그대로 실행하면 전량 실패하는 root cause를 확인했다.
- 실제 SOT layout으로 test fixture를 먼저 바꾼 RED는 `4 failed, 17 passed, 28 deselected`였다. raw reader
  한 곳을 실제 `raw` layout으로 수정한 뒤 audit 전체 `49 passed`다. Gate bytes를 복사하거나 hardlink
  tree를 만들지 않았고 기존 attempt lock/result도 생성하지 않았다.
- 두 독립 review 모두 Critical 0 / Important 0 / Minor 0, Spec PASS, Quality PASS/APPROVE였다. 실제
  1,951 raw regular/missing 0/symlink 0과 비어 있는 legacy `coco/images`를 독립 확인했고 no-follow FD read,
  content aggregate pre/post 경계가 유지됨을 검수했다.
- 기존 canonical 0600 sample audit summary가 보존돼 있음을 확인했다. accepted/full-review와 두 원문 verdict,
  fixed selector seed로 재계산한 object/bytes와 exact 일치하고 293장 verdict raw SHA도 accepted/full artifact
  pin과 일치하므로 새 sample summary를 만들지 않는다.
- layout 수정 후 scoped는 `114 passed`, fresh full regression은 `1923 passed, 5 skipped in 28.35s`,
  `py_compile`과 `git diff --check`는 exit 0이다.

### Owner-only live terminal — Gate COCO bbox contract

- runtime-layout fix implementation `I3=af2a2f807233bcc35e556b60cac378cbac8a0574`와 tracking-only `H3`를
  push했다. MacBook/Mac mini checkout은 clean detached exact I3이며 새 remote owner-only-v2 private
  manifest는 0600, verifier는 `HANDOFF_OK`였다. 이전 owner-only-v1 handoff artifact는 덮어쓰지 않았다.
- fresh local owner-only-v1 attempt에서 Gate quarantine partial-lineage 578건을 0600/no-overwrite로
  publish했다. Gate operational+labeled 1,951, lineage covered 578/missing 1,373/extra 0, candidate 0 정책은
  유지된다.
- full Gate read-only preflight는 manifest↔COCO set 1,951 exact, split mismatch 0, raw regular 1,951,
  raw missing/symlink/nonregular/decode/dimension mismatch 0, reviewed lineage/box/image-SHA join mismatch 0이었다.
- terminal blocker는 pinned COCO의 bbox 계약이다. finite failure 0, nonpositive extent/area 0, area mismatch 0이지만
  negative-origin annotation 13건과 image bounds 초과 annotation 7건이 있어 승인된 full-set
  finite/positive/in-bounds gate를 통과하지 못했다. 개별 record나 source identifier는 기록하지 않는다.
- audit STARTED/result, Owner inventory/decode/mining/dedup, runtime inference/prediction, blind queue/acceptance는
  모두 0이다. validation153/internal151/external60 접근·재평가 0, DB/R2/service/production model/GME/
  labeling-web write/deploy 0, 원본 MOV/Gate raw/COCO 수정 0이다.
- private tree는 local files 6/dirs 3, remote files 2/dirs 1이며 file0600/dir0700 위반 0, symlink/nonregular 0이다.
  기존 locks/results와 blocked attempts는 삭제·덮어쓰기·재실행하지 않는다.
