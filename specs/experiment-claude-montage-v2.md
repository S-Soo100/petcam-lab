# Claude 구독 트랙 피벗 — 몽타주 v2 + claude-video 레시피 입력표현 연구

> Gemini API 퇴역 후, RBA 품질 연구를 Claude Code 구독(추가비용 0)으로 계속하기 위한
> 입력표현(몽타주 v2 / cv-frames) 연구 계획서. "프레임 수 × 셀 해상도 × 타임스탬프" 공간에서
> frames-10 정확도를 더 싼 표현으로 회수하는 게 핵심.
> **모델 체계: production 목표 = Sonnet 4.6 (채택 게이트), 검증 = Opus 4.8 (강건성), Fable 5 = 게이트 제외 (참고선).**

**상태:** 🚧 진행 중 (계획 승인 대기)
**작성:** 2026-06-12
**연관 SOT:** `docs/AI-VIDEO-ANALYSIS-STRATEGY.md` (RBA 전략 — 본 피벗 반영 갱신 필요)

## 0. 방향 전환 컨텍스트 (사용자 결정 2026-06-12)

| 결정 | 내용 |
|---|---|
| **Gemini API 포기** | 비용 등 이유로 연구·production 모두 호출 0. 진행 중이던 4버전 회귀는 63%에서 중단, 클로징 기록 `experiments/gemini-final-partial/` 박제 |
| **연구 엔진 = Claude 구독** | 검증/연구는 Claude Code 서브에이전트 blind 평가로 (API 비용 0, 한도만 관리) |
| **몽타주 재도전** | 목적 3개 동시: ① 비용/처리량 ② 정확도 회복 가설(셀 해상도) ③ production 전송용 표준 입력표현 |
| **claude-video** | 플러그인 설치(단발/YouTube용) + 추출 레시피를 우리 스크립트로 재현해 정량 트랙 |
| **production 정리** | fly `petcam-vlm-worker` 셧다운 (사용자 flyctl). production 재설계는 연구 수렴 후 별도 spec |
| **모델 체계 (06-12 계획 수정)** | **production 목표 모델 = Sonnet 4.6** — 채택 게이트는 Sonnet 기준. **Opus 4.8 = secondary 검증**(모델 특이성/강건성 확인). **Fable 5 = 검증 단계에서 제외** — 85.1%는 historical/reference로만, 게이트에 사용 금지 |
| **클래스 우선순위 (06-12 추가)** | **defecating = 연구 비목표 격하.** 이유 ① 판정 성공률 낮음 + 자료 수집 어려움 ② 똥이 남아 **육안으로 확인 가능**(행동 감지 불필요한 유일 클래스) ③ ~3일 1회 빈도라 효과 미미 ④ 핵심은 **moving(잘 노는지)·shedding·drinking**. 평가셋 202·클래스 taxonomy는 **유지**(cherry-pick 금지 + paired 대칭이라 게이트 무결성 영향 0) — 타겟 실험·최적화만 제외 |

**Gemini 클로징 기록이 주는 마지막 교훈** (145건 paired, `experiments/gemini-final-partial/README.md`):
표적룰은 모델 특이적 (IR 가드: Sonnet +6.9%p ↔ Gemini −2.3%p) / OOD 룰은 모델 무관 견고 (16/16).
→ 이후 모든 프롬프트 룰은 **모델-프롬프트 쌍 단위로** 검증한다.

## 1. 목적

- **연구 처리량 확보**: frames-10 full-202 1회 ≈ 3.3M 서브에이전트 토큰. 몽타주로 클립당
  이미지 토큰을 수 배 줄여 같은 구독 한도에서 실험 횟수를 늘린다.
- **몽타주 명예회복 가설 검증**: 0608 contact sheet(**5×6 main**, 153건 raw 72.5%)가 진 원인은
  격자가 아니라 **셀당 ~72px 해상도**라는 가설 (P2 "게이팅=공간해상도" 발견 기반). 고해상
  몽타주가 frames-10에 근접하는지 측정.
- **production 전송용 표준**: 어떤 모델(local VLM 포함)이 와도 적용 가능한 "권장 입력표현
  스펙"을 산출물로 남긴다 (해상도/프레임수/타임스탬프 유무 + 근거 수치). **1차 production
  목표 모델은 Sonnet 4.6** — 채택 판단은 Sonnet 기준, Opus 4.8은 그 결과가 모델 특이적이지
  않은지 확인하는 검증용.
- 학습 목표: 이미지 토큰 경제(Claude vision 토큰 ≈ w×h/750), 입력표현-정확도 trade-off 설계.

## 2. 스코프

### In (이번 스펙에서 한다)
- **M0** 몽타주 v2 레이아웃 최적점 탐색 — 6 레이아웃 × ts on/off = **12변형 전부** (Sonnet),
  stratified 20건 고정 샘플 (§4-2). Opus는 Sonnet 상위 2~3개 후보만
