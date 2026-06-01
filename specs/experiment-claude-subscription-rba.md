# Experiment — Claude 구독모델 기반 RBA 검증 트랙

> Gemini API 종량제 대신 **Max 구독**(Claude Code / Cowork / claude.ai)을 analyzer 로 써서, [`feature-rba-evidence-based-feeding-drinking.md`](feature-rba-evidence-based-feeding-drinking.md) 의 **증거 기반 접근법이 맞는지를 증분비용 $0 로 빠르게 검증**하는 트랙. 새 정확도 전략이 아니라 **compute/billing 모델을 바꾼 저비용 검증 트랙**이다.

**상태:** 🚧 제안 / 아이디어 설계 (2026-06-02 — 착수 전, 실행 X)
**작성:** 2026-06-02
**연관 SOT:** [`docs/AI-VIDEO-ANALYSIS-STRATEGY.md`](../docs/AI-VIDEO-ANALYSIS-STRATEGY.md) §10.1·§10.6, [`experiment-event-segment-vlm.md`](experiment-event-segment-vlm.md) (Track B/SegmentVLM 전략), [`feature-rba-evidence-based-feeding-drinking.md`](feature-rba-evidence-based-feeding-drinking.md) (검증 대상)

> 🔄 **실행은 petcam-rba-worker 영역.** 이 스펙은 petcam-lab 에서 설계하지만, 실제 Claude CLI/Code batch 실행은 [CLAUDE.md 자매 레포 분리 룰](../CLAUDE.md) 상 [`../petcam-rba-worker`](../../petcam-rba-worker) 가 담당한다. 실행 단계로 넘어가면 이 스펙도 그쪽에 미러하고 sync 표시할 것.

---

## 1. 목적

### 1.1 게임의 핵심 (전제)

Claude(및 모든 LLM)는 mp4 를 직접 못 먹는다. 그래서 **"영상 → 프레임/이미지"** 변환은 항상 모델 바깥에서 일어나야 한다. 마침 Max 구독에 포함된 Claude Code/Cowork 는 그 자르는 작업(ffmpeg 실행)을 직접 할 수 있다. 즉 Gemini API 없이도, **구독 한도 안에서 영상 이해 파이프라인을 돌릴 수 있다.**

### 1.2 왜 이 트랙인가

[`feature-rba-evidence-based-feeding-drinking.md`](feature-rba-evidence-based-feeding-drinking.md) 는 "단정 대신 증거(ROI 체류 + before/after + 표면 핥기)"로 섭식/음수를 판단하자는 **방법론 제안**이다. 이걸 production 급으로 다 짓기 전에, **돈 안 쓰고 먼저 맞는 방향인지 확인**하고 싶다.

전략 문서가 이 트랙의 자리를 이미 만들어 뒀다.

- §10.1: **"진짜 비용 중심은 AI inference"** — analyzer 과금이 단위경제를 결정한다. → 증분비용 $0 analyzer 는 검증용으로 매우 싸다.
- §10.6 Phase 4: 맥미니/자체서버에서 **"local VLM, Claude/Codex CLI, fine-tuned model 비교 실험"**을 production SLA 가 아닌 **side worker**로 규정. → 이 구독 트랙은 그 칸에 정확히 들어간다.

### 1.3 한 줄 정의

> **Claude 구독모델 검증 트랙** = SegmentVLM 전처리(영상→event/contact sheet)는 그대로 두고, analyzer 의 **과금만 Gemini API → Max 구독**으로 바꿔서, 증거 기반 판단법의 방향성을 sample 규모로 $0 검증하는 트랙.

### 1.4 맥미니·Gemini 키와 독립 (2026-06-02 확인)

이 트랙은 아래 둘과 무관하게 진행 가능하다:

- **맥미니 local VLM 학습** (Ollama/gemma3/qwen2.5vl) — 난항 중이며 사용자가 맥미니에서 직접 관리. 이 트랙은 클라우드 Claude(구독)라 로컬 모델과 별개. 맥미니가 안 풀려도 안 막힌다.
- **Gemini API 키** — Claude 로 판정하므로 키 유출/교체와 무관. **키 없이도 검증 가능.**

즉 검증 입력(샘플 + contact sheet)이 이미 `experiments/segment-vlm/` 에 있고 판정기는 Claude Code 자신이므로, 맥미니·키 없이 petcam-lab 에서 바로 dry-run 가능하다 (실행 위치 정식화는 자매레포 룰 확인 후 — 상단 🔄).

