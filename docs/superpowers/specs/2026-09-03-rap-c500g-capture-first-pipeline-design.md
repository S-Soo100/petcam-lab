# RAP C500G 녹화 우선·원본 즉시 R2 파이프라인 설계

> 야간에는 C500G 3대의 30분 원본 녹화와 R2 백업을 최우선으로 수행하고, 전체 디코딩 검증과 썸네일 생성은 08:00 이후 Mac mini가 독립 처리한다.

**상태:** Owner 설계 승인·구현 계획 대기

**작성:** 2026-09-03

**선행 설계:**

- [RAP C500G 장시간 원본 녹화·R2 이중 보관](2026-08-26-rap-c500g-r2-recording-design.md)
- [RAP C500G 로컬 녹화 매니저](2026-08-31-rap-c500g-local-manager-design.md)

**연관 연구:** 환경에 따른 파충류 행동량 분석

이 문서는 선행 설계 중 야간 `전체 decode → thumbnail → manifest → R2` 순서를 변경하는 addendum다.
그 실행 순서가 충돌할 때는 이 문서가 우선하며, 경로·보안·원본 보존·manifest-last·Owner-only 계약은
선행 설계를 그대로 따른다.

## 1. 결정 요약

Mac mini의 `com.teraai.rap-c500g-manager` 단일 launchd 서비스가 production 권한을 계속 소유한다.
서비스 내부 역할만 다음 세 단계로 분리한다.

1. **Capture worker:** 20:00~08:00 KST에 cam01~cam03을 30분 단위로 원본 녹화한다.
2. **Raw upload worker:** 각 원본이 닫히고 빠른 검사를 통과하는 즉시 같은 파일을 R2에 올린다.
3. **Daytime finalizer:** 08:00 이후 전체 디코딩, 썸네일, 최종 manifest와 DB 동기화를 수행한다.

MacBook, Codex/ChatGPT 세션, 브라우저는 실행 조건이 아니다. MacBook은 상태 조회와 보고만 담당한다.
Mac mini가 재부팅돼도 launchd와 SQLite durable queue가 미완료 작업을 이어간다.

이 설계에서 `원본`은 C500G가 전송한 HEVC bitstream을 `-c copy`로 MP4에 재포장한 파일이다.
픽셀 재인코딩은 하지 않으며, R2에 먼저 올라간 원본 video object는 주간 검증에서도 수정하거나
덮어쓰지 않는다.

## 2. 배경과 문제

기존 매니저는 30분 녹화가 끝나면 이전 영상을 전체 디코딩하고 썸네일을 만드는 동안 다음 구간을
녹화했다. 2026-09-02 야간에는 초기 FFmpeg 종료 여유가 실제 RTSP 지연보다 짧아 MP4가 닫히기 전에
종료되는 문제가 있었고, 여유를 90초로 늘린 뒤 00:30~07:30의 카메라별 15개 구간은 연속 성공했다.

직접 원인은 종료 여유였지만 녹화 중 전체 디코딩까지 병행할 이유는 없다. 연구의 우선순위는
원본 수집과 외부 백업이며, 무거운 검증은 원본이 두 곳에 보존된 뒤 수행해도 된다.

## 3. 목표

- 매일 20:00~08:00 KST의 24개 고정 30분 구간을 카메라별로 기록한다.
- 다음 00/30분 녹화 시작이 이전 구간의 디코딩·썸네일·DB 작업 때문에 지연되지 않게 한다.
- 닫힌 원본을 빠르게 검사하고 R2에 즉시 백업한다.
- 08:00 이후 전날 원본 전체를 검증하고 최종 bundle 계약을 완성한다.
- Mac mini가 MacBook과 대화 세션 없이 녹화·업로드·복구·후처리를 독립 수행한다.
- 손상되거나 검증에 실패한 원본도 로컬과 R2에서 삭제하지 않고 실패 상태로 보존한다.
- 기존 경로, manifest-last, 비밀값 제거, Owner-only 조회 계약을 유지한다.

