# Stage D — Supabase 연동 완성 로드맵

> Stage C 가 완성한 "메타데이터 DB + 클립 조회 API" 위에 **앱 연동** 을 쌓는 단계. JWT 검증, 다중 카메라 등록·관리, 썸네일 파이프라인, 외부망 접근까지. 본 문서는 **로드맵** 이며, 각 서브 스테이지는 별도 스펙 파일에서 상세화.

**상태:** 🚧 진행 중
**작성:** 2026-04-22
**연관 SOT:** `../../tera-ai-product-master/docs/specs/petcam-backend-dev.md` — Stage D 상세

---

## 1. 이 로드맵이 존재하는 이유

Stage D 는 단일 스펙으로 묶기엔 너무 큼 (5 개 백엔드 서브 + 5 개 Flutter 서브). 로드맵에:
- **결정 히스토리** (왜 이 방식을 골랐는지 — 대안 비교 포함) 를 한 곳에 남기고
- **서브 스테이지 간 의존성과 권장 진행 순서** 를 명시해서
- **어느 세션에서도** (Claude 세션 바뀌거나 며칠 뒤 재진행 시) 현재 위치 파악 가능하게 한다.

서브 스테이지 각각은 `specs/stage-d{N}-*.md` 에 상세 (In/Out/완료 조건).

---

## 2. 확정 결정 사항 (2026-04-22 시점)

### 결정 1 — 외부망 접근: **Cloudflare Tunnel**

| 구분 | 값 |
|------|-----|
| 방식 | Cloudflare Tunnel (무료) |
| 기본 URL | `*.trycloudflare.com` 자동 할당 (커스텀 도메인 없이 시작) |
| 서버 | 맥북 24 시간 가동, 외출 시 중단 공지 |
| 테스터 규모 | ≤ 5 명 (무료 플랜 충분) |

**대안 비교:**
- **A. Tailscale** — 공짜고 쉽지만 테스터도 Tailscale 설치 필요 → 지인 베타 단계엔 부적합
- **B. Cloudflare Tunnel** ← 선택. 앱만 깔면 끝, 공개 URL 자동 HTTPS
- **C. 클라우드 PaaS (Render/Fly)** — 월 $5~10 + **RTSP 소스가 집에 있어서 맥북 서버도 여전히 필요** = 이중 운영 낭비. 상용 단계에서 재검토
- **D. ngrok** — 무료는 URL 매번 바뀜, 고정 URL 은 $8/월

**향후 트리거:** 테스터 > 20 명, 또는 정식 출시 시 → 클라우드 배포 (C) 로 전환. 이때 카메라-서버 아키텍처도 "각 유저 집에 허브 장치" 로 재설계.

---

### 결정 2 — 썸네일: **캡처 시 jpg 1장 저장 (A 안)**

| 구분 | 값 |
|------|-----|
| 생성 시점 | 세그먼트 종료 시 캡처 워커가 cv2.imwrite |
| 대표 프레임 | motion 클립 = motion 시작 프레임 / idle 클립 = 세그먼트 중간 프레임 |
| 저장 위치 | mp4 파일 옆 `{동일한_이름}.jpg` |
| DB 컬럼 | `camera_clips.thumbnail_path` 추가 (Stage D4 마이그레이션) |
| 디스크 추정 | 클립당 ~30KB. 하루 1440 개 기준 ~43MB/일 (mp4 의 1%) |

**대안 비교:**
- **A. 캡처 시 jpg 저장** ← 선택. 캡처 워커가 어차피 프레임 가짐 → `imwrite` 한 줄 추가
- **B. 요청 시 즉석 생성 + 캐시** — 디스크 절약, 첫 로드 느림, 코드 복잡
- **C. 썸네일 없이 텍스트 피드** — UX 심각, 탈락
- **D. Supabase Storage 업로드** — CDN 장점 있지만 초기 비용/복잡도 오버

---

### 결정 3 — 카메라 등록 UX: **필드 분해 입력 + 테스트 연결**

| 구분 | 값 |
|------|-----|
| 입력 방식 | display_name / host / port(기본 554) / path(기본 stream1) / username / password / pet_id |
| 검증 | 실시간 필드 검증 (IP 포맷, 포트 범위) + "테스트 연결" 버튼으로 실 RTSP 핸드쉐이크 시도 |
| 테스트 연결 구현 | 서버가 3~5초 동안 cv2.VideoCapture 로 첫 프레임 받아보기. 성공/실패/원인 리포트 |

**대안 비교:**
- **1. RTSP URL 통째로 입력** — 오타 시 원인 불명
- **2. 필드 분해** ← 선택. 실시간 검증 + 오류 위치 명확
- **3. Tapo 자동 디스커버리** — 구현 리스크 큼, 플랫폼 권한 복잡. 지금 단계 오버

---

### 결정 4 — 비밀번호 저장: **Fernet 대칭 암호화**