- **M1** 미세접촉 검증 — **M1-core (current micro55) = 채택 기준** + M1-legacy (구 63건, stress 기록용)
- **M2** full-202 정량 + 토큰 실측 → 채택 판정 (**같은 모델끼리만** 비교: Sonnet↔Sonnet, Opus↔Opus)
- **V1** claude-video 레시피(cv-frames) — **drinking recall 후보 확인 + 과탐 점검** (positive 16 +
  negative control ~16, 채택 실험 아님)
- **M3** 캐스케이드 시뮬 (몽타주 → frames 에스컬레이션, 신규 인퍼런스 0 — M2/기존 frames202 재활용)
- claude-video 플러그인 설치 (SKILL.md 검토 후) — 단발 검사/YouTube 레퍼런스 도구로
- Gemini 퇴역 체크리스트 (§8)

### Out (이번 스펙에서 **안 한다**)
- production 파이프라인 재설계/재가동 (연구 수렴 후 별도 spec — local VLM vs 기타는 그때)
- **defecating 타겟 실험/최적화** — §0 클래스 우선순위 결정 (V1에서도 제외). 클래스 taxonomy
  폐기 여부는 별도 spec (hiding 전례 — prompt/라벨링 UI/DB 연쇄). 미래에 배변 감지가 필요해지면
  행동 분류 대신 **잔류물 정적 감지(before-after 스냅샷)** 접근 권장 (똥은 남는다)
- rba-worker(local VLM)에 입력표현 이식 (산출물 spec만 넘김, 실행은 저쪽 레포)
- 프롬프트 룰 추가 변경 (v3.6.1 고정 — 입력표현만 변수로 격리. v3.6.2 IR 가드는 Sonnet 전용 자산으로 보류)
- 영상 네이티브 분석 (Claude는 영상 입력 불가 — 이 한계는 표현 연구로 우회하는 게 본 스펙)
- Vertex AI 전환 검토 (Gemini 포기로 무의미 — 폐기)

> **스코프 변경은 합의 후에만.** 작업 중 In/Out 경계가 흔들리면 이 섹션 수정 + 사유 기록.

## 3. 완료 조건

- [ ] **공통 — 평가/검증 프로세스 준수 (§4-3a)**: 모든 phase는 pre-reg → blind → deterministic
      scorer → LLM audit → discordant review → **decision label(adopt/hold/reject)** 순서를 따름.
      phase별 pre-reg 블록(sample list·모델·변형·기준)이 **실행 전에** 본 스펙에 추가돼 있어야 run 유효
- [ ] **M0**: `scripts/repr_montage_v2.py`로 §4-2 후보 생성 — 6 레이아웃(12f/16f/18f/20f × 1~2장)
      × ts on/off = **총 12변형, 전부 실행**. blind 대상 = **stratified 20건 고정 샘플**(§4-2 구성
      정책 — 착수 직전 clip_id 고정, 이후 변형 간 비교에서 불변). **Sonnet: 12변형 전부 / Opus:
      Sonnet 결과 상위 2~3개 후보만** → "프레임수 × 장수 × 셀 해상도 × ts → 모델별 frames 대비 Δ"
      표로 기록
- [ ] **M1-core (채택 기준)**: M0 최적 후보를 **current micro55** (drinking 16 + eating_prey 22 +
      eating_paste 17, §4-2a)에 blind — **Sonnet(primary): frames 74.5% 대비 −3%p 이내 = 채택 게이트**.
      Opus(secondary): frames 70.9% 대비 −3%p 이내 = 강건성 확인 (미충족 시 채택 불가가 아니라
      "모델 특이적 이득" 플래그 + 원인 기록). paired recovered/broken 분석 필수 (단순 Δ 단독 판정 금지)
- [ ] **M1-legacy (기록 전용)**: 같은 run에서 구 63건 전체(= micro55 + 재분류 8건) 점수를 **별도
      표로만 기록** — 과거 실험과의 연결용 stress set. **채택 판정에 사용 금지**
- [ ] **M2**: full-202 blind를 **같은 모델끼리만** 비교 — **Sonnet montage vs Sonnet frames 78.2%**
      (채택 게이트: −3%p 이내) / Opus montage vs Opus frames 81.2% (강건성 확인). AND 클립당 토큰
      실측 절감 (단일장 목표 ≥2×; 2장 분할형은 절감폭이 작으므로 정확도 이득과 묶어 trade-off 곡선으로
      판단) → 충족 시 "저비용 표준 입력" 채택, 미달 시 사유 분석 후 보류 기록.
      frames 쪽은 P1 jsonl 재사용 (재실행 0). Fable 5는 게이트 비교에 사용 금지
