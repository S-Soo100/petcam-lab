# Local VLM Evidence Analyst 하드닝 설계

> **상태:** owner 설계 승인 / 구현계획 작성 전 문서 검토
>
> **현재 판정:** `IMPLEMENTATION_HARDENING_REQUIRED`
>
> **대체 판정:** 기존 구현 보고서의 `IMPLEMENTATION_BLOCKED_DATA`는 폐기하지 않고 이 문서가 정정한다. 사람 evidence GT가 0/180인 것은 사실이지만, 데이터 부족을 주장한 probe가 실제 Python Evidence·activity 후보군을 조사하지 않았고 runtime도 아직 Universal Python Evidence를 모델 입력에 연결하지 않았다.

## 1. 목표

Mac mini에서 SmolVLM2를 실행하기 전에 다음 두 조건을 순서대로 충족한다.

1. local VLM 입력이 실제 Universal Python Evidence와 deterministic frame materialization을 포함하고, 실행·자원·평가 계약이 누락 시 fail-closed로 동작한다.
2. live Python Evidence와 activity assessment에서 6개 strata 후보군을 먼저 만들고, 그 후보에서만 사람 blind evidence GT 180건을 작성한다.

이 문서는 모델 설치·다운로드·추론을 승인하지 않는다. 이 문서의 완료 결과는 `HARDENED_IMPLEMENTATION_READY_FOR_DATA_REVIEW`까지다.

## 2. 현 상태와 독립 검수 결과

### 2.1 재사용 가능한 구현

- strict JSON schema와 parser
- Gate 기반 6프레임 materializer
- SmolVLM2 MLX adapter 골격
- one-shot runner와 manifest validator
- production DB·Slack·LaunchAgent를 변경하지 않는 안전 경계

### 2.2 구현 차단 결함

1. runner가 프롬프트에 `durable_key`와 `roi_mode`만 전달하고 `clip_python_evidence_runs`의 motion series·dwell·periodicity·excursion을 읽지 않는다.
2. expected repo HEAD와 model snapshot 인자가 생략되면 현재 값이나 상수로 대체되어 runtime drift 검사가 fail-open이다.
3. latency·RSS·swap·temp·capacity·worker deadline 측정이 평가기에 연결되지 않았고 runtime 입력이 없어도 resource gate가 통과한다.
4. scorer의 `presence_f1_ci`가 F1이 아닌 per-example exact accuracy bootstrap이며 visibility·motion CI, strata·ROI breakdown이 없다.
5. object 평가 대상이 0건이어도 품질 gate를 통과할 수 있다.
6. `pyproject.toml`·`uv.lock`에 MLX runtime 재현 계약이 없다.
7. 데이터 probe가 `behavior_logs` 중심의 거친 매핑을 데이터 가용성으로 해석했다.

### 2.3 live read-only 후보 기반

2026-07-21 독립 조회 기준:

- `clip_python_evidence_runs`: 2,403건
- `clip_activity_assessments`: 6,508건
- 30분 episode dedup 가능 분포:
  - active: 298 episode
  - exclude_static: 162 episode
  - exclude_absent: 58 episode
  - unknown: 356 episode

따라서 현재 정확한 상태는 `GT_PENDING`이지 `DATA_INSUFFICIENT`가 아니다. 새 후보 selector가 6개 strata를 산출한 뒤에만 부족 여부를 판정한다.

## 3. 접근 비교와 결정

### A. 하드닝 → 후보 선정 → GT → runtime — 채택

먼저 input·measurement·scorer를 고친다. 그다음 실제 evidence 원장에서 후보를 선정하고 사람이 GT를 작성한다. 사람이 잘못된 표본에 시간을 쓰지 않으며 runtime 결과도 검산할 수 있다.

### B. GT 180건 선작성 — 기각

현재 probe가 Python Evidence·activity pool을 사용하지 않으므로 strata 편향과 누락 위험이 크다.

### C. Mac mini smoke부터 실행 — 기각

현재 runner는 Universal Python Evidence를 전달하지 않고 scorer는 필수 runtime metric 없이도 PASS할 수 있다. 실행 결과가 나와도 연구 질문을 검증하지 못한다.

## 4. 작업 분리

이 설계는 두 개의 독립 구현계획으로 실행한다.

### Work Package A — runtime·scorer 하드닝

코드 변경과 dry test만 수행한다. production DB write, model 설치·다운로드·추론은 금지한다.

### Work Package B — evidence-first 후보 가용성

production SELECT-only로 후보 manifest와 사람 검수 worksheet를 만든다. GT 값 입력, DB write, 모델 출력 열람은 금지한다.

