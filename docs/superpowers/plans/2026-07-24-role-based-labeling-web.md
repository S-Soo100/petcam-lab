# Role-Based Labeling Web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 라벨링 웹을 승인 라벨러·Owner·미승인 사용자의 전용 업무 화면으로 분리하고, 라벨러에게 blind 안전한 오늘 작업·내 기록·읽기 전용 영상 보관함을 제공한다.

**Architecture:** 기존 Supabase Auth와 `labelingAccess` 판정 순서는 유지하고, 순수 역할/경로 계약과 반응형 `RoleShell`을 추가한다. 기존 motion blind 테이블을 읽는 forward-only RPC 세 개로 내 기록·영상 보관함·Owner 현황을 제공하며, Next.js API가 bearer 역할을 다시 확인하고 allowlist mapper로 응답을 제한한다.

**Tech Stack:** Next.js 14 App Router, React 18, TypeScript 5, Tailwind CSS 3.4, Vitest 4, Supabase/PostgreSQL, 기존 UI 컴포넌트.

## Global Constraints

- 설계 정본은 `docs/superpowers/specs/2026-07-24-role-based-labeling-web-design.md`다.
- 역할 판정 순서는 `Owner → 승인 라벨러 → 미승인 사용자`로 고정한다.
- 라벨러 기본 메뉴는 `오늘 작업 / 내 기록 / 영상 보기`, Owner 기본 메뉴는 `운영 현황 / 불일치 검수 / 팀 관리` 세 개뿐이다.
- Owner가 동시에 라벨러여도 기본 홈은 Owner이며, 라벨링은 `직접 라벨링` 보조 버튼으로만 진입한다.
- 상대 라벨러의 제출 원문·판정·digest·reviewer UUID·lease token은 라벨러 응답에 포함하지 않는다.
- 공용 영상 보관함은 모든 카메라의 R2 재생 가능 영상만 다루며 write 동작을 제공하지 않는다.
- 새 blind 라벨은 `agreed` 또는 `owner_resolved`만 공개한다. `awaiting`과 `conflict`에서는 개별 답과 과거 라벨을 숨긴다.
- 기존 라벨 출처는 `기존 Owner 라벨 / 기존 단일 라벨 / 라벨 없음`으로 구분한다.
- VLM·Python Evidence·Gate·router feature 원문은 새 API와 화면에 노출하지 않는다.
- `320 / 360 / 390 / 768 / 1024 / 1440px`에서 메뉴·숫자·버튼 줄바꿈과 viewport 잘림이 없어야 한다.
- 기존 GT schema, comparator, submission payload, legacy v2, motion v3 write RPC를 변경하지 않는다.
- 적용된 migration은 수정하지 않고 새 forward-only migration만 추가한다.
- 구현 단계에서는 production migration apply, main merge, Vercel production deploy, 실제 그룹 변경을 하지 않는다.
- 각 Task는 RED → GREEN → 관련 회귀 → 명시 파일만 commit 순서로 수행한다.

---

## File Map

### 새 파일

- `web/src/lib/labelingRoleNavigation.ts` — 역할별 홈·메뉴·경로 접근 순수 계약.
- `web/src/lib/labelingRoleNavigation.test.ts` — 역할 우선순위와 경로 매트릭스.
- `web/src/lib/labelingRoleData.ts` — history/library/overview 공개 타입과 표시 문구.
- `web/src/lib/labelingRoleData.test.ts` — 라벨 출처·상태 표시 순수 테스트.
- `migrations/2026-07-24_role_based_labeling_reads.sql` — read-only RPC 세 개와 필요한 인덱스.
- `tests/test_role_based_labeling_reads_migration.py` — migration 정적 보안 계약.
- `web/src/lib/labelingRoleServer.ts` — cursor·filter parser와 allowlist row mapper.
- `web/src/lib/labelingRoleServer.test.ts` — cursor/filter/비노출 mapper 테스트.
- `web/src/app/api/labeling-v3/blind/history/route.ts` — 본인 blind 제출 기록.
- `web/src/app/api/labeling-v3/blind/history/route.test.ts` — 본인 scope·blind 비노출 검증.
- `web/src/app/api/labeling-v3/library/route.ts` — 공용 읽기 전용 영상 목록.
- `web/src/app/api/labeling-v3/library/route.test.ts` — 필터·cursor·공개 라벨 계약.
- `web/src/app/api/labeling-v3/library/[clipId]/route.ts` — 공용 읽기 전용 영상 단건.
- `web/src/app/api/labeling-v3/library/[clipId]/route.test.ts` — 단건 공개 필드·404 계약.
- `web/src/app/api/labeling-v3/library/[clipId]/file/url/route.ts` — 승인 사용자용 R2 GET 서명.
- `web/src/app/api/labeling-v3/library/[clipId]/file/url/route.test.ts` — 역할·미디어 실패·key 비노출.
- `web/src/app/api/labeling-v3/blind/owner/overview/route.ts` — Owner 운영 현황.
- `web/src/app/api/labeling-v3/blind/owner/overview/route.test.ts` — owner-only와 집계 mapper.
- `web/src/app/labeling/_role-shell.tsx` — 역할별 desktop/tablet/mobile navigation.
- `web/src/app/labeling/_role-shell.test.tsx` — 세 메뉴·active 상태·반응형 class 계약.
- `web/src/app/labeling/_account-menu.tsx` — 이메일·비밀번호 변경·로그아웃 보조 메뉴.
- `web/src/app/labeling/_labeler-history.tsx` — blind 본인 제출 기록.
- `web/src/app/labeling/library/page.tsx` — 공용 읽기 전용 영상 보관함.
- `web/src/app/labeling/library/[clipId]/page.tsx` — 읽기 전용 재생 상세.
- `web/src/app/labeling/owner/page.tsx` — Owner 운영 현황.
- `web/src/app/labeling/owner/research/page.tsx` — 접힌 연구 도구 허브.
- `web/src/app/labeling/_role-pages.test.tsx` — 주요 화면 SSR 문구·링크·write 부재 테스트.

### 수정 파일

- `web/src/lib/labelingRouteAccess.ts` — 역할별 route category와 redirect.
- `web/src/lib/labelingRouteAccess.test.ts` — deep-link 접근 매트릭스.
- `web/src/lib/motionBlindReviewApi.ts` — 새 GET 클라이언트와 canary union 타입.
- `web/src/app/api/labeling-v3/blind/canary/[cohortId]/route.ts` — 동일 링크 owner/labeler 분기.
- `web/src/app/api/labeling-v3/blind/canary/[cohortId]/route.test.ts` — owner 현황과 labeler blind 회귀.
- `web/src/app/labeling/blind/canary/[cohortId]/page.tsx` — 역할별 canary 화면.
- `web/src/app/labeling/layout.tsx` — 인증은 유지하고 navigation을 `RoleShell`에 위임.
- `web/src/app/labeling/page.tsx` — 역할별 landing.
- `web/src/app/labeling/_home-switch.tsx` — labeler today/owner overview 분기.
- `web/src/app/labeling/_blind-review-queue.tsx` — `오늘 작업` 제목과 완료/이전 활동일 UX.
- `web/src/app/labeling/me/page.tsx` — legacy 내 라벨 대신 blind 본인 기록.
- `web/src/app/labeling/team/page.tsx` — Owner 팀 관리 진입점 문구와 그룹/튜토리얼 연결.
- `web/src/app/labeling/pending/page.tsx` — 미승인 단일 화면 문구.
- `web/src/app/labeling/_blind-review-ui.test.tsx` — 승인된 업무 문구 회귀.
- `docs/FEATURES.md`, `docs/DATABASE.md`, `specs/next-session.md`, `.claude/donts-audit.md` — additive SOT.

