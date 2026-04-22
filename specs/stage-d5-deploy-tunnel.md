# Stage D5 — Cloudflare Tunnel 배포 + AUTH_MODE=prod 전환

> 로컬에서만 돌던 petcam-lab 백엔드를 **외부망 공개**하고, **AUTH_MODE=prod** 로 전환해 JWT 검증을 실전 활성화한다. Stage D 의 마지막 서브. 이후 테스터 5명 이하 베타 단계 진입.

**상태:** 🚧 진행 중
**작성:** 2026-04-22
**연관 SOT:** `../../tera-ai-product-master/docs/specs/petcam-backend-dev.md` — Stage D 배포 섹션
**연관 로드맵:** [`stage-d-roadmap.md`](stage-d-roadmap.md) — 결정 1 (Cloudflare Tunnel), 오픈 이슈 cloudflared 설치 / 잠자기 방지

---

## 1. 목적

- **사용자 가치**: Flutter 앱이 LTE/외부 Wi-Fi 에서도 백엔드에 접근 가능 → 실사용 시나리오 검증. 지금까진 같은 Wi-Fi 안에서만 동작.
- **보안 상향**: 백엔드가 공용 인터넷에 노출되므로 `AUTH_MODE=dev` 는 불가 → JWT 검증 실전 진입. "아무 DEV_USER_ID 로나 접근" 경로 차단.
- **학습 목표**: 역방향 터널 동작 원리, `cloudflared` CLI, 맥북 상시 가동 설정, JWKS 기반 JWT 검증 E2E 검증, iOS ATS 와 HTTPS 강제.

---

## 2. 스코프

### In (이번 스펙에서 한다)

- **Quick Tunnel 찍먹** (체크포인트 1, 10분컷)
  - `brew install cloudflared`
  - `cloudflared tunnel --url http://localhost:8000` 으로 임시 URL 받기
  - iPhone LTE 에서 `https://<random>.trycloudflare.com/health` 접속 성공 확인
  - 원리 체감 후 바로 종료 (상시 운영 아님)
- **Named Tunnel 상시 운영 구성**
  - `cloudflared tunnel login` (Cloudflare 계정 연동)
  - `cloudflared tunnel create petcam-lab` → 터널 UUID + 인증서 생성
  - 고정 URL 부여 (**도메인 있으면** `api.{domain}` DNS CNAME, **없으면** Quick Tunnel 모드 유지하고 URL 은 주기 교체)
  - `~/.cloudflared/config.yml` 작성
  - `cloudflared tunnel run petcam-lab` 백그라운드 실행 (`launchd` plist 옵션 포함)
- **Wi-Fi 이동 동작 확인** — 집/카페/테더링 등 네트워크 바뀌어도 `cloudflared tunnel run` 한 줄로 동일 URL 재연결되는지 검증
- **AUTH_MODE=prod 전환**
  - `.env` 에 `AUTH_MODE=prod` 전환 (기존 `dev` 는 주석으로 보관)
  - `SUPABASE_JWKS_URL` 환경변수 검증 (JWKS 엔드포인트 실제 응답 확인)
  - curl 수동 JWT 로 `/clips` 통과 + JWT 없음 시 401 확인
  - Flutter 앱 BACKEND_URL 교체 후 E2E smoke test
- **보안 최소 체크**
  - 로그 비밀번호/토큰 마스킹 확인 (Stage D1 이미 구현, 회귀 없음 검증)
  - Cloudflare Tunnel 이 HTTPS 강제 → iOS ATS 예외 필요 없음 확인
  - 백엔드 바인딩: `uvicorn --host 127.0.0.1` (외부 직접 노출 차단, Tunnel 만 경유)
- **문서 / 회귀**
  - `README.md` 배포 섹션 추가 (cloudflared 실행 방법 + 잠자기 방지)
  - `.env.example` 에 `AUTH_MODE=prod` 주석 + `SUPABASE_JWKS_URL` 기록
  - `specs/README.md` + `stage-d-roadmap.md` D5 ✅ 반영
  - `pytest -q` 전수 통과 (회귀 없음)
  - `.claude/donts-audit.md` D5 한 줄 추가

### Out (이번 스펙에서 **안 한다**)

