# Don'ts 실전 검증 로그 — petcam-lab

> 목적: `.claude/rules/donts.md` 및 `donts/python.md`가 실제 작업에서 얼마나 작동하는지 누적 추적.
> 운영 시작: 2026-04-17
> 회고: 로그 20줄 쌓일 때마다 또는 월 1회 중 먼저 도래하는 시점.
> 연관: `tera-ai-product-master/.claude/donts-audit.md` (메인 프로젝트 운영 로그)

---

## 기록 방법

Standard 이상 트랙 작업 종료 시 메인 Claude가 아래 한 줄을 추가한다.

```
YYYY-MM-DD {기능} | 작업: {한줄요약} | 참조: {donts 항목} | 지킴: {번호} | 놓침: {번호+이유} | 재발: {있으면 기록} | 메모: {애매했던 점}
```

**필드 설명**
- **기능**: 제너럴 / python / fastapi / opencv / uv / 기타
- **참조**: 이번 작업에서 의식적으로 읽은 donts 항목 (예: `python#4,7` 또는 `general#2,3`)
- **지킴**: 실제로 지킨 항목
- **놓침**: 위반했거나 잊은 항목 + 이유 (없으면 `-`)
- **재발**: 기존 feedback 메모리에 있거나 과거 실수 패턴이 또 나왔나? (없으면 `-`)
- **메모**: 룰이 애매했거나, 새로 추가해야 할 패턴 (없으면 생략)

## 🔁 Three-Strike Rule 추적

새 실수 패턴은 아래 단계로 추적한다. 상세 기준은 [`rules/donts.md`](rules/donts.md) 상단 표 참조.

| 상태 | 기준 | 저장 위치 |
|------|------|----------|
| 1회 | 처음 발생 | `~/.claude/projects/-Users-baek-petcam-lab/memory/feedback_*.md` |
| 2회 | 재발 | 이 파일의 "승격 후보" 섹션 |
| 3회 | 세 번째 | `rules/donts.md` 또는 `rules/donts/python.md`에 정식 룰 |

## 🏷️ 승격 후보 (2회째 발생한 패턴)

_아직 없음._

## 📋 작업 로그

2026-04-18 opencv/rtsp | 작업: Stage A 재시도 로직 + Tapo C200 스모크 테스트 성공 | 참조: general#1,3,5 python#? | 지킴: general#3 (추측 전 ping/nc/ffprobe로 3단 진단), general#1 (cap.release 동작 직접 확인 후 설명) | 놓침: - | 재발: - | 메모: **macOS Local Network Permission** 처음 조우. 증상 = "No route to host" (ping/nc OK인데 ffmpeg/python만 차단). 시스템 바이너리는 통과, brew/uv 설치 바이너리는 차단. **새 규칙 후보**: RTSP/로컬 네트워크 접근 실패 시 "시스템 설정 → 로컬 네트워크 → VSCode/Terminal ON" 을 1차 체크리스트에 넣어야. Tapo 프로비저닝 가이드 작성 시 명시 필요.

2026-04-21 fastapi/supabase | 작업: Stage C 완료 — camera_clips DB + /clips API 3종 + 재시도 큐 + 단위 30개/E2E 1개 | 참조: general#1,2,11 python#4,5,6,11,13 | 지킴: python#5 (StreamingResponse + `_iter_file` 제너레이터, Range 206), python#6 (`get_supabase_client`/`get_dev_user_id` Depends → 테스트에서 override), python#11 (REPO_ROOT 기준 절대경로), python#13 (FakeSupabase + tmp_path 더미 mp4, 실 Supabase/RTSP 의존 X), general#11 (supabase_client.py 에 placeholder 가드 + .env 만 실키), general#1 (apply_migration 후 information_schema 로 컬럼/FK/인덱스/정책 각각 재확인) | 놓침: - | 재발: - | 메모: supabase-py `.table().select().eq().order().limit().execute()` 체인을 mock 으로 흉내낼 때 unittest.mock 보다 **filter 로직 그대로 적용하는 in-memory fake** 가 훨씬 간결 (21개 테스트 작성 비용 대폭 감소). Stage D 에서 JWT 검증용 override 도 동일 패턴 재사용 예정.

