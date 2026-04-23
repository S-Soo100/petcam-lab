# Stage D5 준비 — Cloudflare Tunnel 교육자료 (쉬운 버전)

> D5 착수 전에 개념부터 확실히. **NAT · reverse tunnel · HTTPS · 자동시작** 을 비유 위주로.
> 이 문서만 읽어도 "왜 이 방식인가" 를 설명할 수 있게 하는 게 목표.

## TL;DR (5줄)

1. 지금 Flutter 앱은 **같은 Wi-Fi 에 있을 때만** 맥북 서버에 붙을 수 있다. 카페 4G 에선 불가.
2. 공유기 NAT 방화벽 때문에 외부에서 맥북 안으로 직접 들어올 수 없다. 이게 **모든 가정용 네트워크의 기본**.
3. 해결: **맥북이 먼저 Cloudflare 에 "파이프"를 연다 (outbound)** → 외부 요청이 그 파이프로 역전송됨.
4. 이걸 **Reverse Tunnel** 이라 함. Cloudflare Tunnel 은 공짜 + HTTPS 자동 + 대역폭 무제한.
5. D5 에서 실제 할 일: `cloudflared` 설치 → 맥북 자동 기동 → Flutter 앱의 `BACKEND_URL` 을 HTTPS URL 로 교체.

## 우선순위

