# Flutter 인수인계 — Stage D5 prep (AUTH_MODE=prod 전환)

> **독자:** `tera-ai-flutter` 레포 유지보수 에이전트 / 개발자
> **목적:** petcam-lab 백엔드가 Stage D5 (Cloudflare Tunnel 배포) 에 진입하며 `AUTH_MODE`를 `dev` → `prod`로 전환한다. Flutter 앱이 이 전환을 무리 없이 받아들일 수 있도록 확인·보완할 항목 정리.
> **작성:** 2026-04-22, petcam-lab 백엔드 측. 기존 [`docs/flutter-handoff.md`](flutter-handoff.md) 의 D5 확장본.

---

## 0. TL;DR

**좋은 소식:** Flutter 쪽은 이미 85% 준비됨.

| 항목 | 상태 |
|------|------|
| `supabase_flutter` 인증 SDK + 로그인/회원가입/OTP 화면 | ✅ 구현됨 |
| `CameraRepository` / `ClipRepository` Bearer 자동 부착 | ✅ 구현됨 |
| `_tokenProvider` 가 `currentSession?.accessToken` 매번 fresh 읽기 | ✅ 구현됨 (만료 자동 대응 구조) |
| GoRouter `authStateChanges` 구독 → 로그아웃 시 `/login` redirect | ✅ 구현됨 |
| video_player / CachedNetworkImage 용 `authHeaders()` public 메서드 | ✅ 구현됨 |
| **401 응답 재시도/signOut 인터셉터** | ⚠️ 확인 필요 |
| **BACKEND_URL 환경 전환** (local → LAN IP → Cloudflare) | ⚠️ 변경 예정 |
| **video_player/CachedNetworkImage 에 실제 `authHeaders()` 주입 여부** | ⚠️ 확인 필요 |

**따라서 이번 요청 범위:** 위 ⚠️ 3개만.

---

## 1. 배경 — 왜 지금 이 작업?

petcam-lab 백엔드의 `AUTH_MODE` 스위치 동작:

| 모드 | Authorization 헤더 | 동작 |
|------|-------------------|------|
| `dev` (지금까지) | 무시 | 하드코딩 `DEV_USER_ID` 반환 — 로컬 개발 편의 |
| `prod` (D5 이후) | **필수** | JWT JWKS 검증 → `sub` claim → `user_id`. 없거나 만료 시 401. |

**D5 (Cloudflare Tunnel) 배포의 보안 전제**:
- 백엔드가 공용 인터넷에 노출되므로 `AUTH_MODE=dev`면 누구나 아무 user_id로 접근 가능 → 필수 prod 전환.
- 전환 시점: Cloudflare Named Tunnel 연결 + 도메인 설정 완료 시점 (예정).

---

## 2. 내가 확인한 현재 상태

코드 위치와 흐름을 아래처럼 파악함.

### 2.1 Supabase 초기화

**`lib/main.dart:58-61`**
```dart
await Supabase.initialize(
  url: dotenv.env['SUPABASE_URL']!,
  anonKey: dotenv.env['SUPABASE_ANON_KEY']!,
);
```
SDK 가 내부적으로 iOS Keychain / Android Keystore 에 토큰 저장·복원·자동 refresh 담당. ✅

### 2.2 인증 리포지토리

**`lib/features/auth/data/auth_repository.dart`**
- `signIn` / `signUp` / `verifyOTP` / `resendSignupOTP` / `signOut` 제공
- `authStateChanges` 스트림 노출

**`lib/features/auth/presentation/auth_providers.dart`**
- `authStateProvider` (Stream)
- `currentUserProvider`
- `isAuthenticatedProvider` (Provider<bool>)

### 2.3 백엔드 API 호출 — Bearer 토큰 구조

**`lib/features/my_cage/presentation/my_cage_providers.dart:17-21`**
```dart
final _tokenProviderProvider = Provider<Future<String?> Function()>(
  (ref) => () async =>
      Supabase.instance.client.auth.currentSession?.accessToken,
);
```
매 호출마다 `currentSession` 을 새로 읽어 최신 토큰 반환. SDK 가 자동 refresh 하면 즉시 반영됨. **이 구조가 핵심** — 별도 갱신 로직 필요 없음.

