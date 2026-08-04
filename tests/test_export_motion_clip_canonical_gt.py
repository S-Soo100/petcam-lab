from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.export_motion_clip_canonical_gt import export_canonical_gt, main


class Result:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, rows):
        self.rows = rows
        self.ids: set[str] | None = None
        self.bounds: tuple[int, int] | None = None

    def select(self, _fields: str):
        return self

    def order(self, field: str):
        self.rows = sorted(self.rows, key=lambda row: row[field])
        return self

    def range(self, start: int, end: int):
        self.bounds = (start, end)
        return self

    def in_(self, _field: str, values: list[str]):
        self.ids = set(values)
        return self

    def execute(self):
        rows = self.rows
        if self.ids is not None:
            rows = [row for row in rows if row['id'] in self.ids]
        if self.bounds is not None:
            start, end = self.bounds
            rows = rows[start:end + 1]
        return Result(rows)


class Client:
    def __init__(self):
        self.rows = {
            'motion_clip_canonical_gt_export': [{
                'clip_id': '10000000-0000-4000-8000-000000000001',
                'revision_id': '20000000-0000-4000-8000-000000000001',
                'updated_at': '2026-08-04T00:00:00Z',
                'final_decision': 'label',
                'gt': {'primary_action': 'moving'},
                'source_type': 'blind_consensus',
                'source_version': 'motion-blind-v1',
                'created_at': '2026-08-04T00:00:00Z',
                'actor_id': 'must-not-export',
                'source_id': 'must-not-export',
            }],
        }

    def table(self, name: str):
        return Query(list(self.rows[name]))

    def rpc(self, name: str, _params: dict[str, object]):
        assert name == 'fn_audit_motion_clip_canonical_gt'
        return Query([{'source_mutation_digest': 'a' * 64}])


def test_export_writes_versioned_jsonl_and_manifest_without_sensitive_fields(tmp_path: Path) -> None:
    result = export_canonical_gt(
        Client(),
        tmp_path,
        generated_at='2026-08-04T01:02:03Z',
    )
    record = json.loads(result.data_path.read_text(encoding='utf-8').strip())
    assert record == {
        'clip_id': '10000000-0000-4000-8000-000000000001',
        'revision_id': '20000000-0000-4000-8000-000000000001',
        'decision': 'label',
        'gt': {'primary_action': 'moving'},
        'provenance': {
            'source_type': 'blind_consensus',
            'source_version': 'motion-blind-v1',
        },
    }
    raw = result.data_path.read_text(encoding='utf-8')
    assert 'actor_id' not in raw
    assert 'source_id' not in raw
    manifest = json.loads(result.manifest_path.read_text(encoding='utf-8'))
    assert manifest['schema_version'] == 'motion-clip-canonical-gt-v1'
    assert manifest['source_snapshot_digest'] == 'a' * 64
    assert manifest['generated_at'] == '2026-08-04T01:02:03Z'
    assert manifest['record_count'] == 1


def test_cli_requires_explicit_canonical_source(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(['--output-dir', str(tmp_path)], client_factory=Client)
