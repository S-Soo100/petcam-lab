# TEST-SHEET — Mac mini Local VLM Evidence Analyst

> **상태:** `DRAFT_PLAN_REVIEW` — 실행 금지. owner가 본 시험지를 검토·승인한 뒤 `PRE_REGISTERED` commit을 만들기 전에는 모델 설치·다운로드·inference를 하지 않는다.

## 0. 단 하나의 연구 질문

> Mac mini M1 16GB에서 SmolVLM2 2.2B MLX가 Python Evidence JSON과 deterministic global/ROI 6프레임을 입력받아, production worker를 방해하지 않으면서 사람 evidence GT와 일치하는 보조 관찰을 안정적으로 생성하는가?

통과해도 production 연결, 행동 GT, 자동 제외, selector, cloud 호출 차단은 허용되지 않는다.

## 1. 가설

- **H0:** runtime·완전성·자원·반복 일관성·fresh holdout 품질 중 하나 이상이 사전 기준을 충족하지 못한다.
- **H1:** 모든 gate를 충족해 `PASS_LOCAL_EVIDENCE_ANALYST`가 된다.

## 2. 동결 모델·runtime

| 항목 | 동결값 |
|---|---|
| runtime host | `baeg-endeuui-Macmini.local` |
| execution repo | `/Users/baek-end/petcam-rba-worker` |
| model repo | `mlx-community/SmolVLM2-2.2B-Instruct-mlx` |
| model revision | `844516024a1c4400d34489b89ee067d794e432ed` |
| upstream model revision | `482adb537c021c86670beed01cd58990d01e72e4` |
| model license | `Apache-2.0` |
| model repository storage | `4,493,651,795 bytes` (실제 snapshot download는 사전 설치 때 재측정) |
| MLX-VLM | `mlx-vlm==0.6.5` |
| wheel SHA-256 | `1cc3a8a12cd674bfe3bc7d64c8e511948baf6103240c5ba87585082a2a7da8aa` |
| Python | project Python 3.12 |
| temperature | `0.0` |
| max tokens | `256` |
| durable key당 generation | 정확히 1회, content/schema 실패 재호출 금지 |
| model server | 없음, segment one-shot process |
| network during measured run | `HF_HUB_OFFLINE=1`, R2 GET 외 모델 네트워크 0 |

Phase 1 synthetic smoke 1회는 240 measured inference에 포함하지 않는다. measured key 실패는 실패로 기록하며 같은 key를 품질 결과를 보고 다시 실행하지 않는다.

## 3. 입력 계약

clip마다 정확히 다음을 사용한다.

- Universal Python Evidence JSON 1개
- 전체 프레임 2장
- Gate read-only 재검출 evidence 프레임 4장: bbox union이 있으면 ROI, 없으면 같은 시점의 전체 프레임
- timestamp 오름차순
- benchmark preprocessing cap long edge 최대 384px, 종횡비 유지. model processor의 최대치가 아니라 이번 실험의 동결값이다.
- frame bytes·Python Evidence·prompt의 SHA-256

입력 materializer 규칙:

1. R2 clip은 segment 안에서 한 번만 다운로드한다.
2. 동결 Gate checkpoint로 선택 프레임 6장을 검출한다.
3. 최고 confidence gecko bbox들을 union하고 1.5배 padding 후 frame 경계로 clamp한다.
4. bbox가 없으면 중앙 crop 같은 가짜 ROI를 만들지 않고 같은 네 시점의 전체 프레임을 넣고 `roi_mode=full_frame_no_detection`을 기록한다. absent strata와 Gate false negative를 이 경로로 평가한다.
5. Gate를 unload하고 MLX cache를 정리한 뒤 local VLM을 load한다.
6. 원본 mp4·frame·ROI는 segment 종료 시 모두 삭제한다.

Gate provenance는 checkpoint SHA, threshold, sampler, code HEAD를 기록한다. durable prelabel의 단일 `gecko_bbox`를 union이라고 사용하지 않는다.

## 4. 출력 계약

