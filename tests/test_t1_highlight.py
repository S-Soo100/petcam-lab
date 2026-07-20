"""T1 highlight-selection probe 순수 함수 테스트 (DB/R2/네트워크 불필요).

TEST-SHEET §2 계약: 백분위 평균 합성점수 · (camera, KST date, 2h)버킷 캡 4 ·
결정론(seed 고정) · 결측 성분 0.
"""


def test_percentile_rank_ties_and_range():
    from scripts.t1_highlight_rank import percentile_rank

    # 단조 증가: 0~1 범위, 최솟값 0 / 최댓값 1
    prs = percentile_rank([10.0, 20.0, 30.0, 40.0, 50.0])
    assert prs[0] == 0.0 and prs[-1] == 1.0
    assert prs == sorted(prs)
    # 동률은 평균 순위 (2등·3등 동률 → 같은 pr)
    prs = percentile_rank([1.0, 2.0, 2.0, 3.0])
    assert prs[1] == prs[2]
    assert 0.0 < prs[1] < 1.0
    # n=1 이면 중립 0.5
    assert percentile_rank([7.0]) == [0.5]


def test_composite_score_missing_component_zero():
    from scripts.t1_highlight_rank import compute_scores

    rows = [
        {"clip_id": "a", "observed_sec": 30.0, "roi_mean": 5.0, "peak_autocorr": 0.9},
        {"clip_id": "b", "observed_sec": 10.0, "roi_mean": 1.0, "peak_autocorr": None},
        {"clip_id": "c", "observed_sec": 20.0, "roi_mean": 3.0, "peak_autocorr": 0.1},
    ]
    scores = compute_scores(rows)
    assert set(scores) == {"a", "b", "c"}
    # a 는 모든 성분 최상위 → 최고점
    assert scores["a"] == max(scores.values())
    # b 의 peak_autocorr 결측 = 성분 0 (같은 나머지 성분이라도 감점)
    assert scores["b"] < scores["c"]
    # 전 성분 pr ∈ [0,1] 평균이므로 점수도 [0,1]
    assert all(0.0 <= s <= 1.0 for s in scores.values())


def test_bucket_key_kst_2h_window():
    from scripts.t1_highlight_rank import bucket_key

    # UTC 15:10 = KST 다음날 00:10 → date 넘어가고 창 0
    assert bucket_key("camA", "2026-07-18T15:10:00+00:00") == ("camA", "2026-07-19", 0)
    # UTC 15:10 'Z' 표기 동일 처리
    assert bucket_key("camA", "2026-07-18T15:10:00Z") == ("camA", "2026-07-19", 0)
    # KST 13:59 → 창 6 / KST 14:00 → 창 7
    assert bucket_key("camB", "2026-07-18T04:59:00+00:00")[2] == 6
    assert bucket_key("camB", "2026-07-18T05:00:00+00:00")[2] == 7


def test_select_top_with_bucket_cap():
    from scripts.t1_highlight_rank import select_top_with_cap

    # 같은 버킷에 고득점 6개 몰림 → 캡 4 초과분은 다음 순위 버킷으로
    ranked = [
        {"clip_id": f"x{i}", "score": 1.0 - i * 0.01, "bucket": ("c", "d", 0)}
        for i in range(6)
    ] + [
        {"clip_id": f"y{i}", "score": 0.5 - i * 0.01, "bucket": ("c", "d", 1)}
        for i in range(4)
    ]
    top = select_top_with_cap(ranked, n=8, cap=4)
    picked = [r["clip_id"] for r in top]
    assert len(picked) == 8
    assert sum(1 for r in top if r["bucket"] == ("c", "d", 0)) == 4
    assert picked[:4] == ["x0", "x1", "x2", "x3"]  # 버킷 내 점수순 유지
    assert "x4" not in picked and "x5" not in picked  # 캡 초과 탈락


def test_split_deterministic_and_disjoint():
    from scripts.t1_highlight_rank import SEED, split_groups

    # 버킷 7개 × 캡 4 = 28 ≥ top_n 20 (캡 완화 규칙은 시트에 없음 — 풀이 채울 수 있어야 함)
    ranked = [
        {"clip_id": f"c{i:02d}", "score": (i % 10) / 10, "bucket": ("c", "d", i % 7)}
        for i in range(50)
    ]
    s1, r1 = split_groups(ranked, top_n=20, random_n=20, cap=4, seed=SEED)
    s2, r2 = split_groups(ranked, top_n=20, random_n=20, cap=4, seed=SEED)
    assert [x["clip_id"] for x in s1] == [x["clip_id"] for x in s2]  # 결정론
    assert [x["clip_id"] for x in r1] == [x["clip_id"] for x in r2]
    s_ids = {x["clip_id"] for x in s1}
    assert s_ids.isdisjoint({x["clip_id"] for x in r1})  # S/R 상호배타
    assert len(s1) == 20 and len(r1) == 20
