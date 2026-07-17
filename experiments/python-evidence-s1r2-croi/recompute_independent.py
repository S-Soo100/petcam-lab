# 독립 재계산 — harness(aggregate/percentile/evaluate_*) import 금지. stdlib 만.
import json, hashlib, statistics
RAW="/Users/baek-end/pe-s1-benchmark/experiments/python-evidence-s1r2-croi/raw_results.jsonl"
raw_bytes=open(RAW,"rb").read()
print("raw_sha256:", hashlib.sha256(raw_bytes).hexdigest())
recs=[json.loads(l) for l in raw_bytes.decode().splitlines() if l.strip()]
print("total_records:", len(recs))
warm=[r for r in recs if r["is_warmup"]]
err=[r for r in recs if r["error_code"] is not None]
print("warmup_records:", len(warm), "| error_records:", len(err))
# 성공 measured CROI/mps/cold
succ=[r for r in recs if (not r["is_warmup"] and r["error_code"] is None and isinstance(r["e2e_s"],(int,float)) and r["e2e_s"]>0 and r["condition"]=="CROI" and r["device"]=="mps" and r["cache_mode"]=="cold_independent")]
keys=[(r["clip_id"],r["condition"],r["device"],r["cache_mode"],r["repeat"]) for r in succ]
kset=set(keys)
dups=[k for k in kset if keys.count(k)>1]
print("successful_measured:", len(succ), "| distinct_keys:", len(kset), "| duplicates:", len(dups))
# expected 96 = warmup clip_ids(32) x repeat 1..3
clip_ids=sorted({r["clip_id"] for r in recs if r["condition"]=="CROI"})
expected={(c,"CROI","mps","cold_independent",rp) for c in clip_ids for rp in (1,2,3)}
print("clip_ids:", len(clip_ids), "| expected_keys:", len(expected))
print("missing:", len(expected-kset), "| unexpected:", len(kset-expected))
# 독립 percentile — numpy 없이 linear interpolation (harness 와 다른 구현)
def pct(data,p):
    d=sorted(data); n=len(d)
    if n==1: return d[0]
    r=(p/100)*(n-1); lo=int(r); frac=r-lo
    return d[lo] if lo+1>=n else d[lo]+frac*(d[lo+1]-d[lo])
e2e=[r["e2e_s"] for r in succ]
p50=pct(e2e,50); p95=pct(e2e,95)
cap=3600.0/p95; ratio=cap/80.0
print("p50_s: %.6f | p95_s: %.6f" % (p50,p95))
print("capacity_per_hour: %.4f | ratio_vs_80: %.4f | gate_160_pass: %s" % (cap,ratio,cap>=160))
print("peak_rss_bytes: %d (%.3f GiB) | rss_pass_4GiB: %s" % (max(r["peak_rss_bytes"] for r in succ), max(r["peak_rss_bytes"] for r in succ)/1024**3, max(r["peak_rss_bytes"] for r in succ)<=4*1024**3))
print("peak_temp_bytes: %d (%.3f MiB) | disk_pass_2GiB: %s" % (max(r["temp_peak_bytes"] for r in succ), max(r["temp_peak_bytes"] for r in succ)/1024**2, max(r["temp_peak_bytes"] for r in succ)<=2*1024**3))
