# RAP C500G 장시간 원본 녹화·R2 이중 보관 설계

> C500G 3대의 야간 원본을 30분 단위로 끊어 Mac mini와 Cloudflare R2에 함께 보존하고, Owner 전용 웹에서 상태와 영상을 확인한다.

**상태:** Owner 승인·구현 진행
**작성:** 2026-08-26
**연관 연구:** 환경에 따른 파충류 행동량 분석

## 1. 목표

- `cam01`, `cam02`, `cam03`의 RTSP 원본 스트림을 매일 20:00부터 익일 08:00 KST까지 녹화한다.
- production 파일은 30분 경계에 맞춰 분할한다. test는 같은 파이프라인으로 약 60초 녹화한다.
- 완성된 bundle을 Mac mini 내부 SSD와 기존 Cloudflare R2 버킷 양쪽에 보존한다.
- Owner가 내부 웹에서 카메라·관찰일·상태별로 조회하고 영상을 재생할 수 있게 한다.
- 캡처·업로드 실패와 누락 구간을 재시작 후에도 판별하고 재시도할 수 있게 한다.

## 2. 비목표와 경계

- 기존 `camera_clips`, `motion_clips`, GME, 라벨링 queue, 행동 GT를 생성하거나 수정하지 않는다.
- ROI crop, YOLO/DLC, SPI 산출은 이 단계에서 하지 않는다.
- 로컬 파일이나 R2 object의 자동 삭제·retention은 v1에 넣지 않는다.
- RAP 아카데미용 계정이나 공개 링크를 만들지 않는다.
- RTSP 자격증명, 전체 RTSP URL, R2 secret, service-role key를 DB·로그·manifest·웹 응답에 넣지 않는다.
- 브라우저가 R2 목록을 직접 읽거나 service-role/R2 credential을 받지 않는다.

## 3. 사용자 체험

```text
[현장] Mac mini가 켜지고 서비스가 로드된다.
→ [20:00] 세 카메라 녹화가 같은 30분 경계에서 시작된다.
→ [20:30] 각 카메라의 mp4가 검증되고 썸네일·안전 로그·manifest가 생긴다.
→ [백그라운드] 다음 구간 녹화는 즉시 계속되고, 이전 bundle은 R2에 업로드된다.
→ [웹] Owner가 관찰일을 고르면 72개 예상 구간의 완료·업로드·누락 상태가 보인다.
→ [조작] 한 구간을 누르면 짧게 만료되는 URL로 영상을 재생하고 썸네일·검증값을 확인한다.
→ [감정] 원본이 현장과 클라우드 양쪽에 있으며 어느 구간이 비었는지 즉시 알 수 있다.
```

## 4. 전체 흐름

```text
RTSP 3대
  → FFmpeg 동시 capture (`video.part.mp4`)
  → ffprobe/전체 decode 검증
  → atomic rename (`video.mp4`)
  → thumbnail.jpg + ffmpeg.sanitized.log + manifest.json
  → 로컬 bundle 유지
  → bounded upload queue
  → R2 video/thumb/log multipart 또는 단일 upload
  → R2 HEAD size + sha256 metadata 검증
  → manifest.json 마지막 upload
  → 별도 DB row upsert
  → Owner API → presigned GET → 내부 웹
```

캡처와 업로드를 직렬로 묶지 않는다. 네트워크 업로드가 늦어도 다음 30분 녹화가 시작되어야 한다.
업로드 worker concurrency 기본값은 1이고 설정으로 2까지 허용한다.

## 5. 카메라와 환경변수

논리 카메라명은 `cam01`, `cam02`, `cam03`으로 고정한다. 기본 IP는 각각
`192.168.50.23`, `.24`, `.25`, RTSP path는 ipTIME C500G의 `/onvif1`이다.
IP와 자격증명은 `.env`에서만 읽고 CLI 인자로 받지 않는다.

