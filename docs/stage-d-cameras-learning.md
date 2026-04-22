# Stage D (D1~D3) 학습 노트 — "내 계정에 카메라 연결하기" 전체 흐름

> 오늘 한 걸 한 번 더 처음부터 훑는 복습 자료. **비유 + 다이어그램 위주**, 코드는 최소.
> 전부 소화 못 해도 OK. **TL;DR → 우선순위 1~3** 만 먼저 읽고 나머진 필요할 때 돌아오기.

## TL;DR (5줄)

1. **Supabase 는 "로그인·DB·권한관리"** 를 통째로 해주는 서비스. 우리는 여기 4개 테이블(`auth.users`, `pets`, `cameras`, `camera_clips`) 을 썼다.
2. **카메라 비밀번호는 평문 저장 절대 금지** → Fernet 대칭암호로 암호화해서 DB 에 넣고, 서버 시작할 때 복호화해서 RTSP URL 에 끼운다.
3. **`POST /cameras`** 는 "연결 테스트 → 성공 시에만 암호화 저장" 안전장치 2단계로 돌아감.
4. **서버 시작 시 `cameras` 테이블을 SELECT** → 활성 카메라 1대마다 **독립 스레드(CaptureWorker)** 를 띄운다. cam1·cam2 동시 녹화가 이래서 가능.
5. **녹화된 mp4 + 썸네일 jpg** 는 파일로 디스크에, **메타데이터(언제·어디·몇초·motion 여부)** 는 `camera_clips` 테이블에. 앱이 보여주는 "클립 목록" 의 원천.

## 오늘의 타임라인

```
[D1] Auth/암호화 인프라       ─→  JWT 검증 + Fernet 래퍼
[D2] /cameras CRUD API        ─→  카메라를 DB에 안전하게 등록
[D3] 다중 캡처 워커           ─→  cameras 테이블 → 워커 N개
[D4] 썸네일 파이프라인        ─→  클립 옆에 jpg 저장
```

오늘 끝낸 작업 순서대로 따라가며 아래 개념들을 배웠다.

## 우선순위

