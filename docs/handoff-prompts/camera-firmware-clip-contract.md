# 카메라 펌웨어 ↔ 클라우드 clip 등록 계약

> **작성:** 2026-06-17 / petcam-lab
> **대상:** ESP32-P4 펫캠 펌웨어 담당자
> **목적:** 카메라가 모션 clip을 클라우드에 등록·업로드할 때의 인터페이스 계약. 특히 **녹화 시각(`started_at`)** 을 정확히 박는 것이 핵심.

---

## 배경

지금까지는 맥북의 Python capture worker가 RTSP로 영상을 받아서 → R2 업로드 + DB(`camera_clips`) 등록을 **대행**했습니다. 앞으로 ESP32-P4 카메라가 모션 clip을 **직접 클라우드로 push**하게 되면서, 그 등록 계약을 카메라 펌웨어 쪽으로 옮깁니다.

야간 자동 리포트 시스템이 *"어젯밤 22시~06시 사이에 찍힌 clip"* 을 DB 시각 인덱스로 조회하는데, **그 인덱스의 정확성이 카메라가 박는 녹화 시각에 전적으로 달려 있습니다.**

---

## 등록 흐름 (확정)

```
펫캠 펌웨어
  → Supabase camera_clips 에 row 등록 (직접 접근)
  → 업로드 승인
  → R2 에 영상 업로드
  → (업로드 완료 후) 해당 row 의 r2_key 채움
```

- **DB 등록이 R2 업로드보다 먼저**입니다.
- 따라서 "row 는 있는데 영상은 아직 없는" 중간 상태가 존재합니다. 영상 업로드가 끝나면 **그 row 의 `r2_key` 를 채워주세요.** (리포터는 `r2_key` 가 채워진 row 만 "영상 준비됨"으로 보고 처리합니다.)

---

## 🔴 핵심 요청 — `started_at`

clip row 를 등록할 때 `started_at` 필드에 **녹화가 시작된 실제 시각(UTC)** 을 넣어주세요.

- ✅ 카메라 RTC 기준, **촬영이 시작된 순간**의 시각 (UTC, ISO8601)
- ❌ 업로드한 시각 / 서버에 전송한 시각이 **아닙니다**
- 등록시각(`created_at`)은 서버가 자동(`now()`)으로 찍으니 신경 쓰지 않으셔도 됩니다

**⚠️ 전제: 카메라 시계(RTC)가 NTP 로 동기화돼 있어야 합니다.** 시계가 틀어지면 "어젯밤 clip 조회"가 통째로 어긋납니다 (아래 '왜' 참고).

---

## `camera_clips` 등록 필드

| 필드 | 타입 | 필수 | 펌웨어가 넣을 값 |
|---|---|:---:|---|
| `started_at` | timestamptz | ✅ | **녹화 시작 UTC 시각** (위 핵심 요청) |
| `duration_sec` | real | ✅ | clip 길이(초) |
| `has_motion` | boolean | ✅ | `true` (모션 트리거 clip) |
| `camera_id` | uuid | ✅(권장) | 이 기기의 카메라 UUID (`cameras.id`) |
| `user_id` | uuid | ✅ | 카메라 소유자 user UUID |
| `r2_key` | text | 업로드 후 | `clips/{camera_id}/{YYYY-MM-DD}/{HHMMSS}_motion_{clip_uuid}.mp4` |
| `source` | text | (기본 `'camera'`) | `'camera'` |
| `width` `height` `fps` `codec` `file_size` | — | 선택 | 가능하면 같이 (ffprobe 류) |
| `pet_id` | uuid | 선택 | enclosure 매핑이 있으면 |
| `created_at` | timestamptz | ❌ | **건드리지 마세요** — 서버가 `now()` 자동 |

---

## `r2_key` 규칙 (현재와 동일하게 유지)

```
clips/{camera_id}/{YYYY-MM-DD}/{HHMMSS}_motion_{clip_uuid}.mp4
예: clips/3a6cffbf-…/2026-04-29/052234_motion_aaafbe3f-….mp4
```

key 안에도 녹화 date/시각을 박아두면, `started_at` 이 의심스러울 때 교차검증용 안전망이 됩니다.

---

## 왜 이렇게까지 (이유)

과거 백필 데이터 81건이 `started_at` 에 **등록시각**을 잘못 넣어서, 실제 녹화는 4월인데 DB엔 6월로 찍혀 있습니다. 이런 게 섞이면 시각 기반 조회가 망가집니다. 야간 리포터는 `WHERE started_at BETWEEN …` 한 번으로 그 밤의 clip 만 효율적으로 뽑는데, 이 값이 부정확하면 **리포트에 엉뚱한 날 영상이 들어오거나 그 밤 영상이 누락**됩니다.

---

## 인증 / 보안

- 펌웨어에 **Supabase `service_role` 키를 임베드하지 마세요** (전체 DB 무제한 권한 — 기기 탈취 시 전체 노출).
- 카메라별 토큰 + RLS(Row Level Security) 기반으로, 자기 카메라의 row 만 쓸 수 있게 제한하는 방향을 권장합니다. (현재 `cameras` 테이블에 `token_hash` 컬럼이 이미 있어 기기 인증 토큰 체계가 깔려 있습니다.)

