# 이중 블라인드 라벨링 — Preview 배포 + 12클립 canary 준비 보고서 (2026-07-24)

> 선행: `2026-07-24-double-blind-labeling-hardening-report.md`(P1 3건 닫힘, 세 마커 재확보). 계획: `docs/superpowers/plans/2026-07-24-double-blind-labeling-preview-canary.md`.
> 마스킹 정책: 전체 UUID·이메일·비밀값 미기재(UUID는 8자 prefix, reviewer는 라벨/역할로 지칭).

## 1. HANDOFF_OK 전문
```
HANDOFF_OK task=double-blind-labeling-preview-canary repo=double-blind-labeling-groups-design commit=2dfcaeda runtime=oneshot@slxjvzzfisxqwnghvrit
```
- validator: `uv run python scripts/verify_agent_handoff.py --manifest .../storage/handoffs/2026-07-24-double-blind-labeling-preview-canary-handoff.md`
- runtime target = production Supabase project `slxjvzzfisxqwnghvrit`(MCP `get_project_url` 로 확인, `.env.example`·docs 기대값 일치).

## 2. Branch·commit·preview·build
- branch: `codex/double-blind-labeling-hardening`, HEAD = `2dfcaeda`(plan/manifest 커밋 후, local==origin, clean).
- Vercel preview: `dpl_AGBsRynzcekVCQo2khuVB8aeZrn8` = **READY**(GitHub commit status `Vercel=success` on 2dfcaeda). 실제 `next build` 성공 = build 증거(로컬 `npm run build`는 dangerous-guard/donts#9 차단이라 **UNVERIFIED**, tsc 로 대체 안 함).
- **사람 접속 preview URL: `https://petcam-py7zs6b20-ssoo100s-projects.vercel.app`** (Vercel Deployment Protection 적용 — owner 의 Vercel 접근으로 진입).

## 3. Migration — 이름·적용·검증
- migration entry: `motion_double_blind_labeling`(MCP `apply_migration`, atomic). 파일 `BEGIN;`/`COMMIT;` 제거 후 DDL 전달(Supabase 자체 tx 래핑). 적용 전 `list_migrations` 로 미적용 확인.
- **적용 후 검증(전부 PASS):**
  - 신규 테이블 9 + RPC 12(EXECUTE) + trigger 함수 2 = 14 함수 존재.
  - RLS enabled 9/9, **client policy 0**, anon/authenticated 테이블 권한 0, service_role 전용.
  - append-only trigger 6(submissions·events UPDATE/DELETE/TRUNCATE + cohort DELETE/TRUNCATE).
  - 14 함수 전부 `SECURITY INVOKER` + `search_path=""`; anon/auth EXECUTE 0, service_role EXECUTE 12.
  - **함수 body 무결성: 14/14 정규화 md5 가 tracked 파일과 byte-identical**(disposable DB 에서 15 assertion+동시성 통과한 코드와 동일 → 전이적 정확성).
  - advisor(security): **신규 critical/error/WARN 0**. 신규 9 테이블은 `rls_enabled_no_policy` **INFO**(설계대로 RLS+정책0+service_role전용=default deny, 기존 service_role 테이블 전부 동일). 내 14 함수는 `function_search_path_mutable` 에 없음.
  - production rollback probe: 입력검증 rejection(canary/finalize/group/submit) 전부 예상 SQLSTATE, `blind_residue=0`.

## 4. Pre/Post fingerprint — 금지 테이블 mutation 0
- 사람/큐레이션 테이블 13개 full-row md5 지문을 migration **전/후** 비교 → **전부 byte-identical**:
  behavior_labels(258,cb7cf7f8) · motion_clip_labeling_sessions(153,d3b1971c) · motion_clip_labeling_triage(291,1ed5a7c8) · motion_clip_labeling_triage_events(347,080f1b0c) · motion_clip_labeling_session_revisions(0,d41d8cd9) · clip_labeling_sessions(42,bb8f7d48) · clip_labeling_session_revisions(2,62e52d02) · clip_labeling_triage(0)·triage_events(0) · router_review_labels(147,3d0680c3) · labelers(4,0eade279) · labeler_applications(4,817346a7) · cameras(4,7d8adc69).
- 결론: migration 은 기존 GT/label/triage/session/behavior 테이블을 **하나도 수정하지 않음**. (behavior_logs/motion_clips/clip_activity_assessments 등은 백그라운드 워커가 상시 쓰는 noisy 테이블이라 count 만 참고 — 내 작업 경로는 이 테이블들에 write 하지 않음.)

## 5. Canary group/cohort 상태 + clip 12
- 전용 그룹 `blind-canary-preview-20260724`(id `c209a3f0…`): active member **2**, **active camera 0**(생성 시 `P4 Cam 4`(0 clips) 부여 후 매핑 종료 → live materialization 불가).
- canary cohort(label 동일, id `81594001…`): kind=canary, status=**open**.
- canary slot **24** = clip **12** × reviewer **2**. canary consensus **12 = awaiting**. **submission 0**. **그룹 live slot 0**.
- clip 12: `P4 Cam (dev)` 의 최근 fresh(기존 GT/session/label/slot 없음)·재생가능(r2_key) 영상. 시간대 분산(07-14~07-22, 아침/낮/저녁/밤). 전부 media_ready.
- ⚠️ 카메라 해석: 계약의 "P4 Cam" 은 4개 후보(`P4 Cam (dev)`/`P4 Cam 2(dev)`/`P4 Cam 3`/`P4 Cam 4`) 중 **literal 매칭 + 주 카메라(14,331 clips)**인 `P4 Cam (dev)` 로 선택. 다른 카메라를 원했다면 canary close 후 재생성으로 가역(§9).

## 6. reviewer 각 12 배정 증거
- reviewer resolve(read-only, 각 정확히 1): reviewer#1 display_name `크랑이아빠`(uid `d5e66448…`, owner 2nd 계정) · reviewer#2 email-resolved labeler(uid `dad1a07e…`). 0명/2명 이상 없음.
- slot 분포 per_reviewer = **12/12**(각 reviewer 정확히 12). 동일 12 clip 이 두 reviewer 에게 배정(distinct_clips=12, distinct_reviewers=2, slots=24).
- 두 reviewer 의 canary 큐(`fn_list_motion_blind_queue(uid, NULL,'canary',cohort)`) 각각 **12행**, 전부 media_ready, 전부 P4 Cam (dev), lease 0.

## 7. Blind leakage 검사
- `fn_list_motion_blind_queue` 의 RETURNS TABLE = {clip_id, camera_id, camera_name, started_at, duration_sec, media_ready, activity_day_kst, lease_expires_at} — **peer decision/GT/note/digest·상대 제출상태·UUID(auth)·lease token·evidence·VLM 없음**(구조적 blind).
- API 계층(`mapBlindQueueRow`/detail allowlist)은 web 테스트 + `_blind-hardening.test.ts` 정적 회귀로 상대원문 0 보장(코드 불변).
- 나는 두 reviewer 로 로그인 불가 → **DB/RPC 응답 구조로 blind 검증**(사람 브라우저 로그인은 Stop Point 이후 owner/reviewer 몫).

## 8. 사람 접속 URL + 검수 순서
1. preview `https://petcam-py7zs6b20-ssoo100s-projects.vercel.app` 접속(Vercel 보호 → owner Vercel 접근 필요).
2. 두 reviewer(`크랑이아빠`, email-resolved labeler)가 **각자** 라벨러 계정으로 로그인.
3. canary 진입: owner canary 화면에서 cohort `blind-canary-preview-20260724` 열기(또는 경로 `/labeling/blind/canary/<cohortId>`; 전체 cohortId 는 owner canary UI 또는 `SELECT id FROM public.motion_blind_review_cohorts WHERE label='blind-canary-preview-20260724'` 로 취득 — 본 보고서엔 prefix `81594001…` 만).
4. 각 reviewer 가 **상대 답을 못 본 채** 12개를 각각 한 번씩 판정·제출.
5. 두 사람이 12개를 모두 제출하면 서버가 자동 비교 → 일치=자동합의, 불일치만 owner 검수 대기.
6. owner 는 canary 상태(현재 12 awaiting, agreed/conflict 0 = 정상)를 확인.

## 9. Canary 제거 / rollback 절차
- cohort 종료: `SELECT public.fn_manage_motion_blind_canary('close', <owner_uid>, <cohort_id>, NULL, NULL, NULL, NULL);` → status=closed(row 삭제 아님, 설계 §6.3). closed canary slot/submission 은 append-only 로 보존되나 cohort_kind='canary' 로 격리·live 큐 미노출.
- 그룹: 이미 active camera 0. 필요 시 member `ended_at` 처리(관리 RPC). 그룹 row 는 보존.
- 완전 제거(테이블 DROP)는 별도 forward down-migration(owner 승인). 신규 테이블은 실데이터 없으면 DROP 가능.
- migration 자체 rollback: 기존 migration 파일 수정 없이 forward down-migration 으로만.
- Vercel preview: production alias 미연결 — 방치 시 자동 만료.

## 10. 미검증 항목
- **preview env → production Supabase 연결**: 미확인(Vercel 보호로 앱 미도달 + preview env 읽기 불가). preview 가 production Supabase(slxjvzz)를 가리켜야 canary 가 보인다. owner 가 preview 진입 시 canary 표시로 확인 필요. (blind 라우트는 이 branch 에만 존재 — production main 엔 없음.)
- **`npm run build`(로컬)**: dangerous-guard 차단 → UNVERIFIED. Vercel preview 의 실 `next build` 성공이 대체 증거이나 로컬 재현은 owner 터미널.
- **사람 브라우저 워크스루**: reviewer 계정 로그인 불가로 미실행(설계상 Stop Point). blind·큐·제출 흐름은 DB/RPC + web 테스트로 검증.

## 11. 미실행 확인 (금지 준수)
- main merge **안 함** · Vercel production 배포 **안 함** · production env(`LABELING_QUEUE_SOURCE` 등) 변경 **안 함**.
- live cohort/group/camera assignment **안 함**(canary 그룹 active camera 0, cohort_kind='canary' 전용).
- 기존 label/GT/triage/behavior/activity 수정 **안 함**(13 지문 byte-identical).
- 기존 151건 재사용/Owner Pilot 151 manifest 생성 **안 함**.
- 사람 대신 submission/GT DB 직접 생성 **안 함**(submission 0).
- 상대 라벨/evidence/VLM 노출 **안 함**(구조적 blind).
- force push·기존 migration 파일 수정 **안 함**.
- OrbStack/Docker 미조작.

## 최종 판정
```
DOUBLE_BLIND_LABELING_CANARY_READY_FOR_HUMAN_REVIEW
```
migration·preview·canary 준비 완료. **사람 제출 전이므로 DEPLOYED/PRODUCTION_READY 를 주장하지 않는다.** 다음 = 두 reviewer 가 preview 에서 12개씩 blind 제출 → 자동합의/불일치 → owner 검수 → 수용 시에만 main/production 통합 검토(별도 승인).
