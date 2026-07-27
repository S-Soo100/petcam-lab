# R1 Mac mini Research Runtime Foundation — Claude 독립 설계 검토

## 0. 검토 목적

RBA 연구 시스템 v1의 첫 실행 패키지인 R1을 구현하기 전에, Mac mini 장기 실행 기반의 범위와
안전 계약을 독립적으로 검토해.

이 검토는 설계 검토뿐이야. 코드 구현, Mac mini 접속, LaunchAgent 변경, production DB/R2
접근, 모델 다운로드·추론은 하지 마.

## 1. 필독 정본

아래 파일을 모두 읽고 현재 Git 내용만 근거로 판단해.

1. `AGENTS.md`
2. `docs/research/AI-OPERATING-CONTRACT.md`
3. `docs/research/RUN-MANIFEST.schema.json`
4. `docs/superpowers/specs/2026-07-27-rba-research-system-v1-design.md`
5. `docs/handoff-prompts/2026-07-27-ai-operating-contract-report.md`
6. `docs/research/catalog.json`
7. `specs/next-session.md` 최상단의 2026-07-27~28 연구 블록

## 2. 검토 대상 R1 초안

### 목표

Mac mini가 MacBook 연결이나 대화 세션 지속 여부와 무관하게 승인된 연구 job을 실행하고,
재부팅 후 복구하며, 원격에서 상태를 확인할 수 있는 최소 연구 runtime 기반을 만든다.

R1에서는 dataset inventory, prompt 수정, VLM/local model benchmark, production worker 교체를
시작하지 않는다.

### 권장 구조

1. Mac mini 전용 local SQLite ledger
   - 승인된 research job의 `queued/running/succeeded/failed/cancelled` 상태를 보존한다.
   - claim, lease, heartbeat, attempt, budget, result path, error code를 기록한다.
   - production Supabase와 분리한다.
2. `research-runner`
   - RUN-MANIFEST 검증을 통과한 job만 실행한다.
   - expected-host, clean Git, repo HEAD, lock, deadline, budget을 실행 전에 fail-closed 검사한다.
   - production worker lock 또는 정규 deadline과 충돌하면 job을 실패시키지 않고 양보한다.
3. LaunchAgent
   - Mac mini에서만 설치한다.
   - 재부팅 후 승인된 queued job과 stale running job을 계약에 따라 복구한다.
   - Desktop 대화 세션을 daemon으로 사용하지 않는다.
4. `researchctl`
   - `status --json`, `show <job-id> --json`, `tail <job-id>`의 최소 read interface를 제공한다.
   - HEAD, phase, progress, 최근 오류, 결과 경로, service 상태를 보여준다.
   - secret, raw media, signed URL, credential 내용을 출력하지 않는다.
5. 격리된 job worktree와 결과 디렉터리
   - job마다 고정된 commit/worktree를 사용한다.
   - 결과는 job별 경로에 저장하고 Git에는 summary/report만 포함한다.
   - temp와 부분 결과는 crash cleanup 계약을 따른다.

### 실행·기록 흐름

1. R1 설계와 구현계획을 tracked commit `A`에 고정한다.
2. R1 구현용 start RUN-MANIFEST만 담은 전용 commit `M`을 만든다.
3. 이번 패키지는 `M`에서 정지한다.
4. 별도 구현 승인 후 runner·ledger·CLI를 구현해 `B`를 만든다.
5. 실제 model/runtime provenance를 기록한 final manifest 전용 commit `C`로 닫는다.
6. Mac mini service 설치와 재부팅 canary는 별도 P3 manifest·trusted approval을 요구한다.

### 이번 패키지의 산출물

- R1 상세 설계 문서
- R1 구현계획
- R1 구현용 start RUN-MANIFEST
- Claude 독립 설계 검토 보고서

실제 runtime 코드, Mac mini 설치, LaunchAgent bootstrap, 24시간 시험은 이번 패키지에 포함하지
않는다.

### 성공 기준

- 같은 job의 동시 실행 0
- Mac mini가 아닌 host에서 실행 0
- 재부팅 후 승인 job 복구 가능
- production lock/deadline 충돌 시 자동 양보
- 원격 JSON 상태 조회 가능
- secret·raw video·signed URL 출력 0
- production DB/R2 write 0
- synthetic no-op job으로 lease 만료, crash recovery, 재부팅 복구를 검증할 수 있음

## 3. 대안

### A. Local SQLite + LaunchAgent + CLI

현재 권장안. production과 분리하면서 claim·lease·복구를 구조화할 수 있다.

### B. Git + JSONL만 사용

구현은 단순하지만 동시성, lease, stale-running 복구와 query가 약하다.

### C. Supabase ledger

원격 관측은 쉽지만 migration, RLS, service credential, production 의존성이 R1에 들어온다.

## 4. 필수 검토 질문

1. R1 범위가 runtime foundation으로 충분히 좁고 dataset/model 연구와 분리됐는가?
2. Local SQLite가 Git/JSONL-only 또는 Supabase보다 적절한가?
3. A→M→B→C lifecycle을 이번 plan-only 패키지와 이후 구현 패키지에 적용하는 방식이
   AI 운영 계약과 일치하는가?
4. LaunchAgent 재부팅 복구에서 split-brain, stale lease, 중복 실행을 막는 계약이 충분한가?
5. production worker lock/deadline에 양보하는 방식에서 빠진 운영 위험이 있는가?
6. `researchctl`만으로 MacBook·스마트폰 원격 관측 목표를 달성할 수 있는가?
7. secret, raw media, signed URL, production credential이 ledger/log/status에 유출될 경로가
   남아 있는가?
8. 24시간 지속·재부팅 복구 시험 전에 추가해야 할 synthetic/adversarial test가 있는가?
9. R1 구현 전에 반드시 결정해야 하지만 초안에 빠진 필드·interface·stop condition이 있는가?
10. 기존 runtime worker나 ledger 구현 중 재사용해야 할 검증된 구성요소가 있는가?

## 5. 검토 규칙

- 기억이나 추측으로 live 상태를 단정하지 마.
- 변경 파일을 제안할 때는 현재 repo에서 경로와 기존 구현을 확인해.
- 범위 밖 기능을 R1 필수조건으로 확대하지 마.
- 구현을 시작하거나 파일을 수정하지 마.
- 비밀값, 전체 UUID, R2 key, signed URL을 보고서에 쓰지 마.
- 문제는 `Critical / Important / Minor`로 구분해.
- 각 문제에 근거 파일·line, 영향, 최소 수정안을 적어.

## 6. 결과 형식

Markdown 보고서만 출력해. 다음 순서를 지켜.

1. `# R1 Mac mini Runtime Foundation — Claude Review`
2. `## 최종 판정`
3. `## 잘된 경계`
4. `## Critical`
5. `## Important`
6. `## Minor`
7. `## 권장 설계`
8. `## 구현계획 작성 전 필수 결정`
9. `## 다음 허용 행동`

최종 판정은 아래 둘 중 하나만 사용해.

- `R1_DESIGN_REVIEW_APPROVE`
- `R1_DESIGN_REVIEW_HOLD_<REASON>`