2026-04-22 fastapi/auth | 작업: Stage D1 완료 — JWT 검증(`backend/auth.py`) + Fernet 래퍼(`backend/crypto.py`) + Dev/Prod 분기 + 테스트 32개(auth 15 + crypto 17) | 참조: general#1,2,11 python#6 | 지킴: python#6 (`get_current_user_id` 를 Depends 로, test 에서 `dependency_overrides` override), general#11 (.env.example 에 CAMERA_SECRET_KEY placeholder + 실키 커밋 금지), general#1 (pyjwt `jwt.algorithms.RSAAlgorithm.from_jwk` / `get_unverified_header` 시그니처를 Read·공식 문서로 확인 후 사용) | 놓침: - | 재발: - | 메모: **python-dotenv `override=False` 함정 발견** — 테스트에서 `monkeypatch.delenv("DEV_USER_ID")` 해도 `_dev_user_id()` 내부 `load_dotenv(...)` 가 실제 .env 에서 다시 로드해버림. 해결: `monkeypatch.setenv("DEV_USER_ID", "")` 로 빈 문자열 설정 → `override=False` 가 기존 값(빈 문자열) 유지 → `.strip() + not value` 가드 트리거. 테스트에 주석 남김. JWKS TTL 캐시는 `@lru_cache` 대신 **module-global dict + `time.monotonic()`** 으로 구현 (lru_cache 는 TTL 불가). Fernet I/O 는 spec 의 bytes 대신 **str** 로 변경 — DB TEXT 컬럼 + JSON 응답 직렬화 편의 우선.

2026-04-22 fastapi/opencv | 작업: Stage D2 완료 — `cameras` 테이블 + CRUD API 6종(`backend/routers/cameras.py`) + RTSP 테스트 연결(`backend/rtsp_probe.py`) + 테스트 38개(rtsp_probe 13 + cameras_api 25) | 참조: general#1,7,11 python#4,6,7,11,13 | 지킴: python#4 (cv2 블로킹 3초 → 라우터는 **동기 def**, async 금지), python#7 (cv2.VideoCapture try/finally 로 `cap.release()` 보장 → 테스트로 open 실패 시에도 release 호출 검증), python#13 (실 RTSP 금지 → `cv2.VideoCapture` monkeypatch + numpy.zeros 프레임 mock), python#6 (`get_supabase_client`/`get_current_user_id` 전부 Depends → 테스트에서 override), general#7 (services/ 디렉토리 임의 신설 금지 → flat `backend/*.py` 구조 유지 → rtsp_probe.py 를 backend/ 직계에 배치), general#11 (비번 응답 배제를 스키마 레벨로 강제 — `CameraOut` 에 `password_encrypted` **필드 자체 없음** → Pydantic 자동 배제 / `mask_rtsp_url` 로 로그에서 비번 마스킹) | 놓침: - | 재발: - | 메모: **RLS INSERT 정책 고의 생략 패턴** 첫 도입 — SELECT/UPDATE/DELETE 3개만 생성, INSERT 는 service_role 전담. 프론트가 DB 직결로 insert 해서 test-connection 검증·암호화를 우회하는 경로를 구조적으로 차단. Pydantic v2 `model_dump(exclude_unset=True)` 로 PATCH 부분 업데이트 구현 — Prisma `update({data: undefined})` 와 같은 의미. FakeSupabase 확장판 작성 (SELECT 전용 → INSERT/UPDATE/DELETE 지원, unique 제약 모사, updated_at 자동 갱신) — Stage C 의 select-only fake 로는 부족. Test id 를 Pydantic UUID 검증 통과시키려 `uuid.uuid5(NAMESPACE_DNS, 라벨)` 결정적 매핑 헬퍼 추가. Supabase `moddatetime` extension 은 기본 비활성이었음 → migration 에서 `CREATE EXTENSION IF NOT EXISTS` 명시 활성화 필요.

