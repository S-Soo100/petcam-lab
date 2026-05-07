# 클라우드 아키텍처 학습 — 펫캠 백엔드 재설계 (Part 1: 큰 그림)

> 2026-05-07 재설계 세션 합의 내용. 기존 FastAPI 단일 서버 구조 → Supabase BaaS + 분산 worker 구조로.
> **다음 단계 (캡처 worker 흐름 디테일) 들어가기 전 핵심 개념 정리.**
> TS/JS 비유 + "왜 이 결정?" 중심.

## TL;DR (6줄)

1. **Supabase = BaaS 풀스택** — Auth + Postgres DB + RLS + Webhooks + Edge Function 한 곳. frontend/flutter 가 SDK 로 직접 호출. **FastAPI 의 라우터 거의 사라짐** (worker 만 남음).
2. **R2 = 영상 byte storage 전용** — Supabase 메타데이터 source 와 분리. Worker 가 R2 직접 통신.
3. **Worker 분리** — Capture worker (LAN, 자체 HW 전 임시) + VLM worker (fly.io, 영구). 둘 다 Supabase DB + R2 와 통신.
4. **DB 가 message bus** — `clips.label_status` 컬럼이 큐 역할. SQS/RabbitMQ 안 씀.
5. **Polling > Webhook (현 단계)** — 5분 간격 SELECT 가 가장 단순. 실시간 필요해지면 Webhook 으로 진화.
6. **Contract 모듈화 > 코드 모듈화** — 자체 HW 도착 시 캡처 코드는 폐기 + 새로 짬. 모듈화 가치는 R2 키 규칙 / DB 스키마 / 인증 방식.

## 우선순위

