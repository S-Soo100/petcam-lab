# Canonical GT Production Rollout Report — 2026-08-04

## 판정

`DEPLOYED_VERIFIED`. 기존 교차검수와 Owner direct source를 바꾸지 않는 append-only canonical GT 원장을 Production에 적용하고 Owner·영상 보관함·대시보드·export consumer를 단계별 전환했다.

## 코드·배포

- deployed code commit: `91d738ee8bb5444cef9292a10d905d7bfaed5b7d`
- branch/upstream: `codex/labeling-gt-canonical-plan` / `origin/codex/labeling-gt-canonical-plan`
- final Production deployment: `dpl_5TfgfmA9XWfhsWgbQFGMQibEfMfT`
- deployment URL: `https://petcam-husfsvo3f-ssoo100s-projects.vercel.app`
- Production alias: `https://label.tera-ai.uk`
- build: Vercel Next.js compile·lint·type check 완료, deployment `Ready`

## Production migration

| 파일 | SHA-256 |
|------|---------|
| `2026-08-04_motion_clip_canonical_gt_ledger.sql` | `ac1cd8da7b8d9ccd330eb176ac6572d92900f4361c24f1ca9e9c1d4bc494ddc6` |
| `2026-08-04_motion_clip_canonical_gt_audit_digest_scope.sql` | `1ae933b56ed853bf698e4fa45febf0f40919dd7d80c078956795060f02ce0b37` |
| `2026-08-04_motion_clip_canonical_gt_scheduler.sql` | `e8c7edf5d41883c03de3f91dd0932be71b6df3372d85e67a81bb27cfabc4ea59` |
| `2026-08-04_motion_clip_canonical_gt_consumers.sql` | `a9ca0bb392247444987b88a1cbd1736041a32bdeb023d4a5a1e990ce4562b79f` |

## 최종 flag

- `LABELING_CANONICAL_GT_OWNER_READ_ENABLED=true`
- `LABELING_CANONICAL_GT_OWNER_WRITE_ENABLED=true`
- `LABELING_CANONICAL_GT_LIBRARY_READ_ENABLED=true`
- `LABELING_CANONICAL_GT_DASHBOARD_READ_ENABLED=true`
- `LABELING_CANONICAL_GT_PROJECTION_ENABLED`: Production 미설정, 코드 기본 `false`
- DB `motion_clip_gt_projection_config.enabled=true`
- pg_cron `canonical-motion-gt-projector-v1`: 10분 간격

## 데이터 불변·parity

- source: `live_final=277`, `direct_completed=216`
- source mutation digest: `a6a3be72157110ca04a7b5e0378b5b64e52088b5e6d01e31723fe2140ea2321a` (pre/post 동일)
- canonical: `heads=493`, `revisions=493`
- canonical/export head digest: `8e3d21100d7a2e3249a039f5e3bfd55cd66c7565293c6ebbf1433acbdb552677`
- dashboard revision count/digest: `493` / export와 동일
- dashboard 행동 GT: `486`
- orphan head `0`, overlap `0`, projection parity mismatch `0`, reconciliation pending `0`
- direct/library/dashboard/export parity mismatch `0`
- excluded open canary `42`

## 교차검수 영향 관측

- scheduler 즉시 실행: `succeeded`, scanned/inserted/conflicts `0/0/0`
- 자연 cron 실행: `2026-08-04T08:50:00.456824+00:00`, health `healthy`, pending final source `0`
- live awaiting/conflict: `20966/20 → 20963/23`; 진행 중 작업 3건이 conflict로 이동했고 final source count는 `277`로 불변
- blind source digest 불변, 기존 B그룹 작업 화면 로드와 역할 차단 정상
- Owner 보정 canary는 버튼·권한 노출만 확인했고 실제 GT write는 `0`

## 역할·화면 canary

- Preview: owner read → owner write → library → dashboard 순서로 각각 별도 deployment `Ready`
- Production owner: canonical 합의 GT와 provenance 표시, write-off일 때 보정 버튼 비노출, write-on 뒤 owner에게만 노출
- Production library: final은 `최종 라벨 / label / moving`, awaiting·conflict는 `라벨 확정 중`이며 GT 비노출
- Production dashboard: 영상 `21,681`, 재생 가능 `19,257`, GT `486`; 행동 분포 합계와 DB canonical RPC 일치
- labeler가 Owner detail URL로 접근하면 라벨러 홈으로 차단됨

## 검증

- Python: `1204 passed, 5 skipped`
- Web: `970 passed`
- TypeScript: `npx tsc --noEmit` exit `0`
- local `npm run build`: project safety hook으로 실행 금지; 같은 commit의 Preview·Production Vercel build가 compile/lint/type check 후 `Ready`
- disposable PostgreSQL consumer probe: `CANONICAL_GT_CONSUMERS_PROBE_OK`
- 독립 코드 리뷰: Critical `0`, Important `0`

## Rollback

문제가 생기면 영향 consumer flag를 역순으로 `false`로 내리고 재배포한다. projection 이상이면 먼저 `fn_configure_motion_clip_gt_projection(owner_id, false)`로 scheduler를 멈춘다. canonical revision/head는 감사 원장이므로 삭제하지 않으며 기존 blind/direct source가 즉시 fallback 정본이다. migration·projection rollback probe와 flag-off route 회귀 테스트를 통과했다.
