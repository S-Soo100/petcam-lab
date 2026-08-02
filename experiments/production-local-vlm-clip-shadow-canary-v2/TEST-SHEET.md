# Production Local VLM Clip Shadow Canary v2 — TEST-SHEET

상태: **동결(frozen), 실행 전**

동결 시각: 2026-08-02 KST

목적: contact sheet 실패 뒤, 시간순 개별 이미지 12장으로 Gemma 3 4B가 정지와 실제 이동을 구분하고 production clip shadow를 안전하게 처리할 수 있는지 검증해.

## 변경 불가 계약

- 모델: `gemma3:4b` (digest와 size는 Gate manifest에 기록)
- 입력: 영상당 시간순 개별 JPEG 정확히 12장
- 시점: `0.05 + 0.90*i/11`, `i=0..11`
- 이미지: crop·overlay 없이 긴 변 최대 768px, JPEG quality 90
- 옵션: temperature 0, seed 20260802, num_ctx 4096, num_predict 320, retry 0
- 종료: schema-valid 20건, request 20건, 자원 reject, 무결성 reject, 또는 2026-08-03 07:00 KST
- 데이터 권한: Supabase SELECT, R2 HEAD/GET만 허용. DB/R2 write·GT 확정·자동 label·자동 skip 금지

## Gate A — production 접근 전 필수

모두 동일한 12-image Ollama 경로를 사용하고 아래 4회가 전부 한 번에 맞아야 해.

1. dark empty → `background=dark`
2. static silhouette → `position_change=no`
3. moving silhouette → `position_change=yes`
4. moving silhouette + production schema → 6-key schema-valid

추가 무결성 조건:

- 2번과 3번은 같은 질문의 negative/positive pair여야 해.
- production smoke의 `prompt_eval_count`가 양의 정수여야 해.
- `prompt_eval_count + 320 <= 4096`이어야 해. 아니면 입력 잘림 가능성으로 Gate 실패야.
- Gate 실패 시 cohort/DB/R2/LaunchAgent/plist/service를 만들거나 수정하지 않아.

## 자원·신뢰성 판정

- 연속 2회 free memory 5% 이하 → `REJECT_RESOURCE`
- baseline 대비 swap 1 GiB 초과 → `REJECT_RESOURCE`
- Ollama serve PID 변경 → `REJECT_RESOURCE`
- 20회 요청 중 schema-valid 20 미만 → `REJECT_RELIABILITY`
- schema-valid 20/20 + 자원·무결성 통과 → `LIVE_SHADOW_TECHNICAL_PASS`
- 종료 시각까지 20건 미만 → `INCOMPLETE_LIVE_VOLUME`

기술 통과는 행동 정확도 채택이나 production 자동화 승인이 아니야. 결과는 사람 review와 별도 future holdout 전까지 shadow 연구 자료로만 써.

## 실행 전 체크

- [ ] 정확한 host·40자리 HEAD·clean detached worktree
- [ ] v1 label 미가동 및 v1 plist 부재
- [ ] private root 0700, env/salt 0600
- [ ] 모델 이름·digest·size 확인
- [ ] Gate A 4회와 context budget 통과
- [ ] Slack에 사전 계획 공유

## Attempt 기록

| attempt | 시각(KST) | HEAD | Gate 결과 | production service | 비고 |
|---|---|---|---|---|---|
| 미실행 | - | - | - | 없음 | Gate 통과 전 |
