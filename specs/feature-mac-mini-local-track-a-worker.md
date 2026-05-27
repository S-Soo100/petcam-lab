# Feature — Mac mini Local Track A Worker

> Mac mini M1을 Gemini Track A 대체 후보인 로컬 RBA 분석 worker로 세팅하고, 밤새 쌓인 motion clip을 아침까지 batch 분석한다.

**상태:** 🚧 제안 / 세팅 대기
**작성:** 2026-05-26
**연관:** [docs/AI-VIDEO-ANALYSIS-STRATEGY.md](../docs/AI-VIDEO-ANALYSIS-STRATEGY.md), [docs/MAC_MINI_DEV_ENV.md](../docs/MAC_MINI_DEV_ENV.md), [feature-vlm-worker-fly-deploy.md](feature-vlm-worker-fly-deploy.md), [experiment-mac-mini-segmentvlm-worker.md](experiment-mac-mini-segmentvlm-worker.md)

## 1. 목적

현재 production Track A는 fly.io `petcam-vlm-worker`가 Gemini 2.5 Flash로 60초 motion clip을 1차 라벨링한다. 이 구조는 안정적이지만, API 비용과 외부 모델 의존성이 있다.

이 작업의 목적은 Mac mini M1 16GB를 로컬 분석 worker로 두고, Gemini Track A를 단계적으로 대체할 수 있는지 검증하는 것이다.

목표:
- 밤새 쌓인 motion clip을 아침까지 처리한다.
- Gemini API 호출을 줄이거나, 장기적으로 기본 경로에서 제거한다.
- 기존 `behavior_logs`와 호환되는 label/confidence JSON을 만든다.
- 실패/불확실/P0 후보만 Gemini fallback으로 넘기는 구조를 준비한다.

## 2. 현재 하드웨어 기준

Mac mini:
- Chip: Apple M1
- RAM: 16GB unified memory
- Storage: 256GB
- 역할: 영상 장기 저장소가 아니라 "분석하고 버리는 worker"

판단:
- `gemma3:4b` 급 로컬 VLM은 1차 후보로 현실적이다.
- `qwen2.5vl:7b` 급 모델은 2차 비교 후보로 둔다.
- 256GB는 모델/임시 clip/로그에는 충분하지만, 원본 영상을 오래 저장하면 부족하다.

## 3. 스코프

### In

- Mac mini를 새 장비로 클린 세팅한다.
- `petcam-lab` 레포를 그대로 clone해서 worker 환경을 구성한다.
- Ollama + 로컬 VLM을 설치한다.
- 60초 motion clip에서 frame/contact sheet를 만들고 local VLM으로 분석한다.
- 기존 Gemini Track A와 같은 normalized JSON 출력을 만든다.
- 30~50개 clip으로 Gemini/GT 대비 평가한다.
- Slack 알림은 별도 notifier로 붙인다.

### Out

- 새 레포 생성.
- Mac mini에 production API 서버 전체를 이전.
- Mac mini를 원본 영상 장기 저장소로 사용.
- Gemini worker 즉시 제거.
- 검증 전 `behavior_logs(source='vlm')`를 local 결과로 덮어쓰기.
- 외부 인터넷에 Mac mini API를 직접 공개.

> 스코프 변경은 합의 후에만. 이 작업은 "Track A 대체 검증"이지, SegmentVLM side experiment나 전체 인프라 이전이 아니다.

## 4. 레포 전략

새 레포를 만들지 않는다. Mac mini에서도 같은 `petcam-lab`를 clone한다.

이유:
- 기존 `backend.vlm_worker_main`, R2/Supabase 클라이언트, prompt/eval 자산을 재사용한다.
- `AGENTS.md`, `.codex/`, `.agents/skills/`, `.claude/` 규칙을 함께 가져갈 수 있다.
- local worker도 같은 도메인 모델과 테스트 체계를 따라간다.
- 나중에 production 전환 시 diff가 명확하다.

디렉토리 권장:

```bash
mkdir -p /Users/baek/dev
cd /Users/baek/dev
git clone <petcam-lab-git-url> petcam-lab
cd petcam-lab
uv sync
```

