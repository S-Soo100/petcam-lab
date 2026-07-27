# R1 Mac mini Runtime Foundation — Claude Review

## 최종 판정

**R1_DESIGN_REVIEW_HOLD_RUNTIME_CONTRACT_GAPS**

방향(Mac mini 전용 local ledger + LaunchAgent + read-only CLI)은 맞고, 대안 A를 고른 판단도
지지해. 범위도 dataset/model 연구와 잘 분리돼 있어. 다만 **R1이 스스로 내건 성공 기준
7개 중 4개(동시 실행 0 · 재부팅 복구 · production 양보 · secret 출력 0)** 를 지금 초안의
계약만으로는 달성할 수 없어. 특히 초안 §권장구조 2·5의 "job마다 RUN-MANIFEST 검증 + 고정
commit/worktree"는 현재 validator 구현과 **직접 충돌**해서, 구현계획을 그대로 쓰면 코드를 짜고
나서야 막혀. 이건 범위 확대가 아니라 초안이 이미 약속한 것들의 미결정 항목이라 HOLD로 낸다.

Critical 4건을 결정으로 닫고 초안을 개정하면 approve 가능한 설계야. 재설계급 문제는 없어.

### 검토 기준

- reviewed HEAD: `10366a5a5811616464670fa9f6dc92c9acc77988` (worktree `.worktrees/r1-mac-mini-runtime-foundation`, branch `codex/r1-mac-mini-runtime-foundation`, `git status --porcelain` 공백)
- 읽은 정본: `AGENTS.md` · `docs/research/AI-OPERATING-CONTRACT.md` · `docs/research/RUN-MANIFEST.schema.json` · `docs/research/RUN-MANIFEST.example.json` · `docs/research/README.md` · `docs/research/RETENTION.md` · `docs/research/catalog.json` · `docs/superpowers/specs/2026-07-27-rba-research-system-v1-design.md` · `docs/handoff-prompts/2026-07-27-ai-operating-contract-report.md` · `specs/next-session.md` 최상단 2026-07-27~28 블록
- 근거 확인용 추가 read-only: `scripts/verify_research_run_manifest.py` · `scripts/benchmark_python_evidence_s1.py` · `scripts/request-r1-runtime-review-from-claude.sh` · `docs/superpowers/specs/2026-07-21-mac-mini-local-vlm-evidence-analyst-design.md` · `docs/handoff-prompts/2026-07-16-activity-worker-single-host-migration-closure-report.md` · `.gitignore`
- R1 설계 문서·구현계획·start manifest는 이 HEAD에 **아직 없어**(`git ls-files | grep -i r1` = review prompt/스크립트/테스트 3개뿐). 그래서 검토 대상은 review 문서 §2 초안 산문이고, 코드 검토가 아니라 계약 검토로 진행했어.
- 실행 안 한 것: 구현·리팩터·Mac mini 접속·LaunchAgent·production DB/R2·모델 실행 전부 0. 새 파일은 이 보고서 하나.

### 검토 질문 10개 — 요약 응답

| # | 질문 | 판정 | 근거 |
|---|---|---|---|
| 1 | R1 범위가 충분히 좁은가 | 대체로 Yes (누수 2건) | Important-1, Important-2 |
| 2 | Local SQLite가 적절한가 | **Yes** | 권장설계 §2 |
| 3 | A→M→B→C 적용이 계약과 맞는가 | **부분 No** | Critical-1, Important-3 |
| 4 | 재부팅 복구 계약이 충분한가 | **No** | Critical-2 |
| 5 | 양보 방식에 빠진 운영 위험 | **있음** | Critical-3 |
| 6 | `researchctl`만으로 원격 관측 달성 | **No** (전송·알림 미정의) | Important-4 |
| 7 | secret 유출 경로가 남았는가 | **남아 있음** | Critical-4 |
| 8 | 24시간 시험 전 추가 테스트 | **필요** | 권장설계 §5 |
| 9 | 빠진 필드·interface·stop condition | **다수** | 권장설계 §3, §4 |
| 10 | 재사용할 검증된 구성요소 | **있는데 초안에 0건 언급** | Important-5 |

## 잘된 경계

- **production과 연구 저장소 분리.** ledger를 Supabase가 아닌 Mac mini local SQLite로 두는 선택은 대안 C가 R1에 migration·RLS·service credential·production 의존을 끌고 오는 걸 정확히 회피해. `AI-OPERATING-CONTRACT.md:155-163`의 "장기·원격 실행" 조항(앱은 daemon이 아니다 / ledger·파일에 진행 상태 기록 / 재부팅 뒤 resume 또는 fail-closed)과 1:1로 대응돼.
- **Desktop 세션을 daemon으로 쓰지 않는다는 명시.** `2026-07-27-rba-research-system-v1-design.md:188`의 금지 경계와 일치하고, R1이 그걸 구조로 강제하는 첫 패키지라는 위치도 맞아.
- **R1에서 dataset/prompt/model benchmark를 시작하지 않는다는 선언.** `catalog.json:38,60`의 `next_allowed`와 정확히 같은 경계고, R2~R9 순서를 흐리지 않아.
- **Mac mini service 설치·재부팅 canary를 별도 P3 manifest + trusted approval로 분리한 것.** `AI-OPERATING-CONTRACT.md:20-33`(P3는 일반 문구로 확장 금지, trusted verifier 없으면 중단)과 정합하고, 기본 CLI가 P3를 자기승인 못 한다는 사실(`scripts/verify_research_run_manifest.py:1182-1196`)을 제대로 반영했어.
- **synthetic no-op job으로 lease 만료·crash recovery·재부팅 복구를 검증한다는 성공 기준.** 실데이터·실모델 없이 runtime만 검증하겠다는 태도가 맞고, R1을 R2와 독립시키는 핵심 장치야.
- **production DB/R2 write 0 · secret 출력 0을 성공 기준에 넣은 것.** 계약 `AI-OPERATING-CONTRACT.md:146-153`, `181-191`의 중단 규칙을 R1 수준으로 내린 게 옳아.

