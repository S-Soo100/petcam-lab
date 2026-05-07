# Feature — Capture Worker 분리 (모놀리식 → 별도 service)

> 현재 `backend.main` lifespan 안에 묶인 `CaptureWorker` + `EncodeUploadWorker` 를 별도 프로세스 (entrypoint) 로 분리. API 서버는 cloud 배포 가능 상태로, 캡처는 LAN 에 남되 자체 HW 등장 시 통째 교체될 contract 경계 확정.

**상태:** 🚧 코드 완료, 사용자 실기 검증 대기 (2026-05-07)
**작성:** 2026-05-07
**연관 SOT:** `../../tera-ai-product-master/docs/specs/petcam-backend-dev.md` §165, §212
**상위 spec:** [`cloud-migration-roadmap.md`](cloud-migration-roadmap.md)

## 1. 목적

**문제:**
- 현재 `backend.main:app` 한 프로세스가 (a) FastAPI HTTP API (b) RTSP 캡처 스레드 N개 (c) encode_upload asyncio pool 다 함. 클라우드 배포하려면 캡처가 LAN (Tapo C200 RTSP) 의존이라 "API 만 cloud 로 옮기기" 가 안 됨.
- 자체 HW 웹캠 도착 시 (memory `project_capture_replaced_by_own_hw.md`) capture 부분만 깔끔하게 떼낼 수 있는 경계가 없음.

**해결:**
- API 서버 (`backend.main:app`) = cloud 배포 가능 (fly.io / Railway / Cloud Run).
- 캡처 워커 (`backend.capture_main:run`) = 별도 entrypoint, 로컬 맥북 (또는 추후 자체 HW) 에서 가동.
- 두 프로세스가 공유하는 **contract = clip_recorder payload + Supabase service_role 키**.

**학습 목표:** "한 코드베이스 두 entrypoint" 패턴 (Python `if __name__ == '__main__'` 의 진화). Node 비유: `package.json` 의 `scripts: { api: "...", worker: "..." }`.

## 2. 스코프

### In
1. `backend/capture_main.py` 신규 — `lifespan` 의 캡처/encode 부분만 떼낸 standalone entrypoint.
2. `backend/main.py` 의 lifespan 에서 `CaptureWorker` / `EncodeUploadWorker` 코드 삭제 — API 만 남김.
3. `pyproject.toml` 에 `[project.scripts]` 또는 `[tool.uv.run]` 으로 두 entrypoint 정의.
4. `.env` 분기 — API 서버 / 캡처 워커 둘 다 같은 `.env` 읽되 필요한 변수만 사용.
5. `docs/DEPLOYMENT.md` 갱신 — 두 프로세스 가동법.
6. `docs/ARCHITECTURE.md` 갱신 — 분산 다이어그램.
7. 기존 테스트 통과 (회귀 0).

### Out
- 자체 HW 펌웨어 / 보드 작업 (별도 트랙)
- 캡처 워커 클라우드 배포 (RTSP 가 LAN 안 — 자체 HW 등장 전엔 무의미)
- capture.py 자체 리팩토링 (메모리: 어차피 자체 HW 로 대체될 코드)
- VLM worker 작업 (별도 spec `feature-vlm-worker-cloud.md`)
- API 서버 클라우드 실배포 (이번 spec 은 분리만, 배포는 이후)

## 3. 완료 조건

- [x] `backend/capture_main.py` 생성 — `if __name__ == "__main__": run()` 진입점 + `bootstrap()`/`shutdown()`/`amain()` 분해 (테스트가 직접 호출 가능)
- [x] `backend/main.py` lifespan 에서 capture/encode 부분 제거 (API 만 남김 + `/streams/{id}/status` 엔드포인트 삭제 — 워커 in-memory 상태가 별도 프로세스 영역이라 의미 없음)
- [x] `pyproject.toml` 에 entrypoint 등록 (`petcam-capture`. API 는 `uv run uvicorn backend.main:app` 표준 사용 — spec §4-4 두 번째 옵션)
- [ ] `uv run petcam-capture` → 카메라 N대 워커 가동 + Supabase INSERT 정상 동작 (사용자 실기 검증 대기 — 현재 백엔드 일시 중단 상태)
- [ ] `uv run uvicorn backend.main:app --port 8000` → API 만 가동, `/health` 200, `/clips` 정상 응답 (사용자 실기 검증 대기)
- [ ] 두 프로세스 동시 가동 시 race condition 없음 (특히 startup flush — 사용자 실기 검증 대기)
- [x] `pytest` 전체 통과 (224건, 이전 204건 + 새 4건 + 변경) — `tests/test_capture_main.py` 신규 + `tests/test_main_lifespan.py` 슬림화
- [x] `docs/DEPLOYMENT.md` "두 프로세스 가동법" 섹션 갱신 — 터미널 A/B/C 체크리스트, 캡처 트러블슈팅 capture_main 로그 안내
- [x] `docs/ARCHITECTURE.md` 분산 다이어그램 갱신 — §2 시스템 맵 / §3 backend 내부 구조 / §5 동시성 모델 / §8 결정 표
- [x] 본 spec 상태 + `cloud-migration-roadmap.md` 체크박스 갱신 (코드 완료 시점)

