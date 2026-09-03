# GME Owner 활동 요약·상태 박스 설계

> 상태: `DEPLOYED_OWNER_CANARY_PENDING`
>
> 승인일: 2026-09-03 KST

## 1. 문제

Owner 라벨링 상세의 초록 박스는 게코 탐지 여부만 뜻하지만 움직임으로 오해하기 쉽다. 기존
`GME 관측 움직임 시간`은 서버에서 미리 계산돼도 GT 잠금 뒤에만 보여, Owner가 영상을 끝까지
재생하기 전에는 전체 움직임 시간을 알기 어렵다.

문제 영상의 v2.6 원장은 `moving=0.0초`, `visible=60.5초`, `unknown=0.3초`이고 나머지 관측
구간은 `static`이다. 따라서 이번 수정은 올바른 계산을 재학습하는 작업이 아니라 탐지·정지·움직임을
화면에서 분리하는 작업이다.

## 2. 사용자 체험

- **[화면]** Owner가 상세를 열면 재생 전부터 `게코가 움직인 시간`, `게코가 보인 시간`,
  `게코가 정지한 시간`, `판정 불확실`과 전체 상태 막대를 본다.
- **[조작]** 영상을 재생하거나 원하는 시점으로 이동한다.
- **[반응]** 현재 상태가 상태 막대에 강조되고 박스도 `움직임/정지/미확정`에 맞는 색으로 바뀐다.
- **[감정]** 박스가 계속 보인다는 이유로 게코가 계속 움직였다고 오해하지 않는다.

## 3. 범위

### 포함

- 현재 active detector identity의 성공 artifact만 Owner overlay에 사용
- artifact의 `state_intervals`를 엄격히 검증하고 익명 track index로 변환
- Owner 상세에서 재생 전 전체 요약과 상태 막대 표시
- 움직임·정지·미확정·카메라 움직임·미관측의 색과 문구 분리
- `관측`을 `게코가 보인 시간`으로 바꿔 의미 명확화

### 제외

- YOLO 재학습, 기존 GME run 재분석, DB migration
- 움직임 임계값 변경 또는 새 활동 알고리즘 도입
- 일반 라벨러 blind 화면의 AI 사전 노출 확대
- 활동값으로 자동 제외·행동 정답·건강 상태 확정

## 4. 데이터 계약

`gme-overlay` 응답에 다음 공개 구간만 추가한다.

```ts
type GmeMotionState = 'moving' | 'static' | 'unknown' | 'camera_motion' | 'not_visible';

interface GmeStateInterval {
  start_sec: number;
  end_sec: number;
  state: GmeMotionState;
  track_indexes: number[];
}
```

- 원본 `track_id`, artifact identity, R2 key는 브라우저에 보내지 않는다.
- 구간은 유한한 초, 반열린 범위, 영상 길이 안, 비중첩, 시간순이어야 한다.
- overlay source는 `GME_ACTIVE_DETECTOR_IDENTITY`와 정확히 일치하는 succeeded job만 선택한다.
- 성공 artifact가 없으면 기존처럼 `available=false`; 사람 라벨링은 계속 가능하다.

## 5. 표시 규칙

| 상태 | 박스/막대 | 의미 |
|---|---|---|
| `moving` | 초록 | 지속 기준을 통과한 움직임 |
| `static` | 회색 | 게코는 보이지만 정지 |
| `unknown` | 노랑 | 판정 근거 부족 |
| `camera_motion` | 보라 | 카메라 움직임으로 분리 |
| `not_visible` | 옅은 회색 | 게코 미관측 |

전체 요약은 interval 합집합으로 계산한다. `움직임`과 `정지`를 별도 숫자로 표시하고,
`게코가 보인 시간 = 움직임 + 정지` 불변식을 유지한다. 0초는 성공 분석에서만 숫자로 표시한다.
구간 사이에 공백이 있으면 게코가 안 보였다고 추측하지 않고 `미확정`으로 표시한다.

## 6. 검증

- 문제 영상 fixture에서 `움직임 0초`, `게코가 보인 시간 60.5초`, `정지 60.5초`,
  `미확정 0.3초`가 재생 전 렌더링된다.
- 정지 구간의 박스는 초록이 아니라 회색이다.
- active detector identity가 다른 최신 run은 overlay source로 선택되지 않는다.
- 비정상·중첩·범위 밖 interval과 원본 track id 노출은 거부한다.
- 기존 feedback 버튼과 영상 라벨 저장 흐름은 회귀하지 않는다.

## 7. 로컬 검증 결과

- 관련 테스트: 26개 통과
- 웹 전체 Vitest: 150 files, 1,286 tests 통과
- TypeScript: `npx tsc --noEmit` 통과
- 변경 검사: `git diff --check` 통과
- production 문제 영상 원장: 움직임 0초, 보인 시간 60.5초, 정지 60.5초, 미확정 0.3초로 재확인
- Preview `dpl_7T2gMo9RNos2tA6iFytGNtgALUSg`와 Production
  `dpl_DUAywK76JorvGveZcirPZtheNiBX`가 READY이고 각 Git 커밋의 Vercel 상태가 success다.
- `label.tera-ai.uk`는 새 Production을 가리키며 `/labeling`과 문제 영상 상세는 HTTP 200,
  비로그인 overlay API는 401이다.
- 로그인 Owner 브라우저의 시각 canary는 Chrome 제어 연결이 반복 해제돼 미확인으로 남겼다.
- DB 변경·기존 run 재분석·R2 write는 수행하지 않았다.
