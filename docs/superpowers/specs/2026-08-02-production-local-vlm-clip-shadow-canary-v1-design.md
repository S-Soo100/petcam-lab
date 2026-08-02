# Production Local VLM Clip Shadow Canary v1 설계

**상태:** Owner 서면 승인 / 구현 승인
**작성일:** 2026-08-02
**실행 목표:** 오늘 밤 production에서 새로 생기는 실제 영상 최대 20개를 local VLM이 자동 관찰하되,
결과는 사용자·GT·라우터에 영향을 주지 않는 private shadow로만 남긴다.

## 1. 한 줄 결론

오늘 밤부터 실제 production 입력으로 local VLM을 돌리되, 아직 안전한 사건 경계 모델이 없으므로
영상을 임의로 합치지 않고 **새 motion clip 한 개를 임시 사건 한 개로 취급**해 관찰 결과만 만든다.

## 2. 왜 clip-first인가

사람이 확정한 74경계 시험에서 MiniCPM-V 4.6은 서로 다른 사건 17/17을 전부 합쳤고,
Qwen3-VL 2B는 빈 응답과 swap 한도 초과로 탈락했다. 따라서 두 모델의 경계 판단으로 여러 영상을
자동 사건화하면 안 된다.

반면 사용자가 원하는 최종 제품 계약은 “실제 활동 영상은 모두 볼 수 있고, 모든 사건에 최소 하나의
저비용 AI 관찰이 있다”다. 오늘 밤은 이 목표를 다음처럼 분리해 첫 운영 증거를 만든다.

```text
production 새 clip
→ 영상 한 개를 임시 사건 한 개로 유지
→ 고정 6-frame contact sheet
→ Gemma 3 4B 관찰 JSON
→ Mac mini private shadow 원장
```

원본 파일·DB row는 합치거나 삭제하지 않는다. 이후 안전한 사건 묶기 방법이 생기면 clip 관찰 여러
개를 사건 순서대로 묶어 재사용할 수 있다.

## 3. 검토한 접근

| 접근 | 장점 | 문제 | 판정 |
|---|---|---|---|
| 탈락한 MiniCPM/Qwen3를 그대로 사용자 화면에 연결 | 가장 빠름 | over-merge·빈 응답·자원 실패를 사용자에게 전파 | reject |
| 먼저 사건 묶기 모델을 새로 개발한 뒤 시작 | 이상적인 단위 | 오늘 밤 실제 production 관찰을 시작하지 못함 | 후속 |
| **clip-first private production shadow** | 실제 새 영상·비용·자원·관찰 품질을 오늘 측정, 사용자 영향 0 | 호출 중복이 있고 아직 사건 단위가 아님 | **adopt** |

## 4. 모델 선택

오늘 밤 v1은 Mac mini에 이미 설치되어 있고 `vision` capability가 실측된 `gemma3:4b` 하나만 쓴다.

- architecture: Gemma 3
- parameters: 4.3B
- quantization: Q4_K_M
- installed size: 약 3.3GB
- runtime: Ollama 0.32.5
- 선택 이유: Qwen3-VL 2B의 empty structured output과 MiniCPM의 경계 안전 실패를 운영 canary에
  그대로 반복하지 않으면서, M1 16GB에서 한 번에 하나씩 실행 가능한 기존 vision 모델이다.

이 선택은 사용자용 채택이 아니라 **private production shadow 후보**다. 실행 전 synthetic JSON
smoke를 통과하지 못하면 실제 영상을 한 건도 호출하지 않는다. `qwen2.5vl:7b`는 8.3B라 오늘 밤
메모리 안전 기준 비교 대상에서 제외하고 삭제하지 않는다.

## 5. production 입력 계약

### 5.1 시간과 수량

- 시작: service가 production preflight를 통과한 시각
- 종료: 2026-08-03 07:00 KST 또는 schema-valid 20개 완료 중 먼저 오는 시점
- source: 시작 시각 이후 production `motion_clips`에 생긴 row
- 순서: production 정본 컬럼 `started_at`, `id` 오름차순
- 매 poll마다 시작 이후 전체 창을 다시 SELECT하고 private processed HMAC set을 제외해 가장 이른
  미처리 row를 고른다. 전진 전용 DB cursor를 쓰지 않아 늦게 insert된 이른 `started_at` row도 놓치지 않는다.
- 최대: 모델 요청 20개, key당 정확히 1회, retry 0
- 종료까지 20개가 안 생기면 과거 영상으로 채우지 않고 `INCOMPLETE_LIVE_VOLUME`로 보고

### 5.2 자격