## 4. 비목표

- 12시간을 하나의 영상 파일로 만들지 않는다.
- 영상 픽셀을 H.264/HEVC로 다시 인코딩하지 않는다.
- 야간에 전체 디코딩 검증이나 썸네일 생성을 수행하지 않는다.
- 검증 실패 파일을 자동 삭제·덮어쓰기·교체하지 않는다.
- MacBook heartbeat나 Codex 세션을 scheduler로 사용하지 않는다.
- 카메라 전원 제어, 신규 카메라 등록, ROI·YOLO·DLC·SPI 분석을 추가하지 않는다.
- 기존 `camera_clips`, `motion_clips`, GME, 행동 GT 파이프라인을 변경하지 않는다.
- Windows Service 이식은 이번 범위에 포함하지 않는다.

## 5. 사용자 체험

### 5.1 야간 자동 운영

```text
[화면] Owner가 Mac mini의 로컬 매니저에서 20:00~08:00 계획이 활성 상태임을 본다.
→ [조작] 브라우저와 MacBook을 끄고 현장을 떠난다.
→ [반응] 20:00에 세 카메라가 동시에 녹화를 시작하고 30분마다 새 원본으로 넘어간다.
→ [반응] 닫힌 원본은 빠른 검사 후 R2에 올라가며 다음 녹화는 기다리지 않는다.
→ [알림] 각 구간의 세 카메라 녹화·원본 업로드 결과가 Slack `mac-bot`에 한 번 기록된다.
→ [감정] 현장에 사람이 없어도 원본이 Mac mini와 R2 양쪽에 쌓인다는 확신을 얻는다.
```

### 5.2 오전 후처리

```text
[08:00] 새 녹화가 시작되지 않는다.
→ [반응] Mac mini가 전날 원본을 순서대로 전체 디코딩하고 썸네일·최종 manifest를 만든다.
→ [반응] R2 manifest-last와 DB 상태가 최종 완료로 전진한다.
→ [화면] 매니저에는 `원본 업로드 완료`와 `최종 검증 완료`가 별도 상태로 보인다.
→ [알림] 전날 expected/captured/raw-uploaded/verified 수와 실패가 Slack에 요약된다.
→ [감정] 원본 수집과 품질 검증을 구분해 문제 위치를 바로 이해한다.
```

### 5.3 검증 실패

```text
[반응] 한 원본이 전체 디코딩 검증에 실패한다.
→ [화면] 해당 항목은 `원본 보존·검증 실패`로 표시되고 다른 파일 처리는 계속된다.
→ [알림] camera, slot, 안전한 오류 코드와 Owner 조치 필요 여부가 Slack에 전송된다.
→ [감정] 원본이 사라지지 않은 상태에서 재검사나 수동 복구를 결정할 수 있다.
```

## 6. 전체 데이터 흐름

```text
20:00~08:00 capture window

cam01~cam03 RTSP
  → FFmpeg stream copy (`video.part.mp4`)
  → 정상 종료 + container close
  → quick gate: 존재/크기/ffprobe/길이·codec·hvc1·해상도
  → atomic promote (`video.mp4`)
  → SHA-256
  → R2 `video.mp4` upload + HEAD size/SHA 확인
  → SQLite `raw_uploaded`
  → 다음 30분 capture가 항상 우선

08:00 이후 finalize window

SQLite `raw_uploaded` queue
  → 전체 decode
  → thumbnail 생성
  → sanitized log 확정
  → local final manifest 생성
  → R2 thumbnail/log upload
  → 기존 R2 video HEAD 재검증
  → R2 manifest 마지막 upload
  → DB final upsert
  → SQLite `verified_uploaded`
```

R2에 먼저 올라간 `video.mp4`는 최종 검증 결과와 무관하게 immutable이다. 검증 실패 시 video를
삭제하지 않고 R2 metadata/별도 상태 원장과 DB에 실패를 기록한다. 완료를 뜻하는 최종
`manifest.json`은 전체 검증을 통과한 경우에만 마지막으로 업로드한다.

