from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from scripts.run_rba_openai_smoke import run_smoke
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
        source_head="a" * 40,
    )

    assert report["status"] == "complete"
    assert report["clip_count"] == 3
    assert report["complete_clips"] == 3
    assert report["request_count"] == 3
    assert report["execution_hostname"] == "mac-mini-test"
    assert report["source_head"] == "a" * 40
    assert all(clip["decoded_frames"] == 4 for clip in report["clips"])
    assert seen_keys == ["secret-value-not-for-output"]
    stored = (tmp_path / "runtime" / "smoke-report.json").read_text()
    assert "secret-value-not-for-output" not in stored
    assert (tmp_path / "runtime" / "smoke-report.json").stat().st_mode & 0o777 == 0o600
