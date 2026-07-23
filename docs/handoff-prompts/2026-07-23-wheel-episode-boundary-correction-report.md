# 쳇바퀴 에피소드 10분 경계 교정 — 완료 보고

> 작성: 2026-07-23 · 실행 host: BaekBook-Pro-14-M5.local · branch `codex/wheel-episode-boundary-fix`
> 설계: [`docs/superpowers/specs/2026-07-23-wheel-episode-boundary-correction-design.md`](../superpowers/specs/2026-07-23-wheel-episode-boundary-correction-design.md)
> 계획: [`docs/superpowers/plans/2026-07-23-wheel-episode-boundary-correction.md`](../superpowers/plans/2026-07-23-wheel-episode-boundary-correction.md)
> 시험지·보고서: [`experiments/wheel-episode-dedup-boundary-fix/`](../../experiments/wheel-episode-dedup-boundary-fix/)

## 1. 최종 machine verdict

# `BOUNDARY_CORRECTION_READY_FOR_OWNER_REVIEW`

7개 기계 게이트를 모두 통과했다. **채택·배포 아님** — owner blind 감사가 남았다.

## 2. root cause · RED→GREEN

- **root cause:** v1 `group_clips` 의 run 분리가 `현재 clip − 바로 이전 clip` 간격만 검사 → 5분 간격 clip 이 연쇄로 결합해 그룹 전체 길이가 시험지의 ≤10분 계약을 어겼다(최장 18,224초·118개).
- **RED:** `tests/test_wheel_shadow.py::test_grouping_chain_cannot_exceed_total_episode_span` (+ `exact_episode_span` / `over_episode_span` 경계) — 5분×5개 chaining → 실패(신규 필드·`group_span_sec` 부재).
- **GREEN:** `max_inter_clip_gap_sec` 와 `max_episode_span_sec` 분리. `current−previous > 600` **또는** `current−run_start > 600` 이면 새 run(정확히 600초 포함, 초과만 분리). `group_span_sec`·`validate_group_spans` 로 산출물 직후 hard fail 이중 검증.

## 3. 교정 전 / 후 (동일 frozen signature)

| 지표 | 교정 전(v1) | 교정 후(v1.1) |
|---|---:|---:|
| fresh 그룹 | 32 | 80 |
| fresh membership | 326 | 300 |
| fresh representatives | 71 | 164 |
| fresh max group span | 18,224초 | **600초** |
| 600초 초과 그룹 | 19/32 | **0** |
| 위반 membership | 296/326 | **0** |
| fresh overlap | 0 | 0 |
| **known wheel 그룹** | 4 | 5 |
| **known wheel 대표** | 9 | 11 |
| **known wheel 검토량 감소** | 62.5% | **50.0%** |

known wheel: 교정 전 4그룹 중 2개(ep2 696초·ep3 1,095초)가 전체 길이 초과였고, 교정으로 5그룹(대표 11·미묶음 1)으로 재분할 → `1 − (11+1)/24 = 50.0%`(게이트 ≥50% 경계 충족). v1 62.5% 는 span 위반 포함값이라 교정본으로 대체.

## 4. 7개 기계 게이트 PASS/FAIL

| # | 게이트 | 판정 | 근거 |
|---|---|---|---|
| 1 | 모든 fresh·known 그룹 전체 길이 ≤600초 | **PASS** | span 위반 0 (fresh max 600s·known 0) |
| 2 | overlap 0 | **PASS** | fresh 0·known 0 |
| 3 | 동일 입력 2회 재실행 SHA 동일 | **PASS** | `result_sha256==replay_sha256==5b95f566ca2d…` |
| 4 | 입력 3개 SHA 가 design §4 와 동일 | **PASS** | 3/3 일치 |
| 5 | known wheel 검토량 감소 ≥50% | **PASS** | 50.0% |
| 6 | 기존 전체 + wheel focused 테스트 통과 | **PASS** | 전체 pytest 711 passed |
| 7 | DB/R2 read·write 0·VLM 0·temp media 0 | **PASS** | runner stdlib+pure만·정적 grep 0·temp 미생성 |

독립 재검증(runner 미import, RESULT+CSV만): CSV 80그룹=RESULT·300clip=membership·max span 600s·overlap 0·known reduction 재계산 0.5 일치·CSV 헤더 금지토큰 0. 전부 일치.

## 5. 기존 v1 artifact SHA 불변

`git diff --exit-code 898278ff… -- experiments/wheel-episode-dedup-shadow/{EVIDENCE-AUDIT,frozen-cohort,wheel-roi-profile-v1,shadow-groups}.json` → exit 0(불변). 입력 3개 SHA 도 design §4 와 동일:

- `EVIDENCE-AUDIT.json` `23789fa8…a508e3`
- `frozen-cohort.json` `b67b32f2…d17f953`
- `wheel-roi-profile-v1.json` `653e64c2…35c7825`

## 6. 전체 테스트 결과

`uv run pytest -q` → **711 passed** (v1 706 + 경계 회귀 3 + runner 계약 2). `git diff --check` clean.

## 7. commit SHA · push 상태

| task | commit | 내용 |
|---|---|---|
| T1 | `b4b4dca` | 시험지 동결 |
| T2 | `a54da95` | 연쇄 결합 회귀 RED |
| T3 | `48687eb` | 두 시간 경계 + span 불변식 |
| T4 | `2fd19e2` | correction runner + 계약 테스트 |
| T4b | `b1dc898` | runner 주석 I/O 토큰 제거(정적검사 오탐 방지) |
| T5a | `26d44ab` | RESULT known n_membership/n_ungrouped(독립 재검증용) |
| T5 | `f4f23db` | 재측정 산출물(RESULT/BLIND/REPORT) |
| T6 | (이 커밋) | 완료 보고 + donts-audit |

feature branch `codex/wheel-episode-boundary-fix` push, local==origin, working tree clean(§Stop Point 참조).

## 8. owner blind audit 경로 · 남은 사람 판정

- blind review(점수 비노출): [`experiments/wheel-episode-dedup-boundary-fix/BLIND-REVIEW.csv`](../../experiments/wheel-episode-dedup-boundary-fix/BLIND-REVIEW.csv) — 컬럼 `group_id,is_representative,clip_id,captured_at,labeling_url,owner_verdict`(빈칸).
- 필요한 사람 검수량: fresh 80그룹·membership 300(대표 164) + known wheel 5그룹. owner 가 (a) 다른 행동 혼입 (b) 중요한 wheel interaction 대표 소실 (c) 모호 그룹 중 하나라도 발견하면 reject → 추가 튜닝 없이 자동 중복 묶기 폐기.

## 9. 금지동작 0 증거

- production DB write 0·R2 read/write 0·VLM 0·외부 네트워크 0: runner 정적 grep `supabase|boto3|R2|Slack|VLM|requests|httpx|urllib` = 0건, stdlib+pure 모듈만 import.
- 기존 v1 산출물 수정·삭제 0: base 898278f 대비 diff exit 0.
- ROI·threshold 4종 불변: profile byte-equivalent(SHA §4 일치), `_params_from_profile` 은 기존 값만 읽음.
- migration·라벨링 웹·GT/triage/session/activity/behavior/Python Evidence·자동 label/hold/skip·UI 반영 0.
- temp media 0(runner 는 media 미생성). secret/signed URL/raw media tracked 0.
- reset/rebase/force push/commit rewrite 0. primary checkout·다른 worktree 미수정.

## 10. Stop Point

main merge·DB/UI 반영·배포·추가 threshold 튜닝·owner 판정 대행 없이 정지한다. `ADOPTED`·`PRODUCTION_READY`·`DEPLOYED`·`VERIFIED_FOR_AUTOMATION` 을 주장하지 않는다. 판정은 `BOUNDARY_CORRECTION_READY_FOR_OWNER_REVIEW` 까지다.

## 11. Owner/Codex 종료 판정 — 2026-07-23

기계 게이트 통과 후 실제 제품 효용을 독립 재계산했다.

| 항목 | 값 |
|---|---:|
| fresh 전체 | 779 |
| 대표 | 164 |
| 미묶음 | 479 |
| 실제 검수량 | 643 |
| 실제 절감 | 136 |
| **실제 검수량 감소율** | **17.46%** |
| owner audit 필요량 | 80그룹·300 clip |
| 절감 0인 그룹 | 27그룹·56 clip |

machine gate #5는 known wheel 24개의 감소율 50%만 봤다. 이는 실제 fresh 검수량 감소를
대변하지 못하는 약한 proxy였다. 합의한 제품 기준인 전체 검수량 50% 이상 감소에 비해
실측은 17.46%뿐이고, 채택 검증을 위해 300 clip을 추가로 감사해야 한다.

따라서 owner가 다음 최종 판정을 승인했다.

# `AUTOMATION_REJECTED_LOW_UTILITY`

owner blind audit·추가 튜닝·main merge·UI 연결·canary·배포를 모두 취소한다. 코드와 산출물은
실패 근거로 branch에 보존하고, 라벨링은 기존 수동 검수를 유지한다.

기존 `BOUNDARY_CORRECTION_READY_FOR_OWNER_REVIEW`는 경계 결함의 기계적 교정 결과로 보존하지만,
제품 채택 판단에서는 이 종료 판정이 우선한다.