- **24시간 상시 가동 보장** — 테스트 단계는 **수동 가동 전제**. 사용자가 맥북 켜고 `cloudflared tunnel run` 실행할 때만 서버 접근 가능. 앱은 `/health` ping 실패 시 "서버 대기 중" UX 필요 (Flutter 차기 과제).
- **커스텀 도메인 구매** — 필요하면 별도 결정. 없어도 `*.trycloudflare.com` 또는 `*.cfargotunnel.com` 로 충분.
- **Cloudflare Access (Zero Trust 인증 레이어)** — 테스터 5 명 이하엔 과잉. JWT 검증만으로 충분.
- **CORS 미들웨어 추가** — Flutter Web 배포는 별도 스테이지. iOS/Android 네이티브는 CORS 무관.
- **Cloudflare WAF 룰 / Rate Limit 커스텀** — 무료 플랜 기본값으로 충분. 트래픽 이슈 생기면 재평가.
- **모니터링 대시보드 / Slack 알림** — Stage E 이후 관측성 과제.
- **맥북 하드웨어 이중화 / failover** — 상용 단계 재설계.
- **Flutter 쪽 401 인터셉터 구현** — `docs/flutter-handoff-d5-auth.md` 요청 사항, Flutter 에이전트 담당.
- **라이브 스트리밍 (WebRTC/HLS)** — 현재는 녹화본 재생만. Stage F 이후.
- **카메라 삭제 시 파일 cleanup job** — 로드맵 오픈 이슈, Stage E retention.
- **다중 맥북 분산 캡처** — Stage E 이후 스케일링.

> **스코프 변경은 합의 후에만.** 작업 중 In/Out 흔들리면 본 섹션 수정 + 사유 기록.

---

## 3. 완료 조건

체크리스트가 곧 진행 상태.

### 3.1 Quick Tunnel 체크포인트 (찍먹)

- [ ] `brew install cloudflared` 설치 + `cloudflared --version` 출력 확인
- [ ] `cloudflared tunnel --url http://localhost:8000` 실행 → `https://<random>.trycloudflare.com` URL 출력 확인
- [ ] iPhone LTE (Wi-Fi 끈 상태)에서 해당 URL + `/health` 접속 → JSON 200 응답 확인
- [ ] 원리 체감 후 터미널 Ctrl+C 로 종료

### 3.2 Named Tunnel 상시 운영

- [ ] `cloudflared tunnel login` 브라우저 OAuth 완료 (Cloudflare 계정 연결)
- [ ] `cloudflared tunnel create petcam-lab` 실행 → 터널 UUID + credentials json 파일 생성 확인
- [ ] `~/.cloudflared/config.yml` 작성 (tunnel id, ingress rule, credentials 경로)
- [ ] `cloudflared tunnel run petcam-lab` 실행 → 외부 URL 정상 라우팅 확인
- [ ] 고정 URL 획득 (도메인 있으면 `api.{domain}`, 없으면 `<uuid>.cfargotunnel.com` 또는 Quick Tunnel 유지)
- [ ] (선택) `launchd` plist 로 자동 시작 등록 (`~/Library/LaunchAgents/com.cloudflared.petcam.plist`)

### 3.3 Wi-Fi 이동 동작

- [ ] 집 Wi-Fi 에서 `cloudflared tunnel run petcam-lab` 실행 → 외부 URL `/health` 정상 응답
- [ ] 다른 네트워크 (카페 Wi-Fi / 폰 테더링) 에서 맥북 이동 후 동일 명령 재실행 → **같은 URL** 로 정상 응답
- [ ] 서버 종료 시 앱에서 `/health` 실패 → 클라이언트가 네트워크 오류로 인식 확인 (차후 "서버 대기 중" UX 개선은 Out)

### 3.4 AUTH_MODE=prod 전환

- [ ] `.env` 에 `AUTH_MODE=prod` 설정 + `SUPABASE_JWKS_URL` 확인
- [ ] 서버 재시작 → lifespan 로그 `AUTH_MODE=prod` 표시 확인
- [ ] `curl $URL/clips` (JWT 없이) → 401 응답 확인
- [ ] 수동 JWT 발급 (`curl -X POST .../auth/v1/token?grant_type=password`) → 받은 토큰으로 `/clips` 호출 → 200 확인
- [ ] JWT 만료/위조 토큰 → 401 응답 확인
- [ ] 기존 dev 모드 데이터 연속성 확인 (현재 `DEV_USER_ID` 가 본인 `auth.users.id` 와 동일)

