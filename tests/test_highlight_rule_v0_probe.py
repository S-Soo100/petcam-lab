"""probe 러너의 psql 출력 파서만 검사한다(PG 불필요)."""

from scripts.run_highlight_rule_v0_probe import parse_kv_lines, expect


def test_parse_kv_lines_reads_psql_unaligned_output() -> None:
    out = "initial|t\nreason|움직임 12.5초 · 최장 연속 6.0초\nfired|{long_activity,sustained_move}\n"
    parsed = parse_kv_lines(out)
    assert parsed["initial"] == "t"
    assert parsed["fired"] == "{long_activity,sustained_move}"


def test_expect_raises_with_label_on_mismatch() -> None:
    try:
        expect("case-a", {"initial": "t"}, initial="f")
    except RuntimeError as err:
        assert "case-a" in str(err) and "initial" in str(err)
    else:
        raise AssertionError("expect() must raise on mismatch")
