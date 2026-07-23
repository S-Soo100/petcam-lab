# P4 Cam(dev) 쳇바퀴 에피소드 중복 묶음 read-only shadow — 최종 보고

> 작성: 2026-07-23 · 실행 host: BaekBook-Pro-14-M5.local
> 설계 정본: [`docs/superpowers/specs/2026-07-23-wheel-episode-dedup-design.md`](../superpowers/specs/2026-07-23-wheel-episode-dedup-design.md)
> 계획: [`docs/superpowers/plans/2026-07-23-wheel-episode-dedup-shadow.md`](../superpowers/plans/2026-07-23-wheel-episode-dedup-shadow.md)
> 시험지(동결): [`experiments/wheel-episode-dedup-shadow/TEST-SHEET.md`](../../experiments/wheel-episode-dedup-shadow/TEST-SHEET.md)
> 보고서: [`experiments/wheel-episode-dedup-shadow/REPORT.md`](../../experiments/wheel-episode-dedup-shadow/REPORT.md)

## 최종 판정

# `SHADOW_BLOCKED_INSUFFICIENT_DATA`

shadow 는 **안전하게 완주**했고 자체 게이트(결정론·overlap·temp·mutation·write0)는 전부 통과했다. 판정을
막은 것은 안전 위반이 아니라 **알고리즘의 day-mode 일반화 실패**다: IR(야간) wheel 로 캘리브레이션한 ROI
motion floor 가 주간 baseline 모션을 over-merge 해(대표 `wheel_ep_025` = day 118 clip / 5시간 false
merge), 신뢰 가능한(IR) membership 이 86 으로 pre-registered 100 에 미달한다. 태스크의 "ROI 신뢰 못하면
HOLD" · "membership<100 → BLOCKED" 규칙에 따라 수치를 꾸미지 않고 HOLD 로 종료한다.

---

## 1. branch · commit · push 동기화

- branch: `feat/wheel-episode-dedup-shadow`
- base: `b84d5e49b454a45afe01440f026ee717916c5959` (승인된 설계 commit)
- 최종 commit(로컬 HEAD): `1f388a9d1190e86aced39f566715188f938f2dfd`
- push: 아래 §최종 push 로 origin 동기화(이 보고서 커밋 포함).

커밋 이력(이 브랜치):
1. `docs: shadow 계획·시험지 (S0 동결)`
2. `feat: 순수 결정론 모듈 + 단위테스트`
3. `feat: wheel ROI profile v1 도출`
4. `feat: 오케스트레이터 + known wheel 캘리브레이션`
5. `feat: 실행 산출물 + REPORT (HOLD)`
6. `docs: 최종 handoff 보고` (이 파일)

## 2. frozen cohort 범위 · SHA (동시 라벨링 안전 계약)

- camera: **`P4 Cam (dev)`** (exact name 조회; "P4 Cam 1" 은 별칭 — DB 부재, wheel GT 24/24 일치로 owner 확정)
- started_at 범위(fresh): `2026-07-19T00:00:00+00:00` ~ `2026-07-22T00:00:00+00:00` (UTC, 3 night)
- fresh clip = 779 · known wheel GT = 24 (07-22, EDA/regression 전용)
- **cohort_sha256** = `c253fb6b01b5957d20f7a345fd103ab875cfaf0367a3137db337927af56f31f3`
- Python Evidence run identity: `python-evidence-raw-v1 / croi-temporal-v1` 최신 run 을 clip 별 박제(frozen-cohort.json)
- GT snapshot watermark: `2026-07-23T06:49:28.595378+00:00` (실행 window 내 owner 동시 라벨링 미관측 = watermark 불변)

## 3. ROI profile · preview

- profile: [`experiments/wheel-episode-dedup-shadow/wheel-roi-profile-v1.json`](../../experiments/wheel-episode-dedup-shadow/wheel-roi-profile-v1.json)
  - normalized ROI (x,y,w,h) = (0.47, 0.11, 0.24, 0.30), frame 1280×960
  - status = **provisional_shadow** (owner 확인 전 production 계약 아님)
  - grouping_params(known wheel 캘리브레이션): floor 0.01 · hamming 7 · tolerance 0.02 · novelty 6 · gap 600s
- preview: `experiments/wheel-episode-dedup-shadow/ROI-PREVIEW.png` — **gitignore(raw frame, 미커밋)**. 로컬에서 owner 육안 확인용. wheel 돔(상단 중앙-우측)에 ROI 박스가 얹혀 있음.

## 4. group · membership · 대표 수

| 구분 | 그룹 | membership | 대표 | max 그룹 |
|---|---:|---:|---:|---:|
| 전체 fresh | 32 | 326 | 71 | 118 |
| IR(야간, 캘리브레이션·신뢰) | 14 | **86** | — | 19 |
| day(주간, out-of-calibration) | 18 | 240 | — | **118 (false merge)** |
| ungrouped | — | 453 | — | — |
| known wheel(IR) regression | 4 | 24 | 9 | 9 |

groups_sha256 = `a109682e776b7e5ff425bb55a8fc6d21d77ec2b4c64ff649d56a5bcbdc3b7fd9`