---

### Task 1: 역할별 경로와 내비게이션 순수 계약

**Files:**
- Create: `web/src/lib/labelingRoleNavigation.ts`
- Create: `web/src/lib/labelingRoleNavigation.test.ts`
- Modify: `web/src/lib/labelingRouteAccess.ts`
- Modify: `web/src/lib/labelingRouteAccess.test.ts`

**Interfaces:**
- Consumes: `LabelingAccessInfo['status']` from `web/src/lib/labelingApi.ts`.
- Produces:
  - `type LabelingRole = 'owner' | 'labeler' | 'unapproved'`
  - `resolveLabelingRole(status): LabelingRole`
  - `roleHome(role): string`
  - `roleNavItems(role): readonly RoleNavItem[]`
  - 확장된 `RouteCategory = 'public' | 'apply' | 'pending' | 'owner' | 'labeler' | 'shared' | 'tutorial' | 'landing'`

- [ ] **Step 1: 역할 순수 계약 RED 테스트 작성**

```ts
expect(resolveLabelingRole('owner')).toBe('owner');
expect(resolveLabelingRole('labeler')).toBe('labeler');
expect(resolveLabelingRole('pending')).toBe('unapproved');
expect(roleNavItems('labeler').map((x) => x.label)).toEqual([
  '오늘 작업', '내 기록', '영상 보기',
]);
expect(roleNavItems('owner').map((x) => x.label)).toEqual([
  '운영 현황', '불일치 검수', '팀 관리',
]);
expect(roleNavItems('unapproved')).toEqual([]);
expect(roleHome('owner')).toBe('/labeling/owner');
expect(roleHome('labeler')).toBe('/labeling');
```

- [ ] **Step 2: focused RED 실행**

Run:

```bash
cd web && npm test -- src/lib/labelingRoleNavigation.test.ts
```

Expected: FAIL because `labelingRoleNavigation.ts` does not exist.

- [ ] **Step 3: 최소 역할 계약 구현**

```ts
export type LabelingRole = 'owner' | 'labeler' | 'unapproved';

export interface RoleNavItem {
  href: string;
  label: string;
  activePrefixes: readonly string[];
}

const NAV: Record<LabelingRole, readonly RoleNavItem[]> = {
  labeler: [
    { href: '/labeling', label: '오늘 작업', activePrefixes: ['/labeling/blind/'] },
    { href: '/labeling/me', label: '내 기록', activePrefixes: ['/labeling/me'] },
    { href: '/labeling/library', label: '영상 보기', activePrefixes: ['/labeling/library'] },
  ],
  owner: [
    { href: '/labeling/owner', label: '운영 현황', activePrefixes: ['/labeling/owner'] },
    { href: '/labeling/blind/conflicts', label: '불일치 검수', activePrefixes: ['/labeling/blind/conflicts'] },
    { href: '/labeling/team', label: '팀 관리', activePrefixes: ['/labeling/team', '/labeling/blind/groups'] },
  ],
  unapproved: [],
};

export function resolveLabelingRole(status: string | null): LabelingRole {
  if (status === 'owner') return 'owner';
  if (status === 'labeler') return 'labeler';
  return 'unapproved';
}

export function roleHome(role: LabelingRole): string {
  return role === 'owner' ? '/labeling/owner' : role === 'labeler' ? '/labeling' : '/labeling/pending';
}

export function roleNavItems(role: LabelingRole): readonly RoleNavItem[] {
  return NAV[role];
}
```

- [ ] **Step 4: route category와 redirect RED 테스트 추가**

```ts
expect(categorize('/labeling')).toBe('landing');
expect(categorize('/labeling/library')).toBe('shared');
expect(categorize('/labeling/blind/canary/c1')).toBe('shared');
expect(categorize('/labeling/me')).toBe('labeler');
expect(categorize('/labeling/blind/c1')).toBe('labeler');
expect(categorize('/labeling/owner')).toBe('owner');
expect(categorize('/labeling/motion')).toBe('owner');
expect(categorize('/labeling/router-review')).toBe('owner');
expect(redirectTarget(true, 'owner', 'labeler', false)).toBe('/labeling/owner');
expect(redirectTarget(true, 'labeler', 'owner', false)).toBe('/labeling');
expect(redirectTarget(true, 'owner', 'shared', false)).toBeNull();
expect(redirectTarget(true, 'labeler', 'shared', false)).toBeNull();
```

`/labeling/blind/canary/**`를 일반 `/labeling/blind/**`보다 먼저 분류한다. `/labeling`은 두 역할이
각자의 landing을 렌더하므로 `landing`으로 분류한다. `router-review`, `quarantine`, legacy 큐,
motion owner 큐는 Owner의 연구/직접 라벨링 경로다.

- [ ] **Step 5: focused GREEN과 회귀**

Run:

```bash
cd web && npm test -- src/lib/labelingRoleNavigation.test.ts src/lib/labelingRouteAccess.test.ts
```

Expected: both files PASS.

- [ ] **Step 6: commit**

```bash
git add web/src/lib/labelingRoleNavigation.ts web/src/lib/labelingRoleNavigation.test.ts \
  web/src/lib/labelingRouteAccess.ts web/src/lib/labelingRouteAccess.test.ts
git commit -m "feat: 라벨링 웹 역할별 경로 계약"
```

---

### Task 2: 읽기 전용 데이터 RPC

**Files:**
- Create: `migrations/2026-07-24_role_based_labeling_reads.sql`
- Create: `tests/test_role_based_labeling_reads_migration.py`

**Interfaces:**
- Consumes: existing `motion_clips`, `cameras`, `motion_clip_blind_submissions`,
  `motion_clip_review_slots`, `motion_clip_consensus`, `motion_clip_labeling_sessions`,
  review group/cohort tables.
- Produces:
  - `fn_list_motion_blind_history(uuid,timestamptz,uuid,text,uuid[],timestamptz,timestamptz,text,integer)`
  - `fn_list_motion_labeling_library(uuid,uuid,text,uuid[],timestamptz,timestamptz,text,text,text,timestamptz,uuid,integer)`
  - `fn_get_motion_blind_owner_overview(date)`

- [ ] **Step 1: migration 정적 RED 테스트 작성**

```python
SQL = Path("migrations/2026-07-24_role_based_labeling_reads.sql").read_text()

def test_read_functions_are_service_role_only():
    for fn in (
        "fn_list_motion_blind_history",
        "fn_list_motion_labeling_library",
        "fn_get_motion_blind_owner_overview",
    ):
        assert f"REVOKE ALL ON FUNCTION public.{fn}" in SQL
        assert "FROM PUBLIC, anon, authenticated" in SQL
        assert f"GRANT EXECUTE ON FUNCTION public.{fn}" in SQL
        assert "TO service_role" in SQL

def test_no_write_statements_inside_read_functions():
    bodies = SQL.split("-- READ FUNCTION BODY")
    assert len(bodies) == 4
    for body in bodies[1:]:
        upper = body.split("-- END READ FUNCTION BODY", 1)[0].upper()
        for forbidden in ("INSERT INTO", "UPDATE PUBLIC.", "DELETE FROM", "TRUNCATE"):
            assert forbidden not in upper

def test_library_hides_pending_labels():
    assert "WHEN consensus_status IN ('agreed','owner_resolved')" in SQL
    assert "WHEN consensus_status = 'conflict' THEN 'owner_review'" in SQL
    assert "WHEN consensus_status = 'awaiting' THEN 'awaiting'" in SQL
    assert "ELSE NULL::jsonb" in SQL
```

