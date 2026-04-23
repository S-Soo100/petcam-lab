# feature — 문서 리프레시 (외부 독자 관점 재정비)

> 외부 개발자 / 다른 AI 에이전트 / 미래의 나 누구든 이 레포 열면 "뭐 하는 놈인지 + 어떻게 구성됐는지 + 어디부터 읽어야 하는지" 를 15분 안에 파악할 수 있게 문서 레이어 정비.

**상태:** ✅ 완료 (2026-04-22)
**작성:** 2026-04-22
**연관 SOT:** 없음 (레포 내부 문서 개편. 제품 기획 변경 아님.)

## 1. 목적

Stage D5 배포 마무리 + QA 미러 인프라 완성 시점에 기술 문서가 `README.md` 21KB 단일 파일 + 스펙 파편 + 학습 노트 산재 상태. 새로 들어오는 외부 개발자/AI 가 "이 레포 무엇/왜/어떻게" 를 한눈에 읽을 수 있는 진입점이 없음.

- **독자 1** — 신규 개발자: "이 레포 뭐 하는 놈? 로컬에서 어떻게 돌려?"
- **독자 2** — AI 에이전트 (Claude 외 Codex/Cursor/Gemini): "새로 들어와서 맥락 어떻게 잡지?"
- **독자 3** — 검토자/기획자: "백엔드에 어떤 기능들이 있고, 결정 이력은?"
- **독자 4** — 미래의 나: "3개월 뒤에 왜 이렇게 짰지?"

지금은 4 종류 다 `README.md` 하나에 묶여 있어 독자별 진입이 애매함.

## 2. 스코프

### In

**Phase 1 — 핵심 뼈대**
1. `README.md` 슬림화 (21KB → ~6KB) — 1분 요약 + 퀵스타트 + 문서 지도. 상세는 `docs/` 로 이관.
2. `docs/ARCHITECTURE.md` — 시스템 맵 + `backend/` 모듈 관계 + 데이터 흐름 + 동시성 모델 (ASCII 다이어그램).
3. `docs/FEATURES.md` — 기능 9개 단위 정리 (캡처/모션/세그먼트/썸네일/클립DB/카메라CRUD/인증/배포/QA미러).
4. `AGENTS.md` (레포 루트) — AI 에이전트 공통 진입점. 반말 유지 (CLAUDE.md 와 톤 통일).

**Phase 2 — 보강**
5. `docs/API.md` — 엔드포인트별 요청/응답/상태코드/인증 요구 (Swagger 없이도 OK).
6. `docs/DATABASE.md` — `cameras` / `camera_clips` / `pets` / `clip_mirrors` 스키마 + RLS + 마이그레이션 이력 + ERD ASCII.
7. `docs/DEPLOYMENT.md` — Cloudflare Tunnel 운영 + 서버 기동/종료 체크리스트 + 트러블슈팅.
8. `docs/ENV.md` — 환경변수 전체 표 + 민감도 분류 + 필수/선택/기본값.
9. `docs/CONTRIBUTING.md` — 코드 읽는 순서 + 테스트 규칙 + 커밋 컨벤션 + donts 시스템 설명.
10. `docs/GLOSSARY.md` — 게코/세그먼트/모션/미러/펜딩큐/CFR/AUTH_MODE 등 용어집.

**구조 정리**
- 기존 `docs/*-learning.md` + `docs/flutter-handoff*.md` (총 5개) → `docs/learning/` 서브폴더로 이동.
- 해당 파일들을 참조하는 `specs/*.md` (5개) 의 링크 경로 갱신.
- `specs/README.md` 목록 표에 이 스펙 추가.
- `specs/next-session.md` 갱신 — Phase 1/2 완료 반영 + Stage E 킥오프 항목 유지.

### Out (이번 스펙에서 **안 한다**)
- ERD 이미지 (SVG/PNG) 생성 — ASCII 만. 유지보수 부담.
- API 문서를 OpenAPI 스펙 파일로 생성 (Swagger `/docs` 자동 생성으로 충분).
- 기여 자동화 (lint/pre-commit/CI) — 문서 수정 범위 넘음.
- `tera-ai-product-master` SOT 변경 — 이번 작업은 "어떻게 만들었나" 쪽 정리.
- Flutter 레포 문서 갱신.
- 영문 번역.

## 3. 완료 조건

