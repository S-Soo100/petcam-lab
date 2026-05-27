# Feature — Mac mini Local Track A Worker

> 🔄 **2026-05-27 [`../../petcam-rba-worker/specs/feature-mac-mini-local-track-a-worker.md`](../../petcam-rba-worker/specs/feature-mac-mini-local-track-a-worker.md) 로 미러됨.**
> Mac mini worker 작업의 실제 진행/체크리스트 갱신은 그쪽이 SOT. 이쪽 파일은 production 코어 시각에서 참조용으로 유지하되 수동 sync 가 필요하다.

> Mac mini M1을 Gemini Track A 대체 후보인 로컬 RBA 분석 worker로 세팅하고, 밤새 쌓인 motion clip을 아침까지 batch 분석한다.

**상태:** 🚧 진행 중 / Mac mini 세팅 일부 완료
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
- [x] Homebrew, `uv`, `ffmpeg`, `jq`, `tmux`, Codex CLI 설치 확인.
- [x] `petcam-lab` 작업공간 + `uv sync` 완료.
- [x] `.env` 새로 생성 + local worker 설정 placeholder 주입.
- [x] Ollama 설치 + `gemma3:4b` pull 완료.
- [x] 이미지 1장 vision smoke test 성공.
- [x] R2 clip 1건 다운로드 smoke test 성공.
- [x] 60초 clip → contact sheet → local label JSON 생성 성공.
- [x] 30~50개 평가셋에서 Gemini/GT 대비 리포트 생성.
- [x] 처리 시간 기준 산출: clip당 latency, 밤새 batch 예상 완료 시간.
- [x] Gemini fallback 기준 초안 작성.
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

## 14. 2026-05-26 Mac mini 세팅 로그

- 사용자 권한으로 `uv 0.11.16` 설치 완료 (`~/.local/bin/uv`).
- 복사된 `.venv`는 제거하고 `uv sync`로 Python 3.12.13 가상환경 재생성 완료.
- `.env`는 기존 복사본을 신뢰하지 않고 placeholder 기반으로 새로 생성.
- local-only Track A smoke 경로 추가:
  - `backend/local_track_a.py`
  - `scripts/local_track_a_smoke.py`
  - `tests/test_local_track_a.py`
- 검증:
  - `uv run pytest tests/test_local_track_a.py -q` → 3 passed
  - `uv run pytest tests/test_vlm_worker.py -q` → 11 passed
- 당시 블로커(15번 로그에서 해결됨):
  - 현재 macOS 계정은 관리자 권한이 없어 Homebrew 설치 실패.
  - Xcode Command Line Tools 없음: `xcode-select -p` 실패.
  - `ffmpeg`, `tmux`, `ollama` 미설치.
  - Ollama/gemma3 smoke와 R2 실클립 분석은 secret + Ollama 설치 후 재개.

## 15. 2026-05-26 Mac mini smoke 재개 로그

- Xcode Command Line Tools 설치 확인:
  - `xcode-select -p` → `/Library/Developer/CommandLineTools`
  - `git version 2.50.1 (Apple Git-155)` 확인 후 Homebrew Git 설치.
- Homebrew 필수 도구 설치 확인:
  - Homebrew `5.1.14`
  - Git `2.54.0`
  - uv `0.11.16`
  - ffmpeg `8.1.1`
  - jq `1.8.1`
  - tmux `3.6b`
  - Codex 앱 CLI 경로: `/Applications/Codex.app/Contents/Resources/codex`
- Ollama 설치 확인:
  - `ollama version is 0.24.0`
  - `ollama list` → `gemma3:4b` present (`3.3 GB`)
- synthetic smoke:
  - `/tmp/local-track-a-synthetic-60s.mp4` 생성 (ffmpeg testsrc2, 60초)
  - `uv run python scripts/local_track_a_smoke.py --file /tmp/local-track-a-synthetic-60s.mp4 --clip-id synthetic-60s-smoke --sample-fps 1 --max-frames 60`
  - artifact:
    - `storage/local-track-a/synthetic-60s-smoke.contact-sheet.jpg`
    - `storage/local-track-a/synthetic-60s-smoke.local-track-a.json`
  - 결과: `label=moving`, `confidence=0.95`, `source=local_vlm`, `latency_sec=12.578`
  - 단순 추정: 1 clip 약 13초면 50개 약 11분, 100개 약 22분. 실제 gecko clip은 이미지 복잡도/모델 warm 상태에 따라 다시 측정 필요.
