# 용어집

> 이 레포에서 자주 튀어나오는 단어들. 도메인 / 영상 / 백엔드 순.

## 도메인 (게코 펫캠)

### 게코 (Gecko)
도마뱀의 한 분류. 크레스티드 게코 / 리오파드 게코 등이 펫으로 흔함. **야행성** → 사료 공급·교미·허물벗기 등 주요 이벤트가 새벽 시간대. 사람이 자는 동안 벌어지는 걸 타임머신처럼 돌려보는 게 이 앱의 핵심 가치.

### 펫캠 (Petcam)
반려동물 전용 CCTV. 이 프로젝트는 "도마뱀 특화" 펫캠 — 체온 유지 + 저조도 + 긴 무활동 시간이라는 게코 특성에 맞춰 설계.

### 테라리움 (Terrarium)
도마뱀 사육장. 투명 유리/아크릴 + 자동 온습도 관리. 카메라는 보통 테라리움 상단·측면에 고정.

---

## 영상 / 캡처

### RTSP (Real-Time Streaming Protocol)
IP 카메라가 영상을 스트리밍하는 업계 표준 프로토콜. URL 포맷 `rtsp://<user>:<pass>@<ip>:554/stream1`. Tapo C200 의 `stream1` = 1080p, `stream2` = 720p.

### 세그먼트 (Segment)
**1분짜리 mp4 파일 하나**. 이 레포에서 캡처 워커가 만드는 최소 단위. 저장 경로: `storage/clips/{date}/{camera_uuid}/{HHMMSS}_{motion|idle}.mp4`.

**왜 1분?** 너무 짧으면 파일 수 폭증 (/day 1440 ~ 수십GB 이상), 너무 길면 motion 판정 정밀도 저하. 1분이 MVP 의 균형점.

### 모션 / Motion
**유의미한 움직임**. 두 프레임 간 픽셀 변화율이 임계치 이상이고, 최소 연속 프레임 수 (N프레임 ≈ 1초 @ 12fps) 를 넘겨야 카운트. 세그먼트 총 motion 초가 `MOTION_SEGMENT_THRESHOLD_SEC` 이상이면 파일명 suffix 가 `_motion.mp4`.