| # | 주제 | 왜 중요한가 |
|---|------|-----------|
| 1 | [전체 아키텍처 그림](#1-전체-아키텍처-그림) | 모든 결정의 출발점. 누가 누구에게 호출하나. |
| 2 | [BaaS vs 자체 백엔드](#2-baas-vs-자체-백엔드--왜-supabase-유지) | Supabase 유지 결정 근거. 비용/lock-in/scale. |
| 3 | [DB 가 Message Bus](#3-db-가-message-bus--분산-시스템-핵심-패턴) | 분산 시스템 핵심. 큐/이벤트의 단순화. |
| 4 | [State Machine + Idempotency](#4-state-machine--idempotency) | 재시도 안전한 시스템의 기본. |
| 5 | [Polling vs Webhook vs Cron](#5-polling-vs-webhook-vs-cron) | 트리거 방식 결정. 시작은 단순한 거. |
| 6 | [Contract vs Code Modularity](#6-contract-modularity--code-modularity) | 자체 HW 인계 시점 직결. |
| 7 | [VLM Worker 교체 가능 구조](#7-vlm-worker-교체-가능-구조) | 모델/프롬프트 교체 빈번 예정. |

---

## 1. 전체 아키텍처 그림

### 한 줄 요약
**Supabase 가 중앙 데이터/권한/이벤트 허브**, 무거운 영상 처리는 **외부 worker** 가 R2 와 직접 통신.

### 다이어그램

```
┌─────────────────────────────────────────────────────────────┐
│                  Supabase (중앙 허브)                        │
│   Auth · Postgres DB · RLS · Webhooks · Edge Function       │
└──────────┬──────────────────────────────┬───────────────────┘
           │                              │
           │ (직접 SDK 호출)              │ (webhook trigger or polling)
           │                              │
┌──────────▼─────────┐         ┌──────────▼──────────┐
│ Frontend (web)     │         │  VLM worker         │
│ Flutter app        │         │  (fly.io, 영구)     │
└────────────────────┘         └──────────┬──────────┘
                                          │ (R2 직접)
                                          ▼
                               ┌─────────────────────┐
                               │ R2 (영상 byte)      │
                               └──────────▲──────────┘
                                          │ (R2 PUT)
                               ┌──────────┴──────────┐
                               │ Capture worker      │
                               │ (맥북 → 자체 HW)    │
                               └─────────────────────┘
```

### 컴포넌트 책임

| 컴포넌트 | 책임 | 라이프사이클 |
|---|---|---|
| Supabase | Auth, DB, RLS, 이벤트 hub | 영구 |
| R2 | 영상 byte 저장 | 영구 |
| Frontend (web/Flutter) | UI, Supabase SDK 직접 호출 | 영구 |
| Capture worker | RTSP → 모션 감지 → R2 + DB INSERT | **임시** (자체 HW 가 인계) |
| VLM worker | pending 클립 → Gemini → labels INSERT | 영구 |
| 자체 HW (미래) | 카메라 + 캡처 + 업로드 통합 | 영구 |

### TS/JS 비유

이 그림 = 전형적인 **Jamstack + worker** 아키텍처:
- Supabase ≈ Firebase / Convex (BaaS)
- VLM worker ≈ Inngest / Trigger.dev / Cloud Functions (job worker)
- R2 ≈ S3 / Vercel Blob
- Frontend SDK 직접 호출 = Next.js + Supabase 의 표준 패턴

Node 진영의 비슷한 구조: Next.js + Supabase + Inngest + R2.

---

## 2. BaaS vs 자체 백엔드 — 왜 Supabase 유지?

### 한 줄 요약
**작은~중간 규모에선 Supabase 가 압도적으로 싸고 빠름.** 진짜 자체 운영 가는 시점은 전담 DevOps 인력 있을 때.

### 비용 비교 (현실)

| 규모 | Supabase | 자체 서버 | 운영 시간 |
|---|---|---|---|
| 1만 사용자 | $25/월 | ~$50 (Hetzner+Neon+Clerk) | 자체: ~10h/월 |
| 10만 사용자 | ~$50-100/월 | ~$200/월 + 운영 | 자체: ~30h/월 |
| 100만 사용자 | ~$500-2000/월 | ~$500-1500/월 | 자체: 전담 인력 |

**핵심 인사이트:** 진짜 비용은 **인력 시간**. 작은 규모에선 Supabase 가 압도적으로 쌈. 시간 절감분을 코어 가치 (VLM/HW) 에 투입 = 비즈니스 가치 ↑.

> Tera AI 의 차별점은 **펫 행동 AI** 이지 백엔드 인프라가 아님. 인프라는 BaaS 에 위임.

### Lock-in 분석

Supabase 가 진짜 lock-in 인가? **아님.**

| 영역 | 떠날 수 있나? |
|---|---|
| DB | ✅ Postgres → Neon/RDS/self-host 그대로 이전 |
| Auth | ✅ 표준 JWT → user 마이그레이션 가능 |
| Realtime / Edge Function | ⚠️ Supabase 고유 — 깊게 안 쓰면 무시 가능 |
| 자체 호스팅 | ✅ Supabase 자체가 self-host 가능 |

→ **Firebase 같은 NoSQL/proprietary lock-in 과 다름.** 떠나야 하면 떠날 수 있음.

### 결정 기준 (실전)

- **0~10만 사용자**: Supabase 유지
- **10만+**: 일부만 자체 (예: VLM worker 자체, DB 는 계속 Supabase)
- **진짜 한계 ($1000+/월, 전담 인력 가용)**: 그때 일부씩 → Postgres/JWT 표준이라 이전 가능

### TS/JS 비유

"Supabase 쓸까 자체 서버 쓸까" = "Vercel 쓸까 자체 nginx 쓸까" 와 동급 결정. 인력 시간 vs 인프라 비용 트레이드오프.

---

## 3. DB 가 Message Bus — 분산 시스템 핵심 패턴

### 한 줄 요약
**별도 큐 시스템 (SQS, RabbitMQ) 없이 Postgres 의 한 컬럼만으로 큐 구현.**

### 전통적인 큐 시스템

```
[Producer] → [SQS / RabbitMQ] → [Consumer]
```

별도 인프라 (Redis, RabbitMQ) 가 큐 역할.

### 우리 패턴

```
[Capture worker] → INSERT clips (status='pending') → Postgres
                                                       │
                                            (polling or webhook)
                                                       │
                                                       ▼
                                              [VLM worker] reads
                                              UPDATE clips (status='done')
```

DB 자체가 큐. `label_status` 컬럼이 핵심.

### 왜 이게 동작하나

- **DB 가 진실의 source** — 모든 worker 가 같은 DB 만 보면 됨. 다른 영구 저장소 필요 없음.
- `label_status` 컬럼이 큐 역할 (pending → processing → done/failed)
- Postgres 의 `FOR UPDATE SKIP LOCKED` 로 multi-worker race condition 방지 가능 (필요 시)
- 별도 큐 시스템 비용/복잡도 X

### 언제 전용 큐로 이전하나

- 처리량 매우 높음 (초당 수천+ 메시지)
- 복잡한 retry/dead-letter 정책
- DB 부하 분리 필요

→ 펫캠은 처리량 작아서 **Postgres-as-queue 충분.** 한참 동안.

### TS/JS 비유

NestJS BullMQ 가 Redis 를 큐로 쓰는 패턴 ≈ 우리는 Postgres 를 큐로 씀. 같은 컨셉, 다른 backing store.

---

## 4. State Machine + Idempotency

### 한 줄 요약
**작업 단위 (clip) 가 상태를 가진다 + 같은 작업 재실행 안전해야.**

### State machine

```
pending  ──VLM worker가 잡음──→  processing
                                        │
                          ┌─── 성공 ────┴─── 실패 ──┐
                          ▼                        ▼
                        done                     failed (retry_count++)
```

각 상태의 의미:
- `pending`: 캡처 완료, VLM 대기
- `processing`: 어떤 worker 가 처리 중 (lock 효과)
- `done`: 라벨 INSERT 완료
- `failed`: 영구 실패 (retry_count 임계 초과)

### Idempotency 가 왜 중요?

worker 가 처리 중 죽으면 어떻게 되나?
- pending → processing 까진 갔는데 결과 INSERT 전에 죽음
- 재시작 후 같은 클립 다시 잡음
- **두 번 처리해도 같은 결과** 가 보장돼야 (idempotent)

### 어떻게 보장?

- `labels` 테이블에 `(clip_id, model)` UNIQUE 제약
- 같은 클립 두 번 INSERT 시도 → DB 에서 거절 (또는 UPSERT)
- 결과: 중복 라벨 안 생김

### TS/JS 비유

Stripe API 의 `Idempotency-Key` 헤더 ≈ 우리의 UNIQUE 제약. 같은 키로 두 번 요청해도 한 번만 적용.

---

## 5. Polling vs Webhook vs Cron

### 한 줄 요약
**현 단계: Polling (5분 간격) 가장 단순.** 실시간 필요해지면 Webhook.

### 비교

| | Polling | Webhook | pg_cron |
|---|---|---|---|
| 동작 | worker 가 N분마다 SELECT | INSERT → Supabase 가 외부 URL POST | Supabase cron 이 batch trigger |
| Latency | 최대 N분 | 즉시 | cron 주기 |
| 단순성 | 가장 단순 | retry 정책 필요 | 중간 |
| 실패 시 | 다음 polling 자동 재시도 | webhook 실패 → 재시도 정책 | 다음 cron 재시도 |

### 왜 Polling 으로 시작?

- 펫캠은 실시간 X — 5분 latency 무관 (사용자가 즉시 라벨 보는 시나리오 거의 없음)
- Polling 비용 무시 가능 (작은 SELECT 쿼리)
- batch 처리 = Gemini API 묶어서 호출 (비용 효율)
- 코드 단순 = 디버깅 쉬움

```python
# VLM worker 의 핵심 루프
while True:
    clips = supabase.table('clips') \
        .select('*').eq('label_status', 'pending') \
        .limit(10).execute()
    for clip in clips.data:
        process(clip)
    time.sleep(300)  # 5분
```

### Webhook 으로 진화 시점

- 실시간 알림 필요 (예: 이상 행동 감지 즉시 알림)
- 한 클립만 즉시 처리해야 할 때 (사용자가 "지금 분석" 버튼 누름)
- 처리량 매우 높아서 polling 비효율

### TS/JS 비유

- Polling = `setInterval(() => fetch(...), 300000)` 단순한 패턴
- Webhook = Stripe 의 `event.subscription.updated` webhook 같은 push 모델

---

## 6. Contract Modularity > Code Modularity

### 한 줄 요약
**자체 HW 도착 시 캡처 코드는 폐기 + 새로 짬.** 모듈화 가치는 contract 레벨에서만.

### v1 vs v2 코드의 차이

| | v1 (Tapo + 맥북) | v2 (자체 HW) |
|---|---|---|
| 언어 | Python | 펌웨어 (C/C++/Rust/MicroPython) |
| 영상 source | RTSP pull (OpenCV) | 카메라 센서 직접 |
| 모션 감지 | OpenCV 알고리즘 | 자체 칩 or SW |
| 인코딩 | FFmpeg | HW encoder |
| 업로드 | Python R2 SDK | HTTP/S3 펌웨어 lib |

→ **코드 거의 100% 다시 짜야.** v1 코드를 abstract class 로 모듈화 = 의미 없음.

### 모듈화 가치 = Contract

자체 HW 펌웨어 작성자(미래의 너)가 알아야 할 것:
- **R2 키 네이밍 규칙** (예: `clips/{userId}/{date}/{clipId}.mp4`)
- **clips 테이블 스키마** (필수 필드, 타입)
- **인증 방식** (Supabase 에 INSERT 권한 어떻게 받나)
- **이벤트 순서** (R2 먼저? DB 먼저? 실패 시 cleanup?)

→ 이걸 `specs/` 에 contract 로 문서화. v2 가 동일 contract 따라 push 하면 됨. **코드는 달라도 클라우드 입장에선 같은 모양.**

### YAGNI 원칙

CLAUDE.md: "추상화는 같은 패턴 3번 반복될 때." v1 (Tapo) 만 = 1번. **추상화 시기 아님.** 자체 HW 도 다른 코드베이스라 "반복" 카운트 안 됨.

### 핵심 교훈

> **"교체 가능"** = abstract class 로 갈아끼우기 가 아니라 **폐기 + 새로 짜기**.
> 그래서 모듈화는 코드가 아니라 contract 레벨에서.

---

## 7. VLM Worker 교체 가능 구조

### 한 줄 요약
**v1 부터 모델 교체 빈번 예정.** 인터페이스 + 결과 표준화만 + 과잉 추상화 X.

### 균형점

```
VLM worker
├─ label_clip(clip_path) → Label  # 단일 함수 인터페이스
├─ implementations/
│   ├─ gemini_flash.py            # 모델별 모듈
│   └─ claude_sonnet.py
├─ prompts/v3.5.txt               # 프롬프트 외부화
└─ Label dataclass                # 결과 표준화
```

### 왜 이 정도인가

- **인터페이스 1개** (`label_clip`) — 호출자는 어떤 모델인지 모름
- **구현 분리** — 모델별 모듈. switch 는 환경변수
- **결과 dataclass 표준화** — 모델 교체해도 DB/frontend 영향 X
- **프롬프트 외부화** — 코드 안 바꾸고 prompt 수정

### 진화 방향 (v1 이후)

1. 모델 교체 — Flash → Pro → fine-tuned
2. 다단계 분류 — 저비용 broad → specialized
3. 프레임 샘플링 — full video vs key frames
4. HITL feedback — 사람 수정 라벨 → fine-tuning 데이터
5. 자체 specialized 모델 — 펫 행동 전용 분류기 (Round 2+)

→ 인터페이스만 안정적이면 위 모든 진화가 호출 코드 수정 없이 가능.

### TS/JS 비유

LangChain 의 `LLMChain` interface 와 비슷. 모델 swap 가능, 호출자는 모름.

---

## 핵심 결정 요약 (한 페이지)

| 영역 | 결정 | 이유 |
|---|---|---|
| Auth + DB | Supabase | 인력 시간 절감, 학습 손실 거의 없음 |
| 영상 storage | R2 | 비용/성능 |
| 캡처 worker | LAN (맥북 → 자체 HW) | RTSP NAT 제약 (자체 HW 전), 자체 HW 후 인계 |
| VLM worker | fly.io 컨테이너 | Edge Function 시간 제약 회피, 자체 HW 무관 영구 |
| Frontend | Supabase SDK 직접 | 백엔드 의존 제거 → 맥북 꺼져도 동작 |
| 트리거 | Polling 5분 | 단순 + 실시간 불필요 |
| 큐 | Postgres `label_status` 컬럼 | 별도 큐 시스템 불필요 |
| 모델 교체 | 인터페이스 + dataclass | 호출 코드 수정 없이 모델 swap |
| 자체 HW 인계 | Contract 문서화 | 코드 폐기, contract 만 안정 |

---

## 다음 단계 예고 (Part 2 자료에서 다룰 것)

- 캡처 worker 흐름 디테일 — RTSP → 모션 → 클립 → R2 → DB
- 데이터 모델 — clips/labels/cameras 테이블 설계
- 인프라 — fly.io 스펙, secret 관리, 배포
- 마이그레이션 순서 — 기존 코드에서 새 구조로

---

## 참고 — 이 자료의 출처

2026-05-07 클라우드 아키텍처 재설계 세션에서 합의된 내용 정리. 핵심 결정:

- 기존 FastAPI 단일 서버 → Supabase BaaS + 분산 worker
- 캡처 worker = 임시 (자체 HW 가 인계)
- VLM worker = 영구 (fly.io)
- R2 = 영상 byte 저장, Supabase = 메타/Auth/이벤트 hub
- 마이그레이션 시 frontend 의 fetch → Supabase SDK 직접 호출로 갈아끼우기

**관련 메모리:**
- `project_capture_replaced_by_own_hw.md` — 캡처 worker 자체 HW 대체 계획
- `project_macbook_migration_pending.md` — 맥북 마이그레이션 대기 상태
- `project_vlm_v35_baseline_lock.md` — VLM v3.5 production lock

다음 세션에서 캡처 worker 흐름부터 구체화 들어감.
