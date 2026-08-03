# RBA OpenAI 전환·연구 정리·Dataset v2 설계

> 상태: 2026-08-03 owner 방향 승인. 실행 전 정본.
>
> 이 문서는 local VLM·local router·자동 사건 묶기·Claude CLI 연구를 종료하고,
> 사람 GT와 OpenAI API를 중심으로 RBA 연구를 다시 정렬하는 계약이다.
>
> **2026-08-03 후속 결정:** 이 문서의 `Python/OpenCV 미디어 준비만 유지` 범위는
> [`Gecko Motion Engine v1`](2026-08-03-gecko-motion-engine-v1-design.md)로 확장됐다. 의미
> JSON→local text LLM은 계속 종료 상태지만, GME는 Gate 기반 게코 검출·추적과 실제 움직인
> 시간을 맡는다. 후속 결정이 Python 역할에 우선한다.

## 1. 결정 요약

1. local VLM, local router, 자동 사건 묶기 연구는 종료한다.
2. Claude CLI로 영상을 판독하는 연구도 종료한다.
3. 당분간 의미 분석 provider는 OpenAI API로 단일화한다.
4. Python/OpenCV가 의미 feature JSON을 만들고 local text LLM이 해석하는 단계는 제거한다.
5. Python/OpenCV는 GME로 재정의해 미디어 QA와 Gate 기반 게코 검출·추적·활동시간을 맡는다.
6. 기존 `dataset-203`은 197개 역사 기준판으로 변경 없이 보존한다.
7. 새 RBA Dataset v2는 기존 197개와 최근 Owner-final GT 중 자격을 통과한 영상을 합쳐 만든다.
8. 실패 연구는 현재 계획에서 내리고, 재현에 필요한 이력만 아카이브한 뒤 두 기기의
   실행 서비스·모델·캐시·파생 산출물·불필요 worktree를 제거한다.

## 2. 선택한 접근과 기각한 대안

### 채택: 기준판 보존 + 새 데이터셋 + OpenAI 품질 기준선

기존 사람 GT를 버리지 않고 최근 운영 GT를 더한다. 데이터셋과 모델 예측을 분리해 같은
시험지로 새 OpenAI 모델을 반복 비교한다. 재현 불가능한 자료만 보관하고 재다운로드 가능한
모델과 캐시는 지운다.

### 기각: 새 영상만으로 처음부터 다시 시작

최근 영상만으로는 희귀 행동과 복수 행동의 수가 부족하다. 행동 다양성이 좁아지고 기존 사람
검수 자산을 버리게 된다.

### 기각: 기존 dataset-203 폴더에 계속 추가

과거 모델 예측이 파일명과 manifest에 결합돼 있고 외부·PoC 출처도 섞여 있다. 직접 추가하면
과거 성적 재현, 새 운영 분포, 새 모델 성적이 한 폴더에서 뒤섞인다.

### 기각: 실패 연구 자료를 전부 영구 삭제

왜 중단했는지 근거가 사라져 같은 실험을 반복할 위험이 있다. 다만 재다운로드 가능한 모델,
캐시, 재생성 가능한 프레임은 결과 보고서와 체크섬만 남기고 삭제한다.

## 3. 새 RBA 흐름

```text
production camera
→ 원본 clip을 DB/R2에 보존
→ 사람 blind GT와 Owner-final GT 축적
→ Gecko Motion Engine
   (미디어 QA·게코 검출·추적·노이즈 제거·실제 움직인 시간)
→ OpenAI API 의미 분석
→ model prediction ledger에 별도 저장
→ 사람 검수·오류 분석
→ 사용자 행동 타임라인 연구
```

다음 경로는 현재 흐름에서 제거한다.

```text
Python Evidence 의미 feature JSON
→ local text LLM
→ local router
→ 자동 skip·우선순위·자동 행동 결정
```

OpenAI 결과도 사람 GT를 덮어쓰지 않는다. 자동 사건 병합과 자동 skip은 계속 금지한다.
사건 경계는 현재 Owner-final 결과를 그대로 사용하며, 사건 묶기 모델 연구를 재개하지 않는다.

