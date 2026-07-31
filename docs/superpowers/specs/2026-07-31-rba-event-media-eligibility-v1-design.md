# RBA 사건 묶기 media eligibility v1 설계

**상태:** production read-only 실행 성공 / `PREPARED_MEDIA_VERIFIED_AWAITING_HUMAN_CHANNEL`
**작성일:** 2026-07-31
**선행:** [`event grouping shadow v2`](2026-07-31-rba-event-grouping-shadow-v2-design.md) ·
[`v2 실행 보고서`](../../../experiments/rba-event-grouping-shadow-v2/REPORT.md)

## 1. 문제와 결론

shadow v2는 기존 metadata만으로 exact 120 pair와 unique clip 240을 고르는 데 성공했다. 그러나
artifact 직전 R2 HEAD에서 228개만 확인되고 12개가 모두 `404 Not Found`였다. 영상 총량이
부족한 것이 아니라 DB의 `r2_key`와 실제 R2 객체가 일치하지 않는 영상이 source에 섞인 문제다.

v1은 **사건 표본을 고르기 전에** R2 객체 존재를 source eligibility로 동결한다. fixed cutoff의
DB key 집합을 먼저 만들고, R2 `ListObjectsV2`를 한 번 순회해 양수 크기 객체와 교집합을 만든다.
그 교집합만 activity 후보가 될 수 있다. exact 120을 고른 뒤에는 기존처럼 선택된 240개를
`HeadObject`로 다시 확인한다. LIST와 HEAD 사이에 객체가 사라지면 replacement 없이 중단한다.

## 2. 검토한 세 방식

| 방식 | 장점 | 단점 | 판정 |
|---|---|---|---|
| cutoff 이전 약 1.9만 건을 모두 HEAD | 가장 직접적 | 요청 수·시간이 크고 같은 정보를 반복 조회 | 보류 |
| 240 선택→404 제외→재선택 반복 | 구현이 작음 | 결과를 본 뒤 replacement한 provenance가 복잡하고 종료 횟수 불명확 | reject |
| **R2 LIST inventory→DB 교집합 동결→exact 120→최종 HEAD 240** | 읽기 요청이 작고 eligibility와 최종 확인이 분리됨 | bucket LIST의 privacy·pagination 계약 필요 | **adopt** |

availability는 사건 GT나 영상 내용이 아니다. 따라서 LIST 결과로 404 객체를 source에서 제외하는
것은 label cherry-picking이 아니다. 다만 R2에 남아 있는 영상만 평가하는 availability bias는
보고서에 명시하고 production 자연 분포 주장에는 사용하지 않는다.

## 3. 입력과 경계

- DB source cutoff는 shadow v2와 같은 strict
  `started_at < 2026-07-31T03:44:27.183403+09:00`다.
- DB는 `motion_clips`, `motion_clip_system_exclusions`, `motion_clip_review_slots`,
  `labeling_tutorial_lessons`를 SELECT만 한다.
- R2는 `ListObjectsV2`와 선택 뒤 `HeadObject`만 허용한다.
- R2 key, URL, ETag, raw clip/camera/reviewer ID는 공개 출력하지 않는다.
- GT, submission 답, Python Evidence, Gate, local/cloud VLM은 읽지 않는다.
- DB/R2 mutation, R2 GET, frame decode, service/launchd 변경은 0이다.

R2 전체 bucket을 LIST하되 메모리에는 fixed DB source가 참조하는 key와의 일치 여부만 남긴다.
다른 객체 key는 artifact·로그에 기록하지 않는다.

## 4. Media inventory 계약

### 4.1 DB key 정규화

- `r2_key`는 앞뒤 공백을 제거한 non-empty 문자열이어야 available 후보가 될 수 있다.
- 같은 non-empty key를 두 clip 이상이 공유하면 해당 clip 전부를
  `r2_key_duplicate:media-eligibility-v1` diagnostic으로 내린다. 한 객체가 어느 clip의
  원본인지 일대일로 증명할 수 없지만 다른 정상 clip까지 전체 중단할 이유는 없기 때문이다.
- empty/null key는 오류로 전체 중단하지 않고 `diagnostic_integrity`의
  `r2_key_missing:media-eligibility-v1`로 accounting한다.

### 4.2 LIST pagination

- 모든 page는 HTTP 200과 bool `IsTruncated`를 가져야 한다. `KeyCount=0`이면 boto3/S3가
  `Contents`를 생략하는 정상 응답을 빈 list로 받아들인다. `KeyCount>0`인데 `Contents`가 없거나
  길이가 `KeyCount`와 다르면 fail-closed한다.
- `Contents`의 match key는 문자열이고 `Size`는 bool이 아닌 0 이상의 정수여야 한다.
- `IsTruncated=true`면 non-empty `NextContinuationToken`이 필수다.
- continuation token 재사용·cycle, 10,000 page 초과, SDK 오류는 모두
  `BLOCKED_MEDIA_INVENTORY_FAILED`로 key 없이 중단한다.
- DB key와 일치하고 `Size > 0`인 객체만 available이다. 미등장 또는 size 0은
  `r2_object_absent:media-eligibility-v1` diagnostic이다.

### 4.3 provenance

private manifest에는 다음만 추가한다.

- LIST page 수
- fixed source 기준 available/unavailable count
- available/unavailable clip ID 정렬 집합의 SHA-256
- algorithm version `r2-list-intersection-v1`

