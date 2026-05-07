# Feature — VLM Worker (Cloud, Production)

> 현재 라벨링 웹 (`web/src/app/api/inference/route.ts`) 에서 사용자가 버튼 클릭 시에만 호출되는 VLM 추론을, **백그라운드 워커가 모든 모션 클립에 자동으로** 적용하도록 production 화. R2 직접 read + DB-as-message-bus 폴링 + idempotent INSERT.

**상태:** 🚧 fly.io 클라우드 가동 중 (2026-05-07). 1건 E2E 검증 완료. 159건 회귀 가드 + 100건 비용 추적 미해결.
**작성:** 2026-05-07
**연관 SOT:** `../../tera-ai-product-master/docs/specs/petcam-backend-dev.md`
**상위 spec:** [`cloud-migration-roadmap.md`](cloud-migration-roadmap.md)
**클라우드 배포 후속 spec:** [`feature-vlm-worker-fly-deploy.md`](feature-vlm-worker-fly-deploy.md) (✅ 완료 2026-05-07)
**선행 PoC:** [`feature-poc-vlm-web.md`](feature-poc-vlm-web.md) (Round 3 종료, v3.5 락인)

## 1. 목적

**문제:**
- VLM PoC 는 라벨링 웹에서 admin 이 클릭할 때만 동작. 일반 유저의 Flutter 앱에는 자동 라벨이 없음.
- "하이라이트" 정의 (`cloud-migration-roadmap.md` §4-7) = `behavior_logs.action ∉ ('moving', 'unknown')` 인 클립. **자동 라벨이 없으면 하이라이트 탭이 빔.**

**해결:**
- 백그라운드 워커가 `camera_clips` 폴링 → R2 영상 read → Gemini 호출 → `behavior_logs` INSERT.
- 라벨링 웹의 검수 화면 (`/clips/{id}/inference`) 은 **변경 없이** 그대로 사용 가능 (같은 테이블).

**학습 목표:** DB-as-message-bus 패턴, idempotent worker, polling cadence 결정. Round 1~3 의 v3.5 prompt 자산 + Gemini SDK 사용을 production 워커로 옮기는 ROI.

## 2. 스코프

### In
1. **`backend/vlm_worker_main.py` 신규** — standalone entrypoint, 폴링 루프.
2. **VLM SDK 포팅** — 현재 `web/src/lib/gemini.ts` 의 Gemini 호출을 Python 으로. v3.5 prompt 파일 (`web/prompts/system_base.v3.5.md`, `crested_gecko.v3.5.md`) 은 두 클라이언트 공유 (read-only).
3. **idempotency 보장** — `behavior_logs` 에 `UNIQUE (clip_id, source)` 마이그레이션 또는 NOT EXISTS 폴링 쿼리.
4. **결정론적 출력** — `temperature=0.1`, JSON 응답 강제 (donts/vlm.md 룰 6).
5. **비용 추적** — 호출당 token usage / cost 로깅. `behavior_logs.cost_usd` 컬럼 추가 검토.
6. **에러 분기** — Gemini RateLimitError 만 backoff. AuthError / BadRequest 는 즉시 raise (donts/vlm.md 룰 4).
7. **species 분기** — 현재 PoC 의 `pet.species_id` 기반 prompt 선택 그대로.

### Out
- VLM 모델 변경 (Gemini Flash 2.5 + v3.5 락인 — `next-session.md`)
- prompt 변경 (락인 — v3.6+ 시도 모두 퇴행)
- 평가셋 재구축 / 회귀 (별도 트랙)
- HITL ping 트리거 (`feature-vlm-hitl-ping.md`, 미착수)
- VLM worker 별도 레포 분리 (현재 backend/ 공유 — 후속 결정)
- 클라우드 배포 (이번 spec 은 코드 + 로컬 가동까지) — **fly.io 배포는 별도 spec [`feature-vlm-worker-fly-deploy.md`](feature-vlm-worker-fly-deploy.md) ✅ 완료**
- behavior_logs 마이그레이션 (cost_usd 등 새 컬럼) — 별도 SQL 마이그레이션 트랙

