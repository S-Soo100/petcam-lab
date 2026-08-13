# YOLO26n v2.4b Future Holdout — 단계형 Mac mini handoff 기록

**상태:** `BLOCKED_RUNTIME_HANDOFF_INPUTS`

이 파일은 tracked **handoff tracking record**다. validator manifest가 아니며, 첫 줄이 YAML front matter가
아니므로 `verify_agent_handoff.py`에 넘기면 안 된다. 현재 `HANDOFF_OK`는 없고, 이 문서나 아래 template의
placeholder는 유효 pin 또는 실행 승인이 아니다.

## 1. 고정된 implementation commit I

| 항목 | 값 |
|---|---|
| implementation commit I | `e822f289b38b61d2d29bbd26370be20874e1eb82` |
| implementation host | `BaekBook-Pro-14-M5.local` |
| execution repo | `/Users/baek-end/petcam-lab` |
| plan | `/Users/baek-end/petcam-lab/docs/superpowers/plans/2026-08-13-yolo26n-v24b-postprocess-future-holdout.md` |
| design | `/Users/baek-end/petcam-lab/docs/superpowers/specs/2026-08-13-yolo26n-v24b-postprocess-future-holdout-design.md` |
| runtime kind / host / label | `oneshot` / `baeg-endeuui-Macmini.local` / `yolo26n-v24b-postprocess` |
| checkpoint SHA-256 | `3c9f752b9369b30be4083f837676271640cfd1f4cbfa6027382a380efc4212c4` |
| dataset manifest SHA-256 | `218f32d745e407470c661d97cfe0035e27614cc8f7921ae61835050a0dcd827f` |
| freeze SHA-256 | `PENDING_FREEZE` — artifact가 아직 없음 |

read-only preflight에서 checkpoint artifact 1개와 mode `0600` dataset manifest를 확인했고, v1/v2
attempt dataset manifest bytes는 같은 SHA다. 이 input 사실은 implementation code를 Mac mini에서 실행할
수 있다는 뜻이 아니다.

## 2. 현재 hard stop

`/Users/baek-end/petcam-lab`은 존재하지만 unrelated dirty checkout이고 I는 remote에 없다. 그래서
production checkout을 checkout/reset/sync/pull하지 않고, shared uv environment와 git configuration도
바꾸지 않는다. clean isolated execution repo가 exact I를 가리키는 read-only evidence가 생길 때까지
bootstrap 상태는 `PENDING_CLEAN_IMPLEMENTATION_CHECKOUT`다. 이 상태에서는 validator 실행과 Task 8
실행을 하지 않는다.

freeze의 raw bytes SHA-256은 Task 8 Step 1이 shortage 없이 끝난 뒤에만 알 수 있다. 따라서 freeze
placeholder를 final pin으로 바꾸거나, 현재 문서를 `HANDOFF_OK`라고 부르는 것은 금지다.

## 3. commit과 manifest의 의도된 순서

1. I는 implementation, plan, design을 포함한 commit이다.
2. 이 문서는 I SHA를 기록하는 tracking commit H다. H는 I 이후이므로 H 자체의 `commit_sha`를 validator에
   넣을 수 없다. validator는 requested commit이 execution repo HEAD와 같고 plan/design이 그 commit에
   있어야 한다.
3. 별도 승인으로 clean isolated execution repo가 정확히 I를 checkout하고 그 HEAD/plan/design clean 상태를
   보인 후에만, repo **밖** approved private attempt root에 untracked bootstrap manifest를 작성한다.
4. bootstrap validator가 실제 `HANDOFF_OK`를 출력한 경우에만 Task 8 Step 1을 딱 한 번 실행할 수 있다.
5. Step 1이 freeze를 publish했다면 freeze raw bytes SHA-256을 독립 계산한다. same clean I checkout에서
   exact dataset/freeze SHA를 포함한 untracked final manifest/addendum을 새로 만들고 validator를 다시 통과한
   경우에만 Task 8 Step 2 이후를 허용한다.

실패/shortage/freeze 부재 중 어느 경우도 Task 8 Step 2 이후의 실행 권한으로 확장하지 않는다.

## 4. bootstrap manifest template — 아직 생성하거나 검증하지 않음

아래 block은 `PENDING_CLEAN_IMPLEMENTATION_CHECKOUT`가 해소된 뒤 approved private attempt root의 repo 밖
파일에만 복사한다. 이 template은 validation grid/freeze 생성만 허용한다. 작성 시 I 외 다른 SHA를 쓰지
않고, `git -C /Users/baek-end/petcam-lab rev-parse HEAD`가 I와 exact 일치하지 않으면 즉시 중단한다.

