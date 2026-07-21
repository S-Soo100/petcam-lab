# Mac mini Local VLM Evidence Analyst 계획 검수 보고서

> **판정:** `PLAN_CONDITIONALLY_VALID`
>
> **범위:** 설계·시험지·결과 양식·Mac mini read-only 사실 검수만 수행했다. 모델 설치·다운로드·추론·production write는 수행하지 않았다.

## 1. 검증하려는 내용

이 계획은 다음 두 질문만 검증한다.

1. Mac mini M1 16GB에서 소형 local VLM을 기존 worker와 충돌 없이 one-shot으로 실행할 수 있는가?
2. Python Evidence와 deterministic 6프레임을 읽은 local VLM이 행동 label이 아닌 `presence`, `visibility`, `motion_extent`, body region, object 후보를 사람 evidence GT와 일치하게 만들 수 있는가?

다음은 이번 실험으로 검증하지 않는다.

- cloud VLM 대체·호출 차단·토큰 절감
- 행동 GT·하이라이트·자동 제외·selector 결정
- production 상시 worker·LaunchAgent
- Qwen 상용 사용 가능성

## 2. 계획 결함 감사와 조치

| # | 발견 | 위험 | 조치 | 상태 |
|---|---|---|---|---|
| 1 | Qwen2.5-VL 3B 원본이 비상업 연구 라이선스 | 상용 제품 연구에서 라이선스 위반 | Apache-2.0 `SmolVLM2-2.2B-Instruct-mlx`로 1차 후보 변경, Qwen 사용 금지 | 해소 |
| 2 | durable `clip_prelabels`는 프레임별 bbox union을 보유하지 않음 | 단일 bbox를 union처럼 쓰면 ROI 입력 계약이 거짓 | 선택 6프레임에 Gate를 read-only 재적용해 union 생성 | 해소 |
| 2a | bbox 없음 자체를 input failure로 처리하면 absent 30개와 Gate false negative를 평가할 수 없음 | presence 연구 질문이 표본 계약과 모순 | bbox 없음은 같은 네 시점의 전체 프레임을 사용하고 `full_frame_no_detection` provenance 기록 | 해소 |
| 3 | Gate와 MLX 동시 상주 가능성 | M1 16GB memory pressure·swap 증가 | 입력 segment를 먼저 만들고 Gate unload 후 MLX load | 해소 |
| 4 | raw 결과 경로가 tracked artifact와 혼동될 수 있음 | 원본/모델 출력 실수 커밋 | raw는 `storage/local-vlm-evidence-analyst/`만 사용 | 해소 |
| 5 | strict JSON은 모델이 보장하지 않음 | parser가 관대한 보정을 하면 품질 과대평가 | JSON object 1개만 허용, content/schema retry 0, 실패로 집계 | 해소 |
| 6 | 기존 행동 GT만으로 coarse evidence 채점 불가 | 행동 label에서 visibility·motion을 추측 | 별도 사람 evidence GT worksheet 180/180 요구 | 해소 |
| 7 | Mac mini에 worker 6종이 공존 | benchmark가 운영 worker 지연 가능 | VLM→activity 순서 dual lock, 스케줄 snapshot, 10분 deadline, segment one-shot | 해소 |
| 8 | 작은 표본의 point metric만 보면 불안정 | 우연한 PASS 가능 | fresh holdout 60, strata 표, 95% CI, 반복 30×3 | 해소 |
| 9 | 현재 MLX runtime 미설치 | 지금 즉시 실행 불가 | 설치는 별도 owner 승인 뒤, wheel/model SHA 확인 | 조건 |
| 10 | holdout evidence GT가 아직 준비되지 않음 | blind 품질 검증 불가 | 180 manifest·GT 완성 전 runtime 실행 금지 | 조건 |

추가 한계: 이 1차 benchmark는 `Python Evidence + Gate frame + local VLM` 합성 시스템의 feasibility를 검증한다. Python Evidence JSON의 **인과적 증분 효과**를 frames-only arm과 분리해 증명하지는 않는다. PASS 후 control/treatment paired 실험에서 따로 검증하며, 이번 결과로 “Python JSON 때문에 정확해졌다”고 단정하지 않는다.

## 3. read-only 사실 검증

### Mac mini

