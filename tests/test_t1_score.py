"""T1 채점기 순수 함수 테스트 — TEST-SHEET §4·§5·§7 기계 적용."""


def _sheet(pairs):
    return {rid: v for rid, v in pairs}


def test_score_groups_counts_and_rates():
    from scripts.t1_score_probe import score_groups

    sheet = _sheet([
        ("t1-001", "informative_care"), ("t1-002", "informative_other"),
        ("t1-003", "not_informative"), ("t1-004", "absent"),
        ("t1-005", "unsure"),
        ("t1-006", "not_informative"), ("t1-007", "informative_other"),
    ])
    key = [
        {"review_id": "t1-001", "group": "score"},
        {"review_id": "t1-002", "group": "score"},
        {"review_id": "t1-003", "group": "score"},
        {"review_id": "t1-004", "group": "score"},
        {"review_id": "t1-005", "group": "score"},  # unsure → judged 제외
        {"review_id": "t1-006", "group": "random"},
        {"review_id": "t1-007", "group": "random"},
    ]
    g = score_groups(sheet, key)
    s = g["score"]
    assert s["n"] == 5 and s["judged"] == 4
    assert s["informative"] == 2 and s["care"] == 1 and s["absent"] == 1
    assert s["informative_rate"] == 0.5
    r = g["random"]
    assert r["judged"] == 2 and r["informative"] == 1
    assert r["informative_rate"] == 0.5


def test_decide_rules():
    from scripts.t1_score_probe import decide

    def grp(inf, judged):
        return {"informative": inf, "judged": judged,
                "informative_rate": inf / judged}

    # adopt: 격차 ≥ +20%p AND S informative ≥ 8
    assert decide(grp(10, 20), grp(2, 20)) == "adopt"     # 50% vs 10%
    # 격차 커도 S < 8 이면 adopt 불가 → count 5~7 = hold
    assert decide(grp(6, 20), grp(0, 20)) == "hold"       # 30% vs 0%
    # 격차 10~20%p → hold
    assert decide(grp(9, 20), grp(6, 20)) == "hold"       # 45% vs 30% = +15%p
    # 격차 < 10%p → reject
    assert decide(grp(9, 20), grp(8, 20)) == "reject"     # +5%p
    # S ≤ 4 → reject (격차 무관)
    assert decide(grp(4, 20), grp(0, 20)) == "reject"
