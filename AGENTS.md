# AGENTS.md — AI 에이전트 공용 진입점

> Claude / Codex / Cursor / Gemini / 기타 AI 코딩 도구가 이 레포에 들어왔을 때 **먼저 읽어야 할 파일**. 반말 유지 (프로젝트 전반 톤과 통일).

---

## 0. 너 누구냐?

이 레포는 **petcam-lab** — 도마뱀 특화 펫캠 (게코 캠) 의 **영상 백엔드**. Python 3.12 + FastAPI + OpenCV + Supabase. 학습 겸 실 프로덕트.

**한 줄 요약:** Tapo C200 RTSP 받아 1분 mp4 로 자르고 움직임 감지 태깅 + Supabase 에 메타 기록, Flutter 앱이 JWT 인증으로 조회·재생. 핵심 AI 기술은 **RBA (Reptile Behavior Analysis)** — 밤사이 파충류 펫캠 영상을 행동 타임라인과 케어 시그널로 바꾸는 분석 시스템.

상위 기획·제품 정의는 옆 레포: `../tera-ai-product-master/` (SOT). 이 레포는 "어떻게 만드나" 쪽.

---

## 1. 너가 어떤 AI 인지에 따라 출발점이 다르다

### Claude (Claude Code / claude.ai)
→ **[`CLAUDE.md`](CLAUDE.md)** 를 자동 로드함. 반말 페르소나 + donts 규칙 + Stage 로드맵 + compact instructions 전부 거기 있음. 이 파일은 보조.
→ **2026-08-03 owner 결정:** Claude CLI/구독 세션으로 영상을 판독하는 RBA 연구는 종료됐다.
Claude는 코드·문서 교차검수에만 쓸 수 있고, 새 영상 분석 provider나 GT 생산자로 되살리지 않는다.

### Codex / ChatGPT (codex CLI 포함)
→ **이 파일** 계속 읽은 뒤 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) 으로.
→ 코드 리뷰 목적이면 [`CLAUDE.md`](CLAUDE.md) 의 "핵심 원칙" + [`.claude/rules/donts.md`](.claude/rules/donts.md) 도 확인.
→ 현재 RBA 진입점은 [`RBA OpenAI 전환·Dataset v2 설계`](docs/superpowers/specs/2026-08-03-rba-openai-reset-and-dataset-v2-design.md)다.
local VLM/router/자동 사건 묶기/Claude CLI 연구를 재개하지 않는다.

### Cursor / Windsurf / 기타 IDE 에이전트
→ 이 파일 + [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) + 작업 영역에 해당하는 [`docs/FEATURES.md`](docs/FEATURES.md) 섹션.

### Gemini CLI / 단발 쿼리 AI
→ **한 번만 호출** 될 가능성 높음. [`README.md`](README.md) + 이 파일의 "2. 필수 맥락 요약" 만으로 80% 해결.

### 네가 누군지 명시 안 된 경우
→ 아래 "2. 필수 맥락 요약" 이 최소 단위. 그 이상은 독자별 진입점 참고.

---

## 2. 필수 맥락 요약 (Top-level Context)

**프로젝트**
- 이름: `petcam-lab`
- 목적: 도마뱀(게코) 펫캠 영상 백엔드. 학습 + 상용 제품.
- 핵심 AI 기술명: **RBA (Reptile Behavior Analysis)**. Track A는 motion clip을 넓게 보는 **저비용 의미 분석 역할**이고 현재 production 모델은 미확정이다. Track B는 SegmentVLM 정밀 분석/품질 연구다. 관련 설명 SOT: [`docs/AI-VIDEO-ANALYSIS-STRATEGY.md`](docs/AI-VIDEO-ANALYSIS-STRATEGY.md).
- 연구 트랙 주의: local VLM, local router v0/v1/v2, care-guard v1/v1.1, 자동 사건 묶기,
  Claude CLI 영상 판독은 전부 `archived / invalid-for-adoption`이다. 역사 보고서와 provenance만
  유지하며 실행 후보로 되살리지 않는다.
