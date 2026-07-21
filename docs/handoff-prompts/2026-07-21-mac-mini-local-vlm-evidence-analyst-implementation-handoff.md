---
handoff_version: 1
task_id: local-vlm-evidence-analyst-implementation
execution_repo: /Users/baek/petcam-rba-worker
plan_path: /Users/baek/petcam-rba-worker/docs/superpowers/plans/2026-07-21-mac-mini-local-vlm-evidence-analyst.md
design_path: /Users/baek/petcam-rba-worker/docs/superpowers/specs/2026-07-21-mac-mini-local-vlm-evidence-analyst-design.md
commit_sha: 5392739804257d2b87787bb930c2c89d8b0e8eb6
implementation_host: BaekBook-Pro-14-M5.local
runtime_kind: none
---

# Claude 실행 지시 — Mac mini Local VLM Evidence Analyst 구현

이 handoff는 승인된 설계에 따른 **구현·dry test 지시**다. 모델 설치·다운로드·Mac mini inference 지시가 아니다.

## 시작 계약

1. `/Users/baek/petcam-rba-worker`로 이동한다.
2. branch가 `feat/local-vlm-evidence-analyst`, HEAD가 front matter의 40자리 `commit_sha`와 정확히 일치하는지 확인한다.
3. 다음 validator가 literal `HANDOFF_OK`를 출력하지 않으면 추측 구현하지 말고 중단·보고한다.

```bash
cd /Users/baek/petcam-lab
uv run python scripts/verify_agent_handoff.py \
  --manifest /Users/baek/petcam-lab/docs/handoff-prompts/2026-07-21-mac-mini-local-vlm-evidence-analyst-implementation-handoff.md
```

4. design 전체 → plan 전체 → petcam-rba-worker `AGENTS.md` 순서로 읽는다.
5. `superpowers:executing-plans`와 `superpowers:test-driven-development`를 사용해 Task 1부터 순서대로 수행한다.

## 이번 구현 허용 범위

- Plan Task 1~6 구현·테스트
- Task 7의 SELECT-only data availability 진단과 manifest/GT validator 실행 준비
- Task 8의 cross-repo 검증·정적 보안 감사·보고서 작성
- petcam-lab과 petcam-rba-worker의 feature branch commit·push
- gecko-vision-gate는 pinned read-only 의존성으로만 사용

## 이번 구현 금지 범위

- `mlx-vlm`의 Mac mini 설치·model snapshot 다운로드
- 실제 local VLM inference·240-key benchmark 실행
- Mac mini runtime·LaunchAgent·plist 변경
- production DB/R2 write, Slack 발송
- selector·Claude VLM·행동 GT·하이라이트·자동 제외 연결
- Qwen 모델 다운로드·실행
- holdout 결과를 보기 전 evidence GT를 모델 출력으로 채우는 행위

## 중요한 구현 계약

- 1차 모델은 Apache-2.0 `mlx-community/SmolVLM2-2.2B-Instruct-mlx` revision `844516024a1c4400d34489b89ee067d794e432ed`다.
- durable `clip_prelabels.gecko_bbox`를 frame union으로 재해석하지 않는다.
- 선택 6프레임에 Gate를 read-only로 적용한다. bbox가 있으면 union ROI, 없으면 같은 네 시점의 전체 프레임과 `roi_mode=full_frame_no_detection`을 사용한다.
- Gate를 unload한 뒤 MLX model을 load한다. 둘을 동시에 상주시켜 16GB memory 계약을 깨지 않는다.
- strict JSON을 관대하게 보정하지 않는다. measured key당 generation·content/schema 시도는 1회다.
- unit test는 fake MLX module로 수행하고 model network access를 발생시키지 않는다.
- raw media·frame·model text는 Git에 넣지 않는다.

## 중간·최종 보고

각 Task마다 RED→GREEN 명령과 결과, 변경 파일, commit SHA를 기록한다. Task 8 종료 시 다음을 보고한다.

- 두 레포 branch·HEAD·push 동기화
- 전체 test와 `git diff --check`
- 금지 write·Slack·LaunchAgent·Qwen runtime reference 정적 감사
- model 설치·download·inference 0 증거
- data availability 판정과 아직 필요한 사람 GT 수
- 다음 runtime handoff 가능 여부

최종 판정은 다음 중 하나만 사용한다.

- `IMPLEMENTATION_READY_FOR_RUNTIME_REVIEW`
- `IMPLEMENTATION_BLOCKED_DATA`
- `IMPLEMENTATION_REJECTED`

runtime 설치·실행은 어떤 판정에서도 자동으로 시작하지 말고 사용자와 Codex 검토를 기다린다.