- [ ] **Step 2: RED 실행**

Run:

```bash
uv run pytest -q tests/test_role_based_labeling_reads_migration.py
```

Expected: FAIL because migration is absent.

- [ ] **Step 3: forward migration 작성**

Migration header:

```sql
-- role-based labeling web read models — forward-only, read-only RPC.
-- 기존 2026-07-22/23 migration은 수정하지 않는다.
BEGIN;
```

History signature and query:

```sql
-- READ FUNCTION BODY
CREATE OR REPLACE FUNCTION public.fn_list_motion_blind_history(
  p_reviewer_id uuid,
  p_cursor_submitted_at timestamptz DEFAULT NULL,
  p_cursor_id uuid DEFAULT NULL,
  p_decision text DEFAULT NULL,
  p_camera_ids uuid[] DEFAULT NULL,
  p_date_from timestamptz DEFAULT NULL,
  p_date_to timestamptz DEFAULT NULL,
  p_cohort_kind text DEFAULT NULL,
  p_limit integer DEFAULT 31
) RETURNS TABLE (
  submission_id uuid, clip_id uuid, camera_id uuid, camera_name text,
  started_at timestamptz, duration_sec double precision, media_ready boolean,
  submitted_at timestamptz, decision text, reason_code text,
  initial_gt jsonb, note text, cohort_kind text, final_status text
)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
  IF p_decision IS NOT NULL AND p_decision NOT IN ('label','hold','exclude') THEN
    RAISE EXCEPTION 'invalid decision' USING ERRCODE='22023';
  END IF;
  IF p_cohort_kind IS NOT NULL AND p_cohort_kind NOT IN ('live','canary') THEN
    RAISE EXCEPTION 'invalid cohort kind' USING ERRCODE='22023';
  END IF;
  IF (p_cursor_submitted_at IS NULL) <> (p_cursor_id IS NULL) THEN
    RAISE EXCEPTION 'cursor requires both fields' USING ERRCODE='22023';
  END IF;
  RETURN QUERY
  SELECT s.id, s.clip_id, m.camera_id, cam.name, m.started_at, m.duration_sec,
         m.r2_key IS NOT NULL, s.submitted_at, s.decision, s.reason_code,
         s.initial_gt, s.note, s.cohort_kind, c.status
  FROM public.motion_clip_blind_submissions s
  JOIN public.motion_clips m ON m.id=s.clip_id
  LEFT JOIN public.cameras cam ON cam.id=m.camera_id
  LEFT JOIN public.motion_clip_consensus c
    ON c.clip_id=s.clip_id AND c.cohort_kind=s.cohort_kind
   AND c.cohort_id IS NOT DISTINCT FROM s.cohort_id
  WHERE s.reviewer_id=p_reviewer_id
    AND (p_decision IS NULL OR s.decision=p_decision)
    AND (p_camera_ids IS NULL OR m.camera_id=ANY(p_camera_ids))
    AND (p_date_from IS NULL OR m.started_at>=p_date_from)
    AND (p_date_to IS NULL OR m.started_at<=p_date_to)
    AND (p_cohort_kind IS NULL OR s.cohort_kind=p_cohort_kind)
    AND (p_cursor_submitted_at IS NULL OR s.submitted_at<p_cursor_submitted_at
      OR (s.submitted_at=p_cursor_submitted_at AND s.id<p_cursor_id))
  ORDER BY s.submitted_at DESC, s.id DESC
  LIMIT LEAST(GREATEST(p_limit,1),100);
END;
$$;
-- END READ FUNCTION BODY
```

Library function uses a CTE named `classified`. Its classification is fixed:

```sql
-- READ FUNCTION BODY
CREATE OR REPLACE FUNCTION public.fn_list_motion_labeling_library(
  p_owner_id uuid,
  p_clip_id uuid DEFAULT NULL,
  p_label_state text DEFAULT NULL,
  p_camera_ids uuid[] DEFAULT NULL,
  p_date_from timestamptz DEFAULT NULL,
  p_date_to timestamptz DEFAULT NULL,
  p_time_from text DEFAULT NULL,
  p_time_to text DEFAULT NULL,
  p_label_source text DEFAULT NULL,
  p_cursor_started_at timestamptz DEFAULT NULL,
  p_cursor_id uuid DEFAULT NULL,
  p_limit integer DEFAULT 31
) RETURNS TABLE (
  clip_id uuid, camera_id uuid, camera_name text, started_at timestamptz,
  duration_sec double precision, label_state text, label_source text,
  final_decision text, final_gt jsonb
)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
  IF p_label_state IS NOT NULL
     AND p_label_state NOT IN ('final','awaiting','owner_review','unlabeled') THEN
    RAISE EXCEPTION 'invalid label state' USING ERRCODE='22023';
  END IF;
  IF p_label_source IS NOT NULL
     AND p_label_source NOT IN ('blind_consensus','owner_legacy','single_legacy','none') THEN
    RAISE EXCEPTION 'invalid label source' USING ERRCODE='22023';
  END IF;
  IF (p_cursor_started_at IS NULL) <> (p_cursor_id IS NULL) THEN
    RAISE EXCEPTION 'cursor requires both fields' USING ERRCODE='22023';
  END IF;
  IF (p_time_from IS NULL) <> (p_time_to IS NULL)
     OR (p_time_from IS NOT NULL AND p_time_from !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$')
     OR (p_time_to IS NOT NULL AND p_time_to !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$') THEN
    RAISE EXCEPTION 'invalid time range' USING ERRCODE='22023';
  END IF;

  RETURN QUERY
  WITH base AS (
    SELECT m.id, m.camera_id, cam.name AS camera_name, m.started_at, m.duration_sec,
           bc.status AS consensus_status, bc.final_decision AS consensus_decision,
           bc.final_gt AS consensus_gt,
           ls.reviewed_by AS legacy_reviewer, ls.legacy_gt
    FROM public.motion_clips m
    LEFT JOIN public.cameras cam ON cam.id=m.camera_id
    LEFT JOIN public.motion_clip_consensus bc
      ON bc.clip_id=m.id AND bc.cohort_kind='live'
    LEFT JOIN LATERAL (
      SELECT s.reviewed_by, COALESCE(s.current_gt,s.initial_gt) AS legacy_gt
      FROM public.motion_clip_labeling_sessions s
      WHERE s.clip_id=m.id AND s.initial_gt IS NOT NULL
      ORDER BY (s.reviewed_by=p_owner_id) DESC, s.updated_at DESC, s.id DESC
      LIMIT 1
    ) ls ON true
    WHERE m.r2_key IS NOT NULL
      AND (p_clip_id IS NULL OR m.id=p_clip_id)
      AND (p_camera_ids IS NULL OR m.camera_id=ANY(p_camera_ids))
      AND (p_date_from IS NULL OR m.started_at>=p_date_from)
      AND (p_date_to IS NULL OR m.started_at<=p_date_to)
      AND (
        p_time_from IS NULL
        OR (
          p_time_from<=p_time_to
          AND to_char(m.started_at AT TIME ZONE 'Asia/Seoul','HH24:MI')
              BETWEEN p_time_from AND p_time_to
        )
        OR (
          p_time_from>p_time_to
          AND (
            to_char(m.started_at AT TIME ZONE 'Asia/Seoul','HH24:MI')>=p_time_from
            OR to_char(m.started_at AT TIME ZONE 'Asia/Seoul','HH24:MI')<=p_time_to
          )
        )
      )
  ), classified AS (
    SELECT base.*,
      CASE
        WHEN consensus_status IN ('agreed','owner_resolved') THEN 'final'
        WHEN consensus_status = 'conflict' THEN 'owner_review'
        WHEN consensus_status = 'awaiting' THEN 'awaiting'
        WHEN legacy_gt IS NOT NULL THEN 'final'
        ELSE 'unlabeled'
      END AS public_state,
      CASE
        WHEN consensus_status IS NOT NULL THEN 'blind_consensus'
        WHEN legacy_gt IS NOT NULL AND legacy_reviewer=p_owner_id THEN 'owner_legacy'
        WHEN legacy_gt IS NOT NULL THEN 'single_legacy'
        ELSE 'none'
      END AS public_source,
      CASE
        WHEN consensus_status IN ('agreed','owner_resolved') THEN consensus_decision
        WHEN consensus_status IS NULL AND legacy_gt IS NOT NULL THEN 'label'
        ELSE NULL::text
      END AS public_decision,
      CASE
        WHEN consensus_status IN ('agreed','owner_resolved') THEN consensus_gt
        WHEN consensus_status IS NULL AND legacy_gt IS NOT NULL THEN legacy_gt
        ELSE NULL::jsonb
      END AS public_gt
    FROM base
  )
  SELECT id, camera_id, camera_name, started_at, duration_sec,
         public_state, public_source, public_decision, public_gt
  FROM classified
  WHERE (p_label_state IS NULL OR public_state=p_label_state)
    AND (p_label_source IS NULL OR public_source=p_label_source)
    AND (p_cursor_started_at IS NULL OR started_at<p_cursor_started_at
      OR (started_at=p_cursor_started_at AND id<p_cursor_id))
  ORDER BY started_at DESC, id DESC
  LIMIT LEAST(GREATEST(p_limit,1),100);
END;
$$;
-- END READ FUNCTION BODY
```