- R2 key가 있고 HEAD/GET/decode 가능한 새 clip
- 모델 선택에 Python Evidence 점수, Gate, 행동 GT, 사람 답, 기존 VLM 결과를 사용하지 않음
- `has_motion` 강도나 duration으로 유리한 표본만 고르지 않음
- 일시적 R2 HEAD/GET 실패는 60초 poll에서 최대 3회 재확인할 수 있지만, 모델 요청을 시작한 뒤에는
  같은 key를 재호출하지 않음
- decode 불가·R2 부재는 숨기지 않고 별도 `media_error` aggregate로 기록

DB는 SELECT만, R2는 HEAD/GET만 허용한다. 결과는 production DB가 아니라 Mac private JSONL에만
append+fsync한다.

## 6. 모델 입력

clip마다 duration 기준 `5%, 20%, 40%, 60%, 80%, 95%`의 프레임 6장을 시간순으로 뽑아 3×2
contact sheet 한 장으로 만든다.

- 긴 변 768px 이하, 비율 유지, JPEG quality 90
- 촬영 원본의 좌하단 timestamp를 crop·overlay로 가리지 않음
- sheet에는 `1~6` 순서 외 행동명·evidence·정답을 쓰지 않음
- input bytes·prompt·model digest SHA-256 기록
- 프레임 하나라도 정확히 decode하지 못하면 그 clip은 `media_error`, 모델 호출 0

mp4 전체를 Ollama에 직접 넣는 것이 아니라, 오늘 밤에는 시간축을 대표하는 고정 6장으로 비용과
메모리를 제한한다.

## 7. 고정 출력

prompt version은 `production-local-vlm-clip-shadow-canary-v1`이다. 모델은 다음 JSON object만 반환한다.

```json
{
  "gecko_visibility": "visible|partial|not_visible|uncertain",
  "activity_state": "active|stationary|uncertain",
  "notable_change": "movement|posture|location|interaction|none|uncertain",
  "summary_ko": "관찰된 사실만 적은 120자 이하 한국어 한 문장",
  "confidence": 0.0,
  "needs_human_review": true
}
```

금지 출력:

- 건강·질병·응급 상태 확정
- 먹었다·배변했다처럼 프레임에서 확인되지 않은 사건 추측
- Python Evidence/Gate/GT를 봤다고 주장
- 사용자 조치 지시

Ollama options는 JSON schema format, `think=false`, temperature 0, seed `20260802`,
`num_ctx=4096`, `num_predict=320`, timeout 120초, retry 0으로 동결한다. parser가 답을 보정하거나
빈 응답을 추측하지 않는다.

## 8. runtime 구조

Mac mini 전용 임시 LaunchAgent label:

`com.petcam.local-vlm-clip-shadow-canary-v1`

동작:

1. 60초마다 시작 이후 production clip 전체 창을 다시 SELECT한다.
2. 아직 처리하지 않은 가장 이른 clip을 한 개 고른다.
3. R2 HEAD/GET/decode와 contact sheet를 만든다.
4. Gemma 3 4B를 호출하고 strict JSON을 private JSONL에 append+fsync한다.
5. 20개 완료 또는 07:00 KST에 정상 종료한다.

중복 방지는 private state의 HMAC clip key로 한다. raw clip ID·R2 key·secret·사람 identity는 공개
보고서와 Slack에 출력하지 않는다. service는 기존 capture, Python Evidence, activity, VLM worker를
재시작하거나 plist를 수정하지 않는 별도 label이다.

## 9. 자원 안전 기준

- 모델은 한 번에 하나만 load
- 요청 사이 `keep_alive=5m`, 종료 시 명시적 unload
- 2초마다 free memory, swap, Ollama RSS 기록
- free memory ≤5% 2회 연속이면 새 요청 중단
- 시작 대비 swap `+1GiB` 초과면 새 요청 중단
- Ollama PID 변경·server crash·OOM이면 즉시 `REJECT_RESOURCE`
- timeout·empty·schema invalid는 해당 key 실패이며 retry하지 않음
- resource monitor 자체가 실패해도 fail-closed

## 10. 단계별 gate

### Gate A — 오늘 밤 service 시작 전

- synthetic contact sheet 3종의 smoke 전용 scene schema가 모두 valid
- 같은 합성 sheet 1개를 동결 production prompt·6-key schema로 추가 호출해 schema-valid
- blank/dark/visible-motion 의미가 서로 구별됨
- private root `0700`, artifact `0600`
- exact code HEAD·model digest·prompt digest 고정
- DB write/RPC와 R2 PUT/DELETE method가 runner에 없음
- Ollama와 기존 service pre-snapshot 완료

