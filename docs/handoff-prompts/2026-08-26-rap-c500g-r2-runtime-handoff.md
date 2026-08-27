---
handoff_version: 1
task_id: rap-c500g-manual-production-runtime
execution_repo: /Users/baek-end/.codex/worktrees/rap-c500g-r2/petcam-lab
plan_path: /Users/baek-end/.codex/worktrees/rap-c500g-r2/petcam-lab/docs/superpowers/plans/2026-08-26-rap-c500g-recorder-uploader.md
design_path: /Users/baek-end/.codex/worktrees/rap-c500g-r2/petcam-lab/docs/superpowers/specs/2026-08-26-rap-c500g-r2-recording-design.md
commit_sha: 17a555af1d9e13965d65b05f3a2ffea4f91dafd3
implementation_host: BaekBook-Pro-14-M5
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.teraai.rap-c500g-recorder
---

# RAP C500G 수동 production Mac mini runtime handoff

## 시작 계약

1. `/Users/baek-end/petcam-lab`의 기존 checkout과 다른 production service를 수정하지 마.
2. origin에서 `codex/rap-c500g-r2-recording`을 fetch해 기존 front matter의 `execution_repo`를 fast-forward해.
3. 새 worktree HEAD는 manifest commit일 수 있지만, `commit_sha`의 정확한 후손 1개이고 그 차이는 이 manifest 하나뿐이어야 해.
4. 아래 validator가 literal `HANDOFF_OK`를 출력하기 전에는 migration, R2 write, camera capture, launchd install을 하지 마.

```bash
cd /Users/baek-end/.codex/worktrees/rap-c500g-r2/petcam-lab
uv run python scripts/verify_agent_handoff.py \
  --manifest /Users/baek-end/.codex/worktrees/rap-c500g-r2/petcam-lab/docs/handoff-prompts/2026-08-26-rap-c500g-r2-runtime-handoff.md
```

## 승인된 실행 범위

1. read-only preflight: hostname, HEAD, worktree clean, `.env` mode/필수 변수 **이름만**, `.23/.24/.25` 연결, ffmpeg/ffprobe/uv, local root free space. 외장 root면 required mount의 실제 mount 상태도 확인해.
2. `uv run pytest -q tests/test_rap_c500g_*.py`를 실행해 C500G 회귀 테스트를 통과시켜.
3. 활성 production/test FFmpeg 캡처가 없을 때만 `uv run python -m backend.rap_c500g_main manual-production --duration 60`을 정확히 1회 실행해.
4. 새 결과는 USB와 `c500g` 버킷의 `recordings/camXX/night=YYYY-MM-DD/<timestamp>/`에 video/thumbnail/sanitized log/manifest로 저장해.
5. local 12 artifact, ffprobe/decode, R2 HEAD size/SHA metadata, manifest-last, DB production 3행을 검증해. 원본·R2 object·DB row는 삭제하지 마.
6. launchd는 변경하거나 재시작하지 말고 loaded 상태, working directory, repo HEAD, service label만 확인해.
7. 60초 canary가 통과하면 임시 야간 수동 자동화가 이후 `manual-production --duration 1800`을 호출할 수 있다고 보고해.

## 절대 경계

- RTSP username/password, 전체 RTSP URL, R2 credential, Supabase service-role 값을 출력하거나 전달하지 마.
- 기존 `camera_clips`, `motion_clips`, GME, 행동 GT, 기존 R2 prefix를 쓰거나 수정하지 마.
- Mac mini production service를 unload/restart/수정하지 마.
- local bundle 자동 삭제, R2 삭제, DB DELETE/UPDATE/TRUNCATE를 하지 마.
- 실패 시 같은 key를 임의 덮어쓰거나 새 이름으로 우회하지 말고 오류 코드와 안전한 수량만 보고해.
