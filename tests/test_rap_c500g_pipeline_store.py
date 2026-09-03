from __future__ import annotations

from pathlib import Path

import pytest

from backend.rap_c500g_manager_store import ManagerStore
from backend.rap_c500g_pipeline_types import PipelineItem, PipelineState


SLOT = "2026-09-03T20:00:00+09:00"


def item(*, state: PipelineState = PipelineState.CAPTURED) -> PipelineItem:
    return PipelineItem(
        slot_start=SLOT,
        camera_key="cam01",
        state=state,
        root="RAP-C500G/2026-09-03/cam01/20-00-00",
        payload={"relative_dir": "2026-09-03/cam01/20-00-00"},
    )


def test_pipeline_item_survives_restart_and_advances_monotonically(tmp_path: Path) -> None:
    path = tmp_path / "manager.sqlite3"
    first = ManagerStore(path)
    first.upsert_pipeline_item(item())
    first.complete_pipeline_stage(SLOT, "cam01", PipelineState.RAW_UPLOADED)

    reopened = ManagerStore(path)
    rows = reopened.list_pipeline_items(states=(PipelineState.RAW_UPLOADED,))

    assert [(row.slot_start, row.camera_key, row.state) for row in rows] == [
        (SLOT, "cam01", PipelineState.RAW_UPLOADED)
    ]
    with pytest.raises(ValueError, match="transition"):
        reopened.complete_pipeline_stage(SLOT, "cam01", PipelineState.CAPTURED)


def test_pipeline_stage_claim_is_atomic_and_releasable(tmp_path: Path) -> None:
    store = ManagerStore(tmp_path / "manager.sqlite3")
    store.upsert_pipeline_item(item())

    assert store.claim_pipeline_stage(
        SLOT, "cam01", stage="raw_upload", states=(PipelineState.CAPTURED,)
    ) is True
    assert store.claim_pipeline_stage(
        SLOT, "cam01", stage="raw_upload", states=(PipelineState.CAPTURED,)
    ) is False

    assert store.release_pipeline_claim(SLOT, "cam01", stage="raw_upload") is True


@pytest.mark.parametrize(
    "payload",
    [
        {"url": "rtsp://user:secret@camera/live"},
        {"password": "secret"},
        {"nested": {"access_token": "secret"}},
    ],
)
def test_pipeline_payload_rejects_secrets(tmp_path: Path, payload: dict[str, object]) -> None:
    store = ManagerStore(tmp_path / "manager.sqlite3")

    with pytest.raises(ValueError, match="secret"):
        store.upsert_pipeline_item(
            PipelineItem(
                slot_start=SLOT,
                camera_key="cam01",
                state=PipelineState.CAPTURED,
                root="safe/relative/root",
                payload=payload,
            )
        )
