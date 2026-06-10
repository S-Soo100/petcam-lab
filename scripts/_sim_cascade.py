"""P4 레버 C — 캐스케이드 시뮬레이션 (추가 인퍼런스 0).

이미 모은 frames 202 blind jsonl 3개(Sonnet/Opus/Fable, conf 포함)를 오프라인 결합.
싼 모델(Sonnet)을 base 로, 일부 clip 만 strong(Fable)에 "에스컬레이션"했을 때
정확도가 어디까지 오르나 = (정확도, 에스컬레이션율) 곡선.

핵심 질문: "비싼 모델 호출을 X%만 써서 격차(78.2→85.1, 6.9%p)를 몇 % 회수하나."

라우팅 룰 (에스컬레이션 결정은 base 모델 출력만으로 — 실제 캐스케이드 제약):
  R1 shedding-trigger  : Sonnet 이 shedding 예측 → escalate (P1b 발견 기반 표적)
  R2 vulnerable-class  : Sonnet 이 shedding/defecating/drinking/unseen 예측 → escalate
  R3 conf-threshold    : Sonnet conf < t → escalate (대조군, t sweep)
  R4 disagree(2-model) : Sonnet ≠ Opus → escalate (싼 모델 2개 필요)

대조: random escalation (같은 비율 무작위) — 룰이 random 보다 나은지 검증.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

REPO = Path("/Users/baek/petcam-lab")
EXP = REPO / "experiments"
DS = REPO / "storage" / "dataset-203"

nn_to_c8: dict[str, str] = {}
for d in (EXP / "eval-frames-claude").glob("sample-*"):
    if d.is_dir():
        nn_to_c8[d.name] = json.loads((d / "meta.json").read_text())["src"].split("__")[-1].split(".")[0]


def to_c8(s: str) -> str:
    return nn_to_c8.get(s, s.replace("sample-", ""))


def load(fname: str) -> dict[str, tuple[str, float]]:
    out = {}
    for line in (EXP / "eval-frames-full" / fname).read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            out[to_c8(r["sample"])] = (r["action"], r.get("conf", 0.0))
    return out


sonnet = load("sonnet46_blind.jsonl")
opus = load("opus48_blind.jsonl")
fable = load("fable5_blind.jsonl")
gt = {r["clip_id"][:8]: r["gt"] for r in csv.DictReader(open(DS / "manifest.csv"))}
keys = [c8 for c8 in gt if c8 in sonnet and c8 in opus and c8 in fable]
N = len(keys)

VULN = {"shedding", "defecating", "drinking", "unseen"}


def acc(pred_of: dict[str, str]) -> float:
    return sum(pred_of[c8] == gt[c8] for c8 in keys) / N


base_acc = acc({c8: sonnet[c8][0] for c8 in keys})
ceil_acc = acc({c8: fable[c8][0] for c8 in keys})
gap = ceil_acc - base_acc


def run(escalate: set[str], label: str) -> tuple[float, float]:
    """escalate = strong 으로 넘길 clip 집합. 나머지는 base(Sonnet) 유지."""
    pred = {c8: (fable[c8][0] if c8 in escalate else sonnet[c8][0]) for c8 in keys}
    a = acc(pred)
    rate = len(escalate) / N
    recov = (a - base_acc) / gap if gap else 0.0
    print(f"  {label:36s} esc {len(escalate):3d}/{N} ({rate:4.0%})  "
          f"정확도 {a:.1%}  격차회수 {recov:+.0%}")
    return a, rate


print("=" * 76)
print("★ P4 캐스케이드 시뮬 — base=Sonnet 4.6, strong=Fable 5 (인퍼런스 0)")
print("=" * 76)
print(f"base(Sonnet 단독)    : {base_acc:.1%}")
print(f"ceiling(Fable 단독)  : {ceil_acc:.1%}   격차 {gap:+.1%}p (회수 대상)")
print("-" * 76)

print("\n[R1] shedding-trigger — Sonnet 이 shedding 예측한 clip 만 escalate:")
r1 = {c8 for c8 in keys if sonnet[c8][0] == "shedding"}
run(r1, "Sonnet=shedding → Fable")

print("\n[R2] vulnerable-class — Sonnet 이 취약 4클래스 예측시 escalate:")
r2 = {c8 for c8 in keys if sonnet[c8][0] in VULN}
run(r2, "Sonnet∈{shed,defec,drink,unseen}")

print("\n[R3] conf-threshold sweep (대조군 — confidence 단독 분기):")
for t in [0.6, 0.7, 0.8, 0.9]:
    rt = {c8 for c8 in keys if sonnet[c8][1] < t}
    run(rt, f"Sonnet conf < {t}")

print("\n[R4] disagree(2-model) — Sonnet ≠ Opus 면 escalate (싼모델 2개):")
r4 = {c8 for c8 in keys if sonnet[c8][0] != opus[c8][0]}
run(r4, "Sonnet ≠ Opus → Fable")

print("\n[대조] random escalation (R1~R4 와 같은 비율, 결정론적 해시 샘플):")
# Math.random 불가 → clip8 hex 정렬 후 앞에서 k개 (결정론적 무작위 대용)
ordered = sorted(keys, key=lambda c: c[::-1])  # 역순 해시정렬 = GT와 무상관
for label, rset in [("R1급", r1), ("R2급", r2), ("R4급", r4)]:
    k = len(rset)
    run(set(ordered[:k]), f"random {k}건 ({k/N:.0%})")

print("\n" + "=" * 76)
print("★ 효율 판정 — 룰이 random 보다, 그리고 conf 단독보다 나은가")
print("=" * 76)
a1, _ = acc({c8: (fable[c8][0] if c8 in r1 else sonnet[c8][0]) for c8 in keys}), None
a1 = acc({c8: (fable[c8][0] if c8 in r1 else sonnet[c8][0]) for c8 in keys})
ar1 = acc({c8: (fable[c8][0] if c8 in set(ordered[:len(r1)]) else sonnet[c8][0]) for c8 in keys})
print(f"R1(shedding-trigger) {a1:.1%} vs random 동률비율 {ar1:.1%} → 표적 우위 {a1-ar1:+.1%}p")
print(f"→ 결론: 같은 호출 예산이면 '표적(shedding) 라우팅'이 무작위보다 격차를 더 회수하나 확인.")