Owner overview returns one JSON row. It does not include submission bodies:

```sql
-- READ FUNCTION BODY
CREATE OR REPLACE FUNCTION public.fn_get_motion_blind_owner_overview(
  p_activity_day date
) RETURNS jsonb
LANGUAGE sql SECURITY INVOKER SET search_path = '' AS $$
  SELECT jsonb_build_object(
    'activity_day', p_activity_day,
    'groups', COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
        'group_id', g.id, 'group_name', g.name,
        'clip_total', (SELECT count(DISTINCT s.clip_id) FROM public.motion_clip_review_slots s
          WHERE s.group_id=g.id AND s.cohort_kind='live' AND s.activity_day_kst=p_activity_day),
        'members', (SELECT COALESCE(jsonb_agg(jsonb_build_object(
          'display_name', COALESCE(a.display_name,'라벨러'),
          'submitted_count', (SELECT count(*) FROM public.motion_clip_review_slots s2
            WHERE s2.group_id=g.id AND s2.reviewer_id=gm.user_id
              AND s2.cohort_kind='live' AND s2.activity_day_kst=p_activity_day
              AND s2.submitted_at IS NOT NULL)
        ) ORDER BY gm.user_id),'[]'::jsonb)
          FROM public.motion_labeling_review_group_members gm
          LEFT JOIN public.labeler_applications a ON a.user_id=gm.user_id
          WHERE gm.group_id=g.id AND gm.ended_at IS NULL),
        'agreed_count', (SELECT count(*) FROM public.motion_clip_consensus c
          WHERE c.group_id=g.id AND c.cohort_kind='live' AND c.status='agreed'
            AND EXISTS (SELECT 1 FROM public.motion_clip_review_slots x
              WHERE x.clip_id=c.clip_id AND x.activity_day_kst=p_activity_day)),
        'conflict_count', (SELECT count(*) FROM public.motion_clip_consensus c
          WHERE c.group_id=g.id AND c.cohort_kind='live' AND c.status='conflict'
            AND EXISTS (SELECT 1 FROM public.motion_clip_review_slots x
              WHERE x.clip_id=c.clip_id AND x.activity_day_kst=p_activity_day)),
        'awaiting_count', (SELECT count(*) FROM public.motion_clip_consensus c
          WHERE c.group_id=g.id AND c.cohort_kind='live' AND c.status='awaiting'
            AND EXISTS (SELECT 1 FROM public.motion_clip_review_slots x
              WHERE x.clip_id=c.clip_id AND x.activity_day_kst=p_activity_day))
      ) ORDER BY g.name)
      FROM public.motion_labeling_review_groups g WHERE g.active
    ), '[]'::jsonb),
    'open_canaries', COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
        'cohort_id', c.id, 'label', c.label, 'group_id', c.group_id,
        'clip_total', (SELECT count(DISTINCT s.clip_id) FROM public.motion_clip_review_slots s
          WHERE s.cohort_id=c.id),
        'submitted_total', (SELECT count(*) FROM public.motion_clip_review_slots s
          WHERE s.cohort_id=c.id AND s.submitted_at IS NOT NULL),
        'conflict_count', (SELECT count(*) FROM public.motion_clip_consensus x
          WHERE x.cohort_id=c.id AND x.status='conflict')
      ) ORDER BY c.created_at DESC)
      FROM public.motion_blind_review_cohorts c WHERE c.status='open'
    ), '[]'::jsonb)
  );
$$;
-- END READ FUNCTION BODY
```

Add indexes only if absent:

```sql
CREATE INDEX IF NOT EXISTS idx_motion_blind_history_reviewer_submitted
  ON public.motion_clip_blind_submissions (reviewer_id, submitted_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_motion_clips_library_started
  ON public.motion_clips (started_at DESC, id DESC) WHERE r2_key IS NOT NULL;
```

Revoke all three signatures from `PUBLIC, anon, authenticated`, grant only to `service_role`, add rollback
comments, then `COMMIT`.

- [ ] **Step 4: migration tests GREEN**

Run:

```bash
uv run pytest -q tests/test_role_based_labeling_reads_migration.py
```

Expected: PASS.

- [ ] **Step 5: 전체 Python 회귀**

Run:

```bash
uv run pytest -q
```

Expected: all existing tests plus the new migration tests PASS.

- [ ] **Step 6: commit**

```bash
git add migrations/2026-07-24_role_based_labeling_reads.sql \
  tests/test_role_based_labeling_reads_migration.py
git commit -m "feat: 권한별 라벨링 읽기 모델"
```

---

### Task 3: 서버 mapper와 read-only API

**Files:**
- Create: `web/src/lib/labelingRoleData.ts`
- Create: `web/src/lib/labelingRoleData.test.ts`
- Create: `web/src/lib/labelingRoleServer.ts`
- Create: `web/src/lib/labelingRoleServer.test.ts`
- Create: `web/src/app/api/labeling-v3/blind/history/route.ts`
- Create: `web/src/app/api/labeling-v3/blind/history/route.test.ts`
- Create: `web/src/app/api/labeling-v3/library/route.ts`
- Create: `web/src/app/api/labeling-v3/library/route.test.ts`
- Create: `web/src/app/api/labeling-v3/library/[clipId]/route.ts`
- Create: `web/src/app/api/labeling-v3/library/[clipId]/route.test.ts`
- Create: `web/src/app/api/labeling-v3/library/[clipId]/file/url/route.ts`
- Create: `web/src/app/api/labeling-v3/library/[clipId]/file/url/route.test.ts`
- Create: `web/src/app/api/labeling-v3/blind/owner/overview/route.ts`
- Create: `web/src/app/api/labeling-v3/blind/owner/overview/route.test.ts`
- Modify: `web/src/lib/motionBlindReviewApi.ts`

