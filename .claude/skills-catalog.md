11# Skills Catalog — ECC → petcam-lab

> **출처:** [affaan-m/everything-claude-code](https://github.com/affaan-m/everything-claude-code) · 갱신일: 2026-04-28
> **사용법:** 각 항목 ☐를 ✅로 바꾸면 다음 단계에서 `.claude/skills/{name}/SKILL.md`로 자동 다운로드.
> **등급:** ✅ 강추 / ⚠️ 조건부(의존성·도메인 차이) / ❌ 비추(포함은 했으나 제외 권장)
> **루트:** Raw URL 패턴 → `https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/{name}/SKILL.md`

---

## 도메인 1: 백엔드 (Python / FastAPI / Postgres)

### ✅ python-patterns ✅

- **요약:** Pythonic 관용구, PEP 8, 타입 힌트, 견고하고 유지보수 쉬운 Python 앱을 위한 베스트 프랙티스
- **트리거:** Python 코드 작성·리뷰·리팩토링 시
- **본문:** Core Principles · Type Hints · Error Handling · Context Managers · Comprehensions/Generators · Data Classes · Decorators · Concurrency · Package Organization · Memory/Performance · Tooling · Anti-Patterns
- **petcam-lab 매칭:** backend/ 전반에 적용. **학습 레포 성격에 가장 잘 맞는 베이스라인** — 사용자가 Python 처음이라는 점 고려하면 핵심.

### ✅ python-testing ✅

- **요약:** pytest 기반 Python 테스트 전략 — TDD, fixture, mocking, parametrize, 커버리지
- **트리거:** Python 코드 개발 + 테스트 스위트 설계 시. "TDD 사이클: 실패 테스트 → 최소 구현 → 리팩"
- **본문:** Core Philosophy · pytest Fundamentals · Fixtures · Parametrization · Markers · Mocking · Async Testing · Exceptions · Side Effects · Test Organization · Best Practices · pytest Configuration · Quick Reference
- **petcam-lab 매칭:** 현재 134 pytest 통과 중. fixture/mock 패턴 + RTSP/OpenCV처럼 "fake numpy 프레임으로 테스트" 같은 룰(.claude/rules/donts/python.md #13)과 시너지.

### ✅ postgres-patterns ✅

- **요약:** PostgreSQL 쿼리 최적화·스키마·인덱싱·보안. **Supabase 베스트 프랙티스 기반**
- **트리거:** SQL 쿼리/마이그레이션 작성, 스키마 설계, 성능 트러블슈팅 시
- **본문:** Quick Reference · Index Cheat Sheet · Data Type Quick Reference · Common Patterns · Anti-Pattern Detection · Configuration Template
- **petcam-lab 매칭:** Supabase Postgres 직결. cameras / captures / clip_mirrors 인덱스, RLS, 쿼리 최적화에 가장 핵심. Stage C 이후 필수.

### ☐ database-migrations ✅

- **요약:** 스키마 변경·데이터 마이그레이션·롤백·zero-downtime 배포. Postgres/MySQL + 다수 ORM (Prisma·Drizzle·Kysely·Django·golang-migrate)
- **트리거:** 마이그레이션 작성/리뷰 시
- **본문:** Core Principles · Migration Safety Checklist · PostgreSQL Patterns · 각 ORM 섹션 · Zero-Downtime Strategy · Anti-Patterns
- **petcam-lab 매칭:** Supabase 마이그레이션 SQL 작업 — clip_mirrors 같은 신규 테이블 추가 시 zero-downtime 체크리스트 활용. **Python 쪽은 Django 섹션이지만 우리는 Django 안 씀** → 일반 Postgres 섹션만 사용.

### ✅ api-design ✅

- **요약:** REST API 설계 — 리소스 네이밍, 상태코드, 페이지네이션, 필터링, 에러 응답, 버전관리, rate limit
- **트리거:** 새 API 엔드포인트 설계 또는 기존 계약 리뷰 시
- **본문:** Resource Design · HTTP Methods/Status Codes · Response Format · Pagination · Filtering/Sorting/Search · Auth · Rate Limiting · Versioning · Implementation Patterns · Checklist
- **petcam-lab 매칭:** FastAPI 라우터 (cameras/captures/auth) 컨벤션 정렬. 페이지네이션·에러 포맷 표준화에 도움. **Stage E API 추가 시 권장**.

### ✅ security-review ✅

- **요약:** 인증·입력 검증·시크릿·API 엔드포인트·민감 데이터 처리 시 보안 체크리스트
- **트리거:** 인증 추가, 사용자 입력 처리, 시크릿 다루기, API 엔드포인트 추가 시
- **본문:** Secrets Management · Input Validation · SQL Injection · Auth · XSS · CSRF · Rate Limiting · Sensitive Data · Blockchain Security · Dependency Security · Pre-Deployment Checklist
- **petcam-lab 매칭:** Stage D JWT 검증 + RTSP 비밀번호·Supabase 키 관리. **donts/python.md #11(비밀값 커밋 금지) 보강용**으로 강추. Blockchain Security 섹션은 무관, 무시.

### ☐ security-scan ⚠️

- **요약:** AgentShield로 `.claude/` 자체 보안 검사 — CLAUDE.md, settings.json, MCP 서버, 훅, 에이전트 정의
- **트리거:** 새 프로젝트 셋업 또는 `.claude/settings.json`/CLAUDE.md/MCP 변경 후
- **본문:** Prerequisites · Usage · Auto-Fix · Opus Deep Analysis · Initialize Secure Config · GitHub Action · Severity Levels
- **petcam-lab 매칭:** `.claude/settings.json`·hooks 누적 중이라 정기 audit 가치. **AgentShield 외부 도구 의존** — 설치 부담 있음. 일단 ☐ 보류 추천, 셋업 자유롭다 싶을 때 도입.

---

## 도메인 2: VLM eval & 프롬프트 (Round 1 작업)

> ⚠️ **중요 구분:** 아래 `eval-harness`, `agent-eval`, `ai-regression-testing`은 모두 **"코딩 에이전트/Claude Code 세션 평가"** 가 주제다. **VLM 라벨링 모델 평가**가 아니다. 우리 Round 1 평가에 직접 매칭되는 건 `prompt-optimizer`, `cost-aware-llm-pipeline`, `regex-vs-llm-structured-text`.

### ✅ prompt-optimizer ✅

- **요약:** 사용자가 "이 프롬프트 개선해줘" 요청 시 진단·개선·재작성. ECC 컴포넌트(commands/skills/agents) 매칭, 프로젝트 자동 감지 (pyproject.toml 등)
- **트리거:** "optimize prompt", "improve my prompt", "프롬프트 개선해줘" 등 명시적 요청. **직접 실행 모드에서는 비활성화** (advisory only)
- **본문:** Prompt Diagnosis · ECC Component Matching · Scope Assessment · Optimized Output · Enhancement Rationale · Workflow Recommendation · Project Detection
- **petcam-lab 매칭:** ✨ Round 1 v3.1 프롬프트 보강·2차 평가 작업과 직결. 새 휴리스틱(eating_paste, tongue_flicking 등) 추가 전 진단 도구.

### ✅ cost-aware-llm-pipeline ✅

- **요약:** LLM API 비용 최적화 — 작업 복잡도별 모델 라우팅, 예산 추적, 재시도, 프롬프트 캐싱
- **트리거:** LLM API 호출 앱 빌드 시 비용 통제와 품질 양립
- **본문:** When to Activate · Core Concepts · Composition · Pricing Reference (2025-2026) · Best Practices · Anti-Patterns
- **petcam-lab 매칭:** Gemini API 호출 누적 (라벨링 N건 × 토큰량). 다양성 데이터 보강 단계에서 비용 가시화 도구로 유용.

### ✅ regex-vs-llm-structured-text ✅

- **요약:** 구조화된 텍스트 파싱 시 regex vs LLM 결정 프레임워크 — "regex가 95-98% 케이스를 싸고 결정론적으로 처리"
- **트리거:** 반복 패턴의 구조화된 텍스트 파싱
- **본문:** Decision Framework · Architecture Pattern · Implementation · Real-World Metrics · Best Practices · Anti-Patterns
- **petcam-lab 매칭:** ✨ VLM 출력 JSON 파싱·검증에 직접 적용. 라벨 결과를 regex로 1차 검증 → 실패 시 LLM 재요청 같은 패턴 표준화.

### ☐ ai-regression-testing ⚠️

- **요약:** AI가 작성한 코드의 회귀 테스트 — sandbox-mode API 테스트(DB 의존 없이), 자동 버그체크 워크플로우. **"같은 모델이 코드 쓰고 리뷰할 때 생기는 blind spot"** 잡기
- **트리거:** AI 에이전트가 백엔드 로직 수정, 버그 발견·수정 후, sandbox/mock 모드 사용 시
- **본문:** The Core Problem · Sandbox-Mode API Testing · Bug-Check Workflow Integration · AI Regression Patterns · Strategy · Quick Reference · DO/DON'T
- **petcam-lab 매칭:** **VLM 라벨링 회귀가 아니라 "Claude가 쓴 코드 회귀"임 (혼동 주의)**. tests/ 강화 + sandbox 모드 도입 시 가치. 우선순위는 python-testing보다 낮음.

### ☐ token-budget-advisor ⚠️

- **요약:** 응답 길이/깊이/토큰 예산 안내. 사용자가 명시적 제어 요청 시 25/50/75/100% 옵션 제시
- **트리거:** "짧게", "길게", "토큰 제한 두자" 등 명시적 길이 제어 요청
- **본문:** 토큰 추정 · 응답 크기 추정 · 옵션 제시 · 단축어
- **petcam-lab 매칭:** 일반적 도구. **`origin: community`** (ECC 외부 출처). 적용 가치 보통 — 페어 코딩에서 응답 길이 자주 조절하면 추가.

### ☐ eval-harness ❌

- **요약:** Claude Code 세션을 위한 EDD(Eval-Driven Development) 프레임워크. 정형 평가 + pass@k 메트릭
- **본문:** Philosophy · Eval Types · Grader Types · Metrics · Workflow · Integration · Eval Storage · Best Practices · Product Evals
- **petcam-lab 매칭:** **Claude Code 세션 평가 도구 — VLM 라벨링 평가 아님**. 일반 EDD 학습 자료로는 가치 있으나 즉시 도입 가치 낮음. 보류 추천.

### ☐ agent-eval ❌

- **요약:** 여러 코딩 에이전트(Claude Code, Aider, Codex) 헤드투헤드 비교 — pass rate, cost, time, consistency
- **본문:** Installation · Core Concepts · Workflow · Judge Types · Best Practices · Links
- **petcam-lab 매칭:** **여러 AI 코딩 도구 비교 벤치마크용 — 우리 VLM 평가와 결이 다름**. 제외 추천.

---

## 도메인 3: 워크플로우 & 문서

### ☐ architecture-decision-records ✅

- **요약:** 아키텍처 결정을 ADR 문서로 자동 캡처. 결정 순간 자동 감지, 컨텍스트·대안·근거 기록
- **트리거:** 사용자가 결정 기록 요청 또는 중대한 기술 대안 선택 시
- **본문:** ADR Format · Workflow · Reading ADRs · Directory Structure · Index Format · Detection Signals · Good ADR · ADR Lifecycle · Categories · Integration
- **petcam-lab 매칭:** **학습+실프로덕트 레포에 가장 자연스러움**. 현재 Stage A~D 결정(왜 Supabase Auth만 공유? 왜 on-device 필터링?)이 specs/ 학습노트 섹션에 흩어져 있음 → ADR로 정리. specs/와 시너지.

### ☐ code-tour ✅

- **요약:** CodeTour `.tour` 파일 생성 — 페르소나 타겟 단계별 워크스루(파일·라인 앵커). 온보딩, 아키텍처, PR 리뷰, RCA용
- **트리거:** 가이드 워크스루 아티팩트 요청 시
- **본문:** When to Use/NOT to Use · Workflow · Step Types · SMIG 작성 룰 · Narrative Shape · Example · Anti-Patterns · Best Practices
- **petcam-lab 매칭:** backend/ 구조 학습 가이드. Stage별 walkthrough(RTSP → 감지 → DB → 인증). **VS Code CodeTour 확장 의존** — 사용자가 VS Code 안 쓰면 가치 절감.

### ☐ codebase-onboarding ✅

- **요약:** 새 레포 합류 시 reconnaissance → architecture mapping → convention detection → 아티팩트 생성(Onboarding Guide + starter CLAUDE.md)
- **트리거:** "새 프로젝트 합류" 또는 "Claude Code를 새 레포에 처음 셋업"
- **본문:** Phase 1 Reconnaissance · Phase 2 Architecture Mapping · Phase 3 Convention Detection · Phase 4 Generate Artifacts · Best Practices · Anti-Patterns · Examples
- **petcam-lab 매칭:** 사용자(또는 미래의 Claude 세션)가 처음 합류할 때. CLAUDE.md 보완·갱신 도구로 활용 가능.

### ☐ tdd-workflow ✅

- **요약:** TDD 강제 — 80%+ coverage(unit/integration/E2E)
- **트리거:** 새 기능 작성, 버그 픽스, 리팩토링
- **본문:** Core Principles · Test Types · Git Checkpoints · TDD Steps · Patterns · File Organization · Mocking · Coverage Verification · Common Mistakes · Continuous Testing · Best Practices · Success Metrics
- **petcam-lab 매칭:** python-testing과 결합. pytest 134개 → coverage 가시화·전체 80% 목표 잡을 때.

### ✅ rules-distill ✅

- **요약:** 스킬을 스캔해 횡단 원칙 추출 → 룰 파일에 append/revise/생성. 정기 룰 유지보수용
- **트리거:** 스킬 새로 설치한 후, 룰이 스킬 대비 미흡하다 느낄 때
- **본문:** Phase 1 Inventory · Phase 2 Cross-read & Verdict · Phase 3 User Review · Verdict Reference · Example Run · Design Principles
- **petcam-lab 매칭:** ✨ **이 큐레이션 자체와 시너지**. 스킬 도입 후 `.claude/rules/donts.md` & `donts/python.md`와 비교해 중복·공백 정리.

### ☐ documentation-lookup ⚠️

- **요약:** Context7 MCP로 라이브러리/프레임워크 최신 docs 조회 (학습 데이터 대신)
- **트리거:** 라이브러리/프레임워크 셋업·API 레퍼런스 질문
- **본문:** Core Concepts · When to Use · How It Works · Examples · Best Practices
- **petcam-lab 매칭:** FastAPI/Next.js/Supabase 최신 docs 조회. **Context7 MCP 설치 필요** — 현재 settings.json에 없음. 도입 시 `mcp__context7__*` 권한 추가 필요.

### ☐ deep-research ⚠️

- **요약:** firecrawl + exa MCP로 멀티소스 deep research, 인용 포함 리포트
- **트리거:** 심층 리서치, 경쟁 분석, 기술 평가, due diligence
- **본문:** MCP Requirements · Workflow · Parallel Research · Quality Rules · Examples
- **petcam-lab 매칭:** PoC 단계 기술 비교(예: Supabase vs Firebase, MJPEG vs HLS) 시 유용. **firecrawl + exa MCP 의존** — 미설치. 도입 시 추가 권한·키 필요.

### ☐ coding-standards ⚠️

- **요약:** 크로스프로젝트 코딩 컨벤션 — 네이밍, 가독성, 불변성, 리뷰 베이스라인
- **트리거:** 새 프로젝트/모듈 시작, 코드 품질 리뷰
- **본문:** Code Quality Principles · TypeScript/JavaScript Standards · React Best Practices · API Design Standards · File Organization · Comments · Performance · Testing · Code Smell Detection
- **petcam-lab 매칭:** **TS/JS 위주 — Python 백엔드에는 부분적 적용**. web/ 쪽은 활용 가능. python-patterns로 대체 가능.

---

## 도메인 4: 프론트 (Next.js / React)

> ⚠️ ECC 레포에 `react-patterns`, `nextjs-patterns`, `typescript-patterns` 같은 코어 스킬은 **존재하지 않음**. 아래는 가용한 차선책.

### ☐ frontend-patterns ✅

- **요약:** React/Next.js/state 관리/성능 최적화 패턴
- **트리거:** React 컴포넌트 빌드, 상태 관리
- **본문:** Component Patterns · Custom Hooks · State Management · Performance · Form Handling · Error Boundary · Animation · Accessibility
- **petcam-lab 매칭:** web/ VLM 라벨링 대시보드에 직접. hook/state/form 패턴 정렬.

### ✅ frontend-design ✅

- **요약:** 미적 의도와 시각 일관성 강조 — "방향 정하고 끝까지 밀어붙여라"
- **트리거:** 시각 방향이 코드 품질만큼 중요한 페이지/컴포넌트
- **본문:** Design Workflow · Strong Defaults · Anti-Patterns · Execution Rules · Quality Gate
- **petcam-lab 매칭:** 라벨링 대시보드 시각 정리. 새 화면 추가 시 톤·여백·타이포 가이드.

### ☐ design-system ⚠️

- **요약:** 디자인 시스템 생성·audit, 시각 일관성 체크, 스타일 변경 PR 리뷰
- **트리거:** 일관된 디자인 시스템 만들거나 UI 일관성 audit
- **본문:** How It Works · Mode 1 Generate · Mode 2 Visual Audit · Mode 3 AI Slop Detection · Examples
- **petcam-lab 매칭:** Tailwind 일관성 audit. **현재 web/는 작아서 도입 이르다** — 화면 5개+ 시점에 재고.

### ☐ nextjs-turbopack ⚠️

- **요약:** Next.js 16+ Turbopack — incremental bundling, FS 캐싱, dev 속도, Turbopack vs webpack 결정
- **트리거:** Next.js 16+ 일상 dev에서 Turbopack 사용
- **본문:** When to Use · How It Works · Examples · Best Practices
- **petcam-lab 매칭:** **현재 Next.js 14** → 16 마이그레이션 시점에 도입. 지금은 보류.

---

## 카탈로그 요약

| 도메인              | 강추 ✅ | 조건부 ⚠️ | 비추 ❌ | 합계   |
| ------------------- | ------- | --------- | ------- | ------ |
| 백엔드              | 6       | 1         | 0       | 7      |
| VLM eval & 프롬프트 | 3       | 2         | 2       | 7      |
| 워크플로우 & 문서   | 5       | 3         | 0       | 8      |
| 프론트              | 2       | 2         | 0       | 4      |
| **합계**            | **16**  | **8**     | **2**   | **26** |

**처음 도입 시 가벼운 핵심 세트 추천 (8~10개):**

- python-patterns, python-testing, postgres-patterns (학습+실프로덕트 백본)
- security-review, api-design (FastAPI 보강)
- prompt-optimizer, regex-vs-llm-structured-text (VLM 작업 직결)
- architecture-decision-records, rules-distill (메타 운영)
- frontend-patterns (web/)

---

## Phase 2 다음 단계 (사용자 작업)

1. **위 카탈로그 훑기** — ★/⚠️/❌ 기준 + petcam-lab 매칭 멘트 보고 도입 결정
2. **체크박스 변경** — 도입할 항목의 ☐를 ✅로 (이 파일 직접 수정)
3. **Claude에게 다음 명령** — "카탈로그에서 ✅된 스킬만 `.claude/skills/`로 다운로드해줘"

다음 단계에서 Claude가 할 일:

- 표시된 스킬의 SKILL.md를 raw URL로 fetch → `.claude/skills/{name}/SKILL.md`로 저장
- frontmatter에 `source:` 필드 추가 (출처 URL + 가져온 날짜)
- `.claude/skills/README.md` 작성 (도입 스킬 목록·라이선스·출처·갱신 정책)
- 의존성 있는 스킬(documentation-lookup, deep-research 등) 도입 시 필요한 MCP/도구를 함께 안내

---

## 출처 URL 인덱스

다음 단계(자동 다운로드)에서 이 표 기반으로 fetch.

| 스킬                          | Raw URL                                                                                                              |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| python-patterns               | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/python-patterns/SKILL.md               |
| python-testing                | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/python-testing/SKILL.md                |
| postgres-patterns             | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/postgres-patterns/SKILL.md             |
| database-migrations           | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/database-migrations/SKILL.md           |
| api-design                    | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/api-design/SKILL.md                    |
| security-review               | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/security-review/SKILL.md               |
| security-scan                 | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/security-scan/SKILL.md                 |
| prompt-optimizer              | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/prompt-optimizer/SKILL.md              |
| cost-aware-llm-pipeline       | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/cost-aware-llm-pipeline/SKILL.md       |
| regex-vs-llm-structured-text  | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/regex-vs-llm-structured-text/SKILL.md  |
| ai-regression-testing         | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/ai-regression-testing/SKILL.md         |
| token-budget-advisor          | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/token-budget-advisor/SKILL.md          |
| eval-harness                  | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/eval-harness/SKILL.md                  |
| agent-eval                    | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/agent-eval/SKILL.md                    |
| architecture-decision-records | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/architecture-decision-records/SKILL.md |
| code-tour                     | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/code-tour/SKILL.md                     |
| codebase-onboarding           | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/codebase-onboarding/SKILL.md           |
| tdd-workflow                  | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/tdd-workflow/SKILL.md                  |
| rules-distill                 | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/rules-distill/SKILL.md                 |
| documentation-lookup          | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/documentation-lookup/SKILL.md          |
| deep-research                 | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/deep-research/SKILL.md                 |
| coding-standards              | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/coding-standards/SKILL.md              |
| frontend-patterns             | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/frontend-patterns/SKILL.md             |
| frontend-design               | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/frontend-design/SKILL.md               |
| design-system                 | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/design-system/SKILL.md                 |
| nextjs-turbopack              | https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/skills/nextjs-turbopack/SKILL.md              |

---

## 출처·라이선스 미해결 사항

- ECC 레포 자체 LICENSE 파일 미확인 → Phase 3 직전 검증
- ECC 본가 업데이트 동기화 정책 미정 → Phase 3에서 결정 (수동 재fetch / 무동기화 등)
- `claude-api`, `nextjs` 등 user-level (`~/.claude/skills/`)에 이미 있는 스킬과 이름 충돌 가능 → 카탈로그에서 처음부터 제외함
