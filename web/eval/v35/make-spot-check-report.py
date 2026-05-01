"""dish-presence oracle 결과 → 사람 spot check용 markdown 리포트.

스펙: specs/feature-vlm-feeding-postfilter.md §2.1 (oracle + 사람 spot check)

입력:  web/eval/v35/dish-presence-oracle.jsonl
출력:  web/eval/v35/dish-presence-spot-check.md

목적: 사용자가 영상 직접 안 봐도 reasoning 훑으면서 의심 가는 케이스만 추려낼 수 있게.
의심 케이스 = oracle 결정이 GT/raw와 어긋나거나, confidence 낮거나, reasoning에 모호 표현.
"""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ORACLE_PATH = ROOT / "dish-presence-oracle.jsonl"
OUT_PATH = ROOT / "dish-presence-spot-check.md"


def load_oracle(p: Path) -> list[dict]:
    out = []
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            if r.get("ok"):
                out.append(r)
        except json.JSONDecodeError:
            pass
    return out


def is_suspicious(rec: dict) -> tuple[bool, str]:
    """의심 케이스 휴리스틱."""
    gt = rec.get("gt_action")
    raw = rec.get("raw_action")
    dish = rec.get("dish_present")
    lick = rec.get("licking_behavior")
    conf = rec.get("confidence", 1.0)

    # 1. confidence 0.7 미만 — oracle 자체 모호
    if conf < 0.7:
        return True, f"low confidence {conf:.2f}"

    # 2. GT가 명확한 행동인데 시그널이 어긋남
    if gt == "eating_paste" and not dish:
        return True, "GT=eating_paste지만 dish=false (사료 안 보임?)"
    if gt == "drinking" and dish:
        return True, "GT=drinking인데 dish=true (사료 보이는데 물 마심?)"
    if gt in ("eating_paste", "drinking") and not lick:
        return True, "GT가 먹기/마시기인데 licking=false"
    if gt == "moving" and lick:
        return True, "GT=moving인데 licking=true"

    return False, ""


def main() -> None:
    if not ORACLE_PATH.exists():
        raise SystemExit(f"oracle 결과 없음: {ORACLE_PATH}")

    records = load_oracle(ORACLE_PATH)
    print(f"oracle 결과 {len(records)}건 로드")

    # 분포 통계
    n_dish_true = sum(1 for r in records if r["dish_present"])
    n_lick_true = sum(1 for r in records if r["licking_behavior"])
    avg_conf = sum(r["confidence"] for r in records) / len(records) if records else 0

    # GT × oracle 매트릭스
    sig_dist = Counter()
    for r in records:
        sig_dist[(r["gt_action"], r["dish_present"], r["licking_behavior"])] += 1

    # 의심 케이스 분류
    suspicious = []
    clean = []
    for r in records:
        flag, reason = is_suspicious(r)
        if flag:
            suspicious.append((r, reason))
        else:
            clean.append(r)

    # markdown 생성
    lines = [
        "# dish-presence oracle spot check report",
        "",
        "> 스펙: `specs/feature-vlm-feeding-postfilter.md §2.1`. oracle = Gemini 2.5 Pro.",
        "> 의심 케이스만 영상 직접 확인하고, 결정 다르면 알려줘 → GT 수정 반영.",
        "",
        "## 1. 분포 요약",
        "",
        f"- 전체: **{len(records)}건**",
        f"- dish=true: {n_dish_true}건 / dish=false: {len(records) - n_dish_true}건",
        f"- licking=true: {n_lick_true}건 / licking=false: {len(records) - n_lick_true}건",
        f"- 평균 confidence: {avg_conf:.2f}",
        f"- 의심 케이스: **{len(suspicious)}건** (영상 확인 권장)",
        f"- 클린 (oracle 결정 그대로 GT 채택 후보): {len(clean)}건",
        "",
        "## 2. (gt_action, dish, licking) 매트릭스",
        "",
        "| GT | dish | licking | n |",
        "|---|---|---|---|",
    ]
    for (g, d, l), n in sorted(sig_dist.items(), key=lambda x: (x[0][0], -x[1])):
        lines.append(f"| {g} | {'✓' if d else '✗'} | {'✓' if l else '✗'} | {n} |")
    lines.append("")

    # 의심 케이스 상세
    lines.append(f"## 3. 의심 케이스 ({len(suspicious)}건) — **영상 확인 부탁**")
    lines.append("")
    if not suspicious:
        lines.append("_없음._")
    else:
        for rec, reason in suspicious:
            lines.append(f"### {rec['clip_id'][:8]} — {reason}")
            lines.append("")
            lines.append(f"- GT: `{rec['gt_action']}`  /  raw v3.5: `{rec['raw_action']}`")
            d = "✓" if rec["dish_present"] else "✗"
            l = "✓" if rec["licking_behavior"] else "✗"
            lines.append(f"- oracle: dish={d} / licking={l} / conf={rec['confidence']:.2f}")
            lines.append(f"- reasoning: _{rec['reasoning']}_")
            lines.append(f"- 영상: `{rec.get('clip_id')}` (web/eval에서 clip_id로 file_path 조회)")
            lines.append("")

    # 클린 케이스 (간단 표)
    lines.append(f"## 4. 클린 케이스 ({len(clean)}건)")
    lines.append("")
    lines.append("| clip_id (8) | GT | raw | dish | lick | conf | reasoning |")
    lines.append("|---|---|---|---|---|---|---|")
    for rec in clean[:50]:
        d = "✓" if rec["dish_present"] else "✗"
        l = "✓" if rec["licking_behavior"] else "✗"
        rs = rec["reasoning"][:80].replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {rec['clip_id'][:8]} | {rec['gt_action']} | {rec['raw_action']} "
            f"| {d} | {l} | {rec['confidence']:.2f} | {rs} |"
        )
    if len(clean) > 50:
        lines.append(f"| ... | (총 {len(clean)}건 중 50건만 표시) | | | | | |")

    OUT_PATH.write_text("\n".join(lines) + "\n")
    print(f"리포트 산출: {OUT_PATH}")
    print(f"의심 케이스: {len(suspicious)}건 / 클린: {len(clean)}건")


if __name__ == "__main__":
    main()
