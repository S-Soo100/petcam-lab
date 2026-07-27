import os
import subprocess
from pathlib import Path


SCRIPT = Path("scripts/install_research_runtime_launchd.sh")


def test_installer_requires_expected_host_before_writing(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.update(
        HOME=str(tmp_path),
        RESEARCH_CHECKOUT=str(tmp_path / "checkout"),
        RESEARCH_RUNTIME_ROOT=str(tmp_path / "runtime"),
    )
    result = subprocess.run(
        ("bash", str(SCRIPT)),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert not (tmp_path / "Library/LaunchAgents/com.petcam.research-runtime.plist").exists()


def test_installer_contract_is_fail_closed_and_delete_free() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'RESEARCH_EXPECTED_HOST:-' in text
    assert 'RESEARCH_EXPECTED_HEAD:-' in text
    assert 'status --porcelain --untracked-files=all' in text
    assert "/usr/bin/caffeinate" in text
    assert "<string>-dimsu</string>" in text
    assert "<key>StartInterval</key>" in text
    assert "<integer>60</integer>" in text
    assert "plutil -lint" in text
    assert "launchctl bootstrap" in text
    assert "launchctl bootout" in text
    assert "rm -rf" not in text
    assert "R2" not in text
