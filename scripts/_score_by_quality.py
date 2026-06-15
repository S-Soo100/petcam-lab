"""opus-sonnet-186 예측을 quality_tag 로 층화 — 모델별 hard 샘플 약점 (B1 후속).

새 인퍼런스 없음 (기존 opus.json / v40 sonnet 재집계). manifest quality_tag 조인.
- sample_list(id→path) → meta.json(src) → clip8 → manifest(quality_tag, tag_basis)
- quality 그룹별 Opus/Sonnet raw + 급여경계 정확도
- drinking 한정 quality 층화 (제품 1순위 클래스의 난이도별 모델 비교)

실행: PYTHONPATH=. uv run python scripts/_score_by_quality.py
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXP = REPO / "experiments" / "opus-sonnet-186"
V40RAW = REPO / "experiments" / "v40-regression" / "raw"
MANIFEST = REPO / "storage" / "dataset-203" / "manifest.csv"
FEEDING = {"drinking", "eating_paste"}


def boundary(p: str | None, g: str) -> bool:
    if p is None:
        return False
    return (p in FEEDING) if g in FEEDING else (p == g)


def main() -> int:
    # manifest: clip8 → (quality_tag, tag_basis)
    qmap: dict[str, tuple[str, str]] = {}
    for r in csv.DictReader(MANIFEST.open()):
        qmap[r["clip_id"][:8]] = (r["quality_tag"], r["tag_basis"])

    # sample_list: id → gt, clip8 (meta.json src 경유)
    samples = json.loads((EXP / "sample_list.json").read_text())
    gt: dict[str, str] = {}
    clip8: dict[str, str] = {}
    for s in samples:
        sid = s["id"]
        gt[sid] = s["gt"]
        src = json.loads((Path(s["path"]) / "meta.json").read_text())["src"]
        clip8[sid] = src.rsplit("__", 1)[-1].split(".")[0]

    # 예측 로드
    opus = {r["sample"]: r["action"] for r in json.loads((EXP / "raw" / "opus.json").read_text())}
    sonnet: dict[str, str] = {}
    for f in sorted(V40RAW.glob("v4.0_g*.json")):
        for r in json.loads(f.read_text()).get("results", []):
            sonnet[r["sample"]] = r["action"]
    s0615 = EXP / "raw" / "sonnet0615.json"
    if s0615.exists():
        for r in json.loads(s0615.read_text()):
            sonnet[r["sample"]] = r["action"]

    # quality 그룹별 집계
    def newgrp():
        return {"n": 0, "o": 0, "s": 0, "ob": 0, "sb": 0}

    groups: dict[str, dict] = defaultdict(newgrp)
    for sid in gt:
        qtag, basis = qmap.get(clip8[sid], ("", "none"))
        key = qtag or "(untagged)"
        if basis == "heuristic":
            key += " [heur]"
        g = gt[sid]
        grp = groups[key]
        grp["n"] += 1
        grp["o"] += opus.get(sid) == g
        grp["s"] += sonnet.get(sid) == g
        grp["ob"] += boundary(opus.get(sid), g)
        grp["sb"] += boundary(sonnet.get(sid), g)

    order = ["closeup", "production-like", "production-like [heur]", "handheld-challenging", "(untagged)"]
    keys = order + [k for k in groups if k not in order]
    print("=== quality_tag 층화 — Opus / Sonnet (raw 정확도 · 급여경계) ===")
    print(f"  {'quality_tag':24} {'n':>3}  {'Opus':>11}  {'Sonnet':>11}")
    for k in keys:
        if k not in groups:
            continue
        g = groups[k]
        n = g["n"]
        print(f"  {k:24} {n:>3}  {g['o']:>2}/{n} {g['o']/n:>5.0%}  {g['s']:>2}/{n} {g['s']/n:>5.0%}"
              + (f"   (경계 O{g['ob']}/S{g['sb']})" if any(gt[s] in FEEDING for s in gt if (qmap.get(clip8[s], ('', ''))[0] or '(untagged)') + (' [heur]' if qmap.get(clip8[s], ('', 'none'))[1] == 'heuristic' else '') == k) else ""))

    # drinking 한정 quality 층화 (제품 1순위)
    print("\n=== drinking 한정 quality 층화 (recall, Opus / Sonnet) ===")
    dr: dict[str, dict] = defaultdict(newgrp)
    for sid in gt:
        if gt[sid] != "drinking":
            continue
        qtag = qmap.get(clip8[sid], ("", ""))[0] or "(untagged)"
        grp = dr[qtag]
        grp["n"] += 1
        grp["o"] += opus.get(sid) == "drinking"
        grp["s"] += sonnet.get(sid) == "drinking"
        grp["ob"] += boundary(opus.get(sid), "drinking")
        grp["sb"] += boundary(sonnet.get(sid), "drinking")
    for k in ["closeup", "production-like", "handheld-challenging"]:
        if k not in dr:
            continue
        g = dr[k]
        n = g["n"]
        print(f"  {k:22} {n:>2}: Opus drinking {g['o']}/{n} (경계 {g['ob']}/{n})  ·  Sonnet drinking {g['s']}/{n} (경계 {g['sb']}/{n})")

    # discordant (모델 갈림) × quality
    print("\n=== Opus≠Sonnet discordant × quality_tag ===")
    disc: dict[str, int] = defaultdict(int)
    for sid in gt:
        if opus.get(sid) != sonnet.get(sid):
            qtag = qmap.get(clip8[sid], ("", ""))[0] or "(untagged)"
            disc[qtag] += 1
    for k, n in sorted(disc.items(), key=lambda x: -x[1]):
        print(f"  {k:22}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
