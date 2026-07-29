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

# R1 Mac mini 연구 runtime P3 설치 handoff v12

## 변경 사유

v11은 RunAtLoad부터 marker full dry-run까지 통과했지만 non-interactive sudo authorization
preflight가 실패해 shutdown 명령 전에 exact target과 marker를 rollback했어.

사용자 승인으로 `baek-end`에 exact `/sbin/shutdown -r now`만 허용하는 root-owned
NOPASSWD sudoers 정책을 설치하고 문법·command match·다른 sudo 명령 차단을 검증했다.
v12는 fresh `012` IDs, baseline, audit copy와 marker를 사용한다. v11 감사 이력은
그대로 보존한다.

## provenance

- runtime SHA:
  `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`
- v11 rollback control SHA:
  `b0a48afbb50e3da980d9ce59b6cd5ed1ac42cc2b`
- verifier fix control SHA:
  `61b3caafb3ea3b4b9d65a67a3460bdbe6ef5da87`
- reboot verifier SHA-256:
  `8982bafadb5dd8e9fd7baa3a1f6adc6d84d73c0a9450f090c28babeaa132c389`
- attempt verifier SHA-256:
  `65691b35ecd0570017b8928bdc64798729ed49bd149eaf64def4f07ec3f6c29d`
- manual v12 SHA-256:
  `c03896f543ef5a56c91151633bb7419fe4d0ef8ddfeb7099d88d98f2e29cd709`
- recovery v12 SHA-256:
  `6e50c56ba07fd16284a66e5ceae47f4b9135477a3652e1648aadf54d3d37fac5`
- runtime root:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime`
- target label:
  `com.petcam.research-runtime`
- expected-absent label:
  `com.petcam.vlm-backfill-finalizer`
- exact reboot sudoers:
  `/private/etc/sudoers.d/petcam-research-runtime-reboot`
- exact NOPASSWD command:
  `/sbin/shutdown -r now`

fresh v12 이후 production DB/R2/media/dataset/model, Claude/VLM/local LLM/provider 접근과
production service 변경은 0이어야 해. primary checkout은 읽거나 수정하지 않는다.
Gemini CLI 폐기 상태를 유지한다.

## 설치 전 gate

target/finalizer service/plist/process와 legacy root absent, runtime/control exact
clean/upstream을 확인한다. production plist 7개 hash/WorkingDirectory와 finalizer absent
sentinel을 `r1-p3-production-immutable-baseline-v12.json`에 mode 0600으로 기록한다.

sudoers는 root-owned mode 0440이어야 하고 다음 probe만 NOPASSWD로 match해야 한다.

```bash
sudo -n -l /sbin/shutdown -r now
```

handoff, reboot verifier, attempt verifier와 `012` specs를 runtime root에 mode 0600으로
복사하고 hash를 대조한다. 새 `HANDOFF_OK`를 확보한다.

code gate:

- control attempt verifier tests 4
- control reboot verifier tests 8
- total control tests 12
- system Python compile
- runtime tests 41
- adversarial markers 14 + `R1_RESIDUE_ZERO`
- installer/CLI bash syntax

production guard가 충분한 연속 구간에서 자연 `allowed=True`일 때만 설치한다.

## RunAtLoad, manual, natural

RunAtLoad 1 exit 0과 exact WD/root/HEAD/60초를 확인한다. exact target만 제거하고 control
cwd에서 v12 baseline을 재검증한 뒤 RunAtLoad 2를 같은 방식으로 확인한다.

manual `012`을 root option/env 없이 submit하고 target만 kickstart한다. canonical ledger
tuple이 `succeeded|1|1|0|0|0|NULL`이어야 한다. launchd `runs`를 baseline으로 잡고
kickstart 없이 두 자연 cycle 증가, exit 0, manual tuple 불변을 확인한다.

## SIGKILL과 tracked post-check

recovery `012`을 default root로 submit한다. ledger `running|PID|1|1`과 process ownership,
checkout, parent/child PGID를 assert한 뒤 exact child, parent PGID만 SIGKILL한다. 다음
자연 cycle에서 `succeeded|PID|2|3|0`이어야 한다.

post-check는 다음 tracked helper만 실행한다.

```bash
cd /Users/baek-end/petcam-lab-r1-runtime-p3-control
/usr/bin/python3 scripts/verify_research_runtime_attempt.py \
  --runtime-root "$HOME/Library/Application Support/petcam/research-runtime" \
  --baseline "$HOME/Library/Application Support/petcam/research-runtime/audit/r1-p3-production-immutable-baseline-v12.json" \
  --launch-agents-dir "$HOME/Library/LaunchAgents" \
  --manual-job-id r1-p3-synthetic-canary-012 \
  --recovery-job-id r1-p3-sigkill-recovery-012
```

마지막 출력은 `R1_ATTEMPT_VERIFIED`여야 한다.

## reboot와 24시간

current clean control SHA/upstream, runtime SHA, target plist/hash, pre boot sec, v12
baseline/hash, 두 verifier/handoff hash와 `012` 결과를 schema 2 marker에 mode 0600으로
원자 기록한다. boot sec만 다른 임시 marker로 full reboot verifier preflight를
통과시킨다.

post-reboot heartbeat를 durable하게 예약한 뒤 exact 명령만 실행한다.

```bash
sudo -n /sbin/shutdown -r now
```

reboot 후 `R1_RUNTIME_P3_REBOOT_RECOVERY_OK`일 때만 24시간 시작/완료 예정 시각을 기록하고
`R1_RUNTIME_P3_PENDING_24H`로 service를 유지한다. 24시간 검증이 끝난 뒤 sudoers 정책을
관리자 인증으로 제거한다.

어느 단계든 오류, drift, off-target mutation이면 exact target만 bootout/remove하고 뒤
단계로 가지 않는다. reboot command 전 실패면 pending marker도 제거한다.