## Critical

### Critical-1. "job마다 RUN-MANIFEST 검증 + 고정 commit/worktree"가 validator 계약과 직접 충돌해

**근거**

- 초안 §권장구조 2: "RUN-MANIFEST 검증을 통과한 job만 실행한다", §권장구조 5: "job마다 고정된 commit/worktree를 사용한다".
- `scripts/verify_research_run_manifest.py:870-879` — validator는 `git symbolic-ref --quiet --short HEAD`가 실패하면 `branch_mismatch`로 거부해. **detached HEAD worktree는 통과 불가**야. "고정 commit worktree"는 통상 detached라 정면 충돌이야.
- `scripts/verify_research_run_manifest.py:834-860` — `execution_repo`는 존재하는 **절대경로**여야 하고 `git rev-parse --show-toplevel`과 정확히 같아야 해. Mac mini 홈은 `/Users/baek-end/…`(`docs/handoff-prompts/2026-07-16-activity-worker-single-host-migration-closure-report.md:44`), 이 checkout은 `/Users/baek/…`야. 같은 manifest bytes가 두 host에서 동시에 유효할 수 없어.
- `scripts/verify_research_run_manifest.py:1166-1179` — `implementation_host`는 주입된 host lookup 결과와 canonical exact match. 기본 CLI는 `socket.gethostname()`(:1235)이라 **MacBook에서 만든 manifest는 Mac mini에서 무조건 `implementation_host_mismatch`**야.
- `scripts/verify_research_run_manifest.py:1243`, `979-1002` — manifest는 `execution_repo` 안의 tracked 파일이고 **현재 HEAD blob과 byte-identical**이어야 해. 즉 job마다 manifest를 쓰려면 job마다 M commit이 필요하고, `AI-OPERATING-CONTRACT.md:107-118`상 M은 manifest만 바꾸는 전용 commit, B는 manifest 아닌 tracked diff가 있어야 하며, C는 다시 manifest 전용 commit이야. **runner가 job마다 3개 commit을 자동 생성**해야 한다는 뜻인데 초안엔 그 얘기가 없어.
- `scripts/verify_research_run_manifest.py:883-895` — clean 검사는 `--untracked-files=all`. 실측으로 gitignore된 파일은 dirty로 안 잡히지만(scratch repo 검증: ignored 파일 미출력, untracked 파일만 `?? `), **ignore 안 된 결과·로그를 repo 안에 쓰면 그 순간부터 모든 후속 manifest 검증이 `dirty_tree`로 죽어**.

**영향**

구현계획을 초안대로 쓰면 runner·ledger·CLI를 다 만든 뒤 "job 실행 직전 manifest 검증" 단계에서
막혀. detached worktree 포기 / host별 manifest 분기 / daemon의 자동 commit 중 무엇을 선택하든
설계를 되돌려야 해. 최악은 daemon이 무인으로 Git commit을 만드는 방향으로 흘러 P1 write가
자동화되는 거야.

**최소 수정안**

두 층을 분리해서 초안 §권장구조 2·5를 다시 써.

- **RUN-MANIFEST는 "R1 구현 패키지"(사람 주도, 1회)만 지배한다.** `execution_repo`는 구현이 실제로 일어나는 host의 checkout, `implementation_host`는 그 host, `runtime_kind`는 R1 구현 단계에선 `none`.
- **runner가 실행하는 개별 research job은 RUN-MANIFEST가 아니라 ledger-native `job spec`을 쓴다.** job spec은 승인된 manifest를 `task_id` + `manifest_blob_sha` + `commit_sha`로 **참조만** 하고, Git commit을 만들지 않아.
- job worktree는 detached commit이 아니라 **branch에 붙은 고정 worktree 1개**를 쓰고, 재현성은 `repo_head` 기록 + 실행 전 HEAD 일치 검사로 확보해(이미 `scripts/benchmark_python_evidence_s1.py:268-275`가 쓰는 방식).
- 결과·로그·ledger는 **`.gitignore`된 경로**(`storage/research-runtime/…`, `.gitignore:29`에 `storage/` 이미 있음)에만 쓰고, Git에 들어가는 건 사람이 커밋하는 summary/report뿐이라고 못박아.