2026-04-22 fastapi/opencv | 작업: Stage D4 완료 — 썸네일 파이프라인(`camera_clips.thumbnail_path` 마이그레이션 + `backend/capture.py` jpg 저장 + `GET /clips/{id}/thumbnail`) + 테스트 12개(thumbnail_capture 7 + clips_api thumbnail 5) + 실기 검증 | 참조: general#1,2 python#4,7,9,11,12,13 | 지킴: python#4 (`cv2.imwrite` 는 동기 I/O — 캡처 워커 스레드에서만 호출, async 핸들러에선 미사용), python#9 (cv2 VideoCapture buffer 재사용 → motion_start/midpoint 프레임 캐시 전에 `.copy()` 필수 — 주석으로 명시), python#11 (`mp4_path.with_suffix(".jpg")` 로 파일명 쌍, 절대 경로 유지), python#12 (storage/clips 하위에만 저장 — 레포 루트에 jpg 흩뿌리지 않음), python#13 (실 RTSP/실 frame 금지 → numpy zeros + BGR 파란색 frame 으로 `_save_thumbnail` 단위 테스트, `_SpyRecorder` 로 `_record_clip` payload 주입 검증 — `_capture_loop` 전체는 mock 체인 비용 > 학습 가치라 skip), general#2 (최소 변경 — `_record_clip` 시그니처에 `thumbnail_path: Optional[Path] = None` 추가만, 기존 payload 키 유지) | 놓침: - | 재발: - | 메모: **세그먼트별 프레임 캐시 리셋 타이밍** 결정 — segment rollover 직후 `motion_start_frame = None; midpoint_frame = None` 으로 초기화. 다음 세그먼트 시작 시점 기준. rollover 경로 **main loop + finally 블록 둘 다** 에 썸네일 저장 로직 중복 배치 (finally 는 서버 종료 시 현재 세그먼트 저장 보장). **`cv2.imwrite` 실패 처리** — `cv2.error`/`OSError` 예외 뿐 아니라 **리턴값 False** 도 체크 (imwrite 는 실패 시 False 리턴, 예외 아님). `_save_thumbnail` 이 None 리턴하면 `_record_clip` 은 `thumbnail_path=None` 으로 호출돼 DB 엔 NULL. **FileResponse vs StreamingResponse** — 이미지는 Range 필요 없으니 `FileResponse(path, media_type="image/jpeg")` 로 간결 처리 (aiofiles 비동기 read + Content-Length 자동). Stage C mp4 `StreamingResponse + _iter_file` 과 대비되는 선택지. **404 3분기 패턴** — row 없음 / `thumbnail_path` NULL / 파일 디스크 없음 — 셋 다 404 통일 + detail 로 원인 구분.

