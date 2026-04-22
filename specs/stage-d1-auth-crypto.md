# Stage D1 — JWT 인증 + Fernet 암호화 인프라

> Stage D 의 첫 서브. 후속 D2~D5 와 Flutter F3/F5 가 전제하는 **"인증" + "비밀값 암호화"** 인프라를 먼저 마련. 여기서 만든 `Depends(get_current_user_id)` 와 Fernet 래퍼가 이후 모든 서브 스테이지에 쓰임.

**상태:** ✅ 완료 (2026-04-22)
**작성:** 2026-04-22
**상위 로드맵:** [stage-d-roadmap.md](stage-d-roadmap.md)
**연관 SOT:** `../../tera-ai-product-master/docs/specs/petcam-backend-dev.md` — Stage D 섹션

---

## 1. 목적

- **사용자 가치**: 지금은 `.env` 의 `DEV_USER_ID` 로 한 명만 서비스 가능. JWT 검증이 있어야 여러 유저·Flutter 앱 로그인 기반 조회가 가능해짐. 카메라 비번 암호화는 상용 수준 보안의 최소 요건.
- **학습 목표**:
  - Supabase Auth JWT 구조 (header/payload/signature) 와 검증 흐름
  - JWKS (JSON Web Key Set) 개념 + `@lru_cache` 기반 공개키 캐싱 (TTL)
  - FastAPI `Depends` 계층화 (`get_jwt_payload` → `get_current_user_id`)
  - 대칭 암호화 (Fernet = AES-128-CBC + HMAC) 의 표준 용법
  - `.env` 비밀 키 관리 (placeholder 가드 + 테스트 격리)

---

## 2. 스코프

### In (이번 스펙에서 한다)

- **의존성 추가**
  - `uv add pyjwt[crypto]` — JWT 디코드 + RSA/EC 서명 검증
  - `uv add cryptography` — Fernet (pyjwt[crypto] 설치 시 함께 들어오는지 확인 후 중복 제거)
- **JWT 검증 모듈** (`backend/auth.py` 신설)
  - `get_jwks()` — Supabase JWKS 엔드포인트에서 공개키 셋 받아와 `@lru_cache` 캐시 (TTL 10 분, `time.monotonic()` 로 만료 확인)
  - `verify_jwt(token: str) -> dict` — 서명 검증 + `exp` 체크 → payload 반환
  - `get_jwt_payload(request: Request) -> dict` — `Authorization: Bearer <token>` 헤더 파싱 → `verify_jwt` 호출
  - `get_current_user_id(payload: dict = Depends(get_jwt_payload)) -> str` — `payload["sub"]` 반환 (UUID)
- **Dev 모드 fallback**
  - `.env` 에 `AUTH_MODE=dev` 면 `DEV_USER_ID` 를 그대로 반환 (JWT 검증 스킵)
  - `AUTH_MODE=prod` (기본값) 면 JWT 필수, 없으면 401
  - 로컬 테스트·스크립트가 계속 `DEV_USER_ID` 로 동작하도록 보존
- **Fernet 암호화 모듈** (`backend/crypto.py` 신설)
  - `get_camera_fernet()` — `@lru_cache(maxsize=1)` 로 `Fernet(CAMERA_SECRET_KEY)` 싱글톤
  - `encrypt_password(plaintext: str) -> bytes` / `decrypt_password(ciphertext: bytes) -> str`
  - `.env` placeholder 가드 (placeholder 상태 감지 → `CryptoNotConfigured` 예외)
- **환경변수**
  - `.env.example` 에 추가: `CAMERA_SECRET_KEY=your-fernet-key-base64`, `AUTH_MODE=dev`, `SUPABASE_JWT_ISSUER` (Supabase project URL 기반), `SUPABASE_JWKS_URL`
  - `.env` 에 실제 값 기입 (Fernet 키는 `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` 로 1 회 생성)
- **Stage C `clips.py` 리팩터**
  - `get_dev_user_id` → `get_current_user_id` 로 교체 (`Depends` 한 줄 수정)
  - Dev 모드에서는 기존처럼 동작, Prod 모드에선 JWT 필수
- **테스트 (`tests/test_auth.py` 신설)**
  - JWT 검증 성공 케이스 (유효 토큰)
  - 만료 토큰 → 401
  - 서명 변조 → 401
  - Authorization 헤더 누락 → 401 (Prod 모드) / DEV_USER_ID 반환 (Dev 모드)
  - JWKS 캐시 TTL 만료 후 재조회
  - Fernet: encrypt → decrypt 라운드트립
  - Fernet: placeholder 키 → `CryptoNotConfigured`