### Critical-2. 재부팅·sleep 복구에 fencing 기준이 없어서 stale lease와 중복 실행을 구분 못 해

**근거**

- 초안 §권장구조 1은 `claim, lease, heartbeat, attempt`를 기록한다고만 하고, §권장구조 3은 "stale running job을 계약에 따라 복구한다"고 하는데 **그 계약이 뭔지 정의가 없어**.
- 성공 기준은 "같은 job의 동시 실행 0"인데, lease 만료만으로는 **만료됐지만 아직 살아 있는 프로세스**(sleep에서 깨어난 job, SIGSTOP 뒤 재개, 오래 걸린 I/O)를 배제 못 해. 그 프로세스가 결과 디렉터리에 계속 쓰면 두 attempt의 산출물이 섞여.
- Mac mini는 sleep/wake를 하고 NTP 스텝도 있어. wall-clock lease는 두 경우 모두 오작동해. 레포에 이미 monotonic 기준 예산 구현이 있어(`scripts/benchmark_python_evidence_s1.py:336-355`, `self._clock = clock or time.monotonic`) — 초안은 이걸 안 쓰고 있어.
- `AI-OPERATING-CONTRACT.md:162`는 "재부팅 뒤 manifest·ledger·repo HEAD로 안전하게 resume하거나 fail-closed한다"인데, 재부팅 여부를 **판정할 값**(boot 식별자)이 ledger 필드 목록에 없어.

**영향**

성공 기준 "동시 실행 0"과 "재부팅 후 복구"가 서로를 깨. 복구를 공격적으로 하면 중복 실행,
보수적으로 하면 재부팅 후 영구 `running` 좀비가 남아 큐가 멈춰. 24시간 시험에서 이건 확률적으로만
드러나서 통과해도 증명이 안 돼.

**최소 수정안**

ledger row에 fencing 3종을 필수 필드로 추가하고 복구 규칙을 결정론으로 써.

- `boot_id`(재부팅마다 바뀌는 값, macOS는 `sysctl kern.boottime` 유도값) + `pid`.
- `lease_epoch`(claim마다 단조 증가하는 fencing token). 결과 쓰기·상태 전이는 전부
  `UPDATE … WHERE job_id=? AND lease_epoch=?` CAS로만. epoch 안 맞으면 그 프로세스는 조용히 종료.
- lease 만료는 `lease_expires_monotonic`(같은 boot 내) **AND** `lease_expires_utc`(재부팅 넘김) 둘 다 기록하고 둘 다 지나야 만료.
- 복구 규칙 표를 문서에 박아: `boot_id != 현재 boot` → 프로세스 확정 사망 → 즉시 reclaim(attempt+1). `boot_id == 현재 boot` **AND** pid 살아 있음 → reclaim 금지, heartbeat 대기. `boot_id == 현재` **AND** pid 없음 → reclaim.
- 결과는 `result_dir/<job_id>/<attempt>/`처럼 **attempt별로 격리**해서 좀비가 이전 attempt 산출물을 오염 못 하게.
- runner 인스턴스 자체는 별도 singleton 파일 lock으로 1개만(RunAtLoad + 수동 실행 + `launchctl kickstart` 동시 유입 방지).

### Critical-3. "production lock/deadline 양보"에 관측 수단이 없고, 기존 검증된 구현은 사람이 값을 주장하는 구조야

**근거**

- 초안 §권장구조 2는 "production worker lock 또는 정규 deadline과 충돌하면 job을 실패시키지 않고 양보한다"고만 해.
- 레포에 이미 같은 게이트가 있어: `scripts/benchmark_python_evidence_s1.py:262-283`의 `run_preflight`가 `activity_lock_busy` / `vlm_lock_busy` / `minutes_until_next_job < MIN_SAFE_WINDOW_MIN`(=25.0, :32)로 `SafetyAbort`를 내. **그런데 이 세 값은 관측이 아니라 CLI 인자야** — `:1328-1330`에서 `activity_lock_busy=not args.activity_lock_free`, `minutes_until_next_job=args.window_minutes`. 사람이 창을 확인하고 손으로 넣는 전제야.
- R1은 무인 실행이라 이 전제가 무너져. 그리고 실제 production 스케줄은 `specs/next-session.md:23` 기준 VLM candidate 22/00/02/04:00 KST, historical backfill 매시 :35, activity-worker `StartInterval=3600`이라 **빈 창이 촘촘해**.
- 상태 어휘도 부족해. 초안의 상태 집합은 `queued/running/succeeded/failed/cancelled`인데, 양보는 실패가 아니므로 어디에도 기록될 자리가 없어. 성공 기준 "production lock/deadline 충돌 시 자동 양보"를 **증명할 관측값이 없다**는 뜻이야.
- 굶주림(starvation) 처리도 없어. 매 시각 :35 + 4회 야간 job + 매시 activity면, 안전창 요구가 크면 research job이 영원히 안 도는 경로가 실재해.

**영향**

무인 runner가 production job과 겹쳐 돌거나(관측 실패 시), 반대로 한 번도 안 돌면서 로그상으론
정상으로 보여(양보가 상태로 안 남으니까). 둘 다 24시간 시험을 "통과"할 수 있어.

