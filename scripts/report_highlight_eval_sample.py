"""하이라이트 봉인 평가 표본 보고 (2.6.1 전환 준비 Task 4). 읽기 전용.

1) 층별 표: n · 확정 · 규칙 O · 사람 O · O→O/O→X/X→O/X→X (fn_eval_sample_report)
2) 모집단 가중 수용률·놓침률 — 층 비중은 표본 JSON 의 후보 수(candidates)로 가중. 단순 합산 회수율은 내지 않는다.
3) 임계값 후보표 — 같은 표본의 사람 답에 대해 (activity_sec_gte, longest_sec_gte) 후보별 O 수용률·X 놓침률.
   기본 후보 8/4 · 10/5(현행) · 12/6. `--contract <algo> <detector>` 로 다른 GME 계약(2.6.1)의 숫자로 다시 계산할 수 있다
   (그 계약의 run 이 표본 영상에 있어야 함). 이게 전환 당일 규칙 v1 근거다.

사용:
  uv run python scripts/report_highlight_eval_sample.py --sample-id eval-2026-09
  uv run python scripts/report_highlight_eval_sample.py --sample-id eval-2026-09 --contract gme-motion-v1 <detector64> --candidates 8/4 10/5 12/6
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
load_dotenv(Path("/Users/baek/petcam-lab/.env"))
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
ENGINE = "gme-shadow-v1"


def pct(n: int, d: int) -> str:
    return "-" if d == 0 else f"{100 * n / d:.0f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample-id", required=True)
    ap.add_argument("--contract", nargs=2, metavar=("ALGO", "DETECTOR"), help="임계값 후보표에 쓸 GME 계약(기본: 표본 JSON 의 계약)")
    ap.add_argument("--candidates", nargs="*", default=["8/4", "10/5", "12/6"], help="activity/longest 초 후보")
    a = ap.parse_args()
    sample_path = ROOT / "experiments" / "highlight-eval-sample" / f"{a.sample_id}.json"
    sample = json.loads(sample_path.read_text())
    cand_weight = {(s["camera_id"][:8] + ":" + s["initial"]): s["candidates"] for s in sample["strata"]}
    algo, det = a.contract or (sample["contract"]["algorithm_version"], sample["contract"]["detector_identity"])

    lines: list[str] = [f"# 표본 {a.sample_id} 보고 — {datetime.now(timezone.utc).isoformat(timespec='minutes')}", ""]
    # 1) 층별
    rows = sb.rpc("fn_eval_sample_report", {"p_sample_id": a.sample_id}).execute().data
    lines += ["## 층별 (최초 initial verdict 기준)", "", "| 층 | n | 확정 | 규칙O | 사람O | O→O | O→X | X→O | X→X |", "|---|---|---|---|---|---|---|---|---|"]
    tot = {k: 0 for k in ("total", "labeled", "rule_o", "human_o", "o_to_o", "o_to_x", "x_to_o", "x_to_x")}
    w_acc_n = w_acc_d = w_miss_n = w_miss_d = 0.0
    for r in rows:
        lines.append(f"| {r['stratum']} | {r['total']} | {r['labeled']} | {r['rule_o']} | {r['human_o']} | {r['o_to_o']} | {r['o_to_x']} | {r['x_to_o']} | {r['x_to_x']} |")
        for k in tot:
            tot[k] += int(r[k])
        w = cand_weight.get(r["stratum"], 0)
        labeled = int(r["labeled"])
        if labeled and w:
            if r["stratum"].endswith(":O"):
                w_acc_n += w * int(r["o_to_o"]) / labeled; w_acc_d += w
            else:
                w_miss_n += w * int(r["x_to_o"]) / labeled; w_miss_d += w
    lines.append(f"| **합** | {tot['total']} | {tot['labeled']} | {tot['rule_o']} | {tot['human_o']} | {tot['o_to_o']} | {tot['o_to_x']} | {tot['x_to_o']} | {tot['x_to_x']} |")
    lines += ["", f"- 표본 단순 O 수용률 {pct(tot['o_to_o'], tot['o_to_o'] + tot['o_to_x'])} · X 놓침률 {pct(tot['x_to_o'], tot['x_to_o'] + tot['x_to_x'])}",
              f"- **모집단 가중** O 수용률 {pct(round(w_acc_n), round(w_acc_d)) if w_acc_d else '-'} · X 놓침률 {pct(round(w_miss_n), round(w_miss_d)) if w_miss_d else '-'} (층 비중 = 후보 수, 미확정 층 제외)",
              "- 단순 합산 회수율은 보고하지 않는다(표본이 O/X 를 같은 수로 뽑아 모집단과 다름).", ""]

    # 3) 임계값 후보표: 표본 영상마다 사람 답 + 계약의 features
    lines += [f"## 임계값 후보표 — 계약 {algo} / {det[:12]}…", "", "| 후보 (activity≥/longest≥) | 규칙O | O 수용률 | X 놓침률 | 사람O 중 규칙O(회수) |", "|---|---|---|---|---|"]
    cands = [tuple(float(x) for x in c.split("/")) for c in a.candidates]
    per_clip: list[tuple[bool, dict]] = []  # (human_o, features)
    missing = 0
    for it in sample["items"]:
        args = {"p_clip_id": it["clip_id"], "p_engine_schema_version": ENGINE, "p_algorithm_version": algo, "p_detector_identity": det}
        cur = sb.rpc("fn_highlight_current", args).execute().data[0]
        if cur["source"] != "human":
            continue
        ini = sb.rpc("fn_highlight_initial", args).execute().data[0]
        if ini["status"] != "decided" or not ini["features"]:
            missing += 1
            continue
        per_clip.append((bool(cur["value"]), ini["features"]))
    for act, lon in cands:
        rule_o = [(f.get("visible_sec", 0) or 0) > 0 and (float(f["activity_sec"]) >= act or float(f["longest_moving_sec"]) >= lon) for _, f in per_clip]
        oo = sum(1 for (h, _), r in zip(per_clip, rule_o) if r and h)
        ox = sum(1 for (h, _), r in zip(per_clip, rule_o) if r and not h)
        xo = sum(1 for (h, _), r in zip(per_clip, rule_o) if not r and h)
        xx = sum(1 for (h, _), r in zip(per_clip, rule_o) if not r and not h)
        lines.append(f"| {act:g}/{lon:g} | {oo + ox} | {pct(oo, oo + ox)} ({oo}/{oo + ox}) | {pct(xo, xo + xx)} ({xo}/{xo + xx}) | {pct(oo, oo + xo)} ({oo}/{oo + xo}) |")
    lines += ["", f"- 사람 확정 있는 표본 {len(per_clip)}건 기준 (계약 run 없어 제외 {missing}건). 표본은 O/X 균형 추출이라 회수율 열은 참고용.", ""]

    out = sample_path.with_name(f"{a.sample_id}-report-{datetime.now(timezone.utc).date().isoformat()}.md")
    out.write_text("\n".join(lines))
    print("\n".join(lines))
    print("wrote", out.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
