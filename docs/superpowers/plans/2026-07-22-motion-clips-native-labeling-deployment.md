# Motion Clips Native Labeling v3 Deployment Plan

> 실행 대상: `/Users/baek/petcam-lab/.worktrees/motion-clips-labeling-native`
> 구현 정본: `docs/superpowers/specs/2026-07-22-motion-clips-native-labeling-design.md`
> 기본 안전값: `LABELING_QUEUE_SOURCE=legacy`

## 목표

`motion_clips` 네이티브 라벨링 v3를 production DB와 Vercel에 배포하되, 기존 `/labeling`은 계속 legacy 큐를 보여준다. 숨은 `/labeling/motion`에서 owner canary를 통과한 뒤에만 별도 승인으로 기본 큐를 motion으로 전환한다.

## 사용자 체험

- `[라벨 대기 큐]` 기존 사용자는 배포 직후에도 지금과 같은 legacy 큐를 본다.
- `[숨은 v3 화면]` owner가 `/labeling/motion`을 열면 최신 `motion_clips`가 먼저 보이고, 날짜·카메라로 좁힐 수 있다.
- `[영상 선택]` owner가 카드를 누르면 영상과 사람 판정 폼이 열린다. 저장 전까지 VLM·Python evidence는 보이지 않는다.
- `[판정 저장]` owner가 검토한 답을 저장하면 최초 GT가 잠기고, 이후에만 AI 판정 검수 단계가 열린다.
- `[문제 발생]` 기본 `/labeling`은 legacy 그대로라 즉시 사용자 영향이 없다. motion 기본 전환 뒤 문제면 env를 `legacy`로 되돌려 재배포한다.

## 배포 게이트

### Gate A — 소스와 검증 증거

1. feature HEAD가 `origin/main`의 직계 후손인지 확인한다.
2. 독립 리뷰 PASS, Python/Web/tsc/build 결과와 clean tree를 확인한다.
3. handoff validator가 `HANDOFF_OK`가 아니면 중단한다.

### Gate B — main 통합

1. disposable worktree에서 `origin/main`을 feature HEAD로 `--ff-only` 통합한다.
2. force push 없이 `origin/main`에 push한다.
3. local integration HEAD와 `origin/main`이 같은지 확인한다.

### Gate C — production migration

1. `migrations/2026-07-22_motion_clips_native_labeling.sql`만 migration 도구로 적용한다.
2. RLS ON, anon/authenticated 권한 없음, service-role RPC만 허용되는지 확인한다.
3. transaction rollback probe로 다음을 검증하고 잔류 행이 0인지 확인한다.
   - owner/labeler queue 범위
   - 최신순 `(started_at, id)` keyset
   - public limit 99 + DB sentinel 100
   - media 없음 PT422, GT 잠김 PT423, 경합 PT409/PT410
   - initial GT 불변, event/revision append-only
   - labeler camera option이 실제 처리 가능 큐와 동일
4. probe 실패나 예상 밖 row가 남으면 Vercel 배포 전에 중단한다.

### Gate D — Vercel 배포, legacy 기본 유지

1. Vercel production 환경의 `LABELING_QUEUE_SOURCE`를 조회한다. 없거나 `legacy`면 유지한다.
2. main HEAD를 production에 배포한다.
3. `/labeling`이 legacy, `/labeling/legacy`가 legacy, `/labeling/motion`이 v3로 열리는지 확인한다.
4. API health와 인증 경계(owner 전체·labeler label-only·비로그인 차단)를 확인한다.

### Gate E — owner canary

1. 최신순 첫 카드가 DB의 최신 eligible clip과 일치하는지 확인한다.
2. 3개 카메라 옵션과 카메라 필터를 확인한다.
3. 2·3번 카메라의 2026-07-21 16:30~17:30 KST 클립이 날짜 필터에서 조회되는지 확인한다.
4. 영상 signed URL 재생과 실패 재시도를 확인한다.
5. GT 저장은 owner가 영상을 실제 확인하고 정답을 결정한 1건에만 수행한다. 자동 추측 GT는 금지한다.
6. 저장 전 VLM/evidence 은닉, 저장 후 검수 단계 공개, 중복 저장/경합 차단을 확인한다.

### Gate F — 기본 큐 전환 (별도 승인)

Gate A~E 보고 후 owner의 명시 승인 전에는 수행하지 않는다.

1. Vercel production `LABELING_QUEUE_SOURCE=motion` 설정 후 재배포한다.
2. `/labeling`이 motion, `/labeling/legacy`가 legacy인지 확인한다.
3. 오류·빈 큐·권한 이상이면 즉시 `legacy`로 복원하고 재배포한다.

## 중단 조건

- FF-only 불가, handoff 불일치, migration probe 실패, RLS/권한 누출, build 실패
- 최신순/keyset 중복·누락, owner/labeler 범위 위반, VLM blind 위반
- signed URL에서 다른 clip의 `r2_key` 사용, append-only/initial GT 불변 위반
- canary 정답을 사람이 확인하지 못한 상태

## 완료 보고

- main/Vercel SHA와 배포 URL
- migration 적용명과 rollback probe 결과
- `/labeling`·`/labeling/legacy`·`/labeling/motion` 실제 결과
- 최신순·카메라·날짜·영상·GT canary 결과
- Gate F 수행 여부와 rollback 방법
