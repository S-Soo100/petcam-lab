"""CLI (Task 10 부분): `roi-profile` · `pilot-select` · `pilot-extract` — attempt 디렉터리만 읽고 쓰는 순수 단계."""
from __future__ import annotations

import json
import stat

import pytest

from scripts.yolo26n_v27_c500g.cli import (
    load_dish_tags,
    run_adjudicate,
    run_audit_cvat,
    run_normalize_cvat,
    run_pilot_extract,
    run_pilot_select,
    run_roi_profile,
)
from scripts.yolo26n_v27_c500g.contracts import FrameRequest
from scripts.yolo26n_v27_c500g.private_io import write_private_json_new
from tests.yolo26n_v27_c500g.factories import SHA_A, SHA_B, ZERO_WRITES
from tests.yolo26n_v27_c500g.test_sampling import CAMS, FakeCapture, _build, _cam_digest, _frame_with_marker

LABELS = {"A": "cam01", "B": "cam02", "C": "cam03"}
RECTS = {"left": {"x1": 0.02, "y1": 0.05, "x2": 0.32, "y2": 0.98},
         "middle": {"x1": 0.35, "y1": 0.05, "x2": 0.65, "y2": 0.98},
         "right": {"x1": 0.68, "y1": 0.05, "x2": 0.98, "y2": 0.98}}


def _tool_json(**camera_over) -> dict[str, object]:
    cameras = {label: {"rects": json.loads(json.dumps(RECTS)), "day_verified": True, "ir_verified": True} for label in LABELS}
    for label, over in camera_over.items():
        cameras[label].update(over)
    return {"schema": "c500g-roi-tool-v1", "frame_width": 2880, "frame_height": 1620, "padding_px": 24,
            "cameras": cameras, "updated_at": "2026-09-11T03:00:00.000Z"}


@pytest.fixture
def attempt(tmp_path):
    inventory, roles = _build()
    root = tmp_path / "attempts" / "a9"
    write_private_json_new(root / "inventory" / "source-inventory.private.json", inventory)
    write_private_json_new(root / "roles" / "role-freeze.private.json", roles)
    return root


def _train_refs(attempt, n=3):
    roles = json.loads((attempt / "roles" / "role-freeze.private.json").read_text())
    refs = [r["source_ref"] for r in roles["rows"] if r["role"] == "v27_train"]
    return refs[:n]


def _holdout_ref(attempt):
    roles = json.loads((attempt / "roles" / "role-freeze.private.json").read_text())
    return next(r["source_ref"] for r in roles["rows"] if r["role"] == "v26_holdout")


def test_run_roi_profile_ingests_tool_json_and_writes_validated_profile(attempt, tmp_path):
    tool = tmp_path / "roi-tool.json"
    tool.write_text(json.dumps(_tool_json()))
    out = run_roi_profile(attempt=attempt, tool_json=tool, label_map=LABELS, calibration_sources=_train_refs(attempt),
                          test_sheet_sha256=SHA_A)
    path = attempt / "roi" / "roi-profile.private.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    profile = json.loads(path.read_text())
    assert profile["schema"] == "yolo26n-v27-c500g-roi-profile-v1" and profile["status"] == "V27_ROI_PROFILE_READY"
    assert set(profile["cameras"]) == {_cam_digest(c) for c in CAMS}
    assert profile["calibration_provenance"] == "v27_train" and profile["padding_px"] == 24
    assert "cam0" not in json.dumps(out["summary"]) and out["summary"]["profile_sha256"] == profile["profile_sha256"]
    assert (attempt / "roi" / "roi-tool-input.private.json").exists()
    with pytest.raises(FileExistsError):
        run_roi_profile(attempt=attempt, tool_json=tool, label_map=LABELS, calibration_sources=[], test_sheet_sha256=SHA_A)


def test_run_roi_profile_rejects_unverified_or_holdout_calibration(attempt, tmp_path):
    tool = tmp_path / "roi-tool.json"
    tool.write_text(json.dumps(_tool_json(B={"day_verified": False})))
    with pytest.raises(ValueError, match="day_verified"):
        run_roi_profile(attempt=attempt, tool_json=tool, label_map=LABELS, calibration_sources=[], test_sheet_sha256=SHA_A)
    tool.write_text(json.dumps(_tool_json()))
    with pytest.raises(ValueError, match="holdout"):
        run_roi_profile(attempt=attempt, tool_json=tool, label_map=LABELS, calibration_sources=[_holdout_ref(attempt)],
                        test_sheet_sha256=SHA_A)
    assert not (attempt / "roi" / "roi-profile.private.json").exists()


def _with_profile(attempt, tmp_path):
    tool = tmp_path / "roi-tool.json"
    tool.write_text(json.dumps(_tool_json()))
    run_roi_profile(attempt=attempt, tool_json=tool, label_map=LABELS, calibration_sources=_train_refs(attempt), test_sheet_sha256=SHA_A)