---

## 2. 핵심 프레이밍 — 진짜 새로운 건 딱 하나

사용자가 가져온 5개 아이디어 중 절반은 **이미 기존 Track B 스펙에 설계/실행되어 있다.** 그대로 새로 만들면 중복이므로, 중복은 참조로 처리하고 새로운 축만 남긴다.

| 아이디어 | 내용 | 기존 스펙 관계 | 새로움 |
|---|---|---|---|
| 1. 수동 추출 + 채팅 업로드 | ffmpeg 프레임 → claude.ai 드래그(≤20장) | — (가장 단순한 manual entry) | **구독 과금** 각도만 새로움 |
| 2. 컨택트 시트 트릭 | 5×5 격자 + drawtext 타임스탬프 | [`experiment-event-segment-vlm.md`](experiment-event-segment-vlm.md) §4.7~4.8 ClaudeFrameAnalyzer 가 **이미 contact sheet 입력으로 9건 blind batch 실행** (4/9 recovered) | 거의 없음 (재탕) |
| 3. Claude Code/Cowork 오케스트레이터 | Claude Code 가 ffmpeg 추출 + 분석 + JSON 까지 한 도구로 | 기존 Mac mini 스펙은 Claude CLI 를 **analyzer backend** 로만 봄. **전처리까지 하는 오케스트레이터**로는 미설계 | **새로움 (핵심)** |
| 4. 모션 기반 키프레임 | scene 필터/OpenCV diff 로 활동 구간만 추출 | [`experiment-event-segment-vlm.md`](experiment-event-segment-vlm.md) §4.3 `changed_ratio` event segmentation 그 자체 | 없음 (이미 설계됨) |
| 5. 하이브리드 2단계 | CV 모션+ROI → 결정적 순간만 Claude | evidence 스펙(ROI 체류+before/after) + §1.2 selective fallback 의 합 | 없음 (이미 설계됨) |

**결론:** 진짜 새로운 축은 **"analyzer 의 과금 모델을 Max 구독으로 바꾼다"** 하나다. 아이디어 1·3 이 그걸 구현하는 두 방식(수동 / Claude Code 오케스트레이션)이고, 2·4·5 는 기존 전처리 설계를 재확인한 것이다.

---

## 3. 5개 아이디어를 "AI 부담" 축으로 비교

> 사용자 명시: **이 5개는 발전 단계가 아니라 별개 전술이다.** 아래 표는 우열이 아니라, "AI 가 얼마나 일하나(오케스트레이션 부담)" 축으로 줄세운 비교다. 이 축이 §4 타깃 아키텍처를 가리킨다.

| 전술 | 전처리 주체 | AI(구독) 역할 | 증분비용 | 재현성 | 한 줄 평 |
|---|---|---|---|---|---|
| 1. 수동+채팅 | 사람 (ffmpeg 수동) | 판단만 | $0 (Max 한도) | 낮음 (수동·temp 비고정) | "되는지" 최단 확인용. 20장 제한 |
| 2. 컨택트 시트 | 사람/스크립트 | 판단만 | $0 | 낮음 | 20장에 25프레임 욱여넣기. 미세신호 해상도↓ |
| 3. Claude Code 오케스트레이터 | **AI 가 ffmpeg 직접** | 전처리+판단 | $0 (Max 한도) | 중간 (추출 파라미터 AI 즉흥) | 우아하지만 **AI 가 오케스트레이션 토큰/시간 다 씀** |
| 4. 모션 키프레임 | 스크립트 (CV) | (분석 단계에서 판단) | $0~ | 높음 (결정적 CV) | 긴 영상 압축. §4.3 와 동일 |
| 5. 하이브리드 2단계 | 스크립트 (CV+ROI) | 결정적 순간만 판단 | $0~ | 높음 | 가장 싸고 정확. evidence 스펙과 합치됨 |

핵심 관찰: **전처리를 AI 밖(스크립트/백엔드)으로 뺄수록 AI 부담↓·재현성↑.** 전술 3(AI 가 다 함)은 우아하지만 비효율 끝, 전술 5(스크립트가 다 준비, AI 는 판단만)가 효율 끝. → 다음 섹션.

---

## 4. 타깃 아키텍처 (사용자 명시 방향)

