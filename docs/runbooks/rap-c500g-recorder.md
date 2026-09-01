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

Mac mini에서 `http://127.0.0.1:8765/`를 열면 dashboard/settings/60초 진단을 쓸 수 있어.
MacBook에서 상태를 물을 때는 Mac mini에서 아래 read-only JSON만 읽어.

```bash
uv run python -m backend.rap_c500g_manager_main --state-path \
  "/Users/baek-end/Library/Application Support/rap-c500g-manager/manager.sqlite3" \
  status --json
```

정상은 exit 0, manager unavailable은 2, 저장소 차단·미복구 incident는 3이야. JSON과 UI에는
credential, 전체 RTSP URL, 실제 mount 절대경로가 들어가지 않아.

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

- 20:00~08:00에는 카메라당 30분 slot, night당 총 72개를 기대해.
- `uv run python -m backend.rap_c500g_main sync`는 local manifest를 다시 스캔해.
- 디스크 부족이나 R2 장애 때 로컬 파일을 자동 삭제하지 마.
- 외장 볼륨이 없어서 시작이 거부되면 USB를 다시 마운트한 뒤 service를 재시작해. 내부 SSD
  경로로 임의 fallback하지 마.
- 중지는 아래처럼 service만 unload하고 녹화 root/R2/DB/`.env`는 보존해.

```bash
launchctl bootout gui/$(id -u)/com.teraai.rap-c500g-recorder
```
