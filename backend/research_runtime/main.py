from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from backend.research_runtime.handlers import handler_for


def execute_handler(name: str, raw_args: str, result_path: Path) -> int:
    if name != "synthetic_noop_v1":
        return 2
    try:
        args = json.loads(raw_args)
        if not isinstance(args, dict):
            return 2
        result = handler_for(name)(args)
        payload = json.dumps(
            {"schema_version": 1, "steps": len(result), "result": result},
            sort_keys=True,
            separators=(",", ":"),
        )
        result_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        result_path.write_text(payload, encoding="utf-8")
        os.chmod(result_path, 0o600)
        return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return 2


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 4 and args[0] == "execute-handler":
        return execute_handler(args[1], args[2], Path(args[3]))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
