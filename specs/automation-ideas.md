# 자동화 후보 — IR/발표자료 & 영상 워크플로우

> **출처:** 2026-06-22 투자자용 IR "RBA AI 안내 슬라이드" v4.0 갱신 세션 wrap (automation-scout 발굴).
> **상태:** 기획만. 구현 안 함. 다음에 만들 때 이 설계를 출발점으로.
> **권장 구현 순서:** `scan-slides`(가장 쉬움) → `pick-demo-frames` → `ir-sync`(가장 값지나 정교한 설계 필요, 앞 둘 써보고 패턴 확인 후).
> **공통 주의:** 셋 다 petcam 경로·데이터셋 의존적이라 **이 레포 `.claude/` 아래**에 둔다(글로벌 X). 기존 스킬(`blind-eval`·`new-experiment`·`writing-plans`)과 중복 없음 확인됨.

---

## 1. `scan-slides` (Command) — 난이도 낮음, 오늘 코드 이미 있음

PPTX 슬라이드 텍스트 스캔 + 다중 자료 비교. 이번 세션의 `/tmp/scan_pptx.py`를 커맨드로 포장.

- **위치:** `.claude/commands/scan-slides.md`
- **트리거:** `/scan-slides <pptx> [<pptx2>]`, "이 PPTX 슬라이드 텍스트 뽑아줘"
- **입력:** PPTX 경로 1개(단일) 또는 2개(`--mode compare` 비교)
- **출력:** 슬라이드 번호 + 텍스트 블록 / 비교 모드는 "슬라이드 N: [A] vs [B]" diff
- **핵심 단계:**
  1. `/tmp/scan_slides_<ts>.py` 생성 — `zipfile` + `re` + `xml.etree`로 PPTX slide XML의 `<a:t>` 태그 수집
  2. `uv run python <스크립트> <path>` 실행 → 결과 반환
  3. 비교 모드면 두 파일 각각 실행 후 슬라이드별 나란히 출력
- **주의:** PDF 파싱은 제외(pdfplumber/PyMuPDF 의존성 없음 → "PPTX로 저장 후 사용" 안내). `uv run` 필수(donts/python #2 pip 금지). 절대경로 인자.

## 2. `pick-demo-frames` (Command) — ffmpeg + 비전 선별

평가셋 영상에서 발표/문서용 베스트 프레임 추출. 이번 drinking 프레임 제작 패턴.

- **위치:** `.claude/commands/pick-demo-frames.md`
- **트리거:** `/pick-demo-frames <영상> <라벨>`, "발표용 프레임 뽑아줘", "<행동> 예시 이미지 만들어줘"
- **입력:** 영상 경로, 라벨(drinking 등), (선택) 후보 수(기본 9, 3×3 tile), 저장 경로
- **출력:** 후보 N장 + `best.jpg`(비전 선별 top-1, 또는 top-3) + 선별 이유 한 줄
- **핵심 단계:**
  1. ffmpeg로 균등 간격 N장 추출 (**1080 no-upscale** — 메모리 `input-resolution-micro-contact` 원칙)
  2. 후보 전체를 `Read`(비전)로 보고 라벨 행동이 가장 명확한 프레임 선별
  3. 선별 이유 기록 + best 저장 + (선택) contact sheet tile 생성
- **주의:** `storage/`는 gitignore(커밋 X) → IR과 함께 둘 거면 `docs/ir/assets/` 옵션. ffmpeg 존재 확인 선행. `blind-eval`과 목적 다름(저쪽=GT 정확도 평가 / 이쪽=시각적으로 가장 명확한 한 장 선별). R2 클립 다운로드는 범위 밖.

## 3. `ir-sync` (Skill) — 가장 값짐, 다단계 파이프라인

개발 현황을 IR/발표자료에 반영해 최신화하는 6단계 워크플로우. 이번 세션 전체의 골격.

- **위치:** `.claude/skills/ir-sync/SKILL.md` (단발 변환이 아니라 단계별 출력이 다음 입력이 되는 파이프라인이라 Skill)
- **트리거:** "IR 자료 업데이트", "발표자료 최신화", "개발 현황을 슬라이드에 반영", "투자자 자료 갱신"
- **입력:** 기존 IR 파일 경로(또는 탐색 디렉토리), 청중 유형 `investor`/`partner`/`internal`, (선택) 강조할 최근 마일스톤
- **출력:** ① 슬라이드별 갱신 원고 `.md`(현재→제안 diff + 변경 이유) ② Claude Desktop용 디자인 의뢰서 `.md`(최종 콘텐츠만, 히스토리 X) ③ **사실정확성 체크리스트**(수치·모델명·날짜 사람 검증 항목)
- **핵심 단계:**
  1. 현황 수집 — `specs/`, `CLAUDE.md`, `experiments/INDEX.md`, `docs/` 탐색 → 최근 마일스톤(정확도·클래스 수·모델 변경·R&D 결론, `adopt`/`reject` 포함)
  2. 기존 IR 파싱 — `scan-slides` 재사용
  3. 갭 진단 — 슬라이드 텍스트 vs 현황 → outdated 항목 목록화
  4. 청중별 프레이밍 — investor=해자/방어력, partner=기술 구체성, internal=raw 수치
  5. 슬라이드 원고 초안 (기존 보존 + 변경 이유)
  6. 디자인 의뢰서 (Desktop 넘길 포맷)
- **주의:**
  - **자동 수집 수치는 반드시 "사실정확성 체크리스트"로 사람 검증** — "자동화가 만든 89% 같은 숫자를 검증 없이 IR에" 넣는 사고 방지. (이번 세션도 SOT 일일이 확인함)
  - CAOF **Standard 트랙**(메인 겸임, 에이전트 분리 불필요 — 외부 서비스 없이 로컬 파일+스크립트만).
  - `writing-plans`와 다름(저쪽=코드 구현 계획 / 이쪽=커뮤니케이션 자료 갱신).
  - `scan-slides`·`pick-demo-frames`를 내부 단계로 재사용.
  - IR 톤 SOT 관계: 이 레포는 "어떻게 만드나", 제품 "왜/무엇"은 `tera-ai-product-master`. IR 발표 PPTX 원본은 대표 관리(Downloads). `docs/ir/`는 AI 파트 갱신본 보관소.

---

## 이번 세션 산출 자산 (재사용 시드)

- `/tmp/scan_pptx.py` — PPTX 슬라이드 텍스트 추출 (scan-slides 시드)
- ffmpeg 프레임 추출 → `tile` contact sheet → `Read` 비전 선별 패턴 (pick-demo-frames 시드)
- `docs/ir/teraai-rba-ir.{html,pdf}` — IR 결과물 + 디자인 톤 레퍼런스
