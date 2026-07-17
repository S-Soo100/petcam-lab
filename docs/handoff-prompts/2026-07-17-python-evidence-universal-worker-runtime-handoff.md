---
handoff_version: 1
task_id: python-evidence-universal-worker-runtime
execution_repo: /Users/baek-end/petcam-nightly-reporter
plan_path: /Users/baek-end/petcam-nightly-reporter/install-launchd-python-evidence.sh
design_path: /Users/baek-end/petcam-nightly-reporter/reporter/python_evidence_worker.py
commit_sha: 618f4f854254525b0ebc6f0fcf9153f8e0cd6bc1
implementation_host: BaekBook-Pro-14-M5.local
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.petcam.python-evidence-worker
---

# Runtime Handoff — Python Evidence Universal Worker (Mac mini, steps 5~7)

> front-matter 는 `scripts/verify_agent_handoff.py` 계약(ALLOWED_KEYS 전용). 나머지 배포 컨텍스트는 body 에 둔다.
> **이 manifest 는 Mac mini(`baeg-endeuui-Macmini.local`, user `baek-end`)에서 검증·실행한다.** 구현 laptop 에서는
> execution_repo(`/Users/baek-end/...`)가 없어 HANDOFF_OK 를 만들 수 없다(설계상 execution host 에서 검증).

## 계약 값 (front-matter 매핑)

| manifest 값 | 내용 |
|---|---|
| execution_repo | `/Users/baek-end/petcam-nightly-reporter` (Mac mini nightly) |
| runtime_host | `baeg-endeuui-Macmini.local` |
| runtime_kind | `launchagent` (요청 "LaunchAgent") |
| runtime_label (=service_label) | `com.petcam.python-evidence-worker` |
| commit_sha | nightly main `618f4f854254525b0ebc6f0fcf9153f8e0cd6bc1` (execution_repo HEAD 와 일치해야 HANDOFF_OK) |
| plan_path | `install-launchd-python-evidence.sh` — runtime 배포 계획(installer) |
| design_path | `reporter/python_evidence_worker.py` — runtime 설계(worker 모듈) |

> plan/design 을 installer·worker 로 둔 이유: verify_agent_handoff.py 는 plan/design 이 execution_repo(nightly) 안의
> tracked 파일(commit_sha 시점·clean)이어야 HANDOFF_OK 를 낸다. nightly 는 code-only 라 runtime 아티팩트(installer=배포계획,
> worker=설계)를 plan/design 으로 지정한다.

## 세 레포 통합 SHA (Mac mini fetch + main ff-only 로 아래 SHA 포함 확인)

| 레포 | Mac mini 경로 | main SHA (포함 필수) |
|---|---|---|
| petcam-lab | `/Users/baek-end/petcam-lab` | `33964ff41a82c2b3275d7021167986a2833291d3` |
| petcam-nightly-reporter | `/Users/baek-end/petcam-nightly-reporter` | `618f4f854254525b0ebc6f0fcf9153f8e0cd6bc1` |
| gecko-vision-gate | `/Users/baek-end/myPythonProjects/gecko-vision-gate` (경로는 Mac mini 실제 clone 위치로 조정) | `9ea55eb740e9c87dd240b9282d612772dbc798f3` |

## DB 상태 (이미 배포됨 — Mac mini 는 DB migration 재적용 금지)

- `migration applied = true` (production `slxjvzzfisxqwnghvrit`, `2026-07-17_python_evidence_universal_worker.sql`, ~14:05 UTC).
- `live trigger coverage = 2/2` (신규 clip b0052819·11dd3233 → live job 자동 생성, missing 0).
- H3/H4 rollback probe 10/10 PASS, RLS·policy0·service_role-only, advisor 정상.
- worker 미배포라 job 은 queued 로 안전 누적 중(runs=0).

## Steps 5~7 runbook (Mac mini 에서 자동 수행)

**0) 사전 검증 (execution host 에서)**
```
cd /Users/baek-end/petcam-lab && git fetch origin && git checkout main && git merge --ff-only origin/main
uv run python scripts/verify_agent_handoff.py \
  --manifest /Users/baek-end/petcam-lab/docs/handoff-prompts/2026-07-17-python-evidence-universal-worker-runtime-handoff.md
# 기대: HANDOFF_OK task=python-evidence-universal-worker-runtime repo=petcam-nightly-reporter commit=618f4f85 runtime=launchagent@baeg-endeuui-Macmini.local
```

**1) 세 repo fetch + main ff-only + SHA 포함 확인**
```
for r in petcam-lab petcam-nightly-reporter myPythonProjects/gecko-vision-gate; do
  git -C /Users/baek-end/$r fetch origin && git -C /Users/baek-end/$r merge --ff-only origin/main
done
# petcam-lab HEAD==33964ff, nightly HEAD==618f4f8, gate HEAD==9ea55eb 확인. ff 불가면 중단 보고.
```

**2) foreground canary 5건 (LaunchAgent 설치 전, 수동)**
```
cd /Users/baek-end/petcam-nightly-reporter
# .env: PYTHON_EVIDENCE_ENABLED=1, PYTHON_EVIDENCE_EXPECTED_HOST=baeg-endeuui-Macmini.local,
#        PYTHON_EVIDENCE_GATE_THRESHOLD=0.10, PYTHON_EVIDENCE_BATCH_LIMIT=5
uv run python -m reporter.python_evidence_worker
```
확인(전부 충족해야 통과):
- 성공 5/5, `clip_prelabels` 신규 prelabel 5(없던 clip), `clip_python_evidence_runs` run 5
- provenance 완전(7-column + producer host/run/code_ref), threshold=0.10
- temp media 0(작업 후 임시 mp4 잔류 0)
- selector/VLM/app/GT/activity 결과 변경 0 (clip_activity_assessments/behavior_*/clip_vlm_jobs write 0)

**3) canary 통과 시 LaunchAgent 설치 (batch limit 30 복귀)**
```
PYTHON_EVIDENCE_ENABLED=1 PYTHON_EVIDENCE_EXPECTED_HOST=baeg-endeuui-Macmini.local \
PYTHON_EVIDENCE_GATE_THRESHOLD=0.10 bash install-launchd-python-evidence.sh
# service com.petcam.python-evidence-worker 등록 확인: launchctl print gui/$(id -u)/com.petcam.python-evidence-worker
```

**4) 자연 30분 cycle 1회 확인**
- exit 0, live job lag 정상, duplicate 0, incomplete provenance 0, temp 0.

**5) 역사 dry-run → 30건만 enqueue 및 처리**
```
uv run python -m scripts.enqueue_python_evidence_backfill --start-date <d> --end-date <d> --limit 30 --dry-run  # 조회만
uv run python -m scripts.enqueue_python_evidence_backfill --start-date <d> --end-date <d> --limit 30            # 30건 enqueue
```
- 누락·중복 0 확인 후 worker 가 30건 처리. **대량 enqueue 는 아직 금지.**

## fail-closed / 금지

- HANDOFF_OK 아니면 중단. ff-only 불가·SHA 불일치·canary <5/5·provenance 불완전·temp 잔류·capture 실패 시 즉시 중단 보고.
- selector/VLM/app/GT/activity 결과 변경 금지. migration 재적용 금지(이미 적용).

## 최종 verdict (Mac mini 세션이 선택)
- `UNIVERSAL_EVIDENCE_SHADOW_DEPLOYED_VERIFIED` (steps 5~7 전부 통과)
- `UNIVERSAL_EVIDENCE_DEPLOYMENT_BLOCKED` (fail-closed 발생)
