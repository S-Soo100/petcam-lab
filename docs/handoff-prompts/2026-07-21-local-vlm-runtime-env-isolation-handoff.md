---
handoff_version: 1
task_id: local-vlm-runtime-env-isolation
execution_repo: /Users/baek/petcam-rba-worker.hardening-wt
plan_path: /Users/baek/petcam-rba-worker.hardening-wt/docs/superpowers/plans/2026-07-21-local-vlm-runtime-env-isolation.md
design_path: /Users/baek/petcam-rba-worker.hardening-wt/docs/superpowers/specs/2026-07-21-local-vlm-runtime-env-isolation-design.md
commit_sha: ea1a0f18d8e0b25fcbd49960b1c8dcaf1c64b64c
implementation_host: BaekBook-Pro-14-M5.local
runtime_kind: none
---

# Claude 실행 지시 — Local VLM 전용 uv 런타임 분리

## 시작 계약

1. 이 문서를 받은 세션은 먼저 다음 validator를 실행한다.

```bash
cd /Users/baek/petcam-lab.hardening-wt
uv run python scripts/verify_agent_handoff.py \
  --manifest /Users/baek/petcam-lab.hardening-wt/docs/handoff-prompts/2026-07-21-local-vlm-runtime-env-isolation-handoff.md
```

2. literal `HANDOFF_OK task=local-vlm-runtime-env-isolation ...`가 아니면 구현하지 말고 중단·보고한다.
3. `execution_repo`로 이동해 branch가 `feat/local-vlm-evidence-hardening`, HEAD가 front matter의
   40자리 `commit_sha`, working tree가 clean인지 다시 확인한다.
4. repo `AGENTS.md` → design 전체 → plan 전체 순으로 읽는다.
5. `superpowers:executing-plans`와 `superpowers:test-driven-development`를 사용해 plan Task 1~5를
   체크박스 순서 그대로 실행한다.

## 이번 작업의 정확한 목적

폐기된 DeepLabCut을 부활시키거나 보호하는 작업이 아니다. root 프로젝트에 남아 있는 legacy
`deeplabcut`·`numpy<2` 의존성을 이번 작업에서 제거하지 않고, Local VLM만 별도 uv project·lock·venv로
격리해 `HARDENING_BLOCKED_RUNTIME_PACKAGE`를 해소한다.

## 허용 범위

- plan Task 1~5의 코드·테스트·문서 구현
- `runtime/local-vlm` 전용 `pyproject.toml`·`uv.lock` 생성
- 전용 dependency wheel 설치와 `mlx-vlm==0.6.5` API inspection
- root/isolated 양쪽 테스트 실행
- `feat/local-vlm-evidence-hardening` task별 commit과 origin push
- 최종 보고서 작성:
  `/Users/baek/petcam-rba-worker.hardening-wt/docs/handoff-prompts/2026-07-21-local-vlm-runtime-env-isolation-report.md`

## 금지 범위

- root `pyproject.toml`·root `uv.lock` 수정
- DeepLabCut dependency 제거 또는 관련 script 정리
- model snapshot 다운로드·`from_pretrained`·실제 inference
- Mac mini 접속·runtime 실행·LaunchAgent 변경
- production DB/R2 write·Slack 발송
- Work Package B 후보 선정·사람 GT 작성
- selector·Claude VLM·행동 GT·하이라이트·자동 제외 연결
- main merge, force push, 기존 commit rewrite

## 필수 판정 계약

다음을 모두 만족할 때만 최종 판정을
`HARDENED_IMPLEMENTATION_READY_FOR_DATA_REVIEW`로 쓴다.

- 전용 frozen lock 재현 성공
- exact package/interpreter/API contract 전부 통과
- 실제 `mlx-vlm==0.6.5` contract test GREEN
- root 전체 테스트 GREEN
- root `pyproject.toml`·`uv.lock` SHA pre/post 동일
- 모델 다운로드·inference·운영 mutation 0
- feature branch local==origin, working tree clean

lock/API가 실패하면 `HARDENING_BLOCKED_RUNTIME_PACKAGE`, root 회귀가 발생하면
`HARDENING_REJECTED_REGRESSION`으로 보고한다. 실패를 우회하거나 root 환경에 MLX를 설치하지 않는다.

## 최종 응답 형식

다음만 간결하게 보고하고 멈춘다.

1. 최종 판정
2. 보고서 절대경로
3. task별 commit SHA와 최종 HEAD
4. root/isolated 테스트 결과
5. root lock SHA 불변 증거
6. model download·inference·Mac mini·DB/R2·Slack 0 증거
7. 아직 미검증인 항목과 다음 Work Package B 가능 여부

