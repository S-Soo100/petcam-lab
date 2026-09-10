"""실제 원천 read-only 어댑터. inventory 의 `R2Reader`/`DbReader` Protocol 을 만족하되 쓰기 verb 는 아예 노출하지 않는다.

- ProductionDbReader: supabase table 에서 `mode='production'` 행만, 페이지(기본 1000)를 합쳐 한 응답으로 돌려준다
  (PostgREST 기본 max-rows 1000 을 넘는 날을 대비).
- ReadOnlyR2: boto3 client 를 감싸 `list_objects_v2`/`head_object` 만 노출하고 Bucket 을 고정한다.
"""
from __future__ import annotations

from types import SimpleNamespace


class ProductionDbReader:
    def __init__(self, table, *, page_size: int = 1000) -> None:
        if page_size < 1:
            raise ValueError("page_size must be positive")
        self.table = table
        self.page_size = page_size

    def select(self, columns: str) -> "ProductionDbReader._Query":
        return ProductionDbReader._Query(self, columns)

    class _Query:
        def __init__(self, reader: "ProductionDbReader", columns: str) -> None:
            self.reader, self.columns = reader, columns

        def execute(self) -> SimpleNamespace:
            rows: list[dict[str, object]] = []
            start = 0
            size = self.reader.page_size
            while True:
                page = (
                    self.reader.table.select(self.columns)
                    .eq("mode", "production")
                    .range(start, start + size - 1)
                    .execute()
                    .data
                )
                rows.extend(page)
                if len(page) < size:
                    break
                start += size
            return SimpleNamespace(data=rows)


class ReadOnlyR2:
    def __init__(self, client, *, bucket: str) -> None:
        if not bucket:
            raise ValueError("bucket is required")
        self.client = client
        self.bucket = bucket

    def list_objects_v2(self, **kwargs: object) -> dict[str, object]:
        return self.client.list_objects_v2(Bucket=self.bucket, **kwargs)

    def head_object(self, **kwargs: object) -> dict[str, object]:
        return self.client.head_object(Bucket=self.bucket, **kwargs)
