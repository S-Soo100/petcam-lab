"""blind 인퍼런스 배치 빌더 + 중립 스테이징.

blind 무결성: 에이전트가 (a) GT, (b) "이게 shedding 실험임"을 못 알게 한다.
→ 프레임을 중립 경로 `/tmp/beval/s###/` 로 복사, job/실험명/GT 는 사설 맵(`_batches.json`)에만.
프롬프트도 rubricA(v4.0)/rubricB(v4.1) 로 복사(파일명서 버전 숨김 — 내용은 treatment 라 유지).

3개 잡: fp_v40 / fp_v41 (Set-FP 32) + reg_v41 (Set-REG 185). 배치 8건/에이전트.
Set-FP 프레임은 두 잡이 동일 → 한 번만 스테이징(s001..s032), 두 잡이 공유.

산출:
  /tmp/beval/tasks.json      — 에이전트용 (rubric + 중립 sid + 중립 프레임경로. job/GT 없음)
  /tmp/beval/batch-{i}.json  — 배치별 개별 파일(에이전트가 공유 index 오독하는 스크램블 방지)
  <exp>/_batches.json        — 사설 (batch→job + sid→real_id/gt. 채점 전용, 에이전트 안 봄)

실행: `uv run python experiments/v41-shedding-ir-guard/_build_batches.py`
"""

from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
EXP = Path(__file__).resolve().parent
FP_FRAMES = EXP / "frames-fp"
REG_FRAMES = REPO / "experiments" / "v40-regression" / "frames"
STAGE = Path("/tmp/beval")
BATCH = 8
SEED = 42


def frames_of(d: Path) -> list[str]:
    return [str(p) for p in sorted(d.glob("f_*.jpg"))]


def gt_of(d: Path) -> str:
    return json.loads((d / "meta.json").read_text())["gt"]


def chunk(lst: list, n: int) -> list[list]:
    return [lst[i : i + n] for i in range(0, len(lst), n)]


def main() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    shutil.copy(Path("/tmp/v40_prompt.txt"), STAGE / "rubricA.txt")
    shutil.copy(Path("/tmp/v41_prompt.txt"), STAGE / "rubricB.txt")

    fp_dirs = sorted(FP_FRAMES.glob("sample-*"))
    reg_dirs = sorted(REG_FRAMES.glob("sample-*"))
    assert len(fp_dirs) == 32 and len(reg_dirs) == 185, (len(fp_dirs), len(reg_dirs))

    # 실제 sample dir → 중립 sid, 프레임 스테이징
    sid_map: dict[str, str] = {}  # real_dir_name -> sid
    stage_frames: dict[str, list[str]] = {}  # sid -> neutral frame paths
    real_meta: dict[str, dict] = {}  # sid -> {real_id, gt}
    n = 0
    for d in fp_dirs + reg_dirs:
        n += 1
        sid = f"s{n:03d}"
        sdir = STAGE / sid
        sdir.mkdir()
        neutral = []
        for j, f in enumerate(frames_of(d), 1):
            dst = sdir / f"f_{j:03d}.jpg"
            shutil.copy(f, dst)
            neutral.append(str(dst))
        sid_map[d.name] = sid
        stage_frames[sid] = neutral
        real_meta[sid] = {"real_id": d.name, "gt": gt_of(d)}

    rng = random.Random(SEED)
    fp_order = [d.name for d in fp_dirs]
    reg_order = [d.name for d in reg_dirs]
    rng.shuffle(fp_order)
    rng.shuffle(reg_order)

    private: list[dict] = []   # 사설: job/real/gt
    tasks: list[dict] = []     # 에이전트용: rubric/중립
    jobs = [
        ("fp_v40", fp_order, "rubricA.txt"),
        ("fp_v41", fp_order, "rubricB.txt"),
        ("reg_v41", reg_order, "rubricB.txt"),
    ]
    for job, order, rubric in jobs:
        for grp in chunk(order, BATCH):
            priv_samples = []
            task_samples = []
            for real_name in grp:
                sid = sid_map[real_name]
                priv_samples.append({"sid": sid, **real_meta[sid]})
                task_samples.append({"sid": sid, "frames": stage_frames[sid]})
            private.append({"job": job, "rubric": rubric, "samples": priv_samples})
            tasks.append({"rubric": str(STAGE / rubric), "samples": task_samples})

    (STAGE / "tasks.json").write_text(json.dumps(tasks, ensure_ascii=False))
    (EXP / "_batches.json").write_text(json.dumps(private, ensure_ascii=False, indent=2))

    # ⚠️ 2026-07-08 버그 수정: 공유 tasks.json 에서 에이전트가 "index i" 를 오독해
    # 다른 배치 sid 를 반환하는 스크램블 발생(5/32 배치). → 배치별 **개별 파일**로 분리.
    # Workflow 에이전트는 자기 batch-{i}.json 만 Read → 인덱싱 모호성 원천 제거.
    for i, t in enumerate(tasks):
        (STAGE / f"batch-{i:02d}.json").write_text(json.dumps(t, ensure_ascii=False))

    by_job: dict[str, int] = {}
    for b in private:
        by_job[b["job"]] = by_job.get(b["job"], 0) + len(b["samples"])
    n_imgs = sum(len(s["frames"]) for t in tasks for s in t["samples"])
    print(f"배치 {len(tasks)}개 · 판정 {sum(by_job.values())}건 · 이미지 {n_imgs}장 · 스테이징 {n} sid")
    print(f"  잡별: {by_job}")
    print(f"  에이전트용: /tmp/beval/tasks.json + batch-*.json (중립) · 사설: _batches.json")


if __name__ == "__main__":
    main()
