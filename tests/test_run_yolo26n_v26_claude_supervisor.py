from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile


SCRIPT = Path(__file__).parents[1] / "scripts" / "run_yolo26n_v26_claude_supervisor.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_zip(path: Path, image_count: int) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("README.txt", "blind review")
        for index in range(image_count):
            archive.writestr(f"images/frame_{index:024x}.jpg", f"image-{index}")


def _fixture_contract(tmp_path: Path) -> Path:
    primary = tmp_path / "primary.zip"
    double = tmp_path / "double.zip"
    review_index = tmp_path / "review-index.private.json"
    completion = tmp_path / "bundle-completion.private.json"
    inbox = tmp_path / "human-gt-inbox"
    _write_zip(primary, 2)
    _write_zip(double, 1)
    review_index.write_text('{"records": []}\n')
    completion.write_text('{"status": "V26_BLIND_BBOX_QUEUE_READY"}\n')
    contract = {
        "expected_status": "V26_BLIND_BBOX_QUEUE_READY",
        "primary_zip": str(primary),
        "primary_sha256": _sha256(primary),
        "primary_count": 2,
        "double_review_zip": str(double),
        "double_review_sha256": _sha256(double),
        "double_review_count": 1,
        "review_index": str(review_index),
        "review_index_sha256": _sha256(review_index),
        "completion_manifest": str(completion),
        "human_gt_inbox": str(inbox),
        "prompt_doc": str(tmp_path / "prompt.md"),
        "repo": str(tmp_path),
        "attempt_root": str(tmp_path),
    }
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(contract))
    return contract_path


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_verify_only_accepts_complete_fixed_artifacts_without_human_export(
    tmp_path: Path,
) -> None:
    contract = _fixture_contract(tmp_path)

    result = _run("--contract", str(contract), "--verify-only")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "double_review_count": 1,
        "human_gt_validated": False,
        "human_export_state": "WAITING",
        "primary_count": 2,
        "status": "SUPERVISOR_PREFLIGHT_OK",
    }


def test_present_exports_are_never_reported_as_validated_training_input(
    tmp_path: Path,
) -> None:
    contract = _fixture_contract(tmp_path)
    inbox = Path(json.loads(contract.read_text())["human_gt_inbox"])
    inbox.mkdir()
    (inbox / "primary-cvat-export.zip").write_bytes(b"not-yet-validated")
    (inbox / "double-review-cvat-export.zip").write_bytes(b"not-yet-validated")

    result = _run("--contract", str(contract), "--verify-only")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["human_export_state"] == "PRESENT_UNVALIDATED"
    assert payload["human_gt_validated"] is False


def test_verify_only_fails_closed_when_a_frozen_zip_drifts(tmp_path: Path) -> None:
    contract = _fixture_contract(tmp_path)
    primary = Path(json.loads(contract.read_text())["primary_zip"])
    primary.write_bytes(primary.read_bytes() + b"drift")

    result = _run("--contract", str(contract), "--verify-only")

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "SUPERVISOR_FAIL_CLOSED"
    assert payload["reason"] == "primary_zip_sha256_mismatch"


def test_print_command_allows_read_tools_but_never_bypasses_permissions(
    tmp_path: Path,
) -> None:
    contract = _fixture_contract(tmp_path)

    result = _run(
        "--contract",
        str(contract),
        "--print-claude-command",
        "--claude-executable",
        "/opt/claude",
    )

    assert result.returncode == 0, result.stderr
    command = json.loads(result.stdout)["command"]
    assert command[0] == "/opt/claude"
    assert command[command.index("--allowedTools") + 1] == "Read,Glob,Grep"
    assert command[command.index("--permission-mode") + 1] == "dontAsk"
    assert "--safe-mode" in command
    assert "--no-chrome" in command
    assert "--dangerously-skip-permissions" not in command
    assert "--allow-dangerously-skip-permissions" not in command


def test_print_command_adds_repo_as_read_directory_not_as_prompt_argument(
    tmp_path: Path,
) -> None:
    contract = _fixture_contract(tmp_path)
    contract_payload = json.loads(contract.read_text())

    result = _run("--contract", str(contract), "--print-claude-command")

    assert result.returncode == 0, result.stderr
    command = json.loads(result.stdout)["command"]
    add_dir = command.index("--add-dir")
    assert command[add_dir + 1 : add_dir + 3] == [
        str(tmp_path.resolve()),
        str(Path(contract_payload["attempt_root"]).resolve()),
    ]
    assert "--" not in command
