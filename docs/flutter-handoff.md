# Flutter 인수인계 문서

> **독자:** `tera-ai-flutter` 레포에서 게코 캠 화면을 구현할 개발자 / 에이전트.
> **목적:** petcam-lab 백엔드가 지금 무엇을 제공하는지, Flutter 앱이 어디서 무엇을 호출해야 하는지 한 문서에서 파악.
> **현재 버전:** Stage D4 완료 시점 (2026-04-22). Stage D5 (Cloudflare Tunnel 배포) 전.
> **SOT:** 제품 기획은 [`../../tera-ai-product-master/docs/specs/petcam-b2c.md`](../../tera-ai-product-master/docs/specs/petcam-b2c.md), 백엔드 상세는 [`../../tera-ai-product-master/docs/specs/petcam-backend-dev.md`](../../tera-ai-product-master/docs/specs/petcam-backend-dev.md).

---

## 1. 시스템 구조

```
┌──────────────┐           ┌─────────────────────────────────┐
│              │  ① JWT    │                                 │
│  Flutter 앱  │◀─────────▶│   Supabase (메인 BaaS)           │
│              │  ② DB     │   - auth.users / user_profiles  │
│              │  ③ RLS    │   - pets / species              │
│              │           │   - cameras (SELECT/UPDATE/DELETE) │
│              │           │   - camera_clips (SELECT)       │
│              │           └─────────────────────────────────┘
│              │                       ▲
│              │                       │ service_role (INSERT)
│              │           ┌───────────┴─────────────────────┐
│              │  ④ JWT    │                                 │
│              │──────────▶│   petcam-lab backend (FastAPI)  │
│              │  ⑤ HTTP   │   - /cameras (CRUD + 연결 테스트) │
│              │  ⑥ mp4    │   - /clips (목록/메타/mp4/썸네일) │
└──────────────┘           │                                 │
                            │   RTSP ← 집 안 Tapo 카메라      │
                            └─────────────────────────────────┘
```

**세 계층의 역할:**

| 계층 | 역할 | Flutter 에서 직접 호출? |
|------|------|-------------------------|
| **Supabase Auth** | 로그인/회원가입/JWT 발급 | ✅ `supabase_flutter` SDK |
| **Supabase DB** | 펫/카메라 메타/클립 목록 **조회** | ✅ RLS 가 본인 데이터만 반환 |
| **petcam-lab backend** | 카메라 등록(암호화) + 영상 파일 스트리밍 + 썸네일 | ✅ HTTP (`http`/`dio`) |

---

## 2. 인증 흐름

### 기본 원칙

- **Supabase JWT** 1개로 Supabase DB 와 petcam-lab backend 둘 다 접근.
- Backend 는 `SUPABASE_JWKS_URL` 에서 공개키 받아 **RS256 검증**. 키 캐시 TTL 10분.
- JWT 의 `sub` claim 이 `user_id` → Backend 가 모든 API 에서 이걸 필터로 씀.

### Flutter 쪽 구현

```dart
// 1. Supabase SDK 로그인
final res = await supabase.auth.signInWithPassword(
  email: 'user@example.com',
  password: 'xxx',
);

// 2. 현재 세션 토큰
final jwt = supabase.auth.currentSession?.accessToken;

// 3. petcam-lab backend 호출 시 Authorization 헤더
final resp = await http.get(
  Uri.parse('$backendUrl/clips'),
  headers: {'Authorization': 'Bearer $jwt'},
);
```

### Dev / Prod 모드 (백엔드 측)

백엔드 `.env` 의 `AUTH_MODE` 로 전환:

| 모드 | Authorization 헤더 | 행동 |
|------|--------------------|------|
| `dev` | 무시 | 하드코딩 `DEV_USER_ID` 반환 — 로컬 개발 편의 |
| `prod` | 필수 | JWT 검증, `sub` → `user_id` |

**Flutter 개발 환경은 `dev` 로 띄운 backend 를 쓰는 게 편함** (JWT 없이 curl/앱 둘 다 테스트 가능). 앱 배포 직전 `prod` 로 전환.

### 토큰 만료

- Supabase access_token TTL 기본 1시간. `onAuthStateChange` 로 refresh 자동.
- Backend 는 만료된 토큰에 **401 AuthError** 반환 → Flutter 는 세션 갱신 후 재시도 로직 필요.

---

## 3. 역할 분리 — Supabase 직접 접근 vs Backend API

