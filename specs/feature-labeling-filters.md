# 라벨링 큐/내 라벨 서버사이드 필터링 Implementation Plan

> **구현 방식 (CAOF):** Standard 상단~Critical 경계. 메인이 직접 구현. 검수는 `/검수`(이종 2모델).
> **상태:** ✅ 구현 완료 (2026-07-08, 브랜치 `feat/labeling-filters`)
>
> **구현 노트 (계획 대비 변경):**
> - 썸네일: 계획의 큐응답 `thumb_url` enrich → **API `GET /clips/{id}/thumbnail/url` 일원화**(R1). `clips.py:get_clip_thumbnail_url`이 `thumbnail_r2_key` NULL 시 `r2_key` `.jpg` 파생(`_thumb_key_from_r2`). 프론트는 `getClipThumbnailUrl` clip별 lazy fetch.
> - VLM 태그(목표 4 추가): 큐 카드에 `🔍{action}` / `미분석` 구분.
> - 필터: 계획대로 서버사이드 — queue 5축(camera/date/vlm_action/has_vlm) + mine 4축(action/lick_target/camera/date) + `filter-options`. vlm·mine camera 는 역쿼리.
> - 커밋: `4eea96b`(프론트 썸네일+VLM) · `21c1cf3`(프론트 필터) · `fd16c62`(backend R1~R5). 테스트 labels 41 + 스모크 107 통과.
> - **배포:** 프론트 Vercel(main 머지 자동) + backend `flyctl deploy --config fly.api.toml --app petcam-api`(별도, 두 달치 additive 동반).
> - 세션 중 원칙 전환 이력: 프론트+백 → "backend는 API개발자 요청서"(바탕화면 `petcam-labeling-web-backend-요청-2026-07-08.md`) → "API개발자 위임으로 backend 직접". 최종 풀스택.

**Goal:** '큐'(`/labeling`)와 '내 라벨'(`/labeling/me`) 탭에 서버사이드 필터를 추가해, 라벨러가 특정 VLM 판정·카메라·날짜·라벨 클래스로 좁혀서 작업할 수 있게 한다.

**Architecture:** 백엔드 `labels.py`의 `list_label_queue`/`list_my_labeled` 쿼리에 필터 파라미터를 추가하고, `vlm_action`처럼 다른 테이블(`behavior_logs`)에 있는 축은 **역쿼리**(조건 맞는 `clip_id` 집합을 먼저 뽑아 `IN`/`NOT IN`)로 건다. 카메라 옵션 목록은 깨진 `GET /cameras` 대신 신규 `GET /labels/filter-options`가 `camera_clips`→`cameras` join으로 스코프에 맞게 제공. 프론트는 공통 `_filter-bar.tsx`로 두 탭에서 재사용하고 필터 상태를 URL querystring에 반영.

**Tech Stack:** FastAPI (Query 파라미터), supabase-py (postgrest 체인), Next.js App Router (useSearchParams/router), 기존 `Badge`/`Button`/`Card` UI.

---

## 설계 결정 (사용자 리뷰 포인트 ★)