- cam01: `RAP_CAM_C500G_IP`, `RAP_CAM_C500G_RTSP_USER`, `RAP_CAM_C500G_RTSP_PASSWORD`
- cam02: `RAP_CAM_C500G_02_IP`, `RAP_CAM_C500G_02_RTSP_USER`, `RAP_CAM_C500G_02_RTSP_PASSWORD`
- cam03: `RAP_CAM_C500G_03_IP`, `RAP_CAM_C500G_03_RTSP_USER`, `RAP_CAM_C500G_03_RTSP_PASSWORD`
- 공통: `RAP_C500G_LOCAL_ROOT`
- R2 전용: `R2_C500G_ACCESS_KEY_ID`, `R2_C500G_SECRET_ACCESS_KEY`, `R2_C500G_BUCKET=c500g`
- R2 계정 endpoint: 기존 `R2_ENDPOINT` 공유

기본 local root는 `/Users/baek-end/RAP-c500g-recordings`, 고정 timezone은 `Asia/Seoul`이다.
환경변수 누락은 시작 전에 camera key만 포함한 오류로 fail closed하며 값은 출력하지 않는다.

## 6. 시간·관찰일 계약

- production slot: `20:00, 20:30, …, 07:30`, 각 30분
- `night=YYYY-MM-DD`: 20:00 녹화를 시작한 KST 날짜
- 익일 00:00~08:00 구간도 전날 `night` 아래에 둔다.
- 정상 기대치는 카메라당 24개, 세 카메라 합계 72개다.
- 프로세스가 slot 중간에 재시작되면 다음 경계까지 남은 시간만 `partial=true`로 녹화한다.
- 08:00 이후에는 새 production capture를 시작하지 않는다.
- 모든 저장 시각은 UTC ISO-8601과 KST key 문자열을 함께 기록한다.

## 7. 로컬·R2 경로

Cloudflare R2의 별도 `c500g` 버킷을 사용한다. object key에 `r2/`나 `c500g/`를 반복하지 않고,
local root 아래 상대경로와 R2 key prefix를 동일하게 유지한다. 기존 `petcam-clips` 버킷과 그
자격증명은 변경하지 않는다.

### Test

```text
test/{test_run_id}/{camera}/{segment_start_kst}/
  video.mp4
  thumbnail.jpg
  ffmpeg.sanitized.log
  manifest.json
```

### Production

```text
recordings/{camera}/night=YYYY-MM-DD/{segment_start_kst}/
  video.mp4
  thumbnail.jpg
  ffmpeg.sanitized.log
  manifest.json
```

`test_run_id`는 `test-YYYYMMDDTHHMMSS-KST-<8hex>`이고 `segment_start_kst`는
`YYYYMMDDTHHMMSS+0900`이다. camera와 mode는 allowlist로만 받아 `..`, slash, 제어문자를 거부한다.
같은 논리 segment는 항상 같은 key를 사용해 재시도가 중복 object를 만들지 않는다.

## 8. 캡처·로컬 원자성

1. bundle directory를 만든다.
2. FFmpeg는 TCP RTSP를 `-c copy -tag:v hvc1 -movflags +faststart`로
   `video.part.mp4`에 기록한다. 재인코딩 없이 C500G HEVC 스트림을 macOS QuickTime 호환 MP4로 포장한다.
3. stderr는 line 단위 sanitizer를 거쳐 `ffmpeg.sanitized.log.part`에만 쓴다.
4. FFmpeg 종료코드, 파일 크기, ffprobe duration/codec/codec tag/resolution/fps, 전체 decode를 검증한다.
   HEVC의 `codec_tag_string`이 `hvc1`이 아니면 원자 rename·R2 업로드 전에 실패시킨다.
5. 성공한 mp4만 `video.mp4`로 atomic rename한다.
6. 첫 5~10초 사이 최초 decodable frame으로 `thumbnail.jpg`를 만든다.
7. 안전 로그를 `ffmpeg.sanitized.log`로 rename한다.
8. SHA-256과 metadata를 담은 `manifest.json`을 no-partial 방식으로 원자 기록한다.

