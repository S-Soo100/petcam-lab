"""backend.routers.labels 엔드포인트 단위 테스트 (spec §3-6).

## FakeSupabase 확장 이유
test_clips_api.py 의 FakeSupabase 는 SELECT 만 지원. labels 는 UPSERT + not.in
필터가 필요 → 본 파일에서 mutating 한 버전을 새로 정의. 둘이 비슷하지만 한쪽
(clips) 은 read-only fake 가 의도적으로 단순하므로 강제 통합하지 않음 (3번째
중복 발생 시 conftest 추출).

## 권한 매트릭스 (§4 결정 4) 테스트 분기
- POST: owner / labeler / 외부인 × {정상 / 잘못된 enum / clip 없음}
- GET: owner (전체 라벨러) / labeler (본인만) / 외부인 (404)
- /labels/queue: labeler 전 클립 / owner 본인만 / 미라벨 우선 / cursor pagination
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import get_current_user_id
from backend.routers.labels import router as labels_router
from backend.supabase_client import get_supabase_client


# ────────────────────────────────────────────────────────────────────────────
# Mutating FakeSupabase — upsert + not.in 지원
# ────────────────────────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class _NotProxy:
    def __init__(self, parent: "_FakeQuery") -> None:
        self._parent = parent

    def in_(self, key: str, values: list[Any]) -> "_FakeQuery":
        self._parent._filters.append(("not_in", key, list(values)))
        return self._parent

    def is_(self, key: str, val: Any) -> "_FakeQuery":
        # postgrest `.not_.is_(col, "null")` = SQL `col IS NOT NULL`
        self._parent._filters.append(("not_is", key, val))
        return self._parent


class _FakeQuery:
    """체인 빌더 — execute() 호출 시 underlying table 에 적용/조회."""

    def __init__(self, parent: "FakeSupabase", table_name: str) -> None:
        self._parent = parent
        self._table_name = table_name
        self._mode = "select"
        self._payload: Any = None
        self._on_conflict: str = ""
        self._filters: list[tuple[str, str, Any]] = []
        self._order_by: tuple[str, bool] | None = None
        self._limit: int | None = None

    # --- mode setters ----------------------------------------------------

    def select(self, *_args: Any, **_kwargs: Any) -> "_FakeQuery":
        self._mode = "select"
        return self

    def insert(self, data: Any) -> "_FakeQuery":
        self._mode = "insert"
        self._payload = data
        return self

    def upsert(self, data: Any, *, on_conflict: str = "") -> "_FakeQuery":
        self._mode = "upsert"
        self._payload = data
        self._on_conflict = on_conflict
        return self

    # --- filters ---------------------------------------------------------

    def eq(self, key: str, val: Any) -> "_FakeQuery":
        self._filters.append(("eq", key, val))
        return self

    def lt(self, key: str, val: Any) -> "_FakeQuery":
        self._filters.append(("lt", key, val))
        return self

    def in_(self, key: str, values: list[Any]) -> "_FakeQuery":
        self._filters.append(("in", key, list(values)))
        return self

    @property
    def not_(self) -> _NotProxy:
        return _NotProxy(self)

    def order(self, key: str, desc: bool = False) -> "_FakeQuery":
        self._order_by = (key, desc)
        return self

    def limit(self, n: int) -> "_FakeQuery":
        self._limit = n
        return self

    # --- execute ---------------------------------------------------------

    def execute(self) -> _FakeResponse:
        rows = self._parent._tables.setdefault(self._table_name, [])
        if self._mode == "select":
            return self._do_select(rows)
        if self._mode == "upsert":
            return self._do_upsert(rows)
        if self._mode == "insert":
            return self._do_insert(rows)
        raise NotImplementedError(self._mode)

    def _apply_filters(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = list(rows)
        for op, key, val in self._filters:
            if op == "eq":
                out = [r for r in out if r.get(key) == val]
            elif op == "lt":
                out = [r for r in out if r.get(key) is not None and r[key] < val]
            elif op == "not_in":
                out = [r for r in out if r.get(key) not in val]
            elif op == "in":
                out = [r for r in out if r.get(key) in val]
            elif op == "not_is":
                # `not_.is_(col, "null")` = SQL `col IS NOT NULL`
                if val == "null":
                    out = [r for r in out if r.get(key) is not None]
                else:
                    out = [r for r in out if r.get(key) != val]
        return out

    def _do_select(self, rows: list[dict[str, Any]]) -> _FakeResponse:
        out = self._apply_filters(rows)
        if self._order_by:
            key, desc = self._order_by
            out.sort(key=lambda r: (r.get(key) or ""), reverse=desc)
        if self._limit is not None:
            out = out[: self._limit]
        return _FakeResponse(out)

    def _do_insert(self, rows: list[dict[str, Any]]) -> _FakeResponse:
        new_rows = (
            self._payload if isinstance(self._payload, list) else [self._payload]
        )
        for r in new_rows:
            r.setdefault("id", str(uuid.uuid4()))
            rows.append(dict(r))
        return _FakeResponse([dict(r) for r in new_rows])

    def _do_upsert(self, rows: list[dict[str, Any]]) -> _FakeResponse:
        keys = [k.strip() for k in self._on_conflict.split(",") if k.strip()]
        new_rows = (
            self._payload if isinstance(self._payload, list) else [self._payload]
        )
        result = []
        for new_row in new_rows:
            replaced = False
            if keys:
                for i, existing in enumerate(rows):
                    if all(existing.get(k) == new_row.get(k) for k in keys):
                        rows[i] = {**existing, **new_row}
                        result.append(dict(rows[i]))
                        replaced = True
                        break
            if not replaced:
                row = dict(new_row)
                row.setdefault("id", str(uuid.uuid4()))
                row.setdefault("labeled_at", "2026-05-02T00:00:00+00:00")
                rows.append(row)
                result.append(dict(row))
        return _FakeResponse(result)


class FakeSupabase:
    def __init__(self, tables: dict[str, list[dict[str, Any]]]) -> None:
        self._tables = tables

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self, name)


# ────────────────────────────────────────────────────────────────────────────
# 픽스처
# ────────────────────────────────────────────────────────────────────────────

OWNER_ID = "owner-user-id"
LABELER_ID = "labeler-user-id"
OUTSIDER_ID = "outsider-user-id"
CLIP_ID = "00000000-0000-0000-0000-000000000001"


def _clip_row(
    clip_id: str = CLIP_ID,
    *,
    user_id: str = OWNER_ID,
    started_at: str = "2026-05-02T10:00:00+00:00",
    camera_id: str = "cam-test",
    has_motion: bool = True,
    r2_key: str | None = "clips/test-key.mp4",
) -> dict[str, Any]:
    # default 는 큐 노출 조건 (has_motion=True + r2_key NOT NULL) 만족하는 클립.
    # 큐 제외 케이스 테스트는 has_motion=False 또는 r2_key=None 으로 override.
    return {
        "id": clip_id,
        "user_id": user_id,
        "camera_id": camera_id,
        "started_at": started_at,
        "duration_sec": 60.0,
        "has_motion": has_motion,
        "file_path": "/storage/local.mp4",
        "r2_key": r2_key,
        "thumbnail_r2_key": None,
        "encoded_file_size": None,
        "original_file_size": None,
        "thumbnail_path": None,
    }


def _label_row(
    *,
    clip_id: str = CLIP_ID,
    labeled_by: str,
    action: str = "moving",
    lick_target: str | None = None,
    note: str | None = None,
    labeled_at: str = "2026-05-02T11:00:00+00:00",
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "clip_id": clip_id,
        "labeled_by": labeled_by,
        "action": action,
        "lick_target": lick_target,
        "note": note,
        "labeled_at": labeled_at,
    }


def _make_client(
    *,
    clips: list[dict[str, Any]] | None = None,
    labels: list[dict[str, Any]] | None = None,
    labelers: list[dict[str, Any]] | None = None,
    logs: list[dict[str, Any]] | None = None,
    user_id: str = OWNER_ID,
) -> tuple[TestClient, FakeSupabase]:
    """라우터 마운트 + 두 의존성 override. fake supabase 인스턴스도 반환 (mutate 검증용)."""
    fake = FakeSupabase(
        {
            "camera_clips": list(clips or []),
            "behavior_labels": list(labels or []),
            "labelers": list(labelers or []),
            "behavior_logs": list(logs or []),
        }
    )
    test_app = FastAPI()
    test_app.include_router(labels_router)
    test_app.dependency_overrides[get_supabase_client] = lambda: fake
    test_app.dependency_overrides[get_current_user_id] = lambda: user_id
    return TestClient(test_app), fake


def _log_row(
    *,
    clip_id: str = CLIP_ID,
    action: str = "drinking",
    source: str = "vlm",
    confidence: float | None = 0.85,
    reasoning: str | None = None,
    vlm_model: str | None = "gemini-2.5-flash-zeroshot-v3.5",
    created_at: str = "2026-05-02T11:00:00+00:00",
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "clip_id": clip_id,
        "action": action,
        "source": source,
        "confidence": confidence,
        "reasoning": reasoning,
        "vlm_model": vlm_model,
        "created_at": created_at,
    }


# ────────────────────────────────────────────────────────────────────────────
# POST /clips/{id}/labels — UPSERT + 권한 + enum 검증
# ────────────────────────────────────────────────────────────────────────────


def test_post_label_owner_creates_row() -> None:
    """owner 가 본인 클립에 라벨 → 201 + DB 에 row 1개."""
    client, fake = _make_client(clips=[_clip_row()])
    r = client.post(
        f"/clips/{CLIP_ID}/labels",
        json={"action": "moving"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["clip_id"] == CLIP_ID
    assert body["labeled_by"] == OWNER_ID
    assert body["action"] == "moving"
    assert body["lick_target"] is None
    # DB 에 실제로 들어갔는지
    assert len(fake._tables["behavior_labels"]) == 1


def test_post_label_labeler_can_label_others_clip() -> None:
    """labeler 는 owner 가 아닌 클립에도 라벨 가능."""
    client, fake = _make_client(
        clips=[_clip_row()],
        labelers=[{"user_id": LABELER_ID}],
        user_id=LABELER_ID,
    )
    r = client.post(
        f"/clips/{CLIP_ID}/labels",
        json={"action": "eating_paste", "lick_target": "air"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["labeled_by"] == LABELER_ID
    assert body["action"] == "eating_paste"
    assert body["lick_target"] == "air"


def test_post_label_outsider_404() -> None:
    """외부인은 라벨링 권한 없음 → 404 (clip 존재 leak 방지)."""
    client, fake = _make_client(clips=[_clip_row()], user_id=OUTSIDER_ID)
    r = client.post(
        f"/clips/{CLIP_ID}/labels",
        json={"action": "moving"},
    )
    assert r.status_code == 404
    # 실패 시 라벨 row 가 생성되면 안 됨
    assert fake._tables["behavior_labels"] == []


def test_post_label_invalid_action_422() -> None:
    """enum 외 action → Pydantic 422."""
    client, _ = _make_client(clips=[_clip_row()])
    r = client.post(
        f"/clips/{CLIP_ID}/labels",
        json={"action": "snorting"},  # 9 raw 클래스에 없는 값
    )
    assert r.status_code == 422


def test_post_label_invalid_lick_target_422() -> None:
    """lick_target 도 enum 검증."""
    client, _ = _make_client(clips=[_clip_row()])
    r = client.post(
        f"/clips/{CLIP_ID}/labels",
        json={"action": "drinking", "lick_target": "ceiling"},
    )
    assert r.status_code == 422


def test_post_label_clip_not_found_404() -> None:
    """존재하지 않는 clip → 404."""
    client, _ = _make_client(clips=[])
    r = client.post(
        f"/clips/{CLIP_ID}/labels",
        json={"action": "moving"},
    )
    assert r.status_code == 404


def test_post_label_upsert_replaces_existing() -> None:
    """같은 라벨러가 다시 라벨 → 기존 row 갱신 (UNIQUE clip_id+labeled_by)."""
    existing = _label_row(labeled_by=OWNER_ID, action="drinking", note="first")
    client, fake = _make_client(
        clips=[_clip_row()],
        labels=[existing],
    )
    r = client.post(
        f"/clips/{CLIP_ID}/labels",
        json={"action": "moving", "note": "second"},
    )
    assert r.status_code == 201
    # row 수는 그대로 1
    assert len(fake._tables["behavior_labels"]) == 1
    assert fake._tables["behavior_labels"][0]["action"] == "moving"
    assert fake._tables["behavior_labels"][0]["note"] == "second"


def test_post_label_owner_overrides_other_labelers_label() -> None:
    """owner 가 body.labeled_by 명시 → 다른 라벨러 라벨 강제 생성/수정 (관리자 검수)."""
    existing = _label_row(labeled_by=LABELER_ID, action="drinking", note="라벨러 원본")
    client, fake = _make_client(
        clips=[_clip_row()],
        labels=[existing],
    )
    r = client.post(
        f"/clips/{CLIP_ID}/labels",
        json={
            "action": "moving",
            "note": "owner 정정",
            "labeled_by": LABELER_ID,
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["labeled_by"] == LABELER_ID
    assert body["action"] == "moving"
    assert body["note"] == "owner 정정"
    # row 수는 그대로 1 — UPSERT 로 갱신
    assert len(fake._tables["behavior_labels"]) == 1
    assert fake._tables["behavior_labels"][0]["action"] == "moving"


def test_post_label_owner_creates_label_for_other_user() -> None:
    """owner 가 body.labeled_by 로 라벨 없는 user 의 라벨 신규 생성."""
    client, fake = _make_client(clips=[_clip_row()])
    r = client.post(
        f"/clips/{CLIP_ID}/labels",
        json={"action": "moving", "labeled_by": "tester-user-id"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["labeled_by"] == "tester-user-id"
    assert len(fake._tables["behavior_labels"]) == 1


def test_post_label_labeler_cannot_override_other_users_label() -> None:
    """labeler 가 본인 아닌 labeled_by 명시 → 403 (owner 만 가능)."""
    client, fake = _make_client(
        clips=[_clip_row()],
        labelers=[{"user_id": LABELER_ID}],
        user_id=LABELER_ID,
    )
    r = client.post(
        f"/clips/{CLIP_ID}/labels",
        json={"action": "moving", "labeled_by": "another-labeler-id"},
    )
    assert r.status_code == 403
    # 실패 시 라벨 row 가 생성되면 안 됨
    assert fake._tables["behavior_labels"] == []


def test_post_label_self_labeled_by_works_for_anyone() -> None:
    """labeled_by 가 자기 자신이면 owner 검사 안 함 (명시했어도 본인 작성과 동치)."""
    client, _ = _make_client(
        clips=[_clip_row()],
        labelers=[{"user_id": LABELER_ID}],
        user_id=LABELER_ID,
    )
    r = client.post(
        f"/clips/{CLIP_ID}/labels",
        json={"action": "moving", "labeled_by": LABELER_ID},
    )
    assert r.status_code == 201
    assert r.json()["labeled_by"] == LABELER_ID


def test_post_label_accepts_all_9_raw_actions() -> None:
    """spec §2 의 raw 9 클래스 전부 통과해야 함."""
    actions = [
        "eating_paste",
        "drinking",
        "moving",
        "unknown",
        "eating_prey",
        "defecating",
        "shedding",
        "basking",
        "unseen",
    ]
    for i, action in enumerate(actions):
        clip_id = f"00000000-0000-0000-0000-{i:012d}"
        client, _ = _make_client(clips=[_clip_row(clip_id=clip_id)])
        r = client.post(
            f"/clips/{clip_id}/labels",
            json={"action": action},
        )
        assert r.status_code == 201, f"{action} 거절됨"


# ────────────────────────────────────────────────────────────────────────────
# GET /clips/{id}/labels — owner 전체 / labeler 본인만 / 외부인 404
# ────────────────────────────────────────────────────────────────────────────


def test_get_labels_owner_sees_all_labelers() -> None:
    """owner 는 모든 라벨러의 결과 조회 (GT 합의 검토용)."""
    labels = [
        _label_row(labeled_by=OWNER_ID, action="moving"),
        _label_row(labeled_by=LABELER_ID, action="drinking"),
        _label_row(labeled_by="other-labeler", action="eating_paste"),
    ]
    client, _ = _make_client(clips=[_clip_row()], labels=labels)
    r = client.get(f"/clips/{CLIP_ID}/labels")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 3
    # 모든 labeled_by 포함되어야 함
    labelers = {row["labeled_by"] for row in body}
    assert labelers == {OWNER_ID, LABELER_ID, "other-labeler"}


def test_get_labels_labeler_sees_only_own() -> None:
    """labeler (owner 아님) 는 본인 라벨만 조회 — 다른 라벨러 결과 비공개로 영향 회피."""
    labels = [
        _label_row(labeled_by=OWNER_ID, action="moving"),
        _label_row(labeled_by=LABELER_ID, action="drinking"),
    ]
    client, _ = _make_client(
        clips=[_clip_row()],
        labels=labels,
        labelers=[{"user_id": LABELER_ID}],
        user_id=LABELER_ID,
    )
    r = client.get(f"/clips/{CLIP_ID}/labels")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["labeled_by"] == LABELER_ID


def test_get_labels_outsider_404() -> None:
    """외부인은 라벨 목록 조회 불가."""
    labels = [_label_row(labeled_by=OWNER_ID, action="moving")]
    client, _ = _make_client(
        clips=[_clip_row()], labels=labels, user_id=OUTSIDER_ID
    )
    r = client.get(f"/clips/{CLIP_ID}/labels")
    assert r.status_code == 404


# ────────────────────────────────────────────────────────────────────────────
# GET /labels/queue — 미라벨 우선 + 권한 스코프
# ────────────────────────────────────────────────────────────────────────────


def test_queue_owner_sees_only_own_unlabeled_clips() -> None:
    """비-라벨러 owner 는 본인 클립 중 본인이 라벨 안 한 것만."""
    clips = [
        _clip_row(clip_id="c1", started_at="2026-05-02T10:00:00+00:00"),
        _clip_row(clip_id="c2", started_at="2026-05-02T11:00:00+00:00"),
        _clip_row(
            clip_id="c3",
            user_id="other-owner",
            started_at="2026-05-02T12:00:00+00:00",
        ),
    ]
    labels = [_label_row(clip_id="c1", labeled_by=OWNER_ID)]
    client, _ = _make_client(clips=clips, labels=labels)
    r = client.get("/labels/queue")
    body = r.json()
    ids = [it["id"] for it in body["items"]]
    # c1 은 본인이 라벨함, c3 는 다른 owner. c2 만 남아야 함.
    assert ids == ["c2"]


def test_queue_labeler_sees_all_unlabeled_across_owners() -> None:
    """labeler 는 모든 user_id 의 클립을 큐에 (본인 라벨 제외)."""
    clips = [
        _clip_row(clip_id="c1", started_at="2026-05-02T10:00:00+00:00"),
        _clip_row(
            clip_id="c2",
            user_id="other-owner",
            started_at="2026-05-02T11:00:00+00:00",
        ),
        _clip_row(
            clip_id="c3",
            user_id="other-owner",
            started_at="2026-05-02T12:00:00+00:00",
        ),
    ]
    labels = [_label_row(clip_id="c2", labeled_by=LABELER_ID)]
    client, _ = _make_client(
        clips=clips,
        labels=labels,
        labelers=[{"user_id": LABELER_ID}],
        user_id=LABELER_ID,
    )
    r = client.get("/labels/queue")
    body = r.json()
    ids = [it["id"] for it in body["items"]]
    # 본인이 라벨한 c2 제외, c3 (최신) → c1 순 (started_at desc)
    assert ids == ["c3", "c1"]


def test_queue_pagination_cursor() -> None:
    """limit + cursor seek pagination."""
    clips = [
        _clip_row(clip_id=f"c{i}", started_at=f"2026-05-02T1{i}:00:00+00:00")
        for i in range(5)
    ]
    client, _ = _make_client(
        clips=clips,
        labelers=[{"user_id": LABELER_ID}],
        user_id=LABELER_ID,
    )
    # 첫 페이지 — 최신 2개
    r1 = client.get("/labels/queue", params={"limit": 2})
    body1 = r1.json()
    assert [it["id"] for it in body1["items"]] == ["c4", "c3"]
    assert body1["has_more"] is True
    assert body1["next_cursor"] == "2026-05-02T13:00:00+00:00"

    # 두 번째 페이지 — cursor 로 c2 부터
    r2 = client.get(
        "/labels/queue",
        params={"limit": 2, "cursor": body1["next_cursor"]},
    )
    body2 = r2.json()
    assert [it["id"] for it in body2["items"]] == ["c2", "c1"]


def test_queue_empty_when_all_labeled() -> None:
    """본인이 모든 클립을 라벨했으면 큐 빔."""
    clips = [_clip_row(clip_id="c1")]
    labels = [_label_row(clip_id="c1", labeled_by=OWNER_ID)]
    client, _ = _make_client(clips=clips, labels=labels)
    r = client.get("/labels/queue")
    body = r.json()
    assert body["items"] == []
    assert body["has_more"] is False
    assert body["next_cursor"] is None


def test_queue_excludes_idle_clips() -> None:
    """has_motion=False (idle 세그먼트) 는 큐에서 제외 — 영상 재생 의미 없음."""
    clips = [
        _clip_row(clip_id="motion-c1", has_motion=True),
        _clip_row(clip_id="idle-c2", has_motion=False),
    ]
    client, _ = _make_client(clips=clips)
    r = client.get("/labels/queue")
    body = r.json()
    ids = [it["id"] for it in body["items"]]
    assert ids == ["motion-c1"]


def test_queue_excludes_clips_without_r2_key() -> None:
    """r2_key=NULL 은 큐에서 제외 — cross-origin 라벨링 웹에서 재생 불가."""
    clips = [
        _clip_row(clip_id="r2-c1", r2_key="clips/c1.mp4"),
        _clip_row(clip_id="local-c2", r2_key=None),
    ]
    client, _ = _make_client(clips=clips)
    r = client.get("/labels/queue")
    body = r.json()
    ids = [it["id"] for it in body["items"]]
    assert ids == ["r2-c1"]


# ────────────────────────────────────────────────────────────────────────────
# GET /labels/mine — 본인 라벨 회고 (라벨 시각순)
# ────────────────────────────────────────────────────────────────────────────


def test_mine_returns_labeled_clips_with_label_meta() -> None:
    """본인이 라벨한 클립과 라벨 정보를 함께 반환."""
    clips = [
        _clip_row(clip_id="c1", started_at="2026-05-02T10:00:00+00:00"),
        _clip_row(clip_id="c2", started_at="2026-05-02T11:00:00+00:00"),
    ]
    labels = [
        _label_row(
            clip_id="c1",
            labeled_by=OWNER_ID,
            action="moving",
            labeled_at="2026-05-04T09:00:00+00:00",
        ),
        _label_row(
            clip_id="c2",
            labeled_by=OWNER_ID,
            action="eating_paste",
            lick_target="dish",
            labeled_at="2026-05-04T12:00:00+00:00",
        ),
    ]
    client, _ = _make_client(clips=clips, labels=labels)
    r = client.get("/labels/mine")
    body = r.json()
    assert body["count"] == 2
    items = body["items"]
    # labeled_at desc — c2 (12:00) 가 c1 (09:00) 보다 위
    assert items[0]["clip"]["id"] == "c2"
    assert items[0]["label"]["action"] == "eating_paste"
    assert items[0]["label"]["lick_target"] == "dish"
    assert items[1]["clip"]["id"] == "c1"
    assert items[1]["label"]["action"] == "moving"


def test_mine_excludes_other_users_labels() -> None:
    """다른 라벨러 라벨은 안 보임."""
    clips = [_clip_row(clip_id="c1"), _clip_row(clip_id="c2")]
    labels = [
        _label_row(clip_id="c1", labeled_by=OWNER_ID, action="moving"),
        _label_row(clip_id="c2", labeled_by=LABELER_ID, action="drinking"),
    ]
    client, _ = _make_client(clips=clips, labels=labels)
    r = client.get("/labels/mine")
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["clip"]["id"] == "c1"


def test_mine_includes_idle_and_no_r2_clips() -> None:
    """queue 와 달리 has_motion/r2_key 필터 없음 — 회고 흐름은 모든 라벨한 클립 포함."""
    clips = [
        _clip_row(clip_id="idle", has_motion=False),
        _clip_row(clip_id="no-r2", r2_key=None),
    ]
    labels = [
        _label_row(
            clip_id="idle",
            labeled_by=OWNER_ID,
            labeled_at="2026-05-04T09:00:00+00:00",
        ),
        _label_row(
            clip_id="no-r2",
            labeled_by=OWNER_ID,
            labeled_at="2026-05-04T10:00:00+00:00",
        ),
    ]
    client, _ = _make_client(clips=clips, labels=labels)
    r = client.get("/labels/mine")
    body = r.json()
    assert body["count"] == 2


def test_mine_skips_orphan_labels_with_deleted_clip() -> None:
    """clip 이 삭제됐으면 라벨도 응답에서 빠짐."""
    labels = [
        _label_row(clip_id="ghost", labeled_by=OWNER_ID, action="moving"),
    ]
    client, _ = _make_client(clips=[], labels=labels)
    r = client.get("/labels/mine")
    body = r.json()
    assert body["items"] == []
    assert body["count"] == 0


def test_mine_empty_when_no_labels() -> None:
    """라벨 0건 — 빈 리스트."""
    client, _ = _make_client(clips=[_clip_row()])
    r = client.get("/labels/mine")
    body = r.json()
    assert body["items"] == []
    assert body["count"] == 0
    assert body["has_more"] is False
    assert body["next_cursor"] is None


def test_mine_pagination_cursor() -> None:
    """labeled_at cursor seek pagination."""
    clips = [_clip_row(clip_id=f"c{i}") for i in range(5)]
    labels = [
        _label_row(
            clip_id=f"c{i}",
            labeled_by=OWNER_ID,
            labeled_at=f"2026-05-04T1{i}:00:00+00:00",
        )
        for i in range(5)
    ]
    client, _ = _make_client(clips=clips, labels=labels)
    r1 = client.get("/labels/mine", params={"limit": 2})
    body1 = r1.json()
    # labeled_at desc — c4 (14:00) → c3 (13:00)
    assert [it["clip"]["id"] for it in body1["items"]] == ["c4", "c3"]
    assert body1["has_more"] is True
    assert body1["next_cursor"] == "2026-05-04T13:00:00+00:00"

    r2 = client.get(
        "/labels/mine",
        params={"limit": 2, "cursor": body1["next_cursor"]},
    )
    body2 = r2.json()
    assert [it["clip"]["id"] for it in body2["items"]] == ["c2", "c1"]


# ────────────────────────────────────────────────────────────────────────────
# GET /clips/{id}/inference — VLM 추론 (owner 전용)
# ────────────────────────────────────────────────────────────────────────────


def test_inference_owner_gets_latest_vlm_row() -> None:
    """owner 가 클립의 최신 VLM 추론 1건 조회 → action/confidence/reasoning."""
    logs = [
        _log_row(
            action="moving",
            confidence=0.6,
            created_at="2026-05-01T10:00:00+00:00",
        ),
        _log_row(
            action="drinking",
            confidence=0.82,
            reasoning="그릇 위 혀 동작",
            created_at="2026-05-02T15:00:00+00:00",
        ),
    ]
    client, _ = _make_client(clips=[_clip_row()], logs=logs)
    r = client.get(f"/clips/{CLIP_ID}/inference")
    assert r.status_code == 200
    body = r.json()
    # created_at desc → 두 번째 row (drinking) 가 최신
    assert body["action"] == "drinking"
    assert body["confidence"] == 0.82
    assert body["reasoning"] == "그릇 위 혀 동작"
    assert body["source"] == "vlm"


def test_inference_returns_null_when_no_vlm_row() -> None:
    """추론 없으면 null 반환 (404 아님)."""
    client, _ = _make_client(clips=[_clip_row()])
    r = client.get(f"/clips/{CLIP_ID}/inference")
    assert r.status_code == 200
    assert r.json() is None


def test_inference_excludes_human_source() -> None:
    """source=human 라벨은 제외, source=vlm 만."""
    logs = [
        _log_row(action="moving", source="human", created_at="2026-05-02T15:00:00+00:00"),
        _log_row(action="drinking", source="vlm", created_at="2026-05-02T10:00:00+00:00"),
    ]
    client, _ = _make_client(clips=[_clip_row()], logs=logs)
    r = client.get(f"/clips/{CLIP_ID}/inference")
    body = r.json()
    assert body["action"] == "drinking"
    assert body["source"] == "vlm"


def test_inference_labeler_403() -> None:
    """labeler (비-owner) 는 추론 조회 불가 — 영향 회피 (스펙 §3-C 시나리오 3)."""
    client, _ = _make_client(
        clips=[_clip_row()],
        logs=[_log_row()],
        labelers=[{"user_id": LABELER_ID}],
        user_id=LABELER_ID,
    )
    r = client.get(f"/clips/{CLIP_ID}/inference")
    assert r.status_code == 403


def test_inference_outsider_404() -> None:
    """외부인은 clip 자체 접근 불가."""
    client, _ = _make_client(
        clips=[_clip_row()], logs=[_log_row()], user_id=OUTSIDER_ID
    )
    r = client.get(f"/clips/{CLIP_ID}/inference")
    assert r.status_code == 404


def test_inference_clip_not_found_404() -> None:
    """존재하지 않는 clip → 404."""
    client, _ = _make_client(clips=[])
    r = client.get(f"/clips/{CLIP_ID}/inference")
    assert r.status_code == 404
