# RAP C500G recorder 운영 절차

## 설치 전 gate

1. Mac mini의 repo HEAD와 handoff manifest SHA가 일치하고 `HANDOFF_OK`인지 확인해.
2. `.env` mode가 `0600`이고 cam01~03, R2, Supabase 변수 이름이 있는지만 확인해.
3. Ethernet 우선 경로와 `.23/.24/.25` 카메라 연결을 확인해.
4. `ffmpeg`, `ffprobe`, `uv`, local root 여유 공간을 확인해.
5. `2026-08-26_rap_c500g_recordings.sql` 적용 전에는 daemon을 켜지 마.

외장 저장장치를 local root로 쓰면 `RAP_C500G_REQUIRED_MOUNT`를 실제 볼륨 mount path로
설정해. recorder는 `RAP_C500G_LOCAL_ROOT`가 그 mount 내부이고 볼륨이 실제로 마운트된
경우에만 시작한다. USB가 빠졌을 때 `/Volumes` 아래 내부 SSD 폴더로 우회 기록하지 않는다.

## 60초 test canary

```bash
uv run python -m backend.rap_c500g_main test --duration 60
```

세 camera마다 `video.mp4`, `thumbnail.jpg`, `ffmpeg.sanitized.log`, `manifest.json`이 로컬/R2에
있고 HEAD size/hash, DB 3행, Owner 웹 재생이 맞아야 성공이야.

## launchd 설치

### 시각화 매니저 (현재 운영 권장)

시각화 매니저는 기존 capture/manifest/R2/DB 계약을 그대로 쓰면서 30분 wall-clock 구간,
카메라별 독립 재시도, 외장 저장소 fail-closed, 로컬 UI와 상태 CLI를 한 프로세스에서 관리해.

```bash
uv run python scripts/render_rap_c500g_manager_launchd.py \
  --repo /absolute/petcam-lab \
  --uv /opt/homebrew/bin/uv \
  --log-dir /Users/baek-end/Library/Logs/rap-c500g-manager \
  --state-path "/Users/baek-end/Library/Application Support/rap-c500g-manager/manager.sqlite3" \
  --output /Users/baek-end/Library/LaunchAgents/com.teraai.rap-c500g-manager.plist
```

설치 전까지는 기존 `com.teraai.rap-c500g-recorder`를 유지해. 전환할 때는 활성 FFmpeg가 0인지
확인하고 기존 recorder를 먼저 unload한 다음 새 manager의 60초 진단을 실행해. manager는 기존
service가 loaded이거나 FFmpeg가 하나라도 살아 있으면 fail-closed로 시작을 거부해. 진단이 실패하면
manager를 시작하지 말고 기존 recorder를 즉시 rollback해. 두 production service 동시 실행은 금지해.

```bash
launchctl bootout gui/$(id -u)/com.teraai.rap-c500g-recorder
uv run python -m backend.rap_c500g_manager_main --state-path \
  "/Users/baek-end/Library/Application Support/rap-c500g-manager/manager.sqlite3" \
  diagnostic --duration 60
launchctl bootstrap gui/$(id -u) /Users/baek-end/Library/LaunchAgents/com.teraai.rap-c500g-manager.plist
launchctl print gui/$(id -u)/com.teraai.rap-c500g-manager
```

진단 실패 rollback:

```bash
launchctl bootstrap gui/$(id -u) /Users/baek-end/Library/LaunchAgents/com.teraai.rap-c500g-recorder.plist
```

Mac mini에서 `http://127.0.0.1:8766/`를 열면 dashboard/settings/60초 진단을 쓸 수 있어.
MacBook에서 상태를 물을 때는 Mac mini에서 아래 read-only JSON만 읽어.

```bash
uv run python -m backend.rap_c500g_manager_main --state-path \
  "/Users/baek-end/Library/Application Support/rap-c500g-manager/manager.sqlite3" \
  status --json
```

정상은 exit 0, manager unavailable은 2, 저장소 차단·미복구 incident는 3이야. JSON과 UI에는
credential, 전체 RTSP URL, 실제 mount 절대경로가 들어가지 않아.

capture-first 상태는 같은 JSON의 `pipeline`에서 확인해. 야간 정상은
`mode=capture`, `finalize.active=0`이고 raw upload 대기가 녹화와 독립적으로 줄어드는 상태야.
주간 정상은 `mode=finalize`, 새 capture가 0이며 `finalize.completed`가 증가하는 상태야.
`19:30~20:00`은 `mode=drain`으로 새 후처리를 시작하지 않아 다음 야간 녹화를 보호해.

원본 R2 업로드가 끝났지만 최종 검증 대기 중인 row는 정상 대기야. 재시작 뒤에도 SQLite의
`raw_uploaded` 상태에서 이어가며 같은 camera/slot을 다시 녹화하지 않아. 첫 12시간 acceptance는
실제 24 slot, 카메라 3대의 결과가 모두 관측된 뒤에만 완료로 판정해.

### 이전 recorder (rollback용)

```bash
uv run python scripts/render_rap_c500g_launchd.py \
  --repo /absolute/petcam-lab \
  --log-dir /Users/baek-end/Library/Logs/rap-c500g \
  --output /Users/baek-end/Library/LaunchAgents/com.teraai.rap-c500g-recorder.plist
launchctl bootstrap gui/$(id -u) /Users/baek-end/Library/LaunchAgents/com.teraai.rap-c500g-recorder.plist
```

`launchctl print gui/$(id -u)/com.teraai.rap-c500g-recorder`로 loaded 상태를 확인해.

## 점검과 복구

### 검증 기반 local prune

local 정리는 항상 exact root와 dry-run으로 시작해. 아래 명령은 경로·키를 출력하지 않고 후보 수,
bytes, 제외 이유, plan digest만 보여줘.

```bash
uv run python scripts/prune_rap_c500g_local.py \
  --root /Volumes/RAP-C500G/RAP-c500g-recordings
```

실행은 Owner가 같은 plan digest를 확인한 뒤에만 `--execute --plan-digest <SHA256>`를 함께 사용해.
도구는 execute 직전에 volume UUID/device/root inode, symlink·containment, active/current/partial 상태,
R2 네 object의 size/SHA와 manifest-last, DB captured/uploaded, local pipeline
`verified_uploaded`를 다시 검증해. 하나라도 달라지면 삭제 0으로 중단해.

삭제 대상은 검증된 slot bundle의 `video.mp4`, `thumbnail.jpg`, `ffmpeg.sanitized.log`,
`manifest.json` 네 파일뿐이야. root/prefix/bulk 삭제, R2·DB 삭제, USB 포맷 기능은 없어. receipt는
USB 밖의 `/Users/baek-end/Library/Application Support/rap-c500g-manager/prune-audit`에 0700/0600
append-only로 남겨. 현재·직전 night, active claim, partial/stale/recovery bundle은 항상 제외해.

- 20:00~08:00에는 카메라당 30분 slot, night당 총 72개를 기대해.
- `uv run python -m backend.rap_c500g_main sync`는 local manifest를 다시 스캔해.
- 디스크 부족이나 R2 장애 때 로컬 파일을 자동 삭제하지 마.
- 외장 볼륨이 없어서 시작이 거부되면 USB를 다시 마운트한 뒤 service를 재시작해. 내부 SSD
  경로로 임의 fallback하지 마.
- 중지는 아래처럼 service만 unload하고 녹화 root/R2/DB/`.env`는 보존해.

```bash
launchctl bootout gui/$(id -u)/com.teraai.rap-c500g-recorder
```