**가장 중요한 결정.** Flutter 에서 어떤 걸 Supabase SDK 로 바로 쓰고, 어떤 걸 Backend API 로 호출할지.

### ✅ Supabase 직접 접근 (SDK, RLS 가 보호)

| 동작 | 이유 |
|------|------|
| 펫 목록 (`pets` SELECT) | 단순 조회, 변형 없음 |
| 카메라 **조회/수정/삭제** (`cameras` SELECT/UPDATE/DELETE) | RLS 가 본인 행만 허용 |
| 클립 **목록/상세 메타** (`camera_clips` SELECT) | RLS 로 필터, 초고속 |
| 프로필 수정 (`user_profiles` UPDATE) | RLS |

**Dart 예시:**
```dart
final clips = await supabase
    .from('camera_clips')
    .select('*')
    .order('started_at', ascending: false)
    .limit(20);
```

### ❌ 반드시 Backend API 경유

| 동작 | 이유 |
|------|------|
| 카메라 **등록** (`POST /cameras`) | RTSP 연결 테스트 + 비번 Fernet 암호화 필요. DB 직접 INSERT 는 **RLS 정책 자체가 없어서 차단** |
| 카메라 **테스트 연결** (`POST /cameras/test-connection`) | `cv2.VideoCapture` 로 실 핸드쉐이크 — 서버만 가능 |
| 영상 **파일 스트리밍** (`GET /clips/{id}/file`) | HTTP Range 지원 mp4 — 서버 디스크 접근 |
| 영상 **썸네일** (`GET /clips/{id}/thumbnail`) | 서버 디스크 jpg 파일 |
| 카메라 **PATCH 중 비번 포함** 시 | 재암호화 |

**핵심:** 값을 **변형(암호화/파일 변환)** 하거나 **서버 자원(RTSP/디스크)** 이 필요하면 backend 경유. 단순 CRUD 는 Supabase 직결.

---

## 4. Backend API 엔드포인트 전체

Base URL:
- 로컬: `http://localhost:8000`
- prod (Stage D5 이후): `https://{subdomain}.trycloudflare.com`

### 4.1 헬스 / 상태

| Method | 경로 | 설명 |
|--------|------|------|
| GET | `/` | 생존 확인 |
| GET | `/health` | `{status, capture_attached, startup_error}` |
| GET | `/streams/{camera_id}/status` | 캡처 워커 실시간 상태 (디버깅용) |

### 4.2 카메라 (Stage D2)

| Method | 경로 | Body / Query | 성공 응답 |
|--------|------|--------------|----------|
| POST | `/cameras/test-connection` | `{host, port, path, username, password}` | 200 `{success, detail, elapsed_ms, frame_size}` |
| POST | `/cameras` | `{display_name, host, port, path, username, password, pet_id?}` | 201 `CameraOut` |
| GET | `/cameras` | — | 200 `CameraOut[]` (최신순) |
| GET | `/cameras/{id}` | — | 200 `CameraOut` |
| PATCH | `/cameras/{id}` | 부분 필드 (`password` 오면 재암호화) | 200 `CameraOut` |
| DELETE | `/cameras/{id}` | — | 204 |

**에러:**
- 400 — probe 실패 / PATCH body 비어있음
- 401 — JWT 없음/만료 (prod 모드)
- 404 — 본인 카메라 아님 또는 미존재
- 409 — `(user_id, host, port, path)` 유니크 위반

### 4.3 클립 (Stage C + D4)

| Method | 경로 | Query | 응답 |
|--------|------|-------|------|
| GET | `/clips` | `camera_id?`, `has_motion?`, `from?`, `to?`, `limit=50`, `cursor?` | `{items, count, next_cursor, has_more}` |
| GET | `/clips/{id}` | — | `ClipOut` |
| GET | `/clips/{id}/file` | Range 헤더 지원 | `video/mp4` (200 or 206) |
| GET | `/clips/{id}/thumbnail` | — | `image/jpeg` (200) |

**에러:**
- 404 — clip 미존재 / `thumbnail_path` NULL / 파일 디스크 없음 (`detail` 로 구분)
- 410 — `file_path` DB 에 있으나 디스크에서 사라짐 (mp4)
- 416 — Range 헤더 잘못됨

### 4.4 curl 치트시트