실패 bundle도 `.part`와 안전 로그를 보존하되 완료 manifest를 만들지 않는다. 서비스 재시작 시 완성
manifest가 없는 stale bundle을 `capture_failed`로 기록하고 자동 overwrite하지 않는다.

## 9. 로그 보안

sanitizer는 최소한 다음을 치환한다.

- `rtsp://user:password@host/...` → `rtsp://***:***@host/...`
- 알려진 username/password literal → `***`
- `R2_SECRET_ACCESS_KEY`, `SUPABASE_SERVICE_ROLE_KEY` literal → `***`
- URL query의 `token`, `key`, `signature`, `credential` 값 → `***`

애플리케이션 로그에는 camera key, slot, 상태, byte count, 오류 분류만 남긴다. 예외 문자열도 sanitizer를
거친 뒤 기록한다. `ps`에 RTSP 입력이 잠시 보일 수 있는 FFmpeg 한계는 로컬 same-user 운영 위험으로
문서화하고, 원격 shell/다중 사용자 접근을 허용하지 않는다.

## 10. Manifest 계약

manifest schema version은 `rap-c500g-bundle/v1`이다. 필수 필드는 다음과 같다.

- identity: `bundle_id`, `mode`, `camera_key`, `test_run_id`, `night_date`
- schedule: `scheduled_start_utc`, `actual_start_utc`, `ended_at_utc`, `partial`
- media: `duration_sec`, `codec`, `codec_tag`, `width`, `height`, `fps`, `video_size_bytes`, `video_sha256`
- artifacts: 파일별 상대명, size, SHA-256, content type
- capture: FFmpeg 종료코드, 검증 상태, sanitized warning/error count
- R2: 각 object key, 업로드/HEAD 검증 상태

manifest는 비밀값, 절대 local path, RTSP URL을 허용하지 않는다. R2에 올리는 manifest는 video,
thumbnail, log가 HEAD 검증된 후 최종 상태로 다시 만들어 **항상 마지막에 업로드**한다.

## 11. R2 업로드·무결성

- boto3 high-level `upload_file`과 `TransferConfig`를 별도 모듈에서 사용한다.
- multipart threshold/chunk는 기본 16 MiB, concurrency는 recorder upload worker 수와 별개로 2다.
- object metadata에 `sha256`, `bundle-id`, `camera-key`를 저장한다.
- 업로드 뒤 `head_object`의 `ContentLength`와 metadata `sha256`을 로컬 값과 비교한다.
- video/thumb/log 중 하나라도 실패하면 manifest를 올리지 않고 같은 key로 지수 backoff 재시도한다.
- 기존 object가 같은 size/hash면 업로드를 생략한다. 다르면 fail closed하며 자동 덮어쓰지 않는다.
- upload queue는 local manifest를 스캔해 재구성 가능해야 하며 메모리 queue만 신뢰하지 않는다.

## 12. 별도 DB 원장

신규 `public.rap_c500g_recordings`만 사용한다. 주요 컬럼은 다음과 같다.

- UUID `id`, text `bundle_id` unique
- `mode` (`test|production`), `camera_key`, nullable `test_run_id`, nullable `night_date`
- scheduled/actual/ended timestamp, `partial`
- duration/codec/width/height/fps/size/sha256
- video/thumbnail/log/manifest R2 key
- `capture_status`, `upload_status`, `upload_attempts`, `last_error_code`
- relative local bundle path, `created_at`, `updated_at`, `uploaded_at`

RLS를 활성화하고 anon/authenticated policy는 만들지 않는다. service role만 recorder와 Owner API 서버에서
읽고 쓴다. `(mode, camera_key, scheduled_start_utc, coalesce(test_run_id,''))` 의미 중복을 방지하고
`bundle_id` upsert는 상태를 단조롭게 전진시킨다. DB 실패가 이미 검증된 R2 bundle을 무효화하지 않으며
재동기화 worker가 manifest를 기준으로 row를 복구한다.