- [ ] **V1 (drinking recall 후보 확인 + 과탐 점검 — 채택 실험 아님)**: cv-frames vs frames-10
      paired (모델 정책 동일 — Sonnet 필수, Opus 선택)
      - **V1-positive**: drinking 16건 — frames-10 대비 recovered/broken 측정
      - **V1-negative**: drinking 과탐 위험 negative control ~16건 — 물 없는 곳 혀 탐색
        (moving/chemoreception 경계), eating_paste↔drinking 혼동 후보, 혀/입 움직임 있는 일반
        moving — cv-frames가 **drinking false positive를 늘리는지** 측정
      - 판정: positive에서 회복이 있어도 **negative에서 drinking FP 증가 시 불채택**. 통과해도
        결론은 "cv-frames 후보 유지"일 뿐 — **production 채택은 M2/M3급 또는 별도 full 검증 후
        판단**. 기대치는 낮게(시간축 가설2 음성 + "프레임 밀도↑ 한계효용" 전례) — 저비용 확인 목적.
        defecating은 §0 비목표라 제외
- [ ] **M3**: 캐스케이드 시뮬 (Sonnet 기준 — 몽타주 전건 + 저신뢰/미세접촉만 frames 재판정) —
      토큰 X% 비용으로 frames 정확도 Y% 회수 곡선 산출
- [ ] **산출물**: `docs/INPUT-REPR-SPEC.md` — 권장 입력표현 + 근거 수치 + production 전송 가이드
- [ ] **운영**: §8 Gemini 퇴역 체크리스트 전부 완료
- [ ] `specs/README.md` 목록 갱신 + `next-session.md` 피벗 반영

## 4. 설계 메모

### 4-1. 아키텍처 (연구 랩 구조)

```
storage/dataset-203 (202건 video(.mp4/.mov 혼재) + manifest.csv = GT 로컬 SOT; DB behavior_logs = 원천 SOT)
        │   ⚠️ 파일 탐색은 `*.mp4` glob 금지 — manifest.csv 의 filename 컬럼 기준 (.mov 누락 방지)
        │
        ├─ 입력표현 빌더 (가설별 1스크립트, 산출물은 experiments/ 하위 중립 폴더)
        │    ├─ frames-10  : 기존 (클립당 풀해상도 10장) — 기준선, 재생성 불필요
        │    │     (full-202 blind jsonl도 P1에서 모델별로 이미 존재 — frames 쪽 재실행 0)
        │    ├─ montage-v2 : scripts/repr_montage_v2.py (신규)
        │    │     후보 = §4-2 (프레임 수 ≥10 고정: 12f/16f/18f/20f × 1~2장) @ 캔버스 1536px
        │    │     셀 타임스탬프 오버레이 on/off, 프레임 선택 = 균등 (모션 기반은 P2서 기각됨)
        │    └─ cv-frames  : scripts/repr_cv_frames.py (신규, claude-video 레시피 재현)
        │          duration-adaptive — ffprobe로 실제 duration_sec 읽고 전체 구간 균등 샘플,
        │          max 24장 cap (12s/60s 고정 가정 금지), 프레임당 "t=MM:SS" 라벨,
        │          해상도 768px (claude-video 기본값 모사), whisper 생략 (펫캠 무음성)
        │
        ├─ blind 평가 러너 (기존 프로토콜 그대로)
        │    중립 폴더명 sample-NN + meta.json(GT 은닉) + seed 셔플 + 배치 8건/에이전트
        │    모델: Sonnet 4.6 (primary — production 목표·채택 게이트) / Opus 4.8 (secondary — 강건성 검증)
        │           Fable 5 = 게이트 제외, historical 참고선만
        │    프롬프트: v3.6.1 고정 (전 트랙 동일 — 입력표현만 변수)
        │
        └─ 채점/비교: scripts/_score_repr.py — frames-10 결과와 clip 단위 paired diff
              (recovered / broken / both-wrong) — 집계 Δ 단독 판정 금지 (few-shot 교훈)
```

### 4-2. 핵심 가설과 트레이드오프 — M0 설계

**M0 핵심 질문:** "프레임 수 10개 이상을 유지하면서, 몽타주 **장수 / grid / 셀 해상도 /
timestamp 유무**를 바꿨을 때 Sonnet·Opus가 각자의 frames 기준선을 얼마나 따라잡는가?"

- 프레임 수 **≥10 고정축**인 이유: 기존 실험에서 효과가 있던 구간이 10~20프레임. 프레임 수와
  셀 해상도가 동시에 흔들리면 (구 2×2/3×3/4×4 스윕 = 4/9/16프레임) 원인 귀속이 안 됨 —
  프레임 수를 10+ 로 묶고 "어떻게 배치하나"만 변수로.
- 목적은 단정적 "셀 해상도 하한 식별"이 아니라 **몽타주 레이아웃 최적점 탐색** — 정확도와
  토큰의 trade-off 곡선에서 모델별 최적 후보를 고르는 것.

**M0 후보 (모두 캔버스 1536px, 16:9 프레임 균등 샘플):**

