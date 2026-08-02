import hashlib
import json
from pathlib import Path
import stat

import pytest

from scripts.recompute_local_vlm_clip_shadow import IntegrityError, recompute


def _write_private(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def _jsonl(rows: list[dict[str, object]]) -> bytes:
    return b"".join(
        (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
        for row in rows
    )


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    run = tmp_path / "run"
    out = tmp_path / "report"
    run.mkdir(mode=0o700)
    out.mkdir(mode=0o700)
    (run / "media").mkdir(mode=0o700)
    (run / "inputs").mkdir(mode=0o700)
    image = b"jpeg"
    video = b"video"
    _write_private(run / "inputs" / "clip-a.jpg", image)
    _write_private(run / "media" / "clip-a.mp4", video)
    gate = {
        "schema_version": "production-local-vlm-clip-shadow-gate-a-v1",
        "model": "gemma3:4b",
        "model_inventory": {"digest": "model-digest", "size": 10},
        "prompt_sha256": "prompt-digest",
        "start_at": "2026-08-02T09:00:00+00:00",
        "end_at": "2026-08-02T22:00:00+00:00",
    }
    _write_private(run / "gate-a.json", json.dumps(gate).encode())
    ledger = [
        {
            "type": "request_intent", "clip": "clip-a",
            "model_digest": "model-digest", "prompt_sha256": "prompt-digest",
            "input_sha256": hashlib.sha256(image).hexdigest(),
        },
        {
            "type": "result", "clip": "clip-a", "status": "schema_valid",
            "elapsed_sec": 2.5,
            "prediction": {
                "gecko_visibility": "visible", "activity_state": "active",
                "notable_change": "movement", "summary_ko": "게코가 움직여.",
                "confidence": 0.8, "needs_human_review": False,
            },
        },
        {"type": "media_error", "clip": "clip-b", "error": "RunnerSafetyError"},
    ]
    resources = [
        {"type": "resource", "clip": "monitor", "baseline": True,
         "sample": {"free_percent": 60, "swap_used_bytes": 100, "serve_pid": 10, "serve_rss_kib": 1000}},
        {"type": "resource", "clip": "monitor",
         "sample": {"free_percent": 55, "swap_used_bytes": 200, "serve_pid": 10, "serve_rss_kib": 1500}},
    ]
    _write_private(run / "ledger.jsonl", _jsonl(ledger))
    _write_private(run / "resources.jsonl", _jsonl(resources))
    return run, out


def test_recompute_independently_validates_and_aggregates(tmp_path: Path) -> None:
    run, out = _fixture(tmp_path)
    summary = recompute(run, out)
    assert summary["attempted"] == 1
    assert summary["schema_valid"] == 1
    assert summary["media_error"] == 1
    assert summary["latency_sec"] == {"p50": 2.5, "p95": 2.5, "max": 2.5}
    assert summary["resource"] == {
        "free_min_percent": 55,
        "swap_delta_bytes": 100,
        "serve_rss_max_kib": 1500,
        "pid_drift": False,
        "low_free_abort": False,
    }
    assert stat.S_IMODE((out / "summary-private.json").stat().st_mode) == 0o600


def test_recompute_rejects_duplicate_or_result_without_intent(tmp_path: Path) -> None:
    run, out = _fixture(tmp_path)
    rows = [json.loads(line) for line in (run / "ledger.jsonl").read_text().splitlines()]
    rows.insert(1, dict(rows[0]))
    _write_private(run / "ledger.jsonl", _jsonl(rows))
    with pytest.raises(IntegrityError, match="duplicate"):
        recompute(run, out)

    run, out = _fixture(tmp_path / "other")
    rows = [json.loads(line) for line in (run / "ledger.jsonl").read_text().splitlines()]
    rows = [row for row in rows if row.get("type") != "request_intent"]
    _write_private(run / "ledger.jsonl", _jsonl(rows))
    with pytest.raises(IntegrityError, match="without_intent"):
        recompute(run, out)


def test_recompute_rejects_digest_drift(tmp_path: Path) -> None:
    run, out = _fixture(tmp_path)
    rows = [json.loads(line) for line in (run / "ledger.jsonl").read_text().splitlines()]
    rows[0]["model_digest"] = "other"
    _write_private(run / "ledger.jsonl", _jsonl(rows))
    with pytest.raises(IntegrityError, match="digest"):
        recompute(run, out)


def test_review_html_is_private_read_only_and_public_report_has_no_identity(tmp_path: Path) -> None:
    run, out = _fixture(tmp_path)
    recompute(run, out)
    private_html = (out / "review-index-private.html").read_text()
    public = (out / "public-report.md").read_text()
    assert "media/clip-a.mp4" in private_html
    assert "게코가 움직여" in private_html
    assert "<form" not in private_html and "action=" not in private_html
    assert "clip-a" not in public and "clip-b" not in public
    assert "r2_key" not in public and str(run) not in public
