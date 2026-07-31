# Motion Blind Live v2 Highlight-Soft 구현 보고

## 판정

`DEPLOYED_VERIFIED_ACTIVATION_PENDING_FIRST_LIVE_SLOT`

- execution repo: `/Users/baek-end/petcam-lab-live-comparator-v2`
- branch: `codex/live-comparator-v2-highlight-soft`
- starting SHA: `c9e029e9db199015e7ca357b2b9ba98f65da839b`
- implementation SHA before this docs commit: `dbe0ad3c2a5395c7f53a4e7005acb8d33ae53e1e`
- migration SHA-256: `f652136474ff7ec7a7d462dc80c4452379b52154e2ee298818e5e8e0c8eb9030`
- deployed source SHA: `6d127b662541b3de87284ba63399c631b3633a3f`
- production migration applied: `2026-07-31 13:00 KST`
- Vercel production: `Ready`, `label.tera-ai.uk`, exact Git main commit `6d127b6`
- production R2/media mutation: `0`

## 구현

1. `motionBlindReviewV2.ts`가 v1 결과를 그대로 위임하고 highlight-only conflict만
   `agreed` + final highlight `uncertain`으로 병합한다.
2. slot INSERT가 comparator version을 snapshot한다. 기존/canary/formal은 v1,
   `2026-08-01` 이후 새 live slot만 v2다.
3. DB consensus guard가 exact 2 slots, uniform version, consensus-version 일치,
   canary-v1, activation boundary를 검증한다.
4. Web은 같은 scope의 두 slot에서 검증한 version만 상세·comparator·finalize에 사용한다.
   request body의 version은 허용하지 않는다.
5. session draft key/envelope는 상세 응답의 comparator version으로 v1/v2를 격리한다.

## RED → GREEN

- comparator module missing RED → v1/v2/wheel/segment 31 PASS
- migration missing RED 5 FAIL → static 6 PASS
- access/detail/submit version RED 6 FAIL → focused server wiring 60 PASS
- global v1 draft source RED → draft/UI/hardening 37 PASS
- 전체 suite에서 media URL fixture 4 FAIL → 2-slot/version fixture 보강 후 6 PASS

## 최종 검증

- focused Web: `8 files / 112 tests PASS`
- full Web: `89 files / 884 tests PASS`
- focused migration/formal: `17 PASS`
- Mac mini Python: `939 PASS / 5 SKIP / 1 DESELECT`
  - deselect는 해당 host에 없는 `/Users/baek/petcam-nightly-reporter` 절대경로 probe다.
- root 재검증 Python: `940 PASS / 5 SKIP`
- TypeScript: `npx tsc --noEmit` PASS
- role UI audit: PASS
- disposable PostgreSQL:
  `MOTION_BLIND_LIVE_V2_HIGHLIGHT_SOFT_PROBE_OK`, `PROBE_RESIDUE=0`
- `git diff --check`: PASS

## 불변·보안 감사

- `motion-blind-v1`의 비교 로직 변경 0. 공개 결과 타입만 version generic으로 넓혔다.
- Blind30 TEST-SHEET와 formal v1/v2 migration 변경 0.
- 상대 submission 원문, digest, reviewer UUID, R2 key 응답 노출 0.
- comparator request-body 신뢰 0. unknown/mixed/canary-v2는 fail-closed다.
- 기존 slot/submission/consensus/event rewrite/delete 0.
- npm audit 기존 high 2건은 범위 밖이며 `npm audit fix --force`를 실행하지 않았다.

## Task 6 운영 반영

1. `origin/main`을 `6d127b6`으로 비강제 fast-forward했다.
2. production baseline 후 tracked migration을 정확히 한 번 적용했다.
3. 기존 원장 불변을 count+hash로 확인했다.
   - slots `38,010`, legacy hash 불변
   - submissions `369`, consensus `19,005`, events `217`, 각 hash 불변
4. 신규 구조와 권한을 확인했다.
   - slot v1 `38,010`, v2 `0`
   - mixed slot pair `0`, canary v2 `0`, pre-boundary v2 `0`
   - comparator check·3 triggers 존재
   - trigger functions의 `anon`/`authenticated` EXECUTE `false`
   - finalizer의 `service_role` EXECUTE `true`
5. Git-integrated Vercel production이 exact main commit `6d127b6`을 빌드해
   `label.tera-ai.uk` alias로 `Ready`가 됐고 로그인 화면 read-only smoke를 통과했다.

`2026-08-01` activity-day 전이라 실제 v2 slot은 아직 `0`이다. 첫 신규 live slot이 생기면
`comparator_version=motion-blind-live-v2-highlight-soft`, canary v1, mixed pair 0을 다시
읽기 전용으로 확인한 뒤 `DEPLOYED_VERIFIED`로 승격한다.
