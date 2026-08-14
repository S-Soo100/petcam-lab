# YOLO26n v2.5 historical hard-case 보강 후보 구현 계획

> **For Codex:** `superpowers:executing-plans`와 `superpowers:test-driven-development`로 Task를 순서대로
> 실행한다. 각 production 변경은 먼저 adversarial RED를 재현하고 최소 GREEN 뒤 self-review한다.

**Goal:** Gate 1,951건을 전량 격리하고, Owner MOV 35개에서만 frozen v2.4가 어려워하는 frame을
결정론적으로 선별해 예측이 숨겨진 private CVAT bbox queue를 만든다.

**Architecture:** Owner 입력 감사기는 Gate COCO/manifest/raw bytes/partial lineage를 전혀 받거나 읽지 않고
`gate_policy=quarantine_all`, `gate_candidate_count=0`, `gate_inputs_consumed=false`만 exact provenance로
고정한다. Gate 감사 결과는 immutable historical report에만 남는다. Owner miner는 source file descriptor snapshot, sequential decode, uniform+scene-aware frame mining,
global SHA/dHash dedup을 수행한다. frozen predictor는 verified immutable checkpoint capability만 받고
prediction을 private signal로 남긴다. queue publisher와 별도 validator가 익명 image/COCO bundle과 private
review index를 독립 검증한다.

**Tech Stack:** Python 3.12, pytest, OpenCV, Pillow, NumPy, Ultralytics YOLO26n(승인된 isolated runtime만),
canonical JSON/CSV, SHA-256, POSIX no-overwrite publication.

**Design:**
[`2026-08-14-yolo26n-v25-historical-hardcase-reinforcement-design.md`](../specs/2026-08-14-yolo26n-v25-historical-hardcase-reinforcement-design.md)

**Global constraints:**

- v2.4 train 1,458장은 read-only parent다.
- validation 153, internal fixed-test 151, Owner external 60은 mining·학습·재평가 0이다.
- v2.4b freeze, seven prediction ledgers, one-shot locks, historical fingerprint ledger, shortage inventory를
  삭제·덮어쓰기·재실행하지 않는다.
- DB/R2/service/production model/GME/labeling web read/write/deploy는 모두 0이다.
- 원본 이미지·영상·GT·source identifier·credential은 public report와 terminal summary에 출력하지 않는다.
- 새 artifact는 attempt root 안 0600, directory 0700, regular non-symlink, no-overwrite, one-shot이다.
- 사람 bbox 완료 전 v2.5 dataset/train/eval을 시작하지 않는다.

---

## 2026-08-14 Owner-only 수정 cycle 실행 우선순위

### 2026-08-14 Gate runtime dependency 제거 정정 (최우선)

이 정정은 아래 Amendment A~D보다 우선한다. 기존 구현은 candidate를 0으로 만들고도 Gate raw/COCO/lineage를
train-ready bbox 계약으로 읽어 격리 데이터의 13/7 defect가 Owner 흐름을 막았다. 이는 승인된 decoupling의
구현 버그다.

- `audit-owner-only`와 `run_owner_only_input_audit()`의 입력은 v2.4 dataset manifest와 historical fingerprint
  ledger 두 개뿐이다. Gate path/artifact 옵션은 unknown/TypeError로 거부한다.
- output exact literals는 `gate_policy=quarantine_all`, `gate_candidate_count=0`,
  `gate_inputs_consumed=false`다. 1,951/578/1,373은 REPORT의 과거 설명일 뿐 runtime pin이 아니다.
- `prepare-gate-quarantine-lineage`와 raw Gate validator는 historical 도구로만 보존하며 fresh Owner attempt나
  handoff에서 실행하지 않는다.
- RED는 old Gate-required API/consumer, Gate CLI option acceptance, literal mutation, Gate-derived identity leak를
  재현한다. protected 153/151/60과 historical 1,822 검증, no-overwrite/late ABA는 유지한다.
- fresh execution order는 `audit-owner-only → prepare-owner-bundle → infer-build-queue → independent acceptance`다.
  이전 failed attempt와 lock은 삭제·덮어쓰기·재사용하지 않는다.
