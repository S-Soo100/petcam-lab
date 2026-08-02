# Production Local VLM Clip Shadow Canary v1 보고서

> **상태:** `CLOSED_GATE_A_REJECT_NOT_DEPLOYED`

## 결론

오늘 밤 production clip shadow는 시작하지 않았다. `gemma3:4b`는 합성 이미지를 받고 밝기·도형·
위치 변화 자체는 읽었지만, 한 장의 3×2 접촉표에서 각 패널 안의 상대 위치를 비교하지 못했다.
정지 실루엣에도 `position_change=yes`를 반환해 Gate A를 통과하지 못했다.

## 실행 고정값

- host: `baeg-endeuui-Macmini.local` / Ollama `0.32.5`
- 마지막 검수 code HEAD: `7e1bbff94da866135aed7f8fc28dc40024b08cc0`
- model: `gemma3:4b`
- model digest: `024e4f9e89ca6dc406602213cfc8e3e4326efebb9a8791f665c1e6a9f427bf0f`
- model size: `3,338,801,820 bytes`
- planned end: `2026-08-03T07:00:00+09:00`
- live start: 없음

## Gate A 결과

1. attempt 1은 저대비 static을 `dark_empty`로 반환해 중단했다.
2. attempt 2는 고대비 뒤에도 3-class scene 첫 enum 편향으로 같은 단계에서 중단했다.
3. 직접 관찰 schema로 분리하고 정지/이동에 같은 질문의 반대 답을 요구했지만, static과 moving을
   모두 `position_change=yes`로 보아 중단했다.
4. production 6-key schema smoke까지 도달하지 않았으며 Gate를 완화하거나 실영상을 대신 넣지 않았다.

## production aggregate

| 항목 | 값 |
|---|---:|
| production selected | 0 |
| production model request | 0 |
| DB SELECT / mutation | 0 / 0 |
| R2 HEAD·GET / mutation | 0 / 0 |
| GT·submission·VLM job write | 0 |
| LaunchAgent plist / loaded service | 0 / 0 |
| 사용자 노출·자동 병합·skip | 0 |

## verdict

- technical: `BLOCKED_SYNTHETIC_GATE_A`
- Owner quality audit: 실행 대상 없음
- production adoption: 금지 유지

## 다음 행동

같은 contact-sheet Gate를 더 튜닝하지 않는다. 다음 시도는 별도 decision gate와 TEST-SHEET에서
`6개 개별 이미지 입력` 또는 `다른 local VLM`을 비교한다. 통과 전까지 all-event shadow는 hold다.
