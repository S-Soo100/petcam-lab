# 카메라 펌웨어 ↔ 클라우드 clip 등록 계약 — terra 측 회신

> **회신:** 2026-06-18 / terra-server (ESP32-P4 펫캠 펌웨어 + 백엔드)
> **원문:** petcam-lab 「카메라 펌웨어 ↔ 클라우드 clip 등록 계약」 (2026-06-17)
> **검증:** 코드 기준 (펌웨어 `firebeetle2-p4-yr030`, 백엔드 `terra-server`)

---

## 0. 먼저 — 아키텍처가 계약 가정과 다릅니다 (중요)

계약서는 **"펌웨어가 Supabase `camera_clips`에 직접 row 등록(DB-first) → 업로드 → r2_key 채움"** 을
전제합니다. 그런데 terra 실제 구현은 **서버 경유 방식**이고, 등록 순서도 반대입니다:

```
펌웨어 → POST {terra}/cameras/{uuid}/clips/upload-url   (camera_token)
       ← 서버가 clip_id + presigned R2 PUT URL 발급
펌웨어 → R2 에 mp4/jpg 직접 PUT (presigned URL)
펌웨어 → POST {terra}/cameras/{uuid}/clips              (camera_token)
       ← 서버가 motion_clips 에 INSERT (이때 r2_key 이미 확정)
```

- **펌웨어는 Supabase도 R2도 직접 안 건드립니다.** 자격증명을 아예 안 들고 있어요
  (계약서의 "service_role 임베드 금지" 요구보다 더 강한 수준).
- DB 등록이 **업로드 성공 후**라서, "row는 있는데 영상 없는" 유령 상태가 **원천적으로 안 생깁니다**
  (→ 질문 3 참고).
- 테이블도 `camera_clips`가 아니라 **`motion_clips`** (terra는 petcam-lab과 **별개 Supabase 프로젝트**).
  이 차이가 리포터 연동에 영향이 있어서 §4에 따로 정리했습니다.

핵심 요청인 **`started_at`(녹화 시작 UTC)은 이미 정확히 충족**합니다 (§1-2).

---

## 1. 프로비저닝 (`camera_id` / `user_id`) — ✅ 해결됨

BLE provisioning → `POST {terra}/cameras/pair` (사용자 JWT) 흐름:

- 서버가 `camera_id`(텍스트, `p4cam-xxxx`) + `camera_token` 생성, bcrypt 해시로 `cameras` row INSERT,
  이때 **`owner_id = JWT의 user_id`로 바인딩** (`backend/routers/cameras.py:192`)
- 응답으로 `camera_id` + `id`(= `cameras.id` UUID) + `token` + MQTT 정보 반환 → 펌웨어가 **NVS에 저장**,
  재부팅 시 재페어링 없이 로드 (`main.c:643-660`)
- **클립 업로드 시 펌웨어는 `user_id`를 보내지 않습니다.** 서버가 `camera_token` → `cameras` row →
  `owner_id`로 역추적해서 직접 박습니다. 즉 펌웨어는 소유자 개념을 아예 안 다룹니다
  → 기기 탈취돼도 owner 위조 불가.

→ **계약서 표의 `user_id` 필드는 terra에선 펌웨어 책임이 아니라 서버가 자동 처리.**

---

## 2. 시계 동기화 (NTP) — ✅ 보장됨

- 펌웨어가 부팅 시 **SNTP 동기화** (`pool.ntp.org`, `time.google.com`) 후 **블로킹 대기**
  (`main.c:568-577`, `main.c:749-758`)
- `started_at`은 `gmtime_r` + `strftime("%Y-%m-%dT%H:%M:%SZ")` → **UTC ISO8601, 녹화 시작 시각**
  (`main.c:1234-1235`). 업로드 시각이 아니라 **촬영 시작 순간** 맞습니다.
- **오차**: SNTP 동기화 후엔 수십 ms 수준. 단, **부팅 시 NTP 서버에 못 닿으면** 동기화 실패(타임아웃)
  로그가 찍히고 RTC가 틀어진 채로 갈 수 있음 — 이 케이스만 주의.
  (네트워크 복구 후 재동기화는 POLL 모드라 백그라운드로 보정됨)