### Out (이번 스펙에서 **안 한다**)

- **`cameras` 테이블 / CRUD API** — Stage D2. D1 은 인프라만.
- **`camera_clips` FK 마이그레이션** — Stage D3.
- **썸네일** — Stage D4.
- **Flutter 로그인 UI** — Flutter 레포 F1 작업.
- **JWT refresh token 로직** — Supabase Auth 가 Flutter SDK 레벨에서 처리. petcam 서버는 access_token 검증만.
- **키 로테이션 자동화** — MVP 엔 수동. 상용 단계 과제.
- **Rate limiting** — 별도 스펙.

### 경계 사유

- D1 에 `cameras` CRUD 까지 넣으면 "인증" 과 "카메라 관리" 디버깅이 섞임. 인증만 먼저 단단히.
- Stage C API 는 **Dev 모드로 기존 동작 유지** 가 원칙. JWT 도입으로 기존 테스트 깨지면 안 됨.

---

## 3. 완료 조건

### 의존성
- [x] `uv add pyjwt[crypto]` 완료, `pyproject.toml`/`uv.lock` 커밋
- [x] `cryptography` 가 이미 포함되어 있는지 확인 (pyjwt[crypto] 의존성으로) — 아니면 `uv add cryptography` → pyjwt[crypto] 가 cryptography 을 자동으로 끌어옴, 별도 add 불필요

### 환경변수
- [x] `.env.example` 에 4 개 키 추가: `CAMERA_SECRET_KEY`, `AUTH_MODE`, `SUPABASE_JWT_ISSUER`, `SUPABASE_JWKS_URL`
- [ ] `.env` 에 실제 `CAMERA_SECRET_KEY` 생성 + 기입 (`.env.example` 은 placeholder) — **사용자 작업** (비밀키 채팅 로그에 남기지 않기 위함)
- [x] `.env.example` 주석으로 Fernet 키 생성 명령 안내

### 코드
- [x] `backend/auth.py` 신설
  - [x] `get_jwks()` 구현 (HTTP fetch + 10 분 TTL 캐시)
  - [x] `verify_jwt(token)` 구현 (서명 + exp 검증)
  - [x] `get_jwt_payload` Depends 구현
  - [x] `get_current_user_id` Depends 구현
  - [x] Dev 모드 분기 구현 (`AUTH_MODE=dev` 시 `DEV_USER_ID` 반환)
- [x] `backend/crypto.py` 신설
  - [x] `get_camera_fernet()` 싱글톤 구현
  - [x] `encrypt_password` / `decrypt_password` 구현 (str I/O — DB TEXT 컬럼 + JSON 직렬화 편의)
  - [x] placeholder 가드 (`CryptoNotConfigured` 예외)
- [x] `backend/routers/clips.py` 수정
  - [x] `Depends(get_dev_user_id)` → `Depends(get_current_user_id)` 교체
  - [x] 기존 동작 유지 (Dev 모드에서 `DEV_USER_ID` 반환 같음)

### 테스트
- [x] `tests/test_auth.py` 신설 — JWT 검증 15 케이스 (Dev 3 + Prod header 3 + Prod JWT 6 + JWKS cache 2 + unknown mode 1)
- [x] `tests/test_crypto.py` 신설 — Fernet 라운드트립, placeholder 가드, 싱글톤 (17 케이스)
- [x] 기존 `tests/test_clips_api.py` 가 Dev 모드로 계속 통과 (regression 없음) — 19 tests 통과 (get_dev_user_id 단위 테스트 2개는 test_auth.py 로 대체 이관)
- [x] `uv run pytest` 전체 통과 — 73 passed in 0.76s

### 검증
- [ ] Dev 모드 로컬 기동 → `/clips` 조회 기존처럼 동작 (수동, 선택 사항 — 단위 테스트로 모든 분기 커버됨)
- [ ] Prod 모드 로컬 기동 → Authorization 없이 요청 시 401 (수동, 선택 사항)
- [ ] Prod 모드 + 유효 JWT → 200 + 해당 유저 클립만 반환 (수동, 실 Supabase 필요 — D2 이후로 연기)
- [ ] Prod 모드 + 다른 유저 JWT → 해당 JWT 유저의 클립만 (이전 유저 클립 안 보임) (수동, 실 Supabase 필요 — D2 이후로 연기)
- [ ] `python -c "from backend.crypto import encrypt_password, decrypt_password; print(decrypt_password(encrypt_password('hello')))"` → `hello` 출력 (CAMERA_SECRET_KEY 설정 후 **사용자 작업**)

