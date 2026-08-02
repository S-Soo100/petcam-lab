import json
from pathlib import Path

import pytest

from scripts.recompute_local_vlm_purchase_gate import RecomputeError, recompute


def test_recompute_rejects_missing_terminal_records(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    results = tmp_path / "results.jsonl"
    manifest.write_text(json.dumps({"models": {"m": {"available": True}}, "synthetic": [], "development": []}))
    results.write_text("")
    with pytest.raises(RecomputeError, match="terminal"):
        recompute(manifest, results)