```bash
# 1) 카메라 등록
curl -X POST $BACKEND/cameras \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $JWT" \
  -d '{"display_name":"거실","host":"192.168.0.100","port":554,"path":"stream2","username":"admin","password":"xxx"}'

# 2) 클립 목록
curl "$BACKEND/clips?has_motion=true&limit=20" -H "Authorization: Bearer $JWT"

# 3) 썸네일
curl -o thumb.jpg "$BACKEND/clips/<uuid>/thumbnail" -H "Authorization: Bearer $JWT"

# 4) mp4 재생 (Range)
curl -H "Range: bytes=0-" "$BACKEND/clips/<uuid>/file" -H "Authorization: Bearer $JWT" -o clip.mp4
```

---

## 5. 데이터 모델

### `pets` (Flutter 직접 접근)

```dart
class Pet {
  final String id;                  // uuid
  final String userId;              // FK auth.users
  final String? speciesId;          // FK species
  final String name;
  final String speciesName;         // 예: "크레스티드 게코"
  final String? morph;
  final String sex;                 // 'male'|'female'|'unknown'
  final DateTime? birthDate;
  final DateTime? adoptionDate;
  final double? weight;
  final String? avatarUrl;
  final String? memo;
  final DateTime createdAt;
  final DateTime updatedAt;
}
```

### `cameras` (Flutter: SELECT/UPDATE/DELETE 직결, INSERT 는 API 경유)

```dart
class Camera {
  final String id;                  // uuid
  final String userId;
  final String? petId;
  final String displayName;
  final String host;
  final int port;                   // default 554
  final String path;                // default 'stream1', Tapo 는 'stream2' 권장
  final String username;
  // password_encrypted 는 절대 내려오지 않음 (backend 가 스키마 레벨에서 배제)
  final bool isActive;
  final DateTime? lastConnectedAt;
  final DateTime createdAt;
  final DateTime updatedAt;
}
```

### `camera_clips` (Flutter: SELECT 직결)

```dart
class Clip {
  final String id;                  // uuid
  final String userId;
  final String? petId;
  final String cameraId;            // Stage D2 까진 'cam-1' 같은 문자열, D3 이후 UUID FK 로 마이그레이션 예정
  final DateTime startedAt;         // 녹화 시작 UTC
  final double durationSec;         // 실측 60.0±
  final bool hasMotion;             // _motion.mp4 여부
  final int? motionFrames;          // 누적 motion 프레임 수
  final String filePath;            // REPO_ROOT 기준 상대. 앱은 안 씀 (API 로 받음)
  final int? fileSize;              // bytes
  final String? codec;              // 'avc1' 등
  final int? width;
  final int? height;
  final double? fps;
  final String? thumbnailPath;      // Stage D4 이전 NULL. 앱은 API URL 로 접근
  final DateTime createdAt;
}
```

**중요:**
- `filePath` / `thumbnailPath` 는 **앱이 직접 쓰지 않음**. 앱은 `$backendUrl/clips/$id/file` 과 `/clips/$id/thumbnail` URL 로 접근.
- `thumbnailPath == null` 인 레거시 클립은 앱에서 placeholder 이미지 표시.

---

## 6. Flutter 구현 힌트

### 6.1 비디오 재생 (`video_player`)

```dart
final controller = VideoPlayerController.networkUrl(
  Uri.parse('$backendUrl/clips/$clipId/file'),
  httpHeaders: {'Authorization': 'Bearer $jwt'},
);
await controller.initialize();
controller.play();
```

- `video_player` 플러그인이 내부적으로 HTTP Range 헤더를 알아서 보냄 (시크할 때).
- Backend 는 206 Partial Content 응답하고, 스트리밍이 매끄럽게 이어짐.
- JWT 만료 시 401 → 세션 갱신 후 컨트롤러 재생성 필요.

### 6.2 썸네일 로딩 (`cached_network_image`)

```dart
CachedNetworkImage(
  imageUrl: '$backendUrl/clips/$clipId/thumbnail',
  httpHeaders: {'Authorization': 'Bearer $jwt'},
  placeholder: (ctx, url) => Shimmer(...),
  errorWidget: (ctx, url, err) => Icon(Icons.image_not_supported), // thumbnail_path == null 레거시
);
```

### 6.3 무한 스크롤 (seek pagination)

