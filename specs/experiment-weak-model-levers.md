# Experiment — 약한 모델 레버 테스트 (frames 202)

> Fable 5 가 번 격차(81.7→85.1%)를 약한/싼 모델에서 5개 레버(입력표현·표적룰·캐스케이드·다모델합의·증거레이어)로 얼마나 회수할 수 있는지 실측 → production Gemini(Flash↔Pro) 설계의 사전 검증.

**상태:** 🚧 진행 중 (P1/P1b 완료 — P2~P6 레버 대기)
**작성:** 2026-06-10
**연관 SOT:** 정확도 전략은 [`experiment-event-segment-vlm.md`](experiment-event-segment-vlm.md) · 구독 트랙 원칙은 [`experiment-claude-subscription-rba.md`](experiment-claude-subscription-rba.md) §6 (모델 불일치/재현성 함정)

## 1. 목적

- 2026-06-10 Fable 5 frames 202 blind 에서 모델 레버 실측치 확보: **이전 run 81.7% → Fable 5 85.1%** (recovered 11/broken 4, McNemar p≈0.12). 이득의 절반 이상이 "룰 준수 신뢰성"(moving→unseen 도망 5건 전멸)이었음 → **약한 모델에서도 레버로 회수 가능한 영역이 있다는 가설**.
- 사용자 질문 "Opus 4.8 같은 다른 모델도 Fable처럼 잘하게 하려면?"에 5개 레버 전부 실측으로 답한다.
- 진짜 목적지는 **production Gemini**: Flash(싼 모델)를 레버로 끌어올리는 설계는 종량제 비용에 직결. Claude 구독 트랙($0)으로 사전 검증 후 key 복구 시 Gemini 로 전이.

## 2. 스코프

### In (이번 스펙에서 한다)
- **P1 — 약한 모델 baseline**: Opus 4.8 full 202 frames blind (+ 선택: Sonnet 4.6). 세션 모델명 기록 의무 (06-09 run 모델 미기록 교훈).
- **P2 — 레버 A 입력표현**: 오답셋 N=20 프레임 + 모션 키프레임 선택 ablation.
- **P3 — 레버 B 표적 룰 보강**: P1 에러 패턴 기반 v3.6.2-draft (버전 격리), error-set ablation → 유망시에만 full 202.
- **P4 — 레버 C 캐스케이드 시뮬레이션**: 기존 jsonl 결합으로 **신규 인퍼런스 0** 오프라인 평가. 클래스 기반 라우팅 vs confidence 단독(대조군).
- **P5 — 레버 D 다모델 합의**: weak↔Fable 불일치 건만 3rd vote → majority 정확도.
- **P6 — 레버 E 증거 레이어 PoC**: Apache 라이선스 디텍터(RF-DETR 우선)로 drinking/defecating 오답 ~10건에 ROI 좌표·체류 evidence 생성 → 주입 vs 무주입. **timebox 반나절**, 초과 시 별도 스펙 분리.
- **P7 — 종합**: 레버별 Δ·비용·Gemini 전이가능성 표.

### Out (이번 스펙에서 **안 한다**)
- **Gemini 실측** — key 차단 중. 전이 설계서까지만, 실행은 key 복구 후 별도 항목.
- **v3.6.2 DEFAULT 승격** — Gemini 202 정량 회귀 통과 전 금지 (CLAUDE.md 프롬프트 버전 룰).
- **YOLO 본 구현** — P6 은 "evidence 가 약한 모델 판정을 바꾸는가" 미니 PoC 만.
- **Haiku 4.5 baseline** — vlm donts#1 에서 이미 라벨링 신뢰도 부족 판정. 재확인 가치 낮음 (제외 사유).

> **스코프 변경은 합의 후에만.**

## 3. 완료 조건