```yaml
---
handoff_version: 1
task_id: yolo26n-v24b-postprocess-bootstrap
execution_repo: /Users/baek-end/petcam-lab
plan_path: /Users/baek-end/petcam-lab/docs/superpowers/plans/2026-08-13-yolo26n-v24b-postprocess-future-holdout.md
design_path: /Users/baek-end/petcam-lab/docs/superpowers/specs/2026-08-13-yolo26n-v24b-postprocess-future-holdout-design.md
commit_sha: e822f289b38b61d2d29bbd26370be20874e1eb82
implementation_host: BaekBook-Pro-14-M5.local
runtime_kind: oneshot
runtime_host: baeg-endeuui-Macmini.local
runtime_label: yolo26n-v24b-postprocess
---

범위: Task 8 Step 1만. model load 전에 dataset manifest SHA-256은
218f32d745e407470c661d97cfe0035e27614cc8f7921ae61835050a0dcd827f와 같아야 한다.
checkpoint SHA-256은 model load 전에
3c9f752b9369b30be4083f837676271640cfd1f4cbfa6027382a380efc4212c4와 같아야 한다.
freeze pin: PENDING_FREEZE; Task 8 Step 2+ 권한 없음.
금지: old test151, external60, DB/R2 write, service, git, production.
```

Only after the preconditions above are true, run the real private manifest:

```bash
uv run python /Users/baek-end/petcam-lab/scripts/verify_agent_handoff.py \
  --manifest "$ATTEMPT_ROOT/handoff-bootstrap.md"
```

`HANDOFF_FAIL` 또는 clean-I evidence 부재는 hard stop이다. 기존 Mac mini checkout, git state, shared
environment를 바꿔서 고치지 않는다.

## 5. Step 1 private runtime contract

`ATTEMPT_ROOT` must be a separately approved private absolute attempt root; otherwise use
`PENDING_APPROVED_ATTEMPT_ROOT` and do not run. Ultralytics is intentionally neither added to the repository nor
installed in the Mac mini shared environment. Set its config directory below the attempt root and use this exact
isolated dependency command:

```bash
ATTEMPT_ROOT=/absolute/approved-private/v24b-postprocess-attempt-v1
env YOLO_CONFIG_DIR="$ATTEMPT_ROOT/yolo-config" \
  uv run --isolated --with 'ultralytics==8.4.118' python \
  /Users/baek-end/petcam-lab/scripts/run_yolo26n_v24b_postprocess.py predict-grid \
  --dataset-manifest /absolute/private/dataset-manifest.private.json \
  --checkpoint /absolute/private/best.pt \
  --expected-checkpoint-sha256 3c9f752b9369b30be4083f837676271640cfd1f4cbfa6027382a380efc4212c4 \
  --output "$ATTEMPT_ROOT"
env YOLO_CONFIG_DIR="$ATTEMPT_ROOT/yolo-config" \
  uv run --isolated --with 'ultralytics==8.4.118' python \
  /Users/baek-end/petcam-lab/scripts/run_yolo26n_v24b_postprocess.py freeze \
  --output "$ATTEMPT_ROOT"
```

runner의 SHA와 no-overwrite 검사가 정본이다. 이 계약은 approved private local artifact 생성만 허용하며
DB/R2/service/git/production mutation은 절대 허용하지 않는다.

## 6. final handoff/addendum — freeze가 생긴 뒤에만

`PENDING_FREEZE`인 동안 이 manifest를 만들지 않는다. operator는 새 freeze file의 lowercase 64-hex SHA-256을
독립 계산한 뒤 `ACTUAL_FREEZE_SHA256_FROM_PRIVATE_BYTES`를 바꿔야 한다. 결과 private manifest는 bootstrap과
같은 front matter를 유지하되 `task_id`를 `yolo26n-v24b-future-holdout-final`로 바꾸고 아래 body를 붙인다.

```text
범위: Task 8 Step 2부터 Step 7만; Step 1은 이미 소비됐다.
dataset manifest SHA-256: 218f32d745e407470c661d97cfe0035e27614cc8f7921ae61835050a0dcd827f
postprocess freeze SHA-256: ACTUAL_FREEZE_SHA256_FROM_PRIVATE_BYTES
freeze 조건: inventory/image read 전에 exact raw bytes SHA를 독립 검증한다.
금지: old test151, external60, DB/R2 write, service, git, production.
```

새 private final manifest에 같은 validator를 실행하고 actual output과 freeze SHA를 보존한다. 그 전까지
final handoff는 `PENDING_FREEZE`이며 `HANDOFF_OK`가 아니다.