wall-clock은 동일 입력 manifest hash를 바꾸므로 hashed manifest에 넣지 않는다. public runtime
summary에만 inventory 시작·종료 UTC 시각을 남긴다. public summary에는 count와 digest만 남기며
key·ID는 0이다.

## 5. Accounting과 표본 선택

우선순위는 `blocked_research > diagnostic_integrity > activity_candidate`다.

1. formal/canary/tutorial/frozen clip은 기존처럼 `blocked_research`다.
2. 기존 active system exclusion 또는 invalid duration은 `diagnostic_integrity`다.
3. media inventory에서 unavailable인 clip도 `diagnostic_integrity`다. reason은
   `r2_key_missing`, `r2_key_duplicate`, `r2_object_absent`를 구분한다.
4. 위 조건에 걸리지 않고 양수 duration·R2 object가 있는 clip만 `activity_candidate`다.

그 뒤 shadow v2의 cutoff, 닫힌 activity day, gap bin, exact 12 camera-nights, dev/holdout 60/60,
bin별 20/20/20, unique clip 240, camera cap 36/14, bounded deterministic search를 그대로 쓴다.
media eligibility 이후 exact 계약이 불가능하면 기존 selector blocker로 끝내며 기준을 완화하지 않는다.

## 6. 이중 media preflight

```text
DB fixed source
→ R2 LIST inventory 교집합 동결
→ available source에서 exact 120 선택
→ 선택된 240 R2 HEAD
→ 240/240일 때만 private artifact 생성
```

최종 HEAD는 HTTP 200, 양수 content length, non-empty ETag를 요구한다. 하나라도 실패하면
`BLOCKED_MEDIA_PREFLIGHT_FAILED`이고 replacement·output directory·manifest·worksheet는 0이다.
blocker aggregate는 key 없이 `not_found_404 / auth_401_403 / invalid_response / other`를 나눠
전량 credential 실패와 실제 객체 소실을 구분한다.
240/240이면 상태는 `PREPARED_MEDIA_VERIFIED_AWAITING_HUMAN_CHANNEL`이다.

## 7. 성공 조건

- production DB SELECT only, R2 LIST + HEAD only
- inventory pagination·duplicate DB key·empty key·missing object fail-safe 테스트
- exact 120, unique 240, dev/holdout 60/60, bin별 20/20/20, camera cap 통과
- final R2 HEAD 240/240
- private artifact mode `0700/0600`, no-overwrite
- 독립 aggregate 감사의 selection/provenance hash 일치
- raw ID/key/GT 공개 0, DB/R2/service/model mutation 0
- one-shot 직전 short-clip retention/deletion 자동화의 loaded·실행 상태를 read-only로 확인하고,
  active라면 LIST→HEAD race 가능성을 보고한다. 이 작업에서 service를 pause하지는 않는다.

사람 검수 채널과 reviewer prior exposure는 이 artifact가 성공한 뒤 별도 동결한다. 이 단계는 사건
묶기 채택, production worker, 앱 노출, local VLM 실행을 승인하지 않는다.

## 8. 실패와 다음 행동

- LIST 자체 오류: inventory 구현/권한을 고치기 전 재선택 금지
- unavailable이 많아 exact 120 불가: 새 영상을 자동 대기하지 않고 camera-night/bin별 가용성부터 보고
- final HEAD <240: LIST→HEAD 사이 변화로 간주하고 replacement 없이 중단
- 성공: private artifact와 aggregate report를 만든 뒤 사람 검수 채널 설계로 이동

## 9. iTerm Claude 교차리뷰 반영

공식 AppleScript로 기존 Claude Fable 5/high 세션에 design·TEST-SHEET·plan·runner를 read-only로
전달했다. 판정은 `APPROVE_WITH_CHANGES`, P0 0개였다. P1 여섯 건을 모두 채택했다.

1. `KeyCount=0`일 때 정상적인 `Contents` 생략 허용
2. duplicate DB key는 전체 abort 대신 관련 clip 전부 diagnostic
3. missing key, duplicate key, object absent reason 분리
4. wall-clock을 hashed manifest에서 제외
5. short-clip deletion 자동화의 LIST→HEAD race 사전감사
6. final HEAD 실패를 404/auth/invalid/other aggregate로 분류

## 10. 실행 판정

Mac mini one-shot에서 cutoff 이전 fixed DB inventory `19,279` 중 R2 available `17,702`,
object absent/size 0 `1,577`, missing/duplicate key `0/0`을 확인했다. 선택된 12 camera-night의
source/accounting은 `5,034/5,034`였다. 그 교집합에서 exact 120,
dev/holdout `60/60`, split별 bin `20/20/20`, 12 camera-nights, unique clip 240을 선택했고 최종
R2 HEAD `240/240`을 통과했다. pair/source manifest hash, camera cap `36/14`, private mode
`0700/0600`도 독립 재감사했다. DB/R2 mutation·R2 GET·모델·프레임·서비스 변경은 0이다.

따라서 이전 `228/240` media blocker는 해소됐다. 다음 gate는 사람 검수 채널 동결이며, 사건 묶기
품질 채택과 local VLM 실행은 아직 승인되지 않았다. 상세는
[`REPORT`](../../../experiments/rba-event-media-eligibility-v1/REPORT.md)를 따른다.