운영 시 Mac mini의 `petcam-lab`는 독립 작업공간이다. 맥북의 working tree와 자동 동기화하지 않는다. 변경이 생기면 git branch/commit/PR 흐름으로 합친다.

## 5. Mac mini Codex 환경 전략

Codex는 프로젝트 루트의 `AGENTS.md`를 먼저 읽고 작업한다. 따라서 Mac mini에서도 `petcam-lab`를 clone하면 프로젝트 규칙 대부분은 따라온다.

필수로 확인할 것:

```bash
cd /Users/baek/dev/petcam-lab
ls AGENTS.md CLAUDE.md .codex .agents .claude
codex --version
uv --version
```

Codex에게 처음 줄 프롬프트:

```text
/Users/baek/dev/petcam-lab/AGENTS.md 와
/Users/baek/dev/petcam-lab/specs/feature-mac-mini-local-track-a-worker.md 를 읽고,
이 Mac mini를 Gemini Track A 대체 후보인 local RBA worker로 세팅해줘.
새 레포 만들지 말고 petcam-lab 안에서 진행하고,
production Gemini worker는 아직 건드리지 마.
먼저 환경 확인 → Ollama/gemma3 smoke test → 30~50개 평가 계획 순서로 진행해.
```

주의:
- `.env`는 새로 만든다. 맥북에서 복사하더라도 Git에 넣지 않는다.
- Supabase service role, R2 secret, Slack webhook URL은 `.env`에만 둔다.
- user-level Codex 설정이 필요하면 최소한만 복사한다. 전체 Mac 마이그레이션은 하지 않는다.

## 6. 권장 아키텍처

초기 검증:

```text
R2 / Supabase
  → Mac mini local-track-a-worker polling
  → mp4 임시 다운로드
  → frame sampling / contact sheet 생성
  → Ollama local VLM 분석
  → normalized JSON artifact 저장
  → Gemini/GT와 비교
  → Slack 요약 알림
```

검증 후 운영 후보:

```text
camera_clips pending
  → local Track A worker
  → behavior_logs(source='local_vlm') INSERT
  → low confidence / P0 / parse failure
  → Gemini fallback
  → behavior_logs(source='vlm') or source='gemini_fallback'
```

Mac mini로 inbound HTTP API를 여는 방식도 가능하지만, 운영형은 outbound polling이 더 안정적이다.

선호:
- MVP 빠른 테스트: `http://mac-mini.local:8088/analyze-track-a`
- 운영형: Mac mini가 Supabase queue를 polling

## 7. 모델/입력 전략

1차 모델:

```bash
ollama pull gemma3:4b
```

2차 비교 후보:

```bash
ollama pull qwen2.5vl:7b
```

입력은 mp4 직접 분석보다 contact sheet를 우선한다.

```text
60초 motion clip
→ 1fps 또는 2fps frame sampling
→ contact sheet jpg
→ local VLM
→ label/confidence/needs_review/evidence JSON
```

출력 예시:

```json
{
  "clip_id": "uuid",
  "label": "moving",
  "confidence": 0.72,
  "needs_review": false,
  "model": "gemma3:4b",
  "prompt_version": "local-track-a-v1",
  "evidence": "visible movement near the hide area",
  "source": "local_vlm"
}
```

## 8. Slack 연동

Slack은 분석 worker와 분리된 notifier로 둔다.

1차:
- Incoming Webhook으로 단방향 알림
- batch 완료/실패/health 요약

2차:
- Slack App + Socket Mode
- `/petcam status`, `/petcam summary today`, `/petcam retry failed`

Slack secret:

```bash
SLACK_WEBHOOK_URL=...
```

주의:
- webhook URL은 비밀값이다.
- Mac mini를 Slack 명령 수신용 public endpoint로 직접 노출하지 않는다.
- 명령형은 `allowed_user_ids`, `allowed_channel_ids` 제한을 둔다.

## 9. 완료 조건

