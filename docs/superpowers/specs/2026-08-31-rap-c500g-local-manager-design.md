# RAP C500G 로컬 녹화 매니저 설계

> Mac mini가 브라우저와 MacBook의 가용성에 의존하지 않고 C500G 녹화·복구·R2 동기화를 운영하며, owner가 로컬 UI와 ChatGPT용 읽기 전용 상태로 이를 확인한다.

**상태:** Owner 설계 승인·구현 대기

**작성:** 2026-08-31

**선행 설계:** [2026-08-26 RAP C500G 장시간 원본 녹화·R2 이중 보관](2026-08-26-rap-c500g-r2-recording-design.md)

**연관 연구:** 환경에 따른 파충류 행동량 분석

## 1. 결정 요약

Mac mini에 하나의 Python modular monolith를 둔다. 이 프로세스는 로컬 FastAPI 관리 UI, SQLite
설정·상태 원장, 30분 scheduler, 카메라별 capture supervisor, 검증 queue, R2/DB sync queue,
watchdog와 Slack notifier를 함께 운영한다.

이 설계는 2026-08-26 설계의 원본 bundle, manifest-last, R2·DB 이중 보관, 비밀값 제거 계약을
대체하지 않고 운영 제어층을 추가한다. 로컬 저장소의 현재 운영 기준은 Mac mini 내부 SSD가 아니라
owner가 UI에서 선택한 실제 외장 볼륨이다. 외장 볼륨이 없으면 내부 SSD로 대체하지 않는다.

v1의 주 사용 방식은 다음과 같다.

1. owner가 현장 Mac mini에서 UI를 한 번 열어 스케줄, 등록 카메라, 외장 저장소를 설정한다.
2. Python background service가 브라우저와 무관하게 녹화·검증·업로드를 계속한다.
3. owner는 평소 MacBook에서 ChatGPT에게 상태를 물어보고, ChatGPT는 Mac mini의 안전한 JSON 상태를 읽어 요약한다.
4. 외부 공개 UI와 Cloudflare Access는 v1 범위에서 제외하고 phase 2로 미룬다.

## 2. 목표

- 등록된 C500G 중 선택한 카메라를 동일한 야간 스케줄로 녹화한다.
- production은 KST 00분·30분의 고정 wall-clock 경계를 보존한다.
- 한 카메라의 연결 실패가 다른 카메라나 다음 구간 시작 시각을 밀지 않게 한다.
- 실패한 카메라만 설정된 횟수만큼 자동 재시작하고 한도 초과 시 Slack으로 알린다.
- 선택한 외장 저장소의 mount·RW·여유 공간을 녹화 전과 운영 중 검증한다.
- 완료 bundle을 로컬에 유지하며 R2·DB 동기화 실패는 캡처와 분리해 재시도한다.
- Mac mini 재부팅 뒤에도 스케줄과 저장소 선택이 복원되고 background service가 다시 뜨게 한다.
- owner와 ChatGPT가 비밀값 없이 현재 상태와 최근 장애를 읽을 수 있게 한다.
- 운영 핵심을 OS 중립 모듈로 두어 이후 Windows Service로 교체할 수 있게 한다.

## 3. 비목표

- 카메라 Wi-Fi 가입, 신규 카메라 등록, IP·RTSP 계정 수정 UI는 만들지 않는다.
- UI에서 live video를 재생하거나 원본 MP4를 다운로드하지 않는다.
- 일반 운영용 `지금 녹화` 버튼을 만들지 않는다. 설치 검증용 60초 진단만 제공한다.
- 카메라 전원을 원격 제어하지 않는다. 카메라는 상시 켜져 있고 자동복구 대상은 FFmpeg capture process다.
- ROI crop, YOLO, DLC, SPI 또는 행동 분석을 실행하지 않는다.
- 로컬·R2 원본 자동 삭제와 retention을 도입하지 않는다.
- v1에서 인터넷에 관리 UI를 공개하거나 다중 사용자·권한 모델을 만들지 않는다.
- 기존 `camera_clips`, `motion_clips`, GME, Dataset v2, 행동 GT를 수정하지 않는다.

## 4. 사용자 체험

### 4.1 최초 설정

