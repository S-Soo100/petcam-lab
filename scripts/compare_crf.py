"""
CRF 23 / 26 / 28 인코딩 비교 (spec §3-2 마지막 항목).

실 캡처 클립 N개에 대해 세 CRF 값으로 인코딩 → 입력/출력 사이즈 + 압축률 표 출력.
육안 검증은 별도 (출력 파일 경로 표시 → 사용자가 직접 재생).

사용:
  uv run python scripts/compare_crf.py [N]   # 기본 20개
  → 결과는 stdout 에 markdown 표 + 출력 폴더 경로
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.encoding import encode_lightweight  # noqa: E402

CRF_VALUES = (23, 26, 28)
DEFAULT_N = 20
MIN_SAMPLE_BYTES = 100_000


def _pick_samples(n: int) -> list[Path]:
    """storage/clips/ 에서 100KB+ 인 가장 최근 mp4 N개 (큰 → 작은 순)."""
    clips_root = REPO_ROOT / "storage" / "clips"
    candidates = sorted(
        (p for p in clips_root.rglob("*.mp4") if p.stat().st_size >= MIN_SAMPLE_BYTES),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[:n]


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_N
    samples = _pick_samples(n)
    if not samples:
        raise SystemExit("no mp4 ≥100KB found under storage/clips/")

    out_root = REPO_ROOT / "storage" / "crf_compare"
    out_root.mkdir(parents=True, exist_ok=True)
    print(f"[setup] N={len(samples)} samples, output={out_root}")

    rows: list[tuple[str, int, dict[int, int]]] = []
    for i, src in enumerate(samples, 1):
        src_size = src.stat().st_size
        sizes: dict[int, int] = {}
        for crf in CRF_VALUES:
            dst = out_root / f"{src.stem}_crf{crf}.mp4"
            ok = encode_lightweight(src, dst, crf=crf)
            if not ok:
                print(f"[{i}/{len(samples)}] FAIL crf={crf} src={src.name}")
                sizes[crf] = -1
            else:
                sizes[crf] = dst.stat().st_size
        rows.append((src.name, src_size, sizes))
        print(
            f"[{i}/{len(samples)}] {src.name} "
            f"src={src_size:>10,}  "
            + "  ".join(f"crf{c}={sizes[c]:>10,}" for c in CRF_VALUES)
        )

    # ─── 표 출력 ─────────────────────────────────────────
    print("\n## CRF 비교 표 (markdown)\n")
    print("| # | clip | original | CRF 23 | ratio | CRF 26 | ratio | CRF 28 | ratio |")
    print("|---|------|---------:|-------:|------:|-------:|------:|-------:|------:|")
    for i, (name, src_size, sizes) in enumerate(rows, 1):
        cells = [f"{i}", name, f"{src_size:,}"]
        for crf in CRF_VALUES:
            s = sizes[crf]
            if s < 0:
                cells += ["—", "—"]
            else:
                ratio = s / src_size
                cells += [f"{s:,}", f"{ratio:.2%}"]
        print("| " + " | ".join(cells) + " |")

    # ─── 요약 통계 ────────────────────────────────────────
    print("\n## 요약 (압축률 = encoded / original)\n")
    print("| CRF | mean | median | min | max | mean size (bytes) |")
    print("|-----|-----:|-------:|----:|----:|------------------:|")
    for crf in CRF_VALUES:
        ratios = [
            sizes[crf] / src_size
            for _, src_size, sizes in rows
            if sizes[crf] > 0
        ]
        out_sizes = [sizes[crf] for _, _, sizes in rows if sizes[crf] > 0]
        if not ratios:
            print(f"| {crf} | — | — | — | — | — |")
            continue
        print(
            f"| {crf} | {statistics.mean(ratios):.2%} | "
            f"{statistics.median(ratios):.2%} | "
            f"{min(ratios):.2%} | {max(ratios):.2%} | "
            f"{int(statistics.mean(out_sizes)):,} |"
        )

    print(f"\n육안 검증: {out_root} 안 mp4 직접 재생해서 같은 클립의 CRF 23 vs 26 vs 28 비교.")


if __name__ == "__main__":
    main()
