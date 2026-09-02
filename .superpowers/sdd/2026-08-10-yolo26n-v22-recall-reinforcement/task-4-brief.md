### Task 4: Mac mini 후보 320장 준비

**Files:**
- Create on Mac mini private artifact: `/Users/baek-end/private-rba/yolo26n-v22-candidates/attempt-20260811-owner-v3/`
- No repository file changes.

`attempt-20260810-owner-v1/`은 인공 shortage 실패 provenance로 동결한다. 덮어쓰기와 CVAT
업로드를 금지한다.
`attempt-20260810-owner-v2/`는 실행 PASS 뒤 final HP 103/HN 27 genuine shortage로 끝난
provenance다. v2도 덮어쓰거나 CVAT에 올리지 않는다.

v3의 HP 560/HN 530, 28 sources/night는 v2 accepted yield의 one-sided 95% LCB로 final
HP 220/HN 100을 보수적으로 계획한 bounded scale-up이다. metadata-only preflight에서 해당
선택이 가능한 값이며 기존 classifier, probe/review quota, dedup과 cap은 유지한다.

runner는 `--output`을 위 v3 절대경로 하나로만 허용한다. inventory는 `code/` 외 기존 artifact가
있으면 외부 read 전에 중단한다. analyze는 `code/`, `inventory-selection.private.json`,
`probe-sources.private.json`, `source-clips/`만 허용하고 probe/review/analyzed/manifest/ZIP 등
부분 실행 산출물이 있으면 덮어쓰거나 혼합하지 않는다.
`candidate_exhausted`는 후보 풀이 끝난 뒤 남은 frame quota 수,
`source_exhausted`는 probe 소진으로 source cap을 못 채운 source 수로 기록한다.

**Interfaces:**
- Consumes: Task 3 exact source commit, v2.1 dataset artifact, v2.1 checkpoint, Mac mini reporter read credentials.
- Produces: `V22_CANDIDATE_QUEUE_READY` or exact quota shortage report.

- [ ] **Step 1: exact code snapshot을 private artifact로 복사**

Run from MacBook worktree:

```bash
SOURCE_SHA=$(git rev-parse HEAD)
git archive --format=tar --add-virtual-file="source-commit.txt:$SOURCE_SHA" "$SOURCE_SHA" \
  scripts/build_yolo26n_v22_candidate_queue.py \
  scripts/run_yolo26n_v22_candidate_mining.py | \
ssh baek-end@baeg-endeuui-Macmini.local \
  'mkdir -p /Users/baek-end/private-rba/yolo26n-v22-candidates/attempt-20260811-owner-v3/code && tar -x -C /Users/baek-end/private-rba/yolo26n-v22-candidates/attempt-20260811-owner-v3/code'
```

Expected: remote `code/source-commit.txt`가 local `git rev-parse HEAD`와 일치한다. 이 과정은
`/Users/baek-end/petcam-lab`을 수정하지 않는다.

- [ ] **Step 2: inventory 실행**

Run on Mac mini using the reporter venv that provides `supabase`:

```bash
RUN=/Users/baek-end/private-rba/yolo26n-v22-candidates/attempt-20260811-owner-v3
PYTHON=/Users/baek-end/petcam-nightly-reporter/.venv/bin/python
PYTHONPATH="$RUN/code" "$PYTHON" \
  "$RUN/code/scripts/run_yolo26n_v22_candidate_mining.py" inventory \
  --output "$RUN" \
  --reporter-repo /Users/baek-end/petcam-nightly-reporter \
  --cutoff 2026-07-15T00:00:00Z \
  --existing-selection /Users/baek-end/private-rba/yolo26n-v21-targeted/attempt-20260810-owner-v2/candidate-manifest.private.json \
  --existing-review-csv /Users/baek-end/private-rba/yolo26n-owner-dataset-v21/attempt-20260810-owner-final-v1/combined-review.private.csv \
  --inventory-max-sources 1090 \
  --probe-hard-positive-sources 560 \
  --probe-hard-negative-sources 530 \
  --probe-max-sources-per-night 28 \
  --seed owner-v2.2
```