1. **필터 조합 = AND, querystring 전달.** 예: `/labels/queue?camera_id=<uuid>,<uuid>&vlm_action=drinking,shedding&date_from=2026-07-01&date_to=2026-07-08`. 다중값은 comma-split.
2. **VLM 판정 필터(큐)는 역쿼리.** `vlm_action`은 `behavior_logs`(source=vlm) enrich라 `camera_clips` 쿼리에 직접 못 넣음 → 조건 맞는 `clip_id` 집합을 먼저 뽑아 `camera_clips.id IN`. `has_vlm=false`는 "vlm 판정 전혀 없는 clip"이라 전체 vlm clip_id `NOT IN`. **★ `has_vlm=false`와 `vlm_action` 동시 지정은 모순 → `has_vlm=false`가 우선(vlm_action 무시).**
3. **카메라 옵션 소스 = 신규 `GET /labels/filter-options`.** `GET /cameras`는 `cameras.user_id` 컬럼이 없어 깨져 있음(실측). 대신 `camera_clips`의 스코프(라벨러=전체, owner=본인 `user_id`) distinct `camera_id` → `cameras.id IN` → `name`. 큐/내 라벨 공통(사용자가 접근 가능한 카메라 풀).
4. **날짜 기준: 큐=`started_at`(촬영/정렬축), 내 라벨=`labeled_at`(라벨/정렬축).** ★ 내 라벨을 촬영시각 기준으로 원하면 변경 가능(역쿼리 필요 — 아래 Task 2-3 노트).
5. **필터 UI = 상단 필터 바(드롭다운 select + date input 2개).** 큐/내 라벨 공통 컴포넌트, 축만 props로 분기. "필터 초기화" 버튼 포함.
6. **필터 상태 = URL querystring 동기화.** 새로고침/공유 시 유지. 필터 변경 시 페이지네이션 리셋(cursor 버림).
7. **배포:** 서버사이드라 `flyctl deploy --config fly.api.toml --app petcam-api`(진행중인 API 배포에 합류) + Vercel(프론트).

---

## File Structure

| 파일 | 책임 | 변경 |
|---|---|---|
| `backend/routers/labels.py` | 큐/mine 쿼리에 필터 파라미터 + 역쿼리 헬퍼 + filter-options 엔드포인트 | Modify |
| `tests/test_labels_api.py` | 필터 케이스 테스트 (큐 4축 + mine 4축 + options) | Modify |
| `web/src/lib/labelingApi.ts` | `getQueue`/`getMyLabeled` 필터 파라미터, `getFilterOptions`, 타입 | Modify |
| `web/src/app/labeling/_filter-bar.tsx` | 공통 필터 바 컴포넌트 (드롭다운 + 날짜 + 초기화) | **Create** |
| `web/src/app/labeling/page.tsx` | 큐 필터 바 연결 + querystring | Modify |
| `web/src/app/labeling/me/page.tsx` | 내 라벨 필터 바 연결 + querystring | Modify |

---

## Phase 0 — 공통 헬퍼 + 필터 옵션 API

### Task 0-1: comma-split 파라미터 헬퍼 + VLM 역쿼리 헬퍼

**Files:** Modify `backend/routers/labels.py` (기존 `_attach_vlm_actions` 아래)

- [ ] **Step 1: 헬퍼 추가**

```python
def _csv_param(value: Optional[str]) -> list[str]:
    """comma-separated query param → 리스트. None/빈 → []."""
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def _clip_ids_with_vlm(
    sb: Client, *, actions: list[str] | None = None
) -> set[str]:
    """behavior_logs(source=vlm) 에 존재하는 clip_id 집합. actions 지정 시 그 판정만."""
    q = sb.table("behavior_logs").select("clip_id").eq("source", "vlm")
    if actions:
        q = q.in_("action", actions)
    try:
        resp = q.execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("vlm clip_id lookup failed: %s", exc)
        return set()
    return {r["clip_id"] for r in (resp.data or []) if r.get("clip_id")}
```

- [ ] **Step 2: 커밋** — `git commit -m "feat: 라벨 필터용 comma-split + VLM 역쿼리 헬퍼"`

### Task 0-2: `GET /labels/filter-options` (카메라 목록)

**Files:** Modify `backend/routers/labels.py`, `tests/test_labels_api.py`

- [ ] **Step 1: 실패 테스트**

```python
def test_filter_options_owner_sees_own_cameras() -> None:
    clips = [
        _clip_row(clip_id="c1", camera_id="cam-uuid-1"),
        _clip_row(clip_id="c2", camera_id="cam-uuid-1"),
        _clip_row(clip_id="c3", camera_id="cam-uuid-2"),
    ]
    cameras = [
        {"id": "cam-uuid-1", "name": "거실"},
        {"id": "cam-uuid-2", "name": "작업실"},
    ]
    client, _ = _make_client(clips=clips, cameras=cameras)
    r = client.get("/labels/filter-options")
    assert r.status_code == 200
    names = {c["name"] for c in r.json()["cameras"]}
    assert names == {"거실", "작업실"}
```