### 3.5 Flutter E2E (Flutter 쪽 401 인터셉터 완료 후)

- [ ] Flutter `.env` BACKEND_URL 을 Cloudflare URL 로 교체
- [ ] 로컬 Wi-Fi: 로그인 → 카메라 등록 → 녹화 대기 → 클립 재생 → 썸네일 로드 전부 성공
- [ ] LTE (Wi-Fi 끈 상태): 동일 E2E 전부 성공
- [ ] 로그아웃 상태에서 `/my-cage` 접근 → `/login` redirect 확인
- [ ] 앱 종료 → 재시작 → 자동 로그인 유지 확인

### 3.6 보안 / 회귀

- [ ] `backend/capture.py` 로그에 비밀번호/JWT 평문 없음 재확인
- [ ] uvicorn 바인딩 `127.0.0.1:8000` (외부 직접 노출 차단) — Tunnel 만 경유
- [ ] `pytest -q` 전수 통과 (회귀 없음)
- [ ] `README.md` 배포 섹션 추가
- [ ] `.env.example` 주석 갱신
- [ ] `specs/README.md` + `stage-d-roadmap.md` D5 → ✅
- [ ] `.claude/donts-audit.md` 한 줄 추가

---

## 4. 설계 메모

### 선택한 방법

- **Cloudflare Tunnel (Named)** — 로드맵 결정 1. Quick Tunnel 은 찍먹 전용, 상시는 Named.
- **AUTH_MODE 환경변수 스위치** — Stage D1 이미 구현. `.env` 한 줄 교체로 롤백 용이.
- **수동 가동 전제** — 맥북 24시간 상시 켜두지 않음. 사용자가 시연·테스트 시점에만 `cloudflared tunnel run` 실행. Wi-Fi 이동 자유.

### 고려했던 대안

- **ngrok** — 무료 URL 매번 바뀜 + 고정은 월 $8. Cloudflare 가 더 낫다 (무료 고정 가능).
- **Tailscale** — 테스터도 Tailscale 설치 필요 → 베타 사용자 요구 허들.
- **클라우드 배포 (Render/Fly)** — 월 $5+, 근본적으로 RTSP 소스가 집에 있어 맥북 서버 여전히 필요 = 이중 운영.
- **포트 포워딩** — 공유기 설정 + 공용 IP 가변 + 보안 무방비.

### 전환 순서 (중요)

```
1. Flutter 쪽 401 인터셉터 + video_player/CachedNetworkImage authHeaders 주입 완료 확인
    ↑ (Flutter 에이전트 응답 대기)
2. Quick Tunnel 로 외부 접근 체감 (AUTH_MODE=dev 유지, 토큰 없이도 통과)
3. Named Tunnel 구성 (고정 URL)
4. AUTH_MODE=prod 전환 — 여기서부터 JWT 필수
5. 수동 JWT + curl 로 백엔드만 검증
6. Flutter BACKEND_URL 교체 → E2E
```

순서 뒤집으면 "Flutter 에서 영상 안 뜸" 같은 혼란스런 실패가 날 수 있음. **Flutter 준비 완료 신호를 먼저 받는 게 전제.**

### Named Tunnel 인증 흐름

```
[ 맥북 ]
  │ cloudflared tunnel login
  ▼
[ 브라우저 ]
  │ Cloudflare 계정 OAuth
  │ 도메인 선택 (없으면 건너뛰기)
  ▼
[ Cloudflare ]
  │ 인증서 (cert.pem) 발급
  ▼
[ 맥북 ~/.cloudflared/cert.pem ]
  │ tunnel create 시 이 cert 로 인증
  ▼
[ 터널 UUID + credentials.json 생성 ]
```

### `config.yml` 구조 초안

```yaml
tunnel: <터널-UUID>
credentials-file: /Users/baek/.cloudflared/<UUID>.json
ingress:
  - hostname: api.example.com       # 도메인 있을 때
    service: http://localhost:8000
  - service: http_status:404         # 매칭 안 되는 요청은 404
```

