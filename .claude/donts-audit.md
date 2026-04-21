# Don'ts 실전 검증 로그 — petcam-lab

> 목적: `.claude/rules/donts.md` 및 `donts/python.md`가 실제 작업에서 얼마나 작동하는지 누적 추적.
> 운영 시작: 2026-04-17
> 회고: 로그 20줄 쌓일 때마다 또는 월 1회 중 먼저 도래하는 시점.
> 연관: `tera-ai-product-master/.claude/donts-audit.md` (메인 프로젝트 운영 로그)

---

## 기록 방법

Standard 이상 트랙 작업 종료 시 메인 Claude가 아래 한 줄을 추가한다.

```
YYYY-MM-DD {기능} | 작업: {한줄요약} | 참조: {donts 항목} | 지킴: {번호} | 놓침: {번호+이유} | 재발: {있으면 기록} | 메모: {애매했던 점}
```

**필드 설명**
- **기능**: 제너럴 / python / fastapi / opencv / uv / 기타
- **참조**: 이번 작업에서 의식적으로 읽은 donts 항목 (예: `python#4,7` 또는 `general#2,3`)
- **지킴**: 실제로 지킨 항목
- **놓침**: 위반했거나 잊은 항목 + 이유 (없으면 `-`)
- **재발**: 기존 feedback 메모리에 있거나 과거 실수 패턴이 또 나왔나? (없으면 `-`)
- **메모**: 룰이 애매했거나, 새로 추가해야 할 패턴 (없으면 생략)

## 🔁 Three-Strike Rule 추적

새 실수 패턴은 아래 단계로 추적한다. 상세 기준은 [`rules/donts.md`](rules/donts.md) 상단 표 참조.

| 상태 | 기준 | 저장 위치 |
|------|------|----------|
| 1회 | 처음 발생 | `~/.claude/projects/-Users-baek-petcam-lab/memory/feedback_*.md` |
| 2회 | 재발 | 이 파일의 "승격 후보" 섹션 |
| 3회 | 세 번째 | `rules/donts.md` 또는 `rules/donts/python.md`에 정식 룰 |

## 🏷️ 승격 후보 (2회째 발생한 패턴)

_아직 없음._

## 📋 작업 로그

2026-04-18 opencv/rtsp | 작업: Stage A 재시도 로직 + Tapo C200 스모크 테스트 성공 | 참조: general#1,3,5 python#? | 지킴: general#3 (추측 전 ping/nc/ffprobe로 3단 진단), general#1 (cap.release 동작 직접 확인 후 설명) | 놓침: - | 재발: - | 메모: **macOS Local Network Permission** 처음 조우. 증상 = "No route to host" (ping/nc OK인데 ffmpeg/python만 차단). 시스템 바이너리는 통과, brew/uv 설치 바이너리는 차단. **새 규칙 후보**: RTSP/로컬 네트워크 접근 실패 시 "시스템 설정 → 로컬 네트워크 → VSCode/Terminal ON" 을 1차 체크리스트에 넣어야. Tapo 프로비저닝 가이드 작성 시 명시 필요.

2026-04-21 fastapi/supabase | 작업: Stage C 완료 — camera_clips DB + /clips API 3종 + 재시도 큐 + 단위 30개/E2E 1개 | 참조: general#1,2,11 python#4,5,6,11,13 | 지킴: python#5 (StreamingResponse + `_iter_file` 제너레이터, Range 206), python#6 (`get_supabase_client`/`get_dev_user_id` Depends → 테스트에서 override), python#11 (REPO_ROOT 기준 절대경로), python#13 (FakeSupabase + tmp_path 더미 mp4, 실 Supabase/RTSP 의존 X), general#11 (supabase_client.py 에 placeholder 가드 + .env 만 실키), general#1 (apply_migration 후 information_schema 로 컬럼/FK/인덱스/정책 각각 재확인) | 놓침: - | 재발: - | 메모: supabase-py `.table().select().eq().order().limit().execute()` 체인을 mock 으로 흉내낼 때 unittest.mock 보다 **filter 로직 그대로 적용하는 in-memory fake** 가 훨씬 간결 (21개 테스트 작성 비용 대폭 감소). Stage D 에서 JWT 검증용 override 도 동일 패턴 재사용 예정.

<!-- 예시:
2026-04-20 fastapi | 작업: MJPEG 스트리밍 엔드포인트 추가 | 참조: python#4,5 | 지킴: 4,5 | 놓침: - | 재발: - | 메모: StreamingResponse + 제너레이터 패턴 확인
-->
