# RBA Python 전수 계측 + OpenAI VLM 연구 설계 검수 보고서

> 검수일: 2026-08-03 KST
>
> 대상: `docs/superpowers/specs/2026-08-03-rba-python-prescan-openai-vlm-research-design.md`
>
> 판정: `DESIGN_REVIEWED_READY_FOR_OWNER_WRITTEN_REVIEW`

## 1. 결과 요약

승인된 연구 방향을 하나의 설계와 단계별 체크리스트로 고정했다.

```text
초기: 모든 영상 Python/Gate 전수 계측 + OpenAI VLM 전수 분석
중기: present/uncertain은 VLM, future holdout을 통과한 verified_absent만 생략 후보
후기: 개체 수 → trajectory → 활동 구간 → 별도 GT가 있는 highlight 후보 순으로 확대
```

초기 연구는 비용 절감보다 정확도 상한선 확인이 우선이다. 전체 영상 4fps 입력을 유지하고 Python이 찾은
변화 구간은 최대 20fps로 추가한다. Python/Gate가 API 호출·프레임·GT를 자동으로 줄이거나 바꾸는 연결은
중기 adoption Gate 전까지 금지한다.

## 2. 설계 정본 확인

- 초기 데이터셋: legacy 197 + recent 119 = unique 316
- 316개 highlight: 전부 `include`
- legacy 197: manifest 행동 GT 있음, highlight include는 Owner 일괄 확정, 행동 구간은 `not_measured`
- highlight selector 평가: 316개만으로 금지, 실제 include/exclude·시간 구간 대조군 필요
- 개체 수 정답: 영상 전체에서 동시에 보인 최대 수 `0/1/2/3/4+`
- Python: 실제 decoded frame을 최대 source 30fps까지 순차 전수 계측
- Gate 초기 기준선: decoded frame 전부를 shadow detection
- VLM: 전체 4fps + 6초 window/1초 overlap + 변화 구간 최대 20fps
- 자동 skip·사건 병합·GT·사용자 알림: 이번 연구 변경 0

## 3. Claude 교차검수

iTerm2 공식 AppleScript로 지정된 Claude/RBA 세션에 파일 절대경로를 전달하고 read-only 검수를 요청했다.
Claude는 코드·문서·DB·R2·service·git을 수정하지 않았고 마지막 marker
`REVIEW_PY30_SPEC_DONE`과 P0/P1 재출력 marker `REVIEW_PY30_P01_DONE`을 확인했다.

### 판정

- P0: 0
- P1: 2
- P2: 4

### P1 반영

1. **window→clip 합성 계약 누락 — 채택·수정 완료**
   - window ledger, overlap canonicalization, segment 병합, 대표 행동 결정, max count 집계,
     uncertain 전파, 누락 window의 `incomplete` 처리를 설계 §6.3에 추가했다.
2. **dense frame clip 총량 cap 제안 — 하드 cap은 기각, 위험 표기는 채택**
   - 사용자는 희소 프레임 반복 실패 뒤 정확도 상한선 시험을 승인했다. 따라서 초기 연구에서 비용 때문에
     프레임을 자르지 않는다.
   - 대신 Arm C가 순수 Python 숫자 효과가 아니라 `Python 구간 지정 + 추가 시각 정보`의 결합 정책임을
     명시하고 frame/token/call/latency를 전량 보고한다.
   - API hard limit로 전체 coverage를 보낼 수 없으면 축소 성공으로 꾸미지 않고 `incomplete_input`이다.

### P2 반영

1. legacy 197의 과거 반복 노출과 누적 적응 위험을 명시하고, 최종 일반화는 future holdout만 사용한다.
2. `dataset-203` 이름에서 임의의 6개 제외를 추론하지 않는다. 실제 frozen manifest 197행의 count/digest를
   고정하고, 별도의 203행 원본 목록이 확인될 때만 차이와 사유를 기록한다.
3. `not_observed/uncertain/verified_absent` 승격식의 연속 미검출·confidence 집계·예외·coverage를
   deployment TEST-SHEET에 사전 등록하도록 추가했다.
4. 4fps와 20fps에 같은 timestamp/frame digest가 겹치면 중복 전송하지 않고 frame manifest에 기록한다.

### 반영본 재검수

수정된 설계의 §3.3, §5.2, §6, §7, Phase 0을 Claude가 다시 read-only로 확인했다. window 합성,
silent truncation fail-closed, Arm C의 결합 정책 해석, legacy 197 provenance가 반영됐고 잔여
`P0=0 P1=0` 및 marker `FINAL_PY30_REVIEW_DONE`을 확인했다.

## 4. 자체검수

- placeholder `TBD/TODO/FIXME`: 0
- 197 + 119 = 316과 전부 highlight include 계약: 일치
- 행동 분류 GT와 segment/multi-action 미측정 범위: 분리
- Python 계측, Gate detection, VLM 의미 분석 책임: 분리
- 초기 전수 VLM과 중기 verified-absent 생략 Gate: 분리
- `not_observed != absent`, uncertain VLM 필수, 최소 10% 생략 감사, drift 자동 원복: 명시
- A/B/C paired 비교에서 좋아진 사례와 깨진 사례를 함께 집계: 명시
- window 누락·프레임 누락을 성공으로 처리하는 경로: 없음
- Python summary prompt 주입: 기본 OFF
- local VLM/router/자동 사건 묶기 부활 경로: 없음
- 보고서 secret·개인정보·원문 GT·private R2 key 출력: 금지

## 5. 현재 변경 범위

이번 작업은 연구 설계 문서와 이 검수 보고서만 작성했다.

- API 호출: 0
- DB/R2/GT write: 0
- production service/Vercel/Slack 변경: 0
- Python/Gate/VLM 구현: 0
- commit/push: 0

worktree에는 이번 작업 전부터 다른 사용자 변경과 연구 파일이 함께 있으므로 이를 건드리거나 정리하지
않았다. 프로젝트 규칙상 commit은 별도 명시 승인을 받기 전에는 만들지 않는다.

## 6. 다음 Gate

Owner가 written spec을 최종 확인한 뒤에만 구현 계획으로 전환한다. 구현 계획의 첫 순서는 다음과 같다.

1. Dataset 316 manifest/provenance와 실제 대조군 입력 계약
2. `python-prescan-v1` validator·native-frame streaming·운영 benchmark
3. OpenAI 공식 문서 기반 model/input/price TEST-SHEET
4. A/B/C frozen pilot
5. Gate presence/count shadow와 future holdout

구현 계획 승인 전 DB migration, R2 materialize, API key 설정, production worker 배포를 시작하지 않는다.
