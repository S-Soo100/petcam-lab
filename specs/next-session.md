# 다음 세션 시작 지점

> 매 세션 마지막에 갱신. 다음 세션 초입에 먼저 읽는다.
> **최종 갱신:** 2026-05-02 late evening (Opus 4.7, motion 382/382 R2 ✅ + 88 PoC 업로드 backfill ✅ + owner-override 라벨 권한 추가 — 사용자 브라우저 E2E + Vercel 배포 대기)

## ✅ 직전 세션 산출 — motion 풀 backfill 완료 + owner-override 권한

백엔드 EncodeUploadWorker + R2 업로드 + DB sync 일관 동작 확인. 두 단계 backfill 완료:
- **1차** (camera_id NOT NULL): motion 232/232, 평균 압축 44.5%, 0 fail
- **2차** (NULL 88 PoC 업로드, `clips/uploaded/...` literal): 88/88, 157s, 0 fail (사용자 결정 (b))

**최종 R2 상태**: motion total 382, in_r2 382, pending 0. 88건은 `clips/uploaded/{date}/{stem}_{id}.mp4`.

추가로 **owner-override 라벨 권한** 구현 — `POST /clips/{id}/labels` body 에 `labeled_by` 필드 (선택). owner 가 다른 라벨러 라벨을 강제 수정/생성 가능 (관리자/테스터 검수용). labeler 멤버는 본인 라벨만. 19 테스트 통과.

다음은 사용자 브라우저 E2E (로그인 → 큐 → 클립 → R2 영상 재생) + (통과 시) Vercel 배포.

| 영역 | 상태 |
|---|---|
| §3-1 R2 인프라 (`backend/r2_uploader.py`, env, RLS) | ✅ 코드 완료 |
| §3-2 인코딩 파이프라인 (`backend/encoding.py`, `encode_upload_worker.py`) | ✅ 코드 완료 |
| §3-3 업로드 워커 + DB sync (`backend/r2_uploader.py` insert) | ✅ 코드 완료 |
| §3-4 실기 검증 (motion 382/382 backfill — 232 cam + 88 PoC + 62 신규) | ✅ 2026-05-02 |
| §3-5 `/clips` API r2 redirect (302) + 라벨링 웹용 `/file/url` JSON | ✅ 코드 완료 |
| §3-6 Label API (`backend/routers/labels.py`, `behavior_labels` 테이블) | ✅ 코드 완료 |
| §3-7 라벨링 웹 (`web/src/app/labeling/`) | ✅ 코드 완료 |
| §3-7 Vercel 배포 + Cloudflare DNS (`label.tera-ai.uk`) | 🟡 사용자 작업 |
| §3-7 라벨러 부트스트랩 SQL (`auth.users + labelers INSERT`) | 🟡 사용자 작업 |
| §3-7 라벨러 모바일/PC 실기 검증 | 🟡 사용자 작업 |

상세: [feature-r2-storage-encoding-labeling.md](feature-r2-storage-encoding-labeling.md)

## 🔒 락인된 결정 — 새 세션에서 재논의 금지

### VLM (Round 3 종료, 2026-04-30 락인)
- **v3.5 production floor = 85.5%** (159건 feeding-merged) / 85.7% (154건 dish-postfilter ablation 기준)
- 사용자 명시: "이거보다 더 나빠져서는 안 됨." → 어떤 변경이든 floor 미달이면 채택 X
- v3.5 prompt 백업: `web/prompts/backups/{system_base,crested_gecko}.v3.5.md` — 회귀 시 즉시 롤백
- **prompt 변경 시도 자체가 ROI 0** (6회 검증 실패: v3.6/v3.7-B/v4 + Track B/C/D/E + dish-postfilter)
- 잔존 오답은 prompt 한계가 아닌 **시각 한계** → UX/메타데이터/HITL 정공법
- 회귀 가드 의무: 159건 동일 평가셋으로 새 변경 측정 → 85.5% 미달이면 채택 X

