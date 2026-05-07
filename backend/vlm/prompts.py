"""v3.5 prompt 로드 + species 매핑.

## SOT 원칙
v3.5 prompt 파일은 `web/prompts/backups/{system_base,crested_gecko}.v3.5.md` 가 단일
원천. 라벨링 웹 (`buildSystemPrompt` in `web/src/lib/prompts.ts`) 과 이 파이썬 워커가
**같은 파일을 read** 하도록 함. spec §4-4 — 옵션 A (직접 read).

## 종 매핑
PoC (`web/src/types.ts:119`) `DB_SPECIES_TO_CODE` 동치:
- `crested-gecko` → `crested_gecko`
- `leopard-gecko` → `leopard_gecko`
- `fat-tailed-gecko` → `aft`

DB 미등록 / `pet_id` NULL 인 클립은 라운드 1 기본 종 = `crested_gecko`.

## v3.5 prompt 락인
`feature-poc-vlm-web.md` Round 3 종료 락인. v3.5 templates 의 `{available_classes_block}`
/ `{species_name}` / `{species_specific_notes}` placeholder 만 채워서 system prompt 완성.

## 학습 메모
- TypeScript 의 `Record<Species, BehaviorClass[]>` ≈ Python 의 `dict[Species, list[str]]`.
- 9 raw 클래스 (`BEHAVIOR_CLASSES`) 와 종별 가용 클래스 (`SPECIES_CLASSES`) 가 다름 —
  leopard 는 paste 안 먹어서 `eating_paste` 제외. crested/gargoyle 만 9 클래스 풀.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# v3.5 락인 백업본 — `web/prompts/backups/`. 워커는 이 백업을 read (라벨링 웹은
# `web/prompts/system_base.md` 활성본을 read). v3.6+ 실험을 웹이 시도해도 워커는
# v3.5 백업 그대로 — production drift 차단.
PROMPTS_DIR = REPO_ROOT / "web" / "prompts" / "backups"

Species = Literal["crested_gecko", "gargoyle_gecko", "leopard_gecko", "aft"]
DEFAULT_SPECIES: Species = "crested_gecko"

# DB `species.id` (kebab) → 코드 union (snake). web/src/types.ts:119 미러.
DB_SPECIES_TO_CODE: dict[str, Species] = {
    "crested-gecko": "crested_gecko",
    "leopard-gecko": "leopard_gecko",
    "fat-tailed-gecko": "aft",
}

# 9 raw 클래스 (web/src/types.ts:4 BEHAVIOR_CLASSES 미러).
BEHAVIOR_CLASSES: list[str] = [
    "eating_paste",
    "eating_prey",
    "drinking",
    "defecating",
    "shedding",
    "basking",
    "hiding",
    "moving",
    "unseen",
]

# 종별 가용 클래스 (web/src/types.ts:35 SPECIES_CLASSES 미러).
# leopard / aft 는 paste 사료 안 먹음 → eating_paste 제외.
SPECIES_CLASSES: dict[Species, list[str]] = {
    "crested_gecko": list(BEHAVIOR_CLASSES),
    "gargoyle_gecko": list(BEHAVIOR_CLASSES),
    "leopard_gecko": [c for c in BEHAVIOR_CLASSES if c != "eating_paste"],
    "aft": [c for c in BEHAVIOR_CLASSES if c != "eating_paste"],
}


class PromptNotFound(RuntimeError):
    """v3.5 prompt 파일이 없음. web/ 디렉토리가 분리됐거나 삭제된 경우."""


def map_db_species_to_code(db_species_id: str | None) -> Species:
    """DB `species_id` (kebab-case) → 코드 Species (snake_case).

    NULL / 미매핑 종은 라운드 1 기본 (`crested_gecko`). web PoC 와 동치.
    """
    if not db_species_id:
        return DEFAULT_SPECIES
    return DB_SPECIES_TO_CODE.get(db_species_id, DEFAULT_SPECIES)


def build_system_prompt(species: Species) -> str:
    """v3.5 system prompt 완성본 반환.

    `web/src/lib/prompts.ts:9` 의 `buildSystemPrompt` 동치 포팅.

    Args:
        species: 종 코드 (snake_case).

    Returns:
        Gemini 에 첫 part 로 넘길 문자열.

    Raises:
        PromptNotFound: 백업 파일 누락.
    """
    base_path = PROMPTS_DIR / "system_base.v3.5.md"
    species_path = PROMPTS_DIR / f"{species}.v3.5.md"

    # crested_gecko 외엔 v3.5 백업이 아직 없을 수 있음 (라운드 1 only) — 그 경우
    # web/prompts/species/{species}.md 활성본으로 fallback. drift 위험 있지만 기능
    # 자체는 안 깨짐. 라운드 2~ 다른 종 락인 시 백업 추가 필요.
    if not species_path.is_file():
        species_path = REPO_ROOT / "web" / "prompts" / "species" / f"{species}.md"

    if not base_path.is_file():
        raise PromptNotFound(
            f"v3.5 system_base 파일 없음: {base_path}. web/ 디렉토리 확인."
        )
    if not species_path.is_file():
        raise PromptNotFound(
            f"{species} prompt 파일 없음: {species_path}. v3.5 백업 또는 활성본 확인."
        )

    base = base_path.read_text(encoding="utf-8")
    species_text = species_path.read_text(encoding="utf-8")

    classes_block = "\n".join(f"- {c}" for c in SPECIES_CLASSES[species])
    return (
        base.replace("{available_classes_block}", classes_block)
        .replace("{species_name}", species)
        .replace("{species_specific_notes}", species_text)
    )


__all__ = [
    "BEHAVIOR_CLASSES",
    "DB_SPECIES_TO_CODE",
    "DEFAULT_SPECIES",
    "PROMPTS_DIR",
    "PromptNotFound",
    "SPECIES_CLASSES",
    "Species",
    "build_system_prompt",
    "map_db_species_to_code",
]
