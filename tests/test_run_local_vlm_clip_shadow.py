import json
from datetime import datetime, timezone
from pathlib import Path
import stat

import cv2
import numpy as np
import pytest

from scripts.run_local_vlm_clip_shadow import (
    MODEL,
    ClipCandidate,
    RunnerSafetyError,
    append_ledger,
    build_ollama_payload,
    candidate_from_row,
    fetch_candidates,
    load_processed_keys,
    private_token,
    parse_resource_sample,
    make_synthetic_sheet,
    process_candidate,
    smoke_contract,
    select_next_candidate,
)


class _Response:
    def __init__(self, data: list[dict[str, object]]):
        self.data = data


class _Query:
    def __init__(self, pages: list[list[dict[str, object]]]):
        self.pages = pages
        self.calls: list[tuple[str, object]] = []

    def select(self, columns: str) -> "_Query":
        self.calls.append(("select", columns))
        return self

    def gte(self, column: str, value: str) -> "_Query":
        self.calls.append(("gte", (column, value)))
        return self

    def order(self, column: str) -> "_Query":
        self.calls.append(("order", column))
        return self

    @property
    def not_(self) -> "_Query":
        self.calls.append(("not_", True))
        return self

    def is_(self, column: str, value: str) -> "_Query":
        self.calls.append(("is_", (column, value)))
        return self

    def range(self, start: int, end: int) -> "_Query":
        self.calls.append(("range", (start, end)))
        self._page = start // 2
        return self

    def execute(self) -> _Response:
        return _Response(self.pages[self._page] if self._page < len(self.pages) else [])


class _Client:
    def __init__(self, pages: list[list[dict[str, object]]]):
        self.query = _Query(pages)

    def table(self, name: str) -> _Query:
        assert name == "motion_clips"
        return self.query


def _row(clip_id: str, started_at: str) -> dict[str, object]:
    return {
        "id": clip_id,
        "camera_id": "camera-1",
        "r2_key": f"clips/{clip_id}.mp4",
        "started_at": started_at,
        "duration_sec": 60,
    }


def test_fetch_candidates_uses_only_frozen_columns_and_requeries_full_window() -> None:
    start = datetime(2026, 8, 2, 9, tzinfo=timezone.utc)
    salt = b"s" * 32
    first = _Client([[_row("later", "2026-08-02T09:02:00+00:00")]])
    first_rows = fetch_candidates(first, start_at=start, salt=salt, page_size=2)
    assert [row.private_key for row in first_rows] == [private_token(salt, "clip", "later")]
    assert ("select", "id,camera_id,r2_key,started_at,duration_sec") in first.query.calls
    assert ("is_", ("r2_key", "null")) in first.query.calls
    assert [value for key, value in first.query.calls if key == "order"] == ["started_at", "id"]

    # 다음 poll도 cursor가 아니라 같은 시작점을 다시 조회하므로 늦게 insert된 과거 시각 row를 놓치지 않아.
    second = _Client([[
        _row("late-insert", "2026-08-02T09:01:00+00:00"),
        _row("later", "2026-08-02T09:02:00+00:00"),
    ], []])
    second_rows = fetch_candidates(second, start_at=start, salt=salt, page_size=2)
    assert [row.clip_id for row in second_rows] == ["late-insert", "later"]


def test_candidate_rejects_missing_or_extra_source_fields() -> None:
    row = _row("clip", "2026-08-02T09:00:00+00:00")
    with pytest.raises(RunnerSafetyError, match="source_row"):
        candidate_from_row({**row, "has_motion": True}, b"s" * 32)
    row.pop("r2_key")
    with pytest.raises(RunnerSafetyError, match="source_row"):
        candidate_from_row(row, b"s" * 32)


def test_candidate_accepts_missing_duration_without_using_it_to_select() -> None:
    row = _row("clip", "2026-08-02T09:00:00+00:00")
    row["duration_sec"] = None
    assert candidate_from_row(row, b"s" * 32).duration_sec is None


def test_select_next_excludes_any_key_with_a_persisted_request_intent() -> None:
    rows = (
        ClipCandidate("a", "raw-a", "cam", "a.mp4", "2026-08-02T09:00:00+00:00", 60),
        ClipCandidate("b", "raw-b", "cam", "b.mp4", "2026-08-02T09:01:00+00:00", 60),
    )
    assert select_next_candidate(rows, {"a"}) == rows[1]
    assert select_next_candidate(rows, {"a", "b"}) is None


def test_ledger_fsync_contract_treats_intent_as_processed(tmp_path: Path) -> None:
    ledger = tmp_path / "results.jsonl"
    append_ledger(ledger, {"type": "request_intent", "clip": "private-a"})
    append_ledger(ledger, {"type": "result", "clip": "private-a", "status": "schema_valid"})
    append_ledger(ledger, {"type": "media_error", "clip": "private-b"})
    assert stat.S_IMODE(ledger.stat().st_mode) == 0o600
    assert load_processed_keys(ledger) == {"private-a", "private-b"}
    assert [json.loads(line)["type"] for line in ledger.read_text().splitlines()] == [
        "request_intent", "result", "media_error"
    ]


