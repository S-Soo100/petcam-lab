---
handoff_version: 1
task_id: nightly-label-determinism
execution_repo: /Users/baek/petcam-nightly-reporter
plan_path: /Users/baek/petcam-nightly-reporter/docs/superpowers/plans/2026-07-21-nightly-label-determinism-plan.md
design_path: /Users/baek/petcam-nightly-reporter/docs/superpowers/specs/2026-07-21-nightly-label-determinism-design.md
commit_sha: 46ca39e51b7b6e028d452a5959f34c85631cd67d
implementation_host: BaekBook-Pro-14-M5.local
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.petcam.nightly-reporter
---

# Claude 실행 지시 — Nightly 행동 라벨 결정론 전환 + 오탐 재측정 (petcam-lab P1)

이 handoff는 설계 토론 요청이 아니라 승인된 구현·실행 지시야. 발주 근거: petcam-lab `docs/decision-gate.md` 2026-07-21 "연구방향 상담 P1/P2/P3 판정" 레코드 — P1 **adopt**.

## 시작 계약

1. `execution_repo`로 이동해 `git rev-parse HEAD`가 front matter의 `commit_sha`와 정확히 일치하는지 확인해. ⚠️ 이 SHA는 **`feat/vlm-basking-classification` 브랜치**에 있어 (main 아님). Mac mini production은 main 계열이므로, 브랜치 정리/merge가 필요하면 그 레포의 승인 게이트대로 사용자에게 물어.
2. 아래 validator를 먼저 실행하고 `HANDOFF_OK`가 아니면 추측 구현하지 말고 중단해.

```bash
cd /Users/baek/petcam-lab && uv run python scripts/verify_agent_handoff.py \
  --manifest /Users/baek/petcam-lab/docs/handoff-prompts/2026-07-21-nightly-classify-determinism-handoff.md
```

3. design → plan 순서로 처음부터 끝까지 읽고, plan Task 1부터 순서대로 수행해.
4. Task 1은 systematic-debugging(read-only 진단), 코드 변경은 test-driven-development.

## 반드시 지킬 결정

- **진단 선행**: owner가 본 오탐 라벨(야간 IR→shedding, 쳇바퀴→drinking)이 어느 경로 산출물인지 증거로 특정하기 전에 어떤 코드도 고치지 마. 후보: `reporter/classify.py`(`claude -p`, temperature 제어 불가) / `com.petcam.vlm-candidate-worker`(provider `claude_cli_batch`) / `reporter/anthropic_analyzer.py`(Messages API, temperature=0).
- **원인은 이미 진단됨**: petcam-lab 2026-07-08 재현 — 같은 shedding 오탐 32건이 결정론 조건(v4.0·v4.1 모두)에서 64/64 moving. 프롬프트를 새로 파지 말고 temperature 결정론 배선이 P1의 전부야.
- **프롬프트 버전 함정**: `anthropic_analyzer.py`가 `prompts/system.v4.1.md`를 로드 중인데 petcam-lab 기준 v4.1은 reject, v4.0이 기준선. 기본 v4.0 핀. v4.1 유지하려면 명시 근거를 문서로.
- **재측정은 의사결정용 테스트** → TEST-SHEET(실행 전 고정) + REPORT 의무 (petcam-lab `.claude/rules/research-testing.md` 프로토콜). 잔존 "진짜 오탐 목록"이 petcam-lab P2(케이지 프로필 메타) 착수/폐기를 정하는 입력값이야.
- 그 레포 기존 global constraints 전부 승계: 월 $10 API hard cap, 모델 exact ID `claude-sonnet-5`, durable 저장 전 호출 금지, shadow 경계(`behavior_logs`/하이라이트/알림 불변), **운영 LaunchAgent 변경·유료 활성화는 사용자 승인 후에만**, `uv add`만, 비밀값 `.env`만.
- 완료 시 petcam-lab `docs/decision-gate.md`에 결과를 append로 회신하고(기존 행 수정 금지), 운영 보고는 실제 `runtime_host`(Mac mini)의 hostname·service loaded 상태·repo HEAD 증거로 해.
