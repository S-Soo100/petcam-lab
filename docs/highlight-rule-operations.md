# 하이라이트 자동 1차 판정 — 운영·개선 런북 (2026-09-07)

> **누가 읽나:** 하이라이트 규칙을 조정하거나, 트리거를 추가하거나, 라벨링 웹 v4·앱 API를 고치려는 사람/에이전트(Claude·Codex·사람 모두). 이 문서 하나로 "어디에 무엇이 있고, 무엇을 만지면 무엇이 바뀌고, 어떻게 검증·배포하나"를 알 수 있어야 한다.
> **상태:** production 배포 완료(`DEPLOYED_VERIFIED`, 2026-09-07). 라벨링 웹 `label.tera-ai.uk`, 앱 API `api.tera-ai.uk/highlights`(fly v4), DB migration 5개 적용.
> **왜 이렇게 만들었나(설계 근거·폐기 대안)** 는 스펙에 있다: [`specs/feature-highlight-auto-initial-designation.md`](../specs/feature-highlight-auto-initial-designation.md) · [`specs/feature-labeling-web-v4-simplification.md`](../specs/feature-labeling-web-v4-simplification.md). 여기서는 반복하지 않는다.

## 0. 한 문단 요약

모션 트리거로 찍힌 모든 영상은 GME(Gecko Motion Engine)가 "게코가 실제로 움직인 시간" 등 숫자를 `gme_runs`에 남긴다. **하이라이트 1차 판정은 그 숫자 × 현재 활성 규칙 params의 순수 함수**이며 저장하지 않고 조회 때마다 DB 함수가 계산한다. 라벨링 웹 회원이 영상마다 `O/X`를 한 번 확정하면 append-only 원장에 "그때 보인 1차 판정 스냅샷 + 최종값"이 남는다. 앱과 라벨링 웹은 같은 DB 함수를 읽으므로 항상 같은 답을 본다. 규칙은 params 버전(`hl-rule-vN`)을 새로 만들어 활성화하는 것으로 바뀌고, 옛 확정은 옛 스냅샷과 함께 남는다. **owner 확정 원칙:** 밤당 개수 제한 없음 · `애매` 없음(이진) · 한 영상 한 사람 확정 · 사람 확정은 100% 신뢰 · 사람 교차검증·튜토리얼·AI 호출 없음.

## 1. 데이터 흐름 (어디서 무엇이 계산되나)

```
motion_clips ──(gecko-vision-gate 워커)──► gme_jobs/gme_runs (append-only, exact identity)
                                                  │  candidate_moving_sec_any_gecko · visible_sec · state_intervals …
highlight_rule_versions + highlight_rule_activation_events  (append-only; active = 최신 event)
                                                  │
        fn_highlight_rule_eval(run, params) ── 순수 함수: initial · reason · fired · shadow · features
        fn_highlight_initial(clip, identity)  ── exact identity 의 최신 ok run 을 찾아 eval; run 없음 → pending
        fn_highlight_current(clip, identity)  ── 사람 확정(motion_clip_highlight_verdicts) 있으면 그것, 없으면 initial
                                                  │
   fn_list_labeling_v4_clips (목록·필터·keyset)   fn_submit_highlight_verdict (확정 append)   fn_highlight_rule_stats (유지율)
                │                                          │                                        │
   라벨링 웹 v4 (/labeling/mine, /all, /v4/[clipId])   ─────┘             owner 화면 /labeling/owner/highlight-rules
   petcam-api GET /highlights (p_highlight_state='yes', 본인 카메라)  ─► Flutter 앱 하이라이트 피드
```

**exact identity** = `(engine_schema_version, algorithm_version, detector_identity)`. 라벨링 웹은 Vercel env `GME_ACTIVE_ALGORITHM_VERSION`·`GME_ACTIVE_DETECTOR_IDENTITY`(`readGmeActiveContract()`, `web/src/lib/labelingV3Server.ts`), petcam-api 는 fly secrets 의 같은 이름(품질 보강판에서는 미설정·형식 오류 시 503, 최신 run 폴백 없음)을 **호출 시점에** 읽는다. Codex 세션이 detector/algorithm 을 바꾸면 두 곳 env 를 같이 바꿔야 한다(§6).

## 2. 규칙 params 계약 (지금 함수가 이해하는 것 전부)