| 후보 | 프레임수 | 구성 | 셀 해상도(근사) | 클립당 이미지 토큰(추정) | 노림수 |
|---|---|---|---|---|---|
| 12f-1장 | 12 | 1장 3열×4행 | ~512×288 | ~3.1k | 최대 절감(~2.5×) + 셀 中 |
| 12f-2장 | 12 | 2장 (2×3)+(2×3) | ~768×432 | ~6.3k | 같은 12f에서 셀만 1.5× — 해상도 단독 효과 격리 |
| 16f-1장 | 16 | 1장 4×4 | ~384×216 | ~3.1k | 밀도 우선 단일장 (contact sheet v1 ~72px와 frames 사이 중간점) |
| 16f-2장 | 16 | 2장 (2×4)+(2×4) | ~683×384 | ~6.3k | 밀도+해상도 동시 |
| 18f-2장 | 18 | 2장 (3×3)+(3×3) | ~512×288 | ~6.3k | 12f-1장과 같은 셀에서 밀도 1.5× |
| 20f-1장 | 20 | 1장 4열×5행 (20f-2장 분할형은 **M0 제외** — M0 미달 시 후속 검토) | ~384×216 | ~3.1k | 최대 밀도 단일장 |
| + ts on/off | — | 셀 우상단 `t=MM:SS` 오버레이 | — | — | 타임스탬프 기여 분리 측정 |

> **세로 영상 처리 (2026-06-12 빌더 구현 중 확정):** 표의 셀 해상도는 16:9 가로 기준.
> 평가셋에는 세로(9:16) 폰 영상이 섞여 있어, 16:9 고정 셀이면 셀의 ~70%가 검정 패딩이 됨
> (실측 확인 — 몽타주가 정보 한계가 아니라 레이아웃 낭비로 지는 실험 오염). →
> **세로 영상은 격자 회전(열↔행 스왑) + 셀 비율 = 영상 비율** (패딩 0, 양변 ≤1568 유지).
> 프레임 수·장수 변수는 불변이라 비교축 훼손 없음.

> **변형 수 확정: 6 레이아웃 × ts on/off = 총 12변형 — M0에서 전부 실행 (Sonnet).**
> Opus(secondary)는 Sonnet 결과 상위 2~3개 후보만 확인 — 전 변형 측정은 secondary 역할에 과소비.

**비교축 3개:**
1. **단일장 압축** (12f/16f/20f-1장): 토큰 최소(~2.5× 절감) — 셀 384~512px가 미세접촉에 충분한가
2. **다장 분할** (12f/16f/18f-2장): 셀 683~768px로 해상도 회수 — 대신 절감폭 ~1.25×로 축소
3. **동일 프레임 수에서 셀 크기 효과** (12f-1장 512px vs 12f-2장 768px): 해상도의 단독 기여 격리

**M0 20건 샘플 구성 — stratified, 고정 (랜덤 금지):**

M0는 **대표성 있는 빠른 스크리닝**이지 full benchmark가 아니다. 쉬운 moving 위주로 뽑혀
"결과가 좋아 보이는 착시"가 나는 걸 막기 위해, 어려운 케이스와 제품 중요 케이스를 의도적으로
섞는다:

| 구획 | 건수 | 구성 |
|---|---|---|
| current micro55에서 | **12건** | drinking/eating_prey/eating_paste 균형 (~4/4/4) + 가능하면 각 클래스에 frames 정답/오답 혼합 |
| care-priority/일반에서 | **8건** | moving + shedding + drinking↔chemoreception/moving 경계 케이스 + hand_feeding은 **최대 1~2건** (OOD 과대표집 금지) |

- 실제 clip_id 목록은 **M0 착수 직전** `manifest.csv` + 기존 frames blind 결과를 보고 고정한다.
- **한 번 고정한 M0 sample list는 이후 변형 간 비교에서 절대 바꾸지 않는다** (변형 비교의
  유일 변수 = 입력표현).

**참고 좌표 (기존 실측):**

| 표현 | 프레임수 | 프레임당 해상도 | 클립당 이미지 토큰(추정) | 실측 |
|---|---|---|---|---|
| frames-10 (기준) | 10 | 1024×576 | ~7.9k (786×10) | full-202: Sonnet 78.2% / Opus 81.2% (Fable 85.1% 참고) |
| 5×6 contact sheet main (v1, 폐기) | 30 | **~72px** | ~1.4k | **153건 본평가 v3.6.1 raw 72.5%** — 작은 셀로 미세접촉 손실 확인 |
| 6×6 pilot (v1, 폐기) | 36 | ~72px | ~1.4k | shedding/defecating 일부 파일럿 — 반복 흔들림·순간행동 한계 확인 (본셋 72.5%와 별개) |
| cv-frames-v1 (V1 트랙) | ≤24 (duration-adaptive) | 768×432 | ≤~10k | whole-clip 균등 + 타임스탬프 — drinking 단발 핥기(순간 이벤트) 겨냥 |

- 토큰 ≈ w×h/750 (Claude vision). 캔버스 1536×1536 ≈ 3.1k — 격자 크기와 무관하게 캔버스가 결정.
  여백 트리밍 시 약간 더 절감 (실측은 M0에서).
