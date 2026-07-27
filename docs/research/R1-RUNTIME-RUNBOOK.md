# R1 Mac mini 연구 런타임 운영 Runbook

## 현재 범위

R1은 승인된 `synthetic_noop_v1` job만 실행하는 기반 검증 단계야. dataset, media, detector,
local LLM, Claude/VLM 호출은 모두 금지돼. 구현 manifest의 `runtime_kind`는 `none`이므로 이
문서만으로 Mac mini LaunchAgent를 설치하면 안 돼.

## 구현 host 검증

```bash
uv run pytest -q tests/research_runtime
uv run python scripts/run_research_runtime_adversarial.py
```

두 명령이 통과해도 의미는 `IMPLEMENTED_UNVERIFIED`까지야. 실제 runtime 검증은 별도 P3
RUN-MANIFEST와 runtime attestation이 필요해.

## P3에서만 허용할 설치 순서

1. Mac mini 전용 checkout을 `/Users/baek-end/petcam-lab-research-runtime`에 준비해.
2. P3 manifest의 exact HEAD·hostname·service label을 검증해.
3. `RESEARCH_EXPECTED_HOST`와 `RESEARCH_EXPECTED_HEAD`를 설정하고 installer를 실행해.
4. manual no-op → 자연 60초 cycle → SIGKILL recovery → reboot recovery 순서로 확인해.
5. 24시간 동안 production lock 양보, 중복 실행 0, residue 0을 확인해.

## 조회와 취소

```bash
scripts/researchctl status --json
scripts/researchctl show <job-id> --json
scripts/researchctl tail <job-id> --lines 100
scripts/researchctl cancel <job-id>
```

조회는 read-only고, cancel은 상태를 덮지 않고 의도만 기록해. 새 작업 제출은 strict job spec만
허용해.

## Rollback

P3 설치 뒤 문제가 생기면 다음 순서로 멈춰.

```bash
launchctl bootout gui/$(id -u)/com.petcam.research-runtime
rm "$HOME/Library/LaunchAgents/com.petcam.research-runtime.plist"
```

ledger와 event JSONL은 원인 분석을 위해 삭제하지 않아.
