# Claude 구독 트랙 — hand_feeding OOD 룰 정성 검증 (2026-06-07)

> v3.6 후보 프롬프트의 OOD 룰("도구가 frame 에 보이면 hand_feeding")이 작동하는지, Claude(Claude Code 세션)가 contact sheet 를 **직접 보고** 판정. **방법론 검증 — 모델 일반화/floor 비교 아님** (experiment-claude-subscription-rba.md §6.1). Gemini AQ. key 차단으로 회귀평가가 막힌 동안의 우회 검증.

## 입력
- hand_feeding 5건 + moving 대조 1건 (feature-hand-feeding-ood-label.md GT sync 후)
- R2 영상 → ffmpeg 5×6 contact sheet (`scripts/_make_handfeeding_sheets.py`) → `sample-<short>/contact.jpg`
- 판정기: Claude Code(이 세션). 전술 3 (Claude Code 오케스트레이터 — ffmpeg 추출 + 판정).

## 판정 결과

| clip | GT(sync 후) | dur | contact sheet 도구 식별 | Claude 판정 | OOD 룰 |
|---|---|---|---|---|---|
| b8317750 | hand_feeding | 49.7s | ✅ 핑크 스틱 + 손바닥 | hand_feeding | ✅ 정확 |
| cc0c1d04 | hand_feeding | 12.1s | ✅ 위에서 내려온 손 + 도구 | hand_feeding | ✅ 정확 |
| 9af1ba2e | hand_feeding | 41.3s | ✅ 스푼/시린지 + 손가락 | hand_feeding | ✅ 정확 |
| 27c5b14f | hand_feeding | 6.2s | ⚠️ 불명확 (그릇+어두운 영역) | 미확정 | contact sheet 한계 |
| ce5fee73 | hand_feeding | 11.9s | ⚠️ 불명확 (검은 격자 위) | 미확정 | contact sheet 한계 |
| 65b57205 | moving | 60.0s | 도구 없음 (IR 야간 유목) | moving | ✅ 오탐 0 |

## 발견 (방법론)
1. **OOD 룰 타당** — 도구가 명확히 보이는 3/5 케이스에서 Claude도 hand_feeding 정확 판정. "도구 가시성 → hand_feeding" 룰이 모델 무관하게 작동함을 확인.
2. **대조군 오탐 0** — 도구 없는 moving(65b57205)을 hand_feeding 으로 오탐하지 않음.
3. **contact sheet 해상도 한계 실증 (experiment §9)** — 가는 스틱(27c5b14f 6.2s / ce5fee73 11.9s)은 30프레임·360px contact sheet 에서 식별 실패. Gemini 는 영상 네이티브 입력으로 같은 도구를 봤음 (159 진단의 vlm reasoning: "pink feeding stick" / "stick being held"). → **룰은 맞지만 입력 형태(contact sheet vs 영상)가 미세 도구 검출을 좌우.**

## 한계 (정직히 — 거짓 자신감 방지)
- **모델 일반화 X** (§6.1): Claude 결과지, Gemini 로 같은 결과 보장 안 됨. production = Gemini.
- **재현성 X** (§6.2): Claude Code temperature 비제어, N=1, 약한 블라인드(GT 사전 인지).
- **입력 비대칭**: Claude = contact sheet(저해상 격자) vs Gemini = 영상 네이티브. 동일 입력 아님 → 회귀평가 대체 불가.

## 결론 / 다음
- v3.6 hand_feeding OOD 룰의 **개념적 타당성 확인** (도구 명확 시 작동 + 오탐 0). 채택 근거 보강.
- **정량 채택 판단은 Gemini AIza key 확보 후 `scripts/eval_vlm_v36_handfeeding.py` 회귀평가로** (floor 비교는 동일 모델·동일 입력이어야).
- 운영 함의: contact sheet/저해상 입력은 가는 도구에 약함 → 도구 큰 케이스 우선 신뢰, 미세 도구는 프레임 해상도↑ 또는 영상 네이티브 필요.
