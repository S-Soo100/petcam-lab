# Mac mini Local VLM Evidence Analyst 벤치마크 설계

> **상태:** owner 설계 승인 / 구현·설치·실행 전 문서 검토 단계
>
> **결정:** `BENCHMARK_APPROVED` — Mac mini에서 소형 멀티모달 모델이 Python Evidence와 선택 프레임을 함께 읽어 **보조 관찰**을 만들 수 있는지 shadow로 검증한다.
>
> **절대 경계:** local VLM은 행동 GT, 자동 제외, cloud 호출 차단, production selector 결정을 하지 않는다.

## 1. 목적

다음 두 질문을 분리해 검증한다.

1. Apple M1 16GB Mac mini가 기존 background worker를 방해하지 않고 2~4B급 양자화 멀티모달 모델을 운영할 수 있는가?
2. local VLM이 Python/OpenCV/Gate만으로는 직접 표현하기 어려운 가시성·가림·움직임 범위·사물 후보를 사람 GT와 일치하는 보조 evidence로 만들 수 있는가?

이번 실험은 cloud VLM 대체 실험이 아니다. 통과하더라도 얻는 결론은 `LOCAL_EVIDENCE_ANALYST_FEASIBLE`까지다. Claude VLM 정확도 개선이나 토큰 절감은 후속 paired 실험에서 별도로 증명한다.

## 2. SOT 관계와 과거 실패와의 구분

### 2.1 부합하는 현재 SOT

- 모든 `motion_clips`는 먼저 Universal Python Evidence를 거친다.
- Gate는 bbox·presence 후보·provenance를 제공하는 evidence sensor다.
- Mac mini는 local VLM 비교와 shadow side worker 연구에 사용할 수 있다.
- 사람 blind GT가 모델 출력보다 우선한다.

### 2.2 되살리지 않는 설계

과거 local router v0/v1/v2는 local text LLM이 약한 metadata JSON을 읽고도 거의 모든 영상을 `cloud_now`로 보내 비용을 줄이지 못했다. local VLM 단독 7-class 행동 분류도 collapse 이력이 있다.

이번 실험은 다음 점에서 다르다.

- text-only JSON 대신 선택된 **실제 프레임과 ROI**를 함께 본다.
- 최종 행동 class를 고르지 않는다.
- `skip`, `auto_moving`, `auto_p0`, `cloud_now/later`를 출력하지 않는다.
- production DB와 selector에 결과를 쓰지 않는다.
- abstain을 정상 출력으로 인정한다.

## 3. Mac mini 실행 전 재확인할 baseline

2026-07-21 read-only 감사에서 확인한 값은 다음과 같다.

- host: `baeg-endeuui-Macmini.local`
- Apple M1 / unified memory 16GB / CPU 8 cores
- PyTorch MPS built·available
- audit 시 memory pressure 여유, swap 약 2.67GB 사용 이력
- local VLM runtime(MLX-VLM/Ollama)은 미설치
- Python Evidence, activity, VLM candidate, historical backfill, reporter, router-features가 같은 host에서 실행

이 값은 실행 직전에 다시 측정한다. hostname, RAM, free disk, memory pressure, swap, LaunchAgent 목록·스케줄, repo HEAD가 다르면 실행하지 않고 `BLOCKED_RUNTIME_DRIFT`로 종료한다.

## 4. 검토한 접근

### A. SmolVLM2 2.2B MLX + MLX-VLM — 채택

- Apple Silicon 전용 MLX 생태계를 사용한다.
- 6장의 multi-image 입력과 JSON structured output을 검증한다.
- Apache-2.0 라이선스라 상용 제품 연구에 사용할 수 있다.
- MLX 변환 repository storage는 약 4.49GB이고 16GB Mac mini에서 one-clip-at-a-time 실행 가능성을 검증할 수 있다. 실제 snapshot download bytes는 설치 preflight에서 다시 기록한다.
- 모델 revision과 MLX-VLM version을 고정한다.

### B. Gemma 3 4B + Ollama — 조건부 비교군

- 설치와 운영은 단순하지만 Ollama server 상주 비용과 MLX 대비 처리량을 별도로 확인해야 한다.
- A가 resource·reliability·quality gate 중 하나를 실패할 때만 같은 표본으로 실행한다.

### C. Qwen2.5-VL 3B 4-bit — 라이선스 해소 전 사용 금지

- 기술적으로는 multi-image 후보지만 원본 3B 모델의 Qwen Research License는 비상업 연구만 허용한다.
- Qwen의 별도 상용 허가를 서면으로 확보하기 전에는 다운로드·실행·비교군 사용을 하지 않는다.

