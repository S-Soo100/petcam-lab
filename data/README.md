# data/

평가셋 + 클래스 정의.

## 파일

| 파일 | 설명 |
|---|---|
| `eval-159.jsonl` | v3.5 production baseline 평가 결과 (159 클립) |
| `classes.json` | raw 9 / UI 8 클래스 정의 + 매핑 룰 + tie-break priority |

## eval-159.jsonl 형식

JSON Lines (한 줄 = 한 클립). 라인 예시:

```json
{
  "clip_id": "0125b0f9-50fb-42bf-a622-6c9903afb865",
  "ok": true,
  "action": "moving",
  "confidence": 0.8,
  "reasoning": "The gecko makes a single lick at the food dish but does not engage in sustained, repeated licking required for eating_paste, and then proceeds to move and reposition itself within the enclosure.",
  "elapsed_ms": 11473,
  "model": "gemini-2.5-flash-zeroshot-v3.5"
}
```

| 필드 | 타입 | 의미 |
|---|---|---|
| `clip_id` | uuid | 영상 식별자 (DB `camera_clips.id` FK) |
| `ok` | bool | 추론 성공 (false면 model error/timeout) |
| `action` | string | raw 9-class 중 하나 |
| `confidence` | float [0,1] | 모델 자체 추정 (calibration 안 됨) |
| `reasoning` | string | 자유 텍스트, 디버깅용 |
| `elapsed_ms` | int | API 호출 latency |
| `model` | string | 모델 ID (라운드별 식별) |

## GT 라벨 (별도 export 필요 — 현재 미포함)

이 jsonl에는 **모델 출력만** 포함. GT 정답 라벨은 본 레포 Supabase `behavior_logs(source='human')`에 있음. portable 패키지에서 평가 재현하려면 GT를 별도 jsonl로 export 해서 함께 두어야 함:

```jsonl
{"clip_id": "0125b0f9-...", "gt_action": "moving", "labeled_by": "user_xxx", "labeled_at": "..."}
```

→ TODO: `data/gt-159.jsonl` 추가 export.

## classes.json 활용

- 모델 출력 검증: `action ∈ raw_classes.values` 여부
- UI 노출 매핑: `mappings.raw_to_ui[action] || action`
- 평가 비교: `mappings.eval_only_extra` 추가 적용 (hiding → moving)
- 새 종 추가: `species_availability` 패턴 따라 prompts에 분기