```text
[화면] Mac mini의 로컬 대시보드에 등록된 cam01~cam03와 외장 볼륨이 보인다.
→ [조작] owner가 20:00~08:00, 세 카메라, RAP-C500G 볼륨을 선택한다.
→ [반응] UI가 카메라 RTSP, 볼륨 mount/RW/여유 공간, R2·Slack 연결을 점검한다.
→ [조작] owner가 저장한다.
→ [반응] 설정은 다음 00/30 경계부터 적용된다고 표시되고 background service가 이를 이어받는다.
→ [감정] 브라우저를 닫아도 정해진 시간에 녹화된다는 확신을 얻는다.
```

### 4.2 정상 야간 운영

```text
[화면] 현재 20:00~20:30 구간, 세 카메라의 진행률·최근 프레임·파일 증가량이 보인다.
→ [반응] 20:30에 새 capture가 즉시 시작되고 이전 구간은 검증·R2 동기화 queue로 넘어간다.
→ [화면] 최근 완료 목록에 local/R2/DB 상태가 순차 갱신된다.
→ [감정] 검증이나 업로드가 느려도 다음 녹화가 밀리지 않는다고 이해한다.
```

### 4.3 카메라 장애

```text
[화면] cam02가 `재연결 중 1/3`으로 바뀌고 cam01·cam03은 계속 녹화한다.
→ [반응] 10초, 30초, 60초 간격으로 cam02 FFmpeg만 다시 시작한다.
→ [화면] 복구되면 해당 slot의 남은 시간만 partial로 기록하고 다음 정각에는 정상 시작한다.
→ [반응] 3회를 모두 실패하면 cam02만 `조치 필요`가 되고 Slack에 한 번 알린다.
→ [감정] 한 장비의 문제가 전체 야간 기록을 무너뜨리지 않는다고 느낀다.
```

### 4.4 저장소 장애

```text
[화면] 선택한 외장 볼륨이 없거나 RW가 아니면 저장소가 빨간색 `녹화 차단`으로 표시된다.
→ [반응] 어떤 카메라도 내부 SSD로 우회 녹화하지 않고 Slack에 조치 요청을 보낸다.
→ [감정] 파일이 엉뚱한 디스크를 채우지 않는다는 확신을 얻는다.
```

### 4.5 MacBook에서 상태 확인

```text
[조작] owner가 MacBook의 ChatGPT에게 “오늘 녹화 잘 되고 있어?”라고 묻는다.
→ [반응] ChatGPT가 Mac mini의 `rap-manager status --json`을 읽어 카메라·USB·R2·장애를 요약한다.
→ [감정] 현장 UI에 직접 들어가지 않고도 사실 기반 상태를 확인한다.
```

## 5. 전체 구조

```text
Mac mini launchd
  └─ RAP Manager process
      ├─ Manager API/UI (FastAPI, 127.0.0.1)
      ├─ SQLite config/status/event store
      ├─ Wall-clock scheduler
      ├─ Capture coordinator
      │   ├─ cam01 supervisor → FFmpeg
      │   ├─ cam02 supervisor → FFmpeg
      │   └─ cam03 supervisor → FFmpeg
      ├─ Media verification queue
      ├─ R2/DB durable sync queue
      ├─ Storage watchdog
      └─ Incident manager → Slack

Read-only consumers
  ├─ local dashboard (3~5초 polling)
  └─ rap-manager status --json → SSH/원격 실행 → MacBook ChatGPT
```

modular monolith를 택하는 이유는 단일 Mac mini·단일 owner 규모에서 배포와 복구 단위를 하나로 유지하면서도,
scheduler·capture·sync·UI 경계를 코드 수준에서 분리할 수 있기 때문이다. 별도 웹 서버·message broker·컨테이너
오케스트레이션은 v1에 필요하지 않다.

## 6. 컴포넌트 경계

### 6.1 Manager API/UI

- 대시보드, 설정, 60초 설치 진단, 읽기 전용 상태 API를 제공한다.
- 기본 bind는 `127.0.0.1`이다. 같은 Wi-Fi라는 이유만으로 LAN 전체에 공개하지 않는다.
- MacBook에서 UI가 필요하면 SSH local port forwarding으로 접근한다.
- 브라우저 종료는 scheduler와 capture에 영향을 주지 않는다.
- 입력은 allowlist와 범위 검증을 통과한 구조화 요청만 받는다.

