# Flutter Cloud Handoff — petcam 앱 라벨/하이라이트 통합

> Flutter 앱 (`/Users/baek/myProjects/tera-ai-flutter`) 에서 새 백엔드 contract 에 맞춰 (1) 모든 클립에 라벨 chip 표시 (2) "하이라이트" 탭 추가 (3) R2 signed URL 영상 재생 (4) 라벨링 웹 deep link (admin 전용 옵션) 를 구현하는 작업서. **Flutter 측 새 Claude 세션에 그대로 넘겨주는 contract.**

**상태:** 🚧 진행 중 (백엔드 contract freeze 완료, **VLM 워커 fly.io 가동 시작** 2026-05-07, Flutter PR 대기)
**작성:** 2026-05-07
**대상 레포:** `/Users/baek/myProjects/tera-ai-flutter`
**상위 spec:** [`cloud-migration-roadmap.md`](cloud-migration-roadmap.md)
**연관 SOT:** `../../tera-ai-product-master/docs/specs/petcam-b2c.md`

**백엔드 가동 상태 (2026-05-07 기준)**
- API 서버 (`api.tera-ai.uk`) — Cloudflare Tunnel, 사용자 맥북 의존 (현재 일시 중지 가능)
- VLM 워커 (`petcam-vlm-worker.fly.dev`) — **fly.io always-on, 24/7 가동**. 모션 클립 들어오면 60초 안에 자동 라벨 INSERT
- R2 (영상 스토리지) — Cloudflare, signed URL 발급 가동
- 라벨링 웹 (`label.tera-ai.uk`) — 로컬 dev 가동, Vercel 배포 대기

**Flutter 가 곧바로 만들 수 있는 것:** VLM 워커가 자동 라벨 채우니까 라벨 chip / 하이라이트 탭의 데이터 채워짐. 단 `/me/is_labeler`, `/clips/highlights` endpoint 는 백엔드 미구현 — Flutter 시작 전 사용자에게 백엔드 작업 요청 필요.

## 1. 목적 — 시나리오 매트릭스

| 시나리오 | 누가 | 어디서 | 권한 |
|---------|------|--------|------|
| **A. 자동 라벨 보기** | 모든 유저 | 클립 상세 화면 | RLS — 본인 클립만 |
| **B. 라벨 수정 (HITL)** | **admin/staff** (`labelers` 멤버) | **라벨링 웹 (`label.tera-ai.uk`)** — Flutter 안 만듦 | labelers 멤버만 |
| **C. 하이라이트 피드** | 모든 유저 | 새 탭 또는 새 화면 | RLS — 본인 클립 + 행동 라벨 필터 |

**핵심 결정 (`cloud-migration-roadmap.md` §4-6):** 라벨 수정 UI 는 Flutter 에 안 만든다. 라벨링 웹이 이미 admin 도구로 가동 — 같은 UI 두 곳 만드는 건 중복 + 일반 유저는 어차피 권한 없음.

## 2. 스코프

### In
1. **클립 상세에 라벨 chip 표시** — VLM 자동 라벨 (회색·노랑) + human override 라벨 (초록). 하나만 있으면 그것만, 둘 다면 human 우선 + VLM "원본" 부가 표시.
2. **새 "하이라이트" 탭** — 행동 라벨 (`action ∉ {moving, unknown}`) 클립만 필터. `home → pet → camera → 하이라이트 탭` 위치.
3. **영상 재생 R2 signed URL 전환** — `VideoPlayerController.networkUrl(httpHeaders: ...)` 제거 → backend `/clips/{id}/file/url` 호출 → 응답의 `url` 을 헤더 없이 재생.
4. **`label_repository` 신규** — backend `GET /clips/{id}/labels`, `GET /clips/{id}/inference` 호출 + 도메인 모델.
5. **`is_labeler` provider** — admin/staff 여부. true 면 라벨링 웹 deep link 버튼 노출 (선택).
6. **회귀 0** — 기존 동작 (카메라 등록·삭제·클립 피드·재생) 모두 그대로.

