"""C 레버 — 캐스케이드 시뮬 (base=Sonnet 4.6, strong=Opus 4.8, 인퍼런스 0).

opus-sonnet-186 의 blind 예측(적응형 frames@1080, v4.0)을 오프라인 결합.
base=Sonnet 을 기본, 일부 clip 만 strong=Opus 로 "에스컬레이션" → (정확도, 호출률) 곡선.

핵심 질문:
  1. Opus 호출 X% 로 격차(85.5→88.7, +3.2%p = 6건) 를 몇 % 회수하나 (표적 > random?)
  2. eating_prey 가 Opus 에스컬로 회수되나 (B2 스코프 결정 — REPORT §7-2 정성의 정량 확인)

라우팅 룰 (escalate 결정은 base=Sonnet 출력만으로 — 실제 캐스케이드 제약):
  R1 shedding-trigger : Sonnet=shedding 예측 → Opus (P1b IR 과탐 표적)
  R2 vulnerable-class : Sonnet ∈ {shedding, drinking, eating_prey, unseen} → Opus
                        (v4.0: defecating 폐기 → eating_prey 추가, next-session 지시)
  R3 conf-threshold   : Sonnet conf < t → Opus (대조군, t sweep)
대조: random escalation (같은 비율, 결정론적 해시 — Math.random 불가).
⚠️ R4(2-model disagree)는 strong 자신이 Opus 라 제3판정자 부재 → 186 에선 생략 (TEST-SHEET §3).

실행: PYTHONPATH=. uv run python scripts/_sim_cascade_opus.py
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXP = REPO / "experiments" / "opus-sonnet-186"
V40RAW = REPO / "experiments" / "v40-regression" / "raw"

FEEDING = {"drinking", "eating_paste"}
VULN = {"shedding", "drinking", "eating_prey", "unseen"}
CLASSES = ["moving", "shedding", "hand_feeding", "eating_prey", "eating_paste", "drinking", "unseen"]


# ── 로드 (채점 SOT _score_opus_sonnet.py 와 동일: id 문자열 join) ──────────────
samples = json.loads((EXP / "sample_list.json").read_text())
gt = {s["id"]: s["gt"] for s in samples}

opus: dict[str, tuple[str, float]] = {}
for r in json.loads((EXP / "raw" / "opus.json").read_text()):
    opus[r["sample"]] = (r["action"], r.get("confidence", 0.0))

sonnet: dict[str, tuple[str, float]] = {}
for f in sorted(V40RAW.glob("v4.0_g*.json")):
    for r in json.loads(f.read_text()).get("results", []):
        sonnet[r["sample"]] = (r["action"], r.get("confidence", 0.0))
for r in json.loads((EXP / "raw" / "sonnet0615.json").read_text()):
    sonnet[r["sample"]] = (r["action"], r.get("confidence", 0.0))

keys = [i for i in gt if i in opus and i in sonnet]
N = len(keys)


# ── 채점 ──────────────────────────────────────────────────────────────────
def raw_hit(pred: str, g: str) -> bool:
    return pred == g


def boundary_hit(pred: str, g: str) -> bool:
    if g in FEEDING:
        return pred in FEEDING
    return pred == g


def acc(pred_of: dict[str, str], scorer=raw_hit) -> float:
    return sum(scorer(pred_of[k], gt[k]) for k in keys) / N


base_pred = {k: sonnet[k][0] for k in keys}
ceil_pred = {k: opus[k][0] for k in keys}
base_acc = acc(base_pred)
ceil_acc = acc(ceil_pred)
gap = ceil_acc - base_acc
gap_n = round(gap * N)


def run(escalate: set[str], label: str) -> tuple[float, float]:
    """escalate = Opus 로 넘길 clip 집합. 나머지는 base(Sonnet) 유지."""
    pred = {k: (opus[k][0] if k in escalate else sonnet[k][0]) for k in keys}
    a = acc(pred)
    b = acc(pred, boundary_hit)
    rate = len(escalate) / N
    recov_n = round((a - base_acc) * N)
    recov_pct = (a - base_acc) / gap if gap else 0.0
    print(f"  {label:34s} esc {len(escalate):3d}/{N} ({rate:4.0%})  "
          f"raw {a:.1%}  급여경계 {b:.1%}  격차회수 {recov_n:+d}/{gap_n} ({recov_pct:+.0%})")
    return a, rate


# 결정론적 "무작위" — clip id 역순정렬(GT 무상관). Math.random 불가.
ordered = sorted(keys, key=lambda c: c[::-1])


def random_set(k: int) -> set[str]:
    return set(ordered[:k])


print("=" * 84)
print("★ C 캐스케이드 시뮬 — base=Sonnet 4.6, strong=Opus 4.8 (186, v4.0, 인퍼런스 0)")
print("=" * 84)
print(f"base(Sonnet 단독)   : raw {base_acc:.1%} ({round(base_acc*N)}/{N})")
print(f"ceiling(Opus 단독)  : raw {ceil_acc:.1%} ({round(ceil_acc*N)}/{N})   "
      f"격차 {gap:+.1%}p = {gap_n}건 (회수 대상)")
print("-" * 84)

print("\n[R1] shedding-trigger — Sonnet=shedding 예측만 Opus:")
r1 = {k for k in keys if sonnet[k][0] == "shedding"}
run(r1, "Sonnet=shedding → Opus")
print(f"     └ 같은비율 random 대조:")
run(random_set(len(r1)), f"random {len(r1)}건")

print("\n[R2] vulnerable-class — Sonnet ∈ {shed,drink,prey,unseen} 예측만 Opus:")
r2 = {k for k in keys if sonnet[k][0] in VULN}
run(r2, "Sonnet∈VULN → Opus")
print(f"     └ 같은비율 random 대조:")
run(random_set(len(r2)), f"random {len(r2)}건")

print("\n[R3] conf-threshold sweep (대조군 — confidence 단독 분기):")
for t in [0.6, 0.7, 0.8, 0.9, 0.95]:
    rt = {k for k in keys if sonnet[k][1] < t}
    run(rt, f"Sonnet conf < {t}")

print("\n[참고] 전량 Opus (escalate 100%) = ceiling:")
run(set(keys), "all → Opus")

# ── discordant 진단 (회수 대상이 어느 클래스에 모이나 = 라우팅 효율 근거) ───────
print("\n" + "=" * 84)
print("★ discordant 진단 — Opus 가 회수하는 격차가 어느 클래스에 집중되나")
print("=" * 84)
disc = [k for k in keys if sonnet[k][0] != opus[k][0]]
opus_only = [k for k in disc if opus[k][0] == gt[k] and sonnet[k][0] != gt[k]]   # 회수 대상
sonnet_only = [k for k in disc if sonnet[k][0] == gt[k] and opus[k][0] != gt[k]]  # 에스컬 시 손실
both_wrong = [k for k in disc if opus[k][0] != gt[k] and sonnet[k][0] != gt[k]]
print(f"discordant {len(disc)}건 = Opus만정답 {len(opus_only)} / Sonnet만정답 {len(sonnet_only)} / 둘다오답 {len(both_wrong)}")
print(f"\n회수 대상 (Opus만 정답) {len(opus_only)}건 — GT 클래스 분포:")
from collections import Counter
for c, n in Counter(gt[k] for k in opus_only).most_common():
    sn_preds = ", ".join(sorted({sonnet[k][0] for k in opus_only if gt[k] == c}))
    print(f"  GT={c:13} {n}건  (Sonnet 오답→ {sn_preds})")
print(f"\n에스컬 시 손실 위험 (Sonnet만 정답) {len(sonnet_only)}건:")
for k in sorted(sonnet_only):
    print(f"  {k} GT={gt[k]:13} Sonnet={sonnet[k][0]:13} → Opus={opus[k][0]} (오답)")

# ── 클래스별 회수 분석 (eating_prey = B2 스코프, drinking = 교차) ─────────────
print("\n" + "=" * 84)
print("★ 클래스별 Opus 회수 분석 (B2 스코프 — D2)")
print("=" * 84)
for c in ["eating_prey", "drinking"]:
    cids = [k for k in keys if gt[k] == c]
    s_wrong = [k for k in cids if sonnet[k][0] != c]
    o_recov = [k for k in s_wrong if opus[k][0] == c]
    s_ok = sum(1 for k in cids if sonnet[k][0] == c)
    o_ok = sum(1 for k in cids if opus[k][0] == c)
    pct = len(o_recov) / len(s_wrong) if s_wrong else 0.0
    print(f"\n{c} (GT {len(cids)}건): Sonnet {s_ok}/{len(cids)} · Opus {o_ok}/{len(cids)}")
    print(f"  Sonnet 오답 {len(s_wrong)}건 중 Opus 회수 {len(o_recov)}건 ({pct:.0%})")
    for k in sorted(s_wrong):
        mark = "✓회수" if opus[k][0] == c else "✗유지"
        print(f"    [{mark}] {k} Sonnet={sonnet[k][0]:13} Opus={opus[k][0]}")
