# 하이라이트 2단 tier — ⭐ 대표 / 후보

> 하이라이트 O 가 하루 28~95개라 유저가 볼 수 없다. O/X 는 "후보 자격"으로 그대로 두고, 그 위에 **조회 시 계산되는 하루 상한 레이어**(에피소드 묶기 → 점수 → top-N)를 얹어 앱엔 대표만, 라벨링 웹엔 둘 다 보여준다.

**상태:** ✅ 완료 (2026-09-10 3층 배포 `DEPLOYED_VERIFIED` — DB 함수·fly v6·Vercel; 후속 = Flutter 전환·SOT 한 문장)
**작성:** 2026-09-10
**연관 SOT:** `../../tera-ai-product-master/docs/specs/petcam-ai-pipeline.md` ("앱 하이라이트 실동작" 갱신 필요), 결정 로그 `docs/decision-gate.md` 2026-09-10
**선행 스펙:** [`feature-highlight-auto-initial-designation.md`](feature-highlight-auto-initial-designation.md)(O/X 규칙·원장), [`feature-labeling-web-v4-simplification.md`](feature-labeling-web-v4-simplification.md)(화면)

## 0. owner 확정 사항 (2026-09-10)

- 기준은 셋: **많이 움직였다 · 중복 아니다 · 볼 만하다.** 시간대는 상한이 아니라 묶는 단위로만.
- 하루 = **20:00 → 다음날 20:00 KST**(밤 20~08 을 한 덩어리로 담는 창). 비는 날은 비어도 된다.
- 대표는 **라벨이 아니라 순위**. 사람 확정은 지금처럼 O/X 이진 하나. "대표 고정" 버튼 없음(v0).
- ✨ 의미있는 행동 체크된 사건은 무조건 최상위. 사람 O 확정은 가산. 사람 X 는 후보에서 제거.
- 표본(`eval-2026-09`)·규칙 params·2.6.1 전환 절차는 건드리지 않는다.

## 1. 목적

- **제품:** 아침에 앱을 열면 카메라당 ⭐ 대표 최대 3개. "오늘 밤 가장 활발한 사건 · 움직임 84초 · 클립 6개" 처럼 근거가 붙는다. 나머지는 "더 보기".
- **운영:** 라벨링 웹에서 대표/후보를 같이 보며 O/X·✨ 를 찍으면 순위가 바로 바뀐다(조회 시 계산). "볼 만함"의 사람 신호가 대표 선정에 흘러든다.
- **학습:** 이진 규칙(기준 고정·개수 흔들림) 위에 예산 레이어(개수 고정·기준 흔들림)를 분리해 얹는 법. 저장하지 않는 순위.

## 2. 스코프

### In

1. **DB 함수 `fn_highlight_featured`** — 카메라·기간·GME 계약을 받아 현재 O 클립을 하루(20시 경계)·카메라별 에피소드(간격 30분)로 묶고, 사건 점수로 순위를 매겨 각 클립에 `tier`(`featured`/`candidate`)·에피소드 정보를 붙여 돌려준다. 저장 없음. 기본값 N=3·간격 1800초·하루 시작 20시·`Asia/Seoul`.
2. **앱 API `GET /highlights/featured`** — petcam-api. 본인 카메라, 최근 `days`(기본 7, 최대 31), `tier=featured|all`. 기존 `GET /highlights` 는 그대로(호환).
3. **라벨링 웹** — 목록 카드에 `⭐ 대표 n위` / `후보` 배지, `⭐ 대표만` 칩(최근 7일), 상세 화면에 `⭐ 오늘 대표 2/3 · 사건 6클립 · 움직임 84초` 한 줄.
4. **실측 스크립트** — 대표·후보·사건 수를 카메라×하루로 뽑는 읽기 전용 스크립트(배포 전후 비교).
5. **문서** — 런북 §6.y, 앱 핸드오프 §3 추가, FEATURES §11.9 추가, SOT "앱 하이라이트 실동작" 갱신.

### Out

