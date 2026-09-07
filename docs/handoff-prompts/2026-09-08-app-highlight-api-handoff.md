# 앱 하이라이트 API 전환 핸드오프 — terra-server → petcam-api `/highlights` (2026-09-08)

> 대상: Flutter 앱 개발자 · terra-server 백엔드 개발자 · 이 레포 다음 세션.
> 결정: owner 2026-09-07 — "하이라이트는 자동 규칙 기준으로 먼저 만들고, 사람이 몇 주 관찰하며 기준을 수정한다. 문서화해 두고 앱에도 바로 적용 가능하게."
> 결정 로그: [`docs/decision-gate.md`](../decision-gate.md) 2026-09-07 1~4차 · 스펙: [`feature-highlight-auto-initial-designation.md`](../../specs/feature-highlight-auto-initial-designation.md)

## 1. 무엇이 바뀌나 (한 줄)

앱의 하이라이트 피드가 **terra-server `GET /clips/highlights`(옛 VLM 행동 라벨 기준)** 에서 **petcam-api `GET /highlights`(GME 자동 1차 판정 + 사람 확정 우선)** 로 바뀐다. DB(Supabase `slxjvzzfisxqwnghvrit`)는 같으므로 데이터가 두 벌 되는 게 아니라 HTTP 창구와 판정 기준이 바뀌는 것이다.

## 2. 판정 기준 (앱이 받는 값의 뜻)

| 값 | 뜻 |
|---|---|
| `source = "human"` | 라벨링 웹에서 사람이 `O`로 확정한 영상. 사람 확정이 규칙보다 우선. |
| `source = "rule"` | 사람 확정이 아직 없고, active 규칙이 `O`로 판정한 영상. |
| `reason` | 규칙이 읽은 숫자 그대로. 예 `움직임 12.4초 · 최장 연속 6.1초`. 카드에 그대로 보여줘도 된다. |
| `rule_version` | 판정에 쓰인 규칙 버전(`hl-rule-v0`…). owner 가 라벨링 웹에서 숫자를 바꾸면 새 버전이 활성화되고 **그 순간부터** `source=rule` 영상의 O/X 가 바뀐다(저장된 값이 아니라 조회 시 계산). 사람 확정(`human`)은 안 바뀐다. |

규칙 v0(2026-09-07 owner 승인): 게코가 보인 영상에서 **움직인 시간 ≥ 10초 또는 한 번에 연속 ≥ 5초** 면 `O`. 나머지·게코 미관측 = `X`. `애매` 없음, 밤당 개수 제한 없음. 최근 3주 기준 영상의 약 15%가 `O`(주 카메라 밤당 약 16개). 이 숫자는 **몇 주간 사람 확정 유지율을 보며 바뀔 예정**이니 앱에 하드코딩하지 말 것.

**앱에서 하지 말아야 할 것:** 행동 이름(탈피·음수 등)을 기대하지 않는다 — 이 피드에는 행동 class 가 없다. 행동 class 는 별도 스펙(라벨링 v4 다음 단계)에서 다시 온다.

## 3. 엔드포인트 계약 (petcam-api, `https://api.tera-ai.uk`)

인증: 기존 petcam-api 와 같은 Supabase JWT `Authorization: Bearer <access_token>`. 본인 소유 카메라(`cameras.user_id`)의 영상만.

### `GET /highlights?since=<ISO8601>&limit=<1..100>&cursor=<opaque>`

- `since`(선택): 이 시각 이후(포함) 영상만. 생략 = 하한 없음. naive 시각은 UTC 로 해석, 파싱 실패 400. 앱은 어젯밤 리포트=지난 밤 시작, 하이라이트 화면=30일 전.
- `limit`: 기본 50, 최대 100(초과는 422).
- `cursor`: 이전 응답의 `next_cursor`. 값 형식은 불투명(해석 금지).

응답:

```json
{
  "highlights": [
    {
      "clip_id": "…uuid…",
      "camera_id": "…uuid…",
      "camera_name": "거실",
      "started_at": "2026-09-07T18:12:03+00:00",
      "duration_sec": 60.6,
      "media_ready": true,
      "source": "rule",
      "reason": "움직임 12.4초 · 최장 연속 6.1초",
      "rule_version": "hl-rule-v0",
      "decided_at": null
    }
  ],
  "count": 1,
  "has_more": false,
  "next_cursor": null,
  "rule_version": "hl-rule-v0"
}
```