```dart
Future<({List<Clip> items, String? nextCursor})> fetchPage(String? cursor) async {
  final url = Uri.parse('$backendUrl/clips').replace(queryParameters: {
    'limit': '20',
    if (cursor != null) 'cursor': cursor,
  });
  final resp = await http.get(url, headers: {'Authorization': 'Bearer $jwt'});
  final body = jsonDecode(resp.body);
  return (
    items: (body['items'] as List).map(Clip.fromJson).toList(),
    nextCursor: body['next_cursor'] as String?,
  );
}
```

**왜 cursor 방식?** `offset/limit` 는 페이지 깊어질수록 느려짐. `started_at < cursor` 는 인덱스 한 번 스캔으로 끝.

### 6.4 에러 처리 규약

| HTTP | 의미 | 앱 처리 |
|------|------|---------|
| 400 | 입력 검증 실패 | SnackBar + 필드 하이라이트 |
| 401 | JWT 만료/위조 | 세션 refresh 시도 → 실패 시 로그인 화면 |
| 404 | 리소스 없음 | Empty state 또는 "사라진 항목" UI |
| 409 | 중복 등록 | "이미 등록된 카메라" 다이얼로그 |
| 410 | 파일 사라짐 | 클립 리스트에서 제외 + "영상이 삭제되었어요" |
| 416 | Range 잘못 | (video_player 가 알아서 처리, 앱 코드 노출 드묾) |
| 502 | Supabase 연결 실패 | "잠시 후 다시 시도" + 자동 재시도 |

Backend 는 모든 오류를 `{detail: "..."}` JSON 으로 반환. detail 문자열은 로그용으로 적합, 유저에겐 친절한 번역 필요.

### 6.5 상태 관리 제안

- `flutter_riverpod` 또는 `bloc` 중 선택 — 프로젝트 규약 따름.
- `supabase_flutter` 의 `authStateChange` stream 구독 → 로그인 상태를 최상위 Provider 로.
- 클립 목록은 `PagingController` (`infinite_scroll_pagination`) 또는 커스텀 cursor 컨트롤러.

---

## 7. 로컬 개발 체크리스트

### 7.1 Backend 로컬 기동 (petcam-lab 저장소)

```bash
cd /Users/baek/petcam-lab
uv sync
cp .env.example .env
# .env 편집:
#   RTSP_URL=rtsp://<user>:<pw>@<camera-ip>:554/stream2
#   SUPABASE_URL=https://<ref>.supabase.co
#   SUPABASE_SERVICE_ROLE_KEY=<service_role>
#   DEV_USER_ID=<본인 auth.users.id>
#   AUTH_MODE=dev
#   CAMERA_SECRET_KEY=<Fernet key>
uv run uvicorn backend.main:app --reload
```

### 7.2 Flutter 앱 환경 변수

`.env` 또는 `--dart-define` 으로:
```
BACKEND_URL=http://localhost:8000
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_ANON_KEY=<anon key — 공개 가능>
```

**절대 서비스 롤 키를 앱에 넣지 말 것** — 그거면 RLS 우회돼서 다른 유저 데이터 노출됨. anon key 만 사용.

### 7.3 CORS 주의

- **현재 petcam-lab backend 에 CORS 미들웨어가 없음.**
- Flutter **Web** 빌드로 테스트할 거면 petcam-lab 측에서 `CORSMiddleware` 추가가 먼저 필요 (iOS/Android 네이티브는 CORS 제약 없어서 안 해도 됨).
- Web 지원 시점에 이슈 티켓 주면 petcam-lab 에서 추가 예정.

### 7.4 데이터 시드

1. Supabase Studio 에서 본인 계정으로 로그인 → `auth.users` 에 row 생성
2. `user_profiles` / `pets` 에 수동 INSERT (B2C 앱 쪽에서 자동 생성되는 경로 있으면 그 거 활용)
3. petcam-lab backend `.env` 의 `DEV_USER_ID` 를 그 UUID 로
4. Tapo 카메라 네트워크 연결 → backend 서버 켜면 1분 후 첫 클립 INSERT
5. `curl localhost:8000/clips` 로 row 확인

---

## 8. 제약 사항 & 향후 변경 예정

### 현재 제약

- **단일 카메라만 동작** — `backend/main.py` lifespan 이 `RTSP_URL` 하나만 읽어서 워커 1개. Stage D3 에서 DB 기반 다중 워커로 확장.
- **CORS 미설정** (Flutter Web 블록)
- **라이브 스트리밍 없음** — 지금은 녹화본 재생만. WebRTC/HLS 는 D5 이후 평가.
- **영상 유지 기간 정책 없음** — 디스크 무한 누적. Stage E retention job 과제.