→ 계약서가 걱정한 "백필 81건처럼 등록시각이 섞이는" 문제는 terra에선 구조적으로 안 생깁니다
(등록시각 `created_at`은 서버 `now()`, `started_at`은 펌웨어 RTC로 명확히 분리).

---

## 3. 업로드 실패 시 유령 row — ✅ terra엔 해당 없음

terra는 **업로드 성공 후에만 DB 등록**(DB-last)이라, 계약서가 걱정한 "r2_key 없는 유령 row"가
**생길 수 없습니다.** `motion_clips.r2_key`는 `NOT NULL`이고, row가 존재하면 영상은 이미 R2에 있습니다.

- 반대 케이스(= **R2엔 올라갔는데 메타 POST 실패**)만 가능 → "DB row 없는 R2 orphan".
  이건 `clip_id` prefix 스캔으로 청소 (key와 row id가 동일 UUID라 매칭 쉬움, `clips.py:17-20`).
- 펌웨어는 각 단계 실패 시 에러 로그 남기고 중단 (`uploader.c:302-370`) — 부분 등록 안 함.

→ **펌웨어가 row를 지우거나 서버가 유령 row를 청소하는 정책은 terra에선 불필요.**
(DB-first인 petcam-lab 방식에서만 필요한 정책)

---

## 4. 리포터 연동을 위한 스키마 차이 (확인 필요)

terra `motion_clips` ↔ 계약서 `camera_clips` 매핑:

| 계약서(camera_clips) | terra(motion_clips) | 비고 |
|---|---|---|
| `started_at` | `started_at` | ✅ 동일 의미 (녹화 시작 UTC) |
| `duration_sec` | `duration_sec` | ✅ |
| `has_motion` (bool) | `motion_score` (float 0~1) | terra는 강도값. `>0`이면 모션 |
| `user_id` | `owner_id` | 서버가 박음 |
| `pet_id` | `enclosure_id` | 사육장 매핑 |
| `source` | (없음) | 전부 카메라 직접 push |
| `r2_key` | `r2_key` | 포맷 다름 ↓ |
| — | `thumbnail_key` | terra는 썸네일도 올림 |

- **r2_key 포맷**: terra는 `terra-clips/clips/{camera_id}/{YYYYMMDD-HHMMSS}_{clip_id}.mp4`
  (공유 버킷 `petcam-clips` 안 `terra-clips/` prefix). 계약서의
  `clips/{camera_id}/{YYYY-MM-DD}/{HHMMSS}_motion_{uuid}.mp4`와 다릅니다.
- **가장 큰 이슈**: terra와 petcam-lab은 **다른 Supabase 프로젝트**입니다. 야간 리포터가
  `camera_clips`를 조회하면 **terra 클립은 안 보입니다.** 셋 중 하나를 정해야 합니다:
  1. 리포터가 terra의 `motion_clips`를 직접 조회 (terra DB 접근 권한 부여) — **권장**
  2. terra → petcam-lab `camera_clips`로 동기화 (서버 측 작업)
  3. 펌웨어 dual-write — **비권장** (자격증명 2벌, 복잡도↑)

리포터의 `started_at BETWEEN + r2_key IS NOT NULL` 쿼리 자체는 terra `motion_clips`에
**그대로 적용 가능**합니다 (r2_key가 항상 채워져 있으니 오히려 더 안전).

---

## 요약

| 질문 | terra 답변 |
|---|---|
| 1. 프로비저닝 | `/cameras/pair`에서 서버가 발급, NVS 저장. owner는 서버가 토큰으로 자동 바인딩 (펌웨어 무관) |
| 2. 시계 | SNTP 블로킹 동기화 + UTC ISO8601. NTP 불통 부팅만 주의 |
| 3. 유령 row | DB-last라 발생 불가. 청소 정책 불필요 |
| (추가) 연동 | terra=`motion_clips`/별도 Supabase. 리포터가 어느 DB를 볼지 결정 필요 |

> **미결 (논의 필요):** §4의 리포터 연동 방식 (1/2/3 중 택1) — terra ↔ petcam-lab 팀 합의 사항.
