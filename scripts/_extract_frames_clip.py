"""클립 풀해상도 프레임 추출기 (긴변 1080 no-upscale) — 단일/배치. 재사용 스크립트.

세션마다 반복하던 `python -c` 즉석 추출 + `_prep_frames_*.py` 4개 산재를 대체.
코어는 `storage/dataset-203/analyze.extract_frames` 재사용 + no-upscale 후처리.

입력 기준 (2026-06-13 확정): 긴변 min(원본, 1080), **업스케일 금지**(작은 원본은 원본 유지 —
가짜 보간 픽셀이 VLM 판단 교란 + 토큰 낭비).

추출 모드 2개:
  - 고정 N (default, --n): 균등 N장. ⚠️ ffmpeg fps 필터 + [:n] slice 라 긴 클립은 앞부분만
    커버(60초→0~45초) + t=0 포함. **회귀 재현용으로만 보존**, 신규 평가엔 쓰지 말 것.
  - 적응형 (--adaptive): 간격기반 장수(clamp(dur/interval, min, max)) + **구간중앙 위치**
    (t_i=(i+0.5)*dur/N). t=0/꼬리/뒷부분손실 3대 결함 회피. 긴 클립 미세접촉용 (2026-06-13 신설).

실행:
  단일(적응형): PYTHONPATH=. uv run python scripts/_extract_frames_clip.py <clip8> --out experiments/foo --adaptive
  배치(적응형): PYTHONPATH=. uv run python scripts/_extract_frames_clip.py --from-manifest --gt drinking --out experiments/foo --adaptive
  단일(고정):   PYTHONPATH=. uv run python scripts/_extract_frames_clip.py <clip8> --out experiments/foo --n 10
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
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


def _adaptive_n(dur: float, interval: float, lo: int, hi: int) -> int:
    """간격당 1장 → 클립 길이 비례 장수. 짧은 클립 하한 / 긴 클립 상한 클램프."""
    return max(lo, min(hi, round(dur / interval)))


def extract_adaptive(video: Path, out: Path, interval: float, lo: int, hi: int) -> int:
    """적응형: 간격기반 장수 + 구간중앙 위치(t_i=(i+0.5)*dur/N).

    고정N(ffmpeg fps 필터)의 3대 결함 — ① [:n] slice 로 긴 클립 뒷부분 손실,
    ② t=0 첫 프레임(행동 전), ③ 등간격 aliasing — 을 위치 명시제어로 해소.
    각 구간중앙 타임스탬프를 -ss 로 정확 추출(원본 해상도) 후 no-upscale 다운스케일.
    """
    out.mkdir(parents=True, exist_ok=True)
    dur = analyze.probe_duration(video)
    n = _adaptive_n(dur, interval, lo, hi)
    written = 0
    for i in range(n):
        t = (i + 0.5) * dur / n  # 구간 중앙 → t=0/꼬리 회피, 전 구간 균등
        p = out / f"f_{i + 1:03d}.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", str(video),
             "-frames:v", "1", "-q:v", "3", str(p)],
            capture_output=True,
        )
        if p.exists():
            _enforce_no_upscale(p)
            written += 1
    return written


def _do_extract(video: Path, out: Path, a: argparse.Namespace) -> int:
    """CLI 인자에 따라 적응형/고정N 디스패치."""
    if a.adaptive:
        return extract_adaptive(video, out, a.interval, a.min_frames, a.max_frames)
    return extract(video, out, a.n)


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
    ap.add_argument("--n", type=int, default=10, help="고정모드 프레임 수 (default 10)")
    ap.add_argument("--adaptive", action="store_true", help="간격기반 적응형 + 구간중앙 위치")
    ap.add_argument("--interval", type=float, default=3.5, help="적응형 초/프레임 (default 3.5)")
    ap.add_argument("--min-frames", type=int, default=6, help="적응형 장수 하한 (default 6)")
    ap.add_argument("--max-frames", type=int, default=20, help="적응형 장수 상한 (default 20)")
    ap.add_argument("--out", required=True, help="출력 디렉토리 (repo 상대 또는 절대)")
    ap.add_argument("--exclude-done", help="기존 sample-*/meta.json clip8 제외")
    ap.add_argument("--shuffle", type=int, default=None, metavar="SEED",
                    help="blind: SEED로 sample 순서 셔플 (GT 정렬 패턴 차단)")
    a = ap.parse_args()

    out = Path(a.out) if a.out.startswith("/") else REPO / a.out
    rows = list(csv.DictReader(open(DS / "manifest.csv")))

    if a.from_manifest:
        done = _load_done(Path(a.exclude_done) if a.exclude_done else None)
        sel = [r for r in rows if (not a.gt or r["gt"] == a.gt) and r["clip_id"][:8] not in done]
        if a.shuffle is not None:
            import random
            random.Random(a.shuffle).shuffle(sel)  # blind: GT 정렬 패턴 차단
        print(f"배치 {len(sel)}건 (gt={a.gt or 'all'}, done 제외 {len(done)}, shuffle={a.shuffle}) → {out}")
        for i, r in enumerate(sel, 1):
            d = out / f"sample-{i:02d}"
            nf = _do_extract(DS / r["filename"], d, a)
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
        nf = _do_extract(DS / m[0]["filename"], out, a)
        mode = f"적응형 ~{a.interval}s/프레임" if a.adaptive else f"고정 {a.n}장"
        print(f"{a.target} → {out} ({nf}프레임 @{LONG_EDGE} no-upscale · {mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
