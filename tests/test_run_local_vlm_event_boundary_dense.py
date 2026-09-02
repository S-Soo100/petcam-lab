import base64

from scripts.run_local_vlm_event_boundary_dense import (
    LOCAL_MODELS,
    build_dense_ollama_payload,
    context_budget_valid,
    smoke_response_has_both_images,
)
from scripts.vlm_event_boundary_dense import DENSE_PROMPT


def test_dense_local_payload_uses_two_images_and_deterministic_options() -> None:
    payload = build_dense_ollama_payload("minicpm-v4.6:latest", (b"a", b"b"))

    assert LOCAL_MODELS == ("minicpm-v4.6:latest", "qwen3-vl:2b")
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["messages"][0]["content"] == DENSE_PROMPT
    assert payload["messages"][0]["images"] == [
        base64.b64encode(b"a").decode(),
        base64.b64encode(b"b").decode(),
    ]
    assert payload["options"]["temperature"] == 0
    assert payload["options"]["seed"] == 20260803
    assert payload["options"]["num_ctx"] == 8192


def test_two_image_smoke_requires_both_visual_markers() -> None:
    assert smoke_response_has_both_images('{"a":"red square","b":"blue triangle"}')
    assert not smoke_response_has_both_images('{"a":"red square","b":"unknown"}')
    assert not smoke_response_has_both_images("not-json")


def test_context_budget_reserves_full_output_window() -> None:
    assert context_budget_valid(prompt_eval_count=7000, num_ctx=8192, num_predict=96)
    assert not context_budget_valid(prompt_eval_count=8100, num_ctx=8192, num_predict=96)
    assert not context_budget_valid(prompt_eval_count=0, num_ctx=8192, num_predict=96)