```jsonc
{
  "triggers": [                                   // OR — 켜진(on) 트리거 하나라도 맞으면 O
    {"name": "long_activity",   "on": true,  "activity_sec_gte": 10},   // 활동시간 ≥ N초
    {"name": "sustained_move",  "on": true,  "longest_sec_gte": 5},     // 최장 연속 moving 구간 ≥ N초
    {"name": "frequent_bursts", "on": false, "activity_sec_gte": 3, "bursts_gte": 8}, // 활동 ≥ AND moving 구간 수 ≥
    {"name": "early_action",    "on": false, "first_move_sec_lte": 2}   // 첫 moving 구간 시작 ≤ N초
  ],
  "guards": []                                    // 스키마상 배열 필수. ⚠️ 현재 eval 은 guards 를 읽지 않는다(§7)
}
```

- **활성 v0 = `hl-rule-v0`**: `long_activity(10)` OR `sustained_move(5)` on, 나머지 둘 off(shadow). `SELECT * FROM fn_get_active_highlight_rule()` 로 언제든 확인.
- **선행 규칙:** `visible_sec <= 0` 이면 트리거와 무관하게 X, 근거 `게코 미관측`.
- **근거 문구**는 규칙이 읽은 숫자 그대로: O `움직임 12.4초 · 최장 연속 6.1초` / X `짧은 움직임 4.2초 · 최장 연속 1.0초`. 앱은 이 문구를 그대로 배지에 쓴다.
- **fired / shadow:** `fired` = 켜져 있고 맞은 트리거, `shadow` = 꺼져 있지만 맞았을 트리거. 라벨링 상세 화면에 "켠 트리거 / (꺼진 트리거였다면: …)" 로 표시. **verdict 원장에는 저장되지 않는다** — 필요하면 run 과 params 로 언제든 재계산 가능(§5 쿼리).
- **fail-closed 검증:** 모르는 트리거 이름·빠진 숫자 키는 `22023`. 새 버전 저장(`fn_create_highlight_rule_version`)도 합성 run 에 eval 을 한 번 돌려 같은 검사를 한다.
- `features` (eval 반환): `activity_sec, longest_moving_sec, moving_burst_count, first_moving_sec, visible_sec, duration_sec` — 트리거가 읽는 값 전부. 새 트리거를 만들 때 이 목록을 먼저 넓힌다.

## 3. 주간 조정 루프 (owner가 매주 하는 일)

> **2.6.1 전환 전엔 유지율로 규칙을 바꾸지 않는다** (2026-09-09). 검출기가 바뀌면 숫자 감각이 바뀌어 지금 튜닝은 버려진다. 대신 봉인 표본(`experiments/highlight-eval-sample/`)의 사람 O/X 를 먼저 채우고, 전환 뒤 `scripts/report_highlight_eval_sample.py --contract <새 계약>` 의 임계값 후보표로 규칙 v1 을 낸다.

1. `/labeling/owner/highlight-rules` 열기 → 표 읽기(화면은 **최근 7일 고정**; 다른 기간은 `GET /api/labeling-v4/owner/highlight-stats?from=YYYY-MM-DD&to=YYYY-MM-DD` 또는 §3 끝의 SQL). 컬럼 뜻:
   - `verdict_count` 확정 수 · `decided_count` 1차 판정이 있었던 확정(분모) · `kept_count` 사람이 그대로 둔 수 → **유지율 = kept / decided**
   - `o_to_x` 규칙 O 를 사람이 X 로 · `x_to_o` 규칙 X 를 사람이 O 로 · `pending_initial` 1차 판정 없이(GME 대기/실패) 확정된 수
   - `reason_counts` O→X 사유 분포: `false_detection`(오검출) · `gecko_not_visible` · `camera_shake` · `too_short` · `interesting_low_numbers`(재밌는데 숫자 낮음, X→O 쪽) · `other`
