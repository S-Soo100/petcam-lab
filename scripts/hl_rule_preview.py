import os, statistics as st
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path("/Users/baek/petcam-lab/.env"))
from supabase import create_client
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
KST = timezone(timedelta(hours=9))
def fetch(table, cols, page=1000, **kw):
    rows, off = [], 0
    while True:
        q = sb.table(table).select(cols).range(off, off+page-1)
        for k,v in kw.items(): q = q.gte(k, v) if k.endswith("_gte") is False else q
        b = q.gte("created_at","2026-08-15").eq("status","ok").order("created_at", desc=True).execute().data if table=="gme_runs" else q.gte("started_at","2026-08-15").execute().data
        rows += b
        if len(b) < page: return rows
        off += page
runs = fetch("gme_runs", "clip_id,duration_sec,candidate_moving_sec_any_gecko,visible_sec,max_simultaneous_geckos,state_intervals,tracking_quality,camera_motion_sec,created_at")
clips = fetch("motion_clips", "id,camera_id,started_at,duration_sec")
cam = {c["id"]: c for c in clips}
latest = {}
for r in runs: latest.setdefault(r["clip_id"], r)
latest = {k:v for k,v in latest.items() if k in cam}
print("clips since 08-15", len(clips), "with ok GME run", len(latest))
def feats(r):
    iv = [x for x in (r["state_intervals"] or []) if x["state"]=="moving"]
    longest = max((x["end_sec"]-x["start_sec"] for x in iv), default=0.0)
    dur = float(r["duration_sec"] or 1)
    act = float(r["candidate_moving_sec_any_gecko"] or 0); vis = float(r["visible_sec"] or 0)
    tq = r["tracking_quality"] or {}
    return dict(act=act, longest=longest, n_mov=len(iv), vis_ratio=vis/dur, multi=(r["max_simultaneous_geckos"] or 0)>=2, frag=tq.get("fragmentation_count",0), detected=vis>0, dur=dur)
F = {cid: feats(r) for cid, r in latest.items()}
vals = lambda k: [f[k] for f in F.values()]
for k in ("act","longest","n_mov","vis_ratio","dur"):
    v = vals(k); print(f"{k:9s} median={st.median(v):.1f}  p75={st.quantiles(v,n=4)[2]:.1f}  p90={st.quantiles(v,n=10)[8]:.1f}  max={max(v):.1f}")
print("detected", Counter(vals("detected")), "multi", Counter(vals("multi")))
def rule(f, inc_act, inc_long, exc_act):
    if not f["detected"]: return "제외(미관측)"
    if f["act"]>=inc_act or f["longest"]>=inc_long or f["multi"]: return "포함"
    if f["act"]<exc_act: return "제외(거의 안 움직임)"
    return "애매"
for params in ((10,5,2),(8,4,2),(15,6,3),(5,3,1)):
    c = Counter(rule(f,*params) for f in F.values()); n=len(F)
    print(f"규칙 포함≥{params[0]}s or 최장≥{params[1]}s or 2마리 / 제외<{params[2]}s ->", {k: f"{v} ({v/n:.0%})" for k,v in c.items()})
# per camera per night volume for params (10,5,2)
nights = defaultdict(lambda: defaultdict(Counter))
for cid,f in F.items():
    c = cam[cid]; d = (datetime.fromisoformat(c["started_at"].replace("Z","+00:00")).astimezone(KST) - timedelta(hours=7)).date()
    nights[c["camera_id"][:8]][d][rule(f,10,5,2)] += 1
print("\n카메라별 밤당 평균 (규칙 10/5/2):")
for camid, days in nights.items():
    tot = Counter()
    for d, cnt in days.items(): tot.update(cnt)
    nd = len(days)
    print(f"  {camid} 밤 {nd}개: 영상 {sum(tot.values())/nd:.0f}/밤 ->", {k: f"{v/nd:.1f}/밤" for k,v in tot.items()})

print("\n--- 2마리 조건 뺀 버전 ---")
def rule2(f, inc_act, inc_long, exc_act):
    if not f["detected"]: return "제외(미관측)"
    if f["act"]>=inc_act or f["longest"]>=inc_long: return "포함"
    if f["act"]<exc_act: return "제외(거의 안 움직임)"
    return "애매"
for params in ((10,5,2),(15,6,2),(20,8,2)):
    c = Counter(rule2(f,*params) for f in F.values()); n=len(F)
    print(f"포함≥{params[0]}s or 최장≥{params[1]}s / 제외<{params[2]}s ->", {k: f"{v} ({v/n:.0%})" for k,v in c.items()})
print("\n--- 밤당 활동시간 상위 N개만 포함으로 잡으면 필요한 컷오프 (주 카메라 5b3ea7aa) ---")
per_night = defaultdict(list)
for cid,f in F.items():
    c = cam[cid]
    if not c["camera_id"].startswith("5b3ea7aa"): continue
    d = (datetime.fromisoformat(c["started_at"].replace("Z","+00:00")).astimezone(KST) - timedelta(hours=7)).date()
    per_night[d].append(f["act"])
for N in (5,10,20):
    cuts = [sorted(v, reverse=True)[N-1] for v in per_night.values() if len(v)>=N]
    print(f"  top{N}/밤 -> 활동시간 컷오프 중앙값 {st.median(cuts):.1f}s (최소 {min(cuts):.1f}s, 최대 {max(cuts):.1f}s)")
