# Local VLM Evidence GT 웹 워크스페이스 설계

> **상태:** owner 설계 승인 / 구현계획 작성 전 문서 검토
>
> **선행 판정:** `HARDENED_IMPLEMENTATION_READY_FOR_DATA_REVIEW`
>
> **연구 역할:** Work Package B — evidence-first 후보 가용성 확인과 사람 blind GT 수집

## 1. 목표

production Python Evidence와 activity assessment에서 Local VLM 벤치마크용 후보를 결정론적으로
찾고, owner가 `label.tera-ai.uk`에서 모델·Python·Gate 결과를 보지 않은 채 180개 영상의 evidence
GT를 작성·동결할 수 있게 한다.

이 설계는 모델 설치·다운로드·추론을 승인하지 않는다. 180/180 blind GT와 두 SHA-256이 동결된
뒤에만 별도 runtime 승인으로 넘어간다.

## 2. SOT·의사결정 정합

- `specs/feature-rba-data-engine-v1.md`의 1차 병목은 다양한 운영 영상과 사람 GT 부족이다.
- 사람 GT 확정 전 VLM·Claude·Gate 결과를 숨기고, 모델 판정과 ground truth를 분리해야 한다.
- 기존 Local VLM 설계의 6 strata × 30, dev 120 / fresh holdout 60, 총 180 unique clip 계약을
  유지한다.
- 과거 local router, detector 기반 자동 skip, 행동 자동 라벨은 재등판시키지 않는다.

## 3. 접근 비교와 결정

### A. owner 전용 웹 워크스페이스 — 채택

후보 가용성 확인과 GT 작성을 같은 제품 인증·영상 재생 기반 위에서 처리한다. 180건을 브라우저
밖 CSV에 직접 입력할 때 생기는 행 밀림·중복·로컬 파일 손실을 피하고, 진행률·검증·동결을 서버가
강제할 수 있다.

### B. CSV worksheet만 사용 — 기각

초기 진단은 빠르지만 180건 장기 작업의 임시저장·동시성·완전성·감사 추적이 약하다. CSV export는
검산·백업 산출물로만 유지한다.

### C. 기존 `clip_labeling_sessions` 재사용 — 기각

기존 세션은 행동 GT와 VLM 검수 계약이다. Local VLM evidence 5축과 study split을 섞으면 기존
production GT 의미와 튜토리얼·큐 완료 상태를 오염시킨다.

## 4. 단계와 승인 게이트

### Gate B0 — 검수된 기반 통합

`petcam-lab`과 `petcam-rba-worker`의 Local VLM hardening feature를 각각 `main`에 fast-forward로
통합하고 전체 회귀를 통과시킨다. non-fast-forward merge·force push는 금지한다.

### Gate B1 — SELECT-only 가용성

production DB를 읽어 broad candidate pool, 집계 보고서, Git 제외 per-clip artifact를 만든다.
DB write·migration·Web 배포는 하지 않는다.

판정은 strata별 30분 dedup unique episode 수로 정한다.

- `DATA_AVAILABLE`: 45 이상
- `DATA_AVAILABLE_LOW_MARGIN`: 30~44
- `BLOCKED_DATA_INSUFFICIENT`: 0~29

하나라도 30 미만이면 180 manifest를 만들지 않고 멈춘다. 다른 strata·중복 clip·synthetic 영상으로
채우지 않는다.

### Gate B2 — 코드·스키마 preview

B1이 6 strata 모두 30 이상일 때 owner 전용 API·화면·forward migration을 구현하고 preview에서
적대 DB probe와 owner/labeler E2E를 수행한다. production migration·seed는 별도 승인 전 금지한다.

### Gate B3 — production study 동결·GT 수집

owner 승인 후에만 migration을 production에 적용하고, B1 artifact SHA와 동일한 후보 중 180개를
원자적으로 seed·freeze한다. 그 뒤 owner가 blind GT를 작성한다. 모델 inference는 계속 금지한다.

## 5. 사용자 체험

### 5.1 준비 전·부족 상태

- **[화면]** owner 메뉴에 `Evidence GT`가 보이고, 화면에는 `후보 준비 전` 또는 strata별 가용 episode
  수가 보인다.
