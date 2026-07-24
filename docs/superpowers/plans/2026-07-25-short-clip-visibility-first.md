# Short Clip Visibility-first Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 짧은 장치 오류 clip을 R2에서 삭제하지 않고 DB 원장 기준으로 앱·웹·분석 소비자에서 숨기며, 자동 제외 해제가 사람 판정을 절대 바꾸지 않게 한다.

**Architecture:** `petcam-lab`의 forward migration이 복구 RPC 의미와 `motion_clips` Owner SELECT RLS를 교정한다. 기존 라벨링 web consumer guard에 더해 backend media signer가 service_role 우회 접근을 차단한다. Mac mini worker는 detection/write만 활성화하고 delete switch는 영구적으로 0을 유지한다.

**Tech Stack:** PostgreSQL 15/Supabase RLS, Python 3.12/FastAPI/pytest, Next.js 14/TypeScript/Vitest, Vercel, Fly.io, macOS LaunchAgent

## Global Constraints

- Design SOT: `/Users/baek/petcam-lab/.worktrees/short-clip-visibility/docs/superpowers/specs/2026-07-25-short-clip-visibility-first-design.md`
- applied migration `2026-07-24_short_clip_device_error_retention.sql`을 수정하지 않는다.
- 새 migration은 forward-only이며 기존 함수 이름을 유지한다.
- 시스템 restore는 `motion_clip_labeling_triage`와 triage event를 쓰지 않는다.
- 앱은 Flutter 코드를 변경하지 않고 `motion_clips` RLS와 `security_invoker` view로 차단한다.
- web의 기존 `quarantined/media_deleted` 소비자 가드를 약화하지 않는다.
- signed URL은 exclusion 확인 후에만 발급한다.
- `SHORT_CLIP_RETENTION_DELETE_ENABLED=0`을 모든 단계에서 유지한다.
- R2 delete/claim/lease/list/bulk/prefix 작업은 0이다.
- 실제 사람 clip으로 restore canary를 하지 않는다. 합성 transaction rollback probe만 사용한다.
- 기존 40 quarantined와 823 exclusion row를 삭제·재작성하지 않는다.
- 사람 GT·triage·session·blind·behavior·activity·VLM/Python Evidence 결과를 수정하지 않는다.
- 다른 세션의 primary checkout·untracked 파일을 건드리지 않는다.

---

### Task 1: Forward migration으로 restore와 app RLS 경계 교정

**Files:**
- Create: `migrations/2026-07-25_short_clip_visibility_first.sql`
- Create: `tests/test_short_clip_visibility_first_migration.py`

**Interfaces:**
- Replaces: `public.fn_restore_short_clip_exclusion(uuid,uuid,text,timestamptz) returns text`
- Produces: `public.fn_motion_clip_visible_to_owner(uuid,uuid) returns boolean`
- Alters: policy `own clips select` on `public.motion_clips`

- [ ] **Step 1: RED 정적 테스트 작성**

다음 계약을 정확히 검사한다.

```python
def test_restore_never_writes_human_triage(function_body: str):
    assert "motion_clip_labeling_triage " not in function_body
    assert "motion_clip_labeling_triage_events" not in function_body
    assert "owner_decision" not in function_body


def test_app_visibility_hides_only_terminal_system_exclusions(sql_lower: str):
    assert "fn_motion_clip_visible_to_owner" in sql_lower
    assert "state in ('quarantined','media_deleted')" in sql_lower
    assert 'alter policy "own clips select"' in sql_lower


def test_physical_delete_not_added(sql_lower: str):
    assert "delete from public.motion_clips" not in sql_lower
    assert "delete from public.motion_clip_system_exclusions" not in sql_lower
```

- [ ] **Step 2: RED 확인**

```bash
uv run pytest -q tests/test_short_clip_visibility_first_migration.py
```

Expected: migration missing으로 FAIL.

- [ ] **Step 3: visibility helper 구현**

helper는 `SECURITY DEFINER`, `STABLE`, `SET search_path=''`이며 owner와 exclusion만 boolean으로 판정한다.