- **리스크**: 단일장 셀(384~512px)은 frames-10(1024px)의 절반 이하 — 미세접촉(혀-표면 접촉)에
  부족할 수 있음 → 그 경우 다장 분할로 해상도를 회수하되 토큰 이득 축소. 양쪽 다 frames에 못
  미치면 "몽타주=triage, frames=정밀" 캐스케이드(M3)로 후퇴.
- **cv-frames 정의 — duration-adaptive (고정 길이 가정 금지)**: 데이터셋엔 60초 클립과 짧은
  업로드/테스트 영상이 혼재하므로 "12s 클립 → 24장 @2fps" 같은 특정 길이 전제를 두지 않는다.
  - **cv-frames-v1 (V1 기본)**: whole-clip adaptive — ffprobe로 실제 `duration_sec`를 읽고
    **전체 duration에 걸쳐 균등 샘플, clip당 max 24장 cap**, 프레임당 `t=MM:SS` 라벨.
    짧은 영상은 가능한 범위에서 24장 이하로만 (중복 프레임 억지로 늘리지 않음). 긴 영상도
    cap 고정 — 2fps 무제한 추출 폭주 금지 (60s × 2fps = 120장 같은 케이스 차단).
  - **cv-frames-windowed (미래 옵션, 현재 비활성)**: deterministic event window(모션 경계 등)가
    생기면 그때만 12s window @2fps variant를 별도 arm으로 추가. 지금은 기본값 아님.
- **cv-frames가 frames-10을 이기면**: 입력표현 천장(P2 "소진" 결론)을 타임스탬프/밀도가 다시
  여는 것 — **drinking**(단발 핥기 = 순간 이벤트, frames 바닥 클래스군)의 남은 비-영상 레버.
  단 시간축 가설2 음성 전례로 기대 낮음 — 저비용 확인만(V1 = recall 후보 확인 + 과탐 점검,
  §3). (defecating은 §0 비목표 — 잔류물이 남는 클래스라 행동 감지 자체의 케어 가치가 낮음)

### 4-2a. 평가 서브셋 정의 — current micro55 vs legacy 63

구 "미세접촉 63건"은 **GT 정정 전에** drinking/eating_prey/eating_paste 하드셋으로 뽑은 것.
GT 정정 이후 현재 manifest 기준으로 그 63건 안에 **moving 5건 + hand_feeding 3건**이 섞여
있어, "미세접촉 63건"이라는 이름은 더 이상 정확하지 않다. 분리 정의:

| 서브셋 | 정의 | 용도 |
|---|---|---|
| **current micro55** | 현재 GT 기준 진짜 미세접촉 = **drinking 16 + eating_prey 22 + eating_paste 17 = 55건** | **M1 채택 기준** |
| legacy 63 | 구 63건 전체 (= micro55 + 재분류 8건) | 과거 실험 연결용 stress set — **기록만, 채택 판정 금지** |

**frames 기준선 (P1 blind jsonl을 current GT로 재채점):**

| 모델 | current micro55 | legacy 63 (참고) | full-202 |
|---|---|---|---|
| **Sonnet 4.6 (primary — production 목표)** | **41/55 = 74.5%** | 47/63 = 74.6% | **78.2%** |
| Opus 4.8 (secondary — 검증) | 39/55 = 70.9% | 46/63 = 73.0% | 81.2% |
| Fable 5 (참고선 — 게이트 제외) | — | — | 85.1% |

> legacy 63 ⊃ micro55 이므로 **M1은 63건 1회 run으로 두 표를 동시에 얻는다** (micro55 부분채점
> + 63 전체 기록 — 추가 인퍼런스 0). 구 81.7% full-202 run은 모델 계보가 다른 historical 수치로,
> 게이트 비교에 사용하지 않는다.

### 4-3. 품질 게이트 재정의 (Gemini floor 대체)

| 항목 | 기존 (퇴역) | 신규 |
|---|---|---|
| 기준선 | Gemini v3.5 159건 85.5% | **같은 모델의 frames-10 실측** (§4-2a): Sonnet **78.2%**/micro55 74.5%, Opus 81.2%/70.9%. Fable 85.1%·구 81.7% run은 historical 참고 — 게이트 사용 금지 |
| 채택 게이트 | Gemini 회귀 통과 | **같은 모델 paired blind에서 그 모델의 frames 대비 −3%p 이내 AND recovered≥broken AND 토큰 실측 절감(단일장 목표 ≥2×)**. Sonnet 통과 = 필수(채택), Opus = 강건성 확인(미충족 시 "모델 특이적" 플래그) |
| 평가 프로토콜 | API 정량 (temp 0.1) | 구독 blind 서브에이전트 — temperature 비제어가 구조적 한계 → paired 분석으로 흡수 + 동률/경계는 3-vote |
| 모델 핀 | gemini-2.5-flash | **Sonnet 4.6 (primary·production 목표) + Opus 4.8 (secondary 검증)** — Fable 5 게이트 제외. 결과에 모델·시점 명시, 모델 업데이트 시 기준선 재측정 |