- **[반응]** 한 strata라도 30 미만이면 `표본 부족`을 명확히 표시하고 GT 시작 버튼을 비활성화한다.
- **[감정]** 숫자를 억지로 채운 가짜 연구가 아니라는 점을 확인할 수 있다.

### 5.2 GT 작성

- **[화면]** 진행률, 영상, frame step·속도 조절, 다섯 개 쉬운 질문만 보인다.
- **[금지 노출]** 현재 clip의 stratum·split·selection reason, Python Evidence, Gate bbox/판정,
  activity decision, 기존 behavior GT, VLM·Claude·local model 결과는 보이지 않는다.
- **[조작]** owner가 답을 고르면 draft가 저장된다. 다른 페이지를 다녀와도 마지막 미완료 위치와
  답이 복원된다.
- **[조작]** `최종 제출` 전 확인 화면에서 다섯 축과 한 문장 이유를 다시 본다.
- **[반응]** 제출 후 해당 답은 잠기며 다음 미완료 영상으로 이동한다.
- **[감정]** 장시간 작업 중 입력 손실을 걱정하지 않고, AI 힌트 없이 자신의 관찰만 남길 수 있다.

### 5.3 완료

- 180/180 제출 후 manifest SHA-256과 GT SHA-256, camera/date/strata/split 분포를 보여준다.
- raw selection reason은 완료 뒤에도 일반 UI에 공개하지 않는다. 연구 보고서는 aggregate만 사용한다.
- `runtime 준비 완료`는 표시할 수 있지만 모델 실행 버튼은 제공하지 않는다.

## 6. 후보 가용성 계약

### 6.1 읽기 입력

SELECT-only probe가 읽을 수 있는 정본:

- `motion_clips` 또는 canonical clip metadata
- `clip_python_evidence_runs`
- `clip_activity_assessments`
- `clip_prelabels`
- 기존 사람 `behavior_logs`·현재 GT는 semantic 후보 탐색 보조 신호

금지 입력:

- `clip_vlm_jobs` prediction·reasoning
- Claude/local VLM 결과
- 모델이 만든 label을 사람 GT로 변환한 값

### 6.2 여섯 strata

1. `absent_or_unseen` — 게코 없음·안 보임 후보
2. `big_move` — 큰 이동 후보
3. `rest_micro` — 휴식·국소 미세 움직임 후보
4. `lick_water_food` — 핥기·물·먹이 관련 관찰 후보
5. `wheel_object` — 쳇바퀴·사물 상호작용 후보
6. `hardcase` — 가림·구석·야간 IR·그림자 후보

후보 규칙은 versioned pure function으로 구현한다. 각 결과는 `selector_version`, `stratum`,
`priority_score`, `reason_codes`, `source_run_id`, `source_assessment_id`를 가진다. 점수는 검수 우선순위일
뿐 GT가 아니다. 행동 GT가 필요한 semantic strata 4·5에서는 기존 사람 라벨을 retrieval 신호로만
쓸 수 있으며 evidence 5축 값으로 복사하지 않는다.

### 6.3 dedup·다양성

- episode는 camera별 `captured_at` 오름차순으로 묶는다. 직전 clip과 간격이 30분 이하이면 같은
  episode, 30분을 초과하면 새 episode다. episode key는 `camera_id + 첫 clip captured_at`의
  canonical UTC 문자열이다. 고정 시각 버킷 경계(예: 10:29/10:31)가 가까운 clip을 둘로 나누지
  않는다.
- 같은 clip은 전체 study에서 한 번만 사용한다.
- 같은 episode가 여러 strata 후보면 사전 고정 priority
  `hardcase > wheel_object > lick_water_food > rest_micro > big_move > absent_or_unseen`로 한 곳에만
  배정한다.
- strata별 broad pool은 최대 60 episode를 결정론적으로 보존하고, 최소 margin 목표는 45다.
- 최종 30개는 camera·date 균형을 우선하는 deterministic round-robin으로 고른다.
- 전체 camera 2대 이상, 촬영일 3일 이상이어야 한다.
- 가능한 경우 strata별 단일 camera 비율 60% 이하를 요구한다. 불가능하면 manifest를 만들지 않고
  가용성 보고서에 blocker로 남긴다.