도메인 없을 땐 `hostname` 생략하고 `cloudflared tunnel route dns` 명령어 자체를 스킵. 대신 `cloudflared tunnel run --url http://localhost:8000 <tunnel-name>` 식으로 Quick 모드와 Named 를 결합.

### Wi-Fi 이동 시 동작 (Cloudflare Tunnel 특성)

Cloudflare Tunnel 은 맥북 → 엣지 **outbound** 연결. 따라서:

- Wi-Fi 바뀌어도 cloudflared 가 자동 재연결 → **같은 URL 유지**
- 공유기 포트포워딩 불필요 (어느 네트워크든 outbound 통과)
- 결과: 집·카페·테더링 어디서든 맥북 켜고 `cloudflared tunnel run` 한 줄이면 접속 가능

이 특성 덕에 "수동 가동 전제" 가 실전 시연 시나리오에 충분. 24시간 상시 가동 없이도 테스터·데모 대응 가능.

### Flutter 쪽 주의 (참고)

- Cloudflare URL 은 HTTPS — iOS ATS 자동 통과. 별도 `NSAppTransportSecurity` 설정 불필요.
- 기존에 `http://192.168.x.x:8000` 같은 HTTP LAN 용 예외가 `Info.plist` 에 있으면 제거 권장 (더 이상 필요 없음, 보안 감소).

### 기존 구조와의 관계

- **영향 받는 파일**: `.env`, `.env.example`, `README.md`. 코드 변경 거의 없음 (AUTH_MODE 스위치는 D1 에서 이미 구현).
- **lifespan 로그**: `backend/main.py` startup 에서 `AUTH_MODE` 값 출력 권장 (운영 디버깅용).
- **health endpoint**: `/health` 는 JWT 요구 안 함 → Tunnel 헬스체크 + 앱 ping 에 사용.
- **CORS**: 미적용 유지 (Flutter 네이티브만 대상). Web 지원 시 별도 추가.

### 리스크 / 미해결 질문

- **도메인 소유 여부** — 사용자가 `*.tera-ai.kr` 같은 도메인을 가지고 있는지 확인 필요. 없으면 `*.trycloudflare.com` 또는 `<uuid>.cfargotunnel.com` 로 유지 (고정 URL).
- **cloudflared 프로세스 관리** — 수동 가동 전제이므로 `launchd` 자동 시작은 불필요. 매번 터미널에서 실행 → Ctrl+C 종료. `tmux` 또는 백그라운드 & 로 돌려도 됨.
- **AUTH_MODE 전환 시점의 기존 클립 데이터** — `DEV_USER_ID` 로 저장된 카메라/클립이 실제 로그인 유저 UUID 와 동일해야 연속성 유지. 현재 `DEV_USER_ID=380d97fd-...` = 사용자 본인 계정.
- **Cloudflare 무료 플랜 제한** — 대역폭/요청 수에 공식 상한 없지만 "abuse" 로 판단되면 제한. 5 명 규모엔 무관.
- **Quick Tunnel URL 변경 사이클** — Quick Tunnel 은 세션마다 URL 이 새로 생성됨. Named 없이 쓰면 Flutter `.env` 매번 갱신 = 지옥. Named 로 가야 운영 가능.
- **JWKS 캐시 로테이션** — Supabase 가 키 로테이션 하면 백엔드 캐시 TTL(10분) 만큼 지연. 테스터 규모엔 수용 가능.
- **서버 off 상태 앱 UX** — 맥북 꺼져있으면 앱 API 호출 전부 실패 (네트워크 오류). Flutter 쪽에서 "서버 대기 중" 안내 UI 는 별도 과제 (본 스펙 Out).

---

## 5. 학습 노트

### 핵심 개념

