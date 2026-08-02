from pathlib import Path
import plistlib

from scripts.manage_local_vlm_clip_shadow_launchd import LaunchConfig
from scripts.manage_local_vlm_clip_shadow_launchd_v2 import END_AT, LABEL, exact_plist_path, render_plist


def test_v2_plist_targets_only_v2_runner_and_label(tmp_path: Path) -> None:
    config = LaunchConfig(
        repo_root=tmp_path / "repo", python=tmp_path / "python",
        env_file=tmp_path / "env", salt_file=tmp_path / "salt",
        output_dir=tmp_path / "run", expected_host="host", expected_head="a" * 40,
    )
    payload = plistlib.loads(render_plist(config))
    assert payload["Label"] == LABEL == "com.petcam.local-vlm-clip-shadow-canary-v2"
    assert str(config.repo_root / "scripts" / "run_local_vlm_clip_shadow_v2.py") in payload["ProgramArguments"]
    assert END_AT in payload["ProgramArguments"]
    assert payload["RunAtLoad"] is False and payload["KeepAlive"] is False
    assert exact_plist_path(tmp_path).name == f"{LABEL}.plist"
