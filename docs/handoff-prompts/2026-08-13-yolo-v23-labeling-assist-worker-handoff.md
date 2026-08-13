---
handoff_version: 1
task_id: yolo-v23-labeling-assist-worker
execution_repo: /Users/baek/.codex/worktrees/b0e5/petcam-lab
plan_path: /Users/baek/.codex/worktrees/b0e5/petcam-lab/docs/superpowers/plans/2026-08-13-yolo-v23-labeling-assist-worker.md
design_path: /Users/baek/.codex/worktrees/b0e5/petcam-lab/docs/superpowers/specs/2026-08-13-yolo-v23-labeling-assist-worker-design.md
commit_sha: e666d7e7172e9e3cbd7ee94c903f306eedc28773
implementation_host: BaekBook-Pro-14-M5.local
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.petcam.yolo-preview-worker-v23
---

# YOLO Dataset v2.3 라벨링 보조 Worker handoff

## 시작 계약

1. 구현은 `execution_repo`의 exact `commit_sha`에서 시작한다.
2. design과 plan은 tracked·clean이어야 한다.
3. validator의 literal `HANDOFF_OK` 전에는 구현 파일을 수정하지 않는다.
4. 구현은 MacBook worktree에서 하고 runtime은 Mac mini의 별도 exact-SHA worktree에 둔다.

```bash
cd /Users/baek/.codex/worktrees/b0e5/petcam-lab
uv run python scripts/verify_agent_handoff.py \
  --manifest /Users/baek/.codex/worktrees/b0e5/petcam-lab/docs/handoff-prompts/2026-08-13-yolo-v23-labeling-assist-worker-handoff.md
```

## 허용 범위

- v2.3 warm-start checkpoint의 별도 immutable release copy
- 기존 v2.1과 병렬인 localhost Mac mini LaunchAgent
- 별도 Named Tunnel hostname과 branch-scoped protected Vercel Preview
- 사진·짧은 영상의 후보 bbox canary와 v2.1 rollback round trip
- 배포 완료 후 안전 경계를 포함한 Slack 공유

## 금지 범위

- 학습 원본과 기존 v2.1 artifact/service/worktree/env의 overwrite·삭제·중단
- Vercel production provider/alias promote와 public inference 활성화
- DB/R2 schema/data mutation
- GT 자동확정, 빈 이미지·게코 부재 판정, GME routing, R2 A/B 분류, 삭제, VLM skip
- secret, local path, private manifest, raw GT의 Git/HTTP/Slack 노출

## Fail-closed

release SHA/size/mode, MPS, v2.1 병렬 보존, v2.3 health/threshold/scope, temp cleanup, tunnel isolation,
production 503, rollback round trip 중 하나라도 증명되지 않으면 Preview를 v2.1로 되돌리고
`PREVIEW_READY_LABELING_ASSIST_ONLY`를 주장하지 않는다.

## 실행 결과 (2026-08-13)

- `HANDOFF_OK task=yolo-v23-labeling-assist-worker repo=petcam-lab commit=e666d7e7 runtime=launchagent@baeg-endeuui-Macmini.local`
- reviewed runtime SHA: `dc11b2d68723f9473100599da481c390561485ef`
- runtime: `com.petcam.yolo-preview-worker-v23`, localhost `8094`, clean exact-SHA worktree, MPS health exact
- release: full SHA `dbed3a2d8018a2eb6e4130de57d301414fcd6c9ba80aef8aafdaba55b19a6a34`, size `5,400,581`, files `0444`
- tunnel: existing root-owned v2.1/CVAT process를 재시작하지 않고 v2.3 전용 Named Tunnel/User LaunchAgent로
  분리했다. 기존 v2.1과 CVAT는 계속 `200`이다.
- final protected Preview: `dpl_5i4EL3rcpFTMjXnZmKffvuG3ik45`,
  `https://petcam-eftt5b9uq-ssoo100s-projects.vercel.app`
- canary: image/video actual inference, browser bbox/version/threshold/warnings, zero-detection absence warning,
  production `503` and request count unchanged, v2.1 rollback→v2.3 restore all passed
- DB/R2 schema/data mutation `0`; production adoption remains `NO-GO`, future holdout required