> `_make_client`/`_clip_row`에 `cameras`/`camera_id` 지원 추가 필요 — Step 1b.

- [ ] **Step 1b: 픽스처 확장**

```python
# _make_client 시그니처에 cameras 추가, FakeSupabase tables 에 "cameras" 등록
def _make_client(*, clips=None, labels=None, labelers=None, logs=None,
                 cameras=None, user_id=OWNER_ID):
    fake = FakeSupabase({
        "camera_clips": list(clips or []),
        "behavior_labels": list(labels or []),
        "labelers": list(labelers or []),
        "behavior_logs": list(logs or []),
        "cameras": list(cameras or []),
    })
    ...
# _clip_row 에 camera_id 파라미터 추가 (default "cam-test")
```

- [ ] **Step 2: 엔드포인트 구현**

```python
@router.get("/labels/filter-options")
def get_filter_options(
    sb: Client = Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """필터 드롭다운 옵션. 현재는 카메라 목록(스코프 반영).

    라벨러=전체 카메라, owner=본인 clip 의 카메라만. GET /cameras 는
    cameras.user_id 컬럼이 없어 깨져 있어 여기서 camera_clips→cameras 로 파생.
    """
    cq = sb.table("camera_clips").select("camera_id")
    if not is_labeler(user_id, sb):
        cq = cq.eq("user_id", user_id)
    try:
        resp = cq.execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("filter-options camera scan failed")
        raise HTTPException(status_code=502, detail=f"supabase error: {exc}")

    cam_ids = {r["camera_id"] for r in (resp.data or []) if r.get("camera_id")}
    cameras: list[dict] = []
    if cam_ids:
        try:
            cr = (
                sb.table("cameras")
                .select("id, name")
                .in_("id", list(cam_ids))
                .execute()
            )
            cameras = [
                {"id": c["id"], "name": c.get("name") or c["id"]}
                for c in (cr.data or [])
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("filter-options camera names failed: %s", exc)
    cameras.sort(key=lambda c: c["name"])
    return {"cameras": cameras}
```

- [ ] **Step 3: 테스트 통과 확인** — `uv run pytest tests/test_labels_api.py -q`
- [ ] **Step 4: 커밋** — `git commit -m "feat: GET /labels/filter-options 카메라 목록 (스코프 반영)"`

---

## Phase 1 — 큐 서버사이드 필터

### Task 1-1: `list_label_queue` 필터 파라미터

**Files:** Modify `backend/routers/labels.py` (`list_label_queue`)

- [ ] **Step 1: 실패 테스트 (4축)**

```python
def test_queue_filter_by_camera() -> None:
    clips = [
        _clip_row(clip_id="c1", camera_id="cam-1"),
        _clip_row(clip_id="c2", camera_id="cam-2"),
    ]
    client, _ = _make_client(clips=clips)
    r = client.get("/labels/queue", params={"camera_id": "cam-1"})
    assert [it["id"] for it in r.json()["items"]] == ["c1"]


def test_queue_filter_by_date_range() -> None:
    clips = [
        _clip_row(clip_id="old", started_at="2026-05-01T10:00:00+00:00"),
        _clip_row(clip_id="mid", started_at="2026-05-05T10:00:00+00:00"),
        _clip_row(clip_id="new", started_at="2026-05-09T10:00:00+00:00"),
    ]
    client, _ = _make_client(clips=clips)
    r = client.get("/labels/queue", params={
        "date_from": "2026-05-03T00:00:00+00:00",
        "date_to": "2026-05-07T00:00:00+00:00",
    })
    assert [it["id"] for it in r.json()["items"]] == ["mid"]


def test_queue_filter_by_vlm_action() -> None:
    clips = [_clip_row(clip_id="c1"), _clip_row(clip_id="c2")]
    logs = [
        _log_row(clip_id="c1", action="drinking"),
        _log_row(clip_id="c2", action="moving"),
    ]
    client, _ = _make_client(clips=clips, logs=logs)
    r = client.get("/labels/queue", params={"vlm_action": "drinking"})
    assert [it["id"] for it in r.json()["items"]] == ["c1"]


def test_queue_filter_has_vlm_false() -> None:
    clips = [_clip_row(clip_id="c1"), _clip_row(clip_id="c2")]
    logs = [_log_row(clip_id="c1", action="drinking")]  # c2 는 판정 없음
    client, _ = _make_client(clips=clips, logs=logs)
    r = client.get("/labels/queue", params={"has_vlm": "false"})
    assert [it["id"] for it in r.json()["items"]] == ["c2"]
```