## 3. 완료 조건

- [x] `backend/vlm/gemini_client.py` — Gemini SDK 래퍼 (`google-generativeai` 0.8.6, temperature=0.1, response_mime_type=json, response_schema 강제) + R2 download helper + 일시/영구 에러 분기
- [x] `backend/vlm/prompts.py` — v3.5 prompt 로드 (`web/prompts/backups/*.v3.5.md` 직접 read) + DB→코드 species 매핑 + SPECIES_CLASSES 가용성 체크
- [x] `backend/vlm/worker.py` — `VlmWorker` 클래스 (poll_clips / process_clip / run_once / run). NOT EXISTS 폴링 + UNIQUE 23505 catch + 영구 에러 시 `source='vlm_failed'` INSERT
- [x] `backend/vlm_worker_main.py` — standalone entrypoint (`asyncio.run` + SIGTERM/SIGINT graceful shutdown), capture_main 패턴 동일
- [x] 마이그레이션 SQL — [`migrations/2026-05-07_behavior_logs_unique_clip_source.sql`](../migrations/2026-05-07_behavior_logs_unique_clip_source.sql) (사전 dedup SQL 코멘트 포함)
- [x] `pytest tests/test_vlm_worker.py` 통과 (11 tests) — 폴링 필터/limit/null r2_key, INSERT 정상/permanent/transient/duplicate, species mismatch, run_once 통계
- [x] 전체 회귀: `uv run pytest` — 235/235 통과 (이전 224 + 신규 11)
- [x] `pyproject.toml` `[project.scripts]` 에 `petcam-vlm = "backend.vlm_worker_main:run"` 추가
- [x] `docs/DEPLOYMENT.md` — 터미널 D 추가 + 마이그레이션 안내 + 배포 아키텍처 도식
- [x] `docs/ARCHITECTURE.md` — 프로세스 #3 추가 (시스템 맵, backend/ 트리, 동시성 모델, 핵심 결정 표)
- [x] **마이그레이션 실행 완료 (Supabase MCP, 2026-05-07)** — 사전 dedup (656 → 318 rows, 338 dup 삭제, latest 1건 보존) + CHECK 갱신 (`vlm_failed` 추가) + UNIQUE(clip_id, source). 검증 쿼리로 두 제약 모두 확인.
- [x] **GEMINI_API_KEY 발급 + .env 기입** — 사용자 보유 키 .env 에 기입 완료 (커밋되지 않음)
- [x] **로컬 가동 테스트 (2026-05-07)** — RPC fix 후 `VLM_POLL_INTERVAL_SEC=5 VLM_POLL_LIMIT=3 uv run python -m backend.vlm_worker_main` 실행. clip 70093109 (159 keep-set 중 미라벨 1건) → 첫 사이클에서 폴링·R2 download·Gemini call·INSERT 모두 성공. 결과 `action=moving confidence=0.90 tokens=4256/53` (human GT `moving` 일치, 이전 v3.5 inference 결과와 동일). DB 확인: `behavior_logs.source='vlm', vlm_model='gemini-2.5-flash'`. SIGTERM 클린 종료.
- [x] **fly.io 클라우드 배포 (2026-05-07)** — 별도 spec [`feature-vlm-worker-fly-deploy.md`](feature-vlm-worker-fly-deploy.md). `petcam-vlm-worker` (nrt, shared-cpu-1x 256MB, always-on, /health). E2E 검증: clip 70093109 강제 1건 → action=moving 0.9 INSERT 75초. **production 모드는 `VLM_POLL_INTERVAL_SEC=60`** (로컬 default 30s 와 다름).
- [ ] **회귀 가드** — 159건 평가셋 재인퍼런스 → 85.5% floor 미달 시 즉시 롤백 (`feature-poc-vlm-web.md` 락인 의무). **현재 측정 80.5% (사전 측정값) — production 진입 전 해결 필수, 베타테스터 가동 후 별도 트랙으로 재개**.
- [ ] **비용 추적** — 100건 처리 후 총 token / USD 기록 (현재는 logger 로만, DB 컬럼은 후속)
- [ ] 본 spec 상태 ✅ + `cloud-migration-roadmap.md` 체크박스 갱신 (회귀 가드 통과 시점)