### Out
- Flutter 안에 라벨 수정 UI (관리자/스태프는 라벨링 웹 사용 — `cloud-migration-roadmap.md` §4-6)
- HITL ping (별도 spec, 미착수)
- 라벨 충돌 resolution UI (다중 라벨러 합의)
- 새 인증 흐름 (Supabase JWT 그대로)
- petcam 외 다른 feature (my_pets, chat, wiki 등) — 변경 0

## 3. 백엔드 Contract — Flutter 가 호출할 API

이 섹션이 Flutter 측 작업의 입력. 모든 endpoint 는 `Authorization: Bearer <Supabase JWT>` 헤더 필요 (현재와 동일).

### 3-1. 영상/썸네일 URL — JSON

**기존 (변경 대상):**
```dart
// clip_repository.dart
String fileUrl(String clipId) => '$_backendUrl/clips/$clipId/file';
String thumbnailUrl(String clipId) => '$_backendUrl/clips/$clipId/thumbnail';

// VideoPlayerController.networkUrl(Uri.parse(url), httpHeaders: { 'Authorization': 'Bearer ...' })
```

**신규:**
```
GET /clips/{clip_id}/file/url
Response 200:
{
  "url": "https://<account>.r2.cloudflarestorage.com/...?X-Amz-Signature=...",
  "ttl_sec": 3600,
  "type": "r2"  // 또는 "local" (개발 fallback)
}

GET /clips/{clip_id}/thumbnail/url   // 같은 패턴
```

**Flutter 사용:**
```dart
// 1) JSON 으로 signed URL 받기 (Authorization 필요)
final res = await http.get(
  Uri.parse('$backend/clips/$clipId/file/url'),
  headers: {'Authorization': 'Bearer $jwt'},
);
final signedUrl = (jsonDecode(res.body) as Map)['url'] as String;

// 2) signed URL 자체는 토큰 박혀있어 헤더 불필요
final controller = VideoPlayerController.networkUrl(Uri.parse(signedUrl));
// httpHeaders 제거!
```

**왜 바뀌었나?** signed URL 은 1시간 단발 토큰 자체가 인증 → `<video src>` / `VideoPlayerController` 둘 다 헤더 안 박아도 됨. 동시에 백엔드는 영상 byte 스트리밍 부담 X (R2 가 직접 서빙).

**참고 코드:** `backend/routers/clips.py:224` (`get_clip_file_url`)

### 3-2. 라벨 조회

```
GET /clips/{clip_id}/labels
Response 200: list of LabelOut
[
  {
    "id": "uuid",
    "clip_id": "uuid",
    "labeled_by": "uuid (auth.users.id)",
    "action": "eating_paste",
    "lick_target": "dish",  // null 가능
    "note": "...",          // null 가능
    "labeled_at": "2026-05-07T..."
  }
]
```

**권한:** clip owner 면 모든 라벨러 결과, 라벨러 본인이면 본인 것만, 외부인은 404.

**Flutter 사용:** 일반 유저 = 본인 클립만 → 본인이 owner → 다른 라벨러 (admin/staff) 가 단 라벨도 다 보임.

### 3-3. VLM 추론 결과 조회

```
GET /clips/{clip_id}/inference
Response 200:
{
  "id": "uuid|null",
  "clip_id": "uuid",
  "action": "eating_paste",
  "source": "vlm",
  "confidence": 0.87,
  "reasoning": "...",
  "vlm_model": "gemini-2.5-flash",
  "created_at": "..."
}
또는 null (추론 없음 — 워커가 아직 못 돌렸거나 영구 실패)
```

**권한:** clip owner 만. 라벨러 (비-owner) → 403. 일반 유저는 본인 클립만 보므로 항상 owner.

### 3-4. 하이라이트 클립 목록 (백엔드 endpoint 신규 — 별도 spec 에서 추가)

**제안 — 이 spec 의 일부로 백엔드에 추가:**
```
GET /clips/highlights?cursor=<started_at>&limit=50&pet_id=<uuid>
Response 200:
{
  "items": [
    {
      "clip": { ...camera_clips row... },
      "label": {
        "action": "eating_paste",
        "source": "vlm" | "human",
        "confidence": 0.87  // VLM 인 경우만
      }
    }
  ],
  "next_cursor": "...",
  "has_more": true
}
```

