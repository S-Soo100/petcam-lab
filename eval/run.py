"""모델 추론 — 영상 클립 → action 분류 jsonl 출력.

사용:
  uv run python eval/run.py \
    --videos /path/to/videos \
    --prompt prompt/system_base.md \
    --species prompt/species/crested_gecko.md \
    --classes data/classes.json \
    --out my-results.jsonl \
    --model gemini

모델 어댑터 추가 (Anthropic/OpenAI):
  ModelAdapter ABC 상속 + infer(video_bytes, system_prompt) 구현 → ADAPTERS dict 등록.

자기충족: Supabase 의존 없음. 영상 디렉토리만 있으면 동작.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


# -----------------------------------------------------------------------------
# 데이터 모델
# -----------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class InferenceResult:
    """immutable 추론 결과 — 비용/타임 추적 위해 frozen."""
    clip_id: str
    ok: bool
    action: str | None = None
    confidence: float | None = None
    reasoning: str = ""
    elapsed_ms: int = 0
    model: str = ""
    error: str | None = None

    def to_jsonl(self) -> str:
        d = {"clip_id": self.clip_id, "ok": self.ok}
        if self.ok:
            d.update({
                "action": self.action,
                "confidence": self.confidence,
                "reasoning": self.reasoning,
                "elapsed_ms": self.elapsed_ms,
                "model": self.model,
            })
        else:
            d["error"] = self.error
        return json.dumps(d, ensure_ascii=False)


# -----------------------------------------------------------------------------
# Model Adapter ABC
# -----------------------------------------------------------------------------
class ModelAdapter(ABC):
    """Vision LLM 어댑터. 새 모델 추가 시 이 클래스 상속."""

    model_id: str = ""  # 결과 jsonl에 박힐 모델 식별자

    @abstractmethod
    def infer(self, clip_id: str, video_bytes: bytes, system_prompt: str) -> InferenceResult:
        """영상 1건 → 분류 결과. 실패해도 raise 말고 ok=False로 반환."""
        ...


class GeminiAdapter(ModelAdapter):
    """Gemini 2.5 Flash — v3.5 production baseline."""

    def __init__(self, model_name: str = "gemini-2.5-flash"):
        try:
            import google.generativeai as genai
        except ImportError:
            print("ERROR: google-generativeai 미설치 — `uv add google-generativeai`", file=sys.stderr)
            raise SystemExit(1)

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("ERROR: GEMINI_API_KEY 환경변수 없음", file=sys.stderr)
            raise SystemExit(1)

        genai.configure(api_key=api_key)
        self._genai = genai
        self.model_name = model_name
        self.model_id = f"{model_name}-zeroshot-portable"
        self._model = None  # lazy init (system_prompt 받은 후)

    def _ensure_model(self, system_prompt: str):
        if self._model is None:
            self._model = self._genai.GenerativeModel(
                self.model_name,
                system_instruction=system_prompt,
                generation_config={
                    "temperature": 0.1,
                    "top_p": 0.95,
                    "response_mime_type": "application/json",
                },
            )

    def infer(self, clip_id: str, video_bytes: bytes, system_prompt: str) -> InferenceResult:
        self._ensure_model(system_prompt)
        t0 = time.time()
        try:
            messages = [{
                "role": "user",
                "parts": [{"mime_type": "video/mp4", "data": video_bytes}],
            }]
            response = self._model.generate_content(messages)
            parsed = json.loads(response.text)
            elapsed_ms = int((time.time() - t0) * 1000)
            return InferenceResult(
                clip_id=clip_id,
                ok=True,
                action=parsed.get("action"),
                confidence=parsed.get("confidence"),
                reasoning=parsed.get("reasoning", ""),
                elapsed_ms=elapsed_ms,
                model=self.model_id,
            )
        except json.JSONDecodeError as e:
            return InferenceResult(clip_id=clip_id, ok=False, error=f"json: {str(e)[:120]}")
        except Exception as e:
            return InferenceResult(clip_id=clip_id, ok=False, error=str(e)[:200])


class AnthropicAdapter(ModelAdapter):
    """TODO: Anthropic Claude (Sonnet 4.6+) — vision 지원 모델 사용.

    구현 가이드:
      from anthropic import Anthropic
      client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
      response = client.messages.create(
          model="claude-sonnet-4-6",
          max_tokens=1024,
          system=system_prompt,
          messages=[{
              "role": "user",
              "content": [
                  {"type": "video", "source": {"type": "base64", "media_type": "video/mp4",
                                                "data": base64.b64encode(video_bytes).decode()}},
              ],
          }],
      )
      # response.content[0].text → JSON 파싱
    """
    model_id = "anthropic-claude-stub"

    def infer(self, clip_id: str, video_bytes: bytes, system_prompt: str) -> InferenceResult:
        return InferenceResult(clip_id=clip_id, ok=False, error="NOT_IMPLEMENTED: Anthropic adapter")


class OpenAIAdapter(ModelAdapter):
    """TODO: OpenAI GPT-4o vision — frame extraction 필요할 수 있음.

    구현 가이드:
      from openai import OpenAI
      client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
      # GPT-4o는 video 직접 입력 미지원 (2026-05 기준) — frame 추출 후 image 시퀀스로:
      # 1. cv2.VideoCapture로 영상에서 N frame 균등 추출
      # 2. base64 image로 변환
      # 3. messages에 image_url 시퀀스로 입력
    """
    model_id = "openai-gpt-stub"

    def infer(self, clip_id: str, video_bytes: bytes, system_prompt: str) -> InferenceResult:
        return InferenceResult(clip_id=clip_id, ok=False, error="NOT_IMPLEMENTED: OpenAI adapter")


ADAPTERS: dict[str, type[ModelAdapter]] = {
    "gemini": GeminiAdapter,
    "anthropic": AnthropicAdapter,
    "openai": OpenAIAdapter,
}


# -----------------------------------------------------------------------------
# Prompt 빌더
# -----------------------------------------------------------------------------
def build_system_prompt(prompt_path: Path, species_path: Path, classes_path: Path) -> str:
    """{available_classes_block}, {species_name}, {species_specific_notes} 치환."""
    base = prompt_path.read_text(encoding="utf-8")
    species = species_path.read_text(encoding="utf-8")
    classes_data = json.loads(classes_path.read_text(encoding="utf-8"))

    raw_classes = classes_data["raw_classes"]["values"]
    # v3.5는 hiding 폐기 (8개) — production lock과 일치하려면 hiding 제외
    eval_classes = [c for c in raw_classes if c != "hiding"]
    classes_block = "\n".join(f"- {c}" for c in eval_classes)

    species_name = species_path.stem  # e.g., "crested_gecko"
    return (
        base
        .replace("{available_classes_block}", classes_block)
        .replace("{species_name}", species_name)
        .replace("{species_specific_notes}", species)
    )


# -----------------------------------------------------------------------------
# 영상 디렉토리 탐색
# -----------------------------------------------------------------------------
def iter_videos(videos_dir: Path, target_clip_ids: set[str] | None = None) -> Iterator[tuple[str, Path]]:
    """videos_dir/{clip_id}.mp4 패턴.

    target_clip_ids 주면 해당 ID만 yield.
    """
    for path in sorted(videos_dir.glob("*.mp4")):
        clip_id = path.stem
        if target_clip_ids is None or clip_id in target_clip_ids:
            yield clip_id, path


def already_done(out_path: Path) -> set[str]:
    """기존 jsonl에서 ok=True 인 clip_id — 재실행 시 스킵."""
    if not out_path.exists():
        return set()
    done = set()
    for line in out_path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
            if r.get("ok"):
                done.add(r["clip_id"])
        except (json.JSONDecodeError, KeyError):
            continue
    return done


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    here = Path(__file__).resolve().parent.parent  # vlm-classifier-portable/
    p = argparse.ArgumentParser(description="VLM 행동 분류 추론 — 영상 → jsonl")
    p.add_argument("--videos", type=Path, required=True, help="영상 디렉토리 ({clip_id}.mp4 패턴)")
    p.add_argument("--prompt", type=Path, default=here / "prompt" / "system_base.md")
    p.add_argument("--species", type=Path, default=here / "prompt" / "species" / "crested_gecko.md")
    p.add_argument("--classes", type=Path, default=here / "data" / "classes.json")
    p.add_argument("--out", type=Path, required=True, help="출력 jsonl (append 모드 — 재실행 안전)")
    p.add_argument("--model", choices=list(ADAPTERS.keys()), default="gemini")
    p.add_argument("--limit", type=int, default=None, help="N건만 처리 (디버깅용)")
    p.add_argument("--target-clips", type=Path, default=None,
                   help="평가 대상 clip_id 리스트 jsonl (clip_id 필드 추출). 없으면 videos 전부.")
    return p.parse_args()


def load_target_clips(path: Path | None) -> set[str] | None:
    if path is None:
        return None
    target = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            target.add(r["clip_id"])
        except (json.JSONDecodeError, KeyError):
            continue
    return target


def main() -> None:
    args = parse_args()

    if not args.videos.is_dir():
        print(f"ERROR: videos 디렉토리 없음: {args.videos}", file=sys.stderr)
        raise SystemExit(1)

    system_prompt = build_system_prompt(args.prompt, args.species, args.classes)
    print(f"system prompt 길이: {len(system_prompt)} chars")

    adapter = ADAPTERS[args.model]()
    print(f"모델: {adapter.model_id}")

    target_clips = load_target_clips(args.target_clips)
    if target_clips is not None:
        print(f"평가 대상 clip_id: {len(target_clips)}")

    done = already_done(args.out)
    print(f"기존 완료: {len(done)}건")

    pending = [(cid, p) for cid, p in iter_videos(args.videos, target_clips) if cid not in done]
    if args.limit:
        pending = pending[:args.limit]
    print(f"이번 실행 대상: {len(pending)}건\n")

    if not pending:
        print("처리할 클립 없음. 종료.")
        return

    args.out.parent.mkdir(parents=True, exist_ok=True)

    ok, fail = 0, 0
    t0 = time.time()

    with args.out.open("a", encoding="utf-8") as f:
        for i, (cid, path) in enumerate(pending, 1):
            video_bytes = path.read_bytes()
            result = adapter.infer(cid, video_bytes, system_prompt)
            f.write(result.to_jsonl() + "\n")
            f.flush()

            if result.ok:
                ok += 1
                print(f"[{i}/{len(pending)}] {cid[:8]} → {result.action:14s} "
                      f"conf={result.confidence or 0:.2f} ({result.elapsed_ms}ms)", flush=True)
            else:
                fail += 1
                print(f"[{i}/{len(pending)}] {cid[:8]} FAIL: {result.error[:80]}", flush=True)

    elapsed = time.time() - t0
    print(f"\n=== 완료 === OK {ok} / FAIL {fail} ({elapsed:.0f}s)")
    print(f"결과: {args.out}")


if __name__ == "__main__":
    main()
