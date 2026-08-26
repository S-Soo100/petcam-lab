---
handoff_version: 1
task_id: rap-c500g-r2-runtime
execution_repo: /Users/baek-end/.codex/worktrees/rap-c500g-r2/petcam-lab
plan_path: /Users/baek-end/.codex/worktrees/rap-c500g-r2/petcam-lab/docs/superpowers/plans/2026-08-26-rap-c500g-recorder-uploader.md
design_path: /Users/baek-end/.codex/worktrees/rap-c500g-r2/petcam-lab/docs/superpowers/specs/2026-08-26-rap-c500g-r2-recording-design.md
commit_sha: c0f44c81d8284694754aa7b78a1ac3aa4e83787e
implementation_host: BaekBook-Pro-14-M5
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.teraai.rap-c500g-recorder
---

# RAP C500G Mac mini runtime handoff

## 시작 계약

1. `/Users/baek-end/petcam-lab`의 기존 checkout, branch, production service를 수정하지 마.
2. origin에서 `codex/rap-c500g-r2-recording`을 fetch해 front matter의 `execution_repo`에 별도 worktree를 만들어.
3. 새 worktree HEAD는 manifest commit일 수 있지만, `commit_sha`의 정확한 후손 1개이고 그 차이는 이 manifest 하나뿐이어야 해.
4. 아래 validator가 literal `HANDOFF_OK`를 출력하기 전에는 migration, R2 write, camera capture, launchd install을 하지 마.

```bash
cd /Users/baek-end/.codex/worktrees/rap-c500g-r2/petcam-lab
uv run python scripts/verify_agent_handoff.py \
  --manifest /Users/baek-end/.codex/worktrees/rap-c500g-r2/petcam-lab/docs/handoff-prompts/2026-08-26-rap-c500g-r2-runtime-handoff.md
```

## 승인된 실행 범위

1. read-only preflight: hostname, HEAD, worktree clean, `.env` mode/필수 변수 **이름만**, `.23/.24/.25` 연결, ffmpeg/ffprobe/uv, local root free space.
2. migration SQL을 먼저 정적 검토하고 현재 Supabase에 동일 table이 없는지 read-only 확인해. 적용 직전 상태를 보고하고, Owner 승인된 이번 handoff 범위 안에서 forward migration을 1회 적용해.
3. `uv run python -m backend.rap_c500g_main test --duration 60`으로 세 카메라를 동시에 60초 녹화해.
4. R2 write는 `c500g` 버킷의 새 `test/<run-id>/` prefix에 있는 video/thumbnail/sanitized log/manifest에만 허용해.
5. local 12 artifact, ffprobe/decode, R2 HEAD size/SHA metadata, manifest-last, DB 3행을 검증해. 원본·R2 object·DB row는 삭제하지 마.
6. 실제 test canary가 모두 통과하기 전에는 launchd를 설치하지 마.
7. launchd 설치 뒤 loaded 상태, working directory, repo HEAD, service label을 확인해. 현재 시간이 야간 slot이면 자동 장기녹화가 시작될 수 있으므로 설치 직전 Owner에게 다시 알리고 진행해.

## 절대 경계

- RTSP username/password, 전체 RTSP URL, R2 credential, Supabase service-role 값을 출력하거나 전달하지 마.
- 기존 `camera_clips`, `motion_clips`, GME, 행동 GT, 기존 R2 prefix를 쓰거나 수정하지 마.
- 기존 Mac mini production service를 unload/restart/수정하지 마.
- local bundle 자동 삭제, R2 삭제, DB DELETE/UPDATE/TRUNCATE를 하지 마.
- 실패 시 같은 key를 임의 덮어쓰거나 새 이름으로 우회하지 말고 오류 코드와 안전한 수량만 보고해.