사용자 의도: **"나중엔 백엔드 서비스가 ffmpeg까지 돌려서 준비된 입력만 AI 한테 갖다준다. 그러면 AI 역할·토큰·시간이 절약된다."**

```text
[현재 가능] 전술 1·3: 사람/Claude Code 가 ffmpeg 돌림 → AI 가 오케스트레이션까지 부담
        ↓ (전처리를 밖으로)
[타깃]     백엔드 서비스가 ffmpeg + event 분할 + contact sheet 까지 완성
        → 준비된 이미지/메타데이터만 AI(구독)에 전달
        → AI 는 "증거 판단"만 수행
```

### 4.1 절약되는 것 / 안 되는 것 (과대평가 금지)

- **절약 O — 오케스트레이션 비용**: ffmpeg 명령 작성→실행→출력 파싱→파라미터 결정→재시도하는 tool-call 왕복 토큰·latency. 이게 절약의 실체.
- **절약 X — 이미지 토큰**: contact sheet 이미지 자체의 입력 토큰은 누가 ffmpeg 를 돌리든 동일하다. "준비 작업" 토큰이 줄지 "보는" 토큰이 주는 게 아니다.
- **보너스 — 재현성**: 백엔드가 결정론적으로 자르면 같은 입력이 보장돼 §8 재현성 함정이 일부 해소된다.

### 4.2 중요한 수렴

이 타깃 아키텍처(백엔드 전처리 → AI 판단만)는 **기존 SegmentVLM 파이프라인 구조와 동일하다.** Track B 도 "Python 이 event/contact sheet 생성 → analyzer 는 분석만"이다 ([`experiment-event-segment-vlm.md`](experiment-event-segment-vlm.md) §4.6).

> 따라서 이 트랙이 production 에 남길 진짜 변경은 **"analyzer backend 를 Gemini API 대신 Claude 구독으로 둘 수 있나"** 한 줄로 좁혀진다. 전처리·event·ROI·contact sheet 는 전부 기존 설계 재사용.

---

## 5. 스코프

### In (이번 트랙에서 한다)

- 전술 1(수동 채팅) 또는 3(Claude Code 오케스트레이터)로 **sample 클립 소수(5~15건)**에 증거 기반 판단을 돌려본다.
- 검증 대상을 **방법론(증거 프레이밍)**으로 한정한다 (§6).
- 같은 입력 **N회 반복 일관성**을 측정한다 (재현성 함정 대응).
- 기존 `scripts/claude_segmentvlm_batch.py` 가 보고한 비용($1.78/9건)이 **Max 구독으로 돈 건지 API 로 돈 건지** 규명한다 (§8.3).
- 결과를 `experiments/claude-subscription-rba/` artifact 로만 남긴다.
- 입력은 가능하면 **기존 Track B 전처리 산출물 재사용** (`experiments/segment-vlm/sample-*/`).

### Out (이번 트랙에서 **안 한다**)

- production analyzer 를 Gemini → Claude 구독으로 교체. (이건 검증 결과를 보고 별도 결정)
- 개인 Max 구독을 **production 서빙 경로**로 쓰기. 구독 한도는 Claude Code·채팅·Cowork 가 **같은 통을 공유**하고, 1만 명 규모 실시간 분석을 personal plan 으로 감당하는 구조가 아니다 (전략 §10.6: side worker O, SLA 경로 X).
- evidence 스펙([`feature-rba-evidence-based-feeding-drinking.md`](feature-rba-evidence-based-feeding-drinking.md))의 DB/API/UI 구현. 그건 그 스펙 소관.
- v3.5 prompt·Track A baseline 수정.
- 새 전처리 파이프라인 작성. event/contact sheet 는 기존 SegmentVLM 산출물 재사용.
- `behavior_logs(source='vlm')` 에 구독 트랙 결과 INSERT.

> **스코프 변경은 합의 후에만.** 경계 흔들리면 이 섹션 수정 + 사유 기록.

---

## 6. 검증 설계 — 함정 두 개를 먼저 막는다

이 트랙의 진짜 산출물은 "돌려봤다"가 아니라 **"무엇을 검증했고 무엇은 검증 안 됐는지 정직하게 구분한 리포트"**다.

### 6.1 모델 불일치 함정

Claude(구독)로 잘 나와도 production 은 Gemini 다. 그럼 검증되는 건:

- ✅ **방법론**: "증거 프레이밍(ROI 체류/before-after/표면 핥기)이 top-1 단정보다 나은 신호를 주나" — 모델 무관하게 어느 정도 일반화.
- ❌ **모델 일반화**: "Gemini 로도 같은 결과가 나오나" — **이 트랙으로는 검증 안 됨.** 별도 항목으로 분리.

부산물 발견 가능성: Claude 가 evidence task 에서 Gemini 보다 확실히 좋으면, 그 자체가 **"evidence analyzer backend 는 Gemini 말고 Claude(API/자체서버)가 맞을 수 있다"**는 신호다. → analyzer 선택 의사결정에 입력.

### 6.2 재현성 함정

claude.ai 채팅/Claude Code 는 `temperature=0` 제어가 안 된다 ([`donts/vlm.md`](../.claude/rules/donts/vlm.md) 룰 6). 같은 contact sheet 를 여러 번 넣으면 라벨이 흔들릴 수 있다.

- 대응: 각 sample 을 **최소 3회 반복** 호출하고 **라벨 일관성(majority/흔들림 횟수)**을 기록한다.
- 흔들리면 그 클립은 evidence-level 을 `candidate` 이하로 낮춘다 (evidence 스펙 §4.1 철학과 일치).

### 6.3 측정 지표

기존 Track B 비교 지표(§4.11)를 그대로 쓰되, 구독 트랙 전용 항목 추가:

- evidence-assisted 판단 vs Track A top-1 정확도 (feeding-merged 기준)
- P0 recall (feeding/defecating/shedding/eating_prey)
- **반복 일관성** (동일 입력 N회 라벨 흔들림률) ← 신규
- **증분비용 정체** (구독 한도 차감 vs API 청구) ← 신규
- 사람이 보는 evidence(crop/ROI/시간)가 납득 가능한가 (설명 가능성)

---

## 7. 완료 조건

체크리스트가 곧 진행 상태.

- [ ] 이 스펙 사용자 확인 — In/Out·검증 대상 한정 동의
- [ ] **(now, 키·맥미니 불요) dry-run** — 기존 `experiments/segment-vlm/sample-d95e9eaa`(벽 핥기) contact sheet 를 Claude Code 가 읽고, evidence 스펙 §4.4 행동 모양(sustained lapping vs darting flick) 구분 + 증거 레벨 산출이 되는지 확인. 표면 음수 파이프라인의 절반(접촉/모양) 선검증.
- [ ] §8.3 비용 정체 규명 — `scripts/claude_segmentvlm_batch.py` 가 Max 구독 차감인지 API 청구인지 1건 실측 확인
- [ ] sample 5~15건 입력 준비 — 가급적 `experiments/segment-vlm/sample-*/` 재사용 (신규 전처리 X)
- [ ] 전술 선택 — 1(수동 채팅) 또는 3(Claude Code 오케스트레이터) 중 1차 검증 방식 결정
- [ ] 증거 기반 판단 실행 — evidence 스펙의 "증거 추출 질문"(§4.3) 프롬프트로 호출
- [ ] **반복 일관성 측정** — 동일 입력 ≥3회, 라벨 흔들림률 기록
- [ ] `experiments/claude-subscription-rba/report.md` 작성 — §6.1 방법론/모델 일반화 분리, §6.3 지표 포함
- [ ] 채택/폐기/보류 판단 기록 — "evidence 풀 빌드 정당화 / 폐기 / 추가 검증" 중 결론

---

## 8. 설계 메모

### 8.1 선택한 방법

- **전처리 재사용**: 새 ffmpeg 파이프라인을 짜지 않는다. SegmentVLM 산출물(contact sheet/event mp4)을 그대로 Claude 구독에 넣는다. 빨리 검증하는 게 목적.
- **전술 1 먼저 권장**: Claude Code 오케스트레이터(전술 3)는 우아하지만 오케스트레이션 토큰을 다 쓴다. 검증 단계에선 "수동/스크립트 전처리 → 판단만" 이 노이즈가 적다. 전술 3 의 가치는 "AI 가 전처리까지 가능함을 보이는 것"이지 효율이 아니다.

### 8.2 고려했던 대안 (왜 안 골랐나)