- 이 정정의 새 implementation/tracking/report commit은 각각 `I4/H4/R4`로 부른다. `H4`는 `I4`의
  tracking-file-only 직계 child이고 runtime checkout은 끝까지 clean detached exact `I4`다. repo 밖 0600
  validator manifest는 `commit_sha=I4`와 새 fresh attempt root만 가리킨다. 아래 `I2/H2/R2` 및 Gate
  artifact handoff 문구는 과거 실행 이력이며 이번 live 명령에 사용하지 않는다.

이 절이 아래 원래 Task 1~8보다 우선한다. 원래 Task는 `de5fe79`까지의 구현·검증 이력으로 보존하며
신규 파일 생성이나 missing-module RED를 다시 실행하지 않는다. 이번 승인 cycle은 다음 네 Task만 기존
파일에 TDD로 추가한다.

### Amendment A: 문서와 partial-lineage capability

- Modify: `docs/decision-gate.md`
- Modify: design/plan/REPORT
- Modify: `scripts/audit_yolo26n_v25_reinforcement_inputs.py`
- Modify: `tests/test_audit_yolo26n_v25_reinforcement_inputs.py`
- RED는 기존 full-lineage validator가 578/1,951에서 `Gate origin artifact contract mismatch`로 막히는
  실제 동작, old schema consumer가 Owner-only audit를 거부하는 동작이다.
- `prepare_gate_quarantine_lineage()`와 CLI `prepare-gate-quarantine-lineage`는 pinned accepted/full-review
  bytes에서 578개 canonical lineage만 0600/no-overwrite로 publish한다.
- `audit_gate_quarantine()`와 CLI `audit-owner-only`는 명시 lineage path와
  `expected_gate_sha256={manifest,lineage,coco:*}`를 다시 검증하고 missing 1,373/extra 0을 기록하되
  candidate 0/quarantine 1,951을 고정한다.

### Amendment B: Owner-only consumer와 namespace

- Modify: `scripts/build_yolo26n_v25_owner_hardcase_queue.py`
- Modify: `tests/test_build_yolo26n_v25_owner_hardcase_queue.py`
- owner pipeline과 cross-runtime prepare/infer는 오직 `yolo26n-v25-owner-only-input-audit-v1` /
  `V25_OWNER_ONLY_INPUT_AUDIT_READY`를 받고 candidate 0, quarantine==operational, extra 0을 검증한다.
- legacy inclusion audit, nonzero candidate, Gate record field가 있으면 decode/model load 전에 실패한다.
- 기존 blocked attempt path가 존재하면 실패하고 fresh 0700 path만 만든다.

### Amendment C: verification/review/commit

- Owner-only focused RED→GREEN, 기존 102 scoped, full pytest, py_compile, diff-check, SHA/dHash/role/output ABA
  mutation과 DB/R2/service/production write-path audit를 실행한다.
- 독립 spec/security review Critical·Important 0 전 commit/push/handoff/live 실행을 금지한다.
- 승인 파일만 명시 stage한 새 implementation commit `I2`를 push하고 remote exact SHA를 확인한다.

### Amendment D: exact-I2 live execution

- 기존 blocked local/Mac mini attempt와 lock은 삭제·덮어쓰기·재사용하지 않는다.
- MacBook prepare host와 Mac mini inference host 모두 별도 clean detached exact `I2` checkout을 사용한다.
- 새 tracked handoff record `H2`와 repo 밖 0600 validator manifest를 만들고 `HANDOFF_OK` 뒤에만 실행한다.
- fresh owner-only attempt에서 partial-lineage → quarantine audit → inventory → verified FD decode → historical
  dedup → bundle → frozen inference → blind queue → independent acceptance 순서를 한 번만 실행한다.

---

## Task 1: Decision/design/plan 계약 고정

**Files:**

- Modify: `docs/decision-gate.md`
- Modify: `docs/superpowers/specs/2026-08-14-yolo26n-v25-historical-hardcase-reinforcement-design.md`
- Modify: `docs/superpowers/plans/2026-08-14-yolo26n-v25-historical-hardcase-reinforcement.md`

### Step 1: Current boundary 확인

Run:

```bash
git status --short
git branch --show-current
git rev-parse HEAD
git merge-base --is-ancestor 5b7fb0ca9f7066d033a73179b7a19a5b071b6d0a HEAD
uv run pytest -q
```

Expected: 새 전용 `codex/` branch, parent 포함, baseline `1809 passed, 5 skipped` 이상.

