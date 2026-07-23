"""대표 ≤3 선택 — evidence 품질 · ROI motion · novelty 세 축 (설계 §6.2)."""
from __future__ import annotations

from .signatures import ClipSignature, hamming


def select_representatives(
    members: list[ClipSignature],
    max_reps: int = 3,
    novelty_min_hamming: int = 6,
) -> tuple[str, ...]:
    if not members:
        return ()
    # 1) evidence 품질 최고 (tie: motion peak → clip_id)
    r1 = sorted(members, key=lambda s: (-s.evidence_score, -s.roi_motion_peak, s.clip_id))[0]
    reps = [r1]
    rest = [s for s in members if s.clip_id != r1.clip_id]
    if rest and max_reps >= 2:
        # 2) ROI motion 최대
        r2 = sorted(rest, key=lambda s: (-s.roi_motion_peak, s.clip_id))[0]
        reps.append(r2)
        rest2 = [s for s in rest if s.clip_id != r2.clip_id]
        if rest2 and max_reps >= 3:
            # 3) 앞 두 대표와 시각적으로 가장 다른 것 (novelty 임계 이상일 때만)
            def min_dist(s: ClipSignature) -> int:
                return min(hamming(s.perceptual_hash, r.perceptual_hash) for r in reps)

            r3 = sorted(rest2, key=lambda s: (-min_dist(s), s.clip_id))[0]
            if min_dist(r3) >= novelty_min_hamming:
                reps.append(r3)
    return tuple(r.clip_id for r in reps)