- [x] **P1**: ✅ `opus48_blind.jsonl` 202건 + `_score_frames_models.py` 4모델 비교. **Opus 4.8 = 81.2%** (164/202). Fable 5 85.1% > Opus 81.2% (χ²=3.50, 11-vs-3 — 방향 강하나 단독 유의 직전). B06 에이전트 `5cfe1d48` 1건 JSON 누락 → 보충 에이전트 재판정.
- [x] **P1b**: ✅ `sonnet46_blind.jsonl` 202건. **Sonnet 4.6 = 78.2%** (158/202). Fable 5 > Sonnet **χ²=6.04 유의(p<0.05)**. ★ 격차 원천 규명: Sonnet moving 93→**76%** (IR 야간 창백패치를 shedding 으로 과탐 — 단일 실패모드에 격차 집중). shedding 자체는 90→93%로 외려 높음 = 정밀도 손실. **→ 레버 B(표적 룰)의 직접 타깃 확보.**
- [x] **P2**: ⚠️ **가설 기각** — 모션 키프레임(N=20=균등10+모션피크10) 재판정: 오답셋 **recovered 1/11**(shedding 1건만), 대조군 **broken 0/9**. 순효과 +0.5%p (채택 기준 +1%p 미달). `_p2_extract_keyframes.py`+`_score_p2.py`. **★ 발견: 남은 ceiling 오답은 시간 샘플링 문제가 아니라 공간해상도/시각가시성 한계.** 모션에너지(256px)는 혀 날름(저모션)을 못 짚어 엉뚱한(몸이동) 프레임 선택 → eating_paste 0/3·eating_prey 0/5. 회복된 1건은 shedding(정적 시각증거라 프레임 多=기회 多). **근거: close-up 대조군 9/9 유지 vs 원거리 오답셋 거의 전멸** = 카메라 거리/접촉크기가 게이팅. → **이 오답들은 drinking/defecating 과 같은 시각한계 버킷**(덜 심할 뿐). 프레임트릭 X, 영상네이티브(Gemini)/고해상캡처/HITL.
- [ ] **P3**: `web/prompts/backups/system_base.v3.6.2-draft.md` 신규 파일 + `prompt_version` 분기 (v3.6.1 무손상) → error-set ablation → 유망시 full 202. broken 측정 필수 (근거강제 룰 부작용 교훈)
- [x] **P4**: ✅ `scripts/_sim_cascade.py` (인퍼런스 0). **★ R1 shedding-trigger = 23% 에스컬레이션으로 격차 100% 회수**(Sonnet 78.2%→85.1%=Fable 동급). conf 단독(R3)은 같은 회수에 53% 에스컬레이션 필요(2.3배 비효율, `confidence_abstain_limit` 재확인). random 동률예산 36%만 회수 → 표적 라우팅 +4.5%p 우위. R4 disagree(Sonnet≠Opus) 19%→107%(최고효율, 단 싼모델 2개).
- [ ] **P5**: 불일치 건 3rd vote 실행 (모델 체인: Gemini CLI 멀티모달 확인 → 불가시 Codex CLI → 최후 Opus, 한계 명시) + majority 정확도 표
- [ ] **P6**: evidence 텍스트 주입 vs 무주입 n≈10 정성 비교 (판정 변화 여부 + 방향)
- [ ] **P7**: 종합 표 + `next-session.md` "key 복구 후" 섹션에 Gemini 전이 항목 등록

## 4. 설계 메모

- **평가 프로토콜 고정** (모든 phase 공통): 기추출 frames · v3.6.1 프롬프트(P3 제외) · blind(meta.json 차단) · 라운드로빈 배치 8건 · clip8 채점 · paired recovered/broken + McNemar. **리포트에 세션 모델명 기록**.
- **error-set 우선 전략**: full 202 재실행은 채택 후보 레버만. 잔존 오답 × K트랙 ablation 으로 방향 먼저 결정 (메모리 `feedback_vlm_error_set_ablation_pattern` 패턴).
- **통계 정직성**: 202건에서 ±3%p 는 단독 유의 어려움 (Fable run p≈0.12 실증). 레버 채택은 (a) recovered>broken (b) 에러 패턴 메커니즘 설명 가능 (c) 스택 최종본 full 202 재검증 — 3단으로.
- **캐스케이드가 인퍼런스 0인 이유**: per-clip pred 가 jsonl 로 이미 존재 → 라우팅 룰만 바꿔 오프라인 재생 (JS 비유: 녹화된 응답 fixture 로 라우터 unit test). 라우팅 룰 후보: ① 취약클래스 예측시 에스컬레이션 (defecating/drinking/unseen 인접) ② 클래스×conf 결합 ③ conf 단독 (대조군 — `feedback_vlm_confidence_abstain_limit` 재확인용, 무효 예상).
- **모션 키프레임 (P2 옵션 B)**: `experiments/drinking-motion-poc/motion_energy.py` 프레임차분 재활용 — 균등 샘플 대신 모션 피크 주변 추출. drinking PoC 에선 음성이었지만 keyframe **선택** 용도는 별개 가설.
- **P6 디텍터**: RF-DETR(Apache) 우선, 실패시 YOLOX/D-FINE. Ultralytics AGPL 금지 (2026-06-09 라이선스 결정). evidence 포맷 예: `"gecko ROI: 물그릇 반경 50px 내 체류 8.2s (f_003~f_011), before/after 그릇 영역 픽셀 변화 없음"`.
- **비용 추정**: full 202 1회 ≈ 26 에이전트 × ~125k ≈ **3.3M 서브에이전트 토큰** (Fable run 실측). 세션당 full run 1~2회 제한 권장. error-set run ≈ 0.5~1M.
- **리스크 / 미해결 질문**:
  - Opus 4.8 baseline 이 이미 82~84% 면 레버 검출력 부족 → Sonnet 4.6 추가로 보완 (P1b 결정 사유)
  - Gemini CLI 이미지 입력 가능 여부 미확인 (P5 모델 체인으로 헤지)
  - 구독 한도 — full run 남발 금지, 오늘 Fable run 으로 이미 3.3M 소진
  - **레버 결과는 Claude 트랙 정성** — Gemini 전이는 방법론만 일반화, 수치는 재측정 (§6.1 모델 불일치 함정)

