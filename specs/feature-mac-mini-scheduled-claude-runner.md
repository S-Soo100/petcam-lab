# 맥미니 스케줄드 Claude 러너 — 폴링 워커 골격 + 스모크

> 맥미니가 일정 간격으로 깨어나 서버(Supabase/R2)를 폴링하고 Claude CLI(headless)를 호출하는 상시 워커의 **공통 골격**. 첫 마일스톤은 연결점 생사만 확인하는 walking-skeleton 스모크.

**상태:** 🚧 진행 중 (계획 정렬 단계 — 2026-06-19 개념·계획 합의, 코드 착수 전)
**작성:** 2026-06-19
**연관 SOT:** `../../tera-ai-product-master/docs/specs/petcam-ai-pipeline.md` §11 (RBA 파이프라인 / 자매 레포 토폴로지)

## 1. 목적

- **사용자 가치**: gate · nightly-reporter · rba-worker 등 맥미니 상시 워커들이 전부 공유하는 "주기 실행 + 서버 폴링 + Claude 호출" 패턴을 한 번 제대로 세팅. 워커마다 다시 발명하지 않도록 공통 뼈대 확정.
- **학습 목표**: 폴링 워커 패턴 / OS 스케줄링(launchd · cron) / Claude CLI headless 호출 / Slack Incoming Webhook 알림.
- **왜 지금**: 맥미니 셋업 착수 직전. 실제 라벨링·리포팅 로직을 붙이기 **전에**, 인프라 연결점(스케줄러 · Supabase · Claude · Slack)이 다 살아있는지부터 검증한다 (walking skeleton). 나중에 워커가 안 돌 때 "로직 버그인지 인프라 단절인지" 변수를 미리 제거.

## 2. 스코프

### In (이번 스펙에서 한다)
- **Phase 0 — 스모크(walking skeleton)**: cron 주기 실행 → Supabase 핑 → `claude -p` 호출 → 결과 1줄을 Slack `#mac-bot`에 전송. 4개 연결점(스케줄러·Supabase·Claude·Slack) 생사 확인.
- **공통 골격 문서화**: 폴링 워커 루프 구조, 비밀값(.env) 관리, 스케줄러 선택 기준(cron↔launchd).

### Out (이번 스펙에서 **안 한다**)
- **실제 라벨링/리포팅 로직** — 어느 워커부터 살 붙일지는 **보류**(Phase 1). 스모크 통과가 선행 조건.
- **무한루프 + launchd KeepAlive 상시화** — 스모크는 cron 단발(한 번 돌고 죽음)로 충분. 상시 프로세스는 정착 단계에서.
- **Supabase 라벨 쓰기영역 설계** — Phase 1에서. gate `clip_prelabels`와 쓰기영역이 겹치지 않게 분리(아래 깃발 참조).

> **스코프 변경은 합의 후에만.** Phase 0 스모크가 In의 전부. 그 이상은 Phase 1로 미룬다.

## 3. 완료 조건 (Phase 0 스모크)

만드는 순서 = **아래 위에서부터** (성공 신호 창인 Slack부터 거꾸로 붙인다).

- [ ] Slack `#mac-bot`에 webhook으로 "hello" 1줄 수동 POST 성공 — **성공 신호 창부터 확보** (이게 살아야 나머지 디버깅이 보임)
- [ ] 스크립트가 Supabase에 가벼운 `select` 핑 → 성공/실패 분기 기록
- [ ] 스크립트가 `claude -p "..."` 호출 → stdout 텍스트 수신 확인 (= Claude 구동 성공 증명)
- [ ] 위 3개를 종합한 1줄(`✅ supabase · ✅ claude · HH:MM`)을 스크립트가 Slack에 자동 전송
- [ ] cron(5분 간격)으로 위 스크립트가 무인 반복 실행됨을 2~3 사이클 관찰
- [ ] 비밀값(`SUPABASE_*`, `SLACK_WEBHOOK_URL`) 전부 `.env` — git에 커밋 안 됨

## 4. 설계 메모

### 핵심 결정 (2026-06-19 대화에서 합의)
| 항목 | 결정 | 이유 |
|------|------|------|
| Claude 호출 방식 | **형태② CLI headless** (`claude -p`) | 구독 정액 커버 (Gemini 퇴역 → Claude 구독 피벗의 연장). API 종량제 회피 |
| Slack 전송 주체 | **(b) 스크립트가 쏜다** (Claude 아님) | claude는 텍스트만 반환 → 단계별 진단 분리(claude 실패 vs slack 실패를 구분 가능). Claude한테 도구까지 시키면 스모크 취지(연결점 격리)에 역행 |
| 만드는 순서 | **슬랙부터 거꾸로** (슬랙 → supabase 핑 → claude → cron) | Slack = 결과를 눈으로 보는 창. 이게 먼저 살아야 나머지 디버깅이 보임 |
| 스케줄러 | 스모크 = **cron 5분**, 정착 = **launchd** | cron은 디버깅 루프가 짧음(1시간 안 기다림). launchd는 KeepAlive 자가복구가 정착에 유리 |
| Slack 방법 | **Incoming Webhook** | curl POST 한 방. bot token/OAuth 셋업 불필요 |

