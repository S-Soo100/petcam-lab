---
handoff_version: 1
task_id: r1-mac-mini-runtime-p3-install
execution_repo: /Users/baek-end/petcam-lab-research-runtime
plan_path: /Users/baek-end/petcam-lab-research-runtime/docs/research/R1-RUNTIME-RUNBOOK.md
design_path: /Users/baek-end/petcam-lab-research-runtime/scripts/install_research_runtime_launchd.sh
commit_sha: 7267b642dd9e25a0e199e57c5d41d1e2c04ee419
implementation_host: baeg-endeuui-Macmini.local
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.petcam.research-runtime
---

# R1 Mac mini 연구 runtime P3 설치 handoff v9

## 변경 사유

v8 RunAtLoad 2회와 manual job 자체는 성공했지만 orchestration이 `researchctl show --json`의
nested envelope를 top-level field로 읽어 timeout 처리했어. ERR trap으로 target은 제거됐다.

v9은 fresh `009` IDs를 쓰고 job 판정은 canonical ledger의 structured SQL tuple만 사용한다.

## 고정값

- runtime SHA:
  `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`
- verifier SHA-256:
  `8982bafadb5dd8e9fd7baa3a1f6adc6d84d73c0a9450f090c28babeaa132c389`
- manual v9 SHA-256:
  `af9569554e3fb7f75348f0a9371b2c04ab1fcd0d86017911debf031a4f5abc8d`
- recovery v9 SHA-256:
  `31ca9c1d1f935ca89a3345cb6b57b595bb72c1ac72b419005fb87b01c39c4d35`
- runtime root:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime`
- legacy root:
  `/Users/baek-end/.petcam-research-runtime`
- target label:
  `com.petcam.research-runtime`
- expected-absent label:
  `com.petcam.vlm-backfill-finalizer`

fresh v9 이후 production DB/R2/media/dataset/model, Claude/VLM/local LLM/provider 접근,
production service 변경과 primary checkout read는 0이어야 해.

## 실행 gate

1. target/finalizer/legacy absent, runtime/control exact clean/upstream을 확인한다.
2. production plist 7개 hash/WorkingDirectory와 finalizer absent sentinel을 새
   `r1-p3-production-immutable-baseline-v9.json`에 mode 0600으로 기록한다.
3. baseline verifier는 control checkout cwd에서 실행한다.
4. handoff/spec/verifier audit copy hash를 대조하고 새 `HANDOFF_OK`를 받는다.
5. verifier 8, runtime 41, adversarial 14 + `R1_RESIDUE_ZERO`, compile/bash를 통과한다.
6. production guard가 충분한 연속 구간에서 자연 `allowed=True`여야 한다.

## RunAtLoad와 manual

exact installer로 RunAtLoad 1을 검증하고 target만 제거한다. control cwd에서 v9 baseline을
재검증한 뒤 RunAtLoad 2를 검증한다.

manual spec은 root option/env 없이 submit하고 target만 kickstart한다. 판정 SQL:

```sql
select state, attempt
from jobs
where job_id = 'r1-p3-synthetic-canary-009';
```

tuple이 정확히 `succeeded|1`이어야 한다. legacy root는 생성되면 안 된다.

## 자연 cycle과 SIGKILL

manual 성공 시 launchd `runs`를 baseline으로 잡고 kickstart 없이 두 번 증가하는 동안 exit 0,
manual tuple `succeeded|1` 불변을 확인한다.

recovery spec을 default root로 submit한다. ledger tuple
`running|PID|1|1`을 확인하고 PID의 user/checkout/command, parent PGID와 단일 child PGID를
assert한다. exact research child PGID, parent PGID 순서로 SIGKILL한다.

다음 자연 cycle이 stale lease를 reclaim해 recovery tuple
`succeeded|2|3|0`으로 끝나야 한다. attempt 1 result, duplicate success, orphan process,
provider/cost/media/model/legacy/secret residue는 모두 0이어야 한다.

## reboot와 24시간

앞 단계 통과 뒤 current clean control SHA/upstream, runtime SHA, target plist/hash, pre boot sec,
v9 baseline/hash, verifier/handoff hash와 실제 `009` 결과로 schema 2 marker를 원자 작성한다.
boot sec만 다른 임시 marker로 full verifier preflight를 통과시킨다.

reboot 후 `R1_RUNTIME_P3_REBOOT_RECOVERY_OK`일 때만 24시간 시작/완료 예정 시각을 기록하고
`R1_RUNTIME_P3_PENDING_24H`로 service를 유지한다.

어느 단계든 오류, drift, off-target mutation이면 exact target만 bootout/remove하고 뒤
단계로 가지 않는다.