**`lib/features/my_cage/data/camera_repository.dart:97-104`**
```dart
Future<Map<String, String>> _authHeaders({bool withJson = false}) async {
  final token = await _tokenProvider();
  return {
    if (token != null) 'Authorization': 'Bearer $token',
    if (withJson) 'Content-Type': 'application/json',
  };
}
```

**`lib/features/my_cage/data/clip_repository.dart:149-152`**
```dart
Future<Map<String, String>> authHeaders() async {
  final token = await _tokenProvider();
  return {if (token != null) 'Authorization': 'Bearer $token'};
}
```
public 메서드로 video_player / CachedNetworkImage 에 주입하라고 설계됨.

### 2.4 라우터 가드

**`lib/core/router/app_router.dart:35-76`**
- `_AuthChangeNotifier` + `ref.listen(isAuthenticatedProvider, ...)` 로 인증 상태 변경 시 redirect 재평가
- publicPaths 외 경로는 미인증 시 `/login` 강제 이동
- 인증된 상태에서 `/login` 접근 시 `/home` 으로 튕김

✅ 이것도 이미 잘 짜여있음.

### 2.5 환경 설정

**`lib/core/config/env_config.dart:8-9`**
```dart
static String get backendUrl =>
    dotenv.env['BACKEND_URL'] ?? 'http://localhost:8000';
```

`.env` 의 `BACKEND_URL` 값이 전환 대상.

---

## 3. 요청 사항

### 3.1 지금 — 확인만 (소요 10분)

- [ ] **BACKEND_URL 현재 값** 알려주기 (`.env` 의 `BACKEND_URL=`). 셋 중 하나일 거임:
    - `http://localhost:8000` (Mac 시뮬레이터 전용)
    - `http://192.168.219.105:8000` (실기기 LAN 테스트)
    - 아직 안 씀
- [ ] **현재 dev 모드에서 JWT 가 실제로 가고 있는지** 확인. 로그인 후 `cameraRepositoryProvider` 가 `/cameras/test-connection` 또는 `/cameras` 호출 시 `Authorization: Bearer eyJ...` 헤더 포함되는지.
    - 빠른 확인법: `http` 패키지 대신 `Dio` 로 래핑 후 log interceptor 붙이거나, 백엔드 콘솔에서 헤더 로그 추가.
    - 현재 백엔드는 dev 모드라 **헤더 존재 여부만** 보면 됨 (내용 검증 안 함).

### 3.2 AUTH_MODE=prod 전환 **전에** — 보완

- [ ] **401 응답 처리 인터셉터 추가**

  현재 `_authHeaders()` 는 토큰 없으면 헤더 생략만 함. 401 응답 받았을 때의 대응이 repository 단에 없음.

  권장 처리 (`camera_repository.dart` / `clip_repository.dart` 공통 래퍼):
  ```dart
  Future<http.Response> _authedRequest(
    Future<http.Response> Function() send,
  ) async {
    final resp = await send();
    if (resp.statusCode == 401) {
      // Supabase SDK 는 access_token 만료면 내부적으로 자동 refresh 시도.
      // 여기까지 401 왔다는 건 refresh_token 도 만료/위조된 경우.
      await Supabase.instance.client.auth.signOut();
      // → authStateChanges 가 signedOut 이벤트 발행
      // → routerProvider 의 isAuthenticatedProvider 가 false 로 전환
      // → GoRouter redirect 가 /login 으로 강제 이동
    }
    return resp;
  }
  ```

  이미 인증 만료 시 재로그인 유도 UX 가 있으면 이 방식 생략 가능. **현재 어떻게 처리 중인지** 알려주기.

