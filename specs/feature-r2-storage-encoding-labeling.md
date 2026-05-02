# feature — R2 저장 + 경량 인코딩 + GT 라벨링 웹

> 로컬 디스크에 쌓이는 원본 mp4 를 FFmpeg 로 경량화한 뒤 Cloudflare R2 에 업로드하고, Vercel 라벨링 웹에서 R2 영상을 보며 GT 라벨을 다는 파이프라인.

**상태:** 🚧 진행 중 (스코프/결정 확정 — 구현 착수 가능, 사용자 결정 6건 반영 2026-05-02)
**작성:** 2026-05-02
**연관 SOT:** `../../tera-ai-product-master/docs/specs/petcam-poc-vlm.md` (GT 라벨링 인프라가 Round 4+ 평가셋 확장의 전제) + `petcam-backend-dev.md` (영상 보관/배포)
**연관 스펙:**
- [stage-d4-thumbnail.md](stage-d4-thumbnail.md) — 썸네일 캡처 (이번에 R2 업로드 대상)
- [stage-d5-deploy-tunnel.md](stage-d5-deploy-tunnel.md) — 영상 접근 API 의 외부 공개 경로
- [feature-poc-vlm-web.md](feature-poc-vlm-web.md) — VLM PoC (라벨링 데이터 소비자)

---

## 1. 목적

**사용자 가치**
- VLM Round 3 종료 후 v3.5 = 85.5% production 락인. 잔존 오답은 **시각 한계**로 결론 → 다음 단계는 **평가셋 확장 + GT 라벨 풀 보강**. 그러려면 라벨러가 **어디서든 영상을 보고 라벨을 달 수 있어야** 함 (현재는 로컬 디스크 + curl 만 가능).
- 영상 저장이 맥북 디스크에만 의존 → 디스크 풀 리스크 (`docs/DEPLOYMENT.md` 트러블슈팅 마지막 항목). R2 가 영구 보관, 로컬은 캐시 역할.

**기술 학습 목표**
- FFmpeg CLI subprocess 호출 + CRF/codec 트레이드오프 실측
- Cloudflare R2 (S3-compatible) + signed URL 패턴
- Supabase Auth JWT 를 백엔드(FastAPI)와 라벨링 웹(Vercel) 양쪽이 공유하는 멀티 앱 구성
- 다중 라벨러 동시성 + GT 합의 처리

**왜 지금**
- VLM PoC 가 prompt 한계에 도달 (메모리 `feedback_vlm_rule_overcorrection.md`, `project_vlm_v35_baseline_lock.md`). 다음 라운드는 **데이터·UX 정공법** 으로만 진전 가능.
- R2 + 라벨링 웹은 한 묶음으로 보고 가야 가치 있음 (R2 만 있고 웹 없으면 라벨러 없음 / 웹만 있고 R2 없으면 외부에서 영상 못 봄).

---

## 2. 스코프

### In (이번 스펙에서 한다)

**스토리지 / 인코딩**
- Cloudflare R2 버킷 + access key 발급 + `.env` 설정 (`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_ENDPOINT`)
- `backend/encoding.py` — FFmpeg subprocess 래퍼 (원본 mp4 → H.264 CRF 26 + `+faststart` + audio 제거).
- `backend/r2_uploader.py` — boto3 클라이언트 + `upload_clip(local_path, r2_key)` + signed URL 생성 헬퍼.
- `backend/encode_upload_worker.py` — `asyncio.Queue` 기반 N개 worker. 캡처 워커는 세그먼트 종료 시 `(segment_path, thumb_path, base_clip_meta)` enqueue 만 하고 즉시 다음 루프. worker 가 dequeue → 인코딩 → R2 업로드 → recorder 호출 (DB INSERT). **캡처 루프 비차단 보장** (§4 결정 1).
- 인코딩/업로드 실패 단일 정책: `r2_key=NULL` 로 record 진행, 자동 재시도 없음 (§4 결정 2).
- 인코딩 비교 데이터 — CRF 23/26/28 동일 클립 20~30개 비교, 용량/PSNR/육안 검증 1회. 결과는 본 스펙 §4 에 표로 추가.

**DB 확장**
- `camera_clips`:
  - `r2_key TEXT NULL` (인코딩된 mp4 의 R2 object key)
  - `thumbnail_r2_key TEXT NULL`
  - `encoded_file_size BIGINT NULL` (R2 에 올라간 경량 mp4 바이트)
  - `original_file_size BIGINT NULL` (로컬 원본, 인코딩 비교용)
  - `file_path` / `thumbnail_path` 는 **유지** (로컬 fallback)
- `behavior_labels` 신규 테이블:
  - `id UUID PK / clip_id UUID FK / labeled_by UUID FK auth.users / action TEXT / lick_target TEXT NULL / note TEXT NULL / labeled_at timestamptz`
  - `action`: 5 main class — `eating_paste / drinking / moving / unknown` (+ raw 호환용 `eating_prey / defecating / shedding / basking / unseen` 도 enum 으로 허용; 라벨링 UI 는 5개 노출 + 더보기로 raw 9개)
  - `lick_target` (NULL 가능): `air / dish / floor / wall / object / other` — `eating_paste / drinking` 선택 시에만 라벨러에게 노출. **`air_lick` 은 raw action 이 아니라 (action=eating_paste, lick_target=air) 조합으로 표현** (사용자 결정 2026-05-02)
  - 한 클립 × 여러 라벨러 = 여러 row. UNIQUE(clip_id, labeled_by) 로 한 라벨러가 한 클립에 하나만.
  - 합의는 별도 view 또는 후처리 (이번 스펙 Out)
- `labelers` 신규 테이블 (팀 라벨러 화이트리스트):
  - `user_id UUID PK FK auth.users / added_at timestamptz / note TEXT NULL`
  - 이 테이블에 들어있는 user 는 자기 소유가 아닌 클립도 R2 영상 + 라벨 폼 접근 가능
  - service_role 만 INSERT/DELETE (관리자 수동). 일반 사용자는 SELECT 도 불가

**API**
- `GET /clips/{id}/file` — `r2_key` 있으면 signed URL 302 redirect. 없으면 기존 로컬 스트리밍.
  - 권한: 클립 owner OR `labelers` 멤버
- `GET /clips/{id}/thumbnail` — 동일 패턴 + 동일 권한.
- `POST /clips/{id}/labels` — 라벨 1건 저장. body: `{action, lick_target?, note?}`. `(clip_id, labeled_by)` UPSERT.
  - 권한: 클립 owner OR `labelers` 멤버
