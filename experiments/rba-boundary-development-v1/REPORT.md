# RBA 사건 경계 Development 분석 v1 결과

**실행일:** 2026-08-02

**GT 판정:** `DEVELOPMENT_EVENT_GT_READY_FOR_LOCAL_VLM_BASELINE`

**시간 규칙 utility 판정:** `EVENT_GT_READY_ROUTER_UTILITY_HOLD`

## 한 줄 결론

사람이 확정한 74개 경계로 78개 영상을 21개 사건으로 안전하게 묶는 GT는 만들었지만, 시간 간격만으로 같은 결과를 안전하게 자동화하는 규칙은 아직 채택할 수 없어.

## 연구 목표와 단계

1. 74개 유효 경계의 배정·제출·Owner 해결 이력이 완전한지 확인한다.
2. 두 검수자의 최초 판단 특성과 Owner 개입량을 계산한다.
3. 합의 또는 Owner 최종 결정을 따라 사람 사건 GT를 만든다.
4. `0/5/15/30/60/120초` 시간 규칙을 사람 GT와 비교한다.
5. 같은 salt로 입력 순서를 바꿔 3회 계산하고 결과 hash가 같은지 확인한다.

## 입력 무결성

| 항목 | 결과 |
|---|---:|
| 전체 pair row | 120 |
| 유효 경계 | 74 |
| assignment | 148 |
| submission | 148 |
| Owner resolution | 26 |
| 최종 uncertain | 0 |
| 결정론 재계산 | 3/3 동일 |

고정 입력은 `experiment_id=rba-event-sequence-review-v2`, 동결 manifest digest `edd3f2c230adacb70c0b8bc70072eb632eb0ac48718bdd1ffbeca88649e9dfca`다.

## 사람 판단 결과

| 지표 | 결과 |
|---|---:|
| 두 검수자 최초 일치율 | 64.86% |
| Cohen's kappa | 0.2645 |
| 최초 uncertain 제출 | 4/148, 2.70% |
| Owner 최종 개입 | 26/74, 35.14% |
| Owner 최초 판단 채택 | 17/26, 65.38% |
| 최종 same_event | 57 |
| 최종 different_event | 17 |
| 최종 uncertain | 0 |

최초 판단 confusion matrix는 행이 Owner, 열이 Peer이며 순서는 `same_event / different_event / uncertain`이야.

| Owner \ Peer | same | different | uncertain |
|---|---:|---:|---:|
| same | 39 | 21 | 4 |
| different | 1 | 9 | 0 |
| uncertain | 0 | 0 | 0 |

일치율과 kappa는 사람 판단 난도를 설명하는 기술 통계일 뿐, GT 채택 gate로 사용하지 않았어. 불일치·uncertain 26개는 전부 Owner 최종 결정으로 닫혔고 최종 uncertain은 0개야.

방향 편향도 있어. Owner 최초 판단은 `same_event 64/74(86.49%)`, Peer는 `40/74(54.05%)`였고, 최종값은 `57/74(77.03%)`로 Owner 쪽 성향에 더 가까워졌어. Owner가 자신이 참여한 최초 판단을 다시 최종 해결했고 그 판단이 17/26(65.38%) 채택됐으므로, 이 development GT에는 self-adjudication(본인 최초 답을 본인이 최종 결정함) 편향 가능성이 있어. 그래서 다음 local VLM baseline의 개발 정답으로는 쓰되 독립 future holdout이나 production 품질 증명으로 확대 해석하지 않아.

## 사건 묶음 효과

| 항목 | 결과 |
|---|---:|
| GT에 실제 포함된 고유 영상 | 78 |
| 사람이 확정한 사건 | 21 |
| 줄어든 사건 수 | 57 |
| 사건 수 감소율 | 73.08% |

즉 사용자에게 영상 78개를 따로 보여주는 대신, 사람 기준으로는 21개의 이어진 활동 사건으로 정리할 수 있어. 이 사건 GT는 다음 local VLM baseline의 입력 정답으로 사용할 준비가 됐다는 뜻이야.

## 시간 간격 규칙 평가

