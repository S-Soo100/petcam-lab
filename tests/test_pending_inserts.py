"""
backend.pending_inserts 단위 테스트.

## 검증 목표
- enqueue / flush / max_lines 트리밍 / 손상 라인 무시의 **동작 계약** 확인.
- 파일 I/O 는 tmp_path 로 격리. 실 Supabase·네트워크 의존 없음.

## 왜 이 항목들?
- enqueue → 라인 카운트 증가: 가장 기본 계약.
- flush 전량 성공 → 파일이 비어야 함. "성공 라인 제거" 가 핵심 의도.
- flush 전량 실패 → 원본 유지. 재시도 자원이 보존돼야 장애 복구 가능.
- flush 부분 성공 → 실패분만 남음. 순서 유지 확인 (오래된 게 앞).
- insert_fn 예외 → False 로 간주. 예외가 큐를 오염시키면 안 됨.
- max_lines 초과 → 오래된 라인 drop. 무한 증가 방지 계약.
- 손상 라인 → 로그 남기고 skip. 한 줄 깨져도 나머지는 처리돼야 함.
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.pending_inserts import PendingInsertQueue


def _read_lines(path: Path) -> list[dict]:
    """파일 라인을 JSON 으로 파싱. 테스트 검증용 헬퍼."""
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_enqueue_appends_line(tmp_path: Path) -> None:
    """enqueue 한 번에 파일에 한 줄 append."""
    q = PendingInsertQueue(tmp_path / "pending.jsonl")
    q.enqueue({"camera_id": "cam-1", "n": 1})
    q.enqueue({"camera_id": "cam-1", "n": 2})

    rows = _read_lines(tmp_path / "pending.jsonl")
    assert rows == [
        {"camera_id": "cam-1", "n": 1},
        {"camera_id": "cam-1", "n": 2},
    ]
    assert q.pending_count() == 2


def test_flush_all_success_empties_queue(tmp_path: Path) -> None:
    """insert_fn 이 모두 True → 큐가 비고 (2, 0) 반환."""
    q = PendingInsertQueue(tmp_path / "pending.jsonl")
    q.enqueue({"n": 1})
    q.enqueue({"n": 2})

    success, remaining = q.flush(lambda row: True)

    assert (success, remaining) == (2, 0)
    assert _read_lines(tmp_path / "pending.jsonl") == []
    assert q.pending_count() == 0


def test_flush_all_fail_preserves_queue(tmp_path: Path) -> None:
    """insert_fn 이 모두 False → 큐 그대로, (0, 2) 반환."""
    q = PendingInsertQueue(tmp_path / "pending.jsonl")
    q.enqueue({"n": 1})
    q.enqueue({"n": 2})

    success, remaining = q.flush(lambda row: False)

    assert (success, remaining) == (0, 2)
    assert _read_lines(tmp_path / "pending.jsonl") == [{"n": 1}, {"n": 2}]


def test_flush_partial_keeps_only_failed_rows_in_order(tmp_path: Path) -> None:
    """
    홀수만 성공, 짝수만 실패 시나리오.
    → 짝수 행만 남아야 하고, 원래 순서 유지돼야 함.
    """
    q = PendingInsertQueue(tmp_path / "pending.jsonl")
    for i in range(1, 5):  # 1, 2, 3, 4
        q.enqueue({"n": i})

    success, remaining = q.flush(lambda row: row["n"] % 2 == 1)

    assert (success, remaining) == (2, 2)
    assert _read_lines(tmp_path / "pending.jsonl") == [{"n": 2}, {"n": 4}]


def test_flush_treats_insert_fn_exception_as_failure(tmp_path: Path) -> None:
    """insert_fn 이 예외 던지면 False 취급 → 큐에 남음."""
    q = PendingInsertQueue(tmp_path / "pending.jsonl")
    q.enqueue({"n": 1})

    def raising_insert(row: dict) -> bool:
        raise RuntimeError("network down")

    success, remaining = q.flush(raising_insert)

    assert (success, remaining) == (0, 1)
    assert _read_lines(tmp_path / "pending.jsonl") == [{"n": 1}]


def test_enqueue_drops_oldest_when_max_exceeded(tmp_path: Path) -> None:
    """
    max_lines=3 상태에서 4 번째 enqueue 하면 가장 오래된 1 번이 drop.
    "최근 max_lines 만 남긴다" 계약.
    """
    q = PendingInsertQueue(tmp_path / "pending.jsonl", max_lines=3)
    for i in range(1, 5):  # 1, 2, 3, 4
        q.enqueue({"n": i})

    # 1 이 drop, 2/3/4 만 남음
    assert _read_lines(tmp_path / "pending.jsonl") == [
        {"n": 2},
        {"n": 3},
        {"n": 4},
    ]
    assert q.pending_count() == 3


def test_flush_skips_malformed_lines_but_processes_rest(tmp_path: Path) -> None:
    """
    파일에 손상된 JSON 라인이 섞여 있어도 정상 라인은 처리돼야 함.
    → 외부 편집 사고/디스크 오염 시 큐 전체가 먹통 되면 곤란.
    """
    path = tmp_path / "pending.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    # 직접 라인 3개 작성: 정상 / 깨짐 / 정상
    path.write_text(
        '{"n": 1}\n'
        'this is not json\n'
        '{"n": 2}\n',
        encoding="utf-8",
    )

    q = PendingInsertQueue(path)
    success, remaining = q.flush(lambda row: True)

    # 정상 2개만 success, 손상 라인은 skip → 최종 큐 비어있음.
    assert (success, remaining) == (2, 0)
    assert _read_lines(path) == []


def test_flush_on_empty_file_returns_zero(tmp_path: Path) -> None:
    """파일이 없거나 비어있으면 (0, 0)."""
    q = PendingInsertQueue(tmp_path / "pending.jsonl")
    success, remaining = q.flush(lambda row: True)
    assert (success, remaining) == (0, 0)


def test_pending_count_reflects_current_state(tmp_path: Path) -> None:
    """enqueue / flush 이후 pending_count 가 파일 상태와 일치."""
    q = PendingInsertQueue(tmp_path / "pending.jsonl")
    assert q.pending_count() == 0

    q.enqueue({"n": 1})
    q.enqueue({"n": 2})
    assert q.pending_count() == 2

    q.flush(lambda row: row["n"] == 1)  # 1 만 성공
    assert q.pending_count() == 1
