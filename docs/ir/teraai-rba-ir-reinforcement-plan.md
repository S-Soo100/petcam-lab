# RBA IR 보강 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 투자자와 초기 고객이 RBA의 AI성을 더 쉽게 이해하도록 Track A confidence, Track A 프롬프트 방식, 실제 도마뱀 행동 예시를 보강한다.

**Architecture:** 기존 HTML 기반 IR 덱을 유지하되 9장 구성에서 10장 구성으로 확장한다. 설명은 과장 없이 연구 근거에 맞추고, confidence는 "정답 확률"이 아니라 Track B/HITL 라우팅을 위한 자체 확실성 신호로 정의한다.

**Tech Stack:** HTML/CSS slide deck, Chrome headless PDF export, Poppler `pdftoppm` PNG render, ImageMagick asset resize.

## Global Constraints

- 기존 RBA 구조와 덱 톤을 유지한다.
- Track A confidence는 모델 자체 추정값이며 calibration 되지 않은 값으로 설명한다.
- 프롬프트는 투자자가 이해할 수 있게 "AI에게 주는 판독 체크리스트"로 번역한다.
- 실제 예시 이미지는 연구 샘플에서 가져오고, 이미지별 행동 판단 기준을 한 문장으로 붙인다.
- 최종 산출물은 HTML, PDF, 전체 슬라이드 PNG가 서로 같은 최신본이어야 한다.

---

## 보강 범위

| 보강 항목 | 현재 문제 | 반영 위치 | 반영 방식 |
|---|---|---|---|
| Track A confidence | 신뢰도가 어떻게 나오는지 상상이 어렵고, 정답 확률처럼 오해될 수 있음 | 슬라이드 3 | 모델이 `action`, `confidence`, `reasoning`을 함께 반환한다고 설명. confidence는 자체 확실성 신호이며 Track B/HITL 라우팅에 쓴다고 명시 |
| Track A 프롬프트 | "프롬프트로 분석한다"는 말이 추상적임 | 슬라이드 4 | 입력, 판독 기준, 결정 규칙, JSON 출력 흐름으로 시각화. 먹이그릇 근처만으로 feeding 판단하지 않는 예시 추가 |
| 도마뱀 예시 사진 | 음수 사례는 좋지만 다른 행동 예시가 부족함 | 신규 슬라이드 7 | eating_paste, eating_prey, hand_feeding 실제 샘플 3개를 추가하고 판정 기준을 짧게 설명 |
| 번호와 산출물 | 신규 장표 추가로 기존 9장 구조 변경 필요 | 전체 | 10장 기준으로 페이지 번호 갱신. PDF와 PNG 전체 재생성 |

## 근거

- `/Users/baek/petcam-lab/vlm-classifier-portable/data/README.md`
  - `confidence`는 `[0,1]` 범위의 모델 자체 추정값이며 calibration 되지 않았다고 정의되어 있다.
- `/Users/baek/petcam-lab/vlm-classifier-portable/HISTORY.md`
  - confidence threshold 단독 분기는 효과가 낮았고, 0.95 이상도 76% 정확도에 그쳤다고 기록되어 있다.
- `/Users/baek/petcam-lab/web/prompts/backups/system_base.v4.0.md`
  - 출력 형식은 `{ action, confidence, reasoning }` JSON이다.
  - eating_paste/eating_prey는 visible food/prey와 tongue contact가 필요하다.
  - drinking은 visible water보다 body-anchored repeated licking posture를 본다.
  - 모호하면 moving을 선호한다.
- `/Users/baek/petcam-lab/experiments/v40-regression/REPORT.md`
  - v4.0은 adopt 되었고 raw 85.9%, 급여경계 86.5%로 현재 설명 기준선으로 쓸 수 있다.

## Task 1: 보강계획서 저장

**Files:**
- Create: `/Users/baek/petcam-lab/docs/ir/teraai-rba-ir-reinforcement-plan.md`

- [x] **Step 1: 사용자 피드백을 보강 항목 3개로 정리**

Track A confidence, Track A 프롬프트, 추가 예시 사진을 각각 슬라이드 단위로 매핑한다.

- [x] **Step 2: 연구 근거 파일을 연결**