정렬: `started_at` 내림차순. 항목의 `rule_version` 은 `source=rule` 일 때만 채워지고 `human` 이면 `null`(사람 확정은 규칙 출력이 아님). `media_ready=false` 면 원본이 삭제된 영상이라 재생하지 않는다. 영상 재생·썸네일은 기존처럼 `clip_id` 로 petcam-api 의 clip/motion 엔드포인트를 쓴다(변경 없음).

### `GET /highlights/rule`

활성 규칙 `{version, params, activated_at}`. 디버그·투명성용. 앱 표시엔 불필요.

### 오류

`401` 인증 없음 · `422` 파라미터 범위 밖 · `400` cursor/since 손상 · `404` 활성 규칙 없음(운영 사고, owner 에게) · `502` DB 오류 · `503` GME 계약 미해결(env 도 없고 ok run 도 없음) · `504` 피드 계산 시간 초과(드묾, 재시도).

## 4. 서버 쪽 사실 (petcam-api 운영자용)

- 구현: `backend/routers/highlights.py`. DB 의 `fn_list_labeling_v4_clips(... p_highlight_state='yes' ...)` 를 재사용해 "현재 하이라이트 = 사람 확정 우선, 없으면 규칙" 정의를 라벨링 웹과 **한 곳**에서만 유지한다. 옛 `GET /clips/highlights`(행동 class 기준)는 그대로 두었고 앱은 더 이상 쓰지 않는다.
- fly 앱 `petcam-api` 에 env 필요: `GME_ACTIVE_ALGORITHM_VERSION`, `GME_ACTIVE_DETECTOR_IDENTITY` (라벨링 웹 Vercel 과 같은 값), 선택 `GME_ACTIVE_ENGINE_SCHEMA_VERSION`(기본 `gme-shadow-v1`). 비어 있으면 최신 `ok` GME run 의 값으로 폴백(5분 캐시)하고 경고 로그를 한 번 남긴다.
- 배포: `uv run pytest` → `flyctl deploy --config fly.api.toml --app petcam-api`. **주의:** petcam-api 는 오래 미배포 상태라 그동안의 백엔드 변경이 함께 나간다 → 배포 뒤 `/me/is_labeler`, `/clips`, `/clips/highlights`(legacy) smoke 필수.

## 5. terra-server 개발자에게

- 앱이 terra-server `GET /clips/highlights` 를 더 이상 호출하지 않는다(Flutter `HighlightRepository` 가 petcam-api 로 전환). 그 엔드포인트는 **삭제하지 말고** "앱 미사용" 으로 표시만 해 두면 된다.
- 어젯밤 리포트의 활동시간(`motionSeconds`)은 계속 기존 경로를 쓴다 — 이번 전환은 하이라이트 목록만이다.
- 같은 판정을 terra-server 에서 내고 싶으면 SQL 함수 `fn_list_labeling_v4_clips`(service_role EXECUTE) 를 `p_scope='all', p_camera_ids=<사용자 카메라>, p_highlight_state='yes'` 로 호출하면 petcam-api 와 동일한 결과다. 판정 정의를 따로 구현하지 말 것(드리프트 방지).

## 6. 앱 개발자에게 (Flutter 변경 요약)

- `HighlightRepository` base URL = `EnvConfig.backendUrl`, 경로 `/highlights`.
- `NightlyHighlight` 모델: `vlmAction/confidence/careLevel` 제거 → `source/reason/ruleVersion/cameraId/cameraName/durationSec/decidedAt` 추가.
- 어젯밤 리포트: 행동별 카운트(음수·식사·탈피) 제거 → "하이라이트 N개 + 활동시간". 카드 배지 = `reason`, 사람 확정이면 "확인됨" 표시.
- 72시간 묶음(`groupHighlights`)·재생·즐겨찾기는 `clip_id/started_at` 만 쓰므로 그대로.

## 7. 운영 루프 (왜 기준이 바뀌는가)

라벨링 웹에서 회원들이 매일 1차 판정을 `O/X` 로 확정한다. owner 는 주 1회 `/labeling/owner/highlight-rules` 에서 규칙 버전별 **유지율**(사람이 그대로 둔 비율)·O→X/X→O 수정·사유를 보고 숫자를 바꾼다. 새 버전 활성화 = 앱의 `source=rule` 결과가 즉시 바뀜. 앱은 `rule_version` 을 로그에 남겨두면 "그때 왜 이게 하이라이트였지" 를 추적할 수 있다.