- R2 smoke 대기:
  - 현재 `.env`의 R2 값은 placeholder.
  - `R2_BUCKET 환경변수 누락 또는 placeholder` 확인.
  - 다음 단계는 `.env`에 R2/Supabase secret 주입 후 `--r2-key`로 실제 clip 1건 다운로드 smoke.

## 16. 2026-05-26 R2 실클립 smoke

- `/Users/baek-end/Downloads/petcam-lab/.env`를 현재 작업공간 `.env`로 대체.
  - secret 값은 출력하지 않고 configured/placeholder 여부만 확인.
  - `LOCAL_TRACK_A_*` 기본값은 `.env` 끝에 추가.
- Supabase read-only query로 `has_motion=true AND r2_key IS NOT NULL` clip 5건 확인.
- R2 실클립 1건 다운로드 + local Track A 분석 성공:
  - clip: `70093109-df79-4578-bf40-df559df3f215`
  - r2_key: `clips/uploaded/2026-04-30/70093109-df79-4578-bf40-df559df3f215_70093109-df79-4578-bf40-df559df3f215.mp4`
  - artifact:
    - `storage/local-track-a/70093109-df79-4578-bf40-df559df3f215.contact-sheet.jpg`
    - `storage/local-track-a/70093109-df79-4578-bf40-df559df3f215.local-track-a.json`
  - local result: `label=moving`, `confidence=0.95`, `needs_review=false`, `latency_sec=13.532`
  - read-only 비교:
    - human GT: `moving`
    - production Gemini `source='vlm'`: `moving`, confidence `0.9`
- DB write 없음. `behavior_logs(source='vlm')`/Fly worker는 변경하지 않음.

## 17. 2026-05-26 local Track A 159건 평가

실행:

```bash
uv run python scripts/eval_local_track_a.py
```

결과 artifact:

- `storage/local-track-a/eval/local-track-a-eval.jsonl`
- `storage/local-track-a/eval/local-track-a-eval.summary.json`
- `storage/local-track-a/eval/artifacts/*.contact-sheet.jpg`
- `storage/local-track-a/eval/artifacts/*.local-track-a.json`

요약:

| 항목 | 결과 |
|---|---:|
| 평가셋 | 159 |
| 실패 | 0 |
| raw 정확도 | 62/159 = 38.994% |
| feeding-merged 정확도 | 65/159 = 40.881% |
| Gemini v3.5 feeding-merged floor | 85.5% |
| delta | -44.619%p |
| needs_review | 0/159 = 0.000% |
| latency avg / p50 / p95 / max | 20.02s / 12.96s / 52.47s / 97.03s |
| batch estimate | 50 clips 16.7m / 100 clips 33.4m |

예측 분포:

```text
moving 159/159 = 100.0%
```

GT별 raw 정확도:

```text
defecating    0/16 = 0.0%
drinking      0/11 = 0.0%
eating_paste  0/17 = 0.0%
eating_prey   0/19 = 0.0%
hiding        0/3  = 0.0%
moving       62/62 = 100.0%
shedding      0/29 = 0.0%
unseen        0/2  = 0.0%
```

판단:

- `gemma3:4b` + 1fps contact sheet 방식은 Gemini Track A 대체 불가.
- 품질 실패 원인은 "로컬 VLM이 행동 분류를 못 한다"기보다, 현재 prompt/input 조합에서 모든 motion clip을 `moving`으로 흡수하는 collapse.
- confidence도 0.95 고정에 가까워서 threshold fallback 기준으로 분리할 수 없다.
- 운영 배관은 성공: R2 read, frame sampling, contact sheet, Ollama JSON parse, JSONL resume 모두 정상.
- 장시간 batch 후반부에 latency tail이 커짐. thermal / swap / Ollama model state 관찰 필요.

Gemini fallback 초안:

- 현 상태의 `gemma3:4b` local 결과는 production label로 쓰지 않는다.
- `source='local_vlm'` INSERT도 아직 하지 않는다. artifact-only 유지.
- local result가 `moving`이어도 최종 확정하지 않고 Gemini 또는 human/GT 비교 대상으로 둔다.
- P0 후보(`drinking`, `defecating`, `shedding`, `eating_prey`)는 local 단독 판단 금지.
- 다음 후보는 아래 순서:
  1. `qwen2.5vl:7b` 같은 다른 local VLM 동일 평가.
  2. prompt에 "moving은 마지막 fallback" 규칙 강화.
  3. contact sheet 1장 대신 event crop / ROI / before-after pair 입력 비교.
  4. local은 "moving vs interesting/P0 candidate" binary gate로 축소할지 검토.

