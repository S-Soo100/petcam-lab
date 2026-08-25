# GME Negative Audit Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** GME가 `detected=false`로 판단한 운영 영상의 게코 존재 미탐을 승인 라벨러가 blind로 검수하고, 층화 무작위 negative 120개와 positive control 30개의 결과를 분리 측정해 다음 detector hard-case 후보로 안전하게 보존한다.

**Architecture:** Python 순수 모듈이 read-only 후보 inventory를 검증·층화·결정론적으로 섞어 private frozen manifest를 만든다. 신규 forward migration은 batch/item/submission/correction/adjudication/Dataset 결정 원장을 append-only로 저장하고 service-role RPC만 제공하며, Next.js 라벨링 웹은 이 RPC를 인증된 서버 라우트로 감싸 GME 판단과 control 여부를 숨긴다. 사람 검수 후 독립 Python scorer가 private ledger를 다시 검증해 negative-pool prevalence와 control 발견률을 분리 계산한다.

**Tech Stack:** Python 3.12, pytest, Supabase/PostgreSQL 15, Next.js 14, TypeScript, React, Vitest, R2 presigned GET

**Spec:** `docs/superpowers/specs/2026-08-23-gme-negative-audit-calibration-design.md`

## Global Constraints

- 최초 연구 범위는 **게코 존재 미탐**뿐이다. GME state interval·초 단위 활동시간 GT는 만들지 않는다.
- calibration 기본 계약은 random negative 120, blind positive control 30, 총 150이다.
- random negative는 camera-night 층화와 episode당 최대 2개 cap을 적용한다.
- positive control은 사람 GT가 `visibility in ('visible','partial')`인 development 자료에서만 가져오며 calibration 지표·Dataset 신규 기여 수에서 제외한다.
- frozen v2.5 detector identity는 `d4654168af21d26697ab1bd9a5dc4a05bd92baf5c9328800915cc347803d05b6`, checkpoint SHA-256은 `2b128f105e898bc472ed66861583ab80007dae6e94b291db497d7a2f8081f84a`다.
- 학습 cutoff는 v2.5 training manifest에서 읽어 TEST-SHEET에 SHA와 함께 고정한다. 기억이나 파일 mtime으로 추정하지 않는다.
- validation 153, internal test 151, Owner external 60, future holdout과 train exact/near-duplicate는 후보에서 제외한다.
- near-duplicate 정책은 기존 v2.5 정본과 동일한 `dhash64`, Hamming distance `<=2` reject다. distance 3부터 별개 media로 인정한다.
- GME run 없음·실패·lineage mismatch·media missing·decode failure는 negative 표본이 아니라 `unavailable`이다.
- `negative_pool_gecko_prevalence`만 산출하며 이 표본 하나로 detector recall/FNR을 주장하지 않는다.
- 오류 가능성이 높은 `suspicious` hard-case 마이닝은 이 plan의 production calibration에서 제외한다. 후속 설계가 생겨도 random-negative 분모와 같은 batch/지표에 섞지 않는다.
- 라벨러 공개 API/UI에는 stratum, GME 결과·점수·run/version, control 여부, source key/hash, 다른 제출이 없어야 한다.
- verdict는 `gecko_present | gecko_absent | uncertain | media_error` 네 값이다. `gecko_present`는 실제 영상 길이 안의 대표 timestamp와 정규화 bbox 한 개가 필수다.
- 최초 batch는 item당 최초 제출 1회만 요구한다. Owner 외 라벨러의 `gecko_present | uncertain | media_error`는 REPORT 전에 Owner adjudication이 필요하다.
- batch/item/submission/correction/adjudication/Dataset membership은 append-only다. 기존 GME run, GT, queue eligibility, 활동량, VLM, 하이라이트를 UPDATE/DELETE하지 않는다.
- TEST-SHEET와 frozen manifest가 Owner 승인·동결되기 전에는 production batch를 만들지 않는다.
- migration 적용, Preview 배포, production batch 생성은 각각 별도 실행 전 확인을 거친다.
- 모든 private JSON/CSV 원장은 mode `0600`, no-overwrite(`O_EXCL`)로 기록한다. clip/source ID와 bbox 원문은 로그나 일반 보고에 출력하지 않는다.
- DB/R2/service/git/model 배포는 해당 task가 명시한 allowlist 밖에서는 0이다. R2는 GET/HEAD만 허용한다.
- 구현은 현재 clean isolated worktree/branch에서 진행하고 dirty worktree `/Users/baek/.codex/worktrees/8faf/petcam-lab`는 읽기·stage·cleanup 대상에서 제외한다.

## File Map

- `scripts/gme_negative_audit_sampling.py`: 후보·보호집합·manifest strict schema와 결정론적 층화 표본 생성.
- `scripts/prepare_gme_negative_audit_batch.py`: read-only DB/R2 preflight, private inventory/manifest 작성, 승인 후 manifest import RPC 호출.
- `scripts/score_gme_negative_audit.py`: frozen manifest와 DB export를 독립 검증하고 private ledger/safe aggregate 생성.
- `migrations/2026-08-23_gme_negative_audit_calibration.sql`: append-only 원장, RLS/revoke, service-role RPC.
- `web/src/lib/gmeNegativeAudit.ts`: 공개 verdict/bbox 입력과 API row의 순수 strict validator.
- `web/src/lib/gmeNegativeAuditServer.ts`: 서버 권한, DB row mapping, stable error contract.
- `web/src/lib/gmeNegativeAuditApi.ts`: 브라우저 fetch wrapper. 공개 allowlist만 타입으로 표현.
- `web/src/app/api/labeling-v3/gme-audit/**`: queue/detail/media/submit/Owner API.
- `web/src/app/labeling/gme-audit/**`: GME 점검 queue/detail/Owner summary.
- `web/src/app/labeling/_normalized-bbox-editor.tsx`: 영상 좌표를 `[0,1]` bbox로 변환하는 재사용 가능한 편집기.
- `experiments/gme-negative-audit-calibration-v1/TEST-SHEET.md`: 실제 availability 확인 후 동결할 sampling/decision SOT.
- `experiments/gme-negative-audit-calibration-v1/REPORT.md`: 실행 뒤 safe aggregate와 판정 기록.

