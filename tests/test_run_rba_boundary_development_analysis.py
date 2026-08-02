from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.rba_boundary_development_analysis import StudySnapshot
from scripts.run_rba_boundary_development_analysis import (
    ALLOWED_SELECTS,
    RunnerSafetyError,
    analyze_three_passes,
    create_private_output,
    require_env_file_0600,
    write_new_file,
)


def test_runner_source_has_no_rpc_or_mutation_calls() -> None:
    source = Path("scripts/run_rba_boundary_development_analysis.py").read_text().lower()
    forbidden = (
        ".rpc(",
        ".insert(",
        ".update(",
        ".upsert(",
        ".delete(",
        "reason,",
        "behavior_labels",
        "clip_python_evidence",
        "clip_vlm_jobs",
        "boto3",
    )
    assert not [token for token in forbidden if token in source]
    assert set(ALLOWED_SELECTS) == {
        "rba_boundary_review_cohorts",
        "rba_boundary_review_pairs",
        "rba_boundary_review_assignments",
        "rba_boundary_review_submissions",
        "rba_boundary_review_resolutions",
    }


def test_runner_can_be_executed_directly_from_repo_root() -> None:
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(repo / "scripts/run_rba_boundary_development_analysis.py"), "--help"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_runner_requires_env_file_mode_0600(tmp_path: Path) -> None:
    env_file = tmp_path / "runtime.env"
    env_file.write_text("SUPABASE_URL=x\nSUPABASE_SERVICE_ROLE_KEY=y\n", encoding="utf-8")
    env_file.chmod(0o644)
    with pytest.raises(RunnerSafetyError, match="env_file_mode"):
        require_env_file_0600(env_file)
    env_file.chmod(0o600)
    require_env_file_0600(env_file)


def test_runner_refuses_existing_output_directory(tmp_path: Path) -> None:
    output = tmp_path / "private"
    output.mkdir()
    with pytest.raises(RunnerSafetyError, match="output_exists"):
        create_private_output(output)


def test_private_writer_is_0700_0600_and_no_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "private"
    create_private_output(output)
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    target = output / "artifact.json"
    write_new_file(target, b"{}\n", mode=0o600)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    with pytest.raises(RunnerSafetyError, match="already_exists"):
        write_new_file(target, b"changed", mode=0o600)


def test_three_pass_requires_identical_hashes(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = StudySnapshot(
        experiment_id="x",
        manifest_digest="y",
        total_pair_count=0,
        effective_pairs=(),
        assignments=(),
        submissions=(),
        resolutions=(),
    )
    calls = []

    def stable(snapshot_arg: StudySnapshot, manifest_arg: dict[str, object], salt: bytes):
        calls.append(snapshot_arg)
        return SimpleNamespace(private_payload_sha256="a", public_report_sha256="b")

    monkeypatch.setattr(
        "scripts.run_rba_boundary_development_analysis.analyze_study",
        stable,
    )
    result = analyze_three_passes(snapshot, {}, b"salt")
    assert result.private_payload_sha256 == "a"
    assert len(calls) == 3

    hashes = iter(("a", "a", "different"))

    def unstable(snapshot_arg: StudySnapshot, manifest_arg: dict[str, object], salt: bytes):
        return SimpleNamespace(
            private_payload_sha256=next(hashes),
            public_report_sha256="b",
        )

    monkeypatch.setattr(
        "scripts.run_rba_boundary_development_analysis.analyze_study",
        unstable,
    )
    with pytest.raises(RunnerSafetyError, match="three_pass_mismatch"):
        analyze_three_passes(snapshot, {}, b"salt")


def test_allowed_columns_exclude_reasons_and_source_media() -> None:
    joined = " ".join(ALLOWED_SELECTS.values()).lower()
    for forbidden in ("reason", "left_clip_id", "right_clip_id", "camera_id", "r2_key"):
        assert forbidden not in joined
    assert ALLOWED_SELECTS["rba_boundary_review_submissions"] == (
        "assignment_id,pair_id,reviewer_id,decision,digest,submitted_at"
    )