| 구분 | 값 |
|------|-----|
| 암호화 라이브러리 | `cryptography.fernet` (AES-128-CBC + HMAC-SHA256) |
| 키 보관 | `.env` 의 `CAMERA_SECRET_KEY` (32바이트 base64, `Fernet.generate_key()` 결과) |
| 저장 범위 | **비번만 암호화** (host/port/username/path 는 평문 — 관리 UI 편의) |
| DB 컬럼 | `cameras.password_encrypted BYTEA` |
| 키 로테이션 | MVP 엔 없음. 상용 단계에서 재평가 |

**보안 함정 (잊지 말 것):**
1. `.env` 의 `CAMERA_SECRET_KEY` 절대 커밋 금지 (`.env.example` 은 placeholder)
2. API 응답에 비번 제외 (`SELECT *` 금지, 컬럼 명시, 필요 시 `has_password: true` 만)
3. 로그에 비번 찍지 말기 (RTSP URL 로깅 시 `rtsp://admin:***@host/path` 마스킹)
4. HTTPS 필수 (Cloudflare Tunnel 이 자동 제공)
5. 카메라 삭제 시 `camera_clips` CASCADE + 영상 파일 cleanup 별도 job

**대안 비교:**
- **Fernet** ← 선택. 표준, 단일 키, 간단 API
- **AES-GCM 직접 구현** — 실수 여지 큼
- **Supabase Vault** — 아직 Beta + 러닝 커브

---

### 결정 5 — 데이터 모델: **`cameras` 테이블 신설 + `camera_clips` 마이그레이션**

```sql
-- Stage D2 에서 적용할 DDL 초안
CREATE TABLE cameras (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id),
  pet_id UUID REFERENCES pets(id) ON DELETE SET NULL,
  display_name TEXT NOT NULL,
  host TEXT NOT NULL,
  port INT NOT NULL DEFAULT 554,
  path TEXT NOT NULL DEFAULT 'stream1',
  username TEXT NOT NULL,
  password_encrypted BYTEA NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT true,
  last_connected_at TIMESTAMP,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE cameras ENABLE ROW LEVEL SECURITY;
CREATE POLICY "User reads own cameras"    ON cameras FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "User updates own cameras"  ON cameras FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY "User deletes own cameras"  ON cameras FOR DELETE USING (auth.uid() = user_id);
-- INSERT 는 service_role 전담 (테스트 연결 검증 로직 거쳐야 함)

-- Stage D3 마이그레이션:
-- camera_clips.camera_id TEXT → camera_clips.camera_uuid UUID REFERENCES cameras(id) ON DELETE CASCADE
-- Stage D4 마이그레이션:
-- camera_clips.thumbnail_path TEXT
```

**CASCADE vs SET NULL:** CASCADE 선택. 카메라 삭제 시 영상 파일도 cleanup 필요 → Stage E 이후 백그라운드 job 과제.

---

### 결정 6 — UI 방향: **펫 중심**

```
[홈]
 ├─ 펫 A (도마뱀 뚜기) → 카메라 1 → 클립 피드
 └─ 펫 B (강아지 초코) → 카메라 2 → 클립 피드
```

- 카메라 2 대, 같은 와이파이 (본인 재택), **다른 펫 각각**
- 앱 UI 는 펫 카드 → 탭 → 해당 카메라 피드
- `cameras.pet_id` FK 로 연결

---

### 결정 7 — 카메라 물리 배치: **본인 재택 1개소**

- Tapo C200 2 대 모두 **같은 와이파이 (본인 재택)**
- 맥북 1 대가 둘 다 캡처 (다중 워커)
- **다른 집 설치는 하지 않음** — 이유:
  - 집 B 공유기 포트 포워딩 = 보안 위험 (Tapo 크래킹 사례)
  - 집 B 에 추가 허브 장치 = 관리 포인트 증가
  - 상용 단계에서 "각 유저 집에 허브" 아키텍처로 풀 과제

---

## 3. 서브 스테이지 분할 (petcam-lab)

| 서브 | 스펙 파일 | 핵심 산출물 | 상태 |
|-----|---------|-----------|------|
| **D1** | [stage-d1-auth-crypto.md](stage-d1-auth-crypto.md) | JWT 검증 `Depends` + JWKS 캐시 + Fernet 암호화 모듈 | ✅ 완료 (2026-04-22) |
| **D2** | `stage-d2-cameras-api.md` *(미작성)* | `cameras` 테이블 + RLS + CRUD API 5종 + 테스트 연결 | 📋 대기 |
| **D3** | `stage-d3-multi-capture.md` *(미작성)* | capture 워커 다중화 (DB 기반 동적 로드) + `camera_clips.camera_uuid` FK | 📋 대기 |
| **D4** | `stage-d4-thumbnail.md` *(미작성)* | 캡처 워커 jpg 저장 + `thumbnail_path` 마이그레이션 + `GET /clips/{id}/thumbnail` | 📋 대기 |
| **D5** | `stage-d5-deploy-tunnel.md` *(미작성)* | Cloudflare Tunnel 세팅 + 잠자기 방지 + E2E 검증 | 📋 대기 |