### 6.2 SQLite store

- 하나의 active plan, 적용 대기 plan, 선택 카메라, 외장 볼륨 참조, retry policy를 보관한다.
- runtime snapshot, slot/camera attempt, incident, notification, sync queue 상태를 보관한다.
- WAL mode와 짧은 transaction을 사용하고 파일은 Mac mini의 application support 영역에 둔다.
- RTSP password, 전체 RTSP URL, R2/Supabase/Slack secret은 저장하지 않는다.
- UI 저장은 `pending` revision을 만들며 현재 capture가 끝난 뒤 다음 00/30 경계에서 atomic 적용한다.

### 6.3 Wall-clock scheduler

- active plan의 KST start/end와 고정 30분 경계로 slot을 계산한다.
- 자정을 넘는 20:00~08:00을 하나의 `night`로 묶는다.
- slot마다 선택 카메라 supervisor를 동시에 시작한다.
- 프로세스가 slot 중간에 복구되면 남은 시간만 `partial=true`로 녹화한다.
- 08:00 이후에는 새 production capture를 시작하지 않는다.

### 6.4 Camera supervisor

- 카메라마다 독립 상태와 FFmpeg child process를 하나씩 소유한다.
- 같은 카메라·slot의 FFmpeg가 이미 있으면 두 번째 process를 시작하지 않는다.
- 실패 시 기본 3회, 10초·30초·60초 간격으로 해당 카메라만 재시도한다.
- 재시도는 현재 slot 종료 시각을 넘지 않는다. 20:07에 복구하면 20:30까지 23분만 기록한다.
- 다음 slot에서 retry count를 0으로 초기화하고 실패했던 카메라도 다시 시도한다.
- 다른 카메라의 실패나 재시도 때문에 정상 카메라를 중지하지 않는다.

### 6.5 검증·동기화 worker

- capture 종료 직후 최소한의 파일 close·atomic 승격만 수행하고 다음 slot 시작을 막지 않는다.
- ffprobe, 전체 decode, thumbnail, manifest 완성은 bounded verification queue에서 수행한다.
- 검증된 bundle은 durable local scan을 정본으로 R2/DB sync queue에 들어간다.
- 인터넷·R2·DB 실패는 local capture를 막지 않고 backoff 재시도한다.
- R2는 video/thumbnail/sanitized log를 검증한 뒤 manifest를 마지막으로 업로드한다.
- queue backlog, 가장 오래된 항목 age, 마지막 성공/실패를 상태에 노출한다.

### 6.6 Storage watchdog

- UI에 `/Volumes` 아래의 실제 removable/external mounted volume만 목록으로 제공한다.
- 내부 SSD, system/data volume, network path, 임의 입력 경로는 제외한다.
- 저장 시 volume identity, 표시 이름, mount point를 기록하고 매 capture 전 실제 mount/RW/free bytes를 재검증한다.
- local root는 선택 볼륨 아래의 관리되는 상대 디렉터리로만 만든다.
- volume missing, read-only, 안전 하한 미만이면 전체 새 capture를 fail closed한다.

### 6.7 Incident manager와 Slack

- 카메라 retry 소진, 저장소 차단, manager 치명 오류, R2/DB 장기 backlog를 incident로 관리한다.
- 같은 incident가 open인 동안 Slack을 반복 발송하지 않는다.
- 최초 terminal/open과 이후 recovered/closed 전환만 보낸다.
- Slack 메시지에는 host, camera key 또는 storage label, slot, 안전한 오류 코드, 발생/복구 시각만 넣는다.
- secret, 전체 RTSP URL, 사용자 입력 원문, 로컬 절대경로는 넣지 않는다.

### 6.8 OS adapter

- core는 volume listing, service install/status, process signals를 interface로만 사용한다.
- macOS adapter는 Disk Arbitration/검증된 시스템 명령과 launchd를 사용한다.
- Windows adapter의 volume enumeration과 Windows Service 구현은 phase 2로 미룬다.
- scheduler, supervisor, incident, SQLite schema, API/CLI 계약은 OS에 의존하지 않는다.

## 7. 카메라·설정 계약