- `GET /clips/{id}/labels` — 해당 클립 라벨 목록.
  - 권한: 클립 owner (모든 라벨러의 라벨 조회) OR `labelers` 멤버 (본인 라벨만)
- `GET /labels/queue` — 라벨러용 큐. 미라벨 클립 우선 정렬 (최신순).

**라벨링 웹 (`web/labeling/`)**
- Next.js + Supabase Auth 로그인 (기존 `/web` 와 분리 디렉토리, 같은 Vercel 프로젝트면서 다른 라우트일 수도 있음 — 설계 메모에서 결정).
- 화면 1: 라벨링 대상 클립 목록 (필터: 카메라 / 날짜 / 미라벨 only).
- 화면 2: 단건 라벨링 — R2 영상 재생 + action 4 메인 버튼 (`eating_paste`, `drinking`, `moving`, `unknown`) + (`eating_paste`/`drinking` 선택 시) lick-target sub-question (air/dish/floor/wall/object/other) + 메모 + 저장. raw 9 클래스는 "더보기"에 숨김.
- 라벨 저장 → `POST /clips/{id}/labels` (백엔드 경유. 라벨링 웹이 직접 Supabase 에 쓰지 않음 — 권한·검증·감사 로그 일원화).
- 진행률 표시 (라벨러 본인이 오늘 라벨한 개수).

**문서**
- `docs/DEPLOYMENT.md` — R2 설정 절차 추가
- `docs/ENV.md` 또는 `.env.example` — R2 환경변수 추가
- `docs/DATABASE.md` — `camera_clips` 새 컬럼 + `behavior_labels` 테이블 문서화
- 본 스펙 — 작업 중 결정사항 누적

### Out (이번 스펙에서 안 한다)

- **로컬 원본 mp4 자동 삭제 / cleanup job** — 보관 정책은 §4 결정 메모에 적어두되, 자동 삭제 cron 은 다음 스펙 (`feature-clip-retention.md` 가칭). 우선은 수동 삭제.
- **R2 영상 보관 기간 정책 자동화** — 동일하게 자동 삭제 미포함. 영구 저장 가정 + 비용 모니터링만.
- **Flutter 앱 R2 대응** — 이번엔 라벨링 웹만. Flutter 는 백엔드 redirect 만으로 자동 동작 (signed URL 302 따라가니까), 추가 변경 없음 가정 — 실기 검증으로 확인.
- **GT 합의 알고리즘** — 다중 라벨 충돌 시 "최종 GT" 자동 결정 룰. 이번엔 raw 라벨만 쌓고 수동 합의. 합의 자동화는 `feature-gt-consensus.md` (가칭) 별도.
- **Round 4 평가셋 빌드 자동화** — 라벨된 클립을 jsonl 로 export 하는 스크립트는 라벨링 인프라가 데이터 충분히 쌓인 뒤. 이번 스펙 Out.
- **VLM 자동 prelabel** — "AI 가 미리 라벨 → 사람이 검수" 흐름은 Round 4 본격화 후. 이번엔 0-shot 사람 라벨만.
- **다중 라벨러 충돌 UI** — 동일 클립을 동시에 두 명이 보는 lock / 알림 / 편집 충돌 처리. MVP 에선 last-write-wins + 본인 라벨만 본인이 수정 가능.
- **CDN 가속 / 지역 최적화** — R2 자체가 Cloudflare 엣지라 별도 CDN 불필요 가정. 실측 후 필요하면 다음 스펙.
- **새 카메라 / 새 라벨 클래스 / 새 펫** — 기존 cam1/cam2 + 9-class raw + crested gecko 전제.
- **VLM Round 4 평가 자체** — 이 스펙의 산출물(라벨 데이터)을 받아서 다음 스펙(`feature-vlm-round4.md`)에서 진행.

> **스코프 변경은 합의 후에만.** 작업 중 In/Out 흔들리면 이 섹션 수정 + 사유 기록.

---

## 3. 완료 조건

체크리스트가 곧 진행 상태.

### 3-1. R2 인프라