confidence calibration 한계, v4.0 프롬프트 규칙, v4.0 회귀 보고서의 adoption 근거를 명시한다.

## Task 2: 이미지 자산 정리

**Files:**
- Create: `/Users/baek/petcam-lab/docs/ir/assets/rba-example-eating-paste.jpg`
- Create: `/Users/baek/petcam-lab/docs/ir/assets/rba-example-eating-prey.jpg`
- Create: `/Users/baek/petcam-lab/docs/ir/assets/rba-example-hand-feeding.jpg`

- [x] **Step 1: 연구 샘플에서 대표 이미지를 고른다**

사용 후보:
- eating_paste: `/Users/baek/petcam-lab/experiments/eval-0608-claude/sample-eating-paste-0034/contact.jpg`
- eating_prey: `/Users/baek/petcam-lab/experiments/eval-0608-claude/sample-eating-prey-1635a/contact.jpg`
- hand_feeding: `/Users/baek/petcam-lab/experiments/eval-0608-claude/sample-hand-feeding-1740/contact.jpg`

- [x] **Step 2: IR 슬라이드용 비율로 정리한다**

각 이미지를 900x560 landscape 기준으로 맞추고, 신규 슬라이드에서 동일 비율로 보이게 한다.

## Task 3: 덱 본문 보강

**Files:**
- Modify: `/Users/baek/petcam-lab/docs/ir/teraai-rba-ir.html`

- [x] **Step 1: 슬라이드 3을 confidence 설명 중심으로 보강**

추가할 핵심 문장:
> confidence는 모델이 함께 반환하는 자체 확실성 점수다. 정답 확률로 보정된 값은 아니며, Track B/HITL 진입을 돕는 불확실성 신호로 사용한다.

- [x] **Step 2: 슬라이드 4를 프롬프트 흐름도로 재구성**

입력, 판독 체크리스트, 결정 규칙 예시, JSON 출력 흐름을 보여준다.

- [x] **Step 3: 슬라이드 5를 Track B 연결 설명으로 다듬는다**

confidence 하나만 믿는 구조가 아니라 ROI, motion, 환경 메타데이터를 결합해 모호하거나 중요한 장면을 다시 본다고 설명한다.

- [x] **Step 4: 신규 슬라이드 7을 추가한다**

eating_paste, eating_prey, hand_feeding 실제 예시 이미지 3개와 각 판정 기준을 넣는다.

- [x] **Step 5: 전체 페이지 번호를 10장 기준으로 갱신한다**

기존 로드맵은 8번, structured context packet은 9번, ensemble 구조는 10번이 된다.

## Task 4: 산출물 재생성 및 검수

**Files:**
- Modify: `/Users/baek/petcam-lab/docs/ir/teraai-rba-ir.pdf`
- Modify/Create: `/Users/baek/petcam-lab/docs/ir/teraai-rba-ir-slides/slide-01.png` ... `slide-10.png`

- [x] **Step 1: Chrome headless로 PDF를 다시 만든다**

Run:
```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --headless --disable-gpu --no-sandbox \
  --print-to-pdf=/Users/baek/petcam-lab/docs/ir/teraai-rba-ir.pdf \
  file:///Users/baek/petcam-lab/docs/ir/teraai-rba-ir.html
```

- [x] **Step 2: PDF를 PNG로 렌더링한다**

Run:
```bash
pdftoppm -png -r 144 \
  /Users/baek/petcam-lab/docs/ir/teraai-rba-ir.pdf \
  /Users/baek/petcam-lab/docs/ir/teraai-rba-ir-slides/slide
```

- [x] **Step 3: 산출물 수량과 해상도를 검수한다**

Expected:
- PDF pages: 10
- PNG count: 10
- PNG size: 1920x1080

- [x] **Step 4: 신규/수정 슬라이드를 육안 검수한다**

검수 대상:
- `slide-03.png`
- `slide-04.png`
- `slide-07.png`
- 전체 접촉표 또는 대표 PNG

검수 결과:
- PDF pages: 10
- PNG count: 10
- PNG size: 1920x1080
- 육안 검수: `slide-03.png`, `slide-04.png`, `slide-07.png`, `slide-10.png`, 전체 접촉표 확인