- **역방향 터널 (Reverse Tunnel)** — 내 맥북이 **먼저 Cloudflare 엣지로 outbound 연결**. 이후 외부 요청은 엣지 → 역방향 파이프 → 내 맥북. 공유기 포트포워딩 불필요. 대부분의 공유기가 outbound 허용하므로 무설정 통과.
- **`cloudflared` 데몬 역할** — 로컬 CLI 도구 겸 엣지와 연결 유지하는 프로세스. 맥북에서 24시간 동작 필요.
- **Quick Tunnel vs Named Tunnel** — Quick 은 익명 세션 URL 매번 랜덤, Named 는 계정 연결로 고정 URL/도메인 할당. 개발 단계 Quick → 운영 Named 순서.
- **JWKS (JSON Web Key Set)** — Supabase 가 `/.well-known/jwks.json` 에서 공개키 JSON 배열 제공. 백엔드는 JWT `kid` 헤더로 해당 공개키 선택 → RS256 서명 검증. 비밀키는 Supabase 만 가짐.
- **iOS ATS (App Transport Security)** — iOS 9+ 기본 HTTPS 강제 정책. HTTP 요청은 `NSAppTransportSecurity` 예외 선언 필요. Cloudflare 는 HTTPS 자동이라 예외 불필요.

### JS/TS 비유

- **Cloudflare Tunnel** = ngrok 과 같은 카테고리 (로컬 서버 → 공용 URL), 다만 **무료 + 고정 URL** 이 가능. Node 에서 `npx ngrok http 8000` 대응 = `cloudflared tunnel --url http://localhost:8000`.
- **`cloudflared` 데몬** = PM2 가 Node 앱 관리하듯 Cloudflare 가 터널 프로세스 관리. `launchd` plist = `pm2 startup` + `pm2 save` 대응.
- **JWKS** = Node `jose` 라이브러리의 `createRemoteJWKSet(url)` 과 같은 개념. 백엔드는 공개키 캐시로 서명 검증만.
- **AUTH_MODE 스위치** = Node 앱의 `process.env.NODE_ENV === 'development'` 분기 패턴.

### 명령어 치트시트

```bash
# 설치
brew install cloudflared
cloudflared --version

# Quick Tunnel (찍먹)
cloudflared tunnel --url http://localhost:8000

# Named Tunnel 세팅 (최초 1회)
cloudflared tunnel login                    # 브라우저 OAuth
cloudflared tunnel create petcam-lab        # 터널 생성
cloudflared tunnel list                     # 목록 확인
cloudflared tunnel route dns petcam-lab api.example.com  # 도메인 연결 (선택)

# 서버 가동 시마다 (수동)
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000  # 새 터미널 1
cloudflared tunnel run petcam-lab                              # 새 터미널 2

# 백엔드 바인딩 변경 (외부 직접 차단)
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000

# AUTH_MODE=prod 수동 JWT 테스트
curl -X POST "$SUPABASE_URL/auth/v1/token?grant_type=password" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email":"arthur@kang-sters.com","password":"..."}'

# 받은 access_token 으로 백엔드 호출
curl -H "Authorization: Bearer eyJ..." https://api.example.com/clips
```

---

## 6. 참고

### petcam-lab 내부

- 로드맵: [`stage-d-roadmap.md`](stage-d-roadmap.md) — 결정 1 (Cloudflare Tunnel 선택 사유), 오픈 이슈 cloudflared 설치 / 잠자기 방지
- D1: [`stage-d1-auth-crypto.md`](stage-d1-auth-crypto.md) — AUTH_MODE 스위치 구현 + JWKS 검증 로직
- 학습 노트: [`../docs/stage-d5-tunnel-learning.md`](../docs/stage-d5-tunnel-learning.md) — NAT / 역방향 터널 / Cloudflare vs ngrok 비교
- Flutter 준비 요청: [`../docs/flutter-handoff-d5-auth.md`](../docs/flutter-handoff-d5-auth.md) — 401 인터셉터 / BACKEND_URL 교체
- Flutter 가이드: [`../docs/flutter-handoff.md`](../docs/flutter-handoff.md) — 전반 인수인계

### 외부 자료

- Cloudflare Tunnel 공식: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
- Cloudflare Tunnel (Named) 튜토리얼: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/create-remote-tunnel/
- Supabase JWT 검증: https://supabase.com/docs/guides/auth/jwts
- iOS ATS 가이드: https://developer.apple.com/documentation/bundleresources/information_property_list/nsapptransportsecurity

### 연관 SOT

- `../../tera-ai-product-master/docs/specs/petcam-backend-dev.md` — Stage D 배포 섹션
