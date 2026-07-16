# Python Evidence S1 preflight hardening — 최종 보고서

**판정: `READY_FOR_SAFE_WINDOW`**
**작성 시각(KST): 2026-07-17**
**작성 host: BaekBook-Pro-14-M5.local (implementation_host)**

H1/H2/H3 측정 결함 3개를 TDD(RED→GREEN)로 닫았다. 전체 테스트 512개 통과, feature branch push 완료. Mac mini 본실험·main merge·DB write·VLM 호출·LaunchAgent 변경 없음.

---

## 1. HANDOFF_OK 재확인

```
$ uv run python scripts/verify_agent_handoff.py \
    --manifest /Users/baek/petcam-lab/storage/handoffs/2026-07-17-python-evidence-s1-preflight-hardening.md
HANDOFF_OK task=python-evidence-s1-preflight-hardening repo=python-evidence-s1 commit=abae9e08 runtime=none
```

이전 세션의 `HANDOFF_BLOCKED`는 manifest 포맷 불일치(front-matter 미달)와 commit SHA 불일치(`abae9e01`≠`abae9e08`)로 발생했다. 재작성된 manifest로 통과 확인 후 구현 착수.

---

## 2. 결과 요약

| 항목 | 값 |
|---|---|
| Commit SHA | `4404dd10defb3d157cf3106ec23a6a4afc3455d7` |
| Branch | `feat/python-evidence-s1-benchmark` |
| Push | `abae9e0..4404dd1` → origin |
| 변경 파일 | 3개 (아래 §3 상세) |
| 신규 테스트 | 12개 (H1 6, H2 3, H3 3) |
| 전체 테스트 | 512개 통과 (기존 500 + 신규 12) |
| compileall | OK |
| git diff --check | exit 0 |

---

## 3. 변경 파일

```
scripts/benchmark_python_evidence_s1.py    +103 / -21 lines
tests/test_benchmark_python_evidence_s1.py +177 lines
experiments/python-evidence-s1-throughput/TEST-SHEET.md +1 line
```

**동결 보존 확인:**
- 본실험 workload(32·16 clip), warmup/repeat(1/3), 조건 A6/B12/CROI/DALL, 20분 deadline, 합격 기준 — 미변경.
- manifest `sha256`, influx `sha256`, projected_4_camera_p95=80.0 — 미변경.
- Gate production 코드(`gecko_vision_gate`, `reporter.*`) — 미변경.

---

## 4. H1 — CPU 요청이 실제 CPU 실행을 보장

### RED 증거

```
FAILED tests/test_benchmark_python_evidence_s1.py::test_device_contract_detector_exists
AssertionError: DeviceContractDetector not found — H1 not yet implemented
```

신규 테스트 6개: `test_device_contract_detector_exists`, `test_device_contract_mismatch_raises_safety_abort`,
`test_device_contract_match_passes_through`, `test_device_contract_mps_match_passes`,
`test_device_contract_verified_only_once`, `test_device_contract_no_device_attr_raises`

### 구현 방식 (실제 device 보장)

`DeviceContractDetector` 래퍼 클래스 추가:
- 첫 `detect()` 호출에서 `inner.device` 속성과 요청 device 비교.
- 불일치 → `SafetyAbort("device_mismatch", "model.device={actual} != requested={req}")` — 결과 기록 없이 중단.
- `model.device` 속성 없음 → `SafetyAbort("device_check_failed")` — fail-closed.
- 검증은 1회만 수행(lazy-load 완료 후).

`_make_detector` 수정:
- `torch.backends.mps.is_available` monkeypatch **제거**.
- `GeckoDetector(model_size=..., checkpoint=..., device=device, threshold=threshold)` — device/threshold 명시 전달.
- 반환값을 `DeviceContractDetector(det, requested=device)` 로 감싼다.
- `resolve_device()` 호출 유지 — MPS 미가용 시 생성 전에 `SafetyAbort("mps_unavailable")`.

**보장 흐름:**
1. `resolve_device()` → MPS 미가용이면 생성 전에 중단.
2. `GeckoDetector(device=device)` → checkpoint load 시 명시 device 사용.
3. `DeviceContractDetector._check_device()` → 첫 `detect()` 에서 lazy-load 완료 후 실제 device 검증.

---

## 5. H2 — Temp peak 정직성 (원본 MP4 포함)

### RED 증거

```
AssertionError: Expected >= 160 (100 MP4 + 60 adapter), got 60
AssertionError: Expected > 0 (100B MP4 was downloaded), got 0
```

신규 테스트 3개: `test_temp_peak_includes_downloaded_mp4`,
`test_temp_peak_nonzero_on_download_success_adapter_error`,
`test_temp_peak_warm_no_double_count`

### 구현 방식 (산식)

