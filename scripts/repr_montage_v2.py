"""montage-v2 입력표현 빌더 — M0 12변형 생성 (experiment-claude-montage-v2.md §4-2).

6 레이아웃 × ts on/off = 12변형. 캔버스 폭 1536px 기준, 셀은 16:9 fit (세로 영상은
pillarbox). 같은 n의 변형끼리는 **같은 프레임**을 공유 (1장 vs 2장 = 셀 크기 단독 효과 격리,
ts on/off = 오버레이만 차이). 프레임 선택 = 전체 길이 균등 (모션 기반은 P2 기각).

blind 원칙: 입력 디렉토리에는 jpg만 생성 (meta/GT 없음 — GT는 sample_list.json에만,
inference 입력에 절대 미포함). cv2.imwrite는 EXIF를 쓰지 않음.

실행: PYTHONPATH=. uv run python scripts/repr_montage_v2.py          # 생성 + leakage 검수
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

REPO = Path("/Users/baek/petcam-lab")
DS = REPO / "storage" / "dataset-203"
M0 = REPO / "experiments" / "m0-montage"
INPUTS = M0 / "inputs"

CANVAS_W = 1536
CLAUDE_MAX_SIDE = 1568  # 초과 시 Claude가 다운스케일 → 캔버스 한 변이 넘지 않게 설계

# (이름, n프레임, [장별 (cols, rows)]) — §4-2 후보표와 1:1. 20f-2장 분할형은 M0 제외.
LAYOUTS: list[tuple[str, int, list[tuple[int, int]]]] = [
    ("12f-1s", 12, [(3, 4)]),
    ("12f-2s", 12, [(2, 3), (2, 3)]),
    ("16f-1s", 16, [(4, 4)]),
    ("16f-2s", 16, [(2, 4), (2, 4)]),
    ("18f-2s", 18, [(3, 3), (3, 3)]),
    ("20f-1s", 20, [(4, 5)]),
]


def grid_for(cols: int, rows: int, aspect: float) -> tuple[int, int]:
    """세로 영상(aspect<1)은 격자 회전 (3×4 → 4열×3행) — 셀이 세로로 길어지므로
    열을 늘리고 행을 줄여야 캔버스를 덜 낭비함. 프레임 수/장수는 불변."""
    return (rows, cols) if aspect < 1 else (cols, rows)


def cell_size(cols: int, rows: int, aspect: float) -> tuple[int, int]:
    """캔버스 폭 1536 기준, 셀 비율 = 영상 비율 (패딩 0). 세로 합 1568 초과 시 높이 기준."""
    cw = CANVAS_W // cols
    ch = round(cw / aspect)
    if rows * ch > CLAUDE_MAX_SIDE:
        ch = CLAUDE_MAX_SIDE // rows
        cw = round(ch * aspect)
    return cw, ch


def extract_sets(video: Path, ns: list[int]) -> dict[int, tuple[list[np.ndarray], list[float]]]:
    """n별 균등 프레임 세트를 한 번의 순차 디코드로 수집.

    CAP_PROP_FRAME_COUNT 메타데이터는 실제 디코딩 가능 수보다 클 수 있음(mp4 꼬리 손상) →
    pass1에서 실측 카운트, pass2에서 필요한 인덱스만 retrieve. seek 미사용 (VFR 안전).
    실패는 raise (조용한 skip 금지).
    """
    cap = cv2.VideoCapture(str(video))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
        total = 0
        while cap.grab():
            total += 1
    finally:
        cap.release()
    if total <= 0:
        raise RuntimeError(f"디코딩 가능 프레임 0: {video.name}")

    need = {n: np.unique(np.linspace(0, total - 1, min(n, total)).round().astype(int)) for n in ns}
    wanted = sorted(set().union(*[set(v.tolist()) for v in need.values()]))
    wanted_set = set(wanted)

    got: dict[int, np.ndarray] = {}
    cap = cv2.VideoCapture(str(video))
    try:
        i = 0
        while i <= wanted[-1]:
            if not cap.grab():
                raise RuntimeError(f"pass2 grab 실패 idx={i} (실측 {total}): {video.name}")
            if i in wanted_set:
                ok, fr = cap.retrieve()
                if not ok:
                    raise RuntimeError(f"retrieve 실패 idx={i}: {video.name}")
                got[i] = fr
            i += 1
    finally:
        cap.release()

    return {n: ([got[i] for i in idxs], [float(i) / fps for i in idxs])
            for n, idxs in need.items()}


def fit_cell(frame: np.ndarray, cw: int, ch: int) -> np.ndarray:
    """비율 보존 fit + 검정 패딩 (세로 영상 pillarbox)."""
    h, w = frame.shape[:2]
    scale = min(cw / w, ch / h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
    cell = np.zeros((ch, cw, 3), dtype=np.uint8)
    y, x = (ch - nh) // 2, (cw - nw) // 2
    cell[y:y + nh, x:x + nw] = resized
    return cell


def overlay_ts(cell: np.ndarray, sec: float) -> np.ndarray:
    """셀 우상단 t=MM:SS — 흰 글자 + 검정 외곽선 (IR/주간 모두 가독)."""
    label = f"t={int(sec) // 60:02d}:{int(sec) % 60:02d}"
    ch = cell.shape[0]
    scale = max(0.35, 0.55 * ch / 288)
    thick = max(1, round(scale * 2))
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
    org = (cell.shape[1] - tw - 6, th + 6)
    cv2.putText(cell, label, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick + 2, cv2.LINE_AA)
    cv2.putText(cell, label, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), thick, cv2.LINE_AA)
    return cell


def compose(frames, times, sheets, ts_on: bool) -> list[np.ndarray]:
    """프레임을 장별 격자에 row-major 배치. 셀 비율/격자 방향은 영상 비율 기준."""
    h0, w0 = frames[0].shape[:2]
    aspect = w0 / h0
    out, pos = [], 0
    for base_cols, base_rows in sheets:
        cols, rows = grid_for(base_cols, base_rows, aspect)
        cw, ch = cell_size(cols, rows, aspect)
        canvas = np.zeros((rows * ch, cols * cw, 3), dtype=np.uint8)
        for r in range(rows):
            for c in range(cols):
                if pos >= len(frames):
                    break
                cell = fit_cell(frames[pos], cw, ch)
                if ts_on:
                    cell = overlay_ts(cell, times[pos])
                canvas[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw] = cell
                pos += 1
        out.append(canvas)
    return out


def leakage_check() -> bool:
    """입력 트리에 jpg 외 파일/GT 문자열 경로가 없는지 검수 (§4-3a blind)."""
    classes = ["drinking", "eating", "shedding", "defecating", "moving", "hand_feeding",
               "basking", "hiding", "unseen", "prey", "paste"]
    bad = []
    for p in INPUTS.rglob("*"):
        rel = str(p.relative_to(INPUTS)).lower()
        if p.is_file() and p.suffix != ".jpg":
            bad.append(f"비-jpg 파일: {rel}")
        if any(k in rel for k in classes):
            bad.append(f"클래스명 누출 의심: {rel}")
    for b in bad:
        print(f"  ❌ {b}")
    return not bad


def main() -> int:
    samples = json.loads((M0 / "sample_list.json").read_text())["samples"]
    built = 0
    for s in samples:
        video = DS / s["filename"]
        if not video.is_file():
            raise FileNotFoundError(f"{s['sample']}: {video} 없음 (manifest 기준 탐색)")
        cache = extract_sets(video, sorted({n for _, n, _ in LAYOUTS}))
        for name, n, sheets in LAYOUTS:
            frames, times = cache[n]
            for ts_on in (True, False):
                variant = f"mv2-{name}-{'ts' if ts_on else 'nots'}"
                d = INPUTS / variant / s["sample"]
                d.mkdir(parents=True, exist_ok=True)
                for i, canvas in enumerate(compose(frames, times, sheets, ts_on), 1):
                    cv2.imwrite(str(d / f"sheet{i}.jpg"), canvas,
                                [cv2.IMWRITE_JPEG_QUALITY, 90])
                built += 1
        print(f"  {s['sample']} ✓ ({video.suffix})")

    print(f"\n✅ {built} variant-샘플 생성 ({len(samples)}건 × 12변형)")
    print("\n변형별 실측 이미지 토큰 (클립당, jpg 치수 w×h/750 합 — ts/nots 동일):")
    for name, _, _ in LAYOUTS:
        toks = []
        for s in samples:
            t = 0.0
            for jp in sorted((INPUTS / f"mv2-{name}-ts" / s["sample"]).glob("sheet*.jpg")):
                im = cv2.imread(str(jp))
                t += im.shape[0] * im.shape[1] / 750
            toks.append(t)
        print(f"  mv2-{name}-*  : 평균 ≈ {round(sum(toks) / len(toks)):>5,} tok "
              f"(min {round(min(toks)):,} / max {round(max(toks)):,})")
    print("\nblind leakage 검수:", "✅ PASS" if leakage_check() else "❌ FAIL")
    return 0


if __name__ == "__main__":
    sys.exit(main())
