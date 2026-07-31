# RBA Data Engine Formal Blind30 v2 Implementation Plan

**Goal:** invalid v1을 보존·종료하고 실제 R2 object가 두 번 검증된 미래 표본 exact 30만 v2로
원자 예약한다.

**Architecture:** metadata selector와 threshold는 그대로 두고 R2 media preflight를 별도
순수 판정 단위로 추가한다. 새 service-role-only v2 RPC는 v1 원자성에 future-pool guard와
새 label namespace만 더한다.

## Task 1: v1 invalidation 고정

- [x] production submission 0을 다시 확인한다.
- [x] `fn_manage_motion_blind_canary('close', ...)`를 정확히 1회 호출한다.
- [x] closed cohort 1, slots 60, submissions 0, awaiting consensus 30을 확인한다.
- [x] 기존 lease는 수정하지 않고 자연 만료시킨다.
- [ ] reviewer API가 closed cohort를 `410 cohort_closed`로 반환하는 회귀 경계를 확인한다.

## Task 2: 설계와 실행 계약 선커밋

- [ ] v1을 `INVALID_SAMPLE_AFTER_FREEZE`로 SOT와 보고서에 기록한다.
- [ ] v2 TEST-SHEET와 이 design/plan을 결과 전에 동결한다.
- [ ] threshold, selector ordering, comparator diff 0을 확인한다.
- [ ] docs-only commit을 feature/main에 non-force 반영한다.

## Task 3: R2 media preflight TDD

- [ ] RED: exact 30의 HEAD 200/nonzero/ETag만 통과한다.
- [ ] RED: 404, 403, timeout, zero-size, ETag 누락은 batch 전체 실패다.
- [ ] RED: 실패 clip 교체나 partial attestation이 없다.
- [ ] RED: manifest에 key/credential/raw ETag가 없고 salted digest/fingerprint만 있다.
- [ ] RED: 1차/2차 clip set 또는 digest가 다르면 RPC gate가 닫힌다.
- [ ] GREEN: 최소 구현 후 focused tests를 통과한다.

## Task 4: v2 forward RPC TDD

- [ ] RED: v2 함수/label/unique index/service-role-only/future-pool 계약을 고정한다.
- [ ] RED: 29/31/duplicate, old-pool clip, unqualified reviewer, history/race가 전부 rollback한다.
- [ ] GREEN: `fn_create_motion_blind_formal30_v2` migration과 disposable SQL probe를 구현한다.
- [ ] v1 migration/RPC/label/rows/manifest가 불변인지 회귀 검증한다.

## Task 5: 통합 검증과 배포

- [ ] focused Python/SQL tests, full relevant Python/web/TypeScript/UI audit를 실행한다.
- [ ] diff/security/독립 review를 수행하고 범위 내 finding만 TDD로 고친다.
- [ ] feature를 non-force push하고 fast-forward 가능한 경우에만 main에 통합한다.
- [ ] tracked handoff manifest를 만들고 `HANDOFF_OK`를 확인한다.
- [ ] production forward migration을 한 번 적용한다.
- [ ] function/privilege/guard/index와 `b30v2` zero-state를 read-only 확인한다.

## Task 6: v2 freeze와 예약

- [ ] reviewer 자격과 production v2 zero-state를 직전 재확인한다.
- [ ] 새 T0로 v1 T0 이후 future pool에서 metadata-only exact 30을 선택한다.
- [ ] R2 preflight 1을 30/30 통과한 뒤 manifest mode `0600`을 쓴다.
- [ ] R2 preflight 2를 30/30 통과하고 salted digest 동일성을 확인한다.
- [ ] v2 RPC를 정확히 1회 호출한다. 실패하면 재호출하지 않는다.
- [ ] cohort 1, slots 60(30/30), awaiting 30, submissions 0과 live 범위 밖 무변이를 확인한다.
- [ ] reviewer API의 첫 항목과 소수 spot-check가 재생 가능한지 확인한다.
- [ ] URL 하나만 owner에게 전달하고 human submission 전에 멈춘다.

## 검증 명령

```bash
uv run pytest tests/test_prepare_rba_blind30.py \
  tests/test_motion_blind_formal30_v2_migration.py \
  tests/test_motion_blind_formal30_v2_runtime_probe.py -q
uv run python scripts/run_motion_blind_formal30_v2_probe.py --backend local-postgres
uv run pytest -x -q
cd web && npm test
cd web && npm run audit:labeling-role-ui
cd web && npx tsc --noEmit
git diff --check
```

## Stop 조건

- R2 preflight가 한 건이라도 실패하거나 두 batch digest가 다름
- production `b30v2` row가 예약 전에 0이 아님
- reviewer 자격, DB privilege, guard/index, exact SHA/clean handoff가 불일치
- create RPC가 실패함

Stop 뒤 threshold 완화, clip 교체, 두 번째 RPC, 기존 row 수정은 하지 않는다.