- [ ] **Step 2: 시그니처 + 필터 적용 구현**

```python
@router.get("/labels/queue")
def list_label_queue(
    limit: int = Query(DEFAULT_QUEUE_LIMIT, ge=1, le=MAX_QUEUE_LIMIT),
    cursor: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None, description="comma-separated camera uuid"),
    vlm_action: Optional[str] = Query(None, description="comma-separated action"),
    has_vlm: Optional[bool] = Query(None, description="true=판정있음 / false=판정없음"),
    date_from: Optional[str] = Query(None, description="started_at >= (ISO8601)"),
    date_to: Optional[str] = Query(None, description="started_at <= (ISO8601)"),
    sb: Client = Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
) -> dict:
    # ... (기존 my_clip_ids / user_is_labeler / base q 동일) ...

    if not user_is_labeler:
        q = q.eq("user_id", user_id)
    if my_clip_ids:
        q = q.not_.in_("id", my_clip_ids)
    if cursor:
        q = q.lt("started_at", cursor)

    # ── 신규 필터 ──────────────────────────────────────────────
    cameras = _csv_param(camera_id)
    if cameras:
        q = q.in_("camera_id", cameras)
    if date_from:
        q = q.gte("started_at", date_from)
    if date_to:
        q = q.lte("started_at", date_to)

    # VLM 판정 필터 — behavior_logs 역쿼리
    vlm_actions = _csv_param(vlm_action)
    if has_vlm is False:
        # "판정 전혀 없는 clip" — vlm_action 은 무시 (설계 결정 2)
        all_vlm = _clip_ids_with_vlm(sb)
        if all_vlm:
            q = q.not_.in_("id", list(all_vlm))
    elif vlm_actions or has_vlm is True:
        matched = _clip_ids_with_vlm(sb, actions=vlm_actions or None)
        # 매칭 0건이면 결과 없음 — 불가능 id 로 강제
        q = q.in_("id", list(matched) if matched else ["__none__"])
    # ───────────────────────────────────────────────────────────

    try:
        resp = q.execute()
    # ... (이하 기존 rows/has_more/enrich/return 동일) ...
```

> **주의:** `not_.in_("id", my_clip_ids)`와 vlm `in_("id", ...)`가 같은 `id` 컬럼에 공존. postgrest는 서로 다른 연산자라 AND로 합쳐짐 — 문제 없음. FakeSupabase도 필터 순차 적용이라 동일.

- [ ] **Step 3: 테스트 통과** — `uv run pytest tests/test_labels_api.py -q`
- [ ] **Step 4: 커밋** — `git commit -m "feat: 큐 서버 필터 (카메라/날짜/VLM판정/유무)"`

---

## Phase 2 — 내 라벨 서버사이드 필터

### Task 2-1: `list_my_labeled` 필터 파라미터

**Files:** Modify `backend/routers/labels.py` (`list_my_labeled`)

- [ ] **Step 1: 실패 테스트**