- 현재 실행 우선순위: R2 무효 영상 정리 → 기존 197+최근 Owner-final GT의 Dataset v2 →
  Gecko Motion Engine(GME) offline baseline → 별도 TEST-SHEET의 OpenAI API 행동·관찰 pilot.
  GME는 Gecko Vision Gate를 계속 업그레이드해 게코 검출·추적·노이즈 제거와 실제 움직인 시간을
  측정한다. 과거 Python Evidence→local text LLM 의미 경로는 종료했고 자동 skip은 계속 금지한다.
- 상태: Stage A ~ D5 완료. E (온디바이스 필터링) 스코프 미확정.
- 테스트 기준선: **1,224 passing, 5 skipped** (`uv run pytest -q`, 2026-08-03)

**기술 스택**
- Python 3.12 / FastAPI / uvicorn / OpenCV / Supabase / PyJWT / Cryptography (Fernet)
- 패키지 매니저: **uv** 전용. `pip install` 금지.
- BaaS: Supabase (Auth / Postgres / RLS). `service_role` 키로 RLS 바이패스.
- 배포: fly.io API → `https://api.tera-ai.uk`, R2/Supabase, Vercel 라벨링 웹. Gemini VLM worker는 historical/셧다운 대상.

**레포 관계**
- `tera-ai-product-master` — 제품 기획 SOT ("무엇/왜")
- **`petcam-lab` (여기)** — 백엔드 구현 ("어떻게")
- `tera-ai-flutter` — 모바일 앱

**페르소나 / 톤**
- 사용자는 실용주의 파트너를 원함. 칭찬 X, 결과물 O.
- 모든 응답·주석·문서는 **반말** (한국어 `~해/~지/~네`).
- 학습 레포라 새 개념 쓸 때 **짧은 이유 주석 허용** (일반 코딩 규칙의 "주석 최소화" 예외).

**핵심 금지 규칙** (전체: [`.claude/rules/donts.md`](.claude/rules/donts.md))
1. **기억으로 단정 금지** — 라이브러리 API·파일 경로 언급 전에 `Read` 로 확인.
2. **최소 변경 원칙** — 요청 범위 밖 리팩토링·스타일·과잉 수정 금지.
3. **진단 없는 수정 금지** — 버그 보고 받으면 로그 + 코드 추적 + `git diff` 3단 진단 후 수정.
4. **비밀값 커밋 금지** — RTSP 비번, Supabase 키, Fernet 키는 `.env` 에만.
5. **파괴적 git 작업 금지** — `reset --hard`, `push --force`, `branch -D` 는 사용자 명시 승인 필요.

### Cross-repo·runtime handoff gate

다른 레포·세션·머신의 에이전트에게 구현을 넘길 때는 다음 계약을 먼저 지켜.

1. handoff manifest에 `execution_repo`, plan/design 절대경로, 40자리 commit SHA, `implementation_host`, `runtime_kind`를 적는다.
2. background/runtime 작업이면 `runtime_host`와 service label도 별도로 적는다. 구현 host와 실행 host를 같은 것으로 추측하지 않는다.
3. plan/design은 tracked commit에 포함되고 clean이어야 한다. untracked·staged-only 파일은 전달 금지다.
4. `uv run python scripts/verify_agent_handoff.py --manifest /absolute/handoff.md`를 실행한다.
5. `HANDOFF_OK` 전문과 manifest 절대경로를 전달하기 전에는 다른 에이전트에게 구현 명령을 내리지 않는다.
6. 상대경로만 전달하거나 “최신 main”이라고 쓰지 않는다. 수신 agent는 manifest의 `execution_repo`로 이동해 HEAD를 다시 확인한다.
7. 계획 파일이 없을 때 추측 구현하지 않고 멈추는 것은 올바른 fail-closed다.
8. 운영 완료는 목표 `runtime_host`의 hostname·service loaded 상태·working directory·repo HEAD·실제 run 증거가 있을 때만 주장한다.

### 실행·완료 계약