## 7. 단일 서비스와 내부 역할

launchd label은 기존 `com.teraai.rap-c500g-manager` 하나를 유지한다. 별도 production daemon을
추가하지 않는다. 한 서비스 안에서 executor와 durable queue만 분리한다.

### 7.1 Capture coordinator

- KST 20:00, 20:30, ..., 07:30 경계를 계산한다.
- 세 카메라별 FFmpeg child를 독립 실행한다.
- capture worker는 녹화와 MP4 close까지만 담당한다.
- 전체 디코딩, thumbnail, R2/DB 최종화는 호출하지 않는다.
- 동일 camera/slot 중복 claim을 SQLite로 차단한다.
- retry는 카메라별 최대 3회이며 현재 구간의 남은 시간 안에서만 실행한다.
- 08:00 이후 새 capture를 시작하지 않는다.

### 7.2 Raw upload worker

- quick gate를 통과해 원자 승격된 원본만 업로드한다.
- worker concurrency는 1로 제한해 capture의 디스크·네트워크 우선순위를 보호한다.
- 업로드 실패는 durable queue에 남겨 backoff 재시도하고 capture를 막지 않는다.
- 이미 같은 key에 같은 size/SHA가 있으면 성공으로 수렴한다.
- 같은 key에 다른 content가 있으면 덮어쓰지 않고 `integrity_conflict`로 멈춘다.
- 30분 경계에 capture 시작이 필요하면 capture가 upload보다 우선한다.

### 7.3 Daytime finalizer

- 기본 실행 창은 08:00~19:30 KST다.
- active capture가 하나라도 있으면 시작하지 않는다.
- 전날 night의 `raw_uploaded` 항목을 scheduled slot 순서로 처리한다.
- 전체 decode 기본 concurrency는 3으로 두고 첫 72개 야간 canary에서 처리시간·CPU·온도를 측정한다.
  19:30 drain을 넘기거나 시스템 압박이 확인되면 다음 release에서 낮추며, 야간 capture 중에는 항상 0이다.
- 19:30까지 backlog가 남으면 안전하게 중단하고 다음 08:00에 이어간다.
- 처리 중 재부팅되면 SQLite claim과 local/R2 상태를 대조해 같은 단계부터 멱등 재개한다.
- 원본 video bytes와 R2 key는 변경하지 않는다.

## 8. 파일·R2 계약

production 경로는 기존 계약을 유지한다.

```text
recordings/{camera}/night=YYYY-MM-DD/{segment_start_kst}/
  video.mp4
  thumbnail.jpg
  ffmpeg.sanitized.log
  manifest.json
```

야간 raw 단계에서는 `video.mp4`만 먼저 R2에 존재할 수 있다. 이 상태는 완료 bundle이 아니며
최종 `manifest.json`이 없으므로 기존 manifest-last 판정에서도 완료로 노출되지 않는다.

로컬에는 다음 임시·상태 파일이 있을 수 있다.

- `video.part.mp4`: capture 진행 중 또는 실패 증거
- `ffmpeg.sanitized.log.part`: capture 단계 안전 로그
- SQLite queue row: quick gate, raw upload, finalization 상태

`video.part.mp4`는 R2에 올리지 않는다. 빠른 검사와 atomic promote를 통과한 `video.mp4`만 원본으로
업로드한다.

## 9. 상태 모델

```text
scheduled
  → capturing
  → quick_verifying
  → captured
  → raw_uploading
  → raw_uploaded
  → full_verifying
  → finalizing
  → verified_uploaded
```

실패 상태는 단계별로 분리한다.