### UX 통합 (2026-05-02 완료)
- `feature-vlm-feeding-merge-ux` ✅ 완료 — `types.ts toFeedingMerged()` + `UI_BEHAVIOR_CLASSES` (8 클래스 노출, raw 9 보존)
- F3 결과/평가 매핑 동치 9/9 통과, tsc 통과
- 9 raw → 8 UI: drinking + eating_paste → feeding 묶음

### HITL ping (2026-05-02 신규 spec)
- `feature-vlm-hitl-ping` 🚧 — defecating/shedding/eating_prey 모호 케이스 사용자 검수 (일일 5건 + opt-in)
- confidence<0.7 또는 confusion-prone 클래스 트리거. 코드 미착수.

## 🧭 다음 세션 즉시 착수 — 라벨링 웹 로컬 E2E → NULL 88 결정 → Vercel 배포

**A. R2 가동 검증 ✅ 2026-05-02** (motion 232/232 backfill로 갈음 — spec §3-4 [x]).

### B1. 라벨링 웹 로컬 E2E (지금 dev server :3001 가동 중)

- 사용자 브라우저 검증:
  1. `http://localhost:3001/labeling` → `/labeling/login` 자동 redirect
  2. Supabase 계정 로그인 (owner: `bss.rol20@...` 등)
  3. `/labeling` 큐에 본인 클립 표시 (owner는 본인 user_id 클립만; 라벨러면 전체)
  4. 클립 클릭 → `/labeling/{clipId}` → 영상 재생 (R2 signed URL) + 썸네일 표시
  5. 라벨 폼 제출 → DB `behavior_labels` row 생성 확인
- 백엔드: PID 68928 살아있음 (port 8000, EncodeUploadWorker active). `.env.local` `NEXT_PUBLIC_SUPABASE_ANON_KEY` 채워짐.
- **dev server 정리:** 검증 후 background task `b8xejq7hy` 또는 `lsof -ti:3001 | xargs kill`.

### B2. ✅ NULL camera_id 88건 결정 (b 채택) — 2026-05-02

PoC 평가셋(crested_gecko Round 1~3)을 `clips/uploaded/{date}/{stem}_{id}.mp4` literal 로 backfill.
- 사용자 명시: "싹다 업로드하고 관리자&테스터가 라벨을 확인/수정 할 수 있어야 해 b로 가."
- 88/88 succ, 157s. R2 키에 `uploaded` 박혀 카메라 캡처와 attribution 분리 가능.
- 후속: **owner-override 라벨 권한** 추가 (labels.py LabelCreate.labeled_by). owner 만 다른 라벨러 라벨 강제 수정 가능.

### B3. 라벨링 웹 Vercel 배포 (B1 통과 후)

- Vercel (`web/` 디렉토리) — env 3개 (`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` = `eyJ...rgtvY`, `NEXT_PUBLIC_BACKEND_URL=https://api.tera-ai.uk`)
- Cloudflare DNS — `label.tera-ai.uk` CNAME → `cname.vercel-dns.com`
- 백엔드 `.env` 에 `LABELING_WEB_ORIGINS=https://label.tera-ai.uk` 추가 + 서버 재기동
- 라벨러 1명 부트스트랩 SQL ([docs/DEPLOYMENT.md "라벨링 웹 (Vercel)"](../docs/DEPLOYMENT.md))
- 라벨러 모바일/PC 양쪽에서 클립 10건 라벨 → `behavior_labels` row 10개 확인

### 후순위 (A/B 끝난 뒤 사용자 결정)

- **HITL ping 구현** — spec [`feature-vlm-hitl-ping.md`](feature-vlm-hitl-ping.md). 라벨링 웹 인프라 재사용 (같은 `behavior_labels` 테이블) 검토
- **메타데이터 보강** — dish detection / before-after / 시간대 / 카메라 ROI prior. prompt에 박지 말 것 (룰 5 회피) — 별도 분류기/후처리 레이어로
- **Stage E 온디바이스 필터링** — 별도 트랙. SOT (`../tera-ai-product-master/docs/specs/petcam-b2c.md`) 먼저 읽고 spec 킥오프