상태는 `capturing → captured → uploading → uploaded`이며 실패는 `capture_failed` 또는
`upload_failed`다. `uploaded`는 네 object가 존재하고 manifest-last가 성공한 경우에만 허용한다.

## 13. Owner 웹

- page: `/research/rap/recordings`
- API: `/api/research/rap/recordings`, `/api/research/rap/recordings/[id]`
- 모든 route 첫 단계에서 `requireOwner`를 호출한다.
- query는 `mode`, `camera`, `night`, `status`, cursor, limit만 strict allowlist로 받는다.
- 목록 응답은 R2 key, SHA, local path를 숨기고 안전한 표시 필드만 반환한다.
- detail 응답에서 video/thumbnail URL은 서버가 1시간 이하 presigned GET으로 생성한다.
- UI는 관찰일별 기대 72구간 대비 완료·업로드·누락 수, camera별 필터, 썸네일, 재생, 오류 코드를 보여준다.
- 원본 object 삭제·DB 수정 버튼은 v1에 없다.

## 14. 실패·복구

- 카메라 연결 실패: 다른 카메라 capture는 계속하며 해당 slot만 `capture_failed`로 기록한다.
- FFmpeg hang: slot 경계+grace 후 TERM, 이어 KILL하고 partial을 보존한다.
- R2/인터넷 실패: local bundle 보존, upload retry; 다음 capture를 막지 않는다.
- DB 실패: manifest/R2를 정본으로 pending sync한다.
- 프로세스 재시작: local manifest scan → HEAD 검증 → 미완료 upload/DB sync 재개.
- 디스크 여유가 안전 하한보다 작음: 새 capture를 fail closed하고 기존 파일을 삭제하지 않는다.
- 동일 key hash 충돌: `integrity_conflict`, 자동 overwrite 금지, Owner 확인.

## 15. 관측 지표

- night별 expected/captured/uploaded/failed/gap bundle 수
- camera별 capture 성공률과 실제 duration
- upload backlog 수·최고 age·retry 수
- local free bytes와 예상 다음 slot 필요량
- manifest-last/HEAD/hash 검증 실패 수
- 로그 secret scanner hit 0건

## 16. 단계별 출시

1. 순수 naming/schedule/manifest와 sanitizer 단위 테스트
2. fake FFmpeg·moto R2로 capture/upload/recovery 통합 테스트
3. migration static/runtime probe와 Owner API/UI 테스트
4. 로컬 synthetic 3-camera 60초 dry run
5. 실제 R2 `c500g` 버킷의 새 `test/<run>` prefix에만 3 bundle canary
6. DB row·Owner 웹 재생 검증
7. tracked commit과 handoff manifest 검증
8. Mac mini launchd 설치 후 한 slot canary
9. 첫 12시간 night의 72 expected/gap/size 보고

## 17. 완료 조건

- [ ] 세 카메라 test 60초 bundle이 로컬과 R2에 각각 4개 artifact로 존재한다.
- [ ] production scheduler가 KST 30분 경계와 관찰일을 정확히 계산한다.
- [ ] 350 MiB 이상 파일이 multipart로 업로드되고 HEAD size/hash가 일치한다.
- [ ] manifest가 항상 마지막에 업로드되며 부분 bundle은 웹 완료 목록에 나타나지 않는다.
- [ ] 네트워크·DB 중단 후 재시작하면 중복 없이 재개한다.
- [ ] 원본 RTSP URL·credential·secret이 로그/manifest/DB/API 응답에서 0건이다.
- [ ] Owner 아닌 요청은 401/403이고 Owner만 목록·재생 URL을 받는다.
- [ ] 기존 clip/GME/GT table과 R2 prefix write가 0건이다.
- [ ] local 자동 삭제가 없고 디스크 부족은 fail closed한다.
- [ ] Mac mini 운영은 handoff manifest `HANDOFF_OK` 뒤에만 설치된다.
