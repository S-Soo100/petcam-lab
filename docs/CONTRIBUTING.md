# 기여 가이드

> 이 레포를 고치거나 확장할 때 따를 것. **학습용 + 실프로덕트** 두 성격 다 만족해야 하므로 상용 수준 품질 + 학습 친화적 주석을 병행.

## 목차

- [시작 전에](#시작-전에)
- [코드 읽는 순서](#코드-읽는-순서)
- [개발 루프](#개발-루프)
- [테스트 규칙](#테스트-규칙)
- [커밋 컨벤션](#커밋-컨벤션)
- [스펙 기반 개발 (Lightweight Spec-Driven)](#스펙-기반-개발-lightweight-spec-driven)
- [Don'ts 시스템](#donts-시스템)
- [PR / Pull 프로세스](#pr--pull-프로세스)
- [AI 에이전트 협업](#ai-에이전트-협업)

---

## 시작 전에

1. [`README.md`](../README.md) — 프로젝트 1분 요약
2. [`AGENTS.md`](../AGENTS.md) — 에이전트라면 여기부터
3. [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) — 시스템 맵
4. [`CLAUDE.md`](../CLAUDE.md) — 페르소나 + 학습 레포 맥락 (Claude 가 아니어도 참고)
5. [`.claude/rules/donts.md`](../.claude/rules/donts.md) + [`python.md`](../.claude/rules/donts/python.md) — 금지 규칙

---

## 코드 읽는 순서

처음 레포를 이해할 때 권장 경로. 15분 코스.

1. **[`backend/main.py`](../backend/main.py)** — FastAPI lifespan + 라우터 등록. 전체 기동 흐름의 진입점.
2. **[`backend/capture.py`](../backend/capture.py)** — RTSP 캡처 워커 스레드. `CaptureWorker.run()` 의 메인 루프가 이 프로젝트의 심장.
3. **[`backend/motion.py`](../backend/motion.py)** — 움직임 감지 1파일 (50줄 안팎).
4. **[`backend/clip_recorder.py`](../backend/clip_recorder.py)** — Supabase INSERT + pending 큐 + QA 미러 훅.
5. **[`backend/routers/clips.py`](../backend/routers/clips.py)** — 클립 조회 API 4종.
6. **[`backend/routers/cameras.py`](../backend/routers/cameras.py)** — 카메라 CRUD 6종.
7. **[`backend/auth.py`](../backend/auth.py)** — JWT 검증 + dev/prod 분기.
8. **[`backend/crypto.py`](../backend/crypto.py)** — Fernet 암호화.
9. **[`tests/test_capture.py`](../tests/test_capture.py)** — 캡처 동작 테스트 (fake frame numpy array).
10. **[`specs/README.md`](../specs/README.md)** — 스테이지별 스펙 인덱스.

**모르는 개념 있으면** [`docs/GLOSSARY.md`](GLOSSARY.md) 참조.

---

## 개발 루프

### 환경 구성

```bash
brew install uv
cd /Users/baek/petcam-lab
uv sync               # 의존성 설치 (.venv 자동 생성)
cp .env.example .env  # 실제 값 채우기 → docs/ENV.md
```

### 실행

```bash
# 로컬 서버 (코드 변경 자동 리로드)
uv run uvicorn backend.main:app --reload

# Swagger UI
open http://localhost:8000/docs

# 캡처 워커 없이 API 만 확인하고 싶으면 .env 에 카메라 미등록 상태로
# → /health 의 startup_error 로 "등록된 카메라 없음" 확인
```

### 의존성 추가 / 제거

```bash
uv add <패키지>          # pyproject.toml + uv.lock 동기화
uv add --dev <패키지>    # 개발 전용
uv remove <패키지>
```

**❌ `pip install` 금지** — 이 레포는 `uv` 전용 ([`donts/python.md #1`](../.claude/rules/donts/python.md)).

### 포맷팅 / 린트

현재 강제 도구 없음. 기본 PEP 8 + type hints. 도입 필요해지면 `ruff` 검토 예정 (스펙 필요).

---

## 테스트 규칙

```bash
uv run pytest -xv            # 전체 (fail-fast + verbose)
uv run pytest tests/test_capture.py -v
uv run pytest -k motion      # 이름에 'motion' 포함된 테스트만
```

**현재 134 통과 기준 (Stage A ~ D5 + QA 미러).**

### 규칙

1. **실제 RTSP / 네트워크 의존 금지 (기본)** — 유닛 테스트는 fake frame (numpy array) + mock Supabase. 네트워크 의존이 꼭 필요하면 `@pytest.mark.integration` 붙이고 CI 에서 분리 ([`donts/python.md #13`](../.claude/rules/donts/python.md)).
2. **`pytest -x` 로 실행** — 하나 깨지면 즉시 멈춤. 로그 홍수 방지 ([`donts/python.md #14`](../.claude/rules/donts/python.md)).
3. **`dependency_overrides` 로 DI 대체** — `app.dependency_overrides[get_supabase_client] = lambda: FakeSupabase()` 패턴. `_FakeSupabase + _TableOp` 예시는 [`tests/test_clip_recorder.py`](../tests/test_clip_recorder.py) 참고.
4. **같은 현상 검증은 하나만** — "happy path + 1~2 엣지" 정도. 커버리지 점수 쫓지 말 것.
5. **테스트도 rationale 주석 OK** — 특히 "왜 이 엣지를 테스트하나" 가 비자명하면.

### 테스트 파일 구조

```
tests/
├── test_motion.py            # MotionDetector 픽셀 판정
├── test_capture.py           # CaptureWorker fake frame 루프
├── test_thumbnail_capture.py # 썸네일 생성 경로
├── test_clips_api.py         # /clips 라우터 + pagination
├── test_cameras_api.py       # /cameras CRUD + 중복/암호화
├── test_pending_inserts.py   # JSONL 큐
├── test_clip_recorder.py     # INSERT + pending + 미러 훅
├── test_crypto.py            # Fernet encrypt/decrypt
├── test_rtsp_probe.py        # probe_rtsp 포맷
├── test_auth.py              # JWT verify (ES256 happy path + 위조)
└── test_main_lifespan.py     # 다중 워커 부트스트랩
```

**신규 기능 추가 시** — 대응하는 테스트 파일도 추가 / 확장. 테스트 없는 PR 은 기본 거절.

---

## 커밋 컨벤션

### prefix (필수)

| prefix | 용도 |
|--------|------|
| `feat:` | 새 기능 |
| `fix:` | 버그 수정 |
| `refactor:` | 동작 변화 없는 구조 변경 |
| `test:` | 테스트만 추가/수정 |
| `docs:` | 문서만 |
| `chore:` | 의존성 업데이트, 설정 파일, 빌드 스크립트 등 |

### 메시지

- 한글 + 1줄 요약. 필요하면 본문 추가.
- Co-Authored-By 태그 유지 (AI 페어 프로그래밍).

**예시**
```
feat: RTSP 재시도 로직 + Tapo C200 스모크 테스트 성공
```

```
fix(capture): 60초 녹화가 48초로 재생되던 빨리감기 이슈 해결

VideoCapture.CAP_PROP_FPS 가 Tapo 에서 부정확해 CFR 보정 필요.
measured_fps 로 매 프레임 duration 을 계산 → mp4 writer 에 역전달.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

### 브랜치

- 현재 혼자 작업 단계 — `main` 직접 push 허용.
- 협업자 추가 시점부터 PR 전환.
- 브랜치 네이밍: `{타입}/{설명}` (예: `feat/rtsp-stream`, `fix/cap-release-leak`).

### 파괴적 작업 주의

- `git reset --hard`, `push --force`, `branch -D`, `clean -f` — 사용자 명시 승인 없이 금지 ([`donts.md #9`](../.claude/rules/donts.md)).
- 먼저 원인 조사. "장애물 제거" 목적으로 쓰지 말 것.

---

## 스펙 기반 개발 (Lightweight Spec-Driven)

이 레포는 `specs/` 폴더의 체크리스트가 **곧 진행 상태**. 별도 status/kanban 없음.

### 작업 착수 시 판단 순서

1. **관련 스펙 있나?** `specs/` 에서 찾기.
   - 있으면 → 완료 조건 체크박스 확인, 이번 작업이 어느 항목인지 매핑.
   - 없으면 → 2번.
2. **스펙 필요한 작업인가?** "내일의 나가 '왜 이렇게 했지?' 물을 확률이 높은가?"
   - 예 (스테이지 / 3일+ / 설계 결정) → [`specs/_template.md`](../specs/_template.md) 복사 → 스코프 + 완료 조건 먼저 채우고 **사용자 확인 후** 착수.
   - 아니오 (단발 버그 / 1~2시간) → 스펙 없이 바로.
3. **작업 중** — 설계 결정은 "설계 메모", 새 개념은 "학습 노트" 섹션에 누적.
4. **작업 완료** — 완료 조건 체크박스 채움 → 전부 ✅이면 상태 `✅ 완료` → [`specs/README.md`](../specs/README.md) 목록 표 갱신.

### 원칙

- 체크리스트 = 상태.
- In/Out 경계 명시가 핵심. 스코프 흔들리면 스펙 수정 + 사유 기록.
- 완료 조건은 검증 가능하게 ("`pytest tests/test_foo.py` 통과" 같은 구체 기준).
- 폐기·보류도 남긴다. 왜 안 했는지가 미래 의사결정에 도움.

---

## Don'ts 시스템

### 구조

```
.claude/rules/
├── donts.md          # 전역 금지 규칙 (제너럴)
└── donts/
    └── python.md     # Python / FastAPI / OpenCV / uv 특화
```

### Three-Strike Rule

같은 실수 3회 반복 시 정식 룰로 승격.

| 발생 횟수 | 조치 |
|---------|------|
| 1회 | 메모리에만 저장 (`~/.claude/projects/-Users-baek-petcam-lab/memory/feedback_*.md`) |
| 2회째 | `.claude/donts-audit.md` 에 "승격 후보" 플래그 + 맥락 메모 |
| 3회째 | 정식 룰로 추가 (`donts.md` 또는 `donts/<기능>.md`) |

**예외** — "다시는 하지 마" 명시 / 되돌리기 비용이 큰 사고 (DB 삭제 등) → 1회로 즉시 정식 룰.

### Standard 이상 작업 후

`.claude/donts-audit.md` 에 한 줄 기록.

```
YYYY-MM-DD {기능} | 작업: {요약} | 참조: {규칙} | 지킴: {번호} | 놓침: {번호+이유} | 재발: {있음/없음} | 메모: {비고}
```

---

## PR / Pull 프로세스

협업자 생긴 시점부터 적용. 현재 단독.

1. 브랜치 → 변경 → 커밋
2. `uv run pytest -xv` 통과 확인
3. `git push -u origin <branch>`
4. `gh pr create --title "..." --body "..."`
5. Self-review → 리뷰어 배정 → 머지

**PR 본문 템플릿**

```markdown
## Summary
- ... 바뀐 것 1~3줄
- 관련 스펙: `specs/xxx.md`

## Test plan
- [ ] `uv run pytest -xv`
- [ ] 실기 스모크 (해당되면)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## AI 에이전트 협업

이 레포는 AI 페어 프로그래밍을 적극 사용. 에이전트별 진입점.

| AI 툴 | 읽을 것 |
|-------|---------|
| Claude Code | [`CLAUDE.md`](../CLAUDE.md) — 페르소나 + 프로젝트 규칙 |
| Codex / Cursor / Gemini 등 | [`AGENTS.md`](../AGENTS.md) — 공통 진입점 |

### 에이전트에게 작업 넘길 때

- **명확한 스코프** — "이 스펙의 이 체크박스" 수준으로 구체적으로.
- **수정 범위 제한** — "backend/capture.py 만" 처럼 파일 레벨로.
- **출력 기대치 명시** — "구현 / 리뷰 / 탐색" 중 뭔지.

### 에이전트 폭주 방지

- 변경 파일 10개+ 이면 한 번에 읽지 말 것 — `git diff --stat` → 그룹핑 → 순차 처리.
- Grep 먼저, Read 나중 — 디렉토리 통째 읽기 금지.
- 빌드/수정 루프 최대 3회. 초과 시 중단 + 보고.

상세: `/Users/baek/ideaBank/frameworks/claude-agent-orchestration.md` (CAOF v1.2).

---

## 질문 / 막힐 때

1. 관련 스펙 먼저 읽기 — 거의 대부분 "왜 이렇게 짰는지" 의 설계 메모가 있음.
2. 학습 노트 확인 — [`docs/learning/`](learning/).
3. 그래도 모르겠으면 → 사용자에게 물어보기. "내 해석이 맞는지 확인" 이 "틀린 구현" 보다 싸다.
