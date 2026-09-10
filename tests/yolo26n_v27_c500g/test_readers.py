"""실제 원천 어댑터 — DB(supabase) production 행만·페이지 합치기, R2 는 boto3 client 그대로(읽기 verb 만 노출)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.yolo26n_v27_c500g.readers import ProductionDbReader, ReadOnlyR2


class _FakeQuery:
    def __init__(self, table, columns):
        self.table, self.columns, self.filters, self.window = table, columns, [], None

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def range(self, start, end):
        self.window = (start, end)
        return self

    def execute(self):
        rows = [r for r in self.table.rows if all(r.get(c) == v for c, v in self.filters)]
        if self.window is not None:
            start, end = self.window
            rows = rows[start:end + 1]
        self.table.calls.append((self.columns, list(self.filters), self.window))
        return SimpleNamespace(data=rows)


class _FakeTable:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def select(self, columns):
        return _FakeQuery(self, columns)

    def insert(self, *_a, **_k):  # 쓰기 verb 가 있어도 reader 가 노출하면 안 됨
        raise AssertionError("must not be called")


def test_db_reader_filters_production_and_merges_pages():
    rows = [{"bundle_id": f"rap-{i:02d}", "mode": "production" if i % 3 else "test"} for i in range(7)]
    reader = ProductionDbReader(_FakeTable(rows), page_size=2)
    data = reader.select("bundle_id,mode").execute().data
    assert [r["bundle_id"] for r in data] == ["rap-01", "rap-02", "rap-04", "rap-05"]
    assert all(r["mode"] == "production" for r in data)
    table_calls = reader.table.calls
    assert all(("mode", "production") in f for _, f, _ in table_calls)
    assert [w for _, _, w in table_calls] == [(0, 1), (2, 3), (4, 5)]  # 마지막 페이지가 꽉 차지 않아 종료


def test_db_reader_has_no_write_verbs():
    reader = ProductionDbReader(_FakeTable([]), page_size=10)
    for verb in ("insert", "upsert", "update", "delete"):
        with pytest.raises(AttributeError):
            getattr(reader, verb)


class _FakeClient:
    def __init__(self):
        self.calls = []

    def list_objects_v2(self, **kw):
        self.calls.append(("list", kw))
        return {"Contents": [], "IsTruncated": False, "KeyCount": 0}

    def head_object(self, **kw):
        self.calls.append(("head", kw))
        return {"ContentLength": 1, "Metadata": {}}

    def put_object(self, **kw):
        raise AssertionError("must not be reachable")


def test_read_only_r2_exposes_only_list_and_head_with_bucket_pinned():
    r2 = ReadOnlyR2(_FakeClient(), bucket="c500g")
    r2.list_objects_v2(Prefix="recordings/")
    r2.head_object(Key="recordings/x/video.mp4")
    assert r2.client.calls == [("list", {"Bucket": "c500g", "Prefix": "recordings/"}), ("head", {"Bucket": "c500g", "Key": "recordings/x/video.mp4"})]
    for verb in ("put_object", "upload_file", "delete_object"):
        with pytest.raises(AttributeError):
            getattr(r2, verb)