Work Package A가 먼저 통과해야 B를 시작한다. B의 가용성 결과가 승인된 뒤 별도 세션에서 사람이 GT를 작성한다.

## 5. Work Package A 계약

### H1. Universal Python Evidence 입력 연결

runner는 각 clip의 선택된 `clip_python_evidence_runs` row를 읽고 최소 다음 필드를 정규화한다.

- schema·algorithm version
- provenance와 source prelabel identity
- global motion series
- ROI motion series
- spatial dwell
- periodicity summary
- motion excursions

선택 규칙은 deterministic이어야 한다. 동일 clip에 여러 run이 있으면 사전 등록한 schema·algorithm·provenance와 정확히 일치하는 하나만 허용한다. 0개 또는 2개 이상이면 해당 clip을 `INPUT_EVIDENCE_MISSING` 또는 `INPUT_EVIDENCE_AMBIGUOUS`로 실패시킨다.

프롬프트에는 전체 raw JSON을 무제한 삽입하지 않는다. schema가 허용한 필드만 canonical JSON으로 직렬화하고 byte length 상한을 적용한다. 입력 canonical JSON의 SHA-256을 measured identity와 raw ledger에 기록한다.

### H2. runtime identity fail-closed

다음 값은 CLI 필수 인자로 받으며 기본값을 금지한다.

- lab·rba·gate 40자리 expected HEAD
- model repository와 exact revision
- local snapshot 절대경로와 snapshot verification 값
- MLX-VLM version
- Gate checkpoint SHA-256
- Gate threshold
- prompt·schema·sampler version

누락, Git 조회 실패, snapshot 미존재, revision 불일치, model file 미존재는 inference 전에 nonzero로 종료한다. 현재 HEAD나 상수로 기대값을 자동 보충하지 않는다.

### H3. runtime 계측

clip·run·segment 단위로 다음을 기록한다.

- model load latency
- materialization latency
- generation latency
- end-to-end latency
- process peak RSS
- MLX peak memory를 runtime이 제공할 경우 해당 값
- swap 시작·종료·delta
- temp directory peak bytes와 종료 후 잔존 수
- 성공 clip 기준 sustained clips/hour
- 인접 production worker deadline과 실제 지연

계측 명령 실패나 필드 누락은 `RESOURCE_EVIDENCE_MISSING`이며 resource gate 실패다. 빈 값으로 PASS하지 않는다.

### H4. scorer 수학·coverage 정정

- presence macro F1과 bootstrap 95% CI를 실제 confusion matrix에서 재계산한다.
- visibility weighted F1과 95% CI를 계산한다.
- motion extent macro F1과 95% CI를 계산한다.
- object-positive 표본에 대해서만 top-k recall을 계산하되 evaluable object clip이 사전 등록 최소 수보다 작으면 PASS가 아니라 `QUALITY_EVIDENCE_INSUFFICIENT`다.
- strata별, `roi_mode`별 표본 수·점수·abstain·실패율을 모두 보고한다.
- point metric, CI, confusion matrix를 summary에 함께 기록한다.
- scorer CLI는 runtime artifact를 필수 입력으로 받는다.

### H5. raw ledger 무결성

- malformed JSONL, duplicate measured key, conflicting successful identity를 조용히 건너뛰지 않는다.
- 손상 발견 시 `REJECT_INTEGRITY`로 중단한다.
- clip 실패는 stable code와 redacted diagnostic만 기록한다.
- raw stdout·stderr·secret·media path는 저장하지 않는다.
- scorer와 independent recompute는 expected key 생성 코드를 공유하지 않는다.

### H6. dependency·adapter 재현성

- `mlx-vlm==0.6.5`와 필요한 MLX/Pillow 의존성을 별도 optional group 또는 동등한 고정 install contract로 lock한다.
- 구현 host에서는 모델 snapshot 없이 package import와 adapter 호출 signature를 실제 설치 패키지 기준으로 검증한다.
- model download나 inference는 수행하지 않는다.
- 실제 package 설치를 이번 dry 단계에서 할 수 없다면 `READY_FOR_RUNTIME`을 주장하지 않고 정확한 blocker를 남긴다.

### H7. dry verification과 보고

- 기존·신규 전체 test 통과
- fixture를 사용해 evidence load → prompt canonicalization → fake adapter → raw ledger → scorer → independent recompute를 end-to-end 검증
- evidence hash가 달라지면 measured identity도 달라지는 회귀 테스트
- runtime metric 하나라도 없으면 PASS 불가 테스트
- object-positive 0건, strata 0건, malformed ledger, Git 조회 실패, snapshot 누락 테스트
- production DB write·Slack·LaunchAgent·model download·inference 0 정적 감사