| # | 주제 | 읽어야 할 이유 |
|---|------|---------------|
| 1 | [왜 지금 상태론 부족한가](#1-왜-지금-상태론-부족한가) | 현재 한계 구체화 |
| 2 | [NAT 와 방화벽 기본 개념](#2-nat-와-방화벽-기본-개념) | 모든 얘기의 전제 |
| 3 | [3가지 해결책 비교](#3-방패-뚫는-3가지-방식) | 왜 다른 거 말고 CF Tunnel 인지 |
| 4 | [Reverse Tunnel 작동 원리](#4-reverse-tunnel-작동-원리) | 이거 하나만 이해하면 나머지 쉬움 |
| 5 | [Cloudflare vs ngrok](#5-cloudflare-vs-ngrok) | 왜 CF 인지 근거 |
| 6 | [Quick vs Named Tunnel](#6-quick-tunnel-vs-named-tunnel) | 개발용 · 프로덕션용 분리 |
| 7 | [D5 에서 실제 할 일](#7-d5-에서-실제-할-일) | 체크리스트 프리뷰 |
| 8 | [보안 선결 과제](#8-보안-선결-과제--prod-모드-전환) | ⚠️ 이거 안 하면 사고 |

---

## 1. 왜 지금 상태론 부족한가

### 현재 Flutter 앱 접속 표

| 시나리오 | 접속 가능? | 이유 |
|---------|-----------|------|
| 같은 Wi-Fi 의 맥북 브라우저 | ✅ | `localhost:8000` |
| 같은 Wi-Fi 의 아이폰 Safari | ✅ | `192.168.219.105:8000` (LAN) |
| 카페/지하철 4G 의 아이폰 | ❌ | 외부 인터넷에서 맥북 못 찾음 |
| 친구네 집 Wi-Fi 아이폰 | ❌ | 다른 네트워크 |
| iOS **릴리즈 빌드** (HTTPS 강제) | ❌ | `http://` 는 ATS 차단 |

**프로덕트 배포 = 사용자 누구나, 어디서나, 언제든 접속 가능** → 위 표의 **3~5행을 다 ✅ 로** 만들어야 함.

### 구체적 요구사항
- **공인 URL**: 카페에서도 `https://xxx.com` 하면 우리 맥북이 응답
- **HTTPS**: iOS ATS · 심사 통과
- **IP 변경 내성**: 공유기 재부팅 / 다른 Wi-Fi 로 맥북 이동해도 URL 유지
- **무료 or 저비용**: 개인 프로젝트 단계

→ **Cloudflare Tunnel** 이 이 4가지 전부 만족.

---

## 2. NAT 와 방화벽 기본 개념

### 집 네트워크 구조
```
          [공인 IP = 211.x.x.x]
                   │
         ┌─────────┴─────────┐
         │      공유기        │   ← 방패 역할
         │   (NAT + 방화벽)   │
         └────┬──────────────┘
              │
      [사설 IP = 192.168.x.x]
              │
        ┌─────┴──────┐
        │    맥북     │  ← 당신의 서버
        │  (8000번)   │
        └────────────┘
```

### 공유기가 하는 "방패" 의 정체
1. **NAT (Network Address Translation)**: 여러 집안 기기(맥북·폰·TV) 가 **공인 IP 하나** 를 공유. 바깥은 "이 집" 까지만 알고, 안의 어떤 기기인진 모름.
2. **방화벽 inbound 차단**: 외부 → 내부 방향 연결은 기본적으로 전부 drop. 내부 → 외부 (당신이 유튜브 보는 것) 는 허용.

### 왜 이렇게 설계됐나?
- 1990년대 IPv4 고갈 → NAT 로 공인 IP 1개를 수십 기기가 공유
- 부수 효과: 외부에서 집안 기기 직접 스캔 불가 → **의도치 않은 보안 효과**
- 현재 가정용 인터넷 99% 가 이 구조

### 이게 우리 발목을 잡는 이유
```
[카페 아이폰]  →  http://211.x.x.x:8000  →  [공유기] → ???
                                                 │
                                       "8000번 요청? 어느 기기?
                                        매핑 규칙 없어서 drop."
```

---

## 3. 방패 뚫는 3가지 방식

| 방식 | 요약 | 우리 목적 적합성 |
|------|------|-----------------|
| **A. 포트 포워딩** | 공유기 설정에서 "외부 8000 → 내부 맥북 8000" 규칙 추가 | ❌ 공인 IP 수시 변경, HTTPS 따로 필요, 보안 노출 |
| **B. VPN 망** | 폰과 맥북을 가상 사설망에 같이 넣음 | ❌ 사용자 폰마다 VPN 설치 강요 — 상용 불가 |
| **C. Reverse Tunnel** ⭐ | 맥북이 외부로 먼저 파이프 염. 외부 요청이 그 파이프로 역전송 | ✅ 방화벽 무수정, HTTPS 자동, URL 고정 |

### 각 방식 자세히

**A. 포트 포워딩 (Port Forwarding)**
- 공유기 관리 페이지 접속 → "NAT → 포트 포워드" → 규칙 입력
- 공인 IP 바뀌면 DDNS (dynamic DNS) 도 붙여야 함
- HTTPS 인증서는 Let's Encrypt 로 따로 세팅
- 보안: 서버 취약점이 그대로 외부 노출
- **누가 쓰나**: 자가서버 운영 경력자, IoT 개발자

**B. VPN (Tailscale, ZeroTier 등)**
- 디바이스마다 앱 설치 + 계정 로그인 → 같은 가상 네트워크
- **내 디바이스만 접근** 하면 최고 (집 NAS 에 외부에서 접근 등)
- **사용자 배포형 앱** 엔 부적합 — 남의 폰에 VPN 강요 못 함
- **누가 쓰나**: 원격근무 팀 내부 리소스 접근, 개인 홈랩

**C. Reverse Tunnel (Cloudflare Tunnel, ngrok 등)**
- **맥북에서 데몬 1개 실행** → 외부 터널 서비스로 상시 연결 유지
- 외부 요청이 그 연결을 통해 내부로 전달
- 사용자는 HTTPS URL 만 알면 됨 — 아무 앱도 설치 불필요
- **누가 쓰나**: SaaS/웹앱 개발자, 우리 상황에 딱

---

## 4. Reverse Tunnel 작동 원리

### 그림 한 장으로

```
[카페 아이폰]
     │ HTTPS 요청: GET /health
     ▼
┌─────────────────────────────────┐
│   Cloudflare 엣지 (전세계 300+)  │
│                                  │
│   xyz.trycloudflare.com 이 들어오면
│   → 해당 터널 파이프로 전달       │
└──────────┬──────────────────────┘
           │
           │  ← 이 파이프는 "맥북이 먼저 연 outbound 연결"
           │     공유기는 나가는 연결은 막지 않음
           │
           ▼
    [맥북의 cloudflared 데몬]
           │
           │  → http://localhost:8000 으로 전달
           ▼
    [FastAPI uvicorn]
           │
           │  응답을 같은 경로로 역전송
           ▼
       (사용자 폰까지 도달)
```

### 핵심 포인트 3가지
1. **맥북 → CF 방향** 연결은 공유기가 "유튜브 보는 것" 과 동일하게 허용 → 방화벽 설정 0개.
2. **CF 엣지** 가 HTTPS 종단 → 인증서 관리 불필요, iOS ATS 통과.
3. **URL 고정** (Named Tunnel 의 경우) → 공유기 공인 IP 바뀌어도 상관 없음.

### JS/웹소켓 비유
- HTTPS/HTTP 는 요청-응답 1회성
- WebSocket 은 양방향 상시 연결
- **cloudflared ↔ CF 엣지** 는 WebSocket 보다 한 단계 더 고급 (HTTP/2 멀티플렉싱) 이지만, 개념은 "한 번 열어놓고 계속 데이터 주고받기" 로 같음

---

## 5. Cloudflare vs ngrok

### 둘 다 Reverse Tunnel 서비스. 왜 CF?

| 항목 | ngrok (무료 플랜) | Cloudflare Tunnel |
|------|-------------------|-------------------|
| 가격 | 무료 (제한 있음) | **완전 무료** |
| URL 고정 | ❌ 재시작마다 바뀜 | ⭕ (Named Tunnel) |
| 커스텀 도메인 | 유료 | 무료 (본인 도메인 있으면) |
| 동시 터널 수 | 1개 | 무제한 |
| 대역폭 | 월 제한 | 무제한 |
| HTTPS | ⭕ | ⭕ |
| 계정 가입 | 필수 (무료 터널도) | Quick Tunnel 은 불필요 |
| 상용 사용 | 유료 플랜 필요 | 개인 사용 자유 |

### 결정 이유
- **비용**: 영상 스트리밍은 대역폭 많이 먹음 → ngrok 제한 걸림
- **URL 고정**: 상용 앱이 매번 URL 교체는 불가
- **신뢰성**: Cloudflare 는 전세계 CDN — 도쿄 사용자도 가까운 엣지로 접속

ngrok 은 **30초 데모** 용으론 쉽고 좋음. 우리처럼 **지속 운영** 이면 CF.

---

## 6. Quick Tunnel vs Named Tunnel

### 6a. Quick Tunnel — 임시 데모용
```bash
cloudflared tunnel --url http://localhost:8000
```
결과:
```
Your quick Tunnel has been created! Visit it at:
https://random-word-xxx-abc.trycloudflare.com
```
- 계정 불필요, 즉시 시작
- **종료 후 재실행 시 URL 바뀜**
- 7일 자동 종료 (정책에 따라 변할 수 있음)
- **용도**: 팀원에게 5분간 데모 보여주기, 개발 단계 스모크 테스트

### 6b. Named Tunnel — 고정 URL
```bash
# 사전 준비 (1회)
cloudflared login                    # CF 계정 연결
cloudflared tunnel create petcam     # 터널 생성 (UUID 받음)
cloudflared tunnel route dns petcam petcam.your-domain.com  # DNS 연결

# 실행
cloudflared tunnel run petcam
```
- CF 계정 + **본인 도메인** 필요 (도메인은 연 1~2만원)
- URL 영구 고정: `https://petcam.your-domain.com`
- 여러 포트/서비스 라우팅 가능 (`config.yml`)
- **용도**: 프로덕션 배포, 상용 앱 baseUrl

### 우리 플랜
- **Stage D5 Phase 1**: Quick Tunnel 로 E2E 검증 (맥북·폰·Flutter 전 구간 작동 확인)
- **Stage D5 Phase 2**: 도메인 구입 → Named Tunnel 세팅 → Flutter 앱 baseUrl 고정

---

## 7. D5 에서 실제 할 일

### 체크리스트 미리보기

```
[  ] 1. AUTH_MODE=prod 전환 + Supabase JWT 검증 실전 적용 (⚠️ 보안 선결)
[  ] 2. brew install cloudflared
[  ] 3. Quick Tunnel 로 로컬 스모크 테스트
         └─ 4G 아이폰에서 /health 접속 확인
[  ] 4. launchd plist 작성 — 맥북 부팅 시 cloudflared 자동 기동
[  ] 5. 맥북 잠자기 방지 설정 (`caffeinate` or `pmset noidle`)
[  ] 6. (선택) 도메인 구입 → Named Tunnel 로 고정 URL 확보
[  ] 7. Flutter `BACKEND_URL` 을 HTTPS URL 로 교체 (dart-define 활용)
[  ] 8. 앱 `/health` 헬스체크 주기 핑 → 서버 다운 시 "점검 중" UI
[  ] 9. 운영 로그 수집 — cloudflared 접속 통계, 서버 크래시 알림
```

### 예상 작업 시간
- Quick Tunnel 스모크 테스트: **30분**
- Named Tunnel + launchd: **2시간** (도메인 구입·DNS 전파 포함)
- prod 모드 전환 + Flutter 교체: **3시간**
- 총 **반나절 ~ 하루**

---

## 8. 보안 선결 과제 — prod 모드 전환

### ⚠️ 반드시 D5 착수 **전** 또는 **함께** 해결

현재 상황:
```python
AUTH_MODE=dev
# → Authorization 헤더 무시, DEV_USER_ID 그대로 사용
# → /clips, /cameras, /streams 등 전부 "누구나 호출 가능"
```

여기서 CF Tunnel 만 붙이면:
```
공격자  →  https://xyz.trycloudflare.com/clips  →  모든 영상 리스트 & 다운로드 가능
                                                      │
                                        (터널 URL 한 번 유출되면 끝)
```

### 필수 전환 작업
1. `.env` 의 `AUTH_MODE=dev` → `prod`
2. `SUPABASE_JWT_ISSUER`, `SUPABASE_JWKS_URL` 실 값 세팅
3. Flutter 앱이 Supabase 로그인 → `access_token` 받음
4. 모든 API 호출에 `Authorization: Bearer <token>` 헤더 포함
5. curl 테스트 시에도 토큰 필요 — 개발 편의성 감소 → **개발 중엔 AUTH_MODE=dev 유지, 배포 시점에만 prod**

### Stage D1 에서 이미 구현은 되어 있음
- `backend/auth.py` 의 `get_current_user_id` 가 `AUTH_MODE` 분기 자동 처리
- JWKS TTL 캐시, RS256 서명 검증, `iss`/`exp` 체크 전부 테스트 통과
- 즉, **env 변수 한 줄만 바꾸면 전환 완료** — 이게 D1 에서 미리 깔아둔 공의 보답

### 배포 단계별 auth 전환 타이밍
```
[로컬 개발]          AUTH_MODE=dev   → 변경 없음
[Quick Tunnel 테스트] AUTH_MODE=dev   → 단, URL 절대 공개 금지
[Named Tunnel 배포]   AUTH_MODE=prod  → Flutter 도 로그인 + JWT 붙이기 완료 후 전환
```

---

## 9. 자주 나올 질문

### Q1. 맥북 꺼지면?
터널도 끊김 → 앱 접속 불가. D5 에서 `/health` 주기 핑 + "점검 중" UI 로 대응.

### Q2. 맥북 잠자기 모드는?
`pmset` 설정 안 하면 20분 후 sleep → cloudflared 도 죽음.
```bash
sudo pmset -a sleep 0        # 네트워크 연결 있을 때 sleep 방지
caffeinate -d &              # 또는 수동으로 영구 깨우기 프로세스
```
실전에선 launchd plist 에 `KeepAlive` 옵션 + `pmset` 정책 조합.

### Q3. Cloudflare 가 우리 영상 다 보는 거 아님?
- **암호화**: HTTPS 안에서 CF 는 라우팅만. 다만 TLS termination 이 CF 엣지에서 일어남 → 이론상 CF 는 복호화 가능.
- **상업 정책**: 그런 행동 확인되면 CF 망함. 신뢰 기반.
- **완전한 end-to-end 보호** 원하면 Cloudflare Tunnel with TLS origin pull — 응용 복잡도 급상승.
- **우리 MVP 수준에선 수용 가능 리스크.** 상용 레벨 올라가면 재검토.

### Q4. 도메인 없으면 Named Tunnel 못 쓰나?
Cloudflare 에서 무료 서브도메인 제공 안 함. 최소 `.xyz`, `.link` 도메인 연 $1~5 수준 구입 필요. 또는 Quick Tunnel 로 개발 단계 지속.

### Q5. 공유기 바꾸거나 맥북 이사 가도 URL 유지됨?
⭕ 100% 유지. 터널은 맥북 → CF 방향 outbound 라 공유기 설정·공인 IP 무관. 맥북에 cloudflared 가 떠있고 인터넷 연결되면 끝.

### Q6. 성능 오버헤드는?
- 1홉 추가 (엣지 경유)
- 영상 스트리밍: 맥북 → CF 엣지(근처) → 사용자. 한국 사용자면 지연 수십 ms 추가. 영상 재생엔 영향 거의 무시.
- 녹화 자체는 맥북 로컬 → 영향 0.

---

## 참고

- Cloudflare Tunnel 공식: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
- ngrok 비교 글: https://www.cloudflare.com/learning/access-management/what-is-reverse-proxy/
- Reverse proxy vs Tunnel 차이: https://www.cloudflare.com/learning/access-management/what-is-a-vpn/
- 우리 레포 관련 스펙:
  - [`specs/stage-d-roadmap.md`](../specs/stage-d-roadmap.md) — 전체 로드맵
  - [`specs/stage-d1-auth-crypto.md`](../specs/stage-d1-auth-crypto.md) — prod JWT 기반 작업 (D5 선결 과제)
  - `specs/stage-d5-deploy-tunnel.md` *(D5 착수 시점 생성 예정)*
- Flutter 통합 문서: [`docs/flutter-handoff.md`](flutter-handoff.md)