**보조 지표 (게이트 아님):** **care-priority 3클래스 = moving 72 + shedding 29 + drinking 16
= 117건** 정확도를 모든 리포트에 병기 — "잘 노는지·탈피하는지·물 마시는지"가 제품 가치 1순위라는
사용자 우선순위(§0)와의 정렬 확인용. defecating은 클래스별 표에 보고만 (최적화 비목표).

### 4-3a. 평가/검증 프로세스 — 결과 무결성 감사

> Claude/Codex가 실험 결과를 "그냥 해석"하지 않고 **무결성을 감사**할 수 있게 하는 운영
> 프로세스. 모든 phase(M0~M3, V1)에 공통 적용. 순서: **pre-reg → blind inference →
> deterministic scoring → LLM audit → discordant review → decision label.**

**1. Pre-registration (실행 전 고정)**
- phase별로 **sample list(clip_id) / 모델 / 입력표현(변형) / 통과 기준**을 실행 전에 고정하고,
  본 스펙에 "pre-reg 블록"으로 기록한다 (sample list는 `experiments/<phase>/sample_list.json`).
- **실행 후 기준 변경 금지.** 부득이한 변경은 결과 확인 전에만 + 별도 사유를 pre-reg 블록에
  기록 (사후 변경 = 해당 run 무효). M0 stratified 20건 고정(§4-2)은 이 원칙의 적용례.

**2. Blind inference**
- 분석 모델(서브에이전트)은 **GT를 보지 않는다** — 중립 폴더명 `sample-NN`, GT는 `meta.json`
  분리 보관, 에이전트에 meta 읽기 금지 명시.
- 입력 폴더명/파일명/metadata/EXIF에 **GT leakage 0** — 표현 빌더가 생성 시점에 보장하고,
  phase 첫 run 전에 leakage 검수 1회 (파일명·EXIF strip 확인).
- 출력은 **JSONL 고정 schema**:
  `{"sample": "sample-NN", "action": "<class>", "confidence": 0.0~1.0, "reasoning": "<1문장>", "model": "<id>", "repr": "<변형명>", "phase": "M0"}`

**3. Deterministic scoring (점수는 코드만 산출)**
- 정확도 / paired diff(recovered·broken) / false positive / 토큰 집계는 **Python scorer**
  (`scripts/_score_repr.py`)가 계산한다. **Claude/Codex가 점수를 손계산하는 것 금지** —
  scorer 출력이 유일한 공식 수치.
- scorer는 **missing**(계획 list에 있는데 결과 없음) / **duplicate**(같은 sample 중복 응답) /
  **sample mismatch**(list 밖 sample) / **schema error**(필드 누락·타입·미정의 클래스)를
  전부 **run fail로 처리** (조용한 skip·부분 채점 금지 — 누락 에이전트 재실행 후 재채점).

**4. LLM audit (해석이 아니라 감사)**
- Claude/Codex는 결과의 정답성을 최종 판정하지 않는다. 감사 체크리스트:
  - [ ] sample list가 pre-reg과 일치하는가 (개수·clip_id)
  - [ ] **같은 모델끼리** 비교했는가 (Sonnet↔Sonnet, Opus↔Opus — §4-3)
  - [ ] GT leakage가 없는가 (폴더/파일명/메타)
  - [ ] positive-only 평가로 **과탐(FP)을 놓치지 않았는가** (V1-negative 류 대조군 존재 여부)
  - [ ] recovered/broken 해석이 과장되지 않았는가 (소표본 Δ를 결론으로 승격하지 않았는가)
  - [ ] close-call 결과(게이트 경계 ±1~2건)에 **3-vote 재판정**이 필요한가
  - [ ] GT-noise 후보가 있는가 (양 표현/양 모델이 일관되게 GT와 다른 케이스)