### 멘탈 모델
- **맥미니 = 서버가 아니라 클라이언트.** 집 공유기 NAT 뒤라 외부에서 inbound 불가, outbound만 자유. → 서버가 "일 생겼다"고 push해줄 수 없음 → 맥미니가 능동적으로 폴링하는 구조가 **강제**됨.
- 폴링 워커 루프: `깨어남 → "할 일?" 폴링(Supabase/R2) → 처리(claude) → 결과 쓰기 → 잠듦`.

### 미해결 질문 (사용자 확인 대기 — 스모크 출발선)
- Slack Incoming Webhook URL 발급 상태? (없으면 발급부터)
- 맥미니에 `claude` CLI / `uv` 설치 상태?
- **Phase 1 어느 워커부터** (gate / nightly-reporter / 신규)? — **보류**.

### 🚩 깃발 (Phase 1에서 해소)
Phase 1에서 라벨을 Supabase에 쓸 때, gate의 `clip_prelabels`와 **쓰기영역을 분리**해야 함. 토폴로지 원칙 = "worker 공존 = 스토어별 쓰기영역 분리"(petcam-ai-pipeline §11.3, write-write 충돌 0). 새 워커의 쓰기 테이블/컬럼을 설계 시 먼저 못 박을 것.

### Phase 1 예상 흐름 (사용자 제시, 2026-06-19)
`Supabase todo 조회 → 그 row의 R2 영상 가져오기 → 프레임 추출/조회 → claude 라벨링 → Supabase에 라벨 쓰기`. = §1의 폴링 워커 골격 그대로. "어디까지 처리했나" 표식(processed 컬럼 등)이 핵심 설계 포인트.

## 5. 학습 노트

- **폴링 워커(polling worker)**: 깨어남→폴링→처리→쓰기→잠듦 루프. Node `setInterval(fn, ms)`과 동형 — 다만 "할 일이 있을 때만" 처리한다는 점이 추가.
- **폴링 vs 푸시(push/webhook)**: 푸시는 서버가 먼저 알려주는 방식인데, 맥미니는 inbound가 막혀 푸시를 **못 받음** → 폴링이 강제됨. (R2 같은 object store는 시간 인덱스가 약해 시간범위 폴링은 DB(`started_at`)로 — 메모리 `object-store-time-index`.)
- **스케줄링 2층**:
  - 프로세스 내부 `while True: ...; time.sleep(n)` (≈ `setInterval`) — 프로세스가 계속 떠 있어야 함.
  - OS 스케줄러 `launchd`(맥 네이티브, `.plist`) / `cron`(`crontab -e`) — "N분마다 한 번 실행", 스크립트는 돌고 죽음. **launchd KeepAlive** = 죽으면 OS가 자가복구.
- **Claude headless**: `claude -p "프롬프트"` = 대화 없이 1회 호출, 결과를 stdout으로. 사람 없이 스크립트가 부르는 Claude Code. 구독으로 커버.
- **Slack Incoming Webhook**: 채널에 1줄 알림 보내는 최단 경로. 발급받은 URL에 JSON(`{"text": "..."}`) POST.
- **walking skeleton / smoke test**: 살을 붙이기 전, end-to-end 뼈대를 얇게 한 줄 관통시켜 연결점 생사부터 검증하는 패턴. 변수 제거 → 이후 디버깅이 쉬움.

## 6. 참고

- **SOT**: `../../tera-ai-product-master/docs/specs/petcam-ai-pipeline.md` §11 (자매 레포 토폴로지 / R&D·운영 분리)
- **연관 스펙**: [`feature-mac-mini-local-track-a-worker.md`](feature-mac-mini-local-track-a-worker.md) · [`experiment-mac-mini-segmentvlm-worker.md`](experiment-mac-mini-segmentvlm-worker.md) (특정 워커 구현, rba-worker 미러) — 이 스펙은 그 워커들 **밑단 공통 인프라**.
- **메모리**: `object-store-time-index` · `project_gemini_retirement_claude_pivot` · `project_rba_pipeline_sister_repos`
- **환경**: [`../docs/MAC_MINI_DEV_ENV.md`](../docs/MAC_MINI_DEV_ENV.md)
