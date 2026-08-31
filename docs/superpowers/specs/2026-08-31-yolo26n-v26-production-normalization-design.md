# YOLO26n v2.6 GME 운영 정상화·라벨링 웹 적용 설계

> 상태: Tasks 1~6 구현·검증·push 완료 / runtime handoff·smoke 전
> 결정일: 2026-08-31 KST
> reviewed source commit: `4ce6270def59298ce6a789b6165a1e4801f15b96`
> training source commit: `e4566db750f8e0f668d72aeadd6f8305a2361f90`
> Gate implementation commit: `ecddd4857c22005694197b7df4797b6053b920e2`
> Nightly implementation commit: `d1985c8af9d7191bef3b3bf1707696ce03ebdb38`
> petcam-lab implementation commit: `d266863c112691afcb3e40de8e1f653754c84888`

## 1. 목표와 우선순위

YOLO26n v2.5 때문에 최근 야간 영상에서 발생한 대규모 미탐·오탐과 그로 인한 GME·라벨링 웹의
실사용 장애를 v2.6으로 먼저 정상화한다. v2.7 연구는 아래 범위를 완료한 뒤 시작한다.

1. 신규 production 영상이 v2.6 GME 작업으로 자동 enqueue·처리된다.
2. 기존 저장 production 영상이 v2.6의 새 detector identity로 append-only 재분석된다.
3. 라벨링 웹의 기존 영상 상세는 v2.6 결과만 기본 overlay로 표시한다.
4. 공개 `/gecko-detector`의 production 503 fake gate를 실제 v2.6 worker로 교체한다.
5. v2.5 결과와 사람 GT는 삭제·덮어쓰기하지 않고 rollback 근거로 보존한다.

이번 작업에서 말하는 production 적용은 **GME 운영 detector와 라벨링 보조 화면의 직접 전환**이다.
독립 future holdout 없이 `yolo_active_model`의 formal 승격 조건을 우회하거나 Flutter의 고객 활동량
정본을 바꾸는 일은 아니다.

## 2. 선택지와 결정

### A. v2.5 checkpoint를 같은 경로에서 덮어쓰기

가장 빠르지만 기존 job과 새 결과가 같은 identity로 섞이고 rollback·감사가 불가능하다. 기각한다.

### B. v2.5와 v2.6을 며칠간 병렬 shadow로만 운영

위험은 낮지만 현재 v2.5의 실사용 장애를 계속 노출한다. 장기 병렬 shadow는 기각한다.

### C. 새 v2.6 identity + 짧은 smoke 뒤 직접 전환 — 채택

v2.6 checkpoint와 추론 계약으로 새 detector execution identity를 만들고, 10개 실제 production 영상
smoke 뒤 신규 enqueue·라벨링 기본 overlay를 v2.6으로 즉시 전환한다. 과거 영상은 신규 live보다 낮은
우선순위로 50개씩 재분석한다. 기존 v2.5 원장을 보존하므로 직접 전환과 rollback을 함께 만족한다.

## 3. 고정 v2.6 detector 계약

- model family/version: `YOLO26n / v2.6-warm-start-s28`
- checkpoint SHA-256: `a00e5a7a1e1f9197accb036339a38a7c821f03c8ab79611ebce89e5cde59b513`
- detector freeze SHA-256: `8f8e02beb452ec2ddfdce344dff507294f56136c69224990c50552d22bb343a0`
- old-regression report SHA-256: `3c99e7a2f6633c5c741ee3ed79bda1a52ab575a1cfa9318ca0bdb4583d9be8cb`
- raw confidence: `0.001`
- image size: `960`
- model NMS IoU: `0.70`
- maximum detections: `50`
- accepted box score threshold: `0.15`
- post-selection NMS IoU: `0.55`
- maximum analysis rate: `10fps`
- temporal presence candidate: 연속 5 frame 중 3 frame 이상 accepted detection
- detector execution identity: `89e4738a60ebb71900e05e96f5b7262e8b900f5c9bba9b9cb9e34fca36f789b7`

`detector_identity`는 checkpoint만 복사하지 않고 model/version/checkpoint/schema/threshold/NMS/10fps
시간축 규칙을 `sort_keys=True`, separators `(',', ':')`인 canonical JSON으로 묶은 SHA-256이다. Mac
mini worker, DB live trigger, backfill 도구, 라벨링 웹은 위 literal identity를 사용한다.

## 4. 시스템 경계와 데이터 흐름

```text
신규 production motion_clip
  -> v2.6 identity live job (priority 100)
  -> Mac mini com.petcam.gme-worker
  -> v2.6 detection + temporal decision + GME tracking/activity
  -> append-only gme_run + versioned R2 artifact
  -> 라벨링 웹의 v2.6 전용 overlay

기존 eligible production motion_clip
  -> v2.6 identity historical job (bounded batch 50)
  -> 같은 worker/run/artifact 경로

/gecko-detector upload
  -> Vercel same-origin validation + durable rate limit
  -> 인증된 v2.6 HTTP inference worker
  -> versioned frame bbox response
  -> 요청 종료 시 임시 media 삭제
```

`live`가 `historical`보다 항상 우선한다. live lag p95가 15분을 넘으면 historical claim만 멈추고
신규 영상 처리는 유지한다. 원본 media는 읽기 전용이며 derived GME artifact만 기존 allowlist prefix에
쓴다.

## 5. 라벨링 웹 계약

현재 서버는 clip의 가장 최근 성공 job을 model identity와 무관하게 선택한다. 이를 server-only
`GME_ACTIVE_DETECTOR_IDENTITY`에 정확히 일치하는 성공 run만 선택하도록 바꾼다.