## 4. 설계 메모

### §4-1. 분리 경계 = lifespan 안의 두 블록

**현재 `backend/main.py:140~280` 의 lifespan 구조:**
```
1. Supabase client 초기화        → API + 워커 둘 다 필요
2. cameras 테이블 SELECT          → 워커만 필요
3. PendingInsertQueue + 주기 flush → 워커만 필요
4. EncodeUploadWorker.start()     → 워커만 필요
5. CaptureWorker N개 start()      → 워커만 필요
6. yield                          → API 라우팅 시작
7. (shutdown) 워커 stop, queue drain
```

**분리 후:**
- `backend/main.py` lifespan = (1) + (6) 만. CORS / routers 그대로.
- `backend/capture_main.py` = (1) + (2~5) + (7) — 자체 lifecycle (asyncio.run).

### §4-2. capture_main.py 골격

```python
# backend/capture_main.py
"""
캡처 + 인코딩 + R2 업로드 워커 standalone entrypoint.

API 서버 (`backend.main:app`) 와 별도 프로세스로 가동. RTSP 가 LAN 의존이므로
이 프로세스는 카메라와 같은 네트워크 (지금: 맥북 / 미래: 자체 HW 보드) 에 가동.

DB INSERT 는 Supabase service_role 로 직접 (API 서버 거치지 않음). 즉 워커가
Supabase 와 R2 양쪽에 직접 쓴다.
"""
import asyncio
import logging
import signal

from backend.capture import CaptureWorker
from backend.clip_recorder import make_clip_recorder, make_flush_insert_fn
from backend.encode_upload_worker import EncodeUploadWorker
from backend.pending_inserts import PendingInsertQueue
# ... (lifespan 에서 옮겨온 imports)

logger = logging.getLogger(__name__)

async def main() -> None:
    # 1. Supabase / .env 로드 — main.py 의 lifespan 첫 부분 그대로
    # 2. cameras 로드 + Fernet 검증
    # 3. EncodeUploadWorker.start()
    # 4. CaptureWorker N 개 start()
    # 5. SIGTERM/SIGINT 까지 대기 (asyncio.Event)
    # 6. graceful stop — 캡처 thread 먼저, encode_upload drain, 큐 flush

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    # ... (boot)
    await stop_event.wait()
    # ... (graceful stop)

def run() -> None:
    """uv 스크립트 엔트리."""
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())

if __name__ == "__main__":
    run()
```

**왜 asyncio.run + Event?**
- lifespan 은 FastAPI 가 yield 로 제어. standalone 은 asyncio.run + signal handler 로 직접 제어.
- Node 비유: `process.on('SIGTERM', () => server.close())` 패턴.

### §4-3. main.py lifespan 슬림화 후

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv(REPO_ROOT / ".env")
    logger.warning("AUTH_MODE=%s", os.getenv("AUTH_MODE", "dev"))
    # Supabase 미설정도 /health 는 살아있게
    try:
        get_supabase_client()  # 검증만
    except SupabaseNotConfigured as exc:
        app.state.startup_error = f"Supabase 미설정: {exc}"
    yield