- `capture_failed`: 원본 파일을 정상 종료하지 못함
- `quick_verification_failed`: ffprobe/길이/codec 계약 실패
- `raw_upload_failed`: 로컬 원본은 정상이나 R2 video 백업 실패
- `full_verification_failed`: 로컬·R2 원본은 보존됐지만 전체 decode 실패
- `final_artifact_failed`: thumbnail/log/manifest 생성 또는 업로드 실패
- `db_sync_failed`: bundle은 보존됐지만 DB 최종 동기화 실패
- `integrity_conflict`: 같은 R2 key의 기존 객체가 다른 size/SHA를 가짐

상태는 성공 방향으로만 전진한다. 실패 후 재시도하더라도 이력과 attempt를 append-only로 남긴다.

## 10. 장애와 복구

- **카메라 단절:** 해당 카메라만 현재 slot 안에서 재시도하고 다른 두 카메라는 계속한다.
- **FFmpeg 지연:** 요청 duration과 별도의 종료 grace를 적용해 정상 MP4 close를 기다린다. grace는
  slot duration을 줄이는 값으로 사용하지 않는다.
- **R2/인터넷 장애:** 로컬 원본을 보존하고 raw upload queue에서 재시도한다.
- **전체 검증 실패:** 로컬/R2 원본을 그대로 두고 실패 상태와 안전 로그만 기록한다.
- **Mac mini 재부팅:** launchd가 manager를 재시작하고 SQLite와 local scan으로 capture/raw upload/
  finalize queue를 복원한다.
- **USB 분리·read-only·저용량:** 새 capture를 fail closed하며 내부 SSD로 우회하지 않는다.
- **08:00 경계:** 진행 중인 07:30 slot의 정상 종료와 quick gate/raw upload는 끝내되 새 08:00 slot은
  만들지 않는다. 완료 뒤 daytime finalizer로 전환한다.
- **19:30 경계:** finalizer를 새 작업 없이 drain하고 20:00 capture 준비 상태로 전환한다.

## 11. Slack과 상태 조회

Slack `mac-bot`에는 다음을 보낸다.

- 30분 slot별 세 카메라의 capture/quick gate/raw upload 요약 한 건
- 카메라 retry 소진, storage 차단, integrity conflict 같은 즉시 조치 장애
- 장애 recovery 전환
- daytime finalizer 시작, 주기적 backlog 요약, 전날 최종 결과

같은 incident의 반복 알림은 억제한다. 메시지에는 camera key, slot, 단계, 안전한 오류 코드,
duration/byte count만 넣고 secret·전체 RTSP URL·절대 local path는 넣지 않는다.

MacBook의 ChatGPT는 Mac mini의 read-only status 명령을 호출해 다음 상태만 요약한다.

- 현재/다음 capture slot과 카메라별 파일 증가
- raw upload 성공·대기·실패 수와 oldest age
- daytime full verification 진행률과 실패
- local/R2/DB gap과 USB 여유 공간

상태 조회가 끊겨도 Mac mini의 실행에는 영향이 없다.

## 12. UI 변경

매니저는 한 상태를 `완료`로 뭉치지 않고 카메라·slot마다 다음 세 단계를 표시한다.

1. `원본 녹화`
2. `R2 원본 백업`
3. `최종 검증`

상단에는 야간 capture 상태와 주간 finalizer 상태를 분리해 보여준다. 야간에는 `녹화 우선 모드`,
08:00 이후에는 `후처리 모드` 배지를 표시한다. raw upload가 끝났지만 full verification이 남은 항목은
노란색 대기 상태이며 실패로 표시하지 않는다.

## 13. 검증 계획

### 13.1 자동 테스트

- 20:00~08:00 동안 full decode/thumbnail 실행 0건
- 08:00 이후 active capture가 없을 때만 full verification 시작
- 19:30 drain과 다음 20:00 capture 우선권
- 동일 camera/slot capture·raw upload·finalize 중복 0건
- raw upload 중 다음 경계 capture가 지연되지 않음
- quick gate 실패 video는 R2 upload 0건
- raw-uploaded video의 local/R2 size·SHA 일치
- full verification 실패 시 local/R2 video 삭제·덮어쓰기 0건
- manifest-last는 final verification 성공 후에만 충족
- 서비스 재시작 뒤 각 queue 단계 멱등 복구
- R2/DB/Slack 실패가 capture를 차단하지 않음
- status/UI/Slack 비밀값 노출 0건