- v2.6 run 존재: v2.6 box·활동 참고정보·오류 신고 버튼을 표시한다.
- v2.6 job 처리 중: `v2.6 분석 대기 중`을 표시하고 v2.5 box로 fallback하지 않는다.
- v2.6 job 실패: 사람 라벨링을 막지 않고 `v2.6 결과를 확인할 수 없음`을 표시한다.
- v2.5 run만 존재: v2.5를 현재 결과처럼 보여주지 않는다.
- browser 응답에는 detector identity, R2 key, run UUID를 노출하지 않는다.
- `YOLO가 게코를 놓쳤어`, 오탐, 틀린 bbox 피드백은 화면에 표시된 v2.6 run에만 연결한다.

공개 `/gecko-detector`는 현재 fake provider와 local limiter 때문에 production에서 항상 503이다.
실제 worker adapter는 `YOLO_WORKER_URL`과 secret token을 server-only로 사용하고 timeout·응답 schema·
model version을 검증한다. Vercel process 안에서 YOLO를 실행하지 않고 브라우저에도 worker 주소·token을
노출하지 않는다. Mac mini worker가 unavailable이면 503으로 fail closed한다.

## 6. 사용자 체험 흐름

`[화면]` 라벨링 영상에 `YOLO v2.6` 상태와 해당 영상의 박스·활동 참고정보가 보인다.

→ `[조작]` 사람이 영상을 재생하고 게코 존재·bbox를 직접 판단한다.

→ `[반응]` v2.6이 틀리면 미탐·오탐·틀린 박스 버튼으로 해당 시각을 기록한다. v2.6 결과가 아직
없거나 실패했어도 사람 라벨링은 계속할 수 있다.

→ `[감정]` 오래된 v2.5 박스에 방해받지 않고, 현재 모델이 무엇인지 알고 판단할 수 있다.

`[화면]` `/gecko-detector`에 사진 또는 짧은 영상을 올리면 `YOLO v2.6` 결과가 표시된다.

→ `[조작]` 사용자가 파일을 선택하고 분석한다.

→ `[반응]` same-origin API가 검증 후 실제 worker를 호출하고 bbox를 표시한다. worker 장애는 가짜
결과가 아니라 명확한 unavailable 오류로 끝난다.

## 7. 배포 순서

1. 세 repository, Mac mini hostname/service/working directory, model/freeze SHA를 읽기 전용 검증한다.
2. v2.6 adapter·worker·enqueue·web provider를 테스트하고 tracked commit으로 고정한다.
3. cross-repo runtime manifest를 만들고 `verify_agent_handoff.py`의 `HANDOFF_OK`를 확보한다.
4. Mac mini private model path에 checkpoint를 immutable copy하고 SHA를 재검증한다.
5. production-purpose 실제 영상 10개만 v2.6 identity로 smoke 처리한다.
6. 10/10, provenance 100%, temp residue 0, forbidden write 0을 독립 검수한다.
7. DB live trigger와 Mac mini LaunchAgent를 v2.6 identity로 전환한다.
8. 신규 live 1건의 enqueue→run→artifact→web overlay를 end-to-end 확인한다.
9. 라벨링 웹 Preview와 Owner canary를 통과한 뒤 production 배포한다.
10. 과거 영상 inventory를 dry-run하고 first batch 50건을 검수한 뒤 나머지 backfill을 계속한다.

한 번의 smoke로 모든 역사 backfill 완료를 기다리지 않는다. 신규 영상과 라벨링 웹 정상화가 먼저이고,
과거 재분석은 같은 identity로 계속되는 background 작업이다.

## 8. 성공 기준

- checkpoint/freeze/runtime identity 일치 100%
- smoke 10/10 succeeded, terminal failure 0
- 신규 eligible clip의 v2.6 enqueue coverage 100%
- live lag p95 `<=15분`
- 라벨링 웹이 v2.5 latest run을 현재 결과로 선택하는 경우 0
- `/gecko-detector` 실제 v2.6 response와 model version 검증 성공
- historical first batch 50/50 및 전체 retry/terminal 현황 집계 가능
- v2.5 job/run/artifact와 사람 GT 수정·삭제 0
- 원본 R2 write 0, 허용 GME artifact prefix 밖 write 0
- DB/R2/service secret과 개별 clip/source 식별자 노출 0

## 9. 실패와 rollback

- smoke 실패: live trigger·web default·public worker를 전환하지 않는다.
- live 장애: DB trigger와 LaunchAgent config를 마지막 검증된 v2.5 identity로 되돌린다.
- web 장애: v2.6 worker 호출을 끄고 unavailable 상태로 fail closed한다. fake 결과는 production에 내지 않는다.
- backfill 장애: historical claim만 중단하고 신규 live를 유지한다.
- 이미 생성된 v2.6 job/run/artifact는 provenance로 보존하고 삭제하지 않는다.

rollback은 사용자에게 노출되는 잘못된 v2.6 결과를 멈추기 위한 것이지, 실패 증거를 지우는 작업이
아니다.

## 10. 명시적 제외 범위

- v2.7 데이터 준비·학습·평가
- sealed future holdout을 통과한 것으로 기록하는 일
- `yolo_active_model` formal activation gate 우회
- Flutter/API 고객 활동량 정본 자동 교체
- 모델만으로 영상 제외·삭제·게코 부재·행동명·하이라이트 확정
- 사람 GT 자동 수정

v2.6 운영 정상화와 과거 backfill이 안정 상태에 들어간 뒤 v2.7을 별도 연구로 시작한다.
