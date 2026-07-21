# 라벨링 큐 최신순 보장 — 구현 보고

> 핸드오프: `/Users/baek/.codex/handoffs/2026-07-22-labeling-queue-newest-order-handoff.md`
> 설계: `docs/superpowers/specs/2026-07-22-labeling-queue-newest-order-design.md`
> 계획: `docs/superpowers/plans/2026-07-22-labeling-queue-newest-order.md`
> 실행 repo: `petcam-lab/.worktrees/local-vlm-evidence-web-gt` · branch `codex/local-vlm-evidence-web-gt`

## 최종 판정

## `LABELING_QUEUE_NEWEST_READY_FOR_DEPLOY_REVIEW`

일반 라벨링 큐(`/labeling`)를 정본 정렬키 `(started_at DESC, id DESC)` 로 동결하고, versioned
opaque 복합 cursor·keyset·클라이언트 stale 응답 guard 까지 계획 Task 1~5 를 전부 구현했다.
DB schema/migration 없이 web 전체 테스트·TypeScript·Next production build·Python 회귀가 모두
GREEN 이다. **배포 자체는 실행하지 않았다** — Stop Point 에서 정지하며, Evidence GT Work
Package B 는 Codex 가 이 보고서를 검수하고 새 handoff 를 만든 뒤에만 시작한다.

## 1. 시작 계약 (HANDOFF_OK)

```
cd /Users/baek/petcam-lab/.worktrees/local-vlm-evidence-web-gt
uv run python scripts/verify_agent_handoff.py \
  --manifest /Users/baek/.codex/handoffs/2026-07-22-labeling-queue-newest-order-handoff.md
→ HANDOFF_OK task=labeling-queue-newest-order repo=local-vlm-evidence-web-gt commit=3302556c runtime=none
```

- execution_repo `local-vlm-evidence-web-gt`, branch `codex/local-vlm-evidence-web-gt`,
  시작 HEAD `3302556c99ff3f0a616597c3b83596a3d1955dad` = manifest `commit_sha`, working tree clean ✅.

## 2. Task 별 commit

| Task | 내용 | commit |
|---|---|---|
| 1 | versioned 복합 cursor 계약 (`labelingQueueCursor.ts` + test) | `fcbe7976b8137ac54d46ab6f5ee9b5636efd318d` |
| 2 | 큐 scan `nextCursor` 를 복합 위치 객체로 (`labelingQueue.ts` + test) | `435897d56549966c5d8189b17938f67f77c39035` |
| 3 | API 이중 order + composite keyset + `400 invalid_cursor` (`route.ts` + test) | `1c3d9ad165c2a26be4522c95ccedfe0f2619334a` |
| 4 | client dedup+재정렬 merge + 세대 guard (`labelingQueueClient.ts` + test, `page.tsx`) | `645e937de8d5110fdb180bf43a0df87027eec098` |
| 5 | 전체 검증·문서(FEATURES §11.6·donts-audit)·본 보고 | 이 커밋(§7 push tip) |

각 Task 는 RED 증거 → 최소 구현 → GREEN → 명시 파일 commit 순서로 진행했다.

## 3. Exact test / build 결과

| 검증 | 명령 | 결과 |
|---|---|---|
| web 전체 | `npm test` | **37 files / 356 passed** |
| 신규 회귀(포커스) | cursor+queue+route+client | cursor 6 · queue 4 · route 6 · merge 3 GREEN |
| TypeScript | `npx tsc --noEmit` | **exit 0 (에러 0)** |
| Next production build | `npm run build` (owner 터미널) | **✓ Compiled successfully · Linting/types 통과 · static 19/19** |
| Python 회귀 | `uv run pytest -q` | **660 passed** |
| whitespace | `git diff --check` | clean (exit 0) |

