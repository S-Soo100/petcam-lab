# Codex 작업 이관 — 2026-07-21 연구 재정렬 이후

> **⛔ SUPERSEDED AS ACTIVE HANDOFF:** 이 문서는 Claude→Codex 전환 당시의 historical 입력이다. 현재 활성 정본은 [`../research/ACTIVE-RESEARCH.md`](../research/ACTIVE-RESEARCH.md)이며 충돌 시 그 문서와 decision-gate를 따른다.
>
> 작성: Claude (2026-07-21 저녁, 실제 문서 추가 커밋 `5f50242f0971275dd98da9e32b9df85605d15419`) · 대상: Codex/ChatGPT (codex CLI)
> 이 문서는 자급자족형이다 — 이 파일 + 아래 읽기 순서만으로 컨텍스트가 복원돼야 한다.

## 0. 시작 계약 (순서대로)

1. `cd /Users/baek/petcam-lab && git fetch && git status` — 원격보다 뒤처져 있으면 pull 먼저.
2. 읽기 순서: ① [`AGENTS.md`](../../AGENTS.md) §4-1 step 0 ② [`specs/next-session.md`](../../specs/next-session.md) 최상단 + **2026-07-21 블록 전체** ③ [`docs/decision-gate.md`](../decision-gate.md) 판정 로그 전체.
3. 이 문서와 위 기록이 충돌하면 **decision-gate 로그 > next-session > 이 문서** 순으로 신뢰하고, 충돌 사실을 owner에게 보고.

## 1. 현재 상태 스냅샷 (2026-07-21 저녁)

| 항목 | 상태 |
|---|---|
| P1 라벨 결정론 | 진단·재측정 **완료** — 오탐 42건 중 진짜 오탐 1건(`3e51c7ed`, 물 디스펜서 근접 confabulation, owner 확정), 나머지 41건 = temperature 비결정성. 플랜 B(구독 CLI 3회-일치) `adopt`(약식). **운영 배선(Task 4)은 미착수** — Anthropic 콘솔 결제 결함(KR 개인 크레딧 구매 불가, 지원팀 문의 예정)으로 API 키 없음 |
| P2 케이지 프로필 메타 | **hold** — 실증 근거 1/42뿐. temp=0 확정판(A안) 후 재판단. 착수 금지 |
| P3 = T1 하이라이트 선별 | **reject** — 합성점수 v1 무효. 원인 = detector v2 오검출이 존재+주기성 성분 동시 오염(Cam 2 상시 오염원). v2는 새 TEST-SHEET + decision-gate 재통과 필수 |
| T0 bowl-dwell | **reject** — 근접≠케어. 도메인 사실: drinking은 시간축(분무-window) 문제 |
| 사전 필터(나쁜 클립 제거) | **영구 탈락** — 재제안 금지 (decision-gate 기록) |
| 운영 | launchd auth 장애 해소(키체인/파일 이원 저장 3차 함정). 적체 job 소화 중(succeeded 7 확인). **오늘 밤 카메라 재가동(야간모드) + 22:00 사이클 = 실전 복귀 검증 대기** |
| 사람 GT | blind 판정 120건 적립 (T0 80 + T1 40) |

자매 레포 상태: `petcam-nightly-reporter` `feat/vlm-basking-classification` @ `139ff89` — P1 진단·재측정 산출물 전부 여기(REPORT-B 등). **petcam-lab에서 그 레포 코드를 직접 수정하지 말 것** (docs 커밋도 handoff 컨벤션 안에서만).

## 2. 인계 작업 (우선순위순)

### W1 — 밤 사이클 복구 검증 (07-22 아침, read-only)
- DB SELECT로 확인: `clip_vlm_jobs` 7/20 적체분 소화(queued→succeeded), `failed_retryable` 8건이 새벽 1:10 한도 리셋 후 해소됐는지, 밤 신규 클립·라벨 생성 여부. Slack VLM 요약 카드 도착 여부는 owner에게 질의.
- 결과를 `specs/next-session.md`에 한 블록 append. **DB 쓰기 절대 금지** (SELECT only).
- 실패 지속 시: 수정 시도 금지, 증거(진단 diagnostic JSON) 수집 후 owner 보고. launchd/LaunchAgent 조작 금지.

### W2 — T2 GT 엔진 스펙 초안 (decision-gate 조건부 통과 항목)
- 근거: decision-gate 레코드 #1 "hard negative 21건 → T2 GT 엔진 투입 = 조건부 통과". 조건 = ⓐ `near_bowl_no_care`가 기존 라벨 체계에 없음 → 스키마 매핑 결정 ⓑ DB 쓰기 범위 별도 스펙 + owner 승인.
- 산출물: `specs/` 스펙 문서 초안(스코프·In/Out·완료 조건). ⚠️ GT 이중저장소 함정 주의(`behavior_labels` vs `behavior_logs source=human` — petcam-lab 메모리/CLAUDE.md 참조). **승인 전 DB 쓰기·구현 착수 금지 — 문서만.**
- 재료: T0 hard negative 21건(`experiments/t0-bowl-dwell-probe/key/` + REPORT), T1 blind 40건, 라벨링 웹 v2(운영 pilot 대기 상태).

### W3 — T1 점수식 v2 제안 (선택, 여력 있으면)
- 전제: **decision-gate 4게이트 통과 판정을 로그에 append한 뒤에만** TEST-SHEET 작성. v2 재등판 조건(로그에 명시): 오검출 시그니처 페널티(한 셀 고정+전체 관찰+고주기) / 카메라 정규화 / Gate prelabel 결합 중 택.
- T1 인프라 재사용: `scripts/t1_highlight_rank.py`(percentile·버킷캡·blind 셔플) + `scripts/t1_score_probe.py`. 동결된 T0/T1 시트·표본은 수정 금지.

### 하지 말 것 (탈락·보류 재등판 방지)
- 사전 필터/비용 게이팅 재제안 ✗ · P2 착수 ✗ · 분무 이벤트 검출 probe(owner 보류) ✗ · 프롬프트 룰 추가 ✗ · detector v3 ✗ · local router threshold 튜닝 ✗ (전부 decision-gate에 탈락/보류 기록 있음 — 재평가하려면 탈락 사유 해소를 먼저 제시)

## 3. 하드 룰 (전 작업 공통)

1. **새 방향 제안 = decision-gate 4게이트 선통과 + 로그 append** (기존 행 수정 금지).
2. **의사결정용 테스트 = TEST-SHEET(사전등록·동결) → 실행 → REPORT → INDEX** (`.claude/rules/research-testing.md`).
3. **트랙 분리 준수** (CLAUDE.md): Claude 구독 판독 연구(nightly-reporter/rba-worker) 결과를 덮어쓰거나 그쪽 정책을 임의 변경하지 않는다.
4. production DB는 **SELECT only** (쓰기는 스펙+owner 승인 후). 파괴적 git 금지. 영상은 `storage/` 하위만.
5. 완료 시: 관련 spec 체크박스 갱신 + `specs/next-session.md` append + Standard 이상이면 `.claude/donts-audit.md` 한 줄.

## 4. STOP 조건

- W1에서 장애 재발/신규 장애 → 보고 후 대기 (수리 금지)
- W2 스키마 매핑에 복수 유효안 → 비교표 만들어 owner 선택 대기
- 게이트 판정이 △/✗인데 진행하고 싶은 근거가 있음 → 진행 말고 근거를 로그에 적고 owner 질의