**최소 수정안**

- 상태에 `deferred`(양보)와 `blocked`(preflight fail-closed)를 추가하고, `yield_count` / `last_yield_reason`(enum) / `first_queued_at`을 ledger에 기록해. 양보는 attempt를 올리지 않아.
- lock은 **비차단 획득 시도**로 관측해(연구 runner는 production lock을 절대 보유하지 않고, 즉시 반납). 대상 lock 경로를 문서에 열거해서 고정해.
- deadline은 하드코딩 대신 **선언된 quiet-window 설정 파일**(cron 표현식 + guard band)로 두고, 그 파일이 production 스케줄과 어긋날 수 있음을 인정하는 2차 방어로 lock 관측을 병행해.
- starvation guard: `yield_count`가 임계 초과하거나 `first_queued_at` 이후 N시간 경과하면 `blocked`로 승격하고 **사람에게 보고**(계약 `AI-OPERATING-CONTRACT.md:160-161`의 "상태가 바뀔 때만 보고"와 정합).

### Critical-4. secret 차단이 "출력 단계" 규칙이라 ledger·로그·`tail`에 유출 경로가 그대로 남아

**근거**

- 초안 §권장구조 4는 "`researchctl`은 secret, raw media, signed URL, credential 내용을 출력하지 않는다"고 **표시 단계에만** 제약을 걸어. 반면 §권장구조 1은 ledger에 "error code"를, §권장구조 4는 `tail <job-id>`를 둬.
- `tail`은 정의상 job의 raw 로그를 뿌리는 명령이야. raw 로그에는 child process의 stderr가 들어가고, 거기엔 R2 signed URL(query string에 서명 포함), `.env` 값, traceback의 환경 덤프가 섞일 수 있어. **"출력 안 한다"와 "tail을 제공한다"가 서로 모순**이야.
- 계약은 더 강해. `AI-OPERATING-CONTRACT.md:146-149`는 "비밀번호·API key·webhook·cookie·signed URL을 **기록하지 않는다**"이고, `181-188`은 secret 출력을 자동 중단 사유로 둬. 기록 금지지 출력 금지가 아니야.
- 레포에 이미 같은 결론이 명시돼 있어: `docs/superpowers/specs/2026-07-21-mac-mini-local-vlm-evidence-analyst-design.md:245` — "secret, RTSP URL, raw model stderr/stdout은 artifact에 기록하지 않는다".
- 파일 권한 얘기가 아예 없어. SQLite는 `-wal`/`-shm` 형제 파일까지 생기고, 로그 디렉터리와 함께 기본 umask로 만들어지면 같은 머신의 다른 프로세스가 읽어.

**영향**

성공 기준 "secret·raw video·signed URL 출력 0"이 구조적으로 보장되지 않아. 한 번 기록되면
ledger·로그 파일에 영구히 남아서 사후 redaction으로는 못 되돌려.

**최소 수정안**

- redaction을 **쓰기 경계**로 옮겨. child stdout/stderr는 redactor를 통과한 뒤에만 파일에 떨어지고, ledger에는 `error_code`(enum) + redacted 요약 N자만.
- `researchctl tail`은 **redacted 로그만** 대상으로 한다고 명시. raw 스트림은 디스크에 아예 만들지 않아.
- redactor는 패턴 목록(서명 쿼리 파라미터, `Bearer`, key 형태 문자열, RTSP URL, 절대 홈 경로)을 갖고, **테스트 corpus로 회귀 고정**해(가짜 signed URL·가짜 key를 주입해 ledger·로그·`status --json`·`tail` 4곳에서 0 매치 assert).
- ledger·로그·result dir는 `0700`/`0600`, runner는 명시적 umask 설정. ledger는 네트워크/클라우드 동기 경로 금지(SQLite lock 깨짐 + 유출면 확대).

## Important

### Important-1. R1 산출물 순서가 "설계+계획 → M" 인데, 계약상 A는 그 둘을 이미 tracked로 갖고 있어야 해

`scripts/verify_research_run_manifest.py:1245-1246`은 `design_path`와 `plan_path`를
**`manifest.commit_sha`(=A)** 기준으로 검증해. 그리고 `:935-965`는 working tree bytes가 A의 blob과
byte-identical이어야 통과시켜. 초안 §실행·기록 흐름 1~2는 이 순서를 맞게 썼지만, **이 문서 패키지
자체(설계·계획·이 리뷰 보고서)를 지배하는 manifest는 없어**. 존재할 수도 없고 — M은 manifest만
바꾸는 전용 commit이라 설계·계획을 같이 담을 수 없거든(`AI-OPERATING-CONTRACT.md:107-111`).

- **영향:** 다음 에이전트가 "모든 Standard 작업은 manifest 선행"(`AI-OPERATING-CONTRACT.md:66`)을 곧이곧대로 적용하면 닭-달걀에 빠져.
- **최소 수정:** 초안에 한 줄 추가 — "이 문서 패키지는 `2026-07-27-ai-operating-contract-report.md:172`의 `다음 허용 행동`(= R1 실행 manifest와 구현계획 작성) 권한으로 수행하고, 자체 RUN-MANIFEST를 만들지 않는다."

