"""dish_present 태깅 로컬 도구 — train/val 썸네일만 서빙, holdout 은 403, 태그는 append-only 엔트리 + 컴파일 원장."""
from __future__ import annotations

import hashlib
import json
import stat

import pytest
from fastapi.testclient import TestClient

from scripts.yolo26n_v27_c500g.cli import load_dish_tags
from scripts.yolo26n_v27_c500g.dish_tag_server import compile_dish_tags, create_app
from scripts.yolo26n_v27_c500g.private_io import write_private_json_new
from tests.yolo26n_v27_c500g.factories import SHA_A
from tests.yolo26n_v27_c500g.test_sampling import HOLDOUT_NIGHT, _build

TRAIN_REF = "recordings/cam01/night=2026-08-20/20260820T200000+0900"
HOLDOUT_REF = f"recordings/cam01/night={HOLDOUT_NIGHT}/20260904T200000+0900"


@pytest.fixture
def world(tmp_path):
    inventory, roles = _build(nights=("2026-08-20", "2026-08-21"), slots_per_night=4)
    roles_path = tmp_path / "attempt" / "roles" / "role-freeze.private.json"
    write_private_json_new(roles_path, roles)
    mirror = tmp_path / "mirror"
    for row in roles["rows"]:
        d = mirror / row["source_ref"]
        d.mkdir(parents=True)
        (d / "thumbnail.jpg").write_bytes(b"JPEG:" + row["source_ref"].encode())
    ledger_dir = tmp_path / "attempt" / "dish"
    app = create_app(roles_path=roles_path, mirror_root=mirror, ledger_dir=ledger_dir, test_sheet_sha256=SHA_A, tagger="owner")
    return TestClient(app), roles, mirror, ledger_dir


def test_slots_list_only_train_and_val_roles_in_order(world):
    client, roles, _, _ = world
    slots = client.get("/api/slots").json()["slots"]
    refs = [s["source_ref"] for s in slots]
    assert refs and all(HOLDOUT_NIGHT not in r for r in refs)
    assert refs == sorted(refs)
    assert {s["role"] for s in slots} <= {"v27_train", "v27_val"}
    assert slots[0]["tags"] is None and slots[0]["camera_key"] == "cam01" and slots[0]["night_date"] == "2026-08-20"


def test_thumbnail_served_for_train_and_refused_for_holdout_or_unknown(world):
    client, _, mirror, _ = world
    ok = client.get("/api/thumb", params={"ref": TRAIN_REF})
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/jpeg"
    assert ok.content == (mirror / TRAIN_REF / "thumbnail.jpg").read_bytes()
    assert client.get("/api/thumb", params={"ref": HOLDOUT_REF}).status_code == 403
    assert client.get("/api/thumb", params={"ref": "recordings/cam01/night=2026-08-20/nope"}).status_code == 404
    assert client.get("/api/thumb", params={"ref": "../../etc/passwd"}).status_code == 404


def test_tag_appends_private_entries_and_latest_wins(world):
    client, _, _, ledger_dir = world
    first = client.post("/api/tag", json={"source_ref": TRAIN_REF, "tags": {"left": True, "middle": False, "right": None}})
    assert first.status_code == 200 and first.json()["ok"] is True
    second = client.post("/api/tag", json={"source_ref": TRAIN_REF, "tags": {"left": False, "middle": False, "right": False}})
    assert second.status_code == 200
    entries = sorted((ledger_dir / "entries").glob("*.json"))
    assert len(entries) == 2 and all(stat.S_IMODE(e.stat().st_mode) == 0o600 for e in entries)
    slot = next(s for s in client.get("/api/slots").json()["slots"] if s["source_ref"] == TRAIN_REF)
    assert slot["tags"] == {"left": False, "middle": False, "right": False}
    assert client.post("/api/tag", json={"source_ref": HOLDOUT_REF, "tags": {"left": True, "middle": True, "right": True}}).status_code == 403
    assert client.post("/api/tag", json={"source_ref": TRAIN_REF, "tags": {"left": "yes", "middle": False, "right": False}}).status_code == 422
    assert client.post("/api/tag", json={"source_ref": TRAIN_REF, "tags": {"left": True}}).status_code == 422


def test_compile_dish_tags_flattens_latest_entries_into_ledger(world, tmp_path):
    client, _, _, ledger_dir = world
    client.post("/api/tag", json={"source_ref": TRAIN_REF, "tags": {"left": True, "middle": False, "right": None}})
    client.post("/api/tag", json={"source_ref": TRAIN_REF, "tags": {"left": True, "middle": True, "right": None}})
    other = "recordings/cam02/night=2026-08-21/20260821T203000+0900"
    client.post("/api/tag", json={"source_ref": other, "tags": {"left": False, "middle": False, "right": False}})
    out = ledger_dir / "dish-tags-v1.private.json"
    ledger = compile_dish_tags(ledger_dir, out, test_sheet_sha256=SHA_A)
    assert ledger["schema"] == "yolo26n-v27-c500g-dish-tags-v1" and ledger["status"] == "DISH_TAGS_READY"
    assert ledger["dish_tag_version"] == 1 and ledger["summary"] == {"slots_tagged": 2, "food_in_dish_true": 2, "food_in_dish_false": 3, "unclear": 1,
                                                                     "slots_by_method": {"inspected": 2}}
    assert {e["method"] for e in ledger["entries"]} == {"inspected"}
    assert load_dish_tags(out) == {TRAIN_REF: {"left": True, "middle": True, "right": None}, other: {"left": False, "middle": False, "right": False}}
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        compile_dish_tags(ledger_dir, out, test_sheet_sha256=SHA_A)


def test_index_page_is_served(world):
    client, _, _, _ = world
    page = client.get("/")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert "dish" in page.text.lower() and "/api/slots" in page.text


def test_inbox_accepts_json_from_local_cvat_origin_and_writes_private_file(world):
    client, _, _, ledger_dir = world
    payload = {"job": {"id": 31}, "annotations": {"tags": [], "shapes": []}}
    res = client.post("/api/inbox/job31-warmup", json=payload, headers={"Origin": "http://localhost:8080"})
    assert res.status_code == 200 and res.headers.get("access-control-allow-origin") == "http://localhost:8080"
    saved = sorted((ledger_dir.parent / "cvat-exports").glob("job31-warmup-*.private.json"))
    assert len(saved) == 1 and stat.S_IMODE(saved[0].stat().st_mode) == 0o600
    assert json.loads(saved[0].read_text())["payload"] == payload
    assert res.json()["sha256"] == hashlib.sha256(saved[0].read_bytes()).hexdigest()
    assert client.post("/api/inbox/bad name", json=payload).status_code == 422
    assert client.options("/api/inbox/x", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"}).status_code == 400
