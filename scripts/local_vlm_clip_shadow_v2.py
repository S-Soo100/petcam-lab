"""Individual-12-frame production local VLM shadow의 순수 계약이야."""

from __future__ import annotations

import base64
from typing import Sequence

import cv2
import numpy as np

from scripts.local_vlm_clip_shadow import RESULT_SCHEMA


MODEL = "gemma3:4b"
FRAME_FRACTIONS = tuple(0.05 + 0.90 * index / 11 for index in range(12))
PROMPT_VERSION = "production-local-vlm-clip-shadow-canary-v2"
NUM_CTX = 4096
NUM_PREDICT = 320
PROMPT = """You are observing 12 separate chronological frames from one gecko camera clip.
The attached images are ordered from frame 1 through 12. Compare positions within each image, not positions in a collage.
Use only facts visible in the images. Do not diagnose health, infer unseen eating or defecation, or tell the user what to do.
Return one JSON object matching the supplied schema. summary_ko must be one Korean sentence of at most 120 characters. If evidence is unclear, use uncertain and needs_human_review=true."""


def _fit_frame(frame: np.ndarray, maximum: int = 768) -> np.ndarray:
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("frame_shape")
    height, width = frame.shape[:2]
    scale = min(1.0, maximum / max(height, width))
    if scale == 1.0:
        return frame
    return cv2.resize(
        frame,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA,
    )


def encode_individual_frames(frames: Sequence[np.ndarray]) -> tuple[bytes, ...]:
    if len(frames) != 12:
        raise ValueError("frame_count")
    images: list[bytes] = []
    for frame in frames:
        fitted = _fit_frame(frame)
        ok, encoded = cv2.imencode(".jpg", fitted, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            raise ValueError("jpeg_encode")
        images.append(encoded.tobytes())
    return tuple(images)


def build_ollama_payload(images: Sequence[bytes]) -> dict[str, object]:
    if len(images) != 12:
        raise ValueError("image_count")
    return {
        "model": MODEL,
        "messages": [{
            "role": "user",
            "content": PROMPT,
            "images": [base64.b64encode(image).decode("ascii") for image in images],
        }],
        "stream": False,
        "think": False,
        "format": RESULT_SCHEMA,
        "keep_alive": "5m",
        "options": {
            "temperature": 0,
            "seed": 20260802,
            "num_ctx": NUM_CTX,
            "num_predict": NUM_PREDICT,
        },
    }
