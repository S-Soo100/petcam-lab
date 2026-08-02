# Production Local VLM Clip Shadow Canary v2 보고서

> **상태:** `CLOSED_GATE_A_REJECT_NOT_DEPLOYED`

## 결론

개별 프레임을 12장으로 늘려도 오늘 밤 production clip shadow는 시작하지 않았다.
`gemma3:4b`가 시간순으로 분리된 정지 실루엣 12장을 `position_change=no`로 판정하지 못해
합성 Gate A에서 fail-closed됐다. 3×2 contact sheet만의 문제가 아니라, 현재 모델·프롬프트·
Ollama 경로가 정지와 실제 이동을 운영 전제만큼 안정적으로 구분하지 못한다는 결과다.

## 실행 고정값

- 확인 시각: `2026-08-02 20:01 KST`
- host: `baeg-endeuui-Macmini.local` / arm64 / Ollama `0.32.5`
- code HEAD: `a36ba41c01b40efe676b5e579b7a024b4459deca` (clean detached worktree)
- model: `gemma3:4b`
- model digest: `024e4f9e89ca6dc406602213cfc8e3e4326efebb9a8791f665c1e6a9f427bf0f`
- model size: `3,338,801,820 bytes`
- input: 시간순 개별 JPEG 정확히 12장, 5~95% 균등
- planned end: `2026-08-03T07:00:00+09:00`
- live start: 없음

## Gate A 결과

1. `dark_empty` 단계는 통과했다.
2. `static_silhouette`가 기대값 `position_change=no`를 만족하지 못해 즉시 종료했다.
3. `moving_silhouette`, production 6-key schema, context-budget 검사는 실행하지 않았다.
4. Gate 기준·프롬프트·모델 옵션을 사후 완화하거나 실영상으로 대체하지 않았다.

## production aggregate

| 항목 | 값 |
|---|---:|
| production selected | 0 |
| production model request | 0 |
| DB SELECT / mutation | 0 / 0 |
| R2 HEAD·GET / mutation | 0 / 0 |
| GT·submission·VLM job write | 0 |
| Gate manifest / production ledger / summary | 0 / 0 / 0 |
| LaunchAgent plist / loaded service | 0 / 0 |
| 사용자 노출·자동 label·skip | 0 |
| Gate 종료 뒤 loaded model | 0 |

Mac private runtime은 `0700/0600`, 필요한 env key 6개만 사용했다. worktree는 종료 뒤에도 정확한
HEAD와 clean 상태였고, 판단 근거는 production 결과가 아니라 동결 TEST-SHEET의 합성 Gate다.

## verdict

- technical: `BLOCKED_SYNTHETIC_GATE_A`
- independent recompute: 대상 없음(production ledger 0)
- Owner quality audit: 실행 대상 없음
- production adoption: 금지 유지

## 다음 행동

12장 개별 이미지 경로를 같은 development 정답에 맞춰 반복 튜닝하지 않는다. 다음 실험은 새
TEST-SHEET에서 다른 local VLM 또는 명시적인 시간 정보 입력 방식을 비교해야 한다. 그 후보가 같은
정지/이동 Gate와 자원 Gate를 통과하기 전까지 사건별 all-event shadow와 production 자동화는 hold다.