2026-04-22 fastapi/postgres | 작업: Stage D3 완료 — 다중 캡처 워커 + `camera_clips.camera_id` UUID FK 마이그레이션 + `backend/main.py` lifespan 재작성 + `tests/test_main_lifespan.py` 4개 + 실기 cam1+cam2 동시 녹화 | 참조: general#1,2,7,9 python#4,6,13 | 지킴: general#1 (마이그레이션 apply_migration 각 단계 후 `information_schema.columns` + pg_catalog FK 검증 반복), general#2 (`backend/capture.py` / `backend/motion.py` 내부 로직 한 줄도 안 건드림 — `CaptureWorker.camera_id` 의미만 "라벨 문자열" → "UUID 문자열" 로 재해석), general#7 (워커 레지스트리는 신규 매니저 클래스 도입하지 않고 `app.state.capture_workers: dict` 단순 패턴 유지), general#9 (DROP COLUMN 전에 "ADD nullable → UPDATE backfill → SET NOT NULL → DROP → RENAME" 순 준수, rollback 부담 분산), python#4 (async lifespan 안에서 `sb_client.table().execute()` 는 supabase-py 동기 I/O 지만 startup 1회라 허용 — 주석 명시), python#6 (새 헬퍼 `_build_worker_for_camera` 는 생성자 주입 패턴, 전역 싱글톤 X), python#13 (실 RTSP 금지 → `_FakeWorker` + `_FakeSupabase` 로 lifespan 경로 전체 단위 검증) | 놓침: - | 재발: - | 메모: **"ADD → Backfill → Enforce → Rename" 3.5 step 마이그레이션** Postgres 실전 표준 적용 — Stripe 가이드와 동일. 기존 TEXT `camera_id='cam-1'` 106행을 cam1 UUID 로 backfill 후 컬럼 교체. **FastAPI lifespan 의 TestClient `with` 블록 트리거** 처음 사용 — 인스턴스 생성만으론 startup 안 돎, `with TestClient(app) as client:` 필수. **일부 카메라 skip 격리 패턴** — 비번 복호화 실패 시 해당 워커만 skip + `app.state.skipped_cameras` 에 기록, 다른 카메라는 계속. 전체 서버 죽이지 않음 (SaaS 운영에서 배운 "fail one, keep the rest" 원칙). **`from backend.crypto import get_camera_fernet` 선검증** — 모든 워커 공통 Fernet 키라 루프 진입 전 1회 검증 → `CryptoNotConfigured` 면 전체 skip 으로 fail-fast. **CaptureWorker 테스트 mock 은 `__init__` 인자 저장 + start/stop 호출 기록**으로 충분 — `snapshot()` 은 테스트에서 호출 안 하면 구현 생략.

2026-04-22 cloudflare/auth | 작업: Stage D5 배포 — Cloudflare Named Tunnel(`api.tera-ai.uk`) + AUTH_MODE=prod 전환 + `backend/auth.py` ES256 대응 리팩터 + README 배포 섹션 + 127 pytest 전수 통과 (Flutter E2E 대기 중) | 참조: general#1,2,11 python#6,11 | 지킴: general#1 (JWKS 실응답을 `curl ... /.well-known/jwks.json | jq` 로 검증 → `alg: "ES256"` 발견 → 코드가 RS256 하드코딩된 것 확인 후 수정. PyJWT 의 `jwt.PyJWK` API 를 공식 문서로 검증 후 적용), general#2 (auth.py 리팩터는 최소 범위 — `RSAAlgorithm.from_jwk` 한 줄 → `PyJWK(matching_key)` + `pyjwk.algorithm_name` 한 줄 교체. 전체 함수 구조 보존), general#11 (`.env` 의 Supabase 키·Cloudflare credentials 전부 gitignored. `.env.example` 은 placeholder 유지), python#6 (verify_jwt 는 pure function 유지, 환경변수는 호출부에서 주입), python#11 (`~/.cloudflared/config.yml` 은 홈 디렉토리 절대 경로 — 레포 밖이라 `Path(__file__)` 불필요, cloudflared 가 표준 위치 사용) | 놓침: - | 재발: - | 메모: **JWT 알고리즘 하드코딩 함정** — spec/로드맵 주석엔 "RS256" 으로 쓰여 있었고 PyJWT 튜토리얼도 대부분 RS256 예제라 `RSAAlgorithm.from_jwk()` 를 그대로 넣었음. 실 Supabase JWKS 는 ES256/EC-P256. `jwt.PyJWK(jwk_dict)` 는 `kty` 필드 (`EC` vs `RSA`) 보고 알아서 올바른 Algorithm 객체 생성 + `.key` 로 공개키 반환 + `.algorithm_name` 으로 알고리즘 추론. 알고리즘-agnostic 로딩 표준. **테스트 커버리지** — 기존 RS256 fixtures 는 보존 (하위 호환) + ES256 fixtures 신설 (`ec.generate_private_key(ec.SECP256R1())` + `ECAlgorithm.to_jwk`). **lifespan 로그 가시성** — `logger.info("AUTH_MODE=%s", ...)` 가 uvicorn 기본 설정에서 안 보이는 이슈 (커스텀 모듈 INFO 필터됨) → `logger.warning` 으로 상향. 운영 중 prod → dev 실수 회귀 즉시 감지 목적이라 warning 이 맞음. **Cloudflare 도메인 구매 학습** — `.uk` 도메인은 도메인 주체 확인 없이 이메일만으로 등록 가능 (`.kr` 과 달리 개인정보 제출 절차 없음). Registrar 는 Cloudflare 자체가 "wholesale" 요율로 판매 → 갱신 시 인상 없음 (`.com` $9.15/년, `.uk` 약 $5/년). WHOIS privacy 자동 적용. **전환 순서 교훈** — Flutter 쪽 401 인터셉터 완료 전 AUTH_MODE=prod 전환하면 "앱이 갑자기 500/401" 재현. 순서: ① Flutter 준비 확인 → ② Named Tunnel → ③ prod 전환 → ④ curl 검증 → ⑤ Flutter E2E.

