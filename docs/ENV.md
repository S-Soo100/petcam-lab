# 환경변수 레퍼런스

> `.env` 파일에 넣는 값 전체. 템플릿은 [`.env.example`](../.env.example) — 실제 값은 로컬에만, 커밋 금지.

## 목차

- [민감도 분류](#민감도-분류)
- [전체 표](#전체-표)
- [섹션별 설명](#섹션별-설명)
  - [RTSP 스모크 테스트](#rtsp-스모크-테스트)
  - [캡처 워커 공용](#캡처-워커-공용)
  - [움직임 감지](#움직임-감지)
  - [Supabase](#supabase)
  - [인증 모드](#인증-모드)
  - [JWT 검증 (prod 전용)](#jwt-검증-prod-전용)
  - [카메라 비번 암호화](#카메라-비번-암호화)
- [생성 / 획득 방법](#생성--획득-방법)
- [흔한 실수](#흔한-실수)

---

## 민감도 분류

| 수준 | 예시 | 취급 |
|------|------|------|
| 🔴 Critical | `SUPABASE_SERVICE_ROLE_KEY`, `CAMERA_SECRET_KEY` | 유출 즉시 전면 로테이션. 깃에 절대 금지. 맥북 분실 시 Supabase 대시보드에서 키 revoke + 카메라 비번 전부 재설정 |
| 🟠 Sensitive | `DEV_USER_ID`, `DEV_PET_ID`, `SUPABASE_URL` | 로컬 개발·배포 외 공유 금지. URL 자체는 공개돼도 service_role 없으면 단독 피해 작음 |
| 🟢 Non-secret | 튜닝 파라미터(`MOTION_*`, `SEGMENT_SECONDS`, `AUTH_MODE` 등) | `.env.example` 에 기본값 공개. 커밋 OK (실제 `.env` 는 여전히 커밋 금지) |

**모두 `.env` 에만** — `.env` 는 `.gitignore` 돼 있음. 실수로 커밋되면 git history 에서 제거하고 전 키 로테이션.

---

## 전체 표

| 이름 | 필수 | 기본값 | 민감도 | 섹션 |
|------|:----:|--------|:------:|------|
| `TEST_SNAPSHOT_PATH` | 선택 | `storage/test_snapshot.jpg` | 🟢 | RTSP 스모크 |
| `SEGMENT_SECONDS` | 선택 | `60` | 🟢 | 캡처 |
| `CLIPS_DIR` | 선택 | `storage/clips` | 🟢 | 캡처 |
| `MOTION_PIXEL_THRESHOLD` | 선택 | `25` | 🟢 | 모션 |
| `MOTION_PIXEL_RATIO` | 선택 | `1.0` | 🟢 | 모션 |
| `MOTION_MIN_DURATION_FRAMES` | 선택 | `12` | 🟢 | 모션 |
| `MOTION_SEGMENT_THRESHOLD_SEC` | 선택 | `3.0` | 🟢 | 모션 |
| `SUPABASE_URL` | **필수** | — | 🟠 | Supabase |
| `SUPABASE_SERVICE_ROLE_KEY` | **필수** | — | 🔴 | Supabase |
| `DEV_USER_ID` | **필수** (dev 모드) | — | 🟠 | Supabase |
| `DEV_PET_ID` | 선택 | (빈 값) | 🟠 | Supabase |
| `AUTH_MODE` | 선택 | `dev` | 🟢 | 인증 |
| `SUPABASE_JWT_ISSUER` | **필수** (prod 모드) | — | 🟠 | JWT |
| `SUPABASE_JWKS_URL` | **필수** (prod 모드) | — | 🟠 | JWT |
| `CAMERA_SECRET_KEY` | **필수** | — | 🔴 | 암호화 |

**"필수" 판단 기준** — 없으면 서버가 기동 안 되거나 `/health` 의 `startup_error` 가 뜸.

---

## 섹션별 설명

### RTSP 스모크 테스트

`scripts/test_rtsp.py` 가 사용. 프로덕션 흐름에는 무관.

**`TEST_SNAPSHOT_PATH`** — 스모크 테스트에서 첫 프레임 저장할 경로. 상대경로면 repo root 기준.

---

### 캡처 워커 공용

`backend/capture.py` 가 전 워커 공통으로 사용. 카메라별 override 없음 (현재).

**`SEGMENT_SECONDS`** = `60`
한 mp4 파일에 담을 길이(초). 60초가 MVP 기준. 너무 짧으면 파일 수 폭증, 너무 길면 motion 판정 정밀도 저하.

**`CLIPS_DIR`** = `storage/clips`
mp4 가 쌓일 루트. 상대경로면 repo root 기준. 실제 저장 경로: `{CLIPS_DIR}/{YYYY-MM-DD}/{camera_uuid}/{HHMMSS}_{motion|idle}.mp4`.

---

### 움직임 감지

`backend/motion.py` + `backend/capture.py` 의 run-length 필터.

**`MOTION_PIXEL_THRESHOLD`** = `25` (0~255)
두 프레임 간 픽셀 밝기 차이 임계. 이 값 넘어야 "변한 픽셀" 로 카운트.

**`MOTION_PIXEL_RATIO`** = `1.0` (%)
전체 픽셀 중 변한 비율이 이 값 이상이면 해당 프레임을 motion 으로. 도마뱀이 화면 5~10% 차지 + 야행성 IR 노이즈 고려해 1% 초기값. 오탐 많으면 ↑, 놓침 많으면 ↓.

**`MOTION_MIN_DURATION_FRAMES`** = `12` (프레임)
N 프레임 연속 motion 이어야 진짜 움직임으로 인정 (노이즈 필터). 12 ≈ 1초 @ 12fps.

**`MOTION_SEGMENT_THRESHOLD_SEC`** = `3.0` (초)
1분 세그먼트 안에 유효 motion 이 이 초 이상이면 `_motion.mp4` 로 저장. 미만이면 `_idle.mp4`.

튜닝 전략: [`docs/FEATURES.md` #움직임 감지](FEATURES.md) + [Stage B 스펙](../specs/stage-b-motion-detection.md).

---

### Supabase

Flutter 앱과 같은 프로젝트(`slxjvzzfisxqwnghvrit`) 재사용.

**`SUPABASE_URL`** (필수)
대시보드 `Settings > API > Project URL`. 예: `https://slxjvzzfisxqwnghvrit.supabase.co`

**`SUPABASE_SERVICE_ROLE_KEY`** 🔴 (필수)
같은 페이지의 `service_role (secret)` 키. RLS 바이패스 권한이라 노출 시 전체 DB 유출. 절대 커밋 금지. Flutter 앱 코드에도 포함 금지 (Flutter 는 `anon` 키).

**`DEV_USER_ID`** 🟠 (dev 모드 필수)
`auth.users.id` (UUID). Stage C 로컬 테스트 + dev 모드에서 하드코딩된 user_id 로 쓰임. prod 모드에서는 JWT 의 `sub` 가 이 값을 대체.

**`DEV_PET_ID`** 🟠 (선택)
해당 유저의 `pets.id`. 빈 값이면 `camera_clips.pet_id = NULL` 로 저장. Stage C 초기엔 camera 1 대 → 펫 1 마리 하드 매핑용. Stage D+ 에서 `cameras.pet_id` 로 대체됨.

---

### 인증 모드

**`AUTH_MODE`** = `dev` (기본)
- `dev` — Authorization 헤더 무시, `DEV_USER_ID` 반환. 로컬 개발·pytest 전용.
- `prod` — `Authorization: Bearer <JWT>` 필수. Supabase JWKS 로 서명 검증.

**외부망 공개(Cloudflare Tunnel) 할 때는 반드시 prod.** dev 로 두면 누구나 `DEV_USER_ID` 로 통과.

서버 기동 시 lifespan 이 현재 모드를 warning 레벨로 로그에 찍음 — 실수로 prod 에서 dev 켜진 사고 즉시 감지.

---

### JWT 검증 (prod 전용)

`AUTH_MODE=prod` 일 때 필수. `backend/auth.py` 가 참조.

**`SUPABASE_JWT_ISSUER`**
발급자 검증용. 보통 `{SUPABASE_URL}/auth/v1`. 예: `https://slxjvzzfisxqwnghvrit.supabase.co/auth/v1`

**`SUPABASE_JWKS_URL`**
공개키 셋 엔드포인트. 보통 `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`. 서버가 10분 TTL 로 캐시.

검증 흐름 상세: [`docs/API.md` #인증](API.md#인증) + [Stage D1 스펙](../specs/stage-d1-auth-crypto.md).

---

### 카메라 비번 암호화

**`CAMERA_SECRET_KEY`** 🔴 (필수)
Fernet 대칭키 (URL-safe base64, 32바이트). `cameras.password_encrypted` 암/복호화 전용.

**⚠️ 절대 규칙 — 최초 1회 생성 후 변경 금지.** 바꾸면 기존 DB 암호문 전부 복호화 불가 → 모든 카메라 비번 재등록 필요.

생성:
```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

맥북 분실 시 위험 체인: 맥북 접근권 → `.env` → `CAMERA_SECRET_KEY` → 모든 `cameras.password_encrypted` 복호화 → Tapo 앱 계정 비번 전부 로테이션 필요.

placeholder 문자열(`placeholder-replace-with-generated-fernet-key`) 그대로 두면 서버가 기동 시 `CryptoNotConfigured` 로 감지 → 전 카메라 skip + `/health startup_error` 에 "CAMERA_SECRET_KEY 문제" 표시.

---

## 생성 / 획득 방법

| 값 | 방법 |
|----|------|
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | Supabase 대시보드 → Settings → API |
| `DEV_USER_ID` | Supabase 대시보드 → Authentication → Users → 해당 유저 ID 복사 (UUID). 현재 값: `380d97fd-cb83-4490-ac26-cf691b32614f` (`bss.rol20@gmail.com`) |
| `DEV_PET_ID` | Supabase → Table Editor → `pets` 테이블 → 해당 row 의 `id`. 비워도 됨 |
| `SUPABASE_JWT_ISSUER` | `{SUPABASE_URL}/auth/v1` 그대로 |
| `SUPABASE_JWKS_URL` | `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` 그대로 |
| `CAMERA_SECRET_KEY` | 위 Fernet 생성 커맨드 (1회) |

---

## 흔한 실수

| 증상 | 원인 | 해결 |
|------|------|------|
| `/health` `startup_error: "Supabase 미설정"` | `SUPABASE_URL` 또는 `SUPABASE_SERVICE_ROLE_KEY` 비어있음 | `.env` 에 값 채우고 재기동 |
| `/health` `startup_error: "DEV_USER_ID 미설정"` | `DEV_USER_ID` 빈 값 | `.env` 에 UUID 기입 |
| `/health` `startup_error: "CAMERA_SECRET_KEY 문제"` | placeholder 그대로 | Fernet 생성 커맨드 실행 후 교체 |
| `/health` `capture_workers: 0` + `skipped_cameras` 비어있음 | 등록된 카메라 없음 | `POST /cameras` 로 등록 |
| `/health` `skipped_cameras: ["<uuid> ..."]` | 해당 카메라의 `password_encrypted` 가 **다른** `CAMERA_SECRET_KEY` 로 암호화됨 | 키를 바꿨다면 해당 카메라 삭제 + 재등록. 바꾼 적 없으면 Fernet 토큰 변조 의심 |
| 401 `"JWKS 조회 실패"` | `SUPABASE_JWKS_URL` 오타 or 네트워크 | URL 재확인, curl 로 200 응답 확인 |
| 401 `"AUTH_MODE 값이 이상함"` | `AUTH_MODE=development` 같은 엉뚱한 값 | `dev` 또는 `prod` 만 허용 |
| `.env` 수정 반영 안 됨 | uvicorn `--reload` 는 파일 변경만 감지. `.env` 는 lifespan 에서만 로드 | 서버 재기동 |
| 실수로 `.env` 커밋 | `.gitignore` 누락 or 강제 add | `git rm --cached .env` + history 정리 + 전 키 로테이션 |

---

관련 문서:
- [`.env.example`](../.env.example) — 템플릿
- [`docs/DEPLOYMENT.md`](DEPLOYMENT.md) — prod 배포 시 추가 체크리스트
- [`docs/API.md`](API.md#인증) — 인증 모드 동작 상세
