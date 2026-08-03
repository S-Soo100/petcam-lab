# Gecko Motion Engine production shadow 전환 보고

> 상태: `CUTOVER_ACTIVE / BACKFILL_PROCESSING / ACCURACY_UNVERIFIED`
> 실행 시각: 2026-08-04 KST
> 사용자 노출: 없음

## 1. 전환 결과

- `2026-08-03_gecko_motion_engine_shadow.sql`을 production DB에 적용했다.
- 실제 R2 영상 10개 operational smoke가 `10/10 succeeded`, 고유 clip `10/10`, GME artifact
  `20/20`으로 통과했다.
- 같은 10개를 재enqueue했을 때 신규 job `0`, worker 재계산 `0`으로 멱등성을 확인했다.
- 기존 Python Evidence 처리 중 job `0`을 확인한 뒤 direct-cutover migration을 적용했다.
- `motion_clips` live trigger는 `trg_enqueue_gme_live_job` 1개이고 Python Evidence 신규 enqueue
  trigger는 0개다.
- 전환 후 자연 촬영 clip으로 GME live job 2개가 생성됐고 기존 Python Evidence job overlap은 0이었다.
  확인 시점에 1개는 succeeded, 1개는 다음 one-shot 대기였다.
- Mac mini `com.petcam.gme-worker`는 60초 one-shot으로 활성화했고
  `com.petcam.python-evidence-worker`는 plist·코드·DB 이력을 보존한 채 bootout했다.
- KST 2026-07-15 이후 eligible 영상은 500-row keyset page별 R2 HEAD preflight 후 bounded RPC로
  enqueue했다. live queue는 historical보다 항상 우선한다.
- 전수 enqueue 결과는 DB 날짜 후보 10,787건 중 최종 eligible identity 9,752건이다. 신규 historical
  job은 9,740건이며, 차이 12건은 이미 존재한 smoke 10+live 2 identity라 중복 생성하지 않았다.
- worker는 60초 one-shot, batch 10으로 실행 중이다. 완료·이상 조건은 현재 Codex 작업의 시간별
  `GME backfill completion monitor`가 read-only로 확인한다.

## 2. 재현 버전

| 저장소 | production main SHA |
|---|---|
| `gecko-vision-gate` | `c0f0c6d2e5bbded98504052a53ff3c0ce23f32a7` |
| `petcam-nightly-reporter` | `eba234e40513590a6d4a237c0d5d4e8e8018c383` |
| `petcam-lab` | `385b6f1f24834e5047f741b88057a16a730b5fea` |

Mac mini hostname은 `baeg-endeuui-Macmini.local`이고 세 저장소 HEAD를 위 SHA로 ff-only 동기화했다.
Gate checkpoint SHA-256은 승인된 `cd1162b4...bef17`과 일치했다.

## 3. 검증

- MacBook 전체 회귀: Gate `107 passed`, nightly `478 passed`, lab `1233 passed, 5 skipped`.
- backfill keyset/bounded enqueue 보강 뒤 nightly: `481 passed`.
- one-shot batch를 10으로 명시 배포하도록 보강한 뒤 nightly: `482 passed`.
- Mac mini 대상 회귀: Gate GME `20 passed`, nightly GME 운영 도구 `23 passed`.
- Claude 코드·SQL 교차검수에서 만료 lease의 max-attempt 우회, exposure 전환 frame 오염, 시간 합계
  불변식, stale claim owner 정리 문제를 지적받았고 회귀 테스트와 로컬 PG15 probe로 수정했다.

## 4. smoke 관측치 — 정확도 성적이 아님

10개 smoke에서 candidate moving seconds의 `min/median/max`는 `0.00/0.00/0.96`, unknown seconds는
`4.20/28.62/32.52`, 동시 검출 최대 게코 수는 1이었다. 두 종류 gzip artifact 총량은 53,527 bytes였다.
이 값은 pipeline이 끝까지 실행되고 unknown을 0으로 숨기지 않았다는 운영 증거일 뿐, 활동시간 정확도나
사용자 효용 통과를 뜻하지 않는다.

## 5. 남은 운영 항목

- R2 S3 key는 object read/write는 가능하지만 bucket lifecycle 변경은 `AccessDenied`였다. 따라서
  `terra-derived/gme/v1/debug-14d/` 14일 만료 규칙은 Cloudflare dashboard 로그인 후 별도 적용해야 한다.
  원본·permanent prefix에는 lifecycle을 적용하지 않는다.
- 첫 자연 신규 clip의 trigger 분리는 통과했다. 이후에도 live coverage와 lag를 계속 확인한다.
- enqueue 직후 snapshot은 smoke succeeded 10, live succeeded 2, historical succeeded 42 /
  processing 7 / queued 9,691 / retryable 0 / terminal 0, live lag 0초다. 실제 전수 분석은 계속 진행 중이다.
- 사람 time-interval+bbox/mask GT와 독립 future holdout 전에는 candidate moving time을 Flutter,
  `activity-v1`, 행동 GT, VLM route, 자동 skip, 삭제 근거로 사용하지 않는다.
