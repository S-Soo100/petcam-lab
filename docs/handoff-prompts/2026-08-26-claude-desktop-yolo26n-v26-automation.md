# Claude Desktop 자동화 지시문 — YOLO26n v2.6 사람 GT 검수 감독

> 상태: **역사 보존 / 사람 GT 단계 완료**. 2026-08-27 현재 실제 dataset build와
> training 실행 계약으로 사용하지 않는다. export 파일이 존재한다는 사실만으로
> `V26_HUMAN_GT_VALIDATED` 또는 학습 준비 완료로 해석하지 않는다.

> 이 문서는 Claude Desktop의 예약 자동화에 그대로 붙여 넣기 위한 지시문이야.
> 구현 handoff가 아니라 현재 연구의 **읽기 전용 감독과 사람 GT 도착 후 기계 검증**만 맡긴다.

## 권장 자동화 설정

- 이름: `YOLO26n v2.6 사람 GT 검수 감독`
- 실행 장비: `BaekBook-Pro-14-M5.local`
- 권장 주기: 2시간마다
- 종료 조건: `V26_HUMAN_GT_VALIDATED` 또는 명확한 fail-closed 보고 후 사용자가 종료할 때
- 변경이 없고 사람 입력도 필요 없으면 알림하지 않는다.

## Claude Desktop에 붙여 넣을 프롬프트

