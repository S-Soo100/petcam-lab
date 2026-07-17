# Python Evidence Universal Worker — S2B 배포 보고서

> **작성:** 2026-07-17 · Claude Opus 4.8 (1M context)
> **선행:** hardening-report (DEPLOY_APPROVED_WITH_RUNTIME_GATES)
> **실행 host:** `BaekBook-Pro-14-M5.local` (구현 laptop) · **runtime host:** `baeg-endeuui-Macmini.local` (Mac mini, 별도·미접근)
> **Supabase project:** `slxjvzzfisxqwnghvrit` (production)

## 0. Verdict

```
UNIVERSAL_EVIDENCE_DEPLOYMENT_BLOCKED
```

**DB shadow 계층(steps 1~4)은 production 에 완전 배포·검증 완료.** worker 계층(steps 5~7)은 이 세션이
Mac mini runtime host 가 아니라 **실행 불가**(worker expected-host fail-closed 가 Mac mini 전용, laptop 에서
우회 실행하면 잘못된 host 로 production job 을 처리하게 됨). shadow **worker** 미배포·미검증이라
`SHADOW_DEPLOYED_VERIFIED` 를 선언할 수 없다. Mac mini 세션이 runtime handoff manifest 로 steps 5~7 을 완료해야 한다.

## 1. Step 1 — migration 적용 전 read-only 확인 ✅

- **table grant**: `service_role` INSERT ✓. `anon`/`authenticated` 도 table-level INSERT grant 보유(잔존).
- **RLS**: `motion_clips` RLS **enabled**, INSERT/ALL policy **0개**(SELECT·DELETE policy 만, `auth.uid()=owner_id`).
- **role 속성**: `anon`/`authenticated` `rolbypassrls=false` → RLS default-deny 로 INSERT **불가**. `service_role`/`postgres` `rolbypassrls=true` → INSERT 가능.
- **결론**: effective INSERT = **service_role(앱)·postgres(admin) 만**. capture 작동 중 = service_role 사용. **producer=service_role 확정** → SECURITY INVOKER enqueue trigger 가 service_role(=`python_evidence_jobs` INSERT 권한 보유)로 실행 → **capture 안 깨짐**.
- 잔존 관찰(비차단): anon/authenticated table-level INSERT grant 는 RLS 로 무력화. 향후 INSERT policy 추가 시 위험 재활성 → S3 revoke 권고.

## 2. Step 2 — 세 레포 main 통합 (FF-only) ✅

| 레포 | 이전 main | 새 main (= feature tip) |
|---|---|---|
| gecko-vision-gate | f182ea4b | **9ea55eb740e9c87dd240b9282d612772dbc798f3** |
| petcam-nightly-reporter | 19a1fe56 | **618f4f854254525b0ebc6f0fcf9153f8e0cd6bc1** |
| petcam-lab | 7418bbb | **33964ff41a82c2b3275d7021167986a2833291d3** |

FF-only(force/rewrite 없음). 요청 3개 SHA 전부 각 main 포함.

## 3. Step 3 — production migration + rollback probe ✅

- `2026-07-17_python_evidence_universal_worker.sql` **apply 성공**(~14:05 UTC). 2 table + 5 함수 + 4 trigger 생성.
- **H3/H4 rollback probe 10/10 PASS** (단일 트랜잭션, raise 로 전량 rollback, 잔류 0):
  enqueue-trigger · valid-run · cross-clip-run(22023) · cross-job-complete(22023) · wrong-prelabel(22023) ·
  malformed-JSON(22023) · claim-limit-0(22023) · claim-blank-host(22023) · append-only-UPDATE(0A000) · append-only-DELETE(0A000).
- **RLS/grant/advisor**: 두 테이블 RLS enabled·client policy 0·grant service_role only. advisor 에 내 함수 `function_search_path_mutable` WARN 없음(전부 `search_path=''`), 신규 WARN/ERROR 0. `rls_enabled_no_policy` INFO 는 설계 의도(service_role 전용).

## 4. Step 4 — 자연 신규 clip trigger 검증 ✅

migration 이후 실제 카메라 신규 motion_clip 2건이 live job 자동 생성:

| clip_id | created_at(UTC) | job |
|---|---|---|
| b0052819-… | 14:11:15 | live / priority 100 / queued |
| 11dd3233-… | 14:12:25 | live / priority 100 / queued |

- post-trigger 신규 clip **coverage 100%** (`clips_missing_job=0`, **2/2**). capture 정상(insert 오류 0, gap 은 motion 정적 구간).
- 현재 production: `python_evidence_jobs`=2(live/queued), `clip_python_evidence_runs`=0. worker 미배포라 job 안전 누적(설계 §160).

## 5. Steps 5~7 — BLOCKED (Mac mini runtime host 필요) ⛔

- 이 세션은 laptop(`BaekBook-Pro-14-M5.local`), Mac mini(`baeg-endeuui-Macmini.local`, 사용자 `baek-end`)는 별개 머신(`/Users/baek-end/` 이 laptop 에 없음)이라 shell 접근 불가.
- worker canary(step 5)·LaunchAgent(step 6)·역사 dry-run(step 7)은 Mac mini 에서 실행해야 하며, worker 의 `PYTHON_EVIDENCE_EXPECTED_HOST` fail-closed 가 Mac mini 전용. laptop 우회 실행은 잘못된 host 로 production job 처리 → 하지 않음.
- 실행 절차는 runtime handoff manifest(`2026-07-17-python-evidence-universal-worker-runtime-handoff.md`) §runbook 참조.

## 6. 검증 게이트(요청) 현재 상태

- **secret·원본영상·raw 오류 노출 0**: DB 배포 전 과정 미노출, probe 는 합성 데이터.
- **selector/VLM/app/GT/activity 결과 변경 0**: migration 은 신규 테이블/트리거/RPC 만 추가, 기존 불변. worker 미실행이라 clip_prelabels/run write 0.
- **feature-disabled 시 DB 접근 0**: worker 미배포, flag 기본 false.
- **main merge**: 세 main FF 통합 완료.

## 7. 현재 production 상태 / 안전장치

- 배포됨: 2 테이블 + 5 RPC + enqueue trigger + append-only blocker. 신규 clip 마다 live job 안전 누적.
- 미배포: worker(Mac mini). job queued 누적·소비 0 = 정상 S2B 중간 상태. worker 배포 시 live 우선 backlog drain.
- kill-switch(필요 시): `drop trigger trg_enqueue_python_evidence_job on public.motion_clips;` (capture 무영향). 배포 의도상 armed 유지 권장.

## 8. 다음 액션

1. Mac mini 세션에서 runtime handoff manifest 로 verify → HANDOFF_OK → steps 5~7 실행 → 완료 시 `UNIVERSAL_EVIDENCE_SHADOW_DEPLOYED_VERIFIED`.
2. (S3) motion_clips anon/authenticated table-level INSERT grant revoke 검토(RLS 로 무력화됐으나 latent).
