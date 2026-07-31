import hashlib
from types import SimpleNamespace

import pytest

from scripts.seed_rba_boundary_review import SeedError, build_seed_payload, resolve_reviewers


OWNER_ID = "00000000-0000-4000-8000-000000000001"
PEER_ID = "00000000-0000-4000-8000-000000000002"


class Query:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def select(self, _columns: str) -> "Query":
        return self

    def in_(self, column: str, values: list[str]) -> "Query":
        self.rows = [row for row in self.rows if row.get(column) in values]
        return self

    def eq(self, column: str, value: str) -> "Query":
        self.rows = [row for row in self.rows if row.get(column) == value]
        return self

    def limit(self, count: int) -> "Query":
        self.rows = self.rows[:count]
        return self

    def execute(self) -> SimpleNamespace:
        return SimpleNamespace(data=self.rows)


class Client:
    def __init__(self, applications: list[dict], labelers: list[dict], auth_users: list[SimpleNamespace]) -> None:
        self.rows = {"labeler_applications": applications, "labelers": labelers}
        self.auth = SimpleNamespace(admin=SimpleNamespace(list_users=lambda **_kwargs: auth_users))

    def table(self, name: str) -> Query:
        return Query(list(self.rows[name]))


def manifest() -> dict:
    rows = []
    for i in range(120):
        def uid(n: int) -> str:
            return f"{n:08x}-0000-4000-8000-{n:012x}"
        rows.append({
            "left_clip_id": uid(i * 2 + 1),
            "right_clip_id": uid(i * 2 + 2),
            "pair_id": hashlib.sha256(f"pair-{i}".encode()).hexdigest(),
            "gap_sec": 30.0,
            "gap_bin": "le30",
        })
    return {
        "schema_version": "rba-event-boundary-manifest-v2",
        "experiment_id": "probe",
        "manifest_sha256": "a" * 64,
        "media_preflight": {"verified_count": 240},
        "splits": {"development": rows[:60], "holdout": rows[60:]},
    }


def test_builds_exact_private_seed_payload() -> None:
    payload = build_seed_payload(manifest())
    assert len(payload["pairs"]) == 120
    assert payload["pairs"][0]["ordinal"] == 1
    assert payload["pairs"][60]["split"] == "holdout"
    assert len(payload["payload_digest"]) == 64


@pytest.mark.parametrize("mutation", ["preflight", "split", "reuse"])
def test_fails_closed_on_invalid_manifest(mutation: str) -> None:
    data = manifest()
    if mutation == "preflight":
        data["media_preflight"]["verified_count"] = 239
    elif mutation == "split":
        data["splits"]["development"].pop()
    else:
        data["splits"]["development"][1]["left_clip_id"] = data["splits"]["development"][0]["left_clip_id"]
    with pytest.raises(SeedError):
        build_seed_payload(data)


def test_resolves_owner_from_auth_when_owner_has_no_application(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEV_USER_ID", raising=False)
    client = Client(
        applications=[{"user_id": PEER_ID, "email": "peer@example.com", "status": "approved"}],
        labelers=[{"user_id": PEER_ID}],
        auth_users=[SimpleNamespace(id=OWNER_ID, email="owner@example.com")],
    )

    assert resolve_reviewers(client, "owner@example.com", "peer@example.com") == (OWNER_ID, PEER_ID)


def test_owner_auth_identity_must_match_configured_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_USER_ID", "00000000-0000-4000-8000-000000000099")
    client = Client(
        applications=[{"user_id": PEER_ID, "email": "peer@example.com", "status": "approved"}],
        labelers=[{"user_id": PEER_ID}],
        auth_users=[SimpleNamespace(id=OWNER_ID, email="owner@example.com")],
    )

    with pytest.raises(SeedError, match="owner_identity_mismatch"):
        resolve_reviewers(client, "owner@example.com", "peer@example.com")