```text
MacBook `BaekBook-Pro-14-M5.local`에서 진행 중인 YOLO26n v2.6 최근 연속영상 재학습 연구를 감독해.

이번 자동화의 역할은 다음 두 가지뿐이야.

1. 이미 생성된 blind bbox 검수 묶음과 10fps GME 연구 계약이 변하지 않았는지 읽기 전용으로 확인한다.
2. 사람이 만든 CVAT bbox export가 지정 inbox에 도착하면 파일 수·라벨 형식·bbox·negative 비율·이중검수 일치도를 기계적으로 검증하고 결과만 보고한다.

Claude가 원문 이미지를 열거나 영상 내용을 판독하거나 bbox/GT를 만들면 안 돼. 이미지 bytes는 SHA 계산과 archive member 검증에만 사용해. Claude 판단을 사람 GT로 쓰지 마.

## 고정 실행 범위

- repository: `/Users/baek/.codex/worktrees/yolo-v26-recent-dense/petcam-lab`
- branch: `codex/yolo-v26-recent-dense-retrain`
- 기준 base commit: `13a2debfe4d33728b232101b77a8e06928c34658`
- private attempt: `/Users/baek/private-rba/yolo26n-v26-recent-dense/attempt-20260826-owner-v1`
- design: `/Users/baek/.codex/worktrees/yolo-v26-recent-dense/petcam-lab/docs/superpowers/specs/2026-08-26-yolo26n-v26-recent-dense-retraining-design.md`
- plan: `/Users/baek/.codex/worktrees/yolo-v26-recent-dense/petcam-lab/docs/superpowers/plans/2026-08-26-yolo26n-v26-recent-dense-retraining.md`
- TEST-SHEET: `/Users/baek/.codex/worktrees/yolo-v26-recent-dense/petcam-lab/experiments/yolo26n-v26-recent-dense/TEST-SHEET.md`

이 worktree의 untracked 연구 파일은 사용자 소유야. stage, commit, push, merge, reset, 삭제, 이동, 포맷 변경을 하지 마.

## 현재 고정 상태

- source window production record: 566 clips
- 삭제 정책 tombstone: 137 clips
- 접근·decode 가능한 source: 429 clips
- 2fps raw ledger: 52,356 frames
- blind primary: 2,508 images
- blind double-review: 200 images
- 사람 판정 작업 총합: 2,708
- 과거 protected fingerprint distance `<=2` overlap: 0
- primary exact image duplicate: 0
- decode reserve replacement: 1 image, 같은 source clip 안에서만 교체됨

고정 artifact:

- primary ZIP: `/Users/baek/private-rba/yolo26n-v26-recent-dense/attempt-20260826-owner-v1/blind-queue/blind-primary.zip`
- primary ZIP SHA-256: `7ae6ca56385e940f2312b5b27e8bb3d73b1844e1e5fd7a9492789fead70abd8f`
- double-review ZIP: `/Users/baek/private-rba/yolo26n-v26-recent-dense/attempt-20260826-owner-v1/blind-queue/blind-double-review.zip`
- double-review ZIP SHA-256: `23b2d20432bf17693a6b88d09100d9bd8095238203713ce0b5ffa1f75e4af862`
- private review index: `/Users/baek/private-rba/yolo26n-v26-recent-dense/attempt-20260826-owner-v1/blind-queue/review-index.private.json`
- private review index SHA-256: `dedb48b54cd30221f654f5e22f8d73b730785c6e5bc080038d5b2819856f0dc8`
- selection SHA-256: `e28872a26facb29b304700d13497b0d73e4e29eaec83be197024e33ac47ea7cf`

비밀값, clip/source ID, private_ref, R2 key, 원문 GT row는 출력하지 마. 집계 숫자와 상태만 보고해.

## GME 10fps 연구 계약

- detector analysis rate는 최대 10fps다.
- 원본이 10fps 미만이면 frame을 복제하지 않는다.
- 기본 존재 후보 규칙은 연속 5 frame 중 3 frame 이상 검출이다.
- 1~2 frame짜리 단발 검출은 `present`가 아니라 `unknown/review`다.
- detector threshold, NMS, temporal gap과 3-of-5 규칙은 새 development validation에서 함께 동결한다.
- 이 자동화는 운영 GME 코드·서비스·checkpoint에 이 계약을 배포하지 않는다.

계약 구현은 다음 파일에서만 확인해.

- `/Users/baek/.codex/worktrees/yolo-v26-recent-dense/petcam-lab/scripts/gme_temporal_decision.py`
- `/Users/baek/.codex/worktrees/yolo-v26-recent-dense/petcam-lab/tests/test_gme_temporal_decision.py`

## 매 실행의 읽기 전용 사전 확인

1. hostname이 `BaekBook-Pro-14-M5.local`인지 확인한다.
2. repository의 branch, HEAD, `git status --short`를 읽는다. 변경을 고치지 않는다.
3. `bundle-completion.private.json` status가 `V26_BLIND_BBOX_QUEUE_READY`인지 확인한다.
4. 두 ZIP과 review index의 SHA-256이 위 고정값과 같은지 확인한다.
5. primary ZIP의 익명 image member가 정확히 2,508개인지 확인한다.
6. double-review ZIP의 익명 image member가 정확히 200개인지 확인한다.
7. `scripts/gme_temporal_decision.py`의 최대 분석 fps가 10이고 관련 테스트가 통과하는지 확인한다.
8. production DB/R2/service/model/labeling web에 write나 deploy를 하지 않는다.

패키지나 검사기가 없으면 설치하지 마. 기존 `uv` 환경과 표준 라이브러리로 가능한 동등한 read-only 검증을 사용하고, 불가능한 항목만 명시해.

## 사람 GT inbox 계약

사람 검수가 끝나면 사용자가 다음 폴더를 직접 만들고 CVAT export를 넣는다.

`/Users/baek/private-rba/yolo26n-v26-recent-dense/attempt-20260826-owner-v1/human-gt-inbox`

예상 파일명:

- `primary-cvat-export.zip`
- `double-review-cvat-export.zip`

두 파일 중 하나라도 없으면 학습 준비를 시작하지 마. 빈 파일, `.crdownload` 같은 부분 download, ZIP CRC 오류가 있으면 fail closed로 보고해. 자동으로 CVAT에 로그인하거나 export를 내려받지 마.

## 사람이 export를 넣은 뒤 검증할 것

원본 ZIP을 수정하거나 같은 위치에 압축 해제하지 마. 필요하면 `mktemp -d`로 임시 디렉터리를 만들고 종료 시 해당 임시 디렉터리만 제거해.

1. archive가 정상적으로 열리고 path traversal member가 없는지 확인한다.
2. primary task 2,508개와 double-review task 200개가 private review index의 익명 파일명에 정확히 대응하는지 확인한다.
3. 허용 bbox class가 `gecko` 하나이고, 허용 frame tag가 `uncertain`, `media_error`뿐인지 확인한다.
4. `gecko` bbox가 하나 이상이면 `gecko_present`, bbox와 제외 tag가 모두 없으면 `gecko_absent`로 해석한다. `uncertain` 또는 `media_error` tag가 있으면 bbox 유무와 관계없이 학습 제외로 집계한다.
5. bbox 좌표가 finite이고 image bounds 안에 있으며 width/height가 양수인지 확인한다.
6. `uncertain`과 `media_error`를 absent에 합치지 않고 학습 제외로 집계한다.
7. primary image의 exact 중복, 누락, 알 수 없는 image, 중복 제출을 각각 집계한다.
8. double-review 200건의 presence 불일치, bbox 누락, IoU 불일치를 집계한다. 사람 판정을 Claude 판단으로 고치지 않는다.
9. 사람 확인 `gecko_absent`가 최소 700개이고 primary 유효 판정의 35% 이상인지 확인한다.
10. protected fingerprint overlap과 train/validation split 검사는 아직 dataset이 없으므로 실행한 척하지 말고 다음 단계의 필수 조건으로 남긴다.

CVAT export schema가 예상과 다르면 추측해서 변환하지 마. 사용한 export format과 실제 top-level member 이름만 비식별 집계로 보고하고 `V26_HUMAN_GT_SCHEMA_MISMATCH`로 멈춰.

검증 결과는 원본을 덮어쓰지 않는 신규 경로에만 저장할 수 있다.

`/Users/baek/private-rba/yolo26n-v26-recent-dense/attempt-20260826-owner-v1/human-gt-validation/<UTC timestamp>/validation-report.private.json`

보고서에는 원문 이미지, GT row, source ID를 넣지 말고 aggregate와 artifact SHA만 넣어.

## 통과와 중단 상태

모든 항목이 통과하면 다음 상태를 한 번만 보고해.

`V26_HUMAN_GT_VALIDATED`

함께 보고할 내용:

- primary 유효/absent/present/uncertain/media_error 수
- bbox 총수와 invalid bbox 수
- double-review presence agreement와 bbox agreement aggregate
- confirmed-empty 수와 비율
- export SHA-256과 validation report 절대경로
- 다음 작업은 episode split dataset build이며 아직 학습·배포하지 않았다는 사실

다음 중 하나면 즉시 쉬운 한국어로 fail-closed 보고하고 아무것도 고치지 마.

- blind ZIP/index SHA drift
- primary/double-review count mismatch
- partial 또는 손상된 CVAT export
- 익명 파일 매핑 실패
- invalid bbox 또는 허용되지 않은 class
- confirmed-empty 700개 또는 35% 미달
- Claude가 사람 판정을 대신해야만 진행 가능한 상태
- production DB/R2/service/model/labeling web write·deploy 감지

학습 코드 구현, dataset build, v2.5 checkpoint 복사, warm/clean training, 운영 GME 반영은 이 자동화의 권한 밖이야. `V26_HUMAN_GT_VALIDATED` 뒤에는 후속 Codex 작업이 필요하다고 보고하고 기다려.

사람 export가 아직 없고 고정 artifact도 정상이라면 `DONT_NOTIFY`로 끝내.
```

