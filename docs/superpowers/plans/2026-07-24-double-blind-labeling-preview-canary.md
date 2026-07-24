# 이중 블라인드 라벨링 — Preview 배포 + 12클립 격리 canary 준비 계획 (2026-07-24)

> 선행: `docs/handoff-prompts/2026-07-24-double-blind-labeling-hardening-report.md` (`DOUBLE_BLIND_LABELING_HARDENED_READY_FOR_DB_PREVIEW`, Codex 재검수로 P1 3건 닫힘 확인).
> 설계 정본: `docs/superpowers/specs/2026-07-23-double-blind-labeling-groups-design.md`.
> 이 계획은 owner 가 이번에 명시 승인한 **외부 변경 범위 안에서만** 실행한다. 사람 제출 직전에서 멈춘다.

**Goal:** 검증된 forward migration 을 production Supabase 에 적용하고, feature-branch Vercel preview 를 확인하고, 실데이터와 분리된 전용 canary group/cohort + 12 clip + reviewer 2명을 준비해 사람 라벨러가 접속만 하면 되는 상태(`DOUBLE_BLIND_LABELING_CANARY_READY_FOR_HUMAN_REVIEW`)로 만든다. **사람 제출은 하지 않는다.**

**Runtime target:** production Supabase project `slxjvzzfisxqwnghvrit`(= `.env.example`·docs 기대값과 일치, MCP `get_project_url` 로 확인) + feature-branch Vercel preview.

## 승인된 외부 변경 (이번만)
- production Supabase 에 검증된 forward migration 적용(기존 migration 파일 수정 없음, 새 migration entry).
- migration 직후 RLS·grant·함수·테이블·advisor 검증.
- Vercel feature-branch preview 배포/확인.
- 실데이터 분리 전용 canary group/cohort 생성(live camera assignment 0).
- canary clip 12 + reviewer 2 준비.
- read-only/API smoke(제출 없음).

## 금지 (하드 게이트)
- main merge · Vercel production 배포 · `LABELING_QUEUE_SOURCE` 등 production env 변경.
- live cohort/group/camera assignment.
- 기존 label·GT·triage·behavior·activity 수정.
- 기존 151건 canary 재사용/manifest 생성.
- 사람 대신 submission/GT DB 직접 생성.
- 상대 라벨·evidence·VLM 을 labeler 에 노출.
- force push · 기존 migration 수정.
- 보고서/로그에 비밀값·전체 UUID·이메일 원문 기재(마스킹).

## 두 reviewer (owner 제공, 문서에 원문 미기재)
- reviewer#1: display_name `크랑이아빠`.
- reviewer#2: email(owner 제공, 문서·manifest 에 미기재 — 실행 시 owner 지정값으로만 resolve).
- 두 계정을 approved labeler 에서 **read-only 로 정확히 1명씩** resolve. `크랑이아빠` 가 0명 또는 2명 이상이면 임의 선택 없이 **중단**.

---

## Gate A — production read-only preflight
- MCP `get_project_url` 로 target=`slxjvzzfisxqwnghvrit` 재확인. 다르면 중단.
- migration 미적용 확인: `motion_clip_consensus`·`motion_clip_review_slots`·`motion_clip_blind_submissions` 등 신규 테이블 부재.
- 스냅샷(개수/fingerprint, UUID·PII 미노출): 관련 테이블·함수·grant·RLS·migration 이력. 기존 GT/label/session/consensus 계열 count + md5 지문.
- 통과 조건: target 일치 + 신규 테이블 0.

## Gate B — build 및 preview
- `npm run build` 는 repository guard(donts#9)가 세션 내 차단 → **UNVERIFIED, tsc 로 대체하지 않음**(정직 표기). owner 터미널/Vercel 이 실빌드.
- feature-branch(`codex/double-blind-labeling-hardening`) Vercel preview build 의 실제 success 상태 + 등록 route 를 `vercel`/`gh` deployment status 로 확인.
- preview build 실패면 migration 적용 전 중단.

## Gate C — migration
- 기존 migration 파일 수정 없이 production 에 forward 적용(MCP `apply_migration`; Supabase 가 자체 tx 래핑하므로 파일 `BEGIN;`/`COMMIT;` 제거 후 DDL 만 전달).
- 적용 직후 검증: 신규 테이블·RPC 존재 / RLS enabled / client policy 0·anon·authenticated 권한 0 / service_role 외 EXECUTE 0 / append-only trigger 존재 / advisor 신규 critical·error 0.
- disposable DB 통과 probe 중 **production 에 mutation 을 남기지 않는 검사만** transaction `BEGIN … ROLLBACK` 으로 재확인. residue 반드시 0.

## Gate D — 12클립 canary 데이터 준비
- 두 reviewer 를 approved labeler 에서 read-only resolve(1명씩 정확히). 불일치 시 중단.
- 전용 canary group 생성(name 전용, **live camera assignment 0**).
- `cohort_kind='canary'` 전용 cohort 생성.
- 최근 재생 가능한 **P4 Cam** clip 중 12개 선택: `r2_key` 존재 + 재생 가능 + 기존 canary 와 중복 없음 + 기존 GT/label 무변경 + 가능하면 시간대·행동 분산.
- 동일 12개가 두 reviewer 에게 각각 배정되는지 확인(canary slot 24 = 12×2).
- 상대 제출 여부·내용이 labeler API 에서 미노출인지 확인.

## Gate E — 비파괴 smoke
- preview 에서 두 계정 canary workspace 접근 가능성 확인(제출 없음). 나는 두 계정으로 로그인 불가 → **API 응답 구조/RPC 출력(allowlist·peer 부재)으로 blind 검증**, 실제 브라우저 로그인은 사람 몫(Stop Point).
- 각 계정이 12개를 보고 상대 정보·제출 상태를 못 보는지 응답 구조로 확인.
- owner 화면은 canary 상태를 볼 수 있고 conflict/agreed 0 이 정상.
- production `/labeling` 기본 경로·기존 legacy/motion labeling 동작 무변경.

## Stop Point
사람 라벨러가 실제 12개를 제출해야 하는 지점에서 멈춘다. `DOUBLE_BLIND_LABELING_CANARY_READY_FOR_HUMAN_REVIEW`. migration·preview·canary 준비가 모두 성공해도 사람 제출 전에는 DEPLOYED/PRODUCTION_READY 를 주장하지 않는다.

## Rollback / canary 제거 절차
- canary cohort: `fn_manage_motion_blind_canary('close', …)` 로 status=closed(설계 §6.3, row 삭제 아님). slot/submission 은 append-only 라 남되 cohort_kind='canary' 로 격리·미노출.
- canary group: member/camera 매핑 `ended_at` 처리(관리 RPC). 그룹 row 는 보존.
- migration: forward 적용분은 별도 forward down-migration 으로만 되돌린다(이 파일·기존 migration 수정 금지). 신규 테이블은 실데이터 없으면 `DROP` 가능하나 owner 승인 별도.
- Vercel preview: 자동 만료/삭제(production alias 미연결).
