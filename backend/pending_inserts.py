"""
Supabase INSERT 재시도 큐 (JSONL 파일 기반).

## 왜 파일 기반인가?
- 프로세스 크래시해도 대기열 손실 없음
- Redis / RabbitMQ 등 별도 인프라 필요 없음 (초기 단계엔 과잉)
- 단일 프로세스 + 단일 워커 전제라 동시성 경합 거의 없음

## 왜 JSONL?
- 한 줄 = 한 이벤트. append-only 쓰기 단순
- 중간 줄이 손상돼도 다른 줄은 살아있음
- `tail` / `cat` 으로 디버깅 쉬움

## 최대 라인 제한
- 무한 증가 방지. 1000 라인 ≈ 16.7 시간 분량 (1분 세그먼트 기준).
- 초과 시 가장 오래된 라인부터 drop.

## 스레드 안전성
- `enqueue` 는 캡처 워커 스레드에서, `flush` 는 주기 태스크에서 호출될 수 있음.
- 내부 `threading.Lock` 으로 파일 I/O 직렬화.

## Node 비유
Redis `lpush`/`rpoplpush` 기반 지연 큐의 최소 버전. 여기선 브로커 대신 파일.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_QUEUE_LINES = 1000


class PendingInsertQueue:
    """
    Supabase `camera_clips` INSERT 실패 건을 JSONL 파일에 누적·재전송하는 큐.

    사용 예:
        queue = PendingInsertQueue(Path("storage/pending_inserts.jsonl"))
        queue.enqueue({"user_id": "...", ...})
        success, remaining = queue.flush(lambda row: try_insert(row))
    """

    def __init__(
        self, path: Path, max_lines: int = MAX_QUEUE_LINES
    ) -> None:
        self._path = path
        self._max_lines = max_lines
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def enqueue(self, row: dict[str, Any]) -> None:
        """
        실패한 INSERT 행을 큐 끝에 추가.

        라인 수가 max 에 도달하면 가장 오래된 라인부터 drop 후 append.
        """
        line = json.dumps(row, ensure_ascii=False)
        with self._lock:
            if self._count_lines_locked() >= self._max_lines:
                self._trim_oldest_locked(keep=self._max_lines - 1)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def flush(
        self, insert_fn: Callable[[dict[str, Any]], bool]
    ) -> tuple[int, int]:
        """
        큐에 쌓인 모든 행을 `insert_fn` 에 순서대로 전달.

        Args:
            insert_fn: row -> bool. True 면 INSERT 성공 (큐에서 제거),
                       False 또는 예외면 실패 (큐에 남김).

        Returns:
            (success_count, remaining_count)
        """
        with self._lock:
            if not self._path.exists():
                return 0, 0

            rows = self._read_all_locked()
            remaining: list[dict[str, Any]] = []
            success = 0

            for row in rows:
                try:
                    ok = bool(insert_fn(row))
                except Exception as exc:
                    logger.warning("flush: insert_fn raised: %s", exc)
                    ok = False

                if ok:
                    success += 1
                else:
                    remaining.append(row)

            self._rewrite_locked(remaining)
            return success, len(remaining)

    def pending_count(self) -> int:
        """현재 큐에 남은 라인 수. 모니터링용."""
        with self._lock:
            return self._count_lines_locked()

    # ── 내부 헬퍼 (모두 lock 보유 상태에서만 호출) ───────────────────────

    def _count_lines_locked(self) -> int:
        if not self._path.exists():
            return 0
        with self._path.open("r", encoding="utf-8") as f:
            return sum(1 for _ in f)

    def _read_all_locked(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with self._path.open("r", encoding="utf-8") as f:
            for line_no, raw in enumerate(f, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rows.append(json.loads(raw))
                except json.JSONDecodeError as exc:
                    # 손상된 줄은 복구 불가 → 로그 남기고 버림
                    logger.warning("skip malformed line %d: %s", line_no, exc)
        return rows

    def _rewrite_locked(self, rows: list[dict[str, Any]]) -> None:
        """
        원자적 재기록: tmp 에 쓰고 원본을 덮어씀. 중간 크래시 시 원본 보존.
        """
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        tmp.replace(self._path)

    def _trim_oldest_locked(self, keep: int) -> None:
        """파일의 최근 `keep` 라인만 남기고 나머지 제거."""
        rows = self._read_all_locked()
        if len(rows) <= keep:
            return
        self._rewrite_locked(rows[-keep:])