- [x] `README.md` 가 6KB 내외로 줄어들고 1분 요약 + 퀵스타트 + 문서 지도만 남음
- [x] `docs/ARCHITECTURE.md` 생성 — 시스템 맵 ASCII + 모듈 관계 + 동시성 모델
- [x] `docs/FEATURES.md` 생성 — 기능 9개 단위 (각 기능당 "무엇/왜/어디 코드/관련 스펙")
- [x] `AGENTS.md` 생성 — AI 에이전트 읽기 순서 + 반말 톤 유지
- [x] `docs/API.md` 생성 — 13개 엔드포인트 전부 포함 (clips 4 + cameras 6 + 루트/health/status 3)
- [x] `docs/DATABASE.md` 생성 — 테이블 4개 + RLS + 마이그레이션 이력
- [x] `docs/DEPLOYMENT.md` 생성 — Cloudflare Tunnel 운영 가이드
- [x] `docs/ENV.md` 생성 — 환경변수 전체 표
- [x] `docs/CONTRIBUTING.md` 생성 — 코드 읽기 순서 + 테스트 + 커밋 컨벤션
- [x] `docs/GLOSSARY.md` 생성 — 용어집
- [x] `docs/learning/` 서브폴더 생성 + 기존 learning 노트 5개 이동
- [x] 이동한 파일 참조하는 `specs/*.md` 링크 전부 갱신 (Grep 으로 검증)
- [x] `specs/README.md` 목록에 이 스펙 추가
- [x] `specs/next-session.md` 갱신
- [x] `pytest` 여전히 134 통과 (문서만 고쳤으므로 영향 없어야)

## 4. 설계 메모

### 왜 독자별 문서를 쪼개는가
`README.md` 단일 파일로 "모든 맥락" 을 담으면 길이가 커지고, 신규 개발자는 절반만 읽고 떠나고, AI 에이전트는 토큰 예산을 무관한 섹션에 낭비. 독자별 진입 파일을 쪼개되 **서로 중복되지 않게** 링크로 연결.

### 왜 `docs/` 폴더를 "공식/학습" 2층으로 나누나
기존 `docs/*-learning.md` 는 Stage 진행 당시의 학습 노트 — Claude/개발자가 쓴 **과정 기록**. 공식 아키텍처/API 레퍼런스와 톤·목적이 달라서 섞여 있으면 검색·유지보수 모두 애매. `docs/learning/` 서브로 분리하면 "공식 문서 폴더는 안정, 학습 폴더는 stage 마다 추가" 로 수명 주기가 다름을 명시.

### 왜 `AGENTS.md` 를 루트에 두나
Claude 는 `CLAUDE.md` 를 자동 로드하지만, Codex/Cursor/Gemini 는 관례가 다름. 일부는 `AGENTS.md` 또는 `.cursorrules` 를 읽음. 공통 진입점 하나를 루트에 두고, 각 툴용 링크는 거기서 파생시키는 게 유지보수 단순.

### 왜 반말 톤 유지
`CLAUDE.md` + 사용자 대화 전반이 반말. AGENTS.md 만 중립 톤으로 두면 Claude 가 AGENTS 를 읽고 문체 전염되는 사례 발생 (donts-audit 에 전례 없지만 예방 차원). 통일.

### Phase 1 / 2 쪼개는 이유
Phase 1(4개) 이 당장 효용 크고 서로 상호 참조. Phase 2(6개) 는 각각 독립이라 한 번에 몰아도 되고 쪼개도 됨. 이번 세션에 Phase 1 → Phase 2 순으로 진행, 각 Phase 끝에 커밋 분리 가능.

### 리스크
- **문서 이동 시 링크 깨짐**: `docs/*-learning.md` 가 5 파일에서 참조됨. 이동 후 Grep 으로 검증.
- **중복 누적**: `README.md` 에 있던 내용을 다 `docs/` 로 옮길 때 README 가 너무 얇아지거나 반대로 중복 남김. 기준 — README 는 "1분 파악 + 링크 지도" 만.

## 5. 학습 노트

- **AGENTS.md 관례** — OpenAI Codex 가 "AGENTS.md" 를 에이전트 공용 메타 파일로 제안. Cursor 는 `.cursorrules`. 공통 루트 진입점을 두고 각 툴 파일에서 그걸 include 하게 하는 게 깔끔.
- **문서 정보 아키텍처 (IA)** — "독자별 진입점 / 독자 간 교차 참조 / 단일 소스" 3원칙. 같은 정보를 두 곳에 쓰지 말고, 한 곳에 두고 링크.
- **MkDocs / Docusaurus 안 쓰는 이유** — 정적 사이트 빌더는 오버스펙. GitHub 가 md 렌더링 잘함 + 개발자가 에디터에서 직접 읽음. 추후 필요해지면 도입.

## 6. 참고

- 관련 스펙: [next-session.md](next-session.md) — 작업 완료 후 Phase 2 진행 후보 / Stage E 킥오프 링크 갱신
- 외부 자료:
  - [Diátaxis Framework](https://diataxis.fr/) — 튜토리얼 / how-to / 레퍼런스 / 설명 4분법. Features/API/Architecture 구분에 참고.
  - OpenAI AGENTS.md 관례 (2025 초반 제안, 공식 스펙 없음)
