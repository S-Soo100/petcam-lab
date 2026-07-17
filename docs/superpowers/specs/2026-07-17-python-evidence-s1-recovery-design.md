# Python Evidence S1 Recovery Design

**상태:** 승인됨  
**작성일:** 2026-07-17  
**선행 결과:** `S1_HOLD_RUNTIME_BUDGET` (`2026-07-17 04:41~05:01 KST`)  
**목표:** 운영 워커를 중단하지 않고, 동결된 S1 표본·조건·반복을 그대로 완주해 CROI 처리량 채택 게이트를 판정한다.

## 1. 확인된 문제

첫 S1 실행은 Mac mini에서 20분 hard budget을 정상 준수했지만 full workload를 끝내지 못했다. 완료된 CROI cold 셀은 약 `1,417 clips/h`로 요구 용량 `160 clips/h`보다 충분히 높았으나, A6·warm·CPU가 미완이라 PASS가 아니다.

A6 99건의 `FileNotFoundError` 원인은 2026-07-17 10:50 KST read-only 실측으로 확정됐다.

- SSH 비로그인 환경 `PATH=/usr/bin:/bin:/usr/sbin:/sbin`
- FFmpeg 실제 위치 `/opt/homebrew/bin/ffmpeg`
- 같은 Python 환경에서 `shutil.which("ffmpeg") is None`
- `reporter.vlm_frames.extract_six`는 `subprocess.run(["ffmpeg", ...])`을 사용한다.

따라서 기존 보고서의 “PYTHONPATH 혼합 또는 임시경로 문제”는 근거 없는 추정이며 정정해야 한다. production `extract_six` 결함이 아니라 benchmark 실행 환경의 의존성 전파 결함이다.

## 2. 채택한 복구 방식

운영 LaunchAgent를 중단하지 않고, 동일 workload를 여러 개의 독립적인 20분 이하 안전 구간에서 `--resume`으로 완주한다.

- 기존 S1 결과와 verdict는 역사 기록으로 보존한다.
- recovery는 새 output directory와 새 preregistration을 사용한다.
- 기존 partial raw record를 재사용하지 않고 전체 workload를 처음부터 다시 측정한다.
- 표본 32개, reduced 표본 16개, 조건 A6/B12/CROI/DALL, threshold `0.10`, warmup `1`, measured repeat `3`을 바꾸지 않는다.
- 바뀌는 것은 실행 스케줄뿐이다. 한 번의 20분 run이 아니라 여러 20분 run이 append-safe resume로 동일 workload를 완성한다.
- 각 run은 다음 production job까지 최소 25분, activity/VLM lock free를 만족해야 시작한다.
- 각 run은 최대 20분이며 deadline 도달 시 cleanup 후 정상적인 partial checkpoint로 종료한다.

이 복구 결과는 기존 `S1_HOLD_RUNTIME_BUDGET`을 소급 변경하지 않는다. 새 verdict는 `S1R_*` 네임스페이스로 기록한다.

## 3. 고려한 대안

### A. 운영 워커를 60분 이상 중단하고 한 번에 실행

실험은 단순하지만 production 런타임을 인위적으로 바꾸므로 기각한다. throughput 측정을 위해 실제 운영 안전을 희생할 이유가 없다.

### B. 표본·warmup·repeat 축소

결과를 확인한 뒤 workload를 줄이는 사후 시험 변경이므로 기각한다. 기존 CROI의 유망한 수치가 과대평가될 위험이 있다.

### C. 운영 유지 + 분할 resume

채택한다. 이미 구현된 append-safe key를 활용하고, scientific workload와 판정 기준은 유지하면서 운영 충돌만 피한다.

## 4. 시스템 경계

### 변경 허용

- `petcam-lab` benchmark preflight와 테스트
- recovery 전용 TEST-SHEET·raw/summary/report 경로
- 기존 S1 보고서의 A6 원인 정정 문구
- SOT의 recovery 진행 상태
- Mac mini feature worktree pull과 read-only foreground benchmark

### 변경 금지

- `petcam-nightly-reporter/reporter/vlm_frames.py`
- production Gate/nightly repo HEAD
- LaunchAgent bootout/bootstrap/plist/env
- Supabase write/RPC/migration
- R2 write/delete
- Claude/VLM 호출
- selector·GT·behavior label·app activity 변경
- original `raw_results.jsonl` 삭제·재작성
- sample/threshold/warmup/repeat 사후 축소