### 6.4 split

각 strata 30개를 selection key SHA-256 오름차순으로 안정 정렬한 뒤 첫 20개를 `dev`, 마지막 10개를
`fresh_holdout`으로 배정한다. clip·episode의 split 교집합은 0이어야 한다. split은 UI에 숨긴다.

## 7. 저장 모델

기존 labeling 테이블과 분리한 세 테이블을 사용한다.

### 7.1 `local_vlm_evidence_studies`

- `id`, unique `version`
- `status`: `draft | frozen | gt_complete | archived`
- `selector_version`, `candidate_manifest_sha256`, nullable `gt_sha256`
- `created_by`, `created_at`, `frozen_at`, `completed_at`

`frozen` 이후 candidate manifest identity는 변경할 수 없다.

### 7.2 `local_vlm_evidence_candidates`

- `study_id`, `clip_id`, `stratum`, `split`, `position`
- `episode_key`, `priority_score`, `reason_codes`
- source provenance IDs와 `selection_identity_sha256`

unique: `(study_id, clip_id)`, `(study_id, position)`. 이 테이블은 service-role 전용이며 per-clip
selection 필드를 GT 응답에 포함하지 않는다.

### 7.3 `local_vlm_evidence_annotations`

- `study_id`, `candidate_id`, `reviewed_by`
- `presence_observation`
- `visibility`
- `motion_extent`
- `body_regions[]`
- `object_candidates[]`
- `human_uncertain`
- `reason` 10~500자
- `stage`: `draft | submitted`
- `updated_at`, `submitted_at`

draft는 owner가 수정할 수 있다. `submitted` 이후 UPDATE·DELETE·TRUNCATE를 역할과 무관하게 DB
trigger로 차단한다. study 완료는 정확히 180개 submitted, 필수 enum·배열·reason 완전성, reviewer
일치를 원자적으로 검사한 RPC로만 가능하다.

## 8. API·보안 계약

- 모든 route는 bearer 인증 뒤 product owner를 서버에서 검증한다. 메뉴 숨김은 보안 경계가 아니다.
- anon/authenticated table policy는 0, RLS enabled, table·RPC는 service_role만 사용한다.
- body의 owner ID, study status, candidate provenance를 신뢰하지 않는다.
- GT 목록·상세 응답에는 stratum·split·score·reason_codes·evidence·기존 GT·모델 결과가 없어야 한다.
- signed media URL은 현재 owner media route 패턴을 재사용하고 짧은 TTL을 유지한다.
- DB 오류는 일반 502, study/candidate 없음은 404, stale draft는 409, submitted 수정은 409다.
- draft 저장은 optimistic version을 사용해 여러 탭의 오래된 저장이 최신 답을 덮지 못하게 한다.

## 9. manifest·hash 계약

candidate manifest canonical JSON은 key 정렬·UTF-8·compact separators를 고정한다. 각 row는 clip ID,
stratum, split, episode key, source provenance identity를 포함한다. `candidate_manifest_sha256`은 freeze
RPC가 서버에서 재계산한다.

GT canonical JSON은 position 순서로 clip ID와 일곱 사람 입력 필드만 포함한다. `gt_sha256`은 180개
submitted 완료 RPC가 서버에서 재계산한다. draft는 hash에 포함하지 않는다.

CSV export는 사람이 읽는 백업이며 SHA 정본이 아니다. export에는 영상 URL·signed URL·selection
reason·모델 결과를 넣지 않는다.

## 10. UI 구조

- `/labeling/evidence`: owner 전용 dashboard·진행률
- `/labeling/evidence/[position]`: blind GT 단건 작성
- 기존 `/labeling/[clipId]` 행동 GT 세션과 라우트·draft key를 공유하지 않는다.
- sessionStorage draft를 보조 복구로 쓸 수 있지만 DB draft가 정본이다.
- 이전/다음은 미완료 기준이며, 이미 submitted인 항목은 read-only 요약만 보여준다.
- 접근성: 질문 label과 오류 연결, 첫 오류 focus, 키보드로 재생/저장 가능, enum 색상만으로 의미 전달 금지.

