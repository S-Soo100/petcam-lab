import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.research_runtime.job_spec import JobSpecError, parse_job_spec


NOW = datetime(2026, 7, 28, tzinfo=timezone.utc)


def valid_spec() -> dict:
    return {
        "schema_version": 1,
        "job_id": "r1-noop-001",
        "task_id": "r1-mac-mini-runtime-foundation",
        "handler": "synthetic_noop_v1",
        "handler_args": {"steps": 3, "step_seconds": 0},
        "manifest_blob_sha": "a" * 64,
        "manifest_commit_sha": "b" * 40,
        "repo_head": "c" * 40,
        "expected_host": "baeg-endeuui-Macmini.local",
        "budget": {
            "max_provider_calls": 0,
            "max_cost_krw": 0,
            "max_wall_seconds": 300,
            "deadline": "2026-08-31T23:59:59+09:00",
        },
        "resources": [],
        "privacy_class": "internal",
    }


def write_spec(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "job.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_job_spec_accepts_only_noop_and_zero_external_budget(tmp_path: Path) -> None:
    parsed = parse_job_spec(write_spec(tmp_path, valid_spec()), now=NOW)
    assert parsed.handler == "synthetic_noop_v1"
    assert parsed.resources == ()
    assert len(parsed.canonical_bytes) > 0


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(handler="shell"),
        lambda value: value["budget"].update(max_provider_calls=1),
        lambda value: value.update(password="not-allowed"),
        lambda value: value.update(job_id="../escape"),
        lambda value: value.update(manifest_blob_sha="A" * 64),
        lambda value: value["budget"].update(deadline="2026-07-01T00:00:00Z"),
    ],
)
def test_job_spec_fails_closed(
    tmp_path: Path,
    mutation,
) -> None:
    value = valid_spec()
    mutation(value)
    with pytest.raises(JobSpecError):
        parse_job_spec(write_spec(tmp_path, value), now=NOW)


def test_job_spec_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    text = json.dumps(valid_spec()).replace(
        '"job_id": "r1-noop-001"',
        '"job_id": "r1-noop-001", "job_id": "r1-noop-002"',
    )
    path = tmp_path / "job.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(JobSpecError, match="duplicate_json_key"):
        parse_job_spec(path, now=NOW)
