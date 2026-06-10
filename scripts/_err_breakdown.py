"""배변 제외 시 남은 오답이 어디 뭉쳐 있나 — Fable 5 기준 + 모델 공통 패턴.

각 모델의 오답을 (GT클래스, 혼동방향)으로 분해.
배변/음수(시각정보 부재 = 모델불변)와 나머지(입력표현/GT noise)를 분리.
"""
from __future__ import annotations
import csv, json
from collections import defaultdict
from pathlib import Path

REPO = Path("/Users/baek/petcam-lab"); EXP = REPO / "experiments"; DS = REPO / "storage/dataset-203"
nn = {d.name: json.loads((d/"meta.json").read_text())["src"].split("__")[-1].split(".")[0]
      for d in (EXP/"eval-frames-claude").glob("sample-*") if d.is_dir()}
to_c8 = lambda s: nn.get(s, s.replace("sample-", ""))
def load(f):
    o = {}
    for ln in (EXP/"eval-frames-full"/f).read_text().splitlines():
        if ln.strip():
            r = json.loads(ln); o[to_c8(r["sample"])] = r["action"]
    return o
gt = {r["clip_id"][:8]: r["gt"] for r in csv.DictReader(open(DS/"manifest.csv"))}
M = {"Sonnet": load("sonnet46_blind.jsonl"), "Opus": load("opus48_blind.jsonl"), "Fable": load("fable5_blind.jsonl")}
keys = [c8 for c8 in gt if all(c8 in p for p in M.values())]
N = len(keys)

FLOOR = {"defecating", "drinking"}  # 시각정보 부재(벽응결수/순간이벤트) = 모델불변

def acc(p, subset):
    s = [c8 for c8 in keys if c8 in subset]
    return sum(p[c8]==gt[c8] for c8 in s), len(s)

print("="*68)
print("★ 분모 바꿔가며 정확도 — '고칠 수 있는 것'만 보면")
print("="*68)
allk = set(keys)
no_def = {c8 for c8 in keys if gt[c8] != "defecating"}
no_floor = {c8 for c8 in keys if gt[c8] not in FLOOR}
for name, p in M.items():
    a0 = acc(p, allk); a1 = acc(p, no_def); a2 = acc(p, no_floor)
    print(f"  {name:7s}  전체 {a0[0]:3d}/{a0[1]} {a0[0]/a0[1]:5.1%}   "
          f"배변제외 {a1[0]:3d}/{a1[1]} {a1[0]/a1[1]:5.1%}   "
          f"배변+음수제외 {a2[0]:3d}/{a2[1]} {a2[0]/a2[1]:5.1%}")

print("\n" + "="*68)
print("★ Fable 5 남은 오답 30건 — GT클래스별 + 혼동방향")
print("="*68)
p = M["Fable"]
err = defaultdict(list)
for c8 in keys:
    if p[c8] != gt[c8]:
        err[gt[c8]].append(p[c8])
floor_e = non_e = 0
for g in sorted(err, key=lambda x: -len(err[x])):
    conf = defaultdict(int)
    for pred in err[g]: conf[pred] += 1
    cs = ", ".join(f"→{k}×{v}" for k,v in sorted(conf.items(), key=lambda x:-x[1]))
    tag = "  [시각부재=모델불변]" if g in FLOOR else ""
    print(f"  {g:13s} {len(err[g]):2d}건  ({cs}){tag}")
    if g in FLOOR: floor_e += len(err[g])
    else: non_e += len(err[g])
print("-"*68)
print(f"  배변+음수(모델불변) 오답: {floor_e}건 / 나머지(고칠 여지): {non_e}건")
print(f"  → 나머지 오답의 혼동방향이 거의 '→moving' 이면 = 결정적순간(혀접촉/먹이타격)이")
print(f"     샘플 프레임에 안 잡힌 입력표현 문제(프롬프트/모델 아님).")

# 나머지 오답 중 →moving 비율
non_moving = sum(1 for g in err if g not in FLOOR for pp in err[g] if pp == "moving")
print(f"  실측: 나머지 {non_e}건 중 →moving = {non_moving}건")