**서버 쿼리:**
```sql
SELECT c.*, b.action, b.source, b.confidence
FROM camera_clips c
JOIN behavior_logs b ON b.clip_id = c.id
WHERE c.user_id = auth.uid()
  AND b.action NOT IN ('moving', 'unknown')
  AND b.source IN ('vlm', 'human')
ORDER BY c.started_at DESC, b.created_at DESC
LIMIT 50;
```

**우선순위 (같은 clip 에 vlm + human 둘 다):** human 우선. SQL `DISTINCT ON (clip_id)` 또는 서버 코드에서 dedup.

**대안 (이번 spec Out):** Flutter 클라이언트 단 필터 — 모든 clip + 라벨 join 하지 말고 클라이언트에서 행동 라벨만 골라 보여줌. 단점: 페이지네이션 정합성 깨짐 + 응답 양 ↑ → 서버 endpoint 권장.

### 3-5. labeler 여부 — 신규 endpoint

```
GET /me/is_labeler
Response 200:
{
  "user_id": "uuid",
  "is_labeler": true,
  "added_at": "..."  // null 가능
}
```

**용도:** Flutter 에서 "라벨링 웹 열기" 버튼 표시/숨김. 일반 유저 = false → 버튼 없음.

**서버 구현:** `labelers` 테이블 SELECT (service_role) — `clip_perms.is_labeler(user_id, sb)` 헬퍼 이미 있음.

## 4. Flutter 코드 변경 매트릭스

### 4-1. 새 도메인 모델 (`lib/features/my_cage/domain/`)

```dart
// behavior_label.dart — human 라벨 (admin/staff 가 라벨링 웹에서 작성)
class BehaviorLabel {
  final String id;
  final String clipId;
  final String labeledBy;
  final ActionType action;
  final LickTarget? lickTarget;
  final String? note;
  final DateTime labeledAt;
}

// behavior_inference.dart — VLM 자동 추론 (워커가 작성)
class BehaviorInference {
  final String? id;
  final String clipId;
  final ActionType action;
  final double? confidence;
  final String? reasoning;
  final String? vlmModel;
  final DateTime? createdAt;
}

// action_type.dart — 9 raw class enum
enum ActionType {
  eatingPaste, drinking, moving, unknown,
  eatingPrey, defecating, shedding, basking, unseen,
}

// 표시 매핑 (UX 통합 — drinking + eatingPaste → "feeding")
extension ActionTypeDisplay on ActionType {
  String get displayLabel { ... }   // "밥 먹는 중", "음수", "움직임" ...
  Color get displayColor { ... }    // 라벨별 색
  bool get isHighlight {            // moving, unknown 외 = 하이라이트
    return this != ActionType.moving && this != ActionType.unknown;
  }
}
```

### 4-2. 새 리포지토리 (`lib/features/my_cage/data/`)

**`label_repository.dart` 신규:**
```dart
class LabelRepository {
  final String backendUrl;
  final TokenProvider tokenProvider;

  Future<List<BehaviorLabel>> listLabels(String clipId);
  Future<BehaviorInference?> getInference(String clipId);  // null 가능
}
```

**`clip_repository.dart` 수정:**
- `fileUrl(id)` 시그니처 변경 — sync `String` → async `Future<String>` (`/file/url` 호출 후 url 추출).
- `thumbnailUrl(id)` 동일.
- 또는 함수명 바꿔서 명확히: `Future<ClipPlaybackUrl> getPlaybackUrl(String id)` + `Future<String> getThumbnailUrl(String id)`.

**`me_repository.dart` 신규 (또는 기존 user provider 확장):**
- `Future<bool> isLabeler()` — `/me/is_labeler` 호출 + 캐시 (앱 세션 동안 1회).

**`highlights_repository.dart` 신규:**
- `Future<HighlightsPage> listHighlights({String? cursor, int limit, String? petId})`.

### 4-3. UI 변경 매트릭스

