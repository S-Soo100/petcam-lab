# Stage C 학습 노트 — Supabase + FastAPI + HTTP Range 스트리밍

> Stage C 에서 처음 써본 개념·라이브러리 API 를 **왜 썼는지 · TS/JS 로 치면 뭔지** 기준으로 정리.
> 전부 소화 못 해도 괜찮음. **TL;DR → 우선순위 1~3번** 만 먼저 읽고, 나머진 필요할 때 돌아와서.

## TL;DR (5줄)

1. **Supabase** 는 "Postgres + Auth + API 자동 생성" BaaS. 우리는 서버에서 `service_role` 키로 DB 에 직접 INSERT, 앱은 `anon` 키 + JWT 로 **RLS 가 본인 데이터만 돌려주게**.
2. **FastAPI `Depends()`** 는 NestJS DI 랑 사실상 같은 것. 테스트에서 `dependency_overrides` 로 교체 가능 → Supabase mock 으로 유닛테스트 21개 다 해결.
3. **HTTP Range Request (206 Partial Content)** 를 직접 구현해서 `<video>` / `video_player` 가 **중간부터 재생·시크** 할 수 있게.
4. **Seek pagination** (`started_at < cursor`) 으로 offset 페이지네이션의 느려지는 문제 회피.
5. **파일 기반 재시도 큐(JSONL)** 로 Supabase 잠깐 다운돼도 데이터 안 날림.

## 우선순위

가장 많이 재사용될 것 → 특수한 것 순.

