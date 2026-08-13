#!/usr/bin/env python3
"""Mac mini의 v2.3 학습 원본을 별도 immutable release로 복사한다."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.yolo_release import ReleaseError, create_immutable_release, v23_release_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    args = parser.parse_args()
    manifest = v23_release_manifest()
    try:
        create_immutable_release(
            source=args.source,
            release_root=args.release_root,
            manifest=manifest,
        )
    except ReleaseError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1
    print(
        json.dumps(
            {
                "status": "ready",
                "model_version": manifest.model_version,
                "checkpoint_sha256": manifest.checkpoint_sha256,
                "checkpoint_size": manifest.checkpoint_size,
                "threshold": manifest.threshold,
                "usage_scope": manifest.allowed_use,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

