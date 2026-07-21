# REPORT — Mac mini Local VLM Evidence Analyst

> 이 파일을 복사해 `REPORT.md`를 만든다. 꺾쇠 필드는 실행 증거로 교체하며, 빈 필드가 하나라도 있으면 verdict를 확정하지 않는다.

## 1. 판정

- verdict: `<one exact verdict from TEST-SHEET §11>`
- 실행 시작/종료 KST: `<ISO-8601>` / `<ISO-8601>`
- runtime host: `<hostname>`
- model repo/revision: `<repo>` / `<40-char revision>`
- MLX-VLM version/wheel SHA: `<version>` / `<sha256>`
- prompt/schema version: `<version>` / `<version>`

## 2. Git·입력 provenance

| 항목 | 값 |
|---|---|
| petcam-lab HEAD | `<40-char SHA>` |
| petcam-rba-worker HEAD | `<40-char SHA>` |
| gecko-vision-gate HEAD | `<40-char SHA>` |
| TEST-SHEET SHA-256 | `<sha256>` |
| manifest SHA-256 | `<sha256>` |
| human GT SHA-256 | `<sha256>` |
| raw JSONL SHA-256 | `<sha256>` |
| Gate checkpoint SHA-256 | `<sha256>` |

## 3. 표본 무결성

| 항목 | 기대 | 결과 | 판정 |
|---|---:|---:|---|
| unique clips | 180 | `<n>` | `<pass/fail>` |
| dev / holdout | 120 / 60 | `<n>/<n>` | `<pass/fail>` |
| measured keys | 240 | `<n>` | `<pass/fail>` |
| episode duplicates | 0 | `<n>` | `<pass/fail>` |
| dev↔holdout leakage | 0 | `<n>` | `<pass/fail>` |
| missing / unexpected / duplicate | 0 / 0 / 0 | `<n>/<n>/<n>` | `<pass/fail>` |

strata·camera·date 분포 표를 이어서 기록한다.

## 4. 완전성·schema

- success / error: `<n>/<n>`
- completion rate: `<percent>`
- strict JSON schema success: `<n>/<n>`
- semantic policy violation: `<n>`
- error taxonomy: `<code=count>`

## 5. 성능·자원

| 지표 | 결과 | gate | 판정 |
|---|---:|---:|---|
| model load seconds | `<value>` | 정보 | — |
| materialize p50 / p95 | `<value>/<value>` | 정보 | — |
| generation p50 / p95 | `<value>/<value>` | 정보 | — |
| e2e p50 / p95 | `<value>/<value>` | 정보 | — |
| capacity clips/hour | `<value>` | 4-camera p95×2 | `<pass/fail>` |
| peak RSS GiB | `<value>` | ≤8 | `<pass/fail>` |
| MLX peak GiB | `<value>` | 정보 | — |
| sustained swap delta GiB | `<value>` | ≤1 | `<pass/fail>` |
| temp peak / after | `<value>/<value>` | after=0 | `<pass/fail>` |

## 6. Fresh holdout 품질

| 지표 | point | 95% CI | gate | 판정 |
|---|---:|---:|---:|---|
| presence macro F1 | `<value>` | `<low-high>` | ≥0.85 | `<pass/fail>` |
| present recall | `<value>` | `<low-high>` | ≥0.95 | `<pass/fail>` |
| visibility weighted F1 | `<value>` | `<low-high>` | ≥0.80 | `<pass/fail>` |
| motion macro F1 | `<value>` | `<low-high>` | ≥0.75 | `<pass/fail>` |
| object top-k recall | `<value>` | `<low-high>` | ≥0.75 | `<pass/fail>` |
| abstain rate | `<value>` | `<low-high>` | 정보 | — |

presence·motion confusion matrix와 strata별 표를 이어서 기록한다.

`roi_mode=union_roi|full_frame_no_detection`별 표본 수·present recall·presence/motion 지표를 별도 기록한다. 이 표는 Gate 무검출 상황에서 local VLM이 회복했는지, 아니면 full-frame 입력도 실패했는지 분리하는 진단 근거다.

## 7. 반복 안정성

- repeated clips: `30`
- exact-consistent clips: `<n>`
- consistency: `<percent>` (gate ≥95%)
- 불일치 field별 count: `<field=count>`

## 8. 운영 안전

| 계약 | 결과 | 증거 |
|---|---|---|
| production worker deadline 지연 0 | `<pass/fail>` | `<log range>` |
| nonzero exit 증가 0 | `<pass/fail>` | `<before/after>` |
| DB write 0 | `<pass/fail>` | `<audit>` |
| R2 write 0 | `<pass/fail>` | `<audit>` |
| LaunchAgent 변경 0 | `<pass/fail>` | `<before/after>` |
| temp media 0 | `<pass/fail>` | `<scan>` |
| secret/raw URL 노출 0 | `<pass/fail>` | `<scan>` |

## 9. 오류·대표 사례

오류·정답·오답·abstain 대표 clip은 short id와 owner용 label web 링크만 기록한다. 원본 signed URL이나 영상은 문서에 넣지 않는다.

## 10. 독립 재계산

- harness summary SHA-256: `<sha256>`
- independent summary SHA-256: `<sha256>`
- counts 일치: `<yes/no>`
- metrics 일치: `<yes/no>`
- 불일치가 있으면 verdict: `REJECT_INTEGRITY`

## 11. 결론과 다음 경계

- 채택/기각한 가설: `<H0/H1>`
- exact verdict: `<verdict>`
- 근거 3줄: `<evidence>`
- production 연결: **미승인 유지**
- 다음 연구: PASS일 때만 Claude control vs local-evidence treatment paired TEST-SHEET 작성