- [ ] Mac mini에 macOS 클린 세팅 완료.
- [ ] Homebrew, `uv`, `ffmpeg`, `jq`, `tmux`, Codex CLI 설치 확인.
- [ ] `petcam-lab` clone + `uv sync` 완료.
- [ ] `.env`에 Supabase/R2/Slack/local worker 설정 주입.
- [ ] Ollama 설치 + `gemma3:4b` pull 완료.
- [ ] 이미지 1장 vision smoke test 성공.
- [ ] R2 clip 1건 다운로드 smoke test 성공.
- [ ] 60초 clip → contact sheet → local label JSON 생성 성공.
- [ ] 30~50개 평가셋에서 Gemini/GT 대비 리포트 생성.
- [ ] 처리 시간 기준 산출: clip당 latency, 밤새 batch 예상 완료 시간.
- [ ] Gemini fallback 기준 초안 작성.
- [ ] Slack batch 완료 알림 성공.

## 10. 첫 세팅 체크리스트

Mac mini에서:

```bash
# 0. 상세 개발환경 문서 먼저 확인
open docs/MAC_MINI_DEV_ENV.md

# 1. 기본 도구
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install git uv ffmpeg jq tmux

# 2. 레포
mkdir -p /Users/baek/dev
cd /Users/baek/dev
git clone <petcam-lab-git-url> petcam-lab
cd petcam-lab
uv sync

# 3. 환경
cp .env.example .env
# .env 편집: Supabase/R2/local worker/Slack secret 주입

# 4. Ollama
# 공식 macOS 앱 설치 후:
ollama pull gemma3:4b
ollama list

# 5. 프로젝트 확인
uv run pytest -q
```

테스트 전체가 오래 걸리거나 외부 secret이 부족하면, 먼저 smoke test만 진행한다.

## 11. 평가 기준

30~50개 clip 기준으로 아래를 본다.

품질:
- overall label match
- P0 recall: `feeding`, `drinking`, `defecating`, `shedding`, `eating_prey`
- false highlight rate
- needs_review rate
- JSON parse success rate

운영:
- clip당 평균 latency
- 50개/100개 batch 예상 완료 시간
- 모델 메모리/발열/스왑 여부
- 실패 유형: timeout, parse failure, model hallucination, empty visual evidence

채택 기준 초안:
- low-risk label은 local 결과를 사용할 수 있을 정도로 안정적이어야 한다.
- P0 후보는 local 단독 확정보다 Gemini fallback 또는 HITL로 보낸다.
- local 결과가 Gemini보다 싸더라도, review burden이 커지면 production 기본값으로 쓰지 않는다.

## 12. 기존 Mac mini SegmentVLM 스펙과의 관계

[experiment-mac-mini-segmentvlm-worker.md](experiment-mac-mini-segmentvlm-worker.md)는 Track B selective fallback 실험이다.

이 파일은 Track A 대체 실험이다.

구분:

| 항목 | 이 스펙 | 기존 SegmentVLM Mac mini 스펙 |
|---|---|---|
| 목적 | Gemini Track A 대체 | Track B 정밀 분석 / second opinion |
| 입력 | 60초 motion clip | mismatch / important clip event segments |
| 출력 | clip-level top-1 label | event-level timeline / review artifact |
| production 전환 가능성 | 높음, 검증 후 `source='local_vlm'` | 낮음, 먼저 artifact/HITL |
| 모델 | local VLM 우선 | Claude/Codex/local VLM 비교 |

## 13. 재개 프롬프트

Mac mini의 Codex에게 그대로 전달:

```text
나는 Mac mini M1 16GB/256GB를 petcam-lab의 local RBA worker로 쓰려고 해.
목표는 Gemini Track A를 대체하는 거야. 밤새 쌓인 60초 motion clip을 아침까지 batch 분석하면 돼.

/Users/baek/dev/petcam-lab/AGENTS.md,
/Users/baek/dev/petcam-lab/README.md,
/Users/baek/dev/petcam-lab/docs/AI-VIDEO-ANALYSIS-STRATEGY.md,
/Users/baek/dev/petcam-lab/specs/feature-mac-mini-local-track-a-worker.md
를 먼저 읽고 진행해.

새 레포 만들지 말고 petcam-lab 안에서 작업해.
production fly.io petcam-vlm-worker와 behavior_logs(source='vlm')는 아직 건드리지 마.
먼저 환경 확인, Ollama/gemma3:4b vision smoke test, R2 clip 1건 다운로드, contact sheet 기반 local label JSON 생성까지 해줘.
비밀값은 .env에만 넣고 Git에 올리지 마.
```