```python
def test_mine_filter_by_action() -> None:
    labels = [
        _label_row(clip_id="c1", labeled_by=OWNER_ID, action="drinking"),
        _label_row(clip_id="c2", labeled_by=OWNER_ID, action="moving"),
    ]
    clips = [_clip_row(clip_id="c1"), _clip_row(clip_id="c2")]
    client, _ = _make_client(clips=clips, labels=labels)
    r = client.get("/labels/mine", params={"action": "drinking"})
    assert [it["label"]["clip_id"] for it in r.json()["items"]] == ["c1"]


def test_mine_filter_by_camera() -> None:
    labels = [
        _label_row(clip_id="c1", labeled_by=OWNER_ID),
        _label_row(clip_id="c2", labeled_by=OWNER_ID),
    ]
    clips = [
        _clip_row(clip_id="c1", camera_id="cam-1"),
        _clip_row(clip_id="c2", camera_id="cam-2"),
    ]
    client, _ = _make_client(clips=clips, labels=labels)
    r = client.get("/labels/mine", params={"camera_id": "cam-1"})
    assert [it["label"]["clip_id"] for it in r.json()["items"]] == ["c1"]
```

- [ ] **Step 2: 시그니처 + 필터 구현**

```python
@router.get("/labels/mine")
def list_my_labeled(
    limit: int = Query(DEFAULT_QUEUE_LIMIT, ge=1, le=MAX_QUEUE_LIMIT),
    cursor: Optional[str] = Query(None),
    action: Optional[str] = Query(None, description="comma-separated action"),
    lick_target: Optional[str] = Query(None, description="comma-separated lick_target"),
    camera_id: Optional[str] = Query(None, description="comma-separated camera uuid"),
    date_from: Optional[str] = Query(None, description="labeled_at >= (ISO8601)"),
    date_to: Optional[str] = Query(None, description="labeled_at <= (ISO8601)"),
    sb: Client = Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
) -> dict:
    q = (
        sb.table("behavior_labels")
        .select("*")
        .eq("labeled_by", user_id)
        .order("labeled_at", desc=True)
        .limit(limit + 1)
    )
    if cursor:
        q = q.lt("labeled_at", cursor)

    # ── 신규 필터 ──────────────────────────────────────────────
    actions = _csv_param(action)
    if actions:
        q = q.in_("action", actions)
    lick_targets = _csv_param(lick_target)
    if lick_targets:
        q = q.in_("lick_target", lick_targets)
    if date_from:
        q = q.gte("labeled_at", date_from)
    if date_to:
        q = q.lte("labeled_at", date_to)

    # 카메라 필터 — behavior_labels 엔 camera_id 없음 → clip 역쿼리
    cameras = _csv_param(camera_id)
    if cameras:
        try:
            cam_clips = (
                sb.table("camera_clips")
                .select("id")
                .in_("camera_id", cameras)
                .execute()
            )
            cam_clip_ids = [r["id"] for r in (cam_clips.data or [])]
        except Exception as exc:  # noqa: BLE001
            logger.warning("mine camera filter lookup failed: %s", exc)
            cam_clip_ids = []
        q = q.in_("clip_id", cam_clip_ids or ["__none__"])
    # ───────────────────────────────────────────────────────────

    try:
        labels_resp = q.execute()
    # ... (이하 기존 label_rows/has_more/clip join/return 동일) ...
```

> **★ 날짜 기준 노트:** 위는 `labeled_at`(정렬축). 촬영시각(`started_at`) 기준을 원하면 카메라 필터처럼 `camera_clips`에서 `started_at` 범위 clip_id를 먼저 뽑아 `clip_id IN`. 정렬은 여전히 labeled_at.

- [ ] **Step 3: 테스트 통과** — `uv run pytest tests/test_labels_api.py -q`
- [ ] **Step 4: 커밋** — `git commit -m "feat: 내 라벨 서버 필터 (action/lick_target/카메라/날짜)"`

---

## Phase 3 — 프론트 필터 UI

### Task 3-1: `labelingApi.ts` 필터 파라미터 + 옵션 API

**Files:** Modify `web/src/lib/labelingApi.ts`

- [ ] **Step 1: 타입 + 함수**