| # | 주제 | 왜 중요한가 |
|---|------|-----------|
| 1 | [Supabase 계정·유저 구조](#1-supabase-계정과-유저-구조) | 모든 데이터의 소유권 기준 |
| 2 | [4개 테이블의 관계](#2-4개-테이블의-관계) | DB 스키마 전체 지도 |
| 3 | [카메라 비밀번호 암호화](#3-카메라-비밀번호-암호화-왜-fernet) | 평문 저장이 왜 재앙인지 |
| 4 | [POST /cameras 흐름](#4-post-cameras-내부-흐름) | "등록" 클릭 한 번이 실제로 하는 일 |
| 5 | [서버 기동 → 다중 워커](#5-서버-기동--다중-캡처-워커) | cam1+cam2 동시에 도는 마법 |
| 6 | [녹화 → DB insert 흐름](#6-녹화-세그먼트--db-insert-흐름) | 디스크 vs DB 역할 분담 |
| 7 | [오늘 만든 실제 UUID 들](#7-오늘-만든-실제-uuid-레퍼런스) | 디버깅할 때 참고 |

---

## 1. Supabase 계정과 유저 구조

### 한 줄 요약
Supabase 는 회원가입하면 `auth.users` 테이블에 행이 하나 생기고, 그 행의 **UUID** 가 당신의 "영구 식별자". 모든 다른 데이터(펫·카메라·클립) 는 이 UUID 로 연결된다.

### 비유
```
Supabase 의 auth.users = 주민등록 원부
├── 당신 ID:  380d97fd-cb83-4490-ac26-cf691b32614f
├── 이메일: (로그인용)
└── 비번 해시: (Supabase 가 관리, 우리 서버 접근 불가)

→ 이 UUID 가 "내 집 주소" 같은 거. 모든 소유물은 이 주소에 붙는다.
```

### 왜 이게 중요?
- **RLS (Row Level Security)**: Postgres 가 자동으로 `WHERE user_id = auth.uid()` 를 모든 쿼리에 끼워넣음 → A 유저가 실수로 B 유저 데이터 볼 일 없음.
- 우리 서버는 `service_role` 키로 RLS 를 우회하지만 **코드 안에서 명시적으로** `eq("user_id", dev_user_id)` 필터 건다. 안전장치 이중화.

---

## 2. 4개 테이블의 관계

### ER 다이어그램 (글로)

```
auth.users  (Supabase 가 관리)
    │  id (UUID) — 당신의 영구 ID
    │
    ├──┬──────────────┬─────────────┐
    │  │              │             │
    ▼  ▼              ▼             ▼
  pets         cameras      camera_clips  (← 앱 영상 메타)
    │            │               │
    │            │  pet_id       │  camera_id (FK, D3 이후 UUID)
    └────────────┴────────┬──────┘
                          │  pet_id
                          └─── "이 클립은 누구의 모습이냐"
```

### 각 테이블이 뭐 하는 애인지

| 테이블 | 한 줄 역할 | 오늘 기준 행 수 |
|--------|-----------|----------------|
| `auth.users` | 로그인 아이디 (Supabase 관리) | 2 (본인 + 다른 테스트 계정) |
| `pets` | 키우는 동물 정보 (이름·종·생일) | 3 (테스트1 / 크랑이 / 릴잔틱숫) |
| `cameras` | RTSP 카메라 등록 정보 (비번은 암호화) | 2 (cam1 / cam2) |
| `camera_clips` | 녹화된 세그먼트 메타데이터 | 녹화될수록 증가 |

### 왜 이렇게 쪼갰나? (JS/TS 비유)
- `auth.users` = Firebase Auth 같은 "로그인 전담"
- `pets` / `cameras` / `camera_clips` = Prisma 로 치면 각각 model 1개씩
- **관계형 DB 의 장점**: 카메라 1대 삭제 → `ON DELETE CASCADE` 로 그 카메라의 클립도 자동 삭제 (D3 마이그레이션에서 설정). 참조 정합성 보장.

---

## 3. 카메라 비밀번호 암호화 — 왜 Fernet?

### 문제 상황
```python
# ❌ 나쁜 예 — 평문으로 DB 에 저장
cameras.insert({"password": "12345677"})

# 만약 DB 덤프가 유출되면?
# → 모든 유저의 RTSP 비번이 통째로 공격자에게.
# → 사용자 Wi-Fi 안 카메라가 라이브로 해킹됨.
```

### 해결: Fernet 대칭암호화
```
사용자 입력  →  [Fernet.encrypt(key)]  →  암호문  →  DB 저장
                                        └─ "gAAAABh7..." 같은 base64

서버 시작    →  DB 에서 암호문 읽기  →  [Fernet.decrypt(key)]  →  평문  →  RTSP URL 조립
```

### 핵심 포인트
- **`CAMERA_SECRET_KEY`** 는 `.env` 에만. 코드·DB 어디에도 없음.
- 키 분실 = 모든 암호문 복호화 불가 = 카메라 전수 재등록. **1Password 에 백업 필수.**
- **대칭키**: 같은 키로 암호화·복호화. 서버 1대 운영이라 비대칭(공개/개인키) 필요 없음.

### JS 비유
```typescript
// 유사 라이브러리: Node.js crypto.createCipheriv('aes-256-gcm', ...)
// Fernet 은 "AES-128-CBC + HMAC-SHA256" 를 한 패키지로 묶은 것.
// 매번 IV 생성·인증태그 붙이기·base64 변환을 자동화 → 실수 줄임.
```

---

## 4. `POST /cameras` 내부 흐름

사용자 관점에선 "카메라 등록" 버튼 한 번. 내부에선:

```
[앱]  curl -X POST /cameras
       {"host":"192.168.219.107", "username":"...", "password":"12345677"}
  │
  ▼
[1] FastAPI 가 요청 받음 → Pydantic 으로 body 검증
[2] 서버가 직접 RTSP 연결 테스트 (cv2.VideoCapture)
     ├─ 첫 프레임 받으면 → 성공
     └─ 3초 timeout 또는 실패 → 400 에러 반환 (DB 저장 안 함)
[3] 테스트 통과 시에만 Fernet.encrypt(password) → 암호문
[4] Supabase INSERT: 암호문 + host/port/path/username/pet_id
     └─ 응답에는 password_encrypted 필드 자체가 없음 (Pydantic 스키마에서 제외)
[5] 앱에 201 + UUID 반환
```

### 왜 2단계인가? (test → save)
- "등록했는데 나중에 연결 안 됨" 상황 방지.
- DB 에 저장된 카메라는 **최소한 한 번은 연결 확인됨** 이란 보장.
- 비유: 회원가입 시 이메일 인증 필수로 거는 것과 같은 논리.

---

## 5. 서버 기동 → 다중 캡처 워커

### "서버 하나에 카메라 여러 대" 가 어떻게 가능한가?

```
uvicorn 프로세스 1개
├── main 스레드      (HTTP 요청 받기: /health, /clips, /cameras)
├── 워커 스레드 1    (cam1 의 RTSP 계속 읽기 · 60초마다 mp4 저장 · DB insert)
├── 워커 스레드 2    (cam2 동일 작업, 독립)
└── 비동기 task      (pending insert 재시도 30초마다)
```

### 시작 시 일어나는 일 (`backend/main.py` lifespan)

```
1. .env 읽기 → Supabase 연결
2. DEV_USER_ID 본인의 UUID 확인
3. cameras 테이블 SELECT where user_id=나 and is_active=true
   → [cam1 row, cam2 row] 받음
4. 각 row 마다:
   a. Fernet.decrypt(password_encrypted) → 평문 비번
   b. rtsp://username:password@host:port/path 조립
   c. CaptureWorker(...) 생성 → .start() 호출 → 스레드 1개 뜸
   d. app.state.capture_workers[row.id] = worker  # dict 에 등록
5. yield  (이 아래는 서버 종료 시 실행)
6. 종료 시 모든 워커 .stop() → 스레드 깨끗이 종료
```

### 왜 스레드지 프로세스 아님?
- OpenCV 의 `cv2.VideoCapture` 는 GIL 밖에서 C 레벨로 돌아감 → 스레드 충분.
- 프로세스는 통신·메모리 비용 큼. 카메라 2~5 대 규모에서 스레드가 경제적.
- 수십 대로 늘어나면 멀티프로세스 / 큐 기반 구조 재설계 필요 (Stage E 이후 과제).

### 현재 한계 (D3 Out-of-scope)
- `POST /cameras` 로 새 카메라 추가해도 **즉시 반영 안 됨** — 서버 재시작 필요.
- 동적 워커 add/remove 는 다음 이터레이션 과제.

---

## 6. 녹화 세그먼트 → DB insert 흐름

### 1분 세그먼트가 끝날 때마다 일어나는 일

```
[CaptureWorker 스레드]
  ├─ RTSP 에서 프레임 계속 읽기
  ├─ cv2.VideoWriter 로 mp4 누적 기록
  ├─ motion 감지 (두 프레임 차이 픽셀%)
  │
  ▼ 60초 경과
  │
[세그먼트 종료 처리]
  1. 현재 mp4 close → storage/clips/YYYY-MM-DD/{camera_uuid}/HHMMSS_motion.mp4
  2. 대표 프레임 저장 → 같은 이름.jpg (D4 썸네일)
  3. clip_recorder 호출 → DB INSERT 시도
     ├─ 성공: camera_clips 에 row 추가
     └─ 실패 (네트워크 등): storage/pending_inserts.jsonl 에 append
  4. 새 mp4 시작 (다음 60초)
```

### 왜 디스크 ↔ DB 를 분리?
| 데이터 | 어디에 | 이유 |
|--------|--------|------|
| mp4 바이트 | 로컬 디스크 | 큼 (60초 ≈ 3 MB). DB 에 넣으면 비용·속도 재앙 |
| jpg 바이트 | 로컬 디스크 | 위와 동일 |
| "언제·어디·몇초" 메타 | Supabase DB | 작음. 앱이 "클립 목록" 으로 빠르게 조회 필요 |
| 파일 경로 (`file_path`) | DB 에 문자열로 | 앱 요청 시 `/clips/{id}/file` 이 이 경로로 mp4 스트리밍 |

### Supabase 잠깐 다운 시 어떻게 되나?
- `camera_clips.insert()` 실패 → `pending_inserts.jsonl` 에 JSON 한 줄 append
- 30초 주기 flush task 가 "네트워크 복구되면" 자동 재전송
- 즉, **네트워크 장애로 데이터 손실 없음** (디스크 자체가 터지지 않는 한)

---

## 7. 오늘 만든 실제 UUID 레퍼런스

나중에 디버깅하거나 curl 테스트할 때 참고. (본인 계정 한정)

```
auth.users.id   (당신)   : 380d97fd-cb83-4490-ac26-cf691b32614f

pets
├── 테스트1                 : 55518f35-b251-4ed7-962f-b65611d63223
└── 릴잔틱숫 (오늘 추가)   : d62ced3e-c2d5-4951-8538-0527ceb2869b

cameras
├── cam1 (거실)             : 1c1aea9f-31dc-4801-a8f5-ee74d7f2e3b6
│    host=192.168.219.106, 계정=gecko_cam_home_1
└── cam2 (두번째)           : 3a6cffbf-be83-4c77-9fa7-4fcc517c74a6
     host=192.168.219.107, 계정=gecko_cam_home_2, pet=릴잔틱숫

camera_clips : 1분마다 자동 INSERT (삭제·업데이트 거의 없음)
```

### curl 예시
```bash
# 내 카메라 목록
curl -s http://localhost:8000/cameras | python3 -m json.tool

# cam1 상태
curl -s http://localhost:8000/streams/1c1aea9f-31dc-4801-a8f5-ee74d7f2e3b6/status

# cam2 클립만
curl -s "http://localhost:8000/clips?camera_id=3a6cffbf-be83-4c77-9fa7-4fcc517c74a6&limit=5"

# 특정 클립 mp4 다운로드
curl -s http://localhost:8000/clips/<clip-uuid>/file -o clip.mp4

# 특정 클립 썸네일
curl -s http://localhost:8000/clips/<clip-uuid>/thumbnail -o thumb.jpg
```

---

## 8. 자주 헷갈리는 것들

### Q1. `POST /cameras` 하면 바로 녹화 시작?
**아니요.** DB 에 등록만 됨. 녹화는 **서버 기동 시점** 의 cameras 테이블만 읽음 → 서버 재시작해야 반영.

### Q2. `pet_id` 를 나중에 바꾸면?
PATCH 는 DB 값만 변경. 녹화 중인 워커는 이미 기동 시점의 pet_id 를 들고 있음 → **서버 재시작 전까지 새 클립도 예전 pet_id 로** insert 된다. 오늘 cam2 에 릴잔틱숫 붙일 때 이 이슈 만났음.

### Q3. `camera_clips.camera_id` 가 D3 이전엔 `TEXT "cam-1"` 이었다며?
맞음. D3 마이그레이션에서 `cameras.id` 를 참조하는 **UUID FK** 로 바꿨음 (3.5 step: ADD nullable → backfill → NOT NULL → DROP+RENAME).

### Q4. 서버 중단하면 지금 녹화 중인 1분짜리 mp4 는?
lifespan 의 shutdown 블록이 각 워커의 `.stop()` 호출 → **현재 세그먼트 flush** → mp4 close → DB insert 1번 더 → 종료. 중단 시점까지 저장됨.

### Q5. Supabase 대시보드에서 cameras 테이블 직접 열어서 행 추가하면?
**RLS INSERT 정책이 없어서 실패한다.** 의도적 설계 — 프론트/관리자가 DB 직결로 insert 해서 "test-connection 검증 + Fernet 암호화" 우회하는 경로를 구조적으로 차단. 모든 등록은 반드시 `POST /cameras` 를 경유.

### Q6. `DEV_USER_ID` 는 무슨 의미?
Stage D1 까지 임시 하드코딩한 "로컬에서 내가 누구인지" 라벨. Stage D5 prod 모드 켜면 JWT 에서 진짜 `user_id` 뽑아서 쓰고, 이 env 는 dev 전용으로만 남음.

### Q7. 유저 1000명 쓰면 카메라 1000대. 서버 이대로 괜찮나?
**안 괜찮다.** 지금 구조(카메라 1대 = 스레드 1개 = 서버 CPU 사용)는 Mac 1대 기준 **실용 한계 ≈ 20대**.

**병목 3가지 (Mac mini M2 기준, 카메라 1080p · 3Mbps 추정)**

| 자원 | 카메라 1대 | 100대 | 1000대 |
|------|-----------|-------|--------|
| 네트워크 | 3 Mbps | 300 Mbps | 3 Gbps (회선 초과) |
| 디스크 | 180 MB/h | 18 GB/h | 180 GB/h (SSD 수명 급감) |
| CPU | 1 코어 부분점유 | 10+ 코어 | 100+ 코어 (물리 불가) |

**그래서 실제 프로덕트는 하이브리드 구조로 간다:**

```
[카메라 on-device]        [클라우드 서버]           [유저 앱]
 움직임 1차 필터            받은 클립만 저장          실시간은 P2P/WebRTC
 99% 버림                 무거운 AI (탈피 감지 등)    알림 소비
     ↓ 관심 이벤트만 업로드    ↑ 푸시 알림
```

**핵심 트릭 2개**
1. **1층에서 99% 버림** — 게코는 하루 대부분 가만히 있음. 서버로 올라오는 데이터 1/100 로 감축.
2. **실시간 스트림은 P2P** — 유저가 볼 때만 카메라-폰 직접 연결. 서버는 시그널링만 중계 → 서버 대역폭 = 0.

**단계별 로드맵**
- **MVP (지금)**: 서버에서 전부 처리. 검증 먼저.
- **베타 (~100 유저)**: Cloudflare Tunnel + 클라우드 VM. 서버비 $200~500/월 각오.
- **상용 (100+ 유저)**: Stage E 필수 진입 — ESP32-CAM on-device 필터링 + P2P 스트림.

Ring·Nest·Blink 전부 이 구조. 서버비 수학이 안 맞아서 다 거기로 수렴.

---

## 참고 링크

- Supabase 공식: https://supabase.com/docs
- Fernet 스펙: https://cryptography.io/en/latest/fernet/
- 우리 스펙: [`specs/stage-d1-auth-crypto.md`](../specs/stage-d1-auth-crypto.md), [`specs/stage-d2-cameras-api.md`](../specs/stage-d2-cameras-api.md), [`specs/stage-d3-multi-capture.md`](../specs/stage-d3-multi-capture.md)
- 관련 백엔드 코드: `backend/main.py`, `backend/crypto.py`, `backend/routers/cameras.py`, `backend/capture.py`