```
dest_dir_peak = dir_size_bytes(dest_dir)   # 다운로드 직후 측정
temp_peak_bytes = dest_dir_peak + res.temp_peak_bytes   # 성공 record
temp_peak_bytes = dest_dir_peak                         # 에러 record (다운로드 완료 시)
```

- `_run_one`: `dl = manager.get(...)` 직후 `dest_dir_peak = dir_size_bytes(dest_dir)` 측정.
- `_build_record`: `dest_dir_peak` 파라미터 추가, 두 경로 모두 반영.
- warm 모드: 공유 MP4는 한 시점의 `clip_dir` 크기이므로 중복 합산 없음.
- 실패 record: 다운로드가 완료됐다면 MP4 크기 반영, 0 숨김 없음.
- temp cleanup 0 계약: `scoped_tempdir` 보존, 변경 없음.

---

## 6. H3 — Threshold 사전고정 (0.10)

### RED 증거

```
AssertionError: DEFAULT_GATE_THRESHOLD not found — H3 not yet implemented
```

신규 테스트 3개: `test_default_gate_threshold_is_0_10`,
`test_write_summary_meta_includes_gate_threshold`,
`test_gate_threshold_recorded_in_summary_meta_from_main_flow`

### 구현 방식 (provenance)

- `DEFAULT_GATE_THRESHOLD = 0.10` 상수 추가 (production `activity-v1.gate_threshold` 동일).
- `_make_detector(threshold=DEFAULT_GATE_THRESHOLD)` — `GeckoDetector(threshold=threshold)` 전달.
- `build_adapters(threshold=DEFAULT_GATE_THRESHOLD)` — `_make_detector` 에 전달.
- CLI `--threshold` 기본값 `DEFAULT_GATE_THRESHOLD` — 결과를 본 뒤 바꾸는 것은 사후 게이트 조정임을 help 문구에 명시.
- `summary.json meta.gate_threshold = 0.10` — 결과 파일에서 provenance 확인 가능.
- TEST-SHEET §9 하드 금지에 "결과를 본 뒤 threshold 를 바꾸는 것은 이 시험지 무결성 위반" 문구 추가.

---

## 7. 추가 검수

### Resume key cross-JSONL 회귀

`test_resume_skips_completed`, `test_run_benchmark_resumes_from_completed` — 통과 확인.
CPU/MPS를 별도 실행해도 `(clip_id, condition, device, cache_mode, repeat)` 5-튜플 키가 다르므로 같은 JSONL에 안전하게 합칠 수 있다. 기존 구현 변경 없음.

### 02:05 KST R2 read-only smoke 절차 이탈 (deviation)

이전 세션(2026-07-17 02:05 KST)에 R2 read-only smoke(절차 §7 시작 게이트 점검의 일부)가 1회 수행됐다. 이는 본 preflight hardening 작업이 BLOCKED 판정으로 미착수 상태에서 이탈한 것이다. 당시:
- DB write 0, VLM 호출 0, detector call 0, 로컬 temp 즉시 삭제 확인(scoped_tempdir).
- 02:05 nightly 지연·오류 여부: 본 MacBook 환경에서 확인 불가 (Mac mini nightly는 독립 실행). 본실험 후 Mac mini에서 LaunchAgent run count / last exit / log error 비교로 검수 필요.

이 이탈은 본 최종 S1 보고서의 deviation 항목으로 남긴다. 삭제하지 않는다.

---

## 8. 동결 확인 (변경 없음)

본실험 전에 이미 동결됐으며 이번 커밋에서 수정하지 않은 항목:
- `experiments/python-evidence-s1-throughput/sample_manifest.json` (32 clip, sha256 동결)
- `experiments/python-evidence-s1-throughput/influx_snapshot.json` (projected_4_camera_p95=80.0)
- §3 처리 조건 (A6/B12/CROI/DALL), §5 합격 기준, §7 Stop rules, §8 Decision 룰

---

## 9. 종료

- 판정: **`READY_FOR_SAFE_WINDOW`** — H1/H2/H3 수정 완료, 512/512 테스트 통과, push 완료.
- 다음: Mac mini에서 `≥25분 안전창` 확인 후 본실험 실행.
  ```bash
  uv run python scripts/benchmark_python_evidence_s1.py \
    --manifest experiments/python-evidence-s1-throughput/sample_manifest.json \
    --influx experiments/python-evidence-s1-throughput/influx_snapshot.json \
    --pinned-sha 4404dd10defb3d157cf3106ec23a6a4afc3455d7 \
    --out-dir /tmp/s1_out --device mps --checkpoint <ckpt.pth> \
    --activity-lock-free --vlm-lock-free --window-minutes <N>
  ```
- 결과는 `experiments/python-evidence-s1-throughput/REPORT.md` 에만 기입.