## 11. 오류·복구

- candidate source row가 freeze 전에 사라지거나 identity가 달라지면 freeze 전체 rollback.
- freeze 후 원본 clip 삭제는 FK RESTRICT로 막는다.
- 영상 URL 발급·재생 실패 시 답 제출을 비활성화하고 재시도를 제공한다.
- clip 전환·재시도 응답은 request generation으로 stale response를 폐기한다.
- 브라우저 종료 뒤 DB draft에서 복원한다. local draft와 DB version이 다르면 최신 DB를 보여주고
  사용자에게 충돌 안내를 한다.
- 180 완료 직전 한 행이라도 불완전하거나 submitted가 아니면 gt_complete 전환 전체 rollback.

## 12. 검증

### 12.1 후보 selector

- 동일 snapshot에서 JSON bytes와 SHA가 반복 실행 3회 동일
- 30분 episode·clip 중복 0
- priority 충돌 배정 결정론
- 모델 출력 query·field 참조 0
- strata별 판정과 다양성 blocker 정확성

### 12.2 DB 적대 probe

- cross-study candidate·annotation 차단
- freeze 후 candidate mutation 차단
- submitted annotation UPDATE·DELETE·TRUNCATE 차단
- incomplete 179/180 완료 차단
- enum·배열·reason·optimistic version 변조 차단
- candidate/GT SHA 서버 재계산 일치
- 전량 transaction rollback, probe 잔류 0

### 12.3 API·UI

- 무인증 401, 비owner 403
- 일반 labeler 직링크 403
- 응답에 stratum·split·reason_codes·evidence·기존 GT·VLM key 0
- draft 저장·복원·충돌 409
- 최종 제출 뒤 수정 불가
- clip A 늦은 media/detail 응답이 clip B를 덮지 않음
- 새로고침·페이지 왕복 뒤 진행 위치 복원

### 12.4 수용 검사

- B1 live SELECT-only 보고에서 6 strata별 exact episode count를 독립 쿼리와 대조한다.
- preview에서 owner가 5개 draft→submit을 수행하고 일반 labeler가 접근할 수 없음을 확인한다.
- production seed 전후 behavior GT·VLM·activity·일반 labeling session row 수 불변을 확인한다.
- 180/180 완료 전 model download·inference 호출 0을 정적·운영 로그로 확인한다.

## 13. 배포·중단 경계

1. 일반 라벨 큐 최신순은 독립 배포한다.
2. B1은 SELECT-only로 실행하고 결과를 owner가 승인한다.
3. B2 코드는 preview까지만 배포하고 migration production 적용 전 멈춘다.
4. B3 production migration·seed는 별도 owner 승인 후 실행한다.
5. 180 GT 완료 뒤에도 Mac mini model snapshot 다운로드·inference는 새 handoff와 별도 승인 없이는
   실행하지 않는다.

즉시 중단 조건:

- 어떤 API 응답에서 selection/evidence/model 값이 노출됨
- 일반 라벨러가 evidence route에 접근함
- 후보 180에 clip·episode 중복 발생
- production 행동 GT·VLM·activity row가 변경됨
- submitted GT가 수정·삭제 가능함

## 14. 완료 조건

- Queue 최신순 설계가 별도 완료·배포됐다.
- B1 판정이 6 strata 모두 `DATA_AVAILABLE` 또는 `DATA_AVAILABLE_LOW_MARGIN`이다.
- candidate manifest가 180 unique clip, 180 unique episode, 6×30, dev 120/holdout 60이다.
- owner-only blind UI와 draft·submit·freeze 계약이 적대 probe/E2E를 통과한다.
- 180/180 submitted 후 두 SHA가 서버에서 동결된다.
- 모델 출력 열람·모델 다운로드·inference·일반 GT 변경은 0이다.

## 15. 비목표

- Local VLM 품질·속도 판정
- behavior action 자동 생성
- Python/Gate 기반 자동 제외·자동 skip
- 일반 라벨러에게 연구 GT 할당
- 기존 행동 GT·튜토리얼 계약 변경
- candidate selection reason을 사람 GT 힌트로 노출