### Step 2: Decision gate append

네 gate와 reject 대안을 append-only로 기록한다. 과거 결정을 수정하지 않는다.

### Step 3: 설계·계획 self-review

Run:

```bash
rg -n "validation|fixed-test|external|formal future|사람 bbox|write|no-overwrite|dHash" \
  docs/superpowers/specs/2026-08-14-yolo26n-v25-historical-hardcase-reinforcement-design.md \
  docs/superpowers/plans/2026-08-14-yolo26n-v25-historical-hardcase-reinforcement.md
git diff --check
```

Expected: 역할 혼합 0, whitespace error 0.

---

## Task 2: Gate 전량 quarantine 감사와 Owner-only capability

**Files:**

- Modify: `scripts/audit_yolo26n_v25_reinforcement_inputs.py`
- Modify: `tests/test_audit_yolo26n_v25_reinforcement_inputs.py`

### Step 1: Owner-only RED tests를 먼저 작성

Tests cover:

- Gate `operational+labeled` candidate exact 0, quarantine count는 full set과 exact 동일
- accepted 569 + positive quarantine 9 partial lineage만 있어도 missing 1,373을 기록하고 Owner-only READY
- partial 578을 new candidate로 승격하지 않음(선택편향 방지)
- partial lineage extra·raw manifest/COCO/image/bbox 변조는 계속 fail-closed
- Gate source path/image SHA/bbox record가 owner-only audit/bundle/prediction/queue에 0
- validation153/internal151/external60 protected role 불변
- 기존 blocked attempt 재사용·덮어쓰기 거부, fresh attempt만 허용
- accepted/full-review raw pins에서 canonical partial-lineage 578건을 0600/no-overwrite/STARTED로 만들고,
  audit가 명시 경로와 expected raw SHA를 다시 검증
- CLI `prepare-gate-quarantine-lineage` → `audit-owner-only` 순서와 status consumer migration

- Gate manifest/COCO/image exact bijection
- 실제 Gate SOT의 image bytes는 `gate_root/raw/<manifest filename>`에서 no-follow regular read하며,
  비어 있는 `coco/images`를 입력으로 추정하거나 채우지 않음
- manifest `split`과 `train.json`/`val.json`/`test.json` origin exact 결속; split swap/복제 거부
- private lineage path set은 `operational+labeled` manifest/COCO의 strict subset만 허용; missing은 count,
  extra는 거부
- `operational + labeled=yes` full set을 quarantine 대상으로 고정
- owner-operated/private-training license evidence는 검증하지만 이번 후보 사용 권한은 0
- single `gecko`; reviewed subset뿐 아니라 operational full-set bbox의 finite/positive/area-consistent/in-bounds
  검증(NaN/Inf/degenerate/negative/OOB 거부)
- v2.4 sample audit summary, positive full-review result, final accepted manifest의 schema/count/raw SHA/
  owner-verdict SHA 교차 pin 필수
- positive selected set은 full-review accepted 284장과 exact 일치, quarantined 9장 제외
- negative 285장은 sample negative 20장 mislabeled 0 정책 cohort로만 허용
- accepted 569장과 positive quarantine 9장을 포함한 Gate 전체의 train-eligible 승격 금지
- v2.4 dataset schema/count `1762`, split `1458/153/151`
- v2.4 Gate derivation은 exclusion 감사 이력으로만 검증하고 candidate 생성에 사용하지 않음
- protected historical fingerprint unique 1,822/role 1,973 pin
- protected roles와 historical exact/dHash exclusion ledger는 Owner frame dedup 기준으로만 사용
- unresolved Gate lineage는 count로 기록하고 ambiguous/old val-test/non-operational은 전량 quarantine
- zero Gate candidates만 READY result
- input path/source id가 public exception/CLI stderr에 새지 않음
- output 0600/no-overwrite/pre-post SHA/late ABA/third-party inode preservation

### Step 2: RED 실행

```bash
uv run pytest -q tests/test_audit_yolo26n_v25_reinforcement_inputs.py
```

Expected: 기존 full-lineage exact bijection이 partial 578/missing 1,373에서 실패하고, old audit
schema/status consumer가 Owner-only artifact를 거부한다.

### Step 3: 최소 감사기 구현

Public functions:

```python
def prepare_gate_quarantine_lineage(
    *, accepted_review: Path, positive_full_review_result: Path,
    expected_sha256: Mapping[str, str], output: Path, started_output: Path,
) -> dict[str, object]: ...

def audit_gate_quarantine(
    *, gate_root: Path, gate_manifest: Path, gate_coco_paths: Sequence[Path],
    gate_lineage: Path, expected_gate_sha256: Mapping[str, str],
    sample_audit_summary: Path, positive_full_review_result: Path,
    accepted_review: Path, v24_dataset_manifest: Path,
    historical_fingerprints: Path,
) -> dict[str, object]: ...

def publish_private_audit(*, audit: Mapping[str, object], output: Path) -> str: ...
```

Output schema/status: `yolo26n-v25-owner-only-input-audit-v1` /
`V25_OWNER_ONLY_INPUT_AUDIT_READY`. Output에는 Gate record를 넣지 않고 quarantine/coverage count와
input/code SHA만 둔다.

### Step 4: GREEN과 mutation probes

```bash
uv run pytest -q tests/test_audit_yolo26n_v25_reinforcement_inputs.py
uv run python -m py_compile scripts/audit_yolo26n_v25_reinforcement_inputs.py
git diff --check
```

Mutate one image SHA, one bbox, one split role, one accepted-review pin and confirm each test fails.

---

## Task 3: Owner source inventory와 deterministic frame mining

**Files:**

- Modify: `scripts/build_yolo26n_v25_owner_hardcase_queue.py`
- Modify: `tests/test_build_yolo26n_v25_owner_hardcase_queue.py`

### Step 1: Inventory/mining tests를 먼저 작성

Tests cover:

- only direct-child `.MOV`, regular non-symlink, expected count recorded but not fabricated
- deterministic source ordering by source SHA, never filename
- one-shot `O_NOFOLLOW|O_NONBLOCK` regular-file descriptor snapshot과 pre/post device/inode/size/mtime/SHA
- OpenCV의 두 decode pass가 mutable pathname을 재개방하지 않고 같은 verified `/dev/fd` capability만 소비
- zero/invalid fps, dimensions, frame count, decode failures become safe aggregate exclusions
- OpenCV capture release on every path
- uniform index formula including `N=1`, short videos, duplicate rounded indices
- scene scan exactly 1-second cadence, 64×36 grayscale MAD
- 1-second uniform exclusion, 2-second scene spacing, deterministic tie break
- maximum 12 frames/video
- output frame encoded deterministically with dimensions/SHA pin
- historical exact SHA and dHash `<=2` reject, distance `3` accept
- new-pool global dedup canonical keeper independent of discovery order
- historical ledger coverage/schema/SHA mismatch stops before decode/materialization
- no source filename/path in public summary or safe exception
- raw input unchanged and private output 0600/no-overwrite

### Step 2: RED 실행

```bash
uv run pytest -q tests/test_build_yolo26n_v25_owner_hardcase_queue.py \
  -k 'inventory or uniform or scene or dedup or historical'
```

Expected: new API absent or explicit NotImplemented failure.

### Step 3: Minimal inventory/miner 구현

The miner exposes injected decoder/encoder boundaries for unit tests. Production uses sequential OpenCV decode and
Pillow deterministic JPEG encoding. It never shells out with a source path and never writes beside originals.

Intermediate schemas:

- `yolo26n-v25-owner-source-inventory-v1`
- `yolo26n-v25-mined-frame-ledger-v1`
- status `V25_OWNER_SOURCES_AUDITED` / `V25_MINED_FRAMES_READY`

### Step 4: GREEN과 file mutation audit

```bash
uv run pytest -q tests/test_build_yolo26n_v25_owner_hardcase_queue.py \
  -k 'inventory or uniform or scene or dedup or historical'
uv run python -m py_compile scripts/build_yolo26n_v25_owner_hardcase_queue.py
git diff --check
```

Adversarial probes replace source path after open with a regular rival or FIFO, verify decoder receives only the
opened descriptor capability, alter one historical dHash, and swap destination after publication. Third-party paths
must survive.

---

## Task 4: Frozen v2.4 inference와 hard-case bucket

**Files:**

- Modify: `scripts/build_yolo26n_v25_owner_hardcase_queue.py`
- Modify: `tests/test_build_yolo26n_v25_owner_hardcase_queue.py`