모든 에이전트는 [`docs/agent-execution-contract.md`](docs/agent-execution-contract.md)를 따른다.
사용자가 구현부터 반영까지 승인했다면 리뷰·통합·Preview·canary를 한 작업으로 이어가고 임의의
Stop Point를 만들지 않는다. `IMPLEMENTED_UNVERIFIED`·`PREVIEW_READY`·`DEPLOYED_VERIFIED`를
구분하고, 동등한 대체 검증이 있으면 도구 부재만으로 `BLOCKED` 처리하지 않는다. 보고할 때는
HEAD·upstream·tracked/untracked 상태를 실제 출력 그대로 적는다.

---

## 3. 우선순위 읽기 순서 (맥락 복원용)

빠른 시작 (5분):
1. [`README.md`](README.md) — 1분 요약 + 퀵스타트 + 문서 지도
2. [`specs/next-session.md`](specs/next-session.md) — 직전 세션 마무리 + 다음 할 일

기능/구조 파악 (15분):
3. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — 시스템 맵 + backend 내부 구조
4. [`docs/FEATURES.md`](docs/FEATURES.md) — 기능 9개 단위 정리

작업별 참조 (필요 시):
5. [`docs/API.md`](docs/API.md) — 엔드포인트 레퍼런스
6. [`docs/DATABASE.md`](docs/DATABASE.md) — 테이블 + RLS + 마이그레이션
7. [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — Tunnel 운영
8. [`docs/ENV.md`](docs/ENV.md) — 환경변수 전체
9. [`docs/GLOSSARY.md`](docs/GLOSSARY.md) — 용어집
10. [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) — 코드 기여

결정 이력:
11. [`specs/README.md`](specs/README.md) — 스펙 목록 + 진행 상태
12. 개별 `specs/stage-*.md` — Stage 별 스코프·완료 조건·설계 메모·학습 노트

학습 노트 (과정 기록):
13. [`docs/learning/`](docs/learning/) — Stage 진행 당시 학습 노트 (공식 문서 아님)

---

## 4. 작업할 때 (프로토콜)

### 4-1. 작업 시작 전

0. **🚦 새 방향/투자/실험을 제안·착수하나?** → [`docs/decision-gate.md`](docs/decision-gate.md) 4게이트(①SOT 부합 ②기대효과 명확 ③측정가능 ④유효한 계획)를 먼저 통과시키고 판정을 로그에 append. 과거 탈락 제안 재등판이면 탈락 사유 해소를 먼저 보여야 함. (기존 스펙의 체크박스 진행·단발 버그픽스는 해당 없음 — "방향"이 새로울 때만)
   **현재 연구 상태 요약은 [`specs/next-session.md`](specs/next-session.md) 최상단 + 2026-07-21 블록이 정본** — P1(라벨 결정론) adopt·오탐 42건 전수 재측정 완료(진짜 오탐 1/42, 지배 원인=temperature 비결정성), T0·T1 probe reject(체류-단독·합성점수 v1 무효), P2(케이지 프로필) hold, 사전 필터 재도전 영구 탈락. 이 판정들을 모르는 채 유사 제안을 다시 만들지 말 것.
1. **관련 스펙 있나?** `specs/` 훑고 관련 체크박스 확인.
   - RBA / VLM / SegmentVLM / 세그먼트 분석법 관련이면 [`docs/AI-VIDEO-ANALYSIS-STRATEGY.md`](docs/AI-VIDEO-ANALYSIS-STRATEGY.md) 로 사업·관계도 맥락을 잡고, 구현/실험 상세는 [`specs/experiment-event-segment-vlm.md`](specs/experiment-event-segment-vlm.md) 기준으로 전략을 구분한다.
   - local LLM/router/Python Evidence 의미 JSON/자동 사건 묶기 제안이면 새 실험을 만들지 않고
     2026-08-03 종료 결정을 먼저 확인한다. 단 GME의 Gate 기반 검출·추적·활동시간 연구는 현재
     승인 트랙이며 [`GME v1 설계`](docs/superpowers/specs/2026-08-03-gecko-motion-engine-v1-design.md)를 따른다.
2. **없으면 새로 써야 하나?** 판단 기준 — "내일의 나/사용자가 '왜 이렇게 했지?' 물을 확률이 높은가?"
   - 예 (스테이지/3일+/설계 결정) → `specs/_template.md` 복사 → 스코프·완료 조건 먼저 채우고 **사용자 확인 후** 착수.
   - 아니오 (단발 버그/리팩토링/1~2시간 작업) → 바로 진행.

### 4-2. 코드 작성

- **학습 레포이면서 실 프로덕트** — 새 개념/라이브러리 쓸 때 짧은 WHY 주석 남겨. TS/Node 비유가 있으면 함께.
- **비동기·OpenCV·파일 I/O** 작업은 [`.claude/rules/donts/python.md`](.claude/rules/donts/python.md) 필독.
- 블로킹 I/O (OpenCV, 파일) 는 **동기 `def` 라우트** 또는 `asyncio.to_thread` 로 감싸.
- 테스트 — RTSP/Supabase 의존하는 건 `@pytest.mark.integration`, 유닛은 fake 프레임 (numpy).

### 4-3. 완료 시

- 스펙 체크박스 갱신 → 전부 ✅ 이면 상태를 `✅ 완료` 로.
- `specs/README.md` 목록 표도 같이 갱신.
- Standard 이상 작업이면 [`.claude/donts-audit.md`](.claude/donts-audit.md) 에 한 줄 추가.
- 커밋은 **사용자 명시 승인** 후에만. 자동 커밋 금지.

### 4-4. 커밋 메시지 컨벤션

- prefix 필수: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`
- 한글 설명 (예: `feat: RTSP 프레임 버퍼링 + 재연결 로직`)
- Co-Authored-By 태그 유지 (Claude Code 가 자동 추가)

---

## 5. 에이전트 간 공통 원칙

### 기억보다 확인 우선
라이브러리 API / 파일 경로 / 설정값을 언급하기 전에 `Read` / `Grep` / 공식 문서로 검증. Python 은 자동완성 없는 환경에서도 이 습관 유지.

### 사용자 아이디어 맹목 신뢰 X
- 구현 방식 제시받으면 먼저 **더 나은 대안 탐색**
- 대안 없으면 왜 이게 최선인지 근거 한 줄
- 사용자 기분보다 **더 나은 결과물** 우선

### 실험 먼저, 추상화 나중
- 같은 패턴 **3번** 반복될 때 추상화 도입. 그 전엔 복붙 OK.
- 확정 안 된 설계를 미리 일반화하지 말 것 (YAGNI).

### 스코프 흔들리면 스펙 먼저
코드부터 짜지 말고 `specs/{주제}.md` 에 스코프·완료 조건 먼저 써. "In/Out 경계" 가 핵심.

### 파괴적 작업 전 확인
- `git reset --hard` / `push --force` / `branch -D` / `rm -rf`
- DB 스키마 변경 / 프로덕션 데이터 삭제
- 사용자 명시 승인 없이 진행 금지.

### 외부 AI CLI 호출 권한
사용자는 Gemini CLI / Codex CLI 구독 완료. Claude 가 필요하면 Bash 로 직접 호출 가능:
- `gemini -p "프롬프트"` — Google AI 검토/요약
- `codex exec "프롬프트" -s read-only` — ChatGPT 코드 리뷰

### iTerm Claude 교차검수 접근 규칙

- 사용자가 iTerm에 열어 둔 Claude 세션을 지정했거나 깊은 설계·계획의 Claude 교차검수를 승인한 경우,
  **iTerm2 공식 AppleScript 인터페이스**(`tell application "iTerm2"`)를 기본 접근 경로로 사용한다.
- Computer Use가 iTerm 접근을 안전 정책으로 거부해도 blocker로 처리하지 않는다. 비공식 키 입력 도구나
  화면 좌표 자동화를 우회 수단으로 사용하지 않는다.
- 접근 전 세션 이름을 확인하고, 의도한 Claude/RBA 세션에만 bounded prompt를 보낸다. 출력은 마지막 필요한
  범위만 읽고 URL·credential·secret·개인정보·원문 GT는 출력하거나 전달하지 않는다.
- Claude 교차리뷰 결과는 참고 의견이다. Codex가 현재 SOT·코드·실측 데이터와 대조해 채택/기각 근거를
  남기며, Claude 출력만으로 production 변경·DB/R2 write·배포·정답 확정을 실행하지 않는다.

### Supabase Dashboard Chrome 계정 분리 규칙

- Supabase Dashboard·SQL Editor·Auth 관리자·로그·프로젝트 설정 등 **Supabase 브라우저 UI는 반드시
  `terraaidev@gmail.com`으로 로그인된 Chrome 프로필에서만 접근한다.**
- 접근 전에 선택한 Chrome 프로필 또는 화면의 로그인 계정이 `terraaidev@gmail.com`인지 확인한다.
  확인할 수 없거나 해당 세션이 열려 있지 않으면 중단하고, 다른 계정으로 우회하지 않는다.
- `bss.rol20@gmail.com` Chrome 프로필은 `label.tera-ai.uk`의 Owner 사용자 흐름 검증에만 사용한다.
  이 프로필로 Supabase Dashboard를 열거나 기존 Supabase 탭을 조작하는 것은 금지한다.
- 이 규칙은 브라우저 UI 계정 분리에 관한 것이다. 승인된 CLI·SSH·service-role 운영 절차는 기존
  권한·preflight·비밀값 비출력 규칙을 그대로 따른다.

### RBA 현재·역사 트랙 분리

| 트랙 | 주 위치 | 도구 | 산출물 |
|---|---|---|---|
| 현재 사람 데이터 | `petcam-lab` 라벨링 웹·Dataset v2 | 사람 blind/Owner-final | 행동 GT·복수 행동·구간·provenance |
| 현재 cloud 후보 | 별도 승인 pilot | OpenAI API + deterministic media preparation | GT와 분리된 prediction ledger |
| 현재 활동시간 | `petcam-lab` + `gecko-vision-gate` | GME, detector, tracker, OpenCV | gecko moving/static/not_visible/unknown 구간·활동시간 |
| 역사 archive | 각 experiment/report | local VLM/router, Claude CLI, 자동 사건 묶기 | 실패 근거·재현 provenance만 보존 |

혼합 금지:
- Claude/local/router/사건 묶기 결과를 현재 행동 정답이나 삭제 근거로 쓰지 않는다.
- local router의 `skip`, `auto_moving`, `auto_p0`를 어떤 버전으로도 켜지 않는다.
- GME는 실제 게코 움직인 시간을 측정하지만 행동명·하이라이트·VLM route를 확정하지 않는다.
- Gate v3 결과도 독립 future holdout 전에는 행동 GT나 자동 skip 근거로 쓰지 않는다.

---

## 6. 흔한 함정

- **OpenCV `cap.release()` 누락** — VideoCapture 는 `try/finally` 또는 context manager 로 반드시 해제. 안 하면 스레드 누수.
- **async 핸들러에 블로킹 I/O 직접** — `cv2.VideoCapture`, `cv2.imwrite`, 파일 I/O 는 `def` 로 선언하거나 `asyncio.to_thread` 감싸.
- **pip install** — 금지. `uv add <pkg>` 로 `pyproject.toml` + `uv.lock` 동기화.
- **`storage/` 밖에 영상 저장** — 레포 루트 흩뿌리면 `.gitignore` 통과해 사고.
- **비번 로그 노출** — `mask_rtsp_url` 써서 치환 후 로깅.
- **큰 변경 한 번에 읽기** — 변경 10 파일+ 이면 `git diff --stat` → 그룹핑 → 순차 처리.

---

## 7. 이 파일이 안 다루는 것

- 제품 기획 / 요구사항 → `../tera-ai-product-master/docs/specs/petcam-b2c.md`
- Flutter 앱 쪽 이슈 → `../tera-ai-flutter/`
- 상세 스펙 / 결정 이력 → `specs/*.md` 개별 파일
- Claude 전용 상세 규칙 (compact 지침 등) → [`CLAUDE.md`](CLAUDE.md)

---

**마지막 업데이트:** 2026-08-03 (Gecko Motion Engine 이름·게코가 실제로 움직인 시간 정의·Gate 지속 업그레이드 확정. 상세 `specs/next-session.md` 최상단)
