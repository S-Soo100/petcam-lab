# Router Full Provenance Reprocess

- generated_at: `2026-07-10T07:24:57.990432+00:00`
- local_time: `2026-07-10 16:24 KST`
- decision: `pass-full-reprocess`
- scope: 기존 `clip_router_features` 중 `active_feature_run_id`가 없던 전체 1,338건
- mode: `R2+OpenCV metadata only`
- llm_vlm_calls: `0`

## 결과

- 백필 대상: `1,338`
- 백필 대상 최신 조회: `1,338`
- 백필 대상 ready: `1,338`
- 백필 대상 failed: `0`
- 백필 대상 active_feature_run_id 있음: `1,338`
- 백필 대상 producer metadata 있음: `1,338`
- 백필 대상 feature_params 있음: `1,338`
- 백필 대상 history row 있음: `1,338`
- active_feature_run_id가 history table에 없는 건: `0`
- success: `true`

## 전체 DB 상태

- `clip_router_features`: `1,358`
- 상태: `ready 1,358 / pending 0 / processing 0 / failed 0`
- active_feature_run_id 있음: `1,358`
- producer metadata 있음: `1,358`
- `clip_router_feature_runs`: `1,358`
- run table 상태: `ready 1,358`

## Producer

- producer_name: `router-feature-worker`
- producer_host: `baeg-endeuui-Macmini.local`
- producer_code_ref: `1471f48`
- smoke run: `router-20260710T053827Z-c5f40ae6` = `20`
- full reprocess run: `router-20260710T061934Z-a5f13f7a` = `1,338`

## Reliability

- before: `high 42 / medium 267 / low 1,029`
- after: `high 42 / medium 267 / low 1,029`
- changed_count: `0`

## Feature Stability

이번 전체 백필 대상 1,338건은 재처리 전후 핵심 motion 값이 바뀌지 않았다.

- motion_mean max_abs_delta: `0.0`
- motion_peak max_abs_delta: `0.0`
- active_motion_ratio max_abs_delta: `0.0`

해석: 이번 대상은 기존에 같은 OpenCV feature 값은 이미 있었고, 이번 작업은 provenance/history 연결을 채우는 성격이었다. 이전 20건 smoke에서는 feature 값 변화가 있었으므로, 재처리 안정성은 앞으로도 run history 기준으로 비교해야 한다.

## Mac Mini Automation

- launchd label: `uk.tera-ai.petcam-router-features`
- service state: `running`
- health: `{"ok":true,"service":"router-feature-worker"}`
- health URL on Mac mini: `http://127.0.0.1:8089/health`
- poll mode: pending row를 주기적으로 가져와 R2 영상을 다운로드하고 OpenCV metadata를 만든 뒤 Supabase에 기록
- Slack mode: 기존 상황판 메시지 유지, LLM/VLM 호출 없음

## Artifacts

- `reports/router-full-provenance-reprocess-20260710/selected_before.json`
- `reports/router-full-provenance-reprocess-20260710/after.json`
- `reports/router-full-provenance-reprocess-20260710/runs.json`
- `reports/router-full-provenance-reprocess-20260710/summary.json`
- `reports/router-full-provenance-reprocess-20260710/clip_ids.txt`