def test_run_pilot_select_writes_requests_with_disjoint_warmup(attempt, tmp_path):
    _with_profile(attempt, tmp_path)
    out = run_pilot_select(attempt=attempt, seed="v27-pilot-v1", target=600, warmup=27, test_sheet_sha256=SHA_A)
    path = attempt / "pilot" / "pilot-requests.private.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    doc = json.loads(path.read_text())
    assert doc["schema"] == "yolo26n-v27-c500g-pilot-requests-v1" and doc["status"] == "PILOT_REQUESTS_READY"
    pilot = [FrameRequest.from_json(r) for r in doc["requests"]]
    warm = [FrameRequest.from_json(r) for r in doc["warmup_requests"]]
    assert len(pilot) == 600 and len(warm) == 27
    assert {r.source_ref for r in pilot}.isdisjoint(r.source_ref for r in warm)
    assert out["summary"]["pilot"]["request_count"] == 600 and out["summary"]["warmup"]["request_count"] == 27
    assert "recordings/" not in json.dumps(out["summary"])


def test_run_pilot_select_refuses_test_sheet_mismatch(attempt, tmp_path):
    _with_profile(attempt, tmp_path)
    with pytest.raises(ValueError, match="TEST-SHEET"):
        run_pilot_select(attempt=attempt, seed="s", target=60, warmup=0, test_sheet_sha256=SHA_B)


def test_load_dish_tags_ledger_to_mapping(tmp_path):
    ledger = {"schema": "yolo26n-v27-c500g-dish-tags-v1", "status": "DISH_TAGS_READY", "test_sheet_sha256": SHA_A,
              "dish_tag_version": 1, "entries": [
                  {"source_ref": "recordings/cam01/night=2026-08-20/x", "roi_name": "left", "food_in_dish": True, "tagger": "owner", "tagged_at": "t"},
                  {"source_ref": "recordings/cam01/night=2026-08-20/x", "roi_name": "middle", "food_in_dish": None, "tagger": "owner", "tagged_at": "t"},
              ], **ZERO_WRITES}
    path = tmp_path / "dish-tags-v1.private.json"
    path.write_text(json.dumps(ledger))
    assert load_dish_tags(path) == {"recordings/cam01/night=2026-08-20/x": {"left": True, "middle": None}}
    ledger["schema"] = "other"
    path.write_text(json.dumps(ledger))
    with pytest.raises(ValueError, match="dish-tags"):
        load_dish_tags(path)


def test_run_pilot_extract_writes_queue_zip_lineage_and_double_review(attempt, tmp_path):
    _with_profile(attempt, tmp_path)
    run_pilot_select(attempt=attempt, seed="v27-pilot-v1", target=60, warmup=9, test_sheet_sha256=SHA_A)
    factory = lambda path: FakeCapture(lambda pos: _frame_with_marker(pos, salt=str(path)))  # noqa: E731
    out = run_pilot_extract(attempt=attempt, source_root=tmp_path / "mirror", which="pilot", test_sheet_sha256=SHA_A,
                            double_review_count=6, capture_factory=factory)
    pilot_dir = attempt / "pilot" / "pilot"
    for name in ("review-queue.zip", "review-queue.public.json", "lineage.private.json", "extract-report.private.json", "double-review.private.json"):
        assert (pilot_dir / name).exists(), name
    double = json.loads((pilot_dir / "double-review.private.json").read_text())
    assert double["schema"] == "yolo26n-v27-c500g-double-review-v1" and len(double["anonymous_sequences"]) == 6
    assert out["report"]["kept"] == 60 and out["report"]["status"] == "REVIEW_QUEUE_READY"
    warm = run_pilot_extract(attempt=attempt, source_root=tmp_path / "mirror", which="warmup", test_sheet_sha256=SHA_A,
                             capture_factory=factory)
    assert warm["report"]["kept"] == 9 and warm["queue"]["items"][0]["anonymous_sequence"] == "V27W0001"
    assert not (attempt / "pilot" / "warmup" / "double-review.private.json").exists()


def test_run_roi_profile_attestation_replaces_unticked_flags_and_is_recorded(attempt, tmp_path):
    tool = tmp_path / "roi-tool.json"
    tool.write_text(json.dumps(_tool_json(A={"day_verified": False, "ir_verified": False}, B={"day_verified": False})))
    with pytest.raises(ValueError, match="attest"):
        run_roi_profile(attempt=attempt, tool_json=tool, label_map=LABELS, calibration_sources=[], test_sheet_sha256=SHA_A,
                        attest_verified="   ")
    out = run_roi_profile(attempt=attempt, tool_json=tool, label_map=LABELS, calibration_sources=_train_refs(attempt),
                          test_sheet_sha256=SHA_A, attest_verified="owner drew on IR frames; Claude overlay check on evening frames")
    profile = json.loads((attempt / "roi" / "roi-profile.private.json").read_text())
    assert profile["day_verified"] is True and profile["ir_verified"] is True
    recorded = json.loads((attempt / "roi" / "roi-tool-input.private.json").read_text())
    assert recorded["attest_verified"].startswith("owner drew") and recorded["attested_at_utc"].endswith("Z")
    assert recorded["tool"]["cameras"]["A"]["day_verified"] is False  # 원본 도구 상태는 그대로 보존
    assert out["summary"]["verification"] == "attested"