```

`/health` 응답에서 `capture_workers` / `encode_upload_queue` 는 제거 (이 프로세스가 더 이상 안 가짐). 캡처 워커 상태는 별도 엔드포인트 — 이번 spec Out (단순 분리만, 모니터링 보강은 후속).

### §4-4. pyproject.toml entrypoint

```toml
[project.scripts]
petcam-api = "uvicorn:run"  # CLI 인자로 backend.main:app 받음 — 또는 wrapper
petcam-capture = "backend.capture_main:run"
```

또는 더 간단히:
```bash
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000   # API
uv run python -m backend.capture_main                          # 캡처 워커
```

`docs/DEPLOYMENT.md` 에 두 명령 다 기록.

### §4-5. shared state — 동시 가동 시 race

**우려:**
- `PendingInsertQueue` 는 파일 (`storage/pending_inserts.jsonl`) — 두 프로세스가 동시에 쓰면 충돌?

**판단:** 캡처 워커 **만** pending queue 에 enqueue/flush. API 서버는 안 건드림. 그러므로 안전.

**확인 필요:**
- API 라우터 (`backend/routers/`) 안에서 `pending_inserts` import 하는 곳이 있는지 grep.
- 있으면 그 의존성 끊거나 read-only 분기 처리.

### §4-6. 자체 HW 등장 시 contract 경계

**핵심 — 자체 HW 가 와도 그대로 살아남는 코드:**
- `backend/clip_recorder.py` — `make_clip_recorder` 의 payload 시그니처 = contract.
- `backend/r2_uploader.py` — R2 업로드 SDK wrapper (자체 HW 도 동일 R2 키 규칙 준수해야 함).
- DB 스키마 (`camera_clips`, `r2_key`, etc.) — 변경 없음.

**자체 HW 등장 시 교체될 코드 (이번 spec Out):**
- `backend/capture.py` — RTSP pull 루프. 자체 HW = 카메라가 push 모델.
- `backend/encode_upload_worker.py` — 인코딩이 카메라 보드에서 일어남.
- `backend/capture_main.py` — 더 이상 필요 없음.

**자체 HW contract 옵션 (이번 spec Out, 후속 결정):**
- Option A: 카메라가 직접 R2 + DB INSERT (service_role 키 보유) — 보안 위험.
- Option B: 카메라 → REST `POST /internal/clips` → 서버가 R2 PUT + DB INSERT — 권장.
- Option C: 카메라 → R2 PUT (signed URL 발급받음) + 서버 REST `POST /clips/finalize` 알림 → 서버가 DB INSERT — 최선?

이번 spec 에서는 **B/C 중 어느 쪽이든 contract 변경 0** 이 되도록 `clip_recorder` payload 시그니처를 명확히 문서화하는 게 핵심.

### §4-7. 배포 형태 (이번 spec Out, 참고)

- **API 서버** — fly.io / Railway / Cloud Run (선택은 후속). Supabase JWT 검증 + DB read/write + R2 redirect.
- **캡처 워커** — 자체 HW 등장 전까지 맥북 LAN. systemd / launchd 로 부팅 시 자동 가동.
- **VLM worker** — fly.io 또는 Cloud Run (별도 spec, R2 직접 read).

## 5. 학습 노트

- **graceful shutdown** — `signal.SIGTERM` / `SIGINT` 받으면 새 작업 enqueue 차단 → 진행 중 작업 완료 대기 → 종료. asyncio 에서는 `loop.add_signal_handler(sig, event.set)` + `await event.wait()` 패턴. Node 비유: `process.on('SIGTERM', async () => { server.close(); await drainQueue(); })`.
- **두 entrypoint 한 codebase** — Python 의 `if __name__ == "__main__"` 또는 `[project.scripts]` 로 여러 진입점 노출. 공유 코드 (`backend/`) 는 한 곳, 시작점만 다름. Node 비유: 한 `package.json` 의 `bin` 또는 `scripts` 에 여러 명령.
- **DB-as-message-bus 의 단방향 쓰기** — pending queue 는 워커 한 프로세스만 쓰는 파일. 여러 프로세스가 같은 파일을 쓰려면 file lock (fcntl) 또는 DB 큐로 승격. 이번 spec 은 단일 writer 가정.
- **service_role 키 분리** — API 서버는 RLS 우회 (특정 user_id 명시 필터), 캡처 워커도 service_role. 둘 다 같은 `.env` 의 키 공유. 자체 HW 등장 시엔 카메라마다 별도 단명 토큰 발급으로 진화.

## 6. 참고

- 상위 spec: [`cloud-migration-roadmap.md`](cloud-migration-roadmap.md) §4-3 (capture worker 모듈식 분리)
- 학습 자료: [`../docs/learning/cloud-architecture-overview-learning.md`](../docs/learning/cloud-architecture-overview-learning.md) §6 (contract 모듈화)
- 관련 메모리: `project_capture_replaced_by_own_hw.md` — 자체 HW 등장 시 capture.py 폐기 예정
- 코드 참조:
  - [`backend/main.py:139-285`](../backend/main.py) — 현재 lifespan
  - [`backend/capture.py`](../backend/capture.py) — 그대로 재사용
  - [`backend/encode_upload_worker.py`](../backend/encode_upload_worker.py) — 그대로 재사용
  - [`backend/clip_recorder.py:36`](../backend/clip_recorder.py) — contract 의 자연 경계
