"""다전략 local VLM 평가 — 97 P0 clip 정확도 90% 검증.

목표: Mac mini local LLM으로 Gemini Track A 대체 가능성 검증.
평가셋: 159건 중 moving 제외 P0 라벨만 (97건).
출력: 전략별 jsonl + summary + per-class confusion.

전략:
- A: 새 vision 모델 (moondream/minicpm-v/llama3.2-vision) + 기본 prompt + 60-frame contact sheet
- B: gemma3:4b + anti-collapse prompt + 60-frame contact sheet
- C: gemma3:4b + multi-frame (8 frame multi-image input)
- D: 2-stage cascade (Stage 1: P0 binary, Stage 2: specialized prompt)

실행:
    uv run python scripts/eval_multi_strategy.py --strategy B --model gemma3:4b
    uv run python scripts/eval_multi_strategy.py --strategy A --model moondream:1.8b
    uv run python scripts/eval_multi_strategy.py --strategy C --model gemma3:4b
    uv run python scripts/eval_multi_strategy.py --strategy D --model gemma3:4b
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("eval_multi_strategy")

EVAL_JSONL = REPO_ROOT / "storage" / "local-track-a" / "eval" / "local-track-a-eval.jsonl"
ARTIFACTS_DIR = REPO_ROOT / "storage" / "local-track-a" / "eval" / "artifacts"
OUT_BASE = REPO_ROOT / "storage" / "track-a-eval" / "multi-strategy"
PILOT_FRAMES_DIR = REPO_ROOT / "storage" / "track-a-eval" / "pilot-frames"

OLLAMA_URL = "http://127.0.0.1:11434"

# 9 raw 라벨
BEHAVIOR_CLASSES = [
    "eating_paste", "eating_prey", "drinking", "defecating",
    "shedding", "basking", "hiding", "moving", "unseen",
]
P0_LABELS = {"drinking", "eating_paste", "shedding", "defecating", "eating_prey"}


@dataclass(frozen=True, slots=True)
class EvalRow:
    clip_id: str
    gt_action: str
    r2_key: str
    species_id: str | None
    contact_sheet_path: str


def load_p0_eval_set() -> list[EvalRow]:
    """159건 jsonl에서 moving 제외 P0 라벨만 추출."""
    rows: list[EvalRow] = []
    for line in EVAL_JSONL.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not rec.get("ok"):
            continue
        gt = rec["gt_action"]
        # hiding/unseen은 너무 적지만 P0 (drinking/eating_paste/shedding/defecating/eating_prey)만이 아니라
        # moving만 제외하는 모든 라벨 포함
        if gt == "moving":
            continue
        clip_id = rec["clip_id"]
        sheet = ARTIFACTS_DIR / f"{clip_id}.contact-sheet.jpg"
        rows.append(
            EvalRow(
                clip_id=clip_id,
                gt_action=gt,
                r2_key=rec["r2_key"],
                species_id=rec.get("species_id"),
                contact_sheet_path=str(sheet),
            )
        )
    rows.sort(key=lambda r: r.clip_id)
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Prompt 변종
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_BASELINE = """You are classifying a reptile (crested gecko) petcam contact sheet.
The sheet contains evenly sampled frames from one 60 second motion clip.
Return exactly one JSON object, with no markdown.

Choose one label from:
eating_paste, eating_prey, drinking, defecating, shedding, basking, hiding, moving, unseen

Schema:
{"label":"moving","confidence":0.0,"needs_review":true,"evidence":"short visual evidence"}

Rules:
- confidence must be a number between 0 and 1.
- needs_review is true when the scene is unclear, animal is unseen, or a P0 behavior is possible.
- P0 behaviors are eating_prey, drinking, defecating, shedding.
- evidence must describe visible facts only.
"""

# Strategy B: anti-collapse + structured reasoning + visual cheat sheet
PROMPT_ANTI_COLLAPSE = """You are an expert herpetologist classifying a crested gecko's behavior from a contact sheet.
The contact sheet shows evenly sampled frames from a 60-second motion clip.

CRITICAL RULE: "moving" is the LAST RESORT label. Only use it after carefully checking for these specific behaviors first:

1. drinking — Look for: tongue extended toward WET GLASS surface with visible water droplets/condensation, OR tongue contact with clear liquid in a dish. Single tongue contact with wet glass is SUFFICIENT.