## 4. 설계 메모

### §4-1. 폴링 쿼리 — RPC `fn_vlm_pending_clips`

**최종 결정 (2026-05-07 검증 후 락인):** PostgreSQL RPC 함수로 NOT EXISTS subquery 를 DB 안에서 직접 처리. 워커는 `sb.rpc("fn_vlm_pending_clips", {"p_limit": N})` 한 번만 호출.

```sql
-- migrations/2026-05-07_vlm_pending_clips_rpc.sql
CREATE OR REPLACE FUNCTION public.fn_vlm_pending_clips(p_limit int DEFAULT 10)
RETURNS TABLE (id uuid, r2_key text, pet_id uuid, species_id text)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
  SELECT cc.id, cc.r2_key, cc.pet_id, p.species_id
  FROM camera_clips cc
  LEFT JOIN pets p ON p.id = cc.pet_id
  WHERE cc.has_motion = true
    AND cc.r2_key IS NOT NULL
    AND NOT EXISTS (
      SELECT 1 FROM behavior_logs bl
      WHERE bl.clip_id = cc.id
        AND bl.source IN ('vlm', 'vlm_failed')
    )
  ORDER BY cc.started_at ASC
  LIMIT p_limit;
$$;
GRANT EXECUTE ON FUNCTION public.fn_vlm_pending_clips(int) TO service_role;
```

**왜 RPC 인가? — 폐기된 2-step 클라이언트 다이프 (2026-05-07)**

이전 구현은 supabase-py 로 NOT EXISTS 표현이 어려워 2-step 으로 했음:
1. `behavior_logs WHERE source IN (vlm, vlm_failed)` SELECT → done set
2. `camera_clips WHERE motion + r2_key` LIMIT N×4 → in-memory `id NOT IN done` 필터 → slice [:N]

**버그:** 클라이언트 cutoff (LIMIT N×4) 가 backlog 의 pending 위치보다 작으면 영원히 못 잡음. 실제 사고 사례 (1건 inference 검증 시) — 159건 모두 라벨된 환경에서 가장 최신 클립 1건만 pending 으로 만들어둔 상태에서 `LIMIT 12` 가 oldest-first 로 12개 가져와서 그 안에 신규가 안 들어감 → 워커 5사이클 돌아도 polled=0.

**RPC 의 엣지케이스 zero**:
- backlog 1만건 + steady-state 신규 둘 다 OK (DB 가 항상 pending 만 줌)
- 임의 위치 1건 pending 도 즉시 잡음
- 동시 워커 N대 — 같은 clip 받아도 INSERT UNIQUE(clip_id, source) 23505 race-loser 처리

**왜 ASC?** 오래된 클립부터 처리 → "하이라이트 탭" 채우는 latency 의 P99 가 한 클립 단위 (10s) 가 됨. DESC 면 부팅 직후 N건 backlog 처리 동안 새 클립 무한 대기.

**LIMIT 10 + 30초 폴링:** 한 사이클당 처리량 ≤ 10건 / 30초 = 20건/min. 카메라 2대 × 60s 세그먼트 = 2건/min 생성률 → 충분히 따라잡음. backlog 있을 때 빠르게 소진 + 평상시엔 idle.

**폴링 비용:** 30초마다 RPC 1회. RPC 함수는 `STABLE` + UNIQUE(clip_id, source) 인덱스 활용. Supabase free tier 한 달 ~86k 호출 = 무시.

**보안:** `SECURITY DEFINER` + `GRANT EXECUTE TO service_role` 만. anon/authenticated 회수 → 워커 service_role key 외 접근 차단.

### §4-2. idempotency 패턴

**옵션 A — UNIQUE 제약 (권장):**
```sql
ALTER TABLE behavior_logs
  ADD CONSTRAINT behavior_logs_clip_source_unique UNIQUE (clip_id, source);
```
- INSERT 중복 시 23505 에러 — worker 가 catch + skip.
- 단점: PoC 시절 같은 clip 에 같은 source 로 여러 번 INSERT 한 row 가 있으면 마이그레이션 실패. 사전 dedup 필요.