튜닝 변수: [`docs/ENV.md #움직임 감지`](ENV.md#움직임-감지).

### CFR (Constant Frame Rate)
**일정 프레임레이트**. mp4 표준은 "FPS = 고정값" 전제. Tapo 가 주는 실 FPS 는 12 안팎에서 흔들리므로, 녹화 mp4 헤더의 FPS 메타와 실제 재생 속도가 다르면 "60초 녹화가 48초에 끝나는" 빨리감기 버그 발생.

**해결** — `measured_fps` 로 매 프레임 duration 을 계산해 writer 에 전달 (D5 이전 fix).

### Motion Run-length 필터
**연속 N 프레임 이상의 motion 만 유효**로 치는 필터. 개별 노이즈 프레임을 걸러냄. `MOTION_MIN_DURATION_FRAMES` (기본 12 ≈ 1초) 이상 연속돼야 카운트. 짧은 run 은 버림.

### 썸네일 (Thumbnail)
세그먼트 mp4 의 대표 프레임 jpg. Stage D4 에 추가됨.
- motion 클립: motion 이 시작된 프레임
- idle 클립: 세그먼트 중간 프레임
- 경로: mp4 와 같은 basename + `.jpg`
- 기존 D4 이전 클립은 `thumbnail_path = NULL`

### avc1 / mp4v (코덱)
mp4 파일의 비디오 압축 방식.
- **avc1 (H.264)** — 표준. Flutter `video_player`, 브라우저 `<video>`, iOS `AVPlayer` 전부 지원. 기본 fourcc.
- **mp4v (MPEG-4 Part 2)** — 구식. avc1 설정 실패 시 OpenCV 가 자동 fallback. 일부 플레이어 재생 불가 → 가능하면 avc1.

### fourcc
OpenCV VideoWriter 의 코덱 식별자 (4바이트 코드). 예: `cv2.VideoWriter_fourcc(*'avc1')`.

### probe_rtsp
카메라 등록 전에 RTSP 핸드쉐이크 + 첫 프레임 수신 여부 검증하는 3초짜리 체크. [`backend/rtsp_probe.py`](../backend/rtsp_probe.py). `POST /cameras/test-connection` + `POST /cameras` 에서 자동 호출.

### 해상도 (Tapo C200)
- `stream1` — 1920×1080 @ ~12fps (1080p)
- `stream2` — 1280×720 @ ~12fps (720p, **권장**)

해상도·FPS 는 소스마다 다름 → 런타임에 `cap.get(cv2.CAP_PROP_*)` 로 확인 ([`donts/python.md #10`](../.claude/rules/donts/python.md)).

---

## 백엔드 / 시스템

### 캡처 워커 (CaptureWorker)
RTSP 받아 mp4 세그먼트를 만드는 스레드 1개. 카메라 1대당 워커 1개 → `app.state.capture_workers: dict[camera_uuid, CaptureWorker]`. [`backend/capture.py`](../backend/capture.py).

### lifespan
FastAPI 의 앱 생애주기 컨텍스트 매니저. `startup` / `shutdown` 대체. `yield` 이전이 startup, 이후가 shutdown. 캡처 워커 N 개 기동·정지가 여기서 일어남. [`backend/main.py`](../backend/main.py).

### app.state
FastAPI 앱 레벨 싱글톤 저장소. `Depends()` 는 요청 스코프라 "앱 전체 공유 객체" 에 안 맞아서 대신 씀. 예: `app.state.capture_workers`, `app.state.pending_queue`.

### 펜딩 큐 / Pending Queue
Supabase INSERT 실패 시 재시도할 행들을 담아두는 JSONL 파일 (`storage/pending_inserts.jsonl`). 스레드 세이프 (threading.Lock). 최대 1000 줄 — 초과 시 가장 오래된 것 drop. [`backend/pending_inserts.py`](../backend/pending_inserts.py).

**flush 주기** — 서버 시작 1회 + 30초마다 주기. 네트워크 복구 시 자동 전송.

### 미러 / Clip Mirror
QA 테스터 계정이 오너 계정의 클립을 동일하게 조회하도록 복제 INSERT 하는 best-effort 훅. `clip_mirrors` 테이블 매핑 기반. 정식 공유 기능 아님, QA 종료 시 제거 대상. [`specs/feature-clip-mirrors-for-qa.md`](../specs/feature-clip-mirrors-for-qa.md).

### AUTH_MODE
인증 모드 환경변수.
- `dev` — JWT 검증 스킵, `DEV_USER_ID` 하드코딩. 로컬 / pytest 전용.
- `prod` — `Authorization: Bearer <JWT>` 필수, Supabase JWKS 로 검증. 외부 공개 배포 시 필수.

### JWT (JSON Web Token)
Supabase Auth 가 로그인 성공 시 발급하는 서명된 토큰. 3부분 (header.payload.signature, base64). Supabase 는 비대칭 서명 (현재 ES256/P-256, 과거 RS256).

### JWKS (JSON Web Key Set)
JWT 검증용 공개키 셋. `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` 에서 받음. 서버가 10분 TTL 로 캐시. `kid` (key ID) 로 매칭되는 공개키 찾아 서명 검증.

### kid
JWT header 의 key ID 필드. JWKS 의 어느 키로 서명됐는지 표시. 로테이션 시 달라짐.

### Fernet
**대칭키** 암호화 (AES-128-CBC + HMAC). `cryptography` 라이브러리. 양방향 필수인 카메라 RTSP 비번에 사용. 키 포맷: URL-safe base64 32바이트.

**bcrypt 와 비교** — bcrypt 는 단방향 해시라 원문 복구 불가 (비번 로그인 검증용). Fernet 은 양방향이라 복호화 가능 (우리가 RTSP 에 비번을 실제로 전달해야 하므로).

### service_role vs anon (Supabase 키)
| 키 | RLS | 용도 |
|----|-----|------|
| `anon` | **적용** | 브라우저/앱 코드 (Flutter). 본인 JWT 로 본인 데이터만 |
| `service_role` | **바이패스** | 서버 코드 (이 레포). 어느 user_id 로도 INSERT 가능 |

**절대 규칙** — service_role 키는 클라이언트 코드에 포함 금지.

### RLS (Row-Level Security)
Postgres 의 행 단위 권한 정책. `CREATE POLICY "User reads own clips" ON camera_clips FOR SELECT USING (auth.uid() = user_id)` 로 DB 레벨에서 본인 데이터만 필터링. 앱 코드가 `WHERE user_id = ?` 빼먹어도 데이터 안 샘.

### seek pagination
`?cursor=<started_at>` 커서 기반 페이지네이션. `started_at < cursor ORDER BY started_at DESC LIMIT N`. offset 방식보다 깊은 페이지에서 빠름 (항상 인덱스 한 번의 range scan).

### Range 요청
HTTP 표준. `Range: bytes=1048576-2097151` 로 파일 일부만 요청. FastAPI 기본 `StreamingResponse` 는 미지원이라 `GET /clips/{id}/file` 에서 직접 파싱 + 206 Partial Content 응답 구성.

### Cloudflare Tunnel (Reverse Tunnel)
**cloudflared** 데몬이 맥북 → Cloudflare 엣지로 outbound 연결을 유지하고, 외부 요청이 그 연결을 통해 내부로 전달되는 구조. 공유기 NAT / 포트포워딩 우회.
- **Quick Tunnel** — 임시 랜덤 URL (`*.trycloudflare.com`), 재시작 시 URL 변경.
- **Named Tunnel** — 본인 도메인 CNAME 연결, URL 고정 (`api.tera-ai.uk`).

### SOT (Source of Truth)
"유일 원천". 이 레포는 "어떻게 만들까" 만, 제품 기획·스펙 SOT 는 `tera-ai-product-master` 레포 ([`CLAUDE.md`](../CLAUDE.md)).

### CAOF (Claude Agent Orchestration Framework)
사용자의 전역 AI 협업 프레임워크. `/Users/baek/ideaBank/frameworks/claude-agent-orchestration.md`. 이 레포에 v1.2 스니펫 적용. 주요 원칙: 제한보다 전략, 대규모 변경은 순차 처리, 재시도 최대 3회.

### Diátaxis
문서 정보 아키텍처 프레임워크. 4분법: **Tutorial** (학습) / **How-to** (문제 해결) / **Reference** (정보) / **Explanation** (개념). 이 레포의 `docs/FEATURES.md` (Explanation) ↔ `docs/API.md` (Reference) ↔ `docs/DEPLOYMENT.md` (How-to) 분리에 참고.

---

## 약어

| 약어 | 풀이 |
|------|------|
| ATS | App Transport Security (iOS). HTTPS 강제 |
| CFR | Constant Frame Rate |
| CRUD | Create / Read / Update / Delete |
| DI | Dependency Injection |
| ES256 | ECDSA w/ SHA-256 (JWT 서명 알고리즘) |
| FK | Foreign Key |
| FPS | Frames Per Second |
| JWT | JSON Web Token |
| JWKS | JSON Web Key Set |
| LAN | Local Area Network |
| NAT | Network Address Translation |
| OSS | Open Source Software |
| PK | Primary Key |
| RLS | Row-Level Security |
| RS256 | RSA w/ SHA-256 |
| RTSP | Real-Time Streaming Protocol |
| SOT | Source of Truth |
| TTL | Time To Live |
| URI | Uniform Resource Identifier |
| URL | Uniform Resource Locator |
| UUID | Universally Unique Identifier |
| VCS | Version Control System |