## 🗂️ 현재 시스템 상태 스냅샷 (2026-05-02)

- **VLM:** Gemini 2.5 Flash + v3.5 prompt + feeding-merged = 85.5% (136/159) production 락인
- **R2:** ✅ 인프라 가동 + motion 382/382 backfill (232 cam + 88 PoC `clips/uploaded/` + 62 신규). idle 246건 자동 업로드 완료
- **라벨 권한:** ✅ owner-override 추가 — POST `labeled_by` 명시 시 owner 가 타 라벨러 강제 수정/생성. 19 테스트
- **라벨링 웹:** ✅ 코드 완료 + dev :3001 가동 (`b8xejq7hy`). Vercel 배포 + DNS + 라벨러 부트스트랩 사용자 작업
- **Backend:** PID 68928, port 8000 (capture cam1+cam2 active, encode_upload_queue=0). `api.tera-ai.uk` Cloudflare Tunnel 공개. 22 routes
- **Auth:** `AUTH_MODE=prod`, Supabase JWT (ES256). CORS 라벨링 웹 origins 분리
- **카메라:** cam1 (1c1aea9f) / cam2 (3a6cffbf) — 오너 bss.rol20. mirror cam1-mirror / cam2-mirror — QA dlqudan12
- **Tests:** 204 passing (백엔드 전체)
- **Stage:** A~D5 ✅ / E 🆕 (스코프 미확정) / VLM PoC ✅ Round 3 종료 / R2 ✅ 가동 + 라벨링 코드 완료

## 📂 맥락 복원 — 읽을 파일 (우선순위)

새 세션이 맥락 없이 들어왔을 때 이 순서로:

1. **이 파일** — 오늘의 시작 지점 + 락인 결정
2. [feature-r2-storage-encoding-labeling.md](feature-r2-storage-encoding-labeling.md) — R2/라벨링 전체 결정 + 사용자 가동 체크리스트
3. [feature-poc-vlm-web.md](feature-poc-vlm-web.md) — VLM PoC 전체 결정 이력 (Round 1~3, §3-13까지)
4. [feature-vlm-feeding-merge-ux.md](feature-vlm-feeding-merge-ux.md) — UX 통합 완료 (raw 보존 + UI 매핑)
5. [feature-vlm-hitl-ping.md](feature-vlm-hitl-ping.md) — HITL spec (코드 미착수)
6. `~/.claude/projects/-Users-baek-petcam-lab/memory/MEMORY.md` — 자동 메모리 인덱스
7. [../README.md](../README.md) — 1분 요약 + 퀵스타트
8. [../docs/ENV.md](../docs/ENV.md) — R2 + CORS 환경변수
9. [../docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md) — R2 + Vercel + 부트스트랩 SQL
10. [README.md](README.md) — spec 운영 규칙 + 전체 스펙 목록

## 💬 사용자가 "뭐부터 해야해?" 물으면

1. **첫 확인 — 락인 존중**: v3.5 baseline은 건드리지 않는다고 인지. prompt 변경/clean slate 제안 금지.
2. **즉시 답**: "B1. 라벨링 웹 로컬 E2E (`http://localhost:3001/labeling`). dev server 살아있으면 바로 검증, 죽었으면 `cd web && PORT=3001 npm run dev`. 백엔드도 8000에 살아있어야 함 (`/health` 확인)." 다른 옵션 제시 X.
3. **B1 통과 후**: B2 NULL 88 결정 → B3 Vercel 배포 (env 3개 + DNS + 부트스트랩 SQL). 후순위는 그 뒤에 다시 사용자 결정.
4. **회귀 가드 자동 적용**: 어떤 변경이든 85.5% floor 검증 의무