- **Flutter 화면 전환** — `tera-ai-flutter` 별도. 핸드오프 문서로 계약만 전달.
- **"볼 만함" 자동 점수(행동 모델)** — 지금 숫자로 못 잰다. 점수식에 자리만 비워둔다(§4.3).
- **대표 고정(pin) 버튼**, **tier 파라미터 버전화** — 결정 로그 v0 제외.
- **규칙 params·원장·표본·2.6.1 절차** — 불변.
- **기존 `GET /highlights` 변경** — 앱 호환 유지. 새 엔드포인트만.

> **스코프 변경은 합의 후에만.**

## 3. 완료 조건

- [x] migration `2026-09-10_highlight_featured_tier.sql` — probe §14 통과(`LABELING_V4_PROBE_OK`), 정적 계약 테스트 4 통과 (2026-09-10, production 적용 게이트 ①)
- [x] petcam-api `GET /highlights/featured` — `tests/test_highlights_api.py` 신규 10 통과, fly v6 배포 뒤 owner JWT 200·검증 422 실측 (게이트 ②)
- [x] 라벨링 웹 — `tsc` 0·vitest 1,128 통과, 로컬 실측(배지·대표만·상세 줄·모바일) + production `/labeling/all?featured=yes` (게이트 ③)
- [x] production 실측 — 7일 창 첫 호출 3.43s(생성 직후)·이후 콜드 1.79s/웜 0.29s, 카메라×하루 대표 전부 ≤ 3, ✨ 사건 1위
- [x] 문서 4곳(런북 §6.y·핸드오프 §3·FEATURES §11.9·README) + 결정 로그 게이트 ①②③ 기록. **SOT `petcam-ai-pipeline.md` 한 문장은 owner 확인 뒤 product-master 에서(후속)**

## 4. 설계 메모

### 4.1 왜 "저장하지 않는 순위"인가

대표를 원장에 라벨로 박으면 owner 가 대표 하나를 X 로 뒤집었을 때 다음 후보가 자동으로 올라오지 않는다. 1차 판정을 저장하지 않고 조회 때 계산하는 기존 구조(선행 스펙 §4.2)와 같은 결로, 대표도 `f(현재 O 집합, N, 간격)` 로 매번 계산한다. 입력이 전부 append-only 원장(verdict·flag·run)이라 결과 저장은 중복이다.

### 4.2 계산 순서 (함수 안에서 전부)

```
후보 = 기간·카메라 안 운영 적격 클립 중 current(사람 확정 우선, 없으면 규칙 initial) = O
하루 키 = (started_at AT TIME ZONE 'Asia/Seoul' − 20h)::date
에피소드 = 같은 카메라·같은 하루 안에서 직전 클립 끝(started_at+duration) 과 30분 초과 벌어지면 새 사건
사건 점수 정렬 = (✨ 있음 DESC, 사람 O 있음 DESC, activity 합 DESC, 사건 시작 DESC)
대표 클립 = 사건 안에서 (✨ DESC, 사람 O DESC, activity DESC, 시작 ASC) 1위
tier = 사건 순위 ≤ N 이고 대표 클립이면 'featured', 그 외 O 는 'candidate'
```

에피소드는 하루 경계에서 끊는다(19:50→20:10 사건은 두 하루에 나뉨 — 드물고 단순함이 이득).

### 4.3 점수식 v0 와 비워둔 자리

`activity_sec` 합은 GME 가 이미 주는 숫자라 설명 가능하다("움직임 84초"). "예쁘고 재미있다"는 사람 신호(✨, O)로만 올린다. 행동 GT 모델(물 마시기·탈피)이 생기면 `ORDER BY` 첫 항에 `behavior_score` 를 끼우는 자리가 §4.2 정렬식이다. 그때까지 자동 점수는 안 만든다.

### 4.4 기존 구조와의 관계