### Step 1: Predictor/bucket RED tests 작성

Tests cover:

- exact v2.4 checkpoint SHA + v2.4b freeze SHA + dataset/code/runtime pins
- actual freeze selected exact `confidence=.25/nms_iou=.40/duplicate=4`; prediction ledger same pin
- runtime artifact의 Python binary/uv.lock/distribution set/Ultralytics tree/Torch/TorchVision/NumPy/OpenCV/Pillow
  fingerprint를 현재 runtime에서 독립 재계산하고 model execution 전후 exact 비교
- runtime tree/input reads는 verified regular-file descriptor를 사용하며 pathname ABA/symlink/non-regular 거부
- pre/post는 persistent runtime drift detector이며 same-UID transient writer에 대한 atomic runtime snapshot
  주장은 하지 않음; live는 concurrent writer 없는 approved isolated runtime만 허용하고 불명확하면 block
- immutable verified checkpoint bytes capability; mutable path is never handed to model factory
- fixed `imgsz=960/conf=.25/nms=.40/max_det=50`
- validation/test/external inputs rejected by role before prediction
- zero boxes=`suspected_miss`
- suspected false-positive는 현재 detection 정확히 1개·confidence `<0.50`·같은 source의 ±2.0초
  다른 mined frame detection 0개일 때만 성립; `.50`, `2.0초` 경계 tests
- same-class IoU 0.69/0.70 duplicate boundary
- partial occlusion은 left/top `<=2%` 또는 right/bottom `>=98%`만 사용; temporal 잘림 추정은 제거
- source-diversity is round-robin only; no automatic species label
- multiple signal canonical priority and stable rank
- output prediction ledger private only, no prediction in blind/public record
- checkpoint/frame/output late replacement fails before success

### Step 2: RED 실행

```bash
uv run pytest -q tests/test_build_yolo26n_v25_owner_hardcase_queue.py \
  -k 'predict or bucket or duplicate or occlusion or diversity'
```

### Step 3: Minimal inference/bucket 구현

Factory API receives `_VerifiedCheckpoint(payload: bytes, sha256: str)` and verified frame payloads. Production
adapter exists only for the isolated runtime and has no unsafe path fallback.

### Step 4: GREEN

```bash
uv run pytest -q tests/test_build_yolo26n_v25_owner_hardcase_queue.py
uv run python -m py_compile scripts/build_yolo26n_v25_owner_hardcase_queue.py
git diff --check
```

---

## Task 5: Blind CVAT queue publication과 독립 validator

**Files:**

- Modify: `scripts/build_yolo26n_v25_owner_hardcase_queue.py`
- Modify: `scripts/validate_yolo26n_v25_blind_queue.py`
- Modify: `tests/test_build_yolo26n_v25_owner_hardcase_queue.py`
- Modify: `tests/test_validate_yolo26n_v25_blind_queue.py`

### Step 1: Queue/validator RED tests 작성

Tests cover:

- source round-robin, per-video cap 6, total cap 210, multi-signal priority
- deterministic `V25####` sequence and exact image/index/COCO bijection
- CVAT category exactly one `gecko`; initial annotations empty
- empty-frame allowed contract present
- no source ref/path/video SHA/frame index/prediction/confidence/bucket in public bundle
- private review index pins every public image SHA and private mining/prediction record
- anonymous image EXIF stripped
- builder/validator 모두 actual Pillow format `JPEG`, exact canonical JFIF info, EXIF/ICC/XMP/comment/text
  metadata absence를 검증하고 PNG bytes의 `.jpg` 위장을 거부
- validator도 `BBOX-RULES.md` canonical raw bytes를 독립 exact 검증
- directory 0700/files 0600/non-symlink/no-overwrite/one-shot lock
- pair/directory publication atomic; no transient partial success
- parent/staging/output/coordinator late ABA detected at final success boundary
- failure cleanup relocates only verified self-owned inode; third-party inode unlink 0
- validator independently recomputes SHA/dimensions/counts/permissions/forbidden keys
- queue 0=`V25_HARDCASE_QUEUE_SHORTAGE`, queue ≥1=`V25_BLIND_QUEUE_READY`

### Step 2: RED 실행

```bash
uv run pytest -q tests/test_validate_yolo26n_v25_blind_queue.py
```

### Step 3: Minimal publisher/validator 구현

