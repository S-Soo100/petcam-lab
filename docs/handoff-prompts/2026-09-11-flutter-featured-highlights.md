# Flutter 핸드오프 — 앱 하이라이트를 ⭐ 대표 tier(`GET /highlights/featured`)로 전환 (2026-09-11)

> 대상: `tera-ai-flutter` 레포에서 작업하는 Claude/Codex 에이전트. 아래 "붙여넣기용 프롬프트"를 그대로 첫 메시지로 준다.
> 배경 결정: owner 2026-09-10 "하이라이트가 너무 많다(하루 28~95개) — 많이 움직이고, 중복 없이, 볼 만한 것만". petcam-lab `docs/decision-gate.md` 2026-09-10, 스펙 `specs/feature-highlight-featured-tier.md`.
> 서버 상태: DB 함수·petcam-api **fly v6**·라벨링 웹 전부 production 배포 완료(`DEPLOYED_VERIFIED`). 앱만 남았다.

---

## 붙여넣기용 프롬프트

```
레포: /Users/baek/myProjects/tera-ai-flutter (main, 최신 pull 먼저). 이 레포의 CLAUDE.md·.claude/rules 를 따른다.

목표: 앱 하이라이트 화면·어젯밤 리포트가 petcam-api 의 새 엔드포인트 GET /highlights/featured 를 쓰게 바꾼다.
지금은 GET /highlights?since&limit (O 전체, 최신순) 을 받아 앱에서 72시간 창으로 묶어 보여준다(lib/features/my_cage/domain/highlight_group.dart 의 groupHighlights). 서버가 이제 "하루(20:00→다음날 20:00 KST) 단위 ⭐ 대표 최대 3개 + 나머지 후보" 를 계산해 주므로, 앱의 72h 그룹핑은 서버의 day_key 묶음으로 교체하고, 기본 화면엔 대표만, 후보는 하루마다 "후보 N개 더 보기" 로 접는다.

계약(petcam-api https://api.tera-ai.uk, 기존과 같은 Supabase JWT bearer, 본인 소유 카메라만):
  GET /highlights/featured?days=<1..31>&tier=featured|all&top_n=<1..10>
  - days(기본 7): 오늘 day_key 기준 최근 N개 하루. tier=featured(기본) 대표만 / tier=all 후보 포함. 범위 밖은 422.
  - 응답 {"highlights":[item…], "count":n, "rule_version":"hl-rule-v0", "featured":{"top_n":3,"gap_sec":1800,"day_start_hour":20,"time_zone":"Asia/Seoul","days":7}}
  - item = 기존 /highlights 항목 필드(clip_id, camera_id, camera_name, started_at, duration_sec, media_ready, source, reason, rule_version) + 
      tier: "featured"|"candidate"
      day_key: "YYYY-MM-DD"  (그 하루의 시작 날짜. 20:00 KST 경계 — 09-08 21:00 과 09-09 05:00 은 둘 다 day_key 2026-09-08)
      activity_sec: number
      behavior_flagged: bool   (라벨러가 ✨ 의미있는 행동 체크한 클립)
      episode: {rank:int, clip_count:int, activity_sec:number, started_at, ended_at}
  - 정렬: day_key 최신 → 카메라 → episode.rank → started_at 최신. keyset 없음(하루·카메라당 ≤ top_n). decided_at 은 이 응답에 없다(null 처리).
  - 저장된 값이 아니라 조회 시 계산이다: 진행 중인 하루는 새 클립이 오면 대표가 바뀔 수 있고, 지난 하루는 라벨러가 X/✨ 를 바꿀 때만 바뀐다. 앱에 대표를 오래 캐시하지 말 것(화면 진입마다 재조회, 기존 provider 갱신 정책 유지).
  - 기존 GET /highlights 는 그대로 살아 있다(호환). 이번 작업에서 새 화면이 그것을 더 쓰지 않으면 호출부만 제거하고 repository 메서드는 남겨도 된다.

구현 범위(파일은 실제로 열어 확인하고 맞춘다):
  1. lib/features/my_cage/domain/nightly_highlight.dart — 필드 추가: tier, dayKey, activitySec, behaviorFlagged, episodeRank, episodeClipCount, episodeActivitySec, episodeStartedAt, episodeEndedAt. fromJson 은 없는 키를 기본값으로(기존 /highlights 응답과 호환). isFeatured getter.
  2. lib/features/my_cage/data/highlight_repository.dart — listFeatured({int days = 30, String tier = 'all', int top_n = 3}) 추가. days 는 1..31 로 클램프(서버 le=31). 404 → 빈 목록, 그 외 BackendException(기존 list 와 동일 패턴).
  3. lib/features/my_cage/domain/highlight_group.dart — 72h 창 groupHighlights 대신 day_key 로 묶는 groupByDay(List<NightlyHighlight>) → [(dayKey, featured: [...], candidates: [...])] 최신 day_key 먼저. 각 묶음 안 featured 는 episode.rank 오름차순, candidates 는 started_at 내림차순. highlightGroupKey 는 "그 묶음의 가장 최신 featured started_at ISO" 로 유지(배너 dismiss 의미 = "이 시점까지 봤다" 그대로).
  4. lib/features/my_cage/presentation/my_cage_providers.dart — highlightGroupsProvider 가 listFeatured(days: 30, tier: 'all') 을 부르고 groupByDay 로 파생. latestHighlightAtProvider 는 최신 featured 기준.
  5. lib/features/my_cage/presentation/highlights_screen.dart — 묶음 헤더를 "어젯밤"/"그저께 밤"/"9월 8일 밤" (day_key 기준, 20:00 KST 경계라 "밤" 이 맞음) 으로. 카드 = 대표만. 카드 배지 텍스트: "⭐ {episode.rank}위 · 움직임 {episode.activity_sec 반올림}초 · 클립 {episode.clip_count}개", behavior_flagged 면 "✨" 를 앞에. reason 은 기존처럼 보조 줄. 사람 확정(source=human) 표시는 기존 유지. 묶음 끝에 "후보 N개 더 보기" 버튼 → 펼치면 후보 카드(작게, 시간순). 후보 0 이면 버튼 없음.
  6. 어젯밤 리포트(nightly_report.dart·nightlyReportProvider·nightly_report_badge.dart) — "하이라이트 N개" 의 N = 어젯밤 day_key 의 대표 개수(0~3), 옆에 "후보 M개" 보조. 어젯밤 day_key = 지금이 20:00 KST 이전이면 어제 날짜, 이후면 오늘 날짜(서버와 같은 정의: KST 시각에서 20시간을 뺀 날짜).
  7. 재생·썸네일·즐겨찾기는 clip_id/started_at 만 쓰므로 변경 없음(media_ready=false 면 재생 안 함, 기존과 동일).

체험(구현 전에 이 흐름대로 되는지 스스로 확인):
  [화면] 하이라이트 탭 → "어젯밤" 섹션에 ⭐ 카드 최대 3장(카메라가 여러 대면 카메라별 3장). 카드에 썸네일·"⭐ 1위 · 움직임 84초 · 클립 6개"·시각.
  [조작] 카드 탭 → 재생. 아래 "후보 12개 더 보기" 탭 → 후보 시간순 펼침.
  [반응] 다음 날 아침 열면 새 "어젯밤" 섹션이 위에, 어제 것은 "그저께 밤" 으로 내려감. 새 대표가 오면 도착 배너(dismiss 키가 최신 featured 시각이라 새 대표마다 다시 뜸).
  [감정] "오늘 볼 건 이 세 개" 가 명확하고, 같은 장면 여러 장이 안 보인다.

테스트(기존 test/ 스타일, MockClient):
  - NightlyHighlight.fromJson: featured 응답 → 새 필드 파싱, 기존 /highlights 응답(새 키 없음) → 기본값·tier 'candidate' 아님(빈 문자열 또는 null 로 구분해 isFeatured=false).
  - HighlightRepository.listFeatured: 쿼리 days/tier/top_n 전달, days 32 → 31 클램프, 404 → [], 500 → BackendException.
  - groupByDay: 서로 다른 day_key 2개 + 같은 day_key 의 featured 2·candidate 3 → 묶음 2개, 순서·정렬·highlightGroupKey 검증.
  - 어젯밤 day_key 계산: 2026-09-10 10:00 KST → "2026-09-09", 2026-09-10 21:00 KST → "2026-09-10".
  - 화면 위젯: 대표 3장 + "후보 N개 더 보기" 렌더, 후보 0 이면 버튼 없음.
  flutter analyze 0 · flutter test 통과.

주의:
  - 서버는 owner 계정(bss.rol20@gmail.com)이 소유한 production 카메라가 0 이라 그 계정으론 count 0 이 정답이다. 실데이터 확인은 카메라 소유 계정(leegawnhun@gmail.com)으로 앱 로그인해서 한다. 남의 계정 세션을 스크립트로 만들지 않는다.
  - top_n·days 를 앱에 하드코딩하지 말고 상수 한 곳에. 서버 응답의 featured.top_n 을 그대로 배지 "n/3" 같은 데 써도 된다.
  - 이 엔드포인트에는 행동 이름(탈피·음수)이 없다(기존 핸드오프 §2 와 동일).

완료 보고에 포함: 바뀐 파일 목록, flutter analyze/test 결과, 카메라 소유 계정으로 본 실화면 스크린샷(어젯밤 섹션·더 보기 펼침), 커밋 SHA. main 직접 push 는 owner 확인 뒤.
```

---

## 참고 (petcam-lab 쪽 사실)

- 계약 원문: [`2026-09-08-app-highlight-api-handoff.md`](2026-09-08-app-highlight-api-handoff.md) §3 `GET /highlights/featured`.
- 서버 구현: `backend/routers/highlights.py` `list_featured_highlights`, DB `fn_highlight_featured`(migration `2026-09-10_highlight_featured_tier.sql`). 하루 창 정의 = `featured_window()`.
- production 실측(2026-09-10): 주 카메라 5일 각 대표 3, 대표 시각 분산(03·02·05시 등), ✨ 사건이 1위. 라벨링 웹 `label.tera-ai.uk/labeling/all?featured=yes` 에서 같은 결과를 볼 수 있다(라벨러 계정 필요).
- 앱 실측 뒤 petcam-lab `docs/decision-gate.md` 에 "앱 전환 완료" 한 줄 append 하면 3층 + 앱까지 닫힌다.