---

### Task 1: 결정론적 표본·manifest 계약

**Files:**
- Create: `scripts/gme_negative_audit_sampling.py`
- Create: `tests/test_gme_negative_audit_sampling.py`

**Interfaces:**
- Consumes: read-only candidate mappings와 protected media SHA/dHash 집합.
- Produces: `parse_candidate(raw) -> AuditCandidate`, `select_calibration_batch(..., batch_kind='calibration', negative_count=120, control_count=30) -> AuditSelectionResult` (immutable canonical source pools, pool digests, and selected items), `build_private_manifest(selection: AuditSelectionResult, ...) -> dict[str, object]`, `write_private_json_new(path, payload) -> None`.

- [ ] **Step 1: strict candidate와 중복 방어 RED 테스트 작성**

```python
def test_parse_candidate_requires_exact_lineage_and_available_media():
    raw = candidate(stratum="random_negative")
    assert parse_candidate(raw).gme_detected is False
    for key in ("gme_run_id", "detector_identity", "media_sha256", "camera_night_key", "episode_key"):
        broken = dict(raw)
        broken.pop(key)
        with pytest.raises(AuditContractError):
            parse_candidate(broken)


def test_selection_rejects_protected_and_duplicate_media():
    rows = candidates(120, stratum="random_negative")
    with pytest.raises(AuditContractError, match="protected overlap"):
        select_calibration_batch(rows, controls(30), protected_sha256={rows[0]["media_sha256"]}, protected_dhash64=set(), seed="v1")
    with pytest.raises(AuditContractError, match="near-duplicate overlap"):
        near = [dict(rows[0], media_dhash="0000000000000003"), *rows[1:]]
        select_calibration_batch(near, controls(30), protected_sha256=set(), protected_dhash64={"0000000000000000"}, seed="v1")
```

- [ ] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_gme_negative_audit_sampling.py`

Expected: import error 또는 `AuditContractError`/선택 함수 미구현으로 FAIL.

- [ ] **Step 3: exact schema와 dataclass 구현**

```python
@dataclass(frozen=True, slots=True)
class AuditCandidate:
    clip_id: str
    stratum: Literal["random_negative", "positive_control"]
    started_at: datetime
    duration_sec: float
    camera_night_key: str
    episode_key: str
    gme_run_id: str
    detector_identity: str
    media_sha256: str
    media_dhash: str
    gme_detected: bool
    human_gt_digest: str | None


@dataclass(frozen=True, slots=True)
class AuditManifestItem:
    ordinal: int
    candidate: AuditCandidate
```

`parse_candidate`는 exact key set, canonical UUID/RFC3339, finite positive duration, 64자 lowercase SHA, 16자 lowercase dHash, 고정 detector identity를 검사한다. random negative는 `gme_detected is False`와 `human_gt_digest is None`, control은 `human_gt_digest` SHA가 필수다.

- [ ] **Step 4: 층화·episode cap·blind order RED 테스트 작성**

```python
def test_selection_is_deterministic_stratified_and_caps_episode():
    first = select_calibration_batch(negatives_across_nights(), controls(30), protected_sha256=set(), protected_dhash64=set(), seed="gme-negative-audit-v1")
    second = select_calibration_batch(negatives_across_nights(), controls(30), protected_sha256=set(), protected_dhash64=set(), seed="gme-negative-audit-v1")
    assert first == second
    assert sum(x.candidate.stratum == "random_negative" for x in first) == 120
    assert sum(x.candidate.stratum == "positive_control" for x in first) == 30
    assert max(Counter(x.candidate.episode_key for x in first if x.candidate.stratum == "random_negative").values()) <= 2
    assert [x.ordinal for x in first] == list(range(1, 151))


def test_preview_canary_has_a_separate_exact_size_contract():
    selected = select_calibration_batch(negatives_across_nights(), controls(30), protected_sha256=set(), protected_dhash64=set(), seed="preview", batch_kind="preview_canary", negative_count=4, control_count=2)
    assert len(selected) == 6
    with pytest.raises(AuditContractError):
        select_calibration_batch(negatives_across_nights(), controls(30), protected_sha256=set(), protected_dhash64=set(), seed="preview", batch_kind="preview_canary", negative_count=5, control_count=1)
