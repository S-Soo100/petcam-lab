from __future__ import annotations

import json

from scripts.audit_motion_clip_canonical_gt_rollout import main


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeCall:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return FakeResult(self.data)


class FakeClient:
    def __init__(self, values: dict[str, object]):
        self.values = values

    def rpc(self, name: str, _params: dict[str, object]):
        return FakeCall(self.values[name])


AUDIT = {
    "source_counts": {"live_final": 277, "direct_completed": 216},
    "canonical_counts": {"revisions": 0, "heads": 0},
    "excluded_counts": {"live_awaiting": 20585, "live_conflict": 0, "canary": 42},
    "overlap_count": 2,
    "reconciliation_pending": 0,
    "orphan_head_count": 0,
    "source_mutation_digest": "abc123",
    "parity_mismatch_count": 0,
}
HEALTH = {
    "healthy": True,
    "last_success_at": "2026-08-04T00:00:00+00:00",
    "lag_seconds": 0,
    "pending_final_source_count": 0,
    "last_error_code": None,
}


def test_audit_prints_source_digest_only(capsys) -> None:
    client = FakeClient(
        {
            "fn_audit_motion_clip_canonical_gt": AUDIT,
            "fn_get_motion_clip_gt_projection_health": HEALTH,
        }
    )
    assert main(["--print-source-digest"], client_factory=lambda: client) == 0
    assert capsys.readouterr().out == "abc123\n"


def test_audit_rejects_source_digest_mismatch(capsys) -> None:
    client = FakeClient(
        {
            "fn_audit_motion_clip_canonical_gt": AUDIT,
            "fn_get_motion_clip_gt_projection_health": HEALTH,
        }
    )
    assert main(["--expected-source-digest", "different"], client_factory=lambda: client) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is False
    assert output["audit"]["source_mutation_digest"] == "abc123"


def test_audit_fails_on_orphan_head(capsys) -> None:
    client = FakeClient(
        {
            "fn_audit_motion_clip_canonical_gt": {**AUDIT, "orphan_head_count": 1},
            "fn_get_motion_clip_gt_projection_health": HEALTH,
        }
    )
    assert main([], client_factory=lambda: client) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
