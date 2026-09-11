# Flutter 핸드오프 — 하이라이트 재생을 "움직임부터" 시작 (`play_from_sec`, 2026-09-12)

> 대상: `tera-ai-flutter` 레포에서 작업하는 Claude/Codex 에이전트. 아래 "붙여넣기용 프롬프트"를 그대로 첫 메시지로 준다.
> 배경 결정: owner 2026-09-11 "app에서도 움직임부터 재생하게 할까?" → 시작. 라벨링 웹 v4 는 이미 첫 움직임 0.5초 전으로 자동 건너뛰기를 하고 있었고(overlay 기반), 앱은 0초부터 재생하고 있었다.
> 서버 상태: DB 함수(migration `2026-09-12_highlight_first_moving.sql`)·petcam-api 배포 뒤에 보낼 것 — 배포 전엔 응답에 `play_from_sec` 키가 없다(앱은 키 없음 = null 로 처리해야 하므로 순서가 바뀌어도 안 깨진다).

---

## 붙여넣기용 프롬프트

```
레포: /Users/baek/myProjects/tera-ai-flutter (main, 최신 pull 먼저). 이 레포의 CLAUDE.md·.claude/rules 를 따른다.

목표: 하이라이트 영상을 열면 0초가 아니라 "게코가 움직이기 직전"부터 재생한다. 서버가 시작점을 초 단위로 주고, 앱은 그 지점으로 seek 해서 재생만 하면 된다.

계약(petcam-api https://api.tera-ai.uk, 기존과 동일):
  GET /highlights/featured 와 GET /highlights 의 각 item 에 두 키가 추가됐다.
    first_moving_sec: number|null   — 활성 움직임 엔진이 잡은 첫 움직임 구간 시작(초). 분석 결과가 없으면 null.
    play_from_sec:    number|null   — 서버가 계산한 재생 시작점(초) = max(0, first_moving_sec − 1.5), 단 첫 움직임이 3초 이전이면 null.
  앱은 play_from_sec 만 쓴다(first_moving_sec 은 디버그·미래용). 키가 없거나 null 이면 0초부터(기존 동작).
  리드 1.5초·최소 3초 기준은 서버 상수라 앱에 넣지 않는다.

구현 범위(파일은 실제로 열어 확인하고 맞춘다):
  1. lib/features/my_cage/domain/nightly_highlight.dart — playFromSec (double?) 필드. fromJson 은 키 없음/null → null. 숫자로 오면 double 로.
  2. 재생 화면(하이라이트 카드 탭 → 플레이어; 파일명은 레포에서 찾는다: highlight_player / clip_player / video_player 계열) —
     플레이어 초기화 완료(initialized, duration 확보) 뒤 playFromSec 이 null 이 아니고 duration 보다 작으면 seekTo(playFromSec) → play. 
     null 이거나 duration 이상이면 0초부터. seek 는 영상당 1회만(재생 중 사용자가 타임라인을 옮기면 다시 안 당긴다).
     다음/이전 영상으로 넘어가면 그 영상의 playFromSec 으로 다시 1회.
  3. 플레이어 UI 에 "처음부터" 컨트롤 하나(아이콘 버튼 ⏮ 또는 텍스트). 누르면 seekTo(0) → play. 점프한 초·움직임 초 같은 숫자는 화면에 표시하지 않는다(owner 원칙: 앱엔 숫자·순위·라벨 안 보임).
     선택: 타임라인(있으면)에 시작점을 작은 눈금으로 표시해도 된다. 숫자 텍스트는 금지.
  4. 썸네일·즐겨찾기·목록은 변경 없음.

체험(구현 전에 이 흐름대로 되는지 스스로 확인):
  [화면] 어젯밤 ⭐ 카드 탭 → 플레이어가 열리며 곧바로 게코가 움직이기 1~2초 전 장면부터 재생된다. 로딩 중 0초 프레임이 잠깐 보였다가 튀지 않게, 초기화 뒤 첫 재생 전에 seek.
  [조작] "처음부터" 를 누르면 0초로 돌아가 재생. 타임라인을 직접 옮기면 그대로 둔다.
  [반응] 다음 영상으로 넘어가면 그 영상도 움직임 직전부터. 분석이 없는 영상(옛 영상·사람이 직접 O 한 영상 일부)은 예전처럼 0초부터.
  [감정] 기다리지 않고 바로 볼 것을 본다. 앞부분이 궁금하면 한 번 눌러 되돌아갈 수 있다.

테스트(기존 test/ 스타일):
  - NightlyHighlight.fromJson: play_from_sec 8.8 → 8.8, null → null, 키 없음 → null, 정수 3 → 3.0.
  - 플레이어 위젯/컨트롤러 테스트: playFromSec 8.8·duration 60 → 초기 seek 8.8 후 play 1회; playFromSec null → seek 없음; playFromSec 70·duration 60 → seek 없음; "처음부터" 탭 → seek 0.
  flutter analyze 0 · flutter test 통과.

주의:
  - 서버는 owner 계정(bss.rol20@gmail.com)이 소유한 production 카메라가 0 이라 그 계정으론 count 0 이 정답이다. 실데이터 확인은 카메라 소유 계정(leegawnhun@gmail.com)으로 앱 로그인해서 한다. 남의 계정 세션을 스크립트로 만들지 않는다.
  - mp4 는 faststart 인코딩이라 중간 seek 에 range 요청이 된다. seek 뒤 첫 프레임이 늦게 오면 로딩 표시를 유지하고 0초 프레임을 보여주지 않는다.
  - 서버 배포 전(응답에 키 없음)에도 앱이 정상 동작해야 한다.

완료 보고에 포함: 바뀐 파일 목록, flutter analyze/test 결과, 카메라 소유 계정으로 본 실화면(플레이어가 중간 지점에서 시작한 장면·"처음부터" 컨트롤) 스크린샷 또는 짧은 녹화, 커밋 SHA. main 직접 push 는 owner 확인 뒤.
```

## 참고 (petcam-lab 쪽 사실)

- 서버 계산: `backend/routers/highlights.py` `play_from_sec()` — `PLAY_FROM_LEAD_SEC=1.5`, `PLAY_FROM_MIN_FIRST_MOVING_SEC=3.0`. 재료 `first_moving_sec` 은 DB 함수(`fn_highlight_featured`, `fn_list_labeling_v4_clips` 14/13/12-인자 전부)가 활성 계약 run 의 `state_intervals` 첫 `moving` 구간에서 준다 = `fn_highlight_rule_eval` 의 `features.first_moving_sec` 그대로.
- 라벨링 웹은 overlay 로 같은 동작(리드 0.5초·1초 미만이면 안 뜀)을 이미 하고 있어 변경 없음. 두 화면이 거의 같은 지점에서 시작한다.
- 알려진 한계: bbox 흔들림(jitter) 영상은 첫 "움직임" 이 노이즈일 수 있고, 쳇바퀴 같은 미검출은 null(0초부터). 둘 다 엔진(2.6.1 이후) 쪽 문제 — `docs/highlight-motion-gaps-options.md`.
- 규칙 params·유지율·봉인 표본과 무관(재생 위치일 뿐, 판정이 아니다).