def test_ledger_rejects_corruption_and_duplicate_request_intent(tmp_path: Path) -> None:
    ledger = tmp_path / "results.jsonl"
    append_ledger(ledger, {"type": "request_intent", "clip": "x"})
    with pytest.raises(RunnerSafetyError, match="duplicate"):
        append_ledger(ledger, {"type": "request_intent", "clip": "x"})
    ledger.write_text('{"type":', encoding="utf-8")
    ledger.chmod(0o600)
    with pytest.raises(RunnerSafetyError, match="ledger"):
        load_processed_keys(ledger)


def test_ollama_payload_is_exact_frozen_production_contract() -> None:
    payload = build_ollama_payload(b"jpeg")
    assert payload["model"] == MODEL
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["keep_alive"] == "5m"
    assert payload["options"] == {
        "temperature": 0,
        "seed": 20260802,
        "num_ctx": 4096,
        "num_predict": 320,
    }
    assert payload["format"]["additionalProperties"] is False
    json.dumps(payload, allow_nan=False)


def test_resource_sample_requires_one_stable_ollama_serve_pid() -> None:
    row = parse_resource_sample(
        "System-wide memory free percentage: 62%",
        "total = 2048.00M used = 32.00M free = 2016.00M",
        "123 45678 /opt/homebrew/bin/ollama serve\n456 20 unrelated",
    )
    assert row == {
        "free_percent": 62,
        "swap_used_bytes": 32 * 1024 * 1024,
        "serve_pid": 123,
        "serve_rss_kib": 45678,
    }
    with pytest.raises(RunnerSafetyError, match="pid"):
        parse_resource_sample("free percentage: 62%", "used = 0.00M", "")


def test_synthetic_gate_images_are_deterministic_and_distinct() -> None:
    dark = make_synthetic_sheet("dark_empty")
    static = make_synthetic_sheet("static_silhouette")
    moving = make_synthetic_sheet("moving_silhouette")
    assert dark == make_synthetic_sheet("dark_empty")
    assert len({dark, static, moving}) == 3
    dark_frame = cv2.imdecode(np.frombuffer(dark, np.uint8), cv2.IMREAD_COLOR)
    static_frame = cv2.imdecode(np.frombuffer(static, np.uint8), cv2.IMREAD_COLOR)
    assert static_frame.mean() > dark_frame.mean() + 100


def test_smoke_contract_checks_one_observable_attribute_per_scene() -> None:
    assert smoke_contract("dark_empty")[1:] == ("background", "dark")
    assert smoke_contract("static_silhouette")[1:] == ("position_change", "no")
    assert smoke_contract("moving_silhouette")[1:] == ("position_change", "yes")
    for scene in ("dark_empty", "static_silhouette", "moving_silhouette"):
        schema, key, expected = smoke_contract(scene)
        assert schema["required"] == [key]
        assert expected in schema["properties"][key]["enum"]


def test_transient_r2_failure_retries_three_polls_before_media_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "run"
    output.mkdir(mode=0o700)
    (output / "media").mkdir(mode=0o700)
    (output / "inputs").mkdir(mode=0o700)
    ledger = output / "ledger.jsonl"
    candidate = ClipCandidate("clip", "raw", "cam", "key", "2026-08-02T09:00:00+00:00", 60)

    def transient(*_args: object, **_kwargs: object) -> object:
        from scripts.run_local_vlm_clip_shadow import MediaRetryError
        raise MediaRetryError("network")

    monkeypatch.setattr("scripts.run_local_vlm_clip_shadow.download_media", transient)
    for expected in ("retry", "retry", "processed"):
        assert process_candidate(
            candidate, salt=b"s" * 32, output_dir=output, ledger=ledger,
            r2=object(), bucket="bucket", model_digest="digest",
        ) == expected
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert [row["type"] for row in rows] == ["media_retry", "media_retry", "media_error"]
    assert load_processed_keys(ledger) == {"clip"}


def test_restart_reuses_complete_private_media_and_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "run"
    output.mkdir(mode=0o700)
    media = output / "media"
    inputs = output / "inputs"
    media.mkdir(mode=0o700)
    inputs.mkdir(mode=0o700)
    (media / "clip.mp4").write_bytes(b"complete-video")
    (media / "clip.mp4").chmod(0o600)
    (inputs / "clip.jpg").write_bytes(b"complete-jpeg")
    (inputs / "clip.jpg").chmod(0o600)
    candidate = ClipCandidate("clip", "raw", "cam", "key", "2026-08-02T09:00:00+00:00", 60)
    monkeypatch.setattr(
        "scripts.run_local_vlm_clip_shadow.download_media",
        lambda *_a, **_k: pytest.fail("complete private media must be reused"),
    )
    monkeypatch.setattr(
        "scripts.run_local_vlm_clip_shadow.ollama_json",
        lambda *_a, **_k: {"message": {"content": json.dumps({
            "gecko_visibility": "visible", "activity_state": "active",
            "notable_change": "movement", "summary_ko": "게코가 움직여.",
            "confidence": 0.8, "needs_human_review": False,
        })}},
    )
    assert process_candidate(
        candidate, salt=b"s" * 32, output_dir=output,
        ledger=output / "ledger.jsonl", r2=object(), bucket="bucket", model_digest="digest",
    ) == "processed"
    assert [json.loads(line)["type"] for line in (output / "ledger.jsonl").read_text().splitlines()] == [
        "request_intent", "result"
    ]