- 교차 감사 권장 (donts 제너럴 #6 — 같은 모델 자기 리뷰 금지): Sonnet 결과의 감사는 다른
  모델(Codex CLI 등)로.

**5. Discordant case review**
- 별도 review queue로 분리 (scorer가 자동 추출): ① frames vs montage **갈린** 샘플
  ② Sonnet vs Opus **갈린** 샘플 ③ drinking false positive 후보 (V1-negative 위반 케이스).
- **GT 변경은 Claude/Codex 단독 금지** — review queue에 올리고 **사람 영상 확인 후에만**
  정정 (기존 원칙 "확정은 사람 영상" + blind=라벨QA 전례. GT-noise 후보 2건 5a34267c·ce9bab20도
  여전히 사람 확인 대기).

**6. Decision labels (최종 판단 기록)**
- phase별 최종 판단은 **`adopt` / `hold` / `reject`** 셋 중 하나로만 기록 (스펙 체크리스트에 병기).
- **Sonnet gate 통과 = adopt의 필수 조건** (production 목표 모델이므로).
- **Opus 미충족 = reject가 아니라 `model-specific risk` 플래그** — adopt에 플래그를 달아
  production 전송 시 주의사항으로 승계.
- hold = 게이트 경계/3-vote 미해소/GT-noise 미정리 등 판단 보류 — 사유와 해소 조건 기록.

### 4-4. 실행 순서 (의존 관계)

```
M0 (stratified 20건 × 12변형 Sonnet 전부 = 240 clip-eval + Opus 상위 2~3 후보 40~60 clip-eval,
    ~3-4M tok 보수 추정)
 ──→ M1 (63건 run 1회 = micro55 채점 + legacy63 기록, ×2모델, ~1.2M)
 ──→ M2 (202건 × 2모델 — montage만 신규, frames는 P1 jsonl 재사용, ~3.5M)
 ──→ M3 (캐스케이드 시뮬, 인퍼런스 0)
V1 (positive 16 + negative ~16 × Sonnet 필수 + Opus 선택, ~0.5-1M)  ── M트랙과 독립, 아무 때나
```
- 토큰 추정 근거: full-202 frames 실측 ≈ 16k/clip-eval (이미지 7.9k + 프롬프트/출력 오버헤드).
  몽타주는 이미지가 작아(3.1~6.3k) clip-eval당 ~11-14k 추정 — **정확 수치는 M0에서 실측 후 갱신**.
- M0가 단계 중 최대 예산(12변형 풀스윕) — stratified 20건으로 클립 수를 묶어 통제.
- 주간 구독 한도 고려: full-202급 run은 주 2~3회 이내, 나머지는 error-set 단위.
- Opus를 M0 전 변형에 안 태우는 이유 = secondary 역할(상위 후보 강건성 확인)에 전 변형 측정은
  과소비 — primary(Sonnet)가 고른 **상위 2~3개 후보만** 검증.

### 4-5. 고려했던 대안

- **Claude API(종량제)로 정량 평가**: temperature 제어 가능하지만 "API 비용 포기"라는 피벗
  취지와 충돌 → 기각. 필요 시 최종 채택 직전 1회 확인용으로만 재논의.
- **몽타주 캔버스 >1536px**: Claude가 1568px로 다운스케일 → 의미 없음. 캔버스 분할(다장
  몽타주)은 M0 설계에 정식 포함 (§4-2 비교축 2).
- **2×2 등 10프레임 미만 격자**: 셀은 커지나 기존 유효 구간(10~20프레임)을 벗어나 시간
  커버리지 손실 + 프레임 수 변수가 섞임 → 제외 (2026-06-12 계획 수정).
- **Fable 5를 게이트에 포함**: 최강 참고선이지만 production 목표(Sonnet)와 무관한 점수가
  채택 판단을 왜곡 + 구독 한도 소모 → historical 참고선으로만 (2026-06-12 사용자 결정).
- **모션 키프레임 선택**: P2에서 기각됨 (recovered 1/11) — 균등 샘플 유지.

### 4-6. 리스크 / 미해결 질문

- 서브에이전트 모델 핀: Sonnet 4.6 / Opus 4.8 고정 — 결과 기록에 모델·시점 명시 필수.
  모델 버전 업데이트 시 frames 기준선부터 재측정 (기준선과 후보를 같은 모델 버전으로).
- dataset-203은 gitignore 로컬 자산 — 맥북 마이그레이션 시 복사 목록에 포함할 것.
- blind 청결: 몽타주 생성 스크립트가 GT를 파일명/EXIF에 누설하지 않는지 M0에서 1회 검수.

## 5. 학습 노트

- **Claude vision 토큰 경제**: 이미지 토큰 ≈ w×h/750, 최장변 1568px 초과는 다운스케일.
  → "한 장에 크게"가 "여러 장 작게"보다 토큰 효율 좋음 (montage-v2의 근거).
- **paired 비교 (recovered/broken)**: A/B 집계 Δ는 GT 노이즈·비결정성에 취약 — clip 단위로
  "A맞고 B틀림 / A틀리고 B맞음"을 세는 게 노이즈에 강함 (few-shot 사고의 교훈, 이 레포 표준).
- **표적룰의 모델 특이성**: 같은 프롬프트 1줄이 Sonnet +6.9%p / Gemini −2.3%p — 프롬프트는
  모델과 쌍으로만 의미. (TS 비유: 특정 브라우저 버그 workaround가 다른 브라우저에선 regression)
  → 본 스펙의 **"같은 모델끼리만 비교" 게이트 설계 근거** (Sonnet 후보를 Fable/타모델 기준선과
  비교하면 같은 함정).

## 6. 참고

- 클로징 기록: `experiments/gemini-final-partial/README.md` (Gemini 트랙 마지막 정량)
- 기준선 출처: P1 4모델 blind jsonl (`experiments/eval-frames-full/{sonnet46,opus48,fable5}_blind.jsonl`)
  + `scripts/_score_frames_models.py` — full-202: Sonnet 78.2 / Opus 81.2 / Fable 85.1(참고).
  micro55/legacy63 기준선(§4-2a)은 같은 jsonl을 current GT로 재채점한 값.
  (구 81.7% run·Fable 85.1%는 historical 참고 — 게이트 비교 금지)
- 연관 스펙: `experiment-weak-model-levers.md` (P1~P4 — 캐스케이드 설계 재활용),
  `experiment-claude-subscription-rba.md` (구독 트랙 1기 — contact sheet 적합도 맵)
- claude-video: https://github.com/bradautomates/claude-video (MIT, yt-dlp+ffmpeg+frames 파이프라인)

## 7. Pre-reg 기록 (§4-3a-1 — 실행 전 고정, 사후 변경 금지)

### M0 pre-reg (2026-06-12 고정 — 배치 실행 전)

| 항목 | 고정값 |
|---|---|
| sample list | `experiments/m0-montage/sample_list.json` — stratified 20건 (seed 42, `scripts/_m0_prereg.py` 재현 가능). **이후 불변** |
| 변형 | 12 = 6 레이아웃(12f-1s/12f-2s/16f-1s/16f-2s/18f-2s/20f-1s) × ts on/off. 20f-2s는 M0 제외 |
| 모델 | Sonnet 4.6 = 12변형 전부 / Opus 4.8 = Sonnet 상위 2~3 변형만 / Fable 게이트 제외 |
| 프롬프트 | v3.6.1 고정 (`/tmp/v361_frames_prompt.txt` = production 동치) + 입출력 지시만 추가 |
| 채점 | `scripts/_score_repr.py --phase M0` 단독 (raw 컨벤션). **selftest 6/6 통과 확인됨** (§4-2a 기준선 재현: 41/55·39/55·47/63·46/63·158/202·164/202) |
| **M1 진출 룰 (사전 고정)** | Sonnet raw 상위 **1~2 변형**. 동률 시 ① 실측 이미지 토큰 낮은 쪽 ② 장수 적은 쪽. ts 효과는 같은 레이아웃 ts쌍 비교로 별도 보고 (진출 룰과 분리) |
| 해석 가드 | 20건 = 스크리닝 (±1건 = 5%p 노이즈) — M0 결과로 채택/기각 단정 금지, 후보 선정만. Sonnet frames 동일 20건 기준점 = **12/20** (구성상 정답12/오답8) |

**선정 20건** (`micro 12 = drinking/prey/paste 각 정2오2` + `general 8 = 경계2·moving정1오1·shedding정2오1·hf1`):
sample-01 31da5684(shed,N) · 02 05da625c(mov경계,Y) · 03 0125b0f9(mov,Y) · 04 0d78637c(hf,Y) ·
05 b5637a1a(drink,N) · 06 036a650d(drink,Y) · 07 165f593f(paste,Y) · 08 0146200f(shed,Y) ·
09 0525472f(shed,Y) · 10 2d495ee3(prey,Y) · 11 3abc83bc(paste,N) · 12 2420abd8(mov경계,Y) ·
13 1ef6f35c(paste,Y) · 14 3ab3bce6(prey,Y) · 15 685911a0(drink,N) · 16 26c75091(prey,N) ·
17 04ec15e3(mov,N) · 18 0dbc54a8(paste,N) · 19 55c7c58f(prey,N) · 20 00c089c8(drink,Y)
(Y/N = Sonnet frames 정오)

**입력 생성 완료 (2026-06-12):** `scripts/repr_montage_v2.py` → 240 variant-샘플, blind leakage
검수 PASS (입력 트리에 jpg만, GT/메타 없음). 실측 이미지 토큰(클립당 평균): 12f-1s 2.5k ·
16f-1s 2.0k · 20f-1s 2.4k · 18f-2s 4.1k · 16f-2s 5.2k · 12f-2s 5.3k. 세로 영상 9건은 격자
회전 적용 (§4-2 — 실행 전 빌더 보정이라 pre-reg 위반 아님, 결과 확인 전 수정).

## 8. Gemini 퇴역 체크리스트

- [x] 진행 중 회귀 4런 중단 + 부분 데이터 박제 (`experiments/gemini-final-partial/`) — 2026-06-12
- [ ] fly `petcam-vlm-worker` 셧다운 — **사용자**: `flyctl scale count 0 -a petcam-vlm-worker`
- [x] `GEMINI_API_KEY` 처리 — .env에 두되 코드 신규 사용 금지 (키 자체는 무료, 호출만 0)
- [x] `scripts/eval_vlm_*` Gemini 스크립트 — 삭제하지 않음 (아카이브: docstring "퇴역 2026-06-12" — 2개 파일 완료. `load_eval_set` 등 유틸은 Claude 트랙이 계속 import)
- [x] `docs/AI-VIDEO-ANALYSIS-STRATEGY.md` Track A 서술 갱신 — §4에 피벗 배너 (2026-06-12)
- [x] `specs/next-session.md` 정리 — 피벗 요약이 최상단, key-blocked 항목은 히스토리로만 잔존 (2026-06-12)
