# 하드닝 보고 — Local VLM Evidence Analyst (Work Package A)

> 핸드오프: `petcam-rba-worker/docs/handoff-prompts/2026-07-21-local-vlm-evidence-hardening-handoff.md`
> 설계: `docs/superpowers/specs/2026-07-21-local-vlm-evidence-analyst-hardening-design.md`
> 계획: `docs/superpowers/plans/2026-07-21-local-vlm-evidence-analyst-hardening.md`
> 범위: Work Package A(runtime·scorer 하드닝) 코드·dry test·보고. 모델 snapshot 다운로드·MLX
> inference·Mac mini 접속·production DB/R2 write·Work Package B 후보 선정은 **하지 않음.**

## 최종 판정

## `HARDENING_BLOCKED_RUNTIME_PACKAGE`

Task 1~5·7 의 코드 하드닝은 **완료·전수 테스트 통과·push** 됐고, 실제 `mlx-vlm==0.6.5` API 는
격리 환경에서 **검증**됐다(모델 다운로드 0). 그러나 Task 6 의 **의존성 lock 은 실제 충돌로 차단**됐다:
`mlx-vlm==0.6.5` → `opencv-python>=4.12.0.88` → `numpy>=2` 가 프로젝트의 `numpy>=1.26,<2` 핀
(deeplabcut/opencv 계열)과 충돌해 **같은 venv 에 lock 불가**다. 설계 H6("실제 package 설치를
이번 dry 단계에서 할 수 없다면 READY 를 주장하지 않고 정확한 blocker 를 남긴다")에 따라 READY 를
주장하지 않고 이 blocker 를 남긴다. Mac mini runtime 은 이 충돌 해소(owner 결정) 이후에만 가능하다.

## 1. 시작 계약

```
uv run python scripts/verify_agent_handoff.py --manifest \
  /Users/baek/petcam-rba-worker/docs/handoff-prompts/2026-07-21-local-vlm-evidence-hardening-handoff.md
→ HANDOFF_OK task=local-vlm-evidence-hardening repo=petcam-lab commit=1b2727ef runtime=none
```

- lab HEAD `1b2727ef…` = manifest commit_sha ✅ (design commit `4feb44f` 조상 포함).
- 격리: 기존 untracked/멀티세션 보호를 위해 양쪽 레포에 clean worktree +
  `feat/local-vlm-evidence-hardening` 브랜치 생성 후 작업(핸드오프 §5).

## 2. 두 레포 branch·HEAD(40)

| repo | worktree | branch | HEAD(40) | push |
|---|---|---|---|---|
| petcam-lab | `/Users/baek/petcam-lab.hardening-wt` | feat/local-vlm-evidence-hardening | 이 보고 커밋(아래 §9 push 로 tip 확정) | ✅ |
| petcam-rba-worker | `/Users/baek/petcam-rba-worker.hardening-wt` | feat/local-vlm-evidence-hardening | `9a05228ed125ddcca048e52d485a50ed0bd2e743` | ✅ |

> 계획 초안은 push 대상을 `feat/local-vlm-evidence-analyst` 로 적었으나, 핸드오프 §5 가 worktree
> 격리 + `feat/local-vlm-evidence-hardening` 신규 브랜치를 명시해 그 지시를 따랐다(편차 §10-1).

## 3. Task 별 RED→GREEN·commit

| Task | repo | 신규/수정 | commit |
|---|---|---|---|
| 1 Python Evidence 입력 계약 | rba | `evidence.py`(+test) | `8713a10` |
| 2 evidence→prompt/runner 연결 | rba | prompt/runner/runbook + evidence loader(+test 2) | `f54ad30` |
| 3 runtime identity fail-closed | rba | `runtime_identity.py`, runbook 필수 CLI(+test 2) | `a5bb2ef` |
| 4 ledger 무결성 + 자원 계측 | rba | `runtime_metrics.py`, runner/adapter/runbook(+test 3) | `e4ea629` |
| 5 scorer 수학·coverage·자원 gate | lab | score_/recompute_(+test) | `36a18f5` |
| 6 MLX-VLM 0.6.5 실제 API 검증 + blocker | rba | mlx_adapter + contract test | `9a05228` |
| 7 dry e2e fixture + 보고 | lab | fixture 4종 + cross-boundary test + 보고 | 이 커밋 |

## 4. 반드시 고칠 결함 7개 → 조치·증거

1. **evidence 미연결(durable_key·roi_mode 만 프롬프트)** → `evidence.select_evidence` 로
   `clip_python_evidence_runs` 의 사전 등록 버전 1 run 을 골라 allowlist 21필드를 canonical
   JSON+SHA-256 으로 고정하고, `build_prompt(evidence, frame_context=)` 로 프롬프트·raw ledger 에
   연결. **증거**: `test_runner_passes_canonical_evidence_to_prompt_and_ledger`(raw record 에
   `evidence_source_run_id`·`evidence_sha256`·버전 2필드, canonical evidence 가 프롬프트 도달),
   `test_prompt_embeds_evidence_values`. evidence missing/ambiguous 는 generation 없이 terminal
   input_failure: `test_missing_evidence_is_terminal_input_failure_without_generation`(generate_calls==[]).
2. **expected HEAD/snapshot 자동 대체(fail-open)** → `--lab/rba/gate-head`·`--snapshot-dir`·
   `--model-repo/-revision`·`--gate-checkpoint(-sha256)`·`--gate-threshold`·`--evidence-*-version`
   전부 **CLI 필수**(기본값·`or repo_states[...]`·snapshot 상수 fallback 제거). git 조회 실패·
   dirty·HEAD/revision/repo 불일치·snapshot 미완·checkpoint sha 불일치는 inference 전
   `BLOCKED_RUNTIME_DRIFT`. **증거**: `test_required_runtime_flag_cannot_be_omitted`(12 flag),
   `test_git_command_failure_is_not_clean_repo`, `test_snapshot_directory_name_alone_is_not_proof`.
3. **자원 계측 미연결(runtime 없이 통과)** → `RuntimeMetricsMonitor` 가 latency(materialize/
   model_load/generation/e2e)·RSS·swap·temp peak/residual·worker exit drift·deadline·capacity 를
   실측하고, 계측 실패는 `RESOURCE_EVIDENCE_MISSING`. scorer 는 `--runtime` **필수** + `resource_gate`
   재계산. **증거**: `test_runtime_metrics_missing_command_is_fail_closed`,
   `test_generation_record_has_all_phase_latencies`, `test_runtime_is_mandatory`,
   `test_runtime_missing_field_rejects_resource`, `test_resource_gate_fails_on_bad_metric`.
4. **presence CI 가 F1 아닌 exact-accuracy bootstrap** → `bootstrap_metric_ci(pairs, metric_fn)`
   로 실제 macro/weighted F1 을 resample 재계산. visibility·motion CI 추가, strata·roi_mode
   breakdown 추가. **증거**: `test_presence_ci_bootstraps_macro_f1_not_exact_accuracy`,
   `test_visibility_and_motion_have_ci`, `test_by_strata_keys_match_manifest_and_roi_modes_present`.
5. **object 0건에도 품질 PASS** → evaluable object-positive < `MIN_OBJECT_POSITIVE(10)` 면 object
   gate 통과 불가. **증거**: `test_zero_object_positive_cannot_pass_quality`(REJECT_QUALITY),
   `test_object_below_min_cannot_pass_quality`.
6. **malformed/duplicate JSONL silent skip** → `load_completed_records` 가 malformed/identity 누락/
   중복/충돌을 `LedgerIntegrityError`(RAW_LEDGER_MALFORMED/IDENTITY_MISSING/DUPLICATE/CONFLICT)로
   중단. **증거**: `test_load_completed_records_malformed/…_conflicting_identity/…_duplicate_identical`,
   `test_run_benchmark_aborts_on_corrupt_resume_ledger`.
7. **mlx-vlm 0.6.5 API 미검증** → 격리 env(`uv run --no-project --with mlx-vlm==0.6.5`)로 실제
   signature 검증(§7). 어댑터는 이미 계약 준수. **증거**: contract test 3건 GREEN(ephemeral).

## 5. corrected scorer 결과 (dry fixture)

`tests/fixtures/local_vlm_evidence_hardened/`(18 clip·22 measured key·6 strata·양 ROI mode·
object-positive 12·repeat 2) 로 end-to-end:

- `test_hardened_fixture_scores_and_recomputes_identically`: `canonical_summary(full) ==
  recompute(...)` 및 두 canonical_sha256 일치(scorer↔독립 재계산 합의) ✅
- `gates.resource is True`(유효 runtime), `by_strata` 키 == 6 strata, `by_roi_mode` ==
  {union_roi, full_frame_no_detection}, `coverage.object_positive == 12`, missing/unexpected/
  duplicates == 0 ✅
- 독립 재계산은 `build_measured_keys` import 를 제거하고 expected key·자원 gate 를 별도 구현
  (scorer 상수·helper 미공유).

## 6. runtime metric 완전성 / 누락 거부

`RESOURCE_FIELDS = (peak_rss_bytes, swap_delta_bytes, temp_residual_count, worker_exit_delta,
deadline_delay_sec, sustained_clips_per_hour, projected_four_camera_p95)`. 하나라도 None →
`resource_gate` 가 `RESOURCE_EVIDENCE_MISSING:<fields>` raise → scorer 는 verdict 대신 예외
전파(빈 값 PASS 불가). capacity gate = `sustained_clips_per_hour >= 2 × projected_four_camera_p95`.
MLX peak 미제공은 `mlx_peak_bytes=None` 으로 표기(0 조용히 수용 금지) —
`test_missing_mlx_peak_marked_none_not_zero`.

## 7. 실제 `mlx-vlm==0.6.5` API inspection (모델 다운로드 0)

격리 env inspection (2026-07-21):

```
VERSION 0.6.5
LOAD     load(path_or_hf_repo, adapter_path=None, lazy=False, revision=None, strict=True, **kwargs)
GENERATE generate(model, processor, prompt, image=None, audio=None, video=None, verbose=False, **kwargs)
APPLY    apply_chat_template(processor, config, prompt, add_generation_prompt=True,
                             return_messages=False, num_images=0, num_audios=0, **kwargs)
GenerationResult fields: text, token, generation_tokens, peak_memory, finish_reason, …
generate docstring: "max_tokens (int) … default 100", "temperature (float) … default 0"
generate 내부: stream_generate(model, processor, prompt, image, audio, video, verbose=verbose, **kwargs)
```

- **어댑터 계약 부합**: `load(model_repo, revision=…)` ✅, `generate(model, processor, prompt,
  images, temperature=0.0, max_tokens=256, verbose=False)` — `max_tokens`/`temperature` 는
  명시 파라미터가 아니라 **문서화된 kwargs → stream_generate forward** 라 유효 ✅,
  `apply_chat_template(..., num_images=)` ✅, `GenerationResult.text/generation_tokens/peak_memory` ✅.
  → 어댑터 **기능 변경 불필요**(이미 준수). `verify_mlx_runtime_contract()` 인스펙터 추가.
- **contract test**: 프로젝트 venv 에는 mlx-vlm 미설치(§8 충돌)라 `pytest.importorskip` 으로 skip,
  ephemeral env(`--no-project --with mlx-vlm==0.6.5`)에서 **3 passed** 로 실증.
- **계획과의 API 편차**: 계획 예시 테스트는 `"max_tokens" in generate.parameters` 를 가정했으나
  실제 0.6.5 는 `**kwargs` 라 명시 파라미터가 아니다 → 테스트를 실제 계약(image + VAR_KEYWORD +
  bind_partial)으로 정정(핸드오프 "실제 signature 를 증거로 최소 수정" 준수).

## 8. 실행 차단 blocker (Task 6 dependency lock)

```
uv add --group local-evidence-benchmark "mlx-vlm==0.6.5"
→ No solution: mlx-vlm==0.6.5 depends on opencv-python>=4.12.0.88,
  opencv-python==4.12.0.88 depends on numpy>=2,<2.3.0,
  프로젝트는 numpy>=1.26,<2 (deeplabcut[apple-mchips,gui]>=3.0 / opencv<4.13) → unsatisfiable
```

- **조치**: `pyproject.toml`·`uv.lock` **미수정**(poisoned lock 방지). blocker 를 이 보고와 커밋에 기록.
- **해소 옵션(owner 결정)**: (a) numpy 상향(>=2) — deeplabcut/opencv 회귀 위험 재검증 필요, 또는
  (b) local VLM 벤치마크 워커를 deeplabcut 워커와 **별도 venv/환경**으로 분리(권장 — SLA 무관 side
  worker). 결정 후 `uv add --group local-evidence-benchmark mlx-vlm==0.6.5` + contract test 재실행.

## 9. 전체 test·정적 감사

- petcam-rba-worker: `uv run pytest -q` → **157 passed, 1 skipped**(mlx contract, dry env skip).
  `git diff --check 72898c6..HEAD` clean.
- petcam-lab: `uv run pytest -q` → **660 passed**. `git diff --check 1b2727ef..HEAD` clean.
- 신규 테스트: rba(evidence/runtime_identity/runtime_metrics/runner/mlx contract) + lab(scorer 11 +
  dry e2e 2). pre-existing 실패 0(시작 SHA 기준 전수 통과).
- 정적 금지동작 스캔(insert/update/upsert/delete/slack/launchctl bootstrap/snapshot_download/
  from_pretrained/apply_migration/execute_sql): HIT 전부 false-positive(`sys.path.insert`·
  `hashlib.update`). production DB/R2 write·Slack·LaunchAgent 변경·model download·inference·
  committed media = **0**. selector·cloud VLM·행동 GT·highlight·자동 제외 연결 = **0**.

## 10. 계획 대비 편차 (정직 기록)

1. **브랜치명** — 계획 초안 push 대상 `feat/local-vlm-evidence-analyst` 대신 핸드오프 §5 의
   worktree 격리 + `feat/local-vlm-evidence-hardening` 신규 브랜치 사용.
2. **pyproject/uv.lock 미수정** — §8 의존성 충돌로 lock 불가 → 정확한 blocker 로 대체(설계 H6).
3. **mlx contract 테스트 skip 전략** — 프로젝트 venv 설치 불가라 `importorskip`; 실제 검증은
   ephemeral env 3 passed 로 실증(계획의 `--group` 실행은 lock 후 가능).
4. **generate contract 정정** — 실제 0.6.5 는 `max_tokens`/`temperature` 가 `**kwargs` → 테스트를
   실제 signature 기준으로 수정.
5. **이종 모델 교차 리뷰** — 이번 세션 범위는 self dry test. 독립 검수는 Codex(핸드오프 §종료).

## 11. 남은 조건 = Work Package B 만

이 하드닝 이후 진행 순서(설계 §6·§7):
1. **의존성 blocker 해소**(§8 owner 결정) — Mac mini runtime 전제.
2. **Work Package B**(별도 세션): production SELECT-only 로 6 strata 후보 manifest + 사람 검수
   worksheet 생성(모델 출력 열람·GT 값 입력·DB write 금지). `BLOCKED_DATA_INSUFFICIENT` /
   `DATA_AVAILABLE(_LOW_MARGIN)` 판정.
3. B 승인 후 사람 blind evidence GT 180행(5축) 작성 → validator 통과 → 그때 Mac mini one-shot
   벤치마크 plan 신규 작성 + owner 승인(≈4.5GB snapshot 다운로드).

Task 7 이후 두 feature 브랜치 push 하고 정지. main merge·모델 실행·Work Package B 자동 진행 없음.