## 4. Python의 현재 역할 — Gecko Motion Engine

“Python Evidence 종료”는 Python 영상 처리를 전부 없앤다는 뜻이 아니다.

| 제거 | 유지 |
|---|---|
| optical-flow 등의 의미 feature를 만들어 local LLM에 전달 | 영상 디코딩 가능 여부 검사와 media QA |
| local LLM용 evidence JSON과 reliability 점수 | 시간순 프레임 또는 짧은 입력 구간 추출 |
| router용 `cloud_now/cloud_later/activity_only` 판정 | Gate 기반 bbox/mask와 multi-gecko tracking |
| Evidence 점수에 의한 자동 제외 | 흔들림·IR·노출 분리와 verified moving time |

프레임 수와 입력 표현은 데이터셋에 박지 않는다. OpenAI 모델별 시험 계약에 버전으로 기록한다.

## 5. Dataset v2

### 5.1 세 계층

| 계층 | 구성 | 역할 |
|---|---|---|
| legacy baseline | 기존 dataset-203 197개 | 과거 기준, 희귀 행동, challenge/regression |
| production extension | 최근 촬영분 중 Owner-final GT와 자격검사를 통과한 영상 | 실제 운영 분포 보강 |
| future holdout | 모델·prompt·입력 계약 동결 뒤 촬영된 미공개 영상 | 최종 일반화 검사 |

Dataset v2 manifest는 원본을 복제해 뜻을 숨기지 않고 각 항목의 `source_dataset`,
`source_clip_id`, `media_sha256`, `gt_version`, `dataset_role`을 기록한다. legacy 197개를
계승하더라도 원래 dataset-203 폴더는 수정하지 않는다.

### 5.2 사람 정답 구조

한 영상에 여러 행동이 있을 수 있으므로 top-1 하나만 저장하지 않는다.

- `primary_action`: 사용자에게 가장 먼저 보여줄 대표 행동
- `observed_actions[]`: 실제로 확인된 행동 전체
- `segments[]`: 확인 가능한 경우 행동별 시작·종료 시각
- `visibility`, `quality_tags`, `uncertainty`: 보임·화질·판정 한계
- `gt_provenance`: 최초 blind 답, 합의 또는 Owner-final, 정정 이력

모델명, prompt, 예측, confidence, reasoning은 Dataset v2 manifest에 넣지 않는다.
이 값은 `(dataset_version, sample_id, provider, model, prompt_version, input_policy,
run_id)`를 키로 하는 별도 prediction ledger에 저장한다.

### 5.3 production extension 자격

최근 GT 영상은 다음을 모두 만족해야 한다.

1. 원본이 R2에 실제 존재하고 디코딩된다.
2. 사람 최종 정답과 provenance가 있다.
3. 중복 media hash가 아니다.
4. 카메라·촬영시각 등 누수 방지에 필요한 metadata가 있다.
5. 게코가 실제로 보이거나 `unseen` 자체가 명시적 연구 표본이다.
6. 단순 수량 채우기가 아니라 희귀 행동, 복수 행동, 오분류 난이도, 새 카메라·개체·사육장
   다양성 중 하나 이상의 추가 가치가 있다.

train/validation/future holdout은 clip 랜덤 분할이 아니라 camera-night와 가능한 경우
camera·animal·enclosure 경계를 기준으로 분리한다.

## 6. 연구 아카이브와 두 기기 정리

### 6.1 보존 등급

| 등급 | 처리 |
|---|---|
| Git tracked 문서·코드·보고서 | 중단 사유와 최종 판정을 기록하고 archive index에서 찾을 수 있게 보존 |
| 원본이 DB/R2에 있는 영상의 로컬 복사 | key를 직접 노출하지 않는 manifest·hash 확인 후 삭제 |
| 재현 불가능한 private 결과물 | private R2 연구 archive에 checksum과 함께 보존 후 로컬 삭제 |
| Ollama 모델·모델 캐시·추출 프레임·임시 입력 | 재생성 출처와 버전만 manifest에 적고 archive 없이 삭제 |
| Git worktree | clean·reachable·비밀값 없음 확인 후 제거. dirty이면 먼저 별도 보존 목록으로 격리 |
| launchd 서비스 | production capture/DB/R2/labeling 의존성 감사 후 연구 전용 서비스만 bootout·plist 제거 |