### 13.2 Mac mini 단계별 canary

1. production 비활성 시간에 세 카메라 60초 capture-first 진단을 실행한다.
2. 원본 세 개가 quick gate와 R2 HEAD size/SHA를 통과하는지 확인한다.
3. full verification을 의도적으로 보류해 raw upload 상태가 재시작 뒤 복원되는지 확인한다.
4. daytime finalizer를 실행해 thumbnail/log/manifest/DB까지 완성한다.
5. 한 카메라 RTSP 단절, R2 일시 실패, manager 재시작을 각각 한 번 검증한다.
6. 한 번의 30분 실제 slot에서 다음 경계 시작 지연과 process 수를 측정한다.
7. 검증 후에만 기존 운영 계획을 새 정책으로 전환한다.

### 13.3 첫 야간 성공 기준

- 카메라별 expected 24, capture 24, raw-uploaded 24 또는 명시된 실제 장애
- 정상 카메라의 00/30분 시작 지연 p95 5초 이하, 최대 15초 이하
- 야간 전체 decode와 thumbnail process 0건
- R2 video local size/SHA 일치 72/72
- 08:00 이후 finalizer가 19:30 이전에 전날 queue를 모두 처리하거나, 처리량 부족을 수치로 보고하고
  다음 녹화에 영향 없이 안전 중단
- 최종 성공 bundle의 local/R2 video·thumbnail·log·manifest와 DB가 모두 일치
- capture 실패와 verification 실패를 서로 다른 수치로 보고
- MacBook/Codex/브라우저 가용성에 의존한 실행 0건

## 14. 출시와 rollback

1. 기존 설계와 현재 runtime diff를 기준으로 구현 계획을 만든다.
2. capture/quick gate/raw upload/daytime finalize 상태를 TDD로 구현한다.
3. 기존 원본 경로와 R2 key/DB row의 하위 호환성을 검증한다.
4. synthetic·fake R2·실제 60초 canary를 통과한다.
5. tracked commit 기반 runtime handoff gate에서 `HANDOFF_OK`를 만든다.
6. 활성 capture와 pending upload가 없는 안전창에 Mac mini runtime을 교체한다.
7. capture-first 30분 canary 후 첫 12시간을 감시한다.

rollback은 이전 manager runtime commit과 launchd plist로 되돌리되 이미 생성된 local/R2 원본과 DB row를
삭제하지 않는다. cutover 전후 한 시점에 production 권한을 가진 manager는 정확히 하나여야 한다.

## 15. 완료 조건

- [ ] MacBook·Codex·브라우저가 꺼져도 Mac mini launchd가 녹화와 queue를 실행한다.
- [ ] 야간에는 30분 원본 capture, quick gate, raw R2 upload만 수행한다.
- [ ] 다음 00/30분 capture가 이전 full decode·thumbnail 때문에 지연되지 않는다.
- [ ] R2 video가 local 원본과 같은 size/SHA로 즉시 보존된다.
- [ ] 08:00 이후 full decode·thumbnail·manifest-last·DB sync가 자동 수행된다.
- [ ] full verification 실패 원본도 local/R2에서 삭제·덮어쓰기 없이 보존된다.
- [ ] 재부팅·R2 장애·카메라 단절 뒤 중복 없이 복구한다.
- [ ] Slack과 read-only status가 capture/raw upload/final verification을 구분한다.
- [ ] 첫 야간 72개 expected의 gap과 후처리 처리량을 실제 수치로 보고한다.
- [ ] 기존 RAP R2/DB와 다른 petcam/GME/GT 경계가 유지된다.
