# 라벨링 웹 v2 — 통합 GT·VLM 검수·metadata 설계

**상태:** 사용자 방향 승인 / 구현 계획 전
**작성일:** 2026-07-12
**상위 SOT:** [`specs/feature-rba-data-engine-v1.md`](../../../specs/feature-rba-data-engine-v1.md)

## 1. 목표

`label.tera-ai.uk`를 가끔 확인하는 관리자 화면에서, 매일 쌓이는 영상을 학습 가능한 사람 GT로 바꾸는 생산 도구로 전환한다. 한 clip을 한 화면·한 작업에서 끝내되, 사람 GT가 VLM 예측에 끌리지 않도록 저장 순서를 분리한다.

## 2. 핵심 결정

- 같은 화면에서 **사람 관찰 GT → VLM 판정 검수 → 완료**를 연속 수행한다.
- VLM action·confidence·reasoning은 최초 사람 GT를 확정하기 전까지 숨긴다.
- 사람이 본 사실과 해석을 분리한다. 예를 들어 `관찰=licking`, `target=water_bowl`을 저장하고 `drinking` 같은 의미 행동은 별도 action으로 함께 보존한다.
- camera·animal·enclosure·capture provenance는 시스템이 상속한다. 사람에게 clip마다 반복 입력시키지 않는다.
- bbox·ROI·접촉부위처럼 비용이 큰 라벨은 모든 clip에서 강제하지 않고 Gate audit나 정밀 연구 모드에서만 요구한다.
- 최초 blind GT와 이후 수정·VLM 비교 결과는 덮어쓰지 않고 이력으로 재현 가능해야 한다.

## 3. 사용자 체험

1. `[화면]` 큐 카드에 실제 썸네일, 카메라, 촬영시각, 길이, 검수 상태가 보인다.
2. `[조작]` 사용자가 clip을 연다.
3. `[화면]` 영상과 객관적 시스템 metadata만 보이고 VLM 결과는 잠겨 있다.
4. `[조작]` 사용자가 가시성, 관찰 행동, 행동 구간, 대상, 확신도, 품질·환경 태그를 입력한다.
5. `[조작]` `GT 확정`을 누른다.
6. `[반응]` 최초 blind GT가 저장되고 같은 화면에서 VLM action·confidence·reasoning이 공개된다.
7. `[조작]` 사용자가 VLM을 `정확 / 부분정답 / 오답 / 판정불가`로 평가하고 오류 유형을 고른다.
8. `[조작]` `완료 후 다음`을 누른다.
9. `[반응]` 다음 미완료 clip이 즉시 열린다. 브라우저를 닫았다 돌아와도 단계와 입력이 복원된다.

사용자는 썸네일이 없는 회색 카드, 저장 후 큐로 되돌아가기, 같은 camera/animal metadata 반복 입력, VLM을 본 뒤 GT를 맞추는 경험을 하지 않는다.

## 4. 사람 입력 계약

### 모든 clip의 필수 입력

- `visibility`: `visible / partial / absent / uncertain`
- `primary_action`: 현재 action taxonomy의 대표 행동
- `observed_actions[]`: 이동, 정지, 핥기, 포획, 배변, 허물 제거, wheel/object 상호작용 등 복수 관찰 행동
- `segments[]`: 각 관찰 행동의 `start_sec / end_sec`
- `target`: 물, 물그릇, 먹이그릇, 페이스트, 먹이곤충, 유리, 바닥, 사람 손, 도구, 불명확
- `human_confidence`: `certain / likely / uncertain / unjudgeable`
- `context_tags[]`: IR, glare, occlusion, distant, blur, overexposure, edge, human, shadow, camera_motion, empty_scene
- `note`: 정형 필드로 설명하지 못한 예외만 선택 입력

활동 관련 입력은 행동과 강도를 분리한다.

- `primary_action`: `moving` 등 관찰 가능한 대표 행동. `playing`은 자동 입력값으로 직접 받지 않는다.
- `activity_intensity`: `low / medium / high`
- `enrichment_object`: `wheel / toy / other / none / uncertain`
- `interaction_type[]`: `ride / push / rotate / chase / repeated_return / other`
- `enrichment_verdict`: `candidate / human_confirmed / rejected`. `playing` 고객 문구는 `human_confirmed`에서만 파생한다.

`absent`나 `unjudgeable`처럼 논리적으로 행동 구간을 만들 수 없는 상태에서는 관련 필드를 비활성화한다. top-1을 억지로 고르게 하지 않는다.

### 일반 이동과 enrichment interaction 라벨 가이드

`moving`은 이동·등반·자세 변경·한 번 지나가기처럼 **enrichment object와 명확한 직접·반복 상호작용이 없는 일반 활동**이다.

사람과 VLM은 `playing`이라는 의도를 직접 단정하지 않는다. wheel/장난감 등 enrichment object를 타고·밀고·돌리거나 반복해서 접근한 객관적 interaction을 기록한다. 이 evidence를 사람이 확인하면 제품 표시용 `playing`을 파생한다.

