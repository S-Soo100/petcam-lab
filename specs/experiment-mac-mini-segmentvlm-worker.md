# Experiment — Mac mini SegmentVLM Worker

> 맥미니를 로컬 analyzer worker 로 써서 SegmentVLM selective fallback 을 돌리는 사이드 플랜. fly.io production Gemini 워커는 유지하고, 맥미니는 Claude CLI / Codex CLI / local VLM 실험을 담당한다.

**상태:** 🚧 제안 / 대기
**작성:** 2026-05-16
**연관:** [experiment-event-segment-vlm.md](experiment-event-segment-vlm.md), [feature-vlm-worker-fly-deploy.md](feature-vlm-worker-fly-deploy.md)

## 1. 목적

현재 production VLM 경로는 fly.io `petcam-vlm-worker` 가 R2 영상을 받아 Gemini 2.5 Flash 로 60초 clip 전체를 zero-shot 분류하는 구조다. 이 구조는 안정적이고 저렴하지만, 짧은 행동이 묻히는 mismatch case 에서는 SegmentVLM 방식이 더 좋은 신호를 보였다.

이 실험은 맥미니를 별도 worker 로 두고, production 워커를 건드리지 않은 채 SegmentVLM 분석을 지속적으로 돌릴 수 있는지 검증한다.

목표:
- Claude CLI / Codex CLI / local VLM 을 로컬 구독/로컬 자원 기반으로 실험한다.
- fly.io API 서버와 `petcam-vlm-worker` 의 안정성을 해치지 않는다.
- selective fallback 대상만 처리해서 비용과 처리량을 통제한다.
- 결과를 production `behavior_logs(source='vlm')` 에 바로 섞지 않고, 별도 source/artifact 로 남긴다.

## 2. 권장 아키텍처

```text
Capture worker / existing pipeline
  → R2 mp4 저장
  → Supabase camera_clips / behavior_logs 기본 큐

fly.io petcam-vlm-worker
  → Gemini 2.5 Flash zero-shot
  → behavior_logs(source='vlm')

Mac mini segmentvlm-worker
  → Supabase/R2 outbound polling
  → SegmentVLM event/contact sheet 생성
  → Claude CLI / Codex CLI / local VLM 분석
  → 별도 source 또는 experiment artifact 저장
```

핵심 결정:
- 맥미니로 들어오는 inbound endpoint 를 열지 않는다.
- 맥미니가 Supabase/R2 로 outbound polling 한다.
- fly.io `petcam-api` 와 `petcam-vlm-worker` 는 그대로 둔다.
- 맥미니 worker 는 production 라벨 확정기가 아니라 second opinion / fallback analyzer 다.

## 3. In / Out

### In

- 맥미니에 레포 clone + `uv sync` + ffmpeg/OpenCV 환경 구성
- `scripts/segmentvlm_sample_poc.py` 또는 후속 정식 스크립트를 맥미니에서 실행
- SegmentVLM candidate polling 조건 정의
  - 초기: `VT label != Track A prediction`
  - 운영 후보: low confidence, confusion-prone label, user flagged clip, high-value P0 candidate
- Claude CLI / Codex CLI / local VLM adapter 실험
- 결과 저장 위치 정의
  - 실험 단계: `experiments/segment-vlm/sample-*/*-frame-analysis.json`
  - 운영 후보: `behavior_logs(source='segmentvlm_claude')` 또는 별도 테이블 검토
- worker 로그 / 비용 / 처리량 기록

### Out

- fly.io `petcam-vlm-worker` 교체
- `behavior_logs(source='vlm')` 를 SegmentVLM 결과로 덮어쓰기
- Flutter/UI 변경
- 외부에서 맥미니로 직접 호출하는 공개 API
- 맥미니를 production 단일 장애점으로 만드는 구조

## 4. 첫 실행 플랜

맥미니가 준비되면 이 순서로 진행한다.

1. 환경 확인
   - macOS / Apple Silicon 여부
   - 디스크 여유 공간
   - 네트워크 상시 연결 가능 여부
   - `ffmpeg`, `uv`, `claude`, `codex` 설치 여부
