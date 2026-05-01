"""multi-track 결과 분석 — Track × 그룹 매트릭스 + baseline 대비 Δ.

입력:
  - error-set-154.jsonl (오답 26건 + GT)
  - multi-track-zeroshot.jsonl (Track A~E inference 결과)

출력 (콘솔):
  1) Track별 전체 정확도 (26건 중)
  2) Confusion-pair 그룹 × Track 매트릭스
  3) Track별 confusion 변화 (어느 클래스로 흘렀나)
  4) Baseline (Track A) 대비 Δ — 각 Track의 recovered/broken/held
  5) Best track 추천 + 근거
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ERROR_PATH = ROOT / "error-set-154.jsonl"
MT_PATH = ROOT / "multi-track-zeroshot.jsonl"

# Confusion pair → 그룹 매핑 (Phase 1 결과 기반)
def assign_group(gt: str, raw: str) -> str:
    if (gt, raw) == ("moving", "eating_paste"): return "G1: 그릇 머무름→eating환각"
    if (gt, raw) == ("defecating", "moving"): return "G2: 배변 자세 인식실패"
    if (gt, raw) == ("defecating", "drinking"): return "G2: 배변 자세 인식실패"
    if (gt, raw) == ("drinking", "eating_paste"): return "G3: drinking 단서부족"
    if (gt, raw) == ("drinking", "moving"): return "G3: drinking 단서부족"
    if (gt, raw) == ("eating_prey", "moving"): return "G4: 사냥 동작 평범화"
    if (gt, raw) == ("moving", "shedding"): return "G5: shedding 경계"
    if (gt, raw) == ("shedding", "moving"): return "G5: shedding 경계"
    return f"기타 ({gt}→{raw})"


def load_errors() -> list[dict]:
    out = []
    for line in ERROR_PATH.read_text().splitlines():
        if not line.strip(): continue
        out.append(json.loads(line))
    return out


def load_results() -> dict:
    """{(clip_id, track): record}."""
    out = {}
    if not MT_PATH.exists():
        return out
    for line in MT_PATH.read_text().splitlines():
        if not line.strip(): continue
        try:
            r = json.loads(line)
            if r.get("ok"):
                out[(r["clip_id"], r["track"])] = r
        except Exception:
            pass
    return out


def main() -> None:
    errors = load_errors()
    results = load_results()
    tracks = ["A", "B", "C", "D", "E"]

    # 그룹 할당
    for e in errors:
        e["group"] = assign_group(e["gt"], e["raw"])

    print(f"오답셋: {len(errors)}건 / 결과 records: {len(results)}")
    expected = len(errors) * len(tracks)
    print(f"기대 호출: {expected} / 실제: {len(results)} ({'완료' if len(results)>=expected else f'미완료 -{expected-len(results)}'})")
    print()

    # 1. Track별 전체 정확도 (오답셋 26건 중)
    print("=" * 70)
    print("== Track별 전체 정확도 (오답 26건 중 GT 일치) ==")
    print("=" * 70)
    track_acc = {}
    track_correct = {}
    for t in tracks:
        correct = 0
        n = 0
        for e in errors:
            r = results.get((e["clip_id"], t))
            if not r: continue
            n += 1
            if r["action"] == e["gt"]:
                correct += 1
        track_acc[t] = (correct, n)
        track_correct[t] = {e["clip_id"] for e in errors
                            if (r := results.get((e["clip_id"], t)))
                            and r["action"] == e["gt"]}
        pct = correct/n*100 if n else 0
        print(f"  Track {t}: {correct}/{n} = {pct:.1f}%")
    print()

    # 2. 그룹 × Track 매트릭스
    print("=" * 70)
    print("== 그룹 × Track 매트릭스 (정답 / 그룹내 총건수) ==")
    print("=" * 70)
    groups = sorted({e["group"] for e in errors})
    print(f"{'group':<32} | " + " | ".join(f" {t} " for t in tracks))
    print("-" * 70)
    group_track = {}  # {(group, track): (correct, total)}
    for g in groups:
        clips_in_g = [e for e in errors if e["group"] == g]
        row = [f"{g[:30]:<32}"]
        for t in tracks:
            correct = sum(1 for e in clips_in_g
                          if (r := results.get((e["clip_id"], t)))
                          and r["action"] == e["gt"])
            n = sum(1 for e in clips_in_g if results.get((e["clip_id"], t)))
            group_track[(g, t)] = (correct, n)
            row.append(f"{correct}/{len(clips_in_g)}")
        print(" | ".join(row))
    print()

    # 3. Track별 prediction 분포 (어디로 흘렀나)
    print("=" * 70)
    print("== Track별 prediction 분포 ==")
    print("=" * 70)
    for t in tracks:
        pred_dist = Counter()
        for e in errors:
            r = results.get((e["clip_id"], t))
            if r: pred_dist[r["action"]] += 1
        total = sum(pred_dist.values())
        if total:
            print(f"  Track {t} (n={total}): " + ", ".join(f"{k}={v}" for k, v in pred_dist.most_common()))
    print()

    # 4. Baseline (A) 대비 Δ
    print("=" * 70)
    print("== Baseline (Track A) 대비 Δ ==")
    print("=" * 70)
    a_set = track_correct["A"]
    for t in tracks:
        if t == "A":
            print(f"  Track A: baseline ({len(a_set)}건 정답)")
            continue
        t_set = track_correct[t]
        recovered = t_set - a_set  # A는 틀렸지만 t는 맞춤
        broken = a_set - t_set     # A는 맞췄지만 t는 틀림
        held = a_set & t_set
        delta = len(t_set) - len(a_set)
        sign = "+" if delta >= 0 else ""
        print(f"  Track {t}: {len(t_set)}건 정답 ({sign}{delta} vs A)")
        print(f"    recovered: {len(recovered)}건 (A틀림→{t}맞춤)  {sorted(c[:8] for c in recovered)}")
        print(f"    broken   : {len(broken)}건 (A맞춤→{t}틀림)   {sorted(c[:8] for c in broken)}")
        print(f"    held     : {len(held)}건")
        print()

    # 5. 그룹별 베스트 Track
    print("=" * 70)
    print("== 그룹별 베스트 Track ==")
    print("=" * 70)
    for g in groups:
        clips_in_g = [e for e in errors if e["group"] == g]
        scores = []
        for t in tracks:
            correct = sum(1 for e in clips_in_g
                          if (r := results.get((e["clip_id"], t)))
                          and r["action"] == e["gt"])
            scores.append((t, correct))
        scores.sort(key=lambda x: -x[1])
        top = scores[0]
        print(f"  {g} (n={len(clips_in_g)}): 1위 Track {top[0]} ({top[1]}건)")
        print(f"    전체 순위: {scores}")
    print()

    # 6. 추천: 전체 베스트 Track + 회귀 가드 후보
    best_track = max(track_acc.keys(), key=lambda t: track_acc[t][0])
    bc, bn = track_acc[best_track]
    print("=" * 70)
    print(f"== 추천 ==")
    print("=" * 70)
    print(f"  전체 베스트: Track {best_track} ({bc}/{bn} = {bc/bn*100:.1f}%)")
    print(f"  Phase 4 회귀 가드: 전체 154건에 Track {best_track} 호출 → broken/recovered 측정")
    print(f"  채택 조건: (오답셋 +Δ AND broken@128 ≤ 2) 둘 다 만족")


if __name__ == "__main__":
    main()