**옵션 B — NOT EXISTS 폴링 쿼리만:**
- 위 쿼리 (`§4-1`) 자체가 미처리 행만 가져옴. 동시 워커가 안 되도록 보장하면 충분.
- 단점: 동시 워커 N개 가동 시 race (둘 다 같은 clip 가져감) — UNIQUE 가 최후 보호막.

**결정: A + B 함께.** 마이그레이션 시점 dedup 작업은 별도 SQL.

### §4-3. R2 영상 read

PoC 는 `c.file_path` (로컬) 로 read. production 워커는 R2 직접:

```python
from backend.r2_uploader import generate_signed_url
url = generate_signed_url(clip["r2_key"], ttl_sec=600)
# Gemini 에 URL 직접 전달 (Files API) 또는 download → upload
```

**Gemini Files API:** URL 만 넘기면 Google 이 fetch — 단 internal R2 라 unauthenticated GET 가능해야 함. signed URL 이 그 역할.

**대안 — 다운로드 후 inline:** `requests.get(signed_url)` → bytes → Gemini Files upload. 더 안전 (signed URL leak 위험 ↓) 하지만 latency ↑.

**선택 — Files API + signed URL.** TTL 짧게 (10분). 워커 한 번에 처리.

### §4-4. prompt 락인 + 공유

v3.5 prompt 백업: `web/prompts/backups/{system_base,crested_gecko}.v3.5.md` (`next-session.md` 락인).

**worker 가 prompt 읽는 경로:**
- 옵션 A: `web/prompts/` 의 파일을 Python 이 직접 read (relative path)
- 옵션 B: prompt 를 `backend/vlm/prompts/` 로 복사 (sync 부담 — 실수로 한 쪽만 갱신)
- 옵션 C: DB 에 prompt 행 저장 (over-engineering)

**결정: 옵션 A.** repo root 가 같으니 `web/prompts/...` 직접 read. 장점: single source of truth. 단점: petcam-lab 레포에 web/ 가 없으면 깨짐 → 그 시점에 옵션 B 로 전환.

### §4-5. 결정론 + JSON 강제

donts/vlm.md 룰 6 따라:
```python
generation_config = {
    "temperature": 0.1,
    "top_p": 0.95,
    "response_mime_type": "application/json",
    "response_schema": {  # Gemini 의 structured output
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": [...]},
            "confidence": {"type": "number"},
            "reasoning": {"type": "string"},
        },
        "required": ["action", "confidence", "reasoning"],
    },
}
```

JSON 강제 → regex fallback 제거. 파싱 실패는 RateLimitError 와 다른 영구 에러 (모델 응답 형식 어김) — 즉시 raise + 알림.

### §4-6. 비용 추적

**스키마 추가 후보 (이번 spec Out — 별도 마이그레이션):**
```sql
ALTER TABLE behavior_logs
  ADD COLUMN cost_usd NUMERIC(10, 6);
ALTER TABLE behavior_logs
  ADD COLUMN tokens_input INT;
ALTER TABLE behavior_logs
  ADD COLUMN tokens_output INT;
```

**이번 spec:** Gemini 응답의 `usage_metadata` 를 worker 로그에만 남김. DB 컬럼 추가는 후속.

### §4-7. species 분기

PoC 코드 (`web/src/app/api/inference/route.ts:42~46`):
```typescript
const species: Species = dbSpeciesId
    ? (DB_SPECIES_TO_CODE[dbSpeciesId] ?? DEFAULT_SPECIES)
    : DEFAULT_SPECIES;
```

Python 워커도 같은 매핑 + DEFAULT_SPECIES = `crested_gecko`. 매핑 dict 는 prompt 디렉토리와 함께 read-only 공유.

### §4-8. 에러 분기 & 재시도