```sql
CREATE OR REPLACE FUNCTION public.fn_motion_clip_visible_to_owner(
  p_clip_id uuid,
  p_owner_id uuid
) RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
  SELECT
    p_owner_id = auth.uid()
    AND NOT EXISTS (
      SELECT 1
      FROM public.motion_clip_system_exclusions sx
      WHERE sx.clip_id = p_clip_id
        AND sx.state IN ('quarantined','media_deleted')
    );
$$;

REVOKE ALL ON FUNCTION public.fn_motion_clip_visible_to_owner(uuid,uuid)
  FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.fn_motion_clip_visible_to_owner(uuid,uuid)
  TO authenticated, service_role;

ALTER POLICY "own clips select" ON public.motion_clips
  USING (public.fn_motion_clip_visible_to_owner(id, owner_id));
```

직접 호출은 boolean 외 raw 값을 반환하지 않는다. delete policy는 변경하지 않는다.

- [ ] **Step 4: restore RPC 최소 교체**

기존 입력 검증, lock, `media_deleted` PT428, non-quarantined PT409, lease PT409를 보존한다. triage lock/upsert/event를 제거하고 다음만 수행한다.

```sql
UPDATE public.motion_clip_system_exclusions
SET state = 'restored',
    restored_at = p_now,
    restored_by = p_actor_id,
    restore_reason = p_reason,
    delete_after = NULL,
    delete_lease_token = NULL,
    delete_lease_expires_at = NULL,
    delete_worker_host = NULL,
    updated_at = clock_timestamp()
WHERE id = ex.id;
```

그 뒤 `motion_clip_system_exclusion_events.owner_restored` 한 건을 append하고 `'restored'`를 반환한다.

- [ ] **Step 5: GREEN 확인 및 커밋**

```bash
uv run pytest -q tests/test_short_clip_visibility_first_migration.py
git diff --check
git add migrations/2026-07-25_short_clip_visibility_first.sql \
  tests/test_short_clip_visibility_first_migration.py
git commit -m "fix: 짧은 영상 복구와 앱 가시성 경계 분리"
```

### Task 2: 실제 PostgreSQL rollback probe

**Files:**
- Create: `tests/sql/short_clip_visibility_first_prerequisites.sql`
- Create: `tests/sql/short_clip_visibility_first_probe.sql`
- Create: `scripts/run_short_clip_visibility_first_probe.py`
- Create: `tests/test_short_clip_visibility_first_runtime_probe.py`

**Interfaces:**
- Consumes: Task 1 migration
- Produces markers: `RESTORE_TRIAGE_IMMUTABLE_OK`, `APP_RLS_VISIBILITY_OK`, `PROBE_RESIDUE=0`

- [ ] **Step 1: RED runner 테스트 작성**

local PostgreSQL URL만 허용하고 임시 DB 이름 prefix를 `short_visibility_probe_`로 고정한다. create/drop 실패는 nonzero, production hostname은 거부한다.

- [ ] **Step 2: RED 확인 후 최소 runner 구현**

실행 순서:

```text
temporary database create
→ prerequisites
→ applied 2026-07-24 migration
→ new 2026-07-25 migration
→ probe SQL
→ finally temporary database drop
```

- [ ] **Step 3: probe 시나리오 구현**

transaction 안에서 합성 clip을 사용해 다음을 assert한다.

```text
skip triage md5 pre == post
label triage md5 pre == post
no triage remains no triage
quarantined -> restored + one system event
active lease -> PT409 + state fingerprints unchanged
authenticated owner: quarantined/media_deleted 0, restored/candidate visible
authenticated other owner: all 0
service_role: all rows visible
```

마지막에 rollback하고 fixture/table/role residue 0을 확인한다.

- [ ] **Step 4: 실제 PG15 3회 실행**

```bash
for i in 1 2 3; do
  uv run python scripts/run_short_clip_visibility_first_probe.py
done
```

Expected each run:

```text
RESTORE_TRIAGE_IMMUTABLE_OK
APP_RLS_VISIBILITY_OK
PROBE_RESIDUE=0
```

- [ ] **Step 5: 테스트와 커밋**