production 원본 영상, 사람 GT, DB/R2 객체, 라벨링 웹, capture worker는 정리 대상이 아니다.
현재 작업 worktree의 사용자 변경과 미커밋 연구 결과도 자동 삭제하지 않는다.

### 6.2 제거 후보 범주

- Mac mini와 MacBook의 Ollama/local-VLM 모델 및 캐시
- local VLM·router·Python Evidence 의미 분석 전용 실행 서비스
- local VLM·router·사건 묶기 전용 worktree
- 재생성 가능한 frame/contact-sheet/input cache와 임시 benchmark artifact
- Claude CLI 실행 전용 스크립트·런타임 설정 중 현재 생산 경로가 참조하지 않는 항목

각 실제 경로는 삭제 전에 archive manifest에 `host`, `path`, `size`, `kind`, `keep/delete`,
`reason`, `recovery_source`, `sha256 또는 Git HEAD`로 고정한다. 범주 이름만 보고 삭제하지 않는다.

## 7. SOT 변경 범위

현재 계획을 설명하는 문서는 다음 순서로 고친다.

1. `specs/next-session.md` 최상단: 새 결정과 다음 실행 순서
2. `specs/feature-rba-data-engine-v1.md`: 사람 GT·Dataset v2 우선, local/auto grouping 종료
3. `docs/AI-VIDEO-ANALYSIS-STRATEGY.md`: OpenAI API를 현재 Track A 후보로 두고 역사 트랙 분리
4. `AGENTS.md`: active 연구 진입점과 금지 경로 갱신
5. `docs/decision-gate.md`: owner 승인과 중단 근거 append
6. `experiments/INDEX.md`, `specs/README.md`: 종료·archive·active 구분
7. 제품 SOT: `tera-ai-product-master`의 provider·RBA pipeline 문서와 같은 결론으로 정렬

역사 문서의 과거 실행 사실은 다시 쓰지 않는다. 대신 문서 상단에 `archived`, `superseded`,
`invalid-for-adoption` 중 하나를 표시하고 현재 정본 링크를 단다.

## 8. OpenAI API 도입 경계

- API key와 API billing은 ChatGPT 구독과 별개로 사용자가 OpenAI Platform에서 준비한다.
- key는 Mac mini 비밀 환경파일 또는 secret store에만 두고 Git, Slack, 보고서에 적지 않는다.
- 특정 모델명과 가격은 API pilot TEST-SHEET를 동결할 때 OpenAI 공식 문서로 다시 확인한다.
- production 전 300건 이하의 versioned pilot으로 행동별 품질, abstain, latency, 실제 token과
  비용을 측정한다.
- pilot 통과 전 DB의 사람 GT, 사용자 타임라인, 자동 알림을 OpenAI 결과로 변경하지 않는다.

## 9. 실행 단계와 완료 기준

### Phase 1 — 정본 재정렬

- active SOT 어디에서도 local VLM·router·자동 사건 묶기·Claude CLI를 다음 단계로 안내하지 않는다.
- 실패 연구는 archive index와 중단 사유로 찾을 수 있다.

### Phase 2 — Dataset v2 준비

- legacy 197개가 hash로 고정된다.
- 최근 Owner-final GT 후보의 자격검사와 class/multi-action/camera-night 분포 보고서가 나온다.
- Dataset v2 manifest schema와 validator가 통과한다.
- future holdout은 아직 모델에 노출되지 않는다.

### Phase 3 — 기기 정리

- 삭제 전·후 disk usage와 service/worktree 상태가 기록된다.
- 연구 전용 서비스·모델·캐시는 두 기기에서 제거된다.
- production capture, DB/R2, 라벨링 웹, 사람 GT에는 write 0 또는 기능 변화 0이 검증된다.

### Phase 4 — OpenAI API pilot

