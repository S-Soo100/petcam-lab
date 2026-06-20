# 맥미니 스케줄드 Claude 러너 — 폴링 워커 골격 + 스모크

> 맥미니가 일정 간격으로 깨어나 서버(Supabase/R2)를 폴링하고 Claude CLI(headless)를 호출하는 상시 워커의 **공통 골격**. 첫 마일스톤은 연결점 생사만 확인하는 walking-skeleton 스모크.

**상태:** 🚧 진행 중 (2026-06-20 **Phase 0 맥북 검증 완료 6/6** + GitHub push, 맥미니 이관·검증 남음)
**구현 레포:** [`S-Soo100/petcam-mac-runner`](https://github.com/S-Soo100/petcam-mac-runner) (private, 별도 레포 = 참조 스켈레톤. petcam-lab 통째 이관 아님)
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

**맥북 검증 ✅ 6/6 (2026-06-20).** 맥미니는 동일 절차 재검증 남음.

- [x] Slack `#mac-bot`에 webhook으로 "hello" 1줄 수동 POST 성공 (mac-worker-app webhook)
- [x] 스크립트가 Supabase에 가벼운 `select` 핑 → 성공/실패 분기 기록
- [x] 스크립트가 `claude -p "..."` 호출 → stdout 텍스트 수신 확인
- [x] 위 3개를 종합한 1줄(`✅ supabase · ✅ claude · HH:MM`)을 스크립트가 Slack에 자동 전송
- [x] **launchd(LaunchAgent)**로 무인 반복 (RunAtLoad 즉시 + StartInterval 5분, 2사이클 관찰) — ⚠️ **cron 아님**, §4 참조
- [x] 비밀값(`SUPABASE_*`, `SLACK_WEBHOOK_URL`) 전부 `.env` — git에 커밋 안 됨

> **남은 것 = 맥미니 동일 검증**: clone → `uv sync` → `.env`(맥북 값) → `claude -p`로 로그인 확인 → `./install-launchd.sh` → 로그 `✅ claude`. 통과 시 Phase 0 종료.

## 4. 설계 메모

### 핵심 결정 (2026-06-19 대화에서 합의)
| 항목 | 결정 | 이유 |
|------|------|------|
| Claude 호출 방식 | **형태② CLI headless** (`claude -p`) | 구독 정액 커버 (Gemini 퇴역 → Claude 구독 피벗의 연장). API 종량제 회피 |
| Slack 전송 주체 | **(b) 스크립트가 쏜다** (Claude 아님) | claude는 텍스트만 반환 → 단계별 진단 분리(claude 실패 vs slack 실패를 구분 가능). Claude한테 도구까지 시키면 스모크 취지(연결점 격리)에 역행 |
| 만드는 순서 | **슬랙부터 거꾸로** (슬랙 → supabase 핑 → claude → cron) | Slack = 결과를 눈으로 보는 창. 이게 먼저 살아야 나머지 디버깅이 보임 |
| 스케줄러 | ~~cron 5분~~ → **launchd(LaunchAgent) 필수** | ⚠️ **2026-06-20 발견·정정**: cron 잡은 GUI 로그인 세션 **밖**에서 돌아 claude 구독 인증(login keychain) 접근 불가 → `Not logged in`(rc=1). LaunchAgent는 GUI(Aqua) 세션 실행이라 keychain OK. 검증: 같은 스크립트 cron `❌claude` → launchd `✅claude`. 전제 = 자동로그인+GUI 세션 상시. (당초 "스모크=cron" 계획은 keychain 한계로 폐기) |
| Slack 방법 | **Incoming Webhook** | curl POST 한 방. bot token/OAuth 셋업 불필요 |

### 멘탈 모델
- **맥미니 = 서버가 아니라 클라이언트.** 집 공유기 NAT 뒤라 외부에서 inbound 불가, outbound만 자유. → 서버가 "일 생겼다"고 push해줄 수 없음 → 맥미니가 능동적으로 폴링하는 구조가 **강제**됨.
- 폴링 워커 루프: `깨어남 → "할 일?" 폴링(Supabase/R2) → 처리(claude) → 결과 쓰기 → 잠듦`.

### 미해결 질문 → 해소 (2026-06-20)
- ✅ Slack Incoming Webhook URL — 발급 완료(mac-worker-app → `#mac-bot`), 실물 전송 검증
- ✅ 맥미니 `claude` / `uv` 설치 — 둘 다 완료(사용자 확인). ⚠️ claude **로그인**(keychain 인증)은 맥미니에서 `claude -p` 1회로 별도 확인 필요(설치 ≠ 로그인)
- ✅ 맥미니 운영형태 — **자동로그인 + GUI 세션 상시**(LaunchAgent keychain 전제 충족)
- **Phase 1 어느 워커부터** (gate / nightly-reporter / 신규)? — **여전히 보류**.

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
- **launchd vs cron — keychain 세션 (2026-06-20 실측)**: claude 구독 인증은 macOS **login keychain**에 저장(`~/.claude/.credentials` 파일 아님). cron 데몬은 GUI 로그인 세션 밖이라 keychain 접근 불가 → `claude -p`가 `Not logged in`. **LaunchAgent(gui domain)는 사용자 GUI 세션에서 실행 → keychain 열림.** 그래서 구독 claude 헤드리스 = **launchd 필수**(cron 불가). 대안 `claude setup-token`(long-lived 토큰 → `CLAUDE_CODE_OAUTH_TOKEN` env, 구독 커버)도 있으나 사용자가 keychain 재사용(launchd) 선택. 이 교훈은 gate·nightly-reporter 등 **모든 맥미니 워커에 공통 적용**.

## 6. 참고

- **SOT**: `../../tera-ai-product-master/docs/specs/petcam-ai-pipeline.md` §11 (자매 레포 토폴로지 / R&D·운영 분리)
- **연관 스펙**: [`feature-mac-mini-local-track-a-worker.md`](feature-mac-mini-local-track-a-worker.md) · [`experiment-mac-mini-segmentvlm-worker.md`](experiment-mac-mini-segmentvlm-worker.md) (특정 워커 구현, rba-worker 미러) — 이 스펙은 그 워커들 **밑단 공통 인프라**.
- **메모리**: `object-store-time-index` · `project_gemini_retirement_claude_pivot` · `project_rba_pipeline_sister_repos`
- **환경**: [`../docs/MAC_MINI_DEV_ENV.md`](../docs/MAC_MINI_DEV_ENV.md)