## 5. 의존성 계약

benchmark는 detector/R2 import 전에 다음을 fail-closed 검사한다.

1. `shutil.which("ffmpeg")`가 절대경로를 반환한다.
2. 반환 경로가 실행 가능한 regular file 또는 executable symlink다.
3. `ffmpeg -version`이 제한 시간 안에 exit `0`이다.
4. 실패 시 error code는 `ffmpeg_missing` 또는 `ffmpeg_unusable`만 출력하고 비밀값·전체 PATH는 출력하지 않는다.

Mac mini 실행 명령은 production LaunchAgent와 같은 최소 PATH를 명시한다.

```text
/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
```

## 6. Recovery 데이터 흐름

1. 기존 manifest/influx SHA를 recovery TEST-SHEET에 재고정한다.
2. 빈 recovery output directory에서 시작한다.
3. A6 한 clip canary로 exact `extract_six` 6장 생성·cleanup을 확인한다.
4. MPS cold를 여러 안전창에서 resume한다.
5. MPS warm을 여러 안전창에서 resume한다.
6. CPU reduced 16을 별도 안전창에서 resume한다.
7. raw record completeness matrix를 검사한다.
8. 독립 계산기가 p50/p95/capacity/resource/safety를 재계산한다.
9. 정확히 하나의 `S1R_*` verdict를 기록한다.

## 7. 완전성 계약

성공 판정 전에 condition/device/cache_mode/clip/repeat의 예상 key와 실제 유효 key가 정확히 일치해야 한다.

- MPS: 32개 A6/B12/CROI + reduced 16개 DALL
- CPU: reduced 16개 A6/B12/CROI/DALL
- cache mode: `cold_independent`, `warm_same_run`
- 각 measured key: repeat `1..3`
- warmup record는 존재할 수 있지만 p50/p95에서 제외
- `error_code`가 있는 measured key는 완료로 취급하지 않고 명시적으로 재시도 가능해야 함
- 동일 measured key 중복 성공 record는 0

## 8. 안전과 오류 처리

- FFmpeg preflight 실패: R2·detector·temp 전에 즉시 중단.
- A6 canary 실패: recovery full run 금지, traceback은 로컬 임시 진단에만 보존하고 보고서는 sanitized code만 기록.
- lock busy 또는 안전창 부족: 아무 작업 없이 대기.
- deadline: 현재 adapter 완료 뒤 중단, temp cleanup, partial JSONL 유지.
- 단일 clip decode 실패: sanitized error record 후 다음 run에서 해당 measured key만 재시도.
- detector/R2 계통 실패: 해당 run 중단.
- production job 지연·exit/error 증가·temp leak·mutation 발견: 즉시 `S1R_REJECT_OPERATIONAL_RISK`.

## 9. 판정

- `S1R_PASS_CROI_THROUGHPUT`: 전체 key 완전성 + CROI MPS cold capacity `>=160 clips/h` + 모든 안전 게이트 통과.
- `S1R_REJECT_CROI_THROUGHPUT`: 전체 key는 완성됐지만 CROI MPS cold capacity `<160 clips/h`.
- `S1R_HOLD_INCOMPLETE`: 의존성·안전창·반복 오류 때문에 전체 key를 완성하지 못함.
- `S1R_REJECT_OPERATIONAL_RISK`: production 지연/오류, temp leak, write, VLM 호출 등 안전 위반.

`S1R_PASS_CROI_THROUGHPUT`만 S2 raw-evidence shadow 구현계획 작성으로 이어진다. PASS도 production selector 적용이나 자동 제외 승인은 아니다.

## 10. 산출물

- recovery TEST-SHEET: `experiments/python-evidence-s1-recovery/TEST-SHEET.md`
- recovery raw: Mac mini local ignored artifact `experiments/python-evidence-s1-recovery/raw_results.jsonl`
- recovery summary: `experiments/python-evidence-s1-recovery/summary.json`
- recovery report: `experiments/python-evidence-s1-recovery/REPORT.md`
- 사용자 보고: `docs/handoff-prompts/2026-07-17-python-evidence-s1-recovery-report.md`

## 11. 승인된 결론

S1은 폐기하지 않는다. A6 환경 계약을 먼저 복구한 뒤 동일 workload를 안전 구간별로 완주한다. 시험값을 줄이지 않고, 운영 서비스도 중단하지 않는다.