2. eating_paste — Look for: tongue contacting a small dish or syringe/spoon with OPAQUE paste (brown/tan/yellow color). Sustained mouth-to-paste contact across multiple frames.

3. eating_prey — Look for: a LIVE CRICKET or INSECT visible in the frame, gecko's mouth bitten/holding it, or focused stalking posture toward visible prey. Often shown with tweezers.

4. defecating — Look for: brown/dark fecal pellets visible near or under the gecko, often on a perch or container edge. Tail base slightly lifted. White-tipped feces.

5. shedding — Look for: PATCHES OF PALE/WHITISH OLD SKIN contrasting with normal coloration, partially detached skin flaps on body/legs/tail, gecko's mouth biting/pulling skin pieces. Sock-like white skin on hindlegs is typical.

DECISION PROCEDURE (apply IN ORDER):
Step 1: Is there visible WET GLASS or water with tongue contact? → drinking
Step 2: Is there a visible PASTE/SYRINGE with mouth contact? → eating_paste
Step 3: Is there a visible CRICKET/INSECT with mouth-bite? → eating_prey
Step 4: Are there visible FECAL PELLETS near gecko? → defecating
Step 5: Is there visible WHITE OLD SKIN partially detached? → shedding
Step 6: Only if NONE of the above → moving (or unseen if no gecko visible)

OUTPUT (single JSON object, no markdown):
{"label":"<class>","confidence":0.0-1.0,"needs_review":bool,"evidence":"specific visual evidence with frame reference"}

Available classes:
eating_paste, eating_prey, drinking, defecating, shedding, basking, hiding, moving, unseen

Rules:
- confidence: 0.9+ for clear evidence, 0.6-0.8 for partial visibility, 0.3-0.5 for ambiguous.
- needs_review: true if confidence < 0.7 OR label is P0 OR scene is unclear.
- evidence: cite specific visual features (e.g., "white skin flap visible on left hindleg", "brown pellet near gecko").
- If "moving" is your choice, JUSTIFY in evidence why all P0 checks failed.
"""

# Strategy D Stage 1: P0-detection only
PROMPT_STAGE1_P0_DETECT = """You are a crested gecko behavior screening expert.
Given this contact sheet (60-second motion clip), answer ONE question:

Is there ANY visible evidence of a P0 behavior in any frame?

P0 behaviors:
- drinking (tongue on wet glass or water)
- eating_paste (tongue on paste/syringe)
- eating_prey (cricket/insect with bite)
- defecating (fecal pellets visible)
- shedding (white old skin patches/flaps)

OUTPUT (single JSON, no markdown):
{"p0_candidate": true|false, "candidate_label": "<one of: drinking/eating_paste/eating_prey/defecating/shedding/none>", "confidence": 0.0-1.0, "evidence": "what you see"}

Rules:
- If you see EVEN ONE frame with P0 evidence → p0_candidate: true
- Otherwise → p0_candidate: false, candidate_label: "none"
- Pick the SINGLE most likely P0 label as candidate_label
"""

# Stage 2 prompts per P0 — specialized verification
STAGE2_PROMPTS = {
    "drinking": """Verify: is this DRINKING behavior?
Contact sheet from 60-second clip. The previous screening flagged possible drinking.

Drinking requires:
- WET surface visible (water droplets on glass walls, OR clear liquid in dish)
- Gecko's TONGUE EXTENDED to that wet surface
- Single tongue contact is sufficient (water transfers in one lick)

NOT drinking:
- Tongue flicking in air without water source (sensing)
- Eye-licking (geckos lick eyes to clean — not drinking)
- Head near wall but no tongue extension visible

OUTPUT JSON:
{"label":"drinking" or "moving","confidence":0.0-1.0,"evidence":"..."}
""",
    "eating_paste": """Verify: is this EATING_PASTE behavior?
Contact sheet from 60-second clip. The previous screening flagged possible eating_paste.

Eating_paste requires:
- Small DISH or SYRINGE/SPOON with opaque paste (brown/tan/yellow) visible
- Gecko's TONGUE contacting paste surface (not hovering above)
- REPEATED licking (2-3+ contacts across frames) — single tongue flick is sensing only