판정 순서는 다음과 같다.

1. 게코가 안 보이면 `unseen`이다.
2. feeding/drinking/defecating/shedding 등 직접 care 행동이 보이면 해당 행동을 우선 기록한다.
3. wheel을 타거나 밀어 회전시키는 직접 상호작용이 보이면 해당 interaction type과 구간을 기록한다.
4. 다른 물체는 반복 상호작용이나 재접근이 명확할 때만 enrichment candidate로 기록한다.
5. 단순 이동·등반·정지·물체 옆 통과는 `moving`이다.
6. 한 clip에서 일반 이동 뒤 wheel interaction이 이어지면 moving과 interaction segment를 각각 기록한다.

라벨링 화면은 positive/negative 예시를 상시 표시하고, enrichment candidate에는 object와 interaction type을 필수로 요구한다. 근거를 고를 수 없으면 `moving` 또는 `uncertain`으로 보낸다. VLM도 `playing` 대신 object/contact/rotation/repeated-return evidence만 답한다.

### 시스템 자동 metadata

- camera, animal, species, morph, enclosure
- camera-night, started_at, duration, resolution, FPS
- R2 key, content hash, capture/schema version
- motion feature와 production provenance
- labeler, 최초 라벨 시각, 수정 시각, label schema version
- dataset role과 camera-night split
- VLM model, prompt, input recipe, token/cost
- Gate checkpoint, threshold, sampler

### 조건부 고급 입력

- Gate audit: sampled frame별 bbox 추가·삭제·교정
- 섭식·음수 연구: camera ROI, 접촉 순간, before/after 상태
- enrichment 연구: wheel/장난감 ROI, 반복 상호작용 구간, 활동 유형
- 모호·희소 행동: 2차 라벨러 판정과 disagreement 사유
- 케어 사실: 급여, 물 교체, 실제 배변 확인처럼 영상 밖에서 확인한 event

## 5. VLM 검수 계약

VLM 검수는 최초 blind GT와 exact prediction snapshot을 비교한다.

- verdict: `correct / partially_correct / incorrect / unjudgeable`
- error tags: 행동 혼동, target 혼동, 게코 미검출, 모프 착각, IR/반사, 시간 구간 오류, 근거 부족, 다중행동 누락
- reviewed prediction provenance: `behavior_logs.id`, model, prompt, input recipe
- GT와 VLM prediction은 서로 다른 저장 영역을 사용하며 어느 쪽도 다른 쪽을 덮어쓰지 않는다.

VLM `shedding`은 사람 확인 전 고객 앱에 `AI 탈피 의심 · 확인 필요`로 표시한다. 사람 GT가 shedding이면 `탈피 확인`, 다른 행동이면 오탐으로 내리고 모델 오류 이력은 보존한다.

## 6. 오늘 구현 범위와 후속 범위

### 오늘 우선

1. 썸네일 URL 실패 복구와 실패 원인 표시
2. 사람 GT 전 VLM 숨김
3. 필수 GT + VLM verdict를 한 화면의 2단계로 저장
4. 저장 상태 복원, `완료 후 다음`, 진행률
5. Vercel production 배포와 실제 계정 검증

### 후속

- frame 단위 bbox 편집기
- ROI 편집기
- 다중 라벨러 adjudication dashboard
- dataset export와 split conflict dashboard
- camera/animal/enclosure 관리 UI

## 7. 현재 운영 장애 근거

- 운영 큐와 상세 영상은 동작한다.
- 최신 큐 30건의 파생 jpg는 R2에 30/30 존재한다.
- `camera_clips.thumbnail_r2_key`와 `thumbnail_path`는 비어 있다.
- frontend는 외부 Fly API의 `/clips/{id}/thumbnail/url` 실패를 숨기고 `영상` fallback만 표시한다.
- Fly `petcam-api` production은 2026-05-08 v1이며, 2026-07-08에 추가한 `r2_key -> .jpg` 파생 fallback이 배포되지 않았다.

전체 FastAPI를 즉시 배포하는 것보다 기존 Vercel의 clip permission·R2 signer 패턴을 재사용해 same-origin thumbnail URL route를 만드는 방식을 우선 검토한다. 이렇게 하면 두 달치 backend 변경을 한꺼번에 production에 올리지 않고 라벨링 웹 장애를 격리할 수 있다.

## 8. 성공 기준

- 큐 첫 페이지에서 실제 썸네일 30/30을 표시한다.
- thumbnail URL 실패를 회색 placeholder로 조용히 숨기지 않는다.
- 최초 사람 GT 저장 전에는 VLM action·confidence·reasoning이 DOM과 화면에 노출되지 않는다.
- 한 clip의 GT·VLM verdict·metadata 검수를 완료하고 다음 clip으로 이동할 수 있다.
- 새로고침·재로그인 뒤에도 완료 단계와 이력이 복원된다.
- 최초 blind GT, 현재 GT, exact VLM prediction, VLM verdict를 각각 재현할 수 있다.