- [ ] **video_player 에 `authHeaders()` 실제 주입되어 있는지** 확인

  `lib/features/my_cage/presentation/clip_player_screen.dart` 에서 `VideoPlayerController.networkUrl` 호출 시 `httpHeaders` 에 `clipRepository.authHeaders()` 결과를 넣고 있는지.

  prod 모드 켜면 `/clips/{id}/file` 도 JWT 요구함 → 헤더 없이 호출하면 401 → 영상 안 뜸. dev 모드 땐 통과되니까 놓칠 수 있음.

- [ ] **CachedNetworkImage 썸네일도 동일** (`clip_grid_card.dart` 등)
  ```dart
  CachedNetworkImage(
    imageUrl: clipRepository.thumbnailUrl(clipId),
    httpHeaders: await clipRepository.authHeaders(),  // ← 이게 있어야 함
    ...
  )
  ```

### 3.3 Stage D5 배포 **후에** — 환경 전환

- [ ] `.env` 의 `BACKEND_URL` 교체
  - Quick Tunnel (찍먹): `https://<random>.trycloudflare.com` (매번 바뀜)
  - Named Tunnel (상시): `https://api.tera-ai.kr` 같은 고정 도메인 (도메인은 나중에 결정)
- [ ] iOS ATS 확인
  - Cloudflare 는 HTTPS 강제라 ATS 기본값으로 OK
  - `ios/Runner/Info.plist` 에 `NSAppTransportSecurity` 로 HTTP 예외 뚫어놓은 게 있으면 제거 권장

---

## 4. 토큰 저장·관리 — "어디에 두나" 질문에 대한 공식 답

petcam-lab 측에서 "Flutter 가 Bearer 토큰을 어디 저장하나" 라는 질문이 있었음. 답은:

**`supabase_flutter` SDK 가 다 함. 네가 따로 저장소 만들 필요 없음.**

| 동작 | SDK 내부 처리 |
|------|---------------|
| 로그인 성공 | access_token + refresh_token 을 iOS Keychain / Android Keystore 에 자동 저장 (OS 수준 암호화) |
| 앱 재시작 | `Supabase.initialize()` 직후 자동 복원 → `currentSession` 즉시 유효 |
| access_token 만료 (1h) | 백그라운드에서 refresh_token 으로 자동 갱신 |
| refresh_token 만료 (30d) | `onAuthStateChange` 에 `signedOut` 이벤트 발행 |
| 로그아웃 | Keychain/Keystore 에서 삭제 |

**절대 하지 말 것:**
- `SharedPreferences` 에 수동 저장 (평문, 루팅된 기기에서 노출)
- `flutter_secure_storage` 로 우회 저장 (SDK 와 상태 불일치 위험)
- 메모리 전역변수만 사용 (재시작 시 날아감)

현재 구조 (`_tokenProvider` 매번 `currentSession?.accessToken` 호출) 가 **권장 패턴에 정확히 부합.**

---

## 5. 검증 시나리오 — prod 전환 완료 후 smoke test

아래 8 단계 통과하면 전환 완료.

| # | 시나리오 | 기대 동작 |
|---|---------|----------|
| 1 | 로그아웃 상태에서 `/my-cage` 직접 URL 접근 | `/login` 으로 redirect |
| 2 | 로그인 → 카메라 목록 (`camerasProvider`) | Supabase 직결 SELECT → 200, 본인 행만 |
| 3 | 카메라 등록 → 백엔드 `POST /cameras` | 201, Fernet 암호화되어 DB 저장 |
| 4 | 클립 목록 (`clipsForHourProvider`) | Supabase 직결 SELECT → RLS 통과 |
| 5 | 클립 재생 (`clip_player_screen`) | `video_player` + `httpHeaders` 로 200/206, mp4 재생 |
| 6 | 썸네일 그리드 (`clip_grid_card`) | `CachedNetworkImage` + headers 로 jpg 로드 |
| 7 | 앱 종료 → 재시작 | 자동 로그인 유지, `/home` 진입 |
| 8 | 백엔드 단독으로 curl (`-H "Authorization: Bearer <앱에서 뽑은 토큰>"`) | 200 — Flutter 외부에서도 토큰으로 접근 가능 |

