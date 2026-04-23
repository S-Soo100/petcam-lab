# AGENTS.md — AI 에이전트 공용 진입점

> Claude / Codex / Cursor / Gemini / 기타 AI 코딩 도구가 이 레포에 들어왔을 때 **먼저 읽어야 할 파일**. 반말 유지 (프로젝트 전반 톤과 통일).

---

## 0. 너 누구냐?

이 레포는 **petcam-lab** — 도마뱀 특화 펫캠 (게코 캠) 의 **영상 백엔드**. Python 3.12 + FastAPI + OpenCV + Supabase. 학습 겸 실 프로덕트.

**한 줄 요약:** Tapo C200 RTSP 받아 1분 mp4 로 자르고 움직임 감지 태깅 + Supabase 에 메타 기록, Flutter 앱이 JWT 인증으로 조회·재생.

상위 기획·제품 정의는 옆 레포: `../tera-ai-product-master/` (SOT). 이 레포는 "어떻게 만드나" 쪽.

---

## 1. 너가 어떤 AI 인지에 따라 출발점이 다르다

### Claude (Claude Code / claude.ai)
→ **[`CLAUDE.md`](CLAUDE.md)** 를 자동 로드함. 반말 페르소나 + donts 규칙 + Stage 로드맵 + compact instructions 전부 거기 있음. 이 파일은 보조.

### Codex / ChatGPT (codex CLI 포함)
→ **이 파일** 계속 읽은 뒤 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) 으로.
→ 코드 리뷰 목적이면 [`CLAUDE.md`](CLAUDE.md) 의 "핵심 원칙" + [`.claude/rules/donts.md`](.claude/rules/donts.md) 도 확인.

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
- 상태: Stage A ~ D5 완료. E (온디바이스 필터링) 스코프 미확정.
- 테스트: **134 passing** (`uv run pytest`)

**기술 스택**
- Python 3.12 / FastAPI / uvicorn / OpenCV / Supabase / PyJWT / Cryptography (Fernet)
- 패키지 매니저: **uv** 전용. `pip install` 금지.
- BaaS: Supabase (Auth / Postgres / RLS). `service_role` 키로 RLS 바이패스.
- 배포: Cloudflare Named Tunnel → `https://api.tera-ai.uk` (로컬 맥북에서 수동 가동).

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

1. **관련 스펙 있나?** `specs/` 훑고 관련 체크박스 확인.
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

**마지막 업데이트:** 2026-04-22 (문서 리프레시 후 — `specs/feature-docs-refresh.md` 참조)