카메라 registry는 `.env`의 현재 `cam01`, `cam02`, `cam03` 설정을 로드한다. UI에는 다음 안전 필드만
보인다.

- `camera_key`
- 별칭
- IP 또는 hostname
- RTSP probe 상태와 마지막 probe 시각
- 선택 여부

username, password, 전체 RTSP URL은 API/UI/SQLite/log에 노출하지 않는다. v1은 registry에 없는 카메라를
추가하거나 수정하지 않는다.

active plan은 다음 값을 가진다.

- `start_local=20:00`, `end_local=08:00`
- `segment_minutes=30` 고정
- selected camera keys
- selected external volume reference
- `max_capture_retries=3`
- `retry_delays_sec=[10,30,60]`
- R2 sync enabled와 Slack alert enabled
- revision, saved_at, applied_at

retry 횟수는 UI에서 허용 범위 안에서 변경할 수 있지만 delay sequence는 v1에서 고정한다. 카메라 전부를
해제하거나 저장소가 유효하지 않은 plan은 활성화할 수 없다.

## 8. 상태 모델

### 8.1 Manager

`starting → idle → scheduled → recording → idle`이 정상 흐름이다. 저장소 차단은 `blocked_storage`,
manager 자체 치명 오류는 `degraded`로 표시한다. 개별 카메라 장애만으로 manager 전체를 degraded로 만들지 않는다.

### 8.2 Camera slot

```text
pending → connecting → recording → finalizing → captured
                    ↘ retry_wait → connecting
                    ↘ failed_terminal
```

slot 중간 재연결 또는 늦은 시작은 partial로 기록한다. 여러 시도에서 생성된 조각은 자동으로 이어붙이지 않고
각 시도 provenance를 보존한다. 최종 manifest에는 scheduled duration, captured duration, missing duration,
attempt count와 terminal status를 넣는다.

### 8.3 Sync

`pending_verification → verified → pending_upload → uploaded → db_synced`로 단조롭게 전진한다.
실패는 재시도 가능한 `verification_failed`, `upload_failed`, `db_sync_failed`로 기록하며 기존 완료 파일이나
R2 object를 자동 삭제·덮어쓰지 않는다.

## 9. UI

### 9.1 대시보드

- 상단 요약: 현재 slot, 다음 slot, active plan, 외장 저장소 상태·여유 공간, R2/DB backlog
- 카메라 카드: 별칭/IP, 16:9 thumbnail placeholder 또는 최신 thumbnail, RTSP 상태, 녹화/재시도 상태,
  현재 파일 크기와 증가 여부, 마지막 프레임 시각, retry count
- 최근 완료: camera/slot, duration·partial, local/R2/DB 상태
- 최근 알림: open/recovered incident와 시각
- 텍스트·카드는 충분한 padding/margin과 반응형 grid를 사용하며 좁은 폭에서 표를 강제하지 않는다.

### 9.2 설정

- 시작/종료 시각
- 30분 고정 segment 표시
- 등록 카메라 checkbox
- 검증된 외장 볼륨 radio list와 free space
- 자동 재시도 횟수
- R2·Slack 연결 상태
- `저장하고 다음 경계부터 적용` 버튼

현재 capture 중 설정을 저장해도 child process를 끊지 않는다. 새 revision은 다음 00/30 경계부터 적용한다.

### 9.3 설치 진단

일반 운영 화면과 구분된 설치 도구에서 선택 카메라를 정확히 60초 동안 동시 녹화한다. production 경로나
DB mode와 섞이지 않는 `test/` bundle을 만들고 video, thumbnail, sanitized log, manifest, R2, DB 결과를
표시한다. 활성 production capture가 있으면 진단을 시작하지 않는다.

## 10. 안전한 API·CLI

로컬 UI가 필요한 최소 API만 제공한다.

- `GET /api/status`
- `GET /api/settings`
- `PUT /api/settings/pending`
- `GET /api/volumes`
- `POST /api/probes/cameras`
- `POST /api/diagnostics/recording`
- `GET /api/incidents`

모든 mutation은 loopback에서만 받고 origin/host를 검증한다. destructive delete, 임의 shell, 임의 path,
임의 RTSP URL 입력 endpoint는 만들지 않는다.

