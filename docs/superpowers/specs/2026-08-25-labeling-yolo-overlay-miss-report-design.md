# 라벨링 YOLO/GME 오버레이·미탐 제보 설계

> 상태: `IMPLEMENTED_LOCAL_VERIFIED / CLAUDE_CROSS_REVIEW_APPROVED / PRODUCTION_NOT_DEPLOYED`
>
> 승인일: 2026-08-25 KST

## 1. 결정

현재 이중 블라인드 라벨링 영상에 frozen GME v2.5 영구 artifact의 bbox trajectory를
`YOLO/GME 추적` 오버레이로 표시한다. 라벨러는 박스가 없거나 게코 일부를 놓친 현재 영상 시점에서
`YOLO가 게코를 놓쳤어` 버튼을 누른다. 제보는 사람 행동 GT와 분리된 append-only 오류 원장에
저장하고, 이후 Owner bbox 보정·hard-case 채굴 입력으로 사용한다.

GME negative audit 화면의 `게코 있음 + 대표 시점 + bbox` 계약은 그대로 둔다. 이 변경은 신규
live/canary 이중 블라인드 라벨링 상세 화면에만 적용한다. Flutter 앱과 GME 모델은 변경하지 않는다.

## 2. 사용자 체험

- **[화면]** 영상 위에 현재 시점의 YOLO 관측·GME 추적 bbox가 표시된다.
- **[조작]** 라벨러가 박스 밖 게코 또는 박스가 없는 게코를 발견하면 미탐 버튼을 누른다.
- **[반응]** 현재 시점이 1ms 단위로 저장되고 `미탐 시점을 저장했어`라는 확인이 나온다. 같은
  영상의 다른 시점은 다시 누를 수 있다.
- **[감정]** 라벨러는 행동 라벨링을 중단하지 않고 모델 오류도 빠르게 남길 수 있다.

화면에는 `박스가 없어도 게코가 있을 수 있어`라는 고정 주의문을 표시한다. 라벨러 교육으로
오버레이 사전 노출을 허용한다는 Owner 결정을 따른다.

## 3. 데이터 흐름

```text
assigned motion clip
→ latest succeeded gme_job.result_run_id
→ gme_run permanent artifact (gme-artifact-v1 gzip)
→ server-side SHA 검증·strict parse·track id 제거
→ browser normalized bbox overlay

miss button(current timestamp + overlay revision)
→ server revalidates assignment and current GME run
→ fn_append_motion_clip_gme_miss
→ append-only motion_clip_gme_miss_events
```

## 4. 오버레이 계약

- 현재 GME 결과는 `gme_jobs.status='succeeded'`, `result_run_id`, `gme_runs.status='ok'`의 최신
  `(completed_at DESC NULLS LAST, id DESC)` 한 건만 사용한다.
- R2 key와 원본 artifact는 브라우저에 노출하지 않는다. 서버가 presigned GET으로 읽고
  `permanent_artifact_sha256`을 재계산한다.
- gzip 해제 전후 크기를 제한하고 `schema_version='gme-artifact-v1'`, bbox·timestamp·confidence·
  provenance를 strict 검증한다.
- 응답은 `overlay_revision`, duration, 익명 track index, timestamp, normalized bbox, confidence,
  provenance만 포함한다. detector identity·run UUID·R2 key는 공개하지 않는다.
- `videoWidth`·`videoHeight`로 `object-contain`의 실제 영상 영역을 계산하므로 비-16:9 영상에서도
  normalized bbox를 레터박스가 아닌 영상 프레임에 맞춰 표시한다.
- 현재 시점에서 허용 오차 안의 track별 최신 점만 표시한다. `observed`는 초록 실선,
  `tracked/interpolated`는 하늘색 점선으로 구분한다.
- artifact가 없거나 무결성 검증이 실패하면 영상과 사람 라벨링은 계속되고 오버레이·미탐 버튼만
  `사용 불가`로 표시한다.

## 5. 미탐 원장 계약

- 한 row는 clip, reviewer, live/canary scope, GME run, detector identity, artifact SHA, 1ms canonical
  timestamp, 생성시각, digest를 저장한다.
- reviewer와 scope는 bearer 인증과 기존 slot 배정에서 결정한다. body의 reviewer/run/model 값은
  받지 않는다.
- `overlay_revision`이 현재 run의 artifact SHA와 다르면 `409 overlay_changed`로 거절하고 화면이
  오버레이를 다시 읽는다.
- 같은 reviewer·run·timestamp 중복은 멱등 성공으로 처리한다. 서로 다른 시점은 여러 번 저장한다.
- UPDATE/DELETE/TRUNCATE를 차단한다. browser role 직접 접근은 0이고 service-role RPC만 허용한다.
- 이 이벤트는 사람 GT, consensus, GME run을 수정하지 않는다. bbox 학습자료 승격은 별도 Owner
  보정과 dataset decision 뒤에만 가능하다.

## 6. 완료 기준

1. 미완료 GME negative audit batch는 DB에서 종료되지 않는다.
2. 배정된 라벨러만 해당 clip의 오버레이와 미탐 제보를 사용할 수 있다.
3. artifact SHA·schema·bbox·크기 오류는 fail-closed이며 영상 라벨링을 막지 않는다.
4. 영상 재생 시점에 맞는 bbox가 desktop/mobile 비율에서 정규화 좌표로 표시된다.
5. 버튼은 현재 시점과 frozen GME identity를 append-only로 남기고 GT를 변경하지 않는다.
6. Python·SQL runtime·web unit/route/component 테스트와 local canary를 통과한다.
7. production DB/R2/service/model/Flutter write·deploy는 별도 승인 전 0이다.

## 7. 구현 검증 기록 (2026-08-25 KST)

- Python migration/probe 회귀: 45 passed.
- web 전체 회귀: 1,185 passed, TypeScript `tsc --noEmit` 통과.
- 일회용 PostgreSQL: RPC 성공, 직접 INSERT 거절, scope 멱등, stale revision/미배정/닫힌
  canary 거절, mutation 차단, 최종 residue 0.
- 현재 local Owner canary DB에는 이중 블라인드 기반 schema가 없어 forward migration 적용을
  시도하지 않고 transaction rollback을 확인했다. 대신 현재 소스의 두 Next.js route 실제 dev compile,
  무인증 401 경계, component rendering, 일회용 DB runtime을 결합한 동등 local 검증을 사용했다.
- production DB/R2/service/model/Flutter write·deploy는 수행하지 않았다.
- iTerm Claude 읽기 전용 교차검수에서 확장 DDL 의존과 비-16:9 bbox 정렬 문제 2건을 발견했다.
  core `sha256(convert_to(...))`와 실측 영상 비율 기반 content rect로 수정하고 재현 테스트를 추가했다.
  2차 검수 결과 Critical/Important 0건으로 `CLAUDE_REVIEW_APPROVE`를 받았다.
- 수정 후 PostgreSQL 15 일회용 DB에서 전체 miss-event probe를 다시 실행했고 모든 권한·멱등·stale·
  append-only 검증과 `PROBE_RESIDUE=0`을 확인했다.