```bash
uv run pytest -q tests/test_short_clip_visibility_first_runtime_probe.py
git add tests/sql/short_clip_visibility_first_prerequisites.sql \
  tests/sql/short_clip_visibility_first_probe.sql \
  scripts/run_short_clip_visibility_first_probe.py \
  tests/test_short_clip_visibility_first_runtime_probe.py
git commit -m "test: 짧은 영상 visibility 경계 실 DB 검증"
```

### Task 3: backend signed URL fail-closed guard

**Files:**
- Modify: `backend/clip_perms.py`
- Modify: `backend/routers/clips.py`
- Modify: `tests/test_clips_api.py`

**Interfaces:**
- Produces: `ensure_clip_media_visible(clip_id: str, sb: Client) -> None`
- Consumes: `motion_clip_system_exclusions.state`

- [ ] **Step 1: signer 0회 RED 테스트 작성**

`quarantined`면 404, `media_deleted`면 410, exclusion 없음/restored면 기존 signed URL을 반환하도록 테스트한다. DB lookup 예외는 502이며 signer는 0회다.

- [ ] **Step 2: focused RED 확인**

```bash
uv run pytest -q tests/test_clips_api.py -k "system_exclusion or signed_url"
```

- [ ] **Step 3: 최소 guard 구현**

```python
def ensure_clip_media_visible(clip_id: str, sb: Client) -> None:
    # service_role RLS bypass 뒤에도 signer 직전에 시스템 원장을 확인한다.
    ...
```

guard 응답에는 DB 원문, r2_key, exclusion UUID를 넣지 않는다. `get_clip_file`,
`get_clip_file_url`, `get_clip_thumbnail_url`, `get_clip_thumbnail`에서
`load_clip_with_perms` 직후, signed URL 생성 전 호출한다.

- [ ] **Step 4: GREEN·전체 clips 테스트·커밋**

```bash
uv run pytest -q tests/test_clips_api.py
git add backend/clip_perms.py backend/routers/clips.py tests/test_clips_api.py
git commit -m "fix: 자동 제외 영상 media URL 발급 차단"
```

### Task 4: Owner 웹 문구를 “시스템 해제” 의미로 교정

**Files:**
- Modify: `web/src/app/labeling/motion/auto-excluded/_auto-excluded-list.tsx`
- Modify: `web/src/app/labeling/motion/auto-excluded/_auto-excluded-list.test.tsx`
- Modify: `web/src/lib/labelingV3Api.ts`

**Interfaces:**
- Keeps: `restoreMotionSystemExclusion(clipId, reason)` API signature
- Changes copy only: `라벨 대상으로 복구` → `자동 제외만 해제`

- [ ] **Step 1: RED copy/behavior 테스트**

quarantined 카드에 다음 문구가 있어야 한다.

```text
자동 제외만 해제
기존 사람 판정은 유지돼.
라벨 대상으로 바꾸려면 영상 상세에서 별도로 변경해.
```

버튼 클릭 payload와 API endpoint는 기존과 동일해야 한다.

- [ ] **Step 2: RED 확인**

```bash
cd web
npm test -- --run src/app/labeling/motion/auto-excluded/_auto-excluded-list.test.tsx
```

- [ ] **Step 3: 최소 UI 수정**

상태 카드·cursor·restore request generation은 변경하지 않는다. 성공 notice는
`자동 제외를 해제했어. 기존 사람 판정은 유지돼.`로 표시한다.

- [ ] **Step 4: GREEN·TypeScript·커밋**

```bash
cd web
npm test -- --run src/app/labeling/motion/auto-excluded/_auto-excluded-list.test.tsx
npx tsc --noEmit
cd ..
git add web/src/app/labeling/motion/auto-excluded/_auto-excluded-list.tsx \
  web/src/app/labeling/motion/auto-excluded/_auto-excluded-list.test.tsx \
  web/src/lib/labelingV3Api.ts
git commit -m "fix: 자동 제외 해제와 사람 판정 변경 UX 분리"
```

### Task 5: 전체 검증과 배포 전 보고

**Files:**
- Modify: `docs/DATABASE.md`
- Modify: `docs/FEATURES.md`
- Modify: `specs/next-session.md`
- Modify: `.claude/donts-audit.md`
- Create: `docs/handoff-prompts/2026-07-25-short-clip-visibility-first-report.md`