2026-04-22 fastapi/postgres | 작업: QA 미러링 인프라 — `clip_mirrors` 테이블(service_role 전용) + `backend/clip_recorder.py` live/flush 양쪽 훅 + 테스트 7개 + 부트스트랩 396=396 동기화 + specs/feature-clip-mirrors-for-qa.md | 참조: general#1,2,7 python#6,13 | 지킴: general#1 (실제 DB 상태를 started_at 기준 SQL 로 확인 후 gap 원인을 "flush path 에 미러 훅 없음"으로 특정 → 추측 수정 금지), general#2 (`cameras`/`camera_clips` 스키마는 한 줄도 안 건드리고 `clip_mirrors` 별도 테이블로 격리. DROP TABLE 하나로 기능 제거 가능), general#7 (API 라우트 · 정식 공유 모델 신설 금지 — RLS policy 0건 + service_role 전용으로 백엔드 내부만 사용), python#6 (`_mirror_clip` 은 client/clip_fields 만 받는 pure function — 싱글톤 / 전역 상태 X → 테스트에서 `_FakeSupabase` 주입으로 lookup/insert 실패 시나리오 각각 검증), python#13 (실 Supabase 금지 → `raise_on: list` 로 "첫 INSERT 성공 + 두 번째 INSERT 실패" 순차 시나리오까지 fake 로 커버) | 놓침: **flush path 미러 훅 초기 누락** — 처음 구현 시 `make_clip_recorder` 의 `record()` 에만 `_mirror_clip` 훅을 넣고 `make_flush_insert_fn` 은 수정 안 함. Stage D5 재시작 타이밍에 pending queue 로 떨어진 원본 10건이 복구되면서 미러가 스킵돼 gap 발생. 프로덕션 검증 SQL 로 gap 발견 후 flush path 에도 훅 추가 + 회귀 테스트 2건 보강. | 재발: - | 메모: **best-effort sidecar 는 모든 경로에 동일하게 걸어야 한다** — "원본 성공" 지점이 여러 곳(live INSERT + retry queue flush) 있을 때 한 곳에만 훅을 걸면 재시작·네트워크 장애 타이밍에 데이터 분기 발생. 다음 best-effort 확장 작업 시 "원본이 저장되는 모든 경로" 를 먼저 나열 후 훅 위치 결정. **재시작 중간 gap 은 일회성 SQL 로 복구** — 미러 훅 버그 수정 후 기존 gap 은 `NOT EXISTS` + JOIN `clip_mirrors` 패턴으로 idempotent 한 catch-up SQL 실행 (재실행해도 중복 INSERT 0). **Python logger INFO 가시성** — `backend.clip_recorder` 의 `logger.info("clip mirrored")` 가 uvicorn 기본 설정에서 안 보임 (커스텀 모듈 INFO 필터). 운영 검증은 DB 카운트 대조로 갈음 — 로그 상향은 과잉이라 보류.

<!-- 예시:
2026-04-20 fastapi | 작업: MJPEG 스트리밍 엔드포인트 추가 | 참조: python#4,5 | 지킴: 4,5 | 놓침: - | 재발: - | 메모: StreamingResponse + 제너레이터 패턴 확인
-->
