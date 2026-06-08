# eval-203(153) — Claude blind 통합 평가 + GT 검수 + v3.6.1 OOD 초안

**일자:** 2026-06-08
**범위:** 203건 평가셋 중 contact-sheet **적합 5클래스 153건**(44 eval-0608 + 109 eval-159). 미세/순간 행동 50건은 파일럿서 불가 확정 → 제외.
**판정:** v3.6 프롬프트, 서브에이전트 blind (GT 미공개, meta.json 차단), 5x6 360px.

> ⚠️ **정량 baseline 아님** — Claude + contact sheet. production=Gemini 영상. "정확도 XX%" 인용 금지. 정량은 Gemini key 복구 후 `load_eval_set_0608`/`load_eval_set`.

## 1. 파일럿이 거른 것 — 미세/순간 행동은 contact sheet 불가
shedding 5 + defecating 3을 **6x6 480px(더 조밀) × 3회**로 측정:
- **defecating 0/3** (배변 순간이 36프레임 샘플에 안 걸림, 흔들림조차 없는 일관된 moving = 정보 부재 확정)
- **shedding 1/5** + 흔들림 극심(251ffaaa는 3회에 moving/eating_paste/shedding 전부 다름)
- → 6x6·N회로도 미해결. 해상도가 아니라 "순간/미세 동작 × 프레임 샘플링"의 구조적 한계. **shedding 29·defecating 16·hiding 3·unseen 2(50건) 평가 제외** 결정.

## 2. 153건 결과 (GT 정정 후)
| 클래스 | 정확도 | 판정 |
|---|---|---|
| moving | 91% (58/64) | ✅ contact sheet 충분 |
| hand_feeding | 88% (23/26) | ✅ 도구 가시성 좋음 |
| eating_paste | 61% (11/18) | △ close-up만 |
| eating_prey | 40% (10/25) | ❌ 작은 prey 안 보임 |
| drinking | 35% (7/20) | ❌ 물핥기 안 보임 |

raw 71.2%(109/153). 남은 오답 대부분 `→moving`(drinking 12·eating_prey 10·eating_paste 6) = 미세 접촉 입력 한계.
→ **contact sheet 적합도 맵**: moving·hand_feeding은 영상 없이 가능, drinking·eating_prey·eating_paste의 미세접촉분은 Gemini 영상 필요.

## 3. ★ blind = 라벨 QA — GT 오류 9건 발견·정정
GT 차단 blind 가 픽셀 사실로만 판단 → 등록 라벨 오류를 역으로 검출:
- **2961**(eval-0608): hand_feeding→eating_paste (도구 없는 dish paste)
- **159건 8건**: eating_prey/eating_paste → **hand_feeding** — 사람이 핀셋/시린지/스푼/손으로 급여하는 영상인데 v3.5 시절(hand_feeding 클래스 부재) 라벨이라 오분류. 8장 육안 교차검증 후 정정(`49458257·c928b6ff·c6f22144·e784eb65·7d9b9e8e`=핀셋/손 prey, `41aecaea·dbdd4378·5cfe1d48`=시린지/스푼 paste).
- → **"신규 evidence셋 등록 후 blind 1회 = GT 검수" 루틴이 실증됨.**

## 4. ★ v3.6.1 OOD 룰 초안 (채택 보류)
153건에서 `moving/eating_* → hand_feeding` 과발동 발견: v3.6 OOD 룰이 *"사람 손/도구 보이면 hand_feeding"* 이라 **단순 핸들링(들기/만지기/청소)도 hf로 과분류**.

- **v3.6.1**(`system_base.v3.6.1.md`, v3.6 무손상 버전 격리): OOD 트리거를 *"음식을 게코에게 전달하는 행위(도구에 음식 있고 제시/게코가 먹음)"* 로 좁힘. 단순 손 존재 ≠ hand_feeding.
- **정성 검증(11건)**: 과발동 5건 → **5/5 moving 으로 수정**, 진짜 도구급여 6건 → **6/6 hand_feeding recall 유지**. v3.6 6/11 → v3.6.1 11/11.
- **채택 절대 보류** — 정성 11건 + contact sheet. 메모리 룰("회귀 없이 프롬프트 변경 6번 실패"). Gemini key 복구 후 203 정량(OOD recall + P0 floor + 과발동 감소) 통과해야만 `DEFAULT_PROMPT_VERSION` 승격.

## 다음
1. **Gemini 복구 → v3.6.1 정량 회귀** — `eval_vlm_v36_handfeeding` 에 prompt_version 분기 추가 → 203 으로 v3.5/v3.6/v3.6.1 비교. 과발동↓ + recall 유지 + P0 floor 확인.
2. **미세행동(50건)은 Gemini 영상** — defecating/shedding 은 시간축 있어야. contact sheet 영구 제외.
3. **남은 →moving 입력한계분** — drinking/eating_prey 도 Gemini 영상이면 회복 예상.