```typescript
export interface CameraOption {
  id: string;
  name: string;
}
export interface FilterOptions {
  cameras: CameraOption[];
}

export function getFilterOptions(): Promise<FilterOptions> {
  return request<FilterOptions>('/labels/filter-options');
}

// 큐 필터
export interface QueueFilters {
  camera_id?: string[];
  vlm_action?: string[];
  has_vlm?: boolean;
  date_from?: string;
  date_to?: string;
}
// 내 라벨 필터
export interface MineFilters {
  action?: string[];
  lick_target?: string[];
  camera_id?: string[];
  date_from?: string;
  date_to?: string;
}

function appendCsv(params: URLSearchParams, key: string, vals?: string[]) {
  if (vals && vals.length) params.set(key, vals.join(','));
}
```

- [ ] **Step 2: `getQueue`/`getMyLabeled`에 필터 인자 추가**

```typescript
export function getQueue(opts?: {
  limit?: number;
  cursor?: string;
  filters?: QueueFilters;
}): Promise<QueueResponse> {
  const params = new URLSearchParams();
  if (opts?.limit) params.set('limit', String(opts.limit));
  if (opts?.cursor) params.set('cursor', opts.cursor);
  const f = opts?.filters;
  if (f) {
    appendCsv(params, 'camera_id', f.camera_id);
    appendCsv(params, 'vlm_action', f.vlm_action);
    if (f.has_vlm !== undefined) params.set('has_vlm', String(f.has_vlm));
    if (f.date_from) params.set('date_from', f.date_from);
    if (f.date_to) params.set('date_to', f.date_to);
  }
  const qs = params.toString();
  return request<QueueResponse>(`/labels/queue${qs ? `?${qs}` : ''}`);
}
// getMyLabeled 도 동일 패턴 (MineFilters: action/lick_target/camera_id/date)
```

- [ ] **Step 3: 커밋** — `git commit -m "feat(web): 라벨 필터 API 파라미터 + getFilterOptions"`

### Task 3-2: 공통 `_filter-bar.tsx`

**Files:** Create `web/src/app/labeling/_filter-bar.tsx`

- [ ] **Step 1: 컴포넌트 (드롭다운 select + 날짜 + 초기화)**