2. 해석 가이드
   - `o_to_x` 가 많고 사유가 `false_detection`/`camera_shake` → 규칙이 아니라 **GME 오검출**(jitter overcount) 문제. 규칙 숫자를 올리지 말고 [`specs/experiment-gme-jitter-overcount-mitigation.md`](../specs/experiment-gme-jitter-overcount-mitigation.md) 쪽으로 넘긴다(v0 에 fragmentation 가드를 일부러 안 넣은 이유).
   - `too_short` 많음 → 임계값(10s/5s)을 올릴 후보. `x_to_o` 많음(X→O 는 사유를 묻지 않는다 — 규칙이 놓쳤다는 사실 자체가 신호; `interesting_low_numbers` 는 enum 에만 남은 미사용 값) → 임계값을 내리거나 shadow 트리거(`frequent_bursts`, `early_action`)를 켤 후보. 켜기 전에 §5 쿼리로 "그 트리거가 shadow 로 맞았던 영상의 사람 판정"을 먼저 본다.
   - 카메라별 행이 크게 다르면 절대 임계값 편향(스펙 §4.1a C `camera_relative` 후보).
   - **앵커링 경고(스펙 §4.4):** 유지율이 높아도 "규칙이 맞아서"인지 "사람이 안 고쳐서"인지 구분 못 한다. 첫 사이클은 분포 파악이 목적, 목표치는 그 뒤에 정한다.
3. 규칙 바꾸기 — 같은 화면 "새 버전" 폼: 버전(`hl-rule-v1` 형식 강제), params JSON, note 한 줄 → 저장. **저장 = 즉시 활성화**(`fn_create_highlight_rule_version` 이 activation event 까지 같이 append). 되돌리려면 "재활성화" 폼에 검증된 옛 버전 입력(`fn_activate_highlight_rule_version`).
4. 활성화 즉시 라벨링 웹 목록·앱 `/highlights`(`rule_version` 값이 바뀜) 모두 새 규칙으로 계산된다. 과거 확정은 재계산·수정하지 않는다.
5. 바꾼 사유는 note 에, 판단 근거(표 수치)는 [`docs/decision-gate.md`](decision-gate.md) 에 append(운영 튜닝이라 TEST-SHEET 는 요구하지 않음, 스펙 §4.3).

SQL 로 직접 할 때(Supabase SQL Editor, service_role):
```sql
select * from public.fn_get_active_highlight_rule();
select * from public.fn_highlight_rule_stats(now() - interval '7 days', now());
select * from public.fn_create_highlight_rule_version('hl-rule-v1', '{"triggers":[...],"guards":[]}'::jsonb, '왜 바꿨나', '<owner uuid>');
select * from public.fn_activate_highlight_rule_version('hl-rule-v0', '<owner uuid>');
```

## 4. 코드 지도 (무엇을 고치면 어디가 바뀌나)

| 층 | 파일 | 책임 |
|---|---|---|
| DB 판정 | `migrations/2026-09-08_highlight_rule_v0.sql` | 테이블 3개(`highlight_rule_versions`, `highlight_rule_activation_events`, `motion_clip_highlight_verdicts`) + 함수 `fn_highlight_rule_eval / _initial / _current / fn_get_active_highlight_rule / fn_submit_highlight_verdict / fn_create_… / fn_activate_…` + seed v0. append-only 트리거(`0A000`) |
| DB 목록 | `migrations/2026-09-08_labeling_v4_simplification.sql` → `…_labeling_v4_list_chunked.sql`(현행 목록 RPC) | `fn_list_labeling_v4_clips`(keyset chunk 200 루프, 필터 `p_label_state`/`p_highlight_state`/`p_camera_ids`, production 적격 가드), `fn_list_labeling_v4_cameras/members`, `labeler_camera_assignments`, `fn_set_labeler_camera_assignments`, blind RPC EXECUTE 회수 |
| DB 집계 | `migrations/2026-09-08_highlight_aggregates_fast.sql`(현행) | `fn_get_labeling_v4_overview`, `fn_highlight_rule_stats` |
| DB 폐지 | `migrations/2026-09-08_labeling_tutorial_retirement.sql` | 튜토리얼 RPC 회수(테이블 보존) |
| 웹 타입 | `web/src/lib/highlightV4.ts`, `labelingV4.ts` | 공개 타입·enum·한국어 카피(`HIGHLIGHT_TRIGGER_LABELS`, 사유 라벨). **새 트리거/사유는 여기 라벨 추가** |
| 웹 서버 | `web/src/lib/highlightV4Server.ts`, `labelingV4Server.ts`, `web/src/lib/uuid.ts` | RPC row → 타입 매퍼(fail-closed), SQLSTATE → HTTP 매핑(22023→400, P0002→404, PT403→403, PT409→409, PT428→503) |
| 웹 API | `web/src/app/api/labeling-v4/**` | `clips`(목록) · `clips/[clipId]`(상세·`next`·`file/url`·`gme-overlay`·`verdict`) · `cameras` · `owner/{assignments,overview,highlight-rules,highlight-stats}`; `_access.ts`(역할·UUID), `_highlight.ts`(공용) |
| 웹 화면 | `web/src/app/labeling/{mine,all}/page.tsx`, `_v4-clip-list.tsx`, `v4/[clipId]` + `_v4-clip-detail.tsx`, `owner/highlight-rules/page.tsx`, `owner/_owner-overview-view.tsx`, `team/_camera-assignments.tsx` | 목록/상세/확정, owner 규칙·현황, 카메라 배정. 라우트 접근은 `web/src/lib/labelingRouteAccess.ts`(퇴역 경로 `/labeling/blind`, `/me`, `/tutorial`) |
| 앱 API | `backend/routers/highlights.py` (`main.py` 등록) | `GET /highlights?since&limit&cursor`, `GET /highlights/rule`. 본인 카메라 = `cameras.owner_id`. 계약 문서 [`docs/API.md`](API.md), 핸드오프 [`handoff-prompts/2026-09-08-app-highlight-api-handoff.md`](handoff-prompts/2026-09-08-app-highlight-api-handoff.md) |
| Flutter | `~/myProjects/tera-ai-flutter` 브랜치 `feat/highlights-petcam-api` | `HighlightRepository → BACKEND_URL/highlights`; 문서 그 레포 `docs/handoff-highlights-petcam-api-2026-09-08.md` |
| 계획서(구현 당시 task 단위 기록) | `docs/superpowers/plans/2026-09-07-highlight-rule-v0-db.md`, `2026-09-07-labeling-web-v4.md` | 왜 그 파일이 그 모양인지 |