- `npm run build` 는 레포 안전 훅(`dangerous-guard.sh`, donts#9 — 세션 내 리소스 경합 차단)이
  세션 안 실행을 막아 **owner 터미널에서 `!` 로 실행**했다. 출력: `✓ Compiled successfully`,
  타입 체크 통과, `✓ Generating static pages (19/19)`. `/labeling` 은 `○ Static`(3.72 kB),
  `/api/labeling-v2/queue` 는 `ƒ Dynamic`. tsc(exit 0)로 in-session 타입 검증을 이미 통과했다.

## 4. 계약 증거

### 4.1 동일 `started_at` keyset (같은 초 clip 결정론)

- 큐 scan: `labelingQueue.test.ts` — `returns an object cursor from the last visible item and
  preserves equal timestamps`. 같은 `2026-07-22T02:00:00Z` 3건에서 `nextCursor` 가
  `{ startedAt: same, id: rows[1].id }` 복합 위치로 나온다(started_at 단일키였으면 동률 순서 비결정).
- API keyset: `route.test.ts` — `orders by started_at then id and applies the composite keyset for
  a cursor`. 쿼리에 `.order('started_at',{ascending:false})` **와** `.order('id',{ascending:false})`
  두 번, cursor 있을 때
  `started_at.lt.2026-07-22T01:00:00.000Z,and(started_at.eq.2026-07-22T01:00:00.000Z,id.lt.<uuid>)`
  `.or()` 필터가 정확히 걸린다.
- client merge: `labelingQueueClient.test.ts` — 동률(02:00) `c,b` 를 `id DESC` 로, 역순 응답을
  최신순으로 재정렬. id 중복은 1건으로 접힌다.

### 4.2 invalid cursor → 400 (DB 접근 이전)

- `route.test.ts` — `returns 400 invalid_cursor before DB access`: `?cursor=bad!` 가 status **400**,
  body `{ detail: '페이지 위치가 올바르지 않아.', code: 'invalid_cursor' }`, `collectQueuePage`
  **호출 0**. decode 는 `databaseUnavailable` catch **밖**에 있어 DB 오류(502)와 층위가 분리된다.
- `labelingQueueCursor.test.ts` — invalid base64 / 미지 version(v2) / invalid timestamp / invalid
  UUID 4종이 모두 `InvalidQueueCursorError`. round-trip 은 URL-safe 문자열로 복원.

### 4.3 stale response 폐기

- `page.tsx` 는 요청마다 `requestGeneration.current.next()` 로 세대를 발급하고, `await` 이후
  `isCurrent(generation)` 이 아니면 items·cursor·error·busy·loaded **어떤 상태도 바꾸지 않는다**
  (try 성공/ catch / finally 세 경로 모두 guard). effect cleanup 이 `next()` 로 진행 중 요청을
  무효화한다(필터 변경/언마운트). `requestGeneration.test.ts` 3케이스가 "늦게 도착한 이전 세대
  응답은 무시" 를 회귀로 고정한다.
- 외부 계약: 내부 큐 scan 은 복합 위치 객체를 쓰지만 API `next_cursor` 는 opaque base64url
  문자열만 노출한다(`route.test.ts` — `encodes the object next cursor` 가 실제 decode 로 왕복 검증).

## 5. 금지 경계 (0 증거)

- **DB migration: 0** — 신규/수정 `.sql` 없음. schema 변경 없음.
- **production DB write: 0** — 이번 변경은 web 코드/테스트/문서만. supabase insert/update/delete/
  upsert/rpc 신규 호출 없음(route 는 기존 SELECT 계약 유지, keyset `.or` 만 추가).
- **deploy: 미실행** — Vercel/prod 배포 없음. Stop Point 에서 정지.
- **Evidence GT Work Package B: 미착수** — Codex 검수·새 handoff 전까지 시작 안 함.
- **behavior/VLM/Python Evidence 필드 조회·노출: 0** — privacy audit
  `git diff HEAD~4..HEAD -- web/src | grep -E "prediction_snapshot|reasoning|clip_python_evidence|behavior_logs"`
  → 신규 노출 필드 **0**. blind GT 응답 컬럼·triage·튜토리얼·owner/labeler 게이트 불변.
- **사용자 소유 untracked 파일 추가·삭제·커밋: 0** — 명시 파일만 stage/commit.

## 6. 편차와 미검증

- **계획 대비 편차: 없음.** cursor/queue/route/client/docs 파일과 인터페이스가 계획 File Structure
  와 일치. 클라이언트 merge 의 `[...map.values()]` 만 tsconfig target(TS2802) 때문에 `Array.from`
  으로 조정(동작 동일).
- **미검증(배포 review 게이트)**: production smoke(설계 §8) — 같은 필터 2페이지 `(started_at,id)`
  단조 감소 확인, 라벨러 계정 첫 카드 = 최신 eligible clip read-only 대조 — 는 **배포 review 에서
  owner 가 수행**한다. 이번 작업은 코드·자동 테스트 계약까지만 닫았고 production 데이터에 접근하지
  않았다.

## 7. Branch / push 상태

- branch `codex/local-vlm-evidence-web-gt`, 이 보고 커밋이 tip.
- push 후 local HEAD == `origin/codex/local-vlm-evidence-web-gt`, working tree clean(§7 갱신은 최종
  메시지에 SHA 명시).

## 8. 다음 (Stop Point)

계획 Task 5 Stop Point 에서 정지한다. main merge·production 배포·Evidence GT Work Package B 를
같은 run 에서 시작하지 않는다. Evidence B1 은 Codex 가 이 보고서를 검수하고 새 handoff 를 만든
뒤에만 시작한다.

---

## 9. Codex independent review follow-up (2026-07-22 추가)

Codex 독립 리뷰가 최신순 계약에서 결함 2건을 발견했다. handoff
`2026-07-22-labeling-queue-newest-order-review-fix.md` (HANDOFF_OK task=labeling-queue-newest-review-fix
repo=local-vlm-evidence-web-gt commit=419f85a0 runtime=none) 로 두 건만 TDD 최소 수정했다. 정렬
정본·cursor 계약·금지 경계는 그대로다.

### 9.1 F1 — ISO 문자열 사전순 비교가 실제 시간순을 깨뜨림

- **재현:** `mergeNewestQueueItems` 가 `b.started_at.localeCompare(a.started_at)` 를 썼다. 아래에서
  더 최신인 `.100000` row 가 뒤로 갔다.

  ```
  2026-07-22T01:00:00.100000+00:00   # 실제로 100ms 더 최신 (Date.parse → …100)
  2026-07-22T01:00:00+00:00          # Date.parse → …000
  ```

  문자 비교로는 `'1'`(.100000) > `'+'`(+00:00 없음) 이라 최신 row 가 뒤로 밀린다.
- **수정:** comparator 를 `Date.parse` 두 값의 epoch millisecond DESC 비교로 바꿨다. 둘 다 유효하고
  epoch 동률(예: `2026-07-22T01:00:00Z` vs `2026-07-21T20:00:00-05:00` — 같은 instant)이면
  `id DESC` tie-break. API 에서는 올 수 없는 malformed timestamp 는 `NaN` 을 반환하지 않도록
  결정론적 fallback(raw string DESC → id DESC). `started_at` 값·API 응답은 변환하지 않고 정렬
  비교만 고쳤다. (`web/src/lib/labelingQueueClient.ts`)

### 9.2 F2 — cursor 가 유효한 PostgreSQL UUIDv7 을 거부함

- **계약:** 이전 regex 는 version nibble 을 `[1-5]`, variant 를 `[89ab]` 로 제한했다. PostgreSQL
  `uuid` 타입은 canonical UUIDv7 도 저장하므로, 그런 clip 이 페이지 끝에 오면 서버가 만든 cursor 를
  다음 요청에서 스스로 `400 invalid_cursor` 처리한다.
- **수정:** validation 을 canonical `8-4-4-4-12` hex 형식만 확인하도록 완화했다
  (`/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i`). version/variant nibble 은
  제한하지 않는다. 잘못된 길이·non-hex·구분자 오류는 계속 거부된다. (`web/src/lib/labelingQueueCursor.ts`)

### 9.3 새 테스트 (총 +8, RED→GREEN)

| 파일 | 신규 테스트 | 수 |
|---|---|---|
| `labelingQueueClient.test.ts` | fractional-second epoch 정렬 · 동일 instant `id DESC` tie-break · malformed 결정론 fallback | 3 |
| `labelingQueueCursor.test.ts` | canonical UUIDv7 round-trip · malformed uuid(하이픈 없음/길이 부족/non-hex/구분자 오류) 계속 거부 | 5 |

- **RED 증거:** 수정 전 focused run — `3 failed | 14 passed (17)`. 실패 = F1 fractional 정렬,
  F1 동일-instant tie-break, F2 UUIDv7 round-trip. malformed fallback/거부 테스트는 기존 구현에서도
  통과(계약 잠금용).
- **GREEN 증거:** 수정 후 focused run — `17 passed`. 전체 `npm test` — **37 files / 364 passed**
  (기존 356 → +8).

### 9.4 전체 재검증

| 검증 | 명령 | 결과 |
|---|---|---|
| web 전체 | `npm test` | **364 passed (37 files)** |
| TypeScript | `npx tsc --noEmit` | **exit 0** |
| Next production build | `npm run build` | **owner 터미널 실행 필요** (세션 훅 donts#9 차단; tsc exit 0 로 in-session 타입 검증 통과) |
| Python 회귀 | `uv run pytest -q` | **660 passed** |
| whitespace | `git diff --check` | clean |

- 금지 경계 유지: migration 0 · production DB write 0 · deploy 미실행 · Evidence GT Work Package B
  미착수 · behavior/VLM/Python Evidence 필드 신규 조회·노출 0 (변경은 순수 lib 2파일 + 테스트 2파일
  + 문서·audit).