## 4-1. P1/P1b 실측 결과 (2026-06-10)

| 클래스(GT) | 이전run | Sonnet 4.6 | Opus 4.8 | Fable 5 |
|---|---|---|---|---|
| **raw 전체** | 81.7% | **78.2%** | **81.2%** | **85.1%** |
| moving (72) | 93% | **76%** ⚠️ | 93% | **100%** |
| shedding (29) | 90% | 93% | 90% | 90% |
| hand_feeding (28) | 96% | 96% | 93% | 96% |
| eating_prey (22) | 73% | 73% | 68% | 77% |
| eating_paste (17) | 82% | 76% | 82% | 82% |
| defecating (16) | 19% | 38% | 25% | 31% |
| drinking (16) | 69% | 75% | 62% | 69% |
| unseen (2) | 50% | 100% | 100% | 0% |

**핵심 발견 — 약한 모델 격차는 확산이 아니라 단일 실패모드에 집중:**
- Sonnet 의 7%p 손실은 **거의 전부 moving→shedding 오탐**(IR 야간 창백패치를 허물로 환각). moving 93→76%(−17%p) 한 클래스가 전체 격차를 설명. shedding recall 은 외려 +3%p(정밀도를 깎아먹은 과탐). → **단일 룰로 회수 가능** = 레버 B 의 이상적 타깃.
- Fable 5 의 우위도 moving(→unseen 도망 0 + IR 견고)에서 나옴 = **"룰 준수 신뢰성"이 모델 격차의 주축**, 지각 천장(036a650d 류)은 부차적.
- defecating(19~38%)·drinking(62~75%)은 4모델 전부 바닥 = **모델 불변 한계** 재확인(순간이벤트/벽응결수). 레버로 못 풂 → 영상네이티브/메타/HITL.

**레버 D 사전 데이터(추가 인퍼런스 0):**
- 현행 3모델 **만장일치 158/202(78%) → 정확도 89.9%**. 불일치 44건이 오답의 소굴.
- **majority-vote 85.6% ≈ Fable 단독 85.1%** — 약한 2모델+strong 합의가 strong 단독과 동급. 비용 대비 이득 협소(불일치 44건만 3rd vote 거는 선택적 캐스케이드가 효율적).
- → 레버 C(캐스케이드)는 "불일치 44건만 strong 에스컬레이션"으로 시뮬레이션. 레버 D 는 "전건 합의는 비효율, 불일치만"으로 좁힘.

## 4-2. P4 캐스케이드 시뮬 결과 (2026-06-10, 인퍼런스 0)

base=Sonnet 78.2% / ceiling=Fable 85.1% / 회수 대상 격차 +6.9%p.

| 라우팅 룰 | 에스컬레이션 | 정확도 | 격차 회수 |
|---|---|---|---|
| **R1 Sonnet=shedding → Fable** | **23%** | **85.1%** | **100%** |
| R2 취약4클래스 예측시 | 35% | 84.7% | 93% |
| R3 conf<0.7 (대조군) | 17% | 83.2% | 71% |
| R3 conf<0.9 | 53% | 84.7% | 93% |
| R4 Sonnet≠Opus (싼모델 2개) | 19% | 85.6% | 107% |
| random 동률예산(23%) | 23% | 80.7% | 36% |

