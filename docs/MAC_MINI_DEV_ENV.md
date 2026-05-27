# Mac mini 개발환경 세팅

> Mac mini M1 16GB/256GB를 `petcam-lab` local RBA worker로 쓰기 위한 개발환경 재현 문서. 기준 머신은 현재 맥북 개발환경이다.

**작성:** 2026-05-26  
**대상:** macOS Apple Silicon, 새로 세팅한 Mac mini  
**목표:** `petcam-lab` clone → Codex 작업 가능 → Ollama/local VLM smoke test → RBA worker 개발 가능

---

## 1. 결론

기존 문서에는 `uv`, `.env`, `ffmpeg` 정도만 있고, Node/npm/Java/Codex/Ollama까지 포함한 전체 개발환경 버전표는 없었다.

Mac mini는 새로 세팅한다. 전체 Mac 마이그레이션은 하지 않는다.

필수:
- Xcode Command Line Tools
- Homebrew
- Git
- uv
- ffmpeg
- jq
- tmux
- Codex CLI
- Ollama
- `petcam-lab` 레포

선택:
- Node/npm: `web/` 라벨링 UI나 Next.js 작업할 때 필요
- Java: 현재 worker에는 필요 없음. Android/Flutter 쪽 작업하거나 특정 도구가 요구할 때만 설치
- Claude CLI: Claude Code도 같이 쓸 때만 설치
- cloudflared/flyctl: 배포/터널 작업할 때만 설치

---

## 2. 현재 맥북 기준 버전

2026-05-26 현재 맥북에서 확인한 값:

| 도구 | 버전 / 상태 | 비고 |
|---|---|---|
| macOS | 26.2, build 25C56 | Apple Silicon |
| arch | `arm64` | Mac mini M1과 동일 계열 |
| Xcode path | `/Applications/Xcode.app/Contents/Developer` | CLT 또는 Xcode 필요 |
| Homebrew | 5.1.10 | `/opt/homebrew` |
| Python system/brew | 3.14.3 | `python3`는 brew 3.14를 봄 |
| Project Python | 3.12 | `.python-version`, `uv`가 3.12.13 설치 |
| uv | 0.11.7 | Homebrew |
| ffmpeg | 8.0.1 | brew package는 `8.0.1_4` |
| Node | 24.3.0 | `web/` 작업용 |
| npm | 11.4.2 | Node와 함께 설치 |
| Java runtime | OpenJDK 17.0.14 | `JAVA_HOME`, `java`, `javac`, `java_home`, Flutter 모두 17을 봄 |
| Java installed extras | OpenJDK 23.0.2 | `gradle` 의존성으로 설치되어 있으나 기본 JDK는 아님 |
| Codex CLI | 0.130.0 | `codex-cli 0.130.0` |
| Claude Code | 2.1.150 | 선택 |
| Ollama client | 0.18.2 | 서버 미실행 시 warning 가능 |
| cloudflared | 2026.3.0 | 선택 |

중요:
- 이 레포의 Python 기준은 `python3`가 아니라 **`uv` + `.python-version`의 Python 3.12**다.
- Mac mini에서는 brew Python 버전이 달라도 된다. `uv sync`가 프로젝트 Python을 맞춘다.
- Java는 현재 Mac mini RBA worker에는 필요 없다.

---

## 3. macOS 초기 설정

### 3.1 시스템 설정

1. macOS 최신 업데이트.
2. 새 로컬 계정 사용. 예: `baek` 또는 `petcam`.
3. 자동 잠자기 끄기.
   - System Settings → Lock Screen / Battery / Energy 관련 설정에서 장시간 작업 중 sleep 방지.
4. Remote Login 켜기.
   - System Settings → General → Sharing → Remote Login ON.
5. 필요하면 Screen Sharing도 켜기.
6. 공유기에서 Mac mini에 고정 DHCP IP를 준다.
   - 예: `192.168.0.xx`.
   - `mac-mini.local`도 가능하지만, worker 운영은 고정 IP가 더 안정적이다.

### 3.2 Xcode Command Line Tools

```bash
xcode-select --install
xcode-select -p
```

정상 예:

```text
/Library/Developer/CommandLineTools
```