Work Package A의 유일한 성공 판정은 `HARDENED_IMPLEMENTATION_READY_FOR_DATA_REVIEW`다.

## 6. Work Package B 계약

### 6.1 입력과 조인

SELECT-only probe는 다음을 읽는다.

- `motion_clips` 또는 canonical clip metadata
- `clip_python_evidence_runs`
- `clip_activity_assessments`
- `clip_prelabels`
- 기존 사람 `behavior_logs`·GT는 보조 신호로만 사용

모델 출력은 읽지 않는다. Claude·local VLM 결과를 사람 GT처럼 사용하지 않는다.

### 6.2 후보군 생성

기존 설계의 6개 strata마다 후보 pool을 넓게 만든다.

1. 게코 없음·안 보임
2. 큰 이동
3. 휴식·국소 미세 움직임
4. 핥기·물·먹이 관련 관찰
5. 쳇바퀴·사물 상호작용
6. 가림·구석·야간 IR·그림자 hard case

각 후보는 selection reason, 사용한 evidence field, camera, captured_at, 30분 episode key, clip duration, labeling URL을 가진다. 후보 점수는 GT가 아니라 검수 우선순위이며 자동 label로 저장하지 않는다.

### 6.3 다양성과 부족 판정

- 30분 이내 같은 카메라의 유사 연속 clip은 한 episode로 계산한다.
- clip 중복 0
- 최종 180개는 strata별 30개
- 전체 카메라 2대 이상, 촬영일 3일 이상
- 가능한 경우 strata별 단일 카메라 60% 이하
- pool은 최종 필요량보다 넓게 제공한다. 권장 최소는 strata별 45개 unique episode다.

strata별 30 unique episode를 만들 수 없을 때만 `BLOCKED_DATA_INSUFFICIENT`다. 30은 가능하지만 45에 못 미치면 `DATA_AVAILABLE_LOW_MARGIN`으로 구분한다.

### 6.4 산출물

- read-only availability report
- candidate manifest와 SHA-256
- 사람이 열 수 있는 검수 worksheet
- strata·camera·date·episode 분포
- 제외·중복·누락 사유

이 단계에서 evidence GT 180행을 추측하거나 자동 생성하지 않는다.

## 7. 이후 사람 GT와 runtime gate

Work Package B 승인 후 별도 작업으로 사람이 다음 5축을 blind 작성한다.

- presence
- visibility
- motion extent
- body region
- object interaction

180/180 completeness, holdout 60 blind hash, dev/holdout 교집합 0이 확인된 뒤에만 Mac mini runtime plan을 새로 작성한다. 모델 설치·약 4.5GB snapshot 다운로드는 그 plan에서 owner 별도 승인을 받는다.

## 8. 전역 금지사항

- production DB write·migration
- behavior label·GT·highlight·app activity 변경
- selector·cloud VLM 호출 결정 연결
- Slack·LaunchAgent 변경
- model 설치·snapshot 다운로드·inference
- 데이터 부족을 기존 거친 probe만으로 단정
- runtime metric이나 evaluable sample이 없을 때 PASS
- 현재 feature branch를 main에 merge

## 9. 문서·브랜치 흐름

1. 이 설계 문서를 owner가 검토한다.
2. Work Package A 구현계획과 Claude handoff manifest를 별도 문서로 작성한다.
3. Claude는 A만 feature branch에서 구현하고 보고서로 반환한다.
4. Codex가 A를 독립 검수한다.
5. A 승인 후 Work Package B 계획을 작성한다.
6. B 결과를 Codex가 검수한 뒤 사람 GT 작업 여부를 결정한다.

기존 `feat/local-vlm-evidence-analyst` 구현은 폐기하지 않고 A의 입력 브랜치로 사용한다. 기존 구현 보고서의 성공 주장과 stale HEAD는 A 보고서에서 정정한다.

## 10. 최종 완료 조건

이 설계 단계가 끝났다고 말할 수 있는 조건은 다음과 같다.

- Work Package A가 `HARDENED_IMPLEMENTATION_READY_FOR_DATA_REVIEW`
- Work Package B가 `DATA_AVAILABLE` 또는 정확한 부족 strata를 가진 `BLOCKED_DATA_INSUFFICIENT`
- 후보를 보지 않은 모델 출력으로 GT를 채운 행 0
- model install·download·inference 0
- production consumer 변경 0

그 이후에만 사람 GT 180건과 Mac mini one-shot benchmark로 진행한다.