2. 레포 준비
   - `/Users/baek/petcam-lab` clone 또는 동기화
   - `uv sync`
   - `.env` 또는 필요한 secret 주입
3. CLI 로그인 확인
   - `claude --version`
   - `codex --version` 또는 `codex exec "ping" -s read-only`
4. R2/Supabase read 권한 확인
   - pending 후보 clip 조회
   - R2 mp4 1건 다운로드
5. SegmentVLM artifact 생성
   - `uv run python scripts/segmentvlm_sample_poc.py --limit 3`
6. blind analyzer 실행
   - `uv run python scripts/claude_segmentvlm_batch.py --all --model sonnet`
7. 결과 확인
   - `experiments/segment-vlm/claude-batch-summary.json`
   - recovered / still_wrong_but_review / cost 집계
8. 장시간 worker 전환 검토
   - launchd 또는 tmux/systemd 유사 방식
   - polling interval
   - retry/backoff
   - 로그 파일 위치

## 5. 운영화 후보 설계

정식 worker 로 키울 경우 추천 구조:

```text
backend/segmentvlm_worker_main.py
backend/segmentvlm/
  polling.py
  segmentation.py
  analyzers/
    claude_cli.py
    codex_cli.py
    local_vlm.py
  persistence.py
```

저장 전략 후보:

| 방식 | 장점 | 단점 | 추천 |
|---|---|---|---|
| experiment artifact JSON | 안전, 빠름, DB 변경 없음 | 앱에서 바로 못 봄 | 초기 |
| `behavior_logs(source='segmentvlm_claude')` | 기존 조회 구조 재사용 | source 정책/중복 처리 설계 필요 | 검증 후 |
| 새 테이블 `segmentvlm_runs` | event-level 결과 보존 좋음 | 마이그레이션 필요 | 장기 |

## 6. 리스크

- CLI 기반 호출은 API 기반 호출보다 운영 재현성이 낮다.
- Claude/Codex CLI 로그인 세션 만료 시 worker 가 멈출 수 있다.
- local VLM 은 모델/VRAM/속도에 따라 품질 편차가 크다.
- 맥미니 전원/네트워크 장애는 worker 중단으로 이어진다.
- GT label 을 analyzer 입력에 섞으면 blind 실험이 깨진다.

완화:
- 처음에는 production DB write 없이 artifact 만 저장한다.
- analyzer 입력에서 `gt_action`, `baseline_action`, 원본 파일명, notes 를 제거한다.
- source 를 분리한다: `vlm` 과 `segmentvlm_*` 를 절대 섞지 않는다.
- 결과가 맞아도 자동 확정하지 않고 HITL 후보로 둔다.

## 7. 현재 기준선

2026-05-16 기준 ClaudeFrameAnalyzer blind batch:
- mismatch 후보 26건 중 로컬 원본 영상 발견 9건 처리
- `recovered`: 4/9
- `still_wrong_but_review`: 5/9
- Claude reported cost: 약 `$1.78` / 9건
- 전 건 `needs_human_review=true`

해석:
- 맥미니 worker 는 자동 확정기보다 review / second opinion worker 로 시작하는 게 맞다.
- `defecating`, `drinking` 계열에서 회복 신호가 있다.
- `shedding`, `eating_prey` 는 contact sheet 만으로 부족할 수 있어 event split / frame selection 개선이 필요하다.

## 8. 재개 프롬프트

맥미니를 가져온 뒤 다른 에이전트에게 이렇게 말하면 된다.

```text
/Users/baek/petcam-lab/specs/experiment-mac-mini-segmentvlm-worker.md 를 읽고,
맥미니를 SegmentVLM 로컬 worker 로 세팅하는 작업을 이어서 해줘.
production fly.io petcam-vlm-worker 는 건드리지 말고,
먼저 환경 확인 → 3건 smoke test → Claude/Codex/local analyzer 비교 순서로 진행해.
```