```

- [ ] **Step 5: 결정론적 선택 최소 구현**

후보를 `(camera_night_key, episode_key, started_at, clip_id)`로 canonical 정렬한 뒤 `sha256(f"{seed}:{stratum}:{clip_id}")` 순위로 각 camera-night에서 round-robin 선택한다. 한 episode에서 2개를 넘기지 않고 요청 count가 부족하면 `AuditShortageError`로 전체 생성을 중단한다. `batch_kind='calibration'`은 exact 120/30만, `batch_kind='preview_canary'`는 exact 4/2만 허용한다. 두 stratum을 다시 같은 seed domain의 SHA 순위로 섞어 calibration ordinal 1..150 또는 canary ordinal 1..6을 부여한다.

- [ ] **Step 6: private no-overwrite manifest 테스트와 구현**

```python
def test_private_manifest_is_0600_and_no_overwrite(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "manifest.private.json"
    write_private_json_new(path, valid_manifest())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        write_private_json_new(path, valid_manifest())
```

manifest는 schema/status, TEST-SHEET SHA, seed, cutoff, detector/checkpoint identity, candidate counts, protected manifest SHA 목록, canonical item 150개와 manifest SHA 계산 규칙을 포함한다. `os.open(..., O_CREAT|O_EXCL, 0o600)` 뒤 `os.fchmod(fd, 0o600)`을 실행한다.

- [ ] **Step 7: Task 1 전체 GREEN 및 커밋**

Run: `uv run pytest -q tests/test_gme_negative_audit_sampling.py && git diff --check`

```bash
git add scripts/gme_negative_audit_sampling.py tests/test_gme_negative_audit_sampling.py
git commit -m "feat: GME negative audit 표본 계약 추가"
```

---

### Task 2: append-only DB 원장과 service-role RPC

**Files:**
- Create: `migrations/2026-08-23_gme_negative_audit_calibration.sql`
- Create: `tests/test_gme_negative_audit_migration.py`

**Interfaces:**
- Consumes: Task 1 private manifest의 canonical batch/items.
- Produces: `fn_create_gme_negative_audit_batch`, `fn_list_gme_negative_audit_queue`, `fn_get_gme_negative_audit_item`, `fn_submit_gme_negative_audit`, `fn_append_gme_negative_audit_correction`, `fn_append_gme_negative_audit_adjudication`, `fn_append_gme_negative_audit_dataset_decision`.

- [ ] **Step 1: schema·RLS·append-only RED 테스트 작성**

```python
def test_audit_tables_are_private_and_append_only():
    for table in REQUIRED_TABLES:
        assert f"alter table public.{table} enable row level security" in SQL
        assert f"revoke all on public.{table} from public, anon, authenticated" in SQL
        assert f"before update or delete on public.{table}" in SQL
    assert "before truncate" in SQL


def test_public_rpc_rows_do_not_return_blind_fields():
    public_returns = function_returns("fn_list_gme_negative_audit_queue") + function_returns("fn_get_gme_negative_audit_item")
    for forbidden in ("stratum", "gme_run_id", "detector_identity", "media_sha256", "control"):
        assert forbidden not in public_returns
```

- [ ] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_gme_negative_audit_migration.py`

Expected: migration 파일 부재로 FAIL.

- [ ] **Step 3: immutable tables 구현**

다음 테이블을 exact 이름으로 만든다.

```sql
CREATE TABLE public.gme_negative_audit_batches (...);
CREATE TABLE public.gme_negative_audit_batch_events (...);
CREATE TABLE public.gme_negative_audit_items (...);
CREATE TABLE public.gme_negative_audit_submissions (...);
CREATE TABLE public.gme_negative_audit_corrections (...);
CREATE TABLE public.gme_negative_audit_adjudications (...);
CREATE TABLE public.gme_negative_audit_dataset_decisions (...);
```

batch는 `schema_version='gme-negative-audit-v1'`, `batch_kind='calibration'|'preview_canary'`, expected counts, TEST-SHEET/manifest/detector/checkpoint SHA와 cutoff를 저장한다. calibration은 exact 120/30/150, preview_canary는 exact 4/2/6만 허용한다. item은 `(batch_id, ordinal)`과 `(batch_id, clip_id)` unique, stratum internal, pinned run/media/dHash/assignment를 저장한다. submission은 item unique이며 verdict/bbox/timestamp/digest를 보존한다. 상태 변경은 batch row UPDATE가 아니라 batch_events에 `prepared|opened|closed|scored|invalidated`를 추가한다.

- [ ] **Step 4: append-only·service-role 권한 구현**

모든 원장 테이블에 UPDATE/DELETE/TRUNCATE blocker를 붙이고 anon/authenticated policy는 0개로 둔다. 모든 RPC는 `SECURITY INVOKER SET search_path=''`, `PUBLIC, anon, authenticated` EXECUTE revoke, service_role만 grant한다.

- [ ] **Step 5: batch import RPC strict validation 구현**

`fn_create_gme_negative_audit_batch(p_owner_id uuid, p_manifest jsonb)`는 exact schema/status/batch_kind별 exact counts·ordinal/clip·media unique/고정 identity/assignment를 transaction 안에서 검증한다. current GME job/result pointer가 manifest의 random-negative run과 일치하고 `fn_current_gme_activity(clip_id).detected=false`인 경우만 insert한다. control은 human consensus `final_decision='label'` 및 `final_gt.visibility in ('visible','partial')`를 다시 확인한다. 일부 insert 후 실패하지 않고 전체 rollback한다.

- [ ] **Step 6: queue/detail/submit RPC 구현**

```sql
CREATE FUNCTION public.fn_submit_gme_negative_audit(
  p_item_id uuid,
  p_reviewer_id uuid,
  p_verdict text,
  p_representative_sec numeric,
  p_bbox jsonb
) RETURNS TABLE (submission_id uuid, status text) ...;
```

assignment가 일치하고 latest batch event가 `opened`일 때만 최초 제출을 받는다. `gecko_present`는 `0 <= representative_sec <= duration_sec` 및 bbox exact keys `x,y,width,height`, finite `[0,1]`, positive area, `x+width<=1`, `y+height<=1`을 요구한다. 다른 verdict는 timestamp/bbox가 NULL이어야 한다. 중복 제출은 stable SQLSTATE `PT410`, 미배정은 존재를 숨기는 `PT403`, 닫힌 batch는 `PT427`을 사용한다.

- [ ] **Step 7: correction/adjudication/Dataset decision RPC 구현**

correction은 original submission을 참조하며 원본과 같은 strict verdict 계약을 사용한다. Owner adjudication은 Owner 외 라벨러의 non-absent 결과만 받되 original/correction digest를 pin한다. Dataset decision은 `include_candidate|exclude_duplicate|exclude_holdout|exclude_quality|defer`와 reason을 append하며 control stratum에는 `include_candidate`를 거부한다.

- [ ] **Step 8: migration 정적 GREEN 및 커밋**

Run: `uv run pytest -q tests/test_gme_negative_audit_migration.py tests/test_gme_activity_context_migration.py tests/test_gme_activity_blind_queue_migration.py && git diff --check`

```bash
git add migrations/2026-08-23_gme_negative_audit_calibration.sql tests/test_gme_negative_audit_migration.py
git commit -m "feat: GME negative audit append-only 원장 추가"
```

---

### Task 3: 일회용 PostgreSQL runtime probe

**Files:**
- Create: `tests/sql/gme_negative_audit_prerequisites.sql`
- Create: `tests/sql/gme_negative_audit_probe.sql`
- Create: `scripts/run_gme_negative_audit_probe.py`
- Create: `tests/test_run_gme_negative_audit_probe.py`

**Interfaces:**
- Consumes: Task 2 migration.
- Produces: local-only markers `GME_NEGATIVE_AUDIT_SCHEMA_OK`, `GME_NEGATIVE_AUDIT_BLIND_OK`, `GME_NEGATIVE_AUDIT_APPEND_ONLY_OK`, `PROBE_RESIDUE=0`.

- [ ] **Step 1: probe safety RED 테스트 작성**

```python
def test_probe_rejects_non_local_database():
    with pytest.raises(ProbeBlocked):
        validate_database_url("postgresql://prod.example.com/app")


def test_probe_requires_all_success_markers():
    assert missing_marker("GME_NEGATIVE_AUDIT_SCHEMA_OK") == "GME_NEGATIVE_AUDIT_BLIND_OK"
```

- [ ] **Step 2: prerequisites와 synthetic probe 작성**

prerequisites는 `auth.users`, cameras, motion_clips, human consensus, gme_jobs/runs, `fn_current_gme_activity`의 migration-consumed 최소 컬럼만 만든다. probe는 120 negative/30 control을 축약한 4 negative/2 control fixture로 같은 invariant를 검증한다: import 원자성, 공개 RPC blind field 0, assigned reviewer만 조회·제출, present bbox validation, duplicate submit 차단, append-only mutation 차단, control Dataset include 차단.

- [ ] **Step 3: local-only runner 구현**

기존 `run_motion_double_blind_concurrency_probe.py`의 `LocalPostgresBackend`, host allowlist, random database name, finally cleanup을 재사용한다. 임시 DB 이름은 `blind_probe_gme_negative_<hex>`만 허용하고 production DSN과 기존 DB 이름은 거부한다.

- [ ] **Step 4: RED/GREEN과 잔여 row 0 확인**

Run:

```bash
uv run pytest -q tests/test_run_gme_negative_audit_probe.py
uv run python scripts/run_gme_negative_audit_probe.py --backend local-postgres
```

Expected output:

```text
GME_NEGATIVE_AUDIT_SCHEMA_OK
GME_NEGATIVE_AUDIT_BLIND_OK
GME_NEGATIVE_AUDIT_APPEND_ONLY_OK
PROBE_RESIDUE=0
```

- [ ] **Step 5: 커밋**

```bash
git add tests/sql/gme_negative_audit_prerequisites.sql tests/sql/gme_negative_audit_probe.sql \
  scripts/run_gme_negative_audit_probe.py tests/test_run_gme_negative_audit_probe.py
git commit -m "test: GME negative audit DB runtime 실증 추가"
```

---

### Task 4: blind 서버 도메인과 API

**Files:**
- Create: `web/src/lib/gmeNegativeAudit.ts`
- Create: `web/src/lib/gmeNegativeAudit.test.ts`
- Create: `web/src/lib/gmeNegativeAuditServer.ts`
- Create: `web/src/lib/gmeNegativeAuditServer.test.ts`
- Create: `web/src/lib/gmeNegativeAuditApi.ts`
- Create: `web/src/app/api/labeling-v3/gme-audit/queue/route.ts`
- Create: `web/src/app/api/labeling-v3/gme-audit/queue/route.test.ts`
- Create: `web/src/app/api/labeling-v3/gme-audit/[itemId]/route.ts`
- Create: `web/src/app/api/labeling-v3/gme-audit/[itemId]/route.test.ts`
- Create: `web/src/app/api/labeling-v3/gme-audit/[itemId]/file/url/route.ts`
- Create: `web/src/app/api/labeling-v3/gme-audit/[itemId]/file/url/route.test.ts`
- Create: `web/src/app/api/labeling-v3/gme-audit/[itemId]/submit/route.ts`
- Create: `web/src/app/api/labeling-v3/gme-audit/[itemId]/submit/route.test.ts`
- Create: `web/src/app/api/labeling-v3/gme-audit/[itemId]/correct/route.ts`
- Create: `web/src/app/api/labeling-v3/gme-audit/[itemId]/correct/route.test.ts`

**Interfaces:**
- Consumes: Task 2 RPC, `requireProductionLabelingAccess`, existing R2 `presignGet`.
- Produces: `AuditVerdict`, `NormalizedBox`, `validateAuditSubmission`, `requireAuditAssignment`, browser API `getAuditQueue/getAuditItem/getAuditMedia/submitAudit`.

- [ ] **Step 1: strict payload RED 테스트 작성**

```typescript
it('requires timestamp and one finite normalized box only for gecko_present', () => {
  expect(validateAuditSubmission({ verdict: 'gecko_present', representative_sec: 4.2, bbox: { x: .1, y: .2, width: .3, height: .4 } }, 60)).toEqual(expect.any(Object));
  expect(() => validateAuditSubmission({ verdict: 'gecko_present', representative_sec: 61, bbox: null }, 60)).toThrow();
  expect(() => validateAuditSubmission({ verdict: 'gecko_absent', representative_sec: 1, bbox: null }, 60)).toThrow();
});
```

- [ ] **Step 2: public mapper leak RED 테스트 작성**

```typescript
it.each(['stratum', 'gme_run_id', 'detector_identity', 'media_sha256', 'control'])('never exposes %s', (key) => {
  expect(JSON.stringify(mapAuditQueueRow(privateRow()))).not.toContain(key);
  expect(JSON.stringify(mapAuditDetailRow(privateRow()))).not.toContain(key);
});
```

- [ ] **Step 3: domain/server 최소 구현**

`gmeNegativeAudit.ts`는 exact object key, four-verdict enum, finite bbox/timestamp를 검사한다. `gmeNegativeAuditServer.ts`는 bearer에서 얻은 user id만 RPC에 전달하고, assignment 검증 뒤에만 motion_clips/r2_key를 읽는다. DB 오류는 invalid=400, not_assigned=404, duplicate=409, closed=410, unavailable=502로 안정 매핑한다.

- [ ] **Step 4: queue/detail/media route RED 테스트 작성**

queue 응답은 `{items:[{item_id,ordinal,captured_at,duration_sec,media_ready,submitted}],completed,total}`만 허용한다. detail은 같은 reviewer 자신의 initial/effective verdict·timestamp·bbox와 opaque `revision`만 추가로 반환할 수 있다. `revision`은 본인의 최신 effective submission digest를 감싼 concurrency token이며 공개 필드명에 digest/hash를 쓰지 않는다. assignment 없을 때 clip query와 signer 호출은 0이어야 한다. media route는 assignment 확인 후 짧은 signed URL만 반환하고 r2_key는 응답/로그에 넣지 않는다.

- [ ] **Step 5: queue/detail/media route 구현**

API prefix는 `/api/labeling-v3/gme-audit`로 고정한다. 모든 route는 `runtime='nodejs'`, `dynamic='force-dynamic'`, no-store를 사용한다. query/body의 reviewer id는 금지하고 authenticated id만 사용한다.

- [ ] **Step 6: submit/correction route RED 테스트와 구현**

body max 16 KiB, allowed keys exact `verdict,representative_sec,bbox`로 제한한다. DB RPC 호출 전에 actual clip duration으로 pure validator를 실행한다. 응답은 `{status:'submitted'}`뿐이며 stratum/control/GME 결과를 제출 뒤에도 공개하지 않는다.

correction public body는 `verdict,representative_sec,bbox,reason,revision` exact keys를 사용한다. route는 opaque `revision`을 내부 RPC의 `expected_submission_digest`로만 변환한다. submit 응답은 계속 `{status:'submitted'}`뿐이며 caller는 detail을 다시 읽어 revision을 얻는다. 본인 initial submission이 있고 batch가 아직 `opened`일 때만 correction event를 추가하며 original submission을 절대 갱신하지 않는다. stale revision은 409, 다른 reviewer item은 404로 접는다.

- [ ] **Step 7: focused/full web GREEN 및 커밋**

Run:

```bash
cd web
npm test -- --run src/lib/gmeNegativeAudit.test.ts src/lib/gmeNegativeAuditServer.test.ts src/app/api/labeling-v3/gme-audit
npx tsc --noEmit
```

```bash
git add web/src/lib/gmeNegativeAudit.ts web/src/lib/gmeNegativeAudit.test.ts \
  web/src/lib/gmeNegativeAuditServer.ts web/src/lib/gmeNegativeAuditServer.test.ts \
  web/src/lib/gmeNegativeAuditApi.ts web/src/app/api/labeling-v3/gme-audit
git commit -m "feat: GME negative audit blind API 추가"
```

---

### Task 5: GME 점검 queue와 bbox 사용자 흐름

**Files:**
- Create: `web/src/app/labeling/_normalized-bbox-editor.tsx`
- Create: `web/src/app/labeling/_normalized-bbox-editor.test.tsx`
- Create: `web/src/app/labeling/gme-audit/page.tsx`
- Create: `web/src/app/labeling/gme-audit/[itemId]/page.tsx`
- Create: `web/src/app/labeling/gme-audit/_gme-audit-workspace.tsx`
- Create: `web/src/app/labeling/gme-audit/_gme-audit-ui.test.tsx`
- Modify: `web/src/lib/labelingRoleNavigation.ts`
- Modify: `web/src/lib/labelingRoleNavigation.test.ts`
- Modify: `web/src/lib/labelingRouteAccess.ts`
- Modify: `web/src/lib/labelingRouteAccess.test.ts`
- Modify: `web/src/app/labeling/_role-shell.tsx`
- Modify: `web/src/app/labeling/_role-shell.test.tsx`

**Interfaces:**
- Consumes: Task 4 browser API and existing `ReviewVideo`.
- Produces: `/labeling/gme-audit`, `/labeling/gme-audit/[itemId]`, normalized bbox editor `onChange(box|null)`.

- [ ] **Step 1: 체험 계약 RED 테스트 작성**

```typescript
it('shows only four human verdicts and no model hint', () => {
  const html = renderToStaticMarkup(<GmeAuditWorkspace item={publicItem()} />);
  for (const text of ['게코 있음', '게코 없음', '판단 어려움', '영상 오류']) expect(html).toContain(text);
  for (const forbidden of ['GME negative', 'control', 'detected=false', '활동량', 'confidence']) expect(html).not.toContain(forbidden);
});
```

- [ ] **Step 2: bbox 좌표 RED 테스트 작성**

```typescript
it('converts pointer drag to clamped normalized box', () => {
  expect(normalizeDrag({x: 20,y: 10}, {x: 80,y: 70}, {left: 0,top: 0,width: 100,height: 100})).toEqual({x:.2,y:.1,width:.6,height:.6});
});
```

- [ ] **Step 3: bbox editor 구현**

영상 wrapper 위 투명 SVG overlay에서 pointer down/move/up을 처리한다. 좌표를 actual displayed video rect 기준 `[0,1]`로 clamp하고 width/height가 각각 `>=0.005`인 경우만 확정한다. 키보드/모바일에서는 `bbox 다시 그리기`, `bbox 지우기` 버튼을 제공하고 화면 크기 변화에도 normalized 좌표를 유지한다.

- [ ] **Step 4: queue/detail UI 구현**

queue는 완료/전체와 ordinal만 보여주고 다음 미제출 item으로 이동한다. 하단의 `내가 완료한 항목`에는 ordinal과 정정 링크만 보이며 stratum/GME/control은 없다. detail은 영상 재생, 네 verdict, present일 때 `현재 재생 위치를 대표 시점으로 사용` 버튼과 bbox editor를 보여준다. 저장 성공 후 `저장 완료`를 표시하고 다음 item으로 이동한다. 완료 항목을 다시 열면 기존 initial/effective 본인 판정을 불러 `정정 저장`으로 append-only correction route를 호출한다. 브라우저 draft에는 verdict/timestamp/bbox와 batch/item id만 저장하며 GME/source/internal field는 없다.

- [ ] **Step 5: 역할 메뉴와 접근 분류 구현**

Owner와 승인 labeler 메뉴에 `{href:'/labeling/gme-audit', label:'GME 점검', mobileLabel:'GME', activePrefixes:['/labeling/gme-audit']}`를 추가한다. route category는 `shared`로 분류하되 실제 item 접근은 Task 4 assignment API가 다시 제한한다. `NAV_ICON`에는 `🔎`를 추가한다.

- [ ] **Step 6: 320px/mobile/desktop 및 leak 회귀 GREEN**

Run:

```bash
cd web
npm test -- --run src/app/labeling/_normalized-bbox-editor.test.tsx \
  src/app/labeling/gme-audit/_gme-audit-ui.test.tsx \
  src/lib/labelingRoleNavigation.test.ts src/lib/labelingRouteAccess.test.ts \
  src/app/labeling/_role-shell.test.tsx
npx tsc --noEmit
```

- [ ] **Step 7: 커밋**

```bash
git add web/src/app/labeling/_normalized-bbox-editor.tsx \
  web/src/app/labeling/_normalized-bbox-editor.test.tsx \
  web/src/app/labeling/gme-audit web/src/lib/labelingRoleNavigation.ts \
  web/src/lib/labelingRoleNavigation.test.ts web/src/lib/labelingRouteAccess.ts \
  web/src/lib/labelingRouteAccess.test.ts web/src/app/labeling/_role-shell.tsx \
  web/src/app/labeling/_role-shell.test.tsx
git commit -m "feat: 라벨링 웹 GME 점검 흐름 추가"
```

---

### Task 6: Owner adjudication과 독립 scorer

**Files:**
- Create: `web/src/app/api/labeling-v3/gme-audit/owner/overview/route.ts`
- Create: `web/src/app/api/labeling-v3/gme-audit/owner/overview/route.test.ts`
- Create: `web/src/app/api/labeling-v3/gme-audit/owner/[itemId]/adjudicate/route.ts`
- Create: `web/src/app/api/labeling-v3/gme-audit/owner/[itemId]/adjudicate/route.test.ts`
- Create: `web/src/app/api/labeling-v3/gme-audit/owner/[itemId]/dataset-decision/route.ts`
- Create: `web/src/app/api/labeling-v3/gme-audit/owner/[itemId]/dataset-decision/route.test.ts`
- Create: `web/src/app/labeling/gme-audit/owner/page.tsx`
- Create: `web/src/app/labeling/gme-audit/owner/_owner-audit-view.tsx`
- Create: `web/src/app/labeling/gme-audit/owner/_owner-audit-view.test.tsx`
- Modify: `web/src/lib/gmeNegativeAuditApi.ts`
- Create: `scripts/score_gme_negative_audit.py`
- Create: `tests/test_score_gme_negative_audit.py`

**Interfaces:**
- Consumes: frozen manifest, immutable submissions/corrections/adjudications.
- Produces: Owner pending-adjudication view; `score_audit(manifest, ledger) -> AuditScore`; private raw ledger and safe aggregate.

- [ ] **Step 1: effective verdict와 metric RED 테스트 작성**

```python
def test_score_separates_negative_and_control_and_requires_adjudication():
    score = score_audit(manifest(), ledger_with_owner_adjudication())
    assert score.random_negative == 120
    assert score.negative_present == 6
    assert score.negative_pool_gecko_prevalence == pytest.approx(0.05)
    assert score.control_total == 30
    assert score.control_detected == 29


def test_non_owner_non_absent_without_adjudication_fails_closed():
    with pytest.raises(ScoreContractError, match="adjudication"):
        score_audit(manifest(), ledger_non_owner_present_without_adjudication())
```

- [ ] **Step 2: strict independent scorer 구현**

manifest raw SHA, batch id, 150 exact item set/order, item/submission uniqueness, assignment, verdict shape, correction chain, Owner adjudication, media pre/post SHA를 검증한다. random negative의 valid 분모는 effective verdict가 `gecko_present` 또는 `gecko_absent`인 item만이며 `uncertain`과 `media_error`는 각각 별도 count로 보고한다. Wilson 95% interval을 표준 라이브러리 수식으로 계산하고 control을 절대 negative 분모에 넣지 않는다. duplicate/strata descriptive count와 valid bbox 비율을 함께 출력한다.

- [ ] **Step 3: private output/no-overwrite 구현**

`score` CLI는 DB read-only export를 canonical private ledger로 먼저 0600/O_EXCL 저장하고, safe aggregate에는 batch id, counts, prevalence/CI, control detection, uncertain/media_error, camera-night aggregate만 남긴다. clip/source/reviewer id, bbox, raw timestamp는 safe aggregate에서 제외한다.

- [ ] **Step 4: Owner API/UI RED 테스트 작성**

Owner 아닌 요청은 DB 호출 전 403이다. overview는 aggregate와 `needs_adjudication` item만 반환하고 control 여부는 Owner 화면에서만 볼 수 있다. adjudicate body는 `final_verdict,representative_sec,bbox,reason,expected_submission_digest` exact keys이며 stale digest는 409다. dataset-decision body는 `decision,reason,expected_effective_digest` exact keys이고 control 또는 미완료 adjudication의 `include_candidate`를 409로 거부한다.

- [ ] **Step 5: Owner API/UI 구현**

Owner 화면에는 완료율, random/control 분리 count, non-owner non-absent adjudication queue를 표시한다. Dataset candidate 결정 버튼은 adjudication 완료 후에만 열고 `positive_control`에서는 숨긴다. `gmeNegativeAuditApi.ts`에 `getAuditOwnerOverview`, `adjudicateAuditItem`, `decideAuditDatasetMembership` wrapper를 추가한다. 이 화면도 기존 GME run/GT를 수정하지 않는다.

- [ ] **Step 6: GREEN 및 커밋**

Run:

```bash
uv run pytest -q tests/test_score_gme_negative_audit.py
cd web
npm test -- --run src/app/api/labeling-v3/gme-audit/owner src/app/labeling/gme-audit/owner/_owner-audit-view.test.tsx
npx tsc --noEmit
```

```bash
git add scripts/score_gme_negative_audit.py tests/test_score_gme_negative_audit.py \
  web/src/app/api/labeling-v3/gme-audit/owner web/src/app/labeling/gme-audit/owner
git commit -m "feat: GME negative audit 판정과 점수 원장 추가"
```

---

### Task 7: read-only availability preflight와 TEST-SHEET 동결 준비

**Files:**
- Create: `scripts/prepare_gme_negative_audit_batch.py`
- Create: `tests/test_prepare_gme_negative_audit_batch.py`
- Create: `experiments/gme-negative-audit-calibration-v1/TEST-SHEET.md`
- Create: `experiments/gme-negative-audit-calibration-v1/REPORT.md`

**Interfaces:**
- Consumes: Task 1 selector, current Supabase/R2 read-only state, protected artifact SHA pins.
- Produces: `availability.private.json`, `batch-manifest.private.json`, locked TEST-SHEET candidate; `--apply`일 때만 Task 2 import RPC.

- [ ] **Step 1: dry-run/apply 분리 RED 테스트 작성**

```python
def test_default_preflight_never_writes_db_or_r2(fake_clients, tmp_path):
    run_preflight(config(tmp_path), db=fake_clients.db, r2=fake_clients.r2, apply=False)
    assert fake_clients.db.write_calls == []
    assert fake_clients.r2.write_calls == []


def test_apply_requires_exact_test_sheet_and_manifest_sha(fake_clients, tmp_path):
    with pytest.raises(PreflightError, match="TEST-SHEET"):
        import_batch(config(tmp_path), expected_test_sheet_sha="0" * 64, apply=True)
```

- [ ] **Step 2: read-only candidate inventory 구현**

DB에서 `clip_purpose='production'`, training cutoff 이후, pinned detector의 succeeded current job/run만 읽는다. random negative는 current `fn_current_gme_activity.detected=false`; controls는 development human consensus visible/partial이다. R2는 GET/HEAD로 media bytes SHA와 decode를 검증하고 representative frame dHash를 계산한다. protected manifests의 SHA와 media SHA/dHash를 exact pin으로 받아 exact/near-duplicate를 제거한다.

- [ ] **Step 3: preflight artifact와 shortage 구현**

availability에는 전체 후보 수, camera 수, camera-night 수, episode 수, unavailable reason aggregate만 남긴다. private inventory에는 identities를 0600으로 기록한다. 기본 assignment는 환경의 `DEV_USER_ID` Owner이며, 다른 승인 라벨러를 쓰려면 manifest 생성 전에 exact reviewer UUID 목록을 TEST-SHEET에 추가 승인한다. 120/30 또는 strata coverage가 부족하면 manifest/import 파일을 만들지 않고 `GME_NEGATIVE_AUDIT_SHORTAGE`로 끝낸다.

- [ ] **Step 4: TEST-SHEET에 실행 전 고정값 작성**

문서는 다음 exact 항목을 담는다: research question, pinned detector/checkpoint/training-manifest SHA와 cutoff, negative=120/control=30, seed=`gme-negative-audit-calibration-v1`, episode cap=2, protected artifact SHA 목록, selection algorithm version, verdict/bbox rules, valid/invalid definitions, Wilson CI, DB/R2 write allowlist, manifest SHA가 실행으로 채워지는 freeze section. 판정 label은 exact 세 값이다: protected/lineage violation 또는 valid random negative 100 미만 또는 positive-control `gecko_present` 27/30 미만이면 `INVALID_CALIBRATION`; 그 외 confirmed negative miss가 0이면 `AUDIT_VALID_NO_MISS`; 1개 이상이면 `AUDIT_VALID_MISSES_FOUND`. 어떤 label도 production detector 채택을 뜻하지 않는다. TEST-SHEET는 manifest 생성 전 Owner가 다시 승인하고 이후 수정하지 않는다.

- [ ] **Step 5: REPORT skeleton 작성**

REPORT에는 raw identity 없이 execution status, artifact SHA, counts, prevalence/CI, control detection, uncertain/media_error, camera-night descriptive aggregate, leakage/decode/duplicate count, adopt/hold/reject, 다음 사람 작업만 기록하도록 고정한다.

- [ ] **Step 6: focused GREEN 및 커밋**

Run: `uv run pytest -q tests/test_prepare_gme_negative_audit_batch.py tests/test_gme_negative_audit_sampling.py tests/test_score_gme_negative_audit.py && git diff --check`

```bash
git add scripts/prepare_gme_negative_audit_batch.py tests/test_prepare_gme_negative_audit_batch.py \
  experiments/gme-negative-audit-calibration-v1/TEST-SHEET.md \
  experiments/gme-negative-audit-calibration-v1/REPORT.md
git commit -m "feat: GME negative audit 사전등록과 batch 준비 추가"
```

---

### Task 8: 통합 검증, Preview canary, production 사람 작업 경계

**Files:**
- Modify: `docs/FEATURES.md`
- Modify: `docs/DATABASE.md`
- Create: `docs/handoff-prompts/2026-08-23-gme-negative-audit-calibration-report.md`

**Interfaces:**
- Consumes: Tasks 1–7 전체.
- Produces: implementation commit, test evidence, Preview canary 결과, 승인 후 frozen 150-item batch 또는 fail-closed shortage.

- [ ] **Step 1: 전체 회귀 실행**

```bash
uv run pytest -q
cd web
npm test -- --run
npx tsc --noEmit
npx next build
```

Expected: Python baseline의 기존 skip만 유지, web 전부 PASS, type/build exit 0. repo hook이 특정 build wrapper를 차단하면 허용된 동등 `next build`만 사용하고 결과를 기록한다.

- [ ] **Step 2: local DB probe 재실행**

Run: `uv run python scripts/run_gme_negative_audit_probe.py --backend local-postgres`

Expected: Task 3의 네 marker exact 출력과 residue 0.

- [ ] **Step 3: 문서와 보안 self-review**

`docs/FEATURES.md`에는 GME 점검의 목적·blind UI·자동 제외 금지를, `docs/DATABASE.md`에는 7개 append-only 원장과 service-role RPC를 기록한다. AST/grep으로 새 browser route에서 `stratum|gme_run_id|detector_identity|media_sha256|control` 공개 응답 0, DB/R2 mutation allowlist 밖 호출 0을 확인한다.

- [ ] **Step 4: 코드 리뷰 요청과 finding 처리**

`superpowers:requesting-code-review`로 spec/plan/diff를 검토한다. Critical/Important를 RED 재현 없이 문구로만 닫지 않는다. fix는 최대 3회 loop 안에서 TDD로 반영하고 회귀를 다시 실행한다.

- [ ] **Step 5: implementation 문서 커밋**

```bash
git add docs/FEATURES.md docs/DATABASE.md docs/handoff-prompts/2026-08-23-gme-negative-audit-calibration-report.md
git commit -m "docs: GME negative audit 구현 검증 기록"
```

- [ ] **Step 6: Preview 전용 canary 실행 — 별도 Owner 확인 후**

forward migration을 승인된 Preview DB에만 적용하고 Preview web을 배포한다. 합성/개발 clip 6개(negative 4/control 2)로 batch를 만들며 protected holdout과 production batch는 사용하지 않는다. Owner+라벨러 계정으로 queue/detail/media/submit을 확인하고 API capture에서 forbidden field 0, unauth/미배정 404/403, bbox mobile/desktop, duplicate submit, append-only를 검증한다. canary row는 삭제하지 않고 batch event `closed`를 추가한다.

- [ ] **Step 7: production availability dry-run — read-only**

Task 7 CLI를 `apply=false`로 실행해 availability와 shortage만 보고한다. DB/R2 write 0과 protected 접근 0을 독립 확인한 뒤 실제 count/camera-night/episode aggregate와 TEST-SHEET SHA를 Owner에게 제시한다.

- [ ] **Step 8: TEST-SHEET 재승인 후 manifest freeze**

Owner가 exact TEST-SHEET를 승인하면 private inventory에서 Task 1 selector를 정확히 1회 실행해 `batch-manifest.private.json`을 O_EXCL로 만든다. manifest SHA와 120/30/150, overlap 0, unavailable 0을 독립 검증한다. 실패 artifact를 삭제·덮어쓰기·재실행하지 않고 새 attempt root와 새 승인을 사용한다.

- [ ] **Step 9: production batch 생성 — 별도 Owner 확인 후**

승인된 TEST-SHEET SHA와 manifest SHA를 CLI `--apply`에 exact 전달해 import RPC를 한 번 호출한다. 생성 후 batch/items/events exact count, assignment, public leak 0을 read-only 검증하고 batch event `opened`를 추가한다. 기존 GME/GT/queue/model/R2 object 변경은 0이어야 한다.

- [ ] **Step 10: 사람 검수와 결과 경계 보고**

라벨링 웹 `GME 점검`에서 150개를 검수한다. Owner 외 non-absent는 Owner adjudication 뒤 scorer를 한 번 실행한다. REPORT에는 safe aggregate만 옮기고, Dataset candidate 편입·재학습·checkpoint 교체·production 배포는 새 Decision Gate와 별도 승인 전까지 시작하지 않는다.