Bundle contains:

- `images/V25####.jpg`
- `annotations.coco.json` with images/category and empty annotations
- `BBOX-RULES.md`
- `queue-manifest.json` without private identity
- `cvat-upload.zip` (images, annotations, rules, manifest exact member set; 0600/no-overwrite)
- separate sibling `review-index.private.json`
- `acceptance.private.json`

Validator는 zip raw SHA, exact member set, 각 member가 published bundle bytes와 같은지, forbidden
prediction/source metadata가 zip에도 0인지 독립 확인한다.

### Step 4: GREEN + integrated regression

```bash
uv run pytest -q \
  tests/test_audit_yolo26n_v25_reinforcement_inputs.py \
  tests/test_build_yolo26n_v25_owner_hardcase_queue.py \
  tests/test_validate_yolo26n_v25_blind_queue.py
uv run python -m py_compile \
  scripts/audit_yolo26n_v25_reinforcement_inputs.py \
  scripts/build_yolo26n_v25_owner_hardcase_queue.py \
  scripts/validate_yolo26n_v25_blind_queue.py
git diff --check
```

---

## Task 6: Independent review, full regression, commit/push

**Files:**

- Modify: `reports/yolo26n-v25-historical-hardcase-reinforcement/REPORT.md`
- Modify: `.superpowers/sdd/2026-08-14-yolo26n-v25-historical-hardcase-reinforcement/progress.md`

### Step 1: Independent code/spec review

Reviewer checks at minimum:

- protected-role leakage and test/external inference 0
- Gate full artifact strictness, partial-lineage extra 0, candidate exact 0, Owner artifact identity leak 0
- historical global dHash coverage
- path/inode/TOCTOU publication and third-party unlink 0
- blind bundle prediction/source leak 0
- no training/deploy/runtime mutation

Critical or Important finding 1개 이상이면 adversarial RED부터 고치며 한 cycle 최대 3회다. 3회 뒤에도 남으면
commit/push/runtime 실행을 멈추고 blocker를 보고한다.

### Step 2: Fresh verification

```bash
uv run pytest -q
uv run python -m py_compile \
  scripts/audit_yolo26n_v25_reinforcement_inputs.py \
  scripts/build_yolo26n_v25_owner_hardcase_queue.py \
  scripts/validate_yolo26n_v25_blind_queue.py
git diff --check
git status --short
```

Run mutation probes for SHA, dHash, role, bbox, checkpoint, output ABA. Audit production-domain strings and changed
files. The report records commands/counts/status only, never private identifiers.

### Step 3: Implementation commit `I2` and push

Explicitly stage only Task files. Never use `git add .`.

```bash
git add \
  docs/decision-gate.md \
  docs/superpowers/specs/2026-08-14-yolo26n-v25-historical-hardcase-reinforcement-design.md \
  docs/superpowers/plans/2026-08-14-yolo26n-v25-historical-hardcase-reinforcement.md \
  scripts/audit_yolo26n_v25_reinforcement_inputs.py \
  scripts/build_yolo26n_v25_owner_hardcase_queue.py \
  scripts/validate_yolo26n_v25_blind_queue.py \
  tests/test_audit_yolo26n_v25_reinforcement_inputs.py \
  tests/test_build_yolo26n_v25_owner_hardcase_queue.py \
  tests/test_validate_yolo26n_v25_blind_queue.py \
  reports/yolo26n-v25-historical-hardcase-reinforcement/REPORT.md
git diff --cached --check
git commit -m "feat: YOLO v2.5 hard-case blind bbox queue"
git push -u origin codex/yolo-v25-historical-hardcase-reinforcement
```

이 SHA를 `I2`로 기록하고 remote exact SHA와 clean status를 확인한다. handoff tracking 문서는 아직 만들지
않는다.

---

## Task 7: Cross-runtime handoff와 live private 실행

**Files:**

- Modify: `docs/superpowers/plans/2026-08-14-yolo26n-v25-historical-hardcase-reinforcement-handoff.md`

### Step 1: MacBook exact-I read-only preflight

- `audit-owner-only`, `prepare-owner-bundle`은 별도 clean detached exact `I2`
  execution checkout에서만 실행하고 tracked/untracked clean을 확인한다.