**📋 대기 상태 서브는 착수 직전에 스펙 파일 생성** (미리 쓰면 bikeshedding + 결정 변경 비용).

---

## 4. Flutter (tera-ai-flutter 별도 레포) 서브 작업

> 상세는 `tera-ai-flutter/docs/specs/` 에 별도 스펙으로. 여기선 의존성 매핑만.

| 서브 | 이름 | petcam-lab 의존 |
|-----|------|------|
| **F1** | Supabase Auth 로그인 화면 | (독립 — Supabase 직결) |
| **F2** | 홈 (펫 리스트 + 최근 motion 상태) | (독립 — Supabase `pets`/`camera_clips` 직결) |
| **F3** | 카메라 등록 화면 (필드 분해 + 테스트 버튼) | **D2 필요** |
| **F4** | 클립 피드 (썸네일 + 무한 스크롤) | **D4 필요** (썸네일), Stage C API 재활용 |
| **F5** | 영상 재생 (`video_player` + JWT) | **D1 필요** (JWT 검증), Stage C Range API 재활용 |

---

## 5. 의존성 그림

```
D1 (인증/암호화)
 ├─→ D2 (카메라 API) ────→ F3 (등록 화면)
 │                         │
 │                         ↓ (앱에서 카메라 등록 → DB 저장 1차 E2E)
 │
 └─→ F5 (재생; JWT 검증)
 
 D2 → D3 (다중 캡처) ──┐
                        ├─→ D5 (배포)
 D3 || D4 (썸네일) ─────┘
         │
         └─→ F4 (클립 피드 — 썸네일 포함)

F1 (로그인) → F2 (홈)   (Supabase 직결, petcam 독립)
```

---

## 6. 권장 진행 순서

**전략:** 엔드투엔드 골든 패스 먼저 → 기능 확장.

```
1.  D1  — JWT + Fernet 인프라 (작음, 빠르게)
2.  D2  — cameras CRUD API
3.  F1  — Flutter 로그인
4.  F3  — Flutter 카메라 등록 화면
      ↑ 1차 E2E: "앱에서 카메라 등록 → DB 저장" 성공 데모
5.  D3  — 다중 캡처 워커 (워커 1개 → N개 리팩터)
6.  D4  — 썸네일 파이프라인
7.  F2  — Flutter 홈 펫 리스트
8.  F4  — Flutter 클립 피드 (썸네일)
9.  F5  — Flutter 영상 재생
      ↑ 2차 E2E: "앱에서 클립 재생" 성공 데모 (로컬)
10. D5  — Cloudflare Tunnel 배포 + 테스터 공개
```

**4번 (F3) 완료 시점이 첫 큰 성취 체험 구간** — 엔드투엔드 1 차 검증.
**9번 (F5) 완료 시점이 전체 MVP 완성** — 10 번은 공개용.

---

## 7. 진행 중 기록 가이드 (나중 세션용)

- 서브 스테이지 착수 시 → `specs/stage-d{N}-*.md` 생성 → 스코프/완료 조건만 먼저 채우고 사용자 확인
- 각 서브 완료 시 → 이 로드맵의 상태 표 갱신 (🚧 → ✅) + 서브 스펙 상태도 `✅ 완료`
- 결정 번복이 생기면 → 본 문서 "2. 확정 결정 사항" 에 취소선·재결정 기록
- Standard 이상 작업 후 → `.claude/donts-audit.md` 한 줄 추가 잊지 말 것
- SOT 동기화 필요 시 → `../../tera-ai-product-master/docs/specs/petcam-backend-dev.md` 의 Stage D 섹션 업데이트

---

## 8. 오픈 이슈 (Stage D 진행 중 풀어야 할 것)

- [ ] `cloudflared` 바이너리 설치 + 맥북 잠자기 방지 (`caffeinate` vs 시스템 설정 vs 클램셸 모드) 선택
- [ ] 앱 `/health` ping 체크 간격 결정 (서버 꺼져 있을 때 "점검 중" 자동 표시용)
- [ ] 카메라 삭제 시 영상 파일 cleanup 전략 — 즉시 삭제 vs soft-delete vs 주기 GC
- [ ] Stage D3 의 캡처 워커 "동적 추가/제거" 시 기존 녹화 처리 (중단 vs 완료 후 반영)

---

## 9. 참고

- 로드맵 수립 배경: 2026-04-22 사용자와 학습 세션 겸 설계 토론 (Cloudflare/썸네일/카메라 등록/암호화/FK 결정)
- Stage C 학습 문서: [`../docs/stage-c-learning.md`](../docs/stage-c-learning.md) — D1 JWT 착수 전 `Depends` / RLS 섹션 복습 권장
- 외부 자료:
  - Cloudflare Tunnel: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
  - Supabase JWT 검증: https://supabase.com/docs/guides/auth/jwts
  - Python cryptography Fernet: https://cryptography.io/en/latest/fernet/