**결론 — P1b 발견의 정면 입증:**
- **표적 라우팅(R1)이 핵심.** "싼 모델이 shedding 이라 하면 그것만 비싼 모델에 재확인" — 비싼 호출 23% 로 격차 전부 회수. 약점이 단일 실패모드라 라우팅 트리거도 단일(shedding 예측)이면 충분.
- **conf 단독(R3)은 2.3배 비효율.** R1 과 같은 100% 회수를 conf 로 하려면 53% 에스컬레이션 필요 — confidence 가 "어디가 틀렸나"를 잘 못 가리킴(`feedback_vlm_confidence_abstain_limit` 재확인). 클래스 기반 > conf 기반.
- **random 대비 +4.5%p.** 같은 23% 예산을 무작위로 쓰면 36% 만 회수. 표적이 무작위를 압도 = "격차가 특정 클래스에 집중"의 증거.
- **Gemini 전이 청사진**: production 에서 Flash(base) → "shedding 판정만 Pro 재확인" 캐스케이드가 비용 23% 로 Pro 단독 정확도 근접. key 복구 후 P5/실측에서 검증.

## 4-3. P2 입력표현 결과 (2026-06-10) — 가설 기각, 버킷 재분류

| | recovered | broken | 순효과 |
|---|---|---|---|
| 모션키프레임 N=20 | 1/11 (shedding만) | 0/9 | +0.5%p (기준 미달) |

**가설("결정적순간이 시간샘플에서 샜다 → 모션키프레임이 잡는다")은 기각.** 메커니즘:
- 모션에너지(프레임차분 256px)는 **gross 몸이동**을 짚지 **혀 날름/먹이접촉 같은 저모션 미세동작**을 못 짚음(drinking motion PoC 음성과 같은 이유). → eating_paste 의 lick 순간 대신 몸 재배치 프레임을 골라 오히려 역효과.
- close-up 대조군 9/9 유지 vs 원거리 오답셋 거의 전멸 = **게이팅 변수는 시간샘플 밀도가 아니라 카메라 거리/접촉 크기(공간 해상도)**.
- **버킷 재분류**: ceiling 의 eating_prey/paste →moving 오답은 "고칠 여지(입력표현)"가 아니라 **drinking/defecating 과 같은 시각정보 한계 버킷**(덜 심할 뿐). 입력표현 레버(몽타주→개별프레임 +21%p)는 **이미 소진**됨 — 그 다음 단은 프레임트릭이 아니라 영상네이티브/고해상/HITL.
- ⚠️ 소표본(11건) + 단일 셀렉터(모션에너지)만 검증. "프레임 수 N↑ 단독" arm 은 미검증(공간한계라 효과 낮을 것으로 추정하나 미실측).

## 5. 학습 노트

- **자기 가설 기각도 결과다 (이번 P2)**: "입력표현이 1순위 레버"라는 내 진단이 데이터로 반박됨(recovered 1/11). 좋은 실험은 가설을 죽일 수 있어야 함 — 오버셀 금지, +0.5%p 를 "약간 효과"로 포장하지 않고 기준 미달=기각으로 명시.
- **모션에너지의 맹점**: 프레임차분은 큰 움직임에 반응. 미세접촉(혀)은 저모션이라 모션셀렉터가 오히려 놓침. "결정적 순간"이 항상 고모션은 아니다 — 먹이타격(고모션)은 잡아도 핥기(저모션)는 못 잡음.
- **McNemar test**: paired 정확도 비교의 표준. discordant 쌍(b=A만맞, c=B만맞)만 봄 — 둘 다 맞거나 둘 다 틀린 건 무정보. χ²=(|b−c|−1)²/(b+c), >3.84 면 p<0.05. JS 비유: A/B 테스트에서 "둘 다 같은 결과 낸 유저"는 버리고 "갈린 유저"만 세는 것. Fable vs Sonnet 은 21-vs-7 로 유의, Fable vs Opus 는 11-vs-3 으로 직전(3.50<3.84).
- **정밀도-재현율 트레이드오프 실측**: Sonnet shedding recall↑(93%)인데 전체 정확도↓ — recall 만 보면 "Sonnet 이 허물 더 잘 잡네" 오판. moving 을 깎아먹은 false positive 라 net 손해. 클래스별 recall 표만 보지 말고 혼동 방향을 봐야 함.

## 6. 참고

- Fable 5 run 산출물: `experiments/eval-frames-full/fable5_blind.jsonl` + `scripts/_score_frames_fable5.py`
- 실행 레시피: `/blind-eval` 스킬 (frames 모드)
- 메모리: `feedback_frames_beat_montage` (입력표현 +21%p) · `feedback_vlm_error_set_ablation_pattern` · `feedback_vlm_confidence_abstain_limit` · `project_defecating_drinking_strategy` · `feedback_vlm_rule_overcorrection` (프롬프트 마이크로튜닝 6연패)
- 연관 스펙: `feature-rba-evidence-based-feeding-drinking.md` (P6 evidence 본설계) · `experiment-claude-subscription-rba.md` (트랙 원칙)