### Important-2. M에서 정지하는 설계가 `budget.deadline`·`approved_at`을 만료시킬 수 있고, validator는 그걸 안 막아

초안 §실행·기록 흐름 3 "이번 패키지는 M에서 정지한다" + 4 "별도 구현 승인 후 … B를 만든다".
그런데 `RUN-MANIFEST.schema.json:610-640`의 `budget.deadline`과 `authorization.approved_at`은 M
시점에 고정되고, `AI-OPERATING-CONTRACT.md:120-128`상 final에서 바꿀 수 있는 건 다섯 provenance
필드뿐이야. deadline은 그 다섯에 없어. 그리고 validator는 deadline을 **파싱만** 하고 현재 시각과
비교하지 않아(`scripts/verify_research_run_manifest.py:317-340`은 형식 검증, 실행 경로 `:1230-1332`에
시각 비교 없음).

- **영향:** 구현 승인이 늦어지면 이미 만료된 deadline 아래에서 B가 만들어지고, validator는 통과시켜. "budget·deadline 초과 시 중단"(`AI-OPERATING-CONTRACT.md:190`)이 서류상으로만 남아.
- **최소 수정:** R1 start manifest의 `deadline`을 "승인 대기 기간을 흡수할 만큼" 넉넉히 잡거나(권장), 만료 시 **새 A→M→B→C를 시작한다**고 초안에 명시. 그리고 deadline 강제는 validator가 아니라 실행 에이전트/runner 책임이라고 문서에 못박아.

### Important-3. R1 구현 manifest의 `runtime_kind`가 미정이고, 잘못 고르면 C(final)를 통과할 수 없어

`scripts/verify_research_run_manifest.py:1199-1212` — `runtime_kind != "none"`이면 final에서
runtime attestation verifier가 **필수**야. 그리고 기본 CLI는 verifier를 주입하지 않아
(`:1236-1237` 기본값 `None`, `main()`의 `:1370`이 그대로 호출) → `runtime_attestation_verifier_missing`.
즉 R1 구현 manifest에 `runtime_kind: launchagent`를 적으면 **C를 영원히 못 닫아**.

- **영향:** 구현 끝난 뒤 final 기록 단계에서 막혀. 되돌리려면 새 실행(A→M→B→C)을 다시 시작해야 해(계약 `:129-131`).
- **최소 수정:** 초안에 명시 — R1 구현 패키지의 manifest는 `runtime_kind: none`, `runtime_host: null`, `runtime_label: null`(schema `:134-166`의 `none` 분기 요구). 실제 LaunchAgent 설치는 §실행·기록 흐름 6의 **별도 P3 manifest**에서 `runtime_kind: launchagent` + `runtime_host` + service label + trusted approval + runtime attestation verifier를 갖춰 진행. 지금 초안은 6번에서 "P3 manifest"라고만 하고 attestation verifier가 필요하다는 사실을 안 적었어.

### Important-4. `researchctl`만으로는 "MacBook·스마트폰 원격 관측" 목표를 못 채워

초안 §권장구조 4는 로컬 read-only CLI야. `2026-07-27-rba-research-system-v1-design.md:59`의 운영
완료 조건은 "원격에서 현재 HEAD, job 상태, 최근 결과, 실패 원인을 확인"이고 `:48`은
MacBook·스마트폰을 원격 클라이언트로 둬. **전송 계층이 정의 안 됐어.** 그리고
`AI-OPERATING-CONTRACT.md:160-161`의 "상태가 바뀔 때만 보고 / 승인 요청·BLOCKED·rollback·완료는
즉시 보고"는 **push 경로가 있다는 전제**인데 R1엔 없어.

- **영향:** R1이 "원격 JSON 상태 조회 가능"을 성공 기준으로 선언하지만 SSH 없이는 달성 못 하고, 스마트폰에서 SSH는 사실상 관측 수단이 못 돼.
- **최소 수정:** 둘 중 하나를 초안에 결정으로 적어. (a) R1은 **pull-only**로 한정 — `researchctl status --json`을 SSH로 실행하는 것을 유일한 원격 경로로 명시하고, push 알림은 **R1 범위 밖**이라고 선언(성공 기준 문구도 "SSH pull로 조회 가능"으로 좁힘). (b) 최소 state-change notifier를 R1에 포함. 권장은 (a) — 범위를 지키고, 알림은 자매 레포에 이미 있는 Slack 경로를 나중에 붙이는 게 맞아.

### Important-5. 재사용 가능한 검증된 구성요소가 레포에 있는데 초안이 하나도 언급 안 해

질문 10에 대한 답이야. 이미 실전 통과한 것들:

| 구성요소 | 위치 | R1에서 쓸 곳 |
|---|---|---|
| fail-closed preflight(host·HEAD·dirty·lock·안전창) | `scripts/benchmark_python_evidence_s1.py:250-283` | runner 실행 전 게이트 골격. 단 Critical-3대로 인자→관측으로 바꿔야 함 |
| monotonic 기반 예산·데드라인 | 같은 파일 `:336-360` | lease·wall budget |
| `scoped_tempdir` 정리 계약 | 같은 파일 `:365` | temp/부분결과 crash cleanup |
| 실행 의존성 fail-closed(`which` + 실제 실행) | 같은 파일 `:301-333` | launchd PATH 함정 방어 |
| `EXPECTED_HOST` env + 설치 스크립트 abort 패턴 | `docs/handoff-prompts/2026-07-16-activity-worker-single-host-migration-report.md:32-34`, closure `:44` | host guard 네이밍·plist 주입 계약 통일 |
| Mac mini 안전 운영 계약 8개 항목 | `docs/superpowers/specs/2026-07-21-mac-mini-local-vlm-evidence-analyst-design.md:234-246` | R1 safety 절의 상위 템플릿 |
| launchd 설치 스크립트 형태 | `scripts/install_router_features_launchd.sh` | R1 P3 설치 스크립트 |
| 맥미니 폴링 워커 공통 골격 | 자매 레포 `petcam-mac-runner` (`CLAUDE.md` 자매 레포 절) | LaunchAgent+폴링 스켈레톤 |

- **영향:** 같은 함정(launchd PATH, keychain, 안전창 산정)을 세 번째로 다시 밟을 위험. 그리고 host guard env 이름이 제각각이면 운영자가 헷갈려.
- **최소 수정:** 초안에 "재사용/비재사용 결정" 표를 넣고, 재사용 안 할 항목은 **이유**를 적어. 특히 `petcam-mac-runner`를 골격으로 쓸지 말지는 명시적으로 결정해야 해.

### Important-6. Mac mini에 어느 레포를 두고 R1 runtime을 돌릴지가 기존 레포 규칙과 충돌해

`CLAUDE.md` 자매 레포 절은 "Mac mini 에서는 **petcam-rba-worker 만 clone** 하고 작업(petcam-lab
clone 권장 안 함, 혼동 방지)"이야. 실제 production worker는 `petcam-nightly-reporter`에서 돌고
있어(`…2026-07-16-activity-worker-single-host-migration-closure-report.md:44`의
`WorkingDirectory=/Users/baek-end/petcam-nightly-reporter`). R1 runner 코드가 petcam-lab에 있으면
Mac mini에 petcam-lab checkout이 새로 생겨야 해.

- **영향:** 규칙 위반이거나, 아니면 규칙을 고쳐야 하는데 초안이 그 결정을 안 해. 나중에 "Mac mini에 lab이 왜 있지" 혼동이 재발해.
- **최소 수정:** R1 코드 소유 레포와 Mac mini checkout 경로를 초안에 확정하고, 채택 시 `CLAUDE.md`의 해당 문장을 같은 패키지에서 갱신한다고 적어(문서 갱신은 P1 `docs_write` 범위).

### Important-7. `cancelled` 상태에 도달할 경로가 없고, budget/deadline 초과를 집행할 주체가 없어

초안 §권장구조 1은 상태에 `cancelled`를 두는데, §권장구조 4의 `researchctl`은 `status/show/tail`
**read-only**야. 취소 명령이 없어. 마찬가지로 ledger에 `budget`을 기록한다고만 하고, wall time
초과 시 **누가 자식 프로세스를 죽이는지**가 없어. 계약 `AI-OPERATING-CONTRACT.md:190`은 budget 초과를
자동 중단 사유로 두는데 집행자가 미정이야.

- **영향:** 폭주 job을 멈출 수단이 LaunchAgent bootout밖에 없고, 그건 다른 job까지 죽여.
- **최소 수정:** (a) 취소는 `researchctl cancel <job-id>`로 **ledger에 취소 의도만 쓰는 write 1개**를 허용하고(runner가 heartbeat 시점에 관측해 자체 종료), CLI를 "read-only + cancel 1개"로 정정하거나, (b) R1에선 `cancelled`를 상태 집합에서 빼고 "취소는 R1 범위 밖"이라고 명시. 그리고 wall budget 집행은 **runner가 자식을 supervise하고 초과 시 SIGTERM→SIGKILL**한다고 적어.

## Minor