**Interfaces:**
- Produces `BlindHistoryResponse`, `LabelingLibraryResponse`, `OwnerOverview`,
  `getBlindHistory`, `getLabelingLibrary`, `getLabelingLibraryClip`, `getLibraryFileUrl`,
  `getOwnerOverview`.
- Cursor is opaque base64url JSON with `{v:1,t:string,id:string}` and scope hash. Decode preserves
  PostgreSQL timestamp text verbatim.
- Parser result types are fixed:

```ts
export interface RoleCursor { t: string; id: string }
export type ParseResult<T> =
  | { ok: true; value: T }
  | { ok: false; response: NextResponse };
```

- [ ] **Step 1: public types and copy RED tests**

```ts
expect(labelSourceCopy('blind_consensus')).toBe('이중 확인 완료');
expect(labelSourceCopy('owner_legacy')).toBe('기존 Owner 라벨');
expect(labelSourceCopy('single_legacy')).toBe('기존 단일 라벨');
expect(labelSourceCopy('none')).toBe('라벨 없음');
expect(labelStateCopy('awaiting')).toBe('라벨 확정 중');
expect(labelStateCopy('owner_review')).toBe('Owner 검수 중');
```

Implement exact unions:

```ts
export type PublicLabelState = 'final' | 'awaiting' | 'owner_review' | 'unlabeled';
export type PublicLabelSource =
  | 'blind_consensus' | 'owner_legacy' | 'single_legacy' | 'none';
```

- [ ] **Step 2: parser/mapper RED tests**

Test malformed cursor, partial cursor, invalid time (`24:00`), invalid state/source, limit `0/101`,
microsecond timestamp round-trip, and mapper stripping these injected keys:

```ts
const forbidden = [
  'r2_key', 'reviewer_id', 'peer_decision', 'digest', 'lease_token',
  'prediction_snapshot', 'rank_features', 'evidence_snapshot',
];
for (const key of forbidden) expect(JSON.stringify(mapped)).not.toContain(key);
```

- [ ] **Step 3: server helpers 구현**

Implement:

```ts
export function parseRoleCursor(raw: string | null, scope: string): ParseResult<RoleCursor | null>;
export function encodeRoleCursor(position: { t: string; id: string }, scope: string): string;
export function parseLibraryFilters(search: URLSearchParams): ParseResult<LibraryFilters>;
export function parseHistoryFilters(search: URLSearchParams): ParseResult<HistoryFilters>;
export function mapLibraryRow(row: LibraryRow): LabelingLibraryItem;
export function mapHistoryRow(row: HistoryRow): BlindHistoryItem;
export function mapOwnerOverview(value: unknown): OwnerOverview;
```

Use canonical UUID regex, strict RFC3339 parser from `labelingQueueCursor.ts`, `HH:mm` regex
`^(?:[01]\d|2[0-3]):[0-5]\d$`, and existing `databaseUnavailable` for generic 502 responses.

- [ ] **Step 4: API route RED tests**

History:

- `requireProductionLabelingAccess` owner → `403` because this endpoint is labeler personal history.
- reviewer id always comes from bearer, never query/body.
- RPC gets validated filters and limit+1.
- output contains own GT/note and only `final_status`, never peer content.

Library:

- owner and labeler allowed; pending denied by `requireProductionLabelingAccess`.
- all camera IDs are accepted after UUID validation; no group filter is added.
- invalid cursor/filter → 400 with `code='invalid_request'`.
- `next_cursor` uses last raw timestamp and id.
- single-item route validates UUID, calls the same read RPC with exact `p_clip_id`, and returns 404 when absent.

Media:

- validate UUID.
- authenticate first, then select only `r2_key`.
- null key → 410; signing failure → generic 502.
- response is exactly `{url, expires_in}`.

Owner overview:

- `requireOwner` only.
- activity day defaults to previous closed activity day.
- malformed day → 400.
- output never contains UUID reviewer IDs or emails; only display names and counts.

- [ ] **Step 5: route 구현**

Route pattern:

```ts
export async function GET(req: NextRequest) {
  const access = await requireProductionLabelingAccess(req);
  if (!access.ok) return access.response;
  // endpoint-specific owner/labeler check
  const parsed = parseLibraryFilters(req.nextUrl.searchParams);
  if (!parsed.ok) return parsed.response;
  const filters = parsed.value;
  if (!process.env.DEV_USER_ID) {
    return NextResponse.json({ detail: '라벨 출처를 확인할 수 없어.' }, { status: 503 });
  }
  const { data, error } = await supabaseAdmin.rpc('fn_list_motion_labeling_library', {
    p_owner_id: process.env.DEV_USER_ID,
    p_clip_id: null,
    ...filters.rpc,
    p_limit: filters.limit + 1,
  });
  if (error) return databaseUnavailable('labeling library', error);
  return NextResponse.json(buildLibraryPage(data ?? [], filters));
}
```

Do not return raw Supabase errors. Do not log request Authorization or signed URLs.

- [ ] **Step 6: browser client 추가**

Add functions to `motionBlindReviewApi.ts` using its existing `request<T>`:

```ts
export async function getBlindHistory(filters: BlindHistoryFilters): Promise<BlindHistoryResponse>;
export async function getLabelingLibrary(filters: LibraryFilters): Promise<LabelingLibraryResponse>;
export async function getLabelingLibraryClip(clipId: string): Promise<LabelingLibraryItem>;
export async function getLibraryFileUrl(clipId: string): Promise<{url:string; expires_in:number}>;
export async function getOwnerOverview(day?: string): Promise<OwnerOverview>;
```

- [ ] **Step 7: focused GREEN**

Run:

```bash
cd web && npm test -- \
  src/lib/labelingRoleData.test.ts \
  src/lib/labelingRoleServer.test.ts \
  src/app/api/labeling-v3/blind/history/route.test.ts \
  src/app/api/labeling-v3/library/route.test.ts \
  'src/app/api/labeling-v3/library/[clipId]/route.test.ts' \
  'src/app/api/labeling-v3/library/[clipId]/file/url/route.test.ts' \
  src/app/api/labeling-v3/blind/owner/overview/route.test.ts
```

Expected: all PASS.

- [ ] **Step 8: commit**

```bash
git add web/src/lib/labelingRoleData.ts web/src/lib/labelingRoleData.test.ts \
  web/src/lib/labelingRoleServer.ts web/src/lib/labelingRoleServer.test.ts \
  web/src/lib/motionBlindReviewApi.ts \
  web/src/app/api/labeling-v3/blind/history \
  web/src/app/api/labeling-v3/library \
  web/src/app/api/labeling-v3/blind/owner/overview
git commit -m "feat: 라벨링 역할별 읽기 API"
```

---

### Task 4: 반응형 역할 Shell

