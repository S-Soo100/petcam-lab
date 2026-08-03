from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from scripts.project_motion_clip_canonical_gt import (
    ProjectionOptions,
    build_rpc_params,
    main,
)


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeCall:
    def __init__(self, data):
        self._data = data

    def execute(self):
        if isinstance(self._data, Exception):
            raise self._data
        return FakeResult(self._data)


class FakeClient:
    def __init__(self, results: dict[str, object]):
        self.results = results
        self.calls: list[tuple[str, dict[str, object]]] = []

    def rpc(self, name: str, params: dict[str, object]):
        self.calls.append((name, params))
        return FakeCall(self.results[name])


def test_build_rpc_params_uses_exact_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_USER_ID", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    options = ProjectionOptions(
        apply=False,
        run_id=UUID("40000000-0000-4000-8000-000000000001"),
        limit=250,
        after_source_id=UUID("50000000-0000-4000-8000-000000000001"),
    )
    assert build_rpc_params(options) == {
        "p_owner_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "p_apply": False,
        "p_limit": 250,
        "p_after_source_id": "50000000-0000-4000-8000-000000000001",
        "p_projection_run_id": "40000000-0000-4000-8000-000000000001",
    }


def test_projector_defaults_to_dry_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEV_USER_ID", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    client = FakeClient(
        {
            "fn_project_motion_clip_canonical_gt": {
                "scanned": 2,
                "inserted": 2,
                "already_present": 0,
                "conflicts": 0,
                "dry_run": True,
                "next_after_source_id": None,
            }
        }
    )
    assert main(["--report-dir", str(tmp_path)], client_factory=lambda: client) == 0
    assert client.calls[0][0] == "fn_project_motion_clip_canonical_gt"
    assert client.calls[0][1]["p_apply"] is False
    report = json.loads(next(tmp_path.glob("projection-*.json")).read_text())
    assert report["result"]["dry_run"] is True
    assert "next_after_source_id" not in report["result"]


def test_apply_requires_matching_confirmation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEV_USER_ID", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    client = FakeClient({})
    with pytest.raises(SystemExit) as caught:
        main(
            [
                "--apply",
                "--run-id",
                "40000000-0000-4000-8000-000000000001",
                "--report-dir",
                str(tmp_path),
            ],
            client_factory=lambda: client,
        )
    assert caught.value.code == 2
    assert client.calls == []


def test_apply_records_successful_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEV_USER_ID", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    run_id = "40000000-0000-4000-8000-000000000001"
    client = FakeClient(
        {
            "fn_project_motion_clip_canonical_gt": {
                "scanned": 1,
                "inserted": 1,
                "already_present": 0,
                "conflicts": 0,
                "dry_run": False,
                "next_after_source_id": None,
            },
            "fn_record_motion_clip_gt_projection_run": None,
        }
    )
    assert main(
        [
            "--apply",
            "--run-id",
            run_id,
            "--confirm-run-id",
            run_id,
            "--report-dir",
            str(tmp_path),
        ],
        client_factory=lambda: client,
    ) == 0
    assert client.calls[1][0] == "fn_record_motion_clip_gt_projection_run"
    assert client.calls[1][1]["p_status"] == "succeeded"


def test_dry_run_conflict_is_fail_loud(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEV_USER_ID", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    client = FakeClient(
        {
            "fn_project_motion_clip_canonical_gt": {
                "scanned": 1,
                "inserted": 0,
                "already_present": 0,
                "conflicts": 1,
                "dry_run": True,
                "next_after_source_id": None,
            }
        }
    )
    assert main(["--report-dir", str(tmp_path)], client_factory=lambda: client) == 2


def test_output_never_contains_service_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "service-secret-that-must-not-leak"
    monkeypatch.setenv("DEV_USER_ID", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", secret)
    client = FakeClient(
        {
            "fn_project_motion_clip_canonical_gt": RuntimeError(secret),
        }
    )
    assert main(["--report-dir", str(tmp_path)], client_factory=lambda: client) == 1
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