- Owner source root has expected/actual `.MOV` aggregate.
- v2.4 dataset manifest and historical fingerprint location are discovered from prior private handoff; no guessing.
- Gate root/manifest/COCO/lineage/review evidence는 handoff input이나 preflight 대상이 아니다.
- local shared Python environment is not modified.

### Step 2: Tracked record commit `H2`

Tracked handoff record는 exact implementation commit `I2`, plan/design의 `I2` 내부 절대경로, runtime host,
private validator manifest 예정 경로를 적는다. 이 문서만 수정한 `I2`의 직계 child commit `H2`를 만들고
push한다. `git diff I2..H2`는 tracking record만이어야 한다.

### Step 3: Repo 밖 validator manifest와 HANDOFF_OK

Mac mini 별도 execution checkout을 exact `I2` detached HEAD로 만들고 clean을 확인한다. repo 밖 0600 private
manifest front matter에는 validator가 지원하는 `execution_repo`, `commit_sha=I2`, implementation/runtime host,
plan/design absolute path, runtime kind만 기록한다. input artifact SHA는 body exact pin으로 적고 별도 preflight
shell이 lowercase 64-hex, regular non-symlink, raw bytes SHA, body pin 일치를 검사한다. Then run:

```bash
uv run python scripts/verify_agent_handoff.py --manifest /absolute/handoff.md
```

Expected: exact `HANDOFF_OK`. Without it, do not run Mac mini commands.

### Step 4: Clean runtime preflight

On Mac mini separate clean checkout:

- HEAD equals exact implementation commit `I2` and tracked/untracked status is clean.
- approved YOLO runtime exists; package/runtime fingerprint equals handoff and shared env is unchanged.
- v2.4 checkpoint, dataset manifest, freeze, historical fingerprint and code SHA match.
- private attempt root is new 0700; output paths do not exist.

If no approved runtime exists, report blocker before making an environment.

### Step 5: Execute in order

1. v2.4 dataset/historical fingerprint 두 pin만으로 Gate-free Owner-only input audit
2. publish Owner source inventory/decode ledger
3. validate historical fingerprint
4. `prepare-owner-bundle`: STARTED locks → inventory → mining → strict historical 1,822/role 1,973
   validation → global dedup → 0600 frame bundle on implementation host
5. transfer only the deduped bundle if runtime is remote; verify exact directory SHA and provenance both ends
6. `infer-build-queue`: bundle member/image pre/post verification → frozen v2.4 inference and private signals
7. blind queue build
8. independent acceptance

No one-shot stage is rerun after a partial/error result. Existing v2.4b outputs are read-only.

### Step 6: Post-run report commit `R2`

Runtime이 terminal status에 도달한 뒤에만 비민감 count/status/SHA/verification command를
`reports/yolo26n-v25-historical-hardcase-reinforcement/REPORT.md`에 append한다. source identifier, 원문
image/GT/prediction은 쓰지 않는다. REPORT 한 파일만 stage해 `H2`의 child documentation commit `R2`을
만들고 push한다.

```bash
git diff --name-only I2..H2
# exactly the tracked handoff record
git diff --name-only H2..R2
# exactly reports/yolo26n-v25-historical-hardcase-reinforcement/REPORT.md
```

Runtime clean checkout은 보고 commit을 따라가지 않고 계속 exact `I2`다.

---

## Task 8: 사람 bbox handoff 또는 shortage

If `V25_BLIND_QUEUE_READY`, report only:

- exact anonymous image count and source-video coverage aggregate
- Gate policy quarantine-all / candidate 0 / inputs-consumed false (Gate historical counts는 별도 REPORT에만 유지)
- Owner expected/existing/decoded/excluded/dedup/bucket aggregate
- CVAT zip, public manifest, private review index, acceptance artifact absolute paths and SHA
- bbox rules: visible head/body, no occluded/off-frame extrapolation, multiple animals separate, empty frame allowed
- expected time: `queue_count × 45~90 seconds + 15 minutes`
- explicit stop: no v2.5 training before returned human annotation passes a separate validator and approval

If queue is empty or a security/provenance/runtime gate fails, report only safe aggregate, exact terminal status, and
the smallest safe next option. Do not print filenames, source ids, original images/GT, predictions, or credentials.

Use `superpowers:verification-before-completion` before the status claim and
`superpowers:finishing-a-development-branch` only to report branch/handoff state—not to merge or deploy.