**Files:**
- Create: `web/src/app/labeling/_role-shell.tsx`
- Create: `web/src/app/labeling/_role-shell.test.tsx`
- Create: `web/src/app/labeling/_account-menu.tsx`
- Modify: `web/src/app/labeling/layout.tsx`

**Interfaces:**
- Consumes: `resolveLabelingRole`, `roleNavItems`, `LabelingAccessProvider`.
- Produces: `<RoleShell role pathname accountActions>{children}</RoleShell>`.

- [ ] **Step 1: SSR RED 테스트 작성**

For each role render static markup and assert:

```ts
expect(labelerHtml).toContain('오늘 작업');
expect(labelerHtml).toContain('내 기록');
expect(labelerHtml).toContain('영상 보기');
expect(labelerHtml).not.toContain('불일치 검수');
expect(ownerHtml).toContain('운영 현황');
expect(ownerHtml).toContain('불일치 검수');
expect(ownerHtml).toContain('팀 관리');
expect(ownerHtml).not.toContain('라우터 리뷰');
expect(unapprovedHtml).not.toContain('<nav');
```

Assert class contract:

```ts
expect(labelerHtml).toContain('min-w-0');
expect(labelerHtml).toContain('whitespace-nowrap');
expect(labelerHtml).toContain('fixed');
expect(labelerHtml).toContain('bottom-0');
expect(labelerHtml).toContain('lg:grid');
expect(labelerHtml).not.toContain('bg-zinc-900 text-white');
```

- [ ] **Step 2: RED 실행**

Run:

```bash
cd web && npm test -- src/app/labeling/_role-shell.test.tsx
```

Expected: FAIL because shell does not exist.

- [ ] **Step 3: Shell 구현**

Visual direction: 기능이 많은 admin SaaS가 아니라 **집중형 작업대**다. 기존 emerald palette와
zinc surfaces를 유지하되 선택 메뉴는 검은 채움 대신 `border-emerald-500 bg-emerald-50
text-emerald-950`을 쓴다.

Required layout:

```tsx
<div className="min-h-screen overflow-x-clip bg-zinc-50">
  <header className="sticky top-0 z-40 border-b border-zinc-200 bg-white/95">
    <div className="mx-auto flex min-w-0 max-w-7xl items-center px-4 py-3">
      {/* brand, role badge, compact account menu */}
    </div>
  </header>
  <div className="mx-auto min-w-0 max-w-7xl lg:grid lg:grid-cols-[220px_minmax(0,960px)] lg:gap-8">
    <aside className="hidden lg:block">{/* 3 nav items */}</aside>
    <div className="min-w-0 pb-24 lg:pb-8">{children}</div>
  </div>
  <nav className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-3 border-t bg-white p-2 lg:hidden">
    {/* icon + short Korean label; each item min-w-0 and whitespace-nowrap */}
  </nav>
</div>
```

At `sm` widths the same three tabs remain one line; content cards may become two columns. Only `lg` introduces
the 220px side menu. Long email/camera names use `truncate` with `title`.

- [ ] **Step 4: layout 인증 코드 보존 + Shell 연결**

Keep session/access effects and `LabelingAccessProvider` unchanged. Remove the old mixed `<nav>` block and
render:

```tsx
<LabelingAccessProvider value={{ access, refresh, userId: session?.user.id ?? null }}>
  <RoleShell
    role={resolveLabelingRole(status)}
    pathname={pathname}
    email={session?.user.email ?? ''}
    onChangePassword={() => setPwModalOpen(true)}
    onSignOut={signOut}
  >
    {children}
  </RoleShell>
</LabelingAccessProvider>
```

Public login/signup and unapproved screens render without work navigation. Password change and logout stay
available through `AccountMenu`.

- [ ] **Step 5: GREEN + auth regression**

Run:

```bash
cd web && npm test -- \
  src/app/labeling/_role-shell.test.tsx \
  src/lib/labelingAccess.test.ts \
  src/lib/labelingAccessGuards.test.ts \
  src/lib/labelingRouteAccess.test.ts
```

Expected: PASS.

- [ ] **Step 6: commit**

```bash
git add web/src/app/labeling/_role-shell.tsx \
  web/src/app/labeling/_role-shell.test.tsx \
  web/src/app/labeling/_account-menu.tsx \
  web/src/app/labeling/layout.tsx
git commit -m "feat: 라벨링 웹 역할별 반응형 셸"
```

---

### Task 5: 라벨러 오늘 작업과 내 기록

**Files:**
- Create: `web/src/app/labeling/_labeler-history.tsx`
- Modify: `web/src/app/labeling/_blind-review-queue.tsx`
- Modify: `web/src/app/labeling/_blind-review-progress.tsx`
- Modify: `web/src/app/labeling/_blind-review-view.ts`
- Modify: `web/src/app/labeling/_blind-review-ui.test.tsx`
- Modify: `web/src/app/labeling/me/page.tsx`
- Modify: `web/src/app/labeling/_home-switch.tsx`
- Modify: `web/src/app/labeling/page.tsx`

**Interfaces:**
- Consumes: existing `BlindWorkspace`, `getBlindQueue`, new `getBlindHistory`.
- Produces: labeler landing with latest closed activity day and own immutable history.

- [ ] **Step 1: today-work view RED tests**

Assert copy:

```ts
expect(blindTodayTitle('2026-07-22')).toBe('7월 22일 오늘 작업');
expect(blindEmptyStateMessage(doneWorkspace)).toBe('오늘 할 라벨링을 모두 끝냈어.');
expect(blindPreviousWorkCta(doneWorkspace)).toBe('이전 활동일 작업 보기');
```

The progress card shows own count and group-level aggregate only. It must not show partner decision distribution.

- [ ] **Step 2: history component RED tests**

Render mocked items and assert:

- own `decision`, `reason`, `initial_gt`, `note`, submitted time visible.
- final state only `확정됨 / 검수 중`.
- no peer/digest/reviewer UUID.
- card href is read-only history detail or library detail, never peer endpoint.

- [ ] **Step 3: today queue UX 구현**

Add visible page title `오늘 작업`, activity-day explanation `07:00 ~ 다음 날 07:00`, remaining count,
and completion card. Keep newest-first queue and existing submission continuation unchanged.

When the latest day is done, show a button that selects the next value in `workspace.available_days`. Do not
automatically skip days without explicit click. Store selected day in URL as `activity_day=YYYY-MM-DD`.

- [ ] **Step 4: blind history 구현**

`/labeling/me` becomes:

```tsx
export default function LabelingMinePage() {
  return (
    <Suspense fallback={<RolePageLoading />}>
      <LabelerHistory />
    </Suspense>
  );
}
```

Filters: date, time, camera, own decision, live/canary. Pagination is keyset and stale-response guarded with
`createRequestGeneration()`. History is immutable; no edit button.

- [ ] **Step 5: owner landing 분기**

`HomeSwitch` behavior:

```tsx
if (access?.status === 'labeler') return <BlindReviewQueue />;
if (access?.status === 'owner') return <OwnerHomeRedirect />;
return null;
```

Define `OwnerHomeRedirect` in `_home-switch.tsx`; its only effect is
`useEffect(() => router.replace('/labeling/owner'), [router])`, and it renders the neutral text
`운영 현황으로 이동 중…`. Remove `LABELING_QUEUE_SOURCE` from the default landing; keep the env resolver and
old queues reachable only from Owner direct/research links.

- [ ] **Step 6: focused tests GREEN**

Run:

```bash
cd web && npm test -- \
  src/app/labeling/_blind-review-ui.test.tsx \
  src/app/labeling/_role-pages.test.tsx \
  src/lib/labelingRoleData.test.ts
```

Expected: PASS.

- [ ] **Step 7: commit**

```bash
git add web/src/app/labeling/_labeler-history.tsx \
  web/src/app/labeling/_blind-review-queue.tsx \
  web/src/app/labeling/_blind-review-progress.tsx \
  web/src/app/labeling/_blind-review-view.ts \
  web/src/app/labeling/_blind-review-ui.test.tsx \
  web/src/app/labeling/_role-pages.test.tsx \
  web/src/app/labeling/me/page.tsx \
  web/src/app/labeling/_home-switch.tsx \
  web/src/app/labeling/page.tsx
git commit -m "feat: 라벨러 오늘 작업과 내 기록"
```

---

### Task 6: 읽기 전용 영상 보관함

**Files:**
- Create: `web/src/app/labeling/library/page.tsx`
- Create: `web/src/app/labeling/library/[clipId]/page.tsx`
- Modify: `web/src/app/labeling/_role-pages.test.tsx`

**Interfaces:**
- Consumes: `getLabelingLibrary`, `getLibraryFileUrl`, `PublicLabelState`, `PublicLabelSource`.
- Produces: all-camera read-only list/detail with no mutation control.

- [ ] **Step 1: library SSR RED 테스트**

Assert list contains filter labels:

```ts
for (const label of ['날짜', '시간대', '카메라', '최종 라벨', '라벨 상태', '라벨 출처']) {
  expect(html).toContain(label);
}
```

Assert detail contains `읽기 전용`, and does not contain:

```ts
for (const forbidden of ['라벨 저장', '보류하기', '제외하기', '수정하기']) {
  expect(detailHtml).not.toContain(forbidden);
}
```

- [ ] **Step 2: list 구현**

Use URL query parameters:

```text
date_from, date_to, time_from, time_to, camera_id,
label_state, label_source, final_decision, cursor
```

Defaults: all dates, all cameras, newest `(started_at DESC,id DESC)`. Cards show camera, KST timestamp,
duration, public state badge, source badge. `awaiting`/`owner_review` cards show no GT fields.

Use `SelectionChip` for small option sets and native `<select>`/date/time inputs for large filters. All controls
have visible `<label>` text.

- [ ] **Step 3: read-only detail 구현**

Fetch the selected item from `GET /api/labeling-v3/library/[clipId]` through
`getLabelingLibraryClip(clipId)`. Fetch the signed URL separately. Reset video state on clip change and use
request-generation stale guards.

Render:

- video;
- camera/time/duration;
- label state/source;
- final decision and final GT only when `label_state='final'`;
- `라벨 확정 중` or `Owner 검수 중` otherwise;
- back link preserving list query.

No `POST`, `PATCH`, `DELETE`, decision form, GT form, revise form, or VLM review control.

- [ ] **Step 4: component tests GREEN**

Run:

```bash
cd web && npm test -- src/app/labeling/_role-pages.test.tsx \
  src/app/api/labeling-v3/library/route.test.ts \
  'src/app/api/labeling-v3/library/[clipId]/route.test.ts' \
  'src/app/api/labeling-v3/library/[clipId]/file/url/route.test.ts'
```

Expected: PASS.

- [ ] **Step 5: commit**

```bash
git add web/src/app/labeling/library \
  web/src/app/labeling/_role-pages.test.tsx
git commit -m "feat: 읽기 전용 영상 보관함"
```

---

### Task 7: Owner 운영 홈과 역할 인식 Canary

**Files:**
- Create: `web/src/app/labeling/owner/page.tsx`
- Create: `web/src/app/labeling/owner/research/page.tsx`
- Modify: `web/src/app/api/labeling-v3/blind/canary/[cohortId]/route.ts`
- Modify: `web/src/app/api/labeling-v3/blind/canary/[cohortId]/route.test.ts`
- Modify: `web/src/lib/motionBlindReviewApi.ts`
- Modify: `web/src/app/labeling/blind/canary/[cohortId]/page.tsx`
- Modify: `web/src/app/labeling/team/page.tsx`
- Modify: `web/src/app/labeling/_role-pages.test.tsx`

**Interfaces:**
- Canary response becomes discriminated union:

```ts
export type BlindCanaryResponse =
  | {
      role: 'labeler';
      cohort_id: string;
      items: BlindQueueItem[];
      total_count: number;
      submitted_count: number;
    }
  | {
      role: 'owner';
      cohort_id: string;
      label: string | null;
      status: 'open' | 'closed';
      clip_total: number;
      reviewers: { display_name: string; submitted_count: number }[];
      counts: {
        awaiting: number;
        agreed: number;
        conflict: number;
        owner_resolved: number;
      };
      share_path: string;
    };
```

- [ ] **Step 1: owner home RED 테스트**

Render fixture and assert group cards show labeler completion counts, awaiting/conflict/agreed counts, direct
labeling button, open canary links, and collapsed `연구 도구`. It must not render submission bodies.

- [ ] **Step 2: canary API RED tests**

Replace the old `owner → 403` expectation:

```ts
expect(ownerBody.role).toBe('owner');
expect(ownerBody.reviewers).toEqual([
  { display_name: '라벨러 A', submitted_count: 8 },
  { display_name: '라벨러 B', submitted_count: 7 },
]);
expect(JSON.stringify(ownerBody)).not.toContain('initial_gt');
expect(JSON.stringify(ownerBody)).not.toContain('decision');
```

Keep labeler tests proving only own items are returned. Unapproved access remains 403.

- [ ] **Step 3: role-aware canary route 구현**

Authenticate with `requireProductionLabelingAccess`. Load and validate the cohort first.

- labeler branch: current queue RPC and own slots only.
- owner branch: query cohort metadata, active reviewer display names, per-reviewer submitted counts, and
  consensus status counts. Do not select `motion_clip_blind_submissions`.
- closed cohort: Owner receives status dashboard; labeler receives 410 expired.

- [ ] **Step 4: owner home 구현**

`/labeling/owner` loads `getOwnerOverview()` and renders:

- current previous-closed activity day;
- group cards with two labelers and counts;
- total conflict/awaiting;
- open canaries;
- operational error card only for API/media failures provided by safe aggregate;
- `직접 라벨링` → `/labeling/motion?state=unreviewed`;
- `연구 도구` → `/labeling/owner/research`.

No dashboard load may mutate slots, cohorts, groups, or submissions.

- [ ] **Step 5: research/team IA 구현**

Research hub links to existing:

- `/labeling/quarantine`
- `/labeling/router-review`
- `/labeling/tutorial`
- `/labeling/legacy`

Team page keeps approvals and links to `/labeling/blind/groups` and canary creation. The primary Owner nav still
contains only three items.

- [ ] **Step 6: role-aware canary page 구현**

Branch on `data.role`. Owner gets progress/status/share-link copy UI and conflict link. Labeler keeps own work
cards. Copying `share_path` is a client-only clipboard action and does not expose tokens.

- [ ] **Step 7: focused GREEN**

Run:

```bash
cd web && npm test -- \
  'src/app/api/labeling-v3/blind/canary/[cohortId]/route.test.ts' \
  src/app/labeling/_role-pages.test.tsx
```

Expected: PASS.

- [ ] **Step 8: commit**

