### Task 4: Mac mini 후보 320장 준비

**Files:**
- Create on Mac mini private artifact: `/Users/baek-end/private-rba/yolo26n-v22-candidates/attempt-20260810-owner-v2/`
- No repository file changes.

`attempt-20260810-owner-v1/`은 인공 shortage 실패 provenance로 동결한다. 덮어쓰기와 CVAT
업로드를 금지한다.

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
  'mkdir -p /Users/baek-end/private-rba/yolo26n-v22-candidates/attempt-20260810-owner-v2/code && tar -x -C /Users/baek-end/private-rba/yolo26n-v22-candidates/attempt-20260810-owner-v2/code'
```

Expected: remote `code/source-commit.txt`가 local `git rev-parse HEAD`와 일치한다. 이 과정은
`/Users/baek-end/petcam-lab`을 수정하지 않는다.

- [ ] **Step 2: inventory 실행**

Run on Mac mini using the reporter venv that provides `supabase`:

```bash
RUN=/Users/baek-end/private-rba/yolo26n-v22-candidates/attempt-20260810-owner-v2
PYTHON=/Users/baek-end/petcam-nightly-reporter/.venv/bin/python
PYTHONPATH="$RUN/code" "$PYTHON" \
  "$RUN/code/scripts/run_yolo26n_v22_candidate_mining.py" inventory \
  --output "$RUN" \
  --reporter-repo /Users/baek-end/petcam-nightly-reporter \
  --cutoff 2026-07-15T00:00:00Z \
  --existing-selection /Users/baek-end/private-rba/yolo26n-v21-targeted/attempt-20260810-owner-v2/candidate-manifest.private.json \
  --existing-review-csv /Users/baek-end/private-rba/yolo26n-owner-dataset-v21/attempt-20260810-owner-final-v1/combined-review.private.csv \
  --probe-hard-positive-sources 220 \
  --probe-hard-negative-sources 100 \
  --probe-max-sources-per-night 8 \
  --seed owner-v2.2
```

Expected: R2 GET 전에 source ID 없는 inventory pool/selection 집계가 stdout과
`inventory-selection.private.json`에 기록된다. HP 220/HN 100 exact가 아니면 download 없이
`V22_INVENTORY_SELECTION_SHORTAGE`로 종료하며 DB/R2 write는 0이다.

- [ ] **Step 3: v2.1 model로 24-frame probe와 review queue 생성**

```bash
RUN=/Users/baek-end/private-rba/yolo26n-v22-candidates/attempt-20260810-owner-v2
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
backfill한다. exact 320장 또는 bucket별 planned/accepted/deduplicated/unreadable/shortfall이
fail-closed로 보고되며 shortage를 다른 bucket으로 채우지 않는다.

- [ ] **Step 4: 독립 queue preflight**

Run:

```bash
RUN=/Users/baek-end/private-rba/yolo26n-v22-candidates/attempt-20260810-owner-v2
python3 -c 'import json,pathlib; p=pathlib.Path("/Users/baek-end/private-rba/yolo26n-v22-candidates/attempt-20260810-owner-v2/candidate-manifest.private.json"); d=json.loads(p.read_text()); assert d["prediction_boxes_exposed_to_reviewer"] is False; assert d["db_write_count"] == 0; assert d["r2_write_count"] == 0; assert d["inventory_selection_counts"] == {"hard_positive": 220, "hard_negative": 100}; print(d["status"], d["review_frame_count"], d["bucket_counts"], d["materialization_counts"])'
```

Expected: `V22_CANDIDATE_QUEUE_READY`, review count 320, hard-positive 220, hard-negative 100,
source/night cap 위반 0. 조건을 못 채우면 `V22_CANDIDATE_QUEUE_SHORTAGE`로 멈춘다.

---
