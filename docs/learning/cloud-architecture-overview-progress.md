# 클라우드 아키텍처 Part 1 — 학습 진도

> 자료: [`cloud-architecture-overview-learning.md`](./cloud-architecture-overview-learning.md)
> 시작: 2026-05-07

## 진행 상태

| 섹션 | 상태 | 약점 / 메모 |
|---|---|---|
| 1. 전체 아키텍처 그림 | ✅ | RLS 잘 잡음. **NAT 개념** 새로 배움 (공유기 = NAT, RTSP 가 LAN 안에서만 사는 이유) |
| 2. BaaS vs 자체 백엔드 | ✅ | 기회비용 OK. Lock-in 근거 중 **JWT** 빠뜨림 (Postgres 만 짚음) |
| 3. DB 가 Message Bus | ✅ | **Producer / Consumer / Redis / nginx 기본 개념 약함 — 별도 강의함** |
| 4. State Machine + Idempotency | ✅ | "재시도가 일상" 의 본질 (ACK 미도달 구간) 약했음. **"deterministic"** 단어 처음 배움 |
| 5. Polling vs Webhook vs Cron | ✅ | 3 문제 다 맞춤. 깔끔 통과 |
| 6. Contract Modularity > Code Modularity | ⏸️ 패스 | 사용자 요청으로 스킵. **나중에 다시 처음부터** |
| 7. VLM Worker 교체 가능 구조 | ✅ | Q2 (외부 프롬프트 ↔ v3.5 lock 연결) 못 떠올림. "인터페이스 안정성" 개념 새로 배움 |
| 종합 퀴즈 | ⏸️ 미진행 | 섹션 1~7 가로지르는 응용 문제. 약속했지만 안 함 |

## 복습 우선순위 (트리거 시 이 순서로)

1. **섹션 6 (Contract Modularity)** — 스킵된 섹션. 처음부터 강의 + 퀴즈.
2. **약점 재복습** (필요 시):
   - 분산 시스템에서 재시도가 "일상" 인 본질 (ACK 미도달 구간)
   - Producer / Consumer / Redis / Nginx 기본 개념
   - Deterministic 의 의미
3. **종합 퀴즈** — 섹션 1~7 가로지르는 응용 문제 3 개.

## 핵심 학습 인사이트 (자기 정리용)

- **DB 가 Message Bus** — Postgres `label_status` 컬럼 = 큐. Redis/RabbitMQ 안 씀. 정합성 위험 0 (시스템 1개).
- **Idempotency 의 본질** — exactly-once 는 분산 시스템에서 불가능. at-least-once + 멱등키 (UNIQUE 제약, deterministic R2 키) 로 같은 결과 보장.
- **재시도 안전 polling 쿼리** — `pending OR (processing AND old) AND retry_count < 3 + FOR UPDATE SKIP LOCKED`. 섹션 3, 4 의 모든 도구가 한 쿼리에 들어감.
- **Contract vs Code Modularity** — 언어/HW 경계 넘는 모듈화 = contract (R2 키 / DB 스키마 / 인증 / 이벤트 순서). 같은 코드베이스 안 swap = 인터페이스 + dataclass.
- **Polling 부터** — 단순한 트리거부터, webhook 은 진짜 실시간 필요할 때만. 하이브리드 (일반 polling + 위험 행동 webhook) 가 흔한 패턴.
- **Lock-in 약함의 조건** — 표준 프로토콜 (Postgres SQL, JWT) 위에 BaaS 가 얹힌 경우. Firebase 같은 독자 NoSQL 과 다름.

## 진행 방식 (트리거 시 따를 룰)

- **섹션 단위**: 강의 (3분) → 퀴즈 3 문제 → 채점 → 다음 섹션
- **모르는 개념 나오면 멈춰서 풀어주기** — 학습 레포 원칙. 답 막히면 답 바로 알려주지 말고 힌트 → 그래도 모르면 풀이.
- **톤**: 친구처럼 반말 ("~해", "~지", "~네", "~거든"). JS/TS 비유 적극 활용 (사용자 배경: Node.js 가벼운 경험 + Python 웹크롤링).
- **채점**: ✅ / 🟡 (절반) / 🟠 (방향 빗나감) / ❌. 보강 한 줄 항상 포함.
- **새 섹션 끝나면 이 진도 파일 업데이트** (상태 + 약점 메모).

## 트리거 단어

사용자가 다음 중 하나 보내면 이 파일 읽고 "복습 우선순위" 따라 진행:
- "클라우드 학습 이어서"
- "학습모드"
- "복습시켜줘"
- "Part 1 복습"