## 18. 2026-05-27 qwen2.5vl:7b 평가

목적:

- `gemma3:4b`가 `moving 159/159`으로 collapse했기 때문에 2차 후보 `qwen2.5vl:7b`를 같은 local Track A eval로 비교.

설치:

```bash
ollama pull qwen2.5vl:7b
ollama list
```

확인:

```text
qwen2.5vl:7b  6.0 GB
```

실험 과정:

1. 60프레임 / 320px contact sheet:
   - 첫 clip에서 180초 timeout.
   - M1 16GB에서 전체 159건 평가 조건으로 부적합.
2. 12프레임 / 320px contact sheet:
   - 5건 smoke: raw 4/5 = 80.0%.
   - 하지만 latency avg 83.28s, p95 132.87s, max 142.21s.
   - full run 중 일부 clip이 400~590초까지 튀고, 장시간 batch로 부적합.
3. 12프레임 / 160px contact sheet:
   - 5건 smoke: raw 4/5 = 80.0%.
   - full 159건 평가 완료.

최종 실행:

```bash
caffeinate -dimsu uv run python scripts/eval_local_track_a.py \
  --force \
  --model qwen2.5vl:7b \
  --max-frames 12 \
  --thumb-width 160 \
  --timeout-sec 300 \
  --out storage/local-track-a/eval/qwen2.5vl-7b-eval-12f-160w.jsonl \
  --artifact-dir storage/local-track-a/eval/qwen2.5vl-7b-eval-12f-160w-artifacts
```

결과 artifact:

- `storage/local-track-a/eval/qwen2.5vl-7b-eval-12f-160w.jsonl`
- `storage/local-track-a/eval/qwen2.5vl-7b-eval-12f-160w.summary.json`
- `storage/local-track-a/eval/qwen2.5vl-7b-eval-12f-160w-artifacts/`

요약:

| 항목 | 결과 |
|---|---:|
| 평가셋 | 159 |
| 실패 | 0 |
| raw 정확도 | 75/159 = 47.170% |
| feeding-merged 정확도 | 80/159 = 50.314% |
| Gemini v3.5 feeding-merged floor | 85.5% |
| delta | -35.186%p |
| needs_review | 17/159 = 10.692% |
| latency avg / p50 / p95 / max | 17.98s / 13.07s / 38.91s / 41.23s |
| batch estimate | 50 clips 15.0m / 100 clips 30.0m |

예측 분포:

```text
defecating     1/159 = 0.6%
drinking       8/159 = 5.0%
eating_paste   7/159 = 4.4%
eating_prey    3/159 = 1.9%
moving       124/159 = 78.0%
shedding      16/159 = 10.1%
```

GT별 raw 정확도:

```text
defecating      1/16 = 6.2%
drinking        2/11 = 18.2%
eating_paste    6/17 = 35.3%
eating_prey     2/19 = 10.5%
hiding          0/3  = 0.0%
moving         55/62 = 88.7%
shedding        9/29 = 31.0%
unseen          0/2  = 0.0%
```

판단:

- `qwen2.5vl:7b`는 `gemma3:4b`보다 명확히 낫다.
  - gemma: feeding-merged 40.881%, `moving 159/159`
  - qwen: feeding-merged 50.314%, 예측 분포 다양화
- 그래도 Gemini Track A baseline 85.5%에는 크게 못 미친다.
- local Track A 대체 후보로는 현재 입력/프롬프트 조합에서 실패.
- 속도는 12프레임/160px 조건이면 batch 운영 자체는 가능하다.
- P0 recall이 낮아 production label 확정에는 부적합.
- qwen 결과는 "local cheap label"보다 "interesting candidate / HITL routing 보조 신호"로 재해석하는 쪽이 맞다.

다음 후보:

1. Track A 대체 실험은 여기서 일단 보류. local VLM 단독 top-1은 기준 미달.
2. Track B / SegmentVLM 쪽으로 전환해 event crop + ROI + 짧은 구간 입력을 비교.
3. qwen은 full clip top-1 대신 binary gate로 재평가:
   - `boring_moving_or_unseen`
   - `interesting_p0_candidate`
4. confidence calibration은 믿지 않는다. qwen도 high confidence 오답이 많다.