prompt version은 `local-evidence-analyst-v1`이다. 출력은 markdown fence 없는 JSON object 하나여야 한다.

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
  "observation": "240자 이하 관찰 문장"
}
```

다음 토큰이 `observation`에 나타나면 `semantic_policy_violation`이다.

`basking`, `drinking`, `playing`, `shedding`, `feeding`, `moving`, `unseen`, `highlight`, `skip`, `cloud_now`, `cloud_later`

모델의 raw reasoning은 저장하지 않는다. 반환 text 전체는 Git 제외 raw JSONL에만 저장하고 최대 4KB로 제한한다.

## 5. 표본과 blind 계약

### 5.1 고유 180개

| strata | dev | fresh holdout | 합계 |
|---|---:|---:|---:|
| 게코 없음·안 보임 | 20 | 10 | 30 |
| 큰 이동 | 20 | 10 | 30 |
| 휴식·국소 미세 움직임 | 20 | 10 | 30 |
| 핥기·물·먹이 관련 | 20 | 10 | 30 |
| 쳇바퀴·사물 상호작용 | 20 | 10 | 30 |
| 가림·구석·IR·그림자 hard case | 20 | 10 | 30 |
| **합계** | **120** | **60** | **180** |

- 같은 카메라 30분 이내 유사 clip은 한 episode로 묶어 1개만 사용한다.
- 카메라 2대 이상, 촬영일 3일 이상이어야 한다.
- 같은 clip 중복 0, dev/holdout clip·episode 교집합 0이어야 한다.
- strata별 필요한 수를 중복이나 synthetic 영상으로 채우지 않는다.
- holdout GT는 local model 결과를 보기 전에 완료하고 hash를 동결한다.

### 5.2 반복 60회

holdout에서 strata별 5개, 총 30개를 고정한다. 기본 실행을 포함해 clip당 총 3회다.

- 기본 measured keys: 180
- 반복 추가 keys: 30 × 2 = 60
- 총 measured keys: **240**

반복 key는 input bytes·prompt·model revision이 동일해야 한다. 실행 순서는 seed `20260721`로 섞고, 같은 clip의 3회가 연속하지 않게 한다.

## 6. 사람 evidence GT

평가자는 local model 출력과 Python/Gate evidence를 보지 않고 원본 영상만 본다.

- `presence_observation`
- `visibility`
- `motion_extent`
- body region 복수 선택
- object 복수 선택
- `human_uncertain`
- 이유 1문장

정의:

- `none`: 관찰 가능한 신체 움직임과 몸 중심 이동 없음
- `micro_local`: 몸 중심 이동 없이 머리·꼬리·사지 등 국소 움직임
- `body_translation`: 몸통 또는 몸 중심 위치가 시간에 따라 이동
- `uncertain`: 가림·IR·영상 품질 때문에 구분 불가

행동 GT는 strata 구성에만 사용하고, 없는 coarse evidence 값을 행동 label에서 추측하지 않는다.

## 7. 실행 전 체크리스트

### A. Git·handoff

- [ ] design·plan·TEST-SHEET가 tracked commit에 포함됨
- [ ] 위 commit이 origin에 push됨
- [ ] petcam-lab / petcam-rba-worker / gecko-vision-gate HEAD 40자리 기록
- [ ] `verify_agent_handoff.py` 결과가 `HANDOFF_OK`
- [ ] 세 execution worktree clean

### B. 표본·GT

- [ ] 180 unique clips
- [ ] 6 strata 각각 30
- [ ] dev 120 / fresh holdout 60
- [ ] camera ≥2 / capture date ≥3
- [ ] 30분 episode dedup 위반 0
- [ ] dev↔holdout clip/episode leakage 0
- [ ] evidence GT completeness 180/180
- [ ] manifest·GT SHA-256 기록

### C. Mac mini runtime

- [ ] hostname 정확히 `baeg-endeuui-Macmini.local`
- [ ] M1 / 16GB / free disk ≥20GB
- [ ] `/Users/baek-end/petcam-rba-worker` HEAD 일치
- [ ] `/Users/baek-end/myPythonProjects/gecko-vision-gate` HEAD 일치
- [ ] `/Users/baek-end/petcam-lab` HEAD 일치
- [ ] `mlx-vlm==0.6.5` wheel hash 일치
- [ ] model revision·snapshot hash 일치
- [ ] measured run 시작 전 model snapshot 완전 다운로드
- [ ] activity/VLM shared locks 획득 가능
- [ ] 기존 LaunchAgent 스케줄 snapshot 기록
- [ ] memory pressure critical 아님
- [ ] temp baseline 0

### D. 안전·쓰기 범위

- [ ] Supabase SELECT only
- [ ] R2 GET only
- [ ] behavior/GT/app/selector/Python Evidence DB write 0
- [ ] Slack 발송 0
- [ ] LaunchAgent/plist/env 변경 0
- [ ] model server 상주 0
- [ ] raw media·secret Git 기록 0

## 8. 즉시 중단 조건

다음 중 하나면 새 key를 시작하지 않고 현재 clip cleanup 후 종료한다.

- hostname·repo HEAD·model revision 불일치
- activity 또는 VLM lock 획득 실패
- 다음 scheduled worker까지 안전 여유 10분 미만
- memory pressure critical
- process RSS 8GiB 초과
- swap이 segment baseline보다 1GiB 초과 증가 후 유지
- temp cleanup 실패
- production worker nonzero exit 또는 deadline 지연
- DB/R2 write 탐지
- secret/raw URL 로그 노출
- manifest·GT·input hash 불일치

운영 안전 위반은 결과가 좋아도 `REJECT_RESOURCE` 또는 `REJECT_INTEGRITY`를 우선한다.

## 9. 측정 지표와 계산

### 9.1 완전성

- expected durable keys = 240
- completed success, error, missing, unexpected, duplicate
- successful JSON schema rate
- semantic policy violation count

### 9.2 성능·자원

- model load seconds
- input materialization p50/p95
- generation p50/p95
- end-to-end p50/p95
- capacity = `3600 / e2e_p95`
- projected 4-camera p95 clips/hour 대비 배수
- process peak RSS, MLX peak memory, swap delta, temp peak

### 9.3 품질

- presence confusion matrix, macro F1, present recall
- visibility weighted F1
- motion_extent confusion matrix, macro F1
- object top-k recall
- abstain rate와 non-abstain accuracy
- strata별 위 지표
- `roi_mode=union_roi|full_frame_no_detection`별 위 지표와 실제 present recall
- 정확도/recall에는 Wilson 또는 bootstrap 95% CI를 함께 기록

### 9.4 반복

30개 clip에서 categorical field exact match 여부를 계산한다. 3회 중 하나라도 다르면 해당 clip은 불일치다.

## 10. 사전 통과 기준

| 영역 | 기준 |
|---|---|
| 기본 완료율 | ≥99% |
| 성공 응답 schema | 100% |
| duplicate/unexpected | 0 |
| 반복 exact consistency | ≥95% |
| peak RSS | ≤8GiB |
| sustained swap 증가 | ≤1GiB |
| temp 잔존 | 0 |
| worker 오류·지연 | 0 |
| capacity | projected 4-camera p95의 ≥2배 |
| presence macro F1 | ≥0.85 |
| actual-present recall | ≥0.95 |
| visibility weighted F1 | ≥0.80 |
| motion_extent macro F1 | ≥0.75 |
| object top-k recall | ≥0.75 |

## 11. verdict 우선순위

1. `BLOCKED_RUNTIME_DRIFT`
2. `BLOCKED_DATA_INSUFFICIENT`
3. `REJECT_INTEGRITY`
4. `REJECT_RESOURCE`
5. `REJECT_RELIABILITY`
6. `REJECT_QUALITY`
7. `PASS_LOCAL_EVIDENCE_ANALYST`

정확히 하나만 선택한다. PASS도 production 연결 승인이 아니다.

## 12. 결과 저장

Tracked:

- `experiments/local-vlm-evidence-analyst/TEST-SHEET.md`
- `experiments/local-vlm-evidence-analyst/manifest.json`
- `experiments/local-vlm-evidence-analyst/summary.json`
- `experiments/local-vlm-evidence-analyst/REPORT.md`
- 독립 재계산 script

Git 제외:

- `storage/local-vlm-evidence-analyst/raw_results.jsonl`
- mp4·global frame·ROI frame
- model cache
- raw stdout/stderr

REPORT에는 raw SHA-256, record 수, model snapshot SHA, 실행 HEAD만 기록한다.