전체 Xcode를 설치한 경우 `/Applications/Xcode.app/Contents/Developer`여도 괜찮다.

---

## 4. Homebrew 설치

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Apple Silicon에서는 보통 `/opt/homebrew`에 설치된다.

쉘 설정:

```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
brew --version
```

---

## 5. 필수 도구 설치

```bash
brew install git uv ffmpeg jq tmux
```

확인:

```bash
git --version
uv --version
ffmpeg -version | sed -n '1p'
jq --version
tmux -V
```

기대:
- `uv`는 0.11.x 이상이면 충분.
- `ffmpeg`는 8.x면 현재 맥북과 유사.

---

## 6. 선택 도구 설치

### 6.1 Node/npm

`web/` 라벨링 웹이나 Next.js API route를 건드릴 때 필요하다.

현재 맥북은 brew Node 24.3.0 / npm 11.4.2다. Mac mini는 아래처럼 brew 최신 Node를 설치하면 된다.

```bash
brew install node
node --version
npm --version
```

`web/package.json` 기준:
- Next.js `14.2.35`
- React 18
- TypeScript 5
- `package-lock.json` 있음

웹 의존성 설치:

```bash
cd /Users/baek/dev/petcam-lab/web
npm ci
npm run build
```

Mac mini local RBA worker만 개발한다면 Node는 나중에 설치해도 된다.

### 6.2 Java

현재 `petcam-lab` backend/local worker에는 Java가 필요 없다.

그래도 현재 맥북과 맞춰두고 싶으면 OpenJDK 17만 기본 JDK로 잡는다.

```bash
brew install openjdk@17
mkdir -p "$HOME/Library/Java/JavaVirtualMachines"
ln -sfn /opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk \
  "$HOME/Library/Java/JavaVirtualMachines/openjdk-17.jdk"

echo 'export JAVA_HOME="$HOME/Library/Java/JavaVirtualMachines/openjdk-17.jdk/Contents/Home"' >> ~/.zshrc
echo 'export PATH="$JAVA_HOME/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

java -version
javac -version
/usr/libexec/java_home -V
```

주의:
- 현재 맥북에는 `gradle` 의존성 때문에 `openjdk` 23도 설치되어 있지만, 기본 JDK는 17로 고정했다.
- Java는 나중에 Flutter/Android 빌드나 특정 도구가 요구할 때 다시 정리하는 게 낫다.

### 6.3 cloudflared / flyctl

Mac mini local worker만 돌릴 때는 필요 없다.

터널/배포 작업까지 할 경우:

```bash
brew install cloudflared flyctl
cloudflared --version
fly version
```

---

## 7. Codex / AI 도구

### 7.1 Codex CLI

이미 같은 계정으로 Codex 에이전트를 설치했다면 먼저 확인한다.

```bash
codex --version
which codex
```

현재 맥북 기준:

```text
codex-cli 0.130.0
```

Codex는 프로젝트 루트의 `AGENTS.md`를 읽는다. Mac mini에서도 같은 레포를 clone하면 프로젝트 규칙이 따라온다.

### 7.2 Claude Code

선택이다. Mac mini에서 Claude도 같이 쓸 때만 설치/로그인한다.

```bash
claude --version
```

현재 맥북 기준:

```text
2.1.150 (Claude Code)
```

---

## 8. Ollama 설치

Ollama는 local VLM 실행용이다.

1. Ollama macOS 앱을 설치한다.
2. 앱을 한 번 실행한다.
3. 터미널에서 확인한다.

```bash
ollama --version
ollama list
```

현재 맥북 클라이언트 기준:

```text
client version is 0.18.2
```

모델 설치:

```bash
ollama pull gemma3:4b
ollama list
```

2차 후보는 나중에:

```bash
ollama pull qwen2.5vl:7b
```

주의:
- `ollama --version`에서 서버 미실행 warning이 떠도, 앱/서버를 켜면 된다.
- Mac mini 256GB라 모델을 무작정 많이 받지 않는다.

---

## 9. 레포 세팅

새 레포 만들지 말고 `petcam-lab`를 clone한다.

```bash
mkdir -p /Users/baek/dev
cd /Users/baek/dev
git clone <petcam-lab-git-url> petcam-lab
cd petcam-lab
```