- [x] Cloudflare R2 버킷 생성 (`petcam-clips`) + access key 발급 — 2026-05-02
- [x] `.env` / `.env.example` 에 R2 환경변수 5종 추가 (`R2_ACCOUNT_ID` / `R2_ENDPOINT` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_BUCKET`)
- [x] `backend/r2_uploader.py` — boto3 client (path-style addressing) + `upload_clip()` + `generate_signed_url(key, ttl_sec)`
- [x] `tests/test_r2_uploader.py` — moto 기반 unit test (실 R2 호출은 `scripts/verify_r2.py` 로 분리)
- [x] 수동 검증: `scripts/verify_r2.py` 라운드트립 통과 (786KB mp4 → upload → signed URL → urllib GET → SHA-256 일치 → 삭제) — 2026-05-02

### 3-2. FFmpeg 인코딩

- [x] `ffmpeg` 설치 확인 (Homebrew 가정) + 버전 명시 (`docs/ENV.md`) — `ffmpeg version 7.x (Homebrew)` 확인됨, `shutil.which("ffmpeg")` 런타임 체크 + `FFmpegNotFound` 예외
- [x] `backend/encoding.py` — `encode_lightweight(src, dst, crf=26, preset="veryfast") -> bool` 구현. `-c:v libx264 -crf 26 -preset veryfast -movflags +faststart -an`
- [x] 인코딩 실패 시 (returncode != 0 / timeout / 0바이트 출력) → False + warning 로그 + 부분 출력 cleanup. 호출 측 단일 정책 (§4 결정 2)
- [x] `tests/test_encoding.py` — 12 케이스 통과: 정상 인코딩 / audio strip / CRF 23>28 사이즈 / src 누락·디렉토리·src==dst raise / FFmpegNotFound / 깨진 입력 False+cleanup / dst 부모 누락 / `DEFAULT_CRF==26` 회귀 / `ENCODE_TIMEOUT_SEC==30` 회귀
- [x] CRF 비교: 실 클립 23개 × {CRF 23, 26, 28} 인코딩 → §4 결정 10 표 기록 (CRF 26 채택 근거)

### 3-3. DB 마이그레이션

- [x] **M1** `camera_clips` ALTER — R2 컬럼 4개 추가 (모두 NULL) — 적용 2026-05-02 (`add_r2_columns_to_camera_clips`)
- [x] **M2** `labelers` CREATE TABLE + RLS ENABLE + 정책 0건 (service_role 전용) — 적용 2026-05-02 (`create_labelers_table`)
- [x] **M3** `behavior_labels` CREATE TABLE + 인덱스 + RLS 정책 (본인 row 또는 clip owner) — 적용 2026-05-02 (`create_behavior_labels_table`)
- [x] Supabase information_schema 로 컬럼/테이블/RLS/인덱스 재확인 — 4컬럼·2테이블·4정책·5인덱스 전부 정상
- [x] `docs/DATABASE.md` 업데이트 (camera_clips 새 컬럼 + behavior_labels + labelers + lick-target 차원 설명) — 적용 2026-05-02

**M1 — `camera_clips` R2 컬럼 추가**
```sql
ALTER TABLE camera_clips
  ADD COLUMN r2_key TEXT,
  ADD COLUMN thumbnail_r2_key TEXT,
  ADD COLUMN encoded_file_size BIGINT,
  ADD COLUMN original_file_size BIGINT;

COMMENT ON COLUMN camera_clips.r2_key IS 'R2 mp4 object key. NULL = 인코딩/업로드 실패 또는 백필 전 (로컬 fallback).';
COMMENT ON COLUMN camera_clips.thumbnail_r2_key IS 'R2 썸네일 jpg key. NULL 의미는 r2_key 와 동일.';
COMMENT ON COLUMN camera_clips.encoded_file_size IS '인코딩 후 R2 mp4 바이트. NULL = R2 미업로드.';
COMMENT ON COLUMN camera_clips.original_file_size IS '인코딩 전 원본 mp4 바이트 (capture.py 출력). file_size 와 같은 값을 인코딩 시점에 박아 압축률 분석용.';
```

**M2 — `labelers` 화이트리스트**
```sql
CREATE TABLE labelers (
  user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  added_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  note TEXT,
  added_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE labelers ENABLE ROW LEVEL SECURITY;
-- 정책 0건 = service_role 전용 (clip_mirrors 와 동일 패턴).
-- 라벨러 추가/제거는 백엔드 service_role 또는 SQL 수동.

COMMENT ON TABLE labelers IS '팀 라벨러 화이트리스트. 멤버는 모든 클립 영상/라벨 폼 접근 가능. service_role 전용 (RLS 0건).';
```

**M3 — `behavior_labels`**
```sql
CREATE TABLE behavior_labels (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id UUID NOT NULL REFERENCES camera_clips(id) ON DELETE CASCADE,
  labeled_by UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  action TEXT NOT NULL,         -- enum 검증은 Pydantic 레벨 (결정 6: B). 9 raw 클래스 허용.
  lick_target TEXT,             -- NULL 또는 air/dish/floor/wall/object/other. action=eating_paste|drinking 일 때만 의미.
  note TEXT,
  labeled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (clip_id, labeled_by)
);

CREATE INDEX idx_behavior_labels_clip_id ON behavior_labels (clip_id);
CREATE INDEX idx_behavior_labels_labeled_at_desc ON behavior_labels (labeled_at DESC);

ALTER TABLE behavior_labels ENABLE ROW LEVEL SECURITY;

-- SELECT: 본인 row(labeled_by) OR clip owner.
--   라벨러 멤버 체크는 백엔드 API 가 service_role 로 검증 (결정 4 메모 참조 — RLS 단순화).
CREATE POLICY behavior_labels_select ON behavior_labels
  FOR SELECT
  USING (
    auth.uid() = labeled_by
    OR auth.uid() = (SELECT user_id FROM camera_clips WHERE id = behavior_labels.clip_id)
  );

-- INSERT: 본인 row 만 (clip 권한은 백엔드에서 service_role 키로 검증).
CREATE POLICY behavior_labels_insert ON behavior_labels
  FOR INSERT
  WITH CHECK (auth.uid() = labeled_by);

CREATE POLICY behavior_labels_update ON behavior_labels
  FOR UPDATE
  USING (auth.uid() = labeled_by)
  WITH CHECK (auth.uid() = labeled_by);

CREATE POLICY behavior_labels_delete ON behavior_labels
  FOR DELETE
  USING (auth.uid() = labeled_by);

COMMENT ON TABLE behavior_labels IS 'GT 라벨. 한 클립 × 여러 라벨러 = 여러 row (UNIQUE clip_id+labeled_by). Round 4 평가셋 source.';
```

**RLS 모순 정리** (결정 4 의 원안 vs 적용 차이)
- 결정 4 원안: `INSERT WITH CHECK ... auth.uid() IN labelers`. 하지만 `labelers` 자체가 service_role 전용이라 anon/authenticated 가 SELECT 못 → 정책 평가가 라벨러를 인지 못함.
- 해결안 A: `labelers` SELECT 정책 풀기 — 라벨러 명단 노출 위험.
- 해결안 B: `SECURITY DEFINER` 함수로 우회 — 추가 추상화.
- **채택 (C)**: RLS 는 "본인 row" 만 검증 (anon/authenticated 직접 접근 봉인 효과). 라벨러 권한은 백엔드 API 가 `service_role` 키로 SELECT/INSERT 하면서 코드로 `is_labeler(user_id)` 확인. 결정 4 메모의 "RLS 는 supplement, 백엔드 검사가 main" 원칙과 일관.

### 3-4. 캡처 → 인코딩 → 업로드 파이프라인

- [x] `backend/encode_upload_worker.py` 신규 — `asyncio.Queue` 기반 worker. capture thread → `loop.call_soon_threadsafe` 로 enqueue, worker 가 dequeue → 인코딩 → R2 업로드 → recorder 호출 — 2026-05-02
- [x] `backend/capture.py` 변경 없음 — `clip_recorder` 슬롯에 `EncodeUploadWorker.make_enqueue_callback(recorder)` 를 끼워서 캡처 루프가 enqueue 만 하고 즉시 다음 프레임 (인터페이스 그대로 유지 → 기존 테스트 무회귀) — 2026-05-02
- [x] worker concurrency = `max(1, len(camera_rows))` (카메라 수와 동일). `lifespan` startup `start()` / shutdown `await stop()` 으로 drain — 2026-05-02
- [x] **인코딩 실패 단일 정책**: encode_upload_worker 의 `_fallback_record` 로 통합 처리 — 인코딩 실패 / mp4 업로드 실패 / queue full / loop down 모두 `r2_key=NULL` 로 recorder 호출. 자동 재시도 없음 (spec §4 결정 2)
- [x] `clip_recorder.py` payload 가 새 필드 `id` / `r2_key` / `thumbnail_r2_key` / `encoded_file_size` / `original_file_size` 받아 통과. mirror 경로는 `id` 만 drop (unique violation 방지) + 나머지 r2 메타 공유 — 2026-05-02
- [x] `pending_inserts` 는 dict 직렬화 — 새 필드 자동 통과 (별도 코드 변경 없음, JSON 직렬화 검증으로 충분)
- [x] `tests/test_encode_upload_worker.py` — 9 케이스 통과: success / no thumb / encode fail / mp4 upload fail / thumb-only fail / queue full → 즉시 fallback / stop drain / stop 후 enqueue → fallback / R2 키 날짜 fallback (started_at)
- [x] **실기 검증** (backfill 갈음 — 사용자 결정 2026-05-02): 신규 5건 모션 대신 누적 motion 클립 backfill 로 R2 인프라 가동 확인. **227/227 succ, 0 fail, 8.6분, 평균 압축 44.5%** (914 MB → 410 MB, 504 MB 절감). encode + R2 mp4/thumb 업로드 + DB UPDATE 일관 동작 확인. worker queue 는 backfill 별도 process 라 무관, 백엔드 EncodeUploadWorker 자체는 `/health.encode_upload_queue=0` 로 정상 (capture worker auto-upload 수신 중 idle 246건 자동 업로드도 함께 검증됨) — 2026-05-02
  - **사용자 결정 (2026-05-02)**: 다음 세션 즉시 착수 항목. 통과하면 §3-7 라벨링 웹 배포 (Vercel + DNS + 부트스트랩 SQL) 로 넘어감.
  - 검증 절차:
    1. 서버 가동 — `uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000`. 로그에 `EncodeUploadWorker started (workers=N)` 떠야 함.
    2. 카메라 모션 5건 — 카메라 앞에서 손/도마뱀 움직여 motion segment 5개 생성. 또는 idle 30s 대기 후 motion 트리거 반복.
    3. DB 검증 SQL — Supabase Studio 또는 `uv run python -c`:
       ```sql
       SELECT id, started_at, has_motion, r2_key, encoded_file_size, original_file_size
       FROM camera_clips
       WHERE started_at > NOW() - INTERVAL '15 min'
       ORDER BY started_at DESC LIMIT 10;
       ```
       - 기대: motion 5건 모두 `r2_key` NOT NULL + `encoded_file_size < original_file_size` (CRF 26 압축 효과)
    4. R2 콘솔 — Cloudflare R2 → bucket → `clips/{camera_id}/{date}/{id}.mp4` + `thumbs/{camera_id}/{date}/{id}.jpg` 5쌍 확인. 인코딩된 mp4 가 원본 대비 줄었는지 (보통 30~60%).
    5. queue depth — `curl http://127.0.0.1:8000/health | jq .encode_upload_queue` 로 worker 큐 backlog 관찰. 60s 세그먼트 길이 초과해 쌓이면 alarm (인코딩이 캡처 못 따라감).
  - 실패 시 분기: `r2_key=NULL` 인 row 발견 → 백엔드 로그에서 "encode failed" / "R2 upload failed" / "queue full" 중 어느 fallback 인지 확인 → §4 결정 2 단일 정책대로 후속 batch backfill 또는 코드 fix.
  - **batch backfill 스크립트** — `scripts/backfill_motion_r2.py`. spec §4 결정 2 후속. `--dry-run` / `--limit N` / `--all-null` (기본 motion-only). 인코딩 워커와 병행 가능 (R2 키에 row id 포함 → 충돌 없음). `r2_key IS NULL AND camera_id IS NOT NULL` 가드 — PoC VLM 업로드 클립 (camera_id NULL) 88건 자동 skip — 2026-05-02
  - **남은 결정 — NULL camera_id 88건 motion 클립** (Round 1 PoC VLM 사용자 업로드, `web/storage/poc-clips/` 경로): R2 업로드 안 됨. 옵션 (a) 그대로 skip 유지 (PoC 평가셋과 별개라 라벨링 가치 낮음) (b) `ROUND1_CAMERA_ID=3a6cffbf` (cam2) attribution 후 backfill (단 metadata noise) (c) pseudo-camera "poc-upload" 신설 후 backfill (정확하지만 schema 작업). **사용자 결정 대기.**

### 3-5. 영상 접근 API

- [x] `GET /clips/{id}/file` — `r2_key` 있으면 `RedirectResponse(signed_url, 302)`. 없으면 기존 로컬 StreamingResponse — 2026-05-02
- [x] `GET /clips/{id}/thumbnail` — 동일 패턴 (`thumbnail_r2_key`) — 2026-05-02
- [x] signed URL TTL = 1시간 (`SIGNED_URL_TTL_SEC = 3600` in `clips.py`). 회귀 테스트 `expires=3600` 포함 — 2026-05-02
- [x] 권한: clip owner OR `labelers` 멤버. 헬퍼 `_load_clip_with_perms` + `_is_labeler` (owner short-circuit, labelers fallback). 외부인은 404 (존재 leak 방지) — 2026-05-02
- [x] `tests/test_clips_api.py` 확장 — 12 신규 테스트 (file 6분기 × thumbnail 6분기). `mock_signed_url` fixture 로 R2 호출 차단 + 권한 거부 시 `generate_signed_url` 호출 0회 회귀 — 2026-05-02
- [ ] **실기 검증** (사용자 직접): 라벨링 웹에서 R2 영상 재생 + seek + 모바일 브라우저 재생 (썸네일 포함) — 라벨링 웹 §3-7 가동 후

### 3-6. 라벨 API

- [x] `POST /clips/{id}/labels` — body: `{action, lick_target?, note?, labeled_by?}`. Pydantic enum 검증 (action 9 raw / lick_target 6) + clip 존재 확인 + `(clip_id, labeled_by)` UPSERT (`on_conflict="clip_id,labeled_by"`) — 2026-05-02
- [x] **owner override (관리자/테스터 검수용)** — `body.labeled_by` 가 본인이 아니면 clip owner 검사 → owner 면 강제 생성/수정, 아니면 403. labeler 멤버라도 다른 라벨러 라벨은 못 건드림 — 2026-05-02
- [x] `GET /clips/{id}/labels` — owner: 모든 라벨러 결과 / labeler: 본인만 (load_clip_with_perms + 분기 한 줄) — 2026-05-02
- [x] `GET /labels/queue?limit=N&cursor=...` — 본인 라벨한 clip_id 제외 → labelers 멤버면 전 user 클립, 비-라벨러는 본인 클립만. seek pagination (started_at desc + cursor) — 2026-05-02
- [x] `tests/test_labels_api.py` — 19 케이스 통과: POST owner/labeler/외부인/잘못된 action 422/잘못된 lick_target 422/clip 없음 404/UPSERT replace/9 raw 액션 전부 통과 (8) + **owner override (강제 수정/타인 신규/labeler 403/self 통과) (4)** + GET owner 전체/labeler 본인만/외부인 404 (3) + queue owner 본인만 미라벨/labeler 전 클립/cursor pagination/all labeled empty (4) — 2026-05-02
- [x] 헬퍼 추출 — `backend/clip_perms.py` 신설 (`is_labeler`, `load_clip_with_perms`). 4+ 호출 지점 (clips file/thumbnail + labels POST/GET + queue) 공유. — 2026-05-02

### 3-7. 라벨링 웹

- [x] `web/labeling/` 부트스트랩 — 기존 `/web` 안에 신규 라우트 (spec §4 결정 5 추천 A 채택). `web/src/app/labeling/{login,page,[clipId]}` 3 라우트 + `LabelingLayout` 클라이언트 인증 게이트 — 2026-05-02
- [x] Supabase Auth 로그인 — `web/src/lib/supabaseBrowser.ts` (anon + persistSession), email/password 폼. 회원가입 폼 없음 (관리자 SQL 만으로 가입 — `auth.users` + `labelers` row INSERT) — 2026-05-02
- [x] 클립 목록 화면 — `GET /labels/queue` 호출 (백엔드가 본인 라벨 제외 + labeler/owner 스코프 분기). 카드 그리드, 모션/정지 뱃지, 더보기 페이지네이션 — 2026-05-02
- [x] 단건 라벨링 화면 — `<video>` 로 R2 영상 재생 (신규 `GET /clips/{id}/file/url` JSON 으로 signed URL 받아 src 박음, cross-origin Authorization 우회) + action 4 메인 + (조건부) lick_target 6 + raw 5 더보기 + 메모 — 2026-05-02
- [x] 저장 후 다음 클립으로 자동 이동 — `createLabel` 직후 `getQueue({limit:1})` → 첫 row 로 `router.push` — 2026-05-02
- [x] CORS 미들웨어 + `/file/url` `/thumbnail/url` JSON 엔드포인트 + 기존 `/file` `/thumbnail` 회귀 보존 (8 신규 테스트, 총 59 통과) — 2026-05-02
- [ ] Vercel 배포 + 도메인 (예: `label.tera-ai.uk`) — Cloudflare DNS 추가 — 사용자 작업
- [ ] 라벨러 계정 부트스트랩 SQL — Supabase Studio 에서 `auth.users` INSERT + `labelers` INSERT — 사용자 작업
- [ ] 실기 검증: 라벨러 1명이 모바일/PC 양쪽에서 클립 10개 라벨 → DB 에 정확히 쌓임 — 사용자 작업

### 3-8. 문서 / 정리

- [x] `docs/DEPLOYMENT.md` R2 섹션 (계정·키 발급 + bucket 생성 + 환경변수 + Vercel + 라벨러 부트스트랩 SQL) — 2026-05-02
- [x] `docs/ENV.md` R2 환경변수 + CORS 섹션 (R2 7종 + LABELING_WEB_ORIGINS) — 2026-05-02
- [x] `docs/DATABASE.md` 새 컬럼 + 새 테이블 (labelers + behavior_labels + r2 컬럼) — 직전 세션 적용 완료
- [x] `README.md` 영상 저장 흐름 갱신 (folder structure: web/, storage 로컬 캐시, test count 204) — 2026-05-02
- [x] 본 스펙 §4 결정 5/5-1/5-2 + §5 학습 노트 (Supabase Auth client/server, Next.js auth gate, CORS preflight + Authorization, video cross-origin Authorization 한계) — 2026-05-02
- [x] `specs/README.md` 목록 표 갱신 ("2026-05-02 코드 완료, 사용자 가동 대기") — 2026-05-02
- [x] `specs/next-session.md` 갱신 — 2026-05-02
- [x] `.claude/donts-audit.md` 한 줄 추가 (Rules of Hooks 위반 + JSON URL 엔드포인트 패턴 메모) — 2026-05-02

---

## 4. 설계 메모

작업 중 결정사항 누적. **현재는 초안 — 사용자 확인 후 본격 작업하면서 채움.**

### 결정 1: 인코딩/업로드를 캡처 루프와 분리 (확정 — worker queue)

- **확정: B (worker queue)** (사용자 결정 2026-05-02)
- 구조: `backend/encode_upload_worker.py` 에 `asyncio.Queue` + N 개 worker task. lifespan startup 에서 N task 기동, shutdown 에서 `queue.join()` 후 cancel.
- 캡처 워커는 세그먼트 종료 시 `(segment_path, thumb_path, base_clip_meta)` enqueue 만 하고 즉시 다음 루프. 인코딩/업로드 완료 후 worker 가 `recorder(...)` 호출 → DB INSERT.
- worker concurrency: 카메라 수 = 2 로 시작 (한 카메라당 1개 worker 가용 → 60초 세그먼트당 인코딩+업로드 충분 마진). 카메라 늘리면 N 도 같이.
- **이유**: (a) 캡처 루프 완전 비차단 — RTSP 끊김 / 재연결 / 다음 세그먼트 시작 보장. (b) worker queue 길이 모니터링으로 인코딩이 따라오는지 즉시 가시. (c) donts/python.md 룰 4·5 (블로킹 I/O async 분리) 정공법.
- **리스크**: queue 가 무한정 쌓이면 메모리 ↑. maxsize 설정 + 가득 찼을 때 enqueue 실패 → record 만 진행 (`r2_key=NULL`) 로 fallback.

### 결정 2: 인코딩/업로드 실패 시 동작 (확정 — 단일 정책)

- **확정 정책 (사용자 결정 2026-05-02)**: 모든 실패 케이스 → `r2_key=NULL` 로 DB record 진행, 로컬 원본만 유지. **자동 재시도 없음.** 후속 batch backfill 스크립트 (이번 스펙 Out) 에서 일괄 처리.
- 적용 범위:
  - 인코딩 실패 (FFmpeg returncode != 0 또는 timeout) → R2 업로드 스킵
  - R2 업로드 실패 (네트워크 / 인증 / R2 5xx) → record 만 진행
  - queue 가득참 → record 만 진행
- **이유**: 단순한 운영 모델. 라벨러는 `r2_key IS NULL` 필터로 결손 클립 식별 → 백필 스크립트 1회 실행으로 일괄 복구. 인라인 재시도는 캡처 워커 부담 + 코드 복잡.

### 결정 3: signed URL TTL

- 1시간 — 모바일 브라우저에서 동영상 재생 도중 만료될 일 없음. 라벨링 페이지 떠나면 다음 페이지에서 새로 발급.
- 더 짧게(10분) → 만료된 URL 재생 시 흔들림. 더 길게(24시간) → URL 유출 시 위험 증가 (R2 는 대부분 사적 데이터).

### 결정 4: 팀 라벨러 권한 모델 (확정 — labelers 화이트리스트 + 권한 매트릭스)

사용자 결정 (2026-05-02): MVP 부터 팀 라벨러 모델 박는다.

**역할**
- **owner**: clip 의 `user_id` 와 일치하는 사용자. 본인 클립 라벨 + 모든 라벨러의 라벨 결과 조회.
- **labeler**: `labelers` 테이블에 등록된 사용자. 자기 소유 아닌 클립도 R2 영상 + 라벨 폼 접근 가능. 본인 라벨만 수정.
- **외부인**: 둘 다 아님. 401/403.

**권한 매트릭스**

| 작업 | owner | labeler | 외부인 |
|---|---|---|---|
| `GET /clips` (목록) | 본인 user_id 클립만 | labelers 멤버면 모든 클립 | 본인 user_id 클립만 |
| `GET /clips/{id}/file` (R2/로컬 영상) | ✅ 본인 클립 | ✅ 모든 클립 | ❌ |
| `GET /clips/{id}/thumbnail` | ✅ 본인 클립 | ✅ 모든 클립 | ❌ |
| `POST /clips/{id}/labels` | ✅ 본인 클립 (자기 row OR `labeled_by` override 로 타인 row 강제 수정) | ✅ 모든 클립 (자기 row UPSERT 만) | ❌ |
| `GET /clips/{id}/labels` | ✅ 모든 라벨러 결과 조회 (본인 클립) | ✅ 본인 라벨만 | ❌ |
| `GET /labels/queue` | 본인 클립 미라벨 | labelers 권한 안에서 미라벨 | ❌ |

**RLS 정책**
- `behavior_labels`:
  - INSERT/UPDATE/DELETE: `auth.uid() = labeled_by` AND (`auth.uid() = clip.user_id` OR `auth.uid() IN labelers`)
  - SELECT: `auth.uid() = labeled_by` OR `auth.uid() = clip.user_id` OR `auth.uid() IN labelers AND labeled_by = auth.uid()`
- `labelers`: SELECT/INSERT/UPDATE/DELETE 모두 service_role 만. 일반 사용자는 봉인.
- 백엔드 API 는 `Depends(get_current_user_id)` + 명시적 `is_labeler(user_id)` 체크 (`labelers` SELECT) 후 SQL 분기.

**왜 RLS + 백엔드 양쪽 검사**: RLS 가 최후 방어선, 백엔드 검사가 일관된 에러 메시지 + 감사 로그.

**MVP 사용자**: owner 본인 1명 + labelers 0~2명 (본인 + QA 테스터 추가 가능). 라벨러 추가는 SQL `INSERT INTO labelers (user_id) VALUES ('<uuid>')` 수동.

### 결정 5: 라벨링 웹의 위치 (확정 — A)

- **확정 A (`web/src/app/labeling/`)** — 2026-05-02 구현
- 기존 `web/` Next.js 안에 새 라우트로. URL `/labeling`. UI 컴포넌트 (`Card`, `Button`, `Badge`) + Tailwind 그대로 재사용.
- Supabase Auth 는 별도 클라이언트 — `web/src/lib/supabaseBrowser.ts` (anon key + persistSession). 기존 `supabase.ts` (server-only service_role) 와 **완전 분리**: anon 키는 client bundle 노출 OK (RLS 가 책임), service_role 은 절대 노출 금지.
- `AppHeader` 는 `pathname.startsWith('/labeling')` 일 때 null 반환 — 라벨링은 별도 헤더 (`LabelingLayout`) 사용. 두 헤더 동시 렌더 방지.
- 도메인 분리는 라벨러가 비-소유자로 늘어나면 그때 (별도 Vercel 프로젝트 또는 같은 프로젝트의 도메인 alias).

### 결정 5-1: 영상 src 인증 우회 — `/file/url` JSON 엔드포인트 (확정)

- **문제**: `<video src>` 는 cross-origin 요청에 Authorization 헤더 못 박음. 302 redirect 도 따라가다 헤더 잃음. 라벨링 웹 (다른 origin) 에서 인증된 영상 재생 불가.
- **해결**: `GET /clips/{id}/file/url` (썸네일은 `/thumbnail/url`) — JSON `{url, ttl_sec, type}` 반환. 권한·R2 분기는 기존 `/file` 와 동일 (헬퍼 `load_clip_with_perms` 재사용).
- 프론트는 `request<PlaybackUrl>` 로 Authorization 헤더 붙여 호출 → R2 signed URL 받음 → `<video src={url}>` 박음. signed URL 자체가 단발 토큰이라 추가 인증 불필요.
- 로컬 fallback (`r2_key=NULL`): 같은 origin (AUTH_MODE=dev) 에서만 의미. 상대 경로 `/clips/{id}/file` 반환, 프론트가 `BACKEND_URL` prefix.
- **이유**: industry 표준 패턴 (S3/R2 signed URL UI). 1 round-trip 추가 비용 vs Authorization 헤더 우회 위해 ?token= query 쓰는 보안 안티패턴 회피.

### 결정 5-2: 라벨러 계정 부트스트랩 SQL (사용자 작업)

라벨링 웹은 회원가입 폼을 노출하지 않음. 신규 라벨러 추가는 관리자가 Supabase Studio 에서 직접:

```sql
-- 1. auth.users 에 사용자 생성 (Supabase Studio → Authentication → Users → Invite)
--    또는 SQL:
INSERT INTO auth.users (id, email, encrypted_password, email_confirmed_at, ...)
VALUES (gen_random_uuid(), 'labeler@example.com', crypt('temp-password', gen_salt('bf')), now(), ...);

-- 2. labelers 테이블에 등록 — 멤버만 다른 user 클립 라벨 가능
INSERT INTO labelers (user_id, added_by, note)
VALUES ('<auth.users.id 값>', '<관리자 user_id>', 'Round 4 GT 라벨러');
```

**왜 회원가입 봉인**: 라벨러는 신뢰 그룹 (소수 + 데이터 접근 권한). 자유 가입 = 데이터 유출 리스크. Round 5+ 에서 외부 라벨러 도입 시 별도 승인 플로우 추가.

### 결정 6: behavior_labels 의 label enum 관리

- **선택안 A (DB CHECK constraint + Postgres enum 타입)**: 변경 시 마이그레이션 필요. 안전.
- **선택안 B (앱 레벨 검증만)**: TEXT 컬럼 + FastAPI Pydantic 에서 검증. 라벨 추가가 코드 변경.
- **추천: B** — 라벨 클래스가 VLM 진화 따라 바뀔 가능성 (9 raw → 8 → ...). DB 레벨 enum 변경은 부담. 앱 레벨 검증으로 충분 + 잘못된 라벨 들어와도 분석 단계 필터링 가능.

### 결정 7: R2 object key 네이밍 (확정 — clip_id 포함)

사용자 결정 (2026-05-02): clip_id (UUID) 를 키에 포함.

- **mp4**: `clips/{camera_id}/{YYYY-MM-DD}/{HHMMSS}_{tag}_{clip_id}.mp4`
  - 예: `clips/3c1...74/2026-05-02/153012_motion_8e2f...91.mp4`
- **썸네일**: `thumbnails/{camera_id}/{YYYY-MM-DD}/{HHMMSS}_{tag}_{clip_id}.jpg`

**왜 clip_id 포함**:
- DB row ↔ R2 object 1:1 매칭이 키 자체에서 보장 (디버깅·고아 객체 탐지 쉬움)
- 동일 시각 충돌 방지 (이론적으로 같은 카메라가 같은 초에 두 세그먼트 종료 가능 — 거의 없지만 0 은 아님)
- 라벨링 웹에서 R2 key 만 보고도 어떤 clip_id 인지 즉시 파악

**구현 메모**: clip_id 는 INSERT 전에 미리 `uuid.uuid4()` 로 생성해서 worker → recorder → DB 까지 같은 UUID 전달. 현재 capture/recorder 흐름은 DB 가 UUID 자동 생성 (`gen_random_uuid()`) 라 변경 필요 — payload 에 `id` 명시 박아 INSERT.

### 결정 8: 기존 396개 클립 백필

- 현재 `storage/clips/` 에 쌓인 클립을 R2 로 일괄 업로드할지?
- **추천**: 별도 스크립트 `scripts/backfill_clips_to_r2.py` 작성. 본 스펙 In 에 포함하되 우선순위 낮음 (라벨링 웹 가동 시 기존 클립도 라벨할 수 있어야 함). 백필 안 하면 기존 클립은 로컬 fallback path 로만 접근 가능 → 라벨러가 외부망에서 못 봄.
- → **In 으로 추가하지 않고**, 라벨링 웹 1차 가동 후 필요성 판단. (이번 스펙 Out 으로 명시)

### 결정 9: 라벨링 우선순위

- "어떤 클립을 먼저 라벨할지" 정렬 룰. 무작위? 최신순? VLM 신뢰도 낮은 순?
- **MVP**: 최신순 + 미라벨 only 필터. VLM 신뢰도 정렬은 VLM 추론 결과를 DB 에 저장한 다음 가능 → Round 4 에서.

### 결정 10: CRF 채택 (확정 — CRF 26)

`scripts/compare_crf.py` 로 실 클립 25개 (storage/clips/2026-05-02 도마뱀 캡처본) 인코딩, 23개 성공 (2개는 원본이 깨진 stub — moov 부재). preset=`veryfast`, `+faststart`, `-an` 동일 조건.

**요약 — 압축률 = encoded / original**

| CRF | mean | median | min | max | mean size (bytes) |
|-----|-----:|-------:|----:|----:|------------------:|
| 23 | 58.60% | 60.10% | 55.55% | 61.51% | 801,964 |
| 26 | 33.52% | 34.49% | 30.95% | 36.42% | 456,246 |
| 28 | 21.85% | 22.20% | 19.93% | 24.44% | 296,655 |

**판단**:
- CRF 23 — 원본 대비 ~58% (절반 정도만 절약). 시각 품질 거의 무손실이지만 R2 비용·라벨링 페이지 다운로드 시간 측면 효율 낮음.
- **CRF 26 (채택)** — 원본의 ~1/3 (mean 33.5%). 1.7MB 원본 → 530KB 인코딩본. 라벨링 웹 영상 로딩 빠름 + 도마뱀 행동 식별에 충분한 화질 (육안 검증: `storage/crf_compare/` 에 동일 클립 3종 인코딩 비교 가능).
- CRF 28 — 원본의 ~22% (4.5배 절약). 압축률 매력적이지만 미세 행동 (혀 날름 / 입 주변 잔존물) 식별이 흐려질 가능성. VLM 회귀 리스크 (§리스크 "인코딩 후 메타데이터 손실" 참고).

**원본 mp4 패턴**: OpenCV `cv2.VideoWriter` (`avc1`/`mp4v`) 출력은 H.264 인코더 옵션 노출 안 함 → 우리 ffmpeg veryfast/CRF 26 인코딩본보다 큼. 같은 화질에 1/3 사이즈는 OpenCV 출력의 비효율 + faststart 헤더 재배치 효과.

**왜 PSNR 안 쟀는지**: 도마뱀 행동 라벨링 적합도는 PSNR (수치 SNR) 보다 **육안 + VLM 회귀 평가** 가 더 직접적. 회귀 평가는 §리스크 "메타데이터 손실" 의 follow-up (159건 v3.5 baseline 대비 동일 라벨 비율) 로 분리.

**향후 변경 시**: `backend/encoding.py`의 `DEFAULT_CRF` 만 바꾸면 됨 + `tests/test_encoding.py`의 `test_default_crf_constant_is_26` 회귀 테스트 같이 갱신. 단, 변경 전에 v3.5 회귀 평가 필수 (라벨링 흔들리는지).

### 기존 구조와의 관계

- `capture.py` 의 `_record_clip(...)` 호출 지점이 통합 포인트. 호출 직전에 `(thumb_path, segment_path)` 로 인코딩+업로드 → 결과 dict 를 payload 에 merge.
- `clip_recorder.py` 는 payload dict 를 그대로 받으니 새 필드 4개 자동 통과. mirror 경로도 동일.
- `pending_inserts.py` 는 dict 직렬화 — 새 필드 자동 직렬화. 단 `r2_key=None` 인 경우 직렬화 후 재시도 시 R2 재업로드 안 함 (가정 명시).
- `routers/clips.py` 는 SELECT 컬럼 확장 + redirect 분기.

### 리스크 / 미해결 질문

- **R2 비용 폭발 시나리오**: 정확한 단위 — Storage $0.015/GB·month, Class A (write/list) **$4.50 per 1M requests**, Class B (read) **$0.36 per 1M requests**, egress 무료. 라벨링 트래픽 폭증 시? → MVP 는 라벨러 1~3명 가정, 카메라 2대 × 60s 세그먼트 × 24h = 약 2880 PUT/일 = 월 86k ≪ 1M 무료 (Cloudflare R2 무료 티어 1M Class A / 10M Class B). 라벨러가 클립당 평균 5 GET (썸네일 + 영상 시도) × 일 라벨 100건 = 500 GET/일 = 월 15k ≪ 무료. 모니터링 임계: Class A 월 800k, Class B 월 8M 도달 시 알림.
- **R2 → 백엔드 권한 검증 우회**: signed URL 받으면 만료까지 누구나 접근. 라벨러가 URL 공유하면 데이터 유출. → TTL 짧게 + audit 로그(어떤 라벨러가 어떤 클립의 URL 발급했는지) 검토. MVP 는 신뢰 라벨러 가정.
- **인코딩 후 메타데이터 손실**: FFmpeg 가 H.264 재인코딩 시 timecode/keyframe 위치가 변할 수 있음. VLM 추론에 영향? → CRF 비교 단계에서 v3.5 대비 회귀 평가 1회 (159건 중 R2 인코딩본으로 다시 추론 → 85.5% 유지하는지) 검증 필수.
- **Supabase Storage 안 쓰는 이유**: Supabase Storage 는 같은 BaaS 통합 + RLS 자동. 그러나 (a) 비용이 R2 대비 높고 (b) 영상 트래픽이 Supabase Pro 플랜 무료 티어를 빠르게 소진. R2 무료 한도 (10GB 저장, 1M Class A, 10M Class B) 가 PoC 단계에 충분.
- **Round 4 평가셋 자동화 분리**: 이 스펙은 라벨 인프라까지. "라벨된 클립 → jsonl export → 평가" 는 다음 스펙. 분리 이유: GT 합의 알고리즘이 결정되기 전까진 어떤 라벨을 골라 export 할지 정의 불가.

---

## 5. 학습 노트

작업 중 새로 접한 개념 / API 정리. 현재는 placeholder.

- **Cloudflare R2 (S3-compatible)**: AWS S3 API 호환 + 무료 egress. boto3 그대로 사용 가능, endpoint 만 R2 로. 비교: Supabase Storage 는 Postgres + GoTrue 통합이지만 트래픽 비용 큼.
- **FFmpeg CRF**: Constant Rate Factor. H.264 기준 0~51 (낮을수록 고화질·큰 용량). 23 = 시각적 무손실, 26 = 평균, 28 = 압축 우선. PoC 라벨링은 26 무난.
- **`+faststart` 플래그**: mp4 의 moov atom 을 파일 앞으로 이동. 브라우저가 메타데이터를 먼저 받아 즉시 재생 시작. 없으면 전체 다운로드 후 재생.
- **Signed URL pre-signed**: S3/R2 의 객체 접근을 시간 제한된 URL 로. 백엔드가 발급 → 클라이언트는 R2 와 직접 통신. 백엔드 대역폭 절약.
- **Postgres timestamptz vs timestamp**: 메모리 `feedback_postgres_timestamptz.md` — `behavior_labels.labeled_at` 은 timestamptz 필수.
- **Supabase Auth client/server 분리**: `@supabase/supabase-js` 의 `createClient` 는 anon key (브라우저 OK, RLS 책임) vs service_role key (서버 전용, RLS 우회). Next.js App Router 에서는 `'use client'` 컴포넌트가 anon 클라이언트 import, server 컴포넌트가 service_role 클라이언트 import. `import 'server-only'` 로 service_role 의 클라이언트 번들 유출을 빌드 타임에 차단.
- **Next.js App Router 인증 게이트**: 클라이언트 컴포넌트 (`'use client'`) `layout.tsx` 에서 `useEffect` + `getSession()` → 미로그인이면 `router.replace('/login')`. SSR 인증 (cookie 기반) 은 `@supabase/ssr` 패키지 필요하지만 MVP 는 client-side gate 만으로 충분.
- **CORS preflight + Authorization**: 브라우저가 `Authorization` 헤더 동반 cross-origin 요청 시 OPTIONS preflight. FastAPI `CORSMiddleware` 의 `allow_headers=["Authorization"]` + `allow_credentials=True` 둘 다 필요. `allow_origins` 는 와일드카드 ("*") 와 `allow_credentials=True` 동시 사용 금지 — 명시 origin 만 허용.
- **`<video>` cross-origin Authorization 한계**: HTML5 video element 는 fetch 와 달리 헤더 커스터마이즈 불가. Token 을 URL 쿼리에 박는 건 referrer leak / browser history / server log 경유로 누출 위험. 표준 해결: 백엔드가 signed URL JSON 발급 → 프론트가 그걸 src 에 박기 (signed URL 자체가 시간제한 토큰).

---

## 6. 참고

- 사용자 원본 TODO (이 스펙의 근거): conversation 2026-05-02 (R2 + 경량 인코딩 + GT 라벨링 TODO 10섹션)
- 외부 자료:
  - Cloudflare R2 docs: https://developers.cloudflare.com/r2/
  - boto3 + R2: https://developers.cloudflare.com/r2/api/s3/tokens/
  - FFmpeg H.264 옵션: https://trac.ffmpeg.org/wiki/Encode/H.264
- 연관 메모리:
  - `project_vlm_v35_baseline_lock.md` — 왜 라벨링 인프라가 필요한지의 근거
  - `feedback_vlm_visual_information_limit.md` — prompt/모델 한계 → 데이터·UX 정공법 결론
  - `feedback_postgres_timestamptz.md` — 새 테이블 datetime 컬럼 규칙
- VLM PoC SOT: `../../tera-ai-product-master/docs/specs/petcam-poc-vlm.md` (라벨 클래스 정의)

---

## 7. 작업 순서 (사용자 추천 반영)

1. ✅ 본 스펙 작성 + 사용자 확인 ← **현재 단계**
2. R2 버킷 + 환경변수 + `r2_uploader.py` 단위 테스트까지
3. FFmpeg 인코딩 유틸 + CRF 비교 데이터
4. DB 마이그레이션 (camera_clips 컬럼 + behavior_labels)
5. 캡처 → 인코딩 → 업로드 파이프라인 통합
6. 영상 접근 API r2 redirect
7. 라벨 API
8. 라벨링 웹
9. 회귀 검증 + 문서 + spec 클로징