```python
from google.api_core.exceptions import (
    ResourceExhausted,        # 429 RateLimit → backoff
    DeadlineExceeded,          # 504 → backoff
    InternalServerError,       # 500 → backoff
    InvalidArgument,           # 400 → 영구 (raise + skip clip, 다음 사이클 또 시도하지 않게 behavior_logs 에 source='vlm_failed' INSERT 검토)
    PermissionDenied,          # 403 → 영구 (raise, 알림)
    Unauthenticated,            # 401 → 영구 (raise, 알림)
)
```

**영구 에러 시 behavior_logs INSERT 정책 (검토):**
- 옵션 A: skip → 다음 폴링 사이클에 또 시도 (무한 루프 위험)
- 옵션 B: `source='vlm_failed'` row INSERT → idempotency 자동 (UNIQUE 로 더 이상 시도 안 함)
- **선택: B.** verified=false 로 둠. 라벨러가 검수 시 수동 재시도 옵션 별도.

### §4-9. graceful shutdown

`feature-capture-worker-extraction.md` §4-2 와 같은 패턴:
- `signal.SIGTERM` → stop_event.set()
- 진행 중 클립 처리 완료 후 종료
- 새 폴링 사이클 진입 차단

### §4-10. backend/ 공유 vs 별도 레포

**현재 결정 — 같은 레포 / 같은 backend/ 패키지:**
- 같은 Supabase client / R2 client / DB 모델 / .env
- `backend/vlm/` 서브패키지로 격리

**미래 분리 트리거:**
- VLM worker 가 별도 GPU 자원 필요해지면
- 별도 팀이 관리하면
- 배포 라이프사이클이 어긋나면

지금은 모놀리식 패키지 + 두 entrypoint = 비용 0, lock-in 0.

## 5. 학습 노트

- **Gemini structured output** — `response_schema` 에 JSON Schema 박으면 모델이 강제로 그 구조로 응답. regex fallback 불필요. PoC 시점엔 unstructured 였음.
- **DB-as-message-bus의 idempotency** — 작업 큐를 DB 로 쓰면 "처리 완료" 표시는 결과 INSERT 자체. UNIQUE 제약이 동시 worker race 방어. Node 비유: BullMQ `jobId` 의 dedup.
- **polling cadence 의 두 변수** — (a) 처리 대기 latency target (b) 비용. 라벨러 큐 SLA 가 30s 라면 polling 30s. 더 짧게 가면 비용↑ + 효과 미미.
- **structured output + temperature=0** = 분류 task 의 표준 — 다양성 0, 결정론 100%. 같은 입력 = 같은 출력 (재현성).
- **prompt as file vs DB row** — file = git 추적 + diff 명확, DB row = 동적 스왑 가능. 변경 빈도 낮으면 file. 우리는 v3.5 락인이라 file.

## 6. 참고

- 상위 spec: [`cloud-migration-roadmap.md`](cloud-migration-roadmap.md) §4-4 (DB-as-message-bus), §4-8 (behavior_logs)
- PoC 결과: [`feature-poc-vlm-web.md`](feature-poc-vlm-web.md) — Round 3 락인
- 락인 (재논의 금지): v3.5 prompt, 85.5% floor, model = Gemini Flash 2.5
- Don'ts 룰: [`../.claude/rules/donts/vlm.md`](../.claude/rules/donts/vlm.md) — 모델 선택, 결정론, 재시도 정책, evidence-forcing
- 코드 참조:
  - [`web/src/app/api/inference/route.ts`](../web/src/app/api/inference/route.ts) — 현재 PoC INSERT 로직
  - [`web/src/lib/gemini.ts`](../web/src/lib/gemini.ts) — Gemini SDK 래퍼 (포팅 대상)
  - [`web/prompts/backups/system_base.v3.5.md`](../web/prompts/backups/system_base.v3.5.md) — 락인 prompt
  - [`backend/r2_uploader.py:181`](../backend/r2_uploader.py) — `generate_signed_url`
  - [`backend/routers/labels.py:227`](../backend/routers/labels.py) — `behavior_logs` SELECT (검수 UI 가 worker INSERT 결과를 바로 읽음)