| 화면 | 변경 |
|------|------|
| `clip_player_screen.dart` | (a) `getPlaybackUrl()` 호출로 signed URL 받기 (b) `httpHeaders` 제거 (c) 화면 하단에 라벨 chip section 추가 (LabelRepository + InferenceRepository 병렬 호출) (d) `is_labeler == true` 면 "라벨링 웹에서 수정" deep link 버튼 |
| `clip_feed_screen.dart` (camera_detail 안) | 각 클립 thumbnail 위에 라벨 chip 미니 (선택 — 인디케이터로) |
| `my_cage_screen.dart` 또는 `camera_detail_screen.dart` | 새 탭 "하이라이트" 추가 — `HighlightsRepository.listHighlights()` 호출. 페이지네이션은 기존 ClipPage 와 동일 패턴 |
| `home_screen.dart` (또는 펫 진입점) | 선택 — "오늘 하이라이트 N건" 위젯 |

### 4-4. 라벨 chip 디자인 (제안)

```
┌─────────────────────────────────────────────┐
│ [영상 플레이어]                              │
├─────────────────────────────────────────────┤
│ 자동 분석                                    │
│  🟢 [밥 먹는 중] (confidence 87%)            │
│  💬 "그릇 위에서 혀를 내미는 모습 관찰"       │
├─────────────────────────────────────────────┤
│ 검수 라벨 (관리자 확인)                      │
│  ✅ [밥 먹는 중] · 음수 대상: 그릇            │
│  📝 "다른 표현 가능 — 핥기"                  │
├─────────────────────────────────────────────┤
│ [라벨링 웹에서 보기 →]  ← admin/staff 만     │
└─────────────────────────────────────────────┘
```

**우선순위 표시:**
- VLM 만 있음 → 자동 분석 chip만
- human 만 있음 → 검수 라벨 chip 만 (이런 케이스 거의 없음 — 보통 VLM 먼저 돌고 검수)
- 둘 다 있음 + 같은 라벨 → 검수 라벨에 ✅
- 둘 다 있음 + 다른 라벨 → 둘 다 표시, 검수가 위 (human override)

### 4-5. Provider 구조 (Riverpod)

```dart
// 새 provider
final labelRepositoryProvider = Provider<LabelRepository>((ref) => ...);
final clipLabelsProvider = FutureProvider.family<List<BehaviorLabel>, String>(
  (ref, clipId) async => ref.watch(labelRepositoryProvider).listLabels(clipId),
);
final clipInferenceProvider = FutureProvider.family<BehaviorInference?, String>(
  (ref, clipId) async => ref.watch(labelRepositoryProvider).getInference(clipId),
);
final isLabelerProvider = FutureProvider<bool>((ref) async {
  return ref.watch(meRepositoryProvider).isLabeler();
});
final highlightsProvider = StateNotifierProvider<HighlightsNotifier, AsyncValue<HighlightsPage>>(...);
```

## 5. 작업 순서 (제안)

### Phase 1 — 백엔드 contract 검증 (Flutter 작업 시작 전)
- [ ] 백엔드 `GET /clips/{id}/file/url` 응답 확인 (Postman/curl)
- [ ] 백엔드 `GET /clips/{id}/labels` 응답 확인
- [ ] 백엔드 `GET /clips/{id}/inference` 응답 확인
- [ ] 백엔드 `GET /me/is_labeler` 신규 endpoint 추가 + 검증
- [ ] 백엔드 `GET /clips/highlights` 신규 endpoint 추가 + 검증

### Phase 2 — Flutter 도메인/데이터 레이어 (회귀 0 보장)
- [ ] `BehaviorLabel`, `BehaviorInference`, `ActionType` 도메인 모델
- [ ] `LabelRepository` + `MeRepository` + `HighlightsRepository`
- [ ] `clip_repository.dart` 의 fileUrl/thumbnailUrl async 전환 + 기존 호출부 await 추가
- [ ] 단위 테스트 — repository fake response 로 모델 직렬화 확인

### Phase 3 — UI (시각 검증)
- [ ] `clip_player_screen` 에 라벨 chip section
- [ ] `clip_player_screen` 에 signed URL 영상 재생 (기존 httpHeaders 제거)
- [ ] is_labeler 일 때 "라벨링 웹 deep link" 버튼
- [ ] 새 "하이라이트" 탭 또는 화면

