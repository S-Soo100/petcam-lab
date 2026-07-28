# R1 Mac mini 연구 runtime P3 preinstall 보고

## 판정

`P3_START_VALIDATED_INSTALL_NOT_STARTED`

P3 설계·계획·start manifest와 Mac mini 실행 패키지는 준비됐어. 현재 세션에서는 Mac mini
접속, runtime checkout 생성, LaunchAgent plist 작성·bootstrap을 하지 않았어.

## provenance

- A 설계·계획:
  `d0e2663f66631c2384a9186c0ad12d3951eb95fb`
- M start manifest:
  `85a270f89d3803553203e91e9ee72841affd7cf0`
- M manifest SHA-256:
  `9cd0eabf298833e21ee8ae14d573ad13176cf1154923573a8f6fbfd4d2c93e46`
- runtime code C:
  `8a7ea47041d02180f2fe03ada54f39f45ccf7c26`
- controller branch: `codex/r1-mac-mini-runtime-p3-preinstall`
- target: `launchagent@baeg-endeuui-Macmini.local`
- label: `com.petcam.research-runtime`

## P3 start 검증

기본 CLI는 trusted approval backend가 없으므로 의도대로 차단됐어.

```text
RUN_MANIFEST_FAIL code=approval_verifier_missing
DEFAULT_VALIDATOR_RC=2
```

Owner가 현재 Codex task에서 승인한 exact task·phase·permission·host·service·runtime code만
true로 반환하는 controller-injected verifier로 다음 marker를 얻었어.

```text
RUN_MANIFEST_OK task=r1-mac-mini-runtime-p3-install repo=r1-mac-mini-runtime-foundation base=d0e2663f start_manifest=85a270f8 implementation=none record=85a270f8 permission=P3 model=gpt-5.6-sol runtime=launchagent@baeg-endeuui-Macmini.local
```

manifest 안의 승인 문구 자체를 승인 증거로 사용하지 않았어.

## 준비한 설치 입력

- runtime handoff:
  `docs/handoff-prompts/2026-07-28-r1-mac-mini-runtime-p3-install-handoff.md`
  - SHA-256:
    `317e09cb6fc5ef06565f4dede6bb1729a8b0eab7df7c34ccc29f748cb3d81404`
- synthetic canary:
  `docs/research/run-manifests/jobs/2026-07-28-r1-p3-synthetic-canary.json`
  - file SHA-256:
    `824bfe1df199effccfee680ea0ebc2d50018ce0a8c79608036054151c40ce830`
  - canonical spec SHA-256:
    `d4a1da4c17b7fb3f45a89e95bed11ebafbc0cd3c971858369c5239fa83dc368e`
- runtime checkout 예정 경로:
  `/Users/baek-end/petcam-lab-research-runtime`
- runtime data 예정 경로:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime`

laptop에서 handoff validator를 실행하면 runtime checkout이 아직 없어서
`HANDOFF_FAIL code=repo_missing`으로 차단돼. 이건 현재 stop 경계의 정상 증거야. Mac mini에서
checkout을 만든 뒤 위 SHA-256과 audit copy를 대조하고 `HANDOFF_OK`를 받아야 해.

## local verification

설치 패키지 commit 직전에 fresh 실행한 결과:

- research runtime·RUN-MANIFEST·handoff validator focused suite:
  `363 passed in 16.30s`
- adversarial harness: 아래 14 marker, exit 0
- Python compileall: exit 0
- installer·CLI `bash -n`: exit 0
- canary strict parser:
  `CANARY_SPEC_OK`, provider 0, cost 0, exact Mac mini host

```text
R1_SIGKILL_RECOVERY_OK
R1_REBOOT_FENCING_OK
R1_STALE_EPOCH_OK
R1_SINGLETON_OK
R1_MONOTONIC_CLOCK_OK
R1_PRODUCTION_DEFER_OK
R1_STARVATION_BLOCK_OK
R1_DEADLINE_OK
R1_DISK_FAILURE_OK
R1_REDACTION_OK
R1_BOUNDED_TAIL_OK
R1_LEDGER_FAIL_CLOSED_OK
R1_CANCEL_CLEANUP_OK
R1_RESIDUE_ZERO
```

commit 뒤에는 manifest가 M 이후 byte-identical인지, `git diff --check`, clean tree,
local==origin을 마지막으로 재확인해.

## mutation 0

현재 세션에서 다음은 모두 0이야.

- Mac mini SSH·desktop·filesystem 접근
- `/Users/baek-end/petcam-lab-research-runtime` 생성
- LaunchAgent plist 작성·bootout·bootstrap
- production DB/R2/media/dataset/checkpoint/model 접근
- Claude/VLM/local LLM/provider runtime call과 비용
- production service·main·credential 변경

Gemini CLI 폐기 승인은 별도 운영 정리 범위로 실행했어. MacBook에서는
`@google/gemini-cli@0.40.0` 전역 npm package와 `~/.gemini` CLI credential root를 제거했고,
다음을 확인했어.

```text
GEMINI_CLI_MACBOOK_REMOVED
```

Gemini API credential·backend는 변경하지 않았어. Mac mini는 아직 접속하지 않았으므로 실제
제거가 미실행 상태고, handoff 0번의 제거·부재 검증을 P3 checkout보다 먼저 수행해야 해.

폐기 후 검증:

- petcam runtime·handoff focused suite: `85 passed`
- ideaBank image dry-run backend chain:
  `codex-cli → gemini-api → openai-api`
- ideaBank Python compile·JSON parse·bash syntax·active CLI execution grep: 통과
- MacBook `command -v gemini`, package path, `~/.gemini`: 모두 없음

## 다음 실행

다음 실행은 handoff의 0번부터 시작해. Mac mini에서 Gemini CLI 제거를 확인하고 exact
checkout과 `HANDOFF_OK`까지 확인한 뒤
처음으로 installer를 실행할 수 있어. runtime 증거 전에는 `DEPLOYED`나
`RUNTIME_VERIFIED`를 주장하지 않아.