`rap-manager status --json`은 API와 같은 read model을 로컬에서 읽어 다음을 출력한다.

- schema version, host, manager/service state, uptime
- active/pending plan revision과 현재·다음 slot
- camera별 RTSP, capture, retry, file growth, last frame
- selected volume mount/RW/free bytes
- 최근 완료 bundle과 verification/R2/DB 상태
- open incident와 owner action

JSON은 password, token, webhook, 전체 RTSP URL, R2 key credential, service-role, 절대 local path를 포함하지
않는다. 성공은 exit 0, manager unavailable은 exit 2, 안전 차단 또는 owner 조치 필요는 exit 3으로 고정한다.

## 11. 보안

- RTSP·R2·Supabase·Slack secret은 기존 `.env` 또는 OS protected environment에서만 읽는다.
- SQLite, API response, HTML, manifest, application/FFmpeg log에 secret을 쓰지 않는다.
- FastAPI는 v1에서 `127.0.0.1`에만 bind한다.
- MacBook UI 접근은 SSH local port forwarding을 쓰고, 상태 조회는 제한된 원격 명령으로 제공한다.
- 상태 명령은 mutation을 지원하지 않는다.
- 외장 볼륨과 camera key는 allowlist로만 선택한다.
- 로그·Slack 메시지는 기존 sanitizer와 구조화 오류 코드를 사용한다.
- phase 2 외부 UI를 열 때 Cloudflare Tunnel과 Access single-email allowlist를 별도 설계·검증한다.
- 인터넷·Cloudflare·Slack 장애는 local recorder 동작에 영향을 주지 않는다.

## 12. 자동 테스트

- KST 00/30 경계, 자정 횡단, 08:00 종료, 중간 재시작 partial 계산
- 한 active plan과 pending revision의 다음 경계 atomic 적용
- 세 카메라 동시 시작과 카메라별 독립 retry
- retry 3회 10/30/60초, 현재 slot 제한, 다음 slot count reset
- 같은 camera/slot 중복 FFmpeg 금지
- 한 카메라 실패가 다른 카메라와 다음 slot을 지연하지 않음
- verification/full decode/thumbnail과 R2/DB sync가 다음 capture를 block하지 않음
- 실제 외장 볼륨 allowlist와 내부/system/network/path 입력 거부
- volume missing/read-only/low-space fail-closed, 내부 SSD fallback 0건
- Slack terminal/recovered 1회와 같은 incident 중복 억제
- manager restart 뒤 active plan, incident, sync backlog 복구
- diagnostic과 production identity/path/DB mode 분리
- status JSON exit code와 secret/URL/path redaction
- API loopback/mutation validation과 임의 path/RTSP 입력 부재
- OS-neutral interface와 macOS volume/service adapter contract test

## 13. 현장 acceptance 12개

1. Mac mini에서 local UI가 열리고 background service 상태를 표시한다.
2. 외장 저장소 목록에서 실제 `RAP-C500G`를 선택하고 mount/RW/free 검증을 통과한다.
3. 등록된 cam01~cam03의 TCP 554와 RTSP probe가 모두 성공한다.
4. 20:00~08:00, 고정 30분, 세 카메라 plan을 저장하고 다음 경계 적용을 확인한다.
5. production이 비활성인 시간에 60초 진단을 1회 실행해 카메라별 video·thumbnail·log·manifest 12개를 만든다.
6. MacBook의 ChatGPT가 `rap-manager status --json`을 읽어 세 카메라·USB·R2 상태를 비밀값 없이 요약한다.
7. 한 카메라 연결을 일시 중단해 해당 카메라만 3회 재시도하고 다른 두 카메라가 계속됨을 확인한다.
8. 카메라를 복구해 recovery Slack이 정확히 1회 오고 다음 slot retry count가 초기화됨을 확인한다.
9. 녹화 중이 아닐 때 선택 USB를 제거해 새 capture가 안전 차단되고 내부 SSD fallback이 없음을 확인한다.
10. 60초 진단의 R2 object 12개, manifest-last, DB captured/uploaded 3행, size/SHA를 확인한다.
11. manager process를 한 번 종료해 launchd가 같은 service를 재시작하고 중복 child가 생기지 않음을 확인한다.
12. Mac mini를 재부팅해 active plan, 저장소 참조, service, 상태 JSON이 복원됨을 확인한다.

