# TEST-SHEET — Production Local VLM Clip Shadow Canary v1

> **상태:** `PRE_REGISTERED` — live source·model·prompt·schema·resource gate를 첫 production model
> request 전에 동결한다.

## 1. 질문

Mac mini M1 16GB의 `gemma3:4b`가 오늘 밤 새 production motion clip을 사용자 영향 없이 안정적으로
관찰 JSON으로 만들 수 있는가?

## 2. source

- source table: `motion_clips`
- SELECT allowlist: `id,camera_id,r2_key,started_at,duration_sec`, `r2_key IS NOT NULL`
- 시작: Gate A 통과 뒤 service 시작 직전 확정
- 종료: `2026-08-03T07:00:00+09:00`
- 순서: 매 poll 시작 이후 전체 창을 `started_at,id` 오름차순 조회, private processed HMAC 제외
- 최대 model request: 20
- 07:00까지 20개 미만이면 과거 replacement 없이 `INCOMPLETE_LIVE_VOLUME`
- DB SELECT, R2 HEAD/GET만. Python Evidence·Gate·GT·사람 답·기존 VLM 결과 조회 0

## 3. model/runtime

- host: `baeg-endeuui-Macmini.local`
- model tag: `gemma3:4b`
- actual digest/size: Gate A 직전 private manifest에 freeze
- Ollama: 0.32.5
- request: JSON schema, `think=false`, temperature 0, seed 20260802, `num_ctx=4096`,
  `num_predict=320`, timeout 120초, `keep_alive=5m`, retry 0
- 종료·abort 시 explicit unload

## 4. input

- fractions: `5%,20%,40%,60%,80%,95%`
- exact 6 decoded frames, 3×2 chronological contact sheet 1장
- frame long edge ≤768px, JPEG quality 90
- 원본 timestamp crop/overlay 0, input SHA-256 기록
- 일시적 R2 HEAD/GET 실패는 60초 poll에서 최대 3회 확인한다. 이는 model retry가 아니며 model request 0이다.
- 3회 소진·media absent·decode failure는 `media_error`, model request 0
- `duration_sec` 결손/0은 선택·제외 근거로 쓰지 않고 실제 media frame count로 처리한다.

## 5. production schema

```json
{
  "gecko_visibility": "visible|partial|not_visible|uncertain",
  "activity_state": "active|stationary|uncertain",
  "notable_change": "movement|posture|location|interaction|none|uncertain",
  "summary_ko": "120자 이하 한국어 한 문장",
  "confidence": 0.0,
  "needs_human_review": true
}
```

extra key, fence, NaN/Infinity, enum/range/length 위반, empty content는 invalid다. parser는 보정하거나
재질문하지 않는다. 건강·질병·응급 확정, 사용자 조치 지시는 prompt에서 금지한다.

## 6. Gate A

1. `dark_empty`, `static_silhouette`, `moving_silhouette` 합성 sheet 3개가 smoke scene schema로
   서로 다른 expected enum을 반환한다.
2. 같은 합성 sheet 1개가 동결 production prompt·6-key schema에서 `parse_observation`을 통과한다.
3. 4회는 measured 20회 밖이며 실제 clip/R2/DB row를 사용하지 않는다.
4. exact code HEAD/model/prompt/schema digest, private `0700/0600`, Ollama/service pre-snapshot을 고정한다.

하나라도 실패하면 LaunchAgent를 만들거나 load하지 않는다.

- Gate A attempt 1: `dark_empty` 통과 뒤 저대비 `static_silhouette`를 `dark_empty`로 반환해 중단했다.
  production source/model request는 0, plist/service 생성은 0이었다. 첫 live request 전에 합성 장면을
  고대비 배경/실루엣으로 수정하고 회귀 테스트를 추가한 뒤 새 private run에서 Gate A 전체를 다시 연다.

## 7. 자원 중단

- 2초 resource sample
- free memory ≤5% 2회 연속
- swap baseline 대비 `>1GiB`
- Ollama PID drift/crash/OOM
- resource probe timeout/parse error/monitor exception

어느 하나면 새 request를 시작하지 않고 unload 후 `REJECT_RESOURCE`다.

## 8. verdict 우선순위

| 우선 | 조건 | verdict |
|---:|---|---|
| 1 | source/model/input/prompt/ledger digest 위반·duplicate request | `REJECT_INTEGRITY` |
| 2 | 자원 중단·Ollama crash | `REJECT_RESOURCE` |
| 3 | attempted 20인데 schema-valid 20 미달 | `REJECT_RELIABILITY` |
| 4 | 07:00 종료, attempted 20 미달 | `INCOMPLETE_LIVE_VOLUME` |
| 5 | complete/schema 20/20·자원/integrity 통과 | `LIVE_SHADOW_TECHNICAL_PASS` |

기술 PASS는 사용자 노출 승인이 아니다. Owner 품질 감사는 중대 가시성 오판 0, hallucination 0,
모순 없는 summary ≥16/20, 위험 표본 은닉 0을 별도 확인한다.

## 9. 쓰기·공개 계약

허용: Mac private root/ledger/resource/media/contact sheet, exact 임시 LaunchAgent label 하나.

금지: production DB/R2/GT/submission/VLM job write, 자동 사건 병합·skip·cloud 차단, UI/API 노출,
기존 service/plist/Ollama restart, raw ID/R2 key/secret/사람 identity 공개.
