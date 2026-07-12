from scripts.codex_dataset203_sweep import (
    CallRecord,
    ClipRow,
    TokenUsage,
    cascade_summary,
    extract_usage_from_text,
    select_stratified,
    summarize_records,
)


def test_select_stratified_is_deterministic_and_includes_rare_class() -> None:
    rows = [
        *(ClipRow(filename=f"moving_{i}.mp4", clip_id=f"m{i}", gt="moving") for i in range(8)),
        *(ClipRow(filename=f"drinking_{i}.mp4", clip_id=f"d{i}", gt="drinking") for i in range(4)),
        *(ClipRow(filename=f"unseen_{i}.mp4", clip_id=f"u{i}", gt="unseen") for i in range(2)),
    ]

    first = select_stratified(rows, target_size=8, seed=7)
    second = select_stratified(rows, target_size=8, seed=7)

    assert [r.clip_id for r in first] == [r.clip_id for r in second]
    assert len(first) == 8
    assert sum(1 for r in first if r.gt == "unseen") == 2


def test_select_stratified_honors_tiny_smoke_size() -> None:
    rows = [
        ClipRow(filename=f"{gt}_{i}.mp4", clip_id=f"{gt}{i}", gt=gt)
        for gt in ("moving", "drinking", "unseen")
        for i in range(2)
    ]

    selected = select_stratified(rows, target_size=1, seed=7)

    assert len(selected) == 1


def test_select_stratified_honors_size_when_rare_class_would_overfill() -> None:
    rows = [
        *(ClipRow(filename=f"moving_{i}.mp4", clip_id=f"m{i}", gt="moving") for i in range(72)),
        *(ClipRow(filename=f"drinking_{i}.mp4", clip_id=f"d{i}", gt="drinking") for i in range(24)),
        *(ClipRow(filename=f"unseen_{i}.mp4", clip_id=f"u{i}", gt="unseen") for i in range(2)),
        *(ClipRow(filename=f"shedding_{i}.mp4", clip_id=f"s{i}", gt="shedding") for i in range(29)),
        *(ClipRow(filename=f"hand_{i}.mp4", clip_id=f"h{i}", gt="hand_feeding") for i in range(29)),
        *(ClipRow(filename=f"paste_{i}.mp4", clip_id=f"p{i}", gt="eating_paste") for i in range(19)),
        *(ClipRow(filename=f"prey_{i}.mp4", clip_id=f"r{i}", gt="eating_prey") for i in range(22)),
    ]

    selected = select_stratified(rows, target_size=7, seed=203)

    assert len(selected) == 7


def test_extract_usage_from_text_reads_nested_codex_json_event() -> None:
    text = """
{"type":"started"}
{"type":"response.completed","response":{"usage":{"input_tokens":1200,"output_tokens":80,"total_tokens":1280}}}
"""

    usage = extract_usage_from_text(text)

    assert usage == TokenUsage(input_tokens=1200, output_tokens=80, total_tokens=1280)


def test_summarize_records_reports_accuracy_drop_token_reduction_and_speed() -> None:
    records = [
        _record("s1", "m", "frames-adaptive", "moving", "moving", 0.9, 1000, 10.0),
        _record("s2", "m", "frames-adaptive", "drinking", "drinking", 0.9, 1000, 12.0),
        _record("s1", "m", "contact-sheet", "moving", "moving", 0.9, 250, 3.0),
        _record("s2", "m", "contact-sheet", "moving", "drinking", 0.6, 250, 4.0),
    ]

    summary = summarize_records(records)

    assert summary["by_model_repr"]["m|v40|frames-adaptive"]["accuracy"] == 1.0
    assert summary["by_model_repr"]["m|v40|contact-sheet"]["accuracy"] == 0.5
    paired = summary["paired"]["m|v40|contact-sheet_vs_v40|frames-adaptive"]
    assert paired["token_reduction"] == 0.75
    assert paired["accuracy_drop_pp"] == 50.0
    assert paired["avg_wall_seconds_delta"] == -7.5


def test_cascade_summary_uses_low_confidence_fallback() -> None:
    records = [
        _record("s1", "m", "frames-adaptive", "moving", "moving", 0.9, 1000, 10.0),
        _record("s2", "m", "frames-adaptive", "drinking", "drinking", 0.9, 1000, 12.0),
        _record("s1", "m", "contact-sheet", "moving", "moving", 0.95, 250, 3.0),
        _record("s2", "m", "contact-sheet", "moving", "drinking", 0.4, 250, 4.0),
    ]

    row = cascade_summary(records, model="m", threshold=0.7)

    assert row["fallback_rate"] == 0.5
    assert row["accuracy"] == 1.0
    assert row["token_reduction"] == 0.25
    assert row["avg_wall_seconds"] == 9.5


def _record(
    sample_id: str,
    model: str,
    representation: str,
    predicted_action: str,
    gt: str,
    confidence: float,
    input_tokens: int,
    wall_seconds: float,
) -> CallRecord:
    return CallRecord(
        sample_id=sample_id,
        clip_id=sample_id,
        gt=gt,
        source_filename=f"{sample_id}.mp4",
        model=model,
        representation=representation,
        image_count=1,
        duration_sec=60.0,
        predicted_action=predicted_action,
        confidence=confidence,
        reasoning="",
        needs_human_review=False,
        usage=TokenUsage(input_tokens=input_tokens, output_tokens=0, total_tokens=input_tokens),
        estimated_input_tokens=None,
        wall_seconds=wall_seconds,
        returncode=0,
        error=None,
    )
