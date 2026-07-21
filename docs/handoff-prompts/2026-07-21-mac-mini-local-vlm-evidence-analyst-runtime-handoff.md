---
handoff_version: 1
task_id: local-vlm-evidence-analyst-runtime
execution_repo: /Users/baek/petcam-rba-worker
plan_path: /Users/baek/petcam-rba-worker/docs/superpowers/plans/2026-07-21-mac-mini-local-vlm-evidence-analyst.md
design_path: /Users/baek/petcam-rba-worker/docs/superpowers/specs/2026-07-21-mac-mini-local-vlm-evidence-analyst-design.md
commit_sha: 72898c64519b806162e25cd1d77a27f53dcb5e7f
implementation_host: BaekBook-Pro-14-M5.local
runtime_kind: oneshot
runtime_host: baeg-endeuui-Macmini.local
runtime_label: none
---

# Runtime handoff — Mac mini Local VLM Evidence Analyst 벤치마크

> ⚠️ **아직 실행하지 마라.** 최종 판정 = `IMPLEMENTATION_BLOCKED_DATA`. 아래 데이터 게이트가
> 해소되기 전에는 model 설치·다운로드·inference·240-key 벤치마크를 시작하지 않는다. owner + Codex
> 검토를 기다린다. 이 manifest 는 구현이 완료되었고 pin·계약이 고정되었음을 증명하는 문서다.

## 검증된 전달 계약 (front matter)

- execution_repo = `petcam-rba-worker` (구현 host 경로). Mac mini runtime 경로는
  `/Users/baek-end/petcam-rba-worker` 이므로 runtime preflight 는 그 경로로 **재검증**한다.
- `runtime_kind=oneshot` — 상주 server/LaunchAgent 가 아니라 1회성 프로세스 (design §8).
- `runtime_host=baeg-endeuui-Macmini.local`, `runtime_label=none`.

## 고정된 3-레포 provenance

| repo | 경로(구현 host) | HEAD(40) | 비고 |
|---|---|---|---|
| petcam-lab | /Users/baek/petcam-lab | `feat/local-vlm-evidence-analyst` tip (본 manifest 커밋으로 +1) | 시험지·validator·scorer·recompute·probe SOT |
| petcam-rba-worker | /Users/baek/petcam-rba-worker | `72898c64519b806162e25cd1d77a27f53dcb5e7f` | materializer·adapter·parser·runner (execution_repo) |
| gecko-vision-gate | /Users/baek/myPythonProjects/gecko-vision-gate | `9e39596bdb907a86496948f4bf3a13fe760d8222` | pinned read-only 의존성 (미수정) |

- Gate checkpoint (frozen): `runs/gecko_v2/checkpoint_best_ema.pth`
  SHA-256 `cd1162b4c95041bc9b1ec064bb82ff67cb7d7416b2c778230ea0a59e2f2bef17`
- MLX 모델: `mlx-community/SmolVLM2-2.2B-Instruct-mlx` revision
  `844516024a1c4400d34489b89ee067d794e432ed` (Apache-2.0)
- MLX-VLM: `mlx-vlm==0.6.5` wheel SHA-256
  `1cc3a8a12cd674bfe3bc7d64c8e511948baf6103240c5ba87585082a2a7da8aa`

## ❌ 실행 차단 사유 (데이터 게이트)

`experiments/local-vlm-evidence-analyst/DATA-AVAILABILITY.md` (판정 `BLOCKED_DATA_INSUFFICIENT`):

1. 6 strata 중 1개(big_move)만 30 episode 충족. `rest_micro`·`wheel_object` 행동 GT 0,
   `absent` 2, `hardcase` 3, `lick_water_food` 28.
2. evidence 5축 사람 GT 0/180 (behavior_logs 는 `action`만 보유).
3. holdout blind GT 60 미완료 (owner 사람 작업).

→ owner 가 strata 재조정(design SOT 갱신) + 180 evidence GT 작성 + validator 통과 후에만
runtime 이 가능하다. 그 시점에 이 manifest 의 execution_repo/commit_sha 를 최신 tip 으로 갱신하고
Mac mini 에서 `HANDOFF_OK` 재검증한다.

## Mac mini runtime preflight (데이터 해소 이후에만)

1. hostname == `baeg-endeuui-Macmini.local` (fail-closed, 이미 runbook 이 강제).
2. 3-레포 HEAD 가 manifest 와 일치, working tree clean.
3. `uv run python scripts/verify_agent_handoff.py --manifest <this>` → `HANDOFF_OK`
   (Mac mini 경로 `/Users/baek-end/...` 로 execution_repo·plan·design 재작성 후).
4. disk ≥20GiB, memory pressure 정상, swap baseline, LaunchAgent 스케줄 snapshot, lock 획득 가능.
5. owner 승인 → `uv sync --group local-evidence-benchmark`(mlx-vlm==0.6.5, wheel SHA 검증) →
   SmolVLM2 snapshot 다운로드(revision·bytes 검증) → offline 모드.
6. Phase 1 synthetic smoke 1회 (model load·6이미지·strict JSON·temp0·DB/R2 write0) 통과.
7. `scripts/run_local_evidence_benchmark.py` segment 실행.

## 이번 구현에서 하지 않은 것 (경계 준수 증거)

- mlx-vlm Mac mini 설치·model snapshot 다운로드·local inference: **0**.
- pyproject/uv.lock 수정: **없음** (`uv run` 오프라인 재해석 실패 실증 → pin 을 상수로 고정,
  설치는 Task 9 owner gate).
- production DB/R2 write·Slack·LaunchAgent/plist 변경·Qwen 참조: **0** (정적 감사 통과).
- selector·Claude VLM·행동 GT·highlight·자동 제외 연결: **0**.
