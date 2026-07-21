> ⛔ SUPERSEDED on 2026-07-21: `IMPLEMENTATION_BLOCKED_DATA` was rejected by independent review.
> Current verdict is defined by `2026-07-21-local-vlm-evidence-hardening-report.md`.

# 구현 보고 — Mac mini Local VLM Evidence Analyst (Task 1~8)

> 핸드오프: `2026-07-21-mac-mini-local-vlm-evidence-analyst-implementation-handoff.md`
> 범위: 구현·dry test·보고. **모델 설치·다운로드·Mac mini inference 없음.**

## 최종 판정

## `IMPLEMENTATION_BLOCKED_DATA`

구현 코드(Task 1~6)·검증(Task 7 진단)·핸드오프(Task 8)는 완료·테스트 통과·push 됐다. 그러나
240-key 벤치마크는 **표본/GT 데이터 부재**로 실행할 수 없다. 코드는 runtime review 준비 완료이나,
runtime 자체는 owner 의 데이터 작업 전까지 블록된다.

## 1. 시작 계약

- `verify_agent_handoff.py` → `HANDOFF_OK task=local-vlm-evidence-analyst-implementation
  repo=petcam-rba-worker commit=53927398 runtime=none`
- branch `feat/local-vlm-evidence-analyst`, HEAD `5392739…` = manifest commit_sha ✅
- design → plan → AGENTS.md 순 정독 완료.

## 2. 두 레포 branch·HEAD·push 동기화

| repo | branch | HEAD(40) | push |
|---|---|---|---|
| petcam-lab | feat/local-vlm-evidence-analyst | `2523110f33fe222c5f0d3b8d42c55a11fe697b49` | ✅ origin |
| petcam-rba-worker | feat/local-vlm-evidence-analyst | `72898c64519b806162e25cd1d77a27f53dcb5e7f` | ✅ origin |
| gecko-vision-gate | main | `9e39596bdb907a86496948f4bf3a13fe760d8222` | 미수정(read-only 의존성) |

## 3. Task 별 RED→GREEN·변경파일·commit

| Task | 레포 | RED→GREEN | 신규 파일 | commit |
|---|---|---|---|---|
| 1 validator | lab | `pytest test_validate_local_vlm_evidence_manifest.py` 19 ✅ | validate_local_vlm_evidence_manifest.py (+test) | `b0c6fde` |
| 2 schema/parser/prompt | rba | `pytest test_local_evidence_schema.py` 18 ✅ | backend/local_evidence_analyst/{schema,parser,prompt,__init__}.py (+test) | `76ed8b5` |
| 3 MLX adapter | rba | `pytest test_local_evidence_mlx_adapter.py` 13 ✅ | mlx_adapter.py (+test) | `a2281b9` |
| 4 materializer | rba | `pytest test_local_evidence_materializer.py` 15 ✅ | materializer.py (+test) | `79c7460` |
| 5 runner+runbook | rba | `pytest test_local_evidence_runner.py` 17 ✅ | runner.py, scripts/run_local_evidence_benchmark.py (+test) | `72898c6` |
| 6 scorer+recompute | lab | `pytest test_score_local_vlm_evidence.py` 18 ✅ | score_/recompute_local_vlm_evidence.py (+test) | `a6b6184` |
| 7 data availability | lab | SELECT-only probe 실행 | probe_local_vlm_evidence_availability.py, DATA-AVAILABILITY.md, data-availability.json | `7f65410` |
| 8 handoff/audit | lab | verify oneshot 1 RED→GREEN, 46 ✅ | runtime-handoff.md, verify_agent_handoff.py(oneshot) | `2523110` |

## 4. 전체 test·diff-check

- petcam-lab: `uv run pytest -q` → **647 passed**. `git diff --check` clean.
- petcam-rba-worker: `uv run pytest -q` → **66 passed**. `git diff --check` clean.
- 신규 테스트: rba 63(schema18+mlx13+materializer15+runner17) · lab 38(validator19+scorer18+verify oneshot1).

## 5. 정적 보안 감사 (신규 파일 12개)