- **Minor-1.** 성공 기준 "같은 job의 동시 실행 0"은 **서로 다른 job의 동시 실행**을 금지하지 않아. R1 concurrency를 1로 고정할지 N으로 둘지 미정이고, N>1이면 Critical-2·3의 복잡도가 크게 올라가. 초안에 `max_concurrency = 1`을 R1 결정으로 박는 걸 권장.
- **Minor-2.** ledger 자체의 `schema_version`과 forward-only migration 규칙이 없어. 나중에 컬럼 추가할 때 재부팅 복구 중인 row와 충돌해. 첫 테이블에 `ledger_schema_version` 한 줄 추가면 끝나.
- **Minor-3.** ledger row에 실행을 **인가한 근거**가 안 남아. `task_id` / `manifest_blob_sha` / `manifest_commit_sha` / `repo_head` / `approved_by`를 넣어야 사후 감사에서 "이 job은 무엇이 승인했나"를 답할 수 있어(계약 `AI-OPERATING-CONTRACT.md:167-176`의 최종 보고 요구와 직결).
- **Minor-4.** 로그·result dir의 **보존/회전 정책**이 없어. `docs/research/RETENTION.md:11-16`이 raw는 gitignore 유지 + 위치만 카탈로그 기록이라고 정해뒀으니, R1도 그 표에 한 줄 추가하는 형태로 맞추면 돼.
- **Minor-5.** `researchctl`의 **exit code 계약**과 `--json` 스키마 버전이 없어. 원격 자동화(다음 패키지)에서 바로 필요해져. `status --json`에 `schema_version` 한 필드만 넣어두면 나중이 편해.
- **Minor-6.** macOS **sleep**이 24시간 지속 시험의 숨은 변수인데 초안에 없어. `caffeinate` 또는 전원 설정 중 무엇으로 막을지 정하고, 그게 P3 설치 패키지 항목인지 명시해야 해.
- **Minor-7.** `socket.gethostname()`은 DHCP/DNS 상태에 따라 흔들릴 수 있어(`.local` 유무 등). host guard가 조용히 전 job을 막을 수 있으니, host mismatch는 **`blocked` 상태 + 즉시 보고**로 다뤄야지 그냥 queued로 남기면 안 돼.

## 권장 설계

### 1. 두 층 분리 (Critical-1의 구조적 답)

```
[사람 주도, 1회]  R1 구현 패키지
   A: 설계 + 구현계획 tracked
   M: R1 start manifest만 (runtime_kind: none)
   B: runner + ledger + researchctl 구현
   C: final manifest 기록
        ↓ (별도 P3 manifest + trusted approval + runtime attestation)
[사람 주도, 1회]  Mac mini LaunchAgent 설치 + 재부팅 canary

[무인 반복]       research job
   ledger-native job spec (Git commit 0)
   승인된 manifest를 task_id + manifest_blob_sha 로 참조만
```

핵심: **runner는 Git commit을 만들지 않는다.** 이 한 줄이 Critical-1의 대부분을 해소해.

### 2. 대안 A(Local SQLite) 지지 — 조건부

Git+JSONL(B)은 원자적 claim이 불가능하고(같은 파일 append 경쟁 + fsync 순서), stale-running
질의가 O(전체 스캔)이야. Supabase(C)는 R1에 production credential·RLS·migration을 끌고 들어와서
"production 분리" 원칙 자체를 깨. **SQLite가 맞아.** 다만 조건 4개:

- `journal_mode=WAL`, `synchronous=FULL`(재부팅 복구 정확성이 성능보다 중요), `busy_timeout` 설정.
- 로컬 APFS 경로에만 배치(네트워크/클라우드 동기 폴더 금지 — SQLite 파일 lock이 깨져).
- 상태 전이는 전부 단일 트랜잭션 + `lease_epoch` CAS.
- SQLite와 **별도로 append-only 이벤트 JSONL**을 병행(레포가 이미 선호하는 형태 — `catalog.json:156`의 consensus shadow "append-only 원장"). SQLite는 현재 상태, JSONL은 감사 이력. 둘의 역할을 섞지 마.

### 3. ledger 최소 필드 (초안 대비 추가분 **굵게**)

`job_id` · `task_id` · **`manifest_blob_sha`** · **`manifest_commit_sha`** · **`repo_head`** ·
**`expected_host`** · `state` · **`boot_id`** · **`pid`** · **`lease_epoch`** ·
**`lease_expires_monotonic`** · **`lease_expires_utc`** · `heartbeat_at` · `attempt` ·
**`max_attempts`** · **`yield_count`** · **`last_yield_reason`** · **`first_queued_at`** ·
`started_at` · `finished_at` · **`exit_code`** · `error_code` · **`error_detail_redacted`** ·
`result_dir` · **`result_bytes`** · budget 필드 · **`ledger_schema_version`**

state 집합: `queued / running / deferred / blocked / succeeded / failed / cancelled`
(`deferred`·`blocked` 추가가 Critical-3의 관측 가능성을 만들어)

### 4. stop conditions (start manifest에 적을 것)

계약 `AI-OPERATING-CONTRACT.md:181-191`을 R1 언어로 내린 최소 집합:

- hostname이 `expected_host`와 불일치
- repo HEAD가 job spec의 `repo_head`와 불일치, 또는 tracked tree dirty
- production lock 보유 상태 또는 안전창 부족 → (중단 아니라) `deferred`
- budget wall time / deadline 초과
- redactor 미통과 문자열이 로그·ledger 기록 경로에서 탐지
- result dir residue·temp media 잔류
- ledger 무결성 검사 실패 또는 두 번째 runner 인스턴스 감지

### 5. 24시간 시험 **전에** 돌릴 synthetic·adversarial 테스트 (질문 8)

전부 no-op job으로 가능하고, 전부 production 무관해:

1. **SIGKILL 중단** — running row가 남고, 같은 boot에서 pid 사망 확인 후 정확히 1회 reclaim.
2. **재부팅 모사** — `boot_id`를 강제로 다르게 해서 stale running이 즉시 reclaim되는지.
3. **좀비 쓰기** — lease 만료 후 옛 프로세스가 결과를 쓰려 하면 `lease_epoch` CAS로 0건 반영.
4. **중복 기동** — LaunchAgent RunAtLoad + 수동 실행 동시 → 실행 프로세스 정확히 1.
5. **시계 조작** — wall clock을 뒤로/앞으로 점프시켜도 lease 판정이 안 뒤집히는지(monotonic 병행 검증).
6. **lock 점유** — production lock을 인위적으로 잡은 상태에서 job이 `failed`가 아니라 `deferred`로 가는지, `yield_count`가 오르는지.
7. **굶주림** — lock을 계속 잡아 임계 초과 → `blocked` 승격 + 1회 보고.
8. **deadline 경과 queued** — 시작 자체를 안 하는지.
9. **디스크 가득** — 결과 쓰기 실패가 `succeeded`로 안 새는지.
10. **redaction corpus** — 가짜 signed URL·가짜 key·RTSP URL을 자식 stderr로 뱉게 하고 ledger / 로그파일 / `status --json` / `tail` 4곳에서 0 매치.
11. **대용량 로그 tail** — 수백 MB 로그에서 `tail`이 메모리 폭발 없이 캡을 지키는지.
12. **ledger 잠김/손상** — runner가 두 번째 ledger를 만들지 않고 fail-closed 하는지.

1·2·3·4·6번은 성공 기준과 1:1이라 **이게 없으면 24시간 시험은 통과해도 증명이 아니야.**

## 구현계획 작성 전 필수 결정

Owner가 답해야 진행 가능한 것들. 괄호는 내 권장.

1. **job spec vs RUN-MANIFEST 분리를 채택할지** (권장: 채택. runner는 commit 0.)
2. **R1 구현 manifest의 `runtime_kind`** (필수: `none`. `launchagent`면 C를 못 닫아.)
3. **R1 구현을 어느 host에서 하는지** — `implementation_host`가 exact match라 지금 확정해야 해. (권장: MacBook에서 구현, Mac mini는 P3 설치 단계에서만.)
4. **Mac mini에 둘 R1 코드 레포와 경로** + `CLAUDE.md` 자매 레포 문장 갱신 여부.
5. **`max_concurrency`** (권장: R1은 1.)
6. **양보 판정 입력** — lock 경로 목록 + quiet-window 설정 파일 위치 + 안전창 분(기존 25분을 그대로 쓸지).
7. **starvation 임계** — `yield_count` 상한 또는 대기 시간 상한.
8. **원격 관측 범위** — pull-only(SSH)로 한정할지, notifier를 R1에 넣을지. (권장: pull-only + 성공 기준 문구 정정.)
9. **취소 경로** — `researchctl cancel`을 허용해 CLI를 "read-only + cancel"로 정정할지, `cancelled`를 R1에서 뺄지.
10. **ledger·result·로그 경로** (권장: `.gitignore`된 `storage/` 하위. 그래야 clean 검사와 안 싸워.)
11. **sleep 방지 수단** — `caffeinate` vs 전원 설정, 그리고 그게 P3 설치 항목인지.
12. **재사용 결정** — `petcam-mac-runner` 골격, `run_preflight`, `RuntimeBudget`, `scoped_tempdir`, `EXPECTED_HOST` 네이밍을 각각 쓸지/왜 안 쓸지.
13. **start manifest의 `deadline`** — 구현 승인 지연을 흡수할 값. 만료 시 새 A→M→B→C를 시작한다는 규칙 포함.

## 다음 허용 행동

1. Owner가 위 13개 결정을 확정한다.
2. Critical 4건을 반영해 **R1 상세 설계 문서**를 작성한다 (`docs/superpowers/specs/`).
3. 같은 tracked commit에서 **R1 구현계획**을 작성한다. 이 둘이 들어간 commit이 `A`야.
4. `A` 위에 **manifest 파일 하나만** 담은 `M`을 만든다. `runtime_kind: none`, lifecycle·actual·fallback 5필드 전부 `null`(`AI-OPERATING-CONTRACT.md:111-112`).
5. `uv run python scripts/verify_research_run_manifest.py --manifest <절대경로> --phase start`로 `RUN_MANIFEST_OK`를 확인한다. `--parse-only`의 `RUN_MANIFEST_PARSE_OK`는 **증거가 아니야**(`docs/research/README.md:61-63`).
6. **여기서 정지.** runner·ledger·`researchctl` 구현(`B`)은 별도 구현 승인 뒤에만.
7. LaunchAgent 설치·재부팅 canary·24시간 시험은 별도 P3 manifest + trusted approval verifier + runtime attestation verifier를 갖춘 뒤에만.

계속 금지: 구현 착수, Mac mini 접속, LaunchAgent 조작, production DB/R2 접근, 모델 실행,
dataset/prompt/model benchmark(R2~R9) 선행.

**참고:** 이 보고서 파일은 지금 untracked라 이 worktree는 더 이상 clean이 아니야
(`scripts/verify_research_run_manifest.py:883-895`는 `--untracked-files=all`을 써). manifest 검증을
돌리기 전에 이 파일을 먼저 commit해야 `dirty_tree`를 안 만나.
