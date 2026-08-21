from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

import scripts.run_rba_openai_smoke as smoke_module
from scripts.run_rba_openai_smoke import SmokeContractError, run_smoke
from scripts.run_rba_openai_vlm import VlmWindowPrediction


RUN_ID = "123e4567-e89b-42d3-a456-426614174000"


def _gme_run() -> dict[str, object]:
    return {
        "id": RUN_ID,
        "status": "ok",
        "candidate_moving_sec_any_gecko": 0.5,
        "visible_sec": 1.0,
        "max_simultaneous_geckos": 1,
        "state_intervals": [
            {
                "start_sec": 0.0,
                "end_sec": 0.5,
                "state": "moving",
                "track_ids": ["g1"],
            },
            {
                "start_sec": 0.5,
                "end_sec": 1.0,
                "state": "static",
                "track_ids": ["g1"],
            },
        ],
    }


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
        "scripts/rba_gme_activity.py",
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
    activity_metadata = [
        {
            "camera_ref": "camera-a",
            "activity_day": "2026-08-21",
            "started_at": "2026-08-21T03:00:00Z",
        },
        {
            "camera_ref": "camera-a",
            "activity_day": "2026-08-21",
            "started_at": "2026-08-21T03:00:00Z",
        },
        {
            "camera_ref": "camera-b",
            "activity_day": "2026-08-22",
            "started_at": "2026-08-22T03:00:00Z",
        },
    ]
    for index, value in enumerate((20, 80, 160)):
        path = tmp_path / f"clip-{index}.mp4"
        digest = _video(path, value)
        clips.append(
            {
                "clip_ref": f"smoke-{index}",
                "media_path": str(path),
                "media_sha256": digest,
                "gme_run": _gme_run(),
                **activity_metadata[index],
            }
        )
    clips.reverse()
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
    seen_inputs: list[object] = []
    request_count = 0
    source_repo, expected_script_hashes = _source_repo(tmp_path)
    source_head = subprocess.check_output(
        ["git", "-C", str(source_repo), "rev-parse", "HEAD"], text=True
    ).strip()

    class FakeResponses:
        input_tokens = SimpleNamespace(
            count=lambda **_: SimpleNamespace(input_tokens=1000)
        )

        def parse(self, **kwargs: object) -> object:
            nonlocal request_count
            request_count += 1
            seen_inputs.append(kwargs["input"])
            return SimpleNamespace(
                id=f"resp-{request_count}",
                output_parsed=prediction,
                service_tier="default",
                model="gpt-5.6-terra",
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
    assert all("moving" not in json.dumps(value).lower() for value in seen_inputs)
    for clip in clips:
        frame_manifest = json.loads(
            (
                tmp_path
                / "runtime"
                / str(clip["clip_ref"])
                / "arm-a-frames"
                / "frame-manifest.json"
            ).read_text()
        )
        assert frame_manifest["gme_activity"]["run_id"] == RUN_ID
        assert any(
            "gme-moving-dense" in row["source_policies"]
            for row in frame_manifest["frames"]
        )
    expected_priorities = {
        "smoke-0": {"camera_day_rank": 1, "camera_day_count": 2},
        "smoke-1": {"camera_day_rank": 2, "camera_day_count": 2},
        "smoke-2": {"camera_day_rank": 1, "camera_day_count": 1},
    }
    for clip_ref, priority in expected_priorities.items():
        aggregate = json.loads(
            (tmp_path / "runtime" / clip_ref / "aggregate.json").read_text()
        )
        assert aggregate["gme_activity"] == {
            "run_id": RUN_ID,
            "detected": True,
            "activity_sec": 0.5,
            "visible_sec": 1.0,
        }
        assert aggregate["highlight_activity_priority"] == priority
        serialized = json.dumps(aggregate).lower()
        assert all(term not in serialized for term in ("include", "skip", "gt"))
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


@pytest.mark.parametrize(
    ("invalid_kind", "error_code"),
    [
        ("missing", "gme_run_contract"),
        ("contradictory", "gme_run_contract"),
        ("malformed_activity_candidate", "activity_candidate_contract"),
    ],
)
def test_run_smoke_preflights_clip_three_before_client_or_artifact_creation(
    tmp_path: Path, invalid_kind: str, error_code: str
) -> None:
    clips = []
    for index, value in enumerate((20, 80, 160)):
        path = tmp_path / f"clip-{index}.mp4"
        clip = {
            "clip_ref": f"smoke-{index}",
            "media_path": str(path),
            "media_sha256": _video(path, value),
            "gme_run": _gme_run(),
            "camera_ref": "camera-a",
            "activity_day": "2026-08-21",
            "started_at": "2026-08-21T03:00:00Z",
        }
        clips.append(clip)
    if invalid_kind == "missing":
        clips[2].pop("gme_run")
    else:
        if invalid_kind == "contradictory":
            clips[2]["gme_run"]["candidate_moving_sec_any_gecko"] = 0.6
        else:
            clips[2]["started_at"] = "0001-01-01T00:00:00+23:59"
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
    source_repo, _ = _source_repo(tmp_path)
    client_calls = 0
    provider_calls = 0

    class FakeResponses:
        def parse(self, **_: object) -> object:
            nonlocal provider_calls
            provider_calls += 1
            raise AssertionError("invalid GME context must block provider invocation")

    def client_factory(_: str) -> object:
        nonlocal client_calls
        client_calls += 1
        return SimpleNamespace(responses=FakeResponses())

    with pytest.raises(SmokeContractError, match=error_code):
        run_smoke(
            smoke_manifest=manifest,
            runtime_root=tmp_path / "runtime",
            secret_env=secret,
            client_factory=client_factory,
            execution_hostname="mac-mini-test",
            source_repo=source_repo,
        )

    assert client_calls == 0
    assert provider_calls == 0
    assert not (tmp_path / "runtime").exists()


def test_run_smoke_rejects_media_swapped_after_complete_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clips = []
    for index, value in enumerate((20, 80, 160)):
        path = tmp_path / f"clip-{index}.mp4"
        clips.append(
            {
                "clip_ref": f"smoke-{index}",
                "media_path": str(path),
                "media_sha256": _video(path, value),
                "gme_run": _gme_run(),
                "camera_ref": "camera-a",
                "activity_day": "2026-08-21",
                "started_at": "2026-08-21T03:00:00Z",
            }
        )
    replacement = tmp_path / "replacement.mp4"
    _video(replacement, 240)
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
    source_repo, _ = _source_repo(tmp_path)
    real_scan_video = smoke_module.scan_video
    swapped = False

    def swap_before_artifact_scan(video_path: Path, **kwargs: object) -> object:
        nonlocal swapped
        if kwargs.get("summary_output") is not None and not swapped:
            video_path.write_bytes(replacement.read_bytes())
            swapped = True
        return real_scan_video(video_path, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(smoke_module, "scan_video", swap_before_artifact_scan)
    client_calls = 0
    provider_calls = 0

    class FakeResponses:
        def parse(self, **_: object) -> object:
            nonlocal provider_calls
            provider_calls += 1
            return SimpleNamespace(
                id=f"resp-{provider_calls}",
                output_parsed=VlmWindowPrediction(
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
                ),
                usage=SimpleNamespace(input_tokens=100, output_tokens=20),
            )

    def client_factory(_: str) -> object:
        nonlocal client_calls
        client_calls += 1
        return SimpleNamespace(responses=FakeResponses())

    runtime = tmp_path / "runtime"
    with pytest.raises(SmokeContractError, match="smoke_media_drift"):
        run_smoke(
            smoke_manifest=manifest,
            runtime_root=runtime,
            secret_env=secret,
            client_factory=client_factory,
            execution_hostname="mac-mini-test",
            source_repo=source_repo,
        )

    assert swapped is True
    assert client_calls == 0
    assert provider_calls == 0
    assert not (runtime / "smoke-report.json").exists()
    assert not list(runtime.glob("*/aggregate.json"))