- [ ] **Step 1: 전체 회귀**

```bash
uv run pytest -q
cd web && npm test && npx tsc --noEmit
cd ..
git diff --check
```

- [ ] **Step 2: 금지동작 감사**

확인:

```text
R2 delete code 신규 0
SHORT_CLIP_RETENTION_DELETE_ENABLED=1 신규 0
triage write in restore function 0
Flutter 변경 0
raw key/token/UUID 응답 0
```

- [ ] **Step 3: 문서·보고서 커밋**

보고서에 task별 RED→GREEN, PG markers, 변경 파일, 미검증 운영 항목, 정확한 판정을 기록한다.

```bash
git add docs/DATABASE.md docs/FEATURES.md specs/next-session.md \
  .claude/donts-audit.md \
  docs/handoff-prompts/2026-07-25-short-clip-visibility-first-report.md
git commit -m "docs: 짧은 오류 영상 visibility-first 운영 기록"
git push origin HEAD
```

판정:

```text
SHORT_CLIP_VISIBILITY_FIRST_READY_FOR_DEPLOY
```

### Task 6: production apply·app/web smoke·Mac mini write enable

**Files:**
- Modify after verification: deployment report from Task 5, additive only

**Interfaces:**
- Runtime host: `baeg-endeuui-Macmini.local`
- Runtime label: `com.petcam.short-clip-retention`
- Required runtime flags: `1/1/0`

- [ ] **Step 1: FF-only main integration**

clean disposable worktree에서 `origin/main`이 feature tip의 ancestor인지 확인하고 FF-only push한다. non-FF면 정지한다.

- [ ] **Step 2: production pre-fingerprint와 migration apply**

사람 triage/session/GT/consensus와 기존 40 quarantined의 fingerprint를 저장한 뒤 Supabase
`apply_migration`으로 새 forward migration만 적용한다.

- [ ] **Step 3: production transaction rollback probe**

실제 사람 clip을 사용하지 않는다. 합성 fixture를 transaction 안에서 만들고 Task 2 시나리오를
실행한 뒤 rollback한다. residue 0과 pre-fingerprint 불변을 확인한다.

- [ ] **Step 4: Vercel·Fly 배포**

```bash
cd web && npm run build
cd ..
flyctl deploy --config fly.api.toml
```

Vercel production은 main의 READY deployment를 확인하고 `label.tera-ai.uk`를 smoke한다.
Fly는 `https://api.tera-ai.uk/health` 200과 deployed commit을 확인한다.

- [ ] **Step 5: app/web read-only smoke**

Owner JWT로 확인:

```text
motion_clips direct list: quarantined 0
motion_clips direct single: quarantined 0
v_clip_effective_activity: quarantined 0
web default queue/library: quarantined 0
web auto-excluded: current 40 visible
media signer: quarantined signer 0
```

- [ ] **Step 6: Mac mini flags를 1/1/0으로 설치**

`ssh home-mac`만 사용한다. hostname, repo HEAD, service working directory를 확인한 뒤 installer로
다시 설치한다. expected host 우회 금지다.

```text
SHORT_CLIP_RETENTION_ENABLED=1
SHORT_CLIP_RETENTION_WRITE_ENABLED=1
SHORT_CLIP_RETENTION_DELETE_ENABLED=0
```

- [ ] **Step 7: canary와 자연 cycle**

1회 kickstart와 다음 자연 hourly cycle을 확인한다. 기존 row replay는 멱등이어야 하며, 새
P4 Cam 2(dev) 표시 4/11만 quarantine될 수 있다.

수용 조건:

```text
human triage fingerprint pre==post
off-target quarantine 0
R2 delete/claim/lease 0
LaunchAgent last exit 0
temporary media 0
```

- [ ] **Step 8: 최종 보고·Stop Point**

모든 조건을 통과했을 때만:

```text
SHORT_CLIP_VISIBILITY_FIRST_DEPLOYED_VERIFIED
```

라고 판정한다. `PHYSICAL_DELETE=DISABLED / OUT_OF_SCOPE`를 별도 줄에 명시한다. 오류가 있으면
write를 0으로 되돌리고 근거를 보존한 채 정지한다.

