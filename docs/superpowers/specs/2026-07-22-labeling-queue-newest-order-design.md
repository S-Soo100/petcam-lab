# 라벨링 큐 최신순 보장 설계

> **상태:** owner 설계 승인 / 구현계획 작성 전 문서 검토
>
> **대상:** `https://label.tera-ai.uk/labeling`

## 1. 목표

일반 라벨링 큐가 필터·페이지네이션·동시 요청 상황에서도 항상 촬영 시각 최신순을 유지하게 한다.
라벨러가 첫 화면에서 최신 영상을 보고, `더보기`로는 반드시 더 오래된 영상만 받으며, 같은 촬영
시각을 가진 clip도 누락·중복 없이 결정론적으로 탐색할 수 있어야 한다.

## 2. 현 상태와 결함

API는 이미 `camera_clips.started_at DESC`를 사용하고 UI도 최신순이라고 안내한다. 그러나 계약은
다음 세 경계에서 완전하지 않다.

1. cursor가 `started_at` 하나뿐이라 같은 시각의 여러 clip 사이 순서가 결정론적이지 않고, 다음
   페이지에서 일부가 누락될 수 있다.
2. 필터를 바꾸거나 새로고침한 뒤 이전 요청이 늦게 돌아오면 최신 요청의 목록·오류·busy 상태를
   덮을 수 있다.
3. `더보기` 응답을 단순 append하므로 중복 응답이나 경합이 생겼을 때 최종 배열의 정렬·고유성이
   구조적으로 보장되지 않는다.

## 3. 사용자 체험

- **[화면]** 라벨링 큐에 들어오면 현재 필터에서 가장 최근에 촬영한 영상이 첫 카드로 보인다.
- **[조작]** `더보기`를 누르면 현재 마지막 카드보다 오래된 영상만 아래에 추가된다.
- **[반응]** 같은 초에 촬영된 영상도 고정된 순서로 보이고, 새로고침해도 서로 자리를 바꾸지 않는다.
- **[조작]** 카메라·날짜 필터를 빠르게 바꾼다.
- **[반응]** 이전 필터의 늦은 응답은 버려지고 현재 필터 결과만 보인다.
- **[감정]** 라벨러는 새 영상이 위에 있다는 점과 이미 본 카드가 갑자기 섞이지 않는다는 점을
  신뢰할 수 있다.

## 4. 정렬·cursor 계약

### 4.1 정본 정렬키

정렬 정본은 다음 두 키다.

1. `started_at DESC`
2. `id DESC`

`started_at`은 영상 촬영 시작 시각이며 큐의 "최신" 의미와 일치한다. `id`는 동률 해소용으로만
사용한다. `created_at`이나 라벨 세션 생성 시각으로 의미를 바꾸지 않는다.

### 4.2 versioned opaque cursor

API cursor는 `{ version: 1, started_at, id }`를 URL-safe base64로 인코딩한다. 서버는 다음을 모두
검증한다.

- `version === 1`
- `started_at`이 유효한 ISO-8601 시각
- `id`가 UUID
- decode 실패·필드 누락·미지 version은 일반 `400 invalid_cursor`

cursor 이후 조건은 `(started_at < cursor.started_at) OR
(started_at = cursor.started_at AND id < cursor.id)`다. cursor 원문이나 DB 오류는 응답에 노출하지
않는다.

### 4.3 필터와 live insert

- 카메라·날짜 필터는 첫 페이지와 모든 다음 페이지에 동일하게 적용한다.
- 페이지 탐색 중 새 clip이 생겨도 기존 cursor보다 최신이므로 현재 `더보기` 결과에 끼어들지 않는다.
- 사용자가 `새로고침`하면 cursor를 폐기하고 첫 페이지부터 다시 읽어 새 clip을 최상단에 표시한다.

## 5. 클라이언트 동시성 계약

- 목록 요청마다 generation을 발급한다.
- await 이후 응답·오류·finally는 현재 generation일 때만 상태를 바꾼다.
- 첫 페이지는 기존 목록을 교체하고, 다음 페이지는 `clip.id` 기준으로 dedup한 뒤 정본 정렬키로
  다시 정렬한다.
- 필터 변경은 generation을 올리고 cursor·items·hasMore·error를 새 요청 기준으로 초기화한다.
- `더보기`가 진행 중일 때 같은 버튼의 중복 요청은 막는다.

## 6. API·보안 경계

- 기존 owner/labeler 접근 게이트, 튜토리얼 게이트, blind GT 응답 컬럼을 그대로 유지한다.
- behavior/VLM/evidence 필드를 새로 조회하거나 노출하지 않는다.
- triage·completed-session 필터는 기존 의미를 유지한다.
- DB migration은 없다.
- 기존 cursor 문자열은 새 배포 이후 `400 invalid_cursor`가 될 수 있다. cursor는 URL에 영속화하지
  않는 일시 요청 값이므로 별도 legacy decoder를 두지 않는다.

## 7. 오류 처리

- 잘못된 cursor: `400 invalid_cursor`
- DB 조회 실패: 기존 일반화된 `502`, 내부 테이블명·메시지 비노출
- 오래된 응답: 사용자 오류로 표시하지 않고 조용히 폐기
- thumbnail 실패: 카드 순서와 무관하게 기존 placeholder 동작 유지

## 8. 검증

필수 자동 테스트:

1. 같은 `started_at`의 UUID 동률이 `id DESC`로 고정된다.
2. 복합 cursor 다음 페이지에 누락·중복이 없다.
3. invalid base64, 미지 version, invalid timestamp/UUID가 `400`이다.
4. triage·completed clip을 건너뛰어도 반환 items는 최신순이다.
5. 필터 A의 늦은 응답이 필터 B 목록·오류·busy를 바꾸지 않는다.
6. 중복 clip이 두 응답에 있어도 UI에는 한 번만 보인다.
7. 새로고침 후 새 clip이 첫 카드다.

production smoke:

- 같은 필터에서 API 2페이지를 받아 `(started_at, id)`가 전 구간 단조 감소하는지 확인한다.
- 라벨러 계정으로 첫 카드가 production DB의 최신 eligible clip과 일치하는지 read-only 대조한다.

## 9. 완료 조건

- API와 UI 모두 `(started_at DESC, id DESC)`를 정본으로 사용한다.
- 페이지 간 clip 누락·중복 0이다.
- stale response 회귀 테스트가 통과한다.
- web 전체 테스트·TypeScript·Next build가 통과한다.
- production smoke에서 최신 eligible clip이 첫 카드로 확인된다.

## 10. 비목표

- 라벨링 우선순위 점수 도입
- 희소 행동 oversampling
- 일반 큐에 Python Evidence·VLM 판정 노출
- 자동 격리·자동 skip 정책 변경
