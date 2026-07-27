# Owner GT 172 감사·연구 설계 handoff

## Verdict

`OWNER_GT_AUDIT_READY_FOR_REVIEW`

Owner 직접 완료 GT는 정확히 172건이야. 진행 중 2건, hold 4건, skip 159건, 시스템 격리,
Canary 12 clips/24 submissions, live double-blind 0건을 별도 계층으로 분리했고 eligible 172와
Canary·terminal 시스템 격리 overlap은 0이야.

상세 보고서:
[`experiments/owner-gt-audit-20260727/REPORT.md`](../../experiments/owner-gt-audit-20260727/REPORT.md)

재현·무결성:

- [`audit.sql`](../../experiments/owner-gt-audit-20260727/audit.sql)
- [`fingerprints-start.csv`](../../experiments/owner-gt-audit-20260727/fingerprints-start.csv)
- [`fingerprints-end.csv`](../../experiments/owner-gt-audit-20260727/fingerprints-end.csv)
- [`cohort-fingerprints.csv`](../../experiments/owner-gt-audit-20260727/cohort-fingerprints.csv)
- [`verify_artifacts.py`](../../experiments/owner-gt-audit-20260727/verify_artifacts.py)

## 핵심 실측

- Owner completed: 172 / distinct clip 172
- Owner in-progress `gt_locked`: 2
- required GT key·enum·의미 규칙 위반: 0
- Python Evidence: 172/172, L0/L1 모두 ok
- Gate/prelabel: 172/172
- 기존 VLM: job 24/172, success 23/172
- 기존 VLM success primary exact match: 14/23, 60.9% — selector 편향 회고치
- 카메라 2대, 3일, 5분 gap episode 39
- rare care primary: drinking 3 + eating_paste 1
- Owner eligible ordered SHA-256:
  `8e2bf4e73f8f033288d7632e25e2fbfd69d3de98c62dade2996bbe33686c96ba`

33개 사람 라벨·GT·triage·blind·behavior·Python Evidence·Gate·VLM 관련 테이블의 시작/종료
count+ordered fingerprint가 전부 동일해. 시스템 격리 2개 테이블도 별도 보강 window에서
동일했어. mutation 0 증거 범위는 이 35개 테이블과 Owner cohort이며 DB 전체를 뜻하지 않아.
이번 작업은 SELECT만 실행했고 DB/R2/runtime write 명령은 실행하지 않았어.

## 활용 우선순위

1. Python Evidence coverage + motion/static 신호 descriptive benchmark
2. VLM blind evaluation 후보 — 기존 success 23은 dev/diagnostic으로 격리
3. selector 효용 — unselected rank snapshot 부재로 현재는 회고 EDA만

현재 데이터는 Python technical coverage에는 충분하지만, 2카메라·3일·39 episode와 rare care
4건이라 production 일반화·P0 recall·selector adoption에는 부족해. 다음 최소 행동은 한 질문
(`observed moving` 대 `static without moving`)만 둔 TEST-SHEET를 먼저 동결하는 거야.

## Git·실행 경계

- execution worktree:
  `/Users/baek/.codex/worktrees/7896/petcam-lab`
- branch: `codex/owner-gt-audit-20260727`
- audited base HEAD/origin-main:
  `8e0d62ba679863c6f84f2429a1be7a590dfd075a`
- 변경 범위: `experiments/owner-gt-audit-20260727/`와 이 handoff 문서만
- main merge·production 반영·migration·deploy: 미실행
- 모델 학습·prompt/threshold 튜닝·selector 변경: 미실행

commit SHA는 commit 자체에 자기 SHA를 쓸 수 없으므로 이 문서에는 audited base만 고정했어.
최종 feature branch HEAD와 clean status는 task 최종 응답의 실제 git 출력이 정본이야.