하나라도 실패하면 LaunchAgent를 load하지 않는다.

### Gate B — 내일 아침 기술 판정

- live 요청 20개면 complete/schema 20/20
- timeout·empty·parser failure 0
- resource abort·Ollama crash 0
- duplicate model request 0
- DB/R2/GT/service mutation 0

20개 미만은 실패로 꾸미지 않고 `INCOMPLETE_LIVE_VOLUME`; 품질 확대 판정은 보류한다.

### Gate C — 사람 품질 감사

Owner가 20개 원본과 shadow 결과를 나란히 보고 다음을 독립 판정한다.

- 게코 가시성 중대 오판 0
- 보이지 않는 행동을 했다고 단정한 hallucination 0
- 실제 관찰과 모순 없는 `summary_ko` ≥16/20
- `needs_human_review`가 위험·불명확 표본을 숨긴 건 0

통과해도 verdict는 `LIVE_SHADOW_CANARY_PASS`이며 사용자 화면 노출 승인이 아니다.

### Gate D — all-clip shadow 확대

Gate C 통과 뒤 새 TEST-SHEET로 다음을 별도 실행한다.

- 닫힌 activity day 3일
- 총 100개 이상
- 가능한 범위에서 2 cameras·6 camera-nights 이상
- schema 100%, resource abort 0
- 고정 30개 사람 감사에서 중대 hallucination 0

이 gate까지 통과한 뒤에만 사용자에게 `AI 관찰(beta)`로 노출하는 설계를 연다.

## 11. 사용자에게 보이는 흐름

오늘 밤에는 사용자 UI 변화가 없다.

```text
[화면] 기존 앱·라벨링 웹 그대로
→ [운영] 새 clip이 평소처럼 저장됨
→ [반응] Mac mini가 뒤에서 관찰 JSON을 private로 생성
→ [감정] 사용자는 오판을 보지 않으며, 내일 검증 가능한 실제 운영 증거만 쌓임
```

향후 Gate D를 통과하면 별도 UI 설계에서 영상 아래에 `AI 관찰(beta)`와 `확인 필요`를 표시한다.
그 전에는 사용자에게 노출하지 않는다.

## 12. 실패·복구

- Gate A 실패: production service 시작 0, synthetic report만 남김
- 일부 media 오류: 원인 aggregate를 남기고 다음 새 clip으로 진행, 임의 과거 replacement 금지
- 모델 오류: 해당 key 실패 기록, retry 0
- 자원 오류: 새 요청 중단, model unload, LaunchAgent 종료
- Mac 재부팅: `RunAtLoad=false`; owner 승인 없는 자동 재개 금지
- 종료 뒤 model과 private artifact는 재현성을 위해 보존, 기존 모델 삭제 0

## 13. 명시적 범위 밖

- 여러 clip의 자동 사건 병합
- 사람 GT·owner resolution·교차검수 답 읽기 또는 수정
- Python Evidence·Gate를 모델 입력·자동 제외 근거로 사용
- 자동 skip, cloud 호출 차단, 케어 알림
- 사용자 화면·앱 API·production DB에 VLM 결과 쓰기
- Qwen3-VL 2B 재시도, MiniCPM 경계판정 재사용
- LoRA·fine-tuning·prompt 반복 튜닝

## 14. 실행 체크리스트

### 구현 전

- [ ] TEST-SHEET 동결
- [ ] iTerm2 공식 AppleScript Claude 설계 검수
- [ ] exact host/runtime/service/queue read-only snapshot
- [ ] source query와 R2 read-only 계약 테스트

### 구현

- [ ] 순수 sampler·schema·parser·verdict TDD
- [ ] private processed-set/HMAC·append+fsync·no-overwrite TDD
- [ ] 60초 poll·20개/07:00 종료 TDD
- [ ] resource monitor·unload·fail-closed TDD
- [ ] public aggregate redaction TDD

### production 시작 전

- [ ] focused/full pytest, compileall, `git diff --check`
- [ ] handoff manifest `HANDOFF_OK`
- [ ] Mac exact detached HEAD와 private permission 확인
- [ ] synthetic 3/3 smoke 통과
- [ ] 기존 Ollama/service PID·model digest snapshot
- [ ] 새 LaunchAgent만 load, 기존 service restart 0

### 내일 아침

- [ ] 20개 또는 실제 live 수량·종료 사유 확인
- [ ] model unloaded·service 종료 확인
- [ ] duplicate·schema·latency·resource aggregate 재계산
- [ ] Owner 20개 품질 감사용 private bundle 생성
- [ ] `확대 / 모델 교체 / 중단` verdict 보고
