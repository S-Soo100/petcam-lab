# t1-highlight-selection 테스트 시험지 (Test Sheet)

> 규칙: [`.claude/rules/research-testing.md`](../../.claude/rules/research-testing.md). **실행 전 고정 — 사후 변경 금지.**

**실험 ID:** t1-highlight-selection · **phase:** T1 (하이라이트 선별 probe) · **작성일:** 2026-07-21 · **상태:** 🟡 작성중 (owner 승인 대기 — 승인 시 🔒 고정)

발주 근거: [`docs/decision-gate.md`](../../docs/decision-gate.md) 2026-07-21 연구방향 상담 — P3 adopt (TEST-SHEET 선행 조건). 배경: "볼만한 N개 뽑기"는 필터(빼기)가 아니라 샘플러(뽑기) — DB-first top-N 아키텍처의 뽑기 로직 검증. T0 부산물(dwell/observed = 존재 신호 유효) 활용.

**하드 계약 (T0 승계):** ① production DB **SELECT only** ② blind 유지 — clip_id·점수·그룹을 시트/파일명에 노출 금지, mapping key는 `key/` 격리(채점 전 열람 금지) ③ 시험지 승인 후 동결 ④ 영상은 `storage/` 하위만 ⑤ **LLM/VLM 호출 0회**

## 1. 가설
- **H1 (대립)**: DB-only 합성 점수(존재×활동×주기성, 시간대 분산 캡) 상위 20 클립군은 무작위 20 대비 "볼만함(informative)" 비율이 유의하게 높다.
- **H0 (귀무)**: 점수 상위군의 informative 비율이 무작위와 차이 없다 (게이트 미달).

## 2. Sample list
- 풀: `clip_python_evidence_runs` eligible (T0 §2와 동일: level0/1=ok/ok, observed_sec≥5, n_observations≥3, clip당 최신 run) **− T0 판정 80 clip_id 제외** (재판정 오염 방지)
- **S그룹 (score) n=20**: 합성 점수 내림차순, 단 버킷 캡 — (camera, KST date, 2시간 창)당 최대 4개 (production selector "카메라·구간 최대 4" 정렬). 캡 초과 시 다음 순위로.
- **R그룹 (random) n=20**: S 제외 풀에서 무작위 (seed 고정)
- 고정 방법: `scripts/t1_highlight_rank.py` (SEED=20260721, blind 셔플 SEED+1, tie-break `(-score, clip_id)`) → `sample_list.json` + `key/assignment_key.json`(격리) + `blind_sheet.csv`
- **고정 후 불변**

### 합성 점수 (사전 고정)
풀 전체에서 각 성분의 백분위 순위(percentile rank, 0~1)를 구해 평균:
```
score = mean( pr(observed_sec), pr(roi_mean), pr(peak_autocorr) )
```
- `observed_sec` = 존재(T0 검증: dwell/observed는 게코 존재를 잘 잡음 — absent 3% vs 55%)
- `roi_mean` = 활동 세기. ⚠️ 단독으론 환경모션 오염(T0: absent가 roi_max 높음) — 존재 성분과의 결합이 이 실험의 검증 대상
- `peak_autocorr` = 반복성(핥기·씹기 등 케어 미세동작 후보)
- 결측은 성분 0 처리. 가중치 균등(튜닝 금지 — 이 버전이 v1, 조정은 새 시험지)
- 탐색용 무작위 슬롯은 이 probe에선 **없음** (R그룹이 대조군 역할, ops 기능은 채택 후 스펙에서)

## 3. 모델 / 입력표현 / 프롬프트
- 해당 없음 — 판정자는 **사람(owner) blind 육안**, LLM 0회.
- 판정 단위: 클립 영상 전체 시청 (T0와 동일 흐름, R2 signed GET → `storage/t1-highlight/`)

### 판정 라벨 (blind 시트 기입, 5종)
| verdict | 기준 |
|---|---|
| `informative_care` | 케어행동 관찰: 먹기(paste/prey/hand)·마시기·표면핥기·탈피 관련 |
| `informative_other` | 케어 아니지만 리포트에 실릴 만한 장면: 명확한 탐색/등반/쳇바퀴 등 활발·특이 행동 |
| `not_informative` | 평범/무의미: 미세 움직임·거의 정지·조명 변화 등 |
| `absent` | 게코 안 보임 |
| `unsure` | 판정 불가 |

"볼만함(informative)" = `informative_care` + `informative_other`. **케어 우선** 정의는 지표에서 care를 1차 보조지표로 분리 집계하는 것으로 반영 (owner 논의 2026-07-21).

## 4. 측정 지표
- **주지표**: 그룹별 informative율 (judged = unsure 제외 분모)
- 보조: informative_care율 · absent율(존재 성분 작동 점검) · 버킷 커버리지(S그룹 시간대 분산) · 성분별 백분위 분포(사후 진단용, 판정엔 불사용)

## 5. 합격 기준 (게이트 — 숫자)
- **adopt**: S informative율 − R informative율 ≥ **+20%p** AND S informative ≥ **8/20**
- **hold**: 격차 +10%p 이상 +20%p 미만, 또는 S informative 5~7
- **reject**: 격차 +10%p 미만 또는 S informative ≤ 4
- 안전 점검(게이트 아님, 보고 의무): S absent율 > 10%면 존재 성분 실패로 별도 기록
- 기준선 출처: R그룹 실측 (T0 random20 참고치: absent 55% — informative 기대치 낮음)

## 6. 예상 비용 / 토큰
- LLM/VLM 0. R2 GET 40건(수 분·전송비 무시 수준), DB SELECT 페이지네이션 수 회. owner 판정 부담 40건 (T0의 절반).

## 7. Decision 룰 (사전)
- **adopt** → 점수식 v1을 nightly top-N 후보 selector 입력 스펙으로 승격 제안 (decision-gate 4게이트 재통과 후). blind 판정 40건은 사람 GT로 적립.
- **hold** → 성분/캡 조정안을 **새 시험지**로 재시험 (이 시트 수정 금지).
- **reject** → DB-only 점수식 v1 기각. 다음 후보(Gate prelabel 결합 등)는 별도 게이트 통과 후.
- 해석 가드: n=20/그룹 소표본 — informative율 1건 = 5%p. 격차 게이트(+20%p = 4건 이상)는 이 노이즈를 감안한 값. 단독 클립 사례로 성분 효과를 단정하지 않는다. 이 결과는 "이 3일치 풀"의 참고치이며 fresh camera-night 일반화는 채택 후 별도 검증.
