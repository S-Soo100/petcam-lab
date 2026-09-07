import os, json, gzip, math, statistics as st
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path("/Users/baek/petcam-lab/.env"))
from supabase import create_client
import boto3
from datetime import datetime, timezone, timedelta
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
s3 = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT"], aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
B = os.environ["R2_BUCKET"]; KST = timezone(timedelta(hours=9))
runs = sb.table("gme_runs").select("clip_id,permanent_artifact_key,candidate_moving_sec_any_gecko,visible_sec,duration_sec,max_simultaneous_geckos,tracking_quality,created_at").eq("status","ok").gte("created_at","2026-09-04").gt("visible_sec",0).limit(120).execute().data
clips = {c["id"]: c for c in sb.table("motion_clips").select("id,camera_id,started_at").in_("id",[r["clip_id"] for r in runs]).execute().data}
rows=[]
for r in runs:
    try:
        d = json.loads(gzip.decompress(s3.get_object(Bucket=B, Key=r["permanent_artifact_key"])["Body"].read()))
    except Exception as e:
        continue
    pts = sorted(d["track_points"], key=lambda p:(p["track_id"],p["timestamp_sec"]))
    by = {}
    for p in pts: by.setdefault(p["track_id"],[]).append(p)
    path=0.0; speeds=[]; cells=set(); areas=[]; centers=[]
    for tid, ps in by.items():
        prev=None
        for p in ps:
            x,y,w,h = p["bbox_norm"]; cx,cy = x+w/2, y+h/2; areas.append(w*h); centers.append((cx,cy,p["timestamp_sec"]))
            cells.add((int(cx*6), int(cy*6)))
            if prev and p["timestamp_sec"]-prev[2] <= 0.3:
                dd = math.hypot(cx-prev[0], cy-prev[1]); dt = p["timestamp_sec"]-prev[2]
                path += dd; speeds.append(dd/dt)
            prev=(cx,cy,p["timestamp_sec"])
    if not centers: continue
    centers.sort(key=lambda c:c[2])
    net = math.hypot(centers[-1][0]-centers[0][0], centers[-1][1]-centers[0][1])
    xs=[c[0] for c in centers]; ys=[c[1] for c in centers]
    spread = (max(xs)-min(xs))*(max(ys)-min(ys))
    mv = [i for i in d["intervals"] if i["state"]=="moving"]
    first_move = min((i["start_sec"] for i in mv), default=None)
    tq = r["tracking_quality"] or {}
    c = clips.get(r["clip_id"]); hour = datetime.fromisoformat(c["started_at"].replace("Z","+00:00")).astimezone(KST).hour if c else None
    rows.append(dict(clip=r["clip_id"][:8], cam=(c or {}).get("camera_id","")[:4], hour=hour,
        act=float(r["candidate_moving_sec_any_gecko"] or 0), vis=float(r["visible_sec"]), 
        path=round(path,3), net=round(net,3), spread=round(spread,3), cells=len(cells),
        vmax=round(max(speeds),3) if speeds else 0, area_ratio=round(max(areas)/max(min(areas),1e-4),2), area_mean=round(st.mean(areas),4),
        n_bursts=len(mv), first_move=first_move, multi=r["max_simultaneous_geckos"], frag=tq.get("fragmentation_count",0), gaps=tq.get("detection_gap_count",0)))
print("n", len(rows))
keys=["act","vis","path","net","spread","cells","vmax","area_ratio","area_mean","n_bursts","frag","gaps"]
def corr(a,b):
    if len(a)<3 or st.pstdev(a)==0 or st.pstdev(b)==0: return float('nan')
    ma,mb=st.mean(a),st.mean(b); return sum((x-ma)*(y-mb) for x,y in zip(a,b))/(len(a)*st.pstdev(a)*st.pstdev(b))
print("\n활동시간(act)과의 상관 (1에 가까우면 그냥 활동시간 복제):")
for k in keys[1:]:
    print(f"  {k:10s} r={corr([x['act'] for x in rows],[x[k] for x in rows]):.2f}   중앙값={st.median([x[k] for x in rows]):.3f}  p90={st.quantiles([x[k] for x in rows],n=10)[8]:.3f}")
print("\n활동시간은 낮은데(<5s) 다른 신호가 높은 영상 (예시 8개):")
low=[x for x in rows if x["act"]<5]
for k in ("path","spread","vmax","area_ratio"):
    top=sorted(low,key=lambda x:-x[k])[:2]
    for t in top: print(f"  by {k}: clip {t['clip']} cam {t['cam']} act={t['act']:.1f} path={t['path']} spread={t['spread']} vmax={t['vmax']} area_ratio={t['area_ratio']} bursts={t['n_bursts']}")
print("\n활동시간 높은데(>=10s) 이동 반경(spread)이 작은 영상 (제자리 움직임 후보):")
for t in sorted([x for x in rows if x["act"]>=10], key=lambda x:x["spread"])[:4]:
    print(f"  clip {t['clip']} act={t['act']:.1f} spread={t['spread']} net={t['net']} path={t['path']} frag={t['frag']}")
print("\n시간대별 영상 수:", {h: sum(1 for x in rows if x['hour']==h) for h in sorted({x['hour'] for x in rows if x['hour'] is not None})})