```tsx
'use client';

import { useEffect, useState } from 'react';
import { getFilterOptions, type CameraOption } from '@/lib/labelingApi';
import Button from '@/components/ui/Button';

// 어떤 축을 노출할지 탭이 결정 — 큐/내 라벨이 다른 축을 씀.
export interface FilterAxes {
  camera?: boolean;
  vlmAction?: boolean; // 큐 전용
  hasVlm?: boolean; // 큐 전용
  action?: boolean; // 내 라벨 전용
  lickTarget?: boolean; // 내 라벨 전용
  date: boolean;
}

// 두 탭 공통 값 컨테이너 — 사용 안 하는 축은 undefined.
export interface FilterState {
  camera_id?: string[];
  vlm_action?: string[];
  has_vlm?: boolean;
  action?: string[];
  lick_target?: string[];
  date_from?: string;
  date_to?: string;
}

// enum 옵션 — labelingApi ActionType/LickTargetType 와 정합 유지.
const ACTIONS = ['eating_paste', 'drinking', 'moving', 'unknown',
  'eating_prey', 'defecating', 'shedding', 'basking', 'unseen', 'hand_feeding'];
const LICK_TARGETS = ['air', 'dish', 'floor', 'wall', 'object', 'other'];

export default function FilterBar({
  axes,
  value,
  onChange,
}: {
  axes: FilterAxes;
  value: FilterState;
  onChange: (next: FilterState) => void;
}) {
  const [cameras, setCameras] = useState<CameraOption[]>([]);

  useEffect(() => {
    if (!axes.camera) return;
    getFilterOptions()
      .then((o) => setCameras(o.cameras))
      .catch(() => setCameras([])); // 옵션 로드 실패해도 다른 필터는 동작
  }, [axes.camera]);

  // 단일 select → 배열(1개 또는 빈) 로 정규화. MVP 는 단일 선택.
  const one = (v: string[] | undefined) => (v && v.length ? v[0] : '');
  const setOne = (key: keyof FilterState, v: string) =>
    onChange({ ...value, [key]: v ? [v] : undefined });

  const hasAny =
    value.camera_id?.length ||
    value.vlm_action?.length ||
    value.action?.length ||
    value.lick_target?.length ||
    value.has_vlm !== undefined ||
    value.date_from ||
    value.date_to;

  const sel =
    'rounded-md border border-zinc-300 px-2 py-1 text-sm text-zinc-700';

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md bg-zinc-50 px-3 py-2 ring-1 ring-inset ring-zinc-200">
      {axes.camera && (
        <select
          className={sel}
          value={one(value.camera_id)}
          onChange={(e) => setOne('camera_id', e.target.value)}
        >
          <option value="">전체 카메라</option>
          {cameras.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      )}

      {axes.vlmAction && (
        <select
          className={sel}
          value={one(value.vlm_action)}
          onChange={(e) => setOne('vlm_action', e.target.value)}
        >
          <option value="">전체 VLM 판정</option>
          {ACTIONS.map((a) => <option key={a} value={a}>🔍 {a}</option>)}
        </select>
      )}

      {axes.hasVlm && (
        <select
          className={sel}
          value={value.has_vlm === undefined ? '' : String(value.has_vlm)}
          onChange={(e) =>
            onChange({
              ...value,
              has_vlm: e.target.value === '' ? undefined : e.target.value === 'true',
            })
          }
        >
          <option value="">판정 유무 전체</option>
          <option value="true">판정 있음</option>
          <option value="false">판정 없음</option>
        </select>
      )}

      {axes.action && (
        <select
          className={sel}
          value={one(value.action)}
          onChange={(e) => setOne('action', e.target.value)}
        >
          <option value="">전체 라벨</option>
          {ACTIONS.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
      )}

      {axes.lickTarget && (
        <select
          className={sel}
          value={one(value.lick_target)}
          onChange={(e) => setOne('lick_target', e.target.value)}
        >
          <option value="">전체 lick_target</option>
          {LICK_TARGETS.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      )}

      {axes.date && (
        <>
          <input
            type="date"
            className={sel}
            value={value.date_from?.slice(0, 10) ?? ''}
            onChange={(e) =>
              onChange({
                ...value,
                date_from: e.target.value ? `${e.target.value}T00:00:00+09:00` : undefined,
              })
            }
          />
          <span className="text-xs text-zinc-400">~</span>
          <input
            type="date"
            className={sel}
            value={value.date_to?.slice(0, 10) ?? ''}
            onChange={(e) =>
              onChange({
                ...value,
                date_to: e.target.value ? `${e.target.value}T23:59:59+09:00` : undefined,
              })
            }
          />
        </>
      )}

      {hasAny ? (
        <Button variant="ghost" size="sm" onClick={() => onChange({})}>
          초기화
        </Button>
      ) : null}
    </div>
  );
}
```

> **★ MVP는 축당 단일 선택**(select). 백엔드는 comma 다중을 이미 지원하니, 추후 multi-select로 확장 시 프론트만 수정. (YAGNI)

- [ ] **Step 2: 커밋** — `git commit -m "feat(web): 공통 라벨 필터 바 컴포넌트"`

### Task 3-3: 큐 페이지 연결 + querystring

**Files:** Modify `web/src/app/labeling/page.tsx`

- [ ] **Step 1: FilterBar 연결 + URL 동기화**

```tsx
// import 추가
import { useSearchParams, useRouter } from 'next/navigation';
import FilterBar, { type FilterState } from './_filter-bar';

// querystring ↔ FilterState 직렬화 헬퍼 (파일 상단)
function parseFilters(sp: URLSearchParams): FilterState {
  const csv = (k: string) => {
    const v = sp.get(k);
    return v ? v.split(',') : undefined;
  };
  const hv = sp.get('has_vlm');
  return {
    camera_id: csv('camera_id'),
    vlm_action: csv('vlm_action'),
    has_vlm: hv === null ? undefined : hv === 'true',
    date_from: sp.get('date_from') ?? undefined,
    date_to: sp.get('date_to') ?? undefined,
  };
}
function filtersToQuery(f: FilterState): string {
  const p = new URLSearchParams();
  if (f.camera_id?.length) p.set('camera_id', f.camera_id.join(','));
  if (f.vlm_action?.length) p.set('vlm_action', f.vlm_action.join(','));
  if (f.has_vlm !== undefined) p.set('has_vlm', String(f.has_vlm));
  if (f.date_from) p.set('date_from', f.date_from);
  if (f.date_to) p.set('date_to', f.date_to);
  return p.toString();
}
```

