# R1 Mac mini runtime P3 v2 deploy rollback 보고

## 판정

`V2_DEPLOY_ROLLED_BACK_AFTER_OFFTARGET_ROOT`

runtime fix SHA `a47bea6202b708dd0066155d41904dcb19fccbe5`는 새 `HANDOFF_OK`, 40 tests,
14 adversarial markers, RunAtLoad 2회를 통과했어. 하지만 manual canary 제출 단계에서
`scripts/researchctl` 기본 root가 LaunchAgent root와 달라 off-target ledger가 생겨 즉시
rollback하고 중단했어.

## 통과한 단계

- runtime checkout: `a47bea6202b708dd0066155d41904dcb19fccbe5`, detached clean
- handoff v2 SHA-256:
  `bfdb68b2449c619087244169b4c74275a8b18949f6665a4c258b3459385f392e`
- canary v2 SHA-256:
  `febc19a0e431958fec2dde1957ab5a84ea4696d46c48971d722788c270ca3231`
- `HANDOFF_OK task=r1-mac-mini-runtime-p3-install repo=petcam-lab-research-runtime commit=a47bea62 runtime=launchagent@baeg-endeuui-Macmini.local`
- `uv run pytest -q tests/research_runtime`: `40 passed`
- adversarial markers 14개 + `R1_RESIDUE_ZERO`
- `bash -n scripts/researchctl scripts/install_research_runtime_launchd.sh`
- RunAtLoad 1: `runs = 1`, `last exit code = 0`
- RunAtLoad 2: `runs = 1`, `last exit code = 0`

## block

handoff v2의 canary command는 root를 명시하지 않았다.

```bash
scripts/researchctl submit --spec "<audit-copy>"
```

`researchctl` 기본 root는 `~/.petcam-research-runtime`이고, LaunchAgent root는
`~/Library/Application Support/petcam/research-runtime`이다. 그래서 canary
`r1-p3-synthetic-canary-002`가 target ledger가 아닌 off-target default ledger에 queued로 들어갔다.

증거:

```text
target root status: {"jobs":[],"schema_version":1}
default root status: {"jobs":[{"attempt":0,"cancel_requested":false,"job_id":"r1-p3-synthetic-canary-002","state":"queued"}],"schema_version":1}
```

## rollback

다음을 수행했다.

```bash
launchctl bootout gui/501/com.petcam.research-runtime
rm "$HOME/Library/LaunchAgents/com.petcam.research-runtime.plist"
rm "$HOME/.petcam-research-runtime/events/events.jsonl" "$HOME/.petcam-research-runtime/ledger.sqlite3"
rmdir "$HOME/.petcam-research-runtime/events" "$HOME/.petcam-research-runtime/jobs" "$HOME/.petcam-research-runtime"
```

확인:

```text
TARGET_SERVICE_ABSENT_POSTROLLBACK
OFFTARGET_DEFAULT_ROOT_REMOVED
GEMINI_CLI_STILL_ABSENT
PRODUCTION_BASELINE_UNCHANGED
```

target runtime ledger는 jobs 0이고, media/temp residue 0, secret-like match 0이다.

## 다음 안전 조건

재시도 전 handoff canary command는 target root를 명시해야 해.

```bash
RESEARCH_RUNTIME_ROOT="$HOME/Library/Application Support/petcam/research-runtime" \
scripts/researchctl submit --spec "<audit-copy>"
```

또는:

```bash
scripts/researchctl \
  --root "$HOME/Library/Application Support/petcam/research-runtime" \
  submit --spec "<audit-copy>"
```

이 보고 이후 service는 설치 상태가 아니므로 reboot recovery와 24시간 검증은 시작하지 않았다.
