# Production Local VLM Clip Shadow Canary v2 — Individual 12 Frames

## 결정

v1의 6-frame 3×2 contact sheet는 Gemma 3 4B가 패널별 상대 위치를 비교하지 못해 Gate A에서
종료됐다. v2는 사용자가 승인한 기본 12개 프레임을 **한 장에 합치지 않고 시간순 개별 이미지 12장**으로
전달한다. v1 코드·TEST-SHEET·보고서는 감사 이력으로 수정하지 않는다.

## 입력 계약

- fractions: `0.05 + (0.90 × i / 11)`, `i=0..11` — 5%부터 95%까지 균등 12개
- 각 frame은 원본 crop·timestamp overlay 없이 긴 변 768px 이하, JPEG quality 90
- Ollama `messages[0].images`에 시간순 base64 이미지 12개
- prompt는 이미지 1~12가 시간순임을 명시하고 보이는 사실만 한국어 6-key JSON으로 반환
- model/options: `gemma3:4b`, think false, temperature 0, seed 20260802, ctx 4096,
  predict 320, timeout 120초, keep_alive 5m, model retry 0

## Gate A

실제 clip·DB·R2를 열기 전에 같은 12-image 경로로 다음 4회를 통과해야 한다.

1. dark frames → `background=dark`
2. static oval → `position_change=no`
3. moving oval → `position_change=yes`
4. moving synthetic → production 6-key schema parser PASS

static/moving은 같은 질문에 반대 답을 요구한다. 하나라도 실패하면 v2 plist/service를 만들지 않는다.

## live shadow

- Gate 통과 시점 이후 `motion_clips`, `r2_key IS NOT NULL`, `started_at,id` 순서
- production model request 최대 20, 종료 `2026-08-03T07:00:00+09:00`
- DB SELECT, R2 HEAD/GET만 허용
- 입력 12개 SHA, request intent, 결과, 자원 표본은 Mac private `0700/0600`에만 저장
- label: `com.petcam.local-vlm-clip-shadow-canary-v2`
- free memory ≤5% 2회, swap +1GiB, Ollama serve PID drift/probe 실패 시 종료
- 사용자 노출, GT/submission/VLM job/DB/R2 write, 사건 병합, skip, cloud 차단은 0

## 성공·실패

- Gate 실패: `BLOCKED_SYNTHETIC_GATE_A`, production request 0
- attempted 20/schema 20/resource·integrity PASS: `LIVE_SHADOW_TECHNICAL_PASS`
- attempted 20/schema 미달: `REJECT_RELIABILITY`
- 07:00까지 attempted 20 미달: `INCOMPLETE_LIVE_VOLUME`
- resource/integrity 위반: 각각 `REJECT_RESOURCE` / `REJECT_INTEGRITY`

기술 PASS도 production 사용자 노출 승인이 아니다. Owner가 20개 영상과 관찰 JSON을 별도 감사한다.

## 승인

2026-08-02 owner가 “기본 12개로” 변경하고 즉시 구현·실행을 승인했다.