컴포넌트 안:
- `const searchParams = useSearchParams();`
- `const filters = useMemo(() => parseFilters(new URLSearchParams(searchParams.toString())), [searchParams]);`
- `load(null)` 호출 시 `getQueue({ limit: PAGE_SIZE, filters })` — cursor 페이지네이션에도 `filters` 항상 전달.
- `useEffect(() => { load(null); }, [load, filters]);` — 필터 바뀌면 첫 페이지부터 재로드.
- FilterBar onChange: `router.replace('/labeling?' + filtersToQuery(next))` → searchParams 변경 → 재로드.
- JSX: 헤더 아래, grid 위에 `<FilterBar axes={{ camera: true, vlmAction: true, hasVlm: true, date: true }} value={filters} onChange={(n) => router.replace('/labeling' + (filtersToQuery(n) ? '?' + filtersToQuery(n) : ''))} />`

- [ ] **Step 2: 타입 체크** — `cd web && npx tsc --noEmit`
- [ ] **Step 3: 커밋** — `git commit -m "feat(web): 큐 페이지 필터 바 + querystring 동기화"`

### Task 3-4: 내 라벨 페이지 연결

**Files:** Modify `web/src/app/labeling/me/page.tsx`

- [ ] **Step 1:** Task 3-3과 동일 패턴. axes = `{ camera: true, action: true, lickTarget: true, date: true }`. `parseFilters`/`filtersToQuery`는 mine 축(action/lick_target/camera/date)용으로. `getMyLabeled({ limit, filters })`.
- [ ] **Step 2: 타입 체크** — `cd web && npx tsc --noEmit`
- [ ] **Step 3: 커밋** — `git commit -m "feat(web): 내 라벨 페이지 필터 바"`

---

## 건드리지 않는 것 (스코프 밖)

- 기존 큐/mine 로직: 미라벨 조건, has_motion/r2_key 게이트, seek pagination, 권한 스코프 — **필터는 그 위에 AND로만 추가**.
- `thumb_url`/`vlm_action` enrich (이미 배포 대기 중인 이전 작업).
- `GET /cameras` 버그(cameras.user_id) 수정 — 별개 이슈, 필터는 우회.
- 라벨러 다중 owner 카메라 이름 충돌 — 현재 카메라 2개라 비목표.
- 필터 축당 다중 선택 UI — 백엔드는 지원, 프론트는 MVP 단일.

## 성공 기준 (완료 조건)

- [ ] `uv run pytest tests/test_labels_api.py -q` — 기존 36 + 신규(큐 4축 + mine 2축 + options 1) 전부 통과
- [ ] `cd web && npx tsc --noEmit` exit 0
- [ ] 큐: 카메라/VLM판정/판정유무/날짜 필터가 서버에서 걸리고 페이지네이션 유지
- [ ] 내 라벨: action/lick_target/카메라/날짜 필터 동작
- [ ] 필터 상태가 URL querystring에 반영(새로고침 유지) + "초기화" 동작
- [ ] 필터 없을 때 = 기존 동작과 동일(회귀 없음)

## 배포

서버사이드라 프론트만으론 안 뜸 — **fly API + Vercel 둘 다** 필요:
```bash
uv run pytest -q                                    # 전체 회귀
flyctl deploy --config fly.api.toml --app petcam-api
```
(이전 큐 썸네일/VLM태그 변경 + 이 필터가 같은 배포로 함께 나감)
