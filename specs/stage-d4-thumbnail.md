# Stage D4 — 썸네일 파이프라인

> 캡처 워커가 세그먼트 종료 시 대표 프레임 jpg 1장을 저장하고, `GET /clips/{id}/thumbnail` 로 내려주도록 한다. 앱 클립 피드 화면(F4)의 전제 조건.

**상태:** ✅ 완료 (2026-04-22)
**작성:** 2026-04-22
**연관 SOT:** `../../tera-ai-product-master/docs/specs/petcam-backend-dev.md` — Stage D 썸네일 결정
**연관 로드맵:** [`stage-d-roadmap.md`](stage-d-roadmap.md) — 결정 2 (A 안: 캡처 시 jpg 저장)

## 1. 목적

- **사용자 가치**: 클립 목록에서 썸네일 보이면 원하는 장면 찾기 쉬움. 지금은 파일명/시각/duration 만 있어서 내용 미추정.
- **학습 목표**: `cv2.imwrite` + jpg quality/encoding 파라미터, FastAPI `FileResponse` + `media_type`, DB 컬럼 nullable 마이그레이션 실전.
- **오늘의 백엔드 E2E 완성**: "카메라 등록 → 녹화 → 썸네일 → 클립 목록 → 개별 재생" 전 흐름이 curl 로 검증 가능.

## 2. 스코프

### In (이번 스펙에서 한다)

- `camera_clips.thumbnail_path TEXT NULL` 컬럼 추가 마이그레이션
- `backend/capture.py` 세그먼트 종료 시 jpg 저장
  - **motion 클립**: motion 이 시작된 프레임 저장 (캡처 워커가 갖고 있는 motion start frame)
  - **idle 클립**: 세그먼트 중간(30초 지점 근처) 프레임 저장
  - 경로: `storage/clips/{mp4_basename}.jpg` (mp4 와 이름 쌍)
- `backend/supabase_client.py` insert payload 에 `thumbnail_path` 포함
- `backend/pending_inserts.py` 재시도 큐에도 `thumbnail_path` 반영
- `backend/routers/clips.py` 에 `GET /clips/{id}/thumbnail` 추가
  - `FileResponse` + `media_type="image/jpeg"`
  - 파일 없거나 `thumbnail_path` null → 404
- `tests/test_thumbnail_capture.py` — 캡처 워커 단위 (fake frame → imwrite 호출 검증)
- `tests/test_thumbnail_api.py` — `/clips/{id}/thumbnail` 라우터 단위 (tmp jpg + FakeSupabase)
- 실기 검증: 실제 카메라로 클립 2~3개 쌓고 curl 로 썸네일/영상 둘 다 내려받기

### Out (이번 스펙에서 안 한다)

- **기존 클립 역생성** — null 로 둠. 과거 클립은 앱에서 placeholder 표시.
- **썸네일 해상도 별도 설정** — 일단 원본 프레임 크기 그대로 jpg. 용량/속도 이슈 생기면 D4-B 로 재축소.
- **Supabase Storage 업로드** — 디스크 직저장. CDN 는 상용 단계 재검토 (로드맵 결정 2 대안 D).
- **다중 캡처 워커** — D3 범위. 지금은 1대 카메라 기준 동작 확인.
- **재시도 시 썸네일도 재생성** — mp4 insert 만 재시도. 썸네일은 mp4 저장과 동시에 1회만 저장.
- **`GET /clips/{id}/thumbnail` 404 시 placeholder 이미지 리턴** — 404 그대로 반환, 앱이 자체 placeholder 씀.

> **스코프 변경은 합의 후에만.**

## 3. 완료 조건

- [x] Supabase `camera_clips.thumbnail_path TEXT NULL` 마이그레이션 적용 + `information_schema` 로 재확인
- [x] `backend/capture.py` motion/idle 클립 각각 jpg 저장 — 단위 테스트로 `cv2.imwrite` 호출 + 경로 매칭 검증
- [x] `backend/supabase_client.py` / `backend/pending_inserts.py` insert payload 에 `thumbnail_path` 포함 — 기존 테스트 갱신 + 신규 assertion
- [x] `GET /clips/{id}/thumbnail` — 200 jpg 바이트 반환, 404 경로 (row 없음 / thumbnail_path null / 파일 없음) 3가지 분기 테스트
- [x] `pytest -q tests/test_thumbnail_capture.py tests/test_clips_api.py` 전체 통과 (thumbnail API 는 `test_clips_api.py` 에 통합)
- [x] 기존 모든 테스트 (`pytest -q`) 전수 통과 — 회귀 없음 (122 tests passed)
- [x] 실기 검증: 실제 카메라로 녹화 → DB 에 `thumbnail_path` 있는 row 확인 → `curl GET /clips/{id}/thumbnail -o thumb.jpg` → Preview 로 도마뱀 이미지 확인
- [x] 실기 검증: `curl GET /clips/{id}/file -H "Range: bytes=0-1000000" -o clip.mp4` 로 mp4 1MB 다운로드 + 206 Partial Content 확인
- [x] README.md Stage D4 섹션 추가 (엔드포인트 1개 + curl 예시)
- [x] `specs/README.md` 목록 표 갱신 (D4 → ✅)
- [x] `specs/stage-d-roadmap.md` 서브 스테이지 표 갱신 (D4 → ✅)
- [x] `.claude/donts-audit.md` 한 줄 추가