Expected: R2 GET 전에 source ID 없는 inventory pool/selection 집계가 stdout과
`inventory-selection.private.json`에 기록된다. HP 560/HN 530 exact가 아니면 download 없이
`V22_INVENTORY_SELECTION_SHORTAGE`로 종료하며 DB/R2 write는 0이다.

- [ ] **Step 3: v2.1 model로 24-frame probe와 review queue 생성**

```bash
RUN=/Users/baek-end/private-rba/yolo26n-v22-candidates/attempt-20260811-owner-v3
VENV='/Users/baek-end/Library/Application Support/petcam/yolo26n-day-night-gecko-detection/private/mps-smoke-20260809T191651+0900/venv'
PYTHONPATH="$RUN/code" "$VENV/bin/python" \
  "$RUN/code/scripts/run_yolo26n_v22_candidate_mining.py" analyze \
  --output "$RUN" \
  --model /Users/baek-end/private-rba/yolo26n-owner-dataset-v21/attempt-20260810-owner-final-v1/runs/baseline-960-v21/weights/best.pt \
  --existing-images /Users/baek-end/private-rba/yolo26n-owner-dataset-v21/attempt-20260810-owner-final-v1/input-images \
  --probe-frames-per-source 24 \
  --review-frames-per-source 2 \
  --hard-positive-frames 220 \
  --hard-negative-frames 100 \
  --max-frames-per-night 12 \
  --imgsz 960 \
  --inference-conf 0.05 \
  --seed owner-v2.2
```

Expected: 중복·unreadable frame은 같은 source의 다음 ranked probe와 같은 bucket reserve source로
backfill한다. exact 320장 또는 inventory downloaded/missing 및 bucket별 planned/accepted,
candidate/source exhaustion, night-cap block, requested/readable/decode/imwrite failure,
deduplicated/unreadable/shortfall이 fail-closed로 보고되며 shortage를 다른 bucket으로 채우지 않는다.

- [ ] **Step 4: 독립 queue preflight**

Run:

```bash
RUN=/Users/baek-end/private-rba/yolo26n-v22-candidates/attempt-20260811-owner-v3
python3 -c 'import json,pathlib; p=pathlib.Path("/Users/baek-end/private-rba/yolo26n-v22-candidates/attempt-20260811-owner-v3/candidate-manifest.private.json"); d=json.loads(p.read_text()); assert d["prediction_boxes_exposed_to_reviewer"] is False; assert d["db_write_count"] == 0; assert d["r2_write_count"] == 0; assert d["inventory_selection_counts"] == {"hard_positive": 560, "hard_negative": 530}; assert d["bucket_counts"] == {"hard_positive": 220, "hard_negative": 100}; print(d["status"], d["review_frame_count"], d["bucket_counts"], d["materialization_counts"])'
```

Expected: `V22_CANDIDATE_QUEUE_READY`, review count 320, hard-positive 220, hard-negative 100,
source/night cap 위반 0. 조건을 못 채우면 `V22_CANDIDATE_QUEUE_SHORTAGE`로 멈춘다.

---

## Task4b official review round 2 — immutable code snapshot

- 실행 implementation commit A: `a9429320ca3bb2a0ecce0826c9a38f6521bab49d`
- archive 대상은 docs HEAD가 아니라 위 A로 고정한다.
- 실행 전에 `source-commit.txt`와 아래 세 파일의 exact filename/SHA set을 helper import,
  model load, external read보다 먼저 검증한다.
  - reserve runner: `7cc77bbeee3cc736276dba1471774e6e42244a085b33bcf9acbc96c8242da73c`
  - v2.2 candidate mining helper: `33610d52916b0a4a44135172d781dee58342d4a67f8fae5ae8abcb7bb43706bb`
  - v2.2 candidate queue helper: `a692f0680e9fdfcdaac5ced0da937593b9edc1135868a9456a990b62cee201a9`
- stale commit, extra/missing file, 어느 한 파일 tamper도 fail-closed다.
- docs pin commit B는 A와 위 세 hash를 literal로 담되 실행 source에는 포함하지 않는다.
- live DB/R2/YOLO 실행은 0건이다.