## 14. 구현·전환 순서

1. core model, SQLite store, scheduler, supervisor를 TDD로 구현한다.
2. 기존 capture/naming/manifest/R2/repository 계약을 adapter 뒤에서 재사용한다.
3. verification·sync queue와 incident/Slack을 구현한다.
4. 안전한 status read model, CLI, local API를 구현한다.
5. 승인된 dashboard/settings UI를 연결한다.
6. macOS volume/service adapter와 launchd plist를 구현한다.
7. 전체 자동 테스트와 로컬 fake/synthetic 통합 테스트를 통과한다.
8. tracked commit의 design·plan·runtime manifest로 handoff gate `HANDOFF_OK`를 만든다.
9. 현장 Mac mini에서 read-only preflight 후 60초 진단을 수행한다.
10. 기존 `com.teraai.rap-c500g-recorder`를 그대로 둔 상태에서는 새 manager production을 시작하지 않는다.
11. 진단이 모두 성공하면 기존 recorder를 중지하고 새 manager 하나만 launchd에 올린다.
12. 12개 현장 acceptance를 수행한다. 실패 시 새 manager를 중지하고 기존 recorder service로 rollback한다.

cutover의 핵심 불변식은 `한 시점에 production 권한을 가진 recorder service는 정확히 하나`다. 기존 영상,
R2 object, DB row는 수정하거나 삭제하지 않는다.

## 15. 내일 현장 준비와 세션 인계

물리 조건은 다음이면 충분하다.

- Mac mini 전원과 LAN을 카메라가 붙은 `terraai` 공유기에 연결하고 `192.168.50.x` 주소·gateway를 확인
- cam01~cam03 전원 유지
- `RAP-C500G` 외장 저장소 연결
- R2·DB·Slack을 위한 인터넷 연결
- MacBook을 잠시 같은 공유기의 Wi-Fi에 연결해 동일 subnet의 SSH/현장 확인 경로 확보

같은 Wi-Fi는 MacBook에서 Mac mini에 접근하기 위한 조건이지, loopback UI를 자동 공개하는 설정은 아니다.
Mac mini는 유선 LAN이 정상이라면 Wi-Fi를 동시에 유지할 필요가 없다. UI는 Mac mini 화면에서 직접 열거나
SSH port forwarding을 사용한다.

새 세션은 먼저 이 설계와 구현 계획의 tracked commit, runtime host, 현재 launchd label과 active FFmpeg를
read-only로 확인한다. 그 다음 진단·cutover·acceptance 순서로 진행하며 기존 recorder와 manager를 동시에
production 실행하지 않는다.

## 16. Phase 2

- Cloudflare Tunnel + Access single-email allowlist로 외부 대시보드 접근
- read-only 원격 thumbnail/history와 필요 시 presigned 재생
- Windows Service adapter와 Windows volume enumeration
- 등록 카메라 관리 UI

각 항목은 v1 운영 데이터가 쌓인 뒤 별도 decision gate와 설계를 거친다.

## 17. 완료 조건

- [ ] 브라우저·MacBook이 꺼져도 Mac mini가 스케줄대로 30분 slot을 실행한다.
- [ ] 세 카메라가 같은 경계에서 시작하고 개별 실패가 다른 카메라·다음 slot을 미루지 않는다.
- [ ] 카메라별 제한 재시도, terminal/recovery Slack, 다음 slot reset이 검증된다.
- [ ] 선택 외장 볼륨이 없거나 안전하지 않으면 내부 SSD fallback 없이 전체 새 capture가 차단된다.
- [ ] 검증·R2·DB queue가 다음 capture를 block하지 않고 재시작 뒤 복구된다.
- [ ] local UI와 status JSON이 같은 상태 정본을 보여주며 비밀값 노출이 0건이다.
- [ ] launchd 강제 종료·재부팅 뒤에도 단일 service와 active plan이 복원된다.
- [ ] 현장 acceptance 12개가 증거와 함께 통과한다.
- [ ] 기존 RAP bundle/R2/DB 계약과 기존 clip/GME/GT pipeline write가 유지된다.