```bash
git add web/src/app/labeling/owner \
  'web/src/app/api/labeling-v3/blind/canary/[cohortId]/route.ts' \
  'web/src/app/api/labeling-v3/blind/canary/[cohortId]/route.test.ts' \
  web/src/lib/motionBlindReviewApi.ts \
  'web/src/app/labeling/blind/canary/[cohortId]/page.tsx' \
  web/src/app/labeling/team/page.tsx \
  web/src/app/labeling/_role-pages.test.tsx
git commit -m "feat: Owner 운영 홈과 Canary 현황"
```

---

### Task 8: 미승인 화면, 권한 적대 테스트, 반응형 검증 계약

**Files:**
- Modify: `web/src/app/labeling/pending/page.tsx`
- Modify: `web/src/app/labeling/apply/page.tsx`
- Modify: `web/src/lib/labelingAccessGuards.test.ts`
- Modify: `web/src/lib/labelingRouteAccess.test.ts`
- Modify: `web/src/app/labeling/_role-shell.test.tsx`
- Create: `web/scripts/audit-labeling-role-ui.mjs`

**Interfaces:**
- Produces `npm run audit:labeling-role-ui` static fail-closed audit.

- [ ] **Step 1: unapproved screen RED tests**

Assert pending/rejected/unregistered screens contain one next action, password change/logout access through the
shell, and no work navigation.

- [ ] **Step 2: API authorization matrix tests**

For each new endpoint assert:

| Endpoint | Owner | Labeler | Pending |
|---|---:|---:|---:|
| history | 403 | 200 own only | 403 |
| library | 200 | 200 | 403 |
| library file | 200 | 200 | 403 |
| owner overview | 200 | 403 | 403 |
| canary | owner dashboard | own queue | 403 |

Add injected raw fields to mocked DB rows and assert response JSON excludes:

```text
r2_key Authorization reviewer_id peer_ digest lease_token
prediction_snapshot evidence_snapshot rank_features
```

- [ ] **Step 3: static responsive audit RED**

Create `web/scripts/audit-labeling-role-ui.mjs` that reads `layout.tsx`, `_role-shell.tsx`, role pages and fails
unless these tokens exist:

```js
const required = [
  'min-w-0', 'whitespace-nowrap', 'overflow-x-clip',
  'grid-cols-3', 'bottom-0', 'lg:grid-cols-[220px_minmax(0,960px)]',
];
```

It also fails if `_role-shell.tsx` contains more than three role nav entries or the old labels:

```text
큐, 내 라벨, 라우터 리뷰, 격리함, 그룹 배정
```

Do not scan the entire repo; scan only the shell/navigation files so historical screens do not cause false
positives.

- [ ] **Step 4: package script 추가**

```json
"audit:labeling-role-ui": "node scripts/audit-labeling-role-ui.mjs"
```

- [ ] **Step 5: GREEN**

Run:

```bash
cd web && npm test -- \
  src/lib/labelingAccessGuards.test.ts \
  src/lib/labelingRouteAccess.test.ts \
  src/app/labeling/_role-shell.test.tsx \
  src/app/labeling/_role-pages.test.tsx
npm run audit:labeling-role-ui
```

Expected: tests PASS and audit exits 0.

- [ ] **Step 6: commit**

```bash
git add web/src/app/labeling/pending/page.tsx \
  web/src/app/labeling/apply/page.tsx \
  web/src/lib/labelingAccessGuards.test.ts \
  web/src/lib/labelingRouteAccess.test.ts \
  web/src/app/labeling/_role-shell.test.tsx \
  web/scripts/audit-labeling-role-ui.mjs \
  web/package.json
git commit -m "test: 라벨링 역할 UX 권한과 반응형 계약"
```

---

### Task 9: 전체 검증, 문서, 배포 검토 보고

**Files:**
- Modify: `docs/FEATURES.md`
- Modify: `docs/DATABASE.md`
- Modify: `specs/next-session.md`
- Modify: `.claude/donts-audit.md`
- Create: `docs/handoff-prompts/2026-07-24-role-based-labeling-web-report.md`

**Interfaces:**
- Produces final verdict `ROLE_BASED_LABELING_WEB_READY_FOR_DEPLOY_REVIEW` or an exact blocker verdict.

- [ ] **Step 1: full web tests**

Run:

```bash
cd web && npm test
```

Expected: all tests PASS.

- [ ] **Step 2: TypeScript**

Run:

```bash
cd web && npx tsc --noEmit
```

Expected: exit 0.

- [ ] **Step 3: Python migration regression**

Run:

```bash
uv run pytest -q
```

Expected: all tests PASS.

- [ ] **Step 4: static UI audit**

Run:

```bash
cd web && npm run audit:labeling-role-ui
```

Expected: exit 0.

- [ ] **Step 5: build**

Run outside any session hook that forbids resource-heavy builds:

```bash
cd web && npm run build
```

Expected: Next.js build success and all new routes registered. If the safety hook blocks it, record
`BUILD_UNVERIFIED_SAFETY_HOOK`; do not claim build success from `tsc`.

- [ ] **Step 6: diff and security audit**

Run:

```bash
git diff --check
git diff --stat HEAD~9..HEAD
rg -n "r2_key|reviewer_id|digest|lease_token|prediction_snapshot|evidence_snapshot|rank_features" \
  web/src/app/api/labeling-v3/library \
  web/src/app/api/labeling-v3/blind/history \
  web/src/app/api/labeling-v3/blind/owner/overview
```

Every grep hit must be a server-side select, explicit mapper omission, or negative test. No response mapper may
include a forbidden field.

- [ ] **Step 7: documentation**

Document:

- role-specific navigation;
- library label-state/source semantics;
- the three new service-role read RPCs;
- canary same-link owner/labeler behavior;
- implementation-only status and unapplied migration;
- preview visual gate still required at six widths.

- [ ] **Step 8: report**

The report must include:

1. HANDOFF_OK line and starting SHA.
2. Task-by-task commit SHAs.
3. Exact changed files grouped by role shell/data/API/page.
4. Test/build outputs.
5. Blind leakage audit.
6. Migration static/runtime status.
7. Unverified items.
8. Non-actions: migration apply/main merge/deploy/group mutations.
9. Final branch/HEAD/local==origin/tree status.
10. Next deployment gate: migration rollback probe → Vercel preview → six-width screenshot matrix → role browser canary.

- [ ] **Step 9: final commit and push**

```bash
git add docs/FEATURES.md docs/DATABASE.md specs/next-session.md \
  .claude/donts-audit.md \
  docs/handoff-prompts/2026-07-24-role-based-labeling-web-report.md
git commit -m "docs: 권한별 라벨링 웹 구현 보고"
git push origin HEAD
```

Stop after push. Do not apply the migration, merge main, deploy Vercel, or modify production data.

---

## Preview Deployment Gate (이번 구현 세션에서 실행 금지)

별도 owner/Codex 승인 handoff에서만 수행한다.

1. migration dry probe in disposable/local PostgreSQL.
2. production migration apply with rollback probe and residue 0.
3. Vercel preview build.
4. owner/labeler/unapproved account role routing.
5. `320 / 360 / 390 / 768 / 1024 / 1440px` screenshots:
   - no horizontal overflow (`document.documentElement.scrollWidth <= innerWidth`);
   - nav labels and primary numbers single line;
   - account menu reachable;
   - 200% zoom core task possible.
6. owner canary same URL dashboard and labeler own queue.
7. library cross-group/all-camera read-only verification and pending-label non-disclosure.
8. only after all gates pass: main FF-only integration and production deployment review.