처음부터 A/B/C를 모두 실행하지 않는다. 1차 실행은 A 하나로 총 240 inference를 수행한다.

참고:

- MLX: <https://github.com/ml-explore/mlx>
- MLX-VLM: <https://github.com/Blaizzy/mlx-vlm>
- Gemma 3 Ollama: <https://ollama.com/library/gemma3>
- SmolVLM2: <https://huggingface.co/HuggingFaceTB/SmolVLM2-2.2B-Instruct>
- SmolVLM2 MLX: <https://huggingface.co/mlx-community/SmolVLM2-2.2B-Instruct-mlx>
- Qwen2.5-VL-3B license reference: <https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct>

## 5. 역할과 출력 계약

### 5.1 입력

clip마다 다음만 전달한다.

- Universal Python Evidence JSON
- 전체 화면 대표 프레임 2장
- 선택한 프레임에 Gate를 read-only로 다시 적용해 만든 evidence 프레임 4장: bbox union이 있으면 ROI, 없으면 같은 시점의 전체 프레임
- 시간 순서와 timestamp
- 모델 입력 전 benchmark preprocessing cap으로 long edge 최대 384px, 원본 종횡비 유지. 이는 model processor의 최대치라는 주장이 아니라 이번 자원·품질 계약의 동결값이다.
- 모델 processor가 추가 resize하면 실제 effective size를 provenance에 기록

durable `clip_prelabels`에는 프레임별 bbox union이 아니라 단일 `gecko_bbox`만 저장되므로 이를 union이라고 재해석하지 않는다. 입력 materializer가 동결된 Gate checkpoint로 선택 프레임을 read-only 재검출하고 bbox union을 만든다. bbox가 하나도 없으면 중앙 crop 같은 가짜 ROI를 만들지 않고 같은 네 시점의 전체 프레임을 사용하며 `roi_mode=full_frame_no_detection`을 provenance에 남긴다. 이 fallback은 실제 absent clip과 Gate false negative를 모두 평가하기 위한 계약이다. Gate와 local VLM을 동시에 메모리에 올리지 않고, segment 입력 생성 후 Gate를 unload한 다음 local VLM을 load한다. 프레임 선택·ROI 생성은 deterministic Python 코드가 수행한다. local VLM이 Python 코드를 생성·실행하거나 임의 프레임을 다시 다운로드하지 않는다.

### 5.2 출력

temperature 0과 고정 JSON schema를 사용한다.

```json
{
  "schema_version": "local-evidence-analyst-v1",
  "presence_observation": "present|absent|uncertain",
  "visibility": "clear|partial|poor|none|uncertain",
  "motion_extent": "none|micro_local|body_translation|uncertain",
  "body_region_candidates": ["head|body|tail|whole|unknown"],
  "object_candidates": ["water_bowl|glass|wheel|branch|hide|feeding_tool|other|unknown"],
  "evidence_conflicts": ["string"],
  "abstain": true,
  "observation": "짧은 관찰 문장"
}
```

`observation`은 관찰 가능한 사실만 기록한다. `basking`, `drinking`, `playing`, `shedding`처럼 행동 의미를 확정하는 단어는 금지한다.

### 5.3 금지 출력과 소비처

- 행동 GT 또는 대표 행동 class
- highlight 포함·제외
- cloud 호출 여부나 우선순위
- 건강·케어 판단
- `behavior_labels`, GT, app activity, selector, Python Evidence 원장 쓰기

결과는 benchmark artifact JSONL에만 저장하고 production consumer는 0개로 유지한다.

## 6. 표본 계약

### 6.1 고유 영상 180개

| strata | development | fresh holdout | 합계 |
|---|---:|---:|---:|
| 게코 없음·안 보임 | 20 | 10 | 30 |
| 큰 이동 | 20 | 10 | 30 |
| 휴식·머리/꼬리 미세 움직임 | 20 | 10 | 30 |
| 핥기·물 마시기·먹이 관련 관찰 | 20 | 10 | 30 |
| 쳇바퀴·사물 상호작용 | 20 | 10 | 30 |
| 가림·구석·야간 IR·그림자 hard case | 20 | 10 | 30 |
| **합계** | **120** | **60** | **180** |

규칙:

- 30분 이내 같은 카메라의 유사 연속 clip은 하나의 episode로 보고 하나만 선택한다.
- 같은 clip을 strata 수를 채우기 위해 중복 사용하지 않는다.
- 전체 manifest는 카메라 2대 이상·촬영일 3일 이상을 포함한다.
- 가능한 경우 strata별 한 카메라 비중을 60% 이하로 제한한다. 불가능하면 편향을 숨기지 않고 별도 strata 통계로 보고한다.
- 특정 strata가 부족하면 다른 class로 대체하지 않고 `BLOCKED_DATA_INSUFFICIENT`로 기록한다.
- development 120개는 기존 사람 GT를 사용할 수 있다.
- holdout 60개는 모델 출력을 보기 전에 사람이 blind GT를 확정한다.
- 모델·prompt·입력 형식은 holdout 실행 전에 commit SHA로 동결한다.
- holdout 결과를 본 뒤 prompt나 threshold를 바꾸면 해당 holdout은 폐기하고 새로운 holdout이 필요하다.

### 6.2 반복 안정성 60회 추가

holdout에서 strata별 5개씩 총 30개를 고정한다. 각 clip은 기본 실행을 포함해 총 3회 실행한다.

- 고유 영상 기본 실행: 180회
- 30개 clip의 추가 실행: 30 × 2 = 60회
- **총 local VLM inference: 240회**

반복 실행의 모델 revision, prompt, frame bytes, Python Evidence JSON은 byte-identical이어야 한다.

### 6.3 사람 evidence GT

행동 GT만으로는 `motion_extent`, `visibility`, body region을 모두 채점할 수 없다. 따라서 evaluator는 local model 출력과 Python Evidence를 보지 않은 상태에서 원본 영상을 보고 다음 축을 별도 worksheet에 기록한다.

- `presence_observation`
- `visibility`
- `motion_extent`
- 움직인 body region 복수 선택
- 실제 접촉하거나 상호작용한 object 복수 선택
- 판정 불가 여부와 짧은 이유

정의:

- `none`: 관찰 가능한 신체 움직임과 몸 중심 이동이 없음
- `micro_local`: 몸 중심 이동 없이 머리·꼬리·사지 등 국소 부위만 움직임
- `body_translation`: 몸통 또는 몸 중심 위치가 시간에 따라 이동
- `uncertain`: 가림·IR·프레임 품질 때문에 위 셋을 구분할 수 없음

기존 GT는 development manifest 구성과 행동 strata 확인에 재사용할 수 있지만, 없는 coarse evidence 값을 추측으로 채우지 않는다. holdout worksheet는 model/prompt freeze 이전에 schema만 고정하고, 각 clip 값은 local model 결과를 보기 전에 완료한다. `observation` 자유문장은 정량 채점하지 않는다.

## 7. 실행 순서

### Phase 0 — read-only preflight

1. production clip 유입량을 카메라별·시간대별로 측정한다.
2. projected 4-camera p95 clips/hour를 동결한다.
3. Mac mini host·memory·swap·disk·LaunchAgent·lock·repo HEAD를 기록한다.
4. 모델 license, revision SHA, runtime version, 예상 download size를 기록한다.
5. 180개 manifest와 GT completeness를 검사한다.
6. 결과 디렉터리 `experiments/local-vlm-evidence-analyst/`의 `TEST-SHEET.md`를 작성하고 owner 승인 후 잠근다.

### Phase 1 — runtime safety preflight

전체 benchmark와 별개의 합성/비평가 clip으로 model load 1회와 inference 1회를 수행한다.

- 잘못된 host면 fail-closed
- 모델 load 실패·OOM·schema 실패면 benchmark 미착수
- production DB write 0
- temp cleanup 0건 확인

### Phase 2 — development 120개

- one clip at a time
- deterministic frame/input hash 기록
- local JSONL append + fsync
- clip 실패를 격리하고 다음 clip 진행
- 중단 후 재개 시 성공한 identity를 중복 실행하지 않음

이 단계에서는 prompt 구조 오류와 schema 오류만 수정할 수 있다. 품질을 보고 class별 문구를 임의 튜닝하려면 변경 내용을 기록하고 development를 처음부터 다시 실행한다.

### Phase 3 — 설정 동결

model revision, runtime, prompt, schema, sampler, resize, Python Evidence version을 TEST-SHEET에 고정하고 commit한다.

### Phase 4 — fresh holdout 60개 + 반복 60회

동결한 설정으로만 실행한다. 결과 후 수정은 금지한다.

### Phase 5 — 독립 재계산과 보고

harness를 import하지 않는 별도 script가 manifest 수, inference 수, hash, completion, latency, resource, accuracy, repeat consistency를 재계산한다. 두 계산이 다르면 `REJECT_INTEGRITY`다.

정본 산출물은 다음으로 제한한다.

- `TEST-SHEET.md`: 실행 전 동결 계약
- `manifest.json`: clip 식별자·strata·episode·GT completeness, 원본 media 없음
- `REPORT.md`: 결과와 verdict
- `summary.json`: 독립 재계산 가능한 집계값
- raw inference JSONL: `storage/local-vlm-evidence-analyst/`에만 저장하고 Git 제외, SHA256만 보고서에 기록

