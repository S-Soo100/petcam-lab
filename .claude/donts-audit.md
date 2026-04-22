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

<!-- 예시:
2026-04-20 fastapi | 작업: MJPEG 스트리밍 엔드포인트 추가 | 참조: python#4,5 | 지킴: 4,5 | 놓침: - | 재발: - | 메모: StreamingResponse + 제너레이터 패턴 확인
-->