---

## 협의가 필요한 것 (회신 부탁)

1. **`camera_id` / `user_id` 프로비저닝**: 기기가 자기 `camera_id`(서버 발급 UUID)와 소유자 `user_id` 를 어떻게 받는지 (최초 등록 플로우).
2. **시계 동기화**: 펌웨어에서 NTP 동기화가 보장되는지 / 안 되면 어느 정도 오차가 예상되는지.
3. **업로드 실패 시 row 처리**: R2 업로드가 실패하면 먼저 만든 row 를 어떻게 하나요? (방치되면 "영상 없는 유령 row" 가 남습니다. 일정 시간 `r2_key` 가 안 채워지면 펌웨어가 지우거나, 서버가 청소하는 정책이 필요.)

---

## (부록) 우리측 후속 작업 — 펌웨어와 무관

- `file_path` 컬럼이 현재 `NOT NULL`(맥북 로컬 경로용 레거시)인데, HW캠은 로컬 경로가 없으므로 제약 완화 또는 `r2_key` 대체 — **서버측에서 처리**.
- 확정된 계약을 SOT(`petcam-ai-pipeline.md`)와 nightly-reporter `architecture.md §10` 에 반영.
- nightly indexer = `camera_clips` 시간 윈도우 쿼리(`started_at BETWEEN` + `r2_key IS NOT NULL`) 로 구현.

---

## 📥 terra 회신 + 계약 v1 확정 (2026-06-18)

> 회신 원문: [`camera-firmware-clip-reply.md`](camera-firmware-clip-reply.md) (terra-server — ESP32-P4 펌웨어 `firebeetle2-p4-yr030` + 백엔드).

**아키텍처가 이 계약 가정과 다름 — 단 더 안전한 방향:**
- 펌웨어는 Supabase/R2 **직접 안 건드림** — 서버 경유(presigned URL). 자격증명 0 (계약의 service_role 금지보다 강함).
- **DB-last** (업로드 성공 후 등록) — "영상 없는 유령 row" 원천 불가. 우리 DB-first 전제 + r2_key 유령 필터는 terra엔 해당 없음.
- 저장소가 `camera_clips`가 아니라 **별도 Supabase 프로젝트의 `motion_clips`**.

**협의 3문항 — 전부 충족:**
| 항목 | terra |
|---|---|
| started_at = 녹화 시작 UTC | ✅ **이미 완벽** (SNTP 블로킹 동기화 + `gmtime_r`→UTC ISO8601, 촬영 시작순간). 핵심 요청 그대로 충족 |
| 프로비저닝 | ✅ `/cameras/pair` 서버 발급, `owner_id`=JWT user_id 자동 바인딩 (펌웨어는 소유자 개념 안 다룸) |
| 시계 NTP | ✅ SNTP 보장. ⚠️ 부팅 시 NTP 불통 케이스만 주의 (POLL 모드 백그라운드 보정) |
| 유령 row | ✅ DB-last라 불가, 청소 불필요. 반대로 "R2 orphan(메타 POST 실패)"만 가능 → `clip_id` prefix 스캔으로 청소 |

**§4 리포터 연동 = 옵션 1 확정 (2026-06-18 사용자 결정):**
**nightly 리포터가 terra `motion_clips`를 직접 조회**(terra Supabase 읽기 권한). 동기화 레이어 0, B쿼리(`started_at BETWEEN + r2_key IS NOT NULL`) 그대로 적용 — r2_key가 항상 채워져(DB-last) 오히려 더 안전.

**스키마 매핑 (리포터 기대 ← terra `motion_clips`):**
| 리포터 기대(camera_clips) | terra motion_clips |
|---|---|
| started_at | `started_at` (동일 의미) |
| duration_sec | `duration_sec` |
| has_motion (bool) | **`motion_score`** (float 0~1, `>0`=모션) |
| user_id | `owner_id` |
| pet_id | `enclosure_id` |
| r2_key | `r2_key` (포맷: `terra-clips/clips/{camera_id}/{YYYYMMDD-HHMMSS}_{clip_id}.mp4`) |
| — | `thumbnail_key` (terra 추가 — 썸네일도 업로드) |

**후속 변경 (이 계약으로 확정):**
- ~~`file_path` NOT NULL 완화 마이그레이션~~ → **불필요** (HW캠이 petcam-lab `camera_clips`에 안 씀).
- nightly indexer = **terra `motion_clips` 대상** (camera_clips 아님). ⚠️ **terra DB 읽기 권한 부여가 indexer 구현의 전제** (terra ↔ petcam-lab 조율 필요).
- petcam-lab `camera_clips` 위상 = **레거시 capture worker 데이터** (운영 신규 클립 SOT는 terra `motion_clips`).
- SOT 반영 대상: `petcam-ai-pipeline §11`(terra-server 편입 + 리포터 연동 옵션1) + nightly `architecture §10 Step 2`(motion_clips 조회 + 스키마 매핑).