### 4.1 새 트리거를 추가하는 절차 (예: `wide_travel`)

1. **입력값이 `gme_runs` 에 있나?** 없으면(궤적 스칼라 등) 먼저 값이 저장돼야 한다 — 스펙 §4.1a B 의 ⓐ gecko-vision-gate 엔진에서 run 저장 시 함께 쓰기(cross-repo handoff, `CLAUDE.md` handoff gate 준수) 또는 ⓑ 이 레포의 추출기가 `gme_run_highlight_features`(append-only, run_id 키)에 쓰기. 규칙 함수는 DB 값만 읽는다.
2. **새 migration** (기존 파일 편집 금지): `CREATE OR REPLACE FUNCTION fn_highlight_rule_eval` — 허용 이름 목록·필수 숫자 키 배열·`v_hit` CASE·`features` 에 한 줄씩 추가. `fn_create_highlight_rule_version` 의 합성 run 에 새 입력값 기본치가 필요하면 같이.
3. **정적 계약 테스트** `tests/test_highlight_rule_v0_migration.py` 패턴으로 새 파일 추가 + **probe** `scripts/run_highlight_rule_v0_probe.py` 의 `MIGRATIONS` 끝에 새 migration, 기대값 케이스 추가 → `nice -n 10 uv run python scripts/run_highlight_rule_v0_probe.py --pg-bin /opt/homebrew/opt/postgresql@15/bin` 가 `HIGHLIGHT_RULE_V0_PROBE_OK` / `PROBE_RESIDUE=0`.
4. **웹:** `highlightV4.ts` 의 `HighlightTrigger` union + `HIGHLIGHT_TRIGGER_LABELS`; 매퍼는 모르는 이름을 fail-closed 하므로 빠뜨리면 상세 화면이 500 난다. vitest 로 확인.
5. **앱 API/Flutter:** `reason` 문구만 소비하므로 보통 변경 없음. 문구 형식을 바꾸면 핸드오프 문서 §2 갱신.
6. **params 버전** `hl-rule-vN` 을 owner 화면에서 `on:false`(shadow)로 먼저 넣고 한 주 뒤 §5 쿼리로 shadow 유지율을 본 다음 on.
7. 배포 순서 §6. 결정 로그 append.

### 4.2 사유(change_reason) 추가