`over-merge`는 실제로 다른 사건을 잘못 합친 수, `over-split`은 같은 사건인데 나누어 둔 수야.

| threshold | over-merge | over-split | 해석 |
|---:|---:|---:|---|
| 0초 | 0 | 57 | 아무 사건도 자동 병합하지 않음 |
| 5초 | 0 | 57 | 문면상 안전 후보지만 병합 효과 0건인 no-op |
| 15초 | 0 | 57 | 문면상 안전 후보지만 병합 효과 0건인 no-op |
| 30초 | 2 | 51 | 6개를 더 묶지만 다른 사건 2개를 오병합 |
| 60초 | 6 | 18 | 39개를 더 묶지만 오병합 6개 발생 |
| 120초 | 12 | 9 | 오병합 12개 |

동결 선택 규칙은 over-merge 0을 먼저 요구하고, over-split이 같으면 더 낮은 threshold를 택하므로 선택값은 0초야. 5초·15초는 문면상 안전 후보지만 0초보다 over-split을 하나도 줄이지 못해 선택 규칙상 실용 threshold로 채택할 수 없어. utility PASS는 선택된 안전 threshold가 0초보다 크면서 실제 same 경계를 최소 1개 줄이는 경우를 뜻해. 따라서 사람 사건 GT는 채택하되 metadata-only 시간 router는 보류한다.

## 기대효과

- local VLM을 영상마다 무작정 부르는 대신, 사람 기준 사건 21개 단위로 baseline을 시험할 수 있어.
- “몇 초 이하면 같은 사건” 같은 단순 규칙이 왜 위험한지 실제 오병합 수로 알 수 있어.
- 두 사람만으로 경계를 만들 때 약 35%에서 Owner 최종 판단이 필요하다는 검수 비용 기준이 생겼어.
- 다음 연구는 행동 라벨과 섞지 않고, 이 사건 GT를 local VLM이 얼마나 재현하는지만 별도로 측정할 수 있어.

## 실행 체크리스트

- [x] pinned experiment/digest 일치
- [x] `120/74/148/148/26` exact count 일치
- [x] pair provenance·ordinal·gap bin 일치
- [x] float DB roundtrip 오차만 `abs_tol=1e-9`로 허용, `1e-6` 차단 테스트 통과
- [x] 유효 pair마다 서로 다른 Owner/Peer 2명과 제출 2개 확인
- [x] 필요한 resolution 집합과 실제 26개 exact 일치
- [x] 최종 uncertain 0
- [x] 세 번의 private/public hash 동일
- [x] 첫 실패 salt를 `0600`으로 재사용
- [x] private directory/file `0700/0600`, no-overwrite
- [x] public raw UUID·reviewer identity·reason·camera/date·secret 0
- [x] production DB write/RPC 0
- [x] R2/frame/Python Evidence/Gate/VLM/service 호출 0
- [x] historical holdout 미개방
- [x] local VLM baseline 미실행

## 실행 이력과 재현성

첫 one-shot은 DB와 manifest float 표현의 최대 `3.979039320256561e-13`초 차이를 exact 비교해 fail-closed됐다. ordinal·gap bin 불일치는 0이었고, `abs_tol=1e-9`, `rel_tol=0`과 `1e-6` 차단 테스트를 추가한 뒤 같은 salt로 재실행했다.

- runtime host: `mac-mini-runner` (공개 익명 라벨, exact host는 handoff manifest에만 보존)
- exact HEAD: `319a341b14e5711569be35fc7c2215c2dd37b007`
- handoff: `HANDOFF_OK`
- private payload SHA-256: `9225d29be5cea7aeed82ffae64b6eec7d4c789d93c50c408bdf102e040c7cb71`
- runner public report SHA-256: `91bfce4a60ab31bd6c99d4a671d3347b10b7dd20bfa95932bbd54395a2eb921a`
- production DB/R2/model/service mutation: 0

## 다음 행동

이 결과만으로 production router를 켜지 않아. 다음 별도 계획에서 이 21개 development 사건을 사용해 local VLM baseline의 사건 이어짐 재현율·비용·오류 유형을 측정하고, 독립 future holdout 전에는 production 채택이나 자동 skip을 하지 않는다.
