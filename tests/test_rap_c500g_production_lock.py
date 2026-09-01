from __future__ import annotations

from pathlib import Path

import pytest

from backend.rap_c500g_production_lock import ProductionLockError, production_lock


def test_only_one_production_owner_can_hold_lock(tmp_path: Path) -> None:
    path = tmp_path / "production.lock"

    with production_lock(path):
        with pytest.raises(ProductionLockError):
            with production_lock(path):
                pass

    with production_lock(path):
        pass
