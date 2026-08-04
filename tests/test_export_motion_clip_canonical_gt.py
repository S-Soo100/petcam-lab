from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import scripts.export_motion_clip_canonical_gt as export_module
from scripts.export_motion_clip_canonical_gt import export_canonical_gt, main

CLIP_ID = '10000000-0000-4000-8000-000000000001'
REVISION_ID = '20000000-0000-4000-8000-000000000001'
HEAD_DIGEST = hashlib.sha256(f'{CLIP_ID}|{REVISION_ID}'.encode()).hexdigest()


class Result:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, rows):
        self.rows = rows
        self.ids: set[str] | None = None
        self.bounds: tuple[int, int] | None = None
        self.after: str | None = None
        self.max_rows: int | None = None

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

    def gt(self, _field: str, value: str):
        self.after = value
        return self

    def limit(self, value: int):
        self.max_rows = value
        return self

    def execute(self):
        rows = self.rows
        if self.ids is not None:
            rows = [row for row in rows if row['id'] in self.ids]
        if self.after is not None:
            rows = [row for row in rows if row['clip_id'] > self.after]
        if self.max_rows is not None:
            rows = rows[:self.max_rows]
        if self.bounds is not None:
            start, end = self.bounds
            rows = rows[start:end + 1]
        return Result(rows)


class Client:
    def __init__(self):
        self.rows = {
            'motion_clip_canonical_gt_export': [{
                'clip_id': CLIP_ID,
                'revision_id': REVISION_ID,
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
        assert name == 'fn_get_motion_clip_canonical_gt_export_snapshot'
        return Query([{
            'head_count': 1,
            'head_digest': HEAD_DIGEST,
            'source_mutation_digest': 'a' * 64,
        }])


class ChangingSnapshotClient(Client):
    def __init__(self):
        super().__init__()
        self.snapshot_calls = 0

    def rpc(self, name: str, params: dict[str, object]):
        query = super().rpc(name, params)
        self.snapshot_calls += 1
        if self.snapshot_calls == 2:
            query.rows[0]['head_digest'] = 'b' * 64
        return query


def test_export_writes_versioned_jsonl_and_manifest_without_sensitive_fields(tmp_path: Path) -> None:
    result = export_canonical_gt(
        Client(),
        tmp_path,
        generated_at='2026-08-04T01:02:03Z',
    )
    record = json.loads(result.data_path.read_text(encoding='utf-8').strip())
    assert record == {
        'clip_id': CLIP_ID,
        'revision_id': REVISION_ID,
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
    assert manifest['canonical_head_digest'] == HEAD_DIGEST
    assert manifest['generated_at'] == '2026-08-04T01:02:03Z'
    assert manifest['record_count'] == 1


def test_cli_requires_explicit_canonical_source(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(['--output-dir', str(tmp_path)], client_factory=Client)


def test_export_aborts_when_head_snapshot_changes(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match='canonical_export_snapshot_changed'):
        export_canonical_gt(ChangingSnapshotClient(), tmp_path)
    assert list(tmp_path.glob('*')) == []


def test_manifest_is_completion_marker_when_publish_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = tmp_path / 'manifest.json'
    manifest.write_text('{"old":true}\n', encoding='utf-8')
    original = export_module._atomic_write_text

    def fail_manifest(path: Path, text: str) -> None:
        if path.name == 'manifest.json':
            raise OSError('disk full')
        original(path, text)

    monkeypatch.setattr(export_module, '_atomic_write_text', fail_manifest)
    with pytest.raises(OSError, match='disk full'):
        export_canonical_gt(Client(), tmp_path)
    assert manifest.read_text(encoding='utf-8') == '{"old":true}\n'
    assert list(tmp_path.glob('*.tmp')) == []
