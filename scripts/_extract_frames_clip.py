"""클립 풀해상도 프레임 추출기 (긴변 1080 no-upscale) — 단일/배치. 재사용 스크립트.

세션마다 반복하던 `python -c` 즉석 추출 + `_prep_frames_*.py` 4개 산재를 대체.
코어는 `storage/dataset-203/analyze.extract_frames` 재사용 + no-upscale 후처리.

입력 기준 (2026-06-13 확정): 긴변 min(원본, 1080), **업스케일 금지**(작은 원본은 원본 유지 —
가짜 보간 픽셀이 VLM 판단 교란 + 토큰 낭비).

실행:
  단일: PYTHONPATH=. uv run python scripts/_extract_frames_clip.py <clip8|filename> --out experiments/foo [--n 10]
  배치: PYTHONPATH=. uv run python scripts/_extract_frames_clip.py --from-manifest [--gt drinking] --out experiments/foo [--n 10] [--exclude-done experiments/bar]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import cv2

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "storage" / "dataset-203"
LONG_EDGE = 1080

sys.path.insert(0, str(DS))
import analyze  # noqa: E402 — dataset-203/analyze.py: extract_frames(path, tmpdir, n, long_edge=1024)


def _enforce_no_upscale(p: Path) -> None:
    """긴변 > 1080 이면 다운스케일, 이하면 원본 유지(업스케일 X)."""
    img = cv2.imread(str(p))
    h, w = img.shape[:2]
    if max(h, w) > LONG_EDGE:
        s = LONG_EDGE / max(h, w)
        img = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(p), img, [cv2.IMWRITE_JPEG_QUALITY, 95])


def extract(video: Path, out: Path, n: int) -> int:
    out.mkdir(parents=True, exist_ok=True)
    paths = analyze.extract_frames(video, str(out), n, long_edge=LONG_EDGE)
    for p in paths:
        _enforce_no_upscale(Path(p))
    return len(paths)


def _load_done(d: Path | None) -> set[str]:
    """기존 sample-*/meta.json 의 src clip8 → 재추출 제외."""
    done: set[str] = set()
    if d and d.exists():
        for m in d.glob("sample-*/meta.json"):
            src = json.loads(m.read_text()).get("src", "")
            if src:
                done.add(src.split("__")[-1].split(".")[0])
    return done


def main() -> int:
    ap = argparse.ArgumentParser(description="클립 프레임 추출 @1080 no-upscale")
    ap.add_argument("target", nargs="?", help="clip8 또는 filename (단일 모드)")
    ap.add_argument("--from-manifest", action="store_true", help="manifest 기반 배치")
    ap.add_argument("--gt", help="배치 시 GT 클래스 필터")
    ap.add_argument("--n", type=int, default=10, help="프레임 수 (default 10)")
    ap.add_argument("--out", required=True, help="출력 디렉토리 (repo 상대 또는 절대)")
    ap.add_argument("--exclude-done", help="기존 sample-*/meta.json clip8 제외")
    a = ap.parse_args()

    out = Path(a.out) if a.out.startswith("/") else REPO / a.out
    rows = list(csv.DictReader(open(DS / "manifest.csv")))

    if a.from_manifest:
        done = _load_done(Path(a.exclude_done) if a.exclude_done else None)
        sel = [r for r in rows if (not a.gt or r["gt"] == a.gt) and r["clip_id"][:8] not in done]
        print(f"배치 {len(sel)}건 (gt={a.gt or 'all'}, done 제외 {len(done)}) → {out}")
        for i, r in enumerate(sel, 1):
            d = out / f"sample-{i:02d}"
            nf = extract(DS / r["filename"], d, a.n)
            (d / "meta.json").write_text(
                json.dumps({"gt": r["gt"], "src": r["filename"], "nframes": nf}, ensure_ascii=False)
            )
            print(f"  sample-{i:02d} {r['clip_id'][:8]} {nf}프레임")
    else:
        if not a.target:
            ap.error("단일 모드는 target(clip8 또는 filename) 필요")
        m = [r for r in rows if r["clip_id"][:8] == a.target or r["filename"] == a.target]
        if not m:
            ap.error(f"manifest에 없음: {a.target}")
        nf = extract(DS / m[0]["filename"], out, a.n)
        print(f"{a.target} → {out} ({nf}프레임 @{LONG_EDGE} no-upscale)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