verdict 테이블 CHECK + `fn_submit_highlight_verdict` 검증 + `fn_highlight_rule_stats` FILTER 목록(현재 7개 하드코딩) + `highlightV4.ts` 라벨 — 네 곳을 한 migration/커밋에서 같이. 실물 예: `migrations/2026-09-09_highlight_reason_gecko_visible.sql`(CHECK 는 인라인 자동 이름에 의존하지 않고 컬럼 기준으로 찾아 교체).

## 5. 자주 쓰는 진단 쿼리 (읽기 전용)

```sql
-- 봉인 표본 진행·층별 4분할 (2026-09-09)
select * from public.fn_eval_sample_progress('eval-2026-09');
select * from public.fn_eval_sample_report('eval-2026-09');
```

```sql
-- 한 영상의 현재 판정(사람 우선) — 라벨링 웹·앱이 보는 것과 동일
select * from public.fn_highlight_current('<clip uuid>', 'gme-shadow-v1', '<algorithm>', '<detector identity>');

-- shadow 트리거가 맞았던 확정 영상에서 사람이 O 라고 한 비율 (켜기 전 근거)
with v as (
  select v.clip_id, v.verdict, v.gme_run_id from public.motion_clip_highlight_verdicts v
  where v.kind = 'initial' and v.initial_status = 'decided' and v.created_at >= now() - interval '14 days')
select t as trigger_name, count(*) as hit, count(*) filter (where v.verdict) as human_o
from v join public.gme_runs r on r.id = v.gme_run_id
cross join lateral public.fn_highlight_rule_eval(r, (select params from public.highlight_rule_versions
                                                    where version = (select version from public.fn_get_active_highlight_rule()))) e
cross join lateral unnest(e.shadow) t
group by t;

-- 카메라 소유자 (앱 /highlights 는 owner_id 기준)
select id, name, owner_id from public.cameras;
```

`service_role` 로 python 에서 같은 RPC 를 부르는 예시는 `scripts/run_labeling_v4_probe.py`(로컬) 와 세션 스크래치 `verify_prod_migrations.py` 패턴(`sb.rpc("fn_list_labeling_v4_clips", {...})`) 참고. production 에서 `p_camera_ids=NULL` 은 "전체" 의미이므로 앱 경로에선 절대 NULL 로 부르지 않는다.

## 6. 검증·배포 절차 (순서 고정)

### 6.0 GME 계약(algorithm/detector) 전환 — 2.6.1 등

1. 새 계약으로 **최신 영상부터 역순** 백필을 건다(GME 워커 쪽). 라벨링은 최신부터 하므로 최근 2주가 먼저 차야 끊기지 않는다.
2. owner 현황(`/labeling/owner`)의 **활성 GME 계약 커버리지** 줄을 본다 — env 를 아직 안 바꿨으면 현 계약 기준이므로, 새 계약의 진행은 `fn_gme_contract_coverage('gme-shadow-v1', '<새 algorithm>', '<새 detector>')` 를 SQL Editor 에서 직접 호출해 확인한다.
3. 최근 7일 100% 가 되면 Vercel env + fly secrets 의 `GME_ACTIVE_ALGORITHM_VERSION` / `GME_ACTIVE_DETECTOR_IDENTITY` 를 함께 바꾼다(§6 순서). 앱 API 는 fallback 이 없어(2026-09-08 제거) env 가 틀리면 503 이다.
4. 전환 직후 커버리지 줄이 "최근 7일 100% · 전체 n%" 로 바뀌고, `분석 대기` 목록은 백필이 찰수록 준다. 사람 확정은 rule_version·run id 스냅샷이라 불변.
5. 규칙 재보정은 전환 **뒤** 봉인 표본(`eval-*`)의 임계값 후보표로 한다. 전환 전 유지율로 규칙을 바꾸지 않는다.


