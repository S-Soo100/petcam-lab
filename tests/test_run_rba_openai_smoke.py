from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from scripts.run_rba_openai_smoke import SmokeContractError, run_smoke
from scripts.run_rba_openai_vlm import VlmWindowPrediction


def _video(path: Path, value: int) -> str:
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), 4.0, (64, 48)
    )
    assert writer.isOpened()
    try:
        for _ in range(4):
            writer.write(np.full((48, 64, 3), value, dtype=np.uint8))
    finally:
        writer.release()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_repo(
    path: Path, *, match_runtime_scripts: bool = True
) -> tuple[Path, dict[str, str]]:
    repo = path / "source-repo"
    runtime_scripts = [
        "scripts/rba_python_prescan.py",
        "scripts/rba_openai_frame_policy.py",
        "scripts/rba_openai_clip_aggregate.py",
        "scripts/run_rba_openai_vlm.py",
        "scripts/run_rba_openai_smoke.py",
    ]
    expected_hashes: dict[str, str] = {}
    for relative in runtime_scripts:
        script = repo / relative
        script.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            (Path(__file__).resolve().parents[1] / relative).read_bytes()
            if match_runtime_scripts
            else f"# unrelated {relative}\n".encode()
        )
        script.write_bytes(payload)
        expected_hashes[relative] = hashlib.sha256(payload).hexdigest()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test User"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repo), "add", "--", *runtime_scripts], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "test fixture"], check=True
    )
    return repo, expected_hashes


def test_run_smoke_processes_exact_three_clips_without_exposing_key(
    tmp_path: Path,
) -> None:
    clips = []
    for index, value in enumerate((20, 80, 160)):
        path = tmp_path / f"clip-{index}.mp4"
        digest = _video(path, value)
        clips.append(
            {
                "clip_ref": f"smoke-{index}",
                "media_path": str(path),
                "media_sha256": digest,
            }
        )
    manifest = tmp_path / "smoke-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "rba-openai-smoke-manifest-v1",
                "clip_count": 3,
                "clips": clips,
            }
        )
    )
    secret = tmp_path / "openai.env"
    secret.write_text("OPENAI_API_KEY=secret-value-not-for-output\n")
    secret.chmod(0o600)
    prediction = VlmWindowPrediction(
        primary_action="resting",
        observed_actions=["resting"],
        segments=[],
        max_visible_gecko_count="1",
        count_evidence_timestamps=[0.0],
        visibility="visible",
        occlusion="none",
        quality_flags=[],
        uncertainty="low",
        user_summary="게코가 쉬고 있어.",
    )
    seen_keys: list[str] = []
    request_count = 0
    source_repo, expected_script_hashes = _source_repo(tmp_path)
    source_head = subprocess.check_output(
        ["git", "-C", str(source_repo), "rev-parse", "HEAD"], text=True
    ).strip()

    class FakeResponses:
        def parse(self, **_: object) -> object:
            nonlocal request_count
            request_count += 1
            return SimpleNamespace(
                id=f"resp-{request_count}",
                output_parsed=prediction,
                usage=SimpleNamespace(input_tokens=100, output_tokens=20),
            )

    def client_factory(key: str) -> object:
        seen_keys.append(key)
        return SimpleNamespace(responses=FakeResponses())

    report = run_smoke(
        smoke_manifest=manifest,
        runtime_root=tmp_path / "runtime",
        secret_env=secret,
        client_factory=client_factory,
        max_run_usd=5.0,
        execution_hostname="mac-mini-test",
        source_repo=source_repo,
    )

    assert report["status"] == "complete"
    assert report["clip_count"] == 3
    assert report["complete_clips"] == 3
    assert report["request_count"] == 3
    assert report["execution_hostname"] == "mac-mini-test"
    assert report["source_head"] == source_head
    assert report["runtime_script_sha256"] == expected_script_hashes
    assert all(clip["decoded_frames"] == 4 for clip in report["clips"])
    assert seen_keys == ["secret-value-not-for-output"]
    stored = (tmp_path / "runtime" / "smoke-report.json").read_text()
    assert "secret-value-not-for-output" not in stored
    assert str(source_repo) not in stored
    assert all(str(path) not in stored for path in tmp_path.glob("clip-*.mp4"))
    assert (tmp_path / "runtime" / "smoke-report.json").stat().st_mode & 0o777 == 0o600


def test_run_smoke_rejects_dirty_source_before_client_invocation(tmp_path: Path) -> None:
    source_repo, _ = _source_repo(tmp_path)
    (source_repo / "scripts" / "run_rba_openai_vlm.py").write_text("# dirty\n")
    client_calls = 0

    def client_factory(_: str) -> object:
        nonlocal client_calls
        client_calls += 1
        raise AssertionError("dirty provenance must block before client creation")

    with pytest.raises(SmokeContractError, match="source_repo_dirty"):
        run_smoke(
            smoke_manifest=tmp_path / "not-read.json",
            runtime_root=tmp_path / "runtime",
            secret_env=tmp_path / "not-read.env",
            client_factory=client_factory,
            execution_hostname="mac-mini-test",
            source_repo=source_repo,
        )

    assert client_calls == 0
    assert not (tmp_path / "runtime").exists()


def test_run_smoke_rejects_clean_repo_with_unrelated_runtime_bytes(
    tmp_path: Path,
) -> None:
    source_repo, _ = _source_repo(tmp_path, match_runtime_scripts=False)
    client_calls = 0

    def client_factory(_: str) -> object:
        nonlocal client_calls
        client_calls += 1
        raise AssertionError("unrelated source must block before client creation")

    with pytest.raises(SmokeContractError, match="runtime_source_mismatch"):
        run_smoke(
            smoke_manifest=tmp_path / "not-read.json",
            runtime_root=tmp_path / "runtime",
            secret_env=tmp_path / "not-read.env",
            client_factory=client_factory,
            execution_hostname="mac-mini-test",
            source_repo=source_repo,
        )

    assert client_calls == 0
    assert not (tmp_path / "runtime").exists()