### Phase 4 — 통합 검증
- [ ] 일반 유저 (`bss.rol20@...`) 로그인 → 클립 재생 + 라벨 chip 보임
- [ ] 같은 계정으로 하이라이트 탭 → 행동 라벨 클립만 표시
- [ ] labeler 멤버로 가능하다면 deep link 버튼 노출 확인
- [ ] 백엔드 컷오버 안 한 상태에서도 기존 흐름 동작 (API 응답 형식 호환)

## 6. 검증 기준

### 6-1. 회귀 가드
- 기존 카메라 등록/삭제/클립 피드/재생 모두 동작 (변경 0).
- 기존 인증/스플래시/홈/펫 흐름 변경 0.
- iOS / Android 빌드 + Cloudflare Tunnel API (`api.tera-ai.uk`) 호출 양쪽 동작.

### 6-2. 신규 기능 검증
- 모션 클립 1건 재생 시 라벨 chip 보임 (VLM 또는 human).
- 라벨 없는 클립도 재생은 됨 (chip 영역 비어있거나 "분석 중").
- 하이라이트 탭에 행동 라벨 클립만 보임 (`moving` / `unknown` 안 보임).
- `is_labeler=false` 인 일반 유저에는 라벨링 웹 deep link 버튼 노출 안 됨.

### 6-3. 검증 못 하는 항목 (사용자 명시)
- VLM 워커 가동 전엔 라벨이 안 붙어있는 클립이 대부분 — Flutter 측 시각 검증은 PoC 시절 라벨 (`web/src/app/api/inference/route.ts` 가 만든 row) 기준.
- 백엔드 분리 (capture worker extraction) 시점은 Flutter 와 무관 — 백엔드 endpoint 시그니처만 같으면 OK.

## 7. 학습 노트 (Flutter 측 에이전트용)

- **Supabase JWT + Cloudflare Tunnel** — 현재 Flutter 는 Supabase Auth 로 로그인 → JWT 를 백엔드 (`api.tera-ai.uk`) 와 Supabase DB 양쪽에 보냄. 이 흐름 변경 X.
- **R2 signed URL 의 의미** — 1시간 유효한 단발 토큰. 헤더 인증 불필요. 영상 재생 컨트롤러에 그대로 박으면 됨.
- **`labelers` 화이트리스트 = admin/staff role** — 별도 enum/role 없음. 이 테이블 멤버 = 어드민. 비-멤버 = 일반 유저.
- **하이라이트 = 행동 라벨 클립** — `moving`/`unknown` 외 라벨이 붙은 클립. "이상행동만"이 아니라 "의미있는 행동 = 식사/배변/허물벗기 등 모두" 포함.
- **라벨 수정 UI 가 Flutter 에 없는 이유** — 라벨링 웹 (label.tera-ai.uk) 이 admin 도구로 이미 가동. 같은 UI 두 번 만들 필요 X. 사용자 명시 결정.

## 8. 참고

- 상위 spec: [`cloud-migration-roadmap.md`](cloud-migration-roadmap.md) §4-6 (라벨링 분리), §4-7 (하이라이트 정의), §4-5 (labelers=admin)
- 백엔드 코드:
  - [`backend/routers/clips.py:224`](../backend/routers/clips.py) — `/file/url`
  - [`backend/routers/labels.py:121`](../backend/routers/labels.py) — `/clips/{id}/labels`, `/clips/{id}/inference`
  - [`backend/clip_perms.py`](../backend/clip_perms.py) — `is_labeler` 헬퍼 (신규 endpoint 시 사용)
- Flutter 현재 코드:
  - `lib/features/my_cage/data/clip_repository.dart` — fileUrl 변경 대상
  - `lib/features/my_cage/data/camera_repository.dart` — 변경 0
  - `lib/features/my_cage/presentation/clip_player_screen.dart` — 라벨 chip 추가 + httpHeaders 제거
  - `lib/features/my_cage/presentation/my_cage_screen.dart` — 하이라이트 탭 (선택)
- 기존 핸드오프: [`../docs/learning/flutter-handoff.md`](../docs/learning/flutter-handoff.md) — 현재 인증/통신 흐름
- 락인: VLM v3.5 prompt, 85.5% floor (모델/프롬프트 변경 금지)
- 라벨링 웹 (참조용): [`../web/src/app/labeling/[clipId]/page.tsx`](../web/src/app/labeling/[clipId]/page.tsx)