### 문서
- [x] README 에 `AUTH_MODE` 환경변수 설명 추가 — "Stage D1 — Auth 인프라 + 카메라 암호화" 섹션
- [x] 로드맵의 D1 상태 → ✅ 완료로 갱신 (README 로드맵 표 + stage-d-roadmap.md)

---

## 4. 설계 메모

구현하면서 채울 섹션. 대안·리스크·결정 근거 누적.

### JWT 검증 흐름

```
클라이언트 (Flutter 앱)
  └─ Supabase Auth 로그인 성공 → access_token 획득
  └─ 요청 시 Authorization: Bearer <access_token> 헤더 포함
         │
         ▼
petcam-lab FastAPI
  └─ Depends(get_current_user_id)
         ├─ get_jwt_payload
         │    ├─ 헤더에서 토큰 추출 (없으면 Dev fallback or 401)
         │    └─ verify_jwt
         │         ├─ JWKS 캐시 조회 (10분 TTL, 만료 시 재fetch)
         │         ├─ 서명 검증 (RS256)
         │         ├─ exp 체크
         │         └─ payload 반환
         └─ payload["sub"] (UUID) 반환
```

### 고려했던 대안

- **HS256 + 공유 secret**: 대칭 키 방식. Supabase 는 RS256 기본 → JWKS 쓰는 게 정석
- **Supabase SDK `auth.get_user(token)` 호출**: 매 요청마다 Supabase 호출 → 지연 + 비용. JWKS 캐시 + 로컬 검증이 정석
- **미들웨어 방식** vs **Depends 방식**: Depends 가 FastAPI 패턴에 맞음. 라우트별 선택 적용 가능 (`/health` 는 JWT 불필요)

### AUTH_MODE 분기가 왜 필요?

- 로컬 개발 시 매번 JWT 발급받기 번거로움
- 기존 단위 테스트 (Stage C 21 개) 가 Dev 모드 전제 → 깨지면 안 됨
- CI 에서도 Dev 모드로 테스트
- Prod 배포 시 `.env` 의 `AUTH_MODE=prod` 로 전환

### Fernet 키 유출 시나리오

- `.env` 깃 커밋 실수 → git history 에서 제거 + 키 로테이션 (Stage D+ 과제)
- 맥북 도난 → 해당 키로 암호화된 모든 카메라 비번 복호화 가능 → Tapo 계정 비번 전체 변경 필요
- 완화: 장기적으로 HSM / Cloud KMS 로 이전

### 리스크 / 미해결 질문

- Supabase JWT 의 `sub` 가 항상 `auth.users.id` 와 같은지 최종 확인 필요 (거의 확실하지만 레퍼런스 문서로)
- JWKS URL 이 Supabase 프로젝트마다 고정인지, API 로 제공되는지 확인
- Dev 모드에서 Authorization 헤더가 있으면 검증 vs 무시? → 일단 **무시** (간단함 우선)

---

## 5. 학습 노트

- **JWT (JSON Web Token)**: base64 로 인코딩된 `header.payload.signature`. Supabase 는 RS256 서명 → 서버가 공개키로 검증.
- **JWKS (JSON Web Key Set)**: 공개키 모음. Supabase 가 `https://<project>.supabase.co/auth/v1/.well-known/jwks.json` 에 노출 (정확한 경로 확인 필요).
- **`pyjwt[crypto]`**: `[crypto]` extra 로 cryptography 깔려서 RS256 검증 가능. 없으면 HS256 만.
- **Fernet**: `from cryptography.fernet import Fernet`. `Fernet.generate_key()` → 32바이트 base64 → `Fernet(key)` 인스턴스 → `.encrypt()`/`.decrypt()`.
- **TS/Node 비유**:
  - `Depends(get_current_user_id)` = NestJS `@UserId()` 커스텀 데코레이터
  - JWKS 캐시 = `jwks-rsa` 라이브러리의 caching client
  - Fernet = Node `crypto.createCipheriv('aes-128-cbc', ...)` + HMAC 조합을 한 줄로 묶은 것

---

## 6. 참고

- Supabase JWT 공식: https://supabase.com/docs/guides/auth/jwts
- PyJWT 공식: https://pyjwt.readthedocs.io/
- cryptography Fernet: https://cryptography.io/en/latest/fernet/
- 상위 로드맵: [stage-d-roadmap.md](stage-d-roadmap.md)
- Stage C 학습 문서 (`Depends`, RLS 복습): [`../docs/stage-c-learning.md`](../docs/stage-c-learning.md)
- SOT 스펙: `../../tera-ai-product-master/docs/specs/petcam-backend-dev.md`