### Stage D3 — 다중 캡처 (착수 시점 Flutter 영향)

- `camera_clips.camera_id TEXT` → `camera_uuid UUID REFERENCES cameras(id)` 마이그레이션 예정
- 앱의 클립 목록 필터링이 `camera_id` 문자열 → UUID 로 바뀜. **Dart 모델 타입 교체 필요.**
- 공지되면 모델 갱신.

### Stage D5 — Cloudflare Tunnel 배포

- `BACKEND_URL` 이 localhost → `https://xxx.trycloudflare.com` 으로 변경
- HTTPS 강제 (모바일 HTTP 차단 대응) — URL 교체만 하면 됨
- 맥북 잠자기 중엔 접속 불가 — 앱은 `/health` 주기 ping 으로 "서버 점검 중" 표시 고려

### 스키마 SOT 동기화

- 이 문서의 테이블 필드는 **작성 시점 snapshot**. 스키마 변경은 `tera-ai-product-master/docs/specs/petcam-backend-dev.md` 에 먼저 반영 → 양쪽 레포 갱신.
- 필드 불일치 감지되면 `tera-ai-product-master` 쪽이 기준.

---

## 9. 자주 나올 질문

**Q. 로그인 화면은 Supabase Auth UI 써도 되나?**
A. `supabase_flutter` 의 기본 UI 또는 자체 폼 둘 다 OK. JWT 만 받으면 backend 호출 가능.

**Q. 카메라 등록 flow 에서 "테스트 연결" 를 꼭 앞에 둬야 하나?**
A. 필수는 아니지만 UX 권장. `POST /cameras` 자체가 내부에서 한 번 더 probe 하니 생략해도 정확성은 동일. 단, 유저는 "등록 버튼 눌렀는데 5초 기다렸다 실패" 경험하게 됨.

**Q. 클립 목록을 Supabase 직결로 하면 backend 부하 절약?**
A. 맞음. 메타만 쓰면 Supabase 직결이 기본. backend `/clips` 는 동일 로직을 API 로 한 번 더 감싼 것(편의용). 앱은 Supabase 직결 + 파일/썸네일만 backend 경유가 표준.

**Q. JWT refresh 실패 시?**
A. `supabase.auth.onAuthStateChange` 의 `signedOut` 이벤트 구독 → 라우터 guard 로 로그인 화면 강제 이동.

**Q. 여러 펫 / 여러 카메라 UI 구조?**
A. 결정 6 (로드맵 문서) — **펫 중심**. 홈이 펫 카드 → 펫 탭 → 그 펫의 카메라 → 그 카메라의 클립 피드. `cameras.pet_id` 가 FK.

---

## 10. 참고 문서

- **제품 기획 (SOT):** [`tera-ai-product-master/products/petcam/README.md`](../../tera-ai-product-master/products/petcam/README.md)
- **Backend 개발 스펙 (SOT):** [`tera-ai-product-master/docs/specs/petcam-backend-dev.md`](../../tera-ai-product-master/docs/specs/petcam-backend-dev.md)
- **Stage D 로드맵 (petcam-lab):** [`../specs/stage-d-roadmap.md`](../specs/stage-d-roadmap.md)
- **Stage D1 JWT:** [`../specs/stage-d1-auth-crypto.md`](../specs/stage-d1-auth-crypto.md)
- **Stage D2 Cameras API:** [`../specs/stage-d2-cameras-api.md`](../specs/stage-d2-cameras-api.md)
- **Stage D4 썸네일:** [`../specs/stage-d4-thumbnail.md`](../specs/stage-d4-thumbnail.md)
- **Supabase Flutter SDK:** https://supabase.com/docs/reference/dart/introduction
- **video_player:** https://pub.dev/packages/video_player
- **cached_network_image:** https://pub.dev/packages/cached_network_image
- **infinite_scroll_pagination:** https://pub.dev/packages/infinite_scroll_pagination

---

## 11. 업데이트 로그

| 날짜 | 변경 | 작성 |
|------|------|------|
| 2026-04-22 | 초안 — Stage D4 완료 시점 기준 (JWT + cameras + clips + thumbnail) | petcam-lab 백엔드 세션 |

이후 스키마/엔드포인트 변경이 생기면 이 표에 한 줄 + 본문 해당 섹션 수정.