## 8. Mac mini 안전 운영 계약

- persistent model server나 LaunchAgent를 설치하지 않는다.
- benchmark 전용 one-shot process로 실행하고 segment 종료 시 모델을 unload한다.
- `EXPECTED_HOST=baeg-endeuui-Macmini.local`을 fail-closed로 검사한다.
- 기존 Gate/Python Evidence/VLM과 같은 shared resource lock을 사용한다.
- 실행 직전 live LaunchAgent 스케줄을 다시 읽고 겹치지 않는 segment만 사용한다.
- scheduled worker deadline 전에 안전 여유가 부족하면 새 clip을 시작하지 않는다.
- 임시 프레임은 전용 temp directory에 만들고 성공·실패·signal 종료 모두에서 정리한다.
- 원본 mp4와 frame bytes는 Git·DB·일반 로그에 저장하지 않는다.
- peak RSS, memory pressure, swap delta, disk, process exit, 기존 worker 지연을 매 segment 기록한다.
- secret, RTSP URL, raw model stderr/stdout은 artifact에 기록하지 않는다.

## 9. 사전 등록할 성공 기준

### 9.1 무결성·신뢰성

- manifest 고유 clip 180개, episode 중복 0
- 기본 inference 완료율 ≥99%
- 성공 inference의 JSON schema 통과율 100%
- silent missing·unexpected clip·duplicate identity 0
- 독립 재계산과 harness 수치 완전 일치
- 반복 30개의 categorical field exact consistency ≥95%

### 9.2 자원·운영

- OOM, kernel kill, worker crash 0
- local VLM process peak RSS ≤8GiB
- 실행 전후 sustained swap 증가 ≤1GiB
- temp media 잔존 0
- 기존 LaunchAgent nonzero exit 증가 0
- 기존 scheduled worker deadline 지연 0
- measured sustained capacity ≥ projected 4-camera p95 clips/hour의 2배

### 9.3 보조 evidence 품질

fresh holdout 60개에서 측정한다.

- `presence_observation` macro F1 ≥0.85
- 실제 present clip recall ≥0.95
- `visibility` weighted F1 ≥0.80
- `motion_extent` macro F1 ≥0.75
- object가 실제 존재하는 strata에서 `object_candidates` top-k recall ≥0.75
- hard-case strata에서 non-abstain을 억지로 늘리지 않는다. abstain rate를 별도 보고하고 정확도와 함께 해석한다.

위 품질 기준은 production 자동화 승격 기준이 아니다. local evidence가 사람 관찰과 최소한 일치하는지를 거르는 연구 기준이다.

## 10. verdict

우선순위대로 하나만 선택한다.

1. `BLOCKED_RUNTIME_DRIFT` — host·환경·스케줄이 설계와 다름
2. `BLOCKED_DATA_INSUFFICIENT` — 180개 독립 strata manifest를 만들 수 없음
3. `REJECT_INTEGRITY` — 결과 완전성·독립 재계산 불일치
4. `REJECT_RESOURCE` — memory·throughput·worker interference 실패
5. `REJECT_RELIABILITY` — completion·schema·repeat consistency 실패
6. `REJECT_QUALITY` — fresh holdout evidence 품질 실패
7. `PASS_LOCAL_EVIDENCE_ANALYST` — 모든 gate 통과

`PASS_LOCAL_EVIDENCE_ANALYST`도 production 배포 승인이 아니다.

## 11. 통과 후 별도 연구

통과한 경우에만 새 decision-gate와 별도 TEST-SHEET로 다음을 비교한다.

- control: 현재 Claude VLM 입력
- treatment: 동일 입력 + local evidence JSON
- 사람 GT 대비 Claude 행동 판정 정확도 변화
- Claude 입력 이미지·토큰·실행시간·호출량 변화
- recovered clip과 newly broken clip

`recovered > broken`, 비용 또는 처리량 이득, fresh holdout 안전성을 모두 증명하기 전에는 local evidence를 production Claude prompt나 selector에 연결하지 않는다.

## 12. 현재 승인 범위

승인됨:

- 본 설계와 TEST-SHEET/구현계획 작성
- Mac mini read-only preflight 설계
- 고유 180개·총 240 inference benchmark
- SmolVLM2 2.2B MLX + MLX-VLM 1차 후보

아직 승인되지 않음:

- 모델/runtime 설치와 다운로드
- Mac mini benchmark 실행
- LaunchAgent 설치
- production DB migration/write
- local evidence의 selector·Claude·앱 연결
- 행동 자동 라벨·자동 제외·cloud 호출 차단