1. **로컬 계약:** `cd <repo> && uv run pytest tests/test_highlight_rule_v0_migration.py tests/test_labeling_v4_*_migration.py tests/test_highlight_aggregates_fast_migration.py tests/test_highlights_api.py -q`
2. **일회용 PostgreSQL probe 2종** (`LC_ALL=C` 필요, `nice -n 10`, 동시에 하나만): `scripts/run_highlight_rule_v0_probe.py`, `scripts/run_labeling_v4_probe.py` — 둘 다 `*_PROBE_OK` + `PROBE_RESIDUE=0`.
3. **웹:** `cd <repo>/web && npx tsc --noEmit && npx vitest run` (donts#12 — web 명령은 항상 `cd …/web &&` 프리픽스).
4. **production migration:** owner 승인 뒤 Supabase SQL Editor(project `slxjvzzfisxqwnghvrit`)에 파일 전체를 붙여 실행(`BEGIN/COMMIT` 포함). Chrome 자동화 시 Monaco `setValue` 주입(메모리 `supabase-migration-apply-via-chrome`). 적용 후 read-only 검증: active rule · 목록 2건 · overview · 회수 RPC `42501` · 보존 원장 count 불변(`verify_prod_migrations.py` 패턴).
5. **라벨링 웹:** PR → main 머지 → Vercel 자동 배포(프로젝트 `petcam-lab`, root `web`, alias `label.tera-ai.uk`). CLI 는 `/Users/baek/petcam-lab/web` 에서만 동작(`.vercel` 링크).
6. **앱 API:** `flyctl deploy --config fly.api.toml --app petcam-api`(레포 루트, 빌드 10분+). 배포 뒤 **무인증 401 smoke 만으로 끝내지 않는다** — 사용자 JWT 로 `/highlights` 200 을 확인(2026-09-07 v3 사고: `cameras.user_id` 오타로 인증 호출 전부 502, 401 smoke 는 통과). legacy `/me/is_labeler`, `/clips`, `/clips/highlights` 401 불변도 확인.
7. **GME identity 변경 시**(Codex 가 detector/algorithm 갱신): Vercel env + fly secrets 두 곳 동시 갱신 → 두 서비스 재배포. 어긋나면 라벨링 웹과 앱의 pending/decided 가 달라진다.
8. 결정 로그·`specs/next-session.md`·`.claude/donts-audit.md` append.

## 7. 알려진 한계·함정 (고치기 전에 읽기)

| 항목 | 상태 | 메모 |
|---|---|---|
| `guards` | params 스키마엔 있으나 **eval 이 읽지 않음** | 가드(`camera_shake` 등, 스펙 §4.1a D)를 넣으려면 eval 에 AND-NOT 루프 추가 + 이름 검증. 지금은 빈 배열만 두기 |
| shadow 결과 미저장 | verdict 에 `fired/shadow` 없음 | §5 쿼리로 재계산 가능하므로 설계상 의도. 규칙 버전이 바뀌면 "당시 shadow" 는 옛 params 로 다시 돌려야 함 |
| `pending` 필터 | 목록 RPC 6.5s | GME run 없는 영상은 인덱스로 못 걸러 chunk 를 많이 돈다. 기본 화면은 안 씀 |
| 카메라 소유 | production 카메라 4대 전부 `leegawnhun@gmail.com`(e2d0a451) 소유 | owner 계정(`DEV_USER_ID`)의 `/highlights` 는 `count 0` 이 정상. 라벨링 웹은 소유와 무관(배정=편의 필터) |
| 앱 페이지네이션 | 앱이 `limit=100` 한 페이지 | `has_more:true` 실측(2026-09-07). 서버는 `next_cursor` 를 주므로 앱 쪽 후속 |
| dead route | `web/src/app/api/labeling-v4/clips/[clipId]/highlight/route.ts` 소비처 없음 | 상세 API 가 같은 값을 포함. 삭제 후보 |
| 미사용 파라미터 | `fn_list_labeling_v4_clips.p_is_owner`, overview 의 identity 인자 일부 | 시그니처 유지 중(호출자 5곳). 정리하려면 migration + 웹·backend 호출부 동시 |
| GME 오검출 | jitter overcount(정지 게코가 18초 움직임) | 규칙에서 고치지 않는다 — `experiment-gme-jitter-overcount-mitigation.md` |
| 옛 3-class GT 301건 | 변환 안 함(보존만) | 기준·질문이 달라 v4 O/X 와 비교 불가 |
| blind·튜토리얼 테이블 | 코드 제거·RPC EXECUTE 회수, row 보존(44,524/741/22,262/5) | 복원하려면 새 migration 으로 GRANT. 삭제 금지 |

### 6.x "의미있는 행동" 체크는 규칙과 무관

`motion_clip_behavior_flags`(2026-09-09 migration)는 하이라이트 O/X·유지율·`change_reason` 어디에도 안 들어간다. 행동 GT 라벨링 후보 수집용이며, 규칙 튜닝 근거로 쓰지 않는다. 필터: 목록 `?behavior_flag=yes`, SQL `select clip_id, flagged_by, flagged_at from public.motion_clip_behavior_flags order by flagged_at desc`.

## 8. 관련 문서 색인

- 스펙: [`feature-highlight-auto-initial-designation.md`](../specs/feature-highlight-auto-initial-designation.md)(§4.1a 트리거 후보 로드맵 v0→v1→v2) · [`feature-labeling-web-v4-simplification.md`](../specs/feature-labeling-web-v4-simplification.md)
- 결정 로그: [`decision-gate.md`](decision-gate.md) 2026-09-07 1~4차 + 배포·실측 append
- 앱 계약: [`API.md`](API.md) `/highlights` · [`handoff-prompts/2026-09-08-app-highlight-api-handoff.md`](handoff-prompts/2026-09-08-app-highlight-api-handoff.md)
- 기능 개요: [`FEATURES.md`](FEATURES.md) §11.9
- 제품 SOT: `../tera-ai-product-master/docs/specs/petcam-ai-pipeline.md` "앱 하이라이트 실동작"
- 다음 세션 메모: [`../specs/next-session.md`](../specs/next-session.md)


## 9. 2026-09-08 품질 보강판 (운영 반영 완료)

- API는 명시한 GME 계약만 사용해. `GME_ACTIVE_ALGORITHM_VERSION`과 `GME_ACTIVE_DETECTOR_IDENTITY`를 웹과 같게 설정한 뒤 배포해야 해. 과거 fallback 경로는 제거했어.
- 새 `fn_highlight_quality_stats(from,to)` / owner-only `GET /api/labeling-v4/owner/highlight-quality` / 규칙 관리 품질표를 추가했어. 최초 유지율 표는 그대로야.
- 기본은 최근 7일 처음 검수한 clip이야. 기간은 `[from,to)` UTC, 최대 31일이며 `to` 이전 최신 사람 정정을 최초 자동값과 비교해. 활동일 표시는 촬영시각의 KST 07:00 경계야. API의 UTC 날짜 필터와 활동일은 다른 기준이야.
- 규칙·schema·algorithm·detector·카메라·활동일을 분리해. O 수용률 = O→O / 자동 O 검수 수, X 놓침률 = X→O / 자동 X 검수 수. 분모 0은 '표본 없음', pending/failed는 분모 제외야. 이 표는 검수 표본 품질이며 전체 정확도/처리 커버리지 측정이 아니야.
- 당시 rule params와 run으로 off 트리거를 복원해 **원래 X였던 영상만** 추가 포착으로 집계해. 트리거별 행은 중복 clip이 있을 수 있으므로 합산하지 않아. 사람이 바꾼 이후의 사유로 기술 오류/짧음·선호/기타를 구분하고, 가시성 누락 신호는 별도 수치야.
- 표본 편향을 줄이려면 카메라별 닫힌 밤에서 O와 X를 함께 검수해. 옛 3-class GT 변환, 자동 사람 답 생성, 2.6.1 holdout 접근은 없어.
- 규칙 10초/5초와 off 상태는 바꾸지 않았어. `guards`의 기존 한계도 그대로이며 임의 가드를 켜지 않아.

적용 순서: env 일치 확인 → 승인 후 `2026-09-10_highlight_quality_stats.sql` 적용 → Web/API 배포 → owner 품질표/비-owner 403/인증 앱 피드 확인. 이 migration은 조회 함수와 기간 검색 인덱스만 추가하며 데이터 원장과 활성 규칙을 변경하지 않아. 미적용 시 새 품질표는 오류 안내를 보이고 기존 규칙 관리·유지율은 유지돼. 앱 롤백은 이전 코드 배포, 품질 RPC는 읽기 전용이라 남겨도 기존 기능 영향 없어.

검증: `LC_ALL=C nice -n 10 uv run python scripts/run_highlight_rule_v0_probe.py --pg-bin /opt/homebrew/opt/postgresql@15/bin`, Python 전체 `-x`, Web vitest·tsc·Next build. 상세 결과는 구현 계획에 기록해.

운영 반영 증거와 canary 한계: [구현 결과](research/2026-09-08-highlight-quality-implementation-report.md). 256MB Fly에서 별도 Python 프로세스 검증은 OOM을 유발할 수 있으니 쓰지 않아.