| 것 | 영향 |
|---|---|
| `fn_list_labeling_v4_clips` | 불변. 목록 route 가 페이지의 O 항목에 대해 feed 함수를 한 번 더 호출해 tier 를 붙인다(보조 정보, 실패 시 null) |
| `motion_clip_highlight_verdicts` / `motion_clip_behavior_flags` | 읽기만. 스키마 불변 |
| `GET /highlights` | 불변. `GET /highlights/featured` 신설 |
| 봉인 표본·`fn_eval_sample_report` | 무관(이진 O/X 만 본다) |
| 규칙 params | 불변. tier 기본값은 함수 DEFAULT + API 인자(상한 검사) |

### 4.5 리스크 / 미해결

- **성능:** 앱 7일 × 카메라 4대 ≈ 1,000 클립에 `fn_highlight_rule_eval` LATERAL. 로컬 probe 는 production 성능을 못 잡는다(메모리 `supabase-migration-apply-via-chrome`) → 배포 전 production 읽기 전용 타이밍 실측, 3초 초과면 `motion_clips(camera_id, started_at) WHERE r2_key IS NOT NULL` 부분 인덱스 추가 migration.
- **진행 중인 하루:** 새 클립이 오면 대표가 바뀔 수 있다(더 큰 사건이 오면 밀림). 지난 하루는 사람 확정·✨ 변경 때만 바뀐다. 라이브 피드로선 의도된 동작.
- **`#variable_conflict use_column`:** RETURNS TABLE 컬럼명과 쿼리 컬럼명이 겹치므로 함수 머리에 지시자를 둔다(기존 목록 함수는 별칭으로 피했음).

## 5. 유저 체험 시뮬레이션

**앱(유저, 아침)**
`[화면]` 하이라이트 탭. 카메라별 "어젯밤" 묶음에 ⭐ 카드 최대 3장. 카드: 썸네일 · `⭐ 1위 · 움직임 84초 · 클립 6개` · 시각
→ `[조작]` 카드 탭 → 재생. 아래 `후보 12개 더 보기`
→ `[반응]` 더 보기를 열면 나머지 O 가 시간순
→ `[감정]` "오늘 볼 건 이 세 개" 가 확실하다. 같은 장면이 여러 장 안 보인다.

**라벨링 웹(회원)**
`[화면]` 목록 카드에 `하이라이트 O` 옆 `⭐ 대표 2위` 또는 `후보` 배지. 칩 `⭐ 대표만` 을 켜면 최근 7일 대표만 한 화면
→ `[조작]` 상세를 연다. 판정 바 아래 `⭐ 오늘 대표 2/3 · 사건 6클립 · 움직임 84초`. 평소처럼 O/X·✨
→ `[반응]` X 를 찍으면 이 클립은 후보에서 빠지고, 목록으로 돌아오면 다음 사건이 ⭐ 로 올라와 있다. ✨ 를 찍으면 그 사건이 1위로
→ `[감정]` 내 확정이 앱 대표에 바로 반영된다는 게 보인다. "대표를 고르는" 별도 작업이 없다.

**Owner 주간 확인**
실측 스크립트: `카메라 | 하루 | O | 사건 | 대표 | ✨사건` 표. "대표가 늘 새벽 2시 사건뿐이다" 같은 편향이 보이면 점수식(§4.3)을 논의.

## 6. 학습 노트

- **임계값 vs 예산:** 임계값은 기준을 고정하고 개수가 흔들린다. 예산(top-N)은 개수를 고정하고 기준이 흔들린다. 둘을 층으로 분리하면 GT(이진)는 안정, 피드(순위)는 유연.
- **중복 제거 = 시간 클러스터링:** 연속 모션 클립은 한 사건. 간격 하나로 364→42 가 됐다. 대부분의 "너무 많다"는 중복이었다.
- **plpgsql `#variable_conflict use_column`:** RETURNS TABLE 의 출력 이름이 변수로 잡혀 쿼리 컬럼과 충돌할 때 함수 단위로 컬럼 우선을 선언한다.

## 7. 참고

- 결정 로그: `docs/decision-gate.md` 2026-09-10
- 실측 스크립트(세션 scratchpad → `scripts/report_highlight_featured.py` 로 정리)
- 계획서: `docs/superpowers/plans/2026-09-10-highlight-featured-tier.md`