시나리오 5, 6 은 3.2 체크리스트 완료 후에만 통과함. 놓치면 영상·썸네일만 401 나는 현상으로 증상화.

---

## 6. 백엔드 측 참고사항

### 6.1 dev↔prod 전환 시 데이터 연속성

- dev 모드에서 저장된 카메라·클립은 `DEV_USER_ID` (현재 `380d97fd-cb83-4490-ac26-cf691b32614f`) 소유로 되어있음.
- 프로덕션 로그인 유저의 `auth.users.id` 가 이 UUID 와 동일하면 데이터 연속 유지. 다른 UUID면 새 계정처럼 빈 상태.
- → 개발 시 사용한 계정 그대로 prod 로 올리면 자연스러움.

### 6.2 JWKS 키 캐시

- 백엔드 `SUPABASE_JWKS_URL` 에서 공개키 페치 (TTL 10분).
- Supabase 키 로테이션 시 최대 10분 지연 후 적용. Flutter 쪽에서 별다른 조치 불필요.

---

## 7. 파일 위치 치트시트

```
tera-ai-flutter/
├── .env                                             # BACKEND_URL, SUPABASE_URL, SUPABASE_ANON_KEY
├── lib/
│   ├── main.dart                                    # Supabase.initialize (58-61)
│   ├── core/
│   │   ├── config/env_config.dart                   # EnvConfig.backendUrl
│   │   ├── router/app_router.dart                   # _AuthChangeNotifier, redirect 로직
│   │   └── supabase/supabase_provider.dart          # SupabaseClient singleton
│   └── features/
│       ├── auth/
│       │   ├── data/auth_repository.dart            # signIn/signUp/OTP/signOut
│       │   └── presentation/
│       │       ├── auth_providers.dart              # isAuthenticatedProvider
│       │       ├── login_screen.dart
│       │       ├── signup_screen.dart
│       │       └── email_verification_screen.dart
│       └── my_cage/
│           ├── data/
│           │   ├── camera_repository.dart           # _authHeaders() (97-104)
│           │   └── clip_repository.dart             # authHeaders() (149-152)
│           └── presentation/
│               ├── my_cage_providers.dart           # _tokenProviderProvider (17-21)
│               ├── clip_player_screen.dart          # ← video_player httpHeaders 주입 확인
│               └── widgets/
│                   └── clip_grid_card.dart          # ← CachedNetworkImage httpHeaders 주입 확인
```

---

## 8. 관련 petcam-lab 문서

| 문서 | 내용 |
|------|------|
| [`docs/flutter-handoff.md`](flutter-handoff.md) | 전반 가이드 (D4 시점) — 데이터 모델, 엔드포인트 전체, 에러 코드 |
| [`docs/stage-d-cameras-learning.md`](stage-d-cameras-learning.md) | D1~D3 학습 노트 (Supabase/Fernet/다중 워커) |
| [`docs/stage-d5-tunnel-learning.md`](stage-d5-tunnel-learning.md) | Cloudflare Tunnel 개념 학습 |
| [`specs/stage-d1-auth-crypto.md`](../specs/stage-d1-auth-crypto.md) | AUTH_MODE 스위치 구현 스펙 |
| [`specs/stage-d-roadmap.md`](../specs/stage-d-roadmap.md) | Stage D 전체 로드맵 |

---

## 9. 응답 형식 (Flutter 에이전트 → petcam-lab 측)

이 문서 받은 뒤 응답할 때 아래 형식 권장:

```markdown
## 섹션 3.1 (확인 사항)
- BACKEND_URL: <현재 값>
- JWT 헤더 전송 여부: <확인 결과>

## 섹션 3.2 (보완 사항)
- 401 인터셉터: <기존/신규/필요 없음> + 사유
- video_player httpHeaders: <코드 위치>:<라인>
- CachedNetworkImage httpHeaders: <코드 위치>:<라인>

## 질문/이슈
- (있으면 기재)
```

이러면 petcam-lab 측에서 3.3 (환경 전환) 진행 시 무리 없이 이어받을 수 있음.
