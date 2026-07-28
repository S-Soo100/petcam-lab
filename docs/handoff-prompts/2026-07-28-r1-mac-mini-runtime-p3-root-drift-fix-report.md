# R1 Mac mini runtime P3 researchctl root drift 수정 보고

## 판정

`ROOT_DRIFT_FIXED_READY_FOR_V3_HANDOFF`

v2 manual canary rollback 원인은 LaunchAgent와 `researchctl`의 기본 data root가 달랐기
때문이야.

- LaunchAgent/runtime:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime`
- 기존 `researchctl` default:
  `/Users/baek-end/.petcam-research-runtime`

`scripts/researchctl`은 Python CLI로 인자를 그대로 넘기고, CLI parser가 root를 생략한 모든
명령에 legacy default를 넣었다. 그래서 `submit/status/show/tail/cancel` 모두 같은 CLI
root를 사용했지만 service ledger와는 갈라질 수 있었다.

## RED -> GREEN

RED 테스트는 임시 HOME에서 root 인자와 `RESEARCH_RUNTIME_ROOT`를 모두 생략한 뒤
`submit -> status -> show -> tail -> cancel`을 연속 호출했다. canonical target ledger만
생기고 legacy root는 생기지 않아야 한다.

```text
uv run pytest -q tests/research_runtime/test_cli.py::test_default_root_is_canonical_for_every_command
1 failed
target_root/ledger.sqlite3 absent
```

최소 수정은 `backend/research_runtime/cli.py`의 fallback root 한 곳을 LaunchAgent와 같은
macOS canonical root로 바꾼 거야. explicit `--root`와 `RESEARCH_RUNTIME_ROOT` 우선순위는
그대로 유지한다.

```text
uv run pytest -q tests/research_runtime/test_cli.py::test_default_root_is_canonical_for_every_command
1 passed
```

## 검증

- runtime branch: `codex/r1-runtime-launchd-exit6-fix`
- previous runtime SHA: `a47bea6202b708dd0066155d41904dcb19fccbe5`
- new runtime SHA: `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`
- `uv run pytest -q tests/research_runtime`: `41 passed`
- adversarial marker 14줄, 마지막 marker `R1_RESIDUE_ZERO`
- `bash -n scripts/researchctl scripts/install_research_runtime_launchd.sh`: exit 0
- provider/DB/R2/media/dataset/model/Claude/VLM/local LLM 접근: 0
- production service mutation: 0
- `~/.petcam-research-runtime`: absent

## v3 입력

- handoff:
  `docs/handoff-prompts/2026-07-28-r1-mac-mini-runtime-p3-install-handoff-v3.md`
- manual canary:
  `docs/research/run-manifests/jobs/2026-07-28-r1-p3-synthetic-canary-v3.json`
- SIGKILL recovery:
  `docs/research/run-manifests/jobs/2026-07-28-r1-p3-sigkill-recovery-v3.json`
- handoff SHA-256:
  `071336b5a37f750c5247e52641ba1209cd828e98e2ac91a419d6935dfc9b81b4`
- manual canary SHA-256:
  `1b5e45b980a237c7466f869eb7b22b88d73e132541481c59f62ee58da68a9d57`
- SIGKILL recovery SHA-256:
  `2ca0e02d4c3f1f57cb4978355c89e8cefea287414b994c7bdf0284c743ee647e`

v3 `HANDOFF_OK` 전에는 설치하지 않는다.