## 5. known wheel 24 검토량 감소

- 24 GT(IR) → 4 에피소드(5·3·7·9) · 대표 9 → **검토량 감소 62.5%** (24 → 9). 설계 §2.2 "24→8~12" 부합. **E-WORKLOAD ≥50% 게이트 충족.**

## 6. fresh data 충족 여부

- D-NIGHT (≥3 night): ✅ 07-19(128)·07-20(177)·07-21(474)
- D-MEM (membership ≥100): ⚠️ 전체 326 ≥100 이나 **신뢰(IR) 86 < 100** — day membership 240 은 over-merge 로 신뢰 불가
- D-ROI (ROI 신뢰): ⚠️ IR 신뢰 / **day threshold 신뢰 불가** → HOLD 사유

## 7. 검증 (overlap · determinism · temp · mutation)

| 항목 | 결과 |
|---|---|
| 결정론 | `--replay` 2회 groups_sha 동일(`a109682e…`) + shadow-groups.json 저장 SHA 일치 = **100%** |
| overlap | membership 326, 중복 0, membership∩ungrouped 0 = **0** |
| temp media | `_tmp` 삭제, worktree 내 shadow media 0 (기존 docs/ir 자산 제외) = **0** |
| mutation fingerprint | before == after (`b5292f3ceda934ba…`) = **불변** |
| R2 write / VLM | 코드 grep: R2 `head_object`/`download_file`만·VLM 0·DB `.select`만 = **0** |
| secret/signed URL/raw media tracked | tracked media 0 · tracked .env 0 · signed URL/secret 0 · r2_key 누출 0 = **0** |
| production worker | worker/LaunchAgent/lock 미접촉, evidence append-only 미기록, deadline/error 영향 = **0** |
| 회귀 | `uv run pytest -q` = **706 passed** (baseline 694 + 신규 12), 0 실패 |
| `git diff --check` | clean |

## 8. owner 검수용 BLIND-REVIEW 경로

- [`experiments/wheel-episode-dedup-shadow/BLIND-REVIEW.csv`](../../experiments/wheel-episode-dedup-shadow/BLIND-REVIEW.csv)
  - 컬럼: `group_id, is_representative, clip_id, captured_at, labeling_url, owner_verdict`(빈칸). **score/알고리즘 근거 미노출.**
  - labeling_url = `https://label.tera-ai.uk/labeling/motion/<clip_id>`
  - 알고리즘 점수+provenance 는 분리 파일 [`EVIDENCE-AUDIT.json`](../../experiments/wheel-episode-dedup-shadow/EVIDENCE-AUDIT.json) 에.
- ⚠️ **현재 판정은 HOLD 이므로 전체 BLIND 감사는 v2(mode-scope) 이후로 미룬다.** owner 가 원하면 신뢰 subset(IR 14그룹)만 사전 sanity 감사 가능.

## 9. 미검증 항목 (owner-pending / v2)

- **E-FALSEMERGE (owner blind 감사)**: 미검증. 단 shadow 가 day-mode false merge 를 사전 검출(§4).
- **E-PRESERVE (distinct interaction 대표 보존 100%)**: 미검증(owner 판단).
- **동시 라벨링 실측**: 안전 계약(frozen cohort+fingerprint)은 배선·검증됐으나, 이 실행 window 에 owner 동시 라벨링이 없어 실 동시성 관측은 미확보.
- **ROI owner 확인**: provisional. owner 의 wheel 위치 확인 미완.
- **day-mode wheel 사용 유무**: 야행성 전제(GT 전량 IR). 주간 wheel 사용이 유의미하게 존재하는지 미확인.

## 10. 다음 단계 · 금지 경계

### 다음 (별도 승인 + 새 TEST-SHEET 필요)
1. **mode-scoped v2**: fresh cohort 를 IR(야간)으로 좁히거나 day 전용 floor 별도 캘리브레이션.
2. **긴 run 분할**: 연속 활동에서 10분 경계만으로 안 끊기는 문제 → run 내 sub-episode 분할(모션 정지·perceptual 급변).
3. **fresh 재측정**: v2 threshold 동결 후 새 IR camera-night ≥3 에서 재실행, membership≥100(IR) 목표.
4. owner ROI 확인 → provisional 해제 여부 결정.

### 금지 경계 (이 판정에서도 불변)
- **main merge · DB/UI 구현 · production 배포 없음.** Stop Point 에서 정지.
- production DB write · R2 write · migration · LaunchAgent/worker/배포 변경 · 라벨링 웹 수정 · 자동 label/hold/skip · GT 전파 · VLM 호출 없음(전 과정 준수).

---

## 부록 — S0 handoff 검증 (validator 전문)

```
HANDOFF_OK task=wheel-episode-dedup-shadow repo=wheel-episode-dedup-shadow commit=43a12986 runtime=none
```

(S0 계획·시험지 commit `43a12986352d0955ad7e3eca62f1618fd495faaa` 기준. `scripts/verify_agent_handoff.py` 통과 후 S1 착수.)