## 4. 설계 메모

- **선택한 방법 (캡처 시 jpg 저장)**: 캡처 워커가 어차피 프레임 버퍼 갖고 있으니 `cv2.imwrite` 한 줄이면 끝. CPU/디스크 비용 최소.
- **고려했던 대안**: (로드맵 결정 2 참고) B 요청 시 즉석 생성, C 썸네일 없음, D Supabase Storage. A 가 구현 비용·응답 속도 둘 다 최적.
- **대표 프레임 선택 로직**:
  - **motion 클립** — motion 이 탐지된 **시작 프레임** 이 가장 유용 (뭐가 움직였는지). 이미 `backend/motion.py` 가 알고 있음 → 캡처 워커가 motion start 콜백에서 프레임 캐시.
  - **idle 클립** — 특별한 사건 없으니 **세그먼트 중간(약 30초)** 프레임. 60초 고정 가정하고 frame count ≈ fps * 30 지점 저장.
- **파일명 규칙**: mp4 와 **동일 basename + .jpg 확장자**. 예: `20260422_154300_motion.mp4` ↔ `20260422_154300_motion.jpg`.
  - 이점: 파일명만 봐도 짝 파악 가능, 마이그레이션 시 mp4 경로에서 썸네일 경로 유추 쉬움, `thumbnail_path` 컬럼 null 이어도 `{mp4}.jpg` 시도 fallback 가능 (하지만 MVP 에선 DB 값만 신뢰).
- **이미지 포맷**: jpg quality=85 (cv2 기본). png 는 용량 큼.
- **404 분기 3종**: row 없음 / `thumbnail_path` null (기존 클립) / 파일 디스크 없음. 셋 다 404 로 통일 + 다른 detail 메시지.
- **기존 구조와의 관계**:
  - `backend/capture.py` `_finalize_segment` (또는 유사 함수) 말미에 jpg 저장 추가 — 기존 로직 건드리지 않음.
  - `backend/supabase_client.py` `insert_clip_metadata` payload dict 확장 — 기존 타입 시그니처 조금 변경.
  - `pending_inserts` 는 payload dict 통째로 직렬화하므로 thumbnail_path 자동 포함.
  - `GET /clips/{id}` 응답의 `ClipOut` Pydantic 모델에 `thumbnail_path: str | None` 추가 → 목록/단건 조회에서 앱이 경로 알 수 있음.

### 리스크 / 미해결 질문

- **motion start frame 캐시 방법** — `capture.py` 의 motion detector 가 frame 포인터를 공유하나? 프레임 복사 없이 저장 가능한지 확인 필요 (OpenCV numpy view vs copy).
- **idle 클립 fps 가정** — fps 는 소스마다 다름 (Tapo ~13.6 fps). 실제 fps 로 계산하거나, time 기반 "절반 지점" 로직으로 전환할지 판단.
- **avc1 세그먼트 roll-over 시 썸네일 타이밍** — 기존 padding 로직 타는 세그먼트도 jpg 저장 누락 안 되게 주의. roll-over 직전 프레임 저장 보장.
- **디스크 cleanup** — motion 유지 정책 (30일?) 에 썸네일도 동반 삭제 필요. 이번 스펙 Out, Stage E retention job 과제.

## 5. 학습 노트

- **`cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])`** — 동기 I/O. 캡처 루프 안에서 호출 시 짧은 블로킹(~5ms @ 640x360). async 핸들러가 아닌 캡처 워커 스레드라서 영향 미미.
- **`FileResponse(path, media_type="image/jpeg")`** — FastAPI 가 파일 stat → Content-Length 자동 설정 + aiofiles 로 비동기 read. Stage C 에서 `StreamingResponse` 로 mp4 직접 제너레이터 만든 것과 다른 접근. 이미지는 Range 필요 없으니 FileResponse 로 충분.
- **DB nullable 마이그레이션** — `ALTER TABLE ... ADD COLUMN thumbnail_path TEXT NULL` 은 즉시 완료 (기존 row 전부 NULL 초기값). PostgreSQL 11+ 는 DEFAULT 있는 ADD COLUMN 도 metadata-only. 대형 테이블 주의점은 MVP 에선 고려 불필요.
- **Pydantic `Optional` vs `str | None`** — v2 에서 `str | None` 권장 (Python 3.10+ 타입 표기). `None` 이 default 일 때 앱 쪽은 JSON `null` 로 받음.
- **썸네일 파일 경로 표기**: DB 엔 `storage/clips/xxx.jpg` (REPO_ROOT 상대), 디스크 접근 시 `REPO_ROOT / path` 로 조립. Stage C `_resolve_clip_path` 유틸 동일 패턴 재사용.

## 6. 참고

- 로드맵: [`stage-d-roadmap.md`](stage-d-roadmap.md) 결정 2 (썸네일 A 안), 4 (디스크 cleanup 은 Stage E)
- Stage C: [`stage-c-db-api.md`](stage-c-db-api.md) — `ClipOut` 모델 확장 대상
- Stage B: [`stage-b-motion-detect.md`](stage-b-motion-detect.md) — motion start 프레임 캐시 지점
- OpenCV imwrite 공식: https://docs.opencv.org/4.x/d4/da8/group__imgcodecs.html#ga8ac397bd09e48851665edbe12aa28f25
- FastAPI FileResponse: https://fastapi.tiangolo.com/advanced/custom-response/#fileresponse