| # | 주제 | 왜 중요한가 |
|---|------|-----------|
| 1 | [FastAPI `Depends()` 패턴](#1-fastapi-의-depends) | 모든 핸들러에서 쓰는 핵심. NestJS DI 대응. |
| 2 | [Supabase — service_role / anon / RLS](#2-supabase--서버-키--앱-키--rls) | Stage D 에서 JWT 검증 추가할 때 기반. |
| 3 | [HTTP Range Request](#3-http-range-request---비디오-시크) | 영상 스트리밍 핵심. 앱 `video_player` 가 이걸 기대. |
| 4 | [Seek pagination](#4-seek-pagination--offset-페이지네이션) | 시계열 데이터 전반에 재사용. |
| 5 | [파일 기반 재시도 큐 (JSONL)](#5-파일-기반-재시도-큐-jsonl) | 네트워크 의존 서비스의 일반 패턴. |
| 6 | [lifespan + `asyncio.to_thread`](#6-fastapi-lifespan--asynciotothread) | 동기 라이브러리를 비동기 서버에서 쓰는 법. |
| 7 | [테스트: TestClient + dependency_overrides + Fake](#7-테스트-testclient--dependencyoverrides--fake) | 유닛 테스트의 표준 레시피. |
| 8 | [Partial Index (Postgres)](#8-partial-index--postgres-최적화) | "대부분은 필요없는 인덱스" 상황에서. |

---

## 1. FastAPI 의 `Depends()`

### 한 줄 요약
함수 파라미터에 `param: X = Depends(get_x)` 쓰면 FastAPI 가 **요청마다** `get_x()` 실행해서 그 반환값을 주입.

### NestJS 비유
```typescript
// NestJS
@Injectable()
export class ClipsService {
  constructor(private readonly supabase: SupabaseClient) {}  // DI
}
```

```python
# FastAPI
def list_clips(sb: Client = Depends(get_supabase_client)):  # DI
    ...
```

NestJS 는 클래스/데코레이터 기반, FastAPI 는 **함수 기반 + 타입 힌트**. 실행 모델은 같음.

### 왜 이게 중요?
- **테스트**: `app.dependency_overrides[get_supabase_client] = lambda: FakeSupabase(...)` 한 줄로 mock 교체. NestJS 의 `TestingModule.overrideProvider(...)` 와 같음.
- **요청 스코프 vs 싱글톤**: 기본은 매 요청마다 실행. 싱글톤이 필요하면 `@lru_cache(maxsize=1)` 같이 씀.

### 우리 코드 예
```python
# backend/supabase_client.py
@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    load_dotenv(REPO_ROOT / ".env")
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    return create_client(url, key)
```
`@lru_cache(maxsize=1)` 는 "이 함수는 한 번 실행하고 결과 캐시". 결과적으로 싱글톤.

```python
# backend/routers/clips.py
@router.get("")
def list_clips(
    camera_id: Optional[str] = Query(None),
    sb: Client = Depends(get_supabase_client),  # ← 주입
    user_id: str = Depends(get_dev_user_id),    # ← 주입
) -> dict:
    ...
```

### 헷갈리기 쉬운 것
- `Depends()` 는 **함수 호출이 아님**. 파라미터 기본값으로 `Depends(get_x)` 를 박아두면 FastAPI 가 알아서 호출한다.
- `@lru_cache` 는 **같은 인자 → 같은 결과 보장**. 인자 바뀌면 다시 호출. 인자 없는 함수엔 완벽한 싱글톤.

---

## 2. Supabase — 서버 키 / 앱 키 / RLS

### 한 줄 요약
Supabase = Postgres + Auth + REST/Realtime 자동 생성 + 관리형 호스팅. 우리는 **같은 DB 에 서버도 앱도** 접속하는데, **권한이 다른 두 API 키** 로 분리.

### 두 종류 키

| 키 | 용도 | RLS | 예시 |
|---|---|---|---|
| `anon` (public) | 브라우저/앱에 배포 OK | **적용** (JWT 의 `auth.uid()` 로 필터링) | Flutter 앱이 `SELECT * FROM camera_clips` → 본인 것만 나옴 |
| `service_role` | **서버 전용, 절대 공개 금지** | **바이패스** (모든 행 접근) | petcam-lab 서버가 새 세그먼트 `INSERT` |

**service_role 키가 왜 필요?** 우리 petcam-lab 서버는 여러 유저(나중엔)의 세그먼트를 INSERT 하게 될 건데 각 유저의 JWT 를 갖고 있지 않음. → 바이패스 키로 직접 쓴다.

### RLS (Row-Level Security) 란?
Postgres 의 기능. 테이블에 **"이 행은 누가 SELECT/INSERT/UPDATE/DELETE 할 수 있냐"** 정책을 SQL 로 선언.

```sql
CREATE POLICY "User reads own clips" ON camera_clips
  FOR SELECT USING (auth.uid() = user_id);
```

→ Flutter 앱이 `anon` 키로 `SELECT * FROM camera_clips` 해도 Postgres 가 **자동으로 `WHERE user_id = <JWT sub>`** 를 덧붙임.

### NestJS / Express 비유
```typescript
// 보통 이렇게 모든 라우트에 ownership 미들웨어:
app.use('/clips', requireAuth, requireOwner);
// 실수로 빼먹으면 데이터 유출
```

RLS 는 **DB 레이어에 보안을 내려둔 것**. 서버 코드가 `WHERE` 빼먹어도 DB 가 차단. 이 이중 안전망이 Supabase 생태계의 핵심 철학.

### 우리 구조
```
Flutter 앱 ──(anon key + JWT)──> Supabase Postgres ──RLS── 본인 것만 SELECT
petcam-lab ──(service_role)────> Supabase Postgres ──바이패스── 모든 user INSERT
```

### 주의
- `service_role` 키는 **.env 에만**. git 에 커밋 금지. 공개되면 DB 전체 권한 유출.
- petcam-lab 서버에서 쓸 땐 코드에서 **직접 `WHERE user_id = ...` 명시**. (RLS 바이패스 상태라 안 걸면 다른 유저 것 실수로 건드릴 수 있음.)

우리 코드:
```python
# backend/routers/clips.py
q = sb.table("camera_clips").select("*").eq("user_id", user_id)  # 필수
```

---

## 3. HTTP Range Request — 비디오 시크

### 한 줄 요약
`Range: bytes=1048576-` 헤더로 "파일의 X바이트부터 달라" 요청. 서버는 `206 Partial Content` + `Content-Range: bytes 1048576-2097151/5242880` 로 응답. 비디오 플레이어가 이걸로 시크·부분 다운로드.

### 왜 필요?
- Flutter `video_player` / 브라우저 `<video>` 가 "0:30부터 재생" 할 때 mp4 **앞부분만 버리고 중간부터 달라** 고 요청.
- 기본 `StreamingResponse(open(path, 'rb'))` 는 이걸 처리 안 함 → **직접 파싱 + 206 응답 구성**.

### 우리 구현 핵심
```python
# backend/routers/clips.py
_RANGE_RE = re.compile(r"^\s*bytes\s*=\s*(\d+)-(\d*)\s*$")

def get_clip_file(clip_id: str, request: Request, ...):
    range_header = request.headers.get("range")
    file_size = file_path.stat().st_size

    if not range_header:
        # Range 없음 → 200 OK + 전체
        return StreamingResponse(
            _iter_file(file_path, 0, file_size),
            headers={"Content-Length": str(file_size), "Accept-Ranges": "bytes"},
        )

    match = _RANGE_RE.match(range_header)
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else file_size - 1

    return StreamingResponse(
        _iter_file(file_path, start, end + 1),
        status_code=206,  # ← Partial Content
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(end - start + 1),
        },
    )
```

### 제너레이터로 청크 단위 전송
```python
def _iter_file(path, start, end_exclusive):
    with path.open("rb") as f:
        f.seek(start)
        remaining = end_exclusive - start
        while remaining > 0:
            chunk = f.read(min(256 * 1024, remaining))
            if not chunk: break
            remaining -= len(chunk)
            yield chunk
```
`yield` 를 쓰면 FastAPI 가 **chunked transfer-encoding** 으로 전송. 메모리에 전체 올리지 않음 → GB 짜리 파일도 OK.

### Node 비유
```typescript
// express 의 res.sendFile() 은 Range 자동 처리:
app.get('/video', (req, res) => res.sendFile(path));  // Range OK
```
FastAPI 는 **수동**. 처음엔 번거롭지만 덕분에 "어디까지 보낼지" 를 정교하게 제어 가능.

### 상태 코드 표
| 코드 | 의미 |
|------|------|
| 200 | Range 없음, 전체 전송 |
| 206 | Range 유효, 부분 전송 |
| 416 | Range 헤더 형식 이상 or 파일 크기 초과 |
| 410 | DB 에 행은 있지만 파일이 디스크에서 사라짐 (영구 소실) |

---

## 4. Seek pagination ≠ offset 페이지네이션

### 두 방식 차이

**offset (흔한 방식)**
```sql
SELECT * FROM camera_clips ORDER BY started_at DESC LIMIT 50 OFFSET 1000;
```
- Postgres 가 1000행을 **먼저 읽고 버린 뒤** 50행 반환
- 페이지 깊어질수록 느려짐 (100페이지는 처음부터 5000행 버리고 스캔)

**seek / cursor (우리 방식)**
```sql
SELECT * FROM camera_clips
WHERE started_at < '2026-04-21T05:22:23+00:00'  -- 직전 페이지 마지막의 started_at
ORDER BY started_at DESC LIMIT 50;
```
- 인덱스 범위 스캔 한 번. 페이지 깊이 무관하게 **같은 속도**.
- 앞 페이지에 새 데이터 삽입돼도 중복 없음 (offset 은 중복 가능).

### 응답 형태
```json
{
  "items": [...],
  "count": 50,
  "next_cursor": "2026-04-21T05:22:23+00:00",  // 마지막 행의 started_at
  "has_more": true
}
```
클라이언트는 `next_cursor` 를 다음 요청의 `?cursor=` 로 그대로 사용.

### 우리 코드
```python
# limit 대신 limit+1 을 조회해서 "더 있는지" 판단
q = sb.table("camera_clips").select("*").limit(limit + 1)
if cursor: q = q.lt("started_at", cursor)

rows = q.execute().data
has_more = len(rows) > limit
items = rows[:limit]
next_cursor = items[-1]["started_at"] if has_more else None
```

### 트레이드오프
- ✅ 페이지 깊이 무관, 빠르고 일관성 있음
- ❌ 임의의 N 번째 페이지로 점프 불가 (1페이지 → 2페이지 순차만 가능)
- 보통은 ✅ 이 훨씬 중요. 점프가 필요하면 별도 UX 로 해결.

---

## 5. 파일 기반 재시도 큐 (JSONL)

### 왜 필요?
Supabase 잠깐 다운 / 네트워크 끊김 시 INSERT 실패. 데이터 날리면 안 됨 → **로컬 파일에 쌓아두고 나중에 재전송**.

### 왜 JSONL?
```
{"user_id": "...", "camera_id": "...", "started_at": "..."}
{"user_id": "...", "camera_id": "...", "started_at": "..."}
```
- 한 줄 = 한 이벤트. **append-only** 쓰기 단순 (파일 끝에 `\n` 붙여서 `write`)
- 중간 줄 손상돼도 다른 줄은 안전
- `cat`, `tail` 로 디버깅 쉬움
- **재시작에도 유지** (메모리 큐와 결정적 차이)

### 왜 Redis 안 씀?
- 인프라 하나 더 = 운영 복잡도 ↑
- 초기 단계엔 과잉
- 단일 프로세스·단일 워커 전제라 동시성 경합 거의 없음

3번 이상 반복되면 Redis 로 전환 고려 (우리 YAGNI 원칙).

### 원자적 rewrite 패턴
```python
# 성공한 라인 제거 후 파일 재작성할 때:
tmp = self._path.with_suffix(".jsonl.tmp")
with tmp.open("w") as f:
    for row in remaining:
        f.write(json.dumps(row) + "\n")
tmp.replace(self._path)  # ← 원자적 교체 (POSIX rename)
```
`tmp.replace()` 는 OS 레벨 원자 연산. **중간에 크래시해도 원본 보존**. 부분적으로 쓰인 파일을 절대 만들지 않음.

### Node 비유
```typescript
// Bull Queue / BullMQ 의 파일 기반 간이 버전
// 또는 node-cron + 파일 flush 조합
```

### 우리 구현 요점
```python
# backend/pending_inserts.py
class PendingInsertQueue:
    def enqueue(self, row):
        with self._lock:  # threading.Lock
            if self._count_lines_locked() >= self._max_lines:
                self._trim_oldest_locked(keep=self._max_lines - 1)
            with self._path.open("a") as f:
                f.write(json.dumps(row) + "\n")

    def flush(self, insert_fn) -> tuple[int, int]:
        # insert_fn(row) -> bool. True 면 제거, False 면 남김.
        ...
```
- max_lines=1000 → 무한 증가 방지
- `threading.Lock` → 캡처 스레드와 flush 태스크 동시 접근 안전

---

## 6. FastAPI lifespan + `asyncio.to_thread`

### lifespan 이란?
서버 **시작 / 종료 시점에 딱 한 번** 실행되는 코드. DB 커넥션 초기화, 백그라운드 워커 스폰, 리소스 해제 등.

```python
# backend/main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    worker = CaptureWorker(...)
    worker.start()
    app.state.capture_worker = worker

    yield  # ← 여기서 서버가 요청을 받음

    # --- shutdown ---
    worker.stop()

app = FastAPI(lifespan=lifespan)
```

### Express 비유
```typescript
const server = app.listen(3000);          // startup
process.on('SIGTERM', () => {             // shutdown
  cleanup();
  server.close();
});
```
`asynccontextmanager` + `yield` 가 저 startup/shutdown 을 **한 함수에 묶어서** 명확히 한 구조.

### 왜 `@app.on_event("startup")` 쓰지 말라고?
공식 deprecated. `yield` 기반 lifespan 이 표준. 주된 이유:
- startup 실패 시 shutdown 이 호출 안 되는 버그 (`on_event` 의 설계 결함)
- `yield` 는 try/finally 로 감싸서 **반드시 shutdown 실행** 보장 가능

### `asyncio.to_thread` — 동기 코드를 비동기 컨텍스트에서
Python 의 async 루프는 **블로킹 I/O 가 섞이면 전체 멈춤**. `supabase-py` 의 `.execute()` 는 동기(requests 기반). 이걸 async 태스크에서 쓰려면 스레드풀에 던져야 함.

```python
async def _periodic_flush():
    while True:
        await asyncio.sleep(30)
        # 동기 함수를 블로킹 없이 실행:
        s, r = await asyncio.to_thread(pending_queue.flush, flush_insert)
```

Node 비유: 메인 이벤트 루프에서 `fs.readFileSync()` 절대 쓰지 말라는 것과 같은 이유. 다만 Python 은 `to_thread` 로 **감싸서** 허용.

### 왜 clips.py 의 핸들러는 `def` 인가 (async 아님)?
FastAPI 는 `def` (동기) 핸들러는 자동으로 스레드풀에서 실행. `async def` 핸들러는 이벤트 루프에서 실행. Supabase 동기 호출이 섞인 핸들러는 그냥 `def` 로 두는 게 단순하고 안전.

---

## 7. 테스트: TestClient + dependency_overrides + Fake

### 전략 3단계

1. **TestClient** — FastAPI 의 내장 HTTP 클라이언트 (내부적으로 `httpx`). 실제 네트워크 없이 요청 시뮬레이션.
2. **dependency_overrides** — `Depends()` 주입을 테스트 시에만 교체. 프로덕션 코드 수정 없음.
3. **Fake** — Supabase 체인을 **메모리 리스트 + 필터 로직** 으로 재현.

### 왜 `unittest.mock` 안 쓰고 직접 Fake 만들었나?

```python
# mock 접근 — 체인이 길수록 지저분:
mock_sb = MagicMock()
mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value\
    .order.return_value.limit.return_value.execute.return_value.data = [...]
```

vs

```python
# Fake 접근 — 필터 로직이 실제로 돈다:
class _FakeQuery:
    def eq(self, key, val):
        self._rows = [r for r in self._rows if r.get(key) == val]
        return self
    # ...

client = TestClient(app)
app.dependency_overrides[get_supabase_client] = lambda: FakeSupabase(rows)
```

Fake 쪽이 **테스트 의도가 코드에 드러남**. `eq("camera_id", "cam-1")` 호출 시 실제로 필터링되는 걸 검증.

### 우리 테스트 구조
```python
# tests/test_clips_api.py
test_app = FastAPI()
test_app.include_router(clips_router)
test_app.dependency_overrides[get_supabase_client] = lambda: FakeSupabase({...})
test_app.dependency_overrides[get_dev_user_id] = lambda: USER_ID
client = TestClient(test_app)

r = client.get("/clips", params={"has_motion": "true"})
assert r.status_code == 200
assert r.json()["count"] == 1
```

### 포인트
- 메인 `app` 대신 **미니 app** 을 매 테스트마다 구성: lifespan 안 돎 (RTSP 초기화 시도 안 함). 격리.
- `video_player` 없이 mp4 파일 테스트: `tmp_path` 에 결정적 바이트 패턴 작성, MD5 비교.

### Jest 비유
```typescript
// Jest
jest.mock('./supabase', () => ({ query: () => [...fakeRows] }));
```
`dependency_overrides` 는 **런타임 DI 교체**, Jest mock 은 모듈 자체 교체. 목적은 같음 (외부 의존 제거).

---

## 8. Partial Index — Postgres 최적화

### 일반 인덱스 vs 부분 인덱스
```sql
-- 전체 행 인덱싱:
CREATE INDEX idx_motion ON camera_clips(user_id, has_motion, started_at DESC);

-- motion=true 인 행만 인덱싱:
CREATE INDEX idx_motion ON camera_clips(user_id, has_motion, started_at DESC)
  WHERE has_motion = true;
```

### 왜 이득?
우리 상황:
- 하루 1440 세그먼트 (60초 × 24시간)
- 그중 motion 있는 건 보통 **5% 내외** (도마뱀이 가만 있는 시간이 압도적)
- 전체 인덱스 용량의 **1/20** 만 사용
- 주요 쿼리 "오늘 motion 있는 것만" 이 이 인덱스 타고 날아다님

### 트레이드오프
- ❌ `has_motion = false` 쿼리에는 이 인덱스 쓸모 없음 → 별도 인덱스 필요하면 추가
- ✅ 부분 조건이 명확하게 "소수 행만 매칭" 일 때 매우 효율적

### SQLite 도 지원
Postgres 만의 기능은 아님. 하지만 Postgres 가 훨씬 자주 쓰는 패턴.

---

## 다음 읽을거리

### 우리 레포 안
- `specs/stage-c-db-api.md` — 이 Stage 의 원본 설계 메모
- `backend/routers/clips.py` — 실제 엔드포인트 구현. Range 구현부 주석 참고.
- `backend/pending_inserts.py` — JSONL 큐 원자적 rewrite 주석 참고.
- `tests/test_clips_api.py` — FakeSupabase 구현 + TestClient 사용 예.

### 공식 문서
- **FastAPI Dependencies**: https://fastapi.tiangolo.com/tutorial/dependencies/
- **FastAPI Lifespan**: https://fastapi.tiangolo.com/advanced/events/
- **Supabase RLS**: https://supabase.com/docs/guides/auth/row-level-security
- **supabase-py**: https://supabase.com/docs/reference/python/introduction
- **Postgres Partial Indexes**: https://www.postgresql.org/docs/current/indexes-partial.html
- **MDN HTTP Range**: https://developer.mozilla.org/en-US/docs/Web/HTTP/Range_requests

### 다음 Stage 에서 배울 것 (예고)
- **Supabase Auth JWT 검증** — `jose` or `pyjwt` 로 토큰 서명 확인 + `sub` 클레임 추출
- **Flutter `video_player` 패키지** — HTTP Range 를 클라이언트 쪽에서 어떻게 쓰는지
- **네트워크 설정** — 집 LAN 외부에서 petcam-lab 서버 접근 (Tailscale / Cloudflare Tunnel / 포트포워딩 비교)

---

## 복습 퀴즈 (자기 체크)

- [ ] `service_role` 키를 Flutter 앱에 넣으면 왜 안 되나?
- [ ] `Depends(get_x)` 와 그냥 `get_x()` 호출의 차이?
- [ ] Range 요청에 대한 응답 상태코드 200/206 언제 나뉨?
- [ ] offset 페이지네이션이 왜 페이지 깊어질수록 느려지나?
- [ ] `tmp.replace(self._path)` 를 왜 쓰나? 그냥 덮어쓰면 뭐가 문제?
- [ ] `async def` 핸들러 안에서 `time.sleep(5)` 쓰면 어떤 사고 나나?
- [ ] Fake Supabase 를 만들 때 `.eq()` 가 `self` 를 반환하는 이유?

막히면 해당 섹션으로 돌아가서 답 찾기. 답 안 외워도 됨, **왜 그런지** 를 이해하는 게 중요.
