# 다음 세션 시작 지점

> 매 세션 마지막에 갱신. 다음 세션 초입에 먼저 읽는다.
> **최종 갱신:** 2026-04-22 (Opus 4.7, docs refresh 마무리 후)

## ✅ 직전 세션 산출 — 문서 리프레시 완료

외부 개발자/AI 에이전트/미래의 나 누구나 15분 안에 "뭐 하는 레포/어떻게 구성/어디부터 읽을지" 파악하도록 문서 레이어 전면 정비.

- **결과물:** `README.md` 슬림 + `docs/` 공식 레퍼런스 10개 (ARCHITECTURE / FEATURES / API / DATABASE / DEPLOYMENT / ENV / CONTRIBUTING / GLOSSARY + learning 5개 이동) + 루트 `AGENTS.md` (AI 에이전트 공통 진입점, 반말 톤).
- **체크박스:** 14개 전부 ✅. pytest 134 유지 (문서만 수정).
- 상세: [feature-docs-refresh.md](feature-docs-refresh.md)

## 📌 바로 할 일 — Flutter dlqudan12 E2E (아직 미검증)

네(사용자)가 직접 해야 마무리되는 검증. 다음 세션 때 이미 끝났을 수도 있음.

- **무엇:** `tera-ai-flutter` 앱에서 **`dlqudan12@gmail.com`** 계정으로 로그인 → 홈에 펫 2개 (미러된 것) 표시 → 클립 피드에 썸네일 → 영상 재생 정상.
- **배경:** 오너 계정(`bss.rol20@gmail.com`)의 `cam1 / cam2` 클립을 QA 테스터 계정이 동일하게 보도록 `clip_mirrors` 인프라 구축 완료 (2026-04-22 커밋 `2d8df29`).
- **이슈 발견 시:** 다음 세션에서 버그 리포트부터. 오너 계정은 멀쩡한데 QA 계정만 이상하면 `backend/clip_recorder.py` 의 `_mirror_clip` 경로 의심.

상세: [feature-clip-mirrors-for-qa.md](feature-clip-mirrors-for-qa.md)

## 🧭 방향 결정 필요 — 다음 스테이지 (3 후보)

### 1. ⭐ Stage E 스펙 킥오프 (추천)

CLAUDE.md 에 "E: 온디바이스 필터링" 언급됨. 실제 스코프는 아직 미확정.

- **먼저:** `../tera-ai-product-master/docs/specs/petcam-b2c.md` 읽고 온디바이스 필터링이 뭘 뜻하는지 SOT 확인
- **다음:** `specs/stage-e-*.md` 스코프 + 완료 조건만 먼저 작성 → 사용자 확인 후 착수
- **왜 추천:** D 시리즈 마무리된 지금이 방향 결정하기 좋음. 합의만 해두면 다음 세션에 바로 구현.
- **예상 소요:** 스펙 합의 1 세션 + 구현은 스펙 확정 후 분할

### 2. 오픈 이슈 소화

[stage-d-roadmap.md](stage-d-roadmap.md) 섹션 8 참조. 하루 이내 끝낼 소규모 작업들.

- 카메라 삭제 시 영상 파일 cleanup 전략 (즉시 / soft-delete / GC)
- 캡처 워커 동적 추가·제거 시 진행 중 녹화 처리
- Flutter `/health` ping → "서버 대기 중" 화면 (tera-ai-flutter 레포)

### 3. Flutter 쪽 정비

petcam-lab 엔 영향 없음. `tera-ai-flutter` 레포 작업.
- 로그인 실패 UX 개선
- 클립 피드 무한 스크롤 edge case
- 재생 중 JWT 만료 처리

## 🗂️ 현재 시스템 상태 스냅샷 (2026-04-22)

- **Backend:** `api.tera-ai.uk` 공개 중 (Cloudflare Named Tunnel). 실행은 로컬 노트북 수동 (`uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000`).
- **Auth:** `AUTH_MODE=prod`, Supabase JWT 검증 (ES256).
- **카메라:** cam1 / cam2 (오너 bss.rol20 소유) + cam1-mirror / cam2-mirror (QA dlqudan12 소유, dummy RTSP).
- **클립 카운트:** 양 계정 정확히 동일 동기화 (2026-04-22 커밋 시점 396 clips, 이후 live + flush 양쪽 훅으로 자동 유지).
- **Tests:** 134 passing (`uv run pytest`).
- **Stage 진행:** A ✅ / B ✅ / C ✅ / D1~D5 ✅ / E 🆕.

## 📂 맥락 복원 — 읽을 파일 (우선순위)

새 세션이 맥락 없이 들어왔을 때 이 순서로 읽으면 복원됨:

1. [../README.md](../README.md) — 1분 요약 + 퀵스타트 + 문서 지도 (슬림)
2. [../AGENTS.md](../AGENTS.md) — AI 에이전트 공통 진입점
3. [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) — 시스템 맵 + 모듈 관계 + 동시성 모델
4. [../docs/FEATURES.md](../docs/FEATURES.md) — 기능 9개 단위 정리
5. [README.md](README.md) — spec 운영 규칙 + 전체 스펙 목록
6. 이 파일 — 오늘의 시작 지점
7. [stage-d-roadmap.md](stage-d-roadmap.md) — Stage D 전체 결정 이력 + 오픈 이슈
8. [feature-clip-mirrors-for-qa.md](feature-clip-mirrors-for-qa.md) — 직전 QA 미러 작업 상세
9. `/Users/baek/petcam-lab/CLAUDE.md` — 페르소나 + Stage 로드맵 개요
10. `../tera-ai-product-master/docs/specs/petcam-b2c.md` — 제품 SOT (Stage E 스펙 킥오프 시)

## 💬 사용자가 "뭐부터 해야해?" 물으면

1. 즉시 할 일 (Flutter E2E) 상태부터 물어본다 — 했는지 / 버그 있었는지
2. 결과 따라 세 후보 중 제시 — 사용자 추천 1번 (Stage E)
3. 사용자 결정 후 관련 스펙 파일 열어서 진행