- **새 standalone 스펙 대신 evidence 스펙에 섹션**: 검증 트랙은 별개 수명주기(채택/폐기)를 가지므로 분리가 맞다. evidence 스펙은 "production 구현 계획", 이 스펙은 "그 방향이 맞는지 싸게 보는 실험".
- **mac-mini 스펙 확장**: mac-mini 스펙은 "맥미니라는 하드웨어"가 주제. 이 트랙은 "구독이라는 과금 모델"이 주제라 축이 다름. 단 실행은 그 레포에서.

### 8.3 미해결 질문 / 리스크

- **$1.78 의 정체**: 기존 `claude_segmentvlm_batch.py` 가 "$1.78/9건"을 보고했다(mac-mini 스펙 §7). 이게 **Max 구독 차감**이면 아이디어 1·3 은 이미 부분 가동 중이고 이 트랙의 새로움이 더 줄어든다. **API 청구**면 구독 전환이 진짜 절감이다. → **착수 전 1건 실측으로 규명 필수.**
- **구독 한도 공유**: Claude Code·채팅·Cowork 가 같은 통. 다른 작업과 한도를 다툰다. 검증 규모(수십 건)는 OK 지만 batch 가 커지면 일상 작업이 막힐 수 있다.
- **production 서빙 불가**: 개인 구독은 SLA·동시성·약관상 production 다중 사용자 서빙 경로가 아니다. 검증/내부 도구 한정.
- **재현성**: §6.2. temperature 비고정.
- **evidence confabulation**: analyzer 가 그럴듯한 증거 JSON 을 꾸며낼 수 있다 (evidence 스펙 §11, donts/vlm 룰 5). crop/contact sheet artifact 를 반드시 남겨 사람이 대조 가능하게.

### 8.4 기존 구조와의 관계

- **전처리**: [`experiment-event-segment-vlm.md`](experiment-event-segment-vlm.md) §4.3(segmentation)·§4.7~4.8(contact sheet) 재사용.
- **판단 질문**: [`feature-rba-evidence-based-feeding-drinking.md`](feature-rba-evidence-based-feeding-drinking.md) §4.3(증거 추출 프롬프트) 재사용.
- **analyzer 비교**: [`experiment-event-segment-vlm.md`](experiment-event-segment-vlm.md) §4.6 ClaudeFrameAnalyzer 와 같은 normalized schema 반환.

---

## 9. 학습 노트

- **구독모델 vs API 종량제**: API 는 호출당 과금(production 스케일에 정직), 구독은 정액 한도(검증/내부도구에 쌈). JS 로 치면 "per-request 클라우드 함수 vs 월정액 VPS"의 차이. 스케일·SLA 가 필요하면 종량제, 싸게 실험하면 구독.
- **오케스트레이션 토큰 vs 컨텐츠 토큰**: AI 가 도구를 쓰며 소비하는 토큰(명령/파싱/재시도)과, 실제 콘텐츠(이미지/텍스트)를 보는 토큰은 다르다. 전처리를 밖으로 빼면 전자만 준다.
- **검증 대상 한정**: 다른 모델로 검증한 결과는 "방법론"엔 일반화되지만 "그 모델"엔 일반화 안 된다. 검증 리포트는 둘을 항상 분리해야 거짓 자신감을 막는다.
- **컨택트 시트(contact sheet)**: 여러 시점 프레임을 한 장 격자로 묶어 native video input 없는 모델에 시간 흐름을 압축 전달하는 타협안. 트레이드오프는 프레임당 해상도↓ → 게코 미세신호(혀/발색) 손실.

---

## 10. 참고

- [`feature-rba-evidence-based-feeding-drinking.md`](feature-rba-evidence-based-feeding-drinking.md) — **검증 대상** (증거 기반 섭식/음수 판단법)
- [`experiment-event-segment-vlm.md`](experiment-event-segment-vlm.md) — Track B/SegmentVLM 전처리·analyzer 전략 (재사용 소스)
- [`experiment-mac-mini-segmentvlm-worker.md`](experiment-mac-mini-segmentvlm-worker.md) — Claude CLI batch 실행 환경 (실행 레포: petcam-rba-worker)
- [`docs/AI-VIDEO-ANALYSIS-STRATEGY.md`](../docs/AI-VIDEO-ANALYSIS-STRATEGY.md) §10.1(AI inference 비용)·§10.6(Phase 4 side worker)
- [`.claude/rules/donts/vlm.md`](../.claude/rules/donts/vlm.md) 룰 5(evidence-forcing)·룰 6(temperature 결정론)