| 항목 | 결과 |
|---|---|
| production DB mutation (insert/update/upsert/delete/migration) | **0** (HIT 은 `sys.path.insert`·`hashlib.update` false-positive) |
| Slack / webhook | **0** (HIT 은 "Slack 변경 0" 계약 명시 주석) |
| LaunchAgent/plist 변경 | **0** (`launchctl list` = read-only worker-exit baseline 만) |
| Qwen runtime reference | **0** |
| hardcoded secret / RTSP / signed URL | **0** |
| committed media (mp4/jpg/png) | **0** |

## 6. 모델 설치·download·inference 0 증거

- `mlx-vlm` 설치·model snapshot 다운로드·local inference: **0**. `uv pip show mlx-vlm` → not installed.
- pyproject.toml/uv.lock: **미수정**. 실증: optional group 추가 시 `uv run --offline` 이 재해석
  실패(네트워크 필요) → dry 계약 위반. pin(repo/revision/wheel SHA)은 `mlx_adapter.py` 상수로 고정,
  설치는 Task 9 owner gate 로 이연.
- 모든 MLX 단위 테스트는 fake mlx 모듈 주입 (모델 네트워크 접근 0).
- runbook 은 wrong host 에서 fail-closed 실증: `BLOCKED_RUNTIME_DRIFT HOST_MISMATCH:BaekBook-Pro-14-M5.local`.

## 7. 데이터 가용성 판정 + 필요한 사람 GT 수

- **판정: `BLOCKED_DATA_INSUFFICIENT`** (SELECT-only, DB write 0). 상세 `DATA-AVAILABILITY.md`.
- 6 strata 중 big_move(39 episode)만 30 충족. rest_micro 0 · wheel_object 0 · absent 2 ·
  hardcase 3 · lick_water_food 28.
- **필요한 사람 evidence GT: 180행 (현재 0/180).** behavior_logs 는 `action`만 갖고 evidence 5축
  (presence/visibility/motion_extent/body_region/object)은 없음. holdout blind GT 60 도 미완료.
- manifest.json 은 **생성하지 않음** (유효 180 표본 불가, 위조 금지 = design §6 fail path).
- TEST-SHEET 상태 `DRAFT_PLAN_REVIEW` 유지 (PRE_REGISTERED flip 금지).

## 8. 다음 runtime handoff 가능 여부

- runtime handoff manifest 생성·검증: `HANDOFF_OK task=local-vlm-evidence-analyst-runtime
  repo=petcam-rba-worker commit=72898c64 runtime=oneshot@baeg-endeuui-Macmini.local`.
- **단, 실행은 조건부.** owner 가 (1) strata 재조정(design SOT 갱신) (2) 180 evidence GT blind 작성
  (3) validator 통과 후에만 Mac mini 설치·실행이 가능하다. 그 전에는 어떤 판정에서도 자동 시작 금지.

## 9. 계획 대비 편차 (정직 기록)

1. **Task 3 pyproject/uv.lock 미수정** — dry/no-download 계약 우선. `uv run` 오프라인 재해석 실패로
   실증. pin 은 상수 고정, 설치는 Task 9.
2. **Task 7 manifest.json 미생성** — 데이터 불충분·위조 금지. DATA-AVAILABILITY.md + BLOCKED_DATA 로 대체.
3. **verify_agent_handoff.py 에 oneshot runtime_kind 추가** — plan 이 요구한 `runtime_kind=oneshot`을
   validator 가 지원하지 않아 TDD 로 확장(1 test RED→GREEN). design §8 "1회성 프로세스" semantic.
4. **이종 모델 교차 리뷰 미완** — Codex(버전 불일치 400)·Gemini(대화형 재인증 필요) 둘 다 환경 장애.
   plan Step 2 리뷰 8차원을 test 로 고정된 자체 검증으로 대체(각 차원 대응 테스트 존재). 실증 버그 0.
5. **RuntimeSafetyMonitor RSS/swap 계측 이연** — runtime 전용. runner 는 safety.check() reason 으로
   프레임워크 지원, 실제 RSS/swap wiring 은 Mac mini Task 9 에서 확정.

## 10. 경계 준수 요약

selector·Claude VLM·행동 GT·highlight·자동 제외 연결 0 · production DB/R2 write 0 · Slack 0 ·
LaunchAgent/plist 변경 0 · Qwen 0 · model 설치/다운로드/inference 0. runtime 은 owner + Codex 검토 대기.
