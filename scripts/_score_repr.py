"""입력표현 실험 공식 채점기 — experiment-claude-montage-v2.md §4-3a deterministic scoring.

점수는 이 스크립트만 산출한다 (LLM 손계산 금지). 채점 컨벤션 = P1 raw (pred == gt, merge 없음).

모드:
  --selftest             기존 P1 frames jsonl로 스펙 §4-2a 기준선 재현 검증 (인퍼런스 0)
  --phase M0             experiments/m0-montage/results/*.jsonl 전부 채점 + frames paired Δ표

fail 조건 (§4-3a — 조용한 skip 금지, 발견 시 exit 1):
  missing   — sample_list에 있는데 결과 없음
  duplicate — 같은 sample 중복 응답
  mismatch  — sample_list에 없는 sample
  schema    — 필드 누락 / action 미정의 클래스 / confidence 범위 밖

실행:
  PYTHONPATH=. uv run python scripts/_score_repr.py --selftest
  PYTHONPATH=. uv run python scripts/_score_repr.py --phase M0
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path("/Users/baek/petcam-lab")
DS = REPO / "storage" / "dataset-203"
EXP = REPO / "experiments"
M0 = EXP / "m0-montage"

CLASSES = {"eating_paste", "eating_prey", "drinking", "defecating", "shedding",
           "basking", "hiding", "moving", "unseen", "hand_feeding"}
REQUIRED = {"sample", "action", "confidence", "reasoning", "model", "repr", "phase"}
PRIORITY3 = ("moving", "shedding", "drinking")  # care-priority 보조 지표 (§4-3)


# ── GT / 기존 frames 결과 로드 ───────────────────────────────────────────────
def load_gt() -> dict[str, str]:
    return {r["clip_id"][:8]: r["gt"] for r in csv.DictReader(open(DS / "manifest.csv"))}


def load_frames_preds(fname: str) -> dict[str, str]:
    """P1 blind jsonl → c8: pred. sample-NN(eval-frames-claude)은 meta.json으로 매핑."""
    nn = {d.name: json.loads((d / "meta.json").read_text())["src"].split("__")[-1].split(".")[0]
          for d in (EXP / "eval-frames-claude").glob("sample-*") if d.is_dir()}
    pred = {}
    for line in (EXP / "eval-frames-full" / fname).read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            pred[nn.get(r["sample"], r["sample"].replace("sample-", ""))] = r["action"]
    return pred


def load_legacy63() -> set[str]:
    """구 63건 멤버십 = frames63 blind jsonl의 src c8."""
    out = set()
    for line in (EXP / "eval-frames-claude" / "frames63_blind.jsonl").read_text().splitlines():
        if line.strip():
            out.add(json.loads(line)["src"].split("__")[-1].split(".")[0])
    return out


def raw_acc(pred: dict[str, str], gt: dict[str, str], keys) -> tuple[int, int]:
    ks = [k for k in keys if k in pred]
    return sum(1 for k in ks if pred[k] == gt[k]), len(ks)


# ── selftest — 스펙 §4-2a 기준선 재현 ────────────────────────────────────────
def selftest() -> int:
    gt = load_gt()
    micro55 = [c for c, g in gt.items() if g in ("drinking", "eating_prey", "eating_paste")]
    legacy63 = load_legacy63()
    expected = {  # (모델 jsonl, 서브셋) → (correct, total) — 스펙 §4-2a 고정 수치
        ("sonnet46_blind.jsonl", "micro55"): (41, 55),
        ("opus48_blind.jsonl", "micro55"): (39, 55),
        ("sonnet46_blind.jsonl", "legacy63"): (47, 63),
        ("opus48_blind.jsonl", "legacy63"): (46, 63),
        ("sonnet46_blind.jsonl", "full202"): (158, 202),
        ("opus48_blind.jsonl", "full202"): (164, 202),
    }
    subsets = {"micro55": micro55, "legacy63": list(legacy63), "full202": list(gt)}
    print(f"micro55={len(micro55)} legacy63={len(legacy63)} "
          f"(micro55⊂legacy63: {set(micro55) <= legacy63}) full={len(gt)}")
    ok_all = True
    for (fname, sub), (ec, et) in expected.items():
        c, t = raw_acc(load_frames_preds(fname), gt, subsets[sub])
        mark = "✅" if (c, t) == (ec, et) else "❌"
        ok_all &= (c, t) == (ec, et)
        print(f"  {mark} {fname.split('_')[0]:9s} {sub:9s}: {c}/{t} = {c/t:.1%}  (스펙 기대 {ec}/{et})")
    print("selftest:", "✅ 전부 일치 — 매핑/컨벤션 검증 통과" if ok_all else "❌ 불일치 — 채점 중단")
    return 0 if ok_all else 1


# ── 결과 검증 + 채점 ─────────────────────────────────────────────────────────
def validate(lines: list[dict], expected_samples: set[str], variant: str) -> list[str]:
    errs = []
    seen = set()
    for r in lines:
        miss = REQUIRED - set(r)
        if miss:
            errs.append(f"schema: {r.get('sample', '?')} 필드 누락 {sorted(miss)}")
            continue
        if r["action"] not in CLASSES:
            errs.append(f"schema: {r['sample']} 미정의 클래스 '{r['action']}'")
        if not (isinstance(r["confidence"], (int, float)) and 0 <= r["confidence"] <= 1):
            errs.append(f"schema: {r['sample']} confidence 범위 밖 {r['confidence']!r}")
        if r["sample"] in seen:
            errs.append(f"duplicate: {r['sample']}")
        seen.add(r["sample"])
        if r["sample"] not in expected_samples:
            errs.append(f"mismatch: {r['sample']} 은 sample_list에 없음")
    for s in sorted(expected_samples - seen):
        errs.append(f"missing: {s}")
    return [f"[{variant}] {e}" for e in errs]


def image_tokens(variant: str, sample: str) -> float:
    import cv2  # 지연 import — selftest 경로는 cv2 불필요
    t = 0.0
    for jp in sorted((M0 / "inputs" / variant / sample).glob("sheet*.jpg")):
        im = cv2.imread(str(jp))
        t += im.shape[0] * im.shape[1] / 750
    return t


def score_m0() -> int:
    gt = load_gt()
    plist = json.loads((M0 / "sample_list.json").read_text())["samples"]
    s2c8 = {s["sample"]: s["clip8"] for s in plist}
    expected = set(s2c8)
    sonnet_frames = {s["sample"]: s["sonnet_frames_pred"] for s in plist}
    micro = {s["sample"] for s in plist if s["bucket"].startswith("micro")}

    results_dir = M0 / "results"
    files = sorted(results_dir.glob("*.jsonl")) if results_dir.is_dir() else []
    if not files:
        print(f"결과 없음: {results_dir}/*.jsonl")
        return 1

    all_errs = []
    table = []
    discordant = []
    for f in files:
        variant = f.stem  # e.g. mv2-12f-1s-ts (모델 구분은 파일명 suffix 가능: ...__opus)
        lines = [json.loads(x) for x in f.read_text().splitlines() if x.strip()]
        errs = validate(lines, expected, variant)
        if errs:
            all_errs += errs
            continue
        pred = {r["sample"]: r["action"] for r in lines}
        n_ok = sum(1 for s in expected if pred[s] == gt[s2c8[s]])
        m_ok = sum(1 for s in micro if pred[s] == gt[s2c8[s]])
        p3 = [s for s in expected if gt[s2c8[s]] in PRIORITY3]
        p3_ok = sum(1 for s in p3 if pred[s] == gt[s2c8[s]])
        rec = sorted(s for s in expected
                     if sonnet_frames[s] != gt[s2c8[s]] and pred[s] == gt[s2c8[s]])
        brk = sorted(s for s in expected
                     if sonnet_frames[s] == gt[s2c8[s]] and pred[s] != gt[s2c8[s]])
        toks = round(sum(image_tokens(variant.split("__")[0], s) for s in expected) / len(expected))
        table.append((variant, n_ok, m_ok, len(micro), p3_ok, len(p3), rec, brk, toks))
        discordant += [{"variant": variant, "sample": s, "clip8": s2c8[s], "gt": gt[s2c8[s]],
                        "frames": sonnet_frames[s], "montage": pred[s]}
                       for s in sorted(expected) if pred[s] != sonnet_frames[s]]

    if all_errs:
        print(f"❌ FAIL — 검증 에러 {len(all_errs)}건 (채점 거부, 재실행 후 재채점):")
        for e in all_errs:
            print("  " + e)
        return 1

    print(f"{'variant':22s} {'raw':>7s} {'micro12':>8s} {'prio3':>7s} "
          f"{'rec':>4s} {'brk':>4s} {'imgTok':>7s}")
    for v, n_ok, m_ok, mt, p3_ok, p3t, rec, brk, toks in sorted(
            table, key=lambda x: -x[1]):
        print(f"{v:22s} {n_ok:>3d}/20 {m_ok:>4d}/{mt:<3d} {p3_ok:>3d}/{p3t:<3d} "
              f"{len(rec):>4d} {len(brk):>4d} {toks:>7,}")
    print(f"\n(Sonnet frames 동일 20건 기준선: raw 12/20 — sample_list 구성상 정답12/오답8)")

    q = M0 / "discordant_queue.json"
    q.write_text(json.dumps(discordant, ensure_ascii=False, indent=2))
    print(f"discordant queue → {q} ({len(discordant)}건)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--phase", choices=["M0"])
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.phase == "M0":
        return score_m0()
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