## 사람이 해야 할 준비

1. CVAT task에 rectangle label `gecko`와 frame tag `uncertain`, `media_error`를 만든다.
2. `blind-primary.zip`을 CVAT image task로 올려 2,508장을 검수해. 게코가 없으면 bbox와 tag를 모두 비운 채 완료한다.
3. 별도 라벨러 또는 다른 회차에서 `blind-double-review.zip` 200장을 같은 규칙으로 독립 검수해.
4. 두 export를 `CVAT for images 1.1` 형식으로 내려받아 다음 이름으로 저장해.
   - `primary-cvat-export.zip`
   - `double-review-cvat-export.zip`
5. private attempt 아래 `human-gt-inbox` 폴더에 두 파일을 넣어.
6. Claude Desktop 자동화를 즉시 한 번 실행하거나 다음 예약 실행을 기다려.

## 현재 권한 경계

- 이 문서는 read-only 감독 자동화용이므로 formal implementation handoff manifest가 아니다.
- 이 문서는 당시 사람 GT inbox 감독 설정을 보존한 역사 자료다. 현재 tracked commit과 dataset/training runner의 독립 검증 결과를 실행 기준으로 사용한다.
- Claude Desktop은 stage/commit/push/merge나 새 구현을 시작하지 않는다.
- dataset build와 비교학습을 넘기려면 plan/design을 tracked commit에 포함하고 별도 검증된 handoff를 만든다.