- key 존재 여부만 preflight하고 값을 출력하지 않는다.
- 모델·prompt·입력 정책·예산·성공 기준을 동결한 뒤 별도 승인을 받아 실행한다.
- 결과는 Dataset v2 GT와 분리된 prediction ledger와 성적표로 제출한다.

## 10. 안전·복구 계약

1. DB/R2 원본과 GT는 이 정리 작업에서 수정·삭제하지 않는다.
2. archive 검증 전 로컬 파일을 삭제하지 않는다.
3. production이 참조하는 서비스·repo·env는 의존성 확인 없이 제거하지 않는다.
4. dirty worktree와 사용자 변경은 자동 정리하지 않는다.
5. Git commit·push는 owner의 별도 명시 승인을 받는다.
6. 삭제 결과에는 삭제한 경로, 회수 용량, 복구 가능 여부를 남긴다.

## 11. R2 초기 영상 정리 계약

### 11.1 확인된 범위

한국시간 2026-06-30 00:00부터 2026-07-15 23:59:59까지 `motion_clips`는
11,629개이며 모두 R2 key가 있다. 현재 행동 GT 정본은 4개뿐이고 모두 폐기된 옛
`basking/static` 체계라 Dataset v2에는 재검수 없이 채택하지 않는다.

사건 경계 자격검사에서 Owner가 직접 무효로 확정한 46개는 다음 두 camera-day에만 있다.

- 게코 없음 23개: 2026-06-30의 한 camera-day
- 게코는 보이지만 실제 활동 없음 23개: 2026-07-14의 한 camera-day

두 camera-day 전체는 951개다. 이 중 확정 무효 46개와 canonical GT는 겹치지 않고,
canonical GT 1개가 별도로 포함돼 있다. 따라서 1차 wave는 `확정 삭제 46 + GT 보호 1 +
Owner 검수 904`로 고정한다.

### 11.2 물리 경로와 상태

R2의 폴더 표시는 key prefix다. 한 객체의 이동은 `copy → HEAD 검증 → DB key 교체 → 원본
delete → 원본 HEAD 404` 순서로 수행한다.

```text
현재 정상 prefix
research-quarantine/rba-owner-cleanup-v1/  # 검수 대기, 연구 사용 금지
research-excluded/rba-owner-cleanup-v1/    # 삭제 확정, 삭제 worker 대기
물리 삭제                                  # R2 객체 없음, DB 감사 원장만 유지
```

- 951개는 먼저 고정 manifest와 R2 `ETag + ContentLength + LastModified` object fingerprint
  preflight를 통과한 뒤 quarantine prefix로 옮긴다. 원본에 content SHA-256 metadata가 있으면
  함께 보존하되, 없는 객체를 전부 다운로드해 새 hash를 만들지는 않는다.
- 확정 무효 46개는 immutable Owner decision을 연결하고 excluded prefix를 거쳐 물리 삭제한다.
- canonical GT 1개는 삭제 버튼을 막고 현재 행동 체계로 재검수한다.
- 나머지 904개는 `keep / delete_gecko_absent / delete_no_activity / uncertain` 중 하나를
  Owner가 판정한다.
- `keep`은 원래 prefix로 복구하고 연구 격리를 해제한다.
- `delete_*`는 excluded prefix로 이동하고 감사 기록 뒤 물리 삭제한다.
- `uncertain`은 quarantine에 남으며 Dataset v2와 OpenAI API 입력에서 제외한다.

### 11.3 실수 방지

DB exclusion 원장이 R2 prefix보다 우선한다. quarantine 또는 deleted 상태는 라벨링 signed URL,
공용 library, Dataset v2 builder, OpenAI runner, 연구 sample query에서 모두 제외한다. service-role
스크립트도 공통 eligible view/RPC만 사용하고 `motion_clips`를 직접 읽어 표본을 만들지 않는다.

화면 유사도·camera-day·기존 motion 값은 검수 순서 정렬에만 쓸 수 있다. local VLM,
Python Evidence 또는 OpenAI 예측 하나로 자동 삭제하지 않는다. 신규 촬영분도 Owner가 `게코 없음`
또는 `실제 활동 없음`을 확정하면 같은 quarantine→delete 원장을 사용해 다시 적체되지 않게 한다.