- hostname: `baeg-endeuui-Macmini.local`
- architecture: `arm64`
- runtime repo: `/Users/baek-end/petcam-rba-worker`
- runtime repo HEAD: `c2249af7b902d20fba62fb1f15c89e342a5a11b4`
- MLX-VLM/Ollama: 미설치
- `uv`: `/Users/baek-end/.local/bin/uv`, `/opt/homebrew/bin/uv` 존재; non-login PATH 의존 금지
- free disk: 약 85GiB
- swap 사용 이력: 약 2.67GiB
- activity·VLM lock 존재, 여러 LaunchAgent가 같은 host에서 정상 운용 중

### 모델·runtime

- `mlx-vlm==0.6.5`, Python 3.10~3.12 지원
- wheel SHA-256: `1cc3a8a12cd674bfe3bc7d64c8e511948baf6103240c5ba87585082a2a7da8aa`
- model: `mlx-community/SmolVLM2-2.2B-Instruct-mlx`
- model revision: `844516024a1c4400d34489b89ee067d794e432ed`
- upstream revision: `482adb537c021c86670beed01cd58990d01e72e4`
- license: Apache-2.0
- repository storage: 4,493,651,795 bytes

모든 값은 실행 직전 다시 조회한다. drift가 있으면 자동 갱신하지 않고 `BLOCKED_RUNTIME_DRIFT`다.

## 4. 검증 방법 적합성

| 검증 축 | 방법 | 왜 유효한가 |
|---|---|---|
| 데이터 독립성 | 30분 episode dedup, 2 cameras, 3 dates, dev/holdout 교집합 0 | 인접 clip 복제로 점수가 부풀어 오르는 것을 막음 |
| blind 품질 | holdout 60개의 evidence GT를 출력 열람 전에 동결 | prompt·모델 결과가 사람 판단에 주는 편향 차단 |
| 안정성 | holdout 30개를 byte-identical 입력으로 총 3회 | temperature 0이어도 생길 수 있는 runtime 비결정성 측정 |
| 무결성 | expected measured key 240, duplicate/missing/unexpected 0 | 성공한 것만 골라 보고하는 문제 차단 |
| 자원 | RSS·MLX peak·swap·temp·worker exit/deadline 전후 비교 | 같은 Mac mini의 실제 운영 간섭 측정 |
| 처리량 | e2e p95로 clips/hour 계산, projected 4-camera p95의 2배 요구 | 평균이 아닌 peak 운영 여유 검증 |
| 재현성 | model/runtime/Gate/repo/input/prompt SHA 기록 | 결과를 어떤 코드·입력으로 만들었는지 추적 가능 |
| 독립 검산 | runner를 import하지 않는 별도 scorer | 구현과 검산이 같은 버그를 공유할 위험 축소 |

## 5. 결과 양식 적합성

`REPORT-TEMPLATE.md`는 다음을 강제한다.

- exact verdict 하나
- 세 레포 HEAD와 model/Gate/input provenance
- 표본·key 완전성
- schema·semantic violation
- latency·capacity·RSS·swap·temp
- fresh holdout point metric + 95% CI + confusion matrix
- 반복 consistency
- production write·worker 지연·temp·secret 안전 증거
- harness와 독립 검산 일치 여부

빈 필드가 있으면 최종 verdict를 쓰지 않는다.

## 6. 남은 실행 전 조건

- [ ] owner가 수정된 `TEST-SHEET.md`를 승인해 `PRE_REGISTERED`로 전환
- [ ] design·plan·TEST-SHEET·report template이 commit·push됨
- [ ] 180 unique manifest와 evidence GT 180/180 완성
- [ ] holdout 60의 blind 완료·hash 동결
- [ ] 구현 레포 3개의 40자리 SHA가 handoff manifest에 기록됨
- [ ] `verify_agent_handoff.py`가 Mac mini에서 `HANDOFF_OK`
- [ ] owner가 MLX-VLM 설치와 약 4.5GB model snapshot 다운로드를 별도로 승인

## 7. 최종 판단

계획의 연구 질문, 통제 경계, 표본 수, 품질·자원 gate, 결과 양식은 서로 정합한다. 다만 라이선스 정정 전 Qwen 계획은 유효하지 않았으며, 수정 후에도 데이터·handoff·설치 승인이 없으므로 지금 실행 가능한 상태는 아니다.

따라서 판정은 `PLAN_CONDITIONALLY_VALID`다. 다음 허용 작업은 구현계획에 따른 **harness 구현과 dry test**까지이며, Mac mini 모델 설치·다운로드·240회 실행은 별도 승인 전 금지한다.
