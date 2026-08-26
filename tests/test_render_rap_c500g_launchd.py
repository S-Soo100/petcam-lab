import plistlib
from pathlib import Path

from scripts.render_rap_c500g_launchd import render_plist


def test_rendered_plist_runs_module_without_embedding_env_secrets(tmp_path: Path) -> None:
    repo = tmp_path / "petcam-lab"
    log_dir = tmp_path / "logs"
    payload = plistlib.loads(render_plist(repo=repo, log_dir=log_dir))
    encoded = str(payload)

    assert payload["Label"] == "com.teraai.rap-c500g-recorder"
    assert payload["WorkingDirectory"] == str(repo)
    assert payload["ProgramArguments"] == [
        "/usr/bin/env", "uv", "run", "python", "-m", "backend.rap_c500g_main", "run"
    ]
    assert payload["KeepAlive"] is True
    assert "PASSWORD" not in encoded
    assert "RTSP" not in encoded
    assert "R2_SECRET" not in encoded
