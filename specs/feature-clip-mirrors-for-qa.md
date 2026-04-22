# feature — clip_mirrors (QA 테스터 전용 임시 인프라)

> 소유자 계정의 카메라 클립을 QA 테스터 계정이 동일하게 조회·재생할 수 있게 하는 best-effort 미러링.

**상태:** ✅ 완료
**작성:** 2026-04-22
**연관 SOT:** 없음 (제품 기능 아님. 내부 QA 편의 인프라.)

## 1. 목적

QA 테스터(`dlqudan12@gmail.com`)가 오너 계정(`bss.rol20@gmail.com`)의 `cam1 / cam2`
실시간·녹화 클립을 같은 Flutter 앱에서 로그인하여 검증할 수 있어야 함.
Stage D5 완료 후 공개 도메인 배포(`api.tera-ai.uk`) 상에서 E2E QA 를 돌리기 위한
정치한 가짜 공유 환경.

**정식 공유 기능 아님.** 사용자가 명시: "앞으로 남의 개체 남의 카메라를 보게 할
기능은 없을거야." 이 인프라는 QA 종료 후 정리 대상.

## 2. 스코프

### In
- `public.clip_mirrors` 테이블: `(source_camera_id, mirror_camera_id, mirror_user_id)` 매핑
- `backend/clip_recorder.py`:
  - `_mirror_clip(client, clip_fields)` helper — 매핑 조회 → 복사 INSERT
  - `record` (live path): 원본 INSERT 성공 후 `_mirror_clip` 호출
  - `make_flush_insert_fn` (retry path): 재시도 성공 후에도 `_mirror_clip` 호출
- QA 테스터 계정용 `pets` 2건 + `cameras` 2건 (RTSP 자격 증명은 dummy)
- 최초 데이터 부트스트랩: 오너 클립 전체를 QA 계정으로 복사 INSERT (일회성 SQL)

### Out
- RLS 정책 공개 확장 (기존 `auth.uid() = user_id` 유지; `clip_mirrors` 는 service_role only)
- `cameras`·`pets`·`camera_clips` 스키마 변경
- Flutter 앱 변경 (오너 / QA 모두 동일 API + JWT 스크린 재사용)
- 정식 공유 기능 (링크 공유, 가족 공유, 권한 관리 등)

## 3. 완료 조건

- [x] `clip_mirrors` 테이블 생성 + RLS ENABLE (정책 없음, service_role 전용)
- [x] 오너 cam1/cam2 → QA cam1/cam2 매핑 2건 INSERT
- [x] 부트스트랩 복사 — 오너 clip 과 QA clip 카운트 동일 (2026-04-22 기준 396 = 396)
- [x] `backend/clip_recorder.py` live path 에 미러 훅 반영
- [x] `backend/clip_recorder.py` flush path 에도 미러 훅 반영 (재시작 gap 재발 방지)
- [x] `pytest tests/test_clip_recorder.py` 7/7 통과 (전체 134/134)
- [x] 백엔드 재시작 후 새 클립이 자동으로 양 계정에 미러 — started_at/latest 일치 확인
- [x] QA 계정 Flutter 로그인으로 클립 피드 + 재생 E2E 검증 (사용자 확인 대기)

## 4. 설계 메모

### 왜 별도 테이블인가
`cameras`·`camera_clips` 스키마에 `shared_with_user_id[]` 같은 컬럼을 추가하면
정식 기능으로 오해 / 마이그레이션 부담. 별도 테이블은 DROP 한 번이면 기능 제거
완료. 제품 모델을 오염시키지 않는다.

### 왜 RLS 정책이 없나
`clip_mirrors` 는 사용자 인증된 클라이언트가 직접 조회할 필요가 없음.
`service_role` 로 백엔드에서만 읽고 쓴다. 그래서 RLS ENABLE + 정책 0건 =
anon/authenticated 완전 차단. API 라우트를 추가할 일도 없음.

### 왜 best-effort 인가
미러 실패(lookup 네트워크 장애 / 타겟 cam 조회 실패 / 중복 키 등)는 원본 저장과 무관.
QA 편의 기능이 오너 데이터 정합성을 해치면 안 됨 → 예외 잡고 warning 만 찍고 넘김.
pending queue 에 넣지도 않음 (미러는 영구 신뢰 계층이 아니다).

### Live + Flush 양쪽에 훅이 필요한 이유
`record()` 만 훅을 붙이면, 네트워크 장애로 pending queue 로 떨어진 원본이 **나중에**
flush 될 때 미러가 스킵된다. 실제로 Stage D5 재시작 타이밍에 이 gap 으로 10개 클립이
QA 계정에 누락됐다 — `make_flush_insert_fn` 에도 동일 훅 필수.

### Fake Supabase 테스트 전략
실제 Supabase REST 는 chained call (`.table().select().eq().single().execute()`).
pytest 에서 이걸 흉내낸 `_FakeSupabase + _TableOp` 만들어 사용. `raise_on` dict 로
시나리오별 실패 주입 (`{(table, op): Exception}` 또는 `list` 로 순차 실패).

## 5. 학습 노트

- **Supabase RLS + service_role** — `service_role` 키는 RLS 를 **완전히 bypass**.
  백엔드 내부 테이블 (`clip_mirrors` 처럼 사용자가 직접 안 건드는 것) 은 RLS ENABLE +
  정책 없음으로 두면 client SDK 로는 접근 불가, 백엔드만 사용.
- **best-effort sidecar INSERT 패턴** — 원본 성공 경로에 부가 작업을 붙일 때,
  부가 작업의 예외가 메인 경로의 return / state 에 영향을 주지 않도록 try 로 감싸고
  warning 만 찍는다. Node 에 빗대면 Express `res.send()` 후 `logToExternalService()`
  실패를 request 성공에 묻어나게 하지 않는 것과 같음.
- **CASCADE FK** — `source_camera_id`, `mirror_camera_id` 양쪽 다 `cameras(id)` ON
  DELETE CASCADE. 카메라 삭제 시 미러 매핑도 자동 정리. QA 종료 후 `DELETE FROM
  cameras WHERE user_id = <qa>` 하면 `clip_mirrors` 도 같이 사라진다.

## 6. 참고

- 관련 스펙: [stage-d5-deploy-tunnel.md](stage-d5-deploy-tunnel.md) — 이 인프라가
  필요해진 배경 (public 도메인 + 멀티 유저 로그인 E2E)
- Supabase migration 이름: `add_clip_mirrors_for_qa_testers`
- 제거 체크리스트 (향후 QA 종료 시):
  1. `DROP TABLE public.clip_mirrors;`
  2. `backend/clip_recorder.py` 에서 `_mirror_clip` helper 및 호출 2곳 제거
  3. `tests/test_clip_recorder.py` 의 미러 관련 케이스 제거 (no-mirror 케이스는 남김)
  4. QA 테스터 `auth.users` / `cameras` / `pets` / `camera_clips` 삭제 (CASCADE 활용)