프로젝트 파일 확인:

```bash
ls AGENTS.md CLAUDE.md README.md pyproject.toml uv.lock .python-version
ls .codex .agents .claude
```

Python 환경:

```bash
uv sync
uv run python --version
uv run pytest -q
```

기대:

```text
Python 3.12.x
```

테스트가 secret 부족이나 외부 환경 때문에 깨지면, 먼저 smoke test로 좁힌다.

```bash
uv run python -c "import cv2; import fastapi; import supabase; print('ok')"
```

---

## 10. 환경변수

```bash
cp .env.example .env
```

`.env`는 직접 채운다. 절대 Git에 올리지 않는다.

Mac mini local worker에 필요한 값:

```bash
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET_NAME=...
CAMERA_SECRET_KEY=...

LOCAL_RBA_WORKER_MODEL=gemma3:4b
LOCAL_RBA_WORKER_MODE=artifact
SLACK_WEBHOOK_URL=...
```

기존 환경변수 전체 설명은 [ENV.md](ENV.md)를 따른다.

주의:
- Slack webhook URL은 비밀값이다.
- Supabase service role은 DB 전체 권한이다.
- R2 secret은 bucket 접근 권한이다.
- 이 값들은 채팅/문서/Git에 붙이지 않는다.

---

## 11. 첫 smoke test 순서

Mac mini에서 순서대로 확인한다.

```bash
# 1. 기본 도구
brew --version
uv --version
ffmpeg -version | sed -n '1p'
codex --version

# 2. 프로젝트 Python
cd /Users/baek/dev/petcam-lab
uv run python --version
uv run python -c "import cv2; print(cv2.__version__)"

# 3. Ollama
ollama list
ollama run gemma3:4b "Say ok in one word."

# 4. Slack webhook, .env 로드 후
source .env
curl -X POST -H 'Content-type: application/json' \
  --data '{"text":"petcam Mac mini 개발환경 smoke test"}' \
  "$SLACK_WEBHOOK_URL"
```

이미지/VLM smoke test는 다음 단계에서 별도 스크립트로 만든다.

---

## 12. Mac mini Codex에게 줄 프롬프트

```text
/Users/baek/dev/petcam-lab/AGENTS.md,
/Users/baek/dev/petcam-lab/docs/MAC_MINI_DEV_ENV.md,
/Users/baek/dev/petcam-lab/specs/feature-mac-mini-local-track-a-worker.md
를 먼저 읽어.

이 Mac mini는 M1 16GB/256GB이고, 목적은 Gemini Track A를 대체할 local RBA worker야.
새 레포 만들지 말고 petcam-lab 안에서 진행해.
production fly.io worker와 behavior_logs(source='vlm')는 아직 건드리지 마.

먼저 개발환경을 이 문서 기준으로 점검하고,
부족한 도구 설치 → uv sync → Ollama gemma3:4b smoke test → Slack smoke test까지 진행해.
비밀값은 .env에만 넣고 Git에 올리지 마.
```

---

## 13. 문제 해결

### `uv run python`이 3.12가 아니다

```bash
cat .python-version
uv python install 3.12
uv sync
uv run python --version
```

### `ffmpeg`가 없다

```bash
brew install ffmpeg
which ffmpeg
```

### `cv2` import 실패

```bash
uv sync
uv run python -c "import cv2; print(cv2.__version__)"
```

OpenCV는 `pyproject.toml`의 `opencv-contrib-python-headless`로 들어온다.

### Ollama 서버 연결 실패

```bash
open -a Ollama
ollama list
```

### Slack 알림이 안 온다

```bash
echo "$SLACK_WEBHOOK_URL"
curl -X POST -H 'Content-type: application/json' \
  --data '{"text":"slack test"}' \
  "$SLACK_WEBHOOK_URL"
```

URL을 채팅이나 Git에 붙이지 않는다.

### Java 버전이 이상하다

Mac mini local worker에는 Java가 필요 없다. Android/Flutter 작업이 아니라면 무시해도 된다.

필요할 때만:

```bash
brew install openjdk@17
export PATH="/opt/homebrew/opt/openjdk@17/bin:$PATH"
java -version
```