NOT eating_paste:
- Tongue extended without paste visible
- Head over dish but no actual tongue contact
- Wet glass licking (that's drinking)

OUTPUT JSON:
{"label":"eating_paste" or "moving","confidence":0.0-1.0,"evidence":"..."}
""",
    "eating_prey": """Verify: is this EATING_PREY behavior?
Contact sheet from 60-second clip. The previous screening flagged possible eating_prey.

Eating_prey requires:
- LIVE CRICKET/INSECT clearly visible in frame
- Gecko showing FOCUSED ENGAGEMENT: bite/chew/hold cricket OR fixed stalking gaze
- Often shown with tweezers feeding

NOT eating_prey:
- No visible prey in frame
- Gecko moving generally without prey-locked attention
- Just walking around

OUTPUT JSON:
{"label":"eating_prey" or "moving","confidence":0.0-1.0,"evidence":"..."}
""",
    "defecating": """Verify: is this DEFECATING behavior?
Contact sheet from 60-second clip. The previous screening flagged possible defecating.

Defecating requires:
- Brown/dark FECAL PELLETS visible near or under gecko (often white-tipped)
- Tail base lifted, gecko on perch/edge
- Brief event

NOT defecating:
- No visible feces
- Just sitting on perch

OUTPUT JSON:
{"label":"defecating" or "moving","confidence":0.0-1.0,"evidence":"..."}
""",
    "shedding": """Verify: is this SHEDDING behavior?
Contact sheet from 60-second clip. The previous screening flagged possible shedding.

Shedding requires:
- VISIBLE PATCHES of pale/whitish/dull OLD SKIN contrasting with normal coloration
- AND active removal: mouth biting skin, OR partially detached skin flaps, OR sock-like skin on legs
- Crested geckos often eat shed skin (chewing white pieces visible)

NOT shedding:
- Just dull skin color with no skin pieces/removal
- General body movement without skin evidence
- Just stationary

OUTPUT JSON:
{"label":"shedding" or "moving","confidence":0.0-1.0,"evidence":"..."}
""",
}


# ─────────────────────────────────────────────────────────────────────────────
# Ollama call helpers
# ─────────────────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict[str, Any]:
    """JSON object 추출 (markdown fence 허용)."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end < start:
            raise ValueError(f"JSON 파싱 실패: {text[:300]}")
        parsed = json.loads(stripped[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError(f"response not object: {parsed!r}")
    return parsed


def ollama_call(
    *,
    model: str,
    prompt: str,
    image_paths: list[Path],
    timeout_sec: int = 240,
) -> dict[str, Any]:
    """Ollama generate API 호출. multi-image OK."""
    images_b64 = [
        base64.b64encode(p.read_bytes()).decode("ascii") for p in image_paths
    ]
    payload = {
        "model": model,
        "prompt": prompt,
        "images": images_b64,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1, "top_p": 0.95},
    }
    req = urllib.request.Request(
        f"{OLLAMA_URL.rstrip('/')}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    response_text = str(body.get("response") or "")
    return _extract_json(response_text)


def clamp_confidence(value: Any) -> float:
    try:
        c = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, c))


def normalize_label(label: str) -> str:
    """라벨 정규화. 알 수 없으면 moving."""
    label = str(label or "").strip().lower()
    if label in BEHAVIOR_CLASSES:
        return label
    # 자주 발생하는 동의어
    aliases = {
        "eat_paste": "eating_paste",
        "eat_prey": "eating_prey",
        "drink": "drinking",
        "defecate": "defecating",
        "shed": "shedding",
        "move": "moving",
        "bask": "basking",
        "hide": "hiding",
    }
    return aliases.get(label, "moving")


# ─────────────────────────────────────────────────────────────────────────────
# 전략별 분류 함수
# ─────────────────────────────────────────────────────────────────────────────

def strategy_baseline(row: EvalRow, model: str, prompt: str) -> dict[str, Any]:
    """Strategy A/B: contact sheet 1장 + prompt 변경."""
    sheet = Path(row.contact_sheet_path)
    if not sheet.exists():
        raise FileNotFoundError(f"contact sheet missing: {sheet}")
    raw = ollama_call(model=model, prompt=prompt, image_paths=[sheet])
    label = normalize_label(raw.get("label") or raw.get("action"))
    return {
        "predicted_label": label,
        "confidence": clamp_confidence(raw.get("confidence")),
        "evidence": str(raw.get("evidence") or raw.get("reasoning") or "")[:500],
        "raw_response": raw,
    }


def strategy_multi_frame(row: EvalRow, model: str, prompt: str) -> dict[str, Any]:
    """Strategy C: 8 frame multi-image input."""
    frames_dir = PILOT_FRAMES_DIR / row.clip_id
    frame_paths = sorted(frames_dir.glob("frame_*.jpg"))
    if not frame_paths:
        # pilot에 없으면 contact sheet fallback
        return strategy_baseline(row, model, prompt)
    raw = ollama_call(model=model, prompt=prompt, image_paths=list(frame_paths))
    label = normalize_label(raw.get("label") or raw.get("action"))
    return {
        "predicted_label": label,
        "confidence": clamp_confidence(raw.get("confidence")),
        "evidence": str(raw.get("evidence") or raw.get("reasoning") or "")[:500],
        "raw_response": raw,
        "n_frames": len(frame_paths),
    }


def strategy_cascade(row: EvalRow, model: str, _unused_prompt: str) -> dict[str, Any]:
    """Strategy D: Stage 1 (P0 detect) → Stage 2 (specialized verify)."""
    sheet = Path(row.contact_sheet_path)
    if not sheet.exists():
        raise FileNotFoundError(f"contact sheet missing: {sheet}")
    # Stage 1
    stage1_raw = ollama_call(
        model=model, prompt=PROMPT_STAGE1_P0_DETECT, image_paths=[sheet]
    )
    is_p0 = bool(stage1_raw.get("p0_candidate"))
    candidate = str(stage1_raw.get("candidate_label") or "").strip().lower()
    stage1_confidence = clamp_confidence(stage1_raw.get("confidence"))
    if not is_p0 or candidate not in STAGE2_PROMPTS:
        return {
            "predicted_label": "moving",
            "confidence": 1.0 - stage1_confidence if stage1_confidence > 0 else 0.5,
            "evidence": f"Stage1: no P0 candidate. {stage1_raw.get('evidence', '')}"[:500],
            "raw_response": {"stage1": stage1_raw},
            "stage": 1,
        }
    # Stage 2: verify
    stage2_raw = ollama_call(
        model=model, prompt=STAGE2_PROMPTS[candidate], image_paths=[sheet]
    )
    stage2_label = normalize_label(stage2_raw.get("label"))
    stage2_conf = clamp_confidence(stage2_raw.get("confidence"))
    return {
        "predicted_label": stage2_label,
        "confidence": stage2_conf,
        "evidence": f"Stage2[{candidate}]: {stage2_raw.get('evidence', '')}"[:500],
        "raw_response": {"stage1": stage1_raw, "stage2": stage2_raw},
        "stage": 2,
    }


STRATEGY_FUNCS = {
    "A": strategy_baseline,         # 새 모델 + 기본 prompt
    "B": strategy_baseline,         # gemma3:4b + anti-collapse prompt
    "C": strategy_multi_frame,      # multi-image (gemma3:4b)
    "D": strategy_cascade,          # 2-stage cascade
}

STRATEGY_PROMPTS = {
    "A": PROMPT_BASELINE,
    "B": PROMPT_ANTI_COLLAPSE,
    "C": PROMPT_ANTI_COLLAPSE,
    "D": "",  # cascade가 내부에서 prompt 결정
}


# ─────────────────────────────────────────────────────────────────────────────
# 평가 실행 + 분석
# ─────────────────────────────────────────────────────────────────────────────

def already_done(out_path: Path) -> set[str]:
    if not out_path.exists():
        return set()
    done: set[str] = set()
    for line in out_path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("ok"):
            done.add(str(rec["clip_id"]))
    return done


def run_eval(
    targets: list[EvalRow],
    *,
    strategy: str,
    model: str,
    out_path: Path,
    force: bool = False,
    limit: int | None = None,
) -> None:
    if force and out_path.exists():
        out_path.unlink()
    if limit is not None:
        targets = targets[:limit]

    func = STRATEGY_FUNCS[strategy]
    prompt = STRATEGY_PROMPTS[strategy]
    done = already_done(out_path)
    pending = [t for t in targets if t.clip_id not in done]
    logger.info("Strategy=%s model=%s — 평가 %d건 (done %d, pending %d)",
                strategy, model, len(targets), len(done), len(pending))
    if not pending:
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    started_all = time.monotonic()
    ok = fail = 0
    with out_path.open("a", encoding="utf-8") as f:
        for i, row in enumerate(pending, 1):
            started = time.monotonic()
            try:
                result = func(row, model, prompt)
                latency = time.monotonic() - started
                rec = {
                    "ok": True,
                    "clip_id": row.clip_id,
                    "gt_action": row.gt_action,
                    "species_id": row.species_id,
                    "r2_key": row.r2_key,
                    "model": model,
                    "strategy": strategy,
                    "latency_sec": round(latency, 2),
                    **result,
                }
                ok += 1
                correct = result["predicted_label"] == row.gt_action
                logger.info(
                    "[%d/%d] %s gt=%-13s pred=%-13s %s conf=%.2f %.1fs",
                    i, len(pending), row.clip_id[:8],
                    row.gt_action, result["predicted_label"],
                    "✓" if correct else "✗",
                    result["confidence"], latency,
                )
            except Exception as exc:  # noqa: BLE001 — batch는 계속
                fail += 1
                rec = {
                    "ok": False,
                    "clip_id": row.clip_id,
                    "gt_action": row.gt_action,
                    "error": f"{type(exc).__name__}: {exc!s}"[:500],
                }
                logger.warning("[%d/%d] %s FAIL: %s", i, len(pending),
                               row.clip_id[:8], rec["error"])
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()

    logger.info("완료 ok=%d fail=%d 총 %.1fs", ok, fail,
                time.monotonic() - started_all)


def analyze(out_path: Path) -> dict[str, Any]:
    rows = []
    for line in out_path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
            if rec.get("ok"):
                rows.append(rec)
        except json.JSONDecodeError:
            continue
    n = len(rows)
    if not n:
        print("결과 없음")
        return {}

    correct = sum(1 for r in rows if r["predicted_label"] == r["gt_action"])
    by_gt: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "total": 0})
    confusion: list[tuple[str, str, str]] = []
    for r in rows:
        gt, pred = r["gt_action"], r["predicted_label"]
        by_gt[gt]["total"] += 1
        if gt == pred:
            by_gt[gt]["correct"] += 1
        else:
            confusion.append((r["clip_id"], gt, pred))

    lats = [r["latency_sec"] for r in rows]
    pred_dist: dict[str, int] = defaultdict(int)
    for r in rows:
        pred_dist[r["predicted_label"]] += 1

    summary = {
        "n": n,
        "correct": correct,
        "acc": correct / n,
        "by_gt": {k: dict(v) for k, v in by_gt.items()},
        "pred_dist": dict(pred_dist),
        "latency_avg": sum(lats) / n,
        "latency_p50": sorted(lats)[n // 2],
        "latency_max": max(lats),
        "target_90pct": correct / n >= 0.90,
    }

    print()
    print("=" * 72)
    print(f"P0 평가 결과 — N={n}")
    print("=" * 72)
    print(f"전체 정확도: {correct}/{n} = {correct/n:.1%}  목표 90%: {'✅' if summary['target_90pct'] else '❌'}")
    print()
    print("per-class 정확도:")
    for gt in sorted(by_gt):
        b = by_gt[gt]
        print(f"  {gt:14s} {b['correct']:3d}/{b['total']:3d} = {b['correct']/b['total']:.0%}")
    print()
    print("예측 분포:")
    for p in sorted(pred_dist):
        print(f"  {p:14s} {pred_dist[p]:3d} = {pred_dist[p]/n:.0%}")
    print()
    print(f"latency avg/p50/max: {summary['latency_avg']:.1f}s / {summary['latency_p50']:.1f}s / {summary['latency_max']:.1f}s")
    if confusion:
        print(f"\n오답 {len(confusion)}건:")
        for clip_id, gt, pred in confusion[:30]:
            print(f"  {clip_id[:8]} GT={gt:13s} → {pred}")
        if len(confusion) > 30:
            print(f"  ... +{len(confusion)-30}건")

    summary_path = out_path.with_suffix(".summary.json")
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nsummary: {summary_path}")
    return summary


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=["A", "B", "C", "D"], required=True)
    parser.add_argument("--model", required=True, help="ollama model id")
    parser.add_argument("--limit", type=int, help="N건만 평가")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--tag", default="", help="output 파일 tag")
    args = parser.parse_args()

    targets = load_p0_eval_set()
    logger.info("P0 평가셋 로드: %d건", len(targets))

    tag = args.tag or f"{args.strategy}-{args.model.replace(':', '-').replace('/', '-')}"
    out_path = OUT_BASE / f"{tag}.jsonl"
    run_eval(
        targets,
        strategy=args.strategy,
        model=args.model,
        out_path=out_path,
        force=args.force,
        limit=args.limit,
    )
    analyze(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