def _fake_export(queue_doc, statuses):
    from tests.yolo26n_v27_c500g.test_cvat import LABELS, _shape, _tag
    items = sorted(queue_doc["items"], key=lambda i: i["anonymous_sequence"])
    frames = [{"name": f"v27-c500g/{i['image_name']}", "width": i["width"], "height": i["height"]} for i in items]
    tags, shapes = [], []
    for idx, status in enumerate(statuses):
        tags.append(_tag(idx, status))
        if status == "present":
            shapes.append({**_shape(idx, (10.0, 20.0, 110.0, 220.0)), "id": 700 + idx})
    return {"name": "job-x", "received_at_utc": "t", "payload": {"source": "cvat-api-job-annotations", "cvat_version": "2.66.0",
            "job": {"id": 77, "task_id": 9, "stage": "annotation", "state": "completed"}, "frames": frames, "labels": LABELS,
            "annotations": {"version": 1, "tags": tags, "shapes": shapes, "tracks": [], "intervals": []}}}


def test_run_normalize_cvat_and_adjudicate_from_inbox_exports(attempt, tmp_path):
    _with_profile(attempt, tmp_path)
    run_pilot_select(attempt=attempt, seed="v27-pilot-v1", target=6, warmup=0, test_sheet_sha256=SHA_A)
    factory = lambda path: FakeCapture(lambda pos: _frame_with_marker(pos, salt=str(path)))  # noqa: E731
    run_pilot_extract(attempt=attempt, source_root=tmp_path / "mirror", which="pilot", test_sheet_sha256=SHA_A, double_review_count=3, capture_factory=factory)
    queue_doc = json.loads((attempt / "pilot" / "pilot" / "review-queue.public.json").read_text())
    export = tmp_path / "job77.json"
    export.write_text(json.dumps(_fake_export(queue_doc, ["present", "absent", "present", "absent", "absent", "present"])))
    audit = run_audit_cvat(attempt=attempt, which="pilot", export_path=export, test_sheet_sha256=SHA_A)
    assert audit["ok"] is True and audit["frames_complete"] == 6
    out = run_normalize_cvat(attempt=attempt, which="pilot", export_path=export, test_sheet_sha256=SHA_A)
    path = attempt / "pilot" / "pilot" / "human-gt.private.json"
    assert path.exists() and stat.S_IMODE(path.stat().st_mode) == 0o600
    gt = json.loads(path.read_text())
    assert gt["schema"] == "yolo26n-v27-c500g-human-gt-v1" and gt["summary"]["status_counts"]["present"] == 3 and gt["cvat_job_id"] == 77
    assert out["summary"]["status_counts"]["absent"] == 3
    # 두 번째 정규화는 새 리비전 파일명으로
    out2 = run_normalize_cvat(attempt=attempt, which="pilot", export_path=export, test_sheet_sha256=SHA_A)
    assert out2["path"].name == "human-gt.r2.private.json"
    # double-review: 큐는 double-review.zip 안 manifest, 결과는 pilot/double-review/
    double_doc = json.loads(zipfile_read(attempt / "pilot" / "pilot" / "double-review.zip", "double-review.public.json"))
    export2 = tmp_path / "job78.json"
    export2.write_text(json.dumps(_fake_export(double_doc, ["absent"] * len(double_doc["items"]))))
    out3 = run_normalize_cvat(attempt=attempt, which="double", export_path=export2, test_sheet_sha256=SHA_A)
    assert out3["path"] == attempt / "pilot" / "double-review" / "human-gt.private.json"
    adj = run_adjudicate(attempt=attempt, primary_gt=path, secondary_gt=out3["path"], test_sheet_sha256=SHA_A)
    assert adj["path"] == attempt / "pilot" / "double-review" / "adjudication-queue.private.json"
    assert adj["queue"]["compared_count"] == len(double_doc["items"]) and adj["queue"]["conflict_count"] >= 0
    with pytest.raises(ValueError, match="TEST-SHEET"):
        run_audit_cvat(attempt=attempt, which="pilot", export_path=export, test_sheet_sha256=SHA_B)


def zipfile_read(path, member):
    import zipfile
    with zipfile.ZipFile(path) as zf:
        return zf.read(member)
